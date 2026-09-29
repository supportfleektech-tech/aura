"""Approvals router — list, resolve (follow-ups + terminal)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import db

approvals_r = APIRouter(prefix="/approvals", tags=["approvals"])


def _hermes():
    from ..hermes import hermes
    return hermes


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
    drafts = []
    sent, errors = [], []
    if decision == "approved":
        detail = db.jload(a.get("detail_json"), {})
        if a["risk"] == "R3" and a["title"] == "Run terminal command or script":
            from .. import scripts as _sc, terminal as _t
            text = detail.get("command_text", "")
            from ..orchestrator import _terminal_cmd
            s, sargs = _sc.find_in_text(text)
            if s:
                r = _sc.run(s["id"], source="chat", args=sargs or None)
            else:
                r = _t.exec_command(_terminal_cmd(text), source="chat")
            result["terminal_result"] = r
            db.notify("Terminal/Script executed", f"Command: {text[:80]}", "info")
        else:
            drafts = [d for d in (body.get("drafts") or detail.get("drafts", [])) if isinstance(d, dict)][:5]
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
    db.log_activity("approval", f"Approval {decision}: {a['title']}", "", "general",
                    "success" if decision == "approved" else "warn")
    try:
        from .. import missions as _missions
        resumed = _missions.resume_from_approval(aid, decision)
        if resumed:
            result["mission"] = resumed
    except Exception:
        pass
    return result
