"""Worker pool and persistent job queue (spec §5, FR-WRK-001..005).

Concurrency here is a *thread* pool, not asyncio, and that is deliberate. The DB
layer is one pooled SQLite connection behind an RLock, so N threads writing
concurrently serialise on that lock regardless; what genuinely parallelises is
tool execution (web.fetch, feeds.latest, comms.send), which releases the lock
while it waits on the network. Converting this to asyncio later would risk
deadlocking on the RLock for no throughput gain.

The queue is persistent (`worker_jobs`), so `requeue_stale` returns
interrupted `running` jobs to `queued` on startup rather than losing them —
FR-WRK-005's "zero message loss".

Do NOT enqueue `mission_tick` / `schedule_tick` into this queue. `scheduler_pass`
already ticks missions and schedules inline, before it drains; a queued tick
would race that call and fire the same mission step twice.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import db, prefs

KIND_MISSION_TICK = "mission_tick"
KIND_SCHEDULE_TICK = "schedule_tick"
KIND_CONSOLIDATION = "consolidation"
# The vocabulary `_run` dispatches on. Declared here so the E2E check can assert
# against the same list rather than hardcoding a second copy.
KNOWN_KINDS = (KIND_MISSION_TICK, KIND_SCHEDULE_TICK, KIND_CONSOLIDATION)

MAX_BACKOFF_S = 300
BACKOFF_BASE_S = 5
# Same second-resolution stamp hermes and prefs use; second precision because
# `available_at` is compared as a string against `_now()` in the claim filter.
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return time.strftime(TIME_FMT, time.gmtime())


def _iso(ts: float) -> str:
    return time.strftime(TIME_FMT, time.gmtime(ts))


def pool_size() -> int:
    return max(1, min(int(prefs.get("worker_pool_size") or 3), 8))


def enqueue(kind: str, payload: dict, priority: int = 5, max_retries: int | None = None) -> int:
    if max_retries is None:
        # `or 0`, NOT `or 3`: 0 is a legal setting ("never retry"), and `or 3`
        # would silently discard it. An unset pref never reaches here — prefs.get
        # falls back to the SCHEMA default of 3.
        max_retries = int(prefs.get("worker_max_retries") or 0)
    return db.run(
        "INSERT INTO worker_jobs (user_id, kind, payload_json, priority, max_retries, available_at) "
        "VALUES (1,?,?,?,?,?)",
        (kind, db.jdump(payload or {}), int(priority), int(max_retries), ""))


def claim(n: int = 1) -> list[dict]:
    """Move up to n claimable jobs to `running` and return them.

    Claimable = status 'queued' AND (available_at empty OR <= now).

    This is ONE `UPDATE .. RETURNING` rather than SELECT / UPDATE / re-SELECT.
    The three-statement form double-claims: two threads that both SELECT the
    same id, then both UPDATE (the second UPDATE's `status='queued'` guard makes
    it a no-op, not a failure), then both re-read the row and both run the job.
    Realised in a probe by widening the select->update gap to 20ms: 4 concurrent
    claimers, 4 winners. `RETURNING` evaluates the sub-select and the update
    under one write transaction, so the row can only go to one claimer.

    `RETURNING` gives post-increment `attempts` and no row order guarantee, so
    the priority order is re-imposed here.
    """
    rows = db.run_returning(
        "UPDATE worker_jobs SET status='running', attempts=attempts+1, updated_at=? "
        "WHERE id IN (SELECT id FROM worker_jobs WHERE user_id=1 AND status='queued' "
        "AND (available_at='' OR available_at <= ?) ORDER BY priority ASC, id ASC LIMIT ?) "
        "RETURNING *", (_now(), _now(), max(1, int(n))))
    return sorted(rows, key=lambda r: (int(r["priority"]), int(r["id"])))


def complete(job_id: int, result: Any = None) -> None:
    db.run("UPDATE worker_jobs SET status='done', result_json=?, last_error='', updated_at=? "
           "WHERE id=?", (db.jdump(result if result is not None else {}), _now(), job_id))


def fail(job_id: int, err: str) -> str:
    """Settle a failure. Returns 'retry' or 'dead'.

    `claim` already incremented `attempts`, so `attempts` is the number of
    *executions*, not the number of failures. With max_retries=3 the job
    therefore runs at most 4 times: attempts 1,2,3 retry and the 4th
    (attempts > cap) dead-letters. That is "3 retries then dead-letter"
    (FR-WRK-003), not "4 retries".
    """
    row = db.qone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    if not row:
        return "dead"
    attempts, cap = int(row.get("attempts") or 0), int(row.get("max_retries") or 0)
    if attempts > cap:
        db.run("UPDATE worker_jobs SET status='dead', last_error=?, updated_at=? WHERE id=?",
               (str(err)[:300], _now(), job_id))
        db.notify("Job dead-lettered", f"{row['kind']} — {str(err)[:140]}", "error")
        return "dead"
    delay = min(MAX_BACKOFF_S, (2 ** max(1, attempts)) * BACKOFF_BASE_S)
    db.run("UPDATE worker_jobs SET status='queued', last_error=?, available_at=?, updated_at=? "
           "WHERE id=?", (str(err)[:300], _iso(time.time() + delay), _now(), job_id))
    return "retry"


def _run(job: dict) -> Any:
    kind = job["kind"]
    if kind == KIND_MISSION_TICK:
        from . import missions as _m
        return _m.tick_missions()
    if kind == KIND_SCHEDULE_TICK:
        from . import missions as _m
        return _m.tick_schedules()
    if kind == KIND_CONSOLIDATION:
        from . import consolidate as _c
        return _c.run_pass()
    raise ValueError(f"unknown job kind: {kind}")


def drain(limit: int = 20) -> dict:
    """Claim a batch, run it on the pool, settle each outcome.

    `limit` caps how many jobs one call claims; the claim is further clamped to
    `pool_size * 4` so a manual drain cannot pull an unbounded backlog into
    memory while only having N workers to run it. `limit=0` (or negative) means
    "one pool's worth" rather than "nothing".
    """
    out = {"ran": 0, "done": 0, "retried": 0, "dead": 0}
    want = max(1, int(limit)) if limit else pool_size()
    jobs = claim(min(want, pool_size() * 4))
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=pool_size()) as ex:
        futures = {ex.submit(_run, j): j for j in jobs}
        for fut, job in futures.items():
            out["ran"] += 1
            try:
                complete(job["id"], fut.result())
                out["done"] += 1
            except Exception as e:  # noqa: BLE001 — one bad job must not stop the drain
                if fail(job["id"], str(e)) == "retry":
                    out["retried"] += 1
                else:
                    out["dead"] += 1
    return out


def requeue_stale() -> int:
    """Startup only: return `running` jobs to `queued`. They were interrupted.

    Unconditional by design — there is no "stale" age to compare against
    because the process that owned them is gone. Calling this while the pool is
    live would re-queue jobs that are still executing, so `start_scheduler_loop`
    calls it once, before the loop thread starts, and nothing else does.
    """
    n = (db.qone("SELECT COUNT(*) c FROM worker_jobs WHERE user_id=1 "
                 "AND status='running'") or {}).get("c", 0)
    db.run("UPDATE worker_jobs SET status='queued', updated_at=? "
           "WHERE user_id=1 AND status='running'", (_now(),))
    return int(n)


def stats() -> dict:
    by = {r["status"]: r["c"] for r in db.q(
        "SELECT status, COUNT(*) c FROM worker_jobs WHERE user_id=1 GROUP BY status")}
    kinds = {r["kind"]: r["c"] for r in db.q(
        "SELECT kind, COUNT(*) c FROM worker_jobs WHERE user_id=1 GROUP BY kind")}
    done, dead = by.get("done", 0), by.get("dead", 0)
    settled = done + dead
    # Settled only: a job that was merely enqueued or re-queued is not throughput.
    recent = (db.qone("SELECT COUNT(*) c FROM worker_jobs WHERE user_id=1 "
                      "AND status IN ('done','dead') AND updated_at >= ?",
                      (_iso(time.time() - 60),)) or {}).get("c", 0)
    return {"queued": by.get("queued", 0), "running": by.get("running", 0),
            "done": done, "dead": dead, "throughput_per_min": int(recent),
            "error_rate": round(dead / settled, 3) if settled else 0.0,
            "by_kind": kinds}


def dead_letters(limit: int = 50) -> list[dict]:
    return db.q("SELECT id, kind, attempts, max_retries, last_error, updated_at "
                "FROM worker_jobs WHERE user_id=1 AND status='dead' ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),))


def scheduler_pass() -> dict:
    """One 30-second scheduler pass. The loop body calls this and nothing else.

    Named so it is callable from a test: the real loop sleeps 30s between
    passes, so a test cannot exercise the loop itself, only this function.
    """
    from . import hermes as _h
    from . import missions as _m
    out: dict[str, Any] = {"automations": _h.hermes.tick_automations(),
                           "schedules": _m.tick_schedules(),
                           "missions": _m.tick_missions()}
    try:
        from . import consolidate as _c
        if _c.should_run():
            # run_pass owns the `consolidate_last_run` watermark it sets on
            # completion; writing it again here would be a second writer.
            out["consolidation"] = _c.run_pass()
    except Exception as e:  # noqa: BLE001 — consolidation must not stall the loop
        out["consolidation_error"] = str(e)[:120]
    try:
        out["jobs"] = drain()
    except Exception as e:  # noqa: BLE001
        out["jobs_error"] = str(e)[:120]
    return out