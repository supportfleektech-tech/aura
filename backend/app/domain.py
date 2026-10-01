"""Domain CRUD routers — backward-compatibility shim.

All routers and implementations now live in app.routes.*.
This module re-exports everything so that existing imports
(`from .domain import ROUTERS`, `from .domain import _normalize_status`, etc.)
continue to work without changes.

Hermes tool system references these via _lazy(".domain", "func_name") and
_wrap_model(".domain", "func_name", "ModelName"), so every name must be
accessible from `app.domain`.
"""
from __future__ import annotations

from fastapi import HTTPException

from . import db

# Re-export all routers and the ROUTERS list
from .routes import (  # noqa: F401
    ROUTERS,
    tasks_r, clients_r, projects_r, career_r, personal_r, memory_r, auto_r,
    activity_r, notes_r, approvals_r, gateway_r, push_r,
    brief_r, mail_r, cal_r, sync_r, pro_r, undo_r, cost_r, analytics_r,
    missions_r, home_r, consol_r, board_r, worker_r, slash_r,
)

# Re-export task helpers used by hermes
from .routes.tasks import (  # noqa: F401
    TaskIn, _normalize_status, _normalize_priority, _update_task_impl,
    list_tasks, create_task,
)

# Re-export client helpers
from .routes.clients import (  # noqa: F401
    ClientIn, list_clients, create_client,
)

# Re-export project helpers
from .routes.projects import (  # noqa: F401
    ProjectIn, list_projects, create_project, update_project, add_milestone,
)

# Re-export personal helpers
from .routes.personal import (  # noqa: F401
    ExpenseIn, SleepIn, MoodIn, JournalIn,
    log_mood_impl, log_sleep_impl, add_expense_impl, journal_entry_impl,
)

# Re-export memory helpers
from .routes.memory import store_memory, search_memory  # noqa: F401

# --- Tool implementations referenced by hermes tool registrations ---

def overdue_tasks():
    """Alias hermes expects — the route is `overdue`."""
    from .routes.tasks import overdue
    return overdue()


def prioritize_tasks() -> dict:
    """Rank open tasks by urgency. Returns {tasks: [...]} with a `score` and `why`.

    Scoring is a transparent sum, not a black box: overdue days dominate,
    then explicit priority, then whether the task is attached to a client
    whose health is not "good" (those relationships need attention first).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    rows = db.q(
        "SELECT t.*, c.name client_name, c.health client_health "
        "FROM tasks t LEFT JOIN clients c ON c.id = t.client_id "
        "WHERE t.user_id=1 AND t.status NOT IN ('completed','cancelled') "
        "ORDER BY t.due_at IS NULL, t.due_at LIMIT 50"
    )
    weight = {"high": 30, "medium": 15, "low": 5}
    out = []
    for r in rows:
        score = weight.get((r.get("priority") or "medium").lower(), 15)
        why = []
        due = r.get("due_at")
        if due:
            try:
                due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                days = (now - due_dt).days
                if days >= 0:
                    score += 60 + min(days, 60)
                    why.append(f"{days}d overdue")
                else:
                    score += max(0, 30 + days)
                    why.append(f"due in {-days}d")
            except ValueError:
                pass
        else:
            why.append("no due date")
        health = (r.get("client_health") or "").lower()
        if health and health not in ("good", ""):
            score += 20
            why.append(f"client {health}")
        out.append({**r, "score": score, "why": ", ".join(why) or "open task"})
    out.sort(key=lambda x: (-x["score"], x["id"]))
    return {"tasks": out[:15]}


def draft_followups(_ctx: dict | None = None) -> dict:
    """Draft one follow-up per overdue task. Returns {drafts: [{to, subject, body}]}.

    Drafts are never sent here — the caller routes them through the approval
    gate. Tasks without a reachable client email are skipped rather than
    addressed to a guess, so AURA cannot email the wrong person.
    """
    rows = db.q(
        "SELECT t.*, c.name client_name, c.email client_email, c.org client_org "
        "FROM tasks t LEFT JOIN clients c ON c.id = t.client_id "
        "WHERE t.user_id=1 AND t.status NOT IN ('completed','cancelled') "
        "AND t.due_at IS NOT NULL AND t.due_at < datetime('now') "
        "ORDER BY t.due_at LIMIT 20"
    )
    drafts = []
    for r in rows:
        to = (r.get("client_email") or "").strip()
        if not to:
            continue
        who = r.get("client_name") or to
        subject = f"Following up: {r['title']}"
        body = (
            f"Hi {who},\n\n"
            f"A quick follow-up on “{r['title']}”"
            + (f" for {r['client_org']}" if r.get("client_org") else "")
            + ". It was due "
            + str(r.get("due_at") or "")[:10]
            + ".\n\nCould you let me know where this stands, or suggest a new date?\n\nBest,\nAURA"
        )
        drafts.append({"to": to, "subject": subject, "body": body,
                       "task_id": r["id"], "client_id": r.get("client_id")})
    return {"drafts": drafts[:5], "skipped_no_email": max(0, len(rows) - len(drafts))}


def unread_count() -> dict:
    """Unread email count across configured accounts. Never raises."""
    try:
        from . import mailbox
        n = mailbox.unread_count()
        return {"unread": int(n or 0)}
    except Exception as e:
        return {"unread": 0, "note": f"mail unavailable: {type(e).__name__}"}
