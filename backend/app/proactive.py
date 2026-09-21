"""AURA proactive intelligence — opportunity detector + ranked delivery (§51).

Deterministic detectors scan structured state (tasks, clients, projects,
events, mail, expenses, backups) and emit opportunities with compact
because-reasons (§54). Ranking follows the plan:

    score = importance × urgency × confidence × preference × (1 − 0.5 × disruption)

Only items at/above the `proactive_threshold` setting are delivered, types in
`proactive_muted` are suppressed, and notifications re-fire at most every 20h
per opportunity (never spam).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from . import db

TYPES = ("missed_followup", "deadline_risk", "stale_client", "overloaded_week",
         "conflicting_events", "repeated_manual", "missing_backup", "expense_anomaly",
         "routine_drift", "routine_mission")
NOTIFY_COOLDOWN_H = 20


def _today() -> str:
    try:
        from . import prefs as _p
        return datetime.now(_p.user_tz()).date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()


def _score(i: float, u: float, c: float, d: float, muted: bool) -> float:
    if muted:
        return 0.0
    return round(i * u * c * (1 - 0.5 * d), 3)


def _muted() -> set[str]:
    try:
        from . import prefs as _p
        return {t.strip() for t in str(_p.get("proactive_muted") or "").split(",") if t.strip()}
    except Exception:
        return set()


def _opp(key: str, typ: str, title: str, reasons: list[str], i: float, u: float,
         c: float, d: float, ref: str = "", action: dict | None = None) -> dict:
    return {"key": key, "type": typ, "title": title, "detail": "; ".join(reasons),
            "reasons": reasons, "importance": i, "urgency": u, "confidence": c,
            "disruption": d, "ref": ref, "action": action or {"kind": "none"},
            "score": _score(i, u, c, d, typ in _muted())}


# ------------------------------------------------------------ detectors ---
def _d_missed_followup(today: str) -> list[dict]:
    out = []
    for t in db.q("SELECT id, title, due_at FROM tasks WHERE user_id=1 AND status != 'completed' "
                  "AND lower(title) LIKE '%follow%up%' AND due_at IS NOT NULL "
                  "AND date(due_at) < date(?) LIMIT 5", (today,)):
        try:
            days = (datetime.fromisoformat(today) - datetime.fromisoformat(t["due_at"][:10])).days
        except Exception:
            days = 1
        out.append(_opp(f"followup-task-{t['id']}", "missed_followup",
                        f"Missed follow-up: {t['title']}",
                        [f"due {t['due_at'][:10]} ({days}d overdue)", "follow-ups rot fast — send it today"],
                        0.8, 0.9 if days >= 3 else 0.7, 0.9, 0.2, f"task:{t['id']}",
                        {"kind": "open", "view": "inbox", "label": "Review task"}))
    for m in db.q("SELECT id, sender, subject, created_at FROM emails WHERE user_id=1 "
                  "AND triage='waiting' AND datetime(created_at) < datetime('now','-3 days') LIMIT 5"):
        who = (m["sender"] or "there").split("<")[0].strip() or "there"
        out.append(_opp(f"waiting-mail-{m['id']}", "missed_followup",
                        f"Waiting on: {(m['sender'] or '')[:40]} — {(m['subject'] or '')[:50]}",
                        ["marked waiting over 3 days ago", "nudge them or move it to done"],
                        0.75, 0.6, 0.85, 0.2, f"mail:{m['id']}",
                        {"kind": "draft", "label": "Draft nudge",
                         "text": f"Hi {who} — just following up on “{(m['subject'] or '').strip()}”. "
                                 "Do you have an update on your side?"}))
    return out


def _d_deadline_risk(today: str) -> list[dict]:
    out = []
    rows = db.q("SELECT id, title, due_at, priority FROM tasks WHERE user_id=1 "
                "AND status != 'completed' AND due_at IS NOT NULL "
                "AND date(due_at) BETWEEN date(?) AND date(?, '+2 days') "
                "ORDER BY due_at LIMIT 8", (today, today))
    for t in rows:
        try:
            hrs = (datetime.fromisoformat(t["due_at"]) - datetime.now()).total_seconds() / 3600
        except Exception:
            hrs = 48.0
        u = 0.95 if hrs < 12 else (0.85 if hrs < 24 else 0.7)
        out.append(_opp(f"due-{t['id']}", "deadline_risk",
                        f"Due soon: {t['title']}",
                        [f"due {str(t['due_at'])[:16]}",
                         f"{t.get('priority') or 'medium'} priority"],
                        0.85, u, 0.95, 0.15, f"task:{t['id']}",
                        {"kind": "open", "view": "inbox", "label": "Review tasks"}))
    return out


def _d_stale_client(today: str) -> list[dict]:
    out = []
    for c in db.q("SELECT id, name, created_at FROM clients WHERE user_id=1 LIMIT 50"):
        rel = db.qone("SELECT MAX(updated_at) m FROM ("
                      "SELECT updated_at FROM tasks WHERE user_id=1 AND client_id=? "
                      "UNION ALL SELECT updated_at FROM projects WHERE user_id=1 AND client_id=?)",
                      (c["id"], c["id"])) or {}
        touch = rel.get("m") or c["created_at"]
        try:
            age = (datetime.fromisoformat(today) - datetime.fromisoformat(str(c["created_at"])[:10])).days
            idle = (datetime.fromisoformat(today) - datetime.fromisoformat(str(touch)[:10])).days
        except Exception:
            continue
        if age > 14 and idle > 14:
            out.append(_opp(f"stale-client-{c['id']}", "stale_client",
                            f"Stale relationship: {c['name']}",
                            [f"no linked activity in {idle} days", "send a check-in to stay warm"],
                            0.6, 0.4, 0.7, 0.15, f"client:{c['id']}",
                            {"kind": "create_task", "label": "Add check-in task",
                             "title": f"Check in with {c['name']}", "client_id": c["id"],
                             "priority": "medium"}))
    return out[:5]


def _d_overloaded_week(today: str) -> list[dict]:
    due = db.qone("SELECT COUNT(*) c FROM tasks WHERE user_id=1 AND status != 'completed' "
                  "AND due_at IS NOT NULL AND date(due_at) BETWEEN date(?) AND date(?, '+7 days')",
                  (today, today)) or {}
    ev = db.qone("SELECT COUNT(*) c FROM events WHERE user_id=1 "
                 "AND date(starts_at) BETWEEN date(?) AND date(?, '+7 days')",
                 (today, today)) or {}
    total = (due.get("c", 0) or 0) + (ev.get("c", 0) or 0)
    if total >= 12:
        return [_opp("busy-week", "overloaded_week", f"Overloaded week: {total} commitments",
                     [f"{due.get('c', 0)} tasks due in 7 days", f"{ev.get('c', 0)} events in 7 days",
                      "say “plan my day” to spread the load"],
                     0.7, 0.6, 0.8, 0.1, "",
                     {"kind": "chat", "label": "Plan my day", "text": "plan my day"})]
    return []


def _d_conflicting_events(today: str) -> list[dict]:
    evs = db.q("SELECT id, title, starts_at, ends_at FROM events WHERE user_id=1 "
               "AND date(starts_at) BETWEEN date(?) AND date(?, '+14 days') "
               "ORDER BY starts_at LIMIT 60", (today, today))
    out = []

    def _p(x: str) -> datetime | None:
        try:
            return datetime.fromisoformat(x)
        except Exception:
            return None
    parsed = [(e, _p(e["starts_at"]), _p(e["ends_at"])) for e in evs]
    for i, (a, s1, e1) in enumerate(parsed):
        if not s1 or not e1:
            continue
        for b, s2, e2 in parsed[i + 1:]:
            if not s2 or not e2 or s2 >= e1:
                break
            if s1 < e2 and s2 < e1:
                out.append(_opp(f"clash-{a['id']}-{b['id']}", "conflicting_events",
                                f"Double-booked: {a['title']} × {b['title']}",
                                [f"{a['starts_at'][:16]} overlaps {b['starts_at'][:16]}",
                                 "move one before the day arrives"],
                                0.75, 0.8, 0.95, 0.15, f"event:{a['id']}",
                                {"kind": "open", "view": "calendar", "label": "Resolve clash"}))
                if len(out) >= 3:
                    return out
    return out


def _d_repeated_manual(today: str) -> list[dict]:
    rows = db.q("SELECT lower(trim(title)) t, COUNT(*) c, MAX(id) mid FROM tasks "
                "WHERE user_id=1 AND datetime(created_at) > datetime('now','-30 days') "
                "AND (recurrence IS NULL OR recurrence='') AND ai_generated=0 "
                "GROUP BY t HAVING c >= 3 LIMIT 5")
    out = []
    for r in rows:
        norm = re.sub(r"\s+", " ", (r["t"] or "").strip())
        if len(norm) < 4:
            continue
        out.append(_opp(f"repeat-{r['mid']}", "repeated_manual",
                        f"Repeated chore: “{norm[:60]}” × {r['c']}",
                        [f"created manually {r['c']}× in 30 days", "a scheduled mission could own this"],
                        0.5, 0.3, 0.7, 0.1, f"task:{r['mid']}",
                        {"kind": "mission", "label": "Automate as mission",
                         "goal": f"Automate {norm[:80]}",
                         "every": "weekly"}))
    return out


def _d_missing_backup(today: str) -> list[dict]:
    row = db.qone("SELECT MAX(finished_at) m FROM backups WHERE user_id=1 AND status='ok'") or {}
    if not row.get("m"):
        return [_opp("no-backup", "missing_backup", "No successful backup yet",
                     ["backups table is empty", "one click starts your first backup"],
                     0.9, 0.5, 0.95, 0.1, "",
                     {"kind": "run_backup", "label": "Run backup now"})]
    try:
        days = (datetime.fromisoformat(today) - datetime.fromisoformat(str(row["m"])[:10])).days
    except Exception:
        return []
    if days >= 7:
        return [_opp("stale-backup", "missing_backup", f"No backup in {days} days",
                     [f"last ok backup {str(row['m'])[:10]}",
                      "schedule it once and AURA keeps it automatic"],
                     0.9, min(0.5 + 0.05 * days, 0.95), 0.95, 0.1, "",
                     {"kind": "mission", "label": "Automate daily backup",
                      "goal": "Back up my data", "every": "daily"})]
    return []


def _d_expense_anomaly(today: str) -> list[dict]:
    out = []
    for cur in db.q("SELECT DISTINCT currency FROM expenses WHERE user_id=1 LIMIT 5"):
        c = cur["currency"]
        wk = db.qone("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE user_id=1 "
                     "AND currency=? AND date(created_at) > date(?, '-7 days')", (c, today)) or {}
        base = db.qone("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE user_id=1 "
                       "AND currency=? AND date(created_at) BETWEEN date(?, '-28 days') "
                       "AND date(?, '-7 days')", (c, today, today)) or {}
        week, prev = wk.get("s", 0) or 0, (base.get("s", 0) or 0) / 3
        if prev > 0 and week >= 1.5 * prev and week > 0:
            out.append(_opp(f"spend-{c}", "expense_anomaly",
                            f"Spending spike: {c} {week:,.0f} this week",
                            [f"3-week weekly average is {c} {prev:,.0f}",
                             f"{week / prev:.1f}× normal — check Personal → expenses"],
                            0.65, 0.55, 0.75, 0.2, "",
                            {"kind": "open", "view": "personal", "label": "Review spending"}))
    return out


def _d_disk_low(today: str) -> list[dict]:
    """Fortress guard: the disk hosting backups/uploads is running out of room."""
    import shutil
    from . import config as _cfg
    try:
        du = shutil.disk_usage(_cfg.DATA_DIR)
    except OSError:
        return []
    free_gb = du.free / 1e9
    pct = (du.free / du.total) if du.total else 1.0
    if free_gb >= 10 and pct >= 0.08:
        return []
    i = 0.75 if free_gb < 3 else 0.6
    u = 0.9 if free_gb < 2 else 0.6
    return [_opp(f"disk_low:{int(free_gb)}", "disk_low",
                 f"Disk low on the AURA host — {free_gb:.1f} GB free",
                 [f"{free_gb:.1f} GB free of {du.total / 1e9:.0f} GB ({pct:.0%})",
                  "backups, uploads and the SQLite DB live on this volume"],
                 i, u, 0.95, 0.0, action={"kind": "none"})]


def _d_routine_drift(today: str) -> list[dict]:
    from . import routines as _rt
    drift = _rt.sleep_drift_hours()
    if drift is None or drift > -1.0:
        return []
    return [_opp("sleep-drift", "routine_drift",
                 f"Sleep down {abs(drift)}h vs last week",
                 ["7-day average slipped over an hour",
                  "logged in Personal → sleep — check the trend"],
                 0.6, 0.5, 0.8, 0.15, "",
                 {"kind": "open", "view": "personal", "label": "Review sleep"})]


def _d_routine_mission(today: str) -> list[dict]:
    """A mission you've run 3+ times to completion but never scheduled →
    propose turning it into a routine (autonomous skill improvement)."""
    rows = db.q(
        "SELECT m.id, m.goal, COUNT(r.id) c, MAX(r.finished_at) last "
        "FROM missions m JOIN mission_runs r ON r.mission_id=m.id "
        "WHERE m.user_id=1 AND r.status='done' AND (m.next_run_at='' OR m.next_run_at IS NULL) "
        "AND m.status IN ('done','failed','cancelled') "
        "GROUP BY m.id HAVING c >= 3 ORDER BY last DESC LIMIT 5")
    out = []
    for r in rows:
        goal = (r.get("goal") or "").strip()
        if len(goal) < 4:
            continue
        out.append(_opp(f"routine-mission-{r['id']}", "routine_mission",
                        f"Routine candidate: “{goal[:60]}” × {r['c']}",
                        [f"completed successfully {r['c']} times", "schedule it to run on its own"],
                        0.55, 0.35, 0.85, 0.1, f"mission:{r['id']}",
                        {"kind": "schedule_mission", "label": "Make it a routine",
                         "mission_id": r["id"], "every": "daily"}))
    return out


DETECTORS = (_d_missed_followup, _d_deadline_risk, _d_stale_client, _d_overloaded_week,
             _d_conflicting_events, _d_repeated_manual, _d_missing_backup, _d_expense_anomaly,
             _d_routine_drift, _d_routine_mission, _d_disk_low)


# ------------------------------------------------------------------ api ---
def _threshold() -> float:
    try:
        from . import prefs as _p
        return float(_p.get("proactive_threshold"))
    except Exception:
        return 0.35


def _enabled() -> bool:
    try:
        from . import prefs as _p
        return bool(_p.get("proactive_enabled"))
    except Exception:
        return True


def scan(persist: bool = True) -> list[dict]:
    """Run all detectors, upsert fresh rows, return ranked deliverable items."""
    today = _today()
    found: list[dict] = []
    for det in DETECTORS:
        try:
            found.extend(det(today) or [])
        except Exception:
            continue
    if persist:
        for o in found:
            db.run("INSERT INTO opportunities (key, type, title, detail, score, dismissed,"
                   " first_seen, last_seen) VALUES (?,?,?,?,?,0,"
                   " strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                   " ON CONFLICT(key) DO UPDATE SET title=excluded.title, detail=excluded.detail,"
                   " score=excluded.score, last_seen=excluded.last_seen,"
                   " resolved=0, resolved_at=''",
                   (o["key"], o["type"], o["title"], o["detail"], o["score"]))
        seen = {o["key"] for o in found}
        for r in db.q("SELECT key FROM opportunities WHERE resolved=0 AND dismissed=0"
                      " AND (snoozed_until IS NULL OR snoozed_until='' OR datetime(snoozed_until) <= datetime('now'))"):
            if r["key"] not in seen:
                db.run("UPDATE opportunities SET resolved=1,"
                       " resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE key=?", (r["key"],))
    if not _enabled():
        return []
    dismissed = {r["key"] for r in
                 db.q("SELECT key FROM opportunities WHERE dismissed=1")}
    snoozed = {r["key"] for r in
               db.q("SELECT key FROM opportunities WHERE snoozed_until IS NOT NULL AND snoozed_until != ''"
                    " AND datetime(snoozed_until) > datetime('now')")}
    th, muted = _threshold(), _muted()
    ranked = [o for o in found if o["key"] not in dismissed and o["key"] not in snoozed
              and o["type"] not in muted and o["score"] >= th]
    ranked.sort(key=lambda o: -o["score"])
    return ranked


def list_all(include_dismissed: bool = False) -> list[dict]:
    rows = db.q("SELECT * FROM opportunities WHERE resolved=0 ORDER BY score DESC, last_seen DESC LIMIT 100")
    if not include_dismissed:
        rows = [r for r in rows if not r["dismissed"]]
    return rows


def resolved_history(limit: int = 20) -> list[dict]:
    return db.q("SELECT key, type, title, resolved_at FROM opportunities WHERE resolved=1"
                " ORDER BY resolved_at DESC LIMIT ?", (max(1, min(50, limit)),))


def snooze(key: str, hours: float = 24) -> dict:
    row = db.qone("SELECT * FROM opportunities WHERE key=?", (key,))
    if not row:
        raise KeyError("opportunity not found")
    h = min(168, max(1, float(hours or 24)))
    db.run(f"UPDATE opportunities SET snoozed_until=datetime('now','+{h:g} hours') WHERE key=?", (key,))
    return {"key": key, "snoozed_hours": h}


def _resolve(key: str, item: dict) -> None:
    """Mark an opportunity resolved, upserting the row if it isn't persisted yet."""
    db.run("INSERT INTO opportunities (key, type, title, detail, resolved, resolved_at) "
           "VALUES (?,?,?,?,1,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
           "ON CONFLICT(key) DO UPDATE SET resolved=1, "
           "resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
           (key, item.get("type", ""), item.get("title", ""), item.get("detail", "")))


def act(key: str) -> dict:
    """Execute an opportunity's action. Server-side kinds run here; client kinds echo back."""
    found = [o for o in scan(persist=False) if o["key"] == key]
    if not found:
        return {"ok": False, "gone": True, "message": "already resolved"}
    a = found[0].get("action") or {"kind": "none"}
    kind = a.get("kind", "none")
    if kind == "run_backup":
        from .backup import run_backup
        res = run_backup("local")
        db.log_activity("run", "Proactive action: backup", key, "general", "success")
        return {"ok": True, "kind": kind, "result": res}
    if kind == "create_task":
        from .hermes import hermes as _h
        payload = {"title": a.get("title", "Follow up"), "priority": a.get("priority", "medium")}
        if a.get("description"):
            payload["description"] = a["description"]
        if a.get("client_id"):
            payload["client_id"] = a["client_id"]
        r = _h.execute_tool("tasks.create", payload, {"domain": "general"})
        if not r.get("ok"):
            return {"ok": False, "message": r.get("error", "task create failed")}
        db.log_activity("run", f"Proactive action: task #{r['data'].get('id')}", key, "general", "success")
        return {"ok": True, "kind": kind, "task": r["data"]}
    if kind == "mission":
        from . import missions as _ms
        goal = (a.get("goal") or "").strip()
        if not goal:
            return {"ok": False, "message": "no goal for this mission"}
        m = _ms.create_mission(goal, "auto")
        if not m.get("steps"):
            # no template/planner match — fall back to a concrete recurring-task step
            title = re.sub(r"^automate[:\- ]*", "", goal, flags=re.I).strip()[:140] or goal[:140]
            m = _ms.update_steps(m["id"], [{"kind": "tool", "label": "Create recurring task",
                                            "tool": "tasks.create",
                                            "args": {"title": title, "priority": "medium"}}])
        every = (a.get("every") or "").lower()
        if every in _ms.SCHEDULES and every != "off":
            _ms.set_schedule(m["id"], every)
        try:
            m = _ms.set_status(m["id"], "start") or m
        except ValueError:
            pass  # leave as draft — user starts it from the Missions panel
        _resolve(key, found[0])
        db.log_activity("run", f"Proactive action: mission #{m['id']}", key, "general", "success")
        return {"ok": True, "kind": kind, "mission": m}
    if kind == "schedule_mission":
        from . import missions as _ms
        mid = a.get("mission_id")
        every = (a.get("every") or "daily").lower()
        if every not in _ms.SCHEDULES or every == "off":
            every = "daily"
        m = _ms._row(mid) if isinstance(mid, int) else None
        if not m:
            _resolve(key, found[0])  # mission deleted — clear the stale item
            return {"ok": True, "kind": kind, "gone": True, "note": "mission no longer exists"}
        _ms.set_schedule(mid, every)
        _resolve(key, found[0])
        db.log_activity("run", f"Proactive action: scheduled mission #{mid}", key, "general", "success")
        return {"ok": True, "kind": kind, "mission": _ms._row(mid)}
    if kind in ("draft", "open", "chat"):
        return {"ok": True, "kind": kind, "action": a}
    return {"ok": False, "message": "no action for this item"}


def set_dismissed(key: str, dismissed: bool = True) -> dict:
    row = db.qone("SELECT * FROM opportunities WHERE key=?", (key,))
    if not row:
        raise KeyError("opportunity not found")
    if dismissed:
        db.run("UPDATE opportunities SET dismissed=1 WHERE key=?", (key,))
    else:
        db.run("UPDATE opportunities SET dismissed=0, snoozed_until='' WHERE key=?", (key,))
    return {"key": key, "dismissed": bool(dismissed)}


def notify_top(items: list[dict] | None = None) -> dict | None:
    """Notify the top above-threshold item unless cooled down. Returns it or None."""
    items = scan() if items is None else items
    if not items:
        return None
    top = items[0]
    row = db.qone("SELECT last_notified FROM opportunities WHERE key=?", (top["key"],)) or {}
    try:
        last = datetime.fromisoformat(str(row.get("last_notified") or "2000-01-01T00:00:00"))
        if datetime.now() - last < timedelta(hours=NOTIFY_COOLDOWN_H):
            return None
    except Exception:
        pass
    body = " · ".join(top["reasons"][:2])[:220]
    db.notify(f"🔮 {top['title']}", body)
    try:
        from . import push as _push
        _push.send_push(f"🔮 {top['title']}", body, "/")
    except Exception:
        pass
    db.run("UPDATE opportunities SET last_notified=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE key=?",
           (top["key"],))
    db.log_activity("run", "Proactive nudge sent", top["key"], "general", "success")
    return top
