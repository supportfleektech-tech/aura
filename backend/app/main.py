"""AURA OS API — FastAPI application entrypoint."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, prefs
from .inference import router as model_router, fetch_openrouter_models, test_cloud
from .limits import RateLimitMiddleware, SecurityHeadersMiddleware
from .guard import OriginGuardMiddleware
from .domain import ROUTERS
from .health import system_status
from .hermes import hermes, start_scheduler_loop, TOOLS, PLUGIN_STATUS
from .memory import memory_engine
from .orchestrator import run_turn
from .backup import (
    run_backup,
    history as backup_history,
    available_files,
    restore_backup,
)
from .seed import seed

app = FastAPI(title="AURA OS API", version=config.APP_VERSION)
# Added before CORS so CORS stays outermost (headers land on 429s too).
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=config.CORS_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outermost since v1.15: cross-site mutations die here, before anything runs.
app.add_middleware(OriginGuardMiddleware)

for r in ROUTERS:
    app.include_router(r, prefix=config.API_PREFIX)


@app.on_event("startup")
def _startup():
    db.init_db()
    seed()
    # The loop is a 30s daemon thread that ticks automations, missions and
    # schedules, runs a real consolidation pass and drains the queue against
    # the live DB. Under test that is fatal to reproducibility: every
    # TestClient(app) __enter__ runs this hook and starts *another* thread, and
    # all test modules share one database, so the thread keeps settling rows
    # other modules still own for the whole run (measured: 3 of 13 full-suite
    # runs failing where the baseline was 6 of 6 green). AURA_DISABLE_SCHEDULER=1
    # keeps it off; tests set it (see tests/test_env.py, which every test run
    # imports) and nothing that serves real traffic does. Read as a set of
    # truthy strings rather than `== "1"`, so an exported `=true` or `=yes`
    # does not silently start the thread and reintroduce the flake.
    if os.environ.get("AURA_DISABLE_SCHEDULER", "").strip().lower() not in (
            "1", "true", "yes", "on"):
        start_scheduler_loop()
    print(
        f"AURA ready · privacy={prefs.get('privacy')} · cloud={model_router.cloud.provider}:{'on' if model_router.cloud.configured() else 'off'} · "
        f"cors={'open' if config.CORS_ORIGINS == ['*'] else config.CORS_ORIGINS} · "
        f"rate_limit={'on' if config.RATE_LIMIT_ENABLED else 'off'}"
    )


# ------------------------------------------------------ settings & cloud ---
@app.get("/api/settings")
def settings_get():
    """Effective settings (values + secret-set flags + per-key sources)."""
    return prefs.public_view()


@app.patch("/api/settings")
def settings_patch(payload: dict):
    """Validate + persist settings. Secrets are write-only (empty clears to env)."""
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(400, "body must be a non-empty object")
    try:
        prefs.set_many(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return prefs.public_view()


@app.delete("/api/settings")
def settings_reset():
    """Clear DB overrides — everything falls back to env/defaults."""
    prefs.reset_all()
    return prefs.public_view()


@app.get("/api/cloud/models")
def cloud_models(refresh: bool = False):
    """OpenRouter model catalog (cached 1h); curated free presets when offline."""
    return fetch_openrouter_models(refresh=refresh)


class CloudTest(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None


@app.post("/api/cloud/test")
def cloud_test(t: CloudTest):
    """Minimal completion through saved config, or candidate overrides (not saved)."""
    if t.provider and t.provider not in ("openrouter", "openai", "custom"):
        raise HTTPException(400, "provider must be openrouter|openai|custom")
    return test_cloud(
        t.provider, (t.model or "").strip() or None, (t.api_key or "").strip() or None
    )


# ----------------------------------------------------------------- meta ---
# Optional-by-design surfaces: degraded on these is an honest off-state, never
# a broken system (no Ollama, no feeds followed, terminal disabled by choice…).
SOFT_SERVICES = {"Local LFM", "Model Room", "Feeds", "Weather", "Terminal"}


@app.get("/api/health")
def health():
    s = system_status()
    all_ok = all(
        x["status"] == "online" for x in s["services"] if x["name"] not in SOFT_SERVICES
    )
    return {"ok": all_ok, **s}


@app.get("/api/system")
def system():
    return system_status()


@app.get("/api/me")
def me():
    u = db.qone("SELECT * FROM users WHERE id=1") or {}
    return {
        "name": u.get("name", config.USER_NAME),
        "role": u.get("role", config.USER_ROLE),
        "location": u.get("location", config.USER_LOCATION),
        "version": config.APP_VERSION,
    }


@app.patch("/api/me")
def update_me(body: dict):
    """Update the single-user identity row (onboarding step 1)."""
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be an object")
    allowed = {"name": 80, "role": 120, "location": 120}
    bad = [k for k in body if k not in allowed]
    if bad:
        raise HTTPException(400, f"unknown fields: {', '.join(bad)}")
    clean = {}
    for k, v in body.items():
        if not isinstance(v, str) or not v.strip():
            raise HTTPException(400, f"{k} must be a non-empty string")
        if len(v.strip()) > allowed[k]:
            raise HTTPException(400, f"{k} must be under {allowed[k]} chars")
        clean[k] = v.strip()
    if not clean:
        raise HTTPException(400, "nothing to update")
    db.run("INSERT INTO users (id) VALUES (1) ON CONFLICT(id) DO NOTHING")
    db.run(
        f"UPDATE users SET {', '.join(f'{k}=?' for k in clean)} WHERE id=1",
        tuple(clean.values()),
    )
    return me()


@app.get("/api/tools")
def tools():
    return {
        "tools": hermes.list_tools(),
        "hermes": hermes.version,
        "plugins": PLUGIN_STATUS,
    }


# ----------------------------------------------------------------- chat ---
class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    domain: str | None = None
    attachments: list[dict] = []


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn):
    if not body.message.strip() and not body.attachments:
        raise HTTPException(400, "message is empty")
    if len(body.message) > config.MAX_MESSAGE_CHARS:
        raise HTTPException(413, f"message exceeds {config.MAX_MESSAGE_CHARS} chars")
    if len(body.attachments) > config.MAX_ATTACHMENTS:
        raise HTTPException(400, f"at most {config.MAX_ATTACHMENTS} attachments")
    shortcut = _maybe_slash(body.message, body.attachments, body.session_id)
    if shortcut is not None:
        return shortcut
    gen = run_turn(body.message.strip(), body.session_id, body.domain, body.attachments)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _one_sse(event: str, data: dict) -> str:
    """A single SSE frame. `default=str` so a handler result can never 500 here."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _maybe_slash(message: str, attachments: list, session_id: str | None) -> StreamingResponse | None:
    """Short-circuit a leading-slash command before the orchestrator runs.

    A command is deterministic: `/task Ship the plan` must create exactly one
    task without spending a model call, so it must not go through `run_turn`.
    Matching happens at position 0 only (see `slash.parse`), so prose that
    merely contains a slash mid-sentence is untouched.

    Attachments disqualify the shortcut — a `/`-prefixed message with an
    attachment is a real turn, and dropping the attachment would lose the file.

    A `done` frame closes the stream even though no turn ran: clients clear
    their in-flight flag on `done`, and a slash reply that never sends one
    leaves the composer stuck on "sending" forever.
    """
    if attachments:
        return None
    from . import slash as _slash
    text = (message or "").strip()
    try:
        if _slash.parse(text)[0] is None:
            return None
        out = _slash.execute(text)
    except Exception as e:  # noqa: BLE001 — a slash must never break the stream
        out = {"handled": True, "ok": False, "command": text.split(" ", 1)[0],
               "result": None, "text": f"{type(e).__name__}: {e}"[:200], "view": None}
    frames = [_one_sse("slash", out), _one_sse("done", {"session_id": session_id or ""})]
    return StreamingResponse(
        iter(frames),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions")
def sessions(q: str = "", limit: int = 30):
    like = f"%{q.strip()}%" if q.strip() else None
    where = "WHERE s.title LIKE ?" if like else ""
    p = (like,) if like else ()
    rows = db.q(
        "SELECT s.id, s.title, s.domain, s.created_at, s.updated_at, s.pinned, s.starred,"
        " (s.summary <> '') has_summary,"
        " (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) n"
        f" FROM sessions s {where} ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?",
        (*p, max(1, min(100, limit))),
    )
    return {"sessions": rows}


@app.get("/api/sessions/{sid}")
def session_detail(sid: str):
    msgs = db.q(
        "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC LIMIT 500", (sid,)
    )
    return {"messages": msgs}


@app.patch("/api/sessions/{sid}")
def patch_session(sid: str, body: dict):
    s = db.qone("SELECT id FROM sessions WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "session not found")
    sets, p = [], []
    if "title" in body:
        t = str(body["title"] or "").strip()
        if not t:
            raise HTTPException(400, "title must not be empty")
        sets.append("title=?")
        p.append(t[:120])
    if "domain" in body:
        sets.append("domain=?")
        p.append(str(body["domain"] or "general")[:40])
    if sets:
        sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        db.run(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", (*p, sid))
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    db.run("DELETE FROM messages WHERE session_id=?", (sid,))
    db.run("DELETE FROM sessions WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/sessions/{sid}/branch")
def branch_session(sid: str, body: dict):
    import uuid

    s = db.qone("SELECT * FROM sessions WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "session not found")
    nid = uuid.uuid4().hex[:12]
    db.run(
        "INSERT INTO sessions (id, user_id, title, domain, summary, summary_through, summary_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            nid,
            1,
            (body.get("title") or (s["title"] + " (branch)"))[:120],
            s["domain"],
            s["summary"],
            s["summary_through"],
            s["summary_at"],
        ),
    )
    db.run(
        "INSERT INTO messages (session_id, role, kind, content, meta_json, created_at)"
        " SELECT ?, role, kind, content, meta_json, created_at FROM messages"
        " WHERE session_id=? ORDER BY id ASC",
        (nid, sid),
    )
    return {"id": nid}


def _toggle_flag(sid: str, col: str, body: dict) -> dict:
    s = db.qone("SELECT * FROM sessions WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "session not found")
    v = body.get(col)
    v = (not s[col]) if v is None else bool(v)
    db.run(
        f"UPDATE sessions SET {col}=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (1 if v else 0, sid),
    )
    return {col: v}


@app.post("/api/sessions/{sid}/pin")
def pin_session(sid: str, body: dict):
    return _toggle_flag(sid, "pinned", body)


@app.post("/api/sessions/{sid}/star")
def star_session(sid: str, body: dict):
    return _toggle_flag(sid, "starred", body)


@app.post("/api/sessions/{sid}/compact")
def compact_session(sid: str):
    if not db.qone("SELECT id FROM sessions WHERE id=?", (sid,)):
        raise HTTPException(404, "session not found")
    from . import compact as _cx

    out = _cx.maybe_compact(sid, force=True)
    return {"compacted": bool(out), **(out or {})}


@app.post("/api/sessions")
def create_session(body: dict):
    import uuid

    sid = uuid.uuid4().hex[:12]
    db.run(
        "INSERT INTO sessions (id, user_id, title, domain) VALUES (?,?,?,?)",
        (sid, 1, body.get("title", "Conversation"), body.get("domain", "general")),
    )
    return {"id": sid}


# ------------------------------------------------------- universal search ---
SEARCH_TYPES = ("task", "project", "client", "journal", "file", "application", "memory")


@app.get("/api/search")
def universal_search(
    q: str,
    domain: str | None = None,
    limit: int = 12,
    type: str | None = None,
    frm: str | None = None,
    to: str | None = None,
):
    from .inference import router

    t0 = time.time()
    out: list[dict] = []
    like = f"%{q}%"
    qq = (q or "").strip()
    when = ""
    params: list = []
    if frm:
        when += " AND datetime(created_at) >= datetime(?)"
        params.append(frm)
    if to:
        when += " AND datetime(created_at) <= datetime(?)"
        params.append(to)
    for table, label, cols in [
        ("tasks", "task", "title, description"),
        ("projects", "project", "name, description"),
        ("clients", "client", "name, org, notes"),
        ("journal", "journal", "title, body"),
        ("files", "file", "name, indexed_text"),
        ("applications", "application", "company, role"),
    ]:
        if type and type != label:
            continue
        try:
            sql = (
                f"SELECT *, '{label}' _t FROM {table} WHERE user_id=1 AND "
                f"({' OR '.join(c + ' LIKE ?' for c in cols.split(', '))}){when} LIMIT 5"
            )
            rows = db.q(sql, tuple([like] * len(cols.split(", "))) + tuple(params))
            for r in rows:
                title = r.get("title") or r.get("name") or r.get("company") or label
                matched_field = (
                    "title"
                    if qq.lower() in (title or "").lower()
                    else (
                        "description"
                        if qq.lower() in (r.get("description") or "").lower()
                        else "text"
                    )
                )
                out.append(
                    {
                        "type": label,
                        "id": r.get("id"),
                        "title": title,
                        "snippet": (
                            r.get("description")
                            or r.get("body")
                            or r.get("notes")
                            or r.get("indexed_text")
                            or ""
                        )[:140],
                        "domain": r.get("domain", ""),
                        "relevance": 0.55,
                        "matched": f"{matched_field} matches “{qq[:40]}”",
                    }
                )
        except Exception:
            continue
    if not type or type == "memory":
        for m in memory_engine.search(q, domain, limit=6, embedder=router.embed_fn()):
            out.append(
                {
                    "type": "memory",
                    "id": m["id"],
                    "title": m["title"],
                    "snippet": m["content"][:140],
                    "domain": m["domain"],
                    "relevance": m.get("relevance", 0.5),
                    "matched": f"semantic memory match (relevance {m.get('relevance', 0.5):.2f})",
                    "meta": {"mtype": m["mtype"], "confidence": m["confidence"]},
                }
            )
    out.sort(key=lambda x: -x.get("relevance", 0))
    ms = int((time.time() - t0) * 1000)
    return {
        "results": out[:limit],
        "ms": ms,
        "pipelines": ["sqlite", "fts5", "vector", "rerank"],
    }


# ------------------------------------------------------------ dashboard ---
@app.get("/api/dashboard")
def dashboard():
    tasks = db.q(
        "SELECT * FROM tasks WHERE user_id=1 AND status NOT IN ('completed','cancelled') ORDER BY due_at IS NULL, due_at LIMIT 8"
    )
    over = db.q(
        "SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status NOT IN ('completed','cancelled') AND due_at IS NOT NULL AND date(due_at) < date('now')"
    )[0]["c"]
    done_week = db.q(
        "SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status='completed' AND datetime(completed_at) > datetime('now','-7 days')"
    )[0]["c"]
    projects = db.q(
        "SELECT p.*, c.name client_name FROM projects p LEFT JOIN clients c ON c.id=p.client_id WHERE p.user_id=1 ORDER BY p.updated_at DESC LIMIT 6"
    )
    clients = db.q("SELECT * FROM clients WHERE user_id=1 LIMIT 6")
    recent_activity = db.q(
        "SELECT * FROM activity WHERE user_id=1 ORDER BY id DESC LIMIT 8"
    )
    notes = db.q("SELECT * FROM notifications WHERE user_id=1 ORDER BY id DESC LIMIT 6")
    unread = (
        db.qone("SELECT COUNT(*) c FROM notifications WHERE user_id=1 AND read=0") or {}
    ).get("c", 0)
    mem = memory_engine.stats()
    gateway = db.q("SELECT platform,status,account FROM integrations WHERE user_id=1")
    approvals = db.q(
        "SELECT COUNT(*) c FROM approvals WHERE user_id=1 AND status='pending'"
    )[0]["c"]
    expenses = db.q("SELECT amount FROM expenses WHERE user_id=1 AND currency='KES'")
    blocks = db.q(
        "SELECT * FROM timeblocks WHERE user_id=1 AND date(starts_at)=date('now') ORDER BY starts_at"
    )
    journal = db.q("SELECT mood FROM journal WHERE user_id=1 ORDER BY id DESC LIMIT 6")
    # mood delta from numeric scores in recent entries ("8/10", "grateful 7") — last vs prior mean
    _scores = []
    for _j in journal:
        _m = re.search(r"(\d{1,2})\s*(?:/|out of 10)?", _j.get("mood") or "")
        if _m and 1 <= int(_m.group(1)) <= 10:
            _scores.append(int(_m.group(1)))
    mood_delta = ""
    if len(_scores) >= 2 and sum(_scores[1:]) > 0:
        _prev = sum(_scores[1:]) / len(_scores[1:])
        _pct = round((_scores[0] - _prev) / _prev * 100)
        mood_delta = f"↑ {_pct}%" if _pct >= 0 else f"↓ {abs(_pct)}%"
    # spending momentum: this month vs last month (KES)
    _cur = (
        db.qone(
            "SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE user_id=1 AND currency='KES' AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now')"
        )
        or {}
    ).get("s") or 0
    _last = (
        db.qone(
            "SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE user_id=1 AND currency='KES' AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now','-1 month')"
        )
        or {}
    ).get("s") or 0
    spending_state, spending_dir = "On track", "flat"
    if _last > 0 and _cur > _last:
        spending_state, spending_dir = (
            f"↑ {round((_cur - _last) / _last * 100)}% vs last mo",
            "up",
        )
    elif _last > 0 and _cur < _last:
        spending_state, spending_dir = (
            f"↓ {round((_last - _cur) / _last * 100)}% vs last mo",
            "down",
        )
    spending_other = (
        db.qone("SELECT COUNT(*) c FROM expenses WHERE user_id=1 AND currency!='KES'")
        or {}
    ).get("c", 0)
    _sl = (
        db.qone("SELECT hours FROM sleep_logs WHERE user_id=1 ORDER BY id DESC LIMIT 1")
        or {}
    )
    _hrs = _sl.get("hours")
    _sleep = f"{float(_hrs):.1f}h" if _hrs is not None else ""
    _sleep_state = (
        ""
        if _hrs is None
        else ("Good" if float(_hrs) >= 7 else ("Okay" if float(_hrs) >= 6 else "Low"))
    )
    return {
        "priorities": tasks[:5],
        "counts": {
            "overdue": over,
            "done_week": done_week,
            "memories": mem["total"],
            "unread": unread,
            "pending_approvals": approvals,
            "spending": sum(float(e["amount"]) for e in expenses),
        },
        "projects": projects,
        "clients": clients,
        "activity": recent_activity,
        "notifications": notes,
        "gateway": gateway,
        "timeblocks": blocks,
        "insights": {
            "sleep": _sleep,
            "sleep_state": _sleep_state,
            "mood": (journal[0]["mood"] if journal else "") or "—",
            "mood_delta": mood_delta,
            "spending_state": spending_state,
            "spending_dir": spending_dir,
            "spending_other": str(spending_other),
        },
        "memory_by_domain": mem["by_domain"],
    }


# ----------------------------------------------------------------- files ---
@app.post("/api/files/upload")
async def upload_files(
    request: Request, files: list[UploadFile] = File(...), domain: str = Form("general")
):
    try:
        total = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        total = 0
    if total > config.MAX_REQUEST_MB * 1024 * 1024:
        raise HTTPException(413, f"request exceeds {config.MAX_REQUEST_MB} MB")
    cap = config.MAX_UPLOAD_MB * 1024 * 1024
    saved = []
    for f in files:
        data = await f.read(cap + 1)
        if len(data) > cap:
            raise HTTPException(
                413, f"{f.filename or 'file'} exceeds {config.MAX_UPLOAD_MB} MB"
            )
        safe = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in (f.filename or "upload")
        )[:80]
        dest = config.UPLOAD_DIR / f"{int(time.time() * 1000)}_{safe}"
        dest.write_bytes(data)
        from .extract import extract_text

        ex = extract_text(data, f.filename or safe, f.content_type or "")
        text = ex.get("text", "")
        fid = db.run(
            "INSERT INTO files (user_id,name,mime,size,path,domain,indexed_text) VALUES (1,?,?,?,?,?,?)",
            (
                f.filename or safe,
                f.content_type or mimetypes.guess_type(safe)[0] or "",
                len(data),
                str(dest),
                domain,
                text,
            ),
        )
        if text.strip():
            memory_engine.store(
                f"File: {f.filename}",
                text[:1500],
                domain,
                "context",
                "file-upload",
                0.8,
                0.55,
            )
        db.log_activity(
            "message",
            f"File uploaded: {f.filename}",
            f"{len(data) / 1024:.1f} KB",
            domain,
        )
        saved.append(
            {
                "id": fid,
                "name": f.filename,
                "size": len(data),
                "indexed_chars": len(text),
                "pages": ex.get("pages") or ex.get("slides") or 0,
                "extract_error": ex.get("error", ""),
            }
        )
    return {"files": saved}


@app.get("/api/files")
def list_files():
    return {
        "files": db.q(
            "SELECT f.id,f.name,f.mime,f.size,f.domain,f.created_at,"
            " (SELECT COUNT(*) FROM vision_results v WHERE v.file_id=f.id) analysis_count"
            " FROM files f WHERE f.user_id=1 ORDER BY f.id DESC LIMIT 100"
        )
    }


class VisionIn(BaseModel):
    question: str = ""


@app.post("/api/files/{fid}/analyze")
def analyze_file_endpoint(fid: int, body: VisionIn):
    from .vision import analyze_file

    res = analyze_file(fid, (body.question or "")[:500])
    if not res.get("ok"):
        raise HTTPException(res.get("status", 503), res["error"])
    try:
        row = db.qone("SELECT name, domain FROM files WHERE id=?", (fid,)) or {}
        memory_engine.store(
            f"Image: {row.get('name', fid)}",
            res["description"][:1500],
            row.get("domain") or "general",
            "context",
            "vision",
            0.8,
            0.55,
        )
    except Exception:
        pass
    return res


@app.get("/api/vision/status")
def vision_status():
    from .inference import router

    try:
        pr = router.probe()
        chain = router.chain()
    except Exception:
        pr, chain = {}, []
    ollama_on = bool((pr.get("local_lfm") or {}).get("online")) and "ollama" in chain
    cloud_on = bool((pr.get("cloud") or {}).get("configured")) and "cloud" in chain
    return {
        "ollama_model": str(prefs.get("ollama_vision_model") or "llava"),
        "ollama_online": ollama_on,
        "cloud_configured": cloud_on,
        "available": bool(prefs.get("vision_enabled")) and (ollama_on or cloud_on),
    }


@app.post("/api/vision/look")
async def vision_look(
    frame: UploadFile = File(...), question: str = Form(""), remember: str = Form("1")
):
    from .vision import analyze_image

    data = await frame.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(400, "empty frame")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "frame too large")
    res = analyze_image(
        data, frame.content_type or "image/jpeg", (question or "")[:500]
    )
    if not res.get("ok"):
        raise HTTPException(503, res["error"])
    detail = res["description"][:160] if remember == "1" else "Analysis completed"
    db.log_activity("message", "Live look", detail, "general")
    if remember == "1":
        try:
            memory_engine.store(
                "Live look",
                res["description"][:1500],
                "general",
                "context",
                "vision",
                0.8,
                0.55,
            )
        except Exception:
            pass
    return res


@app.get("/api/files/{fid}/analyses")
def list_analyses(fid: int):
    return {
        "analyses": db.q(
            "SELECT id, file_id, question, description, model, ms, created_at"
            " FROM vision_results WHERE file_id=? ORDER BY id DESC LIMIT 20",
            (fid,),
        )
    }


@app.get("/api/files/{fid}")
def download_file(fid: int):
    r = db.qone("SELECT * FROM files WHERE id=? AND user_id=1", (fid,))
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(r["path"], filename=r["name"])


# ----------------------------------------------------------------- voice ---
@app.post("/api/voice/log")
def voice_log(body: dict):
    """Browser performs STT/TTS (Web Speech API); server keeps transcript + audit."""
    db.log_activity(
        "message",
        "Voice turn",
        (body.get("transcript") or "")[:160],
        body.get("domain", "general"),
    )
    return {"ok": True}


@app.get("/api/voice/config")
def voice_config():
    from . import voice as voicemod

    engines = voicemod.engines()
    current = engines.get("current", {})
    eng = current.get("engine", "browser")
    return {
        "stt": "browser-web-speech",
        "tts": eng,
        "voices": "system" if eng == "browser" else "server",
        "language": prefs.get("voice_lang"),
        "note": "Voice runs locally in the browser; transcripts sync to AURA memory.",
    }


@app.get("/api/voice/status")
def voice_status():
    from . import voice as voicemod

    return voicemod.status()


@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    from . import voice as voicemod

    data = await audio.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "audio too large")
    if not data:
        raise HTTPException(400, "empty audio")
    try:
        out = voicemod.transcribe_bytes(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    db.log_activity("message", "Server transcription", out["text"][:160], "general")
    return out


@app.get("/api/voice/engines")
def voice_engines():
    from . import voice as voicemod

    return voicemod.engines()


@app.post("/api/voice/speak")
def voice_speak(body: dict):
    from . import voice as voicemod

    try:
        audio, media = voicemod.speak(
            body.get("text", ""),
            body.get("engine"),
            body.get("voice"),
            body.get("emotion"),
            body.get("rate"),
            body.get("pitch"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    db.log_activity("message", "Server TTS", (body.get("text") or "")[:160], "general")
    return Response(content=audio, media_type=media)


@app.get("/api/voice/loop/status")
def voice_loop_status():
    from . import wake as wakemod
    from . import voice as voicemod

    try:
        engines = voicemod.engines()
    except Exception:
        engines = {}
    return {
        "wake_available": wakemod.available(),
        "wake_model": wakemod.MODEL_KEY,
        "wake_enabled": bool(prefs.get("wake_enabled")),
        "whisper": bool(engines.get("stt")),
        "tts": engines.get("tts", {}),
        "ws": "/api/voice/loop",
    }


@app.websocket("/api/voice/loop")
async def voice_loop(ws: WebSocket):
    import asyncio
    from . import wake as wakemod
    from .vloop import LoopSession

    await ws.accept()
    wake_ok = wakemod.available()
    cfg = {
        "wake_enabled": wake_ok and bool(prefs.get("wake_enabled")),
        "wake_threshold": float(prefs.get("wake_threshold") or 0.5),
        "vad_energy": float(prefs.get("vad_energy") or 500),
        "followup_ms": int(prefs.get("followup_ms") or 6000),
        "barge_in": bool(prefs.get("barge_in")),
    }
    sess = LoopSession(cfg=cfg)
    await ws.send_json(
        {
            "t": "hello",
            "state": sess.state,
            "wake": cfg["wake_enabled"],
            "tap_to_talk": not cfg["wake_enabled"],
        }
    )
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            evs = []
            if msg.get("bytes") is not None:
                evs = await asyncio.to_thread(sess.feed, msg["bytes"])
            else:
                cmd = (msg.get("text") or "").strip().lower()
                if cmd == "talk":
                    evs = sess.tap_to_talk()
                elif cmd == "played":
                    evs = sess.spoke()
                elif cmd == "stop":
                    break
            for kind, payload in evs:
                if kind == "json":
                    await ws.send_json(payload)
                else:
                    await ws.send_bytes(bytes(payload))
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------- backup ---
@app.post("/api/backup/run")
def backup_run(body: dict):
    return run_backup(body.get("target", "local"))


@app.get("/api/backup/history")
def backup_hist():
    rep = config.LITESTREAM_REPLICA
    return {
        "backups": backup_history(),
        "files": available_files(),
        "litestream": {
            "enabled": bool(rep),
            "replica": (rep.split("@")[-1] if "@" in rep else rep) or None,
        },
    }


@app.post("/api/backup/restore")
def backup_restore(body: dict):
    return restore_backup(body.get("file", ""))


# ------------------------------------------------------- hermes passthru ---
@app.post("/api/hermes/tools/{name}")
def hermes_tool(name: str, body: dict):
    if name not in TOOLS:
        raise HTTPException(404, f"unknown tool {name}")
    if TOOLS[name].risk in ("R2", "R3", "R4"):
        raise HTTPException(403, f"tool {name} requires approval flow")
    return hermes.execute_tool(name, body.get("args", {}), body.get("ctx", {}))


@app.post("/api/hermes/tools/{name}/dry-run")
def hermes_tool_dryrun(name: str, body: dict):
    if name not in TOOLS:
        raise HTTPException(404, f"unknown tool {name}")
    if TOOLS[name].risk in ("R2", "R3", "R4"):
        raise HTTPException(403, f"tool {name} requires approval flow")
    return hermes.execute_dry_run(name, body.get("args", {}), body.get("ctx", {}))


@app.post("/api/hermes/skills/{skill}")
def hermes_skill(skill: str, body: dict):
    return hermes.run_skill(skill, body.get("args", {}), body.get("ctx", {}))


# ------------------------------------------------- ollama model room ---
@app.get("/api/ollama/status")
def ollama_status():
    from . import ollama_sync

    return ollama_sync.status()


@app.post("/api/ollama/sync")
def ollama_sync_now():
    from . import ollama_sync

    r = ollama_sync.sync()
    return r if r.get("ok") else JSONResponse(r, status_code=502)


@app.get("/api/ollama/models")
def ollama_models():
    from . import ollama_sync

    return ollama_sync.list_models()


class OllamaDefault(BaseModel):
    role: str = "chat"
    model: str = ""


@app.post("/api/ollama/default")
def ollama_set_default(b: OllamaDefault):
    from . import ollama_sync

    try:
        return ollama_sync.set_default(b.role, b.model.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------ terminal (v1.14) ---
class TermExec(BaseModel):
    command: str = ""
    machine: str = "local"
    timeout: float | None = None


@app.post("/api/terminal/exec")
def terminal_exec(b: TermExec):
    from . import terminal

    r = terminal.exec_command(b.command, b.machine, source="ui", timeout=b.timeout)
    return r


@app.get("/api/terminal/history")
def terminal_history(limit: int = 50):
    from . import terminal

    return {"runs": terminal.history(limit)}


@app.get("/api/terminal/machines")
def terminal_machines():
    from . import terminal

    return {
        "machines": terminal.machines(),
        "ssh_available": __import__("shutil").which("ssh") is not None,
    }


@app.put("/api/terminal/machines")
def terminal_machines_save(body: dict):
    from . import terminal

    try:
        terminal.save_machines(body.get("machines", []))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "machines": terminal.machines()}


@app.get("/api/terminal/config")
def terminal_config():
    from . import prefs as _p

    return {
        "enabled": bool(_p.get("terminal_enabled")),
        "cwd": str(_p.get("terminal_cwd") or "") or str(Path.home()),
        "timeout_s": _p.get("terminal_timeout_s"),
        "max_out_kb": _p.get("terminal_max_out_kb"),
        "allow_dangerous": bool(_p.get("terminal_allow_dangerous")),
    }


@app.patch("/api/terminal/config")
def terminal_config_patch(body: dict):
    from . import terminal

    out = {}
    if "cwd" in body:
        try:
            out["cwd"] = terminal.set_cwd(str(body["cwd"]))
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, **out}


# ------------------------------------------------------------ feeds (v1.14) ---
@app.get("/api/feeds")
def feeds_list():
    from . import feeds

    return {"feeds": feeds.list_feeds(), "items": feeds.recent_items(40)}


class FeedAdd(BaseModel):
    url: str


@app.post("/api/feeds")
def feeds_add(b: FeedAdd):
    from . import feeds

    try:
        return feeds.add(b.url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/feeds/{fid}")
def feeds_delete(fid: int):
    from . import feeds

    if not feeds.remove(fid):
        raise HTTPException(404, "feed not found")
    return {"ok": True}


@app.post("/api/feeds/refresh")
def feeds_refresh():
    from . import feeds

    if db.DRY_RUN:
        raise HTTPException(409, "dry-run")
    return feeds.refresh_all()


@app.post("/api/feeds/items/{iid}/read")
def feeds_item_read(iid: int, body: dict | None = None):
    from . import db as _db

    row = _db.qone("SELECT id FROM feed_items WHERE id=?", (iid,))
    if not row:
        raise HTTPException(404, "item not found")
    _db.run(
        "UPDATE feed_items SET read=? WHERE id=?",
        (1 if (body or {}).get("read", True) else 0, iid),
    )
    return {"ok": True}


# ------------------------------------------------------------ weather (v1.14) ---
@app.get("/api/weather")
def weather_now(refresh: bool = False):
    from . import weather

    return weather.current(force=refresh)


@app.get("/api/terminal/check")
def terminal_check(machine: str = "local", port: int | None = None):
    from . import terminal

    try:
        return terminal.check_machine(machine, port)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------- script library (v1.15) ---
class ScriptIn(BaseModel):
    name: str
    command: str
    machine: str = "local"
    description: str = ""


@app.get("/api/scripts")
def scripts_list():
    from . import scripts as _sc

    return {"scripts": _sc.list_scripts()}


@app.post("/api/scripts")
def scripts_save(b: ScriptIn):
    from . import scripts as _sc

    try:
        return _sc.save(b.name, b.command, b.machine, b.description)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/scripts/{sid}")
def scripts_delete(sid: int):
    from . import scripts as _sc

    if not _sc.remove(sid):
        raise HTTPException(404, "script not found")
    return {"ok": True}


@app.post("/api/scripts/{sid}/run")
def scripts_run(sid: int, body: dict | None = None):
    from . import scripts as _sc

    return _sc.run(sid, source="ui", args=(body or {}).get("args") or None)


# ------------------------------------------------------ folder watch (v1.15) ---
@app.get("/api/watch")
def watch_state():
    from . import watch as _w

    return {
        "enabled": bool(prefs.get("watch_enabled")),
        "ingest": bool(prefs.get("watch_ingest")),
        "paths": _w.paths(),
        "interval_s": int(prefs.get("watch_scan_interval_s") or 120),
        "recent": _w.recent(15),
        "default_dir": str(_w.default_dir()),
    }


class WatchPaths(BaseModel):
    paths: list[str] = []


@app.put("/api/watch/paths")
def watch_paths(b: WatchPaths):
    from . import watch as _w

    try:
        return {"ok": True, "paths": _w.save_paths(b.paths)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/watch/scan")
def watch_scan():
    from . import watch as _w

    if db.DRY_RUN:
        raise HTTPException(409, "dry-run")
    return _w.scan_once(source="manual")


@app.post("/api/watch/reset")
def watch_reset():
    from . import watch as _w

    return {"ok": True, "cleared": _w.reset_state()}


# -------------------------------------------------- voice calls (v1.14) ---
@app.post("/api/voice/calls")
def calls_save(body: dict):
    from . import calls as _calls

    try:
        return _calls.save(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/voice/calls")
def calls_list(limit: int = 20):
    from . import calls as _calls

    return {"calls": _calls.list_calls(limit)}


@app.get("/api/voice/calls/{cid}")
def calls_get(cid: int):
    from . import calls as _calls

    row = _calls.get_call(cid)
    if not row:
        raise HTTPException(404, "call not found")
    return row


@app.delete("/api/voice/calls/{cid}")
def calls_delete(cid: int):
    from . import calls as _calls

    if not _calls.delete_call(cid):
        raise HTTPException(404, "call not found")
    return {"ok": True}


# ------------------------------------------------- frontend (prod build) ---
def _resolve_dist() -> Path | None:
    """Locate the built frontend.

    The layout differs between a source checkout (backend/app/main.py, dist at
    <repo>/frontend/dist) and the container image (/app/app/main.py, dist at
    /app/frontend/dist), so probing both parents is required — a single
    parent.parent.parent assumption silently yields no UI in Docker.
    """
    override = (os.environ.get("AURA_FRONTEND_DIST") or "").strip()
    here = Path(__file__).resolve().parent
    candidates = [Path(override)] if override else []
    candidates += [
        here.parent.parent / "frontend" / "dist",  # source checkout
        here.parent / "frontend" / "dist",        # container image
        Path("/app/frontend/dist"),
    ]
    for c in candidates:
        try:
            if (c / "index.html").is_file():
                return c
        except OSError:
            continue
    return None


DIST = _resolve_dist()
if DIST is not None:
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def _spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        # Never let a crafted path escape the dist directory.
        if not str(f).startswith(str(DIST.resolve())):
            raise HTTPException(404)
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")

else:  # pragma: no cover - only hit in a dev checkout with no build

    @app.get("/")
    def _no_frontend():
        return {
            "detail": "frontend not built — run `npm run build` in frontend/ "
                      "(or set AURA_FRONTEND_DIST)",
        }


def ensure_ready():
    db.init_db()
    seed()


if __name__ == "__main__":
    import uvicorn

    ensure_ready()
    uvicorn.run(
        app, host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 8000))
    )
