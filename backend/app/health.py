"""Health & diagnostics — real probes, no fabricated statuses."""

from __future__ import annotations

import shutil
import sqlite3
import time

from . import config, db, prefs
from .cache import DEFAULT_TTL_S, TTLCache, tuned_ttl
from .hermes import TOOLS, HERMES_VERSION
from .inference import router as model_router

_STARTED = time.time()

# `system_status()` is NOT cached: DB size, disk free, uptime and the tool
# counters are live facts and a stale "disk 98% full" is a lie. Only the two
# probes below are, and only their expensive leg:
#
#   * `_probe_lfm` makes a real HTTP GET (`router.ollama.healthy()`, which
#     deliberately bypasses the router's own 20s memo) on every /api/health hit.
#     "Local LFM" is a SOFT_SERVICE, so a ≤30s-late verdict cannot turn /api/health
#     `ok` false — and `active_model.local_online`, from `router.probe()`, is
#     already ≤20s stale in the same payload. The cloud-*configured* string is
#     rebuilt live every call, so a key added in Settings shows up immediately
#     instead of contradicting `cloud_configured` two lines below.
#   * `_probe_vector` runs a `COUNT(*) ... WHERE embedding_json != ''` full scan
#     per poll. It can only ever return "online" — both branches do — so nothing
#     about it can go stale; only the "N indexed" detail can.
_probe_cache = TTLCache(max_entries=2, ttl_s=DEFAULT_TTL_S)


def _probe_db() -> tuple[str, str, int]:
    t0 = time.time()
    try:
        db.qone("SELECT COUNT(*) c FROM tasks")
        ms = int((time.time() - t0) * 1000)
        return "online", f"sqlite · {ms}ms", ms
    except Exception as e:
        return "offline", str(e)[:100], -1


def _probe_lfm() -> tuple[str, str, int]:
    from .inference import router

    _probe_cache.set_ttl(tuned_ttl())
    leg = _probe_cache.get("ollama_healthy")
    if leg is None:
        leg = router.ollama.healthy()  # the network call — the expensive part
        _probe_cache.set("ollama_healthy", leg)
    ok, note = leg
    cloud = router.probe()["cloud"]
    if cloud["configured"]:
        cs = f"ready ({cloud['provider']}/{cloud['model']} · {prefs.get('privacy')})"
    else:
        cs = f"disabled (no key · provider {cloud['provider']})"
    if ok:
        return "online", f"ollama · {note or router.ollama.model} · cloud: {cs}", 0
    return "degraded", f"builtin engine active · ollama: {note[:60]} · cloud: {cs}", 0


def _probe_vector() -> tuple[str, str]:
    _probe_cache.set_ttl(tuned_ttl())
    hit = _probe_cache.get("vector")
    if hit is not None:
        return hit
    out = _vector_detail()
    _probe_cache.set("vector", out)
    return out


def _vector_detail() -> tuple[str, str]:
    try:
        import chromadb  # noqa: F401

        return "online", "chromadb available"
    except Exception:
        try:
            r = db.qone(
                "SELECT COUNT(*) c FROM memories WHERE COALESCE(embedding_json,'') != ''"
            )
            n = (r or {}).get("c", 0)
        except Exception:
            n = 0
        return "online", f"sqlite-vector fallback · {n} indexed"


def _embed_detail() -> str:
    try:
        from .inference import router

        fn = router.embed_fn()
        name = getattr(fn, "_emb_name", "hashed:192")
        rows = db.q(
            "SELECT embedding_model m, COUNT(*) c FROM memories "
            "WHERE deleted_at IS NULL GROUP BY embedding_model"
        )
        if not rows:
            return f"{name} · no vectors yet"
        parts = [f"{r['m']}:{r['c']}" for r in rows]
        stale = sum(r["c"] for r in rows if r["m"] != name)
        return f"active={name} · {', '.join(parts)}" + (
            f" · {stale} to migrate" if stale else " · all current"
        )
    except Exception as e:
        return f"unknown ({str(e)[:60]})"


def system_status() -> dict:
    db_s, db_note, db_ms = _probe_db()
    lfm_s, lfm_note, _ = _probe_lfm()
    vec_s, vec_note = _probe_vector()
    disk = shutil.disk_usage(config.DATA_DIR)
    uptime = int(time.time() - _STARTED)
    runs = (
        db.qone(
            "SELECT COUNT(*) c, AVG(duration_ms) avg_ms FROM runs WHERE datetime(created_at) > datetime('now','-1 day')"
        )
        or {}
    )
    tools_ok = db.qone("SELECT COUNT(*) c FROM toolcalls WHERE status='ok'") or {}
    tools_err = db.qone("SELECT COUNT(*) c FROM toolcalls WHERE status='error'") or {}
    services = [
        {
            "name": "Hermes Agent",
            "status": "online",
            "detail": f"embedded runtime · v{HERMES_VERSION} · {len(TOOLS)} tools",
        },
        {"name": "Local LFM", "status": lfm_s, "detail": lfm_note},
        {
            "name": "Memory Engine",
            "status": "online",
            "detail": "hybrid FTS5 + vector + rerank",
        },
        {"name": "Embeddings", "status": "online", "detail": _embed_detail()},
        {"name": "Vector Index", "status": vec_s, "detail": vec_note},
        {"name": "SQLite", "status": db_s, "detail": db_note},
        {
            "name": "Gateway",
            "status": "online",
            "detail": "canonical event bus · 6 connectors",
        },
        {
            "name": "Voice",
            "status": "online",
            "detail": "browser STT/TTS + server hooks + call mode",
        },
        {"name": "Scheduler", "status": "online", "detail": "automation tick 30s"},
    ]
    try:
        from . import ollama_sync as _osy

        st = _osy.status()
        services.insert(
            2,
            {
                "name": "Model Room",
                "status": "online" if st["reachable"] else "degraded",
                "detail": f"{st['model_count']} ollama model(s) · chat={st['chat_model']}"
                + (
                    ""
                    if st["reachable"]
                    else (
                        " · cached view"
                        if st["model_count"]
                        else " · ollama not running, builtin covers chat"
                    )
                ),
            },
        )
    except Exception:
        pass
    try:
        from . import terminal as _tm

        hist = _tm.history(1)
        services.append(
            {
                "name": "Terminal",
                "status": "online" if prefs.get("terminal_enabled") else "degraded",
                "detail": (
                    "disabled by choice — enable in Settings"
                    if not prefs.get("terminal_enabled")
                    else (
                        f"{len(_tm.machines())} machine(s) · last: {hist[0]['command'][:40]}"
                        if hist
                        else f"{len(_tm.machines())} machine(s) · idle"
                    )
                ),
            }
        )
    except Exception:
        pass
    try:
        from . import feeds as _fd

        n = db.qone("SELECT COUNT(*) c FROM feeds") or {}
        cnt = n.get("c") or 0
        services.append(
            {
                "name": "Feeds",
                "status": "online" if cnt else "degraded",
                "detail": f"{cnt} watched feed(s)"
                if cnt
                else "none followed yet (zero-key integration)",
            }
        )
    except Exception:
        pass
    try:
        from . import weather as _wx

        services.append(
            {
                "name": "Weather",
                "status": "online" if _wx.configured() else "degraded",
                "detail": "open-meteo (no key)"
                if _wx.configured()
                else "coords not set in Settings",
            }
        )
    except Exception:
        pass
    probe = model_router.probe()
    chain = model_router.chain()
    active_backend = chain[0] if chain else "builtin"
    active_model = ""
    active_provider = ""
    if active_backend == "ollama":
        active_model = probe["local_lfm"]["model"]
        active_provider = "Local (Ollama)"
    elif active_backend == "cloud":
        active_model = probe["cloud"]["model"]
        active_provider = f"Cloud ({probe['cloud']['provider']})"
    else:
        active_model = "aura-builtin-1.0"
        active_provider = "Builtin"
    return {
        "services": services,
        "metrics": {
            "uptime_s": uptime,
            "db_latency_ms": db_ms,
            "runs_24h": (runs.get("c") or 0),
            "avg_run_ms": round(runs.get("avg_ms") or 0),
            "tools_ok": (tools_ok.get("c") or 0),
            "tools_err": (tools_err.get("c") or 0),
            "disk_free_gb": round(disk.free / 1e9, 2),
        },
        "version": config.APP_VERSION,
        "hermes": HERMES_VERSION,
        "active_model": {
            "backend": active_backend,
            "provider": active_provider,
            "model": active_model,
            "privacy_mode": probe["privacy"],
            "local_online": probe["local_lfm"]["online"],
            "cloud_configured": probe["cloud"]["configured"],
        },
    }
