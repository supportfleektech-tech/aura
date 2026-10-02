#!/usr/bin/env python3
"""AURA OS performance benchmark — offline, deterministic, stdlib-only.

Measures the hot paths against §38 engineering targets and exits non-zero
in --ci mode when any median regresses past its budget. Runs on a scratch
DB (never the live one) with the model chain forced offline (builtin
composer only), so it is reproducible on any machine with no network.

Run:  python3 scripts/benchmark.py [--ci] [--runs N]
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

# Scratch DB before importing app modules (same pattern as eval_agent.py).
_tmp = tempfile.mkdtemp(prefix="aura-bench-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "bench.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import db  # noqa: E402
from app import missions as _missions  # noqa: E402
from app import orchestrator as orch  # noqa: E402
from app.hermes import hermes  # noqa: E402
from app.inference import router as model_router  # noqa: E402
from app.memory import memory_engine  # noqa: E402

# --- determinism: chain forced offline -> builtin composer only ---
_OFFLINE = {"local_lfm": {"online": False, "note": "bench-offline", "model": ""},
            "cloud": {"configured": False, "model": "", "base": "", "provider": ""},
            "builtin": {"online": True, "note": "grounded composer"},
            "privacy": "local-first"}
model_router.probe = lambda: _OFFLINE  # type: ignore[assignment]

# Budgets (p50, seconds) — deliberately generous so CI doesn't flake, but
# tight enough to catch an O(n²) or blocking-IO regression.
BUDGETS_MS = {
    "classify": 5,
    "build_plan": 5,
    "db_write": 50,
    "memory_search": 200,
    "tool_exec": 200,
    "mission_plan": 200,
    "chat_turn_builtin": 800,
    "token_batch": 5,
}

RUNS = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 20
CI = "--ci" in sys.argv


def bench(name: str, fn) -> float:
    samples = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(samples)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    print(f"  {name:<22} p50 {med:8.1f}ms   p95 {p95:8.1f}ms   budget {BUDGETS_MS[name]}ms"
          + ("  ✓" if med <= BUDGETS_MS[name] else "  ✗ OVER BUDGET"))
    return med


def main() -> int:
    db.init_db()
    # seed a tiny but realistic dataset
    for i in range(30):
        db.run("INSERT INTO tasks (user_id,title,status,priority) VALUES (1,?,?,?)",
               (f"Bench task {i}", "inbox", "medium"))
    for i in range(30):
        memory_engine.store(f"Bench fact {i}", f"the bench fact number {i} is a stable marker",
                            "general", "semantic", "bench", 0.6, 0.5)
    print(f"AURA benchmark (runs={RUNS}, ci={CI})\n== hot paths ==")
    results: dict[str, float] = {}
    results["classify"] = bench("classify", lambda: orch.classify("plan my day tomorrow morning"))
    results["build_plan"] = bench("build_plan", lambda: orch.build_plan("plan_day", "plan my day"))
    results["db_write"] = bench("db_write", lambda: db.run(
        "INSERT INTO tasks (user_id,title,status) VALUES (1,'bench-w','inbox')"))
    results["memory_search"] = bench("memory_search", lambda: memory_engine.search(
        "bench fact", None, limit=5, embedder=model_router.embed_fn()))
    results["tool_exec"] = bench("tool_exec", lambda: hermes.execute_tool(
        "tasks.list", {"status": "inbox"}, {"domain": "general"}))
    results["mission_plan"] = bench("mission_plan", lambda: _missions.plan_goal_auto("plan my day"))

    def _turn():
        for _ in orch.run_turn("plan my day", session_id="bench-sess"):
            pass
    results["chat_turn_builtin"] = bench("chat_turn_builtin", _turn)

    def _batch():
        # A non-zero interval: at 0.0 every token takes the flush branch and the
        # `now - self._last >= self._min` comparison this budget is meant to guard
        # is never evaluated. 4ms matches the sse_batch_ms default's shape.
        b = orch.TokenBatcher(0.004)
        for t in ("a", "b", "c", "d", "e", "f", "g", "h"):
            b.add(t)
        b.flush()
    results["token_batch"] = bench("token_batch", _batch)

    print("\n== summary ==")
    over = {k: v for k, v in results.items() if v > BUDGETS_MS[k]}
    if over:
        for k, v in over.items():
            print(f"  OVER BUDGET: {k} {v:.1f}ms > {BUDGETS_MS[k]}ms")
        print("BENCHMARK FAILED")
        return 1 if CI else 0
    print("all medians within budget ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
