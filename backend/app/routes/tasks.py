"""Tasks router — CRUD + overdue."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from .. import db

tasks_r = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskIn(BaseModel):
    title: str
    description: str = ""
    status: str = "inbox"
    priority: str = "medium"
    due_at: str | None = None
    project_id: int | None = None
    client_id: int | None = None
    domain: str = "general"
    tags: list[str] = Field(default_factory=list)
    recurrence: str = ""


def _normalize_status(val: str) -> str:
    """Normalize status values: 'In Progress' -> 'in_progress', 'Completed' -> 'completed'."""
    return val.strip().lower().replace(" ", "_")


def _normalize_priority(val: str) -> str:
    """Normalize priority values: 'HIGH' -> 'high', 'Urgent' -> 'urgent'."""
    return val.strip().lower()


def _update_task_impl(task_id: int = None, id: int = None, **fields) -> dict:
    """Internal task update — used by both HTTP endpoint and tool system."""
    task_id = task_id or id
    if task_id is None:
        raise HTTPException(400, "task id required")
    allowed_fields = {k: v for k, v in fields.items() if k in ("title", "description", "status", "priority", "due_at", "project_id", "client_id", "domain", "tags", "recurrence")}
    if "status" in allowed_fields and isinstance(allowed_fields["status"], str):
        allowed_fields["status"] = _normalize_status(allowed_fields["status"])
    if "priority" in allowed_fields and isinstance(allowed_fields["priority"], str):
        allowed_fields["priority"] = _normalize_priority(allowed_fields["priority"])
    if not allowed_fields:
        raise HTTPException(400, "no valid fields to update")
    sets = ", ".join(f"{k}=?" for k in allowed_fields)
    _before = db.qone("SELECT * FROM tasks WHERE id=? AND user_id=1", (task_id,))
    db.run(f"UPDATE tasks SET {sets}, updated_at=datetime('now') WHERE id=? AND user_id=1", (*allowed_fields.values(), task_id))
    if _before:
        from .. import undo as _u
        _u.record("tasks.update", "update", "tasks", task_id, dict(_before),
                  f"tasks#{task_id} {(_before.get('title') or '')[:80]}")
    return db.qone("SELECT * FROM tasks WHERE id=? AND user_id=1", (task_id,))


@tasks_r.get("")
def list_tasks(status: str | None = None, domain: str | None = None, q: str = ""):
    sql, p = "SELECT t.*, c.name client_name, pr.name project_name FROM tasks t LEFT JOIN clients c ON c.id=t.client_id LEFT JOIN projects pr ON pr.id=t.project_id WHERE t.user_id=1", []
    if status:
        sql += " AND t.status=?"; p.append(status)
    if domain:
        sql += " AND t.domain=?"; p.append(domain)
    if q:
        sql += " AND (t.title LIKE ? OR t.description LIKE ?)"; p += [f"%{q}%", f"%{q}%"]
    return {"tasks": db.q(sql + " ORDER BY t.completed_at IS NOT NULL, t.due_at IS NULL, t.due_at, t.id DESC LIMIT 200", tuple(p))}


@tasks_r.post("")
def create_task(t: TaskIn):
    from datetime import datetime, timezone
    title = (t.title or "").strip()
    if not title:
        # A blank task is never a real task; reject it rather than storing noise.
        raise HTTPException(400, "title is required")
    now = datetime.now(timezone.utc).isoformat()
    status = _normalize_status(t.status)
    priority = _normalize_priority(t.priority)
    tid = db.run(
        "INSERT INTO tasks (user_id, title, description, status, priority, due_at, project_id, client_id, domain, tags_json, recurrence, created_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title, t.description, status, priority, t.due_at, t.project_id, t.client_id, t.domain,
         db.jdump(t.tags), t.recurrence, now, now))
    from .. import undo as _u
    # before=None marks this as a "create" — undo removes the row it inserted.
    _u.record("tasks.create", "create", "tasks", tid, None, f"tasks#{tid} {t.title[:80]}")
    return db.qone("SELECT * FROM tasks WHERE id=?", (tid,))


@tasks_r.patch("/{tid}")
def update_task(tid: int = None, id: int = None, patch: dict = Body(default=None)):
    task_id = tid or id
    if task_id is None:
        raise HTTPException(400, "task id required")
    fields = patch or {}
    return _update_task_impl(task_id, **fields)


@tasks_r.delete("/{tid}")
def delete_task(tid: int):
    _before = db.qone("SELECT * FROM tasks WHERE id=? AND user_id=1", (tid,))
    db.run("DELETE FROM tasks WHERE id=? AND user_id=1", (tid,))
    from .. import undo as _u
    _u.record("tasks.delete", "delete", "tasks", tid, _before,
              f"tasks#{tid} {(_before or {}).get('title', '')[:80]}")
    return {"ok": True}


@tasks_r.get("/overdue/list")
def overdue():
    """Overdue tasks. Key is `overdue` (not `tasks`): the frontend type in
    api.ts, the orchestrator's memory harvest, and scripts/e2e_check.py all read
    `overdue` + `count`. Returning `tasks` silently emptied the overdue list in
    every consumer."""
    rows = db.q("SELECT * FROM tasks WHERE user_id=1 AND status != 'completed' AND due_at IS NOT NULL AND due_at < datetime('now') ORDER BY due_at")
    return {"overdue": rows, "count": len(rows)}
