# AURA OS — Your AI Multimodal Sidekick

A persistent **local-first AI operating system** for work, clients, projects,
memory, automation, and personal life — with a 3D Aura Orb command center,
hybrid memory, a Hermes Agent execution runtime, and approval-gated actions.
No account, no telemetry, no model download required.

## Quickstart

**Docker (recommended)** — UI + API as one service on :8000:

```bash
docker compose up --build -d
# open http://localhost:8000
# optional neural LFM: docker compose --profile lfm up -d && docker compose exec ollama ollama pull llama3.1
```

**Local dev** — backend :8000 + hot-reload UI :5173:

```bash
cd backend && pip install -r requirements.txt && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm install && npm run dev
```

Then press **Ctrl/⌘+K** and try `plan my day`. Full guide: [docs/SETUP.md](docs/SETUP.md).

## What works end-to-end

- **Ask AURA** — intent → memory retrieval → tool plan → streamed answer
  (SSE), with plan stepper, tool activity, memory citations, run tracing.
- **Day planning** — overdue-first priorities + AI time-blocking + briefs.
- **Client follow-ups** — overdue detection → drafts → **R2 approval card**
  (edit inline) → gateway send → activity + notifications.
- **Meeting prep** — who they are (memories) + open items, one command.
- **Resume optimization** — paste/upload → ATS score + JD gaps + versioned
  analyses → export.
- **Interview prep** — role-aware question banks + scored practice log.
- **Voice** — browser STT → act → TTS playback, mic-level orb pulse; **optional server Whisper STT + Piper TTS** (record/upload/speak panels); **Call mode** — ChatGPT-style hands-free conversation: continuous listening, live captions, barge-in, spoken replies, auto-summary saved to memory.
- **Terminal & machines** — audited shell on your own machine (safe/guarded/dangerous classifier, footguns refused, cwd control, full `terminal_runs` log) + named **ssh** targets with TCP liveness checks; **saved scripts** run from the UI, chat (“run my backup script”) or automations — danger-gated at save AND every run; drive it by hand too: “run `git status` in my terminal”.
- **Drop-zone watch** — point AURA at a folder (default `<data>/inbox`): dropped files get parsed, indexed into memory, announced, and can trigger `file` automations; scans are scheduled, deduped by mtime+size, and honestly reported.
- **Security** — cross-site mutation guard (no-login fortress: foreign `Origin` POSTs 403), webhook HMAC signatures, SSRF-safe fetches, write journal + undo, dry-run everywhere.
- **Model Room** — every Ollama model on the box synced with size/quantization/capability badges; one tap to make it the chat/vision/embeddings model; auto-refreshes in the background.
- **Memory** — FTS5 + vector hybrid search with rerank, edit/forget/export; **Ollama embeddings by default with lazy migration**.
- **Automations** — schedule/event/manual/**feed** triggers → notify/backup/brief/
  **webhook** (signed POST + backoff retry)/**terminal**/**home** actions, run-now,
  history, success rates. Unattended terminal actions refuse dangerous commands.
- **Gateway** — 6 platforms (Telegram, Discord, Slack, WhatsApp, Email, Home Assistant): sandbox/live modes, validated credentials,
  live tests, inbound simulation, audited sends, approval-gated delivery.
- **Backups** — one-click snapshot + uploads archive with SHA-256, plus
  verified one-click **restore**.
- **Diagnostics** — 13 real service probes (incl. Model Room, Terminal, Feeds, Weather) + runs/tools/disk metrics; off-states stay honest, never “broken”.
- **Sleep** — `slept 11pm to 6am` → logged + dashboard insight + trends.
- **Files** — PDF/DOCX/XLSX/PPTX parsed and memory-indexed on upload.
- **PWA + push** — installable app, offline shell, VAPID push for automation
  alerts (Settings toggle + test).
- **Plugins** — drop-in `plugin.*` tools (manifest + risk), 2 examples.
- **i18n** — Swahili-first UI (Settings → Lugha), auto-detect.
- **Feeds & weather, no keys** — RSS/Atom watcher (guid dedupe, notifications, brief lines, automation triggers) + Open-Meteo forecasts with umbrella warnings.
- **Sync-ready** — Litestream replica config (one env var, S3/R2/file).

## Project structure

```
aura-os/
  backend/app/    FastAPI: chat SSE, 12 CRUD routers, files, voice, backup,
                  orchestrator (intent→plan→tools→approval→generate),
                  hermes (26 risk-gated tools + plugins, skills, scheduler,
                  gateway bus, webhooks), memory (FTS5 + tagged vectors +
                  lazy migration + rerank), inference (privacy-ordered
                  Ollama → cloud → builtin), extract, push, voice, health
  backend/tests/  80-test suite + router_cases.json (211 utterances)
  scripts/        e2e_check.py (54 live checks) · eval_router.py · gen_vapid.py
  frontend/src/   React + Three.js: orb, shell, palette, 11 views, voice, theme,
                  i18n (en/sw), PWA (manifest + sw + icons), 30 Vitest tests
  data/           SQLite + uploads + backups (created on boot, git-ignored)
  docs/           setup · user · commands · api · architecture · operations ·
                  testing · roadmap · changelog · plugins
  Dockerfile docker-compose.yml
```

## Docs

| Doc | Read it for |
|---|---|
| [SETUP.md](docs/SETUP.md) | Install, Docker, Ollama, env vars, troubleshooting |
| [USER_GUIDE.md](docs/USER_GUIDE.md) | Tour, voice, approvals, automations, backups |
| [CHAT_COMMANDS.md](docs/CHAT_COMMANDS.md) | Every chat command + examples |
| [API.md](docs/API.md) | Full endpoint + SSE reference |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, flows, data model, decisions |
| [OPERATIONS.md](docs/OPERATIONS.md) | Security, backups, monitoring, maintenance |
| [TESTING.md](docs/TESTING.md) | Test layers, E2E script, CI snippet |
| [ROADMAP.md](docs/ROADMAP.md) | Honest gap analysis: what it still needs |

## Tests

```bash
cd backend && python3 -m unittest        # 80 tests: temp DB, ~2s
python3 scripts/eval_router.py           # 211 utterances, must be 100%
python3 scripts/e2e_check.py             # 54 live checks vs running :8000
cd frontend && npm test && npm run build # 30 Vitest + tsc + bundle
```

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `AURA_DATA_DIR` | `./data` | SQLite + uploads + backups |
| `AURA_DB_PATH` | `$AURA_DATA_DIR/aura.db` | SQLite file |
| `AURA_USER_NAME` / `ROLE` / `LOCATION` | Antony / Builder… / Nairobi, Kenya | Profile |
| `AURA_CORS` | `*` | `*` open, or comma-sep origins to lock down |
| `AURA_PRIVACY` | `local-first` | `local-first` / `hybrid` / `cloud` inference chain |
| `AURA_CLOUD_PROVIDER` | `openrouter` | `openrouter` / `openai` / `custom` |
| `AURA_OPENROUTER_API_KEY` / `AURA_OPENROUTER_MODEL` | _(empty = off)_ / `google/gemma-4-31b-it:free` | OpenRouter free models |
| `AURA_CLOUD_API_KEY` / `BASE_URL` / `MODEL` | _(empty = off)_ | OpenAI-compatible fallback |
| `AURA_CUSTOM_BASE_URL` / `_MODEL` / `_KEY` | _(empty)_ | Custom OpenAI-compatible endpoint |
| `AURA_CHAT_RPM` / `API_RPM` / `UPLOAD_RPM` | `120/600/30` | Per-IP rate limits |
| `AURA_VAPID_PUBLIC_KEY` / `_PRIVATE_KEY` | _(empty = push off)_ | `scripts/gen_vapid.py` |
| `AURA_WHISPER_MODEL` / `AURA_PIPER_VOICE` | `tiny` / `en_US-lessac-medium` | Server voice (optional deps) |
| `AURA_LITESTREAM_REPLICA` | _(empty = off)_ | Continuous DB replication |
| `OLLAMA_BASE_URL` / `OLLAMA_CHAT_MODEL` | localhost:11434 / llama3.1 | Local LFM |
| `OLLAMA_EMBED_MODEL` | nomic-embed-text | Optional better embeddings |
| `HERMES_VERSION` | 2.0.0 | Pinned runtime API |

Smarter. Healthier. More Productive. — **AURA OS**
