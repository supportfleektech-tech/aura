"""Projects router — CRUD with milestones."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

projects_r = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    client_id: int | None = None
    status: str = "active"
    progress: int = 0
    deadline: str | None = None
    description: str = ""
    health: str = "on_track"


@projects_r.get("")
def list_projects():
    rows = db.q("SELECT p.*, c.name client_name, c.org client_org FROM projects p LEFT JOIN clients c ON c.id=p.client_id "
                "WHERE p.user_id=1 ORDER BY p.status='completed', p.updated_at DESC")
    for r in rows:
        r["milestones"] = db.q("SELECT * FROM milestones WHERE project_id=? ORDER BY due_at", (r["id"],))
    return {"projects": rows}


@projects_r.post("")
def create_project(p: ProjectIn):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    pid = db.run(
        "INSERT INTO projects (user_id, client_id, name, status, progress, deadline, description, health, created_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p.client_id, p.name, p.status, p.progress, p.deadline, p.description, p.health, now, now))
    return db.qone("SELECT * FROM projects WHERE id=?", (pid,))


def add_milestone(pid: int, m: dict):
    title = (m.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "milestone title is required")
    if not db.qone("SELECT id FROM projects WHERE id=? AND user_id=1", (pid,)):
        raise HTTPException(404, "project not found")
    mid = db.run("INSERT INTO milestones (project_id,title,status,due_at) VALUES (?,?,?,?)",
                 (pid, title, m.get("status") or "open", m.get("due_at")))
    return db.qone("SELECT * FROM milestones WHERE id=?", (mid,))


@projects_r.post("/{pid}/milestones")
def create_milestone(pid: int, m: dict):
    return add_milestone(pid, m)


@projects_r.patch("/{pid}/milestones/{mid}")
def update_milestone(pid: int, mid: int, patch: dict):
    if not db.qone("SELECT id FROM milestones WHERE id=? AND project_id=?", (mid, pid)):
        raise HTTPException(404, "milestone not found")
    allowed = {"title", "status", "due_at"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if not sets:
        raise HTTPException(400, "no valid fields to update")
    db.run(f"UPDATE milestones SET {sets} WHERE id=?",
           (*[patch[k] for k in patch if k in allowed], mid))
    return db.qone("SELECT * FROM milestones WHERE id=?", (mid,))


@projects_r.delete("/{pid}/milestones/{mid}")
def delete_milestone(pid: int, mid: int):
    if not db.qone("SELECT id FROM milestones WHERE id=? AND project_id=?", (mid, pid)):
        raise HTTPException(404, "milestone not found")
    db.run("DELETE FROM milestones WHERE id=?", (mid,))
    return {"ok": True}


@projects_r.patch("/{pid}")
def update_project(pid: int, patch: dict):
    allowed = {"name", "client_id", "status", "progress", "deadline", "description", "health"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if not sets:
        raise HTTPException(400, "no valid fields to update")
    db.run(f"UPDATE projects SET {sets}, updated_at=datetime('now') WHERE id=? AND user_id=1", (*[patch[k] for k in patch if k in allowed], pid))
    return db.qone("SELECT * FROM projects WHERE id=? AND user_id=1", (pid,))


@projects_r.delete("/{pid}")
def delete_project(pid: int):
    _before = db.qone("SELECT * FROM projects WHERE id=? AND user_id=1", (pid,))
    db.run("DELETE FROM projects WHERE id=? AND user_id=1", (pid,))
    from .. import undo as _u
    _u.record("projects.delete", "delete", "projects", pid, _before,
              f"projects#{pid} {(_before or {}).get('name', '')[:80]}")
    return {"ok": True}
