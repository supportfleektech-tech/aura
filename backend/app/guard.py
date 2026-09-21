"""Cross-site request guard — the no-login fortress needs one hard rule:

A *browser* may only mutate AURA from the same origin AURA is served on
(or an origin explicitly listed in AURA_ALLOWED_ORIGINS). Any other page on
the internet that tries `fetch("http://127.0.0.1:8000/api/terminal/exec")`
from the user's laptop gets a 403 before touching anything.

Non-browser callers (Telegram/WhatsApp webhooks, curl, scripts, monitoring)
never send an Origin header — they are unaffected. GET/HEAD/OPTIONS are
unaffected (reads don't mutate; preflight is CORS's business).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config

MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def _host_of(value: str) -> str:
    v = (value or "").strip().lower()
    if "://" in v:
        v = v.split("://", 1)[1]
    return v.rstrip("/")


class OriginGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # noqa: ANN001
        if request.method in MUTATING and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin") or ""
            if origin:
                ohost = _host_of(origin)
                rhost = _host_of(request.headers.get("host") or "")
                if ohost != rhost and ohost not in config.ALLOWED_ORIGIN_HOSTS:
                    return JSONResponse(
                        {"detail": "cross-site request blocked — AURA is single-user and only accepts "
                                   "mutations from its own origin (or AURA_ALLOWED_ORIGINS). "
                                   "Non-browser clients are unaffected."},
                        status_code=403)
        return await call_next(request)
