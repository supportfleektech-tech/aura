"""Worker pool tests, plus the mission-tick regression guard."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-workers-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import inspect  # noqa: E402
import calendar  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, hermes, missions, prefs, workers  # noqa: E402
from app.main import app  # noqa: E402


def _clear_jobs():
    db.run("DELETE FROM worker_jobs")


class WorkersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def setUp(self):
        _clear_jobs()
        prefs.set_many({"worker_max_retries": 3, "worker_pool_size": 3})

    def test_enqueue_claim_complete(self):
        jid = workers.enqueue("custom", {"x": 1})
        claimed = workers.claim(1)
        self.assertEqual([j["id"] for j in claimed], [jid])
        self.assertEqual(claimed[0]["attempts"], 1)
        workers.complete(jid, {"ok": True})
        self.assertEqual(workers.stats()["done"], 1)
        self.assertEqual(workers.stats()["running"], 0)

    def test_claim_is_priority_ordered(self):
        """Priority ascending, ties broken by id — not insertion order.

        `a` is enqueued first but must be claimed third: ordering by id alone
        (or by enqueue order) puts it first and this fails.
        """
        first = workers.enqueue("custom", {"n": "p5-first"}, priority=5)
        top_a = workers.enqueue("custom", {"n": "p1-first"}, priority=1)
        low = workers.enqueue("custom", {"n": "p9"}, priority=9)
        top_b = workers.enqueue("custom", {"n": "p1-second"}, priority=1)
        got = [j["id"] for j in workers.claim(4)]
        self.assertEqual(got, [top_a, top_b, first, low], got)

    def test_claim_is_atomic_across_threads(self):
        """No job may be handed to two claimers.

        A SELECT/UPDATE/re-SELECT claim double-claims whenever two threads pick
        the same id before either marks it: the second UPDATE is a silent no-op
        (its `status='queued'` guard), and both then read the row back. Losing
        this test means a mission step can execute twice. Stressed over many
        rounds because the window is short — one pass proving nothing is worse
        than no test at all.
        """
        n = 6
        for jid in range(n):
            workers.enqueue("custom", {"j": jid})
        rounds = 25
        for _ in range(rounds):
            seen, lock = [], threading.Lock()
            barrier = threading.Barrier(n)

            def grab():
                barrier.wait()
                got = [r["id"] for r in workers.claim(1)]
                if got:
                    with lock:
                        seen.extend(got)

            ts = [threading.Thread(target=grab) for _ in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(len(seen), len(set(seen)),
                             f"same job claimed twice in one round: {seen}")
            for jid in seen:  # settle so the next round starts clean
                workers.complete(jid, {})

    def test_enqueue_inherits_max_retries_pref(self):
        """A pref of 0 means 'never retry', so it must not fall back to 3."""
        prefs.set_many({"worker_max_retries": 0})
        jid = workers.enqueue("custom", {})
        self.assertEqual(db.qone("SELECT max_retries FROM worker_jobs WHERE id=?",
                                 (jid,))["max_retries"], 0)
        self.assertEqual(workers.fail(workers.claim(1)[0]["id"], "boom"), "dead")

    def test_failure_retries_then_dead_letters(self):
        jid = workers.enqueue("custom", {}, max_retries=2)
        for i in (1, 2):
            c = workers.claim(1)
            self.assertTrue(c, "job must be claimable again")
            self.assertEqual(c[0]["attempts"], i, "attempts count executions")
            self.assertEqual(workers.fail(c[0]["id"], "boom"), "retry")
            db.run("UPDATE worker_jobs SET available_at='' WHERE id=?", (c[0]["id"],))
        c = workers.claim(1)
        self.assertEqual(workers.fail(c[0]["id"], "boom again"), "dead")
        dead = workers.dead_letters()
        self.assertEqual([j["id"] for j in dead], [jid])
        self.assertEqual(dead[0]["last_error"], "boom again")
        self.assertEqual(workers.stats()["dead"], 1)

    def test_backoff_delays_the_next_claim(self):
        jid = workers.enqueue("custom", {})
        workers.fail(workers.claim(1)[0]["id"], "boom")
        self.assertEqual(workers.claim(1), [], "a backed-off job must not be re-claimable yet")
        db.run("UPDATE worker_jobs SET available_at='' WHERE id=?", (jid,))
        self.assertEqual(len(workers.claim(1)), 1, "past available_at it is claimable again")

    def test_backoff_grows_with_attempts(self):
        """10s, 20s, 40s — read off the row, not recomputed from the formula.

        A flat backoff would still satisfy every other test here, so the growth
        is asserted explicitly; a growing backoff is what stops a poison job
        from being retried every single scheduler pass.
        """
        jid = workers.enqueue("custom", {}, max_retries=3)
        for expected in (10, 20, 40):
            c = workers.claim(1)
            self.assertTrue(c, "job must be claimable again")
            self.assertEqual(workers.fail(c[0]["id"], "boom"), "retry")
            at = db.qone("SELECT available_at FROM worker_jobs WHERE id=?",
                         (jid,))["available_at"]
            self.assertTrue(at, "a retrying job must carry a future available_at")
            ahead = calendar.timegm(time.strptime(at, workers.TIME_FMT)) - time.time()
            self.assertAlmostEqual(ahead, expected, delta=3,
                                   msg=f"attempt {c[0]['attempts']}: want ~{expected}s, got {ahead:.1f}s")
            db.run("UPDATE worker_jobs SET available_at='' WHERE id=?", (jid,))

    def test_drain_runs_and_settles(self):
        """A success and a failure in one drain, so `done` is not vacuously 0.

        `mission_tick` always settles (`tick_missions` swallows per-mission
        errors), `custom` has no dispatcher and always raises. The failing job
        takes max_retries=0 so it dead-letters on its first execution — with the
        default of 3 it would be *retried* and dead would stay 0.
        """
        workers.enqueue(workers.KIND_MISSION_TICK, {})
        workers.enqueue(workers.KIND_SCHEDULE_TICK, {}, priority=1)
        workers.enqueue("custom", {}, max_retries=0)
        r = workers.drain()
        self.assertEqual(r, {"ran": 3, "done": 2, "retried": 0, "dead": 1}, r)
        self.assertEqual(workers.stats()["done"], 2)
        self.assertEqual(workers.stats()["dead"], 1)
        self.assertEqual([j["kind"] for j in workers.dead_letters()], ["custom"])

    def test_drain_of_empty_queue_is_a_noop(self):
        self.assertEqual(workers.drain(), {"ran": 0, "done": 0, "retried": 0, "dead": 0})

    def test_stats_shape(self):
        for k in ("queued", "running", "done", "dead", "throughput_per_min",
                  "error_rate", "by_kind"):
            self.assertIn(k, workers.stats())
        workers.enqueue("custom", {}, priority=1)
        workers.enqueue("custom", {}, priority=2)
        s = workers.stats()
        self.assertEqual((s["queued"], s["running"], s["done"], s["dead"]), (2, 0, 0, 0), s)
        self.assertEqual(s["by_kind"], {"custom": 2}, s)
        workers.complete(workers.claim(1)[0]["id"], {})
        self.assertEqual(workers.fail(workers.claim(1)[0]["id"], "x"), "retry")
        s = workers.stats()
        # 1 done, 0 dead -> error_rate must be 0.0, not a ZeroDivisionError or 1.0
        self.assertEqual((s["done"], s["dead"]), (1, 0), s)
        self.assertEqual(s["error_rate"], 0.0, s)

    def test_requeue_stale_recovers_interrupted_jobs(self):
        jid = workers.enqueue("custom", {})
        workers.claim(1)
        self.assertEqual(workers.stats()["running"], 1)
        self.assertEqual(workers.requeue_stale(), 1)
        self.assertEqual(workers.stats()["queued"], 1)
        self.assertEqual(workers.stats()["running"], 0)
        self.assertEqual(workers.claim(1)[0]["id"], jid)

    def test_routes(self):
        r = self.c.get("/api/workers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"stats", "pool_size"}, body)
        self.assertEqual(body["pool_size"], 3)
        self.assertIn("by_kind", body["stats"])
        r = self.c.get("/api/workers/dead")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json()["dead"], list)
        r = self.c.post("/api/workers/drain", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("ran", r.json())


class MissionTickTest(unittest.TestCase):
    """Regression: the scheduler must drive missions, not just automations."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def setUp(self):
        _clear_jobs()

    def test_scheduler_loop_source_drives_missions(self):
        """The 30s loop body must reach the mission ticks.

        Asserted against the source, not by running the loop: it is a daemon
        thread that sleeps 30s between passes, so running it would take half a
        minute, leave a thread ticking the shared test DB for the rest of the
        run, and still prove nothing about the wiring.

        Three checks, because one is easy to fake: the loop must *call*
        `scheduler_pass` (parens, so a stray mention does not pass), must no
        longer tick automations itself (otherwise the string above could survive
        while the real work was dropped), and `scheduler_pass` itself must call
        both mission ticks.
        """
        loop = inspect.getsource(hermes.start_scheduler_loop)
        self.assertIn("scheduler_pass()", loop, loop)
        self.assertNotIn("hermes.tick_automations()", loop, loop)
        body = inspect.getsource(workers.scheduler_pass)
        self.assertIn("tick_missions()", body, body)
        self.assertIn("tick_schedules()", body, body)

    def test_scheduler_pass_advances_a_running_mission(self):
        """The behaviour itself: one pass must finish a one-step mission."""
        mid = self.c.post("/api/missions", json={"goal": "T-Tick advance probe"}).json()["id"]
        self.c.patch(f"/api/missions/{mid}", json={"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        self.c.post(f"/api/missions/{mid}/control", json={"action": "start"})
        before = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(before["status"], "running")
        self.assertEqual(before["steps"][0]["status"], "pending")
        out = workers.scheduler_pass()
        self.assertIn("missions", out, out)
        self.assertEqual([f["id"] for f in out["missions"]], [mid], out["missions"])
        after = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(after["status"], "done", after)
        self.assertEqual(after["steps"][0]["status"], "done")

    def test_scheduler_pass_ticks_due_schedules(self):
        """The other half of the bug: tick_schedules was also uncalled.

        Only a finished mission relaunches — a draft still needs review — so the
        fixture is a completed daily mission whose next_run_at has come round.
        """
        mid = self.c.post("/api/missions", json={"goal": "T-Tick schedule probe"}).json()["id"]
        self.c.patch(f"/api/missions/{mid}", json={"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        self.c.post(f"/api/missions/{mid}/schedule", json={"every": "daily"})
        db.run("UPDATE missions SET status='done', step_idx=1, "
               "next_run_at='2000-01-01T00:00:00+00:00' WHERE id=?", (mid,))
        out = workers.scheduler_pass()
        self.assertEqual([s["id"] for s in out["schedules"]], [mid], out["schedules"])
        # tick_schedules relaunches before tick_missions runs, so one pass both
        # relaunches it and drives the new run — assert both happened.
        self.assertEqual([f["id"] for f in out["missions"]], [mid], out["missions"])
        m = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(m["status"], "done", m)
        self.assertEqual(m["steps"][0]["status"], "done")
        self.assertGreater(m["next_run_at"], "2000-01-01",
                           "relaunch must reschedule, or it re-fires forever")


if __name__ == "__main__":
    unittest.main()