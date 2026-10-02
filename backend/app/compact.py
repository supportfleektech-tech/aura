"""Rolling session summaries + context windows (v1.6.0 WS3).

Long sessions lose early context. `maybe_compact` rolls everything older than
the context window into `sessions.summary` (LLM when reachable, else an
extractive heuristic that always works offline). `session_context` returns
summary + recent window for chat generation.
"""
from . import db, prefs


def recent_history(sid: str, window: int | None = None) -> list[dict]:
    w = window or prefs.get("chat_context_window")
    rows = db.q("SELECT role, content FROM messages WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?", (sid, max(1, w)))
    return list(reversed(rows))


def session_context(sid: str) -> dict:
    s = db.qone("SELECT summary FROM sessions WHERE id=?", (sid,)) or {}
    return {"summary": s.get("summary") or "", "history": recent_history(sid)}


def maybe_compact(sid: str, force: bool = False) -> dict | None:
    th = prefs.get("chat_compact_after")
    w = prefs.get("chat_context_window")
    ids = [r["id"] for r in db.q("SELECT id FROM messages WHERE session_id=? "
                                 "AND role IN ('user','assistant') ORDER BY id ASC", (sid,))]
    if len(ids) <= (0 if force else th):
        return None
    st = db.qone("SELECT summary, summary_through FROM sessions WHERE id=?", (sid,)) or {}
    through = int(st.get("summary_through") or 0)
    keep_from = ids[-w] if len(ids) > w else ids[0]
    if keep_from <= through:
        return None  # window already covered by the stored summary
    chunk = db.q("SELECT id, role, content, meta_json FROM messages WHERE session_id=? "
                 "AND id>? AND id<? AND role IN ('user','assistant') ORDER BY id ASC",
                 (sid, through, keep_from))
    if not chunk:
        return None
    old = st.get("summary") or ""
    summary = _llm_summary(chunk, old) or _heuristic_summary(chunk, old)
    new_through = max(c["id"] for c in chunk)
    db.run("UPDATE sessions SET summary=?, summary_through=?, "
           "summary_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
           (summary[:2000], new_through, sid))
    return {"summary": summary[:2000], "through": new_through, "chunk": len(chunk)}


def _render(chunk: list[dict], old: str) -> str:
    lines = [f"Prior summary: {old[:800]}"] if old else []
    for c in chunk[-30:]:
        lines.append(f"{c['role']}: {(c['content'] or '')[:500]}")
    return "\n".join(lines)[:6000]


def _llm_summary(chunk: list[dict], old: str) -> str:
    try:
        from .inference import model_router
        # Summarising a conversation is work, so it activates the on-demand
        # local backend just like a turn does.
        model_router.activate_local()
        probe = model_router.probe()
        msgs = [{"role": "system", "content":
                 "Summarize this conversation segment in 2-4 sentences for continuity: "
                 "main topics, decisions, and open threads. Plain text, no preamble."},
                {"role": "user", "content": _render(chunk, old)}]
        if probe["local_lfm"]["online"]:
            out = (model_router.ollama.chat(msgs, purpose="summary") or "").strip()
            if out:
                return out[:1500]
        if probe["cloud"]["configured"]:
            out = (model_router.cloud.chat(msgs, purpose="summary") or "").strip()
            if out:
                return out[:1500]
    except Exception:
        pass
    return ""


def _heuristic_summary(chunk: list[dict], old: str) -> str:
    users = [(c["content"] or "") for c in chunk if c["role"] == "user"]
    n_a = sum(1 for c in chunk if c["role"] == "assistant")
    intents: list[str] = []
    for c in chunk:
        if c["role"] == "assistant":
            it = db.jload(c.get("meta_json"), {}).get("intent", "")
            if it and it not in intents:
                intents.append(it)
    parts = []
    if old:
        parts.append(f"Previously: {old[:600]}")
    if users:
        parts.append(f"Topic: {users[0][:160]}")
    parts.append(f"Turns: {len(users)} user / {n_a} assistant")
    if intents:
        parts.append("Intents: " + ", ".join(intents[:8]))
    if len(users) > 1:
        parts.append(f"Latest: {users[-1][:160]}")
    return "; ".join(parts)[:1500]
