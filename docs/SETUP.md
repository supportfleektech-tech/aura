# AURA OS — Setup Guide

Get AURA running in under 5 minutes. Pick **Docker** (simplest) or **local dev**
(fastest iteration). No model download is required: AURA ships with a grounded
builtin engine and upgrades to Ollama automatically when reachable.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ (3.12 in Docker) | Backend |
| Node.js | 20+ | Frontend build/dev |
| Docker + Compose | 24+ | Optional, recommended for prod |
| Ollama | any recent | Optional, for local neural LFM |
| RAM / disk | 2 GB / 1 GB free | +4 GB if you add Ollama models |

## Option A — Docker (recommended)

```bash
cd aura-os
docker compose up --build -d
# open http://localhost:8000  (API + UI served as one service)
```

Data persists in the `aura-data` volume (`/data` in the container).
Logs: `docker compose logs -f aura`. Stop: `docker compose down`
(add `-v` to wipe data too).

Verify the UI is actually being served — `GET /` must return 200, not just
`GET /api/health`. The image uses a different directory layout than a source
checkout, so a bad `frontend/dist` path yields a healthy API with no UI.

**Add the local LFM (optional, ~4 GB download):**

```bash
docker compose --profile lfm up -d
docker compose exec ollama ollama pull llama3.1
# AURA detects Ollama within seconds — no restart needed.
```

## Option B — Local development

```bash
# 1. backend  →  http://localhost:8000
cd aura-os/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. frontend  →  http://localhost:5173  (proxies /api → :8000)
cd aura-os/frontend
npm install
npm run dev

> Note: `package.json` pins dev-only `expect-type` to 1.4.0 via `overrides`
> (vitest wants ^1.5.0, whose tarball some registry mirrors lack). Safe to
> drop the override on a full registry.
```

## Option C — Single-service production (no Docker)

```bash
cd aura-os/frontend && npm install && npm run build
cd ../backend && pip install -r requirements.txt
AURA_DATA_DIR=/var/lib/aura python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://SERVER:8000 — backend serves frontend/dist itself
```

Run it under systemd/supervisor for restarts; point `AURA_DATA_DIR` at a
backed-up disk.

## First run

1. Open the app — first boot seeds demo clients, projects, tasks and memories
   (only when the database is completely empty).
2. Press **Ctrl/⌘+K** and try `plan my day`.
3. Open **Clients → Backup Manager** and click **Run Backup Now** — verify a
   snapshot appears with a `sha256:…` note.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `AURA_DATA_DIR` | `./data` | SQLite + uploads + backups root |
| `AURA_DB_PATH` | `$AURA_DATA_DIR/aura.db` | SQLite file (override for tests) |
| `AURA_USER_NAME` | `Antony` | Profile display name |
| `AURA_USER_ROLE` | `Builder · Creator · Optimiser` | Profile role line |
| `AURA_USER_LOCATION` | `Nairobi, Kenya` | Profile location |
| `AURA_CORS` | `http://localhost:5173,http://localhost:3000` | Extra allowed origins (comma-sep) |
| `AURA_PRIVACY` | `local-first` | Recorded on runs; enforcement is future work |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local LFM endpoint |
| `OLLAMA_CHAT_MODEL` | `llama3.1` | Chat model name |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model (optional upgrade) |
| `AURA_CLOUD_API_KEY` | _(empty)_ | Reserved for a future cloud fallback |
| `AURA_CLOUD_MODEL` | _(empty)_ | Reserved for a future cloud fallback |
| `HERMES_VERSION` | `2.0.0` | Pinned Hermes runtime API |
| `AURA_VAPID_PUBLIC_KEY` / `_PRIVATE_KEY` | _(empty = push inert)_ | Web Push keys — `python3 scripts/gen_vapid.py` |
| `AURA_VAPID_SUBJECT` | `mailto:aura@localhost` | VAPID contact claim |
| `AURA_WHISPER_MODEL` | `tiny` | Server STT model (`tiny`/`base`/…; needs `requirements-voice.txt`) |
| `AURA_PIPER_VOICE` | `en_US-lessac-medium` | Server TTS voice (downloaded on first use to `data/models`) |
| `AURA_LITESTREAM_REPLICA` | _(empty = off)_ | e.g. `s3://bucket/aura/aura.db`; enables restore-on-boot + replication |
| `AURA_CHAT_RPM` / `AURA_API_RPM` / `AURA_UPLOAD_RPM` | `120` / `600` / `30` | Per-IP rate limits |
| `AURA_MAX_REQUEST_MB` / `AURA_MAX_UPLOAD_MB` / `AURA_MAX_CHAT_CHARS` / `AURA_MAX_ATTACHMENTS` | `128` / `25` / `50000` / `10` | Payload caps |
| `PORT` | `8000` | Only used by `python -m app.main` directly |

## Optional upgrades

**Ollama (neural replies + better embeddings).** Install Ollama, `ollama pull
llama3.1` (and optionally `nomic-embed-text`), ensure it listens on
`OLLAMA_BASE_URL`. AURA probes it continuously: System status flips Local LFM
to online and answers upgrade from the builtin composer to neural generation
(grounded on the same retrieved tools + memories). If Ollama stops, AURA falls
back silently — nothing breaks.

**ChromaDB (persistent vector collections).** `pip install chromadb` in the
backend env. Without it AURA uses a built-in 192-dim hashed-embedding +
SQLite vector store, which is fine for tens of thousands of memories.

**Server voice (Whisper STT + Piper/Edge TTS).** `pip install -r
backend/requirements-voice.txt`, restart. Models download on first use into
`data/models` (~75MB whisper `tiny` + ~60MB piper voice; Edge Neural needs
no model). Check `GET /api/voice/status`; Voice view shows Server STT/TTS
panels when ready. Browser voice keeps working regardless.

**Human-like voices.** Settings → Voice picks the engine: Browser (instant,
on-device), Piper (fast local server voices), or Edge Neural — free
Microsoft neural voices including Kenyan English (Chilemba, Asilia) and
Kiswahili (Rafiki, Zuri), no API key needed. Edge sends text to Microsoft,
so it requires Hybrid/Cloud privacy (local-first blocks it honestly).
Emotions (neutral/cheerful/calm/excited/serious/sad) act fully on the Edge
US voices and adjust tone everywhere else; Smart breaks adds natural
sentence/paragraph pauses. Use Test voice to preview.

**Web Push.** `python3 scripts/gen_vapid.py` → set the two keys (+ subject),
restart, open Settings → Push Notifications → Enable. Automation
`notify` actions then fan out to subscribed devices (even with the tab
closed, once installed as a PWA). Serve over HTTPS (or localhost) —
browsers require a secure context for push.

**Litestream replication (multi-device / crash safety).** Set
`AURA_LITESTREAM_REPLICA=s3://…` (+ S3 creds) in Docker; the entrypoint
restores on boot if the DB is missing and wraps uvicorn in
`litestream replicate` (10s sync, 72h retention). `litestream.yml` at the
repo root holds the config. Backup history shows replica state.

**Cloud fallback (neural answers without local GPU).** Set `AURA_PRIVACY=hybrid`,
`AURA_CLOUD_API_KEY`, and optionally `AURA_CLOUD_BASE_URL`/`MODEL` (any
OpenAI-compatible provider: OpenAI, Groq, DeepSeek, OpenRouter…). Chain becomes
Ollama → cloud → builtin; `local-first` (default) never touches the network
even with a key set. Cloud grounding withholds `sensitive`/`private` memories
and scrubs credential patterns; every cloud answer is labeled (`model:
cloud/…`) and logged. Verify: System status shows `cloud: ready`, and
`result.engine == "cloud"` on chat turns.

**Cloud cost controls.** Every model call (chat, briefing, triage, session
summaries, connection tests) is journaled with tokens, cost, and purpose.
Settings → Cloud costs shows today/month spend, per-model breakdown, and
daily/monthly USD caps (`0` = unlimited, UTC day). When a cap is hit, cloud
calls fail closed — chat falls back to Ollama/builtin instead of spending.
OpenRouter pricing comes from the live catalog; `:free` models and Ollama
record $0; anything with unknown pricing keeps its tokens with a NULL cost
and is flagged `unknown_pricing` rather than shown as free.

**Image understanding.** Attach images to chat (`{"file_id": N}` from an
upload, ≤3 per turn) or press **Analyze** on any image in Files. AURA
describes with the Ollama vision model (`ollama_vision_model`, default
`llava` — pull one with `ollama pull llava`) first, cloud vision second when
the privacy mode allows it, and otherwise says vision is unavailable instead
of guessing. Toggle: Settings → Profile & Local LFM → Image understanding.
Descriptions persist in `vision_results` (originals stay untouched in
`files`) and are indexed into memory; spend shows under Cloud costs with
purpose `vision`.

## Verification checklist

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 \
  ../venv/bin/python -m unittest discover -s tests   # 344 tests
cd ../frontend && npx tsc --noEmit && npx vitest run && npm run build
python3 scripts/e2e_check.py                         # 101 live checks vs :8000
curl -s localhost:8000/api/health                    # {"ok": true, ...}
```

`AURA_DATA_DIR` is required for tests (it relocates DB, uploads and backups);
`AURA_DB_PATH` alone is not enough. Full details and the CI gate list are in
[TESTING.md](TESTING.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `address already in use :8000` | Another backend is running: `pkill -f "uvicorn app[.]main"` then restart |
| `address already in use :5173` | `pkill -f "vite.*5173"` or use `npm run preview` (:4173) |
| Blank page on :5173 | Backend not running (API proxy fails) — start backend first |
| `Local LFM: degraded` | Normal without Ollama — builtin engine is active; install Ollama to upgrade |
| `npm ci` fails in Docker | Needs `package-lock.json` (present in repo); don't delete it |
| DB looks wrong / reseed | Stop backend, `rm -rf data/aura.db*`, restart (fresh seed) |
| Backups filling disk | Prune `data/backups/aura-backup-*.tar.gz` (keep the newest few) |
| `chromadb` import errors | Optional dep — AURA works without it; uninstall or ignore |
| Permission denied on `/data` | `chown -R $(id -u) /path/to/data` or run Docker as your user |

## Updating

```bash
git pull
cd backend && pip install -r requirements.txt        # new deps, if any
cd ../frontend && npm install && npm run build
# restart the backend; SQLite schema migrates itself (CREATE IF NOT EXISTS)
```
