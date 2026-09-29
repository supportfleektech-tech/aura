"""Push router — VAPID web push."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

push_r = APIRouter(prefix="/push", tags=["push"])


@push_r.get("/vapid-public-key")
def vapid_key():
    from .. import push as pushmod
    return {"key": pushmod.vapid_public_key() or None, "configured": pushmod.configured()}


@push_r.post("/subscribe")
def push_subscribe(body: dict):
    from .. import push as pushmod
    try:
        keys = body.get("keys", {}) or {}
        return pushmod.subscribe(body.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@push_r.post("/unsubscribe")
def push_unsubscribe(body: dict):
    from .. import push as pushmod
    return pushmod.unsubscribe(body.get("endpoint", ""))


@push_r.post("/test")
def push_test(body: dict):
    from .. import push as pushmod
    return pushmod.send_push(body.get("title", "AURA test push") or "AURA test push",
                            body.get("body", "Push is wired up.") or "", body.get("url", "/") or "/")
