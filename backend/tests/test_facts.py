"""Tool-result fact extraction tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-facts-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from app import db, domain, facts, memory, orchestrator, prefs  # noqa: E402


class FactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    # ---------- wrapper payloads (list_* routes: return {"clients": rows}) ----------

    def test_client_output_yields_contact_fact(self):
        out = facts.extract("clients.create", {"client": {
            "id": 1, "name": "Amina Yusuf", "org": "Zebra Foods",
            "email": "amina@zebra.example"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "clients")
        self.assertEqual(out[0]["mtype"], "semantic")
        self.assertIn("amina@zebra.example", out[0]["content"])

    def test_client_without_contact_yields_nothing(self):
        self.assertEqual(facts.extract("clients.create", {"client": {"id": 1, "name": "No Contact"}}), [])

    def test_task_without_due_date_is_not_a_fact(self):
        self.assertEqual(facts.extract("tasks.create", {"task": {"id": 1, "title": "T-Facts ping"}}), [])

    def test_task_with_due_date_is_episodic(self):
        out = facts.extract("tasks.create", {"task": {
            "id": 1, "title": "T-Facts send deck", "due_at": "2026-10-01T09:00:00Z"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["mtype"], "episodic")
        self.assertIn("2026-10-01", out[0]["content"])

    def test_project_yields_career_fact(self):
        out = facts.extract("projects.create", {"project": {"id": 1, "name": "Kopilot", "status": "active"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "career")

    def test_search_output_yields_nothing(self):
        # Real shape: `memory_engine.search` returns a bare list, not a wrapper.
        self.assertEqual(facts.extract("memory.search", memory.memory_engine.search("anything")), [])
        # A memory row is not a client/task/project row either.
        stored = facts.harvest("clients.create", {
            "id": 77, "name": "Nia Bar", "email": "nia@bar.example"})
        self.assertEqual(len(stored), 1, stored)
        self.assertEqual(
            facts.extract("memory.search", {"results": [dict(stored[0])]}), [])

    def test_non_dict_result_yields_nothing(self):
        self.assertEqual(facts.extract("system.status", "a string"), [])
        self.assertEqual(facts.extract("system.status", None), [])

    def test_caps_at_three(self):
        data = {"clients": [{"name": f"C{i}", "email": f"c{i}@x.example"} for i in range(9)]}
        # Exactly 3, not "at most 3" — `<= 3` also passes if the plural
        # branch silently returned nothing, i.e. it cannot fail.
        self.assertEqual(len(facts.extract("clients.list", data)), 3)

    # ---------- Finding 1: bare rows, the shape *.create actually returns ----------

    def test_real_create_client_row_yields_fact(self):
        """Regression guard for the dead `*.create` path.

        `create_client` ends `return db.qone(...)` and `hermes._wrap_model`
        hands that row back unwrapped, so the payload is a BARE row. A
        hand-written `{"client": {...}}` fixture would keep passing after the
        bare-row branch was deleted — this one cannot.
        """
        row = domain.create_client(domain.ClientIn(
            name="Real Client", org="Zebra Foods",
            email="real.client@zebra.example"))
        self.assertNotIn("client", row, row)  # a bare row, not a wrapper
        out = facts.extract("clients.create", row)
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "clients")
        self.assertIn("real.client@zebra.example", out[0]["content"])

    def test_real_create_task_row_yields_fact(self):
        row = domain.create_task(domain.TaskIn(
            title="Real due-dated task", due_at="2026-11-02T09:00:00Z"))
        self.assertNotIn("task", row, row)
        out = facts.extract("tasks.create", row)
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["mtype"], "episodic")
        self.assertIn("2026-11-02", out[0]["content"])

    def test_real_create_task_without_due_yields_nothing(self):
        row = domain.create_task(domain.TaskIn(title="Real undated task"))
        self.assertEqual(facts.extract("tasks.create", row), [])

    def test_real_create_project_row_yields_fact(self):
        row = domain.create_project(domain.ProjectIn(
            name="Real Project", status="active", progress=10,
            deadline="2026-12-01"))
        self.assertNotIn("project", row, row)
        out = facts.extract("projects.create", row)
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "career")
        self.assertIn("Real Project", out[0]["content"])

    def test_real_list_tools_still_harvest_through_wrapper_branch(self):
        """The wrapper branch must survive alongside the bare-row branch."""
        domain.create_client(domain.ClientIn(
            name="Listed Client", email="listed.client@zebra.example"))
        out = facts.extract("clients.list", domain.list_clients())
        self.assertTrue(out, "wrapper payload yielded nothing")
        self.assertTrue(any("listed.client@zebra.example" in f["content"] for f in out), out)

    def test_goal_row_is_not_mistaken_for_a_project(self):
        """`progress` alone must not be enough: a `goals` row has it but no `name`."""
        self.assertEqual(facts.extract("personal.dashboard", {
            "id": 5, "title": "Ship v2", "target": "done", "progress": 40,
            "status": "active", "domain": "career"}), [])

    def test_ack_dict_is_not_a_fact(self):
        self.assertEqual(facts.extract("clients.delete", {"ok": True}), [])

    # ---------- Finding 2: client contact PII must not be cloud-groundable ----------

    def test_client_fact_is_stored_private(self):
        row = domain.create_client(domain.ClientIn(
            name="Pii Client", email="pii.client@zebra.example"))
        stored = facts.harvest("clients.create", row)
        self.assertEqual(len(stored), 1, stored)
        self.assertEqual(stored[0]["sensitivity"], "private", stored[0])
        self.assertEqual(
            memory.sensitivity_scan("Contact: Pii Client\nPii Client — pii.client@zebra.example"),
            "normal", "sensitivity_scan alone would let this through")
        from app.inference import filter_cloud_memories
        kept, withheld = filter_cloud_memories(stored, policy="strict")
        self.assertEqual(kept, [], kept)
        self.assertEqual(withheld, 1, withheld)
        # Withheld under the relaxed policy too.
        kept, _ = filter_cloud_memories(stored, policy="relaxed")
        self.assertEqual(kept, [], kept)

    def test_non_client_facts_still_use_sensitivity_scan(self):
        row = domain.create_task(domain.TaskIn(
            title="Undated scan probe", description=""))
        self.assertEqual(facts.extract("tasks.create", row), [])
        row = domain.create_task(domain.TaskIn(
            title="rotate my api key", due_at="2026-11-03T09:00:00Z"))
        stored = facts.harvest("tasks.create", row)
        self.assertEqual(len(stored), 1, stored)
        self.assertEqual(stored[0]["sensitivity"], "sensitive", stored[0])

    # ---------- Finding 3: a project status change must not accumulate rows ----------

    def test_project_status_change_reconfirms_one_row(self):
        active = facts.extract("projects.list", {"projects": [
            {"id": 91, "name": "Statusy", "status": "active"}]})
        done = facts.extract("projects.list", {"projects": [
            {"id": 91, "name": "Statusy", "status": "done"}]})
        self.assertEqual(len(active), 1, active)
        self.assertEqual(len(done), 1, done)
        # Dedupe is content-only, so the volatile status must not be in content.
        self.assertEqual(active[0]["content"], done[0]["content"])
        self.assertNotIn("done", done[0]["content"])
        # Nor in the title: the dedupe path never rewrites a title, so a status
        # parked there would be a permanently stale claim. Both facts, both
        # fields, status-free.
        self.assertEqual(active[0]["title"], done[0]["title"])
        self.assertNotIn("done", done[0]["title"])

        first = facts.harvest("projects.list", {"projects": [
            {"id": 91, "name": "Statusy", "status": "active"}]})
        self.assertEqual(len(first), 1, first)
        self.assertFalse(first[0].get("deduped"), first[0])
        second = facts.harvest("projects.list", {"projects": [
            {"id": 91, "name": "Statusy", "status": "done"}]})
        self.assertEqual(len(second), 1, second)
        self.assertTrue(second[0].get("deduped"), second)
        self.assertEqual(second[0]["id"], first[0]["id"])
        self.assertEqual(len(db.q(
            "SELECT id FROM memories WHERE content LIKE '%Statusy%' AND deleted_at IS NULL")), 1)

    def test_project_fact_title_carries_no_status(self):
        """The status is gone from `title` too, not relocated to it.

        The dedupe path (`memory.store`) bumps `last_confirmed`/`importance` and
        never rewrites a title, so any status left in the title is stale
        forever — and the title is the field a human reads. This pins the
        invariant across every status, not just the one transition
        `test_project_status_change_reconfirms_one_row` exercises.
        """
        for status in ("active", "done", "paused", "at_risk", None, "", "BLOCKED"):
            out = facts.extract("projects.list", {"projects": [
                {"id": 92, "name": "Titled", "status": status}]})
            self.assertEqual(len(out), 1, (status, out))
            self.assertEqual(out[0]["title"], "Project: Titled", (status, out[0]))
            if status:  # `assertNotIn("")` is vacuously false, so skip empty
                self.assertNotIn(str(status).lower(), out[0]["title"].lower(), status)
                self.assertNotIn(str(status).lower(), out[0]["content"].lower(), status)

    # ---------- a re-confirmation must not weaken an existing sensitivity ------

    def test_dedupe_upgrades_existing_normal_row_to_private(self):
        """A `private` fact deduped onto a `normal` row must upgrade the row.

        `observe` stores chat-derived memories with the scanner's verdict, which
        has no email/phone pattern, so a contact written into chat first lands
        as `normal`. The client fact then dedupes onto it (content Jaccard
        3/4 = 0.75 > 0.55). Before this was guarded, the row kept `normal` and
        stayed cloud-groundable — the `private` marking silently did nothing.
        """
        # Distinctive tokens: this row stays in the shared test DB for the rest
        # of the run, so it must not Jaccard-overlap any other fixture.
        # Real chat path first: no `sensitivity` argument, so the scanner runs.
        observed = memory.memory_engine.observe(
            "My contact is Vesper Quibblegram vesper.quibblegram@zephyr.example")
        self.assertEqual(len(observed), 1, observed)
        self.assertEqual(observed[0]["sensitivity"], "normal", observed[0])

        row = domain.create_client(domain.ClientIn(
            name="Vesper Quibblegram", email="vesper.quibblegram@zephyr.example"))
        stored = facts.harvest("clients.create", row)
        self.assertEqual(len(stored), 1, stored)
        # Same row, re-confirmed — not a second copy.
        self.assertTrue(stored[0].get("deduped"), stored[0])
        self.assertEqual(stored[0]["id"], observed[0]["id"])
        self.assertEqual(stored[0]["sensitivity"], "private", stored[0])
        self.assertEqual(len(db.q(
            "SELECT id FROM memories WHERE content LIKE '%vesper.quibblegram@zephyr.example%'"
            " AND deleted_at IS NULL")), 1)

        # The invariant that matters: not cloud-groundable under ANY policy,
        # including the weakest one.
        from app.inference import filter_cloud_memories
        for policy in ("strict", "relaxed"):
            kept, withheld = filter_cloud_memories([stored[0]], policy=policy)
            self.assertEqual(kept, [], (policy, kept))
            self.assertEqual(withheld, 1, (policy, withheld))

    def test_dedupe_never_downgrades_a_private_row(self):
        """The merge is one-way: a weaker incoming label cannot relax a row."""
        priv = memory.memory_engine.store(
            "Private row", "Zeta downgrade probe zeta@priv.example",
            sensitivity="private")
        self.assertEqual(priv["sensitivity"], "private", priv)
        again = memory.memory_engine.store(
            "Private row", "Zeta downgrade probe zeta@priv.example",
            sensitivity="normal")
        self.assertTrue(again.get("deduped"), again)
        self.assertEqual(again["id"], priv["id"])
        self.assertEqual(again["sensitivity"], "private", again)
        # `sensitive` is the *weaker* label here (strict-only withholding), so
        # it must not displace `private` either.
        third = memory.memory_engine.store(
            "Private row", "Zeta downgrade probe zeta@priv.example",
            sensitivity="sensitive")
        self.assertEqual(third["sensitivity"], "private", third)

    # ---------- harvest / wiring ----------

    def test_harvest_persists_and_second_call_dedupes(self):
        data = {"client": {"id": 9, "name": "Bo Ade", "email": "bo@ade.example"}}
        first = facts.harvest("clients.create", data)
        self.assertEqual(len(first), 1, first)
        self.assertIn("bo@ade.example", first[0]["content"])
        # The first call must actually insert, not dedupe against something
        # that was already in the DB.
        self.assertFalse(first[0].get("deduped"), first[0])
        rows = db.q(
            "SELECT id FROM memories WHERE content LIKE '%bo@ade.example%' AND deleted_at IS NULL")
        self.assertEqual(len(rows), 1, rows)
        second = facts.harvest("clients.create", data)
        self.assertTrue(second[0].get("deduped"), second)
        # Same row re-confirmed, not a second copy.
        self.assertEqual(second[0]["id"], first[0]["id"])
        self.assertEqual(len(db.q(
            "SELECT id FROM memories WHERE content LIKE '%bo@ade.example%' AND deleted_at IS NULL")), 1)

    def test_harvest_emits_facts_event_into_turn_context(self):
        """`_harvest` is the wiring the spec requires; extract() alone does not prove it."""
        data = {"client": {"id": 4, "name": "Wren Cole", "email": "wren@cole.example"}}
        events = orchestrator._harvest("clients.create", data, {}, [], {})
        names = [n for n, _ in events]
        self.assertIn("facts", names)
        payload = dict(events)["facts"]
        self.assertEqual(len(payload["stored"]), 1, payload)
        self.assertEqual(payload["stored"][0]["title"], "Contact: Wren Cole")

    def test_harvest_never_raises_on_junk(self):
        self.assertEqual(facts.harvest("clients.create", object()), [])


    def test_harvest_respects_the_memory_auto_store_preference(self):
        """Turning auto-store off must stop tool results writing memories too.

        `memory_engine.observe` was gated on `memory_auto_store` and the fact
        path was not, so a read-only `tasks.list` kept writing rows after the
        user turned it off — enough churn to fail an agent eval. Pinned here
        because a bypassed preference is invisible until someone notices.
        """
        data = {"client": {"id": 5, "name": "Sena Otieno", "email": "sena@otieno.example"}}
        prefs.set_many({"memory_auto_store": False})
        self.addCleanup(prefs.set_many, {"memory_auto_store": True})
        before = (db.qone("SELECT COUNT(*) c FROM memories") or {}).get("c", 0)

        events = orchestrator._harvest("clients.create", data, {}, [], {})
        self.assertNotIn("facts", [n for n, _ in events],
                         "a disabled preference must emit no facts event")

        after = (db.qone("SELECT COUNT(*) c FROM memories") or {}).get("c", 0)
        self.assertEqual(after, before, "memory_auto_store=False must not write memories")

        prefs.set_many({"memory_auto_store": True})
        events = orchestrator._harvest("clients.create", data, {}, [], {})
        self.assertIn("facts", [n for n, _ in events], "re-enabled must work again")


if __name__ == "__main__":
    unittest.main()
