"""Mail router — email accounts, emails, triage."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

mail_r = APIRouter(prefix="/mail", tags=["mail"])


@mail_r.get("/accounts")
def list_mail_accounts():
    from .. import mailbox as _m
    return {"accounts": _m.list_accounts()}


@mail_r.post("/accounts")
def create_mail_account(b: dict):
    from .. import mailbox as _m
    try:
        return _m.create_account(b.get("name", ""), b.get("host", ""), b.get("port", 993),
                                 b.get("username", ""), b.get("password", ""),
                                 b.get("mode", "sandbox"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.patch("/accounts/{aid}")
def update_mail_account(aid: int, patch: dict):
    from .. import mailbox as _m
    try:
        return _m.update_account(aid, patch)
    except KeyError:
        raise HTTPException(404, "account not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.delete("/accounts/{aid}")
def delete_mail_account(aid: int):
    from .. import mailbox as _m
    _m.delete_account(aid)
    return {"ok": True}


@mail_r.post("/accounts/{aid}/sync")
def sync_mail_account(aid: int):
    from .. import mailbox as _m
    try:
        return _m.sync_account(aid)
    except KeyError:
        raise HTTPException(404, "account not found")


@mail_r.get("/emails")
def list_mail(account_id: int | None = None, unread_only: bool = False,
              triage: str = "", limit: int = 50):
    from .. import mailbox as _m
    if triage and triage not in _m.TRIAGE:
        raise HTTPException(400, f"triage must be one of {', '.join(_m.TRIAGE)}")
    return {"emails": _m.list_emails(account_id, unread_only, triage, limit),
            "unread": _m.unread_count(account_id)}


@mail_r.get("/emails/{mid}")
def get_mail(mid: int):
    from .. import mailbox as _m
    m = _m.get_email(mid)
    if not m:
        raise HTTPException(404, "email not found")
    return m


@mail_r.patch("/emails/{mid}")
def patch_mail(mid: int, b: dict):
    from .. import mailbox as _m
    try:
        return _m.set_email(mid, b.get("seen"), b.get("triage"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@mail_r.post("/triage")
def run_triage(b: dict | None = None):
    from .. import mailbox as _m
    b = b or {}
    return _m.triage_unread(b.get("account_id"), int(b.get("limit", 20) or 20))
