import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, db
from app.memory import memory_engine


class MemoryCorrectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db.reset()
        target = patch.object(config, "DB_PATH", str(Path(self.tmp.name) / "memory.db"))
        target.start()
        self.addCleanup(target.stop)
        self.addCleanup(db.reset)
        db.init_db()

    def test_correction_reindexes_and_preserves_original_source(self):
        def embed(text):
            return [1.0, 0.0, 0.0]

        embed._emb_name = "local:test"
        original = memory_engine.store("Delivery", "BlueKite arrives Monday", source="conversation", embedder=embed)
        mid = original["id"]
        result = memory_engine.update(mid, content="RedFinch arrives Friday")
        row = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
        self.assertEqual(row["embedding_model"], "hashed:192")
        self.assertEqual(len(db.jload(row["embedding_json"])), 192)
        self.assertNotEqual(row["embedding_json"], original["embedding_json"])
        self.assertEqual(result["source"], "user-corrected:conversation")
        self.assertEqual(db.q("SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'BlueKite'"), [])
        self.assertEqual(db.qone("SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'RedFinch'")["rowid"], mid)
        self.assertEqual(memory_engine.search("RedFinch")[0]["content"], "RedFinch arrives Friday")
        again = memory_engine.update(mid, content="RedFinch arrives Saturday")
        self.assertEqual(again["source"], "user-corrected:conversation")

    def test_metadata_and_unchanged_content_do_not_claim_correction(self):
        original = memory_engine.store("Delivery", "BlueKite arrives Monday", source="eval")
        for fields in ({"importance": 0.9}, {"content": original["content"]}):
            with self.subTest(fields=fields):
                result = memory_engine.update(original["id"], **fields)
                self.assertEqual(result["source"], "eval")

    def test_dedupe_tolerates_its_target_being_deleted_between_the_two_reads(self):
        """`_duplicate_of` matches through an FTS join and `store` then re-reads the
        row by id. Those are two reads, so the row can vanish in between. The old code
        dereferenced that `None` (`_before.get("sensitivity")`) and raised
        AttributeError on a row that was already gone; the pre-guard path tolerated it.

        The degradation has to be *sane*, not merely non-raising: with the dedupe
        target gone there is nothing to re-confirm or merge a sensitivity label onto,
        so the memory must be stored fresh and reported as `deduped: False` — a caller
        that trusts `deduped` must not be told a row was re-confirmed when none was.
        """
        real_qone = db.qone
        gone = {"done": False}

        def qone_vanishes(sql, params=()):
            # Only the pre-image read inside the dedupe branch loses the row; the
            # post-INSERT read that builds the return value must still see it.
            if (not gone["done"] and "FROM memories WHERE id=?" in sql
                    and str(sql).startswith("SELECT *")):
                gone["done"] = True
                return None
            return real_qone(sql, params)

        with patch.object(memory_engine, "_duplicate_of", return_value=12345):
            with patch.object(db, "qone", side_effect=qone_vanishes):
                result = memory_engine.store("Delivery", "Peregrine arrives Tuesday")

        self.assertTrue(gone["done"], "the vanished-row path was never exercised")
        self.assertFalse(result["deduped"], result)
        self.assertEqual(result["content"], "Peregrine arrives Tuesday")
        self.assertNotEqual(result["id"], 12345, "must not report the vanished row's id")
        self.assertIsNotNone(db.qone("SELECT * FROM memories WHERE id=?", (result["id"],)),
                             "a vanished dedupe target must still result in a stored row")

    def test_dedupe_branch_is_unchanged_when_the_row_survives(self):
        """The guard must not alter the normal path: a live dedupe target is still
        re-confirmed in place, still reports `deduped: True`, and still returns the
        post-UPDATE row rather than the pre-image."""
        first = memory_engine.store("Delivery", "Osprey leaves Friday")
        again = memory_engine.store("Delivery", "Osprey leaves Friday")
        self.assertTrue(again["deduped"], again)
        self.assertEqual(again["id"], first["id"])
        self.assertNotEqual(again["last_confirmed"], first["last_confirmed"],
                            "the surviving dedupe target must still be re-confirmed")
        self.assertEqual(db.qone("SELECT COUNT(*) AS n FROM memories WHERE id=?", (first["id"],))["n"], 1)
