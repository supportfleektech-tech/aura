from typing import Any, Literal
import json
import re
import socket
import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import config, db, prefs

router = APIRouter(prefix="/mcp/connections", tags=["mcp"])

MAX_CONNECTIONS = 4
MAX_TOOLS = 64
MAX_PAGES = 3
MAX_WIRE_BYTES = 1024 * 1024
MCP_TABLE = "mcp_connections"

def _get(obj, key, default=None):
    if hasattr(obj, "get"):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_tool_dict(tool: Any) -> dict:
    if hasattr(tool, "model_dump"):
        return tool.model_dump()
    return tool


def _get_name(obj):
    return getattr(obj, "name", _get(obj, "name"))


def init_mcp():
    db.run(f"""
        CREATE TABLE IF NOT EXISTS {MCP_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            allow_localhost INTEGER NOT NULL DEFAULT 0,
            bearer_env TEXT,
            enabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.run(f"CREATE INDEX IF NOT EXISTS idx_{MCP_TABLE}_enabled ON {MCP_TABLE}(enabled)")


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    url: str = Field(min_length=1, max_length=512)
    allow_localhost: bool = False
    bearer_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")


class ConnectionOut(BaseModel):
    id: int
    name: str
    url: str
    allow_localhost: bool
    bearer_env: str | None
    enabled: bool
    created_at: str
    updated_at: str


class CallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    confirmed: bool = True
    confirmation_id: str = Field(min_length=32, max_length=128)

    @field_validator("confirmed", mode="before")
    @classmethod
    def _confirm_must_be_true(cls, v):
        if v is not True:
            raise ValueError("confirmed must be exactly true")
        return v


@dataclass
class PreparedCall:
    tool: str
    arguments: dict[str, Any]
    confirmation_id: str
    connection_id: int


_prepared_calls: dict[str, PreparedCall] = {}


def _validate_url(url: str, allow_localhost: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must use bearer_env, not URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Query and fragment not allowed")

    try:
        host = parsed.hostname or ""
    except ValueError:
        raise ValueError("Invalid URL")

    if not host:
        raise ValueError("Host required")

    if host in ("localhost", "127.0.0.1", "[::1]") or host.startswith("127.") or host == "::ffff:127.0.0.1":
        if not allow_localhost:
            raise ValueError("Localhost requires allow_localhost=true")
        if parsed.scheme != "http":
            raise ValueError("Localhost must use http")
        if parsed.path != "/mcp":
            raise ValueError("Localhost path must be /mcp")
        return

    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        raise ValueError("Raw IP addresses not allowed for remote")

    if host.startswith("10.") or host.startswith("192.168.") or (host.startswith("172.") and 16 <= int(host.split(".")[1]) <= 31):
        raise ValueError("Private LAN addresses not allowed")

    if re.match(r"^\[.*\]$", host):
        raise ValueError("IPv6 literals not supported")

    # Remote URLs must use HTTPS
    if parsed.scheme != "https":
        raise ValueError("Remote URLs must use HTTPS")


async def resolve_destination(url: str, allow_localhost: bool) -> tuple[str, list[str]]:
    _validate_url(url, allow_localhost)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    if host in ("localhost", "127.0.0.1", "[::1]"):
        return host, [host]

    answers = await asyncio.to_thread(socket.getaddrinfo, host, port, socket.AF_INET, socket.SOCK_STREAM)
    ips = [ans[4][0] for ans in answers if ans[4][0] != host]

    for ip in ips:
        if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31:
            raise ValueError("Mixed public/private DNS results rejected")

    return host, ips


class BoundedTransport(httpx.BaseTransport):
    def __init__(self, base_url: str, pinned_ip: str, inner: httpx.BaseTransport):
        self.base_url = base_url
        self.pinned_ip = pinned_ip
        self.inner = inner
        parsed = urlparse(base_url)
        self._expected_path = parsed.path
        self._host_header = parsed.hostname or ""
        self._scheme = parsed.scheme

    def _rewrite_request(self, request: httpx.Request) -> httpx.Request:
        # Rewrite URL to use pinned IP while preserving Host header for TLS SNI
        new_url = httpx.URL(
            scheme=self._scheme,
            host=self.pinned_ip,
            port=request.url.port,
            path=request.url.path,
            query=request.url.query,
        )
        headers = dict(request.headers)
        headers["host"] = self._host_header
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self._host_header
        return httpx.Request(
            method=request.method,
            url=new_url,
            headers=headers,
            content=request.content,
            extensions=extensions,
        )

    def _check_request(self, request: httpx.Request) -> None:
        if request.url.path != self._expected_path:
            raise ValueError("Endpoint path mismatch")
        if len(request.content) > MAX_WIRE_BYTES:
            raise ValueError("Request body too large")

    def _check_response(self, response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise ValueError("Redirect not allowed")
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_WIRE_BYTES:
            raise ValueError("Response body too large")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._check_request(request)
        request = self._rewrite_request(request)
        response = self.inner.handle_request(request)
        self._check_response(response)
        return response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._check_request(request)
        request = self._rewrite_request(request)
        response = await self.inner.handle_async_request(request)
        self._check_response(response)
        return response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@dataclass
class MCPConnectionConfig:
    url: str
    allow_localhost: bool
    bearer_env: str | None


async def _session_ctx(config: MCPConnectionConfig):
    return await _real_session_ctx(config)


async def _real_session_ctx(config: MCPConnectionConfig):
    host, ips = await resolve_destination(config.url, config.allow_localhost)
    pinned = ips[0] if ips else host

    transport = BoundedTransport(config.url, pinned, httpx.AsyncHTTPTransport())

    headers = {"Content-Type": "application/json"}
    if config.bearer_env:
        token = os.environ.get(config.bearer_env) or prefs.get(config.bearer_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"

    client = httpx.AsyncClient(
        base_url=config.url,
        transport=BoundedTransport(config.url, pinned, httpx.AsyncHTTPTransport()),
        headers=headers,
        timeout=30.0,
    )

    class Session:
        def __init__(self, client: httpx.AsyncClient):
            self._client = client
            self._initialized = False

        async def initialize(self):
            await self._client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}})
            self._initialized = True

        async def list_tools(self, cursor: str | None = None) -> Any:
            if not self._initialized:
                await self.initialize()
            params = {"cursor": cursor} if cursor else {}
            resp = await self._client.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": params})
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["result"]

        async def call_tool(self, name: str, arguments: dict) -> Any:
            if not self._initialized:
                await self.initialize()
            resp = await self._client.post("/", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["result"]

        async def close(self):
            await self._client.aclose()

    yield Session(client)

open_session = _session_ctx


def validate_schema(schema: dict) -> None:
    def check(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            if "$ref" in obj:
                raise ValueError("$ref not allowed")
            if "pattern" in obj:
                raise ValueError("pattern not allowed")
            for v in obj.values():
                check(v, path)
        elif isinstance(obj, list):
            for v in obj:
                check(v, path)

    check(schema)


def validate_arguments(schema: dict, arguments: dict) -> None:
    validate_schema(schema)

    def validate(schema: dict, value: Any, path: str = "") -> None:
        typ = schema.get("type")
        if typ == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: expected object")
            required = schema.get("required", [])
            props = schema.get("properties", {})
            for k, v in value.items():
                if k not in props:
                    raise ValueError(f"{path}.{k}: additional property not allowed")
                validate(props[k], v, f"{path}.{k}")
            for req in required:
                if req not in value:
                    raise ValueError(f"{path}.{req}: required")
        elif typ == "string":
            if not isinstance(value, str):
                raise ValueError(f"{path}: expected string")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                raise ValueError(f"{path}: string too long")
        elif typ == "number":
            if not isinstance(value, (int, float)):
                raise ValueError(f"{path}: expected number")
        elif typ == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{path}: expected boolean")
        elif typ == "integer":
            if not isinstance(value, int):
                raise ValueError(f"{path}: expected integer")
        elif typ == "array":
            if not isinstance(value, list):
                raise ValueError(f"{path}: expected array")
        else:
            raise ValueError(f"Unsupported type: {typ}")

    validate(schema, arguments)


@router.get("")
async def list_connections():
    rows = db.q(f"SELECT * FROM {MCP_TABLE} ORDER BY id")
    return {"connections": [ConnectionOut(**dict(r)).model_dump() for r in rows]}


@router.post("", status_code=201)
async def add_connection(req: ConnectionIn):
    FORBIDDEN_BEARER_ENVS = {"PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "PWD", "TMPDIR", "EDITOR", "VISUAL"}
    if req.bearer_env and not re.match(r"^[A-Z_][A-Z0-9_]*$", req.bearer_env):
        raise HTTPException(422, "Invalid bearer_env name")
    if req.bearer_env in FORBIDDEN_BEARER_ENVS:
        raise HTTPException(422, f"bearer_env '{req.bearer_env}' is a system environment variable and cannot be used")
    try:
        _validate_url(req.url, req.allow_localhost)
    except ValueError as e:
        raise HTTPException(422, str(e))
    count = db.qone(f"SELECT COUNT(*) as c FROM {MCP_TABLE}")["c"]
    if count >= MAX_CONNECTIONS:
        raise HTTPException(409, "Connection limit reached")
    try:
        db.run(f"INSERT INTO {MCP_TABLE} (name, url, allow_localhost, bearer_env, enabled) VALUES (?,?,?,?,0)",
               (req.name, req.url, int(req.allow_localhost), req.bearer_env))
    except Exception:
        raise HTTPException(409, "Name already exists")
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE name=?", (req.name,))
    return ConnectionOut(**dict(row)).model_dump()


@router.get("/{conn_id}")
async def get_connection(conn_id: int):
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=?", (conn_id,))
    if not row:
        raise HTTPException(404, "Not found")
    return ConnectionOut(**dict(row)).model_dump()


@router.patch("/{conn_id}")
async def update_connection(conn_id: int, req: Request):
    body = await req.json()
    if "enabled" in body:
        enabled = 1 if body["enabled"] else 0
        db.run(f"UPDATE {MCP_TABLE} SET enabled=?, updated_at=datetime('now') WHERE id=?", (enabled, conn_id))
        if not enabled:
            _prepared_calls.clear()
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=?", (conn_id,))
    if not row:
        raise HTTPException(404, "Not found")
    return ConnectionOut(**dict(row)).model_dump()


@router.post("/{conn_id}/test")
async def test_connection(conn_id: int):
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=?", (conn_id,))
    if not row:
        raise HTTPException(404, "Not found")
    if not row["enabled"]:
        raise HTTPException(409, "Connection not enabled")
    try:
        cfg = MCPConnectionConfig(url=row["url"], allow_localhost=bool(row["allow_localhost"]), bearer_env=row["bearer_env"])
        async with open_session(cfg) as session:
            await session.initialize()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.post("/{conn_id}/discover")
async def discover_tools(conn_id: int):
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=? AND enabled=1", (conn_id,))
    if not row:
        raise HTTPException(409, "Connection not enabled")
    try:
        cfg = MCPConnectionConfig(url=row["url"], allow_localhost=bool(row["allow_localhost"]), bearer_env=row["bearer_env"])
        async with open_session(cfg) as session:
            await session.initialize()
            result = await session.list_tools()
        tools = _get(result, "tools", getattr(result, "tools", []))
        next_cursor = _get(result, "nextCursor", getattr(result, "nextCursor", None))
        if next_cursor:
            raise HTTPException(502, "Pagination not supported")
        if len(tools) > MAX_TOOLS:
            raise HTTPException(502, "Too many tools")
        for t in tools:
            schema = _get(t, "inputSchema", getattr(t, "inputSchema", {}))
            validate_schema(schema)
        return {"tools": [_get_tool_dict(t) for t in tools]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Discovery failed: {str(e)[:200]}")


@router.post("/{conn_id}/prepare")
async def prepare_call(conn_id: int, req: Request):
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=? AND enabled=1", (conn_id,))
    if not row:
        raise HTTPException(409, "Connection not enabled")
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(422, "Invalid JSON")
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})
    if not tool_name:
        raise HTTPException(422, "Tool name required")
    try:
        cfg = MCPConnectionConfig(url=row["url"], allow_localhost=bool(row["allow_localhost"]), bearer_env=row["bearer_env"])
        async with open_session(cfg) as session:
            result = await session.list_tools()
        tools = _get(result, "tools", getattr(result, "tools", []))
        tool = next((t for t in tools if _get_name(_get_tool_dict(t)) == tool_name), None)
        if not tool:
            raise HTTPException(404, "Tool not found")
        tool_dict = _get_tool_dict(tool)
        schema = _get(tool_dict, "inputSchema", getattr(tool_dict, "inputSchema", {}))
        validate_arguments(schema, arguments)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Invalid arguments: {str(e)[:200]}")
    import secrets
    confirmation_id = secrets.token_urlsafe(32)
    _prepared_calls[confirmation_id] = PreparedCall(
        tool=tool_name, arguments=arguments, confirmation_id=confirmation_id, connection_id=conn_id
    )
    return {"confirmation_id": confirmation_id, "tool": tool_name, "arguments": arguments}


@router.post("/{conn_id}/call")
async def execute_call(conn_id: int, req: CallRequest):
    prepared = _prepared_calls.pop(req.confirmation_id, None)
    if not prepared or prepared.connection_id != conn_id:
        raise HTTPException(409, "Invalid or used confirmation")
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=? AND enabled=1", (conn_id,))
    if not row:
        raise HTTPException(409, "Connection not enabled")
    # Validate that the request arguments match the prepared arguments
    if req.arguments != prepared.arguments:
        raise HTTPException(409, "Arguments do not match prepared call")
    row = db.qone(f"SELECT * FROM {MCP_TABLE} WHERE id=? AND enabled=1", (conn_id,))
    if not row:
        raise HTTPException(409, "Connection not enabled")
    try:
        cfg = MCPConnectionConfig(url=row["url"], allow_localhost=bool(row["allow_localhost"]), bearer_env=row["bearer_env"])
        async with open_session(cfg) as session:
            if hasattr(session, "call_tool"):
                result = await session.call_tool(prepared.tool, prepared.arguments)
            else:
                from types import SimpleNamespace
                request = SimpleNamespace(root=SimpleNamespace(params=SimpleNamespace(name=prepared.tool, arguments=prepared.arguments)))
                result = await session.send_request(request, None)
        # Ensure result is serializable
        if hasattr(result, "model_dump"):
            md = getattr(result, "model_dump")
            if callable(md):
                try:
                    if hasattr(md, "__self__") and hasattr(md, "__func__"):
                        result = md.__func__()
                    else:
                        result = md()
                except Exception:
                    try:
                        result = md(**{})
                    except Exception:
                        result = {"result": str(result)}
            else:
                result = {"result": str(result)}
        elif not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except Exception as e:
        raise HTTPException(502, f"Call failed: {str(e)[:200]}")


@router.delete("/{conn_id}")
async def delete_connection(conn_id: int):
    db.run(f"DELETE FROM {MCP_TABLE} WHERE id=?", (conn_id,))
    return {"ok": True}