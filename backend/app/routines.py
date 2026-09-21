"""Routine learning — small honest patterns from your own history.

No ML models, no guessing: three cheap aggregates (productive weekday, sleep
drift, top spend category) that feed the morning briefing digest and one
proactive detector. Empty history yields no lines, never filler.
"""
from __future__ import annotations

from . import db

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def routine_lines() -> list[str]:
    """Pattern sentences for briefings. [] when history is too thin."""
    lines = []
    try:
        best = db.qone("SELECT strftime('%w', COALESCE(completed_at, updated_at)) wd, COUNT(*) c FROM tasks "
                       "WHERE user_id=1 AND status='completed' "
                       "AND date(COALESCE(completed_at, updated_at)) > date('now', '-30 days') "
                       "GROUP BY wd ORDER BY c DESC LIMIT 1")
        if best and (best.get("c") or 0) >= 3:
            lines.append(f"Most productive weekday lately: {WEEKDAYS[(int(best['wd']) + 6) % 7]} "
                         f"({best['c']} tasks done in 30d).")
    except Exception:
        pass
    try:
        cur = db.qone("SELECT AVG(hours) a FROM sleep_logs WHERE user_id=1 "
                      "AND date(date) > date('now', '-7 days')") or {}
        prev = db.qone("SELECT AVG(hours) a FROM sleep_logs WHERE user_id=1 "
                       "AND date(date) BETWEEN date('now', '-14 days') AND date('now', '-7 days')") or {}
        a, b = cur.get("a"), prev.get("a")
        if a is not None and b is not None and b > 0:
            drift = round(a - b, 1)
            if abs(drift) >= 0.5:
                direction = "less" if drift < 0 else "more"
                lines.append(f"Sleeping {abs(drift)}h {direction} than the week before "
                             f"({round(a, 1)}h avg).")
    except Exception:
        pass
    try:
        top = db.qone("SELECT category, SUM(amount) s FROM expenses WHERE user_id=1 "
                      "AND date(created_at) > date('now', '-30 days') "
                      "GROUP BY category ORDER BY s DESC LIMIT 1")
        if top and (top.get("s") or 0) > 0:
            lines.append(f"Top spend category (30d): {top['category'] or 'uncategorized'}.")
    except Exception:
        pass
    return lines


def sleep_drift_hours() -> float | None:
    """Negative when sleeping less than the prior week. None when unknowable."""
    try:
        cur = db.qone("SELECT AVG(hours) a, COUNT(*) c FROM sleep_logs WHERE user_id=1 "
                      "AND date(date) > date('now', '-7 days')") or {}
        prev = db.qone("SELECT AVG(hours) a, COUNT(*) c FROM sleep_logs WHERE user_id=1 "
                       "AND date(date) BETWEEN date('now', '-14 days') AND date('now', '-7 days')") or {}
        if (cur.get("c") or 0) < 2 or (prev.get("c") or 0) < 2:
            return None
        a, b = cur.get("a"), prev.get("a")
        if a is None or b is None:
            return None
        return round(a - b, 1)
    except Exception:
        return None
