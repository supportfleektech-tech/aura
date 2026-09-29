"""Activity router — activity feed."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db

activity_r = APIRouter(prefix="/activity", tags=["activity"])


@activity_r.get("")
def list_activity(kind: str | None = None, domain: str | None = None, limit: int = 100):
    sql, p = "SELECT * FROM activity WHERE user_id=1", []
    if kind:
        sql += " AND kind=?"; p.append(kind)
    if domain:
        sql += " AND domain=?"; p.append(domain)
    return {"activity": db.q(sql + " ORDER BY id DESC LIMIT ?", (*p, limit))}
