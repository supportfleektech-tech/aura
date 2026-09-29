"""Calendar router — calendars, events, Google OAuth."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

cal_r = APIRouter(prefix="/calendar", tags=["calendar"])


@cal_r.get("/calendars")
def list_cals():
    from .. import calendar_sync as _c
    return {"calendars": _c.list_calendars()}


@cal_r.post("/calendars")
def create_cal(b: dict):
    from .. import calendar_sync as _c
    try:
        return _c.create_calendar(b.get("name", ""), b.get("source", "local"),
                                  b.get("color", "blue"), b.get("fields", {}))
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.patch("/calendars/{cid}")
def update_cal(cid: int, patch: dict):
    from .. import calendar_sync as _c
    try:
        return _c.update_calendar(cid, patch)
    except KeyError:
        raise HTTPException(404, "calendar not found")


@cal_r.delete("/calendars/{cid}")
def delete_cal(cid: int):
    from .. import calendar_sync as _c
    _c.delete_calendar(cid)
    return {"ok": True}


@cal_r.post("/calendars/{cid}/sync")
def sync_cal(cid: int):
    from .. import calendar_sync as _c
    try:
        return _c.sync_calendar(cid)
    except KeyError:
        raise HTTPException(404, "calendar not found")


@cal_r.get("/events")
def list_events(start: str, end: str):
    from .. import calendar_sync as _c
    try:
        return {"events": _c.events_between(start, end)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.get("/today")
def cal_today():
    from .. import calendar_sync as _c
    return {"events": _c.todays_events()}


@cal_r.get("/week")
def cal_week():
    from .. import calendar_sync as _c
    return {"events": _c.week_events()}


@cal_r.post("/events")
def create_ev(b: dict):
    from .. import calendar_sync as _c
    try:
        cal_id = b.get("calendar_id") or _c.ensure_default_calendar()
        return _c.create_event(int(cal_id), b.get("title", "Untitled"),
                               b.get("starts_at", ""), b.get("ends_at", ""),
                               b.get("description", ""), b.get("location", ""),
                               bool(b.get("all_day", False)))
    except KeyError:
        raise HTTPException(404, "calendar not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.patch("/events/{eid}")
def update_ev(eid: int, patch: dict):
    from .. import calendar_sync as _c
    try:
        return _c.update_event(eid, patch)
    except KeyError:
        raise HTTPException(404, "event not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@cal_r.delete("/events/{eid}")
def delete_ev(eid: int):
    from .. import calendar_sync as _c
    _c.delete_event(eid)
    return {"ok": True}


@cal_r.get("/google/auth-url")
def google_auth_url(calendar_id: int, redirect_uri: str):
    from .. import calendar_sync as _c
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (calendar_id,))
    if not row or row["source"] != "google":
        raise HTTPException(404, "google calendar not found")
    cfg = db.jload(row["config_json"], {})
    if not cfg.get("client_id"):
        raise HTTPException(400, "client_id missing — save it on the calendar first")
    return {"url": _c.google_auth_url(cfg["client_id"], redirect_uri, f"cal-{calendar_id}")}


@cal_r.get("/google/landing")
def google_landing(code: str = "", error: str = ""):
    """OAuth redirect target: shows the code for copy-paste into AURA."""
    from fastapi.responses import HTMLResponse
    body = (f"<h2>Copy this code into AURA</h2><pre style='font-size:18px'>{code}</pre>"
            if code else f"<h2>Google auth failed</h2><p>{error or 'no code'}</p>")
    return HTMLResponse(f"<body style='font-family:sans-serif;background:#0b1428;color:#e8eefc;"
                        f"display:grid;place-items:center;min-height:90vh;text-align:center'>"
                        f"<div>{body}<p><small>You can close this tab.</small></p></div></body>")


@cal_r.post("/google/callback")
def google_callback(b: dict):
    from .. import calendar_sync as _c
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (b.get("calendar_id"),))
    if not row or row["source"] != "google":
        raise HTTPException(404, "google calendar not found")
    if not b.get("code") or not b.get("redirect_uri"):
        raise HTTPException(400, "code + redirect_uri required")
    try:
        return _c.google_exchange(row, b["code"], b["redirect_uri"])
    except RuntimeError as e:
        raise HTTPException(400, str(e))
