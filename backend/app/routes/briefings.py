"""Briefings router — list, create, run."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

brief_r = APIRouter(prefix="/briefings", tags=["briefings"])


@brief_r.get("")
def list_briefs():
    from .. import briefing as _b
    return {"briefings": _b.list_briefings()}


@brief_r.post("")
def create_brief(b: dict):
    from .. import briefing as _b
    try:
        return _b.create_briefing(b.get("name", ""), b.get("kind", "morning"), b.get("prompt", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.patch("/{bid}")
def update_brief(bid: int, patch: dict):
    from .. import briefing as _b
    try:
        return _b.update_briefing(bid, patch)
    except KeyError:
        raise HTTPException(404, "briefing not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.delete("/{bid}")
def delete_brief(bid: int):
    from .. import briefing as _b
    _b.delete_briefing(bid)
    return {"ok": True}


@brief_r.post("/{bid}/run")
def run_brief(bid: int, b: dict | None = None):
    from .. import briefing as _b
    try:
        return _b.run_briefing(bid, extra=(b or {}).get("extra", ""))
    except KeyError:
        raise HTTPException(404, "briefing not found")


@brief_r.post("/run-now")
def run_brief_now(b: dict | None = None):
    from .. import briefing as _b
    try:
        return _b.run_briefing(None, ((b or {}).get("kind") or "morning"), (b or {}).get("extra", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.get("/runs/list")
def list_brief_runs(briefing_id: int | None = None, limit: int = 20):
    from .. import briefing as _b
    return {"runs": _b.list_runs(briefing_id, limit)}
