"""Inbound messaging — Telegram + WhatsApp bots via the gateway.

Outbound already lives in providers.py; this module is the other half:
  telegram — getUpdates polling (works behind NAT, no public URL needed)
             + webhook receiver for deployments with a public URL.
  whatsapp — Meta Cloud API webhook (verification handshake + inbound)
             + Cloud API sending when wa_token/phone_number_id are set
             (generic provider webhook_url remains as fallback).

Everything is token-ready with honest off-states: without credentials the
endpoints say so in data ({ok: False, error}) instead of pretending.
Auto-reply is OFF unless the integration config holds `auto_reply` text.
"""
from __future__ import annotations

import httpx

from . import db
from .hermes import hermes
from .providers import TIMEOUT, get_integration, save_config, send_live

TG_API = "https://api.telegram.org/bot{tok}/{method}"
WA_API = "https://graph.facebook.com/v21.0/{pid}/messages"


def _inbound(platform: str, text: str, payload: dict) -> None:
    hermes.emit_gateway(platform, (text or "")[:500], actor="user", direction="in",
                        payload=payload)
    sender = payload.get("from") or payload.get("chat_id") or "?"
    db.notify(f"{platform.title()} message", f"{sender}: {(text or '')[:120]}", "message")


# ---------------------------------------------------------------- telegram --

def _tg_autoreply(cfg: dict, chat_id: str) -> bool:
    text = (cfg.get("auto_reply") or "").strip()
    if not text or not chat_id:
        return False
    res = send_live("telegram", cfg, chat_id, "", text)
    if res.get("sent"):
        hermes.emit_gateway("telegram", text[:160], actor="aura", direction="out",
                            payload={"chat_id": chat_id, "auto": True})
        return True
    return False


def telegram_poll() -> dict:
    """Fetch pending Telegram updates (long-poll-free; advances stored offset)."""
    row, cfg = get_integration("telegram")
    if not row or (row.get("status") or "") != "connected":
        return {"ok": False, "error": "telegram not connected — connect it in Multi-Platform first."}
    if cfg.get("mode", "sandbox") != "live" or not cfg.get("bot_token"):
        return {"ok": False, "error": "telegram live bot_token not configured."}
    try:
        r = httpx.get(TG_API.format(tok=cfg["bot_token"], method="getUpdates"),
                      params={"offset": cfg.get("tg_offset", 0), "timeout": 10,
                              "allowed_updates": ["message"]}, timeout=TIMEOUT + 10)
        d = r.json()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if not (r.status_code == 200 and d.get("ok")):
        return {"ok": False, "error": str((d.get("description") or f"http {r.status_code}"))[:200]}
    inbound, replies, seen = [], 0, int(cfg.get("tg_offset", 0) or 0)
    for u in d.get("result") or []:
        seen = max(seen, int(u.get("update_id", 0)) + 1)
        msg = u.get("message") or {}
        text = msg.get("text") or ""
        if not text:
            continue
        chat = msg.get("chat") or {}
        frm = msg.get("from") or {}
        _inbound("telegram", text, {"chat_id": str(chat.get("id", "")),
                                    "message_id": msg.get("message_id"),
                                    "from": frm.get("username") or frm.get("first_name") or ""})
        inbound.append({"chat_id": str(chat.get("id", "")), "text": text[:160]})
        if _tg_autoreply(cfg, str(chat.get("id", ""))):
            replies += 1
    cfg["tg_offset"] = seen
    save_config("telegram", cfg)
    return {"ok": True, "fetched": len(d.get("result") or []),
            "inbound": inbound, "replies": replies}


def telegram_webhook(update: dict, secret: str | None) -> dict:
    """Handle one Telegram webhook update. Secret-checked when configured."""
    _, cfg = get_integration("telegram")
    want = (cfg.get("webhook_secret") or "").strip()
    if want and secret != want:
        return {"ok": False, "error": "bad webhook secret"}
    msg = (update or {}).get("message") or {}
    text = msg.get("text") or ""
    if not text:
        return {"ok": True, "handled": False}
    chat = msg.get("chat") or {}
    frm = msg.get("from") or {}
    _inbound("telegram", text, {"chat_id": str(chat.get("id", "")),
                                "message_id": msg.get("message_id"),
                                "from": frm.get("username") or frm.get("first_name") or "",
                                "via": "webhook"})
    replied = _tg_autoreply(cfg, str(chat.get("id", "")))
    return {"ok": True, "handled": True, "replied": replied}


# ---------------------------------------------------------------- whatsapp --

def whatsapp_send_cloud(cfg: dict, to: str, text: str) -> dict:
    """Meta Cloud API text send. Returns providers-style {sent|error}."""
    dest = (to or "").strip() or (cfg.get("default_to") or "")
    if not dest:
        return {"sent": False, "error": "no recipient: set default_to or pass a phone number"}
    try:
        r = httpx.post(WA_API.format(pid=cfg["phone_number_id"]),
                       headers={"Authorization": f"Bearer {cfg['wa_token']}"},
                       json={"messaging_product": "whatsapp", "to": dest,
                             "type": "text", "text": {"body": (text or "")[:4000]}},
                       timeout=TIMEOUT)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        return {"sent": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    if r.status_code in (200, 201) and not (d.get("error")):
        return {"sent": True, "to": dest}
    err = ((d.get("error") or {}).get("message") if isinstance(d, dict) else "") or f"http {r.status_code}"
    return {"sent": False, "error": str(err)[:200]}


def whatsapp_verify(mode: str, token: str, challenge: str) -> str | None:
    """Meta webhook handshake — returns the challenge iff the token matches."""
    _, cfg = get_integration("whatsapp")
    want = (cfg.get("verify_token") or "").strip()
    if mode == "subscribe" and want and token == want:
        return challenge
    return None


def whatsapp_webhook(payload: dict) -> dict:
    """Parse a Meta Cloud API webhook payload; record inbound texts."""
    inbound, replies, skipped = [], 0, 0
    _, cfg = get_integration("whatsapp")
    auto = (cfg.get("auto_reply") or "").strip()
    cloud = bool(cfg.get("wa_token") and cfg.get("phone_number_id"))
    for entry in (payload or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for msg in value.get("messages") or []:
                if msg.get("type") != "text":
                    skipped += 1
                    continue
                text = ((msg.get("text") or {}).get("body") or "")
                sender = msg.get("from", "")
                _inbound("whatsapp", text, {"from": sender, "message_id": msg.get("id"),
                                            "via": "webhook"})
                inbound.append({"from": sender, "text": text[:160]})
                if auto and cloud:
                    res = whatsapp_send_cloud(cfg, sender, auto)
                    if res.get("sent"):
                        hermes.emit_gateway("whatsapp", auto[:160], actor="aura",
                                            direction="out", payload={"to": sender, "auto": True})
                        replies += 1
            skipped += len(value.get("statuses") or [])
    return {"ok": True, "inbound": inbound, "replies": replies, "skipped": skipped}
