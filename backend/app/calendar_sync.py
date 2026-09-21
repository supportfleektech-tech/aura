"""AURA calendar — local events + CalDAV pull/push + Google Calendar sync.

Transports use httpx only (no new deps): CalDAV speaks PROPFIND/REPORT/PUT
with a minimal VEVENT parser; Google uses REST + OAuth2 refresh tokens.
Secrets (passwords, client secrets, refresh tokens) live in config_json and
are never returned — see redacted().
"""
from __future__ import annotations

import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from . import db

TIMEOUT = 20.0
SOURCES = ("local", "caldav", "google")
SECRET_KEYS = ("password", "client_secret", "refresh_token", "access_token")


# ------------------------------------------------------------- calendars --

def _cfg(row: dict) -> dict:
    cfg = db.jload(row.get("config_json"), {})
    return cfg if isinstance(cfg, dict) else {}


def redacted(row: dict) -> dict:
    cfg = _cfg(row)
    safe = {k: v for k, v in cfg.items()
            if k not in SECRET_KEYS and not isinstance(v, dict)}
    secrets = {k: bool(cfg.get(k)) for k in SECRET_KEYS if k in cfg or k == "password"}
    return {"id": row["id"], "name": row["name"], "source": row["source"],
            "color": row.get("color", "blue"), "status": row["status"],
            "fields": safe, "secrets_set": {k: v for k, v in secrets.items() if v},
            "last_sync": row["last_sync"], "last_error": row["last_error"]}


def list_calendars() -> list[dict]:
    ensure_default_calendar()
    return [redacted(c) for c in
            db.q("SELECT * FROM calendars WHERE user_id=1 ORDER BY id")]


def ensure_default_calendar() -> int:
    row = db.qone("SELECT id FROM calendars WHERE user_id=1 AND source='local' LIMIT 1")
    if row:
        return row["id"]
    return db.run("INSERT INTO calendars (user_id,name,source,color) VALUES (1,'Personal','local','blue')")


def create_calendar(name: str, source: str = "local", color: str = "blue",
                    fields: dict | None = None) -> dict:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    fields = dict(fields or {})
    if source == "caldav" and not (fields.get("url") and fields.get("username")):
        raise ValueError("caldav needs url + username (+ password)")
    if source == "google" and not (fields.get("client_id") and fields.get("client_secret")):
        raise ValueError("google needs client_id + client_secret (see docs/GOOGLE_CALENDAR_SETUP.md)")
    cid = db.run("INSERT INTO calendars (user_id,name,source,config_json,color)"
                 " VALUES (1,?,?,?,?)",
                 (name.strip()[:120] or "Calendar", source, db.jdump(fields), color[:20]))
    return {"id": cid}


def update_calendar(cid: int, patch: dict) -> dict:
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (cid,))
    if not row:
        raise KeyError("calendar not found")
    cfg = _cfg(row)
    sets, params = [], []
    for k in ("name", "color", "status"):
        if k in patch and isinstance(patch[k], str):
            sets.append(f"{k}=?")
            params.append(patch[k].strip()[:120])
    if isinstance(patch.get("fields"), dict):
        for k, v in patch["fields"].items():
            if isinstance(v, str) and len(v) < 2000:
                cfg[k] = v.strip()
        sets.append("config_json=?")
        params.append(db.jdump(cfg))
    if sets:
        db.run(f"UPDATE calendars SET {', '.join(sets)} WHERE id=?", (*params, cid))
    db.run("UPDATE calendars SET last_error='' WHERE id=?", (cid,))
    return {"id": cid}


def delete_calendar(cid: int) -> None:
    db.run("DELETE FROM events WHERE calendar_id=? AND user_id=1", (cid,))
    db.run("DELETE FROM calendars WHERE id=? AND user_id=1", (cid,))


def _mark(cid: int, ok: bool, err: str = "") -> None:
    db.run("UPDATE calendars SET last_sync=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
           " last_error=? WHERE id=?", ("" if ok else err[:200], cid))


# --------------------------------------------------------------- events ---

def _iso(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError("starts_at/ends_at required")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"bad datetime: {v[:40]} (use ISO 8601)")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def create_event(calendar_id: int, title: str, starts_at: str, ends_at: str,
                 description: str = "", location: str = "", all_day: bool = False,
                 uid: str = "", etag: str = "") -> dict:
    cal = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (calendar_id,))
    if not cal:
        raise KeyError("calendar not found")
    s, e = _iso(starts_at), _iso(ends_at)
    if e < s:
        raise ValueError("ends_at is before starts_at")
    eid = db.run("INSERT INTO events (user_id,calendar_id,uid,title,description,location,"
                 "starts_at,ends_at,all_day) VALUES (1,?,?,?,?,?,?,?,?)",
                 (calendar_id, (uid or uuid.uuid4().hex[:12])[:120], title.strip()[:200],
                  description.strip()[:2000], location.strip()[:200], s, e, 1 if all_day else 0))
    if etag:
        db.run("UPDATE events SET etag=? WHERE id=?", (etag[:120], eid))
    from . import undo as _u
    _u.record("calendar.create", "create", "events", eid, None, f"events#{eid} {title.strip()[:80]}")
    # push to CalDAV origin (best effort — local row is source of truth)
    pushed = ""
    if db.DRY_RUN:
        db.blocked("caldav: event push skipped")
        pushed = "dry-run: push skipped"
    elif cal["source"] == "caldav":
        try:
            pushed = caldav_push(cal, {"uid": uid or "", "title": title, "description": description,
                                       "location": location, "starts_at": s, "ends_at": e})
        except Exception as ex:
            pushed = f"push failed: {ex}"[:150]
    if db.DRY_RUN and cal["source"] == "google":
        db.blocked("google: event push skipped")
        pushed = "dry-run: push skipped"
    elif cal["source"] == "google":
        try:
            from .calendar_sync import google_insert  # noqa
            google_insert(cal, {"title": title, "description": description,
                                "location": location, "starts_at": s, "ends_at": e})
            pushed = "pushed to google"
        except Exception as ex:
            pushed = f"push failed: {ex}"[:150]
    return {"id": eid, "pushed": pushed}


def update_event(eid: int, patch: dict) -> dict:
    row = db.qone("SELECT * FROM events WHERE id=? AND user_id=1", (eid,))
    if not row:
        raise KeyError("event not found")
    sets, params = [], []
    for k in ("title", "description", "location", "status", "url"):
        if k in patch and isinstance(patch[k], str):
            sets.append(f"{k}=?")
            params.append(patch[k].strip()[:2000])
    for k in ("starts_at", "ends_at"):
        if k in patch:
            sets.append(f"{k}=?")
            params.append(_iso(patch[k]))
    if "all_day" in patch:
        sets.append("all_day=?")
        params.append(1 if patch["all_day"] else 0)
    if sets:
        sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        db.run(f"UPDATE events SET {', '.join(sets)} WHERE id=?", (*params, eid))
        from . import undo as _u
        _u.record("calendar.update", "update", "events", eid, row,
                  f"events#{eid} {row.get('title', '')[:80]}")
    return {"id": eid}


def delete_event(eid: int) -> None:
    _before = db.qone("SELECT * FROM events WHERE id=? AND user_id=1", (eid,))
    db.run("DELETE FROM events WHERE id=? AND user_id=1", (eid,))
    from . import undo as _u
    _u.record("calendar.delete", "delete", "events", eid, _before,
              f"events#{eid} {(_before or {}).get('title', '')[:80]}")


def events_between(start_iso: str, end_iso: str) -> list[dict]:
    return db.q("SELECT e.*, c.name calendar_name, c.color calendar_color FROM events e "
                "LEFT JOIN calendars c ON c.id=e.calendar_id "
                "WHERE e.user_id=1 AND e.starts_at < ? AND e.ends_at > ? "
                "ORDER BY e.starts_at", (_iso(end_iso), _iso(start_iso)))


def _user_day(offset: int = 0) -> tuple[str, str]:
    try:
        from . import prefs as _p
        _tz = _p.user_tz()
    except Exception:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo("Africa/Nairobi")
    now = datetime.now(_tz)
    day = (now + timedelta(days=offset)).date()
    start = datetime(day.year, day.month, day.day, tzinfo=_tz)
    return start.astimezone(timezone.utc).isoformat(), \
        (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def todays_events() -> dict:
    s, e = _user_day(0)
    return {"events": events_between(s, e)}


def week_events() -> list[dict]:
    s, _ = _user_day(0)
    _, e = _user_day(7)
    return events_between(s, e)


# ---------------------------------------------------------------- sync ----

def sync_calendar(cid: int) -> dict:
    row = db.qone("SELECT * FROM calendars WHERE id=? AND user_id=1", (cid,))
    if not row:
        raise KeyError("calendar not found")
    if row["source"] == "local":
        _mark(cid, True)
        n = (db.qone("SELECT COUNT(*) c FROM events WHERE user_id=1 AND calendar_id=?",
                     (cid,)) or {}).get("c", 0)
        return {"ok": True, "source": "local", "events": n}
    try:
        if row["source"] == "caldav":
            res = caldav_pull(row)
        else:
            res = google_pull(row)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:150]}"
        _mark(cid, False, err)
        return {"ok": False, "source": row["source"], "error": err}
    _mark(cid, True)
    db.log_activity("integration", f"Calendar synced ({row['name']})",
                    f"{res.get('new', 0)} new, {res.get('updated', 0)} updated", "general")
    return {"ok": True, "source": row["source"], **res}


def _upsert_event(cal_id: int, ev: dict) -> str:
    """Insert or update by (calendar_id, uid). Returns new|updated|same."""
    row = db.qone("SELECT * FROM events WHERE user_id=1 AND calendar_id=? AND uid=?",
                  (cal_id, ev.get("uid", "")))
    if not row:
        db.run("INSERT INTO events (user_id,calendar_id,uid,title,description,location,"
               "starts_at,ends_at,all_day,url,etag) VALUES (1,?,?,?,?,?,?,?,?,?,?)",
               (cal_id, ev.get("uid", "")[:120], ev.get("title", "(no title)")[:200],
                ev.get("description", "")[:2000], ev.get("location", "")[:200],
                ev["starts_at"], ev["ends_at"], 1 if ev.get("all_day") else 0,
                ev.get("url", "")[:300], ev.get("etag", "")[:120]))
        return "new"
    changed = any((row.get(k) or "") != (ev.get(k) or "")
                  for k in ("title", "description", "location", "starts_at", "ends_at", "url"))
    if changed or (ev.get("etag") and ev["etag"] != (row.get("etag") or "")):
        db.run("UPDATE events SET title=?,description=?,location=?,starts_at=?,ends_at=?,"
               "all_day=?,url=?,etag=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
               (ev.get("title", "(no title)")[:200], ev.get("description", "")[:2000],
                ev.get("location", "")[:200], ev["starts_at"], ev["ends_at"],
                1 if ev.get("all_day") else 0, ev.get("url", "")[:300],
                ev.get("etag", "")[:120], row["id"]))
        return "updated"
    return "same"


# --------------------------------------------------------------- CalDAV ---

_DAV = "{DAV:}"
_CAL = "{urn:ietf:params:xml:ns:caldav}"


def parse_vevent(ics: str) -> dict | None:
    """Minimal VEVENT parser: unfolding + DTSTART/DTEND/DURATION/SUMMARY/etc."""
    lines = re.sub(r"\r\n[ \t]", "", (ics or "").replace("\r\n", "\n")).split("\n")
    in_ev, props = False, {}
    for ln in lines:
        up = ln.strip().upper()
        if up == "BEGIN:VEVENT":
            in_ev = True
            props = {}
        elif up == "END:VEVENT" and in_ev:
            break
        elif in_ev and ":" in ln:
            head, val = ln.split(":", 1)
            key = head.split(";")[0].upper()
            params = head.upper()
            props.setdefault(key, []).append((val.strip(), params))
    if not props or "DTSTART" not in props:
        return None

    def dt(key: str) -> tuple[str, bool]:
        raw, params = props[key][0]
        allday = "VALUE=DATE" in params or re.fullmatch(r"\d{8}", raw) is not None
        if allday:
            d = datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            return d.isoformat(), True
        m = re.match(r"(\d{8})T(\d{6})(Z?)", raw)
        if not m:
            raise ValueError(f"bad {key}: {raw[:30]}")
        d = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        tzid = re.search(r"TZID=([^;:]+)", params)
        if m.group(3):
            d = d.replace(tzinfo=timezone.utc)
        elif tzid:
            try:
                from zoneinfo import ZoneInfo
                d = d.replace(tzinfo=ZoneInfo(tzid.group(1)))
            except Exception:
                d = d.replace(tzinfo=timezone.utc)
        else:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(), False

    try:
        start, ad = dt("DTSTART")
    except ValueError:
        return None
    if "DTEND" in props:
        try:
            end, _ = dt("DTEND")
        except ValueError:
            end = start
    elif "DURATION" in props:
        dur = props["DURATION"][0][0]
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", dur)
        h, mi = int(m.group(1) or 0), int(m.group(2) or 0) if m else (1, 0)
        end = (datetime.fromisoformat(start) + timedelta(hours=h, minutes=mi)).isoformat()
    else:
        end = (datetime.fromisoformat(start) + timedelta(hours=1 if not ad else 24)).isoformat()
    first = lambda k: props[k][0][0] if k in props else ""  # noqa: E731
    if ad:  # all-day end is exclusive in ICS; keep at least the start day
        es = datetime.fromisoformat(end)
        if es <= datetime.fromisoformat(start):
            end = (datetime.fromisoformat(start) + timedelta(days=1)).isoformat()
    return {"uid": first("UID") or uuid.uuid4().hex[:12],
            "title": first("SUMMARY") or "(no title)",
            "description": first("DESCRIPTION"), "location": first("LOCATION"),
            "starts_at": start, "ends_at": end, "all_day": ad,
            "url": first("URL")}


def _dav_auth(cfg: dict) -> tuple[str, str]:
    return cfg.get("username", ""), cfg.get("password", "")


def caldav_pull(cal: dict, days_back: int = 30, days_fwd: int = 90) -> dict:
    cfg = _cfg(cal)
    base = (cfg.get("url") or "").rstrip("/")
    if not base:
        raise ValueError("caldav url missing")
    auth = _dav_auth(cfg)
    # 1. principal → calendar-home
    r = httpx.request("PROPFIND", base, auth=auth, depth="0",
                      headers={"Content-Type": "application/xml", "Depth": "0"},
                      content='<?xml version="1.0"?><d:propfind xmlns:d="DAV:">'
                              '<d:prop><d:current-user-principal/></d:prop></d:propfind>',
                      timeout=TIMEOUT)
    home = base
    if r.status_code in (200, 207):
        try:
            root = ET.fromstring(r.text)
            href = root.find(f".//{_DAV}href")
            if href is not None and href.text:
                hp = href.text.strip()
                home = hp if hp.startswith("http") else base + hp
        except ET.ParseError:
            pass
    # 2. REPORT time-range on the home (or the configured url directly)
    now = datetime.now(timezone.utc)
    s = (now - timedelta(days=days_back)).strftime("%Y%m%dT%H%M%SZ")
    e = (now + timedelta(days=days_fwd)).strftime("%Y%m%dT%H%M%SZ")
    body = ('<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/>'
            '<c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
            f'<c:comp-filter name="VEVENT"><c:time-range start="{s}" end="{e}"/>'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>")
    last_err = ""
    for target, depth in ((home, "1"), (base, "1")):
        r = httpx.request("REPORT", target, auth=auth,
                          headers={"Content-Type": "application/xml", "Depth": depth},
                          content=body, timeout=TIMEOUT)
        if r.status_code in (200, 207):
            break
        last_err = f"http {r.status_code}"
    else:
        raise RuntimeError(f"caldav REPORT failed: {last_err or 'no response'}")
    root = ET.fromstring(r.text)
    ns = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
    new = updated = 0
    for resp in root.findall("d:response", ns):
        etag_el = resp.find(f".//{_DAV}getetag")
        data_el = resp.find(f".//{_CAL}calendar-data")
        if data_el is None or not data_el.text:
            continue
        ev = parse_vevent(data_el.text)
        if not ev:
            continue
        ev["etag"] = (etag_el.text or "").strip("\"' ")[:120] if etag_el is not None else ""
        st = _upsert_event(cal["id"], ev)
        new += st == "new"
        updated += st == "updated"
    return {"new": new, "updated": updated}


def _ics_escape(v: str) -> str:
    return (v or "").replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def build_vevent(ev: dict) -> str:
    s = datetime.fromisoformat(ev["starts_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    e = datetime.fromisoformat(ev["ends_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    fmt = lambda d: d.strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//AURA OS//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{ev.get('uid') or uuid.uuid4().hex}\r\n"
            f"DTSTAMP:{fmt(datetime.now(timezone.utc))}\r\n"
            f"DTSTART:{fmt(s)}\r\nDTEND:{fmt(e)}\r\n"
            f"SUMMARY:{_ics_escape(ev.get('title', ''))}\r\n"
            f"DESCRIPTION:{_ics_escape(ev.get('description', ''))}\r\n"
            f"LOCATION:{_ics_escape(ev.get('location', ''))}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")


def caldav_push(cal: dict, ev: dict) -> str:
    cfg = _cfg(cal)
    base = (cfg.get("url") or "").rstrip("/")
    uid = ev.get("uid") or uuid.uuid4().hex
    r = httpx.put(f"{base}/{uid}.ics", auth=_dav_auth(cfg),
                  headers={"Content-Type": "text/calendar"}, content=build_vevent({**ev, "uid": uid}),
                  timeout=TIMEOUT)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"caldav PUT http {r.status_code}: {r.text[:120]}")
    return f"pushed {uid}.ics"


# --------------------------------------------------------------- Google ---

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar"


def google_auth_url(client_id: str, redirect_uri: str, state: str = "aura") -> str:
    return (GOOGLE_AUTH + "?" + urlencode(
        {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
         "scope": GOOGLE_SCOPES, "access_type": "offline", "prompt": "consent", "state": state}))


def google_exchange(cal: dict, code: str, redirect_uri: str) -> dict:
    cfg = _cfg(cal)
    r = httpx.post(GOOGLE_TOKEN, data={
        "client_id": cfg.get("client_id", ""), "client_secret": cfg.get("client_secret", ""),
        "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri},
        timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200 or "refresh_token" not in d:
        raise RuntimeError(f"oauth exchange failed: {str(d.get('error', r.status_code))[:150]}")
    cfg["refresh_token"] = d["refresh_token"]
    cfg["access_token"] = d.get("access_token", "")
    cfg["token_expiry"] = time.time() + int(d.get("expires_in", 3600)) - 60
    db.run("UPDATE calendars SET config_json=? WHERE id=?", (db.jdump(cfg), cal["id"]))
    return {"ok": True}


def _google_token(cal: dict) -> str:
    cfg = _cfg(cal)
    if cfg.get("access_token") and time.time() < float(cfg.get("token_expiry", 0)):
        return cfg["access_token"]
    r = httpx.post(GOOGLE_TOKEN, data={
        "client_id": cfg.get("client_id", ""), "client_secret": cfg.get("client_secret", ""),
        "refresh_token": cfg.get("refresh_token", ""), "grant_type": "refresh_token"},
        timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200 or "access_token" not in d:
        raise RuntimeError(f"token refresh failed: {str(d.get('error', r.status_code))[:150]}")
    cfg["access_token"] = d["access_token"]
    cfg["token_expiry"] = time.time() + int(d.get("expires_in", 3600)) - 60
    db.run("UPDATE calendars SET config_json=? WHERE id=?", (db.jdump(cfg), cal["id"]))
    return cfg["access_token"]


def _gdt(v: dict | None) -> tuple[str, bool]:
    if not v:
        raise ValueError("missing date")
    if v.get("date"):
        d = datetime.strptime(v["date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return d.isoformat(), True
    raw = v.get("dateTime", "")
    d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(), False


def google_pull(cal: dict) -> dict:
    tok = _google_token(cal)
    now = datetime.now(timezone.utc)
    params = {"timeMin": (now - timedelta(days=30)).isoformat(),
              "timeMax": (now + timedelta(days=90)).isoformat(),
              "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
    r = httpx.get(f"{GOOGLE_API}/calendars/primary/events", params=params,
                  headers={"Authorization": f"Bearer {tok}"}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"google list http {r.status_code}: {r.text[:150]}")
    new = updated = 0
    for g in r.json().get("items", []):
        if g.get("status") == "cancelled":
            continue
        try:
            s, ad = _gdt(g.get("start"))
            e, _ = _gdt(g.get("end"))
        except (ValueError, KeyError):
            continue
        st = _upsert_event(cal["id"], {"uid": g.get("id", ""), "title": g.get("summary", ""),
                                       "description": g.get("description", ""),
                                       "location": g.get("location", ""),
                                       "starts_at": s, "ends_at": e, "all_day": ad,
                                       "url": g.get("htmlLink", ""),
                                       "etag": (g.get("etag") or "")[:120]})
        new += st == "new"
        updated += st == "updated"
    return {"new": new, "updated": updated}


def google_insert(cal: dict, ev: dict) -> str:
    tok = _google_token(cal)
    r = httpx.post(f"{GOOGLE_API}/calendars/primary/events",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"summary": ev.get("title", ""), "description": ev.get("description", ""),
                         "location": ev.get("location", ""),
                         "start": {"dateTime": ev["starts_at"]}, "end": {"dateTime": ev["ends_at"]}},
                   timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"google insert http {r.status_code}: {r.text[:150]}")
    return r.json().get("id", "")


# ------------------------------------------------------- NL date parse ---

_WDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
          "friday": 4, "saturday": 5, "sunday": 6}
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def parse_event_time(text: str, now: datetime | None = None) -> tuple[str, str] | None:
    """Parse 'tomorrow 2pm', 'friday 10:30', 'in 2 hours', 'sep 12 9am'…

    Returns (starts_iso, ends_iso) in UTC, or None when no time found.
    Duration: 'for 30 min' / 'for 2h', else 1h."""
    low = f" {text.lower()} "
    try:
        from . import prefs as _p
        nbo = _p.user_tz()
    except Exception:
        from zoneinfo import ZoneInfo
        nbo = ZoneInfo("Africa/Nairobi")
    now = now or datetime.now(nbo)
    if now.tzinfo is None:
        now = now.replace(tzinfo=nbo)

    dur_min = 60
    m = re.search(r"\bfor (\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minutes)\b", low)
    if m:
        dur_min = int(float(m.group(1)) * (60 if m.group(2).startswith("h") else 1))
        dur_min = max(5, min(dur_min, 24 * 60))

    def at(day: datetime, h: int, mi: int = 0) -> tuple[str, str]:
        s = day.replace(hour=h, minute=mi, second=0, microsecond=0)
        if s.tzinfo is None:
            s = s.replace(tzinfo=nbo)
        e = s + timedelta(minutes=dur_min)
        return s.astimezone(timezone.utc).isoformat(), e.astimezone(timezone.utc).isoformat()

    m = re.search(r"\bin (\d+)\s*(h|hr|hours?|min|mins|minutes)\b", low)
    if m:
        delta = timedelta(hours=int(m.group(1)) if m.group(2).startswith("h") else 0,
                          minutes=0 if m.group(2).startswith("h") else int(m.group(1)))
        s = now + delta
        e = s + timedelta(minutes=dur_min)
        return s.astimezone(timezone.utc).isoformat(), e.astimezone(timezone.utc).isoformat()

    tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    h24 = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", low)
    hhmm = None
    if tm:
        h = int(tm.group(1)) % 12 + (12 if tm.group(3) == "pm" else 0)
        hhmm = (h, int(tm.group(2) or 0))
    elif h24 and re.search(r"\b(at|tomorrow|today|on|mon|tue|wed|thu|fri|sat|sun)\b.{0,12}" + re.escape(h24.group(0)), low):
        hhmm = (int(h24.group(1)), int(h24.group(2)))

    base = now
    if "tomorrow" in low:
        base = now + timedelta(days=1)
    else:
        for name, wd in _WDAYS.items():
            if re.search(rf"\b{name}\b", low):
                delta = (wd - now.weekday()) % 7 or 7
                if "next" in low:
                    delta += 7
                base = now + timedelta(days=delta)
                break
        else:
            m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (\d{1,2})\b", low)
            if m:
                y = now.year
                cand = now.replace(month=_MONTHS[m.group(1)], day=min(int(m.group(2)), 28))
                if cand.date() < now.date():
                    cand = cand.replace(year=y + 1)
                base = cand
    if hhmm is None:
        return None
    s_iso, e_iso = at(base, *hhmm)
    if datetime.fromisoformat(s_iso) < now.astimezone(timezone.utc) - timedelta(minutes=1):
        s_iso, e_iso = at(base + timedelta(days=1), *hhmm)
    return s_iso, e_iso


def event_title_from_text(text: str) -> str:
    t = re.sub(r"(?i)^\s*(please\s+)?(schedule|book|add|create|set\s*up)\s+(a|an|my)?\s*", "", text.strip())
    t = re.sub(r"(?i)\b(today|tomorrow|next week|on \w+day|\w+day)\b", "", t)
    t = re.sub(r"\b\d{1,2}(?::\d{2})?\s*(am|pm)\b", "", t)
    t = re.sub(r"\b(at\s+)?([01]?\d|2[0-3]):[0-5]\d\b", "", t)
    t = re.sub(r"\bin \d+\s*(h|hr|hours?|min|mins|minutes)\b", "", t)
    t = re.sub(r"\bfor \d+(?:\.\d+)?\s*(h|hr|hrs|hour|hours|min|mins|minutes)\b", "", t)
    t = re.sub(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}\b", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—,.:")
    return t[:200] or "Meeting"
