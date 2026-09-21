"""Named script library — your recurring commands, saved and audited.

A script is a name + a shell command (+ machine). Saving runs the same
dangerous-pattern gate as the Terminal, so a saved script can never smuggle
a footgun later (re-checked at every run too). Runs flow through the audited
terminal exec path — nothing here executes on its own.

Commands may contain `{placeholder}` slots that callers can fill
(`run my deploy script with target=staging`); values are shell-quoted.
"""
from __future__ import annotations

import json
import re
import shlex
import time

from . import db

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def list_scripts() -> list[dict]:
    return db.q("SELECT * FROM scripts ORDER BY name")


def get(name_or_id) -> dict | None:
    s = str(name_or_id or "").strip()
    if not s:
        return None
    if s.isdigit():
        return db.qone("SELECT * FROM scripts WHERE id=?", (int(s),))
    return db.qone("SELECT * FROM scripts WHERE name=?", (s,))


def save(name: str, command: str, machine: str = "local", description: str = "") -> dict:
    name = str(name or "").strip().lower()
    command = str(command or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("script name: 2-40 chars, lowercase (a-z 0-9 _ -)")
    if not command:
        raise ValueError("command required")
    if len(command) > 1500:
        raise ValueError("command too long (1500 char cap)")
    from . import terminal
    risk, why = terminal.classify(command)
    if risk == "dangerous":
        raise ValueError(f"refused — {why}")
    try:
        terminal._resolve(machine)  # validates name / rejects unknown
    except ValueError as e:
        raise ValueError(f"machine: {e}") from e
    db.run("INSERT INTO scripts (name,command,machine,description) VALUES (?,?,?,?) "
           "ON CONFLICT(name) DO UPDATE SET command=excluded.command, machine=excluded.machine, "
           "description=excluded.description",
           (name, command, machine or "local", str(description or "")[:300]))
    row = get(name) or {}
    db.audit("scripts.save", "script", str(row.get("id", "")), f"{name}: {command[:100]}")
    db.log_activity("system", f"Script saved: {name}", f"risk {risk}", "general", "success")
    return {"ok": True, "id": row.get("id"), "name": name, "risk": risk}


def remove(script_id: int) -> bool:
    row = db.qone("SELECT name FROM scripts WHERE id=?", (script_id,))
    if not row:
        return False
    db.run("DELETE FROM scripts WHERE id=?", (script_id,))
    db.audit("scripts.remove", "script", str(script_id), row["name"])
    return True


def _fill(command: str, args: dict | None) -> str:
    if not args:
        return command
    def sub(m):
        key = m.group(1)
        if key not in args:
            return m.group(0)
        return shlex.quote(str(args[key])[:500])
    return re.sub(r"\{([a-z0-9_]+)\}", sub, command)


def run(name_or_id, source: str = "ui", args: dict | None = None) -> dict:
    s = get(name_or_id)
    if not s:
        return {"ok": False, "error": f"no such script: {name_or_id}"}
    command = _fill(s["command"], args if isinstance(args, dict) else None)
    from . import terminal
    res = terminal.exec_command(command, s.get("machine") or "local", source=source)
    status = ("denied" if res.get("denied") else "dry_run" if res.get("dry_run")
              else "ok" if res.get("ok") else "error")
    db.run("UPDATE scripts SET run_count=run_count+1, last_run=?, last_status=? WHERE id=?",
           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), status, s["id"]))
    if isinstance(res, dict):
        res = {**res, "script": s["name"], "risk_note": res.get("risk_note", "")}
    return res


def find_in_text(text: str) -> tuple[dict | None, dict]:
    """Extract 'run (my|the) <name> script' from chat text → (script, args)."""
    low = (text or "").lower()
    m = re.search(r"\bscript\s*[:>]\s*([a-z0-9][a-z0-9_-]{1,39})", low)
    if not m:
        m = re.search(r"\brun\b[^?.!]*?\b(?:my|the)\s+([a-z0-9][a-z0-9_-]{1,39})\s+script\b", low)
    if not m:
        return None, {}
    s = get(m.group(1))
    args = {}
    am = re.search(r"\bwith\s+([a-z0-9_]+)\s*=\s*[`'\"]?([^\s`'\"]+)", low)
    if am:
        args[am.group(1)] = am.group(2)
    return s, args
