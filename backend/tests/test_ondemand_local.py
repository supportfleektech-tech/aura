"""On-demand local backend: nothing contacts Ollama until it is wanted.

The user asked for cloud-first with local models as the secondary that has to
be started deliberately, rather than being probed from startup. These tests pin
the boundary by counting network calls, not by asserting on return values — a
return-value assertion cannot tell "did not call" from "called and cached".
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-ondemand-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, health, prefs  # noqa: E402
from app.inference import router  # noqa: E402
from app.main import app  # noqa: E402


class OnDemandLocalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def setUp(self):
        self._real_healthy = router.ollama.healthy
        self.calls = []
        router.ollama.healthy = lambda *a, **k: (self.calls.append(1), (False, "stub"))[1]
        router._local_active = False
        router._checked_at = 0.0
        router._ollama_ok = None
        prefs.set_many({"ollama_on_demand": True, "privacy": "local-first"})
        self.addCleanup(prefs.set_many, {"ollama_on_demand": False})

    def tearDown(self):
        router.ollama.healthy = self._real_healthy
        router._local_active = False

    def test_dormant_probe_makes_no_network_call(self):
        pr = router.probe()
        self.assertEqual(self.calls, [], "an idle AURA must not open a connection to Ollama")
        self.assertIn("dormant", pr["local_lfm"]["note"])
        self.assertTrue(pr["on_demand"])

    def test_health_panel_reports_not_started_without_calling(self):
        status, note, _ = health._probe_lfm()
        self.assertEqual(self.calls, [], "the health poll must not probe a model server")
        self.assertEqual(status, "degraded")
        self.assertIn("not started", note)

    def test_activate_probes_exactly_once(self):
        router.activate_local()
        self.assertEqual(len(self.calls), 1)
        router.activate_local()
        self.assertEqual(len(self.calls), 1, "activation is idempotent — a turn is not a re-probe")
        router.activate_local(force=True)
        self.assertEqual(len(self.calls), 2, "force is the explicit re-check")

    def test_activate_route_is_the_explicit_start(self):
        r = self.c.post("/api/ollama/activate")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(len(self.calls), 1)

    def test_turning_on_demand_off_restores_eager_probing(self):
        prefs.set_many({"ollama_on_demand": False})
        router.probe()
        self.assertEqual(len(self.calls), 1,
                         "with on-demand off, probe must behave as it always did")

    def test_a_typed_message_activates_the_local_backend(self):
        """A turn is an explicit request for an answer, so it must un-dormant."""
        from app import orchestrator

        self.assertEqual(self.calls, [], "precondition: dormant")
        for _ in orchestrator.run_turn("hello there", session_id="ondemand-1"):
            pass
        self.assertGreaterEqual(len(self.calls), 1,
                                "a typed message must activate the local backend")

    def test_local_first_still_never_reaches_cloud(self):
        """The privacy invariant must survive on-demand work.

        On-demand changes *when* Ollama is contacted; it must not change *what*
        `local-first` is allowed to reach.
        """
        self.assertNotIn("cloud", router.chain())
        prefs.set_many({"privacy": "cloud"})
        self.assertEqual(router.chain()[0], "cloud",
                         "cloud mode puts cloud first — the toggle already existed")


if __name__ == "__main__":
    unittest.main()
