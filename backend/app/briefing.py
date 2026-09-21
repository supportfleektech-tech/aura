"""AURA briefings — scheduled LLM digests (morning/evening/weekly/custom).

A briefing gathers a digest (overdue + due-today tasks, today's calendar,
unread mail/notifications, pending approvals), drafts it through the model
chain (cloud/local/builtin), stores the run, and notifies (+push). Scheduling
reuses automations with action_kind="brief".
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import db

NBO = ZoneInfo("Africa/Nairobi")


def _tz():
    try:
        from . import prefs as _p
        return _p.user_tz()
    except Exception:
        return NBO


def _domain_filter() -> tuple[str, list]:
    """SQL clause limiting tasks to onboarding-chosen domains.

    `general` tasks always pass; empty/all selection = no filter."""
    try:
        from . import prefs as _p
        sel = [d for d in ("career", "clients", "personal") if _p.get(f"domain_{d}")]
    except Exception:
        sel = ["career", "clients", "personal"]
    if len(sel) in (0, 3):
        return "", []
    return ("AND (domain='general' OR domain IN (%s)) " % ",".join("?" * len(sel)), sel)
KINDS = ("morning", "evening", "weekly", "custom")

KIND_PROMPTS = {
    "morning": ("Write a punchy morning briefing (<=180 words, markdown). Sections: "
                "Today's focus (top 3 by urgency), Schedule, Watch-outs (overdue, waiting mail, "
                "approvals). End with one line of momentum advice."),
    "evening": ("Write a short evening shutdown review (<=140 words, markdown). Sections: "
                "What got done, Still open, Tomorrow's head-start. End with one wind-down note."),
    "weekly": ("Write a weekly review (<=220 words, markdown). Sections: Wins, Slipped items, "
                "Money & health snapshot if present, Next week's big 3. End with one priority call."),
    "custom": "Summarize the digest below crisply in markdown (<=180 words).",
}


def _today_str(offset: int = 0) -> str:
    return (datetime.now(_tz()) + timedelta(days=offset)).date().isoformat()


def gather_digest() -> dict:
    today = _today_str()
    _df, _dp = _domain_filter()
    overdue = db.q("SELECT id, title, priority, due_at FROM tasks WHERE user_id=1 "
                   "AND status != 'completed' AND due_at IS NOT NULL AND date(due_at) < date(?) "
                   + _df + "ORDER BY due_at LIMIT 8", (today, *_dp))
    due_today = db.q("SELECT id, title, priority FROM tasks WHERE user_id=1 "
                     "AND status != 'completed' AND due_at IS NOT NULL AND date(due_at) = date(?) "
                     + _df + "ORDER BY priority LIMIT 8", (today, *_dp))
    inbox_n = (db.qone("SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status='inbox' " + _df,
                       tuple(_dp)) or {}).get("c", 0)
    notes = db.q("SELECT title, body FROM notifications WHERE user_id=1 AND read=0 "
                 "ORDER BY id DESC LIMIT 5")
    notes_n = (db.qone("SELECT COUNT(*) c FROM notifications WHERE user_id=1 AND read=0") or {}).get("c", 0)
    approvals = db.q("SELECT id, title, risk FROM approvals WHERE user_id=1 AND status='pending' LIMIT 5")
    try:
        from .calendar_sync import todays_events
        events = [{"title": e["title"], "starts_at": e["starts_at"], "location": e["location"]}
                  for e in todays_events().get("events", [])[:8]]
    except Exception:
        events = []
    try:
        from .mailbox import top_unread, unread_count
        mail = {"unread": unread_count(),
                "top": [{"sender": m["sender"], "subject": m["subject"], "triage": m["triage"]}
                        for m in top_unread(5)]}
    except Exception:
        mail = {"unread": 0, "top": []}
    blocks = db.q("SELECT title, starts_at, ends_at FROM timeblocks WHERE user_id=1 "
                  "AND date(starts_at) = date(?) ORDER BY starts_at LIMIT 6", (today,))
    try:
        from . import proactive as _pro
        opps = _pro.scan()[:3]
    except Exception:
        opps = []
    try:
        from . import routines as _rt
        routines = _rt.routine_lines()
    except Exception:
        routines = []
    try:
        from . import weather as _wx
        weather = _wx.brief_line()
    except Exception:
        weather = ""
    try:
        from . import feeds as _fd
        feed_items = [{"title": i["title"], "feed": i.get("feed_title") or ""}
                      for i in _fd.recent_items(5)]
    except Exception:
        feed_items = []
    return {"date": today, "overdue": overdue, "due_today": due_today, "inbox_tasks": inbox_n,
            "events": events, "timeblocks": blocks, "unread_notes": notes_n, "notes": notes,
            "approvals": approvals, "mail": mail, "opportunities": opps, "routines": routines,
            "weather": weather, "feed_items": feed_items}


def _digest_text(d: dict) -> str:
    try:
        _tzn = str(_tz())
    except Exception:
        _tzn = "Africa/Nairobi"
    L = [f"Date: {d['date']} ({_tzn})"]
    L.append(f"Overdue tasks ({len(d['overdue'])}): " +
             (", ".join(f"{t['title']} [{t['priority']}]" for t in d["overdue"]) or "none"))
    L.append(f"Due today ({len(d['due_today'])}): " +
             (", ".join(t["title"] for t in d["due_today"]) or "none"))
    L.append(f"Inbox tasks: {d['inbox_tasks']}")
    L.append(f"Today's events ({len(d['events'])}): " +
             (", ".join(f"{e['title']} @ {e['starts_at'][11:16]}" for e in d["events"]) or "none"))
    L.append(f"Unread notifications: {d['unread_notes']}" +
             (f" — latest: {'; '.join(n['title'] for n in d['notes'][:3])}" if d["notes"] else ""))
    L.append(f"Unread mail: {d['mail']['unread']}" +
             (f" — {'; '.join(m['subject'][:60] for m in d['mail']['top'][:3])}" if d["mail"]["top"] else ""))
    L.append(f"Pending approvals ({len(d['approvals'])}): " +
             (", ".join(a["title"] for a in d["approvals"]) or "none"))
    opps = d.get("opportunities") or []
    L.append(f"Opportunities ({len(opps)}): " +
             ("; ".join(f"{o['title']} (because: {o['reasons'][0]})" if o.get("reasons") else o["title"]
                        for o in opps) or "none"))
    routines = d.get("routines") or []
    if routines:
        L.append("Your patterns: " + " ".join(routines))
    if d.get("weather"):
        L.append(d["weather"])
    feeds = d.get("feed_items") or []
    if feeds:
        L.append(f"Fresh from your feeds ({len(feeds)}): " +
                 "; ".join(f"{f['title'][:70]} [{f['feed'][:20]}]" for f in feeds))
    return "\n".join(L)


def _builtin_compose(kind: str, d: dict) -> str:
    """Deterministic fallback when no neural backend answers."""
    head = {"morning": "☀️ Morning briefing", "evening": "🌙 Evening review",
            "weekly": "📅 Weekly review"}.get(kind, "📌 Briefing")
    L = [f"## {head} — {d['date']}", ""]
    focus = ([f"**{t['title']}** (overdue)" for t in d["overdue"][:3]] +
             [f"**{t['title']}**" for t in d["due_today"][:3]])[:3]
    L.append("**Today's focus:** " + (" · ".join(focus) if focus else "inbox is clear — pick one deep task"))
    if d["events"]:
        L.append("**Schedule:** " + ", ".join(
            f"{e['title']} ({e['starts_at'][11:16]})" for e in d["events"]))
    else:
        L.append("**Schedule:** nothing on the calendar")
    watch = []
    if d["overdue"]:
        watch.append(f"{len(d['overdue'])} overdue tasks")
    if d["mail"]["unread"]:
        watch.append(f"{d['mail']['unread']} unread mail")
    if d["approvals"]:
        watch.append(f"{len(d['approvals'])} approvals waiting")
    if d["unread_notes"]:
        watch.append(f"{d['unread_notes']} unread notifications")
    L.append("**Watch-outs:** " + (", ".join(watch) if watch else "all quiet"))
    opps = d.get("opportunities") or []
    if opps:
        L.append("🔮 **Worth a look:** " + "; ".join(
            f"{o['title']} — {(o.get('reasons') or [''])[0]}" for o in opps[:3]))
    if kind == "morning" and d.get("weather"):
        L.append(f"🌦️ **{d['weather']}**")
    feeds = d.get("feed_items") or []
    if feeds:
        L.append("📰 **From your feeds:** " + "; ".join(
            f"{f['title'][:70]} [{f['feed'][:20]}]" for f in feeds[:4]))
    L.append("")
    L.append("_Drafted by the builtin engine (no cloud/local model answered)._")
    return "\n".join(L)


def compose(kind: str = "morning", extra: str = "") -> tuple[str, str, int]:
    """Returns (text, model_name, ms). Never raises on model failure."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    t0 = time.time()
    d = gather_digest()
    prompt = (KIND_PROMPTS[kind] + (f"\nExtra instruction: {extra.strip()}" if extra.strip() else ""))
    text, model = "", "builtin/digest"
    try:
        from .inference import router
        text, model = router.generate([
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Digest:\n" + _digest_text(d)}],
            purpose="briefing")
    except Exception:
        text, model = "", "builtin/digest"
    if not (text or "").strip():
        text, model = _builtin_compose(kind, d), "builtin/digest"
    return text, model, int((time.time() - t0) * 1000)


# ------------------------------------------------------------------ CRUD ---

def list_briefings() -> list[dict]:
    return db.q("SELECT b.*, (SELECT COUNT(*) FROM briefing_runs r "
                "WHERE r.briefing_id=b.id) runs FROM briefings b WHERE user_id=1 ORDER BY id")


def create_briefing(name: str, kind: str = "morning", prompt: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    bid = db.run("INSERT INTO briefings (user_id,name,kind,prompt) VALUES (1,?,?,?)",
                 (name.strip()[:120] or f"{kind.title()} briefing", kind, prompt.strip()[:2000]))
    return {"id": bid}


def update_briefing(bid: int, patch: dict) -> dict:
    row = db.qone("SELECT * FROM briefings WHERE id=? AND user_id=1", (bid,))
    if not row:
        raise KeyError("briefing not found")
    sets, params = [], []
    for k in ("name", "prompt"):
        if k in patch and isinstance(patch[k], str):
            sets.append(f"{k}=?")
            params.append(patch[k].strip()[:2000])
    if "kind" in patch:
        if patch["kind"] not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        sets.append("kind=?")
        params.append(patch["kind"])
    if "enabled" in patch:
        sets.append("enabled=?")
        params.append(1 if patch["enabled"] else 0)
    if sets:
        db.run(f"UPDATE briefings SET {', '.join(sets)} WHERE id=?", (*params, bid))
    return {"id": bid}


def delete_briefing(bid: int) -> None:
    db.run("DELETE FROM briefing_runs WHERE briefing_id=?", (bid,))
    db.run("DELETE FROM briefings WHERE id=? AND user_id=1", (bid,))


def list_runs(briefing_id: int | None = None, limit: int = 20) -> list[dict]:
    q = ("SELECT r.*, b.name briefing_name FROM briefing_runs r "
         "LEFT JOIN briefings b ON b.id=r.briefing_id WHERE r.user_id=1")
    params: tuple = ()
    if briefing_id:
        q += " AND r.briefing_id=?"
        params = (briefing_id,)
    return db.q(q + " ORDER BY r.id DESC LIMIT ?", (*params, max(1, min(100, limit))))


def run_briefing(briefing_id: int | None = None, kind: str = "morning",
                 extra: str = "") -> dict:
    name = f"{kind.title()} briefing"
    if briefing_id:
        row = db.qone("SELECT * FROM briefings WHERE id=? AND user_id=1", (briefing_id,))
        if not row:
            raise KeyError("briefing not found")
        kind = row["kind"]
        name = row["name"]
        extra = (row["prompt"] + "\n" + extra).strip()
    text, model, ms = compose(kind, extra)
    rid = db.run("INSERT INTO briefing_runs (user_id,briefing_id,kind,output,model,ms)"
                 " VALUES (1,?,?,?,?,?)", (briefing_id, kind, text[:8000], model, ms))
    if briefing_id:
        db.run("UPDATE briefings SET last_run=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
               " last_model=? WHERE id=?", (model, briefing_id))
    preview = text.replace("\n", " ")[:180]
    db.notify(f"📌 {name}", preview)
    try:
        from . import push as _push
        _push.send_push(f"📌 {name}", preview, "/")
    except Exception:
        pass
    db.log_activity("run", f"Briefing: {name}", f"{ms}ms · {model}", "general", "success")
    return {"run_id": rid, "kind": kind, "model": model, "ms": ms, "output": text}
