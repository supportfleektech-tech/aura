"""Gateway router — integrations, messaging, simulate."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Response

from .. import db

gateway_r = APIRouter(prefix="/gateway", tags=["gateway"])


def _hermes():
    from ..hermes import hermes
    return hermes


@gateway_r.get("/status")
def gateway_status():
    from ..providers import get_integration, redacted_status
    rows = db.q("SELECT platform,status,account,last_test FROM integrations WHERE user_id=1")
    for r in rows:
        _, cfg = get_integration(r["platform"])
        r.update(redacted_status(r["platform"], cfg))
    return {"integrations": rows, "events": _hermes().recent_events(20)}


@gateway_r.post("/{platform}/connect")
def gw_connect(platform: str, body: dict):
    from ..providers import get_integration, save_config, validate_config
    if platform not in ("telegram", "discord", "slack", "whatsapp", "email", "homeassistant"):
        raise HTTPException(404, f"unknown platform {platform}")
    _, cfg = get_integration(platform)
    incoming = body.get("config") if isinstance(body.get("config"), dict) else {}
    for k, v in incoming.items():
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()
    mode = (body.get("mode") or cfg.get("mode") or "sandbox").lower()
    if mode not in ("sandbox", "live"):
        raise HTTPException(400, "mode must be sandbox|live")
    if mode == "live":
        missing = validate_config(platform, cfg)
        if missing:
            raise HTTPException(400, f"missing live credentials: {', '.join(missing)}")
    cfg["mode"] = mode
    save_config(platform, cfg)
    db.run("UPDATE integrations SET status='connected', account=? WHERE user_id=1 AND platform=?",
           (body.get("account") or f"{platform} account", platform))
    _hermes().emit_gateway(platform, f"{platform} connected ({mode})", actor="system", direction="out")
    return {"ok": True, "mode": mode}


@gateway_r.post("/{platform}/disconnect")
def gw_disconnect(platform: str, body: dict | None = None):
    from ..providers import save_config
    if (body or {}).get("forget"):
        save_config(platform, {})
    db.run("UPDATE integrations SET status='disconnected' WHERE user_id=1 AND platform=?", (platform,))
    return {"ok": True}


@gateway_r.post("/{platform}/test")
def gw_test(platform: str):
    import time as _t
    from datetime import datetime, timezone as tz
    from ..providers import test_connection
    _t0 = _t.time()
    res = test_connection(platform)
    if res.get("ok"):
        db.run("UPDATE integrations SET last_test=?, status='connected' WHERE user_id=1 AND platform=?",
               (datetime.now(tz.utc).isoformat(), platform))
        _hermes().emit_gateway(platform, f"connection test ({res.get('mode', 'sandbox')})", actor="aura", direction="out")
        db.log_activity("integration", f"Gateway test: {platform}", res.get("detail", "ping ok"), "general", "success")
    else:
        db.run("UPDATE integrations SET status='error' WHERE user_id=1 AND platform=?", (platform,))
        db.log_activity("integration", f"Gateway test FAILED: {platform}", res.get("error", "")[:150], "general", "error")
    res["latency_ms"] = res.get("latency_ms", max(1, int((_t.time() - _t0) * 1000)))
    res["platform"] = platform
    return res


@gateway_r.post("/simulate")
def gw_simulate(ev: dict):
    if ev.get("send_live"):
        from ..providers import send as provider_send
        plat = ev.get("platform", "telegram")
        res = provider_send(plat, ev.get("to", ""), ev.get("subject", "AURA live test"),
                            ev.get("text", "hello"))
        if res.get("sent"):
            e = _hermes().emit_gateway(plat, (ev.get("text") or "")[:160], actor="aura",
                                    direction="out", payload={"mode": res.get("mode")})
            db.log_activity("integration", f"Live test message sent via {plat}",
                            f"mode={res.get('mode')}", "general", "success")
            return {"event_id": e["event_id"], "sent": True, "mode": res.get("mode")}
        raise HTTPException(400, res.get("error") or res.get("note", "send failed"))
    e = _hermes().emit_gateway(ev.get("platform", "telegram"), ev.get("text", "hello"), actor="user")
    return {"event_id": e["event_id"]}


# --- messaging bots ---

@gateway_r.post("/telegram/poll")
def gw_telegram_poll():
    from .. import messaging
    return messaging.telegram_poll()


@gateway_r.post("/telegram/webhook")
def gw_telegram_webhook(update: dict,
                        secret: str | None = Header(default=None, alias="x-telegram-bot-api-secret-token")):
    from .. import messaging
    res = messaging.telegram_webhook(update or {}, secret)
    if res.get("error") == "bad webhook secret":
        raise HTTPException(403, "bad webhook secret")
    return res


@gateway_r.get("/whatsapp/webhook")
def gw_whatsapp_verify(hub_mode: str = Query(default="", alias="hub.mode"),
                       hub_token: str = Query(default="", alias="hub.verify_token"),
                       hub_challenge: str = Query(default="", alias="hub.challenge")):
    from .. import messaging
    chal = messaging.whatsapp_verify(hub_mode, hub_token, hub_challenge)
    if chal is None:
        raise HTTPException(403, "verify_token mismatch")
    return Response(content=chal, media_type="text/plain")


@gateway_r.post("/whatsapp/webhook")
def gw_whatsapp_webhook(payload: dict):
    from .. import messaging
    return messaging.whatsapp_webhook(payload or {})
