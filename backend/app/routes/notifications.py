"""Notifications router."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db

notes_r = APIRouter(prefix="/notifications", tags=["notifications"])


@notes_r.get("")
def list_notes():
    return {"notifications": db.q("SELECT * FROM notifications WHERE user_id=1 ORDER BY id DESC LIMIT 50"),
            "unread": (db.qone("SELECT COUNT(*) c FROM notifications WHERE user_id=1 AND read=0") or {}).get("c", 0)}


@notes_r.post("/{nid}/read")
def read_note(nid: int):
    db.run("UPDATE notifications SET read=1 WHERE id=?", (nid,))
    return {"ok": True}


@notes_r.post("/read-all")
def read_all():
    db.run("UPDATE notifications SET read=1 WHERE user_id=1")
    return {"ok": True}
