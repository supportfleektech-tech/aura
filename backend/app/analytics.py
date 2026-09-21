"""Analytics dashboards (v1.8.0). Read-only aggregates over existing tables.

Every section degrades to empty lists / nulls when there is no data — the
frontend renders honest empty states, never fake zeros presented as insight.
"""
from __future__ import annotations

import re

from . import db

_MOOD = re.compile(r"(\d{1,2})\s*(?:/|out of 10)?")


def _spending() -> dict:
    cur = db.q("SELECT currency, COALESCE(SUM(amount),0) t FROM expenses WHERE user_id=1"
               " AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now') GROUP BY currency")
    last = db.q("SELECT currency, COALESCE(SUM(amount),0) t FROM expenses WHERE user_id=1"
                " AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now','-1 month') GROUP BY currency")
    last_m = {r["currency"]: r["t"] for r in last}
    by_currency = []
    for r in sorted(cur, key=lambda x: -x["t"]):
        m, l = round(r["t"], 2), round(last_m.get(r["currency"], 0) or 0, 2)
        by_currency.append({"currency": r["currency"], "month": m, "last_month": l,
                            "delta_pct": round((m - l) / l * 100) if l else None})
    for code, l in sorted(last_m.items()):
        if code not in {r["currency"] for r in cur}:
            by_currency.append({"currency": code, "month": 0, "last_month": round(l, 2), "delta_pct": -100})
    return {
        "by_currency": by_currency,
        "by_day": db.q("SELECT date(created_at) day, currency, ROUND(SUM(amount),2) total FROM expenses"
                       " WHERE user_id=1 AND date(created_at) >= date('now','-13 days')"
                       " GROUP BY day, currency ORDER BY day"),
        "by_category": db.q("SELECT category, currency, ROUND(SUM(amount),2) total FROM expenses"
                            " WHERE user_id=1 AND date(created_at) >= date('now','-30 days')"
                            " GROUP BY category, currency ORDER BY total DESC LIMIT 12"),
    }


def _tasks() -> dict:
    done_30 = (db.qone("SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status='completed'"
                       " AND date(completed_at) >= date('now','-30 days')") or {}).get("c", 0)
    created_30 = (db.qone("SELECT COUNT(*) c FROM tasks WHERE user_id=1"
                          " AND date(created_at) >= date('now','-30 days')") or {}).get("c", 0)
    overdue = (db.qone("SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status != 'completed'"
                       " AND due_at IS NOT NULL AND date(due_at) < date('now')") or {}).get("c", 0)
    return {
        "done_14d": db.q("SELECT date(completed_at) day, COUNT(*) n FROM tasks WHERE user_id=1"
                         " AND status='completed' AND date(completed_at) >= date('now','-13 days')"
                         " GROUP BY day ORDER BY day"),
        "created_30": created_30, "done_30": done_30,
        "completion_rate": round(min(1.0, done_30 / created_30), 2) if created_30 else None,
        "overdue_now": overdue,
        "by_status": {r["status"]: r["c"] for r in
                      db.q("SELECT status, COUNT(*) c FROM tasks WHERE user_id=1 GROUP BY status")},
    }


def _habits() -> list[dict]:
    return [{"name": h["name"], "streak": h["streak"] or 0, "last_done": h["last_done"] or "",
             "done_today": (h["last_done"] or "")[:10] == db.qone("SELECT date('now') d")["d"]}
            for h in db.q("SELECT name, streak, last_done FROM habits WHERE user_id=1 ORDER BY streak DESC")]


def _sleep() -> dict:
    nights = db.q("SELECT date, hours FROM sleep_logs WHERE user_id=1 ORDER BY date DESC LIMIT 7")
    nights.reverse()
    avg = round(sum(n["hours"] for n in nights) / len(nights), 1) if nights else None
    return {"avg_7d": avg, "nights": nights}


def _mood() -> dict:
    rows = db.q("SELECT date(created_at) day, mood FROM journal WHERE user_id=1"
                " AND date(created_at) >= date('now','-13 days') ORDER BY day")
    by_day: dict[str, list[int]] = {}
    for r in rows:
        m = _MOOD.search(r["mood"] or "")
        if m:
            by_day.setdefault(r["day"], []).append(min(10, int(m.group(1))))
    points = [{"day": d, "score": round(sum(v) / len(v), 1)} for d, v in sorted(by_day.items())]
    allv = [s for v in by_day.values() for s in v]
    return {"avg_14d": round(sum(allv) / len(allv), 1) if allv else None, "points": points}


def _activity() -> dict:
    return {
        "runs_14d": db.q("SELECT date(created_at) day, COUNT(*) n FROM runs"
                         " WHERE date(created_at) >= date('now','-13 days') GROUP BY day ORDER BY day"),
        "messages_14d": db.q("SELECT date(created_at) day, COUNT(*) n FROM messages"
                             " WHERE date(created_at) >= date('now','-13 days') GROUP BY day ORDER BY day"),
    }


def _slope(points: list[float]) -> float | None:
    """Least-squares slope over evenly spaced points. None if <3 points."""
    n = len(points)
    if n < 3:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(points) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, points))
    den = sum((x - mx) ** 2 for x in xs)
    return round(num / den, 3) if den else None


def _forecast() -> dict:
    """Honest projections: null whenever there isn't enough data to project."""
    # spending: trailing 14d daily average -> next 7d (KES + any currency)
    by_day = db.q("SELECT date(created_at) day, currency, ROUND(SUM(amount),2) total FROM expenses"
                  " WHERE user_id=1 AND date(created_at) >= date('now','-13 days')"
                  " GROUP BY day, currency ORDER BY day")
    per_cur: dict[str, list[float]] = {}
    for r in by_day:
        per_cur.setdefault(r["currency"], []).append(float(r["total"] or 0))
    spending_next_7d = None
    if per_cur:
        code = sorted(per_cur, key=lambda c: -sum(per_cur[c]))[0]  # dominant currency
        days = per_cur[code]
        if len(days) >= 3:
            daily = sum(days) / len(days)
            spending_next_7d = {"currency": code, "amount": round(daily * 7, 2),
                                "basis": f"{len(days)}d average"}
    # task velocity: completions/day over 14d -> next 7d
    done = [r["n"] for r in db.q(
        "SELECT date(completed_at) day, COUNT(*) n FROM tasks WHERE user_id=1 AND status='completed'"
        " AND date(completed_at) >= date('now','-13 days') GROUP BY day ORDER BY day")]
    task_velocity = round(sum(done) / 14, 2) if done else None
    # sleep trend: slope of last 7 nights
    nights = db.q("SELECT date, hours FROM sleep_logs WHERE user_id=1 ORDER BY date DESC LIMIT 7")
    nights.reverse()
    sleep_trend = _slope([n["hours"] for n in nights])
    # mood trend: slope of last 14 days
    rows = db.q("SELECT date(created_at) day, mood FROM journal WHERE user_id=1"
                " AND date(created_at) >= date('now','-13 days') ORDER BY day")
    by_day: dict[str, list[int]] = {}
    for r in rows:
        m = _MOOD.search(r["mood"] or "")
        if m:
            by_day.setdefault(r["day"], []).append(min(10, int(m.group(1))))
    pts = [sum(v) / len(v) for _, v in sorted(by_day.items())]
    mood_trend = _slope(pts)
    return {"spending_next_7d": spending_next_7d,
            "task_velocity_per_day": task_velocity,
            "tasks_next_7d": round(task_velocity * 7) if task_velocity is not None else None,
            "sleep_trend": sleep_trend, "mood_trend": mood_trend}


def overview() -> dict:
    return {"spending": _spending(), "tasks": _tasks(), "habits": _habits(),
            "sleep": _sleep(), "mood": _mood(), "activity": _activity(),
            "forecast": _forecast()}
