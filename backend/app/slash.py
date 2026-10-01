"""Agentic slash commands (spec §3, FR-CMD-001..005).

A command is a deterministic Python handler, not a prompt. That is the whole
point: `/task Ship the plan` must create exactly one task without spending a
model call, so nothing here routes through the orchestrator.

`parse` matches only at position 0 — a `/` mid-sentence is prose, and treating
it as a command would silently eat part of the user's sentence.

`execute` never raises. A malformed or failing command is a *result* the caller
renders, not a 500 in the middle of a chat stream.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from . import db, prefs

# name -> {"name", "category", "summary", "example", "arg", "handler"}
CATALOG: list[dict] = []


def _cmd(name: str, category: str, summary: str, example: str, arg: str,
         handler: Callable[[str], dict]) -> None:
    CATALOG.append({"name": name, "category": category, "summary": summary,
                    "example": example, "arg": arg, "handler": handler})


def _need(args: str, usage: str) -> None:
    if not (args or "").strip():
        raise ValueError(f"Usage: {usage}")


def _pick(rows: list[dict], token: str, name_key: str, what: str) -> dict:
    """Resolve `token` against `rows`: exact id, then exact name, then a
    *unique* substring.

    The substring step refuses to guess. `/done client` with three candidates
    returns an error naming them rather than completing whichever row happened
    to come first — a loose match that silently completes the wrong task is
    worse than no match at all.
    """
    token = (token or "").strip()
    by_id = next((r for r in rows if str(r.get("id")) == token), None)
    if by_id is not None:
        return by_id
    low = token.lower()
    exact = [r for r in rows if str(r.get(name_key) or "").strip().lower() == low]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"{low!r} matches {len(exact)} {what} by name — use the id")
    partial = [r for r in rows if low and low in str(r.get(name_key) or "").lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(f"#{r.get('id')} {str(r.get(name_key))[:40]}" for r in partial[:5])
        raise ValueError(f"“{token}” matches {len(partial)} {what} ({names}) — use the id")
    raise ValueError(f"no {what} matching “{token}”")


# ---------------------------------------------------------------- memory ---

def _mem_store(args: str) -> dict:
    _need(args, "/remember <fact>")
    from .memory import memory_engine
    row = memory_engine.store(args[:72], args, "general", "semantic", "slash")
    row.pop("embedding_json", None)  # a 192-float vector is not output
    return {"memory": row}


def _mem_forget(args: str) -> dict:
    """Two-step delete: list the candidates, delete only on an explicit confirm.

    `_fts_query` OR-joins up to 12 tokens, so `/forget meeting` is *every*
    memory containing "meeting" — which is the correct answer to the question
    the user asked, and the wrong thing to do to their memory store on one
    keystroke. So a bare `/forget <topic>` reports and changes nothing, and the
    destructive half needs the literal word `confirm`:

        /forget meeting             -> 12 candidates, nothing deleted
        /forget meeting confirm     -> deletes exactly those 12

    Two-step rather than an interactive prompt so it behaves identically from
    chat and from the palette, where there is no shared modal to own.
    """
    _need(args, "/forget <topic> [confirm]")
    from .memory import memory_engine
    topic, _, tail = (args or "").strip().rpartition(" ")
    # Only a *trailing* `confirm` with something left over counts, so a topic
    # that happens to be the word "confirm" is still forgetable.
    if tail.strip().lower() == "confirm" and topic.strip():
        topic = topic.strip()
        # Capture the titles *before* the delete: after it, the rows are
        # soft-deleted and a second candidate query would return nothing, so the
        # user would be told how many went without being shown what.
        cands = memory_engine.forget_candidates(topic)
        n = memory_engine.forget_topic(topic)
        return {"forgotten": n, "titles": [c["title"] for c in cands], "confirmed": True}
    topic = (args or "").strip()
    cands = memory_engine.forget_candidates(topic)
    return {"forgotten": 0, "candidates": cands, "count": len(cands),
            "confirmed": False, "confirm_with": f"/forget {topic} confirm"}


def _mem_search(args: str) -> dict:
    _need(args, "/search <query>")
    from .memory import memory_engine
    return {"results": memory_engine.search(args, limit=8)}


def _mem_list(_args: str) -> dict:
    from .memory import memory_engine
    return {"stats": memory_engine.stats(),
            "recent": db.q("SELECT id,title,domain,mtype,importance FROM memories "
                           "WHERE user_id=1 AND deleted_at IS NULL ORDER BY id DESC LIMIT 10")}


# ----------------------------------------------------------------- tasks ---

def _tasks_create(args: str) -> dict:
    _need(args, "/task <title>")
    from .routes.tasks import TaskIn, create_task
    return {"task": create_task(TaskIn(title=args))}


def _tasks_list(_args: str) -> dict:
    from .routes.tasks import list_tasks
    return list_tasks(status="inbox")


def _tasks_done(args: str) -> dict:
    _need(args, "/done <task id or title>")
    from .routes.tasks import _update_task_impl, list_tasks
    # Only open tasks are candidates: re-completing a finished one by a loose
    # title match is how the wrong row gets closed.
    rows = [t for t in list_tasks()["tasks"]
            if str(t.get("status") or "") not in ("completed", "cancelled")]
    hit = _pick(rows, args, "title", "open task")
    return {"task": _update_task_impl(task_id=hit["id"], status="completed")}


# ------------------------------------------------------------ automation ---

def _mission_new(args: str) -> dict:
    _need(args, "/mission <goal>")
    from . import missions as _m
    return {"mission": _m.create_mission(args)}


def _mission_list(_args: str) -> dict:
    from . import missions as _m
    return {"missions": _m.list_missions(10)}


def _auto_run(args: str) -> dict:
    _need(args, "/run <automation name or id>")
    from .hermes import hermes
    # A paused automation is not runnable. tick_automations filters on the same
    # predicate, so `/run` must not be a way around it.
    rows = db.q("SELECT * FROM automations WHERE user_id=1 AND status='active'")
    hit = _pick(rows, args, "name", "active automation")
    return {"ran": hermes.fire_event(hit, fire_id=f"slash-{hit['id']}")}


# ---------------------------------------------------------------- system ---

def _status(_args: str) -> dict:
    from .health import system_status
    return {"status": system_status()}


def _health(_args: str) -> dict:
    from .config import DB_PATH
    from .health import system_status
    return {"status": system_status(),
            "db_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0}


def _backup(_args: str) -> dict:
    from .backup import run_backup
    return {"backup": run_backup()}  # additive: writes a new archive, deletes nothing


def _models(_args: str) -> dict:
    from . import ollama_sync
    return ollama_sync.list_models()


def _logs(_args: str) -> dict:
    return {"logs": db.q("SELECT id,kind,title,detail,created_at FROM activity "
                         "WHERE user_id=1 ORDER BY id DESC LIMIT 20")}


# -------------------------------------------------------------------- ai ---

def _think(args: str) -> dict:
    _need(args, "/think <prompt>")
    from .inference import router as _r
    if not _r.probe().get("local_lfm", {}).get("online"):
        raise ValueError("local model is offline — start Ollama, or use /ask")
    return {"text": _r.ollama.chat([{"role": "user", "content": args}], purpose="chat")}


def _ask(args: str) -> dict:
    _need(args, "/ask <model> <prompt>")
    parts = args.split(None, 1)
    if len(parts) < 2:
        raise ValueError("Usage: /ask <model> <prompt>")
    model, prompt = parts
    from .inference import router as _r
    return {"model": model,
            "text": _r.ollama.chat([{"role": "user", "content": prompt}],
                                   model=model, purpose="chat")}


def _switch(args: str) -> dict:
    _need(args, "/switch <model>")
    from . import ollama_sync
    # set_default validates against the *synced* catalog (falling back to a live
    # probe) before it writes, and it honours the `ollama_base_url` pref. Reaching
    # for /api/tags by hand here would have written a model AURA never verified.
    out = ollama_sync.set_default("chat", args.strip())
    return {"ollama_chat_model": out["model"], "role": out["role"]}


# ------------------------------------------------------------- registry ---

def _nav(view: str) -> Callable[[str], dict]:
    return lambda _args: {"view": view}


for _n, _v in (("/home", "home"), ("/career", "career"), ("/clients", "clients"),
               ("/personal", "personal"), ("/memory", "memory"), ("/voice", "voice"),
               ("/automations", "automations"), ("/settings", "settings")):
    _cmd(_n, "Navigation", f"Open {_v}", _n, "", _nav(_v))

_cmd("/remember", "Memory", "Store a fact", "/remember standup is at 9am", "text", _mem_store)
_cmd("/forget", "Memory", "Delete everything about a topic (needs: confirm)",
     "/forget old address confirm", "topic [+ confirm]", _mem_forget)
_cmd("/search", "Memory", "Hybrid search your memory", "/search invoice Zebra", "text", _mem_search)
_cmd("/memories", "Memory", "Counts and recent memories", "/memories", "", _mem_list)
_cmd("/task", "Tasks", "Create a task", "/task Review the PR", "text", _tasks_create)
_cmd("/tasks", "Tasks", "List inbox tasks", "/tasks", "", _tasks_list)
_cmd("/done", "Tasks", "Complete a task by id or title", "/done 42", "id or title", _tasks_done)
_cmd("/mission", "Automation", "Plan and create a mission", "/mission plan my week", "text", _mission_new)
_cmd("/missions", "Automation", "List missions", "/missions", "", _mission_list)
_cmd("/run", "Automation", "Run an automation now", "/run morning brief", "name or id", _auto_run)
_cmd("/status", "System", "System status", "/status", "", _status)
_cmd("/backup", "System", "Take a backup now", "/backup", "", _backup)
_cmd("/models", "System", "Show installed local models", "/models", "", _models)
_cmd("/health", "System", "Health plus database size", "/health", "", _health)
_cmd("/logs", "System", "Recent activity log", "/logs", "", _logs)
_cmd("/think", "AI", "One local-model answer, no tools, no memory write", "/think why is CI red", "text", _think)
_cmd("/ask", "AI", "Ask a specific model", "/ask llama3.1 summarise my day", "model + text", _ask)
_cmd("/switch", "AI", "Switch the local chat model", "/switch llama3.1:8b", "model", _switch)

_BY_NAME = {c["name"]: c for c in CATALOG}
CUSTOM_KEY = "slash_custom"


def _custom() -> list[dict]:
    try:
        v = prefs.get(CUSTOM_KEY)
    except Exception:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []


def _custom_view(c: dict) -> dict:
    return {"name": c.get("name", ""), "category": "Custom",
            "summary": str(c.get("prompt", ""))[:80],
            "example": c.get("name", ""), "arg": "text"}


def custom() -> list[dict]:
    return [dict(c) for c in _custom()]


# The frontend `View` union, mirrored from frontend/src/store.tsx. An
# unvalidated `view` here is not a cosmetic problem: App.tsx renders views with a
# `view === x` chain and no default branch, so one typo produced a blank main
# pane with no error anywhere. This mirrors the automation `entity_id` invariant
# (hermes.validate_action) — validate against a known set before persisting.
#
# A hardcoded list in Python will drift, so `test_slash.py` parses the union out
# of frontend/src/store.tsx and asserts the two sets are identical. That test is
# the sync mechanism, not a comment.
VIEWS = frozenset({
    "home", "career", "clients", "personal", "inbox", "calendar", "memory",
    "sessions", "voice", "gateway", "automations", "board", "activity",
    "analytics", "smarthome", "files", "models", "terminal", "feeds", "settings",
})


def save_custom(name: str, prompt: str, view: str = "") -> dict:
    name = (name or "").strip()
    if not name.startswith("/"):
        raise ValueError("custom command name must start with /")
    if any(ch.isspace() for ch in name):
        raise ValueError("custom command name cannot contain spaces")
    if name in _BY_NAME:
        raise ValueError(f"{name} is a built-in command")
    if not (prompt or "").strip():
        raise ValueError("custom command needs a prompt")
    view = (view or "").strip()
    if view and view not in VIEWS:
        raise ValueError(f"{view!r} is not a view — pick one of: {', '.join(sorted(VIEWS))}")
    rows = [c for c in _custom() if c.get("name") != name]
    row = {"name": name, "prompt": prompt.strip(), "view": view}
    rows.append(row)
    prefs.set_many({CUSTOM_KEY: json.dumps(rows)})
    return row


def delete_custom(name: str) -> None:
    # Accept both `/brief` and `brief`: the DELETE path segment carries no
    # leading slash, so comparing verbatim would silently delete nothing.
    key = (name or "").strip()
    key = key if key.startswith("/") else "/" + key
    rows = [c for c in _custom() if c.get("name") != key]
    prefs.set_many({CUSTOM_KEY: json.dumps(rows)})


def all_commands() -> list[dict]:
    """Catalog + custom, with the Python handlers stripped — this crosses HTTP."""
    out = [{k: v for k, v in c.items() if k != "handler"} for c in CATALOG]
    out.extend(_custom_view(c) for c in _custom())
    return out


def parse(text: str) -> tuple[dict | None, str]:
    """(command, raw_args). command is None when this is not a command."""
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, ""
    # Split on any whitespace, not just " ": `/task\tBuy milk` used to miss the
    # space entirely, so `head` was "/task\tBuy" (no such command), `parse`
    # returned None, and the whole line fell through to the model as prose.
    parts = t.split(None, 1)
    head = parts[0]
    args = parts[1].strip() if len(parts) > 1 else ""
    if len(args) >= 2 and args[0] == args[-1] and args[0] in "\"'":
        args = args[1:-1]
    cmd = _BY_NAME.get(head)
    if cmd is not None:
        return cmd, args
    for c in _custom():
        if c.get("name") == head:
            return {**_custom_view(c), "handler": None, "custom": c}, args
    return None, ""


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)[:4000]
    except Exception:
        try:
            return str(value)[:4000]
        except Exception:
            return ""


def _none() -> dict:
    return {"handled": False, "ok": False, "command": "", "result": None, "text": "", "view": None}


def execute(text: str) -> dict:
    """Run a command. Never raises — a bad command is a result, not a 500."""
    try:
        cmd, args = parse(text)
    except Exception as e:  # noqa: BLE001
        return {**_none(), "text": f"{type(e).__name__}: {e}"[:200]}
    if cmd is None:
        return _none()
    name = cmd["name"]
    custom_row = cmd.get("custom")
    if custom_row is not None:
        prompt = str(custom_row.get("prompt") or "")
        return {"handled": True, "ok": True, "command": name,
                "result": {"prompt": prompt, "view": custom_row.get("view") or ""},
                "text": prompt, "view": custom_row.get("view") or None}
    try:
        result = cmd["handler"](args)
    except ValueError as e:
        return {"handled": True, "ok": False, "command": name, "result": None,
                "text": _as_text(str(e)), "view": None}
    except Exception as e:  # noqa: BLE001 — surface it, never crash the chat stream
        return {"handled": True, "ok": False, "command": name, "result": None,
                "text": _as_text(f"{type(e).__name__}: {e}")[:200], "view": None}
    try:
        return {"handled": True, "ok": True, "command": name, "result": result,
                "text": _as_text(result),
                "view": result.get("view") if isinstance(result, dict) else None}
    except Exception as e:  # noqa: BLE001
        return {"handled": True, "ok": False, "command": name, "result": None,
                "text": _as_text(f"{type(e).__name__}: {e}")[:200], "view": None}