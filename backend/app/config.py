"""AURA OS backend configuration — environment-driven, local-first defaults."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AURA_DATA_DIR", str(BASE_DIR / ".." / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = os.environ.get("AURA_DB_PATH", str(DATA_DIR / "aura.db"))
USER_NAME = os.environ.get("AURA_USER_NAME", "Antony")
USER_ROLE = os.environ.get("AURA_USER_ROLE", "Builder · Creator · Optimiser")
USER_LOCATION = os.environ.get("AURA_USER_LOCATION", "Nairobi, Kenya")

# Inference routing: ollama (local LFM) -> builtin engine fallback
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.1")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CLOUD_API_KEY = os.environ.get("AURA_CLOUD_API_KEY", "")
CLOUD_MODEL = os.environ.get("AURA_CLOUD_MODEL", "gpt-4o-mini")
CLOUD_BASE_URL = os.environ.get("AURA_CLOUD_BASE_URL", "https://api.openai.com/v1").rstrip("/")
CLOUD_PROVIDER = os.environ.get("AURA_CLOUD_PROVIDER", "openrouter")  # openrouter | openai | custom
OPENROUTER_BASE_URL = os.environ.get("AURA_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_API_KEY = os.environ.get("AURA_OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("AURA_OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
OPENROUTER_REFERER = os.environ.get("AURA_OPENROUTER_REFERER", "https://aura-os.local")
OPENROUTER_TITLE = os.environ.get("AURA_OPENROUTER_TITLE", "AURA OS")
DEFAULT_PRIVACY = os.environ.get("AURA_PRIVACY", "local-first")  # local-first | hybrid | cloud

HERMES_VERSION = os.environ.get("HERMES_VERSION", "2.0.0")
APP_VERSION = "1.16.0"
API_PREFIX = "/api"
def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


# Rate limiting (sliding window per client IP; 0 disables a scope)
RATE_LIMIT_ENABLED = os.environ.get("AURA_RATE_LIMIT_ENABLED", "1") == "1"
RL_CHAT_PER_MIN = _int_env("AURA_RL_CHAT_PER_MIN", 120)
RL_UPLOAD_PER_MIN = _int_env("AURA_RL_UPLOAD_PER_MIN", 30)
RL_API_PER_MIN = _int_env("AURA_RL_API_PER_MIN", 600)

# Payload caps
MAX_MESSAGE_CHARS = _int_env("AURA_MAX_MESSAGE_CHARS", 50000)
MAX_ATTACHMENTS = _int_env("AURA_MAX_ATTACHMENTS", 10)
MAX_UPLOAD_MB = _int_env("AURA_MAX_UPLOAD_MB", 25)
MAX_REQUEST_MB = _int_env("AURA_MAX_REQUEST_MB", 128)

# Web Push (PWA) — generate with scripts/gen_vapid.py; empty = push inert
VAPID_PUBLIC_KEY = os.environ.get("AURA_VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("AURA_VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("AURA_VAPID_SUBJECT", "mailto:aura@localhost")

# Server voice (requirements-voice.txt; models download on first use)
WHISPER_MODEL = os.environ.get("AURA_WHISPER_MODEL", "tiny")
PIPER_VOICE = os.environ.get("AURA_PIPER_VOICE", "en_US-lessac-medium")

# Litestream replica URL (empty = replication off)
LITESTREAM_REPLICA = os.environ.get("AURA_LITESTREAM_REPLICA", "")

# CORS: "*" (default, convenient for trusted single-user + previews) or an
# explicit comma-separated origin list to lock down. Credentials are only
# allowed with explicit origins (browsers reject wildcard + credentials).
_CORS_RAW = os.environ.get("AURA_CORS", "*").strip()
if _CORS_RAW == "*":
    CORS_ORIGINS = ["*"]
    CORS_CREDENTIALS = False
else:
    CORS_ORIGINS = [o.strip() for o in _CORS_RAW.split(",") if o.strip()] or ["http://localhost:5173"]
    CORS_CREDENTIALS = True

# Cross-site guard (v1.15): with no login, a browser tab on any website could
# POST to this API (DNS-rebinding / drive-by). We therefore reject state-
# changing /api/* requests whose Origin header names a different host, unless
# that origin is explicitly allowed here. Non-browser clients (webhooks, curl,
# the mobile provider servers) never send Origin and are unaffected.
# AURA_ALLOWED_ORIGINS: comma-separated "http(s)://host[:port]" or bare hosts.
ALLOWED_ORIGINS_RAW = os.environ.get("AURA_ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGIN_HOSTS = {
    (o.split("://", 1)[-1] if "://" in o else o).strip().lower().rstrip("/")
    for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()
}
