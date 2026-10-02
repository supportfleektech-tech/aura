"""Slash command parser and executor tests."""
import os
import pathlib
import random
import re
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-slash-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, prefs, slash  # noqa: E402
from app import memory as memory_module  # noqa: E402
from app.main import app  # noqa: E402

memory_engine = memory_module.memory_engine


def slash_memory_store(text):
    """`/remember <text>` through the command surface itself."""
    r = slash.execute(f"/remember {text}")
    assert r["ok"], r
    return r["result"]["memory"]


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


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

    # ------------------------------------------------------- /forget -----
    # Realistic single-line memories, the shape a person actually types.
    _CORPUS = [
        "Standup is at 9am every morning in the main room",
        "The gym membership renews on the third of March",
        "Wifi password for the office is written on the fridge",
        "Pharmacy is broken",
        "I prefer oat milk in my coffee and never dairy",
        "The server rack in closet B was replaced last year",
        "Visa application expires at the end of the month",
        "Book club meets on the first Wednesday monthly",
    ]

    def _seed_corpus(self, rows):
        """Store `rows` and return their ids, refusing to dedupe them away."""
        ids = []
        for text in rows:
            r = slash_memory_store(text)
            self.assertFalse(r.get("deduped"), f"fixture deduped: {text}")
            ids.append(r["id"])
        return ids

    def test_forget_a_nonsense_topic_deletes_nothing(self):
        """Over-delete direction.

        The old gate was `match >= 0.35`, and `match` is
        `max(lex, sem)`. "Pharmacy is broken" collides with the nonsense topic
        "vimlish tarb" at hashed-embedding cosine **0.654** — short memories
        concentrate on few hash buckets, so unrelated text clears a 0.35 bar
        routinely (0.45 on a 120k-row synthetic sweep). Measured before the fix:
        `forget_topic("vimlish tarb")` deleted "Pharmacy is broken" and nothing
        else was even close.
        """
        ids = self._seed_corpus(self._CORPUS)
        candidates = memory_engine.forget_candidates("vimlish tarb")
        self.assertEqual(candidates, [], f"nonsense topic matched {candidates}")
        n = memory_engine.forget_topic("vimlish tarb")
        self.assertEqual(n, 0, f"a nonsense topic deleted {n} memories")
        live = {r["id"] for r in db.q("SELECT id FROM memories WHERE deleted_at IS NULL")}
        self.assertTrue(set(ids) <= live, "the corpus lost rows to a nonsense topic")

    def test_forget_finds_the_on_topic_row_past_the_old_limit_50_window(self):
        """Under-delete direction.

        `forget_topic` used to call `search(topic, limit=50)` and filter that
        window on `match`. `search` ranks by `score`, which is ~91%
        importance/confidence — so on a corpus with more than 50 rows mentioning
        the topic, the genuinely on-topic row can fall outside the window.
        Measured before the fix on 61 memories: `/forget meeting` deleted 38
        *incidental* mentions and kept the one actually about the meeting (its
        position in the 50-row window was `None`).
        """
        target = ("The meeting about the leaking roof above the Kilimani bedroom was "
                  "rescheduled to Thursday after the contractor finally confirmed that "
                  "the flashing around the chimney needs replacing before the rains")
        tid = slash_memory_store(target)["id"]
        rnd = random.Random(23)
        nouns = "boiler kettle hedge fence lamp shelf drawer ladder toolbox bike tyre".split()
        acts = "service clean repair replace tighten oil patch inspect".split()
        made, i = 0, 0
        while made < 60:  # 60 incidental mentions + the target = past the window
            i += 1
            text = f"Meeting {i}: {rnd.choice(acts)} the {rnd.choice(nouns)} with the {i} crew"
            if not slash_memory_store(text).get("deduped"):
                made += 1
        live = db.qone("SELECT COUNT(*) c FROM memories WHERE deleted_at IS NULL")["c"]
        self.assertGreaterEqual(live, 61, live)

        # The precondition that made the old window miss: search() could not see
        # the target at all.
        self.assertNotIn(tid, [h["id"] for h in memory_engine.search("meeting", limit=50)],
                         "fixture no longer exceeds the old window — the bug it proves is gone")
        self.assertIn(tid, [h["id"] for h in memory_engine.forget_candidates("meeting")])

        n = memory_engine.forget_topic("meeting")
        self.assertGreaterEqual(n, 61, n)
        self.assertIsNotNone(db.qone("SELECT deleted_at FROM memories WHERE id=?",
                                     (tid,))["deleted_at"],
                             "the genuinely on-topic row survived a topic delete")

    def test_forget_lists_candidates_and_deletes_nothing_until_confirmed(self):
        # Two-step: a bare `/forget` reports and changes nothing.
        rows = ["zxqvwmn kaleidoscopic standup note",
                "zxqvwmn kaleidoscopic quixotic retro",
                "Something entirely unrelated about the wifi password"]
        ids = self._seed_corpus(rows)
        live_before = {r["id"] for r in db.q("SELECT id FROM memories WHERE deleted_at IS NULL")}

        dry = slash.execute("/forget zxqvwmn kaleidoscopic")
        self.assertTrue(dry["ok"], dry)
        self.assertFalse(dry["result"]["confirmed"])
        self.assertEqual(dry["result"]["forgotten"], 0)
        titles = [c["title"] for c in dry["result"]["candidates"]]
        self.assertEqual(len(titles), 2, titles)
        self.assertTrue(any("kaleidoscopic" in t for t in titles), titles)
        # Not a bare count: the user must be able to see what is about to go.
        self.assertIn("standup note", " ".join(titles), titles)
        self.assertEqual(dry["result"]["confirm_with"], "/forget zxqvwmn kaleidoscopic confirm")
        live_after = {r["id"] for r in db.q("SELECT id FROM memories WHERE deleted_at IS NULL")}
        self.assertEqual(live_before, live_after, "a bare /forget deleted something")

        wet = slash.execute("/forget zxqvwmn kaleidoscopic confirm")
        self.assertTrue(wet["ok"], wet)
        self.assertTrue(wet["result"]["confirmed"])
        self.assertEqual(wet["result"]["forgotten"], 2, wet["result"])
        self.assertEqual(len(wet["result"]["titles"]), 2, wet["result"])
        gone = db.q("SELECT id FROM memories WHERE deleted_at IS NOT NULL")
        for mid in ids[:2]:
            row = db.qone("SELECT deleted_at FROM memories WHERE id=?", (mid,))
            self.assertIsNotNone(row, "the row was hard-deleted; user content must be soft-deleted")
            self.assertIsNotNone(row["deleted_at"])
        self.assertIsNone(db.qone("SELECT deleted_at FROM memories WHERE id=?",
                                  (ids[2],))["deleted_at"], "the unrelated row was deleted")
        self.assertTrue(gone)
        # And the survivors are no longer offered.
        self.assertEqual(memory_engine.forget_candidates("zxqvwmn kaleidoscopic"), [])

    def test_forget_multi_word_topic_needs_every_word(self):
        """A multi-word topic is an intersection, not a union.

        `_fts_query` OR-joins tokens, and `forget_candidates` inherited that:
        `/forget old address` matched every row containing *either* word. On the
        corpus below — the re-reviewer's, including the row that matches on
        `old` alone — it deleted 5 of 6, taking out "Cheap wine — an old
        vintage from 2011" and "The old boiler needs replacing before winter"
        along with the two address rows. That is the command's own registered
        example (`/forget old address confirm`), so a user typing the
        documented form destroyed unrelated memories.

        The general search path keeps its OR-join: recall wants "any of these
        words". A destructive topic-delete wants "this subject".
        """
        rows = {
            "old_kilimani": "The old address was 14 Kilimani Road, moved in 2019",
            "old_flat": "My old address is the Kilimani flat with the blue gate",
            "new_drive": "New address is Riverside Drive, apartment 4B",
            "vintage": "Cheap wine — an old vintage from 2011",
            "boiler": "The old boiler needs replacing before winter",
        }
        ids = {k: slash_memory_store(v)["id"] for k, v in rows.items()}

        def live(key):
            return db.qone("SELECT deleted_at FROM memories WHERE id=?",
                           (ids[key],))["deleted_at"] is None

        for key in ids:  # fixture sanity: everything starts live
            self.assertTrue(live(key), key)

        wet = slash.execute("/forget old address confirm")
        self.assertTrue(wet["ok"], wet)
        titles = wet["result"]["titles"]
        # The two rows actually about the old address went.
        self.assertFalse(live("old_kilimani"), titles)
        self.assertFalse(live("old_flat"), titles)
        self.assertIn("old address", " ".join(titles).lower(), titles)
        # The three rows that matched on one word did not.
        self.assertTrue(live("vintage"), f"an 'old' mention was deleted: {titles}")
        self.assertTrue(live("boiler"), f"an 'old' mention was deleted: {titles}")
        self.assertTrue(live("new_drive"), f"an 'address' mention was deleted: {titles}")

    def test_forget_single_word_topic_still_matches_every_row_with_it(self):
        """The intersection must not narrow a one-word topic to nothing."""
        a = slash_memory_store("Lease renewal is due on the first of April")["id"]
        b = slash_memory_store("The lease for the Kilimani flat runs to March")["id"]
        wet = slash.execute("/forget lease confirm")
        self.assertTrue(wet["ok"], wet)
        self.assertGreaterEqual(wet["result"]["forgotten"], 2, wet["result"])
        for mid in (a, b):
            self.assertIsNotNone(
                db.qone("SELECT deleted_at FROM memories WHERE id=?", (mid,))["deleted_at"],
                f"a single-word topic stopped matching id={mid}")

    def test_forget_renders_a_sentence_not_a_json_dump(self):
        """The transcript line for a destructive command is not machine output.

        `text` used to be `json.dumps` of the whole result, so a confirmed
        forget read `{"forgotten": 3, "titles": [...]}` in the chat bubble. The
        structured fields stay for programmatic callers; only `text` changes.
        """
        a = slash_memory_store("The old address was 14 Kilimani Road")["id"]
        slash_memory_store("My old address is the Kilimani flat")

        dry = slash.execute("/forget old address")
        self.assertNotIn("{", dry["text"], dry["text"])
        self.assertIn("Nothing has been deleted yet", dry["text"])
        self.assertIn("Kilimani Road", dry["text"])
        self.assertIn("/forget old address confirm", dry["text"])

        wet = slash.execute("/forget old address confirm")
        self.assertNotIn("{", wet["text"], wet["text"])
        self.assertTrue(wet["text"].startswith("Deleted 2 memories"), wet["text"])
        self.assertIn("Kilimani Road", wet["text"])
        # Structured fields are unchanged, for callers that want them.
        self.assertEqual(wet["result"]["forgotten"], 2)
        self.assertEqual(len(wet["result"]["titles"]), 2)
        self.assertTrue(wet["result"]["confirmed"])
        self.assertIsNotNone(db.qone("SELECT deleted_at FROM memories WHERE id=?",
                                     (a,))["deleted_at"])

        miss = slash.execute("/forget zxqvwmn kaleidoscopic")
        self.assertIn("No memories about", miss["text"], miss["text"])
        self.assertEqual(miss["result"]["forgotten"], 0)

    def test_result_text_is_a_sentence_when_a_handler_supplies_one(self):
        """The general rule, so `/ask` and `/think` stop rendering `{"text": …}`."""
        self.assertEqual(slash.execute("/memories")["text"], slash._as_text(
            slash.execute("/memories")["result"]))
        r = slash.execute("/think why is CI red")
        self.assertFalse(r["text"].startswith("{") and '"text"' in r["text"],
                         f"a model answer was dumped as JSON: {r['text'][:120]}")

    def test_forget_confirm_is_the_only_way_to_delete(self):
        # A topic whose text is literally "confirm" is still forgetable, because
        # the flag is only a *trailing* token with something left over.
        mid = slash_memory_store("confirm the plumber appointment")["id"]
        dry = slash.execute("/forget confirm")
        self.assertFalse(dry["result"]["confirmed"], dry["result"])
        self.assertEqual(dry["result"]["forgotten"], 0)
        self.assertIsNone(db.qone("SELECT deleted_at FROM memories WHERE id=?", (mid,))["deleted_at"])
        wet = slash.execute("/forget confirm the plumber appointment confirm")
        self.assertEqual(wet["result"]["forgotten"], 1, wet["result"])
        self.assertIsNotNone(db.qone("SELECT deleted_at FROM memories WHERE id=?", (mid,))["deleted_at"])

    def test_topic_match_is_membership_not_a_threshold(self):
        """A one-point drift must not be able to change the outcome.

        `search` derives its lexical score as `-bm25/8 + 0.35`. SQLite's bm25
        returns -1e-06 for a term present in most of a corpus, so a genuine weak
        FTS hit measures *exactly* 0.350 — the old `lex >= 0.35` predicate sat on
        its own constant's floor with zero margin. Admission is now "the row came
        back from MATCH", which has no magnitude to drift.
        """
        for corpus_term in ("roof", "zqjxwl"):
            self.assertTrue(memory_module._is_topic_match(True),
                            "an FTS hit must be admitted regardless of any score")
        self.assertFalse(memory_module._is_topic_match(False))
        # Prove the floor is real, not folklore: a weak hit sits exactly on it.
        self.assertAlmostEqual(-(-0.000001) / 8.0 + 0.35, 0.35, places=6)

    def test_parse_splits_on_any_whitespace_not_just_a_space(self):
        cmd, args = slash.parse("/task\tBuy milk")
        self.assertEqual(cmd["name"], "/task")
        self.assertEqual(args, "Buy milk")
        cmd, args = slash.parse("/task\nBuy milk")
        self.assertEqual(cmd["name"], "/task")
        self.assertEqual(args, "Buy milk")
        cmd, args = slash.parse("/done   42")
        self.assertEqual(cmd["name"], "/done")
        self.assertEqual(args, "42")
        # Multiple spaces inside the argument must survive as one space-padded
        # string, not be silently truncated at the first run.
        _, args = slash.parse("/remember standup  is  at  nine")
        self.assertEqual(args, "standup  is  at  nine")

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

    def test_run_records_last_run_counters_and_an_audit_row(self):
        """AGENTS.md: "three automation fire paths exist and all must record."

        `/run` is a *fourth* path. Only the refusal case was covered, which left
        the invariant unenforced exactly where a regression would be invisible:
        `_fire_one` skips counters and the audit trail, so a handler that
        reached the wrong function would still have failed the paused test for an
        unrelated reason. This asserts the recorded effects, not the return value.
        """
        before_audit = db.qone("SELECT COUNT(*) c FROM activity")["c"]
        # `proactive` is the action kind that actually succeeds with no provider
        # and no network, so the *success* counter is exercised rather than the
        # failure branch. (`backup` is dispatched by `_fire_one` but is absent
        # from `validate_action`'s allow-list, so the API refuses to create it —
        # pre-existing and out of scope here.)
        aid = self.c.post("/api/automations", json={
            "name": "T-Slash active automation",
            "trigger_kind": "manual", "trigger_config": {},
            "action_kind": "proactive", "action_config": {},
        }).json()["id"]
        row0 = db.qone("SELECT last_run, success_count, fail_count FROM automations WHERE id=?",
                       (aid,))
        self.assertIsNone(row0["last_run"], aid)
        self.assertEqual(row0["success_count"], 0, aid)

        r = slash.execute("/run T-Slash active automation")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["result"]["ran"]["ok"], r["result"])

        row1 = db.qone("SELECT last_run, success_count, fail_count FROM automations WHERE id=?",
                       (aid,))
        self.assertIsNotNone(row1["last_run"],
                             "/run did not stamp last_run — counters and audit were skipped")
        self.assertEqual(row1["success_count"], row0["success_count"] + 1,
                         "/run did not increment the success counter")
        self.assertEqual(row1["fail_count"], row0["fail_count"])
        self.assertGreater(db.qone("SELECT COUNT(*) c FROM activity")["c"], before_audit,
                           "/run wrote no activity row at all")

    def test_run_resolves_by_exact_name_case_insensitively(self):
        aid = self.c.post("/api/automations", json={
            "name": "T-Slash Casefolded Run",
            "trigger_kind": "manual", "trigger_config": {},
            "action_kind": "proactive", "action_config": {},
        }).json()["id"]
        # `_pick`'s exact-name branch, which was dead: no test reached it, because
        # every other case went through the id or the unique-substring branch.
        r = slash.execute("/run t-slash casefolded run")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["ran"]["id"], aid, r["result"])
        by_id = slash.execute(f"/run {aid}")
        self.assertTrue(by_id["ok"], by_id)
        self.assertEqual(by_id["result"]["ran"]["id"], aid)

    def test_pick_exact_name_branch(self):
        rows = [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Alpha Beta"}]
        # Exact wins over the substring that would otherwise also match.
        self.assertEqual(slash._pick(rows, "Alpha", "name", "thing")["id"], 1)
        self.assertEqual(slash._pick(rows, "alpha", "name", "thing")["id"], 1)
        self.assertEqual(slash._pick(rows, "1", "name", "thing")["id"], 1)
        self.assertEqual(slash._pick(rows, "Beta", "name", "thing")["id"], 2)
        with self.assertRaises(ValueError):
            slash._pick(rows, "nothing here", "name", "thing")

    def test_switch_writes_the_preference_on_success(self):
        """The success half of the pair. Only the refusal was covered, so a
        handler that refused everything — or one that never reached the write —
        passed the whole suite. `set_default` is stubbed because the real one
        needs an Ollama catalog, which does not exist in CI; what is under test
        here is the *handler*: that it passes the "chat" role, reads
        `model`/`role` out of the result, and reports them."""
        before = prefs.get("ollama_chat_model")
        from app import ollama_sync
        real = ollama_sync.set_default
        seen = {}

        def fake(role, name):
            seen["role"], seen["name"] = role, name
            return {"model": name, "role": role}

        ollama_sync.set_default = fake
        try:
            r = slash.execute("/switch  qwen2.5:1.5b ")
            self.assertTrue(r["ok"], r)
            self.assertEqual(seen, {"role": "chat", "name": "qwen2.5:1.5b"}, seen)
            self.assertEqual(r["result"]["ollama_chat_model"], "qwen2.5:1.5b")
            self.assertEqual(r["result"]["role"], "chat")
        finally:
            ollama_sync.set_default = real
            prefs.set_many({"ollama_chat_model": before})

    def test_switch_refusal_leaves_the_preference_alone(self):
        """And the two halves disagree in the right direction: the stub above
        would have accepted anything, so this proves the refusal is the real
        validator's doing and not the stub's."""
        before = prefs.get("ollama_chat_model")
        r = slash.execute("/switch definitely-not-installed-xyz")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"], "an unvalidated model was accepted")
        self.assertEqual(prefs.get("ollama_chat_model"), before)

    def test_backup_is_additive_and_records_an_archive(self):
        from app import config as aura_config
        d = pathlib.Path(aura_config.BACKUP_DIR)
        before = {p.name for p in d.glob("aura-backup-*")} if d.is_dir() else set()
        r = slash.execute("/backup")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["result"]["backup"]["ok"], r["result"])
        after = {p.name for p in d.glob("aura-backup-*")}
        self.assertTrue(after - before, "no new archive was written")
        # It added; it removed nothing. That is the whole safety claim for
        # `/backup` being reachable from a chat box.
        self.assertTrue(before <= after, f"/backup deleted existing archives: {before - after}")

    def test_think_reports_the_local_model_being_offline(self):
        # Ollama is pointed at 127.0.0.1:1 by the harness, so the offline branch
        # is the only reachable one here — and it must be a clear answer, not a
        # raw connection error.
        r = slash.execute("/think why is CI red")
        self.assertTrue(r["handled"])
        if r["ok"]:
            self.assertTrue(r["result"]["text"])
        else:
            self.assertIn("offline", r["text"].lower(), r["text"])

    def test_ask_happy_path_uses_the_named_model(self):
        calls = {}

        class _Ollama:
            def chat(self, messages, model=None, purpose=None):
                calls["messages"] = messages
                calls["model"] = model
                calls["purpose"] = purpose
                return "the fake answer"

        from app.inference import router as r_
        real = r_.ollama
        real_active = r_._local_active
        r_.ollama = _Ollama()
        r_._local_active = True  # already activated; /ask must not re-probe
        try:
            r = slash.execute("/ask qwen2.5:1.5b summarise my day")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["model"], "qwen2.5:1.5b")
            self.assertEqual(r["result"]["text"], "the fake answer")
            self.assertEqual(calls["model"], "qwen2.5:1.5b")
            self.assertEqual(calls["messages"], [{"role": "user", "content": "summarise my day"}])
        finally:
            r_.ollama = real
            r_._local_active = real_active

    def test_mission_creates_and_is_listed(self):
        r = slash.execute("/mission T-Slash plan the release week")
        self.assertTrue(r["ok"], r)
        mid = r["result"]["mission"]["id"]
        listing = slash.execute("/missions")
        self.assertTrue(listing["ok"], listing)
        self.assertTrue(any(m["id"] == mid for m in listing["result"]["missions"]),
                        listing["result"])
        db.run("DELETE FROM mission_runs WHERE mission_id=?", (mid,))
        db.run("DELETE FROM missions WHERE id=?", (mid,))

    def test_ask_requires_model_and_prompt(self):
        r = slash.execute("/ask onlymodel")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("Usage", r["text"])

    def test_execute_never_raises(self):
        """Fuzz, asserting the actual result shape.

        The previous version asserted only `isinstance(r, dict)` plus two key
        names, which passes for `{"handled": "banana", "ok": []}`. The frontend
        branches on `r.ok` to pick the message role and calls `setView(r.view)`
        for a nav command, so a wrong-typed or missing field is a real defect —
        assert the types.
        """
        keys = {"handled", "ok", "command", "result", "text", "view"}
        for text in ("/task " + "x" * 5000, "/switch", "/run", "/done", "/forget",
                     "/" + "z" * 300, "/health\x00null", "/ask", "/mission", "/search",
                     "/task\tBuy milk", "/forget confirm", "/forget x confirm"):
            r = slash.execute(text)
            self.assertIsInstance(r, dict, text)
            self.assertEqual(set(r), keys, f"{text!r} -> {sorted(r)}")
            self.assertIsInstance(r["handled"], bool, (text, r["handled"]))
            self.assertIsInstance(r["ok"], bool, (text, r["ok"]))
            self.assertIsInstance(r["command"], str, (text, r["command"]))
            self.assertIsInstance(r["text"], str, (text, r["text"]))
            self.assertTrue(r["text"] or r["ok"] is False, f"{text!r} rendered nothing")
            # `result` is a dict or None; `view` is a string or None. Both are
            # read positionally by the client, so a list here would render "[...]".
            self.assertTrue(r["result"] is None or isinstance(r["result"], dict), (text, r["result"]))
            self.assertTrue(r["view"] is None or isinstance(r["view"], str), (text, r["view"]))
            if not r["handled"]:
                self.assertIs(r["result"], None, text)
                self.assertIs(r["view"], None, text)
            # The same shape over HTTP — the route passes it through untouched.
            h = self.c.post("/api/slash/execute", json={"text": text})
            self.assertEqual(h.status_code, 200, text)
            self.assertEqual(set(h.json()), keys, text)
            for k in ("handled", "ok"):
                self.assertIsInstance(h.json()[k], bool, (text, k))

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

    def test_custom_rejects_an_unknown_view(self):
        # App.tsx is a `view === x` chain with no default branch, so an
        # unvalidated target renders a blank main pane and no error anywhere.
        for bad in ("analytic", "Home", "home2", "../etc", "analytics extra"):
            r = self.c.post("/api/slash/custom",
                            json={"name": "/badtarget", "prompt": "x", "view": bad})
            self.assertEqual(r.status_code, 400, f"{bad!r} was accepted: {r.text}")
            self.assertFalse(any(c["name"] == "/badtarget" for c in slash.custom()),
                             f"{bad!r} was persisted")
        # Every real view is accepted, and empty stays allowed ("just a prompt").
        for good in sorted(slash.VIEWS):
            r = self.c.post("/api/slash/custom",
                            json={"name": f"/to{good}", "prompt": "x", "view": good})
            self.assertEqual(r.status_code, 200, f"{good!r} rejected: {r.text}")
        self.assertEqual(self.c.post("/api/slash/custom",
                                     json={"name": "/noview", "prompt": "x"}).status_code, 200)
        self.assertEqual(self.c.post("/api/slash/custom",
                                     json={"name": "/blankview", "prompt": "x",
                                           "view": "   "}).status_code, 200)
        for c in slash.custom():
            slash.delete_custom(c["name"])

    def test_slash_views_match_the_frontend_view_union(self):
        """The sync mechanism for the backend/frontend view set.

        The frontend derives `View` from the `VIEWS` array in `store.tsx`, so
        TypeScript cannot drift from itself — but a Python list absolutely can
        drift from it, and a stale entry here is an accepted target that renders
        nothing. So the union is read out of the TypeScript source and compared.
        """
        src = (REPO_ROOT / "frontend" / "src" / "store.tsx").read_text(encoding="utf-8")
        block = re.search(r"export const VIEWS = \[(.*?)\] as const;", src, re.S)
        self.assertIsNotNone(block, "frontend/src/store.tsx no longer exports `VIEWS`")
        fe = set(re.findall(r'"([^"]+)"', block.group(1)))
        self.assertEqual(fe - set(slash.VIEWS), set(),
                         "backend is missing view(s) the frontend can navigate to")
        self.assertEqual(set(slash.VIEWS) - fe, set(),
                         "backend accepts a view the frontend cannot render")
        self.assertGreater(len(fe), 0)
        # And it is genuinely used as the type source, not a stale extra export.
        self.assertIn("export type View = (typeof VIEWS)[number];", src)

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
