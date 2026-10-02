"""Suite-wide environment guard and scratch cleanup.

Named `test_*` so `unittest discover -s tests` imports it. See the note in
`tests/__init__.py` for why the scheduler guard needs two homes; this file is
the one that covers the documented full-suite command.

Also reclaims the scratch directories the suite leaves behind. Every test
module that needs a database calls `tempfile.mkdtemp()` at import time, and two
tests create more per invocation, and none of them ever cleaned up. Each full
run leaked roughly 20 MB, which is enough to fill a disk over a few dozen runs
and surface as `sqlite3.OperationalError: database or disk is full` — a failure
that looks like a code bug and is not one. The sweep is restricted to this
suite's own prefixes under the system temp dir, so it cannot touch a real
server's data.
"""
import atexit
import os
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("AURA_DISABLE_SCHEDULER", "1")

# Only prefixes this suite uses exclusively. `aura-restore-` is deliberately
# absent: app/backup.py uses the same prefix for an in-flight production
# restore, so sweeping it could delete a real server's work dir mid-extraction.
# That test's own dir is small enough to not be worth the risk.
#
# Keep this in step with the `mkdtemp` prefixes in backend/tests/*.py — a
# missing entry is an unbounded leak that no amount of waiting will reclaim,
# because the sweep only globs what is listed here.
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
