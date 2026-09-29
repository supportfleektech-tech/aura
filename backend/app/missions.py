"""Goal delegation — multi-step background missions with approval holds.

A mission is a planned Hermes tool chain executed one step per scheduler tick::

    draft →(start)→ running →(R2+ step)→ awaiting →(resolve)→ running → done

R0/R1 steps run unattended; R2+ steps and draft-sends pause for approval
(reusing the approvals table + resolve flow). Every transition notifies.
Full template matches run on start; keyword-fallback plans need one-click
review first (needs_review) — AURA never executes a plan it guessed at.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import db, prefs

SCHEDULES = ("off", "hourly", "daily", "weekly")


def _step(label: str, tool: str, args: dict | None = None) -> dict:
    return {"kind": "tool", "label": label, "tool": tool, "args": args or {},
            "status": "pending", "note": ""}


TEMPLATES: list[tuple[str, list[str], list[dict]]] = [
    ("plan_day", ["plan my day", "sort my day", "daily plan", "plan today"],
     [_step("Find overdue tasks", "tasks.overdue"),
      _step("Rank today's tasks", "tasks.prioritize"),
      _step("Build focus blocks", "schedule.plan_day")]),
    ("inbox_zero", ["inbox zero", "triage mail", "sort my inbox", "clear my inbox", "triage my inbox"],
     [_step("Sync inbox", "email.sync"),
      _step("Triage unread mail", "email.triage"),
      _step("Summarize what's left", "email.unread")]),
    ("followups", ["follow up", "followup", "follow-ups", "chase clients"],
     [_step("Draft follow-ups", "comms.draft_followups"),
      {"kind": "send_drafts", "label": "Send drafts (approval)", "drafts_from": 0,
       "status": "pending", "note": ""}]),
    ("backup_check", ["backup", "back up"],
     [_step("System status", "system.status"),
      _step("Run backup", "system.backup", {"target": "local"})]),
    ("morning_intel", ["brief me", "morning intel", "catch me up", "daily briefing"],
     [_step("Morning briefing", "briefing.now", {"kind": "morning"}),
      _step("Opportunity scan", "proactive.scan"),
      _step("Today's calendar", "calendar.today")]),
    ("weekly_review", ["weekly review", "review my week", "week in review"],
     [_step("Weekly briefing", "briefing.now", {"kind": "weekly"}),
      _step("Next 7 days", "calendar.week"),
      _step("Opportunity scan", "proactive.scan")]),
]

KEYWORD_TOOLS: list[tuple[list[str], str, str, dict]] = [
    (["priorit"], "tasks.prioritize", "Rank tasks", {}),
    (["plan"], "schedule.plan_day", "Build focus blocks", {}),
    (["backup"], "system.backup", "Run backup", {"target": "local"}),
    (["mail", "inbox", "email"], "email.triage", "Triage mail", {}),
    (["brief"], "briefing.now", "Generate briefing", {"kind": "morning"}),
    (["scan", "opportunit"], "proactive.scan", "Opportunity scan", {}),
    (["draft"], "comms.draft_followups", "Draft follow-ups", {}),
    (["calendar", "week"], "calendar.week", "Next 7 days", {}),
    (["status", "health"], "system.status", "System status", {}),
]


def plan_goal(goal: str) -> tuple[list[dict], bool, str]:
    """Returns (steps, needs_review, message). Pure — no DB writes."""
    return plan_goal_auto(goal, planner="auto")[:3]


def _tool_catalog() -> str:
    from .hermes import TOOLS
    lines = []
    for t in TOOLS.values():
        if t.risk in ("R3", "R4"):
            continue  # the planner never drafts destructive/prohibited tools
        lines.append(f"- {t.name} [{t.risk}] — {t.description}")
    return "\n".join(sorted(lines))


PLANNER_SYS = (
    "You draft execution plans for AURA, a personal AI OS. Reply with JSON ONLY: "
    "{\"steps\": [{\"tool\": \"name\", \"args\": {}, \"label\": \"short label\"}]} "
    "using ONLY tools from the catalog below, at most 8 steps, in dependency order. "
    "Prefer read-only (R0) steps before writes (R1). For sending anything, end with "
    "{\"tool\": \"comms.draft_followups\"} and NO send step — approval is added automatically. "
    "If the goal needs none of these tools, reply {\"steps\": []}.\n\nTool catalog:\n")


def plan_goal_llm(goal: str) -> tuple[list[dict], bool, str, str]:
    """LLM-drafted plan. Returns (steps, ok, message, model). Always needs review."""
    from .hermes import TOOLS
    from .inference import router
    try:
        text, model = router.generate(
            [{"role": "system", "content": PLANNER_SYS + _tool_catalog()},
             {"role": "user", "content": (goal or '').strip()[:500]}],
            purpose="planning")
    except Exception as e:  # noqa: BLE001 — planner failure is data
        return [], False, f"AI planner unavailable ({str(e)[:100]}).", ""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0]
    try:
        parsed = json.loads(raw or "")
    except ValueError:
        return [], False, "AI planner returned invalid JSON.", model
    items = parsed.get("steps", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return [], False, "AI planner returned an unusable shape.", model
    steps = []
    for it in items[:8]:
        if not isinstance(it, dict) or it.get("tool") not in TOOLS:
            continue
        if TOOLS[it["tool"]].risk in ("R3", "R4"):
            continue
        args = it.get("args") if isinstance(it.get("args"), dict) else {}
        steps.append(_step(it.get("label") or it["tool"], it["tool"], args))
    if not steps:
        return [], False, "AI planner couldn't draft a valid plan.", model
    return steps, True, f"AI-planned {len(steps)} step(s) ({model}) — review, then start.", model


def plan_goal_auto(goal: str, planner: str = "auto") -> tuple[list[dict], bool, str, str]:
    """Planner chain. Returns (steps, needs_review, message, planner_used)."""
    g = (goal or "").strip()
    if not g:
        return [], True, "Tell me the goal first.", "none"
    if planner not in ("auto", "template", "llm"):
        raise ValueError("planner must be auto|template|llm")

    def _template() -> tuple[list[dict], bool, str, str] | None:
        gl = g.lower()
        for name, kws, steps in TEMPLATES:
            if any(k in gl for k in kws):
                return [dict(s) for s in steps], False, f"Planned '{name}' — {len(steps)} steps.", "template"
        return None

    def _keyword() -> tuple[list[dict], bool, str, str]:
        gl = g.lower()
        found = []
        for kws, tool, label, args in KEYWORD_TOOLS:
            if any(k in gl for k in kws) and all(s.get("tool") != tool for s in found):
                found.append(_step(label, tool, dict(args)))
        if found:
            return found, True, f"Guessed {len(found)} step(s) from keywords — review, then start.", "keyword"
        return [], True, ("No template matches that goal yet. Known goals: plan my day, "
                          "inbox zero, follow up, backup, brief me, weekly review."), "none"

    order = {"auto": ("template", "llm", "keyword"),
             "template": ("template", "keyword"),
             "llm": ("llm", "template", "keyword")}[planner]
    llm_note = ""
    for stage in order:
        if stage == "template":
            hit = _template()
            if hit:
                return hit
        elif stage == "llm":
            steps, ok, msg, _model = plan_goal_llm(g)
            if ok:
                return steps, True, msg, "llm"
            llm_note = msg
        else:
            found = _keyword()
            if found[0]:
                return found
            if llm_note and planner == "llm":
                return [], True, llm_note, "none"
            return found
    return [], True, "No plan.", "none"


# ------------------------------------------------------------------ CRUD --

def _row(mid: int) -> dict | None:
    m = db.qone("SELECT * FROM missions WHERE id=? AND user_id=1", (mid,))
    if m:
        m["steps"] = db.jload(m.get("steps_json"), [])
    return m


def create_mission(goal: str, planner: str = "auto") -> dict:
    steps, review, message, used = plan_goal_auto(goal, planner)
    mid = db.run("INSERT INTO missions (user_id, goal, steps_json, needs_review) VALUES (1,?,?,?)",
                 ((goal or "").strip(), db.jdump(steps), 1 if review else 0))
    return {"id": mid, "goal": (goal or "").strip(), "status": "draft",
            "steps": steps, "needs_review": review, "message": message, "planner": used}


def list_missions(limit: int = 20) -> list[dict]:
    rows = db.q("SELECT * FROM missions WHERE user_id=1 ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["steps"] = db.jload(r.get("steps_json"), [])
    return rows


def update_steps(mid: int, steps: list[dict]) -> dict:
    from .hermes import TOOLS
    clean = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        kind = s.get("kind", "tool")
        if kind == "send_drafts":
            clean.append({"kind": "send_drafts", "label": s.get("label", "Send drafts"),
                          "drafts_from": int(s.get("drafts_from", 0) or 0),
                          "status": "pending", "note": ""})
        elif kind == "tool" and s.get("tool") in TOOLS:
            args = s.get("args") if isinstance(s.get("args"), dict) else {}
            clean.append({"kind": "tool", "label": s.get("label") or s["tool"],
                          "tool": s["tool"], "args": args, "status": "pending", "note": ""})
    if not clean:
        raise ValueError("no valid steps (unknown tools are dropped)")
    db.run("UPDATE missions SET steps_json=?, step_idx=0, needs_review=0, status='draft', "
           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND user_id=1",
           (db.jdump(clean), mid))
    return _row(mid) or {}


def set_status(mid: int, status: str) -> dict | None:
    m = _row(mid)
    if not m:
        return None
    if status == "start":
        if not m["steps"]:
            raise ValueError("mission has no steps — set steps first")
        if m["status"] not in ("draft", "paused"):
            raise ValueError(f"cannot start from {m['status']}")
        db.run("UPDATE missions SET status='running', needs_review=0 WHERE id=?", (mid,))
        _open_run(mid)
        db.notify("Mission started", (m["goal"] or "")[:140], "info")
    elif status in ("pause", "cancel"):
        if m["status"] not in ("running", "awaiting", "paused", "draft"):
            raise ValueError(f"cannot {status} from {m['status']}")
        db.run("UPDATE missions SET status=? WHERE id=?",
               ("paused" if status == "pause" else "cancelled", mid))
    else:
        raise ValueError("status must be start|pause|cancel")
    return _row(mid)


# -------------------------------------------------------------- execute --

def _save(m: dict) -> None:
    db.run("UPDATE missions SET status=?, steps_json=?, step_idx=?, result=?, "
           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
           (m["status"], db.jdump(m["steps"]), m["step_idx"], m.get("result", ""), m["id"]))


def _summarize(data) -> str:
    try:
        s = json.dumps(data)
    except (TypeError, ValueError):
        s = str(data)
    return (s[:300] + "…") if len(s) > 300 else s


def _checkins() -> bool:
    try:
        from . import prefs as _p
        return bool(_p.get("mission_step_checkins"))
    except Exception:
        return False


def _push(title: str, body: str) -> None:
    try:
        from .push import send_push
        send_push(title, body, url="/automations")
    except Exception:
        pass


def _done(m: dict) -> None:
    notes = [f"{s.get('label')}: {s.get('note')}" for s in m["steps"] if s.get("note")]
    m["status"] = "done"
    m["result"] = "; ".join(notes)[:500]
    _save(m)
    _close_run(m["id"], "done", f"{len(m['steps'])} steps done")
    db.notify("Mission complete", f"{m['goal'][:100]} — {len(m['steps'])} steps done.", "success")
    _push("Mission complete", m["goal"][:100])


def _fail(m: dict, err: str) -> None:
    m["status"] = "failed"
    m["result"] = err[:300]
    _save(m)
    _close_run(m["id"], "failed", err[:200])
    db.notify("Mission failed", f"{m['goal'][:100]} — {err[:140]}", "error")
    _push("Mission failed", f"{m['goal'][:100]} — {err[:100]}")


def _advance(m: dict) -> None:
    m["step_idx"] += 1
    if m["step_idx"] >= len(m["steps"]):
        _done(m)
    else:
        _save(m)


def _fire_step(m: dict, step: dict) -> None:
    from .hermes import TOOLS, RISK_PROHIBITED, hermes
    if step.get("kind") == "send_drafts":
        src = m["steps"][step.get("drafts_from", 0)] if m["steps"] else {}
        drafts = ((src.get("data") or {}).get("drafts", [])) if isinstance(src, dict) else []
        drafts = [d for d in drafts if isinstance(d, dict)][:5]
        if not drafts:
            step["status"], step["note"] = "skipped", "no drafts produced — skipped"
            _advance(m)
            return
        aid = db.run("INSERT INTO approvals (user_id, risk, title, detail_json, expires_at) VALUES (1,'R2',?,?,datetime('now',?))",
                     (f"Mission: send {len(drafts)} draft(s)",
                      db.jdump({"mission_id": m["id"], "step_idx": m["step_idx"],
                                "kind": "send_drafts", "drafts": drafts, "channel": "email"}),
                      prefs.get("approval_timeout")))
        step["status"], step["approval_id"] = "awaiting", aid
        m["status"] = "awaiting"
        _save(m)
        db.notify("Mission needs your call", f"{len(drafts)} draft(s) ready to send.", "warn")
        return
    tool = step.get("tool", "")
    if tool not in TOOLS:
        step["status"], step["note"] = "failed", f"unknown tool {tool}"
        _save(m)
        _fail(m, f"unknown tool {tool}")
        return
    risk = TOOLS[tool].risk
    if risk == RISK_PROHIBITED:
        step["status"], step["note"] = "failed", "prohibited by policy"
        _save(m)
        _fail(m, f"{tool} is prohibited by policy")
        return
    if risk not in ("R0", "R1"):
        aid = db.run("INSERT INTO approvals (user_id, risk, title, detail_json, expires_at) VALUES (1,?,?,?,datetime('now',?))",
                     (risk, f"Mission step: {step.get('label')}",
                      db.jdump({"mission_id": m["id"], "step_idx": m["step_idx"],
                                "kind": "tool", "tool": tool, "args": step.get("args", {})}),
                      prefs.get("approval_timeout")))
        step["status"], step["approval_id"] = "awaiting", aid
        m["status"] = "awaiting"
        _save(m)
        db.notify("Mission needs your call", f"{step.get('label')} ({risk}) awaits approval.", "warn")
        return
    step["status"] = "running"
    _save(m)
    try:
        r = hermes.execute_tool(tool, step.get("args") or {}, {"domain": "general", "mission": m["id"]})
    except Exception as e:  # noqa: BLE001 — tool failure fails the mission, loudly
        step["status"], step["note"] = "failed", str(e)[:200]
        _save(m)
        _fail(m, f"{tool}: {e}")
        return
    data = r.get("data")
    step["status"] = "done"
    step["note"] = _summarize(data)
    try:
        step["data"] = json.loads(json.dumps(data)) if data is not None else {}
    except (TypeError, ValueError):
        step["data"] = {}
    if _checkins():
        db.notify("Mission step done", (step.get("label") or "")[:140], "info")
    _advance(m)


def _open_run(mid: int) -> None:
    db.run("INSERT INTO mission_runs (mission_id, status) VALUES (?, 'running')", (mid,))


def _close_run(mid: int, status: str, summary: str) -> None:
    db.run("UPDATE mission_runs SET finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
           "status=?, summary=? WHERE mission_id=? AND finished_at=''",
           (status, summary[:300], mid))


def list_runs(mid: int, limit: int = 10) -> list[dict]:
    return db.q("SELECT * FROM mission_runs WHERE mission_id=? ORDER BY id DESC LIMIT ?",
                (mid, max(1, min(limit, 50))))


def set_schedule(mid: int, every: str) -> dict | None:
    from .hermes import _next_run
    if not _row(mid):
        return None
    every = (every or "").lower()
    if every not in SCHEDULES:
        raise ValueError(f"schedule must be one of {','.join(SCHEDULES)}")
    if every == "off":
        db.run("UPDATE missions SET schedule_json='{}', next_run_at='' WHERE id=?", (mid,))
    else:
        db.run("UPDATE missions SET schedule_json=?, next_run_at=? WHERE id=?",
               (db.jdump({"every": every}), _next_run({"every": every}), mid))
    return _row(mid) or {}


def tick_schedules() -> list[dict]:
    """Launch due scheduled missions. Called by the scheduler loop.

    Only finished missions (done/failed/cancelled) relaunch — drafts still
    need review, paused/running/awaiting are left alone.
    """
    from .hermes import _next_run
    now = datetime.now(timezone.utc).isoformat()
    launched = []
    rows = db.q("SELECT * FROM missions WHERE user_id=1 AND next_run_at != '' AND next_run_at <= ? "
                "AND status IN ('done','failed','cancelled') ORDER BY id LIMIT 5", (now,))
    for m in rows:
        try:
            steps = db.jload(m.get("steps_json"), [])
            sched = db.jload(m.get("schedule_json"), {})
            if not steps or not isinstance(sched, dict) or not sched.get("every"):
                db.run("UPDATE missions SET next_run_at='' WHERE id=?", (m["id"],))
                continue
            for s in steps:
                if isinstance(s, dict):
                    s["status"] = "pending"
                    s.pop("note", None)
                    s.pop("data", None)
            db.run("UPDATE missions SET status='running', steps_json=?, step_idx=0, "
                   "needs_review=0, result='', next_run_at=? WHERE id=?",
                   (db.jdump(steps), _next_run(sched), m["id"]))
            _open_run(m["id"])
            db.notify("Mission started", (m["goal"] or "")[:140], "info")
            launched.append({"id": m["id"], "scheduled": True})
        except Exception as e:  # noqa: BLE001 — one bad schedule must not stall the loop
            db.run("UPDATE missions SET next_run_at='' WHERE id=?", (m["id"],))
            launched.append({"id": m["id"], "error": str(e)[:120]})
    return launched


def tick_missions() -> list[dict]:
    """Execute one step per running mission. Called by the scheduler loop."""
    fired = []
    for m in db.q("SELECT * FROM missions WHERE user_id=1 AND status='running' ORDER BY id LIMIT 5"):
        m["steps"] = db.jload(m.get("steps_json"), [])
        if m["step_idx"] >= len(m["steps"]):
            _done(m)
            fired.append({"id": m["id"], "done": True})
            continue
        try:
            _fire_step(m, m["steps"][m["step_idx"]])
            fired.append({"id": m["id"], "step": m["step_idx"], "status": m["status"]})
        except Exception as e:  # noqa: BLE001 — one bad mission must not stall the loop
            _fail(m, str(e))
            fired.append({"id": m["id"], "error": str(e)[:120]})
    return fired


def resume_from_approval(aid: int, decision: str) -> dict | None:
    """Continue a mission held on approval aid. Returns None if not a mission hold."""
    a = db.qone("SELECT * FROM approvals WHERE id=?", (aid,))
    if not a:
        return None
    detail = db.jload(a.get("detail_json"), {})
    mid = detail.get("mission_id")
    if not mid:
        return None
    m = _row(mid)
    if not m or m["status"] != "awaiting":
        return {"mission_id": mid, "resumed": False}
    idx = int(detail.get("step_idx", m["step_idx"]) or 0)
    step = m["steps"][idx] if 0 <= idx < len(m["steps"]) else None
    if step is None:
        return {"mission_id": mid, "resumed": False}
    if decision != "approved":
        step["status"], step["note"] = "skipped", f"skipped by you ({decision})"
        m["status"] = "running"
        _save(m)
        _advance(m)
        return {"mission_id": mid, "resumed": True, "skipped": True}
    if detail.get("kind") == "send_drafts":
        sent = detail.get("drafts_sent", detail.get("drafts", []))
        step["status"] = "done"
        step["note"] = f"sent {len(sent)} message(s)"
    else:
        from .hermes import hermes
        try:
            r = hermes.execute_tool(detail.get("tool", ""), detail.get("args") or {},
                                    {"domain": "general", "mission": mid})
            step["status"] = "done"
            step["note"] = _summarize(r.get("data"))
        except Exception as e:  # noqa: BLE001 — approved but failed at runtime
            step["status"], step["note"] = "failed", str(e)[:200]
            _save(m)
            _fail(m, f"{detail.get('tool')}: {e}")
            return {"mission_id": mid, "resumed": True, "failed": True}
    m["status"] = "running"
    _save(m)
    _advance(m)
    return {"mission_id": mid, "resumed": True}
