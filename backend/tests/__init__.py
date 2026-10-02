"""Backend test package — the guard for the `tests.test_*` invocation style.

Covers `python -m unittest tests.test_kanban`, which imports this package.
It does NOT cover `unittest discover -s tests`: discovery puts `backend/tests`
on `sys.path[0]` and imports the modules top-level, so this file never runs
there (verified — `'tests' in sys.modules` is False after `discover`).
`tests/test_env.py` carries the same guard for that style; see its docstring
for why both are needed, and why the sweep below has to be duplicated here too.

What the guard prevents: `_startup` calls `start_scheduler_loop()` on every
`TestClient(app).__enter__`, and each of those 30s daemon threads runs
`scheduler_pass` — a real consolidation pass, mission tick and job drain —
against the single shared test DB, mutating rows other modules still own
mid-assertion.
"""
import atexit
import os
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("AURA_DISABLE_SCHEDULER", "1")

# Duplicated in test_env.py on purpose: the two invocation styles import
# different files, and a scratch dir leaked by one is leaked by both. Keep both
# lists in step with the `mkdtemp` prefixes in backend/tests/*.py — a missing
# entry is an unbounded leak that no amount of waiting reclaims, since the
# sweep only globs what is listed.
#
# `aura-restore-` is deliberately absent: app/backup.py uses that prefix for an
# in-flight production restore, so sweeping it could delete a real server's
# work dir mid-extraction.
_SCRATCH_PREFIXES = (
    "aura-test-",
    "aura-watch-",
    "aura-consol-",
    "aura-facts-",
    "aura-board-",
    "aura-workers-",
    "aura-cache-",
    "aura-slash-",
    "aura-ondemand-",
)

# Two overlapping suite runs share these prefixes, so a young directory may
# belong to a run that is still going. Only reclaim what is old enough to have
# been abandoned.
_ABANDONED_AFTER_S = 3600


def _reclaim_scratch() -> None:
    root = Path(tempfile.gettempdir())
    cutoff = time.time() - _ABANDONED_AFTER_S
    for prefix in _SCRATCH_PREFIXES:
        for path in root.glob(f"{prefix}*"):
            try:
                if path.stat().st_mtime > cutoff:
                    continue
                shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue


atexit.register(_reclaim_scratch)
