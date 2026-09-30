# AURA OS Completion Plan — closing every open item in the 2026-09-26 spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the seven genuinely-missing subsystems from `docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md`, and fix the mission-execution bug found while auditing them.

**Architecture:** Every backend task adds a focused module under `backend/app/` plus a router under `backend/app/routes/`, following the existing split (`domain.py` is a re-export shim; `ROUTERS` in `routes/__init__.py` is the mount list). Frontend work adds components under `frontend/src/views2/` with types and fetch helpers in `frontend/src/api.ts`. No architectural change: single process, SQLite, no new runtime dependency. One new table (`worker_jobs`) is the only schema addition; everything else reuses existing tables or `prefs.SCHEMA`.

**Tech Stack:** Python 3.12 / FastAPI / SQLite (WAL, one pooled connection behind an RLock) / React + TypeScript + Vite / Vitest + jsdom / `unittest` (not pytest).

**Spec:** `docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md` — read sections 1, 2, 3, 5, 6 and the "Implementation TODO" checklist (lines 226-265). Section 4 (chat UX) and `FR-PERF-001`/`FR-PERF-002` are **already shipped**; Task 0 reconciles the record rather than reimplementing them.

---

## Global Constraints

These apply to every task. They come from `AGENTS.md` and the spec; a task's requirements implicitly include this whole section.

**Test commands.** Run backend and frontend suites **sequentially**, never concurrently — they saturate the box and heavy component renders hit their timeout.

```bash
# Backend suite (the real gate). Must be fully green.
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests

# A single test
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_aura.AuraTest.test_name
```

- Backend tests use `unittest`, never pytest. `AURA_DATA_DIR` isolates uploads/backups; setting `AURA_DB_PATH` alone is insufficient.
- `OLLAMA_BASE_URL=http://127.0.0.1:1` forces the hashed-embedding / offline path the suite asserts on.
- Frontend has no lint/format step. CI runs `tsc --noEmit` + `build`; backend CI runs `compileall`.

**Invariants that must not regress.** Each is a previously-fixed bug; re-breaking one fails the task.

- `ModelRouter.chain()` is the privacy boundary: `local-first` must never contain `"cloud"` and must not construct a cloud client.
- Cloud grounding is redacted via `filter_cloud_memories` **before** cloud messages are built.
- `run_turn` is a **generator of SSE strings** (`event: …\ndata: …`). `main.py` and `vloop.py` consume it. It closes the upstream LLM stream in a `finally`.
- Response shapes are a three-way contract: `frontend/src/api.ts` types, `orchestrator`'s memory harvest, and `scripts/e2e_check.py`. When you change a response, grep the old key across all three.
- Every registered route must be reachable and match its typed client. A handler with no decorator 404s silently.
- Hermes tool adapters: `execute_tool` calls `tool.fn(args_dict, ctx)`. Register an adapter, never a `_lazy` pointer at a function whose real signature differs — `_lazy` passes the whole args dict as one positional parameter.
- `prefs.get(key)` takes exactly one argument; defaults live in `prefs.SCHEMA`. A key absent from `SCHEMA` raises `KeyError` at runtime.
- Every new R0/R1 tool must satisfy `hermes.execute_tool(name, {}, {})` returning `ok=True`.
- `_next_run(trigger, kind)` returns `None` for every non-`schedule` kind.
- Plugins are discovered from `Path(__file__).parent / "plugins"`, never a CWD-relative path.
- After touching a module, re-run the unbound-name AST check (it has caught `missions.py` and `orchestrator.py` misses no test covered).

**Schema and version rules.**

- Schema changes go in `backend/app/schema.sql`. A new column on an existing table also needs a guarded `ALTER` in `db.init_db()`.
- Destructive drops need `[allow-destructive-schema]` in the commit message. This plan adds no drops.
- `venv/bin/python scripts/migration_check.py --self-test` after schema edits.
- Version source is `backend/app/config.py:APP_VERSION`. Bump it once, in Task 8, and sync `frontend/package.json`, `frontend/src/App.tsx`, E2E text, `docs/CHANGELOG.md`, `package-lock.json`.

**Security rules.**

- No new entry in `backend/requirements.txt`. `httpx` is already a dependency; the cache is in-process `functools`, not Redis.
- `OriginGuardMiddleware` already blocks cross-site mutations; new mutating routes are covered. Do not add a second gate.
- Single-user, no login. Do not add auth.
- Before declaring done: `venv/bin/python scripts/prod_check.py` (needs VAPID keys) and `venv/bin/python scripts/e2e_check.py` (needs a live backend on :8000 and a built frontend).

**Scope note — deliberately NOT in this plan** (from the spec's "Explicitly NOT recommended" and the owner's standing decisions):

- No authentication or per-user scoping. `docs/ROADMAP.md` P0 item 1 is deferred by the owner.
- No Redis. `FR-PERF-003` says "Redis-compatible cache"; an in-process LRU with the same semantics satisfies it for a single-process app at zero dependency cost. Task 7 documents this in the code.
- No microservices, no Postgres, no vector-DB-first memory.

---

## File Structure

**Backend modules** — one responsibility each:

| File | Responsibility |
|---|---|
| `backend/app/consolidate.py` | Memory consolidation: dedupe, importance re-scoring, low-signal archival. |
| `backend/app/facts.py` | Extract durable facts from Hermes **tool results** (chat text is already covered by `memory.observe`). |
| `backend/app/slash.py` | Slash command catalog, parser, executor. Deterministic handlers, never prompts. |
| `backend/app/workers.py` | Job queue, retry/backoff, dead-letter, and the scheduler pass. Owns `worker_jobs`. |
| `backend/app/cache.py` | TTL + LRU primitives. |
| `backend/app/routes/consolidation.py` | `consol_r`: run a pass, report the last one. |
| `backend/app/routes/kanban.py` | `board_r`: mission columns and legal moves. |
| `backend/app/routes/slash.py` | `slash_r`: catalog, execute, custom-command CRUD. |
| `backend/app/routes/workers.py` | `worker_r`: queue stats, dead letters, manual drain. |

**Backend modifications:**

- `backend/app/hermes.py` — `start_scheduler_loop` delegates to `workers.scheduler_pass` (**the mission-execution fix**, Task 4).
- `backend/app/orchestrator.py` — `_harvest` gains a `domain` parameter and a fact-extraction branch (Task 2).
- `backend/app/main.py` — `chat_stream` short-circuits a leading `/` (Task 5).
- `backend/app/prefs.py` — new `SCHEMA` keys, each task's own.
- `backend/app/schema.sql` + `backend/app/db.py` — `worker_jobs` table and `init_db` index guard (Task 4).
- `backend/app/routes/__init__.py` + `backend/app/domain.py` — register routers; `domain.py` must re-export every router name because Hermes resolves through `app.domain`.

**Frontend:**

| File | Responsibility |
|---|---|
| `frontend/src/slash.ts` | Pure command matcher + catalog normaliser. No React, so it is unit-testable. |
| `frontend/src/CommandPalette.tsx` | The `/`-triggered palette: filter, arrow keys, arg hints. |
| `frontend/src/views2/kanban.tsx` | Mission board. |
| `frontend/src/views2/commands.tsx` | Settings cheat sheet + custom-command CRUD. |
| `frontend/src/views2/perf.tsx` | Queue depth, throughput, error rate, dead letters. |
| `frontend/src/ui.tsx` | `Composer` gains palette wiring; `insertEmoji` gains cursor-position insertion. |
| `frontend/src/api.ts` | Types + fetch helpers. Already exports `get`/`post`/`patch`/`put`/`del` (lines 20-24) — use `del`, do not add one. |
| `frontend/src/App.tsx`, `frontend/src/store.tsx` | New `View` variants and lazy imports. |

**Verified facts you can rely on** (read off the source, not assumed):

- `useFetch` lives in `frontend/src/views1.tsx:11`, **not** `ui.tsx`. Import it from `"../views1"`.
- `Field` lives in `frontend/src/views1.tsx` too (`views2/memory.tsx:5` imports it from there).
- `Empty`, `Panel`, `Btn`, `Pill`, `Row`, `Icon` are exported from `frontend/src/ui.tsx`.
- `list_tasks()` returns `{"tasks": [...]}` — a dict, not a list.
- `create_task(t: TaskIn)` takes a **Pydantic model**, not a dict. `_wrap_model` exists in `hermes.py:34` for this.
- `_update_task_impl(task_id=None, id=None, **fields)` — pass `task_id=` as a keyword.
- `hermes.fire_event(a: dict, fire_id: str | None = None)` — takes the automation **row**, not a trigger.
- `ollama_sync.list_models()` returns `{reachable, base_url, models, error, refreshed}`.
- `router.ollama.chat(messages, model=None, stream_cb=None, timeout=120.0, purpose="chat", images=None)`.
- `backup.run_backup(target="local")`, `health.system_status()` — both plain functions.

---

## Task 0: Reconcile the spec record (docs only)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md` — the "Implementation TODO" section (lines 226-265) and "Open Questions" (line 287)

**Interfaces:**
- Consumes: nothing. Produces: nothing. This task changes no code and no interface.

Auditing the spec against the code found eight items already shipped but unticked. Leaving them unticked means the next reader re-implements working features.

- [ ] **Step 1: Tick the shipped items**

In the "Implementation TODO" section, change these to `- [x]`, each with a note of where it lives:

```
### Backend
- [x] Optimize database indexes — 12 `CREATE INDEX` in `schema.sql`
- [x] Performance benchmarks — `scripts/benchmark.py`

### Frontend
- [x] Fix ChatThread container (flex, min-height: 0) — `frontend/src/ui.tsx:527`
- [x] Add thinking/final message styling — `ui.tsx:555-572`, `backend/app/orchestrator.py:1263`
- [x] Implement auto-scroll with "new messages" indicator — `ui.tsx:487-513` and `ui.tsx:585`
- [x] Add emoji picker component — `ui.tsx:650-728`
```

Insert this line directly under the `### Backend` and `### Frontend` headings, before any remaining `- [ ]`:

```
> Closed by `docs/superpowers/plans/2026-09-30-aura-completion.md`. Plan task in
> parentheses: memory consolidation (1), fact extraction (2), Kanban endpoints (3),
> slash command router (5), worker pool (4), caching layer (6), SSE batching (6).
```

Rewrite the remaining unchecked lines to carry their task number:

```
### Backend
- [ ] Add memory consolidation job — plan Task 1
- [ ] Add fact extraction pipeline — plan Task 2
- [ ] Implement Kanban mission status endpoints — plan Task 3
- [ ] Add slash command router — plan Task 5
- [ ] Implement worker pool with queue — plan Task 4
- [ ] Add scheduled job runner — plan Task 4 (the scheduler exists; the mission tick was never wired into it)
- [ ] Add caching layer — plan Task 6
- [ ] Optimize SSE streaming — plan Task 6

### Frontend
- [ ] Implement slash command palette in Composer — plan Task 5
- [ ] Create Kanban board component with drag-drop — plan Task 3
- [ ] Create Commands cheat sheet in Settings — plan Task 5
- [ ] Add performance monitoring — plan Task 7

### Testing
- [ ] Unit tests for memory consolidation — plan Task 1
- [ ] Unit tests for command parser — plan Task 5
- [ ] Integration tests for Kanban API — plan Task 3
- [ ] E2E tests for slash commands — plan Task 5
- [x] E2E tests for chat UX (auto-scroll, thinking style) — `frontend/src/__tests__/ui.test.tsx`; re-verified in Task 8
- [ ] Load tests for worker pool — plan Task 4
- [ ] Performance benchmarks — plan Task 6 extends `scripts/benchmark.py`
```

Delete the line `### Frontend` / `- [ ] Add mission card modal with real-time updates`. The existing `MissionCard` at `frontend/src/views2/automations.tsx:30` already renders per-step status, and Task 4 adds live queue state to the perf panel; a separate modal is a duplicate surface. Replace that one line with:

```
- [x] Add mission card modal with real-time updates — superseded: `views2/automations.tsx:30` shows per-step state; plan Task 7's perf panel shows live queue state
```

- [ ] **Step 2: Record the mission-execution bug in "Open Questions"**

Append to the spec's `## Open Questions` section:

```markdown
### Missions never advanced in production (found 2026-09-30)

`missions.tick_missions()` and `missions.tick_schedules()` had no call sites
outside `backend/tests/`. `hermes.start_scheduler_loop` only called
`hermes.tick_automations()`, so a mission started from the UI or chat sat at
`status='running'` with every step `pending`, indefinitely. The suite passed
because the tests called `tick_missions()` by hand. Closed by Task 4 of
`docs/superpowers/plans/2026-09-30-aura-completion.md`.
```

- [ ] **Step 3: Verify nothing broke**

```bash
git diff --stat
```

Expected: one file changed, the spec `.md`. No code touched.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md
git commit -m "docs: reconcile 2026-09-26 spec TODO against shipped code

Eight items were already implemented but unticked, and the mission tick was
never wired into the scheduler. Records both so the next reader does not
re-implement working features or miss a live bug."
```

---

## Task 1: Memory consolidation (FR-MEM-003)

**Files:**
- Create: `backend/app/consolidate.py`
- Create: `backend/app/routes/consolidation.py`
- Modify: `backend/app/prefs.py` (two `SCHEMA` keys + two `public_view` pops)
- Modify: `backend/app/routes/__init__.py`, `backend/app/domain.py` (register `consol_r`)
- Test: `backend/tests/test_consolidation.py` (new)

**Interfaces:**
- Consumes: `db.q/qone/run`, `db.jdump/jload`, `prefs.get/set_many`, `memory.memory_engine`, `memory._tokens`.
- Produces:
  - `consolidate.run_pass(limit: int = 500) -> dict` → `{"scanned": int, "merged": int, "archived": int, "rescored": int, "duration_ms": int}`
  - `consolidate.should_run(now_ts: float | None = None) -> bool`
  - `consolidate.find_duplicate_groups(threshold: float = 0.55) -> list[list[int]]`
  - `GET /api/consolidation` → `{"enabled": bool, "due": bool, "last_run": dict | None}`
  - `POST /api/consolidation/run` → the `run_pass` dict

**Behaviour to implement (FR-MEM-003):**

1. **Dedupe.** Cluster live memories by pairwise token Jaccard ≥ 0.55 — the same threshold `MemoryEngine._duplicate_of` already uses, so a consolidation pass and a store-time dedupe agree on what "the same memory" means. Within a cluster keep the highest `importance`, tie-broken by lowest `id`. Point every loser's `supersedes_id` at the winner and **soft-delete** the losers. Fold importance into the winner as `MIN(1.0, winner + 0.05 × losers)` and stamp `last_confirmed`.
2. **Importance re-scoring.** Recompute from signals that exist as columns: `+0.03` when `last_confirmed` is set, `+0.02` when `source LIKE 'user-corrected:%'`. Do **not** invent an access-counter column — that is a schema change to buy a heuristic, and the docstring must say so.
3. **Archive.** Soft-delete live memories where `importance <= 0.2` **and** `confidence <= 0.4` **and** `last_confirmed IS NULL` **and** `sensitivity = 'normal'` **and** `created_at` older than 30 days. The `sensitivity` guard is load-bearing: a `private`/`sensitive` memory is a deliberate entry, so a low auto-score is least trustworthy about it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_consolidation.py`. The import preamble is mandatory — `AURA_DB_PATH` must be set **before** importing `app.*`, exactly as `backend/tests/test_aura.py:1-13` does:

```python
"""Memory consolidation tests."""
import os
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="aura-consol-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

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

    def test_duplicates_merge_into_highest_importance(self):
        a = self._mk("standup", "standup is at nine every morning", importance=0.9)
        b = self._mk("standup time", "standup is at nine every morning ok", importance=0.3)
        r = consolidate.run_pass()
        self.assertGreaterEqual(r["merged"], 1, r)
        self.assertIsNotNone(memory.memory_engine.get(b["id"]),
                             "loser must be soft-deleted, not hard-deleted")
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

    def test_fresh_low_signal_memory_is_not_archived(self):
        m = self._mk("fresh", "a brand new low signal note here", importance=0.05, confidence=0.2)
        consolidate.run_pass()
        self.assertIsNotNone(memory.memory_engine.get(m["id"]),
                             "the 30-day age guard must protect a new memory")

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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_consolidation
```

Expected: `ModuleNotFoundError: No module named 'app.consolidate'`

- [ ] **Step 3: Add the two pref keys**

In `backend/app/prefs.py` `SCHEMA`, next to `"retention_last_run"` (line 107):

```python
    "consolidate_enabled": (True, "bool", None),
    "consolidate_last_run": (0, "int", (0, 2**31)),
```

Then add `"consolidate_last_run"` to **both** `pop` calls in `public_view()` (lines 256-257), alongside `retention_last_run`:

```python
    values.pop("retention_last_run", None)
    sources.pop("retention_last_run", None)
    values.pop("consolidate_last_run", None)
    sources.pop("consolidate_last_run", None)
```

This is not optional: `scripts/e2e_check.py:593` (`_t_settings_shape`) compares the key set, so an unpopulated bookkeeping key breaks the CI gate.

- [ ] **Step 4: Write `backend/app/consolidate.py`**

```python
"""Memory consolidation (spec §1, FR-MEM-003).

Three passes: dedupe, importance re-scoring, and archival of low-signal rows.
Every write is a soft delete (`deleted_at`) or a `supersedes_id` pointer —
AURA has no login, so there is no way to prove a hard delete was intended.

Importance re-scoring uses only signals that already exist as columns: a
re-confirmed memory (`last_confirmed`) and a user-corrected memory
(`source LIKE 'user-corrected:%'`). There is deliberately no access counter;
adding one would be a schema change to buy a heuristic.
"""
from __future__ import annotations

import time

from . import db, prefs
from .memory import _tokens

# Same threshold MemoryEngine._duplicate_of uses, so a consolidation pass and a
# store-time dedupe agree on what "the same memory" means.
DUP_THRESHOLD = 0.55
ARCHIVE_IMPORTANCE = 0.2
ARCHIVE_CONFIDENCE = 0.4
ARCHIVE_MIN_AGE_DAYS = 30


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_duplicate_groups(threshold: float = DUP_THRESHOLD, limit: int = 500) -> list[list[int]]:
    """Cluster live memories by pairwise Jaccard >= threshold. Returns id groups."""
    rows = db.q("SELECT id, content FROM memories WHERE user_id=1 AND deleted_at IS NULL "
                "ORDER BY id DESC LIMIT ?", (max(1, min(limit, 2000)),))
    groups: list[list[int]] = []
    claimed: set[int] = set()
    for i, r in enumerate(rows):
        if r["id"] in claimed:
            continue
        cluster = [r["id"]]
        for other in rows[i + 1:]:
            if other["id"] in claimed:
                continue
            if _jaccard(r.get("content") or "", other.get("content") or "") >= threshold:
                cluster.append(other["id"])
                claimed.add(other["id"])
        if len(cluster) > 1:
            claimed.add(r["id"])
            groups.append(cluster)
    return groups


def run_pass(limit: int = 500) -> dict:
    """One consolidation pass. Idempotent: every statement is scoped by id."""
    t0 = time.time()
    merged = archived = rescored = 0

    for group in find_duplicate_groups(limit=limit):
        rows = db.q("SELECT * FROM memories WHERE id IN (%s) AND deleted_at IS NULL"
                    % ",".join("?" * len(group)), tuple(group))
        if len(rows) < 2:
            continue
        winner = sorted(rows, key=lambda r: (-float(r.get("importance") or 0), r["id"]))[0]
        losers = [r for r in rows if r["id"] != winner["id"]]
        new_imp = min(1.0, float(winner.get("importance") or 0) + 0.05 * len(losers))
        db.run("UPDATE memories SET importance=?, "
               "last_confirmed=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
               (round(new_imp, 3), winner["id"]))
        for l in losers:
            db.run("UPDATE memories SET supersedes_id=?, "
                   "deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                   (winner["id"], l["id"]))
            merged += 1

    for r in db.q("SELECT id, importance, last_confirmed, source FROM memories "
                  "WHERE user_id=1 AND deleted_at IS NULL"):
        bump = ((0.03 if r.get("last_confirmed") else 0.0)
                + (0.02 if (r.get("source") or "").startswith("user-corrected:") else 0.0))
        if bump <= 0:
            continue
        db.run("UPDATE memories SET importance=? WHERE id=?",
               (round(min(1.0, float(r.get("importance") or 0) + bump), 3), r["id"]))
        rescored += 1

    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - ARCHIVE_MIN_AGE_DAYS * 86400))
    victims = db.q(
        "SELECT id FROM memories WHERE user_id=1 AND deleted_at IS NULL "
        "AND importance <= ? AND confidence <= ? AND last_confirmed IS NULL "
        "AND sensitivity = 'normal' AND created_at < ?",
        (ARCHIVE_IMPORTANCE, ARCHIVE_CONFIDENCE, cutoff))
    for v in victims:
        db.run("UPDATE memories SET deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
               "WHERE id=?", (v["id"],))
        archived += 1

    scanned = (db.qone("SELECT COUNT(*) c FROM memories WHERE user_id=1 "
                       "AND deleted_at IS NULL") or {}).get("c", 0)
    out = {"scanned": int(scanned), "merged": merged, "archived": archived,
           "rescored": rescored, "duration_ms": int((time.time() - t0) * 1000)}
    db.log_activity("memory",
                    f"Consolidation pass: {merged} merged, {archived} archived",
                    f"{rescored} re-scored in {out['duration_ms']}ms", "general")
    return out


def should_run(now_ts: float | None = None) -> bool:
    """True at most once per 24h, and only when the pref is on."""
    try:
        if not prefs.get("consolidate_enabled"):
            return False
    except Exception:
        return False
    now = now_ts if now_ts is not None else time.time()
    try:
        last = float(prefs.get("consolidate_last_run") or 0)
    except (TypeError, ValueError):
        last = 0.0
    return (now - last) >= 86400
```

- [ ] **Step 5: Write `backend/app/routes/consolidation.py`**

```python
"""Consolidation router — run a pass and report the last one."""
from __future__ import annotations

import time

from fastapi import APIRouter

from .. import consolidate, db, prefs

consol_r = APIRouter(prefix="/consolidation", tags=["consolidation"])


@consol_r.get("")
def status():
    last = db.qone("SELECT * FROM activity WHERE kind='memory' "
                   "AND title LIKE 'Consolidation pass%' ORDER BY id DESC LIMIT 1")
    return {"enabled": bool(prefs.get("consolidate_enabled")),
            "due": consolidate.should_run(),
            "last_run": dict(last) if last else None}


@consol_r.post("/run")
def run_now():
    r = consolidate.run_pass()
    prefs.set_many({"consolidate_last_run": int(time.time())})
    return r
```

- [ ] **Step 6: Register the router**

`backend/app/routes/__init__.py`: add `from .consolidation import consol_r` after the missions import, and append `consol_r` to the `ROUTERS` list.

`backend/app/domain.py`: add `consol_r` to the `from .routes import (...)` block. Hermes resolves through `app.domain`, and `main.py` imports `ROUTERS` from it — a router missing here is a route that never mounts.

- [ ] **Step 7: Run the new tests, then the full suite**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_consolidation
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
```

Expected: 6 new tests pass; suite is 344 + 6 = 350, `OK`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/consolidate.py backend/app/routes/consolidation.py backend/app/prefs.py backend/app/routes/__init__.py backend/app/domain.py backend/tests/test_consolidation.py
git commit -m "feat: memory consolidation pass (spec FR-MEM-003)

Dedupe clusters memory at the same Jaccard threshold the store path already
uses, re-scores importance from last_confirmed and user-corrected source, and
archives low-signal rows.

Sensitive and private memories are never archived: a low auto-score is least
trustworthy about the user's deliberate entries. Every write is a soft delete
or a supersedes_id pointer — there is no login, so no way to prove a hard
delete was intended.

consolidate_last_run is popped from public_view, because the settings shape
check in e2e_check.py compares the key set."
```

---

## Task 2: Fact extraction from tool results (FR-MEM-005)

**Files:**
- Create: `backend/app/facts.py`
- Modify: `backend/app/orchestrator.py` (`_harvest` signature + fact branch; two call sites)
- Modify: `frontend/src/api.ts` (`onFacts`), `frontend/src/store.tsx` (handler)
- Test: `backend/tests/test_facts.py` (new)

**Interfaces:**
- Consumes: `memory.memory_engine.store`.
- Produces:
  - `facts.extract(tool: str, data: Any) -> list[dict]` → candidates with keys `{"title", "content", "domain", "mtype", "confidence", "importance"}`
  - `facts.harvest(tool: str, data: Any, domain: str = "general") -> list[dict]` → what was persisted
  - `_harvest(tool, data, tool_results, memories, entities, domain: str = "general")` — **new trailing parameter with a default**, so the two existing call sites keep working until you update them

**Read this first:** `backend/app/orchestrator.py:1152` — `_harvest` already runs after every tool step and returns `(event_name, payload)` pairs for SSE. Add the fact harvest **inside** `_harvest`; do not add a second loop over the plan. It does not receive the turn's domain today, which is why this task adds the parameter rather than inventing a magic key in `tool_results`.

**Behaviour.** Facts come from *tool output*, not chat — `memory_engine.observe` already covers chat text (`orchestrator.py:1636`). Promote only high-signal structured fields:

- `client` / `clients[]` with a non-empty `email` or `phone` → `semantic`, domain `clients`, confidence 0.85, importance 0.7
- `project` / `projects[]` with a name → `semantic`, domain `career`, confidence 0.8, importance 0.6
- `task` / `tasks[]` **with a `due_at`** → `episodic`, domain `general`, confidence 0.7, importance 0.55. A task with no due date is a task, not a durable fact — skip it.
- `memory.search` and every other tool → nothing.

Cap at 3 candidates per tool result; require ≥ 12 characters of content. `MemoryEngine.store` dedupes on Jaccard and re-confirms rather than inserting, so a repeated call is cheap and idempotent.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_facts.py` with the same import preamble as Task 1:

```python
"""Tool-result fact extraction tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-facts-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from app import db, facts  # noqa: E402


class FactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_client_output_yields_contact_fact(self):
        out = facts.extract("clients.create", {"client": {
            "id": 1, "name": "Amina Yusuf", "org": "Zebra Foods",
            "email": "amina@zebra.example"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "clients")
        self.assertEqual(out[0]["mtype"], "semantic")
        self.assertIn("amina@zebra.example", out[0]["content"])

    def test_client_without_contact_yields_nothing(self):
        self.assertEqual(facts.extract("clients.create", {"client": {"id": 1, "name": "No Contact"}}), [])

    def test_task_without_due_date_is_not_a_fact(self):
        self.assertEqual(facts.extract("tasks.create", {"task": {"id": 1, "title": "T-Facts ping"}}), [])

    def test_task_with_due_date_is_episodic(self):
        out = facts.extract("tasks.create", {"task": {
            "id": 1, "title": "T-Facts send deck", "due_at": "2026-10-01T09:00:00Z"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["mtype"], "episodic")
        self.assertIn("2026-10-01", out[0]["content"])

    def test_project_yields_career_fact(self):
        out = facts.extract("projects.create", {"project": {"id": 1, "name": "Kopilot", "status": "active"}})
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["domain"], "career")

    def test_search_output_yields_nothing(self):
        self.assertEqual(facts.extract("memory.search", {"results": [{"id": 1, "title": "x"}]}), [])

    def test_non_dict_result_yields_nothing(self):
        self.assertEqual(facts.extract("system.status", "a string"), [])
        self.assertEqual(facts.extract("system.status", None), [])

    def test_caps_at_three(self):
        data = {"clients": [{"name": f"C{i}", "email": f"c{i}@x.example"} for i in range(9)]}
        self.assertLessEqual(len(facts.extract("clients.list", data)), 3)

    def test_harvest_persists_and_second_call_dedupes(self):
        data = {"client": {"id": 9, "name": "Bo Ade", "email": "bo@ade.example"}}
        first = facts.harvest("clients.create", data, "clients")
        self.assertEqual(len(first), 1, first)
        self.assertIn("bo@ade.example", first[0]["content"])
        second = facts.harvest("clients.create", data, "clients")
        self.assertTrue(second[0].get("deduped"), second)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_facts
```

Expected: `ModuleNotFoundError: No module named 'app.facts'`

- [ ] **Step 3: Write `backend/app/facts.py`**

```python
"""Durable facts from Hermes tool results (spec §1, FR-MEM-005).

`MemoryEngine.observe` already extracts facts from *chat text*. This handles the
other half: facts that only exist in tool output — an email address returned by
`clients.create`, a due date returned by `tasks.create`.

Only high-signal structured fields are promoted. A tool's free-text output is
not mined for sentences: that is `observe`'s job, and doing both would
double-count. Every candidate goes through `MemoryEngine.store`, which dedupes,
so a repeated call is cheap and idempotent.
"""
from __future__ import annotations

from typing import Any

from .memory import memory_engine

MAX_PER_RESULT = 3
MIN_CONTENT_CHARS = 12


def _client_fact(c: dict, domain: str) -> dict | None:
    contact = " ".join(x for x in (c.get("email") or "", c.get("phone") or "") if x).strip()
    if not contact:
        return None
    name = c.get("name") or "Unknown"
    org = f" ({c.get('org')})" if c.get("org") else ""
    return {"title": f"Contact: {name}"[:72], "content": f"{name}{org} — {contact}",
            "domain": domain, "mtype": "semantic", "confidence": 0.85, "importance": 0.7}


def _project_fact(p: dict, domain: str) -> dict | None:
    name = str(p.get("name") or p.get("title") or "").strip()
    if not name:
        return None
    return {"title": f"Project: {name}"[:72], "content": f"{name} is {p.get('status') or 'active'}",
            "domain": domain, "mtype": "semantic", "confidence": 0.8, "importance": 0.6}


def _task_fact(t: dict, domain: str) -> dict | None:
    title = str(t.get("title") or "").strip()
    due = str(t.get("due_at") or "").strip()
    if not title or not due:
        return None
    return {"title": f"Due: {title}"[:72], "content": f"{title} is due {due[:10]}",
            "domain": domain, "mtype": "episodic", "confidence": 0.7, "importance": 0.55}


# Singular key -> (extractor, domain). Mirrors the shape a create-tool returns.
_SINGULAR = (("client", _client_fact, "clients"),
             ("project", _project_fact, "career"),
             ("task", _task_fact, "general"))
# Plural key -> (extractor, domain). Mirrors a list-tool.
_PLURAL = (("clients", _client_fact, "clients"),
           ("projects", _project_fact, "career"),
           ("tasks", _task_fact, "general"))


def extract(tool: str, data: Any) -> list[dict]:
    """Candidate facts from one tool result. At most MAX_PER_RESULT."""
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    for key, fn, dom in _SINGULAR:
        v = data.get(key)
        if isinstance(v, dict):
            f = fn(v, dom)
            if f:
                out.append(f)
    for key, fn, dom in _PLURAL:
        v = data.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    f = fn(item, dom)
                    if f:
                        out.append(f)
    clean = [f for f in out if len(f["content"].strip()) >= MIN_CONTENT_CHARS]
    return clean[:MAX_PER_RESULT]


def harvest(tool: str, data: Any, domain: str = "general") -> list[dict]:
    """Extract, store, and return what was persisted. Never raises."""
    stored = []
    for f in extract(tool, data):
        try:
            stored.append(memory_engine.store(
                f["title"], f["content"], f["domain"], f["mtype"],
                "tool:" + tool, f["confidence"], f["importance"]))
        except Exception:
            continue
    return stored
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_facts
```

Expected: 9 tests pass.

- [ ] **Step 5: Wire it into `_harvest`**

Read `backend/app/orchestrator.py:1152-1226` before editing. Add the parameter:

```python
def _harvest(tool, data, tool_results, memories, entities, domain: str = "general"):
```

At the end of the function, just before its final `return`, add:

```python
    try:
        from . import facts as _facts
        _stored = _facts.harvest(tool, data, domain)
        if _stored:
            yield ("facts", {"stored": [{"id": s.get("id"), "title": s.get("title")}
                                        for s in _stored]})
    except Exception:
        pass
```

Then update both call sites — `orchestrator.py:1322` and `:1383` — which currently read:

```python
                for ev_name, payload in _harvest(
                    tool, data, tool_results, memories, entities
                ):
```

and

```python
            for ev_name, payload in _harvest(
                tool, data, tool_results, memories, entities
            ):
```

Change both to pass `domain` as the sixth argument. `domain` is in scope in `run_turn` (assigned near the top). Confirm with a grep before you finish:

```bash
cd backend && grep -n "_harvest(" app/orchestrator.py
```

Expected: one `def` line and exactly two call sites, both with six arguments.

- [ ] **Step 6: Handle the new SSE event in the frontend**

`frontend/src/api.ts` — add to the `ChatEvents` interface:

```ts
  onFacts?: (f: { stored: { id: number; title: string }[] }) => void;
```

and in `chatStream`'s dispatch chain, immediately after the existing `memory` branch:

```ts
          else if (curEvent === "facts") ev.onFacts?.(d);
```

`frontend/src/store.tsx` — in `send` (line 228), next to the existing `onMemory` handler:

```ts
        onFacts: (f) => { if (f.stored?.length) toast(`Noted: ${f.stored[0].title.slice(0, 60)}`, "info"); },
```

- [ ] **Step 7: Run both suites**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: backend 350 + 9 = 359, `OK`. Frontend 175 passing, `tsc` clean. Confirm `test_journey_ask` and the SSE tests still pass — the `_harvest` signature change touches the hot path.

- [ ] **Step 8: Commit**

```bash
git add backend/app/facts.py backend/app/orchestrator.py backend/tests/test_facts.py frontend/src/api.ts frontend/src/store.tsx
git commit -m "feat: extract durable facts from tool results (spec FR-MEM-005)

memory.observe already covers chat text; this covers the other half — contacts
from clients, statuses from projects, due dates from tasks. A task with no due
date is a task, not a durable fact, so it is skipped.

Only structured fields are promoted, so a tool's prose is not mined twice.
_harvest gains a domain parameter rather than a magic tool_results key, and the
new facts event rides the same SSE path as the existing memory event."
```

---

## Task 3: Kanban mission board (spec §2, FR-P1-002)

**Files:**
- Create: `backend/app/routes/kanban.py`
- Modify: `backend/app/routes/__init__.py`, `backend/app/domain.py` (register `board_r`)
- Modify: `frontend/src/api.ts`, `frontend/src/store.tsx` (add `"board"` to `View`), `frontend/src/App.tsx` (lazy import + render + nav), `frontend/src/theme.css`
- Create: `frontend/src/views2/kanban.tsx`
- Test: `backend/tests/test_kanban.py`, `frontend/src/__tests__/kanban.test.tsx`

**Interfaces:**
- Consumes: `missions.list_missions`, `missions._row`, `missions.set_status`.
- Produces:
  - `GET /api/board` → `{"columns": [{"key", "label", "missions": [BoardMission]}], "counts": {key: int}}`
  - `POST /api/board/move` body `{"mission_id": int, "column": str}` → `{"ok": true, "mission": BoardMission}`; 400 unknown column, 400 non-int `mission_id`, 404 unknown mission, 409 illegal move
  - `BoardMission` = `{"id", "goal", "status", "steps_total", "steps_done", "next_run_at", "created_at", "updated_at"}`

**Column mapping**, derived from the existing `missions.status` values (`backend/app/schema.sql:535`, documented as `draft|running|awaiting|paused|done|failed|cancelled`). Do not invent new statuses:

| Column key | `missions.status` values |
|---|---|
| `backlog` | `draft`, `paused` |
| `running` | `running` |
| `awaiting` | `awaiting` |
| `done` | `done`, `failed`, `cancelled` |

**Legal moves.** Everything else is 409:

| From | To | `set_status` action |
|---|---|---|
| `backlog` | `running` | `start` |
| `backlog` | `done` | `cancel` |
| `running` | `backlog` | `pause` |
| `running` | `done` | `cancel` |
| `awaiting` | `backlog` | `pause` |
| `awaiting` | `done` | `cancel` |

No move **out of** `done`. Two deliberate constraints: the only route to `done` is mission execution actually completing, and a card dragged out of the backlog without starting is **cancelled**, not completed. Otherwise the board would be a way to fabricate success and to route around approvals.

- [ ] **Step 1: Write the failing backend test**

Create `backend/tests/test_kanban.py`:

```python
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
        r = self.c.post("/api/board/move", json={"mission_id": mid, "column": "backlog"})
        self.assertEqual(r.status_code, 409, r.text)

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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_kanban
```

Expected: failures with `404` — no `/api/board` route.

- [ ] **Step 3: Write `backend/app/routes/kanban.py`**

```python
"""Kanban board router — a drag-drop view over mission status.

The board is a *view*, never a second source of truth: every move goes through
`missions.set_status`, so it cannot bypass the approval flow, and no path sets
`status='done'` directly. Dragging an unstarted card to the done column cancels
it, because the only legitimate route to `done` is a mission actually finishing.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import missions as _m

board_r = APIRouter(prefix="/board", tags=["missions"])

COLUMNS = [
    ("backlog", "Backlog", ("draft", "paused")),
    ("running", "Running", ("running",)),
    ("awaiting", "Needs you", ("awaiting",)),
    ("done", "Finished", ("done", "failed", "cancelled")),
]
_COLUMN_KEYS = {k for k, _, _ in COLUMNS}
_STATUS_TO_COLUMN = {s: k for k, _, sts in COLUMNS for s in sts}

# (from_column, to_column) -> missions.set_status action. Anything absent is a 409.
MOVES = {
    ("backlog", "running"): "start",
    ("backlog", "done"): "cancel",
    ("running", "backlog"): "pause",
    ("running", "done"): "cancel",
    ("awaiting", "backlog"): "pause",
    ("awaiting", "done"): "cancel",
}


def _card(m: dict) -> dict:
    steps = m.get("steps") or []
    done = sum(1 for s in steps
               if isinstance(s, dict) and s.get("status") in ("done", "skipped"))
    return {"id": m["id"], "goal": m["goal"], "status": m["status"],
            "steps_total": len(steps), "steps_done": done,
            "next_run_at": m.get("next_run_at", ""), "created_at": m.get("created_at", ""),
            "updated_at": m.get("updated_at", "")}


@board_r.get("")
def board():
    by_col: dict[str, list[dict]] = {k: [] for k, _, _ in COLUMNS}
    for m in _m.list_missions(limit=100):
        by_col[_STATUS_TO_COLUMN.get(m["status"], "backlog")].append(_card(m))
    return {"columns": [{"key": k, "label": lab, "missions": by_col[k]} for k, lab, _ in COLUMNS],
            "counts": {k: len(v) for k, v in by_col.items()}}


@board_r.post("/move")
def move(body: dict):
    mid, col = body.get("mission_id"), body.get("column")
    if col not in _COLUMN_KEYS:
        raise HTTPException(400, f"column must be one of {','.join(sorted(_COLUMN_KEYS))}")
    if not isinstance(mid, int) or isinstance(mid, bool):
        raise HTTPException(400, "mission_id must be an integer")
    m = _m._row(mid)
    if not m:
        raise HTTPException(404, "not found")
    src = _STATUS_TO_COLUMN.get(m["status"], "backlog")
    if src == col:
        return {"ok": True, "mission": _card(m)}
    action = MOVES.get((src, col))
    if action is None:
        raise HTTPException(409, f"cannot move a {src} mission to {col}")
    try:
        updated = _m.set_status(mid, action)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not updated:
        raise HTTPException(404, "not found")
    return {"ok": True, "mission": _card(updated)}
```

- [ ] **Step 4: Register the router**

`backend/app/routes/__init__.py`: add `from .kanban import board_r` and append `board_r` to `ROUTERS`. `backend/app/domain.py`: add `board_r` to the `from .routes import (...)` re-export block.

- [ ] **Step 5: Run the backend tests**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_kanban
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
```

Expected: 7 board tests pass; suite is 359 + 7 = 366, `OK`.

- [ ] **Step 6: Add the typed client**

`frontend/src/api.ts`, above the `api` object:

```ts
export type BoardMission = { id: number; goal: string; status: string; steps_total: number; steps_done: number; next_run_at: string; created_at: string; updated_at: string };
export type BoardColumn = { key: "backlog" | "running" | "awaiting" | "done"; label: string; missions: BoardMission[] };
```

and inside `api`, beside `automations` (which is at line 237):

```ts
  board: {
    get: () => get<{ columns: BoardColumn[]; counts: Record<string, number> }>("/board"),
    move: (mission_id: number, column: string) =>
      post<{ ok: boolean; mission: BoardMission }>("/board/move", { mission_id, column }),
  },
```

- [ ] **Step 7: Write the failing frontend test**

Create `frontend/src/__tests__/kanban.test.tsx`. Read `frontend/src/__tests__/missions.test.tsx` first and copy its mock and setup shape — these run in jsdom and mock `api`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { KanbanView } from "../views2/kanban";
import { api } from "../api";

vi.mock("../api", () => ({
  api: { board: { get: vi.fn(), move: vi.fn() } },
  ago: (s: string) => s,
}));

vi.mock("../store", () => ({
  useStore: () => ({ toast: vi.fn() }),
}));

const CARD = { id: 1, goal: "Plan my week", status: "draft", steps_total: 2, steps_done: 0, next_run_at: "", created_at: "", updated_at: "" };
const COLUMNS = [
  { key: "backlog", label: "Backlog", missions: [CARD] },
  { key: "running", label: "Running", missions: [] as typeof CARD[] },
  { key: "awaiting", label: "Needs you", missions: [] as typeof CARD[] },
  { key: "done", label: "Finished", missions: [] as typeof CARD[] },
] as any;

describe("KanbanView", () => {
  beforeEach(() => {
    (api.board.get as any).mockResolvedValue({ columns: COLUMNS, counts: { backlog: 1, running: 0, awaiting: 0, done: 0 } });
    (api.board.move as any).mockResolvedValue({ ok: true, mission: { ...CARD, status: "running" } });
  });

  it("renders every column with its cards", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    for (const label of ["Backlog", "Running", "Needs you", "Finished"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("exposes a start control for a backlog card", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /start/i }));
    await waitFor(() => expect(api.board.move).toHaveBeenCalledWith(1, "running"));
  });

  it("offers no controls on a finished card", async () => {
    (api.board.get as any).mockResolvedValue({
      columns: COLUMNS.map((c: any) => (c.key === "done" ? { ...c, missions: [{ ...CARD, status: "done" }] } : c)),
      counts: { backlog: 1, running: 0, awaiting: 0, done: 1 },
    });
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    const done = screen.getByLabelText("Finished").closest("section") as HTMLElement;
    expect(done.querySelectorAll("button").length).toBe(0);
  });

  it("surfaces a rejected move as a toast, not a silent no-op", async () => {
    (api.board.move as any).mockRejectedValue(new Error("cannot move a done mission to backlog"));
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /start/i }));
    await waitFor(() => expect(api.board.move).toHaveBeenCalled());
  });
});
```

- [ ] **Step 8: Write `frontend/src/views2/kanban.tsx`**

Native HTML5 drag-and-drop is untestable in jsdom (no `DataTransfer`), so moves are driven by explicit buttons — those are what the tests assert on — while `draggable`/`onDrop` is wired for real browsers:

```tsx
import { useState } from "react";
import { api, BoardColumn, BoardMission } from "../api";
import { useStore } from "../store";
import { useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

const NEXT: Record<string, { col: string; label: string }[]> = {
  backlog: [{ col: "running", label: "Start" }, { col: "done", label: "Cancel" }],
  running: [{ col: "backlog", label: "Pause" }, { col: "done", label: "Cancel" }],
  awaiting: [{ col: "backlog", label: "Pause" }, { col: "done", label: "Cancel" }],
  done: [],
};

export function KanbanView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.board.get());
  const [over, setOver] = useState<string | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);

  const move = async (m: BoardMission, col: string) => {
    try {
      await api.board.move(m.id, col);
      reload();
      toast(`Moved “${m.goal.slice(0, 40)}”`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const cols: BoardColumn[] = data?.columns || [];

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="rocket" s={20} /> Missions Board</h2>
        <Pill c="violet">
          {Object.values(data?.counts || {}).reduce((a, b) => a + b, 0)} missions
        </Pill>
      </div>
      <div className="board" data-testid="board">
        {cols.map((c) => (
          <section
            key={c.key}
            aria-label={c.label}
            className={`boardcol ${over === c.key ? "over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setOver(c.key); }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              if (dragId === null) return;
              const card = c.missions.find((m) => m.id === dragId);
              setDragId(null);
              if (card) void move(card, c.key);
            }}
          >
            <header><strong>{c.label}</strong><Pill c="blue">{c.missions.length}</Pill></header>
            {c.missions.map((m) => (
              <div
                key={m.id}
                className="boardcard"
                draggable
                onDragStart={(e) => { setDragId(m.id); e.dataTransfer.setData("text/plain", String(m.id)); }}
                onDragEnd={() => setDragId(null)}
              >
                <strong>{m.goal}</strong>
                <small>{m.steps_done}/{m.steps_total} steps · {m.status}</small>
                <Row icon="clock"
                  title={m.next_run_at ? `Next ${m.next_run_at.slice(0, 16).replace("T", " ")}` : "No schedule"} />
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(NEXT[c.key] || []).map((a) => (
                    <Btn key={a.col} small onClick={() => move(m, a.col)}>{a.label}</Btn>
                  ))}
                </div>
              </div>
            ))}
            {c.missions.length === 0 && <Empty title="Empty" sub="Nothing here yet." />}
          </section>
        ))}
        {cols.length === 0 && <Empty title="Loading board" sub="Fetching missions…" />}
      </div>
      <Panel icon="shield" title="How moves work" sub="The board cannot fake success">
        <small className="dim">
          A card dragged out of the backlog without starting is cancelled, not completed. The only
          route to Finished is a mission actually finishing, so the board can never mark work done
          that AURA did not do. Cards needing approval stay in Needs you until you resolve them in
          Activity.
        </small>
      </Panel>
    </div>
  );
}
```

`useFetch` is imported from `"../views1"` — it lives there, not in `ui.tsx`.

- [ ] **Step 9: Add the view to the app**

`frontend/src/store.tsx` line 7 — add `"board"` to the `View` union:

```ts
export type View = "home" | "career" | "clients" | "personal" | "inbox" | "calendar" | "memory" | "sessions" | "voice" | "gateway" | "automations" | "board" | "activity" | "analytics" | "smarthome" | "files" | "models" | "terminal" | "feeds" | "settings";
```

`frontend/src/App.tsx` — add beside the other lazy imports (lines 7-22):

```tsx
const KanbanView = lazy(() => import("./views2/kanban").then((m) => ({ default: m.KanbanView })));
```

and a render branch beside the automations one:

```tsx
            {view === "board" && <KanbanView />}
```

Add a nav entry. Find the nav array with `grep -n '"automations"' frontend/src/App.tsx frontend/src/home.tsx` and add `{ k: "board", icon: "rocket", label: "Board" }` in the exact shape of its neighbours.

- [ ] **Step 10: Add the board CSS**

Append to `frontend/src/theme.css`, following the existing custom-property conventions:

```css
/* ---------------- missions board ---------------- */
.board { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: start; }
.boardcol { background: var(--surface-2, rgba(255,255,255,0.03)); border: 1px solid var(--border); border-radius: 14px; padding: 10px; min-height: 160px; display: flex; flex-direction: column; gap: 8px; }
.boardcol.over { border-color: var(--cyan); box-shadow: 0 0 0 1px var(--cyan) inset; }
.boardcol header { display: flex; justify-content: space-between; align-items: center; }
.boardcard { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 8px; display: flex; flex-direction: column; gap: 6px; cursor: grab; }
.boardcard:active { cursor: grabbing; }
@media (max-width: 900px) { .board { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .board { grid-template-columns: 1fr; } }
```

- [ ] **Step 11: Verify the frontend**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: 175 + 4 = 179 passing, `tsc` clean.

- [ ] **Step 12: Commit**

```bash
git add backend/app/routes/kanban.py backend/app/routes/__init__.py backend/app/domain.py backend/tests/test_kanban.py frontend/src/views2/kanban.tsx frontend/src/api.ts frontend/src/store.tsx frontend/src/App.tsx frontend/src/theme.css frontend/src/__tests__/kanban.test.tsx
git commit -m "feat: Kanban mission board (spec §2)

Columns are derived from the existing missions.status values, and every drag
goes through missions.set_status. Two deliberate constraints: the only route to
Finished is a mission actually completing, and a card dragged out of the
backlog without starting is cancelled rather than marked done. Otherwise the
board would be a way to fabricate success and to route around approvals.

Drag-and-drop is wired for real browsers but moves are driven by buttons, since
jsdom has no DataTransfer to test with."
```

---

## Task 4: Worker pool, persistent queue, and the mission-tick fix (spec §5, FR-WRK-001..005)

**Files:**
- Create: `backend/app/workers.py`, `backend/app/routes/workers.py`
- Modify: `backend/app/schema.sql` (`worker_jobs`), `backend/app/db.py` (`init_db` index guard)
- Modify: `backend/app/hermes.py` (`start_scheduler_loop` — **the mission-execution fix**)
- Modify: `backend/app/prefs.py` (two keys), `backend/app/routes/__init__.py`, `backend/app/domain.py`
- Test: `backend/tests/test_workers.py`

**Interfaces:**
- Consumes: `db`, `prefs`, `missions.tick_schedules`, `missions.tick_missions`, `consolidate`.
- Produces:
  - `workers.enqueue(kind, payload: dict, priority: int = 5, max_retries: int | None = None) -> int`
  - `workers.claim(n: int = 1) -> list[dict]`
  - `workers.complete(job_id: int, result: Any = None) -> None`
  - `workers.fail(job_id: int, err: str) -> str` → `"retry"` or `"dead"`
  - `workers.drain(limit: int = 20) -> dict` → `{"ran", "done", "retried", "dead"}`
  - `workers.scheduler_pass() -> dict` — **one 30s pass**; the loop body calls this and nothing else
  - `workers.requeue_stale() -> int`, `workers.pool_size() -> int`, `workers.stats() -> dict`, `workers.dead_letters(limit=50) -> list[dict]`
  - `stats()` keys: `queued`, `running`, `done`, `dead`, `throughput_per_min`, `error_rate`, `by_kind`
  - `GET /api/workers` → `{"stats": …, "pool_size": int}`; `GET /api/workers/dead`; `POST /api/workers/drain`

**The bug this task fixes first.** `missions.tick_missions()` and `missions.tick_schedules()` have **no call sites** outside tests. `start_scheduler_loop` (`backend/app/hermes.py:868-879`) calls only `hermes.tick_automations()`, so a mission started from the UI or chat sits at `running` with every step `pending`, indefinitely. The suite passes because tests call `tick_missions()` by hand. Step 1 writes the regression test before any pool work.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS worker_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL,                    -- mission_tick | schedule_tick | consolidation | custom
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued', -- queued | running | done | dead
  priority INTEGER NOT NULL DEFAULT 5,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  last_error TEXT NOT NULL DEFAULT '',
  result_json TEXT NOT NULL DEFAULT '',
  available_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_worker_jobs_claim ON worker_jobs(status, priority, available_at);
```

The index is the claim path. `available_at` carries the backoff so a failing job does not spin.

**Backoff:** `min(300, 2 ** max(1, attempts) * 5)` → 10s, 20s, 40s. After `max_retries` the job goes `dead` and raises `db.notify(..., "error")`. `FR-WRK-003` asks for 3 retries then dead-letter; the schema default is 3 and `prefs` lets the user lower it.

**Why threads, not asyncio.** The DB layer is one pooled SQLite connection behind an `RLock`, so N threads writing concurrently serialise on that lock regardless. What genuinely parallelises is tool execution (`web.fetch`, `feeds.latest`, `comms.send`), which releases the lock while it waits on the network. Converting this to asyncio later would risk deadlocking on the RLock for no throughput gain. The docstring must say this, so nobody "fixes" it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workers.py`:

```python
"""Worker pool tests, plus the mission-tick regression guard."""
import inspect
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-workers-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import time  # noqa: E402
import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, hermes, missions, prefs, workers  # noqa: E402
from app.main import app  # noqa: E402


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
        db.run("DELETE FROM worker_jobs")
        prefs.set_many({"worker_max_retries": 3, "worker_pool_size": 3})

    def test_enqueue_claim_complete(self):
        jid = workers.enqueue("custom", {"x": 1})
        claimed = workers.claim(1)
        self.assertEqual([j["id"] for j in claimed], [jid])
        self.assertEqual(claimed[0]["attempts"], 1)
        workers.complete(jid, {"ok": True})
        self.assertEqual(workers.stats()["done"], 1)

    def test_claim_is_priority_ordered(self):
        workers.enqueue("custom", {"n": "low"}, priority=9)
        top = workers.enqueue("custom", {"n": "high"}, priority=1)
        self.assertEqual(workers.claim(1)[0]["id"], top)

    def test_failure_retries_then_dead_letters(self):
        jid = workers.enqueue("custom", {}, max_retries=2)
        for _ in range(2):
            c = workers.claim(1)
            self.assertTrue(c, "job must be claimable again")
            self.assertEqual(workers.fail(c[0]["id"], "boom"), "retry")
            db.run("UPDATE worker_jobs SET available_at='' WHERE id=?", (c[0]["id"],))
        c = workers.claim(1)
        self.assertEqual(workers.fail(c[0]["id"], "boom again"), "dead")
        self.assertEqual([j["id"] for j in workers.dead_letters()], [jid])

    def test_backoff_delays_the_next_claim(self):
        jid = workers.enqueue("custom", {})
        workers.fail(workers.claim(1)[0]["id"], "boom")
        self.assertEqual(workers.claim(1), [], "a backed-off job must not be re-claimable yet")
        db.run("UPDATE worker_jobs SET available_at='' WHERE id=?", (jid,))
        self.assertEqual(len(workers.claim(1)), 1, "past available_at it is claimable again")

    def test_drain_runs_and_settles(self):
        workers.enqueue("custom", {"ok": True})
        r = workers.drain()
        self.assertEqual(r["ran"], 1, r)
        self.assertEqual(r["done"], 0, r)
        self.assertEqual(r["dead"], 1, r)

    def test_drain_of_empty_queue_is_a_noop(self):
        self.assertEqual(workers.drain(), {"ran": 0, "done": 0, "retried": 0, "dead": 0})

    def test_stats_shape(self):
        for k in ("queued", "running", "done", "dead", "throughput_per_min",
                  "error_rate", "by_kind"):
            self.assertIn(k, workers.stats())

    def test_requeue_stale_recovers_interrupted_jobs(self):
        jid = workers.enqueue("custom", {})
        workers.claim(1)
        self.assertEqual(workers.stats()["running"], 1)
        self.assertEqual(workers.requeue_stale(), 1)
        self.assertEqual(workers.stats()["queued"], 1)
        self.assertEqual(workers.claim(1)[0]["id"], jid)

    def test_routes(self):
        self.assertEqual(self.c.get("/api/workers").status_code, 200)
        self.assertEqual(self.c.get("/api/workers/dead").status_code, 200)
        r = self.c.post("/api/workers/drain", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("ran", r.json())


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

    def test_scheduler_loop_source_drives_missions(self):
        """The 30s loop body must reach the mission ticks.

        Asserted against the source, not by running the loop: it is a daemon
        thread that sleeps 30s between passes, so running it would take half a
        minute and still prove nothing about the wiring.
        """
        src = inspect.getsource(hermes.start_scheduler_loop)
        self.assertIn("scheduler_pass", src, src)

    def test_scheduler_pass_advances_a_running_mission(self):
        mid = self.c.post("/api/missions", json={"goal": "T-Tick advance probe"}).json()["id"]
        self.c.patch(f"/api/missions/{mid}", json={"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        self.c.post(f"/api/missions/{mid}/control", json={"action": "start"})
        before = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(before["steps"][0]["status"], "pending")
        out = workers.scheduler_pass()
        self.assertIn("missions", out, out)
        after = self.c.get(f"/api/missions/{mid}").json()
        self.assertEqual(after["status"], "done", after)
        self.assertEqual(after["steps"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_workers
```

Expected: `ModuleNotFoundError: No module named 'app.workers'`

- [ ] **Step 3: Add the schema and the init guard**

Append to `backend/app/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS worker_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  priority INTEGER NOT NULL DEFAULT 5,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  last_error TEXT NOT NULL DEFAULT '',
  result_json TEXT NOT NULL DEFAULT '',
  available_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_worker_jobs_claim ON worker_jobs(status, priority, available_at);
```

`CREATE TABLE IF NOT EXISTS` plus a standalone `CREATE INDEX IF NOT EXISTS` means an existing database picks the index up on the next `executescript(schema)` — no `init_db` guard is needed. Verify that claim by running the migration self-test in Step 9; only add a guard if that fails.

- [ ] **Step 4: Add the two pref keys**

In `backend/app/prefs.py` `SCHEMA`, after `"mission_step_checkins"` (line 81):

```python
    "worker_pool_size": (3, "int", (1, 8)),
    "worker_max_retries": (3, "int", (0, 5)),
```

`worker_pool_size` default 3 is `FR-WRK-001`'s value. Neither is bookkeeping, so both stay visible in `public_view` and appear in the Settings UI.

- [ ] **Step 5: Write `backend/app/workers.py`**

```python
"""Worker pool and persistent job queue (spec §5, FR-WRK-001..005).

Concurrency here is a *thread* pool, not asyncio, and that is deliberate. The DB
layer is one pooled SQLite connection behind an RLock, so N threads writing
concurrently serialise on that lock regardless; what genuinely parallelises is
tool execution (web.fetch, feeds.latest, comms.send), which releases the lock
while it waits on the network. Converting this to asyncio later would risk
deadlocking on the RLock for no throughput gain.

The queue is persistent (`worker_jobs`), so `requeue_stale` returns
interrupted `running` jobs to `queued` on startup rather than losing them —
FR-WRK-005's "zero message loss".
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import db, prefs

KIND_MISSION_TICK = "mission_tick"
KIND_SCHEDULE_TICK = "schedule_tick"
KIND_CONSOLIDATION = "consolidation"
KNOWN_KINDS = (KIND_MISSION_TICK, KIND_SCHEDULE_TICK, KIND_CONSOLIDATION)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def pool_size() -> int:
    return max(1, min(int(prefs.get("worker_pool_size") or 3), 8))


def enqueue(kind: str, payload: dict, priority: int = 5, max_retries: int | None = None) -> int:
    if max_retries is None:
        max_retries = int(prefs.get("worker_max_retries") or 3)
    return db.run(
        "INSERT INTO worker_jobs (user_id, kind, payload_json, priority, max_retries, available_at) "
        "VALUES (1,?,?,?,?,?)",
        (kind, db.jdump(payload or {}), int(priority), int(max_retries), ""))


def claim(n: int = 1) -> list[dict]:
    """Move up to n claimable jobs to `running` and return them.

    Claimable = status 'queued' AND (available_at empty OR <= now). Rows are
    re-read after the UPDATE so the returned `attempts` is the post-increment
    value the caller should act on.
    """
    ids = [r["id"] for r in db.q(
        "SELECT id FROM worker_jobs WHERE user_id=1 AND status='queued' "
        "AND (available_at='' OR available_at <= ?) ORDER BY priority ASC, id ASC LIMIT ?",
        (_now(), max(1, int(n))))]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    db.run(f"UPDATE worker_jobs SET status='running', attempts=attempts+1, updated_at=? "
           f"WHERE id IN ({marks}) AND status='queued'", (_now(), *ids))
    return db.q(f"SELECT * FROM worker_jobs WHERE id IN ({marks}) ORDER BY priority ASC, id ASC",
                tuple(ids))


def complete(job_id: int, result: Any = None) -> None:
    db.run("UPDATE worker_jobs SET status='done', result_json=?, last_error='', updated_at=? "
           "WHERE id=?", (db.jdump(result if result is not None else {}), _now(), job_id))


def fail(job_id: int, err: str) -> str:
    """Settle a failure. Returns 'retry' or 'dead'."""
    row = db.qone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    if not row:
        return "dead"
    attempts, cap = int(row.get("attempts") or 0), int(row.get("max_retries") or 0)
    if attempts > cap:
        db.run("UPDATE worker_jobs SET status='dead', last_error=?, updated_at=? WHERE id=?",
               (str(err)[:300], _now(), job_id))
        db.notify("Job dead-lettered", f"{row['kind']} — {str(err)[:140]}", "error")
        return "dead"
    delay = min(300, (2 ** max(1, attempts)) * 5)
    db.run("UPDATE worker_jobs SET status='queued', last_error=?, available_at=?, updated_at=? "
           "WHERE id=?", (str(err)[:300], _iso(time.time() + delay), _now(), job_id))
    return "retry"


def _run(job: dict) -> Any:
    kind = job["kind"]
    if kind == KIND_MISSION_TICK:
        from . import missions as _m
        return _m.tick_missions()
    if kind == KIND_SCHEDULE_TICK:
        from . import missions as _m
        return _m.tick_schedules()
    if kind == KIND_CONSOLIDATION:
        from . import consolidate as _c
        return _c.run_pass()
    raise ValueError(f"unknown job kind: {kind}")


def drain(limit: int = 20) -> dict:
    """Claim jobs, run them on the pool, settle each outcome."""
    out = {"ran": 0, "done": 0, "retried": 0, "dead": 0}
    jobs = claim(min(int(limit), pool_size() * 4) if limit else pool_size())
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=pool_size()) as ex:
        futures = {ex.submit(_run, j): j for j in jobs}
        for fut, job in futures.items():
            out["ran"] += 1
            try:
                complete(job["id"], fut.result())
                out["done"] += 1
            except Exception as e:  # noqa: BLE001 — one bad job must not stop the drain
                if fail(job["id"], str(e)) == "retry":
                    out["retried"] += 1
                else:
                    out["dead"] += 1
    return out


def requeue_stale() -> int:
    """On startup: return `running` jobs to `queued`. They were interrupted."""
    n = (db.qone("SELECT COUNT(*) c FROM worker_jobs WHERE user_id=1 "
                 "AND status='running'") or {}).get("c", 0)
    db.run("UPDATE worker_jobs SET status='queued', updated_at=? "
           "WHERE user_id=1 AND status='running'", (_now(),))
    return int(n)


def stats() -> dict:
    by = {r["status"]: r["c"] for r in db.q(
        "SELECT status, COUNT(*) c FROM worker_jobs WHERE user_id=1 GROUP BY status")}
    kinds = {r["kind"]: r["c"] for r in db.q(
        "SELECT kind, COUNT(*) c FROM worker_jobs WHERE user_id=1 GROUP BY kind")}
    done, dead = by.get("done", 0), by.get("dead", 0)
    settled = done + dead
    recent = (db.qone("SELECT COUNT(*) c FROM worker_jobs WHERE user_id=1 AND updated_at >= ?",
                      (_iso(time.time() - 60),)) or {}).get("c", 0)
    return {"queued": by.get("queued", 0), "running": by.get("running", 0),
            "done": done, "dead": dead, "throughput_per_min": int(recent),
            "error_rate": round(dead / settled, 3) if settled else 0.0,
            "by_kind": kinds}


def dead_letters(limit: int = 50) -> list[dict]:
    return db.q("SELECT id, kind, attempts, max_retries, last_error, updated_at "
                "FROM worker_jobs WHERE user_id=1 AND status='dead' ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),))


def scheduler_pass() -> dict:
    """One 30-second scheduler pass. The loop body calls this and nothing else.

    Named so it is callable from a test: the real loop sleeps 30s between
    passes, so a test cannot exercise the loop itself, only this function.
    """
    from . import hermes as _h
    from . import missions as _m
    out: dict[str, Any] = {"automations": _h.hermes.tick_automations(),
                           "schedules": _m.tick_schedules(),
                           "missions": _m.tick_missions()}
    try:
        from . import consolidate as _c
        if _c.should_run():
            out["consolidation"] = _c.run_pass()
            prefs.set_many({"consolidate_last_run": int(time.time())})
    except Exception as e:  # noqa: BLE001 — consolidation must not stall the loop
        out["consolidation_error"] = str(e)[:120]
    try:
        out["jobs"] = drain()
    except Exception as e:  # noqa: BLE001
        out["jobs_error"] = str(e)[:120]
    return out
```

`KNOWN_KINDS` is exported for the E2E check in Task 8; if it is unused elsewhere, drop it rather than leave a dangling constant.

- [ ] **Step 6: Fix the scheduler loop — the mission-execution bug**

Replace `start_scheduler_loop` at `backend/app/hermes.py:866-881`:

```python
def start_scheduler_loop() -> None:
    """Start the 30-second scheduler loop for automations, missions and jobs.

    The loop body is `workers.scheduler_pass`, not inline work: missions used to
    be ticked only from tests, so a mission started from the UI sat at `running`
    forever. Keeping the body in a named function also makes it callable from a
    test, which the sleeping thread is not.
    """
    from . import workers as _w
    try:
        _w.requeue_stale()
    except Exception:
        traceback.print_exc()

    def _loop():
        interval_s = 30
        while True:
            try:
                _w.scheduler_pass()
            except Exception:
                traceback.print_exc()
            try:
                db.run("UPDATE approvals SET status='expired' WHERE status='pending' "
                       "AND expires_at IS NOT NULL AND expires_at <= datetime('now')")
            except Exception:
                pass
            time.sleep(interval_s)

    threading.Thread(target=_loop, daemon=True, name="aura-scheduler").start()
```

Confirm `db` is imported at module scope in `hermes.py` — the existing loop body already calls `db.run`, so it is. If it is only imported inside `tick_automations`, add `from . import db` at the top; do not add a second import inside the loop.

- [ ] **Step 7: Write `backend/app/routes/workers.py`**

```python
"""Worker router — queue observability and manual drain."""
from __future__ import annotations

from fastapi import APIRouter

from .. import workers

worker_r = APIRouter(prefix="/workers", tags=["workers"])


@worker_r.get("")
def status():
    return {"stats": workers.stats(), "pool_size": workers.pool_size()}


@worker_r.get("/dead")
def dead(limit: int = 50):
    return {"dead": workers.dead_letters(limit)}


@worker_r.post("/drain")
def drain():
    return workers.drain()
```

- [ ] **Step 8: Register the router**

`backend/app/routes/__init__.py`: add `from .workers import worker_r`, append `worker_r` to `ROUTERS`. `backend/app/domain.py`: add `worker_r` to the re-export block.

- [ ] **Step 9: Run the tests and the migration check**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_workers
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
venv/bin/python scripts/migration_check.py --self-test
```

Expected: 11 new tests pass; suite is 366 + 11 = 377, `OK`. The `test_scheduler_loop_source_drives_missions` test is the regression guard — do not weaken it to make the suite pass.

- [ ] **Step 10: Benchmark the new pass**

```bash
venv/bin/python scripts/benchmark.py --ci
```

Expected: all medians within budget. `scheduler_pass` adds a mission tick to every 30s cycle, not to the chat turn, so `chat_turn_builtin` must be unchanged.

- [ ] **Step 11: Commit**

```bash
git add backend/app/workers.py backend/app/routes/workers.py backend/app/schema.sql backend/app/prefs.py backend/app/hermes.py backend/app/routes/__init__.py backend/app/domain.py backend/tests/test_workers.py
git commit -m "feat: worker pool, and fix missions never advancing in production

missions.tick_missions() and tick_schedules() had no call sites outside tests.
The 30s loop only ran hermes.tick_automations(), so a mission started from the
UI or chat sat at status='running' with every step pending, indefinitely. The
suite passed because the tests called tick_missions() by hand.

The loop body is now workers.scheduler_pass, which is callable from a test — the
sleeping thread is not — and test_scheduler_loop_source_drives_missions is the
regression guard.

Jobs are persistent and re-claimed on restart, so an interrupted run re-queues
rather than vanishing. Retries back off 10s/20s/40s, then dead-letter with a
notification. Threads rather than asyncio because the DB is one connection
behind an RLock: tool execution parallelises, DB writes do not."
```

---

## Task 5: Agentic slash commands (spec §3, FR-CMD-001..005)

**Files:**
- Create: `backend/app/slash.py`, `backend/app/routes/slash.py`
- Modify: `backend/app/prefs.py` (`slash_custom` key), `backend/app/routes/__init__.py`, `backend/app/domain.py`
- Modify: `backend/app/main.py` (`chat_stream` short-circuit + `_one_sse`)
- Create: `frontend/src/slash.ts`, `frontend/src/CommandPalette.tsx`, `frontend/src/views2/commands.tsx`
- Modify: `frontend/src/ui.tsx` (`Composer`), `frontend/src/api.ts`, `frontend/src/store.tsx`, `frontend/src/views2/settings.tsx`
- Test: `backend/tests/test_slash.py`, `frontend/src/__tests__/slash.test.ts`, `frontend/src/__tests__/commandpalette.test.tsx`

**Interfaces:**
- Consumes: `db`, `prefs`, `hermes.TOOLS`, `hermes.hermes`, `missions`, `memory.memory_engine`, `backup.run_backup`, `health.system_status`, `inference.router`, `ollama_sync.list_models`, `routes.tasks.{TaskIn, list_tasks, _update_task_impl}`.
- Produces:
  - `slash.CATALOG: list[SlashCommand]`, `SlashCommand = {"name", "category", "summary", "example", "arg", "handler"}`
  - `slash.parse(text) -> tuple[SlashCommand | None, str]` — `(command, raw_args)`. `None` unless the text starts with `/` at position 0 **and** the name is known.
  - `slash.execute(text) -> dict` → `{"handled": bool, "ok": bool, "command": str, "result": Any, "text": str, "view": str | None}`. Never raises.
  - `slash.all_commands() -> list[dict]` (catalog + custom, handlers stripped)
  - `slash.custom() -> list[dict]`, `save_custom(name, prompt, view="") -> dict`, `delete_custom(name) -> None`
  - `GET /api/slash` → `{"commands": [...]}`; `POST /api/slash/execute`; `POST /api/slash/custom` (400 on invalid); `DELETE /api/slash/custom/{name}`

**The catalog** — `FR-CMD-002` names these exactly; implement all of them:

| Command | Category | Arg | Behaviour |
|---|---|---|---|
| `/home` `/career` `/clients` `/personal` `/memory` `/voice` `/automations` `/settings` | Navigation | — | `{"view": "<name>"}`, no DB write |
| `/remember <fact>` | Memory | text | `memory_engine.store(title, content, "general")` |
| `/forget <topic>` | Memory | text | `memory_engine.forget_topic(topic)` |
| `/search <query>` | Memory | text | `memory_engine.search(query, limit=8)` |
| `/memories` | Memory | — | `memory_engine.stats()` + 10 most recent |
| `/task <title>` | Tasks | text | `create_task(TaskIn(title=…))` |
| `/tasks` | Tasks | — | `list_tasks(status="inbox")` → `{"tasks": […]}` |
| `/done <id or title>` | Tasks | id or title | `_update_task_impl(task_id=…, status="completed")`; numeric arg is an id, else a title substring match |
| `/mission <goal>` | Automation | text | `missions.create_mission(goal)` |
| `/missions` | Automation | — | `missions.list_missions(10)` |
| `/run <name or id>` | Automation | name or id | `hermes.fire_event(row, fire_id=…)` |
| `/status` | System | — | `health.system_status()` |
| `/backup` | System | — | `backup.run_backup()` |
| `/models` | System | — | `ollama_sync.list_models()` |
| `/health` | System | — | `system_status()` + DB size on disk |
| `/logs` | System | — | 20 most recent `activity` rows |
| `/think <prompt>` | AI | text | one local-model answer; no tools, no memory write |
| `/ask <model> <prompt>` | AI | model + text | one completion against the named model |
| `/switch <model>` | AI | model | `prefs.set_many({"ollama_chat_model": model})`, validated against the installed catalog |

**Argument parsing (`FR-CMD-003`).** `parse` splits on the **first** space only, so `/task Review the PR draft` keeps its spaces. Strip one layer of matching surrounding quotes (`"` or `'`). If a command's `arg` is non-empty and the argument is empty, `execute` returns `{"handled": true, "ok": false, "text": "Usage: …"}` — never a silent no-op.

**Custom commands (`FR-CMD-004`).** Stored under the `slash_custom` pref key as a JSON list of `{"name", "prompt", "view"}`. A name must start with `/`, contain no whitespace, and not collide with a built-in; otherwise 400. Executing one returns its prompt so the client sends it as a normal message.

**Chat integration.** A leading `/` in `POST /api/chat/stream` is handled before the orchestrator runs, so `/task …` works from any client. It does **not** go through `run_turn`: a command is deterministic and must not spend a model call.

- [ ] **Step 1: Write the failing backend test**

Create `backend/tests/test_slash.py`:

```python
"""Slash command parser and executor tests."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aura-slash-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

import unittest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, slash  # noqa: E402
from app.main import app  # noqa: E402


class SlashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.c = TestClient(app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def test_catalog_covers_the_spec(self):
        names = {c["name"] for c in slash.CATALOG}
        required = {"/home", "/career", "/clients", "/personal", "/memory", "/voice",
                    "/automations", "/settings", "/remember", "/forget", "/search",
                    "/memories", "/task", "/tasks", "/done", "/mission", "/missions",
                    "/run", "/status", "/backup", "/models", "/health", "/logs",
                    "/think", "/ask", "/switch"}
        self.assertEqual(required - names, set(), f"missing: {sorted(required - names)}")
        for c in slash.CATALOG:
            self.assertTrue(c["summary"], c)
            self.assertTrue(c["example"], c)
            self.assertIn(c["category"],
                          {"Navigation", "Memory", "Tasks", "Automation", "System", "AI"}, c)

    def test_parse_splits_on_first_space_only(self):
        cmd, args = slash.parse("/task Review the PR draft")
        self.assertEqual(cmd["name"], "/task")
        self.assertEqual(args, "Review the PR draft")

    def test_parse_strips_matching_quotes(self):
        _, args = slash.parse('/task "Review the PR"')
        self.assertEqual(args, "Review the PR")
        _, args = slash.parse("/task 'Review the PR'")
        self.assertEqual(args, "Review the PR")

    def test_parse_only_matches_at_position_zero(self):
        self.assertIsNone(slash.parse("hello world")[0])
        self.assertIsNone(slash.parse("mid /task sentence")[0])
        self.assertIsNone(slash.parse("/nope")[0])
        self.assertIsNone(slash.parse("")[0])

    def test_navigation_returns_view(self):
        r = slash.execute("/career")
        self.assertTrue(r["handled"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["view"], "career")

    def test_missing_arg_is_a_usage_error_not_a_noop(self):
        r = slash.execute("/remember")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("Usage", r["text"])

    def test_remember_then_search_roundtrip(self):
        r = slash.execute("/remember standup is at nine every morning")
        self.assertTrue(r["ok"], r)
        s = slash.execute("/search standup")
        self.assertTrue(s["ok"], s)
        self.assertTrue(any("standup" in str(x.get("content", "")) for x in s["result"]["results"]),
                        s["result"])

    def test_task_create_then_list_then_done_by_id(self):
        r = slash.execute("/task T-Slash ship the plan")
        self.assertTrue(r["ok"], r)
        tid = r["result"]["task"]["id"]
        listing = slash.execute("/tasks")
        self.assertTrue(any("T-Slash" in str(t.get("title", "")) for t in listing["result"]["tasks"]),
                        listing["result"])
        d = slash.execute(f"/done {tid}")
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["result"]["task"]["status"], "completed")

    def test_done_by_title_substring(self):
        r = slash.execute("/task T-Slash unique marker zebra")
        tid = r["result"]["task"]["id"]
        d = slash.execute("/done zebra")
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["result"]["task"]["id"], tid)

    def test_done_unknown_task_is_an_error_not_a_crash(self):
        r = slash.execute("/done nothing matches this string")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("no task matching", r["text"])

    def test_unknown_command_is_not_handled(self):
        self.assertFalse(slash.execute("/definitelynotacommand")["handled"])
        self.assertFalse(slash.execute("plain text")["handled"])

    def test_offline_commands_work_without_a_model(self):
        for cmd in ("/status", "/health", "/models", "/logs", "/memories"):
            r = slash.execute(cmd)
            self.assertTrue(r["handled"], cmd)
            self.assertIsNotNone(r["text"], cmd)

    def test_ask_requires_model_and_prompt(self):
        r = slash.execute("/ask onlymodel")
        self.assertTrue(r["handled"])
        self.assertFalse(r["ok"])
        self.assertIn("Usage", r["text"])

    def test_custom_command_lifecycle(self):
        r = self.c.post("/api/slash/custom", json={"name": "/brief", "prompt": "summarise my day"})
        self.assertEqual(r.status_code, 200, r.text)
        g = self.c.get("/api/slash")
        self.assertTrue(any(c["name"] == "/brief" for c in g.json()["commands"]), g.text)
        ex = slash.execute("/brief")
        self.assertTrue(ex["handled"], ex)
        self.assertEqual(ex["text"], "summarise my day")
        self.assertEqual(self.c.delete("/api/slash/custom/brief").status_code, 200)
        self.assertFalse(slash.execute("/brief")["handled"])

    def test_custom_rejects_bad_names(self):
        for bad in ({"name": "/task", "prompt": "x"},
                    {"name": "no-slash", "prompt": "x"},
                    {"name": "/has space", "prompt": "x"},
                    {"name": "/empty", "prompt": ""}):
            self.assertEqual(self.c.post("/api/slash/custom", json=bad).status_code, 400, bad)

    def test_execute_route(self):
        self.assertEqual(self.c.get("/api/slash").status_code, 200)
        r = self.c.post("/api/slash/execute", json={"text": "/health"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["handled"])
        r = self.c.post("/api/slash/execute", json={"text": "not a command"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["handled"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_slash
```

Expected: `ModuleNotFoundError: No module named 'app.slash'`

- [ ] **Step 3: Add the `slash_custom` pref key**

In `backend/app/prefs.py` `SCHEMA`, near the chat settings (after `"enter_to_send"`, line 84):

```python
    "slash_custom": ("[]", "str", 8000),   # JSON list of {name, prompt, view}
```

Without this key `prefs.get("slash_custom")` raises `KeyError` and no custom command can persist. It is a user-facing setting, so it stays in `public_view`.

- [ ] **Step 4: Write `backend/app/slash.py`**

```python
"""Agentic slash commands (spec §3, FR-CMD-001..005).

A command is a deterministic Python handler, not a prompt. That is the whole
point: `/task Ship the plan` must create exactly one task without spending a
model call, so nothing here routes through the orchestrator.

`parse` matches only at position 0 — a `/` mid-sentence is prose, and treating
it as a command would silently eat part of the user's sentence.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from . import db, prefs

CATALOG: list[dict] = []


def _cmd(name: str, category: str, summary: str, example: str, arg: str,
         handler: Callable[[str], dict]) -> None:
    CATALOG.append({"name": name, "category": category, "summary": summary,
                    "example": example, "arg": arg, "handler": handler})


def _need(args: str, usage: str) -> None:
    if not args.strip():
        raise ValueError(f"Usage: {usage}")


# ---------------------------------------------------------------- memory ---

def _mem_store(args: str) -> dict:
    _need(args, "/remember <fact>")
    from .memory import memory_engine
    return {"memory": memory_engine.store(args[:72], args, "general", "semantic", "slash")}


def _mem_forget(args: str) -> dict:
    _need(args, "/forget <topic>")
    from .memory import memory_engine
    return {"forgotten": memory_engine.forget_topic(args)}


def _mem_search(args: str) -> dict:
    _need(args, "/search <query>")
    from .memory import memory_engine
    return {"results": memory_engine.search(args, limit=8)}


def _mem_list(_args: str) -> dict:
    from .memory import memory_engine
    return {"stats": memory_engine.stats(),
            "recent": db.q("SELECT id,title,domain,mtype,importance FROM memories "
                           "WHERE user_id=1 AND deleted_at IS NULL ORDER BY id DESC LIMIT 10")}


# ----------------------------------------------------------------- tasks ---

def _tasks_create(args: str) -> dict:
    _need(args, "/task <title>")
    from .routes.tasks import TaskIn, create_task
    return {"task": create_task(TaskIn(title=args))}


def _tasks_list(_args: str) -> dict:
    from .routes.tasks import list_tasks
    return list_tasks(status="inbox")


def _tasks_done(args: str) -> dict:
    _need(args, "/done <task id or title>")
    from .routes.tasks import _update_task_impl, list_tasks
    token = args.strip()
    rows = list_tasks()["tasks"]
    hit = next((t for t in rows if str(t.get("id")) == token), None) or \
        next((t for t in rows if token.lower() in str(t.get("title", "")).lower()), None)
    if not hit:
        raise ValueError(f"no task matching “{token}”")
    return {"task": _update_task_impl(task_id=hit["id"], status="completed")}


# ------------------------------------------------------------ automation ---

def _mission_new(args: str) -> dict:
    _need(args, "/mission <goal>")
    from . import missions as _m
    return {"mission": _m.create_mission(args)}


def _mission_list(_args: str) -> dict:
    from . import missions as _m
    return {"missions": _m.list_missions(10)}


def _auto_run(args: str) -> dict:
    _need(args, "/run <automation name or id>")
    from .hermes import hermes
    rows = db.q("SELECT * FROM automations WHERE user_id=1 AND status='active'")
    token = args.strip()
    hit = next((a for a in rows if str(a["id"]) == token), None) or \
        next((a for a in rows if token.lower() in str(a.get("name", "")).lower()), None)
    if not hit:
        raise ValueError(f"no active automation matching “{token}”")
    return {"ran": hermes.fire_event(hit, fire_id=f"slash-{hit['id']}")}


# ---------------------------------------------------------------- system ---

def _status(_args: str) -> dict:
    from .health import system_status
    return {"status": system_status()}


def _health(_args: str) -> dict:
    from .config import DB_PATH
    from .health import system_status
    return {"status": system_status(),
            "db_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0}


def _backup(_args: str) -> dict:
    from .backup import run_backup
    return {"backup": run_backup()}


def _models(_args: str) -> dict:
    from . import ollama_sync
    return ollama_sync.list_models()


def _logs(_args: str) -> dict:
    return {"logs": db.q("SELECT id,kind,title,detail,created_at FROM activity "
                         "WHERE user_id=1 ORDER BY id DESC LIMIT 20")}


# -------------------------------------------------------------------- ai ---

def _think(args: str) -> dict:
    _need(args, "/think <prompt>")
    from .inference import router as _r
    if not _r.probe().get("local_lfm", {}).get("online"):
        raise ValueError("local model is offline — start Ollama, or use /ask")
    return {"text": _r.ollama.chat([{"role": "user", "content": args}], purpose="chat")}


def _ask(args: str) -> dict:
    _need(args, "/ask <model> <prompt>")
    parts = args.split(None, 1)
    if len(parts) < 2:
        raise ValueError("Usage: /ask <model> <prompt>")
    model, prompt = parts
    from .inference import router as _r
    return {"model": model,
            "text": _r.ollama.chat([{"role": "user", "content": prompt}],
                                   model=model, purpose="chat")}


def _switch(args: str) -> dict:
    _need(args, "/switch <model>")
    from . import ollama_sync
    from .config import OLLAMA_BASE_URL
    import httpx
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        r.raise_for_status()
        installed = [m.get("name") for m in (r.json().get("models") or [])]
    except Exception as e:
        raise ValueError(f"cannot reach Ollama at {OLLAMA_BASE_URL}: {e}")
    if args not in installed:
        raise ValueError(f"“{args}” is not installed — have: {', '.join(str(m) for m in installed[:8])}")
    ollama_sync.set_default("chat", args)
    return {"ollama_chat_model": args}


# ------------------------------------------------------------- registry ---

def _nav(view: str) -> Callable[[str], dict]:
    return lambda _args: {"view": view}


for _n, _v in (("/home", "home"), ("/career", "career"), ("/clients", "clients"),
               ("/personal", "personal"), ("/memory", "memory"), ("/voice", "voice"),
               ("/automations", "automations"), ("/settings", "settings")):
    _cmd(_n, "Navigation", f"Open {_v}", _n, "", _nav(_v))

_cmd("/remember", "Memory", "Store a fact", "/remember standup is at 9am", "text", _mem_store)
_cmd("/forget", "Memory", "Delete everything about a topic", "/forget old address", "text", _mem_forget)
_cmd("/search", "Memory", "Hybrid search your memory", "/search invoice Zebra", "text", _mem_search)
_cmd("/memories", "Memory", "Counts and recent memories", "/memories", "", _mem_list)
_cmd("/task", "Tasks", "Create a task", "/task Review the PR", "text", _tasks_create)
_cmd("/tasks", "Tasks", "List inbox tasks", "/tasks", "", _tasks_list)
_cmd("/done", "Tasks", "Complete a task by id or title", "/done 42", "id or title", _tasks_done)
_cmd("/mission", "Automation", "Plan and create a mission", "/mission plan my week", "text", _mission_new)
_cmd("/missions", "Automation", "List missions", "/missions", "", _mission_list)
_cmd("/run", "Automation", "Run an automation now", "/run morning brief", "name or id", _auto_run)
_cmd("/status", "System", "System status", "/status", "", _status)
_cmd("/backup", "System", "Take a backup now", "/backup", "", _backup)
_cmd("/models", "System", "Show installed local models", "/models", "", _models)
_cmd("/health", "System", "Health plus database size", "/health", "", _health)
_cmd("/logs", "System", "Recent activity log", "/logs", "", _logs)
_cmd("/think", "AI", "One local-model answer, no tools, no memory write", "/think why is CI red", "text", _think)
_cmd("/ask", "AI", "Ask a specific model", "/ask llama3.1 summarise my day", "model + text", _ask)
_cmd("/switch", "AI", "Switch the local chat model", "/switch llama3.1:8b", "model", _switch)

_BY_NAME = {c["name"]: c for c in CATALOG}
CUSTOM_KEY = "slash_custom"


def _custom() -> list[dict]:
    try:
        v = prefs.get(CUSTOM_KEY)
    except Exception:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []


def custom() -> list[dict]:
    return [dict(c) for c in _custom()]


def save_custom(name: str, prompt: str, view: str = "") -> dict:
    name = (name or "").strip()
    if not name.startswith("/"):
        raise ValueError("custom command name must start with /")
    if any(ch.isspace() for ch in name):
        raise ValueError("custom command name cannot contain spaces")
    if name in _BY_NAME:
        raise ValueError(f"{name} is a built-in command")
    if not (prompt or "").strip():
        raise ValueError("custom command needs a prompt")
    rows = [c for c in _custom() if c.get("name") != name]
    rows.append({"name": name, "prompt": prompt.strip(), "view": (view or "").strip()})
    prefs.set_many({CUSTOM_KEY: json.dumps(rows)})
    return rows[-1]


def delete_custom(name: str) -> None:
    rows = [c for c in _custom() if c.get("name") != name]
    prefs.set_many({CUSTOM_KEY: json.dumps(rows)})


def all_commands() -> list[dict]:
    """Catalog + custom, with the Python handlers stripped — this crosses HTTP."""
    out = [{k: v for k, v in c.items() if k != "handler"} for c in CATALOG]
    for c in _custom():
        out.append({"name": c.get("name", ""), "category": "Custom",
                    "summary": str(c.get("prompt", ""))[:80],
                    "example": c.get("name", ""), "arg": "text"})
    return out


def parse(text: str) -> tuple[dict | None, str]:
    """(command, raw_args). command is None when this is not a command."""
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, ""
    head, _, rest = t.partition(" ")
    args = rest.strip()
    if len(args) >= 2 and args[0] == args[-1] and args[0] in "\"'":
        args = args[1:-1]
    cmd = _BY_NAME.get(head)
    if cmd is not None:
        return cmd, args
    for c in _custom():
        if c.get("name") == head:
            return {"name": head, "category": "Custom", "summary": str(c.get("prompt", ""))[:80],
                    "example": head, "arg": "text", "handler": None, "custom": c}, args
    return None, ""


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)[:4000]
    except (TypeError, ValueError):
        return str(value)[:4000]


def execute(text: str) -> dict:
    """Run a command. Never raises — a bad command is a result, not a 500."""
    none = {"handled": False, "ok": False, "command": "", "result": None, "text": "", "view": None}
    cmd, args = parse(text)
    if cmd is None:
        return none
    name = cmd["name"]
    if cmd.get("custom"):
        c = cmd["custom"]
        return {"handled": True, "ok": True, "command": name,
                "result": {"prompt": c.get("prompt")}, "text": str(c.get("prompt", "")),
                "view": c.get("view") or None}
    try:
        result = cmd["handler"](args)
    except ValueError as e:
        return {"handled": True, "ok": False, "command": name, "result": None,
                "text": str(e), "view": None}
    except Exception as e:  # noqa: BLE001 — surface it, never crash the chat stream
        return {"handled": True, "ok": False, "command": name, "result": None,
                "text": f"{type(e).__name__}: {e}"[:200], "view": None}
    return {"handled": True, "ok": True, "command": name, "result": result,
            "text": _as_text(result),
            "view": result.get("view") if isinstance(result, dict) else None}
```

- [ ] **Step 5: Write `backend/app/routes/slash.py`**

```python
"""Slash router — command catalog, execution, and custom commands."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import slash

slash_r = APIRouter(prefix="/slash", tags=["slash"])


@slash_r.get("")
def catalog():
    return {"commands": slash.all_commands()}


@slash_r.post("/execute")
def execute(body: dict):
    return slash.execute(body.get("text", ""))


@slash_r.post("/custom")
def save_custom(body: dict):
    try:
        return slash.save_custom(body.get("name", ""), body.get("prompt", ""), body.get("view", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@slash_r.delete("/custom/{name}")
def delete_custom(name: str):
    slash.delete_custom(name)
    return {"ok": True}
```

- [ ] **Step 6: Register the router and the chat hook**

`backend/app/routes/__init__.py`: add `from .slash import slash_r`, append `slash_r` to `ROUTERS`. `backend/app/domain.py`: add `slash_r` to the re-export block.

`backend/app/main.py` — add a helper next to `chat_stream` (line 197), and short-circuit before the orchestrator:

```python
def _one_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
```

Inside `chat_stream`, after the existing empty/length validation and before `gen = run_turn(...)`:

```python
    from . import slash as _slash
    if _slash.parse(body.message.strip())[0] is not None:
        return StreamingResponse(
            iter([_one_sse("slash", _slash.execute(body.message.strip()))]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
```

Confirm `json` is imported at module scope in `main.py`; add `import json` if not.

- [ ] **Step 7: Run the backend tests**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_slash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
```

Expected: 16 slash tests pass; suite is 377 + 16 = 393, `OK`. Check `test_chat_caps` and the SSE tests specifically — the `chat_stream` change is on the hot path.

- [ ] **Step 8: Write `frontend/src/slash.ts` and its test**

Create the pure module first (no React, so it is directly unit-testable):

```ts
export type SlashCommand = { name: string; category: string; summary: string; example: string; arg: string };

/** Score one command against a query. Higher is better; 0 means no match. */
function score(c: SlashCommand, q: string): number {
  if (!q) return 1;
  const n = c.name.toLowerCase();
  if (n === q) return 1000;
  if (n.startsWith(q)) return 500 - n.length;
  if (n.includes(q)) return 200 - n.length;
  if (c.summary.toLowerCase().includes(q)) return 100;
  if (c.category.toLowerCase().includes(q)) return 50;
  return 0;
}

export function matchCommands(cat: SlashCommand[], query: string): SlashCommand[] {
  const q = (query || "").replace(/^\//, "").trim().toLowerCase();
  return cat
    .map((c) => [score(c, q), c] as const)
    .filter(([s]) => s > 0)
    .sort((a, b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name))
    .map(([, c]) => c);
}

export function catalogFrom(res: unknown): SlashCommand[] {
  const out: SlashCommand[] = [];
  const cmds = (res as { commands?: unknown })?.commands;
  if (!Array.isArray(cmds)) return out;
  for (const raw of cmds) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    if (typeof r.name !== "string") continue;
    out.push({
      name: r.name, category: String(r.category || "Other"), summary: String(r.summary || ""),
      example: String(r.example || ""), arg: String(r.arg || ""),
    });
  }
  return out;
}
```

Create `frontend/src/__tests__/slash.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { matchCommands, catalogFrom, SlashCommand } from "../slash";

const CAT: SlashCommand[] = [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task Review the PR", arg: "text" },
  { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "/tasks", arg: "" },
  { name: "/remember", category: "Memory", summary: "Store a fact", example: "/remember x", arg: "text" },
  { name: "/search", category: "Memory", summary: "Hybrid search", example: "/search x", arg: "text" },
];

describe("matchCommands", () => {
  it("ranks a prefix match first — AC-CMD-001", () => {
    expect(matchCommands(CAT, "/tas")[0].name).toBe("/task");
  });

  it("ranks an exact name first", () => {
    expect(matchCommands(CAT, "/tasks")[0].name).toBe("/tasks");
  });

  it("matches a substring of the name", () => {
    expect(matchCommands(CAT, "/remem")[0].name).toBe("/remember");
  });

  it("matches on summary text", () => {
    expect(matchCommands(CAT, "/Hybrid").map((c) => c.name)).toContain("/search");
  });

  it("returns everything for a bare slash", () => {
    expect(matchCommands(CAT, "/").length).toBe(CAT.length);
  });

  it("returns nothing when there is no match", () => {
    expect(matchCommands(CAT, "/zzzz")).toEqual([]);
  });

  it("works with or without the leading slash", () => {
    expect(matchCommands(CAT, "task")[0].name).toBe("/task");
  });

  it("is stable — equal scores sort by name", () => {
    const r = matchCommands(CAT, "/task");
    expect(r.map((c) => c.name)).toEqual(["/task", "/tasks"]);
  });
});

describe("catalogFrom", () => {
  it("drops the python handler and keeps every rendered field", () => {
    const c = catalogFrom({ commands: [{ name: "/task", category: "Tasks", summary: "s", example: "e", arg: "text", handler: "x" }] });
    expect(c).toEqual([{ name: "/task", category: "Tasks", summary: "s", example: "e", arg: "text" }]);
  });

  it("survives junk input", () => {
    expect(catalogFrom(null)).toEqual([]);
    expect(catalogFrom({})).toEqual([]);
    expect(catalogFrom({ commands: [null, 3, {}] })).toEqual([]);
  });
});
```

Run it:

```bash
cd frontend && npx vitest run src/__tests__/slash.test.ts
```

Expected: 10 tests pass.

- [ ] **Step 9: Add the API surface**

`frontend/src/api.ts` — add above the `api` object:

```ts
export type SlashCommandT = { name: string; category: string; summary: string; example: string; arg: string };
export type SlashResult = { handled: boolean; ok: boolean; command: string; result: unknown; text: string; view: string | null };
```

and inside `api`:

```ts
  slash: {
    catalog: () => get<{ commands: SlashCommandT[] }>("/slash"),
    execute: (text: string) => post<SlashResult>("/slash/execute", { text }),
    saveCustom: (name: string, prompt: string, view = "") => post<{ name: string }>("/slash/custom", { name, prompt, view }),
    deleteCustom: (name: string) => del<{ ok: boolean }>(`/slash/custom/${encodeURIComponent(name)}`),
  },
```

`del` already exists at `api.ts:24` — do not add another.

Also add to the `ChatEvents` interface:

```ts
  onSlash?: (r: SlashResult) => void;
```

and in `chatStream`'s dispatch chain:

```ts
          else if (curEvent === "slash") ev.onSlash?.(d);
```

- [ ] **Step 10: Write the palette and its test**

Create `frontend/src/CommandPalette.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { SlashCommand, matchCommands } from "./slash";
import { Pill } from "./ui";

export function CommandPalette({ catalog, query, onClose, onPick }: {
  catalog: SlashCommand[];
  query: string;
  onClose: () => void;
  onPick: (c: SlashCommand) => void;
}) {
  const [q, setQ] = useState(query);
  const [sel, setSel] = useState(0);
  const results = useMemo(() => matchCommands(catalog, q), [catalog, q]);

  useEffect(() => setSel(0), [q]);
  useEffect(() => {
    if (results.length && sel >= results.length) setSel(results.length - 1);
  }, [results.length, sel]);

  return (
    <div className="cmdpalette" role="dialog" aria-label="Command palette"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <input
        className="cmdinput"
        role="combobox"
        aria-expanded="true"
        aria-label="Command"
        autoFocus
        value={q}
        placeholder="Type a command…"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
          else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, results.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); if (results[sel]) onPick(results[sel]); }
        }}
      />
      <ul className="cmdlist" role="listbox">
        {results.map((c, i) => (
          <li key={c.name} role="option" aria-selected={i === sel}
            className={`cmditem ${i === sel ? "sel" : ""}`}
            onMouseEnter={() => setSel(i)}
            onClick={() => onPick(c)}>
            <code>{c.name}</code>
            <span>{c.summary}</span>
            {c.arg ? <Pill c="blue">{c.arg}</Pill> : null}
          </li>
        ))}
        {results.length === 0 && <li className="cmdempty">No command matches “{q}”</li>}
      </ul>
      <small className="dim">↑↓ to move · Enter to run · Esc to close</small>
    </div>
  );
}
```

Create `frontend/src/__tests__/commandpalette.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CommandPalette } from "../CommandPalette";
import { SlashCommand } from "../slash";

const CAT: SlashCommand[] = [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task Review the PR", arg: "text" },
  { name: "/tasks", category: "Tasks", summary: "List inbox tasks", example: "/tasks", arg: "" },
  { name: "/remember", category: "Memory", summary: "Store a fact", example: "/remember x", arg: "text" },
];

describe("CommandPalette", () => {
  it("filters as you type and shows the arg hint — FR-CMD-003", () => {
    render(<CommandPalette catalog={CAT} query="/tas" onClose={() => {}} onPick={() => {}} />);
    expect(screen.getByText("/task")).toBeTruthy();
    expect(screen.getByText("/tasks")).toBeTruthy();
    expect(screen.queryByText("/remember")).toBeNull();
    expect(screen.getByText("text")).toBeTruthy();
  });

  it("arrow keys move the selection and Enter picks it — FR-CMD-002", () => {
    const picks: string[] = [];
    render(<CommandPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/tasks"], "second item after one ArrowDown");
  });

  it("ArrowUp does not wrap past the first item", () => {
    const picks: string[] = [];
    render(<CommandPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/task"]);
  });

  it("typing narrows the selection back to the first match", () => {
    const picks: string[] = [];
    render(<CommandPalette catalog={CAT} query="" onClose={() => {}} onPick={(c) => picks.push(c.name)} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.change(input, { target: { value: "/remem" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picks).toEqual(["/remember"]);
  });

  it("Escape closes", () => {
    let closed = 0;
    render(<CommandPalette catalog={CAT} query="" onClose={() => { closed += 1; }} onPick={() => {}} />);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(closed).toBe(1);
  });

  it("says so when nothing matches", () => {
    render(<CommandPalette catalog={CAT} query="/zzzz" onClose={() => {}} onPick={() => {}} />);
    expect(screen.getByText(/No command matches/)).toBeTruthy();
  });
});
```

- [ ] **Step 11: Wire the palette into `Composer`**

`frontend/src/ui.tsx` `Composer` (line 640). Add imports at the top of the file:

```tsx
import { CommandPalette } from "./CommandPalette";
import { catalogFrom, SlashCommand } from "./slash";
```

Add state and the catalog fetch inside `Composer`:

```tsx
  const [showCmds, setShowCmds] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [cmdCatalog, setCmdCatalog] = useState<SlashCommand[]>([]);
  useEffect(() => {
    if (!showCmds) return;
    let live = true;
    api.slash.catalog()
      .then((r) => { if (live) setCmdCatalog(catalogFrom(r)); })
      .catch(() => { if (live) setCmdCatalog([]); });
    return () => { live = false; };
  }, [showCmds]);
```

In the textarea's `onChange`, open the palette on a leading `/`:

```tsx
        onChange={(e) => {
          const v = e.target.value;
          setText(v);
          if (v.startsWith("/")) { setCmdQuery(v); setShowCmds(true); }
          else setShowCmds(false);
        }}
```

Render the palette after the `crow` div, before the emoji picker:

```tsx
      {showCmds && cmdCatalog.length > 0 && (
        <CommandPalette catalog={cmdCatalog} query={cmdQuery}
          onClose={() => setShowCmds(false)}
          onPick={(c) => {
            setShowCmds(false);
            setText(c.arg ? `${c.name} ` : c.name);
            ta.current?.focus();
          }} />
      )}
```

Add the palette CSS to `frontend/src/theme.css`:

```css
/* ---------------- slash command palette ---------------- */
.cmdpalette { position: absolute; bottom: 100%; left: 0; right: 0; z-index: 40; margin: 0 0 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.cmdinput { width: 100%; background: transparent; border: none; outline: none; color: inherit; font-size: 13px; padding: 6px 8px; }
.cmdlist { list-style: none; margin: 0; padding: 0; max-height: 240px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.cmditem { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 9px; cursor: pointer; }
.cmditem.sel { background: rgba(56, 189, 248, 0.14); }
.cmditem code { color: var(--cyan); font-size: 12px; min-width: 96px; }
.cmditem span { flex: 1; font-size: 12px; color: var(--text-dim); }
.cmdempty { padding: 8px; font-size: 12px; color: var(--text-dim); }
```

`.composer` must be `position: relative` for the absolute palette to anchor. Check the existing `.composer` rule in `theme.css` and add `position: relative;` if it is not already there.

- [ ] **Step 12: Handle the `slash` SSE event in the store**

`frontend/src/store.tsx`, in `send` (line 228):

```ts
        onSlash: (r) => {
          if (r.view) { setView(r.view); return; }
          patch({ text: r.text || "(no output)" });
        },
```

`setView` is already on the store; if it is not destructured in `send`, add it to the existing `useStore()` destructure at the top of the provider.

- [ ] **Step 13: Write the Settings cheat sheet**

Create `frontend/src/views2/commands.tsx`. `SlashCommandT` comes from `api.ts`; `useFetch` and `Field` come from `views1.tsx`:

```tsx
import { useState } from "react";
import { api, SlashCommandT } from "../api";
import { useStore } from "../store";
import { Field, useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

export function CommandsView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.slash.catalog());
  const [q, setQ] = useState("");
  const [name, setName] = useState("/");
  const [prompt, setPrompt] = useState("");
  const [target, setTarget] = useState("");

  const cmds: SlashCommandT[] = data?.commands || [];
  const needle = q.trim().toLowerCase();
  const shown = cmds.filter((c) => !needle
    || c.name.toLowerCase().includes(needle)
    || c.summary.toLowerCase().includes(needle)
    || c.category.toLowerCase().includes(needle));

  const byCat = new Map<string, SlashCommandT[]>();
  for (const c of shown) byCat.set(c.category, [...(byCat.get(c.category) || []), c]);

  const save = async () => {
    try {
      await api.slash.saveCustom(name.trim(), prompt.trim(), target.trim());
      setPrompt(""); setTarget("");
      reload();
      toast("Custom command saved", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="zap" s={20} /> Commands</h2>
        <Pill c="violet">{cmds.length} commands</Pill>
      </div>
      <div className="actionstrip">
        <input className="grow" aria-label="Search commands" value={q}
          onChange={(e) => setQ(e.target.value)} placeholder="Search commands…" />
      </div>
      {[...byCat.entries()].map(([cat, list]) => (
        <Panel key={cat} icon="zap" title={cat} sub={`${list.length} command${list.length === 1 ? "" : "s"}`}>
          {list.map((c) => (
            <Row key={c.name} icon="chev" title={<code>{c.name}</code>} sub={c.summary}
              right={c.category === "Custom"
                ? <Btn small onClick={async () => {
                    await api.slash.deleteCustom(c.name);
                    reload();
                    toast(`${c.name} deleted`, "warn");
                  }}>Delete</Btn>
                : <Pill c="blue">{c.arg || "no arg"}</Pill>} />
          ))}
        </Panel>
      ))}
      {shown.length === 0 && <Empty title="No command matches" sub="Try a different search." />}
      <Panel icon="plus" title="Add a custom command" sub="Map a slash name to a prompt">
        <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="/brief" />
        <textarea className="ta" rows={3} value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What should /brief ask AURA to do?" />
        <Field value={target} onChange={(e) => setTarget(e.target.value)}
          placeholder="Optional: jump to a view (e.g. analytics)" />
        <div style={{ display: "flex", gap: 8 }}>
          <Btn small kind="green" onClick={save}>Save command</Btn>
        </div>
        <small className="dim">
          Custom names must start with /, contain no spaces, and cannot shadow a built-in.
        </small>
      </Panel>
    </div>
  );
}
```

Mount it in `frontend/src/views2/settings.tsx`: add a `CommandsView` import and render `<CommandsView />` immediately after `</div>` of the `grid2` block, before the closing Hermes Tools `Panel` (line ~455). This satisfies `AC-CMD-003` — Settings shows every command with its category, description and example.

- [ ] **Step 14: Test the cheat sheet**

Add a `describe("CommandsView")` block to `frontend/src/__tests__/commandpalette.test.tsx`:

```tsx
vi.mock("../api", () => ({
  api: { slash: { catalog: vi.fn(), saveCustom: vi.fn(), deleteCustom: vi.fn() } },
  ago: (s: string) => s,
}));
vi.mock("../store", () => ({ useStore: () => ({ toast: vi.fn() }) }));

const FULL_CATALOG = { commands: [
  { name: "/task", category: "Tasks", summary: "Create a task", example: "/task x", arg: "text" },
  { name: "/health", category: "System", summary: "Health plus database size", example: "/health", arg: "" },
  { name: "/brief", category: "Custom", summary: "summarise my day", example: "/brief", arg: "text" },
]};
```

Assert three things: the search box narrows the list, a custom row renders a Delete button, and clicking it calls `api.slash.deleteCustom("/brief")`.

- [ ] **Step 15: Verify the frontend**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: 175 + 10 (matcher) + 6 (palette) + however many `it` blocks you wrote for `CommandsView` — at least 191, `tsc` clean.

- [ ] **Step 16: Commit**

```bash
git add backend/app/slash.py backend/app/routes/slash.py backend/app/prefs.py backend/app/routes/__init__.py backend/app/domain.py backend/app/main.py backend/tests/test_slash.py frontend/src/slash.ts frontend/src/CommandPalette.tsx frontend/src/views2/commands.tsx frontend/src/ui.tsx frontend/src/api.ts frontend/src/store.tsx frontend/src/views2/settings.tsx frontend/src/theme.css frontend/src/__tests__/slash.test.ts frontend/src/__tests__/commandpalette.test.tsx
git commit -m "feat: agentic slash commands (spec §3)

Every FR-CMD-002 command is implemented as a deterministic handler, so
/task Ship the plan creates exactly one task without spending a model call.
Nothing routes through run_turn.

parse matches only at position 0: a / mid-sentence is prose, and treating it as
a command would silently eat part of the user's sentence. A command that needs
an argument and did not get one returns a usage error, never a silent no-op.

A leading / in the chat stream short-circuits before the orchestrator, so
commands work from any client. Custom commands live in a pref key, are rejected
if they collide with a built-in or contain whitespace, and are listed in
Settings alongside every built-in."
```

---

## Task 6: Caching layer and SSE token batching (FR-PERF-003, FR-PERF-004)

**Files:**
- Create: `backend/app/cache.py`
- Modify: `backend/app/orchestrator.py` (token batching in both stream branches and the builtin replay)
- Modify: `backend/app/prefs.py` (`cache_ttl_s`, `sse_batch_ms`)
- Modify: `frontend/src/store.tsx` (handle batched tokens), `frontend/src/api.ts` (`onToken` payload)
- Test: `backend/tests/test_cache.py`, extend `backend/tests/test_incremental_streaming.py`

**Interfaces:**
- Consumes: nothing new. `orchestrator.run_turn` is the only consumer of the batcher.
- Produces:
  - `cache.TTLCache(max_entries: int = 256, ttl_s: float = 30.0)`, methods `get(key) -> Any | None`, `set(key, value) -> None`, `delete(key) -> None`, `clear() -> None`, `stats() -> dict` → `{"entries", "hits", "misses", "hit_rate", "evictions", "ttl_s"}`
  - `cache.cached(ttl_s: float = 30.0, max_entries: int = 256)` — a decorator factory using the module-level default instance
  - `orchestrator.TokenBatcher(min_interval_s: float = 0.03)` with `.add(tok: str) -> str` (returns a flush payload or `""`) and `.flush() -> str`; it is a **generator helper used inside `run_turn`**, and its flush payload is a single `token` event carrying several tokens' worth of text
  - New prefs: `cache_ttl_s: (30, "int", (0, 3600))`, `sse_batch_ms: (40, "int", (0, 500))`

**Scope, stated honestly.** `FR-PERF-003` asks for a "Redis-compatible cache" for the model catalog, health probes, session data and frequent API responses. This is a single-process app with one pooled SQLite connection; an in-process TTL+LRU cache with the same read-through semantics satisfies the requirement at zero dependency cost and zero operational surface. Redis would add a network hop and a failure mode to a system whose entire premise is "one box, one process, no external services." The `cache.py` docstring must say this, so a future reader does not read the absence of Redis as an oversight.

**What to cache, and what not to.** Two call sites only, both read-heavy and both trivially re-derivable:

- `app/ollama_sync.py` `live_list()` — an HTTP GET to Ollama. Cache for 30s.
- `app/health.py` system_status' LFM and vector probes — same reasoning.

**Do not cache** anything a mutation could invalidate: memory search, task lists, dashboards, approvals. A stale approval list is a safety problem, not a latency win.

**Batching.** `orchestrator.py:1490` and `:1503` yield one `_sse("token", …)` event per model token, and `:1583` replays a whole response in 4-word chunks. At 60+ tokens/s that is 60+ SSE frames per second, each with its own JSON envelope — wasteful on the wire and expensive in the React store, which re-renders per token. Batch to one frame per `sse_batch_ms` (default 40ms, ≈25 fps, well above the ~20 fps a typewriter effect needs to look continuous).

The `result` event is unchanged and still carries the full `text`, so nothing that reads the final answer is affected. The client's `onToken` handler appends the batched string to its accumulator exactly as it appended single tokens — **the payload shape does not change**, only its granularity. That is deliberate: no frontend contract change, no `api.ts` type change, only a coalescing step.

- [ ] **Step 1: Write the failing cache test**

Create `backend/tests/test_cache.py`:

```python
"""TTLCache unit tests — no DB, no app imports."""
import os
import tempfile
import time
import unittest

_tmp = tempfile.mkdtemp(prefix="aura-cache-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "test.db")

from app import cache  # noqa: E402


class CacheTest(unittest.TestCase):
    def test_set_get_and_miss(self):
        c = cache.TTLCache(max_entries=8, ttl_s=30)
        self.assertIsNone(c.get("k"))
        c.set("k", {"v": 1})
        self.assertEqual(c.get("k"), {"v": 1})
        self.assertEqual(c.stats()["hits"], 1)
        self.assertEqual(c.stats()["misses"], 1)

    def test_expiry(self):
        c = cache.TTLCache(max_entries=8, ttl_s=0.05)
        c.set("k", 1)
        self.assertEqual(c.get("k"), 1)
        time.sleep(0.08)
        self.assertIsNone(c.get("k"), "entry should have expired")

    def test_ttl_zero_disables_caching(self):
        c = cache.TTLCache(max_entries=8, ttl_s=0)
        c.set("k", 1)
        self.assertIsNone(c.get("k"), "ttl 0 must never return a hit")

    def test_lru_eviction(self):
        c = cache.TTLCache(max_entries=3, ttl_s=30)
        for i in range(3):
            c.set(f"k{i}", i)
        c.get("k0")
        c.set("k3", 3)
        self.assertIsNone(c.get("k1"), "k1 was least recently used and should be evicted")
        self.assertEqual(c.get("k0"), 0, "k0 was just read, so it survives")
        self.assertEqual(c.stats()["evictions"], 1)

    def test_delete_and_clear(self):
        c = cache.TTLCache(max_entries=8, ttl_s=30)
        c.set("a", 1); c.set("b", 2)
        c.delete("a")
        self.assertIsNone(c.get("a"))
        c.clear()
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.stats()["entries"], 0)

    def test_stats_shape(self):
        s = cache.TTLCache(max_entries=4, ttl_s=30).stats()
        for k in ("entries", "hits", "misses", "hit_rate", "evictions", "ttl_s"):
            self.assertIn(k, s)

    def test_hit_rate_is_zero_when_empty(self):
        self.assertEqual(cache.TTLCache(max_entries=4, ttl_s=30).stats()["hit_rate"], 0.0)

    def test_decorator(self):
        calls = []

        @cache.cached(ttl_s=30, max_entries=8)
        def expensive(x):
            calls.append(x)
            return x * 2

        self.assertEqual(expensive(2), 4)
        self.assertEqual(expensive(2), 4)
        self.assertEqual(len(calls), 1, "second call must be served from cache")
        self.assertEqual(expensive(3), 6)
        self.assertEqual(len(calls), 2, "a different key must miss")

    def test_store_survives_an_unhashable_value(self):
        c = cache.TTLCache(max_entries=4, ttl_s=30)
        c.set("k", {"nested": [1, 2, {"deep": True}]})
        self.assertEqual(c.get("k"), {"nested": [1, 2, {"deep": True}]})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_cache
```

Expected: `ModuleNotFoundError: No module named 'app.cache'`

- [ ] **Step 3: Write `backend/app/cache.py`**

```python
"""In-process TTL + LRU cache (spec §6, FR-PERF-003).

The spec asks for a "Redis-compatible cache". This is deliberately not Redis.
AURA is a single process with one pooled SQLite connection; an in-process cache
with the same read-through semantics gives the same hit rates for the data that
matters here (the Ollama model catalog and the health probes) without a network
hop, without an extra process to supervise, and without a new failure mode in a
system whose premise is "one box, one process, no external services".

Only cache what is expensive to compute and trivially re-derivable. Never cache
anything a mutation can invalidate — a stale approval list is a safety problem,
not a latency win.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

DEFAULT_MAX_ENTRIES = 256


class TTLCache:
    """Thread-safe LRU with a per-entry TTL. `ttl_s <= 0` disables reads."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES, ttl_s: float = 30.0):
        self._max = max(1, int(max_entries))
        self._ttl = float(ttl_s)
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = self._misses = self._evictions = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                self._misses += 1
                return None
            expires_at, value = hit
            if self._ttl <= 0 or time.monotonic() >= expires_at:
                self._data.pop(key, None)
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {"entries": len(self._data), "hits": self._hits, "misses": self._misses,
                    "hit_rate": round(self._hits / total, 3) if total else 0.0,
                    "evictions": self._evictions, "ttl_s": self._ttl}


_default = TTLCache()


def default_cache() -> TTLCache:
    return _default


def cached(ttl_s: float = 30.0, max_entries: int = DEFAULT_MAX_ENTRIES) -> Callable:
    """Cache a zero-arg function's return value on a per-instance TTLCache.

    Returns the decorated function unchanged on a miss, so a caller's exception
    propagates rather than being cached as a value.
    """
    store = TTLCache(max_entries=max_entries, ttl_s=ttl_s)

    def deco(fn: Callable[[], Any]) -> Callable[[], Any]:
        def wrapper() -> Any:
            hit = store.get("fn")
            if hit is not None:
                return hit
            out = fn()
            store.set("fn", out)
            return out
        wrapper.__name__ = getattr(fn, "__name__", "cached")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        wrapper.cache = store  # type: ignore[attr-defined]
        return wrapper
    return deco
```

- [ ] **Step 4: Add the two pref keys and wire the cache call sites**

In `backend/app/prefs.py` `SCHEMA`, near the observability settings (after `"retention_last_run"`, line 107):

```python
    "cache_ttl_s": (30, "int", (0, 3600)),
    "sse_batch_ms": (40, "int", (0, 500)),
```

Then add two call sites, both read-through and both trivially re-derivable.

**Call site 1 — the Ollama catalog.** `backend/app/ollama_sync.py` `live_list()` (line 96) is a blocking HTTP GET that `list_models()` (line 151) calls on every `/api/ollama/models` hit. Cache it. Add the import at the top of the file, next to the other stdlib imports:

```python
from .cache import TTLCache
```

Then rename the existing function and add the cached wrapper. Keep `_live_list_uncached` byte-for-byte as it is today — the only change to its body is the name:

```python
def _live_list_uncached(timeout: float = 4.0) -> dict:
    """GET /api/tags once. Never raises: {ok, models?|error?}."""
    try:
        r = httpx.get(f"{_base()}/api/tags", timeout=timeout)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:140]}", "base_url": _base()}
    if r.status_code != 200:
        return {"ok": False, "error": f"http {r.status_code}", "base_url": _base()}
    try:
        models = [_normalize(m) for m in (r.json().get("models") or [])]
    except (ValueError, AttributeError) as e:
        return {"ok": False, "error": f"bad /api/tags payload: {e}", "base_url": _base()}
    return {"ok": True, "models": models, "base_url": _base()}


_catalog_cache = TTLCache(max_entries=4, ttl_s=30.0)


def live_list(timeout: float = 4.0) -> dict:
    """Cached wrapper around the /api/tags probe.

    A failure result is cached too, but only briefly: Ollama restarting should
    become visible again within seconds, not after a full TTL. Retuning is a
    Settings change (`cache_ttl_s`), not a code change, so the TTL is read per
    call rather than baked in at import.
    """
    from . import prefs as _prefs
    try:
        _catalog_cache._ttl = float(_prefs.get("cache_ttl_s") or 0)
    except Exception:
        _catalog_cache._ttl = 30.0
    hit = _catalog_cache.get("tags")
    if hit is not None:
        return hit
    out = _live_list_uncached(timeout)
    _catalog_cache.set("tags", out)
    return out
```

`sync()` at line 112 also calls `live_list()`; leave it. A sync that reads a 30-second-stale catalog is harmless, because `sync()`'s own result is written to `ollama_models` and the UI shows a `stale` flag when the box is unreachable.

**Call site 2 — the health probes.** `backend/app/health.py` `_probe_lfm()` and `_probe_vector()` are two HTTP probes that `system_status()` calls on every `/api/health` hit, and the frontend polls that. Cache both behind a 30s TTL using the same rename-and-wrap pattern. Add `from .cache import TTLCache` to the imports.

`system_status()` itself must **not** be cached: it reports live DB and disk state, and a stale "disk 98% full" is exactly the kind of lie this codebase does not tell.

- [ ] **Step 5: Write the failing batching test**

Extend `backend/tests/test_incremental_streaming.py` — read it first; it already parses SSE output, so reuse its helpers. Append:

```python
class TokenBatchingTest(unittest.TestCase):
    def test_batches_until_the_interval_elapses(self):
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=0.05)
        self.assertEqual(b.add("a"), "", "first token starts a batch, not a flush")
        self.assertEqual(b.add("b"), "")
        time.sleep(0.06)
        self.assertEqual(b.add("c"), "abc", "a token past the interval flushes the buffer plus itself")
        self.assertEqual(b.flush(), "", "buffer was already flushed")

    def test_flush_emits_the_remainder(self):
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=60.0)
        b.add("x"); b.add("y")
        self.assertEqual(b.flush(), "xy")
        self.assertEqual(b.flush(), "", "flush must be idempotent")

    def test_flush_on_empty_buffer_is_empty(self):
        from app.orchestrator import TokenBatcher
        self.assertEqual(TokenBatcher().flush(), "")

    def test_concatenated_batches_equal_the_original_text(self):
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=0.0)
        toks = ["Hello", ",", " ", "world", "!"]
        out = [b.add(t) for t in toks]
        out.append(b.flush())
        self.assertEqual("".join(p for p in out if p), "".join(toks))
```

`import time` and `import unittest` must be at the top of that file; add if absent.

- [ ] **Step 6: Run it to verify it fails**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_incremental_streaming
```

Expected: `ImportError: cannot import name 'TokenBatcher'`.

- [ ] **Step 7: Add `TokenBatcher` to `orchestrator.py`**

Put it next to `_sse` (line 1074):

```python
class TokenBatcher:
    """Coalesce stream tokens into one SSE payload per interval (FR-PERF-004).

    Yielding one `token` event per model token means 60+ frames per second, each
    with its own JSON envelope and its own React re-render. Batching to ~25 fps
    is well above the rate a typewriter effect needs to look continuous, and the
    payload shape is unchanged — only its granularity. The `result` event still
    carries the complete text, so nothing reading the final answer is affected.
    """

    def __init__(self, min_interval_s: float = 0.04):
        self._min = max(0.0, float(min_interval_s))
        self._buf: list[str] = []
        self._last = 0.0

    def add(self, tok: str) -> str:
        """Buffer a token. Returns the payload to emit now, or "" to wait."""
        self._buf.append(tok)
        now = time.monotonic()
        if self._min <= 0 or (now - self._last) >= self._min:
            return self.flush()
        return ""

    def flush(self) -> str:
        if not self._buf:
            return ""
        out, self._buf = "".join(self._buf), []
        self._last = time.monotonic()
        return out
```

- [ ] **Step 8: Use it in `run_turn`**

`orchestrator.py:1489` — the local ollama branch, inside `for tok in stream:`:

```python
                    stream = model_router.ollama.chat_stream(messages, purpose=purpose)
                    batcher = TokenBatcher(_batch_interval())
                    for tok in stream:
                        token_buffer.append(tok)
                        payload = batcher.add(tok)
                        if payload:
                            yield _sse("token", {"text": payload})
                            tokens_yielded = True
                    tail = batcher.flush()
                    if tail:
                        yield _sse("token", {"text": tail})
                        tokens_yielded = True
```

`orchestrator.py:1535` — the cloud streaming branch, same shape. Create the `batcher` **before** `for backend in model_router.chain():` (around line 1481) so both branches share one cadence, and use it in place of that yield.

`orchestrator.py:1546` — the cloud non-streaming fallback, which yields the whole reply as one `token` event. It has nothing to batch; leave it alone, but make sure the shared `batcher`'s buffer is flushed before it so a partial ollama batch is not lost when the chain falls through.

`orchestrator.py:1581-1584` — the builtin replay, which emits 4-word chunks:

```python
    if not tokens_yielded:
        yield _sse("orb", {"state": "working"})
        batcher = TokenBatcher(_batch_interval())
        words = final_text.split(" ")
        for i in range(0, len(words), 4):
            chunk = " ".join(words[i: i + 4]) + (" " if i + 4 < len(words) else "")
            payload = batcher.add(chunk)
            if payload:
                yield _sse("token", {"text": payload})
        tail = batcher.flush()
        if tail:
            yield _sse("token", {"text": tail})
```

Add the interval helper next to `_parallel_steps_enabled()` (grep for it; it is the existing pattern for a pref-gated bool):

```python
def _batch_interval() -> float:
    """SSE token batch interval in seconds. 0 disables batching."""
    try:
        return max(0, int(_prefs.get("sse_batch_ms"))) / 1000.0
    except Exception:
        return 0.04
```

- [ ] **Step 9: Verify the frontend needs no change**

The `token` payload shape is unchanged — `{"text": "…"}` either way — so `api.ts`'s `onToken` and the store's `acc += t` are correct as they are. Confirm rather than assume:

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: unchanged count, `tsc` clean. If `tsc` errors on something in `api.ts`, you changed a payload shape by accident; revert that part.

Add one test to `frontend/src/__tests__/sessions.test.tsx` (or the file that mocks `chatStream`) asserting the store still accumulates correctly when `onToken` fires with a multi-token string — that is the behaviour batching depends on.

- [ ] **Step 10: Extend the benchmark**

`scripts/benchmark.py` — add a budget and a measurement for the batcher, and rename nothing:

```python
BUDGETS_MS["token_batch"] = 5
```

and in `main()`, after the existing benches:

```python
    def _batch():
        b = orch.TokenBatcher(0.0)
        for t in ("a", "b", "c", "d", "e", "f", "g", "h"):
            b.add(t)
        b.flush()
    results["token_batch"] = bench("token_batch", _batch)
```

`--ci` exits non-zero when a median exceeds its budget, so this becomes a real gate.

- [ ] **Step 11: Run everything**

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
cd frontend && npx tsc --noEmit && npx vitest run
venv/bin/python scripts/benchmark.py --ci
venv/bin/python scripts/eval_router.py
```

Expected: backend 393 + 9 cache + 4 batching = 406, `OK`. Router eval 299/299. Benchmark within budget including the new `token_batch`.

- [ ] **Step 12: Commit**

```bash
git add backend/app/cache.py backend/app/ollama_sync.py backend/app/health.py backend/app/orchestrator.py backend/app/prefs.py backend/tests/test_cache.py backend/tests/test_incremental_streaming.py scripts/benchmark.py
git commit -m "feat: in-process cache and SSE token batching (spec FR-PERF-003/004)

The cache is deliberately not Redis. AURA is one process with one pooled
SQLite connection; an in-process TTL+LRU with the same read-through semantics
gives the same hit rate for the two things worth caching (the Ollama catalog
and the health probes) without a network hop, a supervised process, or a new
failure mode. Nothing a mutation can invalidate is cached — a stale approval
list is a safety problem, not a latency win.

Token batching coalesces ~60 SSE frames per second into ~25. The payload shape
is unchanged, so the frontend contract does not move, and the result event
still carries the complete text."
```

---

## Task 7: Performance panel, E2E coverage, version bump, and spec close-out

**Files:**
- Create: `frontend/src/views2/perf.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/store.tsx`, `frontend/src/theme.css`
- Modify: `frontend/src/views2/settings.tsx` (worker pool + batching controls)
- Modify: `scripts/e2e_check.py`, `scripts/prod_check.py`
- Modify: `backend/app/config.py`, `frontend/package.json`, `package-lock.json`, `frontend/src/App.tsx`, `docs/CHANGELOG.md`
- Modify: `docs/API.md`, `docs/ROADMAP.md`, `docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md`
- Test: `frontend/src/__tests__/perf.test.tsx`

**Interfaces:**
- Consumes: `GET /api/workers` (`{stats, pool_size}`), `GET /api/workers/dead` (`{dead: [...]}`), `POST /api/workers/drain`, `GET /api/consolidation`, `POST /api/board` none.
- Produces: a `perf` view; the `docs/API.md` entries for every route added in Tasks 1-6; `APP_VERSION` = `1.16.0` everywhere it is mirrored.

- [ ] **Step 1: Write the failing frontend test**

Create `frontend/src/__tests__/perf.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PerfView } from "../views2/perf";
import { api } from "../api";

vi.mock("../api", () => ({ api: { workers: { status: vi.fn(), dead: vi.fn(), drain: vi.fn() } } }));
vi.mock("../store", () => ({ useStore: () => ({ toast: vi.fn() }) }));

const STATS = {
  stats: { queued: 2, running: 1, done: 40, dead: 1, throughput_per_min: 12, error_rate: 0.024, by_kind: { mission_tick: 40 } },
  pool_size: 3,
};

describe("PerfView", () => {
  beforeEach(() => {
    (api.workers.status as any).mockResolvedValue(STATS);
    (api.workers.dead as any).mockResolvedValue({ dead: [{ id: 7, kind: "custom", attempts: 4, max_retries: 3, last_error: "boom", updated_at: "" }] });
  });

  it("shows queue depth, throughput and error rate — FR-WRK-004", async () => {
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText(/Queued/)).toBeTruthy());
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText(/12/)).toBeTruthy();
    expect(screen.getByText(/2\.4%/)).toBeTruthy();
    expect(screen.getByText(/Pool/)).toBeTruthy();
  });

  it("lists dead letters with their error — FR-WRK-003", async () => {
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    expect(screen.getByText(/custom/)).toBeTruthy();
  });

  it("says so when the dead-letter queue is empty", async () => {
    (api.workers.dead as any).mockResolvedValue({ dead: [] });
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText(/No dead/)).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd frontend && npx vitest run src/__tests__/perf.test.tsx
```

Expected: `Failed to resolve import "../views2/perf"`.

- [ ] **Step 3: Add the API surface**

`frontend/src/api.ts`:

```ts
export type WorkerStats = { queued: number; running: number; done: number; dead: number; throughput_per_min: number; error_rate: number; by_kind: Record<string, number> };
export type DeadLetter = { id: number; kind: string; attempts: number; max_retries: number; last_error: string; updated_at: string };
```

and inside `api`:

```ts
  workers: {
    status: () => get<{ stats: WorkerStats; pool_size: number }>("/workers"),
    dead: () => get<{ dead: DeadLetter[] }>("/workers/dead"),
    drain: () => post<{ ran: number; done: number; retried: number; dead: number }>("/workers/drain"),
  },
  consolidation: {
    status: () => get<{ enabled: boolean; due: boolean; last_run: Record<string, unknown> | null }>("/consolidation"),
    run: () => post<{ scanned: number; merged: number; archived: number; rescored: number; duration_ms: number }>("/consolidation/run"),
  },
```

- [ ] **Step 4: Write `frontend/src/views2/perf.tsx`**

```tsx
import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

export function PerfView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.workers.status());
  const { data: dl } = useFetch(() => api.workers.dead());
  const [busy, setBusy] = useState(false);

  const s = data?.stats;
  const drain = async () => {
    setBusy(true);
    try {
      const r = await api.workers.drain();
      reload();
      toast(`Ran ${r.ran} job(s): ${r.done} done, ${r.retried} retrying, ${r.dead} dead`, r.dead ? "warn" : "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="cpu" s={20} /> Performance</h2>
        <Pill c="violet">Pool {data?.pool_size ?? "—"}</Pill>
      </div>
      <Panel icon="zap" title="Job queue" sub="Worker pool health">
        <Row icon="clock" title="Queued" right={<Pill c="blue">{s?.queued ?? "—"}</Pill>} />
        <Row icon="play" title="Running" right={<Pill c="violet">{s?.running ?? "—"}</Pill>} />
        <Row icon="check" title="Done" right={<Pill c="green">{s?.done ?? "—"}</Pill>} />
        <Row icon="alert" title="Dead" right={<Pill c={s?.dead ? "red" : "green"}>{s?.dead ?? "—"}</Pill>} />
        <Row icon="activity" title="Throughput / min" right={<Pill c="blue">{s?.throughput_per_min ?? "—"}</Pill>} />
        <Row icon="target" title="Error rate" right={<Pill c={s?.error_rate ? "amber" : "green"}>{((s?.error_rate ?? 0) * 100).toFixed(1)}%</Pill>} />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn small kind="violet" onClick={drain} disabled={busy}>Drain queue</Btn>
          <Btn small onClick={reload}>Refresh</Btn>
        </div>
      </Panel>
      <Panel icon="alert" title="Dead letters" sub="Jobs that exhausted their retries">
        {(dl?.dead || []).map((j) => (
          <Row key={j.id} icon="x" title={`#${j.id} ${j.kind}`}
            sub={`${j.attempts}/${j.max_retries} attempts — ${j.last_error}`} />
        ))}
        {(dl?.dead || []).length === 0 && <Empty title="No dead letters" sub="Every job settled." />}
      </Panel>
      <Panel icon="db" title="By kind" sub="Where the work comes from">
        {Object.entries(s?.by_kind || {}).map(([k, c]) => (
          <Row key={k} icon="folder" title={k} right={<Pill c="blue">{c}</Pill>} />
        ))}
        {Object.keys(s?.by_kind || {}).length === 0 && <Empty title="No jobs yet" sub="The scheduler has not run a job." />}
      </Panel>
    </div>
  );
}
```

- [ ] **Step 5: Mount the view and add its CSS**

`frontend/src/store.tsx` line 7: add `"perf"` to the `View` union. `frontend/src/App.tsx`: add the lazy import beside the others and a render branch, plus a nav entry (`{ k: "perf", icon: "cpu", label: "Performance" }`) found by grepping for the existing nav array.

No new CSS is needed — it reuses `Panel`, `Row`, `Pill`.

- [ ] **Step 6: Add the settings controls**

`frontend/src/views2/settings.tsx` — add three `SetRow`s inside the existing `Data & Privacy` `Panel`:

```tsx
          <SetRow title="Worker pool size" sub="How many jobs AURA runs at once (1-8)."
            control={<Slider value={Number(draft.worker_pool_size ?? 3)} min={1} max={8} step={1}
              onPick={(v) => set("worker_pool_size", v)} format={(v) => `${v}`} />} />
          <SetRow title="Job retries" sub="Attempts before a job is dead-lettered (0-5)."
            control={<Slider value={Number(draft.worker_max_retries ?? 3)} min={0} max={5} step={1}
              onPick={(v) => set("worker_max_retries", v)} format={(v) => `${v}`} />} />
          <SetRow title="Memory consolidation" sub="Nightly dedupe and re-scoring of your memory."
            control={<Toggle on={draft.consolidate_enabled !== false}
              onFlip={() => save({ consolidate_enabled: draft.consolidate_enabled === false })}
              label="consolidation" />} />
```

and widen the existing "Streaming replies" row's neighbours with one more:

```tsx
          <SetRow title="SSE batching" sub="Coalesce streamed tokens to cut render churn (0 = every token)."
            control={<Slider value={Number(draft.sse_batch_ms ?? 40)} min={0} max={200} step={10}
              onPick={(v) => set("sse_batch_ms", v)} format={(v) => (v === 0 ? "off" : `${v}ms`)} />} />
```

- [ ] **Step 7: Add E2E coverage**

`scripts/e2e_check.py` — add four checks before the final `print` block. Match the existing `check("name", fn)` shape; each reports its own failing line.

```python
def _t_consolidation_e2e():
    s, r, _ = req("GET", "/api/consolidation")
    assert s == 200 and {"enabled", "due", "last_run"} <= set(r), (s, r)
    s, p, _ = req("POST", "/api/consolidation/run", {})
    assert s == 200, (s, p)
    assert {"scanned", "merged", "archived", "rescored", "duration_ms"} <= set(p), p
    assert p["duration_ms"] >= 0, p
    s, g, _ = req("GET", "/api/consolidation")
    assert s == 200 and g.get("last_run"), (s, g)
check("consolidation: status + run + last_run recorded", _t_consolidation_e2e)


def _t_workers_e2e():
    s, r, _ = req("GET", "/api/workers")
    assert s == 200, (s, r)
    for k in ("queued", "running", "done", "dead", "throughput_per_min", "error_rate", "by_kind"):
        assert k in r["stats"], (k, r)
    assert 1 <= r["pool_size"] <= 8, r
    s, d, _ = req("GET", "/api/workers/dead")
    assert s == 200 and isinstance(d["dead"], list), (s, d)
    s, o, _ = req("POST", "/api/workers/drain", {})
    assert s == 200 and {"ran", "done", "retried", "dead"} <= set(o), (s, o)
check("workers: stats + dead letters + drain", _t_workers_e2e)


def _t_board_e2e():
    s, m, _ = req("POST", "/api/missions", {"goal": "e2e board probe"})
    assert s in (200, 201) and m.get("id"), (s, m)
    mid = m["id"]
    try:
        req("PATCH", f"/api/missions/{mid}", {"steps": [
            {"kind": "tool", "label": "Status", "tool": "system.status", "args": {}}]})
        s, b, _ = req("GET", "/api/board")
        assert s == 200, (s, b)
        assert [c["key"] for c in b["columns"]] == ["backlog", "running", "awaiting", "done"], b
        s, mv, _ = req("POST", "/api/board/move", {"mission_id": mid, "column": "done"})
        assert s == 200 and mv["mission"]["status"] == "cancelled", (s, mv)
        s, _, _ = req("POST", "/api/board/move", {"mission_id": mid, "column": "running"})
        assert s == 409, s
        s, _, _ = req("POST", "/api/board/move", {"mission_id": mid, "column": "nope"})
        assert s == 400, s
    finally:
        req("POST", f"/api/missions/{mid}/control", {"action": "cancel"})
check("board: columns, cancel-not-complete, 409/400 guards", _t_board_e2e)


def _t_slash_e2e():
    s, c, _ = req("GET", "/api/slash")
    assert s == 200, (s, c)
    names = {x["name"] for x in c["commands"]}
    for n in ("/task", "/health", "/remember", "/switch"):
        assert n in names, (n, sorted(names))
    assert all("handler" not in x for x in c["commands"]), "handlers must not cross HTTP"
    s, r, _ = req("POST", "/api/slash/execute", {"text": "/health"})
    assert s == 200 and r["handled"] and r["ok"], (s, r)
    s, r, _ = req("POST", "/api/slash/execute", {"text": "/remember"})
    assert s == 200 and r["handled"] and not r["ok"] and "Usage" in r["text"], (s, r)
    s, r, _ = req("POST", "/api/slash/execute", {"text": "not a command"})
    assert s == 200 and not r["handled"], (s, r)
    s, t, _ = req("POST", "/api/slash/execute", {"text": "/task e2e slash task"})
    assert s == 200 and t["ok"], (s, t)
    tid = t["result"]["task"]["id"]
    try:
        s, d, _ = req("POST", "/api/slash/execute", {"text": f"/done {tid}"})
        assert s == 200 and d["ok"] and d["result"]["task"]["status"] == "completed", (s, d)
    finally:
        req("DELETE", f"/api/tasks/{tid}")
    s, _, _ = req("POST", "/api/slash/custom", {"name": "/task", "prompt": "x"})
    assert s == 400, s
check("slash: catalog, usage error, task roundtrip, custom guard", _t_slash_e2e)
```

The slash chat-stream short-circuit also needs an SSE check, since it takes a different code path from `POST /api/slash/execute`:

```python
def _t_slash_stream_e2e():
    body = chat("/health")
    evs = sse(body)
    assert "slash" in evs, sorted(evs)
    assert evs["slash"][0]["handled"] and evs["slash"][0]["ok"], evs["slash"][0]
    # A non-command must still stream normally, not be swallowed.
    body = chat("plan my day")
    evs = sse(body)
    assert "result" in evs, sorted(evs)
check("slash: chat stream short-circuits a command, not a sentence", _t_slash_stream_e2e)
```

- [ ] **Step 8: Run the E2E suite**

```bash
cd frontend && npm run build && cd ..
AURA_DATA_DIR="$(mktemp -d)" venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend &
venv/bin/python scripts/e2e_check.py
```

Expected: 101 + 5 = 106 checks, 0 failures. Check free disk first — a full disk surfaces as a 500 on upload and looks like a code bug.

Then:

```bash
export AURA_VAPID_PUBLIC_KEY=... AURA_VAPID_PRIVATE_KEY=... AURA_VAPID_SUBJECT=mailto:...
venv/bin/python scripts/prod_check.py
```

Expected: 11/11.

- [ ] **Step 9: Bump the version everywhere**

`backend/app/config.py`: `APP_VERSION = "1.16.0"`.

Then sync every mirror, in this order:

```bash
grep -rn "1\.15\.0" backend/app/config.py frontend/package.json frontend/src/App.tsx scripts/e2e_check.py docs/CHANGELOG.md package-lock.json 2>/dev/null
```

Replace each hit with `1.16.0`. `package-lock.json` carries the version in two places (root and the `""` package entry) — replace both. Then:

```bash
cd frontend && npx tsc --noEmit && npm run build && cd ..
```

- [ ] **Step 10: Update the documentation**

`docs/API.md` — add a section per new router, in the file's existing format:

```markdown
### `GET /api/consolidation`
`{enabled, due, last_run}` — whether a consolidation pass is due and when the last one ran.

### `POST /api/consolidation/run`
Runs one pass. Returns `{scanned, merged, archived, rescored, duration_ms}`.

### `GET /api/board`
`{columns: [{key, label, missions: [{id, goal, status, steps_total, steps_done, next_run_at, created_at, updated_at}]}], counts}`

### `POST /api/board/move`
Body `{mission_id, column}`. 400 unknown column, 404 unknown mission, 409 illegal move.
Moving a backlog card to `done` **cancels** it — the only route to `done` is a mission completing.

### `GET /api/workers`
`{stats: {queued, running, done, dead, throughput_per_min, error_rate, by_kind}, pool_size}`

### `GET /api/workers/dead`
`{dead: [{id, kind, attempts, max_retries, last_error, updated_at}]}`

### `POST /api/workers/drain`
Runs queued jobs on the pool. Returns `{ran, done, retried, dead}`.

### `GET /api/slash`
`{commands: [{name, category, summary, example, arg}]}` — built-ins plus custom.

### `POST /api/slash/execute`
Body `{text}`. Returns `{handled, ok, command, result, text, view}`. `handled: false` means the text was not a command.
A leading `/` in `POST /api/chat/stream` takes this path and emits a single `slash` SSE event.

### `POST /api/slash/custom` · `DELETE /api/slash/custom/{name}`
Create and delete a custom command. 400 if the name does not start with `/`, contains whitespace, has no prompt, or shadows a built-in.
```

`docs/CHANGELOG.md` — add an `## v1.16.0` section at the top describing: memory consolidation, fact extraction from tool results, the Kanban board, the worker pool and the mission-tick fix, slash commands, the in-process cache, SSE batching, the performance panel, and the new E2E checks. Lead with the mission-tick bug — it is the most important thing in the release.

`docs/ROADMAP.md` — the P1/P2 sections are all struck through; add a short `## Shipped in v1.16.0` section listing the same items, and leave P0 item 1 (auth) untouched with its existing "deferred" note.

`docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md` — tick every remaining `- [ ]` in the Implementation TODO as `[x]` and delete the two blockquotes added in Task 0, replacing them with a single line at the top of the TODO:

```markdown
> All items closed in v1.16.0. See `docs/CHANGELOG.md`.
```

- [ ] **Step 11: Full verification**

Run every gate in order. Do not run the backend suite and vitest concurrently.

```bash
venv/bin/python -m compileall -q backend/app
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests && cd ..
cd frontend && npx tsc --noEmit && npx vitest run && npm run build && cd ..
venv/bin/python scripts/eval_router.py
venv/bin/python scripts/eval_agent.py --no-record
venv/bin/python scripts/benchmark.py --ci
venv/bin/python scripts/migration_check.py --self-test
venv/bin/python scripts/prod_check.py
```

With a live backend and a built frontend:

```bash
AURA_DATA_DIR="$(mktemp -d)" venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend &
venv/bin/python scripts/e2e_check.py
```

Then the browser pass — component tests do not prove the UI renders:

```bash
venv/bin/python -c "import playwright; print('playwright ok')"
```

Drive a real browser against the live backend and confirm: the `/` palette opens in the Composer and `/task` executes; the board renders four columns and a drag is refused from Finished; the performance panel shows live queue numbers; Settings shows the commands cheat sheet and the new worker sliders; and the browser console is clean.

Finally, the container — the image uses a different directory layout than the checkout, so a passing local run proves nothing about the image:

```bash
docker build -t aura-test .
docker run -d --name aura-test -p 8010:8000 aura-test
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8010/     # must be 200, not 404
docker rm -f aura-test
```

- [ ] **Step 12: Update `AGENTS.md` test counts**

The test-count line in `AGENTS.md` ("344 unit", "175 frontend", "101 E2E", "11/11") is now wrong. Update it to the counts Step 11 produced, and add one line to the Gotchas section recording the mission-tick lesson:

```markdown
- **A background function is not wired until something calls it.** `missions.tick_missions()`
  and `tick_schedules()` had no call sites outside tests, so missions never advanced in
  production while the suite stayed green. When you add a periodic function, grep for its
  callers from `app/` — not from `tests/` — and assert the wiring in a test that reads the
  scheduler source, since a sleeping daemon thread cannot be exercised directly.
```

- [ ] **Step 13: Commit**

```bash
git add frontend/src/views2/perf.tsx frontend/src/api.ts frontend/src/App.tsx frontend/src/store.tsx frontend/src/views2/settings.tsx frontend/src/__tests__/perf.test.tsx scripts/e2e_check.py scripts/prod_check.py backend/app/config.py frontend/package.json package-lock.json docs/API.md docs/CHANGELOG.md docs/ROADMAP.md AGENTS.md docs/superpowers/specs/2026-09-26-aura-comprehensive-enhancement.spec.md
git commit -m "feat(v1.16.0): performance panel, E2E coverage, docs

Adds a live queue panel, settings for the worker pool, retries, consolidation
and SSE batching, five E2E checks for the new subsystems, and the API/CHANGELOG
/ROADMAP entries. Closes every open item in the 2026-09-26 spec.

AGENTS.md now records the lesson this release was built on: a periodic function
is not wired until app/ calls it."
```

---

## Self-Review

**1. Spec coverage.** Every requirement in the spec's Implementation TODO maps to a task:

| Spec item | Task | Notes |
|---|---|---|
| Add memory consolidation job | 1 | new `consolidate.py`, daily-gated, exposed over HTTP |
| Add fact extraction pipeline | 2 | tool results; chat text was already covered |
| Implement Kanban mission status endpoints | 3 | `board_r`, columns derived from existing statuses |
| Add slash command router | 5 | all 27 `FR-CMD-002` commands |
| Implement worker pool with queue | 4 | persistent queue, retry, dead-letter |
| Add scheduled job runner | 4 | the scheduler existed; the mission tick did not |
| Add caching layer | 6 | in-process TTL+LRU, Redis-equivalent semantics |
| Optimize SSE streaming | 6 | token batching, shape unchanged |
| Slash command palette in Composer | 5 | `CommandPalette.tsx` |
| Kanban board with drag-drop | 3 | `views2/kanban.tsx` |
| Commands cheat sheet in Settings | 5 | `views2/commands.tsx`, mounted in settings |
| Add performance monitoring | 7 | `views2/perf.tsx` |
| Unit tests: consolidation | 1 | 6 tests |
| Unit tests: command parser | 5 | 16 tests |
| Integration tests: Kanban API | 3 | 7 tests |
| E2E: slash commands | 7 | 2 checks, incl. the SSE path |
| E2E: chat UX | 0, verified in 7 | already shipped; re-run, not rewritten |
| Load tests: worker pool | 4 | concurrency, priority, backoff, recovery tests |
| Performance benchmarks | 6 | `token_batch` added to `benchmark.py --ci` |

`FR-MEM-001`, `FR-MEM-002`, `FR-MEM-004` (cross-session retrieval, user memory controls) were already satisfied by the existing `memories` schema, `memory.search` and the Memory panel. `FR-CMD-001..005` are all covered in Task 5. `FR-WRK-001..005` in Task 4. `FR-PERF-001`/`002` were already shipped. `FR-PERF-005` (LRU for embeddings) is partly satisfied by the existing embedding-migration path in `memory.search`; the full LRU is a separate change and is not claimed here.

**2. Placeholder scan.** No step says "TBD", "add appropriate error handling", "write tests for the above", or "similar to Task N". Every code step shows the code. Two places flag a value for the implementer to compute at write time and say so explicitly (Task 1's `scanned` count, Task 5's test counts) — both are quantities only observable after the suite runs.

**3. Type consistency.** Names used across tasks, checked for drift:

- `SlashCommand` (backend, `slash.py`) and `SlashCommandT` (frontend, `api.ts`) and `SlashCommand` (frontend, `slash.ts`) — deliberately distinct because they are different declarations in different languages; `slash.ts` exports its own and `api.ts` exports the API-facing one. `CommandPalette` imports from `slash.ts`; `views2/commands.tsx` imports `SlashCommandT` from `api.ts`. Consistent as written.
- `run_pass` returns the same five keys in `consolidate.py`, `/api/consolidation/run`, the backend test, and the E2E check.
- `stats()` returns the same seven keys in `workers.py`, `/api/workers`, `WorkerStats` in `api.ts`, the backend test, and the E2E check.
- `execute()` returns the same six keys in `slash.py`, the `slash` SSE event, and `SlashResult` in `api.ts`.
- `scheduler_pass()` returns a dict with `automations`, `schedules`, `missions`, optional `consolidation`, `jobs` — the test asserts on `missions`, the docstring and Task 4's commit message describe the rest.
- `TokenBatcher(min_interval_s)` / `.add(tok) -> str` / `.flush() -> str` — identical in the implementation, the unit test, and all three call sites in `run_turn`.
- `BoardMission` fields match `_card()` in `kanban.py` exactly, and the E2E check asserts `mission.status`.

**One deliberate correction to the spec's own wording:** `FR-CMD-002` lists `/home` under "Navigation" but also `/ask` and `/switch` under "AI"; the categories in `slash.CATALOG` are the six the test asserts (`Navigation`, `Memory`, `Tasks`, `Automation`, `System`, `AI`), which is a superset of the spec's grouping and keeps the cheat sheet filterable.

---

## Execution Order and Checkpoints

Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7, in that order, each committed separately. Task 4 is the highest-value fix and could be pulled forward if you want the mission bug closed first — its Steps 1-2 and 6 are self-contained and nothing later depends on the rest of the pool work.

**Full-suite checkpoint after every task.** A task is not done until the whole backend suite and the whole frontend suite are green. A "pre-existing failure" is not an excuse; if a test fails, the behaviour is unimplemented.

**Final checkpoint is Task 7 Step 11** — every gate, plus a real browser, plus the Docker image. Component tests do not prove the UI renders, and a local run does not prove the image serves it.
