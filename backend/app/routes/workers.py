"""Worker router — queue observability and manual drain."""
from __future__ import annotations

from fastapi import APIRouter

from .. import workers

worker_r = APIRouter(prefix="/workers", tags=["workers"])


@worker_r.get("")
def status():
    return {"stats": workers.stats(), "pool_size": workers.pool_size()}


@worker_r.get("/dead")
def dead(limit: int = 50):
    return {"dead": workers.dead_letters(limit)}


@worker_r.post("/drain")
def drain():
    return workers.drain()