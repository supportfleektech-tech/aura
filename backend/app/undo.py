"""Undo journal + inverse-op restore (v1.6.0 WS2).

Covered tables (all INTEGER PK `id`): tasks, clients, projects, memories, events.
Writes are journaled at the engine/tool layer with a before-image; `undo_last`
applies the inverse op. Journal is capped; entries are consumed on undo.
"""
from . import db

CAP = 50
TABLES = {"tasks", "clients", "projects", "memories", "events"}


def record(tool: str, op: str, table: str, row_id, before: dict | None = None,
           summary: str = "") -> None:
    """Journal one write. No-op for uncovered tables / missing ids (never crash a write)."""
    if table not in TABLES or not row_id or op not in ("create", "update", "delete"):
        return
    try:
        db.run("INSERT INTO write_journal (tool, op, tbl, row_id, before_json, summary)"
               " VALUES (?,?,?,?,?,?)",
               (tool, op, table, str(row_id),
                db.jdump(before) if before else None, (summary or f"{op} {table}#{row_id}")[:300]))
        db.run("DELETE FROM write_journal WHERE id NOT IN"
               " (SELECT id FROM write_journal ORDER BY id DESC LIMIT ?)", (CAP,))
    except Exception:
        pass


def tail(n: int = 10) -> list[dict]:
    return db.q("SELECT id, at, tool, op, tbl, row_id, summary FROM write_journal"
                " ORDER BY id DESC LIMIT ?", (max(1, min(n, CAP)),))


def _insert_row(table: str, row: dict) -> None:
    cols = list(row.keys())
    db.run(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
           tuple(row[c] for c in cols))


def _apply(entry: dict) -> str:
    t, rid, before = entry["tbl"], entry["row_id"], db.jload(entry["before_json"], None)
    if t not in TABLES:
        raise ValueError(f"table {t} not undoable")
    if entry["op"] == "create":
        gone = db.qone(f"SELECT id FROM {t} WHERE id=?", (rid,)) is None
        db.run(f"DELETE FROM {t} WHERE id=?", (rid,))
        return f"{t}#{rid} was already gone" if gone else f"removed {t}#{rid} ({entry['summary']})"
    if not before:
        raise ValueError("no before-image")
    cols = [c for c in before if c != "id"]
    if entry["op"] in ("update", "delete"):
        # delete-undo must UPDATE when the row survives (soft deletes) or INSERT when hard-gone
        if db.qone(f"SELECT id FROM {t} WHERE id=?", (rid,)):
            db.run(f"UPDATE {t} SET {','.join(f'{c}=?' for c in cols)} WHERE id=?",
                   (*[before[c] for c in cols], rid))
        else:
            _insert_row(t, before)
        return f"restored {t}#{rid} ({entry['summary']})"
    raise ValueError(f"unknown op {entry['op']}")


def undo_last(steps: int = 1) -> dict:
    rows = db.q("SELECT * FROM write_journal ORDER BY id DESC LIMIT ?",
                (max(1, min(int(steps or 1), 10)),))
    undone = []
    for r in rows:
        try:
            msg = _apply(r)
        except Exception as ex:  # consume the entry even on failure; report honestly
            msg = f"could not undo {r['summary']}: {ex}"[:200]
        db.run("DELETE FROM write_journal WHERE id=?", (r["id"],))
        undone.append({"id": r["id"], "summary": r["summary"], "result": msg})
    left = db.qone("SELECT COUNT(*) n FROM write_journal") or {"n": 0}
    return {"undone": undone, "remaining": left["n"]}
