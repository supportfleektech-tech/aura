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
from pathlib import Path

os.environ.setdefault("AURA_DISABLE_SCHEDULER", "1")

_SCRATCH_PREFIXES = (
    "aura-test-",
    "aura-restore-",
    "aura-watch-",
    "aura-consol-",
    "aura-facts-",
    "aura-board-",
    "aura-workers-",
    "aura-cache-",
    "aura-sse-",
)


def _reclaim_scratch() -> None:
    root = Path(tempfile.gettempdir())
    for prefix in _SCRATCH_PREFIXES:
        for path in root.glob(f"{prefix}*"):
            shutil.rmtree(path, ignore_errors=True)


atexit.register(_reclaim_scratch)
