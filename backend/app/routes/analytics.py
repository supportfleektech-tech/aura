"""Analytics router — overview."""
from __future__ import annotations

from fastapi import APIRouter

analytics_r = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_r.get("/overview")
def analytics_overview():
    from .. import analytics as _a
    return _a.overview()
