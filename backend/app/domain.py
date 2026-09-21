"""Domain CRUD routers: tasks, clients, projects, career, personal, memory,
automations, activity, notifications, approvals, gateway."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from typing import Any

from . import db
from .memory import memory_engine

# Lazy import to avoid circular dependency with hermes
def _hermes():
    from .hermes import hermes
    return hermes

# ---------------------------------------------------------------- tasks ---
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
    now = datetime.now(timezone.utc).isoformat()
    tid = db.run(
        "INSERT INTO tasks (user_id, title, description, status, priority, due_at, project_id, client_id, domain, tags_json, recurrence, created_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (t.title, t.description, t.status, t.priority, t.due_at, t.project_id, t.client_id, t.domain,
         db.jdump(t.tags), t.recurrence, now, now))
    return db.qone("SELECT * FROM tasks WHERE id=?", (tid,))


@tasks_r.patch("/{tid}")
def update_task(tid: int = None, id: int = None, patch: dict = None, **kwargs):
    # Accept both 'tid' and 'id' for the task ID, and 'patch' or other fields as the update
    task_id = tid or id
    if task_id is None:
        raise HTTPException(400, "task id required")
    
    # If patch is not provided, build it from kwargs
    if patch is None:
        patch = {k: v for k, v in kwargs.items() if k not in ('tid', 'id')}
    
    allowed = {"title", "description", "status", "priority", "due_at", "project_id", "client_id", "domain", "tags", "recurrence"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if not sets:
        raise HTTPException(400, "no valid fields to update")
    vals = [patch[k] for k in patch if k in allowed] + [task_id]
    db.run(f"UPDATE tasks SET {sets}, updated_at=datetime('now') WHERE id=? AND user_id=1", (*[patch[k] for k in patch if k in allowed], task_id))
    return db.qone("SELECT * FROM tasks WHERE id=? AND user_id=1", (task_id,))


@tasks_r.delete("/{tid}")
def delete_task(tid: int):
    _before = db.qone("SELECT * FROM tasks WHERE id=? AND user_id=1", (tid,))
    db.run("DELETE FROM tasks WHERE id=? AND user_id=1", (tid,))
    from . import undo as _u
    _u.record("tasks.delete", "delete", "tasks", tid, _before,
              f"tasks#{tid} {(_before or {}).get('title', '')[:80]}")
    return {"ok": True}


@tasks_r.get("/overdue/list")
def overdue():
    rows = db.q("SELECT * FROM tasks WHERE user_id=1 AND status != 'completed' AND due_at IS NOT NULL AND due_at < datetime('now') ORDER BY due_at")
    return {"tasks": rows}


# -------------------------------------------------------------- clients ---
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
        from . import undo as _u
        _u.record("clients.update", "update", "clients", cid, _before,
                  f"clients#{cid} {(_before or {}).get('name', '')[:80]}")
    return db.qone("SELECT * FROM clients WHERE id=?", (cid,))


@clients_r.delete("/{cid}")
def delete_client(cid: int):
    _before = db.qone("SELECT * FROM clients WHERE id=? AND user_id=1", (cid,))
    db.run("DELETE FROM clients WHERE id=? AND user_id=1", (cid,))
    from . import undo as _u
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


# ------------------------------------------------------------- projects ---
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


@projects_r.patch("/{pid}")
def update_project(pid: int, patch: dict):
    allowed = {"name", "client_id", "status", "progress", "deadline", "description", "health"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if not sets:
        raise HTTPException(400, "no valid fields to update")
    vals = [patch[k] for k in patch if k in allowed] + [pid]
    db.run(f"UPDATE projects SET {sets}, updated_at=datetime('now') WHERE id=? AND user_id=1", (*[patch[k] for k in patch if k in allowed], pid))
    return db.qone("SELECT * FROM projects WHERE id=? AND user_id=1", (pid,))


@projects_r.delete("/{pid}")
def delete_project(pid: int):
    _before = db.qone("SELECT * FROM projects WHERE id=? AND user_id=1", (pid,))
    db.run("DELETE FROM projects WHERE id=? AND user_id=1", (pid,))
    from . import undo as _u


# Personal models
class ExpenseIn(BaseModel):
    category: str
    amount: float
    currency: str = "KES"
    note: str = ""


class SleepIn(BaseModel):
    hours: float
    bedtime: str | None = None
    wake_at: str | None = None
    quality: str | None = None
    note: str | None = None


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
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    sid = db.run(
        "INSERT INTO sleep_logs (user_id, hours, bedtime, wake_at, quality, note, date, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?, date('now'), ?)",
        (s.hours, s.bedtime, s.wake_at, s.quality, s.note, now))
    return {"id": sid, "hours": s.hours, "bedtime": s.bedtime, "wake_at": s.wake_at,
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


# --------------------------------------------------------------- career ---
def add_milestone(pid: int, m: dict):
    mid = db.run("INSERT INTO milestones (project_id,title,status,due_at) VALUES (?,?,?,?)",
                 (pid, m.get("title", "Milestone"), m.get("status", "open"), m.get("due_at")))
    return {"id": mid}


# --------------------------------------------------------------- career ---
career_r = APIRouter(prefix="/career", tags=["career"])


@career_r.get("/overview")
def overview():
    resumes = db.q("SELECT id,name,version,ats_score,created_at FROM resumes WHERE user_id=1 ORDER BY id DESC LIMIT 10")
    apps = db.q("SELECT * FROM applications WHERE user_id=1 ORDER BY updated_at DESC LIMIT 50")
    interviews = db.q("SELECT * FROM interviews WHERE user_id=1 ORDER BY id DESC LIMIT 20")
    blocks = db.q("SELECT * FROM timeblocks WHERE user_id=1 AND date(starts_at)=date('now') ORDER BY starts_at")
    tasks = db.q("SELECT * FROM tasks WHERE user_id=1 AND domain='career' AND status NOT IN ('completed','cancelled') LIMIT 20")
    stages: dict[str, int] = {}
    for a in apps:
        stages[a["stage"]] = stages.get(a["stage"], 0) + 1
    return {"resumes": resumes, "applications": apps, "interviews": interviews,
            "today_blocks": blocks, "tasks": tasks, "pipeline": stages}


@career_r.post("/resumes/analyze")
def analyze_resume(body: dict):
    r = _hermes().execute_tool("career.ats_analyze", {"text": body.get("text", ""),
                                                   "job_description": body.get("job_description", ""),
                                                   "name": body.get("name", "Resume")}, {"domain": "career"})
    return r["data"]


@career_r.get("/resumes")
def list_resumes():
    return {"resumes": db.q("SELECT * FROM resumes WHERE user_id=1 ORDER BY id DESC LIMIT 20")}


@career_r.get("/resumes/{rid}/download")
def download_resume(rid: int):
    from fastapi.responses import PlainTextResponse
    r = db.qone("SELECT * FROM resumes WHERE id=? AND user_id=1", (rid,))
    if not r:
        raise HTTPException(404, "resume not found")
    return PlainTextResponse(r["content"] or "", headers={
        "Content-Disposition": f'attachment; filename="aura-resume-v{r["version"]}.md"'})


@career_r.post("/applications")
def add_application(a: dict):
    aid = db.run("INSERT INTO applications (user_id,company,role,stage,url,notes) VALUES (1,?,?,?,?,?)",
                 (a.get("company", ""), a.get("role", ""), a.get("stage", "saved"), a.get("url", ""), a.get("notes", "")))
    return {"id": aid}


@career_r.patch("/applications/{aid}")
def update_application(aid: int, patch: dict):
    allowed = {"company", "role", "stage", "url", "notes"}
    sets = ", ".join(f"{k}=?" for k in patch if k in allowed)
    if sets:
        db.run(f"UPDATE applications SET {sets} WHERE id=?", (*[patch[k] for k in patch if k in allowed], aid))
    return {"ok": True}


@career_r.post("/interviews")
def add_interview(iv: dict):
    iid = db.run("INSERT INTO interviews (user_id,company,role,scheduled_at,score,feedback,qa_json) VALUES (1,?,?,?,?,?,?)",
                 (iv.get("company", ""), iv.get("role", ""), iv.get("scheduled_at"), iv.get("score"),
                  iv.get("feedback", ""), db.jdump(iv.get("qa", []))))
    return {"id": iid}


@career_r.get("/interviews/questions")
def questions(role: str = "Software Engineer"):
    return _hermes().execute_tool("career.interview_questions", {"role": role}, {})["data"]


@career_r.get("/blocks")
def blocks(date: str | None = None):
    return _hermes().execute_tool("schedule.blocks", {"date": date} if date else {}, {})["data"]


@career_r.post("/blocks/plan")
def plan_blocks(body: dict):
    return _hermes().execute_tool("schedule.plan_day", body, {})["data"]


@career_r.post("/blocks")
def add_block(b: dict):
    bid = db.run("INSERT INTO timeblocks (user_id,title,starts_at,ends_at,kind) VALUES (1,?,?,?,?)",
                 (b.get("title", "Focus"), b["starts_at"], b["ends_at"], b.get("kind", "focus")))
    return {"id": bid}


@career_r.delete("/blocks/{bid}")
def del_block(bid: int):
    db.run("DELETE FROM timeblocks WHERE id=?", (bid,))
    return {"ok": True}


# ------------------------------------------------------------- personal ---
personal_r = APIRouter(prefix="/personal", tags=["personal"])


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


# --------------------------------------------------------------- memory ---
memory_r = APIRouter(prefix="/memories", tags=["memory"])


@memory_r.get("")
def list_memories(domain: str | None = None, mtype: str | None = None, q: str = "", limit: int = 100):
    sql, p = "SELECT id,domain,mtype,title,content,source,confidence,importance,sensitivity,created_at,updated_at,last_confirmed FROM memories WHERE user_id=1 AND deleted_at IS NULL", []
    if domain:
        sql += " AND domain=?"; p.append(domain)
    if mtype:
        sql += " AND mtype=?"; p.append(mtype)
    if q:
        sql += " AND (title LIKE ? OR content LIKE ?)"; p += [f"%{q}%", f"%{q}%"]
    rows = db.q(sql + " ORDER BY importance DESC, id DESC LIMIT ?", (*p, limit))
    return {"memories": rows, "stats": memory_engine.stats()}


@memory_r.post("")
def create_memory(m: dict):
    r = memory_engine.store(m.get("title", "Memory"), m.get("content", ""), m.get("domain", "general"),
                            m.get("mtype", "semantic"), m.get("source", "ui"),
                            float(m.get("confidence", 0.8)), float(m.get("importance", 0.6)))
    r.pop("embedding_json", None)
    return r


def store_memory(title: str, content: str, domain: str = "general"):
    """Wrapper for hermes tool - stores a memory with given title, content, domain."""
    return create_memory({"title": title, "content": content, "domain": domain})


@memory_r.post("/search")
def search_memories(body: dict):
    from .inference import router
    return {"results": memory_engine.search(body.get("query", ""), body.get("domain"), body.get("mtype"),
                                            int(body.get("limit", 8)), embedder=router.embed_fn())}


def search_memory(query: str, domain: str | None = None, mtype: str | None = None, limit: int = 6):
    """Search memories - used by hermes tool."""
    from .inference import router
    return memory_engine.search(query, domain, mtype, limit, embedder=router.embed_fn())


@memory_r.patch("/{mid}")
def update_memory(mid: int, patch: dict):
    return memory_engine.update(mid, **patch) or {}


@memory_r.delete("/{mid}")
def delete_memory(mid: int):
    memory_engine.delete(mid)
    return {"ok": True}


@memory_r.post("/forget")
def forget_topic(body: dict):
    return {"forgotten": memory_engine.forget_topic(body.get("topic", ""))}


# ---------------------------------------------------------- automations ---
auto_r = APIRouter(prefix="/automations", tags=["automations"])


@auto_r.get("")
def list_auto():
    rows = []
    for a in db.q("SELECT * FROM automations WHERE user_id=1 ORDER BY id DESC"):
        a = dict(a)
        if a.get("action_kind") == "webhook":  # never leak the signing secret
            try:
                cfg = db.jload(a.get("action_config"), {})
                if cfg.get("secret"):
                    cfg["secret"] = "***"
                    a["action_config"] = db.jdump(cfg)
            except Exception:
                pass
        rows.append(a)
    return {"automations": rows}


@auto_r.post("")
def create_auto(a: dict):
    r = _hermes().execute_tool("automations.create", a, {})
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "invalid automation"))
    return r["data"]


@auto_r.patch("/{aid}")
def update_auto(aid: int, patch: dict):
    allowed = {"name", "status", "trigger_config", "action_config", "action_kind", "trigger_kind", "next_run"}
    if "action_kind" in patch:
        from .hermes import ACTION_KINDS
        if patch["action_kind"] not in ACTION_KINDS:
            raise HTTPException(400, f"action_kind must be one of {', '.join(ACTION_KINDS)}")
        if patch["action_kind"] == "brief":
            from .hermes import _validate_brief_action
            a = db.qone("SELECT action_config FROM automations WHERE id=?", (aid,))
            cfg = db.jload((a or {}).get("action_config"), {})
            if isinstance(patch.get("action_config"), dict):
                cfg = {**cfg, **patch["action_config"]}
            try:
                _validate_brief_action(cfg)
            except ValueError as e:
                raise HTTPException(400, str(e))
    if patch.get("action_kind") == "webhook" or isinstance(patch.get("action_config"), dict) or "action_kind" in patch:
        a = db.qone("SELECT action_kind, action_config FROM automations WHERE id=?", (aid,))
        if a and (patch.get("action_kind", a["action_kind"]) == "webhook"):
            from .hermes import validate_webhook_action
            cfg = db.jload(a["action_config"], {})
            if isinstance(patch.get("action_config"), dict):
                cfg = {**cfg, **patch["action_config"]}
            try:
                validate_webhook_action(cfg)
            except ValueError as e:
                raise HTTPException(400, str(e))
    conv = {k: (db.jdump(patch[k]) if k in ("trigger_config", "action_config") and isinstance(patch[k], dict) else patch[k])
            for k in patch if k in allowed}
    sets = ", ".join(f"{k}=?" for k in conv)
    if sets:
        db.run(f"UPDATE automations SET {sets} WHERE id=?", (*conv.values(), aid))
    return {"ok": True}


@auto_r.post("/{aid}/run")
def run_auto(aid: int, dry_run: bool = False):
    if dry_run:
        try:
            return _hermes().dry_fire(aid)
        except KeyError:
            raise HTTPException(404, "not found")
    a = db.qone("SELECT * FROM automations WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404, "not found")
    db.run("UPDATE automations SET next_run=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (aid,))
    return {"ran": _hermes().tick_automations()}


@auto_r.delete("/{aid}")
def delete_auto(aid: int):
    db.run("DELETE FROM automations WHERE id=?", (aid,))
    return {"ok": True}


# ---------------------------------------------------- activity & notes ---
activity_r = APIRouter(prefix="/activity", tags=["activity"])


@activity_r.get("")
def list_activity(kind: str | None = None, domain: str | None = None, limit: int = 100):
    sql, p = "SELECT * FROM activity WHERE user_id=1", []
    if kind:
        sql += " AND kind=?"; p.append(kind)
    if domain:
        sql += " AND domain=?"; p.append(domain)
    return {"activity": db.q(sql + " ORDER BY id DESC LIMIT ?", (*p, limit))}


notes_r = APIRouter(prefix="/notifications", tags=["notifications"])


@notes_r.get("")
def list_notes():
    return {"notifications": db.q("SELECT * FROM notifications WHERE user_id=1 ORDER BY id DESC LIMIT 50"),
            "unread": (db.qone("SELECT COUNT(*) c FROM notifications WHERE user_id=1 AND read=0") or {}).get("c", 0)}


@notes_r.post("/{nid}/read")
def read_note(nid: int):
    db.run("UPDATE notifications SET read=1 WHERE id=?", (nid,))
    return {"ok": True}


@notes_r.post("/read-all")
def read_all():
    db.run("UPDATE notifications SET read=1 WHERE user_id=1")
    return {"ok": True}


# ----------------------------------------------------------------- push ---
push_r = APIRouter(prefix="/push", tags=["push"])


@push_r.get("/vapid-public-key")
def vapid_key():
    from . import push as pushmod
    return {"key": pushmod.vapid_public_key() or None, "configured": pushmod.configured()}


@push_r.post("/subscribe")
def push_subscribe(body: dict):
    from . import push as pushmod
    try:
        keys = body.get("keys", {}) or {}
        return pushmod.subscribe(body.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@push_r.post("/unsubscribe")
def push_unsubscribe(body: dict):
    from . import push as pushmod
    return pushmod.unsubscribe(body.get("endpoint", ""))


@push_r.post("/test")
def push_test(body: dict):
    from . import push as pushmod
    return pushmod.send_push(body.get("title", "AURA test push") or "AURA test push",
                            body.get("body", "Push is wired up.") or "", body.get("url", "/") or "/")


# ------------------------------------------------------------ approvals ---
approvals_r = APIRouter(prefix="/approvals", tags=["approvals"])


@approvals_r.get("")
def list_approvals(status: str = "pending"):
    rows = db.q("SELECT * FROM approvals WHERE user_id=1 AND status=? ORDER BY id DESC LIMIT 30", (status,))
    for r in rows:
        r["detail"] = db.jload(r.get("detail_json"), {})
    return {"approvals": rows}


@approvals_r.post("/{aid}/resolve")
def resolve_approval(aid: int, body: dict):
    decision = body.get("decision", "rejected")
    if decision not in ("approved", "rejected", "cancelled"):
        raise HTTPException(400, "decision must be approved|rejected|cancelled")
    a = db.qone("SELECT * FROM approvals WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404, "not found")
    if a["status"] == "expired":
        raise HTTPException(409, "approval has expired")
    db.run("UPDATE approvals SET status=?, resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (decision, aid))
    result: Any = {"decision": decision}
    if decision == "approved":
        detail = db.jload(a.get("detail_json"), {})
        if a["risk"] == "R3" and a["title"] == "Run terminal command or script":
            # R3 terminal/script execution approval
            from . import scripts as _sc, terminal as _t
            text = detail.get("command_text", "")
            from .orchestrator import _terminal_cmd
            s, sargs = _sc.find_in_text(text)
            if s:
                r = _sc.run(s["id"], source="chat", args=sargs or None)
            else:
                r = _t.exec_command(_terminal_cmd(text), source="chat")
            result["terminal_result"] = r
            db.notify("Terminal/Script executed", f"Command: {text[:80]}", "info")
        else:
            # Follow-ups draft approval (existing logic)
            drafts = [d for d in (body.get("drafts") or detail.get("drafts", [])) if isinstance(d, dict)][:5]
            sent, errors = [], []
            for d in drafts:
                r = _hermes().execute_tool("comms.send", {"platform": detail.get("channel", "email"),
                                                       "to": d.get("to", ""), "subject": d.get("subject", ""),
                                                       "text": f"{d.get('subject','')}\n\n{d.get('body','')}"}, {})
                data = r.get("data") or {}
                (sent if data.get("sent") else errors).append(data)
            result["sent"] = sent
            if errors:
                result["errors"] = [e.get("error") or e.get("note", "send failed") for e in errors]
            detail["drafts_sent"] = drafts
            db.run("UPDATE approvals SET detail_json=? WHERE id=?", (db.jdump(detail), aid))
            if errors and not sent:
                db.notify("Follow-ups FAILED", "; ".join(result["errors"])[:180], "error")
            elif errors:
                db.notify("Follow-ups partially sent", f"{len(sent)} ok, {len(errors)} failed.", "warn")
            else:
                db.notify("Follow-ups sent", f"{len(sent)} message(s) dispatched via gateway.", "info")
        detail["drafts_sent"] = drafts
        db.run("UPDATE approvals SET detail_json=? WHERE id=?", (db.jdump(detail), aid))
        if errors and not sent:
            db.notify("Follow-ups FAILED", "; ".join(result["errors"])[:180], "error")
        elif errors:
            db.notify("Follow-ups partially sent", f"{len(sent)} ok, {len(errors)} failed.", "warn")
        else:
            db.notify("Follow-ups sent", f"{len(sent)} message(s) dispatched via gateway.", "info")
    db.log_activity("approval", f"Approval {decision}: {a['title']}", "", "general",
                    "success" if decision == "approved" else "warn")
    try:
        from . import missions as _missions
        resumed = _missions.resume_from_approval(aid, decision)
        if resumed:
            result["mission"] = resumed
    except Exception:
        pass
    return result


# -------------------------------------------------------------- missions ---
missions_r = APIRouter(prefix="/missions", tags=["missions"])


@missions_r.get("")
def list_missions():
    from . import missions as _m
    return {"missions": _m.list_missions()}


@missions_r.post("")
def create_mission(body: dict):
    from . import missions as _m
    if not (body.get("goal") or "").strip():
        raise HTTPException(400, "goal is empty")
    try:
        return _m.create_mission(body["goal"], body.get("planner", "auto") or "auto")
    except ValueError as e:
        raise HTTPException(400, str(e))


@missions_r.get("/{mid}")
def get_mission(mid: int):
    from . import missions as _m
    m = _m._row(mid)
    if not m:
        raise HTTPException(404, "not found")
    return m


@missions_r.patch("/{mid}")
def patch_mission(mid: int, body: dict):
    from . import missions as _m
    if not isinstance(body.get("steps"), list):
        raise HTTPException(400, "steps must be a list")
    try:
        return _m.update_steps(mid, body["steps"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@missions_r.post("/{mid}/schedule")
def schedule_mission(mid: int, body: dict):
    from . import missions as _m
    try:
        m = _m.set_schedule(mid, body.get("every", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not m:
        raise HTTPException(404, "not found")
    return m


@missions_r.get("/{mid}/runs")
def mission_runs(mid: int):
    from . import missions as _m
    if not _m._row(mid):
        raise HTTPException(404, "not found")
    return {"runs": _m.list_runs(mid)}


@missions_r.post("/{mid}/control")
def control_mission(mid: int, body: dict):
    from . import missions as _m
    try:
        m = _m.set_status(mid, body.get("action", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not m:
        raise HTTPException(404, "not found")
    return m


# -------------------------------------------------------------- gateway ---
gateway_r = APIRouter(prefix="/gateway", tags=["gateway"])


@gateway_r.get("/status")
def gateway_status():
    from .providers import get_integration, redacted_status
    rows = db.q("SELECT platform,status,account,last_test FROM integrations WHERE user_id=1")
    for r in rows:
        _, cfg = get_integration(r["platform"])
        r.update(redacted_status(r["platform"], cfg))
    return {"integrations": rows, "events": _hermes().recent_events(20)}


@gateway_r.post("/{platform}/connect")
def gw_connect(platform: str, body: dict):
    from .providers import get_integration, save_config, validate_config
    if platform not in ("telegram", "discord", "slack", "whatsapp", "email", "homeassistant"):
        raise HTTPException(404, f"unknown platform {platform}")
    _, cfg = get_integration(platform)
    incoming = body.get("config") if isinstance(body.get("config"), dict) else {}
    for k, v in incoming.items():
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()
    mode = (body.get("mode") or cfg.get("mode") or "sandbox").lower()
    if mode not in ("sandbox", "live"):
        raise HTTPException(400, "mode must be sandbox|live")
    if mode == "live":
        missing = validate_config(platform, cfg)
        if missing:
            raise HTTPException(400, f"missing live credentials: {', '.join(missing)}")
    cfg["mode"] = mode
    save_config(platform, cfg)
    db.run("UPDATE integrations SET status='connected', account=? WHERE user_id=1 AND platform=?",
           (body.get("account") or f"{platform} account", platform))
    _hermes().emit_gateway(platform, f"{platform} connected ({mode})", actor="system", direction="out")
    return {"ok": True, "mode": mode}


@gateway_r.post("/{platform}/disconnect")
def gw_disconnect(platform: str, body: dict | None = None):
    from .providers import save_config
    if (body or {}).get("forget"):
        save_config(platform, {})
    db.run("UPDATE integrations SET status='disconnected' WHERE user_id=1 AND platform=?", (platform,))
    return {"ok": True}


@gateway_r.post("/{platform}/test")
def gw_test(platform: str):
    import time as _t
    from datetime import datetime, timezone as tz
    from .providers import test_connection
    _t0 = _t.time()
    res = test_connection(platform)
    if res.get("ok"):
        db.run("UPDATE integrations SET last_test=?, status='connected' WHERE user_id=1 AND platform=?",
               (datetime.now(tz.utc).isoformat(), platform))
        _hermes().emit_gateway(platform, f"connection test ({res.get('mode', 'sandbox')})", actor="aura", direction="out")
        db.log_activity("integration", f"Gateway test: {platform}", res.get("detail", "ping ok"), "general", "success")
    else:
        db.run("UPDATE integrations SET status='error' WHERE user_id=1 AND platform=?", (platform,))
        db.log_activity("integration", f"Gateway test FAILED: {platform}", res.get("error", "")[:150], "general", "error")
    res["latency_ms"] = res.get("latency_ms", max(1, int((_t.time() - _t0) * 1000)))
    res["platform"] = platform
    return res


@gateway_r.post("/simulate")
def gw_simulate(ev: dict):
    if ev.get("send_live"):
        from .providers import send as provider_send
        plat = ev.get("platform", "telegram")
        res = provider_send(plat, ev.get("to", ""), ev.get("subject", "AURA live test"),
                            ev.get("text", "hello"))
        if res.get("sent"):
            e = _hermes().emit_gateway(plat, (ev.get("text") or "")[:160], actor="aura",
                                    direction="out", payload={"mode": res.get("mode")})
            db.log_activity("integration", f"Live test message sent via {plat}",
                            f"mode={res.get('mode')}", "general", "success")
            return {"event_id": e.event_id, "sent": True, "mode": res.get("mode")}
        raise HTTPException(400, res.get("error") or res.get("note", "send failed"))
    e = _hermes().emit_gateway(ev.get("platform", "telegram"), ev.get("text", "hello"), actor="user")
    return {"event_id": e.event_id}


# ------------------------------------------------- messaging bots (WS-D) ---
@gateway_r.post("/telegram/poll")
def gw_telegram_poll():
    from . import messaging
    return messaging.telegram_poll()


@gateway_r.post("/telegram/webhook")
def gw_telegram_webhook(update: dict,
                        secret: str | None = Header(default=None, alias="x-telegram-bot-api-secret-token")):
    from . import messaging
    res = messaging.telegram_webhook(update or {}, secret)
    if res.get("error") == "bad webhook secret":
        raise HTTPException(403, "bad webhook secret")
    return res


@gateway_r.get("/whatsapp/webhook")
def gw_whatsapp_verify(hub_mode: str = Query(default="", alias="hub.mode"),
                       hub_token: str = Query(default="", alias="hub.verify_token"),
                       hub_challenge: str = Query(default="", alias="hub.challenge")):
    from . import messaging
    chal = messaging.whatsapp_verify(hub_mode, hub_token, hub_challenge)
    if chal is None:
        raise HTTPException(403, "verify_token mismatch")
    return Response(content=chal, media_type="text/plain")


@gateway_r.post("/whatsapp/webhook")
def gw_whatsapp_webhook(payload: dict):
    from . import messaging
    return messaging.whatsapp_webhook(payload or {})


ROUTERS = [tasks_r, clients_r, projects_r, career_r, personal_r, memory_r, auto_r, activity_r, notes_r, approvals_r, gateway_r, push_r]


# ------------------------------------------------------------- briefings ---
brief_r = APIRouter(prefix="/briefings", tags=["briefings"])


@brief_r.get("")
def list_briefs():
    from . import briefing as _b
    return {"briefings": _b.list_briefings()}


@brief_r.post("")
def create_brief(b: dict):
    from . import briefing as _b
    try:
        return _b.create_briefing(b.get("name", ""), b.get("kind", "morning"), b.get("prompt", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.patch("/{bid}")
def update_brief(bid: int, patch: dict):
    from . import briefing as _b
    try:
        return _b.update_briefing(bid, patch)
    except KeyError:
        raise HTTPException(404, "briefing not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.delete("/{bid}")
def delete_brief(bid: int):
    from . import briefing as _b
    _b.delete_briefing(bid)
    return {"ok": True}


@brief_r.post("/{bid}/run")
def run_brief(bid: int, b: dict | None = None):
    from . import briefing as _b
    try:
        return _b.run_briefing(bid, extra=(b or {}).get("extra", ""))
    except KeyError:
        raise HTTPException(404, "briefing not found")


@brief_r.post("/run-now")
def run_brief_now(b: dict | None = None):
    from . import briefing as _b
    try:
        return _b.run_briefing(None, ((b or {}).get("kind") or "morning"), (b or {}).get("extra", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@brief_r.get("/runs/list")
def list_brief_runs(briefing_id: int | None = None, limit: int = 20):
    from . import briefing as _b
    return {"runs": _b.list_runs(briefing_id, limit)}


# ------------------------------------------------------------------ mail ---
mail_r = APIRouter(prefix="/mail", tags=["mail"])


@mail_r.get("/accounts")
def list_mail_accounts():
    from . import mailbox as _m
    return {"accounts": _m.list_accounts()}


@mail_r.post("/accounts")
def create_mail_account(b: dict):
    from . import mailbox as _m
    try:
        return _m.create_account(b.get("name", ""), b.get("host", ""), b.get("port", 993),
                                 b.get("username", ""), b.get("password", ""),
                                 b.get("mode", "sandbox"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.patch("/accounts/{aid}")
def update_mail_account(aid: int, patch: dict):
    from . import mailbox as _m
    try:
        return _m.update_account(aid, patch)
    except KeyError:
        raise HTTPException(404, "account not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.delete("/accounts/{aid}")
def delete_mail_account(aid: int):
    from . import mailbox as _m
    _m.delete_account(aid)
    return {"ok": True}


@mail_r.post("/accounts/{aid}/sync")
def sync_mail_account(aid: int):
    from . import mailbox as _m
    try:
        return _m.sync_account(aid)
    except KeyError:
        raise HTTPException(404, "account not found")


@mail_r.get("/emails")
def list_mail(account_id: int | None = None, unread_only: bool = False,
              triage: str = "", limit: int = 50):
    from . import mailbox as _m
    if triage and triage not in _m.TRIAGE:
        raise HTTPException(400, f"triage must be one of {', '.join(_m.TRIAGE)}")
    return {"emails": _m.list_emails(account_id, unread_only, triage, limit),
            "unread": _m.unread_count(account_id)}


@mail_r.get("/emails/{mid}")
def get_mail(mid: int):
    from . import mailbox as _m
    m = _m.get_email(mid)
    if not m:
        raise HTTPException(404, "email not found")
    return m


@mail_r.patch("/emails/{mid}")
def patch_mail(mid: int, b: dict):
    from . import mailbox as _m
    try:
        return _m.set_email(mid, b.get("seen"), b.get("triage"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.post("/triage")
def run_triage(b: dict | None = None):
    from . import mailbox as _m
    b = b or {}
    return _m.triage_unread(b.get("account_id"), int(b.get("limit", 20) or 20))


# ------------------------------------------------------------- calendar ---
cal_r = APIRouter(prefix="/calendar", tags=["calendar"])


@cal_r.get("/calendars")
def list_cals():
    from . import calendar_sync as _c
    return {"calendars": _c.list_calendars()}


@cal_r.post("/calendars")
def create_cal(b: dict):
    from . import calendar_sync as _c
    try:
        return _c.create_calendar(b.get("name", ""), b.get("source", "local"),
                                  b.get("color", "blue"), b.get("fields", {}))
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.patch("/calendars/{cid}")
def update_cal(cid: int, patch: dict):
    from . import calendar_sync as _c
    try:
        return _c.update_calendar(cid, patch)
    except KeyError:
        raise HTTPException(404, "calendar not found")


@cal_r.delete("/calendars/{cid}")
def delete_cal(cid: int):
    from . import calendar_sync as _c
    _c.delete_calendar(cid)
    return {"ok": True}


@cal_r.post("/calendars/{cid}/sync")
def sync_cal(cid: int):
    from . import calendar_sync as _c
    try:
        return _c.sync_calendar(cid)
    except KeyError:
        raise HTTPException(404, "calendar not found")


@cal_r.get("/events")
def list_events(start: str, end: str):
    from . import calendar_sync as _c
    try:
        return {"events": _c.events_between(start, end)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.get("/today")
def cal_today():
    from . import calendar_sync as _c
    return {"events": _c.todays_events()}


@cal_r.get("/week")
def cal_week():
    from . import calendar_sync as _c
    return {"events": _c.week_events()}


@cal_r.post("/events")
def create_ev(b: dict):
    from . import calendar_sync as _c
    try:
        cal_id = b.get("calendar_id") or _c.ensure_default_calendar()
        return _c.create_event(int(cal_id), b.get("title", "Untitled"),
                               b.get("starts_at", ""), b.get("ends_at", ""),
                               b.get("description", ""), b.get("location", ""),
                               bool(b.get("all_day", False)))
    except KeyError:
        raise HTTPException(404, "calendar not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.patch("/events/{eid}")
def update_ev(eid: int, patch: dict):
    from . import calendar_sync as _c
    try:
        return _c.update_event(eid, patch)
    except KeyError:
        raise HTTPException(404, "event not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.delete("/events/{eid}")
def delete_ev(eid: int):
    from . import calendar_sync as _c
    _c.delete_event(eid)
    return {"ok": True}


@cal_r.get("/google/auth-url")
def google_auth_url(calendar_id: int, redirect_uri: str):
    from . import calendar_sync as _c
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (calendar_id,))
    if not row or row["source"] != "google":
        raise HTTPException(404, "google calendar not found")
    cfg = db.jload(row["config_json"], {})
    if not cfg.get("client_id"):
        raise HTTPException(400, "client_id missing — save it on the calendar first")
    return {"url": _c.google_auth_url(cfg["client_id"], redirect_uri, f"cal-{calendar_id}")}


@cal_r.get("/google/landing")
def google_landing(code: str = "", error: str = ""):
    """OAuth redirect target: shows the code for copy-paste into AURA."""
    from fastapi.responses import HTMLResponse
    body = (f"<h2>Copy this code into AURA</h2><pre style='font-size:18px'>{code}</pre>"
            if code else f"<h2>Google auth failed</h2><p>{error or 'no code'}</p>")
    return HTMLResponse(f"<body style='font-family:sans-serif;background:#0b1428;color:#e8eefc;"
                        f"display:grid;place-items:center;min-height:90vh;text-align:center'>"
                        f"<div>{body}<p><small>You can close this tab.</small></p></div></body>")


@cal_r.post("/google/callback")
def google_callback(b: dict):
    from . import calendar_sync as _c
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (b.get("calendar_id"),))
    if not row or row["source"] != "google":
        raise HTTPException(404, "google calendar not found")
    if not b.get("code") or not b.get("redirect_uri"):
        raise HTTPException(400, "code + redirect_uri required")
    try:
        return _c.google_exchange(row, b["code"], b["redirect_uri"])
    except RuntimeError as e:
        raise HTTPException(400, str(e))


# ----------------------------------------------------------------- sync ---
sync_r = APIRouter(prefix="/sync", tags=["sync"])


@sync_r.get("/export")
def sync_export(device: str = ""):
    from . import sync as _s
    from . import prefs as _p
    _s.log_export(device or _p.get("device_name"))
    return _s.export_bundle()


@sync_r.post("/import")
def sync_import(b: dict):
    from . import sync as _s
    try:
        return _s.import_bundle(b.get("bundle", {}), b.get("device", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@sync_r.get("/log")
def sync_history(limit: int = 20):
    from . import sync as _s
    return {"log": _s.history(limit)}



# -------------------------------------------------------------- proactive ---
pro_r = APIRouter(prefix="/proactive", tags=["proactive"])


@pro_r.get("")
def list_proactive(include_dismissed: bool = False, limit: int = 20):
    from . import proactive as _p
    items = _p.scan()
    if include_dismissed:
        items = [{**{"key": r["key"], "type": r["type"], "title": r["title"],
                       "detail": r["detail"], "score": r["score"],
                       "dismissed": bool(r["dismissed"])}} for r in _p.list_all(True)]
    return {"opportunities": items[:max(1, min(50, limit))]}


@pro_r.post("/scan")
def scan_proactive():
    from . import proactive as _p
    items = _p.scan()
    top = _p.notify_top(items)
    return {"opportunities": items, "notified": top["key"] if top else None}


@pro_r.patch("/{key}/dismiss")
def dismiss_proactive(key: str, b: dict | None = None):
    from . import proactive as _p
    try:
        return _p.set_dismissed(key, (b or {}).get("dismissed", True))
    except KeyError:
        raise HTTPException(404, "opportunity not found")


@pro_r.post("/{key}/snooze")
def snooze_proactive(key: str, b: dict | None = None):
    from . import proactive as _p
    try:
        return _p.snooze(key, (b or {}).get("hours", 24))
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    except (TypeError, ValueError):
        raise HTTPException(400, "hours must be a number")


@pro_r.post("/{key}/act")
def act_proactive(key: str):
    from . import proactive as _p
    try:
        res = _p.act(key)
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    if not res.get("ok") and not res.get("gone"):
        raise HTTPException(400, res.get("message", "action failed"))
    return res


@pro_r.get("/resolved")
def resolved_proactive(limit: int = 20):
    from . import proactive as _p
    return {"resolved": _p.resolved_history(limit)}


undo_r = APIRouter(prefix="/undo", tags=["undo"])


@undo_r.get("")
def undo_preview():
    from . import undo as _u
    return {"journal": _u.tail(), "undoable": bool(_u.tail(1))}


@undo_r.post("")
def undo_apply(b: dict | None = None):
    from . import undo as _u
    return _u.undo_last(int((b or {}).get("steps", 1) or 1))


cost_r = APIRouter(prefix="/costs", tags=["costs"])


@cost_r.get("")
def costs_summary():
    from . import costs as _c
    return _c.summary()


@cost_r.get("/calls")
def costs_calls(limit: int = 50):
    rows = db.q("SELECT * FROM llm_usage ORDER BY id DESC LIMIT ?", (max(1, min(200, limit)),))
    return {"calls": rows}


analytics_r = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_r.get("/overview")
def analytics_overview():
    from . import analytics as _a
    return _a.overview()


ROUTERS += [brief_r, mail_r, cal_r, sync_r, pro_r, undo_r, cost_r, analytics_r, missions_r]


# ------------------------------------------------------------------ home ---
home_r = APIRouter(prefix="/home", tags=["home"])


@home_r.get("/status")
def home_status():
    from .providers import get_integration, redacted_status
    row, cfg = get_integration("homeassistant")
    out = {"platform": "homeassistant", "status": (row or {}).get("status", "disconnected"),
           "account": (row or {}).get("account", ""),
           "last_test": (row or {}).get("last_test")}
    out.update(redacted_status("homeassistant", cfg))
    return out


@home_r.get("/entities")
def home_entities():
    from . import homeassistant as _ha
    return _ha.states()


@home_r.post("/service")
def home_service(body: dict):
    from . import homeassistant as _ha
    res = _ha.call_service(body.get("domain", ""), body.get("service", ""),
                           body.get("entity_id", ""),
                           body.get("data") if isinstance(body.get("data"), dict) else None)
    db.log_activity("integration",
                    f"Home: {body.get('domain')}.{body.get('service')} {body.get('entity_id', '')}",
                    res.get("error", res.get("mode", ""))[:120], "general",
                    "success" if res.get("ok") else "error")
    return res


ROUTERS.append(home_r)
