"""AURA inbound email — IMAP sync (live) or sample inbox (sandbox), with triage.

Accounts are sandbox by default: syncing loads a realistic sample inbox and
no network happens. Live mode polls IMAP UNSEEN (read-only on the server —
AURA tracks its own seen flags). Passwords live in config_json and are never
returned by any helper here.
"""
from __future__ import annotations

import imaplib
import re
import time
from datetime import datetime, timezone
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from typing import Any

from . import db

TRIAGE = ("unread", "action", "waiting", "fyi", "done")
FETCH_LIMIT = 25
BODY_CHARS = 4000


# ------------------------------------------------------------- accounts ---

def _cfg(row: dict) -> dict:
    cfg = db.jload(row.get("config_json"), {})
    return cfg if isinstance(cfg, dict) else {}


def list_accounts() -> list[dict]:
    out = []
    for a in db.q("SELECT * FROM email_accounts WHERE user_id=1 ORDER BY id"):
        cfg = _cfg(a)
        n = (db.qone("SELECT COUNT(*) c FROM emails WHERE user_id=1 AND account_id=? AND seen=0",
                     (a["id"],)) or {}).get("c", 0)
        out.append({"id": a["id"], "name": a["name"], "host": a["host"], "port": a["port"],
                    "username": a["username"], "mode": a["mode"], "status": a["status"],
                    "has_password": bool(cfg.get("password")), "unseen": n,
                    "last_sync": a["last_sync"], "last_error": a["last_error"]})
    return out


def create_account(name: str, host: str = "", port: int = 993, username: str = "",
                   password: str = "", mode: str = "sandbox") -> dict:
    if mode not in ("sandbox", "live"):
        raise ValueError("mode must be sandbox|live")
    if mode == "live" and not (host and username and password):
        raise ValueError("live mode needs host, username and password")
    aid = db.run("INSERT INTO email_accounts (user_id,name,host,port,username,config_json,mode)"
                 " VALUES (1,?,?,?,?,?,?)",
                 (name.strip() or "Inbox", host.strip(), int(port or 993),
                  username.strip(), db.jdump({"password": password}), mode))
    return {"id": aid}


def update_account(aid: int, patch: dict) -> dict:
    row = db.qone("SELECT * FROM email_accounts WHERE id=? AND user_id=1", (aid,))
    if not row:
        raise KeyError("account not found")
    cfg = _cfg(row)
    sets, params = [], []
    for k in ("name", "host", "username", "status"):
        if k in patch and isinstance(patch[k], str):
            sets.append(f"{k}=?")
            params.append(patch[k].strip()[:200])
    if "port" in patch:
        sets.append("port=?")
        params.append(max(1, min(65535, int(patch["port"]))))
    if "mode" in patch:
        if patch["mode"] not in ("sandbox", "live"):
            raise ValueError("mode must be sandbox|live")
        sets.append("mode=?")
        params.append(patch["mode"])
    if "password" in patch:
        cfg["password"] = (patch["password"] or "").strip()
        sets.append("config_json=?")
        params.append(db.jdump(cfg))
    if patch.get("mode") == "live" or (row["mode"] == "live" and "mode" not in patch):
        host = patch.get("host", row["host"])
        user = patch.get("username", row["username"])
        if not (host and user and cfg.get("password")):
            raise ValueError("live mode needs host, username and password")
    if sets:
        db.run(f"UPDATE email_accounts SET {', '.join(sets)} WHERE id=?", (*params, aid))
    db.run("UPDATE email_accounts SET last_error='' WHERE id=?", (aid,))
    return {"id": aid}


def delete_account(aid: int) -> None:
    db.run("DELETE FROM emails WHERE account_id=? AND user_id=1", (aid,))
    db.run("DELETE FROM email_accounts WHERE id=? AND user_id=1", (aid,))


# ---------------------------------------------------------------- sync ----

def _decode(h: Any) -> str:
    if not h:
        return ""
    parts = []
    for text, enc in decode_header(str(h)):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or "utf-8", "replace"))
            except Exception:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def _body_text(msg: Message) -> str:
    plain, html = "", ""
    try:
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
    except Exception:
        parts = [msg]
    for p in parts:
        try:
            ctype = (p.get_content_type() or "").lower()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = p.get_payload(decode=True)
            if not payload:
                continue
            charset = p.get_content_charset() or "utf-8"
            text = payload.decode(charset, "replace")
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not html:
                html = text
        except Exception:
            continue
    if plain.strip():
        return plain.strip()
    if html.strip():
        txt = re.sub(r"(?i)<(script|style)[^>]*>.*?</\1>", " ", html)
        txt = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", txt)
        txt = re.sub(r"<[^>]+>", " ", txt)
        return re.sub(r"\s+", " ", txt).strip()
    return ""


def _store(account_id: int, uid: str, mid: str, sender: str, to: str,
           subject: str, body: str, mail_date: str) -> bool:
    """Insert unless uid/message-id already present. Returns True if new."""
    if uid and db.qone("SELECT 1 x FROM emails WHERE user_id=1 AND account_id=? AND uid=?",
                       (account_id, uid)):
        return False
    if mid and db.qone("SELECT 1 x FROM emails WHERE user_id=1 AND account_id=? AND message_id=?",
                       (account_id, mid)):
        return False
    clean = re.sub(r"\s+", " ", (body or "").strip())[:BODY_CHARS]
    db.run("INSERT INTO emails (user_id,account_id,uid,message_id,sender,recipients,subject,"
           "snippet,body,mail_date) VALUES (1,?,?,?,?,?,?,?,?,?)",
           (account_id, uid[:120], mid[:200], sender[:200], to[:300],
            subject[:300], clean[:280], clean, mail_date[:40]))
    return True


def _mark(aid: int, ok: bool, err: str = "") -> None:
    db.run("UPDATE email_accounts SET last_sync=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
           " last_error=? WHERE id=?", ("" if ok else err[:200], aid))


def sync_account(aid: int) -> dict:
    row = db.qone("SELECT * FROM email_accounts WHERE id=? AND user_id=1", (aid,))
    if not row:
        raise KeyError("account not found")
    if row["mode"] != "live":
        n = seed_sample_inbox(aid)
        _mark(aid, True)
        db.log_activity("integration", f"Sandbox inbox seeded ({row['name']})",
                        f"{n} sample messages", "general")
        return {"ok": True, "mode": "sandbox", "new": n}
    cfg = _cfg(row)
    t0 = time.time()
    try:
        box: imaplib.IMAP4 = imaplib.IMAP4_SSL(row["host"], int(row["port"] or 993))
        try:
            box.login(row["username"], cfg.get("password", ""))
            box.select("INBOX", readonly=True)
            _, data = box.search(None, "UNSEEN")
            uids = (data[0] or b"").split()[-FETCH_LIMIT:]
            new = 0
            for u in uids:
                _, f = box.fetch(u, "(RFC822)")
                raw = f[0][1] if f and f[0] else b""
                if not raw:
                    continue
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                body = _body_text(msg)
                try:
                    mdate = msg.get("date").datetime.isoformat() if msg.get("date") else ""
                except Exception:
                    mdate = ""
                if _store(aid, f"srv-{u.decode()}", _decode(msg.get("message-id")),
                          _decode(msg.get("from")), _decode(msg.get("to")),
                          _decode(msg.get("subject")), body, mdate):
                    new += 1
        finally:
            try:
                box.logout()
            except Exception:
                pass
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:150]}"
        _mark(aid, False, err)
        return {"ok": False, "mode": "live", "new": 0, "error": err}
    _mark(aid, True)
    ms = int((time.time() - t0) * 1000)
    db.log_activity("integration", f"Mail synced ({row['name']})", f"{new} new in {ms}ms", "general")
    return {"ok": True, "mode": "live", "new": new, "latency_ms": ms}


# ------------------------------------------------------- sample inbox ---

SAMPLES: list[tuple[str, str, str, str]] = [
    ("Brian Otieno <brian@clientx.com>", "Re: ShopLite launch checklist",
     "Morning! The launch checklist looks good. Two things before Friday: "
     "fix the M-Pesa callback timeout and confirm the delivery date for the "
     "admin dashboard. Can you reply with an ETA today?",
     "action"),
    ("M-Pesa <alerts@mpesa.example>", "Payment received: KES 12,500",
     "You have received KES 12,500.00 from SHOPLITE LTD. Txn ID QK7X2M9P. "
     "New balance KES 48,320.00.",
     "fyi"),
    ("Wanjiru (Recruiter) <wanjiru@techtalent.example>", "Senior Frontend role — Nairobi (hybrid)",
     "Hi! I came across your profile and thought you'd be a great fit for a "
     "Senior Frontend role at a fintech in Westlands — KES 350-450k, hybrid. "
     "Open to a 15-min chat this week?",
     "action"),
    ("Kenya Power <bills@kplc.example>", "Your electricity bill is ready",
     "Dear customer, your bill for meter 37192645 is KES 2,340 due 20 Sep. "
     "Pay via M-Pesa paybill 888880.",
     "action"),
    ("Morning Brew <news@morningbrew.example>", "☕ Tue markets + AI roundup",
     "Markets up 0.4%. In AI: three new open-weight reasoning models dropped "
     "this week. Plus: Nairobi startup raises $4M seed. Unsubscribe link below.",
     "fyi"),
    ("GitHub <notifications@github.com>", "[aura-os] CI passed on main",
     "All checks have passed: 80 unit tests, 36 frontend tests, build clean. "
     "No action needed.",
     "fyi"),
    ("Amina Said <amina@shoplite.example>", "Waiting on: contract signature",
     "Hi! Just checking whether you signed the maintenance contract I sent "
     "last Thursday — our finance team needs it before releasing the deposit.",
     "waiting"),
    ("Jambojet <deals@jambojet.example>", "Flash sale: NBO → Diani 4,999",
     "48-hour flash sale on coastal routes. Book by midnight Thursday. "
     "Terms apply. Unsubscribe here.",
     "fyi"),
]


def seed_sample_inbox(aid: int) -> int:
    n = 0
    for i, (sender, subject, body, _triage) in enumerate(SAMPLES):
        if _store(aid, f"sample-{i}", f"<sample-{i}@aura.local>", sender, "me@aura.local",
                  subject, body,
                  datetime.now(timezone.utc).isoformat()):
            n += 1
    return n


# ---------------------------------------------------------------- triage --

_RULES: list[tuple[str, str, str]] = [
    ("fyi", "newsletter/unsubscribe footer", r"unsubscrib|newsletter|daily digest|roundup"),
    ("fyi", "automated notification", r"^(github|ci|alerts?|notifications?)\b|no action needed|all checks have passed"),
    ("fyi", "payment receipt", r"payment received|txn id|paybill|receipt for"),
    ("action", "bill due", r"bill .{0,20}(due|ready)|amount due|pay by|paybill \d"),
    ("action", "direct ask/ETA", r"\b(eta|asap|today|by friday|please (reply|confirm|send|review|sign))\b"),
    ("waiting", "waiting on someone", r"\bwaiting on\b|checking whether|just checking|following up"),
]


def _rule_triage(subject: str, body: str, sender: str) -> tuple[str, str] | None:
    text = f"{subject}\n{sender}\n{body[:600]}".lower()
    for triage, reason, pat in _RULES:
        if re.search(pat, text):
            return triage, f"rule: {reason}"
    return None


def _llm_triage(subject: str, snippet: str) -> tuple[str, str] | None:
    """One-shot classification via the model chain. None when unavailable."""
    try:
        from .inference import router
        text, model = router.generate([
            {"role": "system", "content": "Classify this email with ONE word: action, waiting, fyi, or done. "
             "action = needs my reply/effort. waiting = I'm waiting on someone. fyi = informative only. Reply with just the word."},
            {"role": "user", "content": f"Subject: {subject[:160]}\n{snippet[:400]}"}],
            purpose="triage")
    except Exception:
        return None
    word = (text or "").strip().lower().split()[0:1]
    if word and word[0] in ("action", "waiting", "fyi", "done"):
        return word[0], f"llm: {model}"
    return None


def triage_unread(account_id: int | None = None, limit: int = 20, use_llm: bool = True) -> dict:
    q = "SELECT * FROM emails WHERE user_id=1 AND triage='unread'"
    params: tuple = ()
    if account_id:
        q += " AND account_id=?"
        params = (account_id,)
    rows = db.q(q + " ORDER BY id LIMIT ?", (*params, limit))
    done, llm_used = 0, 0
    for m in rows:
        hit = _rule_triage(m["subject"], m["body"], m["sender"])
        if not hit and use_llm and llm_used < 10:
            hit = _llm_triage(m["subject"], m["snippet"])
            if hit:
                llm_used += 1
        if not hit:
            continue
        db.run("UPDATE emails SET triage=?, triage_reason=? WHERE id=?", (*hit, m["id"]))
        done += 1
    return {"triaged": done, "llm_used": llm_used, "checked": len(rows)}


# ----------------------------------------------------------------- read ---

def unread_count(account_id: int | None = None) -> int:
    q = "SELECT COUNT(*) c FROM emails WHERE user_id=1 AND seen=0"
    params: tuple = ()
    if account_id:
        q += " AND account_id=?"
        params = (account_id,)
    return ((db.qone(q, params)) or {}).get("c", 0)


def top_unread(limit: int = 5) -> list[dict]:
    return db.q("SELECT id, sender, subject, snippet, triage, mail_date FROM emails "
                "WHERE user_id=1 AND seen=0 ORDER BY id DESC LIMIT ?", (limit,))


def list_emails(account_id: int | None = None, unread_only: bool = False,
                triage: str = "", limit: int = 50) -> list[dict]:
    q = ("SELECT id, account_id, sender, subject, snippet, mail_date, seen, triage,"
         " triage_reason FROM emails WHERE user_id=1")
    params: list = []
    if account_id:
        q += " AND account_id=?"
        params.append(account_id)
    if unread_only:
        q += " AND seen=0"
    if triage:
        q += " AND triage=?"
        params.append(triage)
    return db.q(q + " ORDER BY id DESC LIMIT ?", (*params, max(1, min(200, limit))))


def get_email(mid: int) -> dict | None:
    return db.qone("SELECT * FROM emails WHERE id=? AND user_id=1", (mid,))


def set_email(mid: int, seen: bool | None = None, triage: str | None = None) -> dict:
    if triage is not None and triage not in TRIAGE:
        raise ValueError(f"triage must be one of {', '.join(TRIAGE)}")
    sets, params = [], []
    if seen is not None:
        sets.append("seen=?")
        params.append(1 if seen else 0)
    if triage is not None:
        sets.append("triage=?")
        params.append(triage)
    if sets:
        db.run(f"UPDATE emails SET {', '.join(sets)} WHERE id=? AND user_id=1", (*params, mid))
    return {"id": mid}
