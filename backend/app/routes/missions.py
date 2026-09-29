"""Missions router — multi-step goal execution."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

missions_r = APIRouter(prefix="/missions", tags=["missions"])


@missions_r.get("")
def list_missions():
    from .. import missions as _m
    return {"missions": _m.list_missions()}


@missions_r.post("")
def create_mission(body: dict):
    from .. import missions as _m
    if not (body.get("goal") or "").strip():
        raise HTTPException(400, "goal is empty")
    try:
        return _m.create_mission(body["goal"], body.get("planner", "auto") or "auto")
    except ValueError as e:
        raise HTTPException(400, str(e))


@missions_r.get("/{mid}")
def get_mission(mid: int):
    from .. import missions as _m
    m = _m._row(mid)
    if not m:
        raise HTTPException(404, "not found")
    return m


@missions_r.patch("/{mid}")
def patch_mission(mid: int, body: dict):
    from .. import missions as _m
    if not isinstance(body.get("steps"), list):
        raise HTTPException(400, "steps must be a list")
    try:
        return _m.update_steps(mid, body["steps"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@missions_r.post("/{mid}/schedule")
def schedule_mission(mid: int, body: dict):
    from .. import missions as _m
    try:
        m = _m.set_schedule(mid, body.get("every", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not m:
        raise HTTPException(404, "not found")
    return m


@missions_r.get("/{mid}/runs")
def mission_runs(mid: int):
    from .. import missions as _m
    if not _m._row(mid):
        raise HTTPException(404, "not found")
    return {"runs": _m.list_runs(mid)}


@missions_r.post("/{mid}/control")
def control_mission(mid: int, body: dict):
    from .. import missions as _m
    try:
        m = _m.set_status(mid, body.get("action", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not m:
        raise HTTPException(404, "not found")
    return m
