"""Rate limiting + security headers (stdlib-only, per-IP sliding windows).

Scopes (requests/min, 0 disables): chat (POST /api/chat/stream), upload
(POST /api/files/upload + heavy voice ops), api (everything else under
/api). Limits live in
config so tests can monkeypatch them; set AURA_RATE_LIMIT_ENABLED=0 to
switch the middleware off entirely.
"""
from __future__ import annotations

import time
from collections import deque
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
WINDOW = 60.0


def scope_for(method: str, path: str) -> tuple[str, int] | None:
    if not path.startswith("/api/"):
        return None
    if method == "POST" and path == "/api/chat/stream":
        return ("chat", config.RL_CHAT_PER_MIN)
    if method == "POST" and path in ("/api/files/upload", "/api/voice/transcribe",
                                     "/api/voice/speak"):
        return ("upload", config.RL_UPLOAD_PER_MIN)
    return ("api", config.RL_API_PER_MIN)


def check(ip: str, scope: str, limit: int) -> tuple[bool, int, int]:
    """Sliding-window check. Returns (allowed, remaining, retry_after_s)."""
    if limit <= 0:
        return True, 0, 0
    now = time.time()
    q = _hits[(ip, scope)]
    while q and now - q[0] >= WINDOW:
        q.popleft()
    if len(q) >= limit:
        return False, 0, max(1, int(WINDOW - (now - q[0])))
    q.append(now)
    return True, limit - len(q), 0


def reset() -> None:
    _hits.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if config.RATE_LIMIT_ENABLED:
            scoped = scope_for(request.method, request.url.path)
            if scoped:
                scope, limit = scoped
                ip = request.client.host if request.client else "unknown"
                allowed, remaining, retry = check(ip, scope, limit)
                if not allowed:
                    return JSONResponse(
                        {"detail": f"rate limit exceeded, retry in {retry}s"},
                        status_code=429,
                        headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(limit),
                                 "X-RateLimit-Remaining": "0"})
                resp = await call_next(request)
                resp.headers["X-RateLimit-Limit"] = str(limit)
                resp.headers["X-RateLimit-Remaining"] = str(remaining)
                return resp
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return resp
