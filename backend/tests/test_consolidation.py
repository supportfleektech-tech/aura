"""Memory consolidation tests."""
import os
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="aura-consol-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

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

    def _signalled(self, title, content, source="test", days_ago=1, importance=0.5):
        """A row already carrying both re-scoring signals, both aged `days_ago`.

        Stamps are written with SQLite's own `strftime` so they are the exact
        shape `consolidate._epoch` parses — and so a test can age a signal
        without hand-rolling ISO. `store()` is unusable for this: it dedupes,
        so a second copy never gets a `last_confirmed` of its own.
        """
        row = self._raw(title, content, importance=importance)
        db.run("UPDATE memories SET last_confirmed="
               "strftime('%Y-%m-%dT%H:%M:%fZ','now',?), source=?, "
               "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now',?) WHERE id=?",
               (f"-{days_ago} day", source, f"-{days_ago} day", row["id"]))
        return dict(db.qone("SELECT * FROM memories WHERE id=?", (row["id"],)))

    def _imp(self, mid):
        return float(db.qone("SELECT importance FROM memories WHERE id=?", (mid,))["importance"])

    def _await_second_boundary(self):
        """Block until the wall clock is within 50 ms of a second boundary.

        The two idempotency regressions below only bite when the pass's end and
        the stamp it wrote fall in the *same* second — that is exactly the case a
        finer-grained parse gets wrong. Waiting for a fresh second makes that the
        likely case instead of a coin flip, so the tests keep catching the
        regression whether or not the pass happens to straddle. A pass takes
        single-digit milliseconds, so it comfortably fits inside the second.
        """
        while time.time() % 1 > 0.05:
            time.sleep(0.005)

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

    def test_archive_survives_high_importance_low_confidence_aged(self):
        """Pins the importance threshold: this row satisfies *every* other clause.

        Low confidence, aged, `last_confirmed IS NULL`, `sensitivity = 'normal'`
        — only `importance = 0.5` stands between it and archival. Archiving it
        can therefore only mean `ARCHIVE_IMPORTANCE` was not applied. The old
        `test_archive_skips_sensitive_and_private` could not say this: its one
        must-archive row satisfied the sensitivity guard too, so the count it
        asserted was satisfied by the sensitivity clause alone.
        """
        row = self._mk("platypus", "platypus foraging survey across the weir pool",
                       importance=0.5, confidence=0.2, sensitivity="normal")
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?",
               (row["id"],))
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "an important memory must survive even with low confidence")

    def test_archive_survives_recent_low_signal_row(self):
        """Pins the 30-day age guard: low importance *and* low confidence, but new."""
        row = self._mk("quetzal", "quetzal nest count in the upper canopy terrace",
                       importance=0.05, confidence=0.2, sensitivity="normal")
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "a row older than nothing yet is not an archive candidate")

    def test_archive_survives_high_confidence_low_importance_aged(self):
        """Pins the confidence threshold: this row satisfies *every* other clause.

        Low importance, aged, `last_confirmed IS NULL`, `sensitivity = 'normal'` —
        only `confidence = 0.7` stands between it and archival. Note that no
        *survival* test can pin the confidence threshold from the other side: a
        row that has to be archived cannot also be a must-survive row, so the
        threshold needs its own dedicated fixture rather than a variant of the
        existing ones.
        """
        row = self._mk("bandicoot", "bandicoot nesting survey beside the gravel track",
                       importance=0.05, confidence=0.7, sensitivity="normal")
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?",
               (row["id"],))
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "a confident memory must survive even at low importance")

    def test_archive_survives_confirmed_low_signal_row(self):
        """Pins the `last_confirmed IS NULL` clause, and nothing else.

        Low importance, low confidence, aged, normal sensitivity. The
        confirmation is stamped 900 days ago so it is also *not* a live
        re-scoring signal — `last_confirmed` protects a row from archival
        whatever its age, not only while it is fresh.
        """
        row = self._raw("tapir", "tapir browse line along the shaded corridor",
                        confidence=0.2, importance=0.05)
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z', "
               "last_confirmed=strftime('%Y-%m-%dT%H:%M:%fZ','now','-900 day') WHERE id=?",
               (row["id"],))
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "only `last_confirmed IS NULL` can be keeping this row alive")

    def test_archive_survives_private_low_signal_row(self):
        """The load-bearing guard, isolated: private beats every other disqualifier."""
        row = self._mk("diary", "note about the far creek where the dam gave way",
                       importance=0.05, confidence=0.2, sensitivity="private")
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?",
               (row["id"],))
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "a private memory must never be archived, however low-signal")

    def test_merged_row_is_not_also_archived(self):
        """Pins the archive pass reading rows the earlier passes have mutated.

        Pass order is dedupe, re-score, archive, so this pass's archive query
        sees the merge fold's output and the merge's `last_confirmed` stamp.
        The winner below stays *under* `ARCHIVE_IMPORTANCE` after the fold, so
        the stamp is the only thing saving it — if a future change reordered the
        archive pass ahead of the dedupe, it would be archived in the same pass
        it was merged in. Losing a candidate is the conservative direction, so
        the passes stay in this order; this test is what keeps that a decision
        rather than an accident.
        """
        prefs.set_many({"consolidate_last_run": 0})
        a = self._raw("dugong", "dugong seagrass meadow census off the point",
                      confidence=0.2, importance=0.05)
        b = self._raw("dugong census", "dugong seagrass meadow census off the point again",
                      confidence=0.2, importance=0.05)
        self.assertNotEqual(a["id"], b["id"])
        db.run("UPDATE memories SET created_at='2020-01-01T00:00:00.000Z' WHERE id IN (?,?)",
               (a["id"], b["id"]))
        r = consolidate.run_pass()
        self.assertGreaterEqual(r["merged"], 1, r)
        winner = min(a["id"], b["id"])
        self.assertIsNone(memory.memory_engine.get(max(a["id"], b["id"])), "loser merged away")
        self.assertLessEqual(self._imp(winner), consolidate.ARCHIVE_IMPORTANCE,
                             "the winner must still be archive-eligible on importance, "
                             "or this test proves nothing about the interaction")
        self.assertIsNotNone(memory.memory_engine.get(winner),
                             "a merge winner is disqualified from archival by the merge itself")

    def test_fresh_low_signal_memory_is_not_archived(self):
        m = self._mk("fresh", "a brand new low signal note here", importance=0.05, confidence=0.2)
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(m["id"]),
                             "the 30-day age guard must protect a new memory")

    def test_back_to_back_passes_do_not_rescore(self):
        """Back-to-back passes, no waiting — the watermark must hold on its own grid.

        The re-arm tests below `sleep(1.05)`, which is what let the resolution
        mismatch through: they re-stamp a signal a whole second past the
        watermark, so both a fractional and a floored parse score them. Here the
        confirmation is stamped `now`, i.e. in the same wall-clock second the
        pass runs in, and the assertion is that nothing walks to the 1.0 cap
        anyway.

        Deterministic under the fix, not merely likely: pass 1 always consumes
        the signal (the watermark starts at 0), and the watermark it then writes
        is at least as new as the stamp, whatever second boundary falls where.
        """
        prefs.set_many({"consolidate_last_run": 0})
        row = self._raw("numbat", "numbat thermal survey of the eastern catchment wall")
        self._await_second_boundary()
        db.run("UPDATE memories SET last_confirmed="
               "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (row["id"],))
        consolidate.run_pass()
        after_first = self._imp(row["id"])
        self.assertAlmostEqual(after_first, 0.53, places=3, msg="0.5 + 0.03, source is not corrected")
        consolidate.run_pass()
        consolidate.run_pass()
        self.assertAlmostEqual(self._imp(row["id"]), after_first, places=3,
                               msg="a signal this pass already scored must not score again")

    def test_back_to_back_passes_do_not_rescore_merge_winner(self):
        """The merge path, with nothing but a back-to-back pass between runs.

        The dedupe pass stamps `last_confirmed` on the winner *inside*
        `run_pass`, and the same call's re-scoring pass then reads that stamp.
        Resolved finer than the watermark the pass writes at its end, that stamp
        reads as newer still, so the winner is bumped here — and again on every
        following pass, straight to the cap. Run once per merge group so a single
        unlucky straddle cannot hide the regression.
        """
        for a_title, a_body in (("wombat", "wombat track count along the lower causeway"),
                               ("caracal", "caracal track count along the upper terrace"),
                               ("bilby", "bilby track count beside the shaded gully")):
            prefs.set_many({"consolidate_last_run": 0})
            a = self._raw(a_title, a_body, importance=0.90)
            b = self._raw(a_title + " count", a_body + " ok", importance=0.30)
            self.assertNotEqual(a["id"], b["id"])
            self._await_second_boundary()
            r = consolidate.run_pass()
            self.assertGreaterEqual(r["merged"], 1, r)
            after_first = self._imp(a["id"])
            self.assertAlmostEqual(after_first, 0.98, places=3,
                                   msg="0.90 + 0.05 merge fold + 0.03 scored once, here")
            consolidate.run_pass()
            consolidate.run_pass()
            self.assertAlmostEqual(self._imp(a["id"]), after_first, places=3,
                                   msg="the merge winner must be scored once, then hold")

    def test_epoch_lands_on_the_watermark_grid(self):
        """The resolution contract itself, with no wall-clock race in it.

        `_epoch` and `prefs.set_many({"consolidate_last_run": int(time.time())})`
        must resolve the same instant identically. If the parse is finer than the
        watermark, a stamp written *during* a pass compares as newer than the
        watermark that pass ends by writing — which is the double-count, and it
        does not depend on any test being lucky with timing.
        """
        now = time.time()
        stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(consolidate._epoch(stamp), int(now),
                         "signal stamps must resolve to whole seconds, the grid the "
                         "watermark is written on")

    def test_dedupe_threshold_is_strict_like_store_time(self):
        """Consolidation must not merge a pair `_duplicate_of` deliberately split.

        11 shared tokens over a 20-token union is exactly 0.55. `_duplicate_of`
        (memory.py:133) uses `> 0.55`, so it keeps this pair apart; a
        `>= 0.55` here would merge what the store refused to merge.
        """
        a = self._raw("quoll census", "estep marlin ocelot puffin quoll rook sable tapir "
                      "umbra velvet wren")
        b = self._raw("quoll notes", "estep marlin ocelot puffin quoll rook sable tapir "
                      "umbra velvet wren xerus yak zebu aardvark badger cittern dhole "
                      "egret flick")
        self.assertEqual(consolidate._jaccard(a["content"], b["content"]), 0.55,
                         "fixture must sit exactly on the threshold")
        r = consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(a["id"]),
                             "a pair the store kept apart must survive consolidation")
        self.assertIsNotNone(memory.memory_engine.get(b["id"]), r)

    def test_second_pass_does_not_rescore(self):
        """The property `run_pass` documents: an un-reconfirmed signal is scored once."""
        prefs.set_many({"consolidate_last_run": 0})
        row = self._signalled("quokka", "quokka forage census in the flooded quarry",
                              source="user-corrected:test")
        consolidate.run_pass()
        self.assertAlmostEqual(self._imp(row["id"]), 0.55, places=3,
                               msg="0.5 + 0.03 confirmed + 0.02 corrected")
        consolidate.run_pass()
        consolidate.run_pass()
        self.assertAlmostEqual(self._imp(row["id"]), 0.55, places=3,
                               msg="a signal older than the watermark must not re-score; "
                                   "unfixed this pins importance at 1.0 within a month")

    def test_reconfirmed_between_passes_is_rescored(self):
        """The watermark must not freeze the signal — a new confirmation re-arms it."""
        prefs.set_many({"consolidate_last_run": 0})
        row = self._signalled("axolotl", "axolotl telemetry survey across the quarry annexe")
        consolidate.run_pass()
        before = self._imp(row["id"])
        # Both the watermark and the stamp are second-resolution, so a
        # re-confirmation inside the same second as the pass reads as stale.
        # Cross the boundary; otherwise this test races the clock.
        time.sleep(1.05)
        db.run("UPDATE memories SET last_confirmed="
               "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (row["id"],))
        consolidate.run_pass()
        self.assertAlmostEqual(self._imp(row["id"]), round(before + 0.03, 3), places=3)

    def test_recorrection_between_passes_is_rescored(self):
        """Same watermark, other column: `source` is scored off `updated_at`."""
        prefs.set_many({"consolidate_last_run": 0})
        row = self._signalled("wombat", "wombat burrow survey along the northern ridge",
                              source="user-corrected:test")
        consolidate.run_pass()
        before = self._imp(row["id"])
        self.assertAlmostEqual(before, 0.55, places=3,
                               msg="0.5 + 0.03 confirmed + 0.02 corrected")
        time.sleep(1.05)
        memory.memory_engine.update(row["id"], content=row["content"] + " revised")
        consolidate.run_pass()
        self.assertAlmostEqual(self._imp(row["id"]), round(before + 0.02, 3), places=3)

    def test_first_pass_on_fresh_install_scores_old_signals(self):
        """consolidate_last_run=0 must not make the first pass a silent no-op."""
        prefs.set_many({"consolidate_last_run": 0})
        row = self._signalled("capybara", "capybara thermal survey along the southern weir",
                              days_ago=900)
        r = consolidate.run_pass()
        self.assertGreaterEqual(r["rescored"], 1, r)
        self.assertAlmostEqual(self._imp(row["id"]), 0.53, places=3,
                               msg="0.5 + 0.03, even though the confirmation is 900 days old")
        self.assertIsNotNone(memory.memory_engine.get(row["id"]),
                             "last_confirmed still shields it from archival")

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
