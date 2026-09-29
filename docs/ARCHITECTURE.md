# AURA OS — Architecture

```
┌─────────────┐   SSE    ┌──────────────────────────────────────────────┐
│  React SPA  │◄────────►│ FastAPI (main.py) ─ chat · CRUD · files ·     │
│  Three orb  │  /api/*  │ voice · backup · hermes · SPA hosting        │
└─────────────┘          └──────┬───────────────┬───────────────┬───────┘
                                │               │               │
                    ┌───────────▼────┐  ┌──────▼────────┐  ┌───▼──────────┐
                    │ orchestrator.py │  │  domain.py    │  │  health.py   │
                    │ intent→plan→   │  │  11 CRUD      │  │  real probes │
                    │ tools→approve→ │  │  routers      │  │  + metrics   │
                    │ generate       │  └───────────────┘  └──────────────┘
                    └──────┬─────────┘
              ┌────────────┼────────────────────────┐
              ▼            ▼                        ▼
     ┌────────────┐ ┌──────────────┐        ┌──────────────┐
     │ hermes.py  │ │ inference.py │        │  memory.py   │
     │ 23 tools   │ │ Ollama LFM → │        │ FTS5 + 192-d │
     │ skills,    │ │ builtin      │        │ hashed vec + │
     │ scheduler, │ │ composer     │        │ BM25 rerank  │
     │ gateway bus│ │ (fallback)   │        │ write pipe   │
     └─────┬──────┘ └──────────────┘        └──────┬───────┘
           │                                      │
           └──────────────┬───────────────────────┘
                          ▼
              ┌───────────────────────┐
              │ SQLite (WAL) · db.py  │  single pooled conn + RLock
              │ 58 tables · FTS index │  users…audit (see below)
              └───────────────────────┘
```

## Request flows

**Chat turn** (`POST /api/chat/stream`): classify intent (ordered regex rules,
first match wins) → load session + last turns + domain context → build plan
(labeled steps, each bound to a Hermes tool or pseudo-tool) → execute with
per-step SSE events → pause at `__approval__` if drafts exist (skip when
empty) → generate: Ollama LFM when healthy, else builtin grounded composer →
persist messages, touch session title/`updated_at` → write outcome memories →
SSE `result` + `done`.

**Approval**: `comms.draft_followups` builds drafts → `__approval__` step
inserts the row + emits `approval` event → user edits/approves in the UI →
`POST /approvals/{id}/resolve` sends via `comms.send` on the stored channel,
persists `drafts_sent`, notifies, logs activity.

**Automation tick** (daemon thread, 30s): due rows (`next_run <= now`,
active) fire by `action_kind` — `notify` (notification), `backup`
(snapshot), `chat` (brief activity) — then success/fail counters update.

**Backup/restore**: `sqlite3.backup()` online snapshot + uploads tarball →
sha256 recorded. Restore validates tarball → `PRAGMA integrity_check` +
table check → safety-copies live DB → `db.reset()` + file swap + WAL cleanup
→ reconnect → restores missing uploads → activity log.

## Data model (SQLite, single file)

| Group | Tables |
|---|---|
| Identity | `users`, `integrations` |
| Conversation | `sessions`, `messages` |
| Memory | `memories` (+`memories_fts`), `files` (indexed_text) |
| Work | `tasks`, `clients`, `projects`, `milestones`, `timeblocks` |
| Career | `resumes`, `applications`, `interviews` |
| Personal | `journal`, `goals`, `expenses`, `habits`, `sleep_logs` |
| Ops | `automations`, `activity`, `notifications`, `approvals`, `backups`, `runs`, `toolcalls`, `audit`, `push_subscriptions` |
| Gateway | `gateway_events` — the canonical inbound/outbound message feed behind `/api/gateway/status` `events[]`; `activity` stays the human-readable audit log |

Conventions: `user_id` default 1 (single-user), UTC ISO-8601 timestamps,
soft-delete for memories (`deleted_at`), JSON sidecars (`*_json`) for
semi-structured payloads. Schema is idempotent (`CREATE TABLE IF NOT
EXISTS` + `INSERT OR IGNORE`); the one true migration so far
(`embedding_model` on `memories`) runs as a guarded `ALTER TABLE` in
`init_db`, backfilling legacy rows as `hashed:192`.

## Key decisions

- **SQLite + WAL as the source of truth.** One file, zero ops, online
  backups. A single pooled connection behind an RLock keeps threads safe;
  writers are serialized, readers are fast enough for a personal OS.
- **Privacy-ordered inference chain.** `AURA_PRIVACY` selects the backend
  order — `local-first`: Ollama → builtin; `hybrid`: Ollama → cloud →
  builtin; `cloud`: cloud first. **Unknown modes fail closed to local-first,
  and `local-first` never contains `cloud` and never even constructs a cloud
  client** — picking a cloud model requires explicitly switching privacy to
  `hybrid`/`cloud`. The builtin grounded composer is always last, so AURA
  answers with zero models. Cloud calls use an OpenAI-compatible endpoint with
  withheld sensitive memories + scrubbed grounding, and every answer is
  labeled with its engine.
- **Real delivery, explicit opt-in.** `providers.py` implements Telegram Bot
  API, SMTP, Discord/Slack webhooks, and a generic WhatsApp-provider POST
  behind per-platform `sandbox|live` modes. Sandbox is the default and makes
  no network calls; live requires validated credentials and surfaces all
  failures.
- **Edge hardening in-process.** `limits.py` adds per-IP sliding-window rate
  limits and security headers as middleware; payload caps are enforced at the
  route layer (`413`s). Safe-exposure still wants a TLS + auth proxy in
  front (see OPERATIONS).
- **Tagged embeddings + lazy migration.** Every vector records its maker
  (`embedding_model`: `hashed:192` vs `ollama:nomic-embed-text`). When the
  active embedder differs, search re-embeds ≤5 stale rows per query, so an
  old DB converges to Ollama vectors without downtime or a batch job.
  FTS5/BM25 carries recall during the transition.
- **Drop-in plugin tools.** `load_plugins()` imports `app/plugins/*.py` and
  `$DATA_DIR/plugins/*.py` (manifest + `run`), enforcing the `plugin.*`
  prefix, R0–R2 risk ceiling, and builtin-name protection. Idempotent
  (hot-reload safe), failure-isolated, reported in `/api/tools`.
- **PWA + Web Push.** Manifest + generated icons + a service worker that
  cache-firsts the app shell (never `/api/*`) and renders push payloads.
  `push.py` fans out with VAPID, pruning 410s; automation `notify` calls it
  best-effort so push can never break a run.
- **Optional server voice.** `voice.py` lazy-loads faster-whisper + Piper
  (models under `data/models`), returning `503` with install hints when
  the optional deps are absent. Routes cap input; TTS returns raw WAV.
- **Litestream as a deployment concern.** Replication lives in
  `litestream.yml` + `entrypoint.sh`, not in app code — the app only
  reports replica state. Off by default; enabling is one env var.
- **Risk-gated tools.** R0 reads, R1 local writes, R2+ external actions.
  The HTTP passthrough refuses R2+ outright; R2 only executes inside an
  approved resolution. Gateway *delivery* to real provider APIs is
  deliberately future work — today sends are audited records, never silent.
- **Voice at the edge.** STT/TTS run in the browser (Web Speech API); the
  server only audits transcripts. No audio storage, no cloud voice bill.
- **Seeded, not empty.** First boot creates a believable workspace (clients,
  projects, tasks, memories) so every view and journey is demonstrable;
  seeding only fires on a completely empty DB and never re-fires.

## Frontend notes

React 18 + Three.js (orb) + Vite, no router library — view state lives in a
typed store (`store.tsx`) with an SSE-aware `send()`, mic-level tracking, and
toasts. `api.ts` is the single typed client. Styling is one design-system
file (`theme.css`); mobile collapses the sidebar into a bottom nav. A top-level
error boundary guarantees a recoverable screen instead of a crash. Production
`dist/` is served by the backend itself (SPA fallback), so deployment is one
process on one port.
