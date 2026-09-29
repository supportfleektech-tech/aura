"""Undo router — preview + apply."""
from __future__ import annotations

from fastapi import APIRouter

undo_r = APIRouter(prefix="/undo", tags=["undo"])


@undo_r.get("")
def undo_preview():
    from .. import db
    from .. import undo as _u
    recent = _u.tail()
    # `remaining` from the apply endpoint is the true total; the preview must not
    # silently disagree with it just because `tail()` is capped.
    total = (db.qone("SELECT COUNT(*) n FROM write_journal") or {"n": len(recent)})["n"]
    return {"journal": recent, "undoable": bool(recent), "remaining": total}


@undo_r.post("")
def undo_apply(b: dict | None = None):
    from .. import undo as _u
    return _u.undo_last(int((b or {}).get("steps", 1) or 1))
