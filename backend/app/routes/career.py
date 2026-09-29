"""Career router — resumes, applications, interviews, time blocks."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

career_r = APIRouter(prefix="/career", tags=["career"])


def _hermes():
    from ..hermes import hermes
    return hermes


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
