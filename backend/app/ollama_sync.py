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

import copy
import json
import time

import httpx

from . import db, prefs
from .cache import DEFAULT_TTL_S, TTLCache, tuned_ttl

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


def _live_list_uncached(timeout: float = 4.0) -> dict:
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


# The probe is an HTTP GET and `live_list` sits under /api/health, /api/ollama/*
# and the model room, so a short read-through cache removes a network round trip
# per poll. `_FAIL_TTL_S` keeps a *failure* out of the cache almost immediately:
# Ollama restarting has to become visible in seconds, not after a full TTL.
#
# The key is scoped to the base URL. Keying on the constant "tags" would let a
# Settings change of `ollama_base_url` serve the *previous* machine's inventory
# and reachability for up to a full TTL while `status()`'s own `base_url` field
# (read live from prefs) already reported the new one — /api/ollama/models and the
# Model Room row would then describe two different machines in one payload. With
# the base in the key the swap is a plain miss, with no cross-module invalidation
# to keep in sync.
_catalog_cache = TTLCache(max_entries=8, ttl_s=DEFAULT_TTL_S)
_FAIL_TTL_S = 2.0
_TAGS = "tags"


def invalidate_catalog() -> None:
    """Drop the cached probe. Called whenever the catalog is rewritten, so an
    explicit refresh always refreshes.

    Also drops the health probe cache: `Local LFM` and `Model Room` are two rows
    of one /api/health payload fed by two independent caches, and a rewrite that
    only invalidated one of them could leave `Local LFM: online` sitting beside
    `Model Room: degraded` for a full TTL after a successful sync. Imported
    lazily — `health` imports this module, so a top-level import would be
    circular.
    """
    _catalog_cache.clear()
    try:
        from . import health

        health.clear_probes()
    except Exception as e:  # a cache-clearing helper must never be the thing that raises
        db.log_activity("tool", "Probe cache clear failed",
                        f"{type(e).__name__}: {e}"[:140], "general", "warn")


def live_list(timeout: float = 4.0, use_cache: bool = True) -> dict:
    """Cached wrapper around the /api/tags probe.

    `use_cache=False` is the honest path for anything that *verifies* rather
    than displays: `sync()` (an explicit refresh) and `set_default()` (which
    validates a model name against the catalog) both take it, so no validation
    can ever be satisfied by a stale answer.

    The cached value is a deep copy in both directions. `dict(...)` copies only
    the envelope: the `models` list and every model dict inside it are still the
    same objects, so a caller doing `got["models"][0]["name"] = ...` — or simply
    `got["models"].append(...)` — edits the object the next reader is handed.
    Copying deeply on store *and* on read makes the cache unreachable to caller
    mutation, which is the only property the shallow copy pretended to give.

    The TTL comes from Settings (`cache_ttl_s`) and is read per call, not baked
    in, so retuning takes effect without a restart; 0 disables caching.
    """
    if not use_cache:
        return _live_list_uncached(timeout)
    _catalog_cache.set_ttl(tuned_ttl())
    hit_key = f"{_TAGS}:{_base()}"
    hit = _catalog_cache.get(hit_key)
    if hit is not None:
        return copy.deepcopy(hit)
    out = _live_list_uncached(timeout)
    # Store a deep copy: the value handed to a caller must never be reachable
    # from the object a later reader gets back.
    _catalog_cache.set(hit_key, copy.deepcopy(out),
                       ttl_s=_FAIL_TTL_S if not out.get("ok") else None)
    return out


def sync(force: bool = False) -> dict:
    """Refresh the cached catalog. On failure the previous cache survives.

    Bypasses the read-through cache and drops it: a sync exists to re-read
    Ollama, so reading a 30s-stale answer here would stamp a fresh `synced_at`
    onto a catalog nobody re-read — the panel would then claim "synced just now"
    for data that is up to half a minute old.
    """
    invalidate_catalog()
    res = _live_list_uncached()
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


def list_models(refresh: bool = False) -> dict:
    """Catalog for the UI. `refresh=True` re-probes Ollama and updates the cache first."""
    if refresh:
        try:
            sync()  # on failure the previous cache survives, by design
        except Exception:
            pass  # a cache refresh failure must not hide a live answer
    probe = live_list(timeout=1.5)
    return {"reachable": bool(probe.get("ok")), "base_url": _base(),
            "models": cached(), "error": probe.get("error", ""),
            "refreshed": bool(refresh)}


def _select(key: str, role: str, name: str, known: set[str], unreachable: bool = False) -> dict:
    """Apply a validated model choice, or explain why it is not available."""
    if name not in known:
        if not known and unreachable:
            raise ValueError("cannot verify the model: Ollama is unreachable and no catalog is "
                             "synced — start Ollama and sync first")
        raise ValueError(f"{name} not in your local catalog ({', '.join(sorted(known)[:6])}"
                         f"{'…' if len(known) > 6 else ''}) — I only point at models that exist")
    prefs.set_many({key: name})
    return {"ok": True, "role": role, "model": name}


def set_default(role: str, name: str, refresh: bool = False) -> dict:
    """Point chat/vision/embed at a synced model. Validates against the catalog.

    Ollama's own answer is the authority whenever it gives one, and the DB
    catalog is only the fallback. Probing only when the DB catalog was empty was
    the old behaviour and it was wrong in both directions — a model dropped from
    Ollama stayed acceptable for as long as the row survived in SQLite, and a
    freshly pulled model was rejected until a sync ran.

    The probe is read through `_catalog_cache` rather than taken fresh on every
    call, because a settings mutation had no business paying up to 2.5s of
    network on the happy path. The bound this accepts is the cache TTL —
    `cache_ttl_s` (30s default) — and it is safe in one direction only:

    * A *positive* cached verdict (the model is in the list) can only be stale
      in the harmless direction. The model was present up to a TTL ago, so it
      exists now or the caller is about to be refused on its very next use.
    * A *negative* cached verdict is not safe: the cache may predate an
      `ollama pull`, and a freshly pulled model would stay unselectable until
      the entry expired. So a negative verdict is re-probed uncached before it
      is allowed to refuse anything.

    Net effect: acceptance costs no network round trip, and refusal always rests
    on a probe that is seconds old at worst. `refresh=True` skips the cache
    entirely and forces a fresh probe, for an explicit "check the machine now".

    DELIBERATE TRADE, not a guarantee: when Ollama is unreachable and a catalog
    *is* synced, the DB rows are accepted as-is. That answer can be as old as
    the last successful sync — at least `ollama_sync_interval_min` (30 min by
    default), and unbounded when auto-sync is off or syncs keep failing — so a
    model removed while Ollama was down can still be pointed at. Refusing
    instead would make the whole model room unusable during an outage, which is
    a worse failure than a stale acceptance on a path that only ever runs
    offline.
    """
    key = {"chat": "ollama_chat_model", "vision": "ollama_vision_model",
           "embed": "ollama_embed_model"}.get(role)
    if not key:
        raise ValueError("role must be chat|vision|embed")
    if not name:
        raise ValueError("model name required")

    # The synced DB catalog. Only ever a fallback for an answer Ollama declined
    # to give, never a substitute for one it gave.
    db_names = {m["name"] for m in cached()}

    probe = live_list(timeout=2.5, use_cache=not refresh)
    if not probe.get("ok"):
        return _select(key, role, name, db_names, unreachable=True)

    known = {m["name"] for m in probe["models"]}
    if name not in known:
        # Negative verdict: confirm it uncached before refusing, so a model pulled
        # after this entry was cached is still selectable.
        fresh = _live_list_uncached(timeout=2.5)
        if fresh.get("ok"):
            known = {m["name"] for m in fresh["models"]}
        else:
            # Ollama went away between the two reads, so there is no authority left
            # and the synced catalog is all there is.
            return _select(key, role, name, db_names, unreachable=True)
    return _select(key, role, name, known)


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
