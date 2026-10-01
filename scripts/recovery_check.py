import hashlib
import io
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="aura-recovery-"))
        # Each case runs in its own subprocess, so this cleanup is the only thing
        # standing between a run and a pile of abandoned scratch DBs. Leaked
        # dirs filled a disk once and surfaced as unrelated "database or disk is
        # full" failures elsewhere.
        self.addCleanup(shutil.rmtree, self.scratch, True)
        for key in tuple(os.environ):
            if key.startswith(("AURA_", "OLLAMA_", "HERMES_")) or key == "LITESTREAM_REPLICA":
                os.environ.pop(key)
        os.environ.update(
            AURA_DATA_DIR=str(self.scratch),
            AURA_DB_PATH=str(self.scratch / "aura.db"),
            OLLAMA_BASE_URL="http://127.0.0.1:1",
            AURA_PRIVACY="local-first",
        )
        sys.path.insert(0, str(ROOT / "backend"))
        from app import config, db
        from app.main import app
        from fastapi.testclient import TestClient

        self.assertEqual(config.DATA_DIR, self.scratch)
        self.assertEqual(Path(config.DB_PATH), self.scratch / "aura.db")
        self.assertEqual(config.UPLOAD_DIR, self.scratch / "uploads")
        self.assertEqual(config.BACKUP_DIR, self.scratch / "backups")
        self.config, self.db = config, db
        db.init_db()
        self.addCleanup(db.reset)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(lambda: print(f"Recovery scratch retained: {self.scratch}"))

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def backup(self):
        result = self.request("POST", "/api/backup/run", json={"target": "local"})
        self.assertTrue(result["ok"], result)
        archive = self.config.BACKUP_DIR / result["file"]
        self.assertEqual(archive.stat().st_size, result["size_bytes"])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), result["sha256"])
        history = self.request("GET", "/api/backup/history")
        self.assertIn(result["file"], [row["name"] for row in history["files"]])
        return result["file"]

    def restore(self, name):
        result = self.request("POST", "/api/backup/restore", json={"file": name})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["file"], name)
        return result

    def titles(self):
        return {row["title"] for row in self.request("GET", "/api/tasks")["tasks"]}

    def test_database_restore_and_safety_copy(self):
        self.request("POST", "/api/tasks", json={"title": "Recovery before"})
        name = self.backup()
        self.request("POST", "/api/tasks", json={"title": "Recovery after"})
        self.assertEqual(self.titles(), {"Recovery before", "Recovery after"})
        result = self.restore(name)
        self.assertEqual(self.titles(), {"Recovery before"})
        safety = self.config.BACKUP_DIR / result["safety_copy"]
        self.assertTrue(safety.is_file())
        connection = sqlite3.connect(f"{safety.as_uri()}?mode=ro", uri=True)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                {row[0] for row in connection.execute("SELECT title FROM tasks")},
                {"Recovery before", "Recovery after"},
            )
        finally:
            connection.close()
        self.request("POST", "/api/tasks", json={"title": "Recovery writable"})
        self.assertEqual(self.titles(), {"Recovery before", "Recovery writable"})
        self.db.reset()
        self.assertEqual(self.titles(), {"Recovery before", "Recovery writable"})

    def test_settings_restore(self):
        self.request("PATCH", "/api/settings", json={"timezone": "UTC"})
        name = self.backup()
        changed = self.request("PATCH", "/api/settings", json={"timezone": "Europe/London"})
        self.assertEqual(changed["values"]["timezone"], "Europe/London")
        self.restore(name)
        restored = self.request("GET", "/api/settings")
        self.assertEqual(restored["values"]["timezone"], "UTC")
        self.assertEqual(restored["sources"]["timezone"], "db")

    def test_upload_recovery_preserves_existing_files(self):
        for name in ("missing.bin", "existing.bin"):
            self.request(
                "POST", "/api/files/upload",
                files={"files": (name, b"snapshot bytes\x00", "application/octet-stream")},
            )
        paths = {row["name"]: Path(row["path"]) for row in self.db.q("SELECT name, path FROM files")}
        archive = self.backup()
        paths["missing.bin"].rename(self.scratch / "retained-missing.bin")
        paths["existing.bin"].write_bytes(b"newer local bytes")
        extra = self.config.UPLOAD_DIR / "local-only.bin"
        extra.write_bytes(b"local only")
        result = self.restore(archive)
        self.assertEqual(result["uploads_restored"], 1)
        self.assertEqual(paths["missing.bin"].read_bytes(), b"snapshot bytes\x00")
        self.assertEqual(paths["existing.bin"].read_bytes(), b"newer local bytes")
        self.assertEqual(extra.read_bytes(), b"local only")
        self.assertEqual(
            {row["name"] for row in self.request("GET", "/api/files")["files"]},
            {"missing.bin", "existing.bin"},
        )
        self.assertEqual(self.restore(archive)["uploads_restored"], 0)

    def test_invalid_backups_preserve_live_state(self):
        self.request("POST", "/api/tasks", json={"title": "Keep live task"})
        sentinel = self.config.UPLOAD_DIR / "keep.bin"
        sentinel.write_bytes(b"keep live upload")
        corrupt = self.config.BACKUP_DIR / "aura-backup-corrupt.tar.gz"
        corrupt.write_bytes(b"not a gzip archive")
        empty = self.config.BACKUP_DIR / "aura-backup-empty.tar.gz"
        with tarfile.open(empty, "w:gz"):
            pass
        invalid_db = self.config.BACKUP_DIR / "aura-backup-invalid-db.tar.gz"
        content = b"not a SQLite database"
        with tarfile.open(invalid_db, "w:gz") as archive:
            member = tarfile.TarInfo("aura.db")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        for name in ("wrong-name.zip", "aura-backup-missing.tar.gz", corrupt.name, empty.name, invalid_db.name):
            with self.subTest(name=name):
                result = self.request("POST", "/api/backup/restore", json={"file": name})
                self.assertFalse(result["ok"], result)
                self.assertTrue(result["error"])
                self.assertEqual(self.titles(), {"Keep live task"})
                self.assertEqual(sentinel.read_bytes(), b"keep live upload")
                self.assertEqual(list(self.config.BACKUP_DIR.glob(".pre-restore-*.db")), [])
        self.request("POST", "/api/tasks", json={"title": "Still writable"})
        self.assertEqual(self.titles(), {"Keep live task", "Still writable"})


if __name__ == "__main__":
    cases = unittest.defaultTestLoader.getTestCaseNames(RecoveryTests)
    if len(sys.argv) == 1:
        codes = [subprocess.run([sys.executable, __file__, f"RecoveryTests.{case}"]).returncode for case in cases]
        sys.exit(int(any(codes)))
    if len(sys.argv) != 2 or sys.argv[1] not in {f"RecoveryTests.{case}" for case in cases}:
        sys.exit("Run without arguments, or specify exactly one RecoveryTests.test_* case")
    unittest.main(verbosity=2)
