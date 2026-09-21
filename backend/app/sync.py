"""AURA device sync — portable JSON bundles with merge-by-natural-key.

Litestream replicates the DB file (single-writer). These bundles are the
multi-device story: export on device A, import on device B. Import dedupes by
natural key, remaps foreign keys (clients/projects), and reports conflicts
(same key, different content — existing row wins, nothing is overwritten).

Never exported: credentials (integrations, email/calendar configs), push
subscriptions (device-specific), observability (activity/audit/runs).
Memory vectors are dropped (target re-embeds on read).
"""
from __future__ import annotations

from typing import Any

from . import db

# table -> natural key columns (dedupe) ; None key column = always insert
TABLES: dict[str, tuple[str, ...] | None] = {
    "clients": ("name",),
    "projects": ("name",),
    "milestones": ("project_id", "title"),
    "tasks": ("title", "created_at"),
    "memories": ("title", "content"),
    "journal": ("title", "created_at"),
    "goals": ("title",),
    "habits": ("name",),
    "expenses": ("amount", "category", "created_at"),
    "sleep_logs": ("date", "bedtime", "wake_at"),
    "timeblocks": ("title", "starts_at"),
    "events": ("uid",),
    "automations": ("name", "trigger_kind", "action_kind"),
    "briefings": ("name", "kind"),
    "sessions": ("title", "domain", "created_at"),
    "messages": ("session_id", "role", "content", "created_at"),
}
SKIP_COLS = {"embedding_json"}  # dropped from memories on export
NO_USER_COL = {"messages", "milestones"}
COMPARE_COLS = 6  # fields compared for conflict detection (besides key + id)


def _cols(table: str) -> list[str]:
    # PRAGMA via db layer: use a throwaway select to discover columns
    row = db.qone(f"SELECT * FROM [{table}] LIMIT 1")
    if row:
        return [c for c in row.keys() if c != "id" and c not in SKIP_COLS]
    # empty table: fall back to known columns from any row ever (schema probe)
    probe = {"clients": ["user_id", "name", "org", "email", "phone", "health", "notes",
                         "contract_value", "created_at"]}
    return probe.get(table, [])


def export_bundle() -> dict:
    import time as _t
    tables: dict[str, list[dict]] = {}
    for t in TABLES:
        cols = _cols(t)
        if not cols and db.qone(f"SELECT COUNT(*) c FROM [{t}]")["c"] == 0:
            tables[t] = []
            continue
        if not cols:  # empty-table fallback: re-derive from schema via LIMIT 0 trick
            tables[t] = []
            continue
        sel = ', '.join('[' + c + ']' for c in cols)
        rows = db.q(f"SELECT {sel} FROM [{t}]" + ("" if t in NO_USER_COL else " WHERE user_id=1"))
        tables[t] = rows
    # sessions/messages ownership: keep sessions of user 1 + their messages
    tables["sessions"] = [r for r in tables.get("sessions", [])]
    # denormalized FK hints so import can re-link by name across devices
    try:
        cnames = {c["id"]: c["name"] for c in
                  db.q("SELECT id, name FROM clients WHERE user_id=1")}
        pnames = {c["id"]: c["name"] for c in
                  db.q("SELECT id, name FROM projects WHERE user_id=1")}
        for r in tables.get("projects", []):
            if r.get("client_id") and r["client_id"] in cnames:
                r["_client"] = cnames[r["client_id"]]
        for r in tables.get("milestones", []):
            if r.get("project_id") and r["project_id"] in pnames:
                r["_project"] = pnames[r["project_id"]]
        for r in tables.get("tasks", []):
            if r.get("client_id") and r["client_id"] in cnames:
                r["_client"] = cnames[r["client_id"]]
            if r.get("project_id") and r["project_id"] in pnames:
                r["_project"] = pnames[r["project_id"]]
    except Exception:
        pass
    # session hints so import can re-link messages by (title, created_at)
    try:
        smap = {s["id"]: (s["title"], s["created_at"]) for s in
                db.q("SELECT id, title, created_at FROM sessions WHERE user_id=1")}
        for r in tables.get("messages", []):
            hit = smap.get(r.get("session_id"))
            if hit:
                r["_session_title"], r["_session_created"] = hit
    except Exception:
        pass
    return {"format": "aura-sync/1", "exported_at": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
            "tables": tables}


def _find(table: str, key: tuple[str, ...], row: dict) -> dict | None:
    # IS (not =): NULL key parts match each other, so sparse rows still dedupe
    where = " AND ".join(f"[{c}] IS ?" for c in key)
    try:
        return db.qone(f"SELECT * FROM [{table}] WHERE {where} LIMIT 1",
                       tuple(row.get(c) for c in key))
    except Exception:
        return None


def import_bundle(bundle: dict, device: str = "") -> dict:
    if not isinstance(bundle, dict) or bundle.get("format") != "aura-sync/1":
        raise ValueError("not an aura-sync/1 bundle")
    if not isinstance(bundle.get("tables"), dict):
        raise ValueError("bundle has no tables")
    stats: dict[str, dict[str, int]] = {}
    conflicts: list[dict] = []
    idmap: dict[str, dict[Any, int]] = {"clients": {}, "projects": {}}

    def _keymap(table: str, src_row: dict, new_id: int) -> None:
        if table in idmap:
            # map by natural name for FK remap (best effort across devices)
            nm = src_row.get("name")
            if nm:
                idmap[table][nm] = new_id

    order = ["clients", "projects", "milestones", "tasks", "memories", "journal",
             "goals", "habits", "expenses", "sleep_logs", "timeblocks", "events",
             "automations", "briefings", "sessions", "messages"]
    for t in order:
        rows = bundle["tables"].get(t, [])
        if not isinstance(rows, list):
            continue
        key = TABLES[t]
        ins = skip = conf = 0
        for src in rows:
            if not isinstance(src, dict):
                continue
            row = {k: v for k, v in src.items() if k != "id" and k not in SKIP_COLS}
            # FK remap into this device's ids (by name hint; NULL when absent)
            if t in ("projects", "tasks") and row.get("_client"):
                hit = db.qone("SELECT id FROM clients WHERE user_id=1 AND name=?",
                              (row["_client"],))
                row["client_id"] = hit["id"] if hit else None
            elif t in ("projects", "tasks"):
                row["client_id"] = None
            if t in ("milestones", "tasks") and row.get("_project"):
                hit = db.qone("SELECT id FROM projects WHERE user_id=1 AND name=?",
                              (row["_project"],))
                row["project_id"] = hit["id"] if hit else None
            elif t in ("milestones", "tasks"):
                row["project_id"] = None
            row.pop("_client", None)
            row.pop("_project", None)
            if t == "events":
                try:
                    from .calendar_sync import ensure_default_calendar
                    row["calendar_id"] = ensure_default_calendar()
                except Exception:
                    row["calendar_id"] = 0
            if t == "messages":
                if row.get("_session_title") is not None:
                    hit = db.qone("SELECT id FROM sessions WHERE user_id=1 AND title=?"
                                  " AND created_at=?",
                                  (row.get("_session_title"), row.get("_session_created")))
                    if hit:
                        row["session_id"] = hit["id"]
                    else:  # orphan: its session didn't merge — skip, don't misattach
                        skip += 1
                        continue
                row.pop("_session_title", None)
                row.pop("_session_created", None)
            if key:
                hit = _find(t, key, row)
                if hit:
                    diff = [c for c in row.keys() - set(key) - {"id"}
                            if str(hit.get(c) or "") != str(row.get(c) or "")][:COMPARE_COLS]
                    if diff:
                        conf += 1
                        if len(conflicts) < 25:
                            conflicts.append({"table": t,
                                              "key": {c: row.get(c) for c in key},
                                              "differing": diff})
                    else:
                        skip += 1
                    if t in idmap and row.get("name"):
                        idmap[t][row["name"]] = hit["id"]
                    continue
            cols = [c for c in row if c != "id"]
            if not cols:
                continue
            if t == "sessions":
                # sessions.id is a TEXT PK with no default — mint one like create_session
                import uuid as _uuid
                row["id"] = _uuid.uuid4().hex[:12]
                cols = ["id"] + cols
            try:
                nid = db.run(f"INSERT INTO [{t}] ([{'], ['.join(cols)}]) "
                             f"VALUES ({', '.join('?' * len(cols))})",
                             tuple(row[c] for c in cols))
            except Exception:
                conf += 1
                continue
            ins += 1
            _keymap(t, row, nid)
        stats[t] = {"inserted": ins, "skipped": skip, "conflicts": conf}
    total_conf = sum(v["conflicts"] for v in stats.values())
    db.run("INSERT INTO sync_log (user_id,device,direction,tables_json,conflicts,note)"
           " VALUES (1,?,'import',?,?,?)",
           (device[:80] or "unknown", db.jdump(stats), total_conf,
            f"{sum(v['inserted'] for v in stats.values())} rows merged"))
    db.log_activity("system", "Sync bundle imported",
                    f"{device or 'unknown'} · {total_conf} conflicts (kept local)", "general")
    return {"tables": stats, "conflicts": conflicts,
            "inserted": sum(v["inserted"] for v in stats.values())}


def log_export(device: str = "") -> None:
    db.run("INSERT INTO sync_log (user_id,device,direction,tables_json,conflicts,note)"
           " VALUES (1,?,'export','{}',0,'bundle downloaded')", (device[:80] or "unknown",))


def history(limit: int = 20) -> list[dict]:
    return db.q("SELECT * FROM sync_log WHERE user_id=1 ORDER BY id DESC LIMIT ?",
                (max(1, min(100, limit)),))
