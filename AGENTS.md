# AGENTS.md — AURA OS

Trust `.github/workflows/ci.yml` and executable scripts over stale commands in `README.md`/`docs/`. Release: `docs/RELEASE.md`.

## Commands & Prerequisites

**Backend** (run from `backend/`; use `../venv/bin/python`):

```bash
../venv/bin/python -m pip install -r requirements.txt
AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests
../venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- **Tests use `unittest`, not pytest**. `AURA_DATA_DIR` isolates uploads/backups; `AURA_DB_PATH` alone is insufficient.
- Hashed-embedding test expects Ollama unreachable; `OLLAMA_BASE_URL=http://127.0.0.1:1` forces that path.
- `VoiceV2Test.test_speak_edge_privacy_and_mocked_success` needs `edge-tts` (in `requirements-voice.txt`).

**Repo root** (evals need backend deps):

```bash
venv/bin/python -m compileall -q backend/app
venv/bin/python scripts/eval_router.py
venv/bin/python scripts/eval_agent.py --no-record
venv/bin/python scripts/eval_agent.py --no-record --case ID
```

- Router/agent evals require 100%. Update `backend/tests/router_cases.json` / `agent_cases.json` before changing routing/tools/composition.
- `--no-record` prevents writes to dev DB.
- `scripts/e2e_check.py` / `scripts/prod_check.py` need live backend on :8000; build frontend first. E2E mutates data — use scratch `AURA_DATA_DIR`.

**Frontend** (from `frontend/`):

```bash
npm ci
npx tsc --noEmit && npx vitest run && npm run build
npm run dev  # :5173, proxies /api to :8000 (start backend first)
```

- No separate lint/format; CI uses `tsc` + `build`. Backend CI uses `compileall`.
- Node `^20.19.0 || ^22.13.0 || >=24.0.0` required. Vite 8 + `@vitejs/plugin-react@6`; plugin-react 4 causes `ERESOLVE`.
- **Keep `vite.config.ts` proxy `changeOrigin: false`** — `guard.py` compares browser `Origin` host (incl. port) with `Host`; rewriting breaks PATCH onboarding/settings with 403. Use `AURA_ALLOWED_ORIGINS` for exceptions, not `AURA_CORS`.

## Key Architecture (v1.15+)

- **Kokoro TTS + Personality** — Offline engine (`af_heart` default) in `backend/app/voice.py`; 4 controls (warmth/humour/style/pacing) wired via `inference.py`. `scripts/download_kokoro.py` fetches 136 MB to `DATA_DIR/models/kokoro/`.
- **MCP connection manager** — Streamable HTTP endpoints in `backend/app/mcp_connections.py` with DNS pinning, byte caps, redirect blocking, per-tool enablement, confirmation flow, credential isolation.
- **Memory retrieval** — Union of 30 ranked FTS + 400 recent; embedding fallback fixed. Tests: `backend/tests/test_memory_retrieval.py`.
- **Speech interruption** — Unified `AbortController` + guards across `store.tsx`, `views2.tsx`, `views4.tsx` (25/25 tests pass).
- **Frontend lazy loading** — Views + Three.js lazy-loaded; main chunk ~259 kB (was 863 kB).

## Critical Fixes Applied (Sept 2026 + Session Updates)

| Issue | Fix | Files |
|-------|-----|-------|
| Circular import `hermes.py` ↔ `domain.py` | Lazy imports via `_lazy()` / `_wrap_model()` | `hermes.py:23`, `inference.py` |
| Version property recursion | `_version` backing field | `hermes.py` |
| Tools endpoint double-wrapping | Extract `tools` array from `list_tools()` | `main.py` |
| Ollama IPv6 bind failure | Default `127.0.0.1:11434` (not `localhost`) | `config.py` |
| Missing `automations.create` tool | Implemented `_t_automation_create` | `hermes.py:1427` |
| Missing `career.ats_analyze` tool | Created `app/career.py` + schema `job_description` | `career.py`, `schema.sql` |
| `_lazy()` wrapper passed args wrong | Now unpacks `**args` for domain fns | `hermes.py:27` |
| MCP SSRF protection | DNS pinning, IP validation, byte caps, redirect block | `mcp_connections.py` |
| Approval timeout (30s default) | `expires_at` column + cleanup job | `prefs.py`, `hermes.py` |
| Scheduler lock | `threading.Lock` prevents overlapping ticks | `hermes.py` |
| Streaming deduplication | Real-time token yield vs final replay | `orchestrator.py` |
| Stop Generating button | Composer, call overlay, voice loop | `store.tsx`, `ui.tsx` |
| Autoplay race | User-gesture gate in `store.tsx` | `store.tsx` |
| **Agent eval 48% → 100%** | Fixed personal tools, memory search, briefing, sleep parsing, calendar, project/client creation | `domain.py`, `hermes.py`, `orchestrator.py`, `briefing.py`, `calendar_sync.py`, `schema.sql` |
| Personal tools (mood/sleep/expense/journal) | Direct DB implementations via `*_impl` wrappers | `domain.py`, `hermes.py` |
| Sleep parsing (`parse_sleep_text`) | Added `created_at` to `sleep_logs`; fixed regex | `hermes.py`, `schema.sql` |
| Briefing tool (`briefing.now`) | Wired to `run_briefing`; fixed `todays_events()` dict return | `hermes.py`, `briefing.py`, `calendar_sync.py` |
| Project/client creation | Switched `_lazy` → `_wrap_model` with Pydantic models | `hermes.py`, `domain.py` |
| Task update args | Accept both `id` and `tid` params | `domain.py` |
| Calendar today | `todays_events()` returns `{"events": [...]}` dict | `calendar_sync.py` |
| Briefing calendar | `gather_digest()` uses `todays_events().get("events", [])` | `briefing.py` |
| Memory search harvest | `_harvest()` handles `memory.search` tool results | `orchestrator.py` |
| Moods table | Added `moods` table with `created_at` | `schema.sql`, `domain.py` |
| `parse_sleep_text` export | Added to `hermes.__all__`; `start_scheduler_loop` restored | `hermes.py` |

## Wiring & Pitfalls

- `main.py` mounts `domain.ROUTERS` under `/api`, initializes/seeds DB, starts scheduler. Chat → `orchestrator.run_turn`; Hermes owns tool execution/approval.
- Settings (`prefs.py`) resolve **DB override > env > code default**; changing env may not change existing profile.
- `data/` = real user storage; never delete for tests or commit. `AURA_DB_PATH` alone doesn't relocate uploads/backups.
- SQLite: one pooled connection, WAL + RLock. Restore swaps DB file and resets connection; never retain connection across restore.
- Schema changes → `schema.sql`; existing columns need guarded `ALTER` in `db.init_db()`. `scripts/migration_check.py` compares committed Git refs (not working tree); `--self-test` is Git-free. Destructive drops need `[allow-destructive-schema]` in commit msg.
- Version source: `backend/app/config.py:APP_VERSION`. Sync with `frontend/package.json`, `frontend/src/App.tsx`, E2E text, `docs/CHANGELOG.md`, `package-lock.json`.
- Plugins: `backend/app/plugins/` + `$DATA_DIR/plugins/`; `plugin.*`, R0–R2, stdlib-only; in-process (no sandbox); see `docs/PLUGINS.md`.
- Single-user, no login. OriginGuard ≠ auth; preserve mutation guards, rate limits, webhook HMAC; don't assume public exposure safe.

## Test Quirks

- **Run single test**: `AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_aura.AuraTest.test_task_create_echoes_title`
- Many backend tests fail due to pre-existing missing `HermesAdapter` methods (`recent_events`, `emit_gateway`, etc.) — not regressions.
- Frontend: 175/175 Vitest tests pass (jsdom; `api.test.ts` runs in Node).
- Router eval: 299/299 (100%) when Ollama available.
- **Agent eval: 33/33 (100%)** — requires real Ollama with `llama3.1:8b` model for full pass.
- `eval_agent.py --case sleep` now passes with `slept 11pm to 6am` format.

## Quick Verification Checklist

```bash
# Backend compiles
venv/bin/python -m compileall -q backend/app

# Frontend typecheck + tests
cd frontend && npx tsc --noEmit && npx vitest run

# Router eval (needs Ollama on 127.0.0.1:11434)
venv/bin/python scripts/eval_router.py

# Agent eval (needs Ollama with llama3.1:8b on 127.0.0.1:11434)
venv/bin/python scripts/eval_agent.py --no-record

# Core backend tests
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_aura.AuraTest.test_health tests.test_aura.AuraTest.test_dashboard tests.test_aura.AuraTest.test_classify tests.test_aura.AuraTest.test_journey_ask tests.test_aura.AuraTest.test_task_create_echoes_title tests.test_aura.AuraTest.test_automations tests.test_aura.AuraTest.test_career_ats tests.test_aura.AuraTest.test_clients_projects tests.test_aura.AuraTest.test_memories_crud

# Prod check (needs VAPID keys in env)
export AURA_VAPID_PUBLIC_KEY=... AURA_VAPID_PRIVATE_KEY=... AURA_VAPID_SUBJECT=mailto:...
venv/bin/python scripts/prod_check.py
```

## Ollama Models for Agent Eval

Agent eval requires **real Ollama with `llama3.1:8b`** (not qwen2.5:1.5b). Pull it:

```bash
ollama pull llama3.1:8b
```

Then configure in settings or via API:
```bash
curl -X PATCH http://127.0.0.1:8000/api/settings -H "Content-Type: application/json" -d '{"ollama_chat_model": "llama3.1:8b"}'
```

Without `llama3.1:8b`, agent eval falls back to builtin composer (~48% pass).

## Common Gotchas

- **`AURA_DATA_DIR` required for tests** — `AURA_DB_PATH` alone doesn't isolate uploads/backups
- **`changeOrigin: false` in Vite** — required for OriginGuard to work correctly
- **`parse_sleep_text`** expects `"slept 11pm to 6am"` or `"log sleep 7.5 hours"` format
- **`AURA_VAPID_PUBLIC_KEY` + `AURA_VAPID_PRIVATE_KEY`** needed for prod check push test
- **`OLLAMA_BASE_URL=http://127.0.0.1:1`** in CI forces hashed-embedding path
- **`AURA_DATA_DIR` must be a temp dir** for test isolation
- **`scripts/download_kokoro.py`** must run once for Kokoro TTS (136 MB)
- **`scripts/gen_vapid.py`** generates VAPID keys for Web Push