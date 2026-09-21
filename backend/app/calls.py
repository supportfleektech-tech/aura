"""Voice calls — persistence + summaries for the hands-free call mode (v1.14).

The browser (or fortress loop) streams the conversation; when a call ends it
POSTs the transcript here. We store it, count turns, and ask the model router
for a short summary (chatgpt-style "here's what we talked about"). Memory
auto-store policy applies to call transcripts like any other input.
"""
from __future__ import annotations

import re

from . import db, prefs


def _turns(transcript: str) -> int:
    """One turn = one user utterance (what a call screen shows as exchanges)."""
    return len(re.findall(r"^You[:>]", transcript or "", re.M)) or \
        len([l for l in (transcript or "").splitlines() if l.strip()]) // 2


def save(body: dict) -> dict:
    transcript = str(body.get("transcript") or "").strip()[:20000]
    if not transcript:
        raise ValueError("transcript required")
    mode = str(body.get("mode") or "browser")
    if mode not in ("browser", "fortress", "tap"):
        raise ValueError("mode must be browser|fortress|tap")
    started, ended = str(body.get("started_at") or ""), str(body.get("ended_at") or "")
    secs = int(body.get("seconds") or 0)
    if not secs and started and ended:
        try:
            from datetime import datetime
            f = "%Y-%m-%dT%H:%M:%S"
            a = datetime.fromisoformat(started.replace("Z", ""))
            b = datetime.fromisoformat(ended.replace("Z", ""))
            secs = max(0, int((b - a).total_seconds()))
        except (ValueError, TypeError):
            secs = 0
    summary = ""
    model = ""
    if prefs.get("call_summary"):
        from .inference import router as mr
        prompt = ("Summarize this voice call between the user and AURA in 1-2 short "
                  "sentences. Plain text, no markdown, no preamble.\n\n" + transcript[:4000])
        try:
            summary, model = mr.generate([{"role": "user", "content": prompt}], purpose="summary")
            summary = (summary or "").strip()[:600]
        except Exception:
            summary, model = "", ""
    if not summary:  # honest offline fallback — deterministic digest, no model
        lines = [l.strip() for l in transcript.splitlines() if l.strip()][:6]
        summary = "Call with " + str(len(transcript.splitlines())) + " lines; opened: " + \
                  (lines[0][:80] if lines else "—")
        model = model or "digest"
    cid = db.run("INSERT INTO calls (started_at,ended_at,mode,seconds,turns,transcript,summary,model,source) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (started, ended, mode, min(max(secs, 0), 86400), _turns(transcript),
                  transcript, summary, model, str(body.get("source") or "ui")))
    db.log_activity("message", f"Voice call saved ({mode})", f"{secs}s · {summary[:80]}", "general")
    try:  # store in memory so call topics remain searchable
        from .memory import memory_engine
        if prefs.get("memory_auto_store"):
            memory_engine.store(title=f"Voice call · {mode} · {secs}s",
                                content=transcript[:1500], source="voice_call",
                                importance=0.55)
    except Exception:
        pass
    row = db.qone("SELECT * FROM calls WHERE id=?", (cid,)) or {}
    row["transcript"] = (row.get("transcript") or "")[:400] + ("…" if len(row.get("transcript") or "") > 400 else "")
    return {"ok": True, "id": cid, "summary": summary, "model": model, "call": row}


def list_calls(limit: int = 20) -> list[dict]:
    rows = db.q("SELECT id,started_at,ended_at,mode,seconds,turns,summary,model,source "
                "FROM calls ORDER BY id DESC LIMIT ?", (min(max(int(limit or 20), 1), 100),))
    return rows


def get_call(call_id: int) -> dict | None:
    row = db.qone("SELECT * FROM calls WHERE id=?", (call_id,))
    if row:
        row["turns_list"] = [l for l in (row.get("transcript") or "").splitlines() if l.strip()][:400]
    return row


def delete_call(call_id: int) -> bool:
    row = db.qone("SELECT id FROM calls WHERE id=?", (call_id,))
    if not row:
        return False
    db.run("DELETE FROM calls WHERE id=?", (call_id,))
    return True
