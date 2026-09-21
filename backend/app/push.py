"""Web Push (PWA) — VAPID-signed notifications via pywebpush.

Setup: run `python3 scripts/gen_vapid.py`, put the keys in
AURA_VAPID_PUBLIC_KEY / AURA_VAPID_PRIVATE_KEY. Without keys the module
is inert (subscribe still stores endpoints; sends are skipped).
"""
from __future__ import annotations

import json

from . import config, prefs, db


def vapid_public_key() -> str:
    return getattr(config, "VAPID_PUBLIC_KEY", "")


def configured() -> bool:
    return bool(getattr(config, "VAPID_PUBLIC_KEY", "") and getattr(config, "VAPID_PRIVATE_KEY", ""))


def subscribe(endpoint: str, p256dh: str, auth: str) -> dict:
    if not endpoint.startswith("https://"):
        raise ValueError("push endpoint must be https://")
    if not p256dh or not auth:
        raise ValueError("push subscription needs p256dh + auth keys")
    db.run("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (1,?,?,?) "
           "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth",
           (endpoint, p256dh, auth))
    n = (db.qone("SELECT COUNT(*) c FROM push_subscriptions WHERE user_id=1") or {}).get("c", 0)
    return {"ok": True, "subscriptions": n}


def unsubscribe(endpoint: str) -> dict:
    db.run("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
    return {"ok": True}


def send_push(title: str, body: str = "", url: str = "/") -> dict:
    """Fan out to all subscriptions. Returns {sent, dropped, skipped}."""
    if db.DRY_RUN:
        db.blocked("push: notifications not sent")
        return {"sent": 0, "dropped": 0, "skipped": 0, "dry_run": True}
    subs = db.q("SELECT * FROM push_subscriptions WHERE user_id=1")
    if not subs:
        return {"sent": 0, "dropped": 0, "skipped": 0}
    if not configured():
        return {"sent": 0, "dropped": 0, "skipped": len(subs)}
    if prefs.in_quiet_hours():
        db.log_activity("system", "Push suppressed (quiet hours)", title[:120], "general")
        return {"sent": 0, "dropped": 0, "skipped": len(subs), "quiet": True}
    from pywebpush import WebPushException, webpush
    sent, dropped = 0, 0
    payload = json.dumps({"title": title, "body": body[:200], "url": url})
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s["endpoint"],
                                   "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=payload,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": getattr(config, "VAPID_SUBJECT", "mailto:aura@localhost")},
            )
            sent += 1
        except Exception as e:
            if isinstance(e, WebPushException) and getattr(e, "response", None) is not None \
                    and e.response.status_code in (404, 410):
                db.run("DELETE FROM push_subscriptions WHERE id=?", (s["id"],))
                dropped += 1
            else:
                db.log_activity("system", "Push send failed", str(e)[:150], "general", "warn")
    return {"sent": sent, "dropped": dropped, "skipped": 0}
