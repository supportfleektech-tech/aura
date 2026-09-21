"""Idempotency helper — dedupe external side effects on retry (§39).

The webhook automation has exponential-backoff retry (5m→2h); a retried POST
can double-fire a receiver that already processed the original. Two layers:

1. Stable fire id: `fire_webhook` gets a `_fire_id` (uuid) that survives
   retries and is sent as `X-Aura-Idempotency-Key` — the *receiver* dedupes.
2. Client-side dedupe: `claim()` records a fingerprint before an external
   send and returns False if the same fingerprint was already claimed inside
   the TTL window — AURA itself skips the duplicate send.
"""
from __future__ import annotations

import hashlib
import time

from . import db

DEFAULT_TTL_S = 3600


def fingerprint(*parts: str) -> str:
    """Stable short fingerprint for a logical send."""
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode())
    return h.hexdigest()[:32]


def claim(kind: str, fp: str, ttl_s: int = DEFAULT_TTL_S) -> bool:
    """True if this (kind, fingerprint) is newly claimed; False if duplicate."""
    now = time.time()
    expire = int(now + max(1, ttl_s))
    row = db.qone("SELECT fingerprint FROM send_dedupe WHERE kind=? AND fingerprint=?", (kind, fp))
    if row:
        return False
    db.run("INSERT OR IGNORE INTO send_dedupe (kind, fingerprint, expires_at) VALUES (?,?,?)",
           (kind, fp, expire))
    return True


def release(kind: str, fp: str) -> None:
    """Drop a claim so a later legitimate send is not blocked."""
    db.run("DELETE FROM send_dedupe WHERE kind=? AND fingerprint=?", (kind, fp))


def prune() -> int:
    """Delete expired claims. Called from the scheduler loop. Returns removed count."""
    db.run("DELETE FROM send_dedupe WHERE expires_at < ?", (int(time.time()),))
    return 0
