"""Home Assistant router — status, entities, services."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db

home_r = APIRouter(prefix="/home", tags=["home"])


@home_r.get("/status")
def home_status():
    from ..providers import get_integration, redacted_status
    row, cfg = get_integration("homeassistant")
    out = {"platform": "homeassistant", "status": (row or {}).get("status", "disconnected"),
           "account": (row or {}).get("account", ""),
           "last_test": (row or {}).get("last_test")}
    out.update(redacted_status("homeassistant", cfg))
    return out


@home_r.get("/entities")
def home_entities():
    from .. import homeassistant as _ha
    return _ha.states()


@home_r.post("/service")
def home_service(body: dict):
    from .. import homeassistant as _ha
    res = _ha.call_service(body.get("domain", ""), body.get("service", ""),
                           body.get("entity_id", ""),
                           body.get("data") if isinstance(body.get("data"), dict) else None)
    db.log_activity("integration",
                    f"Home: {body.get('domain')}.{body.get('service')} {body.get('entity_id', '')}",
                    res.get("error", res.get("mode", ""))[:120], "general",
                    "success" if res.get("ok") else "error")
    return res
