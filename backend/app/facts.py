"""Durable facts from Hermes tool results (spec §1, FR-MEM-005).

`MemoryEngine.observe` already extracts facts from *chat text*. This handles the
other half: facts that only exist in tool output — an email address returned by
`clients.create`, a due date returned by `tasks.create`.

Only high-signal structured fields are promoted. A tool's free-text output is
not mined for sentences: that is `observe`'s job, and doing both would
double-count. Every candidate goes through `MemoryEngine.store`, which dedupes,
so a repeated call is cheap and idempotent.
"""
from __future__ import annotations

from typing import Any

from .memory import memory_engine

MAX_PER_RESULT = 3
MIN_CONTENT_CHARS = 12


def _client_fact(c: dict, domain: str) -> dict | None:
    contact = " ".join(x for x in (c.get("email") or "", c.get("phone") or "") if x).strip()
    if not contact:
        return None
    name = c.get("name") or "Unknown"
    org = f" ({c.get('org')})" if c.get("org") else ""
    return {"title": f"Contact: {name}"[:72], "content": f"{name}{org} — {contact}",
            "domain": domain, "mtype": "semantic", "confidence": 0.85, "importance": 0.7}


def _project_fact(p: dict, domain: str) -> dict | None:
    name = str(p.get("name") or p.get("title") or "").strip()
    if not name:
        return None
    return {"title": f"Project: {name}"[:72], "content": f"{name} is {p.get('status') or 'active'}",
            "domain": domain, "mtype": "semantic", "confidence": 0.8, "importance": 0.6}


def _task_fact(t: dict, domain: str) -> dict | None:
    title = str(t.get("title") or "").strip()
    due = str(t.get("due_at") or "").strip()
    if not title or not due:
        return None
    return {"title": f"Due: {title}"[:72], "content": f"{title} is due {due[:10]}",
            "domain": domain, "mtype": "episodic", "confidence": 0.7, "importance": 0.55}


# Singular key -> (extractor, domain). Mirrors the shape a create-tool returns.
_SINGULAR = (("client", _client_fact, "clients"),
             ("project", _project_fact, "career"),
             ("task", _task_fact, "general"))
# Plural key -> (extractor, domain). Mirrors a list-tool.
_PLURAL = (("clients", _client_fact, "clients"),
           ("projects", _project_fact, "career"),
           ("tasks", _task_fact, "general"))


def extract(tool: str, data: Any) -> list[dict]:
    """Candidate facts from one tool result. At most MAX_PER_RESULT."""
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    for key, fn, dom in _SINGULAR:
        v = data.get(key)
        if isinstance(v, dict):
            f = fn(v, dom)
            if f:
                out.append(f)
    for key, fn, dom in _PLURAL:
        v = data.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    f = fn(item, dom)
                    if f:
                        out.append(f)
    clean = [f for f in out if len(f["content"].strip()) >= MIN_CONTENT_CHARS]
    return clean[:MAX_PER_RESULT]


def harvest(tool: str, data: Any, domain: str = "general") -> list[dict]:
    """Extract, store, and return what was persisted. Never raises."""
    stored = []
    for f in extract(tool, data):
        try:
            stored.append(memory_engine.store(
                f["title"], f["content"], f["domain"], f["mtype"],
                "tool:" + tool, f["confidence"], f["importance"]))
        except Exception:
            continue
    return stored