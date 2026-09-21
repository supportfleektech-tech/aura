"""SQLite persistence layer — the application source of truth."""
from __future__ import annotations

import json
import sqlite3
import contextlib
import threading
from pathlib import Path
from typing import Any

from . import config

_lock = threading.RLock()

# Dry-run support (v1.6.0 WS2): when DRY_RUN is set, run()/run_many() skip
# commit so preview() can roll everything back. preview() holds _lock (RLock)
# for the whole preview so no concurrent request can interleave writes.
DRY_RUN = False
BLOCKED: list[str] = []


def blocked(note: str) -> None:
    """Record a suppressed external side effect (network/LLM/files)."""
    if DRY_RUN and note not in BLOCKED:
        BLOCKED.append(note)
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        try:
            _conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            _conn = _connect()
        return _conn


def reset() -> None:
    """Close the pooled connection; the next query transparently reconnects.
    Used by backup restore (the DB file is swapped underneath us)."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None


def init_db() -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with _lock:
        c = conn()
        c.executescript(schema)
        cols = [r[1] for r in c.execute("PRAGMA table_info(memories)").fetchall()]
        if "embedding_model" not in cols:  # v1.2: tag which embedder made each vector
            c.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT NOT NULL DEFAULT 'hashed:192'")
        scol = [r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()]
        for col, ddl in (("summary", "TEXT NOT NULL DEFAULT ''"),
                         ("summary_through", "INTEGER NOT NULL DEFAULT 0"),
                         ("summary_at", "TEXT NOT NULL DEFAULT ''"),
                         ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                         ("starred", "INTEGER NOT NULL DEFAULT 0")):
            if col not in scol:  # v1.6: rolling summaries + pin/star
                c.execute(f"ALTER TABLE sessions ADD COLUMN {col} {ddl}")
        ocol = [r[1] for r in c.execute("PRAGMA table_info(opportunities)").fetchall()]
        for col, ddl in (("resolved", "INTEGER NOT NULL DEFAULT 0"),
                         ("resolved_at", "TEXT NOT NULL DEFAULT ''"),
                         ("snoozed_until", "TEXT NOT NULL DEFAULT ''")):
            if col not in ocol:  # v1.8: auto-resolution + snooze
                c.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {ddl}")
        micol = [r[1] for r in c.execute("PRAGMA table_info(missions)").fetchall()]
        for col, ddl in (("schedule_json", "TEXT NOT NULL DEFAULT '{}'"),
                         ("next_run_at", "TEXT NOT NULL DEFAULT ''")):
            if col not in micol:  # v1.11: scheduled missions
                c.execute(f"ALTER TABLE missions ADD COLUMN {col} {ddl}")
        c.execute(
            "INSERT OR IGNORE INTO users (id, name, role, location) VALUES (1, ?, ?, ?)",
            (config.USER_NAME, config.USER_ROLE, config.USER_LOCATION),
        )
        for platform in ("telegram", "discord", "slack", "whatsapp", "email", "homeassistant"):
            c.execute(
                "INSERT OR IGNORE INTO integrations (user_id, platform, status) VALUES (1, ?, 'disconnected')",
                (platform,),
            )
        c.commit()


def row_to_dict(row: Any) -> dict:
    return dict(row) if row is not None else {}


def q(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        cur = conn().execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def qone(sql: str, params: tuple = ()) -> dict | None:
    with _lock:
        cur = conn().execute(sql, params)
        r = cur.fetchone()
        return dict(r) if r else None


def run(sql: str, params: tuple = ()) -> int:
    """Execute a write; returns lastrowid."""
    with _lock:
        cur = conn().execute(sql, params)
        if not DRY_RUN:
            conn().commit()
        return cur.lastrowid or 0


def run_many(sql: str, seq: list[tuple]) -> None:
    with _lock:
        conn().executemany(sql, seq)
        if not DRY_RUN:
            conn().commit()


def log_activity(kind: str, title: str, detail: str = "", domain: str = "general",
                 severity: str = "info", source: str = "aura") -> None:
    run(
        "INSERT INTO activity (user_id, kind, domain, title, detail, severity, source) VALUES (1,?,?,?,?,?,?)",
        (kind, domain, title, detail, severity, source),
    )


def notify(title: str, body: str = "", level: str = "info") -> None:
    run("INSERT INTO notifications (user_id, title, body, level) VALUES (1,?,?,?)", (title, body, level))


def audit(action: str, entity: str = "", entity_id: str = "", detail: str = "") -> None:
    run("INSERT INTO audit (user_id, action, entity, entity_id, detail) VALUES (1,?,?,?,?)",
        (action, entity, entity_id, detail))


def jdump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def jload(s: str | None, default: Any = None) -> Any:
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except Exception:
        return default if default is not None else {}


@contextlib.contextmanager
def preview():
    """Run a thunk with all writes + external effects suppressed; roll back."""
    global DRY_RUN, BLOCKED
    with _lock:
        DRY_RUN, BLOCKED = True, []
        try:
            yield BLOCKED
        finally:
            DRY_RUN = False
            try:
                conn().rollback()
            finally:
                BLOCKED = []
