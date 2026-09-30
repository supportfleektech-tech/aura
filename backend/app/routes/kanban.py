"""Kanban board router — a drag-drop view over mission status.

The board is a *view*, never a second source of truth: every move goes through
`missions.set_status`, so it cannot bypass the approval flow, and no path sets
`status='done'` directly. Dragging an unstarted card to the done column cancels
it, because the only legitimate route to `done` is a mission actually finishing.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import missions as _m

board_r = APIRouter(prefix="/board", tags=["missions"])

COLUMNS = [
    ("backlog", "Backlog", ("draft", "paused")),
    ("running", "Running", ("running",)),
    ("awaiting", "Needs you", ("awaiting",)),
    ("done", "Finished", ("done", "failed", "cancelled")),
]
_COLUMN_KEYS = {k for k, _, _ in COLUMNS}
_STATUS_TO_COLUMN = {s: k for k, _, sts in COLUMNS for s in sts}

# (from_column, to_column) -> missions.set_status action. Anything absent is a 409.
MOVES = {
    ("backlog", "running"): "start",
    ("backlog", "done"): "cancel",
    ("running", "backlog"): "pause",
    ("running", "done"): "cancel",
    ("awaiting", "backlog"): "pause",
    ("awaiting", "done"): "cancel",
}


def _card(m: dict) -> dict:
    steps = m.get("steps") or []
    done = sum(1 for s in steps
               if isinstance(s, dict) and s.get("status") in ("done", "skipped"))
    return {"id": m["id"], "goal": m["goal"], "status": m["status"],
            "steps_total": len(steps), "steps_done": done,
            "next_run_at": m.get("next_run_at", ""), "created_at": m.get("created_at", ""),
            "updated_at": m.get("updated_at", "")}


@board_r.get("")
def board():
    by_col: dict[str, list[dict]] = {k: [] for k, _, _ in COLUMNS}
    for m in _m.list_missions(limit=100):
        by_col[_STATUS_TO_COLUMN.get(m["status"], "backlog")].append(_card(m))
    return {"columns": [{"key": k, "label": lab, "missions": by_col[k]} for k, lab, _ in COLUMNS],
            "counts": {k: len(v) for k, v in by_col.items()}}


@board_r.post("/move")
def move(body: dict):
    mid, col = body.get("mission_id"), body.get("column")
    if col not in _COLUMN_KEYS:
        raise HTTPException(400, f"column must be one of {','.join(sorted(_COLUMN_KEYS))}")
    if not isinstance(mid, int) or isinstance(mid, bool):
        raise HTTPException(400, "mission_id must be an integer")
    m = _m._row(mid)
    if not m:
        raise HTTPException(404, "not found")
    src = _STATUS_TO_COLUMN.get(m["status"], "backlog")
    if src == col:
        return {"ok": True, "mission": _card(m)}
    action = MOVES.get((src, col))
    if action is None:
        raise HTTPException(409, f"cannot move a {src} mission to {col}")
    try:
        updated = _m.set_status(mid, action)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not updated:
        raise HTTPException(404, "not found")
    return {"ok": True, "mission": _card(updated)}
