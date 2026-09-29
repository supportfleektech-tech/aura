"""Personal router — journal, mood, sleep, expenses, goals, habits."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

from .. import db

personal_r = APIRouter(prefix="/personal", tags=["personal"])


class ExpenseIn(BaseModel):
    category: str
    amount: float
    currency: str = "KES"
    note: str = ""


class SleepIn(BaseModel):
    hours: float | None = None
    bedtime: str | None = None
    wake_at: str | None = None
    quality: str | None = None
    note: str | None = None

    @validator("hours")
    def _validate_hours(cls, v):
        if v is not None and (v < 0 or v > 24):
            raise ValueError("hours must be between 0 and 24")
        return v


class MoodIn(BaseModel):
    mood: str
    note: str = ""


class JournalIn(BaseModel):
    body: str


def log_mood_impl(m: MoodIn) -> dict:
    """Implementation for personal.log_mood tool."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    mid = db.run(
        "INSERT INTO moods (user_id, mood, note, created_at) VALUES (1, ?, ?, ?)",
        (m.mood, m.note or "", now))
    return {"id": mid, "mood": m.mood, "note": m.note, "created_at": now}


def log_sleep_impl(s: SleepIn) -> dict:
    """Implementation for personal.log_sleep tool."""
    from datetime import datetime, timezone, date, timedelta
    now = datetime.now(timezone.utc).isoformat()
    hours = s.hours
    if hours is None and s.bedtime and s.wake_at:
        today = date.today()
        def _parse_ampm(val: str) -> datetime:
            for fmt in ("%H:%M", "%I:%M%p", "%I%p"):
                try:
                    return datetime.strptime(f"{today} {val.strip()}", f"%Y-%m-%d {fmt}").replace(second=0, microsecond=0)
                except ValueError:
                    continue
            raise ValueError(f"cannot parse time: {val}")
        bedtime_dt = _parse_ampm(s.bedtime)
        wake_dt = _parse_ampm(s.wake_at)
        if wake_dt <= bedtime_dt:
            wake_dt += timedelta(days=1)
        hours = round((wake_dt - bedtime_dt).total_seconds() / 3600, 1)
    elif hours is None:
        raise ValueError("hours or bedtime+wake_at required")
    sid = db.run(
        "INSERT INTO sleep_logs (user_id, hours, bedtime, wake_at, quality, note, date, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?, date('now'), ?)",
        (hours, s.bedtime, s.wake_at, s.quality, s.note, now))
    return {"id": sid, "hours": hours, "bedtime": s.bedtime, "wake_at": s.wake_at,
            "quality": s.quality, "note": s.note, "date": datetime.now().date().isoformat()}


def add_expense_impl(e: ExpenseIn) -> dict:
    """Implementation for personal.add_expense tool."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    eid = db.run(
        "INSERT INTO expenses (user_id, category, amount, currency, note, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (e.category, e.amount, e.currency, e.note or "", now))
    return {"id": eid, "category": e.category, "amount": e.amount, "currency": e.currency,
            "note": e.note, "created_at": now}


def journal_entry_impl(j: JournalIn) -> dict:
    """Implementation for personal.journal tool."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    jid = db.run(
        "INSERT INTO journal (user_id, body, created_at) VALUES (1, ?, ?)",
        (j.body, now))
    return {"id": jid, "body": j.body, "created_at": now}


def _hermes():
    from ..hermes import hermes
    return hermes


@personal_r.get("/overview")
def personal_overview():
    journal = db.q("SELECT * FROM journal WHERE user_id=1 ORDER BY id DESC LIMIT 10")
    goals = db.q("SELECT * FROM goals WHERE user_id=1 ORDER BY id DESC LIMIT 20")
    expenses = db.q("SELECT * FROM expenses WHERE user_id=1 ORDER BY id DESC LIMIT 60")
    habits = db.q("SELECT * FROM habits WHERE user_id=1")
    sleep = db.q("SELECT * FROM sleep_logs WHERE user_id=1 ORDER BY id DESC LIMIT 7")
    total = sum(float(e["amount"]) for e in expenses if (e.get("currency") or "KES") == "KES")
    return {"journal": journal, "goals": goals, "expenses": expenses, "habits": habits,
            "sleep": sleep, "spending_total": total, "currency": "KES"}


@personal_r.post("/journal")
def add_journal(j: dict):
    return _hermes().execute_tool("personal.journal", j, {"domain": "personal"})["data"]


@personal_r.post("/mood")
def log_mood(m: dict):
    return _hermes().execute_tool("personal.log_mood", m, {"domain": "personal"})["data"]


@personal_r.post("/sleep")
def log_sleep(s: dict):
    r = _hermes().execute_tool("personal.log_sleep", s, {"domain": "personal"})
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "invalid sleep entry"))
    return r["data"]


@personal_r.post("/expenses")
def add_expense(e: dict):
    return _hermes().execute_tool("personal.add_expense", e, {"domain": "personal"})["data"]


@personal_r.post("/goals")
def add_goal(g: dict):
    gid = db.run("INSERT INTO goals (user_id,domain,title,target,progress) VALUES (1,?,?,?,?)",
                 (g.get("domain", "personal"), g.get("title", ""), g.get("target", ""), g.get("progress", 0)))
    return {"id": gid}


@personal_r.patch("/goals/{gid}")
def update_goal(gid: int, patch: dict):
    allowed = {"title", "target", "progress", "status", "domain"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if sets:
        db.run(f"UPDATE goals SET {sets} WHERE id=?", (*[patch[k] for k in patch if k in allowed], gid))
    return {"ok": True}


@personal_r.post("/habits")
def add_habit(h: dict):
    hid = db.run("INSERT INTO habits (user_id,name) VALUES (1,?)", (h.get("name", "Habit"),))
    return {"id": hid}


@personal_r.post("/habits/{hid}/done")
def habit_done(hid: int):
    h = db.qone("SELECT * FROM habits WHERE id=?", (hid,))
    if h:
        db.run("UPDATE habits SET streak=streak+1, last_done=date('now') WHERE id=?", (hid,))
    return {"ok": True}
