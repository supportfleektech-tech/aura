"""Costs router — usage summary + call log."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db

cost_r = APIRouter(prefix="/costs", tags=["costs"])


@cost_r.get("")
def costs_summary():
    from .. import costs as _c
    return _c.summary()


@cost_r.get("/calls")
def costs_calls(limit: int = 50):
    rows = db.q("SELECT * FROM llm_usage ORDER BY id DESC LIMIT ?", (max(1, min(200, limit)),))
    return {"calls": rows}
