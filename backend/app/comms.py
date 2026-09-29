"""Comms — outbound messaging dispatcher with duplicate suppression.

Wraps `providers.send` and adds an idempotency guard so an approval replay, a
retried automation, or a double-click cannot deliver the same message twice.
The guard is a short-lived in-process ring of recent content fingerprints; it
is intentionally not persisted, because suppressing a *deliberate* resend of
the same text hours later would be wrong.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

from . import db

__all__ = ["send", "DEDUP_WINDOW_S", "DEDUP_MAX"]

DEDUP_WINDOW_S = 300.0
DEDUP_MAX = 512

_lock = threading.Lock()
_recent: "OrderedDict[str, float]" = OrderedDict()


def _fingerprint(platform: str, to: str, subject: str, text: str) -> str:
    raw = "\x1f".join((platform or "", to or "", subject or "", text or ""))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _prune(now: float) -> None:
    while _recent:
        oldest_key, oldest_ts = next(iter(_recent.items()))
        if now - oldest_ts <= DEDUP_WINDOW_S and len(_recent) < DEDUP_MAX:
            break
        _recent.pop(oldest_key, None)


def _is_duplicate(fp: str) -> bool:
    now = time.time()
    with _lock:
        _prune(now)
        prev = _recent.get(fp)
        if prev is not None and now - prev <= DEDUP_WINDOW_S:
            return True
        _recent[fp] = now
        _recent.move_to_end(fp)
        return False


def reset_dedup() -> None:
    """Clear the duplicate-suppression window (used by tests and manual re-sends)."""
    with _lock:
        _recent.clear()


def send(platform: str, to: str, subject: str, text: str, *,
         idempotency_key: str | None = None, force: bool = False) -> dict:
    """Send via the gateway. Returns the provider result, plus `duplicate` when suppressed.

    `idempotency_key` overrides the content fingerprint, letting a caller mark a
    retry as the *same* logical send. `force=True` bypasses suppression entirely.
    """
    fp = idempotency_key or _fingerprint(platform, to, subject, text)
    if db.DRY_RUN:
        # Preview first: a dry run must always report what it would do, and must
        # never consume the fingerprint — otherwise a preview would suppress the
        # real send that follows it.
        db.blocked("push: notifications not sent")
        return {"sent": False, "dry_run": True, "platform": platform,
                "would": f"{platform}:{to or '-'} {subject or (text or '')[:60]}".strip()}
    if not force and _is_duplicate(fp):
        db.log_activity(
            "message", f"Duplicate send suppressed: {platform}",
            f"to={to or '-'} subject={subject or '-'}",
            "general", "warning",
        )
        return {"sent": False, "duplicate": True, "platform": platform,
                "note": "identical message was already sent — suppressed as a duplicate"}
    # Import inside the call so the provider layer stays the single source of
    # truth and remains patchable in tests.
    from . import providers
    return providers.send(platform, to, subject, text)
