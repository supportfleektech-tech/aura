"""AURA OS settings store — validated key/value preferences in SQLite.

Effective value resolution: DB row > environment default > code default.
Secrets (API keys) are write-only over the API: GET only reports `*_set`
booleans, never values. Unknown keys are rejected on write.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import config, db

# -- schema: key -> (default, kind, constraint) --------------------------------
# kinds: enum | bool | int | float | str | secret | url | hhmm
SCHEMA: dict[str, tuple[Any, str, Any]] = {
    # AI engine / cloud
    "privacy": ("local-first", "enum", ("local-first", "hybrid", "cloud")),
    "cloud_provider": ("openrouter", "enum", ("openrouter", "openai", "custom")),
    "openrouter_model": ("google/gemma-4-31b-it:free", "str", 200),
    "openai_model": ("gpt-4o-mini", "str", 200),
    "custom_base_url": ("", "url", 300),
    "custom_model": ("", "str", 200),
    "cloud_temperature": (0.6, "float", (0.0, 2.0)),
    "cloud_max_tokens": (900, "int", (64, 8000)),
    "cloud_reasoning": (False, "bool", None),
    "cloud_memory_policy": ("strict", "enum", ("strict", "relaxed")),
    "memory_auto_store": (True, "bool", None),
    "vision_enabled": (True, "bool", None),
    # local LFM
    "ollama_base_url": (config.OLLAMA_BASE_URL, "url", 300),
    "ollama_chat_model": (config.OLLAMA_CHAT_MODEL, "str", 200),
    "ollama_vision_model": ("llava", "str", 200),
    "ollama_embed_model": (config.OLLAMA_EMBED_MODEL, "str", 200),
    # ollama model-room sync (v1.14)
    "ollama_auto_sync": (True, "bool", None),
    "ollama_sync_interval_min": (30, "int", (1, 1440)),
    # local terminal / machine control (v1.14)
    "terminal_enabled": (True, "bool", None),
    "terminal_cwd": ("", "str", 300),
    "terminal_timeout_s": (30, "int", (2, 600)),
    "terminal_max_out_kb": (64, "int", (8, 512)),
    "terminal_allow_dangerous": (False, "bool", None),
    "terminal_machines": ("[]", "str", 8000),  # JSON: [{"name","host"}] — ssh targets
    # feeds + weather (v1.14)
    "feeds_refresh_min": (30, "int", (0, 1440)),
    "weather_enabled": (True, "bool", None),
    "weather_lat": (0.0, "float", (-90.0, 90.0)),
    "weather_lon": (0.0, "float", (-180.0, 180.0)),
    "weather_place": ("", "str", 80),
    # voice calls (v1.14)
    "call_summary": (True, "bool", None),
    # folder watch (v1.15)
    "watch_enabled": (False, "bool", None),
    "watch_paths": ("[]", "str", 4000),          # JSON list of directories
    "watch_ingest": (True, "bool", None),         # index + remember file text
    "watch_scan_interval_s": (120, "int", (30, 3600)),
    # voice
    "voice_lang": ("en-KE", "str", 20),
    "voice_engine": ("browser", "enum", ("browser", "piper", "edge", "kokoro")),
    "voice_kokoro_id": ("af_heart", "enum", ("af_heart", "af_bella", "af_sarah", "am_adam", "am_michael", "bf_emma", "bm_george")),
    "ai_warmth": ("warm", "enum", ("neutral", "warm", "supportive")),
    "ai_humour": ("off", "enum", ("off", "light", "playful")),
    "ai_style": ("conversational", "enum", ("conversational", "professional", "direct")),
    "ai_pacing": ("balanced", "enum", ("concise", "balanced", "unhurried")),
    "voice_edge_id": ("en-KE-ChilembaNeural", "str", 80),
    "voice_piper_id": ("en_US-lessac-medium", "str", 80),
    "voice_browser_name": ("", "str", 120),
    "voice_emotion": ("neutral", "enum", ("neutral", "cheerful", "calm", "excited", "serious", "sad")),
    "voice_pitch": (1.0, "float", (0.5, 2.0)),
    "voice_breaks": (True, "bool", None),
    "voice_rate": (1.0, "float", (0.5, 2.0)),
    "voice_autoplay": (False, "bool", None),
    # always-on voice loop (v1.9)
    "wake_enabled": (False, "bool", None),
    "wake_threshold": (0.5, "float", (0.1, 0.95)),
    "vad_energy": (500.0, "float", (100.0, 4000.0)),
    "followup_ms": (6000, "int", (2000, 30000)),
    "barge_in": (True, "bool", None),
    "mission_step_checkins": (False, "bool", None),
    # worker pool (spec §5, FR-WRK-001/003)
    "worker_pool_size": (3, "int", (1, 8)),
    "worker_max_retries": (3, "int", (0, 5)),
    # chat
    "chat_streaming": (True, "bool", None),
    "enter_to_send": (True, "bool", None),
    "chat_timestamps": (False, "bool", None),
    # slash commands (spec §3, FR-CMD-004) — JSON list of {"name","prompt","view"}
    "slash_custom": ("[]", "str", 8000),
    "chat_parallel_steps": (True, "bool", None),
    "approval_timeout": ("+30 seconds", "str", 50),
    # notifications
    "toast_duration_ms": (4200, "int", (1500, 12000)),
    "quiet_start": ("", "hhmm", None),
    "quiet_end": ("", "hhmm", None),
    # data & privacy
    "retention_days": (90, "int", (0, 3650)),
    "device_name": ("aura-main", "str", 80),
    "onboarded": (False, "bool", None),
    "timezone": ("Africa/Nairobi", "tz", 60),
    "domain_career": (True, "bool", None),
    "domain_clients": (True, "bool", None),
    "domain_personal": (True, "bool", None),
    "proactive_enabled": (True, "bool", None),
    "proactive_threshold": (0.1, "float", (0.0, 1.0)),
    "chat_compact_after": (30, "int", (10, 200)),
    "chat_context_window": (12, "int", (4, 40)),
    "cost_daily_cap_usd": (0.0, "float", (0.0, 10000.0)),
    "cost_monthly_cap_usd": (0.0, "float", (0.0, 100000.0)),
    "proactive_muted": ("", "str", 200),
    "retention_last_run": (0, "int", (0, 2**31)),
    "consolidate_enabled": (True, "bool", None),
    "consolidate_last_run": (0, "int", (0, 2**31)),
    # secrets (write-only via API)
    "openrouter_key": ("", "secret", 300),
    "openai_key": ("", "secret", 300),
    "custom_key": ("", "secret", 300),
}

SECRET_KEYS = {k for k, (_, kind, _) in SCHEMA.items() if kind == "secret"}

# Env vars act as defaults when no DB row exists (existing env config keeps working).
_ENV_DEFAULTS = {
    "privacy": "AURA_PRIVACY",
    "cloud_provider": "AURA_CLOUD_PROVIDER",
    "openrouter_model": "AURA_OPENROUTER_MODEL",
    "openai_model": "AURA_CLOUD_MODEL",
    "openrouter_key": "AURA_OPENROUTER_API_KEY",
    "openai_key": "AURA_CLOUD_API_KEY",
    "custom_base_url": "AURA_CUSTOM_BASE_URL",
    "custom_model": "AURA_CUSTOM_MODEL",
    "custom_key": "AURA_CUSTOM_KEY",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_chat_model": "OLLAMA_CHAT_MODEL",
}

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _env_default(key: str) -> Any:
    import os
    env = _ENV_DEFAULTS.get(key)
    if env and os.environ.get(env):
        return os.environ[env]
    return SCHEMA[key][0]


def validate(key: str, value: Any) -> Any:
    """Validate + coerce a single setting. Raises ValueError on rejection."""
    if key not in SCHEMA:
        raise ValueError(f"unknown setting: {key}")
    default, kind, rule = SCHEMA[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "1", "yes", "on"):
            return True
        if isinstance(value, str) and value.lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key} must be true/false")
    if kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        lo, hi = rule
        if not (lo <= v <= hi):
            raise ValueError(f"{key} must be {lo}..{hi}")
        return v
    if kind == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        lo, hi = rule
        if not (lo <= v <= hi):
            raise ValueError(f"{key} must be {lo}..{hi}")
        return round(v, 3)
    if kind == "enum":
        if value not in rule:
            raise ValueError(f"{key} must be one of {', '.join(rule)}")
        return value
    if kind == "secret":
        if not isinstance(value, str) or len(value) > rule:
            raise ValueError(f"{key} must be a string under {rule} chars")
        return value.strip()
    if kind == "url":
        if not isinstance(value, str) or len(value) > rule:
            raise ValueError(f"{key} must be a string under {rule} chars")
        v = value.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https://")
        return v
    if kind == "hhmm":
        if not isinstance(value, str):
            raise ValueError(f"{key} must be 'HH:MM' or empty")
        v = value.strip()
        if v and not _HHMM.match(v):
            raise ValueError(f"{key} must be 'HH:MM' (24h) or empty")
        return v
    if kind == "tz":
        if not isinstance(value, str) or len(value) > rule:
            raise ValueError(f"{key} must be a string under {rule} chars")
        v = value.strip() or default
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(v)
        except Exception:
            raise ValueError(f"{key} is not a valid IANA timezone: {v}")
        return v
    # str
    if not isinstance(value, str) or len(value) > rule:
        raise ValueError(f"{key} must be a string under {rule} chars")
    return value.strip()


def get(key: str) -> Any:
    """Effective value: DB row, else env default, else code default."""
    if key not in SCHEMA:
        raise KeyError(key)
    try:
        row = db.qone("SELECT value_json FROM settings WHERE key=?", (key,))
    except Exception:
        row = None
    if row:
        try:
            return db.jload(row["value_json"])
        except Exception:
            pass
    return _env_default(key)


def set_many(items: dict) -> dict:
    """Validate + persist. Empty-string secret clears to env/default. Returns saved keys."""
    if not isinstance(items, dict):
        raise ValueError("settings body must be an object")
    saved = {}
    for key, value in items.items():
        v = validate(key, value)
        db.run("INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
               "updated_at=excluded.updated_at",
               (key, db.jdump(v), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        saved[key] = v
    return saved


def reset_all() -> None:
    db.run("DELETE FROM settings")


def public_view() -> dict:
    """API-safe snapshot: values (no secrets), secret-set flags, and sources."""
    values, secrets, sources = {}, {}, {}
    for key in SCHEMA:
        if key in SECRET_KEYS:
            secrets[key] = bool(get(key))
            sources[key] = "db" if _db_has(key) else ("env" if _env_set(key) else "default")
        else:
            values[key] = get(key)
            sources[key] = "db" if _db_has(key) else ("env" if _env_set(key) else "default")
    values.pop("retention_last_run", None)
    sources.pop("retention_last_run", None)
    values.pop("consolidate_last_run", None)
    sources.pop("consolidate_last_run", None)
    return {"values": values, "secrets": secrets, "sources": sources}


def _db_has(key: str) -> bool:
    try:
        return db.qone("SELECT 1 x FROM settings WHERE key=?", (key,)) is not None
    except Exception:
        return False


def _env_set(key: str) -> bool:
    import os
    env = _ENV_DEFAULTS.get(key)
    return bool(env and os.environ.get(env))


# -- quiet hours (user timezone) ----------------------------------------------

def user_tz():
    """Effective user timezone (never raises — falls back to Nairobi)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(get("timezone") or "Africa/Nairobi")
    except Exception:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Africa/Nairobi")


def in_quiet_hours(now_ts: float | None = None) -> bool:
    """True when push/noisy alerts should be suppressed."""
    start, end = get("quiet_start"), get("quiet_end")
    if not start or not end:
        return False
    try:
        from zoneinfo import ZoneInfo
        import datetime as dt
        now = dt.datetime.fromtimestamp(now_ts if now_ts is not None else time.time(),
                                        tz=user_tz())
        cur = now.hour * 60 + now.minute
        s = int(start[:2]) * 60 + int(start[3:])
        e = int(end[:2]) * 60 + int(end[3:])
        return cur >= s or cur < e if s > e else s <= cur < e
    except Exception:
        return False


# -- retention pruning (observability tables only — never user content) --------

PRUNE_TABLES = ("activity", "audit", "toolcalls")


def prune_retention(now_ts: float | None = None) -> dict:
    """Delete observability rows older than retention_days. Runs at most daily."""
    days = get("retention_days")
    if not days:
        return {"pruned": 0, "tables": [], "skipped": "retention off (0 = keep forever)"}
    now = now_ts if now_ts is not None else time.time()
    if now - float(get("retention_last_run") or 0) < 86400:
        return {"pruned": 0, "tables": [], "skipped": "already ran in last 24h"}
    import datetime as dt
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    total, tables = 0, []
    for t in PRUNE_TABLES:
        try:
            n = db.run(f"DELETE FROM {t} WHERE created_at < ?", (cutoff,))
            total += n
            tables.append({"table": t, "deleted": n})
        except Exception:
            continue
    try:
        set_many({"retention_last_run": int(now)})
    except Exception:
        pass
    return {"pruned": total, "tables": tables, "cutoff": cutoff}
