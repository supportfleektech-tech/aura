"""Ollama model room — sync every model on the machine into AURA.

Reads `GET {ollama_base_url}/api/tags`, normalizes each entry (size, family,
parameter count, quantization) and infers capabilities (chat / vision /
embed / tools) from a curated family table so the settings UI can offer
pickers without guessing. The catalog is cached in SQLite (`ollama_models`)
so the model room still shows the last-known inventory when Ollama is down —
with an explicit `stale` flag, never a lie.

Everything degrades honestly: unreachable → {reachable: False, ...}.
"""
from __future__ import annotations

import json
import time

import httpx

from . import db, prefs

_LAST_SYNC = {"ts": 0.0}

# Family -> what it can do. Unknown families get chat-only (safe default:
# the router probes before use anyway).
_VISION = {"llava", "minicpm-v", "moondream", "qwen2.5vl", "qwen2vl", "llava-llama-3",
           "llama3.2-vision", "bakllava", "nvakeji", "granite3.2-vision", "glm-4v"}
_EMBED = {"nomic-embed-text", "mxbai-embed-large", "snowflake-arctic-embed",
          "bge-m3", "all-minilm", "jina-embeddings-v2-base-en", "snowflake-arctic-embed2"}
_TOOLS = {"llama3.1", "llama3.2", "qwen2.5", "qwen3", "gemma3", "mistral", "mistral-nemo",
          "mixtral", "command-r", "command-r7b", "deepseek-r1", "phi4", "llama3",
          "hermes3", "aya-experience", "granite3.1"}
# MoE / reasoning families worth a heads-up in the UI (slower first token)
_NOTES = {"deepseek-r1": "reasoning model — slow first token, thinky",
          "qwen3": "thinking model — may need /no_think for chat brevity"}


def _base() -> str:
    return str(prefs.get("ollama_base_url") or "").rstrip("/") or "http://localhost:11434"


def _fmt_size(n: int) -> str:
    gb = (n or 0) / 1e9
    return f"{gb:.1f} GB" if gb >= 1 else f"{max(1, round((n or 0) / 1e6))} MB"


def _fmt_params(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    suffix = text[-1:]
    multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(suffix, 1)
    try:
        n = float(text[:-1] if multiplier != 1 else text) * multiplier
    except (ValueError, OverflowError):
        return ""
    if not 0 < n < float("inf"):
        return ""
    if n < 1e9:
        return f"{n / 1e6:g}M"
    return f"{n / 1e9:.1f}B".replace(".0B", "B")


def _key(s: str) -> str:
    """Model row 'llama3.1:latest' → family key 'llama3.1' for lookups."""
    return (s or "").split(":")[0].lower()


def _caps(name: str, info: dict) -> list[str]:
    fam = (info.get("family") or "").lower()
    low = _key(name)
    caps = ["chat"]
    if fam in _VISION or any(v in low for v in _VISION):
        caps.append("vision")
    if fam in _EMBED or "embed" in low or "minilm" in low:
        caps = ["embed"]  # embedding models are not chat models
    if fam in _TOOLS or any(t in low for t in _TOOLS):
        caps.append("tools")
    return caps


def _normalize(raw: dict) -> dict:
    d = raw.get("details") or {}
    name = raw.get("model") or raw.get("name") or ""
    size = int(raw.get("size") or 0)
    fam = (d.get("family") or "").lower()
    caps = _caps(name, d)
    out = {"name": name, "family": fam, "size_bytes": size, "size": _fmt_size(size),
           "parameter_size": _fmt_params(d.get("parameter_size")),
           "quantization": (d.get("quantization_level") or "").strip(),
           "modified_at": str(raw.get("modified_at") or ""),
           "capabilities": caps,
           "note": _NOTES.get(fam, _NOTES.get(_key(name), ""))}
    return out


def live_list(timeout: float = 4.0) -> dict:
    """GET /api/tags once. Never raises: {ok, models?|error?}."""
    try:
        r = httpx.get(f"{_base()}/api/tags", timeout=timeout)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:140]}", "base_url": _base()}
    if r.status_code != 200:
        return {"ok": False, "error": f"http {r.status_code}", "base_url": _base()}
    try:
        models = [_normalize(m) for m in (r.json().get("models") or [])]
    except (ValueError, AttributeError) as e:
        return {"ok": False, "error": f"bad /api/tags payload: {e}", "base_url": _base()}
    return {"ok": True, "models": models, "base_url": _base()}


def sync(force: bool = False) -> dict:
    """Refresh the cached catalog. On failure the previous cache survives."""
    res = live_list()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not res.get("ok"):
        db.log_activity("system", "Ollama sync skipped", res.get("error", "?")[:140], "general", "warn")
        return {"ok": False, "error": res.get("error"), "base_url": res.get("base_url", _base()),
                "synced_at": _last_db_sync()}
    db.run("DELETE FROM ollama_models")
    db.run_many("INSERT OR REPLACE INTO ollama_models "
                "(name,family,size_bytes,param_size,quantization,modified_at,caps_json,synced_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(m["name"], m["family"], m["size_bytes"], m["parameter_size"],
                  m["quantization"], m["modified_at"], json.dumps(m["capabilities"]), now)
                 for m in res["models"]])
    _LAST_SYNC["ts"] = time.time()
    db.audit("ollama.sync", "ollama_models", "", f"{len(res['models'])} model(s) from {res['base_url']}")
    db.log_activity("system", "Ollama models synced", f"{len(res['models'])} model(s)", "general", "success")
    return {"ok": True, "models": len(res["models"]), "synced_at": now,
            "base_url": res["base_url"], "names": [m["name"] for m in res["models"]]}


def _last_db_sync() -> str:
    row = db.qone("SELECT synced_at FROM ollama_models ORDER BY synced_at DESC LIMIT 1")
    return (row or {}).get("synced_at") or ""


def cached() -> list[dict]:
    rows = db.q("SELECT * FROM ollama_models ORDER BY size_bytes DESC, name")
    out = []
    for r in rows:
        caps = db.jload(r["caps_json"], []) or []
        out.append({"name": r["name"], "family": r["family"], "size_bytes": r["size_bytes"],
                    "size": _fmt_size(r["size_bytes"]), "parameter_size": r["param_size"],
                    "quantization": r["quantization"], "capabilities": caps,
                    "modified_at": r["modified_at"], "synced_at": r["synced_at"],
                    "note": _NOTES.get(r["family"], _NOTES.get(_key(r["name"]), ""))})
    return out


def list_models() -> dict:
    """Cache-first catalog for the UI, with a live probe for the status dot."""
    probe = live_list(timeout=1.5)
    return {"reachable": bool(probe.get("ok")), "base_url": _base(),
            "models": cached(), "error": probe.get("error", "")}


def set_default(role: str, name: str) -> dict:
    """Point chat/vision/embed at a synced model. Validates against the catalog."""
    key = {"chat": "ollama_chat_model", "vision": "ollama_vision_model",
           "embed": "ollama_embed_model"}.get(role)
    if not key:
        raise ValueError("role must be chat|vision|embed")
    if not name:
        raise ValueError("model name required")
    known = {m["name"] for m in cached()}
    if not known:  # cache empty — try live before trusting the name
        live = live_list(timeout=2.5)
        if live.get("ok"):
            known = {m["name"] for m in live["models"]}
    if not known:
        raise ValueError("cannot verify the model: Ollama is unreachable and no catalog is "
                         "synced — start Ollama and sync first")
    if name not in known:
        raise ValueError(f"{name} not in your local catalog ({', '.join(sorted(known)[:6])}"
                         f"{'…' if len(known) > 6 else ''}) — I only point at models that exist")
    prefs.set_many({key: name})
    return {"ok": True, "role": role, "model": name}


def status() -> dict:
    cat = cached()
    ts = _last_db_sync()
    stale = bool(ts) and time.time() - _LAST_SYNC["ts"] > max(60, int(prefs.get("ollama_sync_interval_min")) * 60)
    probe = live_list(timeout=1.5)
    return {"reachable": bool(probe.get("ok")), "base_url": _base(),
             "model_count": len(cat), "synced_at": ts,
             "stale": bool(stale and cat), "error": (probe or {}).get("error", ""),
             "chat_model": prefs.get("ollama_chat_model"),
             "vision_model": prefs.get("ollama_vision_model"),
             "embed_model": prefs.get("ollama_embed_model"),
             "auto_sync": bool(prefs.get("ollama_auto_sync"))}


def maybe_auto_sync() -> dict | None:
    """Called from the scheduler loop; self-throttles to the configured interval."""
    if not prefs.get("ollama_auto_sync"):
        return None
    every = max(60, int(prefs.get("ollama_sync_interval_min") or 30) * 60)
    if _LAST_SYNC["ts"] and time.time() - _LAST_SYNC["ts"] < every:
        return None
    return sync()
