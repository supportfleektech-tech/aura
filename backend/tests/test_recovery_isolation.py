import os
from pathlib import Path
import subprocess
import sys
import unittest


class RecoveryIsolationTest(unittest.TestCase):
    def run_case(self, name):
        root = Path(__file__).resolve().parents[2]
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "recovery_check.py"), f"RecoveryTests.{name}"],
            cwd=root / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_database_restore_and_safety_copy(self):
        self.run_case("test_database_restore_and_safety_copy")

    def test_settings_restore(self):
        self.run_case("test_settings_restore")

    def test_upload_recovery_preserves_existing_files(self):
        self.run_case("test_upload_recovery_preserves_existing_files")

    def test_invalid_backups_preserve_live_state(self):
        self.run_case("test_invalid_backups_preserve_live_state")
