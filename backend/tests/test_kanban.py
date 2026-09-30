"""Kanban board API tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-board-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, missions  # noqa: E402
from app.main import app  # noqa: E402


class BoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def _mission(self, status="draft"):
        m = self.c.post("/api/missions", json={"goal": f"T-Board {status} probe"}).json()
        mid = m["id"]
        self.c.patch(f"/api/missions/{mid}", json={"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        if status == "running":
            self.c.post(f"/api/missions/{mid}/control", json={"action": "start"})
        return mid

    def test_columns_and_counts(self):
        mid = self._mission("running")
        r = self.c.get("/api/board")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([c["key"] for c in r.json()["columns"]],
                         ["backlog", "running", "awaiting", "done"])
        self.assertGreaterEqual(r.json()["counts"]["running"], 1)
        self.assertIn(mid, [m["id"] for m in r.json()["columns"][1]["missions"]])
        card = [m for m in r.json()["columns"][1]["missions"] if m["id"] == mid][0]
        for k in ("id", "goal", "status", "steps_total", "steps_done",
                  "next_run_at", "created_at", "updated_at"):
            self.assertIn(k, card)

    def test_move_start_then_pause(self):
        mid = self._mission("draft")
        r = self.c.post("/api/board/move", json={"mission_id": mid, "column": "running"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mission"]["status"], "running")
        r = self.c.post("/api/board/move", json={"mission_id": mid, "column": "backlog"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mission"]["status"], "paused")

    def test_board_cannot_fake_completion(self):
        mid = self._mission("draft")
        r = self.c.post("/api/board/move", json={"mission_id": mid, "column": "done"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mission"]["status"], "cancelled",
                         "a card dragged to done without running must cancel, never complete")

    def test_move_out_of_done_is_409(self):
        mid = self._mission("draft")
        self.c.post(f"/api/missions/{mid}/control", json={"action": "start"})
        missions.tick_missions()
        self.assertEqual(self.c.get(f"/api/missions/{mid}").json()["status"], "done")
        # No path out of done, in any direction — not just back to the backlog.
        for col in ("backlog", "running", "awaiting"):
            r = self.c.post("/api/board/move", json={"mission_id": mid, "column": col})
            self.assertEqual(r.status_code, 409, f"done -> {col} was not refused: {r.text}")
        self.assertEqual(self.c.get(f"/api/missions/{mid}").json()["status"], "done")

    def test_bad_column_and_missing_mission(self):
        mid = self._mission("draft")
        self.assertEqual(self.c.post("/api/board/move",
                                     json={"mission_id": mid, "column": "nope"}).status_code, 400)
        self.assertEqual(self.c.post("/api/board/move",
                                     json={"mission_id": 999999, "column": "running"}).status_code, 404)
        self.assertEqual(self.c.post("/api/board/move",
                                     json={"mission_id": "abc", "column": "running"}).status_code, 400)

    def test_same_column_move_is_a_noop(self):
        mid = self._mission("draft")
        r = self.c.post("/api/board/move", json={"mission_id": mid, "column": "backlog"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mission"]["status"], "draft")

    def test_board_includes_a_stepless_mission(self):
        m = self.c.post("/api/missions", json={"goal": "T-Board empty"}).json()
        r = self.c.get("/api/board")
        self.assertEqual(r.status_code, 200)
        self.assertIn(m["id"], [x["id"] for col in r.json()["columns"] for x in col["missions"]])


if __name__ == "__main__":
    unittest.main()
