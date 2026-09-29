"""Proactive router — scan, dismiss, snooze, act."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

pro_r = APIRouter(prefix="/proactive", tags=["proactive"])


@pro_r.get("")
def list_proactive(include_dismissed: bool = False, limit: int = 20):
    from .. import proactive as _p
    items = _p.scan()
    if include_dismissed:
        items = [{**{"key": r["key"], "type": r["type"], "title": r["title"],
                       "detail": r["detail"], "score": r["score"],
                       "dismissed": bool(r["dismissed"])}} for r in _p.list_all(True)]
    return {"opportunities": items[:max(1, min(50, limit))]}


@pro_r.post("/scan")
def scan_proactive():
    from .. import proactive as _p
    items = _p.scan()
    top = _p.notify_top(items)
    return {"opportunities": items, "notified": top["key"] if top else None}


@pro_r.patch("/{key}/dismiss")
def dismiss_proactive(key: str, b: dict | None = None):
    from .. import proactive as _p
    try:
        return _p.set_dismissed(key, (b or {}).get("dismissed", True))
    except KeyError:
        raise HTTPException(404, "opportunity not found")


@pro_r.post("/{key}/snooze")
def snooze_proactive(key: str, b: dict | None = None):
    from .. import proactive as _p
    try:
        return _p.snooze(key, (b or {}).get("hours", 24))
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    except (TypeError, ValueError):
        raise HTTPException(400, "hours must be a number")


@pro_r.post("/{key}/act")
def act_proactive(key: str):
    from .. import proactive as _p
    try:
        res = _p.act(key)
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    if not res.get("ok") and not res.get("gone"):
        raise HTTPException(400, res.get("message", "action failed"))
    return res


@pro_r.get("/resolved")
def resolved_proactive(limit: int = 20):
    from .. import proactive as _p
    return {"resolved": _p.resolved_history(limit)}
