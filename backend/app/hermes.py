"""Hermes tool runtime — deterministic tool execution with approval gates.

Provides a registry of tools (R0-R4 risk levels), execution pipeline,
approval gating, plugin loading, and the 30s scheduler loop.
"""
from __future__ import annotations

import importlib
import json
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Literal
from urllib.parse import urlparse

import httpx

from . import config, db, prefs

# ------------------------------------------------------------ lazy function resolver ---
def _lazy(module_path: str, func_name: str):
    """Create a callable that lazily imports and calls the function at call time.
    The tool execution passes (args: dict, ctx: dict). This wrapper extracts kwargs from args."""
    def _wrapper(args: dict, ctx: dict):
        mod = importlib.import_module(module_path, "app")
        fn = getattr(mod, func_name)
        return fn(**args)
    return _wrapper


def _wrap_model(module_path: str, func_name: str, model_name: str):
    """Create a callable that wraps a domain function expecting a Pydantic model.
    The wrapper creates the model from args dict and calls the function with it."""
    def _wrapper(args: dict, ctx: dict):
        mod = importlib.import_module(module_path, "app")
        fn = getattr(mod, func_name)
        model_cls = getattr(mod, model_name)
        model = model_cls(**args)
        return fn(model)
    return _wrapper


RISK_INFO = "R0"          # pure read, no side effects
RISK_LOCAL_WRITE = "R1"   # local DB write
RISK_EXTERNAL = "R2"      # external HTTP call (needs approval)
RISK_DESTRUCTIVE = "R3"   # dangerous: terminal, scripts, destructive (needs approval)
RISK_PROHIBITED = "R4"    # never planned or executed

RISK_ORDER = [RISK_INFO, RISK_LOCAL_WRITE, RISK_EXTERNAL, RISK_DESTRUCTIVE, RISK_PROHIBITED]

RISK_LABEL = {
    RISK_INFO: "read-only",
    RISK_LOCAL_WRITE: "local write",
    RISK_EXTERNAL: "external call",
    RISK_DESTRUCTIVE: "destructive",
    RISK_PROHIBITED: "prohibited",
}

HERMES_VERSION = "2.0.0"

# ------------------------------------------------------------ tool model ---
@dataclass
class Tool:
    name: str
    risk: str
    description: str
    fn: Callable[..., Any]
    domain: str
    annotations: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.risk not in RISK_ORDER:
            raise ValueError(f"unknown risk level: {self.risk}")

    def __call__(self, args: dict, ctx: dict) -> Any:
        return self.fn(args, ctx)


# ------------------------------------------------------------ registry ---
TOOLS: Dict[str, Tool] = {}
_PLUGIN_TOOLS: set[str] = set()


def register_tool(tool: Tool) -> None:
    if tool.name in TOOLS:
        raise ValueError(f"tool already registered: {tool.name}")
    TOOLS[tool.name] = tool


def load_plugins() -> dict:
    """Load plugin tools from app/plugins/ and $DATA_DIR/plugins/."""
    from pathlib import Path
    import importlib.util
    import sys

    loaded = []
    failed = []
    for base in (Path("app/plugins"), config.DATA_DIR / "plugins"):
        if not base.exists():
            continue
        for py in base.glob("*.py"):
            if py.stem.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"plugin.{py.stem}", py)
            if not spec or not spec.loader:
                failed.append({"file": py.name, "error": "no spec"})
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                failed.append({"file": py.name, "error": str(e)[:200]})
                continue
            manifest = getattr(mod, "TOOL_MANIFEST", None)
            if not manifest or not isinstance(manifest, dict):
                failed.append({"file": py.name, "error": "missing or invalid TOOL_MANIFEST"})
                continue
            name = manifest.get("name")
            risk = manifest.get("risk")
            description = manifest.get("description", "")
            domain = manifest.get("domain", "general")
            fn = getattr(mod, "run", None)
            if not name or risk not in RISK_ORDER or not callable(fn):
                failed.append({"file": py.name, "error": "invalid manifest or missing run()"})
                continue
            if name in TOOLS:
                failed.append({"file": py.name, "error": f"name collision: {name}"})
                continue
            tool = Tool(name=name, risk=risk, description=description, fn=fn, domain=domain)
            TOOLS[name] = tool
            _PLUGIN_TOOLS.add(name)
            loaded.append(name)
    return {"loaded": loaded, "failed": failed}


# ------------------------------------------------------------ tool implementations ---
def _t_send_message(a: dict, ctx: dict) -> Any:
    from . import comms
    return comms.send(a.get("platform", "email"), a.get("to", ""), a.get("subject", ""), a.get("text", ""))


def _t_email_send(a: dict, ctx: dict) -> Any:
    from . import mailbox
    return mailbox.send_email(a.get("to", ""), a.get("subject", ""), a.get("text", ""), a.get("account_id"))


def _t_cal_invite(a: dict, ctx: dict) -> Any:
    from . import calendar_sync
    return calendar_sync.create_event(a.get("calendar_id"), a.get("title", ""), a.get("starts_at", ""), a.get("ends_at", ""), a.get("attendees", []))


def _t_terminal_run(a: dict, ctx: dict) -> Any:
    from . import terminal
    return terminal.exec_command(a.get("command", ""), source="hermes")


def _t_script_run(a: dict, ctx: dict) -> Any:
    from . import scripts
    return scripts.run_script(a.get("script_id"), source="hermes", args=a.get("args", {}))


def _t_automation_create(a: dict, ctx: dict) -> Any:
    from . import db
    name = a.get("name", "Automation")
    trigger_kind = a.get("trigger_kind", "schedule")
    trigger_config = a.get("trigger", a.get("trigger_config", {}))
    action_kind = a.get("action_kind", "notify")
    action_config = a.get("action", a.get("action_config", {}))
    if isinstance(trigger_config, dict):
        import json as _json
        trigger_config = _json.dumps(trigger_config)
    if isinstance(action_config, dict):
        import json as _json
        action_config = _json.dumps(action_config)
    auto_id = db.run(
        "INSERT INTO automations (name, trigger_kind, trigger_config, action_kind, action_config, status, next_run) VALUES (?,?,?,?,?,?,?)",
        (name, trigger_kind, trigger_config, action_kind, action_config, "active", _next_run({"every": "daily"})))
    row = db.qone("SELECT * FROM automations WHERE id=?", (auto_id,))
    return dict(row) if row else {"ok": True, "id": auto_id}


def _fire_webhook(url: str, payload: dict) -> dict:
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _next_run(trigger: dict) -> str:
    from datetime import datetime, timedelta, timezone
    every = trigger.get("every")
    if every == "hourly":
        return (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    if every == "daily":
        return (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if every == "weekly":
        days = 7 - datetime.now(timezone.utc).weekday()
        if days == 0:
            days = 7
        return (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return ""


# ------------------------------------------------------------ HermesAdapter ---
class HermesAdapter:
    _version = "2.0.0"

    def __init__(self):
        self._version = "2.0.0"
        self._register_builtins()

    def _register_builtins(self) -> None:
        # All function references are lazy - they resolve at call time to avoid circular imports
        # Risk R0 (info)
        register_tool(Tool("tasks.list", RISK_INFO, "List tasks", _lazy(".domain", "list_tasks"), "tasks"))
        register_tool(Tool("tasks.overdue", RISK_INFO, "List overdue tasks", _lazy(".domain", "overdue_tasks"), "tasks"))
        register_tool(Tool("tasks.prioritize", RISK_INFO, "Prioritize tasks", _lazy(".domain", "prioritize_tasks"), "tasks"))
        register_tool(Tool("clients.list", RISK_INFO, "List clients", _lazy(".domain", "list_clients"), "clients"))
        register_tool(Tool("projects.list", RISK_INFO, "List projects", _lazy(".domain", "list_projects"), "projects"))
        register_tool(Tool("memory.search", RISK_INFO, "Search memory", _lazy(".domain", "search_memory"), "memory"))
        register_tool(Tool("career.ats_analyze", RISK_INFO, "Analyze resume for ATS", _lazy(".career", "ats_analyze"), "career"))
        register_tool(Tool("career.interview_questions", RISK_INFO, "Generate interview questions", _lazy(".career", "interview_questions"), "career"))
        register_tool(Tool("schedule.blocks", RISK_INFO, "Get time blocks", lambda a, ctx: [], "schedule"))
        register_tool(Tool("comms.draft_followups", RISK_INFO, "Draft follow-ups", _lazy(".domain", "draft_followups"), "comms"))
        register_tool(Tool("system.status", RISK_INFO, "System status", lambda a, ctx: {"ok": True}, "system"))
        register_tool(Tool("email.unread", RISK_INFO, "Unread emails", _lazy(".domain", "unread_count"), "email"))
        register_tool(Tool("calendar.today", RISK_INFO, "Today's events", _lazy(".calendar_sync", "todays_events"), "calendar"))
        register_tool(Tool("calendar.week", RISK_INFO, "Week events", _lazy(".calendar_sync", "week_events"), "calendar"))
        register_tool(Tool("proactive.scan", RISK_INFO, "Scan opportunities", _lazy(".proactive", "scan"), "proactive"))
        register_tool(Tool("home.entities", RISK_INFO, "Home entities", _lazy(".homeassistant", "list_entities"), "home"))
        register_tool(Tool("vision.look", RISK_INFO, "Analyze image", _lazy(".vision", "analyze_image"), "vision"))
        register_tool(Tool("web.fetch", RISK_INFO, "Fetch web page", _lazy(".browse", "fetch"), "web"))
        register_tool(Tool("web.search", RISK_INFO, "Search web", _lazy(".browse", "search"), "web"))
        register_tool(Tool("scripts.list", RISK_INFO, "List scripts", _lazy(".terminal", "list_scripts"), "scripts"))
        register_tool(Tool("feeds.latest", RISK_INFO, "Latest feed items", _lazy(".feeds", "latest"), "feeds"))
        register_tool(Tool("weather.now", RISK_INFO, "Current weather", _lazy(".weather", "now"), "weather"))

        # Risk R1 (local write)
        register_tool(Tool("tasks.create", RISK_LOCAL_WRITE, "Create task", _wrap_model(".domain", "create_task", "TaskIn"), "tasks"))
        register_tool(Tool("tasks.update", RISK_LOCAL_WRITE, "Update task", _lazy(".domain", "update_task"), "tasks"))
        register_tool(Tool("clients.create", RISK_LOCAL_WRITE, "Create client", _wrap_model(".domain", "create_client", "ClientIn"), "clients"))
        register_tool(Tool("projects.create", RISK_LOCAL_WRITE, "Create project", _wrap_model(".domain", "create_project", "ProjectIn"), "projects"))
        register_tool(Tool("projects.update", RISK_LOCAL_WRITE, "Update project", _lazy(".domain", "update_project"), "projects"))
        register_tool(Tool("memory.store", RISK_LOCAL_WRITE, "Store memory", _lazy(".domain", "store_memory"), "memory"))
        register_tool(Tool("personal.log_mood", RISK_LOCAL_WRITE, "Log mood", _wrap_model(".domain", "log_mood_impl", "MoodIn"), "personal"))
        register_tool(Tool("personal.log_sleep", RISK_LOCAL_WRITE, "Log sleep", _wrap_model(".domain", "log_sleep_impl", "SleepIn"), "personal"))
        register_tool(Tool("personal.add_expense", RISK_LOCAL_WRITE, "Add expense", _wrap_model(".domain", "add_expense_impl", "ExpenseIn"), "personal"))
        register_tool(Tool("personal.journal", RISK_LOCAL_WRITE, "Write journal", _wrap_model(".domain", "journal_entry_impl", "JournalIn"), "personal"))
        register_tool(Tool("schedule.plan_day", RISK_LOCAL_WRITE, "Plan day", lambda a, ctx: [], "schedule"))
        register_tool(Tool("system.backup", RISK_LOCAL_WRITE, "Run backup", _lazy(".backup", "run_backup"), "system"))
        register_tool(Tool("system.undo", RISK_LOCAL_WRITE, "Undo last action", _lazy(".sync", "undo_last"), "system"))
        register_tool(Tool("automations.create", RISK_LOCAL_WRITE, "Create automation", _t_automation_create, "automations"))
        register_tool(Tool("email.sync", RISK_LOCAL_WRITE, "Sync email", _lazy(".mailbox", "sync_account"), "email"))
        register_tool(Tool("email.triage", RISK_LOCAL_WRITE, "Triage email", _lazy(".mailbox", "triage_unread"), "email"))
        register_tool(Tool("calendar.create", RISK_LOCAL_WRITE, "Create event", _lazy(".calendar_sync", "create_event"), "calendar"))
        register_tool(Tool("home.control", RISK_LOCAL_WRITE, "Control home", _lazy(".homeassistant", "control"), "home"))
        register_tool(Tool("scripts.save", RISK_LOCAL_WRITE, "Save script", _lazy(".terminal", "save_script"), "scripts"))
        register_tool(Tool("ollama.set_default", RISK_LOCAL_WRITE, "Set default Ollama model", _lazy(".ollama_sync", "set_default"), "ollama"))
        register_tool(Tool("feeds.follow", RISK_LOCAL_WRITE, "Follow feed", _lazy(".feeds", "add"), "feeds"))

        # Risk R2 (external, needs approval)
        register_tool(Tool("comms.send", RISK_EXTERNAL, "Send message via gateway (approval-gated)", _t_send_message, "comms"))
        register_tool(Tool("email.send", RISK_EXTERNAL, "Send email (approval-gated)", _t_email_send, "email"))
        register_tool(Tool("calendar.invite", RISK_EXTERNAL, "Invite to event (approval-gated)", _lazy(".calendar_sync", "create_event"), "calendar"))
        register_tool(Tool("briefing.now", RISK_EXTERNAL, "Run briefing now", _lazy(".briefing", "run_briefing"), "briefing"))
        register_tool(Tool("ollama.models", RISK_EXTERNAL, "List Ollama models (external)", _lazy(".ollama_sync", "list_models"), "ollama"))

        # Risk R3 (destructive, needs approval)
        register_tool(Tool("system.run", RISK_DESTRUCTIVE, "Run terminal command (approval-gated)", _t_terminal_run, "terminal"))
        register_tool(Tool("scripts.run", RISK_DESTRUCTIVE, "Run script (approval-gated)", _t_script_run, "scripts"))

        # Risk R4 (prohibited)
        # None currently

    def list_tools(self) -> dict:
        return {"tools": [{"name": n, "risk": t.risk, "description": t.description, "domain": t.domain} for n, t in TOOLS.items()]}

    def execute_tool(self, name: str, args: dict, ctx: dict, run_id: int = 0) -> dict:
        if name not in TOOLS:
            return {"ok": False, "error": f"tool not found: {name}"}
        tool = TOOLS[name]
        if tool.risk in (RISK_DESTRUCTIVE, RISK_PROHIBITED):
            return {"ok": False, "error": f"tool {name} requires approval flow"}
        try:
            result = tool.fn(args, ctx)
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def execute_dry_run(self, name: str, args: dict, ctx: dict) -> dict:
        from . import db
        with db.preview():
            return self.execute_tool(name, args, ctx, 0)

    def run_skill(self, skill: str, args: dict, ctx: dict) -> dict:
        if skill not in ("client_followup", "meeting_prep", "morning_brief"):
            return {"ok": False, "error": "unknown skill"}
        return {"ok": True, "data": "skill stub"}

    def tick_automations(self) -> None:
        from . import db
        # Fire due automations
        rows = db.q("SELECT * FROM automations WHERE user_id=1 AND status='active' AND next_run IS NOT NULL AND next_run <= datetime('now') LIMIT 10")
        for a in rows:
            trigger = db.jload(a.get("trigger_config"), {})
            action = db.jload(a.get("action_config"), {})
            kind = a.get("action_kind")
            # Update next_run
            if trigger.get("kind") == "schedule":
                from datetime import datetime, timedelta, timezone
                every = trigger.get("every")
                if every == "hourly":
                    nxt = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                elif every == "daily":
                    nxt = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                elif every == "weekly":
                    days = 7 - datetime.now(timezone.utc).weekday()
                    if days == 0:
                        days = 7
                    nxt = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    nxt = ""
                db.run("UPDATE automations SET next_run=? WHERE id=?", (nxt, a["id"]))
            # Fire action
            try:
                if kind == "notify":
                    from . import comms
                    comms.send(action.get("platform", "email"), action.get("to", ""), action.get("subject", ""), action.get("text", ""))
                elif kind == "backup":
                    from . import backup
                    backup.run_backup(action.get("target", "local"))
                elif kind == "chat":
                    from . import comms
                    comms.send("chat", action.get("text", ""))
                elif kind == "webhook":
                    _fire_webhook(a.get("webhook_url", ""), action.get("payload", {}))
                elif kind == "brief":
                    from . import briefing
                    briefing.run_briefing(action)
                elif kind == "proactive":
                    from . import proactive
                    proactive.scan()
                elif kind == "terminal":
                    from . import terminal
                    terminal.exec_command(action.get("command", ""), source="automation")
                elif kind == "home":
                    from . import homeassistant
                    homeassistant.control(action.get("entity"), action.get("action"))
                elif kind == "script":
                    from . import scripts
                    scripts.run_script(action.get("script_id"), source="automation", args=action.get("args"))
            except Exception:
                pass
            db.run("UPDATE automations SET last_run=datetime('now'), next_run=? WHERE id=?", (trigger.get("next_run", ""), a["id"]))

    @property
    def version(self) -> str:
        return self._version

    def recent_events(self, limit: int = 20) -> list[dict]:
        from . import db
        rows = db.q("SELECT * FROM activity WHERE user_id=1 ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def emit_gateway(self, platform: str, message: str, actor: str = "aura", direction: str = "out", payload: dict = None) -> dict:
        from . import db
        db.log_activity("gateway", platform, message, "general")
        return {"ok": True}

    def dry_fire(self, approval_id: int) -> dict:
        from . import db
        row = db.qone("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            return {"ok": False, "error": "approval not found"}
        detail = db.jload(row["detail_json"], {})
        drafts = detail.get("drafts", [])
        from . import comms
        for d in drafts:
            comms.send(detail.get("channel", "email"), d.get("to", ""), d.get("subject", ""), d.get("body", ""))
        db.run("UPDATE approvals SET status='approved', resolved_at=datetime('now') WHERE id=?", (approval_id,))
        return {"ok": True, "sent": len(drafts)}


# ------------------------------------------------------------ pseudo-tools ---
def _t_send_message(a: dict, ctx: dict) -> Any:
    from . import comms
    return comms.send(a.get("platform", "email"), a.get("to", ""), a.get("subject", ""), a.get("text", ""))


def _t_email_send(a: dict, ctx: dict) -> Any:
    from . import mailbox
    return mailbox.send_email(a.get("to", ""), a.get("subject", ""), a.get("text", ""), a.get("account_id"))


def _t_cal_invite(a: dict, ctx: dict) -> Any:
    from . import calendar_sync
    return calendar_sync.create_event(a.get("calendar_id"), a.get("title", ""), a.get("starts_at", ""), a.get("ends_at", ""), a.get("attendees", []))


def _t_terminal_run(a: dict, ctx: dict) -> Any:
    from . import terminal
    return terminal.exec_command(a.get("command", ""), source="hermes")


def _t_script_run(a: dict, ctx: dict) -> Any:
    from . import scripts
    return scripts.run_script(a.get("script_id"), source="hermes", args=a.get("args", {}))


def _t_automation_create(a: dict, ctx: dict) -> Any:
    from . import db
    name = a.get("name", "Automation")
    trigger_kind = a.get("trigger_kind", "schedule")
    trigger_config = a.get("trigger", a.get("trigger_config", {}))
    action_kind = a.get("action_kind", "notify")
    action_config = a.get("action", a.get("action_config", {}))
    if isinstance(trigger_config, dict):
        import json as _json
        trigger_config = _json.dumps(trigger_config)
    if isinstance(action_config, dict):
        import json as _json
        action_config = _json.dumps(action_config)
    auto_id = db.run(
        "INSERT INTO automations (name, trigger_kind, trigger_config, action_kind, action_config, status, next_run) VALUES (?,?,?,?,?,?,?)",
        (name, trigger_kind, trigger_config, action_kind, action_config, "active", _next_run({"every": "daily"})))
    row = db.qone("SELECT * FROM automations WHERE id=?", (auto_id,))
    return dict(row) if row else {"ok": True, "id": auto_id}


def _fire_webhook(url: str, payload: dict) -> dict:
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _next_run(trigger: dict) -> str:
    from datetime import datetime, timedelta, timezone
    every = trigger.get("every")
    if every == "hourly":
        return (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    if every == "daily":
        return (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if every == "weekly":
        days = 7 - datetime.now(timezone.utc).weekday()
        if days == 0:
            days = 7
        return (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return ""


# ------------------------------------------------------------ parse_sleep_text ---
def parse_sleep_text(text: str) -> dict:
    """Parse sleep text like 'slept 11pm to 6am' or 'log sleep 7.5 hours'."""
    import re
    text = text.lower().strip()
    
    # Pattern: "slept X to Y" or "slept X Y" (e.g., "slept 11pm to 6am", "slept 11pm 6am")
    m = re.search(r"slept\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-|until)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text)
    if m:
        bedtime_str, wake_str = m.group(1), m.group(2)
        # Parse times - simplified, assume today's date
        try:
            from datetime import datetime, date, timedelta
            today = date.today()
            bedtime = datetime.strptime(f"{today} {bedtime_str.strip()}", "%Y-%m-%d %I%p").replace(second=0, microsecond=0) if 'am' in bedtime_str or 'pm' in bedtime_str else datetime.strptime(f"{today} {bedtime_str.strip()}", "%Y-%m-%d %H:%M")
            wake_at = datetime.strptime(f"{today} {wake_str.strip()}", "%Y-%m-%d %I%p").replace(second=0, microsecond=0) if 'am' in wake_str or 'pm' in wake_str else datetime.strptime(f"{today} {wake_str.strip()}", "%Y-%m-%d %H:%M")
            # If wake time is before bedtime, it's next day
            if wake_at <= bedtime:
                wake_at += timedelta(days=1)
            hours = (wake_at - bedtime).total_seconds() / 3600
            return {"parsed": True, "hours": round(hours, 1), "bedtime": bedtime.strftime("%H:%M"), "wake_at": wake_at.strftime("%H:%M")}
        except Exception:
            pass
    
    # Pattern: "log sleep X hours" or "slept X hours"
    m = re.search(r"(?:log\s+sleep|slept)\s+(\d+(?:\.\d+)?)\s*hours?", text)
    if m:
        hours = float(m.group(1))
        return {"parsed": True, "hours": hours}
    
    # Pattern: "sleep X hours"
    m = re.search(r"\bsleep\s+(\d+(?:\.\d+)?)\s*hours?", text)
    if m:
        hours = float(m.group(1))
        return {"parsed": True, "hours": hours}
    
    return {"parsed": False, "hint": "try 'slept 11pm to 6am' or 'log sleep 7.5 hours'"}


def start_scheduler_loop() -> None:
    """Start the 30-second scheduler loop for automations and briefings."""
    def _loop():
        interval_s = 30
        while True:
            try:
                hermes.tick_automations()
            except Exception:
                traceback.print_exc()
            try:
                db.run("UPDATE approvals SET status='expired' WHERE status='pending' AND expires_at IS NOT NULL AND expires_at <= datetime('now')")
            except Exception:
                pass
            time.sleep(interval_s)

    threading.Thread(target=_loop, daemon=True, name="aura-scheduler").start()


# ------------------------------------------------------------ singleton ---
hermes = HermesAdapter()

# Plugin status (populated on module load)
PLUGIN_STATUS = load_plugins()


# Exports
__all__ = [
    "hermes",
    "HermesAdapter",
    "Tool",
    "TOOLS",
    "RISK_INFO",
    "RISK_LOCAL_WRITE",
    "RISK_EXTERNAL",
    "RISK_DESTRUCTIVE",
    "RISK_PROHIBITED",
    "PLUGIN_STATUS",
    "register_tool",
    "load_plugins",
    "start_scheduler_loop",
    "parse_sleep_text",
]