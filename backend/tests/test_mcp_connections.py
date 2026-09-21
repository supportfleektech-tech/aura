import asyncio
import importlib
import json
import os
import socket
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import config, db, mcp_connections as mc


TOOL = {"name": "greet", "description": "<b>Untrusted greeting</b>", "inputSchema": {
    "type": "object", "properties": {"name": {"type": "string", "maxLength": 40}},
    "required": ["name"], "additionalProperties": False}}


class MCPBoundaryTest(unittest.TestCase):
    def test_calls_require_explicit_confirmation(self):
        for confirmed in (False, 1, "true"):
            with self.subTest(confirmed=confirmed), self.assertRaises(ValidationError):
                mc.CallRequest(tool="greet", arguments={}, confirmed=confirmed, confirmation_id="x" * 32)

    def test_router_exists(self):
        self.assertTrue(hasattr(mc, "router"), "MCP router is required")


class MCPManagementTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(mc, "init_mcp"), "MCP persistence initialization is required")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db.reset()
        target = patch.object(config, "DB_PATH", str(Path(self.tmp.name) / "mcp.db"))
        target.start()
        self.addCleanup(target.stop)
        self.addCleanup(db.reset)
        db.init_db()
        mc.init_mcp()
        app = FastAPI()
        app.include_router(mc.router, prefix="/api")
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.events = []
        self.pages = [SimpleNamespace(tools=[SimpleNamespace(model_dump=lambda **kw: TOOL)], nextCursor=None)]
        owner = self

        class Session:
            async def initialize(self):
                owner.events.append("initialize")

            async def list_tools(self, **kwargs):
                owner.events.append("list")
                return owner.pages[min(owner.events.count("list") - 1, len(owner.pages) - 1)]

            async def send_request(self, request, result_type):
                owner.events.append(("call", request.root.params.name, request.root.params.arguments))
                return SimpleNamespace(model_dump=lambda **kw: {"content": [{"type": "text", "text": "Hello Ada"}], "isError": False})

        @asynccontextmanager
        async def session(connection):
            owner.events.append("open")
            try:
                yield Session()
            finally:
                owner.events.append("close")

        target = patch.object(mc, "open_session", session)
        target.start()
        self.addCleanup(target.stop)

    def add(self, **extra):
        return self.client.post("/api/mcp/connections", json={"name": "greetings", "url": "http://127.0.0.1:8765/mcp", "allow_localhost": True, **extra})

    def enable(self):
        server = self.add().json()
        self.assertEqual(self.client.patch(f"/api/mcp/connections/{server['id']}", json={"enabled": True}).status_code, 200)
        return f"/api/mcp/connections/{server['id']}"

    def prepare(self, path, arguments=None):
        self.assertEqual(self.client.post(path + "/discover").status_code, 200)
        result = self.client.post(path + "/prepare", json={"tool": "greet", "arguments": arguments or {"name": "Ada"}})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_add_disabled_persist_enable_test_discover_delete(self):
        response = self.add()
        self.assertEqual(response.status_code, 201, response.text)
        server = response.json()
        self.assertFalse(server["enabled"])
        path = f"/api/mcp/connections/{server['id']}"
        for action in ("test", "discover"):
            self.assertEqual(self.client.post(path + "/" + action).status_code, 409)
        self.assertEqual(self.events, [])
        db.reset()
        self.assertEqual(len(self.client.get("/api/mcp/connections").json()["connections"]), 1)
        self.client.patch(path, json={"enabled": True})
        self.assertTrue(self.client.post(path + "/test").json()["ok"])
        result = self.client.post(path + "/discover").json()
        self.assertEqual(result["tools"][0]["name"], "greet")
        self.assertEqual(self.events, ["open", "initialize", "close", "open", "initialize", "list", "close"])
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.client.post(path + "/test").status_code, 404)

    def test_exact_confirmation_single_use_and_arguments_validation(self):
        path = self.enable()
        ready = self.prepare(path)
        payload = {"tool": "greet", "arguments": {"name": "Ada"}, "confirmed": True, "confirmation_id": ready["confirmation_id"]}
        self.assertEqual(self.client.post(path + "/call", json={**payload, "confirmed": False}).status_code, 422)
        self.assertEqual(self.client.post(path + "/call", json={**payload, "arguments": {"name": "Eve"}}).status_code, 409)
        ready = self.prepare(path)
        payload["confirmation_id"] = ready["confirmation_id"]
        result = self.client.post(path + "/call", json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("Hello Ada", json.dumps(result.json()))
        self.assertEqual(self.client.post(path + "/call", json=payload).status_code, 409)
        self.assertEqual(sum(isinstance(e, tuple) for e in self.events), 1)
        self.assertEqual(self.events.count("open"), self.events.count("close"))
        for arguments in ({}, {"name": 42}, {"name": "Ada", "extra": True}):
            self.assertEqual(self.client.post(path + "/prepare", json={"tool": "greet", "arguments": arguments}).status_code, 422)

    def test_disable_invalidates_pending_confirmation(self):
        path = self.enable()
        ready = self.prepare(path)
        self.client.patch(path, json={"enabled": False})
        self.client.patch(path, json={"enabled": True})
        self.assertEqual(self.client.post(path + "/call", json={"tool": "greet", "arguments": {"name": "Ada"}, "confirmed": True, "confirmation_id": ready["confirmation_id"]}).status_code, 409)
        self.assertFalse(any(isinstance(e, tuple) for e in self.events))

    def test_untrusted_annotations_do_not_authorize_and_tools_are_bounded(self):
        path = self.enable()
        self.pages = [SimpleNamespace(tools=[SimpleNamespace(model_dump=lambda **kw: {**TOOL, "annotations": {"readOnlyHint": True}})] * (mc.MAX_TOOLS + 1), nextCursor=None)]
        response = self.client.post(path + "/discover")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(any(isinstance(e, tuple) for e in self.events))

    def test_pagination_is_bounded(self):
        path = self.enable()
        self.pages = [SimpleNamespace(tools=[], nextCursor="again")]
        self.assertEqual(self.client.post(path + "/discover").status_code, 502)
        self.assertLessEqual(self.events.count("list"), mc.MAX_PAGES)

    def test_no_inline_credentials_and_no_disabled_network(self):
        for extra in ({"token": "not-a-real-token"}, {"bearer_env": "PATH"}, {"enabled": True}):
            self.assertEqual(self.add(**extra).status_code, 422)
        self.assertEqual(self.add(bearer_env="AURA_MCP_GREETING_TOKEN").status_code, 201)
        self.assertNotIn("Authorization", self.client.get("/api/mcp/connections").text)
        self.assertEqual(self.events, [])

    def test_duplicate_names_and_connection_cap(self):
        self.assertEqual(self.add().status_code, 201)
        self.assertEqual(self.add().status_code, 409)
        with patch.object(mc, "MAX_CONNECTIONS", 1):
            self.assertEqual(self.add(name="other").status_code, 409)

    def test_unsafe_urls_rejected_without_network(self):
        for url in ("http://192.168.1.2/mcp", "https://10.0.0.1/mcp", "http://example.com/mcp", "https://user:secret@example.com/mcp", "https://example.com/mcp?token=x", "https://example.com/#x", "http://127.0.0.1:8000/api/settings", "https://[::ffff:127.0.0.1]/mcp"):
            with self.subTest(url=url):
                self.assertEqual(self.add(url=url).status_code, 422)
        self.assertEqual(self.add(allow_localhost=False).status_code, 422)
        self.assertEqual(self.events, [])


class MCPTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_dns_rejects_mixed_public_private_results(self):
        self.assertTrue(hasattr(mc, "resolve_destination"))
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("93.184.216.34", "10.0.0.1")]
        with patch("socket.getaddrinfo", return_value=answers):
            with self.assertRaises(ValueError):
                await mc.resolve_destination("https://example.com/mcp", False)

    async def test_transport_pins_ip_preserves_tls_host_and_blocks_redirect(self):
        self.assertTrue(hasattr(mc, "BoundedTransport"))
        seen = []

        async def handle(request):
            seen.append(request)
            return httpx.Response(307, headers={"location": "http://10.0.0.1/mcp"})

        transport = mc.BoundedTransport("https://example.com/mcp", "93.184.216.34", inner=httpx.MockTransport(handle))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(ValueError):
                await client.get("https://example.com/mcp")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.host, "93.184.216.34")
        self.assertEqual(seen[0].headers["host"], "example.com")
        self.assertEqual(seen[0].extensions["sni_hostname"], "example.com")

    async def test_transport_caps_bytes_and_disallows_other_endpoints(self):
        self.assertTrue(hasattr(mc, "BoundedTransport"))
        transport = mc.BoundedTransport("http://127.0.0.1:8765/mcp", "127.0.0.1", inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (mc.MAX_WIRE_BYTES + 1))))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(ValueError):
                await client.get("http://127.0.0.1:8765/mcp")
            with self.assertRaises(ValueError):
                await client.get("http://127.0.0.1:8765/admin")

    async def test_schema_subset_rejects_refs_patterns_and_complexity(self):
        self.assertTrue(hasattr(mc, "validate_arguments"))
        for schema in ({"$ref": "https://example.com/schema"}, {"type": "string", "pattern": "x"}, {"type": "object", "properties": {"x": {"$ref": "#"}}}):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                mc.validate_arguments(schema, {})
        mc.validate_arguments(TOOL["inputSchema"], {"name": "Ada"})
