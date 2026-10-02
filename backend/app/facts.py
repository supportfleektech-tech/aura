"""Durable facts from Hermes tool results (spec §1, FR-MEM-005).

`MemoryEngine.observe` already extracts facts from *chat text*. This handles the
other half: facts that only exist in tool output — an email address returned by
`clients.create`, a due date returned by `tasks.create`.

Only high-signal structured fields are promoted. A tool's free-text output is
not mined for sentences: that is `observe`'s job, and doing both would
double-count. Every candidate goes through `MemoryEngine.store`, which dedupes,
so a repeated call is cheap and idempotent.

Two payload shapes have to be recognised, because the routes return both:

* a **wrapper** — `list_*` routes end in `return {"clients": rows}`
  (`routes/clients.py:27`, `routes/tasks.py:66`, `routes/projects.py:28`);
* a **bare row** — `create_*`/`update_*`/`get_*` routes end in
  `return db.qone(...)` and `hermes._wrap_model` hands that row back unwrapped
  (`routes/clients.py:38`, `routes/tasks.py:87`, `routes/projects.py:39`).

A bare row is discriminated on the entity's *own columns*, never on the tool
name: within one family `clients.list` returns a wrapper and `clients.create`
returns a row, so the name does not say which. The column sets below were read
off the real `SELECT *` returns, not guessed.
"""
from __future__ import annotations

from typing import Any

from .memory import memory_engine
from .hermes import RISK_INFO

MAX_PER_RESULT = 3
MIN_CONTENT_CHARS = 12


def _client_fact(c: dict) -> dict | None:
    contact = " ".join(x for x in (c.get("email") or "", c.get("phone") or "") if x).strip()
    if not contact:
        return None
    name = c.get("name") or "Unknown"
    org = f" ({c.get('org')})" if c.get("org") else ""
    # Client contact details are third-party PII. `sensitivity_scan` has no
    # email/phone pattern, so without this they would be stored "normal" and
    # `inference.filter_cloud_memories` would ground them from a cloud model.
    # "private" is withheld under both the strict and the relaxed policy.
    return {"title": f"Contact: {name}"[:72], "content": f"{name}{org} — {contact}",
            "domain": "clients", "mtype": "semantic", "confidence": 0.85,
            "importance": 0.7, "sensitivity": "private"}


def _project_fact(p: dict) -> dict | None:
    name = str(p.get("name") or p.get("title") or "").strip()
    if not name:
        return None
    # `status` is deliberately absent from BOTH `title` and `content`. `store`
    # dedupes on content alone (>0.55 Jaccard over tokens), and "Kopilot is
    # active" vs "Kopilot is done" scores ~0.33 — every status change would
    # insert a rival row and leave the stale one behind. Parking the status in
    # `title` dodged that but caused a worse bug: the dedupe path never rewrites
    # a title (it bumps only `last_confirmed` and `importance`), so a row titled
    # "Project: Kopilot (active)" claims "active" forever, on the one surface a
    # human actually reads. A fact has no third field that is not title or
    # content, so the status is dropped outright: a missing status is
    # recoverable from the projects table, a stale one is not.
    return {"title": f"Project: {name}"[:72], "content": f"{name} is a tracked project",
            "domain": "career", "mtype": "semantic", "confidence": 0.8,
            "importance": 0.6, "sensitivity": None}


def _task_fact(t: dict) -> dict | None:
    title = str(t.get("title") or "").strip()
    due = str(t.get("due_at") or "").strip()
    if not title or not due:
        return None
    return {"title": f"Due: {title}"[:72], "content": f"{title} is due {due[:10]}",
            "domain": "general", "mtype": "episodic", "confidence": 0.7,
            "importance": 0.55, "sensitivity": None}


def _bare_row_fact(row: dict) -> dict | None:
    """One entity row, as every `create_*`/`update_*`/`get_*` route returns it.

    Column sets verified against the real rows:
      clients  — id, user_id, name, org, email, phone, health, notes, ...
      tasks    — id, user_id, title, description, status, priority, due_at, ...
      projects — id, user_id, client_id, name, status, progress, deadline, ...
    `progress`/`deadline` exist only on `projects`; a `goals` row also has
    `progress` but no `name`, so it cannot match.
    """
    if not isinstance(row, dict) or "id" not in row:
        return None
    if row.get("email") or row.get("phone"):
        return _client_fact(row)
    if row.get("title") and row.get("due_at"):
        return _task_fact(row)
    if row.get("name") and ("progress" in row or "deadline" in row):
        return _project_fact(row)
    return None


# Singular wrapper key -> extractor. Mirrors a wrapped single-entity payload.
_SINGULAR = (("client", _client_fact),
             ("project", _project_fact),
             ("task", _task_fact))
# Plural wrapper key -> extractor. Mirrors a list payload.
_PLURAL = (("clients", _client_fact),
           ("projects", _project_fact),
           ("tasks", _task_fact))


def _is_write_tool(tool: str) -> bool:
    """True when the tool asserted something, rather than merely reporting it.

    The risk taxonomy already draws this line: R0 is a pure read, R1+ is a
    local write. A `tasks.list` result is not a new fact about the user — it is
    a re-read of rows they already own in the tasks table, and turning it into a
    durable memory duplicates data that then has to be kept in sync (the same
    stale-row class as a changing project status). Worse, every stored memory
    journals a write, so a read-only turn recorded user actions it never took:
    `agent_cases.json`'s `read_tasks_without_mutation` asserts that
    `write_journal` stays empty after "list my tasks, do not change them".

    So: facts come from writes. `tasks.create` asserts a due date worth
    remembering; `tasks.list` re-derives one the user can already see.
    """
    if tool.startswith("__"):  # orchestrator pseudo-tools are read-only context folds
        return False
    from .hermes import TOOLS
    tool_obj = TOOLS.get(tool)
    return bool(tool_obj) and tool_obj.risk != RISK_INFO


def extract(tool: str, data: Any) -> list[dict]:
    """Candidate facts from one write-tool result. At most MAX_PER_RESULT."""
    if not isinstance(data, dict) or not _is_write_tool(tool):
        return []
    out: list[dict] = []
    row = _bare_row_fact(data)
    if row:
        out.append(row)
    for key, fn in _SINGULAR:
        v = data.get(key)
        if isinstance(v, dict):
            f = fn(v)
            if f:
                out.append(f)
    for key, fn in _PLURAL:
        v = data.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    f = fn(item)
                    if f:
                        out.append(f)
    clean = [f for f in out if len(f["content"].strip()) >= MIN_CONTENT_CHARS]
    return clean[:MAX_PER_RESULT]


def harvest(tool: str, data: Any) -> list[dict]:
    """Extract, store, and return what was persisted. Never raises."""
    stored = []
    for f in extract(tool, data):
        try:
            stored.append(memory_engine.store(
                f["title"], f["content"], f["domain"], f["mtype"],
                "tool:" + tool, f["confidence"], f["importance"], f["sensitivity"]))
        except Exception:
            continue
    return stored
