"""Slash command parser and executor tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-slash-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, prefs, slash  # noqa: E402
from app.main import app  # noqa: E402


def sse_events(body: str) -> dict:
    """Minimal SSE reader — a slash reply is exactly one `slash` frame."""
    evs = {}
    for part in body.split("\n\n"):
        name, data = None, ""
        for ln in part.split("\n"):
            if ln.startswith("event:"):
                name = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if name and data:
            evs.setdefault(name, []).append(data)
    return evs


class SlashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    # ------------------------------------------------ catalog + parsing --
    def test_catalog_covers_the_spec(self):
        names = {c["name"] for c in slash.CATALOG}
        required = {"/home", "/career", "/clients", "/personal", "/memory", "/voice",
                    "/automations", "/settings", "/remember", "/forget", "/search",
                    "/memories", "/task", "/tasks", "/done", "/mission", "/missions",
                    "/run", "/status", "/backup", "/models", "/health", "/logs",
                    "/think", "/ask", "/switch"}
        self.assertEqual(required - names, set(), f"missing: {sorted(required - names)}")
        self.assertEqual(len(slash.CATALOG), len(names), "duplicate command names")
        for c in slash.CATALOG:
            self.assertTrue(c["summary"], c)
            self.assertTrue(c["example"], c)
            self.assertIn(c["category"],
                          {"Navigation", "Memory", "Tasks", "Automation", "System", "AI"}, c)
            self.assertTrue(callable(c["handler"]), c)

    def test_parse_splits_on_first_space_only(self):
        cmd, args = slash.parse("/task Review the PR draft")
        self.assertEqual(cmd["name"], "/task")
        self.assertEqual(args, "Review the PR draft")

    def test_parse_strips_matching_quotes(self):
        _, args = slash.parse('/task "Review the PR"')
        self.assertEqual(args, "Review the PR")
        _, args = slash.parse("/task 'Review the PR'")
        self.assertEqual(args, "Review the PR")
        # Unbalanced quotes are prose, not a reason to mangle the text.
        self.assertEqual(slash.parse('/task "Review the PR')[1], '"Review the PR')
        self.assertEqual(slash.parse("/task 'mixed\"")[1], "'mixed\"")

    def test_parse_only_matches_at_position_zero(self):
        self.assertIsNone(slash.parse("hello world")[0])
        self.assertIsNone(slash.parse("mid /task sentence")[0])
        self.assertIsNone(slash.parse("/nope")[0])
        self.assertIsNone(slash.parse("")[0])
        self.assertIsNone(slash.parse(None)[0])

    # ------------------------------------------------------------ handlers --
    def test_navigation_returns_view(self):
        r = slash.execute("/career")
        self.assertTrue(r["handled"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["view"], "career")
        # Navigation is a view switch, not a write.
        self.assertEqual(slash.execute("/home")["view"], "home")

    def test_missing_arg_is_a_usage_error_not_a_noop(self):
        for cmd in ("/remember", "/forget", "/search", "/task", "/done",
                    "/mission", "/run", "/think", "/switch"):
            r = slash.execute(cmd)
            self.assertTrue(r["handled"], cmd)
            self.assertFalse(r["ok"], f"{cmd} was a silent no-op")
            self.assertIn("Usage", r["text"], cmd)

    def test_remember_then_search_roundtrip(self):
        r = slash.execute("/remember standup is at nine every morning")
        self.assertTrue(r["ok"], r)
        s = slash.execute("/search standup")
        self.assertTrue(s["ok"], s)
        self.assertTrue(any("standup" in str(x.get("content", "")) for x in s["result"]["results"]),
                        s["result"])

    def test_forget_only_touches_the_topic(self):
        # FTS is OR-joined, so the topic must be a nonce no other suite's
        # fixtures can contain — otherwise "forgotten" counts a neighbour.
        r = slash.execute("/remember zxqvwmn kaleidoscopic standup note")
        self.assertTrue(r["ok"], r)
        mid = r["result"]["memory"]["id"]
        live = db.q("SELECT COUNT(*) c FROM memories WHERE deleted_at IS NULL")[0]["c"]

        # The load-bearing half: an unrelated topic must delete nothing.
        miss = slash.execute("/forget qqqzz wubblefrotz")
        self.assertTrue(miss["ok"], miss)
        self.assertEqual(miss["result"]["forgotten"], 0)
        self.assertEqual(db.q("SELECT COUNT(*) c FROM memories WHERE deleted_at IS NULL")[0]["c"],
                         live, "/forget deleted memories that never mentioned the topic")

        hit = slash.execute("/forget zxqvwmn kaleidoscopic")
        self.assertTrue(hit["ok"], hit)
        self.assertGreaterEqual(hit["result"]["forgotten"], 1)
        row = db.qone("SELECT deleted_at FROM memories WHERE id=?", (mid,))
        self.assertIsNotNone(row, "the row was hard-deleted; user content must be soft-deleted")
        self.assertIsNotNone(row["deleted_at"])
        gone = slash.execute("/search zxqvwmn")["result"]["results"]
        self.assertNotIn(mid, [g.get("id") for g in gone], gone)

    def test_task_create_then_list_then_done_by_id(self):
        r = slash.execute("/task T-Slash ship the plan")
        self.assertTrue(r["ok"], r)
        tid = r["result"]["task"]["id"]
        listing = slash.execute("/tasks")
        self.assertTrue(any("T-Slash" in str(t.get("title", "")) for t in listing["result"]["tasks"]),
                        listing["result"])
        d = slash.execute(f"/done {tid}")
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["result"]["task"]["status"], "completed")

    def test_done_by_title_substring(self):
        r = slash.execute("/task T-Slash unique marker zebra")
        tid = r["result"]["task"]["id"]
        d = slash.execute("/done zebra")
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["result"]["task"]["id"], tid)

    def test_done_refuses_an_ambiguous_title(self):
        a = slash.execute("/task T-Slash doublet alpha marker")["result"]["task"]["id"]
        b = slash.execute("/task T-Slash doublet beta marker")["result"]["task"]["id"]
        self.assertNotEqual(a, b)
        r = slash.execute("/done doublet")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"], "a loose match completed one of two candidates")
        self.assertIn("use the id", r["text"])
        for tid in (a, b):
            still = db.qone("SELECT status FROM tasks WHERE id=?", (tid,))
            self.assertNotEqual(still["status"], "completed", tid)

    def test_done_unknown_task_is_an_error_not_a_crash(self):
        r = slash.execute("/done nothing matches this string")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("no open task matching", r["text"])

    def test_unknown_command_is_not_handled(self):
        self.assertFalse(slash.execute("/definitelynotacommand")["handled"])
        self.assertFalse(slash.execute("plain text")["handled"])

    def test_offline_commands_work_without_a_model(self):
        for cmd in ("/status", "/health", "/models", "/logs", "/memories"):
            r = slash.execute(cmd)
            self.assertTrue(r["handled"], cmd)
            self.assertTrue(r["ok"], f"{cmd}: {r['text']}")
            self.assertNotEqual(r["text"], "", cmd)

    def test_switch_validates_against_the_installed_catalog(self):
        before = prefs.get("ollama_chat_model")
        r = slash.execute("/switch definitely-not-installed")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"], "an unvalidated model was accepted")
        self.assertEqual(prefs.get("ollama_chat_model"), before,
                         "the pref was written despite the model not being installed")

    def test_run_refuses_a_paused_automation(self):
        from app import hermes as hermes_mod
        aid = self.c.post("/api/automations", json={
            "name": "T-Slash paused automation",
            "trigger_kind": "manual", "trigger_config": {},
            "action_kind": "chat", "action_config": {"text": "should never fire"},
        }).json()["id"]
        self.c.patch(f"/api/automations/{aid}", json={"status": "paused"})
        r = slash.execute("/run T-Slash paused automation")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"], "a paused automation was fired")
        self.assertIn("no active automation matching", r["text"])
        self.assertEqual(
            db.qone("SELECT last_run FROM automations WHERE id=?", (aid,))["last_run"], None)
        del hermes_mod

    def test_ask_requires_model_and_prompt(self):
        r = slash.execute("/ask onlymodel")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("Usage", r["text"])

    def test_execute_never_raises(self):
        for text in ("/task " + "x" * 5000, "/switch", "/run", "/done", "/forget",
                     "/" + "z" * 300, "/health\x00null", "/ask", "/mission", "/search"):
            r = slash.execute(text)
            self.assertIsInstance(r, dict, text)
            self.assertIn("handled", r)
            self.assertIn("ok", r)

    # ------------------------------------------------------------- custom --
    def test_custom_command_lifecycle(self):
        r = self.c.post("/api/slash/custom", json={"name": "/brief", "prompt": "summarise my day"})
        self.assertEqual(r.status_code, 200, r.text)
        g = self.c.get("/api/slash")
        self.assertTrue(any(c["name"] == "/brief" for c in g.json()["commands"]), g.text)
        ex = slash.execute("/brief")
        self.assertTrue(ex["handled"], ex)
        self.assertEqual(ex["text"], "summarise my day")
        self.assertEqual(self.c.delete("/api/slash/custom/brief").status_code, 200)
        self.assertFalse(slash.execute("/brief")["handled"])

    def test_custom_rejects_bad_names(self):
        for bad in ({"name": "/task", "prompt": "x"},
                    {"name": "no-slash", "prompt": "x"},
                    {"name": "/has space", "prompt": "x"},
                    {"name": "/empty", "prompt": ""},
                    {"name": "/tab\there", "prompt": "x"}):
            self.assertEqual(self.c.post("/api/slash/custom", json=bad).status_code, 400, bad)
        self.assertEqual(self.c.post("/api/slash/custom", json={}).status_code, 400)

    def test_custom_survives_a_corrupt_pref(self):
        prefs.set_many({slash.CUSTOM_KEY: "{not json"})
        try:
            self.assertEqual(slash.custom(), [])
            self.assertFalse(slash.execute("/anything")["handled"])
            self.assertEqual(len(slash.all_commands()), len(slash.CATALOG))
        finally:
            prefs.set_many({slash.CUSTOM_KEY: "[]"})

    # -------------------------------------------------------------- HTTP --
    def test_execute_route(self):
        self.assertEqual(self.c.get("/api/slash").status_code, 200)
        r = self.c.post("/api/slash/execute", json={"text": "/health"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["handled"])
        r = self.c.post("/api/slash/execute", json={"text": "not a command"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["handled"])
        r = self.c.post("/api/slash/execute", json={})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["handled"])

    def test_chat_stream_short_circuits_a_leading_slash(self):
        import json as _json
        before = {s["id"] for s in db.q("SELECT id FROM sessions")}
        r = self.c.post("/api/chat/stream", json={"message": "/task T-Slash via stream"})
        self.assertEqual(r.status_code, 200, r.text)
        evs = sse_events(r.text)
        # `done` must close the stream: clients clear their in-flight flag on it,
        # and a slash reply without one leaves the composer stuck on "sending".
        self.assertEqual(list(evs), ["slash", "done"], f"got frames {list(evs)}")
        out = _json.loads(evs["slash"][0])
        self.assertTrue(out["handled"], out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["command"], "/task")
        tid = out["result"]["task"]["id"]
        self.assertEqual(db.qone("SELECT title FROM tasks WHERE id=?", (tid,))["title"],
                         "T-Slash via stream")
        # No model call and no turn: a command must not open a session.
        self.assertEqual({s["id"] for s in db.q("SELECT id FROM sessions")}, before)

    def test_chat_stream_short_circuit_reports_a_usage_error_as_data(self):
        import json as _json
        r = self.c.post("/api/chat/stream", json={"message": "/remember"})
        self.assertEqual(r.status_code, 200, r.text)
        out = _json.loads(sse_events(r.text)["slash"][0])
        self.assertTrue(out["handled"])
        self.assertFalse(out["ok"])
        self.assertIn("Usage", out["text"])

    def test_chat_stream_leaves_mid_sentence_slashes_to_the_orchestrator(self):
        r = self.c.post("/api/chat/stream", json={"message": "remind me to /task the PR later"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("slash", sse_events(r.text))
        self.assertEqual(
            db.q("SELECT id FROM tasks WHERE title LIKE '%remind me to%'"), [])

    def test_chat_stream_keeps_attachments_with_a_leading_slash(self):
        # A `/`-prefixed message carrying an attachment is a real turn: the
        # shortcut would drop the file.
        r = self.c.post("/api/chat/stream", json={
            "message": "/task please read this", "attachments": [{"id": 1, "name": "a.pdf"}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("slash", sse_events(r.text))


if __name__ == "__main__":
    unittest.main()