"""Consolidation router — run a pass and report the last one."""
from __future__ import annotations

import time

from fastapi import APIRouter

from .. import consolidate, db, prefs

consol_r = APIRouter(prefix="/consolidation", tags=["consolidation"])


@consol_r.get("")
def status():
    last = db.qone("SELECT * FROM activity WHERE kind='memory' "
                   "AND title LIKE 'Consolidation pass%' ORDER BY id DESC LIMIT 1")
    return {"enabled": bool(prefs.get("consolidate_enabled")),
            "due": consolidate.should_run(),
            "last_run": dict(last) if last else None}


@consol_r.post("/run")
def run_now():
    r = consolidate.run_pass()
    prefs.set_many({"consolidate_last_run": int(time.time())})
    return r
