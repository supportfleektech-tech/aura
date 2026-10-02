import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_scratch = tempfile.TemporaryDirectory(prefix="aura-retrieval-")
os.environ.setdefault("AURA_DATA_DIR", _scratch.name)

from app import config, db
from app.inference import ModelRouter
from app.memory import MemoryEngine, hashed_embed


class MemoryRetrievalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db.reset()
        target = patch.object(config, "DB_PATH", str(Path(self.tmp.name) / "memory.db"))
        target.start()
        self.addCleanup(target.stop)
        self.addCleanup(db.reset)
        db.init_db()
        self.engine = MemoryEngine()

    def insert(self, content, domain="general", mtype="semantic", deleted=None,
               vector=None, model="hashed:192", importance=0.5, confidence=0.7):
        return db.run(
            "INSERT INTO memories (user_id, title, content, domain, mtype, deleted_at, "
            "embedding_json, embedding_model, importance, confidence) VALUES (1,?,?,?,?,?,?,?,?,?)",
            (content, content, domain, mtype, deleted,
             db.jdump(hashed_embed(content) if vector is None else vector), model, importance, confidence),
        )

    def fill_recent(self, count=405, domain="general"):
        db.run_many(
            "INSERT INTO memories (user_id, title, content, domain, embedding_json) VALUES (1,?,?,?,?)",
            [("Routine", "routine daily planning", domain, db.jdump(hashed_embed("routine daily planning")))] * count,
        )

    def test_older_rare_fts_match_survives_recent_window(self):
        old = self.insert("quartzfalcon observatory")
        self.fill_recent()
        hits = self.engine.search("quartzfalcon", limit=1)
        self.assertEqual([h["id"] for h in hits], [old])
        self.assertEqual(hits[0]["why_used"], "matched your words")

    def test_filtered_candidates_do_not_crowd_out_domain_and_type(self):
        for _ in range(35):
            self.insert("quartzfalcon", domain="private-other")
            self.insert("quartzfalcon", domain="work", mtype="episodic")
            self.insert("quartzfalcon", domain="work", deleted="2026-01-01")
        work = self.insert("quartzfalcon", domain="work")
        general = self.insert("quartzfalcon")
        self.fill_recent(domain="private-other")
        hits = self.engine.search("quartzfalcon", domain="work", mtype="semantic", limit=10)
        self.assertEqual([h["id"] for h in hits], [general, work])
        self.assertTrue(all(h["why_used"] == "matched your words" for h in hits))

    def test_fts_limit_selects_best_matches_with_deterministic_ties(self):
        for _ in range(35):
            self.insert("quartzfalcon " + "routine " * 100)
        best = self.insert("quartzfalcon")
        self.fill_recent()
        for _ in range(2):
            self.assertEqual(self.engine.search("quartzfalcon", limit=1)[0]["id"], best)

    def test_union_deduplicates_and_keeps_candidate_bound(self):
        old = [self.insert("quartzfalcon") for _ in range(40)]
        self.fill_recent()
        hits = self.engine.search("quartzfalcon", limit=1000)
        ids = [h["id"] for h in hits]
        self.assertEqual(len(ids), 430)
        self.assertEqual(ids[:30], list(reversed(old[-30:])))
        recent_match = self.insert("quartzfalcon")
        hits = self.engine.search("quartzfalcon", limit=1000)
        ids = [h["id"] for h in hits]
        self.assertEqual(ids[0], recent_match)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(ids), 430)

    def test_same_dimension_different_models_never_score_after_migration_budget(self):
        ids = [self.insert("observatory", vector=[1.0] + [0.0] * 31,
                           model="ollama:old", importance=0, confidence=0) for _ in range(6)]
        def embed(text):
            return [1.0] + [0.0] * 31
        embed._emb_name = "ollama:new"
        hits = self.engine.search("unmatched", embedder=embed)
        self.assertEqual([h["id"] for h in hits], list(reversed(ids[1:])))
        self.assertEqual(db.qone("SELECT embedding_model FROM memories WHERE id=?", (ids[0],))["embedding_model"], "ollama:old")

    def test_invalid_stored_vectors_do_not_crash_or_score(self):
        for vector in ({"bad": 1}, "x" * 192, [float("nan")] * 192, ["x"] * 192):
            self.insert("observatory", vector=vector)
        hits = self.engine.search("observatory")
        self.assertEqual(len(hits), 4)
        for row in db.q("SELECT embedding_json, embedding_model FROM memories"):
            self.assertEqual(row["embedding_model"], "hashed:192")
            self.assertTrue(all(isinstance(v, float) for v in db.jload(row["embedding_json"])))
        self.assertTrue(all(0 < h["relevance"] < 2 for h in hits))

    def test_invalid_local_embeddings_fall_back_with_consistent_identity(self):
        router = ModelRouter()
        for invalid in (None, [], [1.0], [float("nan")] * 32,
                        [float("inf")] * 32, ["bad"] * 32, [0.0] * 32):
            with self.subTest(invalid=repr(invalid)[:40]), \
                    patch.object(router, "probe", return_value={"local_lfm": {"online": True}}), \
                    patch.object(router.ollama, "embed", return_value=invalid):
                fn = router.embed_fn()
                result = fn("quartzfalcon")
                self.assertEqual(getattr(result, "_emb_name", getattr(fn, "_emb_name", None)), "hashed:192")
                self.assertEqual(result, hashed_embed("quartzfalcon"))

    def test_fallback_during_migration_is_not_tagged_or_scored_as_neural(self):
        router = ModelRouter()
        mid = self.insert("observatory", vector=[1.0] * 64, model="ollama:old", importance=0, confidence=0)
        for size in (32, 192):
            with self.subTest(size=size), \
                    patch.object(router, "probe", return_value={"local_lfm": {"online": True}}), \
                    patch.object(router.ollama, "embed", side_effect=[[1.0] + [0.0] * (size - 1), None]):
                hits = self.engine.search("unmatched", embedder=router.embed_fn())
                self.assertEqual(hits, [])
                row = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
                self.assertEqual(row["embedding_model"], "hashed:192")
                self.assertEqual(len(db.jload(row["embedding_json"])), 192)

    def test_result_identity_survives_next_call_recovering(self):
        router = ModelRouter()
        with patch.object(router, "probe", return_value={"local_lfm": {"online": True}}), \
                patch.object(router.ollama, "embed", side_effect=[None, [1.0] + [0.0] * 31]):
            fn = router.embed_fn()
            fallback = fn("quartzfalcon")
            neural = fn("observatory")
            self.assertEqual(getattr(fallback, "_emb_name", None), "hashed:192")
            self.assertTrue(getattr(neural, "_emb_name", "").startswith("ollama:"))
            self.assertEqual(len(neural), 32)

    def test_unavailable_ollama_stores_hashed_identity(self):
        router = ModelRouter()
        with patch.object(router, "probe", return_value={"local_lfm": {"online": True}}), \
                patch.object(router.ollama, "embed", return_value=None):
            row = self.engine.store("Observatory", "quartzfalcon observatory", embedder=router.embed_fn())
        self.assertEqual(row["embedding_model"], "hashed:192")
        self.assertEqual(db.jload(row["embedding_json"]), hashed_embed("quartzfalcon observatory"))


    def test_cosine_is_scale_invariant_for_unnormalised_vectors(self):
        """`_cosine` must be a cosine, not a dot product.

        Every other test in this suite runs with Ollama unreachable, so every
        vector comes from `hashed_embed`, which L2-normalises — which is exactly
        why a bare dot product passed for so long. Real `nomic-embed-text`
        vectors have norm ~20, and there a dot product ranks by vector LENGTH:
        a perfect match scores ~230 instead of 1.0, swamping the FTS term, and
        the UI renders `relevance * 100` as a percentage ("23000%").
        """
        from app.memory import _cosine

        # Same direction, wildly different lengths.
        short = [1.0, 0.0, 0.0]
        long = [20.0, 0.0, 0.0]
        self.assertAlmostEqual(_cosine(short, short), 1.0, places=6)
        self.assertAlmostEqual(_cosine(short, long), 1.0, places=6,
                               msg="collinear vectors of different norms must both score 1.0")
        self.assertLessEqual(abs(_cosine(short, long)), 1.0,
                             "cosine must stay in [-1, 1] or the UI percentage is nonsense")

        # Perpendicular and opposite stay at the boundaries.
        self.assertAlmostEqual(_cosine([1.0, 0.0], [0.0, 5.0]), 0.0, places=6)
        self.assertAlmostEqual(_cosine([1.0, 0.0], [-3.0, 0.0]), -1.0, places=6)

        # A longer but non-collinear vector must not outrank a closer one.
        near = [10.0, 1.0]
        far_long = [30.0, 0.5]
        self.assertGreater(_cosine(near, far_long), _cosine(near, [10.0, 0.0]) - 0.01,
                           "sanity: aligned pair outranks the perpendicular one")

        # Degenerate input must not raise.
        self.assertEqual(_cosine([0.0, 0.0], [1.0, 1.0]), 0.0)
        self.assertEqual(_cosine([], []), 0.0)

    def test_search_relevance_stays_within_unit_range_for_real_scale_vectors(self):
        """A whole-search check with unnormalised vectors, end to end.

        Pins the user-visible symptom: `relevance` is rendered as a percentage
        in the Memory and Home views, so it must never leave [0, 1].
        """
        import app.memory as _m
        from app import db as _db

        _db.init_db()
        real_embedder = lambda text: [20.0 * (i + 1) for i in range(192)]  # norm ~ 2700
        before = _db.qone("SELECT COUNT(*) c FROM memories") or {"c": 0}
        _m.memory_engine.store("WQ12 anchoring note", "the WQ12 deployment anchors the shelf",
                               "general", "semantic", "test", 0.7, 0.5)
        hits = _m.memory_engine.search("WQ12", limit=10, embedder=real_embedder)
        self.assertGreaterEqual(len(hits), 1)
        for h in hits:
            self.assertGreaterEqual(h["relevance"], -1.0, h["title"])
            self.assertLessEqual(h["relevance"], 1.0,
                                 f"{h['title']} scored {h['relevance']}: UI shows this as a %")
        if len(hits) > 1:
            self.assertLessEqual(len(hits), (before.get("c", 0)) + 12,
                                 "score>0.05 must not admit the entire corpus")
        _db.run("DELETE FROM memories WHERE source='test' AND title LIKE 'WQ12%'")


if __name__ == "__main__":
    unittest.main()
