"""Sync router — export/import."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

sync_r = APIRouter(prefix="/sync", tags=["sync"])


@sync_r.get("/export")
def sync_export(device: str = ""):
    from .. import sync as _s
    from .. import prefs as _p
    _s.log_export(device or _p.get("device_name"))
    return _s.export_bundle()


@sync_r.post("/import")
def sync_import(b: dict):
    from .. import sync as _s
    try:
        return _s.import_bundle(b.get("bundle", {}), b.get("device", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@sync_r.get("/log")
def sync_history(limit: int = 20):
    from .. import sync as _s
    return {"log": _s.history(limit)}
