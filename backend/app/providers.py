"""Outbound provider adapters — real delivery with sandbox fallback.

Every platform has two modes (stored per-integration in config_json):
  sandbox (default) — no network calls; sends are recorded in the audit trail.
  live              — real API calls using the stored credentials.

Secrets are NEVER returned by any status helper — see redacted_status().
All network failures are returned as data, never raised.
"""
from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage
from typing import Any

import httpx

from . import db

TIMEOUT = 15.0
PLATFORMS = ("telegram", "discord", "slack", "whatsapp", "email", "homeassistant")

REQUIRED: dict[str, list[str]] = {
    "telegram": ["bot_token"],
    "email": ["smtp_host", "smtp_user", "smtp_pass", "from_addr"],
    "discord": ["webhook_url"],
    "slack": ["webhook_url"],
    "whatsapp": ["webhook_url"],
    "homeassistant": ["base_url", "token"],
}

_SECRET_SUBSTR = ("token", "pass", "secret", "webhook", "key", "pwd")


def get_integration(platform: str) -> tuple[dict | None, dict]:
    row = db.qone("SELECT * FROM integrations WHERE user_id=1 AND platform=?", (platform,))
    cfg = db.jload((row or {}).get("config_json"), {}) if row else {}
    return row, cfg if isinstance(cfg, dict) else {}


def save_config(platform: str, cfg: dict) -> None:
    db.run("UPDATE integrations SET config_json=? WHERE user_id=1 AND platform=?",
           (db.jdump(cfg), platform))


def validate_config(platform: str, cfg: dict) -> list[str]:
    if platform == "whatsapp":
        # Two accepted credential sets: generic provider webhook, or Cloud API.
        if cfg.get("webhook_url"):
            return []
        if cfg.get("wa_token") and cfg.get("phone_number_id"):
            return []
        if cfg.get("wa_token") or cfg.get("phone_number_id"):
            return (["phone_number_id"] if cfg.get("wa_token") else ["wa_token"])
        return ["webhook_url or wa_token+phone_number_id"]
    return [k for k in REQUIRED.get(platform, []) if not (cfg.get(k) or "")]


def redacted_status(platform: str, cfg: dict) -> dict:
    """Public status view — secrets never leave the server."""
    safe = {k: v for k, v in cfg.items()
            if not any(s in k.lower() for s in _SECRET_SUBSTR)
            and k not in ("last_error", "last_ok")
            and not isinstance(v, dict)}
    return {"mode": cfg.get("mode", "sandbox"),
            "configured": not validate_config(platform, cfg),
            "missing": validate_config(platform, cfg),
            "fields": safe,
            "last_error": cfg.get("last_error", ""),
            "last_ok": cfg.get("last_ok", "")}


def resolve_email(to: str) -> str | None:
    """Turn a draft recipient ('Brian Otieno' or 'a@b.com') into an address."""
    to = (to or "").strip()
    if "@" in to:
        return to
    if not to:
        return None
    for c in db.q("SELECT name, email FROM clients WHERE user_id=1 AND email LIKE '%@%'"):
        n = (c.get("name") or "").lower()
        if n and (n in to.lower() or to.lower() in n):
            return c["email"]
    return None


def _remember(platform: str, ok: bool, note: str = "") -> None:
    _, cfg = get_integration(platform)
    if ok:
        cfg["last_ok"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cfg.pop("last_error", None)
    else:
        cfg["last_error"] = note[:200]
    save_config(platform, cfg)


# ------------------------------------------------------------ live sends ---

def _send_telegram(cfg: dict, to: str, text: str) -> dict:
    chat_id = to.strip() if to.strip().lstrip("-").isdigit() else (cfg.get("default_chat_id") or "")
    if not chat_id:
        return {"sent": False, "error": "no chat_id: set default_chat_id or a numeric recipient"}
    r = httpx.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                   json={"chat_id": chat_id, "text": text[:4000]}, timeout=TIMEOUT)
    d = r.json()
    if r.status_code == 200 and d.get("ok"):
        return {"sent": True, "message_id": str((d.get("result") or {}).get("message_id", ""))}
    return {"sent": False, "error": str(d.get("description") or f"http {r.status_code}")[:200]}


def _send_email(cfg: dict, to: str, subject: str, text: str) -> dict:
    addr = resolve_email(to)
    if not addr:
        return {"sent": False, "error": f"no email address for {to or 'recipient'} — add it to the client record"}
    msg = EmailMessage()
    msg["From"] = cfg.get("from_addr", "")
    msg["To"] = addr
    msg["Subject"] = subject or "Message from AURA"
    msg.set_content(text or "")
    host, port = cfg.get("smtp_host", ""), int(cfg.get("smtp_port", 587) or 587)
    if port == 465:
        smtp: Any = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
    else:
        smtp = smtplib.SMTP(host, port, timeout=TIMEOUT)
        if str(cfg.get("use_tls", "1")) == "1":
            smtp.starttls()
    try:
        smtp.login(cfg.get("smtp_user", ""), cfg.get("smtp_pass", ""))
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return {"sent": True, "to": addr}


def _send_webhook(cfg: dict, text: str, limit: int, key: str) -> dict:
    r = httpx.post(cfg["webhook_url"], json={key: (text or "")[:limit]}, timeout=TIMEOUT)
    if r.status_code in (200, 201, 204):
        return {"sent": True}
    return {"sent": False, "error": f"http {r.status_code}: {r.text[:150]}"}


def _send_whatsapp(cfg: dict, to: str, text: str) -> dict:
    dest = to.strip() or (cfg.get("default_to") or "")
    if not dest:
        return {"sent": False, "error": "no recipient: set default_to or pass a phone number"}
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    r = httpx.post(cfg["webhook_url"], json={"to": dest, "text": (text or "")[:4000]},
                   headers=headers, timeout=TIMEOUT)
    if r.status_code in (200, 201, 202, 204):
        return {"sent": True, "to": dest}
    return {"sent": False, "error": f"http {r.status_code}: {r.text[:150]}"}


def send_live(platform: str, cfg: dict, to: str, subject: str, text: str) -> dict:
    try:
        if platform == "telegram":
            res = _send_telegram(cfg, to, text)
        elif platform == "email":
            res = _send_email(cfg, to, subject, text)
        elif platform == "discord":
            res = _send_webhook(cfg, text, 2000, "content")
        elif platform == "slack":
            res = _send_webhook(cfg, text, 3000, "text")
        elif platform == "whatsapp":
            if cfg.get("wa_token") and cfg.get("phone_number_id"):
                from .messaging import whatsapp_send_cloud  # lazy: messaging imports providers
                res = whatsapp_send_cloud(cfg, to, text)
            else:
                res = _send_whatsapp(cfg, to, text)
        elif platform == "homeassistant":
            return {"sent": False, "error": "homeassistant is a control plane, not messaging — use /api/home"}
        else:
            return {"sent": False, "error": f"unknown platform {platform}"}
    except Exception as e:
        res = {"sent": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    res["mode"] = "live"
    res["platform"] = platform
    _remember(platform, bool(res.get("sent")), res.get("error", ""))
    return res


def send(platform: str, to: str, subject: str, text: str) -> dict:
    """Dispatcher: sandbox (audited, no network) or live (real API)."""
    row, cfg = get_integration(platform)
    if not row:
        return {"sent": False, "platform": platform, "error": f"unknown platform {platform}"}
    if platform == "homeassistant":
        return {"sent": False, "platform": platform,
                "error": "homeassistant is a control plane, not messaging — use /api/home"}
    if (row.get("status") or "") != "connected":
        return {"queued": True, "platform": platform,
                "note": f"{platform} not connected — connect it in Multi-Platform first."}
    if cfg.get("mode", "sandbox") == "live":
        missing = validate_config(platform, cfg)
        if missing:
            return {"sent": False, "platform": platform, "mode": "live",
                    "error": f"missing live credentials: {', '.join(missing)}"}
        return send_live(platform, cfg, to, subject, text)
    return {"sent": True, "platform": platform, "to": to, "mode": "sandbox"}


# ---------------------------------------------------------- live tests ----

def test_connection(platform: str) -> dict:
    """Validate credentials. Webhook platforms receive one real test message."""
    t0 = time.time()
    row, cfg = get_integration(platform)
    if not row:
        return {"ok": False, "error": "unknown platform"}
    if cfg.get("mode", "sandbox") != "live":
        return {"ok": True, "mode": "sandbox", "latency_ms": max(1, int((time.time() - t0) * 1000))}
    missing = validate_config(platform, cfg)
    if missing:
        return {"ok": False, "mode": "live", "error": f"missing: {', '.join(missing)}"}
    try:
        if platform == "telegram":
            r = httpx.get(f"https://api.telegram.org/bot{cfg['bot_token']}/getMe", timeout=TIMEOUT)
            d = r.json()
            if not (r.status_code == 200 and d.get("ok")):
                return {"ok": False, "mode": "live",
                        "error": str(d.get("description") or f"http {r.status_code}")[:150]}
            detail = f"@{((d.get('result') or {}).get('username', ''))}"
        elif platform == "email":
            host, port = cfg.get("smtp_host", ""), int(cfg.get("smtp_port", 587) or 587)
            smtp: Any = (smtplib.SMTP_SSL(host, port, timeout=TIMEOUT) if port == 465
                         else smtplib.SMTP(host, port, timeout=TIMEOUT))
            try:
                if port != 465 and str(cfg.get("use_tls", "1")) == "1":
                    smtp.starttls()
                smtp.login(cfg.get("smtp_user", ""), cfg.get("smtp_pass", ""))
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass
            detail = f"SMTP login ok ({host})"
        elif platform == "homeassistant":
            from . import homeassistant as _ha
            ping = _ha.ping()
            if not ping.get("ok"):
                return {"ok": False, "mode": "live", "error": ping.get("error", "unreachable")}
            detail = ping.get("detail", "API running")
        else:
            res = send_live(platform, cfg, "", "", "✅ AURA connection test — your gateway works.")
            if not res.get("sent"):
                return {"ok": False, "mode": "live", "error": res.get("error", "send failed")}
            detail = "test message delivered"
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:150]}"
        _remember(platform, False, err)
        return {"ok": False, "mode": "live", "error": err}
    ms = max(1, int((time.time() - t0) * 1000))
    _remember(platform, True)
    return {"ok": True, "mode": "live", "latency_ms": ms, "detail": detail}
