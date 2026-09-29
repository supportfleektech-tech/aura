"""Unit tests for guard.py, limits.py, and inference.py."""
import unittest
import time


class TestGuard(unittest.TestCase):
    """Tests for OriginGuardMiddleware."""

    def test_host_of_strips_scheme_and_slash(self):
        from app.guard import _host_of
        self.assertEqual(_host_of("http://localhost:5173"), "localhost:5173")
        self.assertEqual(_host_of("https://example.com/"), "example.com")
        self.assertEqual(_host_of("localhost:5173"), "localhost:5173")
        self.assertEqual(_host_of(""), "")
        self.assertEqual(_host_of(None), "")

    def test_mutating_methods_defined(self):
        from app.guard import MUTATING
        self.assertIn("POST", MUTATING)
        self.assertIn("PUT", MUTATING)
        self.assertIn("PATCH", MUTATING)
        self.assertIn("DELETE", MUTATING)
        self.assertNotIn("GET", MUTATING)
        self.assertNotIn("HEAD", MUTATING)


class TestLimits(unittest.TestCase):
    """Tests for rate limiting."""

    def setUp(self):
        from app import limits
        limits.reset()

    def test_scope_for_routes(self):
        from app import limits, config
        old_chat = config.RL_CHAT_PER_MIN
        old_upload = config.RL_UPLOAD_PER_MIN
        old_api = config.RL_API_PER_MIN
        config.RL_CHAT_PER_MIN = 10
        config.RL_UPLOAD_PER_MIN = 5
        config.RL_API_PER_MIN = 20
        try:
            self.assertEqual(limits.scope_for("POST", "/api/chat/stream"), ("chat", 10))
            self.assertEqual(limits.scope_for("POST", "/api/files/upload"), ("upload", 5))
            self.assertEqual(limits.scope_for("POST", "/api/voice/transcribe"), ("upload", 5))
            self.assertEqual(limits.scope_for("POST", "/api/voice/speak"), ("upload", 5))
            self.assertEqual(limits.scope_for("GET", "/api/tasks"), ("api", 20))
            self.assertEqual(limits.scope_for("POST", "/api/tasks"), ("api", 20))
            self.assertIsNone(limits.scope_for("GET", "/health"))
            self.assertIsNone(limits.scope_for("GET", "/"))
        finally:
            config.RL_CHAT_PER_MIN = old_chat
            config.RL_UPLOAD_PER_MIN = old_upload
            config.RL_API_PER_MIN = old_api

    def test_check_allows_within_limit(self):
        from app import limits
        allowed, remaining, retry = limits.check("127.0.0.1", "api", 5)
        self.assertTrue(allowed)
        self.assertEqual(remaining, 4)
        self.assertEqual(retry, 0)

    def test_check_blocks_at_limit(self):
        from app import limits
        for _ in range(3):
            limits.check("10.0.0.1", "api", 3)
        allowed, remaining, retry = limits.check("10.0.0.1", "api", 3)
        self.assertFalse(allowed)
        self.assertEqual(remaining, 0)
        self.assertGreater(retry, 0)

    def test_check_zero_limit_always_allows(self):
        from app import limits
        allowed, remaining, retry = limits.check("127.0.0.1", "api", 0)
        self.assertTrue(allowed)

    def test_reset_clears_all(self):
        from app import limits
        limits.check("127.0.0.1", "api", 5)
        limits.reset()
        allowed, remaining, retry = limits.check("127.0.0.1", "api", 1)
        self.assertTrue(allowed)
        self.assertEqual(remaining, 0)  # 1 - 1 = 0

    def test_separate_ips_independent(self):
        from app import limits
        limits.check("10.0.0.1", "api", 1)
        allowed, remaining, _ = limits.check("10.0.0.2", "api", 1)
        self.assertTrue(allowed)


class TestInferenceNormModel(unittest.TestCase):
    """Tests for _norm_model capability extraction."""

    def test_norm_model_empty(self):
        from app.inference import _norm_model
        r = _norm_model({})
        self.assertIn("id", r)
        self.assertIn("name", r)
        self.assertFalse(r["reasoning"])
        self.assertFalse(r["vision"])

    def test_norm_model_with_reasoning_param(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "test/reason", "supported_parameters": ["reasoning"]})
        self.assertTrue(r["reasoning"])

    def test_norm_model_with_thinking_param(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "test/think", "supported_parameters": ["thinking"]})
        self.assertTrue(r["reasoning"])

    def test_norm_model_vision_via_modality(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "test/vision", "architecture": {"modality": "text+image->text"}})
        self.assertTrue(r["vision"])
        self.assertTrue(r["multimodal"])

    def test_norm_model_video_multimodal(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "test/video", "architecture": {"modality": "text+video->text"}})
        self.assertTrue(r["multimodal"])
        self.assertFalse(r["vision"])

    def test_norm_model_free_detection(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "test:free", "pricing": {"prompt": "0", "completion": "0"}})
        self.assertTrue(r["free"])

    def test_norm_model_preserves_id(self):
        from app.inference import _norm_model
        r = _norm_model({"id": "custom/model-v2"})
        self.assertEqual(r["id"], "custom/model-v2")


class TestInferenceRouter(unittest.TestCase):
    """Tests for ModelRouter."""

    def test_chain_local_first(self):
        from app import prefs, config
        old_key = config.CLOUD_API_KEY
        config.CLOUD_API_KEY = ""
        try:
            from app.inference import router
            chain = router.chain()
            self.assertEqual(chain[0], "ollama")
            self.assertIn("builtin", chain)
        finally:
            config.CLOUD_API_KEY = old_key

    def test_probe_has_required_keys(self):
        from app.inference import router
        p = router.probe()
        self.assertIn("local_lfm", p)
        self.assertIn("cloud", p)
        self.assertIn("builtin", p)
        self.assertIn("privacy", p)


class TestHermesParseSleepText(unittest.TestCase):
    """Tests for parse_sleep_text."""

    def test_slept_11pm_to_6am(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("slept 11pm to 6am")
        self.assertTrue(r["parsed"])
        self.assertAlmostEqual(r["hours"], 7.0, places=1)

    def test_slept_10_30pm_to_5_30am(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("slept 10:30pm to 5:30am")
        self.assertTrue(r["parsed"])
        self.assertAlmostEqual(r["hours"], 7.0, places=1)

    def test_log_sleep_hours(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("log sleep 7.5 hours")
        self.assertTrue(r["parsed"])
        self.assertEqual(r["hours"], 7.5)

    def test_sleep_5_hours(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("sleep 5 hours")
        self.assertTrue(r["parsed"])
        self.assertEqual(r["hours"], 5.0)

    def test_unparseable(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("I feel great today")
        self.assertFalse(r["parsed"])
        self.assertIn("hint", r)

    def test_midnight_crossing(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("slept 11pm to 7am")
        self.assertTrue(r["parsed"])
        self.assertAlmostEqual(r["hours"], 8.0, places=1)

    def test_24h_format(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("slept 23:00 to 07:00")
        self.assertTrue(r["parsed"])
        self.assertAlmostEqual(r["hours"], 8.0, places=1)

    def test_with_hyphen(self):
        from app.hermes import parse_sleep_text
        r = parse_sleep_text("slept 10pm - 6am")
        self.assertTrue(r["parsed"])
        self.assertAlmostEqual(r["hours"], 8.0, places=1)


if __name__ == "__main__":
    unittest.main()
