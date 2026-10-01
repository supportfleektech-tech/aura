"""Backend test package — the guard for the `tests.test_*` invocation style.

Covers `python -m unittest tests.test_kanban`, which imports this package.
It does NOT cover `unittest discover -s tests`: discovery puts `backend/tests`
on `sys.path[0]` and imports the modules top-level, so this file never runs
there (verified — `'tests' in sys.modules` is False after `discover`).
`tests/test_env.py` carries the same guard for that style; see its docstring
for why both are needed.

What the guard prevents: `_startup` calls `start_scheduler_loop()` on every
`TestClient(app).__enter__`, and each of those 30s daemon threads runs
`scheduler_pass` — a real consolidation pass, mission tick and job drain —
against the single shared test DB, mutating rows other modules still own
mid-assertion.
"""
import os

os.environ.setdefault("AURA_DISABLE_SCHEDULER", "1")
