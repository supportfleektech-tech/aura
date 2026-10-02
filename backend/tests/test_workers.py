"""Worker pool tests, plus the mission-tick regression guard."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-workers-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

# AURA_DISABLE_SCHEDULER is set in tests/test_env.py (discover) and
# tests/__init__.py (tests.test_*). Not here: a run that never imports this
# module would then leave the scheduler thread live.

import inspect  # noqa: E402
import calendar  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, hermes, missions, prefs, workers  # noqa: E402
from app.main import app  # noqa: E402


def _clear_jobs():
    db.run("DELETE FROM worker_jobs")


def _quiesce_missions():
    """Park every mission other test modules left behind.

    All modules share one database, so by the time this file runs, missions
    started by test_aura / test_kanban are still `running` and completed ones
    may carry a due `next_run_at`. `tick_missions` and `tick_schedules` both
    select `ORDER BY id LIMIT 5`, so those rows get ticked alongside — or
    instead of — the fixture this class just created. Only the assertions here
    depend on this, and no module runs after this one.
    """
    db.run("UPDATE missions SET next_run_at='' WHERE user_id=1")
    db.run("UPDATE missions SET status='done' WHERE user_id=1 "
           "AND status NOT IN ('done','failed','cancelled')")


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
        self.assertEqual({k: r[k] for k in ("ran", "done", "retried", "dead")},
                         {"ran": 3, "done": 2, "retried": 0, "dead": 1}, r)
        self.assertEqual(set(r["results"]), {"schedule_tick", "mission_tick"}, r)
        self.assertEqual(workers.stats()["done"], 2)
        self.assertEqual(workers.stats()["dead"], 1)
        self.assertEqual([j["kind"] for j in workers.dead_letters()], ["custom"])

    def test_drain_of_empty_queue_is_a_noop(self):
        r = workers.drain()
        self.assertEqual({k: r[k] for k in ("ran", "done", "retried", "dead")},
                         {"ran": 0, "done": 0, "retried": 0, "dead": 0})
        self.assertEqual(r["results"], {}, "an empty drain reports no per-kind results")

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


class PoolSizeTest(unittest.TestCase):
    """`pool_size` is the ThreadPoolExecutor's max_workers, so its clamp matters.

    prefs validates `worker_pool_size` to 1..8 on write, so the clamp only ever
    sees a value the validator would have rejected — a corrupt settings row, or
    a future SCHEMA range widened without revisiting this line. That is exactly
    when it must not hand back 0 (max_workers=0 raises ValueError, killing every
    drain) or 99 (99 threads contending on one SQLite lock buys no throughput).
    `prefs.get` is stubbed rather than set through set_many for that reason.
    """

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_pool_size_is_clamped_to_the_valid_range(self):
        self.assertEqual(workers.pool_size(), 3, "unset pref -> SCHEMA default")
        # `0 or 3` -> 3: a zero is indistinguishable from unset here, and the
        # validator rejects 0 anyway, so it falls back rather than clamping.
        for raw, want in ((0, 3), (None, 3), (-4, 1), (20, 8), (1, 1), (8, 8)):
            with mock.patch.object(prefs, "get", return_value=raw):
                self.assertEqual(workers.pool_size(), want, f"raw={raw!r}")


class StatsFieldsTest(unittest.TestCase):
    """The computed fields of stats(), asserted against a built fixture.

    `stats_shape` above only proves the keys exist, so hardcoding any of these
    three expressions to a constant keeps every test in this file green. They are
    the numbers a user reads on the workers panel, so each is pinned to a value
    worked out by hand from a known set of rows.
    """

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        _clear_jobs()

    def test_throughput_counts_only_recently_settled_jobs(self):
        self.assertEqual(workers.stats()["throughput_per_min"], 0)
        jid = workers.enqueue("custom", {})
        # Queued is not throughput: a job nobody has run has settled nothing.
        self.assertEqual(workers.stats()["throughput_per_min"], 0)
        workers.complete(workers.claim(1)[0]["id"], {})
        self.assertEqual(workers.stats()["throughput_per_min"], 1)
        db.run("UPDATE worker_jobs SET updated_at=? WHERE id=?",
               (workers._iso(time.time() - 3600), jid))
        self.assertEqual(workers.stats()["throughput_per_min"], 0,
                         "a row settled an hour ago is not this minute's throughput")

    def test_error_rate_is_dead_over_settled(self):
        self.assertEqual(workers.stats()["error_rate"], 0.0,
                         "nothing settled yet -> 0.0, not a ZeroDivisionError")
        for _ in range(3):
            workers.complete(workers.enqueue("custom", {}), {})
        dead = workers.enqueue("custom", {}, max_retries=0)
        # claim() first: fail() reads `attempts`, which counts executions, so
        # failing an unclaimed job sees 0 attempts and retries instead.
        self.assertEqual([j["id"] for j in workers.claim(1)], [dead])
        self.assertEqual(workers.fail(dead, "boom"), "dead")
        s = workers.stats()
        self.assertEqual((s["done"], s["dead"]), (3, 1), s)
        self.assertEqual(s["error_rate"], 0.25, s)
        # Queued work is neither a success nor a failure, so it must not move it.
        workers.enqueue("custom", {})
        self.assertEqual(workers.stats()["error_rate"], 0.25, workers.stats())


class RunReturningTest(unittest.TestCase):
    """Direct coverage for `db.run_returning`, the primitive `claim` is built on.

    db.py's other helpers are exercised from test_aura.py, but this one is
    load-bearing for the queue — `claim` is a single UPDATE..RETURNING precisely
    because the SELECT/UPDATE/re-SELECT form double-claims — and until now
    nothing tested it except claim itself.
    """

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        _clear_jobs()

    def test_returns_the_updated_rows(self):
        jid = workers.enqueue("custom", {"n": 1})
        rows = db.run_returning(
            "UPDATE worker_jobs SET status='done' WHERE id=? RETURNING id, status", (jid,))
        self.assertEqual(rows, [{"id": jid, "status": "done"}], rows)
        self.assertEqual(
            db.qone("SELECT status FROM worker_jobs WHERE id=?", (jid,))["status"], "done")

    def test_returns_empty_when_nothing_matched(self):
        self.assertEqual(db.run_returning(
            "UPDATE worker_jobs SET status='done' WHERE id=-1 RETURNING id"), [])

    def test_honours_dry_run(self):
        jid = workers.enqueue("custom", {})
        with db.preview():
            out = db.run_returning(
                "UPDATE worker_jobs SET status='dead' WHERE id=? RETURNING status", (jid,))
        # The statement still reports the rows it would have written...
        self.assertEqual(out, [{"status": "dead"}], out)
        # ...but DRY_RUN suppressed the commit and preview rolled it back, which
        # is the whole point: without the `if not DRY_RUN` guard this row sticks.
        self.assertEqual(
            db.qone("SELECT status FROM worker_jobs WHERE id=?", (jid,))["status"], "queued")


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
        _quiesce_missions()

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
        # The ticks moved behind the queue, so the guard follows them: the pass
        # must enqueue a mission cycle, and the dispatcher must run both ticks.
        # One hop further than before, same property — a mission cannot stop
        # advancing without breaking this.
        body = inspect.getsource(workers.scheduler_pass)
        self.assertIn("enqueue(KIND_MISSION_CYCLE", body, body)
        self.assertNotIn("_m.tick_missions()", body,
                         "the cycle must go through the queue, not be called inline")
        dispatch = inspect.getsource(workers._run)
        self.assertIn("tick_missions()", dispatch, dispatch)
        self.assertIn("tick_schedules()", dispatch, dispatch)

    def test_scheduler_pass_advances_a_running_mission(self):
        """The behaviour itself: one pass must finish a one-step mission.

        Asserts this mission is *among* the fired ones rather than the only one:
        `tick_missions` legitimately advances every running mission, and which
        other rows are running depends on module order. `setUp` parks them, so
        membership is what this test actually means.
        """
        mid = self.c.post("/api/missions", json={"goal": "T-Tick advance probe"}).json()["id"]
        self.c.patch(f"/api/missions/{mid}", json={"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        self.c.post(f"/api/missions/{mid}/control", json={"action": "start"})
        before = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(before["status"], "running")
        self.assertEqual(before["steps"][0]["status"], "pending")
        out = workers.scheduler_pass()
        self.assertIn("missions", out, out)
        self.assertIn(mid, [f["id"] for f in out["missions"]], out["missions"])
        after = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(after["status"], "done", after)
        self.assertEqual(after["steps"][0]["status"], "done")

    def test_enqueue_has_a_production_caller(self):
        """The pool must be wired, not merely implemented.

        This branch wrote the rule into AGENTS.md — "a background function is not
        wired until something in `app/` calls it" — after a mission tick turned
        out to have no production caller while its tests were green. The same
        mistake would make `enqueue` an 11-test shell and leave the perf panel
        showing zeros forever. Grep `app/`, never `tests/`.
        """
        import ast as _ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        callers = []
        for py in app_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                tree = _ast.parse(py.read_text())
            except SyntaxError:
                continue
            for n in _ast.walk(tree):
                if isinstance(n, _ast.Call):
                    fn = n.func
                    name = fn.attr if isinstance(fn, _ast.Attribute) else (
                        fn.id if isinstance(fn, _ast.Name) else None)
                    if name == "enqueue":
                        callers.append(f"{py.relative_to(app_dir)}:{n.lineno}")
        self.assertTrue(callers, "workers.enqueue has no caller in backend/app — the pool is inert")

    def test_scheduler_pass_runs_the_mission_cycle_through_the_queue(self):
        """The cycle must go via the queue, not an inline call.

        Pinned because the inline version also worked, so no behavioural test
        could tell them apart — the only difference is durability: a queued job
        survives a restart and retries with backoff.
        """
        db.run("DELETE FROM worker_jobs")
        workers.scheduler_pass()
        kinds = {r["kind"] for r in db.q("SELECT DISTINCT kind FROM worker_jobs")}
        self.assertIn(workers.KIND_MISSION_CYCLE, kinds,
                      f"mission cycle was not enqueued; kinds seen: {kinds}")
        self.assertEqual(workers.stats()["queued"], 0, "the pass must also drain what it enqueues")

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
        self.assertIn(mid, [s["id"] for s in out["schedules"]], out["schedules"])
        # tick_schedules relaunches before tick_missions runs, so one pass both
        # relaunches it and drives the new run — assert both happened.
        self.assertIn(mid, [f["id"] for f in out["missions"]], out["missions"])
        m = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(m["status"], "done", m)
        self.assertEqual(m["steps"][0]["status"], "done")
        self.assertGreater(m["next_run_at"], "2000-01-01",
                           "relaunch must reschedule, or it re-fires forever")


if __name__ == "__main__":
    unittest.main()