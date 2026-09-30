"""Memory consolidation tests."""
import os
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="aura-consol-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from app import consolidate, db, memory, prefs  # noqa: E402


class ConsolidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        prefs.set_many({"consolidate_enabled": True})

    def _mk(self, title, content, **kw):
        return memory.memory_engine.store(
            title, content, kw.get("domain", "general"), kw.get("mtype", "semantic"),
            "test", kw.get("confidence", 0.7), kw.get("importance", 0.5),
            kw.get("sensitivity"))

    def _raw(self, title, content, **kw):
        """Insert straight to the table, past MemoryEngine._duplicate_of.

        Storing the second copy through `store` never reaches a consolidation
        pass: the store path dedupes it away first (that is what the second
        assertion below used to trip over). A row written this way is what an
        import, a migration, or a pre-dedupe write leaves behind.
        """
        mid = db.run(
            "INSERT INTO memories (user_id, domain, mtype, title, content, source, "
            "confidence, importance, sensitivity) VALUES (1,?,?,?,?,?,?,?,?)",
            (kw.get("domain", "general"), kw.get("mtype", "semantic"), title, content,
             "test", kw.get("confidence", 0.7), kw.get("importance", 0.5),
             kw.get("sensitivity") or "normal"))
        return dict(db.qone("SELECT * FROM memories WHERE id=?", (mid,)))

    def test_duplicates_merge_into_highest_importance(self):
        a = self._mk("standup", "standup is at nine every morning", importance=0.9)
        b = self._raw("standup time", "standup is at nine every morning ok", importance=0.3)
        self.assertNotEqual(a["id"], b["id"])
        r = consolidate.run_pass()
        self.assertGreaterEqual(r["merged"], 1, r)
        loser = db.qone("SELECT * FROM memories WHERE id=?", (b["id"],))
        self.assertIsNotNone(loser, "loser must be soft-deleted, not hard-deleted")
        self.assertIsNotNone(loser["deleted_at"])
        self.assertEqual(loser["supersedes_id"], a["id"])
        self.assertIsNone(memory.memory_engine.get(b["id"]))
        row = db.qone("SELECT * FROM memories WHERE id=?", (a["id"],))
        self.assertGreater(row["importance"], 0.9)

    def test_archive_skips_sensitive_and_private(self):
        kept = self._mk("bank", "bank pin is four four four four", importance=0.05,
                        confidence=0.2, sensitivity="sensitive")
        priv = self._mk("therapist", "my therapist is on tuesdays", importance=0.05,
                        confidence=0.2, sensitivity="private")
        dropped = self._mk("scratch", "old scratch note about nothing at all",
                           importance=0.05, confidence=0.2)
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z' "
               "WHERE id IN (?,?,?)", (kept["id"], priv["id"], dropped["id"]))
        r = consolidate.run_pass()
        self.assertGreaterEqual(r["archived"], 1, r)
        self.assertIsNotNone(memory.memory_engine.get(kept["id"]))
        self.assertIsNotNone(memory.memory_engine.get(priv["id"]))
        self.assertIsNone(memory.memory_engine.get(dropped["id"]))

    def test_fresh_low_signal_memory_is_not_archived(self):
        m = self._mk("fresh", "a brand new low signal note here", importance=0.05, confidence=0.2)
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(m["id"]),
                             "the 30-day age guard must protect a new memory")

    def test_should_run_is_daily(self):
        prefs.set_many({"consolidate_last_run": 0})
        self.assertTrue(consolidate.should_run())
        prefs.set_many({"consolidate_last_run": int(time.time())})
        self.assertFalse(consolidate.should_run())
        self.assertTrue(consolidate.should_run(now_ts=time.time() + 86401))

    def test_disabled_pref_blocks(self):
        prefs.set_many({"consolidate_enabled": False, "consolidate_last_run": 0})
        self.assertFalse(consolidate.should_run())

    def test_routes(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            prefs.set_many({"consolidate_enabled": True})
            r = c.post("/api/consolidation/run")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn("merged", r.json())
            g = c.get("/api/consolidation")
            self.assertEqual(g.status_code, 200)
            self.assertIn("enabled", g.json())
            self.assertIn("last_run", g.json())


if __name__ == "__main__":
    unittest.main()
