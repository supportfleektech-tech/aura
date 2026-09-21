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
