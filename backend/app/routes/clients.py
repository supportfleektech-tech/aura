"""Clients router — CRUD with project/task counts."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

clients_r = APIRouter(prefix="/clients", tags=["clients"])


class ClientIn(BaseModel):
    name: str
    org: str = ""
    email: str = ""
    phone: str = ""
    health: str = "good"
    notes: str = ""
    contract_value: float = 0


@clients_r.get("")
def list_clients():
    rows = db.q("SELECT c.*, (SELECT COUNT(*) FROM projects p WHERE p.client_id=c.id AND p.status!='completed') open_projects,"
                " (SELECT COUNT(*) FROM tasks t WHERE t.client_id=c.id AND t.status NOT IN ('completed','cancelled')) open_tasks"
                " FROM clients c WHERE c.user_id=1 ORDER BY c.name")
    return {"clients": rows}


@clients_r.post("")
def create_client(c: ClientIn):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cid = db.run(
        "INSERT INTO clients (user_id, name, org, email, phone, health, notes, contract_value, created_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (c.name, c.org, c.email, c.phone, c.health, c.notes, c.contract_value, now, now))
    return db.qone("SELECT * FROM clients WHERE id=?", (cid,))


@clients_r.patch("/{cid}")
def update_client(cid: int, patch: dict):
    allowed = {"name", "org", "email", "phone", "health", "notes", "contract_value"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    _before = db.qone("SELECT * FROM clients WHERE id=? AND user_id=1", (cid,)) if sets else None
    if sets:
        db.run(f"UPDATE clients SET {sets} WHERE id=? AND user_id=1", (*[patch[k] for k in patch if k in allowed], cid))
        from .. import undo as _u
        _u.record("clients.update", "update", "clients", cid, _before,
                  f"clients#{cid} {(_before or {}).get('name', '')[:80]}")
    return db.qone("SELECT * FROM clients WHERE id=?", (cid,))


@clients_r.delete("/{cid}")
def delete_client(cid: int):
    _before = db.qone("SELECT * FROM clients WHERE id=? AND user_id=1", (cid,))
    db.run("DELETE FROM clients WHERE id=? AND user_id=1", (cid,))
    from .. import undo as _u
    _u.record("clients.delete", "delete", "clients", cid, _before,
              f"clients#{cid} {(_before or {}).get('name', '')[:80]}")
    return {"ok": True}


@clients_r.get("/{cid}")
def get_client(cid: int):
    c = db.qone("SELECT * FROM clients WHERE id=? AND user_id=1", (cid,))
    if not c:
        raise HTTPException(404, "client not found")
    c["projects"] = db.q("SELECT * FROM projects WHERE client_id=? ORDER BY updated_at DESC", (cid,))
    c["tasks"] = db.q("SELECT * FROM tasks WHERE client_id=? AND status NOT IN ('completed','cancelled') ORDER BY due_at", (cid,))
    return c
