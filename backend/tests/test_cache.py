"""TTLCache unit tests — no DB, no app imports for the cache itself.

The `CacheWiringTest` class below does import the app: a green cache unit test
proves nothing if the two call sites quietly stopped using the cache.
"""
import os
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

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
        from app import db, ollama_sync as osy, prefs

        osy.invalidate_catalog()
        self.addCleanup(osy.invalidate_catalog)
        # `set_default` writes a pref and the seeds write catalog rows; the suite
        # shares one DB, so neither may leak into a later module.
        chat_model = prefs.get("ollama_chat_model")
        self.addCleanup(prefs.set_many, {"ollama_chat_model": chat_model})
        self.addCleanup(db.run, "DELETE FROM ollama_models")

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

    def test_a_nested_mutation_does_not_poison_the_cache(self):
        """Reassigning a top-level key is the easy case and a shallow copy handles
        it. The hazard is *inside* the envelope: `models` and each model dict are
        shared with the cached value, so a nested edit is what actually poisons
        the next reader. This is the test whose absence let the shallow copy ship.
        """
        from app import ollama_sync as osy

        calls = []
        with self._tags(_TAGS_A, calls):
            got = osy.live_list()
            got["models"][0]["name"] = "POISONED"       # nested dict edit
            got["models"].append({"name": "GHOST"})      # nested list edit
            again = osy.live_list()
        self.assertEqual(len(calls), 1, "a nested edit must not force a re-probe either")
        self.assertEqual([m["name"] for m in again["models"]], ["a:1"],
                         "a nested edit by one caller reached the next reader")
        self.assertEqual(again["models"][0]["family"], "fa",
                         "the whole cached model dict was shared, not just the name")

    def test_the_cache_is_keyed_on_the_ollama_base_url(self):
        """Pointing `ollama_base_url` at another machine must not serve the
        previous one's inventory and reachability for a full TTL — and
        `status()` reports the *new* base_url live, so one payload would otherwise
        describe two machines."""
        from app import ollama_sync as osy
        from app import prefs

        real_get = prefs.get
        box = {"base": "http://box-a:11434"}

        def fake_get(key):
            return box["base"] if key == "ollama_base_url" else real_get(key)

        calls = []
        with self._tags(_TAGS_A, calls):
            with patch("app.prefs.get", side_effect=fake_get):
                first = osy.live_list()
                box["base"] = "http://box-b:11434"
                second = osy.live_list()
        self.assertEqual(first["base_url"], "http://box-a:11434")
        self.assertEqual(len(calls), 2,
                         "changing ollama_base_url must be a cache miss, not a hit on box-a")
        self.assertEqual(second["base_url"], "http://box-b:11434")
        # …and back to box-a: its own entry is untouched and still a valid hit, so
        # the key scopes the entries instead of the cache simply being flushed.
        with self._tags(_TAGS_B, calls):
            with patch("app.prefs.get", side_effect=fake_get):
                box["base"] = "http://box-a:11434"
                third = osy.live_list()
        self.assertEqual(len(calls), 2, "box-a's entry should still have been there")
        self.assertEqual(third["base_url"], "http://box-a:11434")

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

    def _seed_db_catalog(self, names):
        from app import db

        db.run("DELETE FROM ollama_models")
        for n in names:
            db.run(
                "INSERT OR REPLACE INTO ollama_models (name,family,size_bytes,param_size,"
                "quantization,modified_at,caps_json,synced_at) VALUES (?,?,?,?,?,?,?,?)",
                (n, "fam", 1, "1B", "", "", '["chat"]', "2026-01-01T00:00:00Z"),
            )

    def test_set_default_revalidates_against_a_live_probe_when_ollama_answers(self):
        """The DB catalog is not the authority. Proving it needs the catalog to be
        *populated and wrong* in both directions — the old code probed only when it
        was empty, so with rows present it accepted a model Ollama had dropped and
        rejected one it had just gained."""
        from app import ollama_sync as osy

        self._seed_db_catalog(["a:1"])
        calls = []
        with self._tags(_TAGS_B, calls):  # Ollama now has b:1 and c:1, not a:1
            self.assertTrue(osy.set_default("chat", "c:1")["ok"],
                            "a freshly pulled model must validate against a live probe")
            with self.assertRaises(ValueError):
                osy.set_default("chat", "a:1")
        # Two probes for two calls, but not one *each*: `c:1` is absent from the
        # first probe's answer only in the sense that it had to be asked about —
        # the point that matters is asserted by the two tests below.
        self.assertGreaterEqual(len(calls), 2)

    def test_set_default_accepts_a_cached_probe_without_a_network_round_trip(self):
        """The reason `set_default` reads `_catalog_cache`: a settings mutation must
        not pay a 2.5s probe on the happy path. A model the cached probe already
        lists is accepted from it — and a stale positive can only ever fail safe,
        since the model existed up to a TTL ago.
        """
        from app import ollama_sync as osy

        self._seed_db_catalog(["a:1"])
        calls = []
        with self._tags(_TAGS_A, calls):
            osy.live_list()          # warm the cache: Ollama has a:1
            self.assertEqual(len(calls), 1)
            first = osy.set_default("chat", "a:1")
            second = osy.set_default("chat", "a:1")
        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertEqual(len(calls), 1,
                         "a model already listed by the cached probe must not re-probe")

    def test_set_default_refresh_bypasses_the_cache(self):
        """`refresh=True` is the explicit escape hatch: it must re-read the machine
        even when the cache holds an answer that would already have decided it."""
        from app import ollama_sync as osy

        self._seed_db_catalog(["a:1"])
        calls = []
        with self._tags(_TAGS_A, calls):
            osy.live_list()          # warm the cache with a:1
            self.assertEqual(len(calls), 1)
            self.assertTrue(osy.set_default("chat", "a:1", refresh=True)["ok"])
        self.assertEqual(len(calls), 2, "refresh=True must force a fresh probe")

    def test_set_default_reprobes_before_refusing_on_a_cached_negative(self):
        """The one staleness that must not survive: a cached answer that does *not*
        list the model may predate an `ollama pull`, and refusing on it would keep a
        freshly pulled model unselectable until the entry expired. So a negative
        verdict is re-probed uncached first.

        This is the bound the fix accepts, stated as a test: acceptance may read a
        probe up to `cache_ttl_s` old, but a refusal never does.
        """
        from app import ollama_sync as osy

        self._seed_db_catalog([])
        calls = []
        # The first probe answers "Ollama is up and has nothing"; every later probe
        # answers with a:1 present — i.e. the model gets pulled between the two.
        seq = iter([{"models": []}, _TAGS_A])

        def fake_get(url, timeout=None):
            calls.append(url)
            return _Resp(next(seq, _TAGS_A))

        with patch("app.ollama_sync.httpx.get", side_effect=fake_get):
            osy.live_list()  # caches the empty answer
            self.assertEqual(len(calls), 1)
            res = osy.set_default("chat", "a:1")
        self.assertTrue(res["ok"], "a model pulled after the cached empty probe must be selectable")
        self.assertEqual(len(calls), 2, "a cached negative must be re-probed before refusing")

    def test_set_default_still_refuses_a_model_ollama_dropped(self):
        """The hole the uncached probe was introduced to close must stay closed: a
        model present in a non-empty DB catalog but absent from Ollama is refused,
        cache or no cache."""
        from app import ollama_sync as osy

        self._seed_db_catalog(["a:1"])
        calls = []
        with self._tags(_TAGS_B, calls):  # Ollama has b:1 and c:1, not a:1
            with self.assertRaises(ValueError):
                osy.set_default("chat", "a:1")
            # A second attempt must not start accepting it from a cached negative.
            with self.assertRaises(ValueError):
                osy.set_default("chat", "a:1")
        self.assertGreaterEqual(len(calls), 2)

    def test_set_default_falls_back_to_the_db_catalog_only_when_ollama_is_down(self):
        """The one case the DB catalog is still trusted, and it is a deliberate
        trade: refusing here would make the model room unusable during an outage.
        Documented in `set_default` as staleness, not as a guarantee."""
        from app import ollama_sync as osy

        self._seed_db_catalog(["a:1"])

        def boom(*a, **k):
            raise ConnectionError("connection refused")

        with patch("app.ollama_sync.httpx.get", side_effect=boom):
            self.assertTrue(osy.set_default("chat", "a:1")["ok"],
                            "offline: the last synced catalog is the only answer available")
            self.assertRaises(ValueError, osy.set_default, "chat", "never-synced:1")

    def test_set_default_refuses_when_there_is_nothing_to_validate_against(self):
        from app import ollama_sync as osy

        self._seed_db_catalog([])
        self.assertRaises(ValueError, osy.set_default, "chat", "a:1")

    def test_invalidate_catalog_also_drops_the_health_probe_cache(self):
        """`Local LFM` and `Model Room` are two rows of one /api/health payload fed
        by two caches; a catalog rewrite that cleared only one of them could show
        `Local LFM: online` next to `Model Room: degraded` for a full TTL."""
        from app import health, ollama_sync as osy

        health._probe_cache.set("ollama_healthy:http://x", (True, "note"))
        health._probe_cache.set("vector", ("online", "chromadb available"))
        osy.invalidate_catalog()
        self.assertEqual(health._probe_cache.stats()["entries"], 0)

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

    def test_system_status_is_never_cached(self):
        """The single most important prohibition in this task.

        `system_status()` carries live DB counts, disk free and uptime — a stale
        "disk 98% full" is a lie. Wrapping it in a cache decorator leaves every
        other test in this file green, which is precisely the failure mode the
        brief exists to prevent. So this test is behavioural rather than
        structural: change the DB underneath and the *second* call must see it.
        """
        from app import db, health

        db.run("DELETE FROM runs WHERE trace_id='cache-probe'")
        before = health.system_status()["metrics"]["runs_24h"]
        db.run("INSERT INTO runs (trace_id, session_id, duration_ms) VALUES ('cache-probe', '', 1)")
        try:
            after = health.system_status()["metrics"]["runs_24h"]
            self.assertEqual(after, before + 1,
                             "system_status() served a cached payload: the DB changed "
                             "underneath it and the second call did not notice")
        finally:
            db.run("DELETE FROM runs WHERE trace_id='cache-probe'")
            health._probe_cache.clear()


    def test_scratch_sweep_reclaims_old_dirs_and_spares_young_ones(self):
        """The suite leaks a scratch dir per module; the sweep is what bounds it.

        Also pins the two-homes property: the sweep is registered in BOTH
        tests/__init__.py (for `python -m unittest tests.test_x`) and
        tests/test_env.py (for `discover -s tests`, which never imports the
        package). Asserted on the prefix list rather than by invoking atexit,
        which cannot be re-run inside a test.
        """
        import tempfile as _tf
        import time as _t
        from pathlib import Path

        pkg = __import__("tests")
        old = Path(_tf.gettempdir()) / "aura-cache-sweepcheck-old"
        young = Path(_tf.gettempdir()) / "aura-cache-sweepcheck-young"
        self.addCleanup(lambda: [shutil.rmtree(p, ignore_errors=True) for p in (old, young)])
        for p in (old, young):
            p.mkdir(parents=True, exist_ok=True)
        old_mtime = _t.time() - (pkg._ABANDONED_AFTER_S + 3600)
        os.utime(old, (old_mtime, old_mtime))

        self.assertIn("aura-cache-", pkg._SCRATCH_PREFIXES)
        self.assertIn("aura-slash-", pkg._SCRATCH_PREFIXES)
        self.assertNotIn("aura-restore-", pkg._SCRATCH_PREFIXES,
                         "app/backup.py uses that prefix for a live restore")

        pkg._reclaim_scratch()
        self.assertFalse(old.exists(), "an abandoned scratch dir must be reclaimed")
        self.assertTrue(young.exists(), "a young dir may belong to a run still in flight")

        # Every prefix the suite actually uses must be swept, or it leaks forever.
        used = {m.group(1) for m in re.finditer(
            r'mkdtemp\(prefix="(aura-[a-z-]+)"',
            "".join(open(f).read() for f in Path("tests").glob("test_*.py")))}
        unswept = {p for p in used if p not in pkg._SCRATCH_PREFIXES} - {"aura-restore-"}
        self.assertEqual(unswept, set(), f"test scratch prefixes never swept: {unswept}")


if __name__ == "__main__":
    unittest.main()
