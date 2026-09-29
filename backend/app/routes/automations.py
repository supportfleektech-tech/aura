"""Automations router — CRUD, run, dry-run."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

auto_r = APIRouter(prefix="/automations", tags=["automations"])


def _hermes():
    from ..hermes import hermes
    return hermes


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
    from ..hermes import validate_action
    allowed = {"name", "status", "trigger_config", "action_config", "action_kind", "trigger_kind", "next_run"}
    if not (set(patch) & set(allowed)):
        raise HTTPException(400, "no valid fields to update")
    row = db.qone("SELECT * FROM automations WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "not found")
    # Validate the *merged* result, so a partial patch cannot produce an
    # automation that only becomes invalid once written.
    if "action_kind" in patch or "action_config" in patch:
        kind = patch.get("action_kind", row["action_kind"])
        cfg = db.jload(row["action_config"], {})
        if isinstance(patch.get("action_config"), dict):
            cfg = {**cfg, **patch["action_config"]}
        try:
            validate_action(kind, cfg)
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
    a = db.qone("SELECT * FROM automations WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404, "not found")
    hermes = _hermes()
    if dry_run:
        # Fire the action with writes and outbound side effects suppressed, so the
        # user can see what it *would* do. last_run/next_run stay untouched.
        from .. import db as _db
        with _db.preview() as blocked:
            try:
                res = hermes._fire_one(a, fire_id=f"dry-{aid}")
            except Exception as e:
                res = {"ok": False, "error": str(e)[:200]}
            blocked = list(blocked)
        return {"dry_run": True, "fired": res, "blocked": blocked}
    # Use SQLite's own datetime() so the value is directly comparable against
    # datetime('now') in tick_automations(). An ISO-8601 'T' separator sorts
    # after a space and would never match.
    db.run("UPDATE automations SET next_run=datetime('now') WHERE id=?", (aid,))
    return {"ran": hermes.tick_automations()}


@auto_r.delete("/{aid}")
def delete_auto(aid: int):
    db.run("DELETE FROM automations WHERE id=?", (aid,))
    return {"ok": True}
