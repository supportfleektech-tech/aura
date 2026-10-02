"""TTLCache unit tests — no DB, no app imports for the cache itself.

The `CacheWiringTest` class below does import the app: a green cache unit test
proves nothing if the two call sites quietly stopped using the cache.
"""
import os
import tempfile
import time
import unittest

_tmp = tempfile.mkdtemp(prefix="aura-cache-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

from app import cache  # noqa: E402


class CacheTest(unittest.TestCase):
    def test_set_get_and_miss(self):
        c = cache.TTLCache(max_entries=8, ttl_s=30)
        self.assertIsNone(c.get("k"))
        c.set("k", {"v": 1})
        self.assertEqual(c.get("k"), {"v": 1})
        self.assertEqual(c.stats()["hits"], 1)
        self.assertEqual(c.stats()["misses"], 1)

    def test_expiry(self):
        c = cache.TTLCache(max_entries=8, ttl_s=0.05)
        c.set("k", 1)
        self.assertEqual(c.get("k"), 1)
        time.sleep(0.08)
        self.assertIsNone(c.get("k"), "entry should have expired")

    def test_ttl_zero_disables_caching(self):
        c = cache.TTLCache(max_entries=8, ttl_s=0)
        c.set("k", 1)
        self.assertIsNone(c.get("k"), "ttl 0 must never return a hit")

    def test_lru_eviction(self):
        c = cache.TTLCache(max_entries=3, ttl_s=30)
        for i in range(3):
            c.set(f"k{i}", i)
        c.get("k0")
        c.set("k3", 3)
        self.assertIsNone(c.get("k1"), "k1 was least recently used and should be evicted")
        self.assertEqual(c.get("k0"), 0, "k0 was just read, so it survives")
        self.assertEqual(c.stats()["evictions"], 1)

    def test_delete_and_clear(self):
        c = cache.TTLCache(max_entries=8, ttl_s=30)
        c.set("a", 1); c.set("b", 2)
        c.delete("a")
        self.assertIsNone(c.get("a"))
        c.clear()
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.stats()["entries"], 0)

    def test_stats_shape(self):
        s = cache.TTLCache(max_entries=4, ttl_s=30).stats()
        for k in ("entries", "hits", "misses", "hit_rate", "evictions", "ttl_s"):
            self.assertIn(k, s)

    def test_hit_rate_is_zero_when_empty(self):
        self.assertEqual(cache.TTLCache(max_entries=4, ttl_s=30).stats()["hit_rate"], 0.0)

    def test_decorator(self):
        calls = []

        @cache.cached(ttl_s=30, max_entries=8)
        def expensive(x):
            calls.append(x)
            return x * 2

        self.assertEqual(expensive(2), 4)
        self.assertEqual(expensive(2), 4)
        self.assertEqual(len(calls), 1, "second call must be served from cache")
        self.assertEqual(expensive(3), 6)
        self.assertEqual(len(calls), 2, "a different key must miss")

    def test_store_survives_an_unhashable_value(self):
        c = cache.TTLCache(max_entries=4, ttl_s=30)
        c.set("k", {"nested": [1, 2, {"deep": True}]})
        self.assertEqual(c.get("k"), {"nested": [1, 2, {"deep": True}]})

    def test_per_entry_ttl_overrides_the_default(self):
        """A failure must be held for seconds, not a full TTL — that is the whole
        point of the per-entry override at the /api/tags call site."""
        c = cache.TTLCache(max_entries=4, ttl_s=30)
        c.set("short", 1, ttl_s=0.05)
        c.set("long", 2)
        self.assertEqual(c.get("short"), 1)
        self.assertEqual(c.get("long"), 2)
        time.sleep(0.08)
        self.assertIsNone(c.get("short"), "the short-TTL entry must have expired")
        self.assertEqual(c.get("long"), 2, "the default-TTL entry must survive")

    def test_set_ttl_disables_reads_without_dropping_entries(self):
        c = cache.TTLCache(max_entries=4, ttl_s=30)
        c.set("k", 1)
        self.assertEqual(c.get("k"), 1)
        c.set_ttl(0)
        self.assertIsNone(c.get("k"), "ttl 0 must never return a hit")
        c.set_ttl(30)
        self.assertIsNone(c.get("k"), "an entry stored under ttl 0 stays dead")
        c.set("k2", 2)
        self.assertEqual(c.get("k2"), 2, "caching is live again")


_TAGS_A = {"models": [{"model": "a:1", "size": 1, "details": {"family": "fa", "parameter_size": "1B"}}]}
_TAGS_B = {"models": [{"model": "b:1", "size": 1, "details": {"family": "fb", "parameter_size": "1B"}},
                      {"model": "c:1", "size": 1, "details": {"family": "fc", "parameter_size": "1B"}}]}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class CacheWiringTest(unittest.TestCase):
    """The cache is only worth anything if the call sites actually use it, and
    only safe if the *validating* paths bypass it."""

    @classmethod
    def setUpClass(cls):
        from app import db

        db.init_db()

    def setUp(self):
        from app import ollama_sync as osy

        osy.invalidate_catalog()
        self.addCleanup(osy.invalidate_catalog)

    def _tags(self, payload, calls):
        from unittest.mock import patch

        def fake_get(url, timeout=None):
            calls.append(url)
            return _Resp(payload)

        return patch("app.ollama_sync.httpx.get", side_effect=fake_get)

    def test_live_list_serves_the_second_call_from_cache(self):
        from app import ollama_sync as osy

        calls = []
        with self._tags(_TAGS_A, calls):
            first = osy.live_list()
            second = osy.live_list()
        self.assertEqual(len(calls), 1, "the second /api/tags GET must come from the cache")
        self.assertEqual(first["ok"], True)
        self.assertEqual([m["name"] for m in second["models"]], ["a:1"])

    def test_a_mutated_result_does_not_poison_the_cache(self):
        from app import ollama_sync as osy

        calls = []
        with self._tags(_TAGS_A, calls):
            got = osy.live_list()
            got["ok"] = False
            got["models"] = []
            again = osy.live_list()
        self.assertEqual(len(calls), 1, "the poisoned envelope must not have evicted the entry")
        self.assertEqual(again["ok"], True)
        self.assertEqual([m["name"] for m in again["models"]], ["a:1"])

    def test_sync_bypasses_and_invalidates_the_cache(self):
        """A refresh that reads a cached catalog stamps a fresh `synced_at` onto
        data nobody re-read — the panel would claim 'synced just now'."""
        from app import db, ollama_sync as osy

        calls = []
        with self._tags(_TAGS_A, calls):
            osy.sync()
        self.assertEqual(len({m["name"] for m in osy.cached()}), 1)
        with self._tags(_TAGS_B, calls):
            osy.sync()
        self.assertEqual(len({m["name"] for m in osy.cached()}), 2,
                         "sync must re-probe, not replay the cached catalog")
        db.run("DELETE FROM ollama_models")

    def test_set_default_validates_against_a_fresh_probe(self):
        """A stale catalog must not be able to accept a model Ollama dropped, nor
        reject one it just gained."""
        from app import db, ollama_sync as osy

        db.run("DELETE FROM ollama_models")  # force the live-lookup path
        try:
            calls = []
            with self._tags(_TAGS_A, calls):
                osy.live_list()  # warm the cache with the OLD catalog
            with self._tags(_TAGS_B, calls):
                self.assertTrue(osy.set_default("chat", "c:1")["ok"],
                                "a freshly pulled model must validate against a live probe")
                self.assertEqual(len(calls), 2, "set_default must not read the cached catalog")
                self.assertRaises(ValueError, osy.set_default, "chat", "a:1")
        finally:
            db.run("DELETE FROM ollama_models")

    def test_cache_ttl_zero_disables_the_catalog_cache(self):
        from unittest.mock import patch

        from app import ollama_sync as osy
        from app import prefs

        real_get = prefs.get

        def fake_get(key):
            return 0 if key == "cache_ttl_s" else real_get(key)

        calls = []
        with self._tags(_TAGS_A, calls):
            with patch("app.prefs.get", side_effect=fake_get):
                osy.live_list()
                osy.live_list()
        self.assertEqual(len(calls), 2, "cache_ttl_s=0 must mean no caching at all")

    def test_a_failure_is_not_held_for_the_full_ttl(self):
        from unittest.mock import patch

        from app import ollama_sync as osy

        def boom(*a, **k):
            raise ConnectionError("connection refused")

        with patch("app.ollama_sync._FAIL_TTL_S", 0.05):
            with patch("app.ollama_sync.httpx.get", side_effect=boom) as p:
                osy.live_list()
                osy.live_list()
                self.assertEqual(p.call_count, 1, "a failure is cached, briefly")
            time.sleep(0.08)
            with patch("app.ollama_sync.httpx.get", side_effect=boom) as p:
                osy.live_list()
                self.assertEqual(p.call_count, 1,
                                 "past the failure TTL the probe must run again")

    def test_health_probes_are_cached_but_the_counters_are_not(self):
        from unittest.mock import patch

        from app import health

        health._probe_cache.clear()
        before = health._probe_cache.stats()  # counters are cumulative
        with patch("app.inference.router.ollama.healthy",
                   side_effect=lambda *a, **k: (True, "note")):
            health._probe_lfm()
            health._probe_lfm()
            after = health._probe_cache.stats()
        self.assertEqual(after["hits"] - before["hits"], 1, "the second probe must hit the cache")
        self.assertEqual(after["misses"] - before["misses"], 1,
                         "the ollama HTTP leg must not run twice inside the TTL")

        scanned = []
        real_qone = health.db.qone

        def _count(sql, *a, **k):
            # Only the memories scan matters; the settings read behind tuned_ttl
            # is expected to go to the DB.
            if "FROM memories" in str(sql):
                scanned.append(1)
                return {"c": 7}
            return real_qone(sql, *a, **k)

        health._probe_cache.clear()
        # Force the fallback branch: with chromadb importable the probe returns
        # before the query and this test would measure nothing.
        with patch.dict("sys.modules", {"chromadb": None}):
            with patch("app.health.db.qone", side_effect=_count):
                first_v = health._probe_vector()
                second_v = health._probe_vector()
        self.assertEqual(len(scanned), 1, "the vector COUNT(*) full scan must be cached")
        self.assertEqual(first_v, second_v)
        self.assertIn("7 indexed", first_v[1])
        health._probe_cache.clear()


if __name__ == "__main__":
    unittest.main()
