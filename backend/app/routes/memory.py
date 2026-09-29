"""Memory router — CRUD, search, forget."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db
from ..memory import memory_engine

memory_r = APIRouter(prefix="/memories", tags=["memory"])


def store_memory(title: str, content: str, domain: str = "general"):
    """Wrapper for hermes tool - stores a memory with given title, content, domain."""
    return create_memory({"title": title, "content": content, "domain": domain})


def search_memory(query: str, domain: str | None = None, mtype: str | None = None, limit: int = 6):
    """Search memories - used by hermes tool."""
    from ..inference import router
    return memory_engine.search(query, domain, mtype, limit, embedder=router.embed_fn())


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


@memory_r.post("/search")
def search_memories(body: dict):
    from ..inference import router
    return {"results": memory_engine.search(body.get("query", ""), body.get("domain"), body.get("mtype"),
                                            int(body.get("limit", 8)), embedder=router.embed_fn())}


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
