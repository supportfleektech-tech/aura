"""Home Assistant control plane — lights, switches, scripts via the HA REST API.

Connection lives on the `homeassistant` gateway integration (base_url + token,
sandbox/live) so it inherits connect/test/disconnect, redaction, and honest
off-states. Sandbox mode serves clearly-labeled demo entities and flips them
in memory — it never claims to move anything physical.
"""
from __future__ import annotations

import httpx

from .providers import TIMEOUT, get_integration, validate_config

DEMO = [
    {"entity_id": "light.demo_lamp", "state": "on",
     "attributes": {"friendly_name": "Demo Lamp (sandbox)"}},
    {"entity_id": "switch.demo_fan", "state": "off",
     "attributes": {"friendly_name": "Demo Fan (sandbox)"}},
    {"entity_id": "sensor.demo_temperature", "state": "21.5",
     "attributes": {"friendly_name": "Demo Temperature (sandbox)", "unit_of_measurement": "°C"}},
]

_demo_state: dict[str, str] = {}


def _live_cfg() -> tuple[dict | None, dict]:
    row, cfg = get_integration("homeassistant")
    if not row or (row.get("status") or "") != "connected":
        return None, {"error": "homeassistant not connected — connect it in Home first."}
    if cfg.get("mode", "sandbox") != "live":
        return None, {"sandbox": True}
    missing = validate_config("homeassistant", cfg)
    if missing:
        return None, {"error": f"missing live credentials: {', '.join(missing)}"}
    return cfg, {}


def _req(method: str, path: str, cfg: dict, body: dict | None = None):
    base = (cfg.get("base_url") or "").rstrip("/")
    return httpx.request(method, f"{base}{path}",
                         headers={"Authorization": f"Bearer {cfg.get('token')}",
                                  "Content-Type": "application/json"},
                         json=body, timeout=TIMEOUT)


def ping() -> dict:
    """GET /api/ — used by gateway Test. Returns {ok, detail?/error?}."""
    cfg, err = _live_cfg()
    if err.get("sandbox"):
        return {"ok": True, "detail": "sandbox — demo entities only"}
    if cfg is None:
        return {"ok": False, "error": err.get("error", "not configured")}
    try:
        r = _req("GET", "/api/", cfg)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if r.status_code == 401:
        return {"ok": False, "error": "unauthorized — check the long-lived access token"}
    if r.status_code != 200:
        return {"ok": False, "error": f"http {r.status_code}: {r.text[:120]}"}
    return {"ok": True, "detail": "API running"}


def states() -> dict:
    """All entity states. {entities[], mode} — 401s and network faults are data."""
    cfg, err = _live_cfg()
    if err.get("sandbox"):
        ents = []
        for e in DEMO:
            eid = e["entity_id"]
            ents.append({**e, "state": _demo_state.get(eid, e["state"])})
        return {"entities": ents, "mode": "sandbox"}
    if cfg is None:
        return {"entities": [], "mode": "live", "error": err.get("error", "not configured")}
    try:
        r = _req("GET", "/api/states", cfg)
    except Exception as e:
        return {"entities": [], "mode": "live",
                "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if r.status_code == 401:
        return {"entities": [], "mode": "live",
                "error": "unauthorized — check the long-lived access token"}
    if r.status_code != 200:
        return {"entities": [], "mode": "live", "error": f"http {r.status_code}: {r.text[:120]}"}
    try:
        data = r.json()
    except ValueError:
        return {"entities": [], "mode": "live", "error": "invalid JSON from Home Assistant"}
    return {"entities": data if isinstance(data, list) else [], "mode": "live"}


def call_service(domain: str, service: str, entity_id: str = "",
                 data: dict | None = None) -> dict:
    """POST /api/services/{domain}/{service}. {ok, state?/error?}."""
    domain, service = (domain or "").strip(), (service or "").strip()
    if not domain or not service:
        return {"ok": False, "error": "domain and service are required"}
    if "/" in domain or "/" in service or ".." in domain + service:
        return {"ok": False, "error": "invalid domain/service"}
    cfg, err = _live_cfg()
    if err.get("sandbox"):
        eid = (entity_id or "").strip()
        known = [e["entity_id"] for e in DEMO]
        if eid and eid not in known:
            return {"ok": False, "error": f"unknown sandbox entity {eid}"}
        if service == "toggle" and eid:
            cur = _demo_state.get(eid, next(e["state"] for e in DEMO if e["entity_id"] == eid))
            _demo_state[eid] = "off" if cur == "on" else "on"
        elif service in ("turn_on", "turn_off") and eid:
            _demo_state[eid] = "on" if service == "turn_on" else "off"
        return {"ok": True, "mode": "sandbox", "state": _demo_state.get(eid, "")}
    if cfg is None:
        return {"ok": False, "error": err.get("error", "not configured")}
    body = dict(data or {})
    if entity_id:
        body["entity_id"] = entity_id
    try:
        r = _req("POST", f"/api/services/{domain}/{service}", cfg, body)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if r.status_code == 401:
        return {"ok": False, "error": "unauthorized — check the long-lived access token"}
    if r.status_code not in (200, 201):
        return {"ok": False, "error": f"http {r.status_code}: {r.text[:120]}"}
    return {"ok": True, "mode": "live"}
