"""Hermes tool runtime — deterministic tool execution with approval gates.

Provides a registry of tools (R0-R4 risk levels), execution pipeline,
approval gating, plugin loading, and the 30s scheduler loop.
"""
from __future__ import annotations

import importlib
import json
import re
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
    # Anchor the bundled plugin dir to this package, not the process CWD — a
    # relative "app/plugins" silently loaded zero plugins whenever the server
    # was started from anywhere other than backend/.
    bases = [Path(__file__).resolve().parent / "plugins", config.DATA_DIR / "plugins"]
    for base in bases:
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
    return scripts.run(a.get("script_id"), source="hermes", args=a.get("args", {}))


def _t_automation_create(a: dict, ctx: dict) -> Any:
    from . import db
    name = a.get("name", "Automation")
    trigger_kind = a.get("trigger_kind", "schedule")
    trigger_config = a.get("trigger", a.get("trigger_config", {}))
    action_kind = a.get("action_kind", "notify")
    action_config = a.get("action", a.get("action_config", {}))
    if trigger_kind not in TRIGGER_KINDS:
        raise ValueError("trigger_kind must be one of " + ", ".join(TRIGGER_KINDS))
    if not isinstance(trigger_config, dict):
        raise ValueError("trigger must be an object")
    # Validate before persisting: an automation is a standing instruction to run
    # later, so a malformed or dangerous config must never reach the table.
    validate_action(action_kind, action_config)
    next_run = a.get("next_run") or _next_run(trigger_config, trigger_kind)
    import json as _json
    trigger_config = _json.dumps(trigger_config)
    if isinstance(action_config, dict):
        action_config = _json.dumps(action_config)
    auto_id = db.run(
        "INSERT INTO automations (name, trigger_kind, trigger_config, action_kind, action_config, status, next_run) VALUES (?,?,?,?,?,?,?)",
        (name, trigger_kind, trigger_config, action_kind, action_config, "active", next_run))
    row = db.qone("SELECT * FROM automations WHERE id=?", (auto_id,))
    return dict(row) if row else {"ok": True, "id": auto_id}



_ROLE_HINT = re.compile(
    r"\b(?:for|as)\s+(?:an?\s+)?([A-Za-z][A-Za-z /-]{2,40}?)\s+"
    r"(?:role|position|job|interview|career)\b",
    re.I,
)


def extract_role(text: str) -> str:
    """Best-effort job role from free chat text. '' when nothing is recognisable.

    Deliberately conservative: AURA must not invent a role, so it returns an
    empty string rather than guessing, and the caller falls back to a default.
    """
    t = (text or "").strip()
    m = _ROLE_HINT.search(t)
    if m:
        role = m.group(1).strip(" -/")
        if role and len(role) <= 40:
            return role.title()
    return ""


def _tool_interview_questions(a: dict, ctx: dict) -> Any:
    from . import career as _career
    text = (a.get("text") or a.get("job_description") or "").strip()
    role = (a.get("role") or extract_role(text) or "Software Engineer").strip()
    return _career.interview_questions(text, role)


def _tool_proactive_scan(a: dict, ctx: dict) -> Any:
    from . import proactive as _pro
    persist = a.get("persist", True)
    items = _pro.scan(persist=bool(persist))
    try:
        limit = int(a.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit > 0:
        items = items[:limit]
    return {"opportunities": items, "count": len(items)}


def _tool_home_entities(a: dict, ctx: dict) -> Any:
    from . import homeassistant as _ha
    domain = (a.get("domain") or "").strip()
    if domain and not _HOME_TOKEN.match(domain):
        return {"error": "home domain contains invalid characters"}
    res = _ha.states()
    if domain:
        res = {**res, "entities": [e for e in res.get("entities", [])
                                   if str(e.get("entity_id", "")).startswith(domain + ".")]}
    return res


def _tool_home_control(a: dict, ctx: dict) -> Any:
    from . import homeassistant as _ha
    try:
        _validate_home_action(a)
    except ValueError as e:
        return {"error": str(e)}
    return _ha.call_service(a.get("domain", ""), a.get("service", ""),
                            a.get("entity_id") or a.get("entity", ""),
                            a.get("data") or None)


def _tool_scripts_save(a: dict, ctx: dict) -> Any:
    from . import scripts as _scripts
    name = (a.get("name") or "").strip()
    command = (a.get("command") or "").strip()
    if not name:
        return {"error": "script name required"}
    if not command:
        return {"error": "script command required"}
    return _scripts.save(name, command, machine=(a.get("machine") or "local"),
                         description=(a.get("description") or ""))


def _tool_system_backup(a: dict, ctx: dict) -> Any:
    from . import backup as _backup
    from . import db as _db
    target = a.get("target") or "local"
    if _db.DRY_RUN:
        # A backup writes files and a backups row — both suppressed in preview.
        _db.blocked(f"backup: would create archive in {target} mode")
        return {"dry_run": True, "would": f"backup: {target}"}
    return _backup.run_backup(target)


def _tool_tasks_update(a: dict, ctx: dict) -> Any:
    from .domain import _update_task_impl
    task_id = a.get("task_id") or a.get("id")
    if task_id is None:
        return {"error": "task_id required"}
    fields = {k: v for k, v in a.items() if k not in ("task_id", "id")}
    if not fields:
        return {"error": "no fields to update"}
    return _update_task_impl(task_id, **fields)


def _tool_projects_update(a: dict, ctx: dict) -> Any:
    from .domain import update_project
    pid = a.get("project_id") or a.get("id")
    if pid is None:
        return {"error": "project_id required"}
    patch = a.get("patch") or {k: v for k, v in a.items() if k not in ("project_id", "id", "patch")}
    if not isinstance(patch, dict) or not patch:
        return {"error": "patch required (object of fields to change)"}
    return update_project(pid, patch)


def _tool_briefing_now(a: dict, ctx: dict) -> Any:
    from . import briefing
    kind = (a.get("kind") or "morning").strip().lower()
    if kind not in BRIEF_KINDS:
        return {"error": "brief kind must be one of " + ", ".join(BRIEF_KINDS)}
    return briefing.run_briefing(a.get("briefing_id"), kind=kind,
                                  extra=(a.get("prompt") or a.get("extra") or ""))


def _tool_web_fetch(a: dict, ctx: dict) -> Any:
    from . import browse
    url = (a.get("url") or "").strip()
    if not url:
        return {"error": "url required"}
    return browse.fetch(url)


def _tool_web_search(a: dict, ctx: dict) -> Any:
    from . import browse
    query = (a.get("query") or "").strip()
    if not query:
        return {"error": "query required"}
    return browse.search(query, limit=a.get("limit") or 5)


# vision.look accepts base64 rather than raw bytes because tool args are JSON.
_MAX_IMAGE_B64 = 8_000_000


def _tool_vision_look(a: dict, ctx: dict) -> Any:
    import base64
    import binascii
    raw = a.get("image_b64") or ""
    if not isinstance(raw, str) or not raw.strip():
        return {"error": "image_b64 required (base64-encoded image, no data: prefix)"}
    if len(raw) > _MAX_IMAGE_B64:
        return {"error": f"image too large (max {_MAX_IMAGE_B64} base64 chars)"}
    if "," in raw[:64] and raw.strip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {"error": "image_b64 is not valid base64"}
    from . import vision
    return vision.analyze_image(data, a.get("mime") or "image/png",
                                (a.get("question") or "")[:500])


ACTION_KINDS = ["notify", "chat", "webhook", "brief", "proactive", "terminal", "home", "script"]

TRIGGER_KINDS = ["schedule", "event", "manual", "feed", "file"]

BRIEF_KINDS = ["morning", "evening", "weekly", "custom"]

# Home Assistant identifiers are `domain.object_id`; nothing else is ever accepted.
# This blocks shell/SQL-ish metacharacters reaching the gateway.
_HOME_TOKEN = re.compile(r"^[A-Za-z0-9_]+$")
_HOME_ENTITY = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def validate_webhook_action(cfg: dict) -> None:
    """Raise ValueError if a webhook action config is unsafe or malformed.

    https is required for any real remote target. Plain http is permitted only
    for loopback, so a self-hosted integration on the same box still works
    without letting cleartext leave the machine.
    """
    if not isinstance(cfg, dict):
        raise ValueError("webhook action must be an object")
    url = (cfg.get("url") or "").strip()
    if not url:
        raise ValueError("webhook action requires a url")
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("webhook url must include a host")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
            pass
        else:
            raise ValueError("webhook url must use https")
    payload = cfg.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("webhook payload must be an object")
    secret = cfg.get("secret", "")
    if secret and not isinstance(secret, str):
        raise ValueError("webhook secret must be a string")


def _validate_brief_action(cfg: dict) -> None:
    if not isinstance(cfg, dict):
        raise ValueError("brief action must be an object")
    kind = (cfg.get("kind") or "morning").strip().lower()
    if kind not in BRIEF_KINDS:
        raise ValueError("brief kind must be one of " + ", ".join(BRIEF_KINDS))
    if kind == "custom" and not (cfg.get("prompt") or "").strip():
        raise ValueError("brief kind 'custom' requires a prompt")


def _validate_terminal_action(cfg: dict) -> None:
    """Refuse to persist a dangerous command as an automation action."""
    if not isinstance(cfg, dict):
        raise ValueError("terminal action must be an object")
    command = (cfg.get("command") or "").strip()
    if not command:
        raise ValueError("terminal action requires a command")
    from . import terminal as _terminal
    risk, why = _terminal.classify(command)
    if risk == "dangerous":
        raise ValueError(f"refused — dangerous command: {why}")


def _validate_script_action(cfg: dict) -> None:
    """Resolve the referenced script now, so a standing automation can never
    point at a script that has since been deleted."""
    if not isinstance(cfg, dict):
        raise ValueError("script action must be an object")
    ref = cfg.get("script_id", cfg.get("name", cfg.get("script")))
    if ref is None or ref == "":
        raise ValueError("script action requires script_id or name")
    from . import scripts as _scripts
    try:
        found = _scripts.get(ref)
    except Exception as e:
        raise ValueError(f"unknown script: {ref}") from e
    if not found:
        raise ValueError(f"unknown script: {ref}")
    args = cfg.get("args", {})
    if args is not None and not isinstance(args, dict):
        raise ValueError("script args must be an object")


def _validate_home_action(cfg: dict) -> None:
    if not isinstance(cfg, dict):
        raise ValueError("home action must be an object")
    for key in ("domain", "service", "action"):
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise ValueError(f"home {key} must be a string")
        if not val or not _HOME_TOKEN.match(val):
            raise ValueError(f"home {key} contains invalid characters")
    for key in ("entity_id", "entity"):
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, str) or not _HOME_ENTITY.match(val):
            raise ValueError("home entity must be 'domain.object_id'")


# action_kind -> validator. Anything not listed accepts any object config.
_ACTION_VALIDATORS = {
    "webhook": validate_webhook_action,
    "brief": _validate_brief_action,
    "terminal": _validate_terminal_action,
    "home": _validate_home_action,
    "script": _validate_script_action,
}


def validate_action(action_kind: str, action_config: Any) -> None:
    """Validate an automation action config for the given kind. Raises ValueError."""
    if action_kind not in ACTION_KINDS:
        raise ValueError("action_kind must be one of " + ", ".join(ACTION_KINDS))
    if not isinstance(action_config, dict):
        raise ValueError(f"{action_kind} action must be an object")
    validator = _ACTION_VALIDATORS.get(action_kind)
    if validator is not None:
        validator(action_config)


def _sign(secret: str, body: bytes) -> str:
    import hmac
    import hashlib
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def fire_webhook(automation_id: Any, trigger_kind: str, action: dict,
                 fire_id: str | None = None) -> dict:
    """POST a signed automation event. Returns {ok, status|error}.

    The body is signed with HMAC-SHA256 over the exact bytes sent so the
    receiver can verify integrity, and carries an idempotency key so a retry
    after a timeout cannot double-fire a downstream side effect.
    """
    action = action if isinstance(action, dict) else {}
    validate_webhook_action(action)
    event = {
        "event": "automation.fired",
        "automation_id": automation_id,
        "trigger": trigger_kind,
        "data": action.get("payload") or {},
    }
    if fire_id:
        event["idempotency_key"] = fire_id
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "X-Aura-Event": "automation.fired"}
    if fire_id:
        headers["X-Aura-Idempotency-Key"] = fire_id
    secret = action.get("secret") or ""
    if secret:
        headers["X-Aura-Signature"] = _sign(secret, body)
    try:
        r = httpx.post(action["url"], content=body, headers=headers, timeout=10.0)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _next_run(trigger: dict, kind: str = "schedule") -> str | None:
    """Next fire time for a trigger. Non-schedule triggers are one-shot: None.

    Returning a timestamp for `feed`/`file`/`manual`/`event` would make the
    scheduler re-fire a one-shot trigger forever, so those never get one.
    """
    if (kind or "schedule") != "schedule":
        return None
    from datetime import datetime, timedelta, timezone
    every = (trigger or {}).get("every")
    now = datetime.now(timezone.utc)
    if every == "hourly":
        return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    if every == "daily":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if every == "weekly":
        days = 7 - now.weekday()
        if days == 0:
            days = 7
        return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return None


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
        register_tool(Tool("career.interview_questions", RISK_INFO, "Generate interview questions", _tool_interview_questions, "career"))
        register_tool(Tool("schedule.blocks", RISK_INFO, "Get time blocks", lambda a, ctx: [], "schedule"))
        register_tool(Tool("comms.draft_followups", RISK_INFO, "Draft follow-ups", _lazy(".domain", "draft_followups"), "comms"))
        register_tool(Tool("system.status", RISK_INFO, "System status", lambda a, ctx: {"ok": True}, "system"))
        register_tool(Tool("email.unread", RISK_INFO, "Unread emails", _lazy(".domain", "unread_count"), "email"))
        register_tool(Tool("calendar.today", RISK_INFO, "Today's events", _lazy(".calendar_sync", "todays_events"), "calendar"))
        register_tool(Tool("calendar.week", RISK_INFO, "Week events", _lazy(".calendar_sync", "week_events"), "calendar"))
        register_tool(Tool("proactive.scan", RISK_INFO, "Scan opportunities", _tool_proactive_scan, "proactive"))
        register_tool(Tool("home.entities", RISK_INFO, "Home entities", _tool_home_entities, "home"))
        register_tool(Tool("vision.look", RISK_INFO, "Analyze image", _tool_vision_look, "vision"))
        register_tool(Tool("web.fetch", RISK_INFO, "Fetch web page", _tool_web_fetch, "web"))
        register_tool(Tool("web.search", RISK_INFO, "Search web", _tool_web_search, "web"))
        register_tool(Tool("scripts.list", RISK_INFO, "List scripts", _lazy(".scripts", "list_scripts"), "scripts"))
        register_tool(Tool("feeds.latest", RISK_INFO, "Latest feed items", _lazy(".feeds", "latest"), "feeds"))
        register_tool(Tool("weather.now", RISK_INFO, "Current weather", _lazy(".weather", "current"), "weather"))

        # Risk R1 (local write)
        register_tool(Tool("tasks.create", RISK_LOCAL_WRITE, "Create task", _wrap_model(".domain", "create_task", "TaskIn"), "tasks"))
        register_tool(Tool("tasks.update", RISK_LOCAL_WRITE, "Update task", _tool_tasks_update, "tasks"))
        register_tool(Tool("clients.create", RISK_LOCAL_WRITE, "Create client", _wrap_model(".domain", "create_client", "ClientIn"), "clients"))
        register_tool(Tool("projects.create", RISK_LOCAL_WRITE, "Create project", _wrap_model(".domain", "create_project", "ProjectIn"), "projects"))
        register_tool(Tool("projects.update", RISK_LOCAL_WRITE, "Update project", _tool_projects_update, "projects"))
        register_tool(Tool("memory.store", RISK_LOCAL_WRITE, "Store memory", _lazy(".domain", "store_memory"), "memory"))
        register_tool(Tool("personal.log_mood", RISK_LOCAL_WRITE, "Log mood", _wrap_model(".domain", "log_mood_impl", "MoodIn"), "personal"))
        register_tool(Tool("personal.log_sleep", RISK_LOCAL_WRITE, "Log sleep", _wrap_model(".domain", "log_sleep_impl", "SleepIn"), "personal"))
        register_tool(Tool("personal.add_expense", RISK_LOCAL_WRITE, "Add expense", _wrap_model(".domain", "add_expense_impl", "ExpenseIn"), "personal"))
        register_tool(Tool("personal.journal", RISK_LOCAL_WRITE, "Write journal", _wrap_model(".domain", "journal_entry_impl", "JournalIn"), "personal"))
        register_tool(Tool("schedule.plan_day", RISK_LOCAL_WRITE, "Plan day", lambda a, ctx: [], "schedule"))
        register_tool(Tool("system.backup", RISK_LOCAL_WRITE, "Run backup", _tool_system_backup, "system"))
        register_tool(Tool("system.undo", RISK_LOCAL_WRITE, "Undo last action", _lazy(".undo", "undo_last"), "system"))
        register_tool(Tool("automations.create", RISK_LOCAL_WRITE, "Create automation", _t_automation_create, "automations"))
        register_tool(Tool("email.sync", RISK_LOCAL_WRITE, "Sync email", _lazy(".mailbox", "sync_account"), "email"))
        register_tool(Tool("email.triage", RISK_LOCAL_WRITE, "Triage email", _lazy(".mailbox", "triage_unread"), "email"))
        register_tool(Tool("calendar.create", RISK_LOCAL_WRITE, "Create event", _lazy(".calendar_sync", "create_event"), "calendar"))
        register_tool(Tool("home.control", RISK_LOCAL_WRITE, "Control home", _tool_home_control, "home"))
        register_tool(Tool("scripts.save", RISK_LOCAL_WRITE, "Save script", _tool_scripts_save, "scripts"))
        register_tool(Tool("ollama.set_default", RISK_LOCAL_WRITE, "Set default Ollama model", _lazy(".ollama_sync", "set_default"), "ollama"))
        register_tool(Tool("feeds.follow", RISK_LOCAL_WRITE, "Follow feed", _lazy(".feeds", "add"), "feeds"))

        # Risk R2 (external, needs approval)
        register_tool(Tool("comms.send", RISK_EXTERNAL, "Send message via gateway (approval-gated)", _t_send_message, "comms"))
        register_tool(Tool("email.send", RISK_EXTERNAL, "Send email (approval-gated)", _t_email_send, "email"))
        register_tool(Tool("calendar.invite", RISK_EXTERNAL, "Invite to event (approval-gated)", _lazy(".calendar_sync", "create_event"), "calendar"))
        # R1, not R2: a briefing composes locally and notifies the owner on their
        # own device. It sends nothing to a third party, so it must not require
        # an external-call approval.
        register_tool(Tool("briefing.now", RISK_LOCAL_WRITE, "Run briefing now", _tool_briefing_now, "briefing"))
        register_tool(Tool("ollama.models", RISK_EXTERNAL, "List Ollama models (external)", _lazy(".ollama_sync", "list_models"), "ollama"))

        # Risk R3 (destructive, needs approval)
        register_tool(Tool("system.run", RISK_DESTRUCTIVE, "Run terminal command (approval-gated)", _t_terminal_run, "terminal"))
        register_tool(Tool("scripts.run", RISK_DESTRUCTIVE, "Run script (approval-gated)", _t_script_run, "scripts"))

        # Risk R4 (prohibited)
        # None currently

    def list_tools(self) -> list[dict]:
        """Every registered tool as {name, risk, description, domain}."""
        return [{"name": n, "risk": t.risk, "description": t.description, "domain": t.domain}
                for n, t in TOOLS.items()]

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
        """Run a tool with every write and external effect suppressed.

        Returns {dry_run: True, ok, result, blocked, error?} where `blocked`
        lists the side effects that *would* have happened. Nothing is persisted.
        """
        from . import db
        with db.preview() as blocked:
            res = self.execute_tool(name, args, ctx, 0)
            blocked = list(blocked)
        out = {"dry_run": True, "ok": bool(res.get("ok")), "blocked": blocked}
        if res.get("ok"):
            out["result"] = res.get("data")
        else:
            out["error"] = res.get("error", "tool failed")
        return out

    def run_skill(self, skill: str, args: dict, ctx: dict) -> dict:
        if skill not in ("client_followup", "meeting_prep", "morning_brief"):
            return {"ok": False, "error": "unknown skill"}
        return {"ok": True, "data": "skill stub"}

    def _fire_one(self, a: dict, fire_id: str | None = None) -> dict:
        """Execute a single automation's action. Returns {ok, error?}."""
        action = db.jload(a.get("action_config"), {})
        kind = a.get("action_kind")
        if kind == "notify":
            from . import comms
            comms.send(action.get("platform", "email"), action.get("to", ""),
                       action.get("subject", ""), action.get("text", ""))
        elif kind == "chat":
            from . import comms
            comms.send("chat", action.get("text", ""))
        elif kind == "webhook":
            res = fire_webhook(a.get("id"), a.get("trigger_kind"), action, fire_id=fire_id)
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", "webhook failed")}
        elif kind == "brief":
            from . import briefing
            _validate_brief_action(action)
            briefing.run_briefing(action.get("briefing_id"),
                                  kind=(action.get("kind") or "morning"),
                                  extra=(action.get("prompt") or ""))
        elif kind == "proactive":
            from . import proactive
            # scan() alone only ranks; notify_top() is what actually surfaces the
            # top item to the user, and nothing else called it.
            proactive.notify_top(proactive.scan())
        elif kind == "terminal":
            from . import terminal
            _validate_terminal_action(action)
            res = terminal.exec_command(action.get("command", ""), source="automation")
            if isinstance(res, dict) and res.get("ok") is False:
                return {"ok": False, "error": res.get("error", "command refused")}
        elif kind == "home":
            from . import homeassistant
            _validate_home_action(action)
            homeassistant.control(action.get("entity_id") or action.get("entity"),
                                  action.get("service") or action.get("action"))
        elif kind == "script":
            from . import scripts
            scripts.run(action.get("script_id"), source="automation", args=action.get("args"))
        elif kind == "backup":
            from . import backup
            backup.run_backup(action.get("target", "local"))
        else:
            return {"ok": False, "error": f"unknown action_kind: {kind}"}
        return {"ok": True}

    def _reschedule(self, a: dict, trigger: dict, ok: bool) -> str | None:
        """Compute and persist the next fire time, backing off exponentially on failure.

        Returns the next_run value written (None means "do not fire again").
        """
        kind = a.get("trigger_kind", "schedule")
        if ok:
            if trigger.get("_retry_n"):
                # Recovered — drop the backoff state so a future failure
                # restarts from the first attempt rather than staying stuck.
                trigger.pop("_retry_n", None)
                db.run("UPDATE automations SET trigger_config=? WHERE id=?",
                       (db.jdump(trigger), a["id"]))
            return _next_run(trigger, kind)
        # Failure: retry with exponential backoff so a dead endpoint does not
        # hammer the network on every scheduler tick.
        from datetime import datetime, timedelta, timezone
        attempt = int(trigger.get("_retry_n") or 0) + 1
        trigger["_retry_n"] = attempt
        db.run("UPDATE automations SET trigger_config=? WHERE id=?",
               (db.jdump(trigger), a["id"]))
        if kind != "schedule" or attempt > 5:
            return None
        delay = min(2 ** attempt, 60)
        return (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat()

    def _record(self, a: dict, trigger: dict, res: dict) -> dict:
        """Persist the outcome of one fire: counters, last_run, next_run, audit."""
        from . import db
        ok = bool(res.get("ok"))
        next_run = self._reschedule(a, trigger, ok)
        db.run("UPDATE automations SET last_run=datetime('now'), next_run=?, "
               "success_count=success_count+?, fail_count=fail_count+? WHERE id=?",
               (next_run, 1 if ok else 0, 0 if ok else 1, a["id"]))
        if not ok:
            db.log_activity("automation", f"Automation failed: {a.get('name', '')}",
                            (res.get("error") or "unknown error")[:200], "general", "error")
        return {"id": a["id"], "ok": ok, "name": a.get("name", ""),
                **({"error": res["error"]} if not ok and res.get("error") else {})}

    def fire_event(self, a: dict, fire_id: str | None = None) -> dict:
        """Fire an event-triggered automation (file/feed) immediately.

        Event triggers never get a `next_run`, so they are invisible to
        `tick_automations`; they must go through here so the run is still
        counted and audited exactly like a scheduled fire.
        """
        from . import db
        trigger = db.jload(a.get("trigger_config"), {})
        try:
            res = self._fire_one(a, fire_id=fire_id)
        except Exception as e:
            res = {"ok": False, "error": str(e)[:200]}
        return self._record(a, trigger, res)

    def tick_automations(self) -> list[dict]:
        """Fire every due automation once. Returns one result per automation fired."""
        from . import db
        results: list[dict] = []
        # next_run is stored as ISO-8601 (or SQLite datetime for manual runs);
        # datetime(next_run) normalises both before comparing.
        rows = db.q("SELECT * FROM automations WHERE user_id=1 AND status='active' "
                    "AND next_run IS NOT NULL AND datetime(next_run) <= datetime('now') "
                    "ORDER BY next_run LIMIT 10")
        for a in rows:
            trigger = db.jload(a.get("trigger_config"), {})
            fire_id = f"auto-{a['id']}-{a.get('last_run') or 'first'}"
            try:
                res = self._fire_one(a, fire_id=fire_id)
            except Exception as e:
                res = {"ok": False, "error": str(e)[:200]}
            results.append(self._record(a, trigger, res))
        return results

    @property
    def version(self) -> str:
        return self._version

    def recent_events(self, limit: int = 20) -> list[dict]:
        """Recent gateway events, newest first, as {platform, actor, direction, text, ts}."""
        from . import db
        rows = db.q("SELECT id, platform, actor, direction, text, created_at ts "
                    "FROM gateway_events WHERE user_id=1 ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def emit_gateway(self, platform: str, message: str, actor: str = "aura",
                     direction: str = "out", payload: dict = None) -> dict:
        """Record a gateway message on the canonical event feed and the audit log.

        Returns the new event's id so callers (e.g. /api/gateway/simulate) can
        reference exactly what was recorded.
        """
        from . import db
        text = (message or "")[:500]
        eid = db.run("INSERT INTO gateway_events (user_id, platform, actor, direction, text, payload_json)"
                     " VALUES (1,?,?,?,?,?)",
                     (platform, actor, direction, text, db.jdump(payload or {})))
        db.log_activity("gateway", platform, text, "general")
        return {"ok": True, "event_id": eid, "platform": platform,
                "actor": actor, "direction": direction}

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
            def _parse_ampm(s: str) -> datetime:
                for fmt in ("%Y-%m-%d %I:%M%p", "%Y-%m-%d %I%p"):
                    try:
                        return datetime.strptime(f"{today} {s.strip()}", fmt).replace(second=0, microsecond=0)
                    except ValueError:
                        continue
                return datetime.strptime(f"{today} {s.strip()}", "%Y-%m-%d %H:%M")
            is_ampm = lambda s: 'am' in s or 'pm' in s
            bedtime = _parse_ampm(bedtime_str) if is_ampm(bedtime_str) else datetime.strptime(f"{today} {bedtime_str.strip()}", "%Y-%m-%d %H:%M")
            wake_at = _parse_ampm(wake_str) if is_ampm(wake_str) else datetime.strptime(f"{today} {wake_str.strip()}", "%Y-%m-%d %H:%M")
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
    "ACTION_KINDS",
    "fire_webhook",
]