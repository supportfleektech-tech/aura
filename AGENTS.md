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
- To start from the repo root instead, use `venv/bin/python -m uvicorn app.main:app --app-dir backend`. Anything that resolves a path relative to CWD will break there — that is how plugins silently failed to load. Prefer CWD-independent code.

**Repo root** (evals need backend deps):

```bash
venv/bin/python -m compileall -q backend/app
venv/bin/python scripts/eval_router.py
venv/bin/python scripts/eval_agent.py --no-record
venv/bin/python scripts/eval_agent.py --no-record --case ID
```

- Router/agent evals require 100%. Update `backend/tests/router_cases.json` / `agent_cases.json` before changing routing/tools/composition.
- `--no-record` prevents writes to dev DB.
- **`e2e_check.py` and `prod_check.py` are CI gates** (the `e2e` job), not optional extras. They need a live backend on :8000 and a built frontend. E2E mutates data — use a scratch `AURA_DATA_DIR`. `prod_check` needs VAPID keys (`scripts/gen_vapid.py` generates a throwaway pair). Both report the failing source line, so a bare `✗` still tells you where to look.

**Frontend** (from `frontend/`):

```bash
npm ci
npx tsc --noEmit && npx vitest run && npm run build
npm run dev  # :5173, proxies /api to :8000 (start backend first)
```

- No separate lint/format; CI uses `tsc` + `build`. Backend CI uses `compileall`.
- Node `^20.19.0 || ^22.13.0 || >=24.0.0` required. Vite 8 + `@vitejs/plugin-react@6`; plugin-react 4 causes `ERESOLVE`.
- **Keep `vite.config.ts` proxy `changeOrigin: false`** — `guard.py` compares browser `Origin` host (incl. port) with `Host`; rewriting breaks PATCH onboarding/settings with 403. Use `AURA_ALLOWED_ORIGINS` for exceptions, not `AURA_CORS`.
- `testTimeout` is 20 s in `vitest.config.ts` on purpose — a heavy `SettingsView` render exceeds the 5 s default under load.
- `venv` has Playwright + Chromium, so a real browser pass against a live backend is available (console errors, breakpoints, a11y, chat). Component tests do not prove the UI renders.

## Key Architecture (v1.15+)

- **Backend routers** live in `app/routes/` (22 modules). `app/domain.py` is a thin re-export shim — hermes.py tool system references functions via `_lazy(".domain", "func_name")` and `_wrap_model(".domain", "func_name", "ModelName")`, so every name must be accessible from `app.domain`.
- **Frontend views2** split into `src/views2/` (7 modules + barrel `index.ts`). All `import { X } from "./views2"` continue to work via the barrel.
- **Kokoro TTS + Personality** — Offline engine (`af_heart` default) in `backend/app/voice.py`; 4 controls (warmth/humour/style/pacing) wired via `inference.py`. `scripts/download_kokoro.py` fetches 136 MB to `DATA_DIR/models/kokoro/`.
- **MCP connection manager** — Streamable HTTP endpoints in `backend/app/mcp_connections.py` with DNS pinning, byte caps, redirect blocking, per-tool enablement, confirmation flow, credential isolation.
- **Memory retrieval** — Union of 30 ranked FTS + 400 recent; embedding fallback fixed. Tests: `backend/tests/test_memory_retrieval.py`.
- **Frontend lazy loading** — Views + Three.js lazy-loaded; main chunk ~258 kB (was 863 kB).

## Wiring & Pitfalls

- `main.py` mounts `domain.ROUTERS` under `/api`, initializes/seeds DB, starts scheduler. Chat → `orchestrator.run_turn`; Hermes owns tool execution/approval.
- Settings (`prefs.py`) resolve **DB override > env > code default**; changing env may not change existing profile.
- `data/` = real user storage; never delete for tests or commit. `AURA_DB_PATH` alone doesn't relocate uploads/backups.
- SQLite: one pooled connection, WAL + RLock. Restore swaps DB file and resets connection; never retain connection across restore.
- Schema changes → `schema.sql`; existing columns need guarded `ALTER` in `db.init_db()`. `scripts/migration_check.py` compares committed Git refs (not working tree); `--self-test` is Git-free. Destructive drops need `[allow-destructive-schema]` in commit msg.
- Version source: `backend/app/config.py:APP_VERSION`. Sync with `frontend/package.json`, `frontend/src/App.tsx`, E2E text, `docs/CHANGELOG.md`, `package-lock.json`.
- Plugins: `backend/app/plugins/` + `$DATA_DIR/plugins/`; `plugin.*`, stdlib-only, in-process (no sandbox). A plugin exports `TOOL_MANIFEST` + `run(args, ctx)` — that signature *is* enforced, but the `R0–R2` risk ceiling is **convention only**; the loader accepts anything in `RISK_ORDER`. See `docs/PLUGINS.md`.
- Single-user, no login. OriginGuard ≠ auth; preserve mutation guards, rate limits, webhook HMAC; don't assume public exposure safe.

## Invariants (breaking these reintroduces fixed bugs)

- **Hermes tool adapters.** `execute_tool` calls `tool.fn(args_dict, ctx)`. A tool registered with `_lazy(".mod", "fn")` passes the **whole args dict as `fn`'s first positional parameter** — wrong whenever `fn` is not literally `(a: dict, ctx: dict)`. These are dead tools that fail only at call time. When `fn`'s real signature differs (e.g. `web.fetch(url)`, `career.interview_questions(job_description, role)`), write a `_tool_*(a, ctx)` adapter and register that instead. Check: `hermes.execute_tool(name, {}, {})` must return `ok=True` for every R0/R1 tool.- **`ModelRouter.chain()` is the privacy boundary.** `local-first` must **never** contain `"cloud"`, and must not even construct a cloud client (tests assert `get_cloud_client` is not called). Data only leaves the machine in `hybrid`/`cloud`.
- **Cloud grounding is redacted.** `filter_cloud_memories` must run before cloud messages are built; `redacted_memories` in the `result` SSE event reports the count. Never send `messages` to a provider unfiltered.
- **Automation actions are validated before they are persisted** (`hermes.validate_action`). Webhook URLs must be `https` — or `http` to a loopback host only, so a same-box integration works without letting cleartext leave the machine. Terminal actions are refused when `terminal.classify` says `dangerous`; home `entity_id` must match `domain.object_id`; script actions must resolve to a real script. Validate in `_t_automation_create` and again on `PATCH /api/automations/{id}` against the *merged* config.
- **Three automation fire paths exist and all must record.** `tick_automations()` (scheduled, due via `next_run`) and `fire_event()` (feed/file triggers, which have `next_run IS NULL`). Feeds and the watcher must call `fire_event`, never `_fire_one` — `_fire_one` alone skips counters and the audit trail.
- **`_next_run(trigger, kind)`** returns `None` for every non-`schedule` kind. Event/manual/feed/file triggers are one-shot; giving them a timestamp makes the scheduler re-fire them forever.
- **`terminal.exec_command` is the terminal safety boundary** — it classifies, refuses `dangerous` unless `Settings → Terminal → allow dangerous`, and audits every exec. Do not add a second approval gate in `orchestrator.run_turn`; it made chat terminal commands unusable without adding protection.
- **`comms.send` order is load-bearing:** dry-run check *first* (and never consumes the dedup fingerprint), then dedup, then the provider. Reversing it lets a preview suppress the real send.
- **`prefs.get(key)` takes exactly one argument**; defaults live in `prefs.SCHEMA`. Passing a second arg raises `TypeError` at runtime.
- `run_turn` is a **generator of SSE strings** (`event: …\ndata: …`), consumed by `main.py` and `vloop.py`. It closes the upstream LLM stream in a `finally`, so a client hang-up releases the provider connection.
- **Response shapes are a contract with three consumers**: the frontend `api.ts` types, `orchestrator`'s memory harvest, and `scripts/e2e_check.py`. A route returning `{tasks: …}` where the rest of the system reads `{overdue: …}` silently empties the list everywhere — this has already happened once. When changing a response, grep for the old key first.
- **Every registered route must be reachable and match its typed client.** `POST /projects/{id}/milestones` had a handler function but no decorator, so the frontend call 404'd. `emit_gateway` returned a dict while its caller read `.event_id`, 500-ing `/api/gateway/simulate`. Check both ends.
- **Plugins are discovered from `Path(__file__).parent / "plugins"`**, never a CWD-relative path — the relative form loaded zero plugins whenever the server was started from anywhere but `backend/`.
- `frontend/dist` is located by probing both the source-checkout and container layouts (`_resolve_dist()` in `main.py`), or via `AURA_FRONTEND_DIST`. A single `parent.parent.parent` assumption silently produces an image with no UI.
- Undefined-name bugs are invisible until a rare branch runs. After touching a module, re-run the AST check for unbound names (it has already caught `missions.py` and `orchestrator.py` misses that no test covered directly).

## Test Quirks

- **Run single test**: `AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest tests.test_aura.AuraTest.test_task_create_echoes_title`
- **Full backend suite must be fully green (344 tests).** A "pre-existing failure" excuse is not acceptable — if a test fails, the behaviour is unimplemented, not the test optional. Compare against a clean `git worktree` at the target commit before calling anything a regression. Skips drop from 2 to 1 once `requirements-voice.txt` (edge-tts) is installed.
- Frontend: 175/175 Vitest tests pass (jsdom; `api.test.ts` runs in Node).
- E2E script: 101/101. `prod_check`: 11/11 (1 benign warn — no backup archive yet). `pip-audit` and `npm audit --omit=dev`: clean.
- Router eval: 299/299 (100%) when Ollama available.
- **Agent eval: 33/33 (100%)** — requires real Ollama with `llama3.1:8b` model for full pass.
- Do **not** run `backend -m unittest` and `npx vitest` concurrently — both saturate the box and heavy component renders hit their timeout. Run them sequentially.

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

# Full backend suite (the real gate)
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 ../venv/bin/python -m unittest discover -s tests

# Prod check (needs VAPID keys in env)
export AURA_VAPID_PUBLIC_KEY=... AURA_VAPID_PRIVATE_KEY=... AURA_VAPID_SUBJECT=mailto:...
venv/bin/python scripts/prod_check.py

# E2E + prod build (live backend on :8000, frontend built)
cd frontend && npm run build && cd ..
AURA_DATA_DIR="$(mktemp -d)" venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend &
venv/bin/python scripts/e2e_check.py
```

> **Check free disk before e2e/prod runs.** A full disk surfaces as
> `500 Internal Server Error` on file upload, which looks exactly like a code bug
> but is not one.

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

## Gotchas not covered above

- **Verify the container actually serves the UI**: `docker build . && docker run -p 8010:8000 …`, then assert `GET /` is 200 — not just `GET /api/health`. The image uses a different directory layout than the checkout.
- **When you change a response shape, grep the old key** across `frontend/src/api.ts`, `backend/app/orchestrator.py`, and `scripts/e2e_check.py` — all three read the same payloads.
- `scripts/e2e_check.py` prints `@file.py:NN` for a failed bare assert; read that line instead of guessing which step broke.
- `parse_sleep_text` expects `"slept 11pm to 6am"` or `"log sleep 7.5 hours"`.
- `start.sh` (untracked) starts backend + Vite dev server together for local work.
