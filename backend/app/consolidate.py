"""Memory consolidation (spec §1, FR-MEM-003).

Three passes: dedupe, importance re-scoring, and archival of low-signal rows.
Every write is a soft delete (`deleted_at`) or a `supersedes_id` pointer —
AURA has no login, so there is no way to prove a hard delete was intended.

Importance re-scoring uses only signals that already exist as columns: a
re-confirmed memory (`last_confirmed`) and a user-corrected memory
(`source LIKE 'user-corrected:%'`). There is deliberately no access counter;
adding one would be a schema change to buy a heuristic.
"""
from __future__ import annotations

import time

from . import db, prefs
from .memory import _tokens

# Same threshold MemoryEngine._duplicate_of uses, so a consolidation pass and a
# store-time dedupe agree on what "the same memory" means.
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
    """Cluster live memories by pairwise Jaccard >= threshold. Returns id groups."""
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
            if _jaccard(r.get("content") or "", other.get("content") or "") >= threshold:
                cluster.append(other["id"])
                claimed.add(other["id"])
        if len(cluster) > 1:
            claimed.add(r["id"])
            groups.append(cluster)
    return groups


def run_pass(limit: int = 500) -> dict:
    """One consolidation pass. Idempotent: every statement is scoped by id."""
    t0 = time.time()
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

    for r in db.q("SELECT id, importance, last_confirmed, source FROM memories "
                  "WHERE user_id=1 AND deleted_at IS NULL"):
        bump = ((0.03 if r.get("last_confirmed") else 0.0)
                + (0.02 if (r.get("source") or "").startswith("user-corrected:") else 0.0))
        if bump <= 0:
            continue
        db.run("UPDATE memories SET importance=? WHERE id=?",
               (round(min(1.0, float(r.get("importance") or 0) + bump), 3), r["id"]))
        rescored += 1

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
