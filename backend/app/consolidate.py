"""Memory consolidation (spec §1, FR-MEM-003).

Three passes: dedupe, importance re-scoring, and archival of low-signal rows.
Every write is a soft delete (`deleted_at`) or a `supersedes_id` pointer —
AURA has no login, so there is no way to prove a hard delete was intended.

Importance re-scoring uses only signals that already exist as columns: a
re-confirmed memory (`last_confirmed`) and a user-corrected memory
(`source LIKE 'user-corrected:%'`). There is deliberately no access counter;
adding one would be a schema change to buy a heuristic. Both signals are gated
on a `consolidate_last_run` watermark, because both columns are written by
ordinary use (the dedupe pass, `memory.store`, `memory.update`) — scored on
bare presence they would re-apply forever and pin importance at 1.0. Signal
timestamps and the watermark are compared on the same whole-second grid; see
`_epoch`.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import db, prefs
from .memory import _tokens

# Same threshold, and the same strict comparison, MemoryEngine._duplicate_of
# uses (memory.py:133), so a consolidation pass and a store-time dedupe agree on
# what "the same memory" means. The operator matters: a pair sitting exactly on
# the threshold is one the store deliberately kept apart, so consolidation must
# not merge it back together.
DUP_THRESHOLD = 0.55
ARCHIVE_IMPORTANCE = 0.2
ARCHIVE_CONFIDENCE = 0.4
ARCHIVE_MIN_AGE_DAYS = 30


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_duplicate_groups(threshold: float = DUP_THRESHOLD, limit: int = 500) -> list[list[int]]:
    """Cluster live memories by pairwise Jaccard > threshold. Returns id groups."""
    rows = db.q("SELECT id, content FROM memories WHERE user_id=1 AND deleted_at IS NULL "
                "ORDER BY id DESC LIMIT ?", (max(1, min(limit, 2000)),))
    groups: list[list[int]] = []
    claimed: set[int] = set()
    for i, r in enumerate(rows):
        if r["id"] in claimed:
            continue
        cluster = [r["id"]]
        for other in rows[i + 1:]:
            if other["id"] in claimed:
                continue
            if _jaccard(r.get("content") or "", other.get("content") or "") > threshold:
                cluster.append(other["id"])
                claimed.add(other["id"])
        if len(cluster) > 1:
            claimed.add(r["id"])
            groups.append(cluster)
    return groups


def _epoch(stamp: str | None) -> int:
    """Whole epoch seconds for a stamp as SQLite writes them (`%Y-%m-%dT%H:%M:%S.%fZ`).

    Floored to whole seconds on purpose: the watermark it is compared against is
    written as `int(time.time())`, so the two sides must live on the same
    one-second grid. A fractional parse is not merely lower-precision, it is
    *wrong* here — `int()` is monotone, so `floor(stamp) <= int(pass_end)` holds
    for anything written during a pass, and a fractional parse breaks that: a
    stamp at `…02.619` reads newer than a watermark of `…02` and the signal is
    re-counted on the next pass. Flooring makes the pass's own writes
    unconditionally non-fresh, which is what closes the merge path (the dedupe
    pass stamps `last_confirmed` on the winner, then the same call's re-scoring
    pass reads it).

    0 for NULL or unparseable: an unreadable stamp must not read as "just
    confirmed", which is the trap the pre-watermark pass fell into.
    """
    if not stamp:
        return 0
    try:
        return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def _watermark() -> float:
    """`consolidate_last_run` in epoch seconds.

    0 on a fresh install, which reads as 1970: the first pass counts every real
    signal instead of silently no-opping on an unwritten watermark.
    """
    try:
        return float(prefs.get("consolidate_last_run") or 0)
    except (TypeError, ValueError):
        return 0.0


def run_pass(limit: int = 500) -> dict:
    """One consolidation pass: dedupe, then importance re-scoring, then archival.

    Three passes run. Exactly one of them — importance re-scoring — is idempotent,
    and that is the only one that claims to be.

    **Importance re-scoring is idempotent, and this is the property the pass
    exists to protect.** It scores a signal only if the signal's timestamp is on
    the far side of the `consolidate_last_run` watermark, both compared on
    whole-second resolution. Consequences, stated as guarantees:

    - A pass with no confirmation or correction newer than the watermark leaves
      every importance untouched — including the merge winner, whose
      `last_confirmed` this very call stamps. Running back-to-back passes, with
      no waiting and no clock help, cannot walk anything toward the 1.0 cap.
    - A genuinely new signal is counted exactly once, then never again, because
      the watermark written at the end of the pass is at least as new as anything
      written during it.

    The one thing the watermark cannot do is count a signal that arrives within
    the same wall-clock second as the previous pass's completion: it reads as
    part of the interval already scored. That is at most a sub-second window per
    pass and costs a `+0.03` heuristic bump, not the memory — the signal itself
    is a column value that nothing clears.

    The dedupe and archive passes stay stateful by design — merging and retiring
    rows is the point — but neither can resurrect a signal the watermark already
    consumed, and neither is claimed to be idempotent.
    """
    t0 = time.time()
    watermark = _watermark()
    merged = archived = rescored = 0

    for group in find_duplicate_groups(limit=limit):
        rows = db.q("SELECT * FROM memories WHERE id IN (%s) AND deleted_at IS NULL"
                    % ",".join("?" * len(group)), tuple(group))
        if len(rows) < 2:
            continue
        winner = sorted(rows, key=lambda r: (-float(r.get("importance") or 0), r["id"]))[0]
        losers = [r for r in rows if r["id"] != winner["id"]]
        new_imp = min(1.0, float(winner.get("importance") or 0) + 0.05 * len(losers))
        db.run("UPDATE memories SET importance=?, "
               "last_confirmed=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
               (round(new_imp, 3), winner["id"]))
        for l in losers:
            db.run("UPDATE memories SET supersedes_id=?, "
                   "deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                   (winner["id"], l["id"]))
            merged += 1

    for r in db.q("SELECT id, importance, last_confirmed, updated_at, source FROM memories "
                  "WHERE user_id=1 AND deleted_at IS NULL"):
        # `source` is written together with `updated_at` by memory.update, so
        # updated_at is the correction's timestamp. Note this pass never
        # touches updated_at itself — it would refresh the signal it just scored.
        confirmed = _epoch(r.get("last_confirmed")) > watermark
        corrected = ((r.get("source") or "").startswith("user-corrected:")
                     and _epoch(r.get("updated_at")) > watermark)
        bump = (0.03 if confirmed else 0.0) + (0.02 if corrected else 0.0)
        if bump <= 0:
            continue
        db.run("UPDATE memories SET importance=? WHERE id=?",
               (round(min(1.0, float(r.get("importance") or 0) + bump), 3), r["id"]))
        rescored += 1

    # This query sees rows the two passes above have already mutated, and that is
    # deliberate. Re-scoring runs first, so a row that just earned importance can
    # no longer qualify; and a merge winner was stamped `last_confirmed`, which
    # this query excludes. A row can therefore be *promoted out* of the archive
    # set by its own pass and will be picked up, if ever, by a later one. Losing
    # a candidate is the conservative direction — a row that survives this pass
    # is re-examined next pass, whereas archiving one that was promoted is not
    # reversible. Do not reorder these passes to "fix" it.
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - ARCHIVE_MIN_AGE_DAYS * 86400))
    victims = db.q(
        "SELECT id FROM memories WHERE user_id=1 AND deleted_at IS NULL "
        "AND importance <= ? AND confidence <= ? AND last_confirmed IS NULL "
        "AND sensitivity = 'normal' AND created_at < ?",
        (ARCHIVE_IMPORTANCE, ARCHIVE_CONFIDENCE, cutoff))
    for v in victims:
        db.run("UPDATE memories SET deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
               "WHERE id=?", (v["id"],))
        archived += 1

    prefs.set_many({"consolidate_last_run": int(time.time())})

    scanned = (db.qone("SELECT COUNT(*) c FROM memories WHERE user_id=1 "
                       "AND deleted_at IS NULL") or {}).get("c", 0)
    out = {"scanned": int(scanned), "merged": merged, "archived": archived,
           "rescored": rescored, "duration_ms": int((time.time() - t0) * 1000)}
    db.log_activity("memory",
                    f"Consolidation pass: {merged} merged, {archived} archived",
                    f"{rescored} re-scored in {out['duration_ms']}ms", "general")
    return out


def should_run(now_ts: float | None = None) -> bool:
    """True at most once per 24h, and only when the pref is on."""
    try:
        if not prefs.get("consolidate_enabled"):
            return False
    except Exception:
        return False
    now = now_ts if now_ts is not None else time.time()
    try:
        last = float(prefs.get("consolidate_last_run") or 0)
    except (TypeError, ValueError):
        last = 0.0
    return (now - last) >= 86400
