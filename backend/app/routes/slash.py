"""Slash router — command catalog, execution, and custom commands."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import slash

slash_r = APIRouter(prefix="/slash", tags=["slash"])


@slash_r.get("")
def catalog():
    return {"commands": slash.all_commands()}


@slash_r.post("/execute")
def execute(body: dict):
    # execute() never raises, so a bad command is a 200 with handled/ok false —
    # not a 500 that would abort the chat stream it was fired from.
    return slash.execute((body or {}).get("text", ""))


@slash_r.post("/custom")
def save_custom(body: dict):
    body = body or {}
    try:
        return slash.save_custom(body.get("name", ""), body.get("prompt", ""),
                                 body.get("view", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@slash_r.delete("/custom/{name}")
def delete_custom(name: str):
    slash.delete_custom(name)
    return {"ok": True}
