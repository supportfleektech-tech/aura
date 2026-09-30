"""Tool-result fact extraction tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-facts-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from app import db, facts, orchestrator  # noqa: E402


class FactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

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
        self.assertEqual(facts.extract("memory.search", {"results": [{"id": 1, "title": "x"}]}), [])

    def test_non_dict_result_yields_nothing(self):
        self.assertEqual(facts.extract("system.status", "a string"), [])
        self.assertEqual(facts.extract("system.status", None), [])

    def test_caps_at_three(self):
        data = {"clients": [{"name": f"C{i}", "email": f"c{i}@x.example"} for i in range(9)]}
        # Exactly 3, not "at most 3" — `<= 3` also passes if the plural
        # branch silently returned nothing, i.e. it cannot fail.
        self.assertEqual(len(facts.extract("clients.list", data)), 3)

    def test_harvest_persists_and_second_call_dedupes(self):
        data = {"client": {"id": 9, "name": "Bo Ade", "email": "bo@ade.example"}}
        first = facts.harvest("clients.create", data, "clients")
        self.assertEqual(len(first), 1, first)
        self.assertIn("bo@ade.example", first[0]["content"])
        # The first call must actually insert, not dedupe against something
        # that was already in the DB.
        self.assertFalse(first[0].get("deduped"), first[0])
        rows = db.q(
            "SELECT id FROM memories WHERE content LIKE '%bo@ade.example%' AND deleted_at IS NULL")
        self.assertEqual(len(rows), 1, rows)
        second = facts.harvest("clients.create", data, "clients")
        self.assertTrue(second[0].get("deduped"), second)
        # Same row re-confirmed, not a second copy.
        self.assertEqual(second[0]["id"], first[0]["id"])
        self.assertEqual(len(db.q(
            "SELECT id FROM memories WHERE content LIKE '%bo@ade.example%' AND deleted_at IS NULL")), 1)

    def test_harvest_emits_facts_event_into_turn_context(self):
        """`_harvest` is the wiring the spec requires; extract() alone does not prove it."""
        data = {"client": {"id": 4, "name": "Wren Cole", "email": "wren@cole.example"}}
        events = orchestrator._harvest("clients.create", data, {}, [], {}, "clients")
        names = [n for n, _ in events]
        self.assertIn("facts", names)
        payload = dict(events)["facts"]
        self.assertEqual(len(payload["stored"]), 1, payload)
        self.assertEqual(payload["stored"][0]["title"], "Contact: Wren Cole")


if __name__ == "__main__":
    unittest.main()