# AURA OS — Changelog

## v1.15.0 — 2026-09-14 — Fortress hardening: origin guard, script library, drop-zone watch

- **Cross-site request guard (security, important)**: with no login and
  `CORS=*`, any web page opened in your browser could previously `POST` to
  the local API — including the v1.14 `/api/terminal/exec`. `OriginGuardMiddleware`
  (outermost layer) now rejects every state-changing `/api/*` request whose
  `Origin` names a foreign host: drive-by and DNS-rebinding attacks get a 403
  before touching anything. Same-origin app traffic and origin-less
  server-to-server callers (webhooks, curl, monitors) are unaffected;
  extra front-origins go through `AURA_ALLOWED_ORIGINS`. E2E proves both the
  block and the pass-through.
- **Named script library (`scripts.py`)**: recurring commands become `scripts`
  rows (name, command, machine, description). The danger gate runs at save
  AND at every run; `{placeholder}` args are shell-quoted at fill time (a
  hostile arg is refused by the classifier anyway — defense in depth).
  Endpoints `/api/scripts` CRUD + `/{id}/run`; tools `scripts.list|run|save`;
  automation **action kind `script`** (unknown script → 400 at creation);
  chat: “run my backup-prod script” resolves through the script-aware
  `__terminal_or_script__` plan step. The Terminal screen gains a Scripts
  panel (run, delete, counters, inline last output).
- **Folder watch (`watch.py`)** — the drop-zone integration: enable in
  Settings, point AURA at directories (default `<data>/inbox`), the scheduler
  scans every `watch_scan_interval_s`; new/changed files are registered as
  files, text-extracted and **memorized** (`watch_ingest`), announced, and
  fire automations with **trigger kind `file`** (contains/pattern match on
  name+path). `watched_files` keeps path+size+mtime so a file only re-triggers
  when it really changes; `POST /api/watch/scan` + `reset` for manual control;
  Files screen hosts the panel.
- **Machine liveness**: `GET /api/terminal/check?machine=x` — a 1.5s TCP
  probe (host:port parsed from the ssh target) answering “is the machine even
  there?” without touching credentials; “Check” button per machine row.
- **`disk_low` proactive detector**: the volume holding the DB, uploads and
  backups dropping under ~10 GB (or 8%) surfaces as an opportunity with the
  real numbers; self-clears when space frees up.
- **Voice & terminal QoL**: Recent Calls panel on the Voice screen (duration,
  turns, summary, delete, “Start a call”), and ↑/↓ command recall in the
  Terminal input seeded from the audit history.
- **Bug fixes**
  - `_next_run` scheduled `feed`-kind automations daily *in addition to*
    event firing — event kinds (`manual|event|feed|file`) now all stay
    one-shot (unit + e2e assertions).
  - e2e approval case collided with the 60s comms dedupe on quick re-runs —
    recipients are now unique per run and the assertion honestly accepts a
    dedupe as proof of the pipeline.
- Gates: backend 261/261, vitest 85/85 (20 files), TSC clean, E2E 101 PASS,
  router 299/299, agent 27/27, benchmark all-in-budget, prod 11/0/1.

## v1.14.0 — 2026-09-14 — The Machine Room: terminal, Ollama sync, calls, feeds, weather

Everything AURA needs to reach *the machine itself*, wired end-to-end.

- **Ollama model sync (the Model Room)**: `backend/app/ollama_sync.py` reads
  `GET {ollama_base_url}/api/tags`, normalizes every model on the machine
  (size, parameter count, quantization, family) and *infers capabilities*
  (chat / vision / embed / tools) from a curated family table. The catalog is
  cached in SQLite (`ollama_models`) so the room still shows the last-known
  inventory when Ollama sleeps (flagged `stale`, never a lie). Scheduler
  auto-sync (`ollama_auto_sync`, `ollama_sync_interval_min`). New endpoints
  `/api/ollama/status|models|sync|default`; the Model Room screen lists every
  model with one-tap *use for chat / vision / embeddings* (validated against
  the catalog — unknown names are refused). `ollama_embed_model` is now a
  real setting that actually drives `OllamaClient.embed` (was env-only).
- **Terminal — run commands & scripts on your machine (and beyond)**:
  `backend/app/terminal.py` executes through `/bin/sh -lc` as your user with
  a three-tier classifier (`safe` read-only allowlist with subcommand checks
  — `git status` yes, `git clean -fd` no; `guarded` anything else;
  `dangerous` footguns like `rm -rf /`, `mkfs`, `dd of=/dev/…`, fork bombs,
  `curl|sh` — **refused** unless `terminal_allow_dangerous`). Dry-run
  previews never execute. Every run is audited in `terminal_runs` (source,
  exit code, duration, output size) — denials included. Remote machines:
  named **ssh targets** (`terminal_machines`, `ssh -o BatchMode=yes`, key
  auth only, host strings validated against an allow-pattern). New `system.run`
  Hermes tool (R3 — visible in chat, excluded from unattended mission
  planning), `terminal_run` chat intent ("run `git status` in my terminal"),
  backtick/`terminal:` command extraction, and a full Terminal screen
  (machine picker, cwd control, output pane, execution log, quick commands).
- **Automations × terminal × home**: two new action kinds — `terminal`
  (dangerous commands rejected at *creation*, always, even with the global
  allow-on) and `home` (validated Home Assistant `domain.service` +
  entity_id). Plus a new automation **trigger kind `feed`** — RSS items
  matching a keyword fire the rule the moment they're discovered.
- **RSS/Atom feeds (`feeds.py`)** — the zero-credential integration: follow
  any feed URL (suggested: HN frontpage, Lobsters, BBC World), stdlib parser
  (RSS 2.0 + namespaced Atom), guid dedupe, per-feed honest `error` field,
  auto-refresh on the scheduler (`feeds_refresh_min`), new-item notifications
  and a morning-brief digest line. Chat: "what's on my feeds?"
  (`feeds_latest`) and "follow <url>" (`feed_follow`). Feeds screen + `feeds.latest`/
  `feeds.follow` tools.
- **Weather without a key (`weather.py`)**: Open-Meteo current + 3-day
  outlook from your lat/lon (Settings → Weather), 15-min cache, umbrella
  warning in morning briefs, `weather.now` tool + `weather` chat intent.
  Unconfigured/unreachable → honest `{ok: false, reason}` — never a fake
  temperature.
- **Voice Call mode (ChatGPT-advanced-voice style, hands-free)**: full-screen
  call overlay — continuous Web Speech listening while idle, live captions,
  barge-in (start talking and AURA stops mid-sentence), spoken replies via
  your TTS engine (browser / piper / edge), mute, timer. Ends → transcript
  POSTs to `/api/voice/calls`, is summarized (`calls.py`, model router with
  a deterministic digest fallback) and lands in memory so call topics stay
  searchable. Browsers without Web Speech (Firefox/Safari) fall back to 5s
  hold-to-talk through the server Whisper loop; tap mode is honestly labeled.
- **Honest health**: `/api/health` gained Model Room, Terminal, Feeds and
  Weather services — optional surfaces report `degraded` in off-states, and
  the `ok` flag excludes them (a machine without Ollama is not a broken AURA).
- **Bug fixes found in the full review**
  - eval harness timezone bug: agent-eval seeded events on UTC `date.today()`
    while `_user_day()` windows are in the user's tz — any near-midnight run
    failed `calendar_today`/`briefing`. Harness now seeds on the user's day.
  - `INSERT OR IGNORE` + `lastrowid` can report stale rowids when the row is
    ignored — feeds new-item counting switched to an existence pre-check.
  - Terminal classifier originally trusted bare first tokens (`python3 x.py`
    counted "safe"); now subcommands are validated (`git`, `ollama`, `docker`,
    `systemctl`, `pip`…) and redirects / command-substitution downgrade to
    `guarded`.
  - Atom parsing used the defunct `purl.org` namespace; now derives the
    namespace from the document root (fixes standard Atom 1.0 feeds).
  - `fire_webhook` docstring sat *after* a statement (dead string); relocated.
  - health "5 connectors" → 6 (whatsapp counted).
- Gates: backend 248/248, vitest 80/80 (19 files), TSC clean, E2E 97/0/1
  (warn = VAPID off-state), router 299/299, agent 27/27, benchmark all-in-budget.
- Out of scope by owner decision: auth/multi-user (single-user fortress,
  remote access via Tailscale/VPN), native mobile app.

## v1.13.0 — 2026-09-11 — Finalization & diligence

- **Benchmark harness + CI gate (§38)**: `scripts/benchmark.py` measures the
  hot paths (router classify/plan, DB write, memory search, tool exec,
  mission planning, full builtin chat turn) offline + deterministically and
  fails `--ci` when any median regresses past budget. Wired into the CI
  backend job — closing the last open first-release acceptance item.
- **Idempotency (§39)**: webhook automation fires now carry a stable
  `_fire_id` (uuid, survives retries, cleared on success) sent as
  `X-Aura-Idempotency-Key` so receivers can dedupe retries; `comms.send`
  suppresses identical duplicates within 60s via the new `send_dedupe`
  table (additive). Expired claims are pruned on the scheduler tick.
- **Search filters + explainability (§31)**: `/api/search` gains `type`,
  `frm` (from), `to` filters and every result now carries a `matched`
  reason ("title matches …", "semantic memory match (relevance 0.87)");
  the command palette surfaces it.
- **Autonomous skill improvement (§50)**: new `routine_mission` detector —
  a mission completed 3+ times but never scheduled becomes a one-click
  "Make it a routine" opportunity (`schedule_mission` action).
- **Advanced analytics (§50)**: `/api/analytics/overview` gains `forecast`
  — next-7d spending, task velocity, sleep + mood trends (least-squares,
  honest `null` when data is thin); new Forecast panel.
- **Parallel subagents (§76)**: consecutive R0 read-only steps in a chat
  plan now execute concurrently (pool of 4), results joined in plan order.
  Toggle `chat_parallel_steps` (default on).
- Gates: backend 226/226, vitest 72/72 (18 files), TSC clean, E2E
  89/0/0, router 265/265, agent 27/27, benchmark all-in-budget.

## v1.12.0 — 2026-09-11 — Autonomy: proactive missions, web search, mission visibility

- **Proactive → auto-mission (advanced proactive intelligence)**: the
  repeated-chore opportunity now offers **Automate as mission** (weekly) and
  stale backups offer **Automate daily backup**. One click creates the
  mission (auto planner, with a concrete recurring-task fallback when no
  template matches), applies the schedule, auto-starts R0/R1-only plans, and
  resolves the opportunity — closing the detect → act loop end-to-end.
- **Web search (deeper agent delegation)**: new `web.search` R0 Hermes tool
  + `web_search` chat intent — keyless DuckDuckGo HTML search, SSRF-guarded,
  10s-capped, ≤6 results, honest off-state (never fabricates). Builtin
  composer renders titled links + snippets; the tool is available to mission
  plans and the LLM planner.
- **Mission visibility in chat**: `mission_status` intent ("how are my
  missions") streams each mission's step progress as SSE `mission` events and
  renders live progress in the chat thread (see also the Missions panel).
- Gates: backend 218/218, vitest 72/72 (18 files), TSC clean, E2E
  88/0/0, router 265/265, agent 27/27.

## v1.11.0 — 2026-09-09 — Proactive autonomy: scheduled missions, run history, push

- **Scheduled missions**: `POST /api/missions/{mid}/schedule
  {every: off|hourly|daily|weekly}` — due schedules relaunch finished
  missions on the 30s scheduler tick (same trigger format as
  automations). Drafts still need review; paused/running/awaiting are
  left alone; stepless missions get their schedule cleared.
- **Run history**: new `mission_runs` table — runs open on start
  (manual or scheduled) and close on done/fail; `GET /{mid}/runs`
  powers the "last run" line on each mission card.
- **Completion push**: mission done/fail now fan out via Web Push
  (`send_push`, quiet-hours aware, inert without keys/subs) alongside
  the existing in-app notification.
- UI: per-mission repeat picker + next-run time + last-run summary.
- Gates: backend 206/206, vitest 71/71 (18 files), TSC clean, E2E
  85/0/0, router 252/252, agent 27/27.

## v1.10.0 — 2026-09-09 — Autonomy batch: LLM mission planner, live senses, web reader

- **LLM mission planner**: `POST /api/missions {goal, planner=auto|template|llm}`
  drafts novel multi-step plans from the R0–R2 tool catalog (fenced-JSON
  parsing, max 8 steps, unknown/R3/R4 tools dropped, empty+builtin safe
  when no model). LLM plans always `needs_review`; UI ✨ AI-plan toggle.
- **Live senses**: `POST /api/vision/look` (frame + optional question,
  memory opt-out) + `GET /api/vision/status` honest capability report +
  `vision.look` R0 Hermes tool. Files-view Look panel: camera preview,
  screenshot, or upload.
- **Web reader**: paste any link in chat → `web_read` intent fetches it
  (≤2 pages, SSRF guards, HTML/text only, 1.5MB/15s caps) and grounds the
  reply. Hermes tool `web.fetch` (R0). No new dependencies.
- Gates: backend 200/200, vitest 70/70 (18 files), TSC clean, E2E
  84/0/0, router 252/252, agent 27/27.

## v1.9.0 — 2026-09-09 — JARVIS batch: voice loop, missions, smart home, remote access

- **Always-on voice loop**: "hey jarvis" wake word (openWakeWord, bundled
  model, off by default) + full-duplex `WS /api/voice/loop` — 16kHz PCM
  in, JSON events + TTS clips out. Sleep → listen → think → speak with
  VAD end-pointing, a 6s follow-up window, and wake-word barge-in (no
  echo cancellation, honestly documented). Tap-to-talk fallback without
  the wake dep, browser-TTS fallback without server TTS. Live
  Conversation panel + wake controls in Settings.
- **Missions (goal delegation)**: `POST /api/missions {goal}` plans a
  Hermes tool chain (6 templates run on start; keyword guesses need
  one-click review; unknown goals say so). One step per scheduler tick;
  R0/R1 run unattended, R2+ and draft-sends park in `awaiting` and
  resume when the approval resolves. Every transition notifies.
  Missions panel in Automations.
- **Routine learning**: briefing digests gain `routines[]` (productive
  weekday, sleep drift, top spend — honest empties) plus a
  `routine_drift` proactive detector (sleep down >1h → open Personal).
- **Smart Home**: Home Assistant as a 6th gateway integration
  (`base_url`+token, sandbox/live) with `/api/home` (status, entities,
  service calls), sandbox demo entities, a Smart Home view with
  toggles, and `home.entities` (R0) / `home.control` (R1) Hermes tools.
- **Reachability**: `docs/REMOTE_ACCESS.md` — always-on hosting,
  Tailscale + `serve` HTTPS (mic/PWA need a secure context), Funnel
  for bot webhooks, and go-live checklists for Telegram, WhatsApp,
  and Home Assistant. Persona pass: AURA addresses Antony by name
  with sparing dry wit; grounding discipline unchanged.
- Gates: backend 179/179, vitest 67/67, TSC clean, E2E 82/0/0,
  router 252/252, agent 27/27.

## v1.8.0 — 2026-09-09 — Agency batch: proactive actions, analytics, messaging bots

- **Advanced proactive intelligence**: 8 detectors (missed follow-ups,
  deadline risk, stale clients, overloaded days, clashes, repeated
  patterns, missing/stale backups, expense anomalies) with per-type
  executable actions (`create_task`/`run_backup` run server-side via
  Hermes and are undo-journaled; `draft`/`open`/`chat` hand to the
  client), snooze (1–168h), auto-resolution with history
  (`GET /resolved`), and exclusion of resolved/snoozed items.
- **Analytics dashboards**: read-only `GET /api/analytics/overview`
  (spending by currency/day/category with month delta, task completion
  + overdue, habit streaks, sleep, journal mood, AURA activity) and a
  new Analytics view with honest empty states — no fake zeros.
- **Messaging bots via gateway**: Telegram `getUpdates` polling (no
  public URL needed) + secret-verified webhook receiver; WhatsApp
  Cloud API sending (`wa_token`+`phone_number_id`, generic webhook
  fallback kept) + Meta handshake/inbound webhook; inbound lands on
  the event bus with a notification; optional `auto_reply` (off by
  default). Gateway UI gains token fields, Check-messages polling,
  and webhook setup hints — everything token-ready with honest
  off-states until live credentials are added.
- Gates: backend 151/151, vitest 58/58, TSC clean, E2E 79/0/0,
  router 252/252, agent 27/27.

## v1.7.0 — 2026-09-09 — Human-like voices: engines, emotions, smart breaks

- **Human-like voices (Voice v2)**: three TTS engines — Browser (system
  voices + pitch), Piper (5 curated downloadable voices, offline, speed
  control), and Edge Neural (8 free Microsoft voices incl. Kenyan English
  Chilemba/Asilia + Kiswahili Rafiki/Zuri, gated on Hybrid/Cloud privacy).
  6 emotion presets (full mstts acting on Edge US voices, prosody
  everywhere), SSML smart breaks, markdown stripping for speech,
  per-engine voice picker + Test voice in Settings, and `GET
  /api/voice/engines`. E2E performs a live neural synthesis round-trip.

## v1.6.0 — 2026-09-09 — Agency + accountability: proactive, undo, sessions, evals, costs, vision

- **Proactive engine + explainability (WS1)**: `/api/proactive`
  scan/list/dismiss with automation hooks, and reply explainability —
  plan-trace SSE steps, memory citations with relevance, cloud redaction
  counts on every turn.
- **Dry-run + undo (WS2)**: Hermes tool dry-runs, automation `dry_run`
  execution, and `/api/undo` round-trips with a journaled undo log.
- **Sessions + compaction (WS3)**: full session lifecycle (pin/star/branch/
  search) with rolling summaries — auto-compaction past the context window
  (LLM when reachable, extractive heuristic offline) injected back into
  generation context.
- **Agent/AI eval framework (WS4)**: 27 golden tasks at 100% with grounded
  scoring, runs tracked in `eval_runs`, agent-case shape validation in the
  unit suite, and a CI gate (`eval_agent.py --no-record`).
- **Cloud cost controls (WS5)**: `llm_usage` journal (provider, model,
  purpose, tokens, cost, latency, ok) fed by every model call; OpenRouter
  per-token pricing snapshotted from the live catalog with static fallbacks
  for known OpenAI models and honest NULL-cost + `unknown_pricing` flag for
  anything unpriced. Daily/monthly USD caps fail closed (`BudgetExceeded`,
  chat falls back down the chain). `GET /api/costs` + `/api/costs/calls`,
  Settings → Cloud costs panel (spend, budgets, top models).
- **Image understanding (WS6)**: `vision.py` chain (Ollama vision model →
  cloud `image_url` vision, privacy-mode aware) with an honest 503
  off-state; `POST /api/files/{id}/analyze` + `GET …/analyses` backed by a
  `vision_results` table; chat `{"file_id"}` attachments (≤3) grounded into
  replies; >3 MB images downscaled pre-send; Files → Analyze button and
  Settings vision toggle + model field; vision spend journaled as
  `purpose:"vision"`.

## v1.5.0 — 2026-09-09 — Ops readiness: CI, migration guard, prod check, onboarding

- **GitHub CI** (`.github/workflows/ci.yml`): backend (compile + unit +
  router-eval), frontend (tsc + vitest + build, dist artifact), E2E (live
  server + `e2e_check.py` + `prod_check.py`), security audit (blocking
  `pip-audit` + prod-deps `npm audit`; dev-only advisories report without
  blocking), and the migration guard. Tag workflow (`release.yml`) rebuilds
  and publishes the `dist/` tarball with SHA-256.
- **Migration guard** (`scripts/migration_check.py`): diffs `schema.sql`
  base-vs-head in CI, fails on dropped tables/columns or explicit DROPs
  unless the commit message carries `[allow-destructive-schema]`. Fixture
  self-test + git-mode verified.
- **Production check** (`scripts/prod_check.py`): 10 readiness gates —
  version mirrors consistent, prod bundle present, deploy files in place,
  data dir writable, DB `integrity_check`, services online, live version
  matches code, backup recency, VAPID state, cloud-key sanity.
- **First-run onboarding** (§83 + §84): 7-step wizard (identity + timezone,
  domains, memory mode, intelligence, platforms, notifications, first
  goals/projects) writing real settings/rows, gated on the server
  `onboarded` flag, ending with "Ask AURA anything." and a one-click demo
  prompt. EN + Swahili, replayable from Settings → Data.
- **Timezone + domains are real settings**: `timezone` (IANA-validated)
  drives quiet hours, briefing dates, and calendar day math (no more
  hardcoded Nairobi); `domain_career/clients/personal` filter briefing
  task sections; `PATCH /api/me` edits identity. Timezone row added to
  Settings.
- **Release docs**: `docs/RELEASE.md` (process, migration notes, model +
  Hermes compat matrices, rollback) and an operations production checklist.
- **Tests**: 101 unit + 71 E2E + 43 frontend + 243 router-eval, green.

## v1.4.0 — 2026-09-09 — Connections: briefings, mail, calendar, multi-device sync

- **Scheduled LLM briefings**: saved briefing configs (morning/evening/custom
  prompt, `GET/POST/PATCH/DELETE /api/briefings`, run-now + run history with
  a notification on completion). Briefings run through the effective cloud
  chain (OpenRouter/OpenAI/custom → Ollama → builtin fallback) and are a
  first-class automation action — schedule a 7 AM brief from the Automation
  Center. `brief me` / `evening briefing` in chat.
- **Email reading + triage** (`/api/mail`): multiple accounts in `sandbox`
  mode (8-message sample inbox, idempotent sync) or `live` IMAP (credentials
  required, secrets never leak in list JSON — `has_password` flag only).
  Rule-based triage (`action/waiting/fyi/done`) over unread with optional LLM
  pass, full reader, unread counts. Inbox UI with account manager, triage tabs
  and reader; `check my email` in chat.
- **Calendar, three ways** (`/api/calendar`): local-first events (CRUD,
  validation, today/week agenda) + CalDAV pull (REPORT, VEVENT round-trip,
  best-effort push) + Google OAuth (auth URL, copy-paste code landing page,
  refresh-token exchange, confirmed-only pull). Calendar UI with week agenda,
  event composer and per-source connection cards; `what's on today` /
  `schedule lunch Friday 1pm` in chat.
- **More Hermes tools (34 total)**: `email_*`, `cal_*`, `briefing_now`,
  `tasks_prioritize` join the runtime; chat routes to them via 4 new intents
  (`briefing`, `email_check`, `calendar_today`, `calendar_create`).
- **Multi-device sync** (`/api/sync`): portable `aura-sync/1` JSON bundles —
  export on device A, import on device B. Merge by natural key with FK
  re-link (`_client`/`_project`/`_session` hints), local-wins conflicts +
  `sync_log` history. Fixed four real merge bugs the E2E self-import
  exposed: sessions keyed by stripped `id` (now `(title, domain,
  created_at)`), `sleep_logs` keyed by nonexistent `created_at` (now `(date,
  bedtime, wake_at)`), NULL-unsafe `=` matching (now NULL-safe `IS`), and
  TEXT-PK sessions importing with NULL ids (now minted). Settings Data panel:
  device name + export download / import merge.
- **PWA + mobile polish**: install prompt capture with TopBar install button,
  service worker v2 (cache-first + offline navigation fallback), safe-area
  bottom nav, 16px inputs (no iOS zoom), 40–48px touch targets, sticky chat
  composer. EN + Swahili strings for the new views.
- **Tests**: 96 unit + 70 E2E + 39 frontend + 243 router-eval, green.

## v1.3.0 — 2026-09-09 — OpenRouter free models, settings system, view fixes

- **OpenRouter provider**: first-class cloud backend alongside OpenAI/custom
  endpoints. Paste a key from openrouter.ai/keys, pick a `:free` model (or
  type any ID), Test, Save — no restart. Proper `HTTP-Referer`/`X-Title`
  headers, temperature + max-tokens controls, strict/relaxed cloud memory
  policy. `GET /api/cloud/models` proxies the live catalog (1h cache,
  curated free presets when offline); `POST /api/cloud/test` tries saved
  config or throwaway candidates without saving.
- **Settings system**: new validated `settings` store (`GET/PATCH/DELETE
  /api/settings`, DB > env > defaults, secrets write-only with `*_set`
  flags, per-key sources). Everything hot-reloads: privacy chain, cloud
  provider/keys/models, Ollama URL/model, voice (lang/rate/autoplay),
  chat (streaming/enter-to-send/timestamps), toast duration, quiet hours
  (push suppression, Nairobi time), observability retention (nightly
  prune of activity/audit/tool logs — never user content), memory
  auto-store. Tabbed Settings UI with connection tester + live model
  list + diagnostics download + reset.
- **Appearance prefs**: dark/darker/light themes, 5 accents, compact
  density, font scaling — instant preview, per-browser.
- **Fixed dead workspaces**: Career, Clients & Projects, and Personal
  views crashed on load (hooks declared after the loading return —
  "rendered more hooks" error). All hooks hoisted; jsdom smoke tests
  now render every fixed view. `Waveform` also null-guards canvas
  contexts (headless browsers).
- **Tests**: 80 unit + 61 E2E + 36 frontend + 211 router-eval, green.

## v1.2.1 — 2026-09-09 — hardening patch

- **Webhook secret redaction**: `GET /automations` masks `action_config.secret`
  as `***` (same policy as gateway credentials); signing still reads the real
  value from the DB at fire time.
- **PATCH validation closes kind-switch hole**: switching an automation to
  `webhook` (or editing its config) validates the *merged* config — no more
  URL-less webhook rows that only fail at fire time. Non-object `action`
  payloads rejected at create.
- **Voice rate limiting**: `/voice/transcribe` + `/voice/speak` moved into
  the strict 30/min media bucket (were 600/min); corrupt audio now returns
  `400` instead of a misleading `503`.
- **XLSX streaming**: sheet rows consumed via `islice` instead of
  materializing the whole sheet (large-workbook memory fix).
- **Tests**: 66 unit + 54 E2E + 30 frontend + 211 router-eval, green.

## v1.2.0 — 2026-09-09 — webhooks, sleep, voice, PWA, plugins, i18n

- **Webhook automation actions**: HMAC-signed POST + JSON payload, exp
  backoff retry (5m→2h cap), URL validation (400s), Automation UI fields,
  self-fire E2E; manual/event triggers fixed to one-shot.
- **Sleep tracking**: `sleep_logs`, `sleep_log` intent
  (`slept 11pm to 6am`, `log sleep 7.5 hours`), `POST /personal/sleep`
  (400 on bad input), real dashboard insight, Personal UI panel.
- **Richer file parsing**: new `extract.py` — PDF (pypdf, page count),
  DOCX (paragraphs+tables), XLSX (all sheets), PPTX (slides+tables),
  image metadata; `indexed_chars`/`pages`/`extract_error` per file.
- **Server-side voice (optional)**: faster-whisper STT + Piper TTS,
  lazy model download to `data/models`, `GET /voice/status`,
  `POST /voice/transcribe|speak`; Voice UI record/upload/speak panels;
  loop-verified live (speak → transcribe roundtrip).
- **Frontend tests**: Vitest + Testing Library, 30 tests — helpers,
  api client, primitives, i18n parity, push/PWA assets.
- **Router eval harness**: `scripts/eval_router.py` + 211 utterances at
  100%; fixed 5 real bugs it found (prioritize/meditate prefix regexes,
  cron-status yield, client plurals, healthy/diagnostics).
- **Ollama embeddings by default**: `embedding_model` tags, lazy re-embed
  migration (≤5/search), legacy-DB ALTER migration, Embeddings health row.
- **PWA + push**: manifest, generated icons, service worker (app-shell
  cache, push/click handlers), VAPID Web Push (`scripts/gen_vapid.py`),
  notify-automation fan-out with 410 pruning, Settings toggle + test.
- **Litestream sync config**: `litestream.yml`, entrypoint with
  restore-on-boot + replicate wrap, Dockerfile binary install, compose
  docs, `litestream` field in backup history.
- **Plugin tools**: `app/plugins/` (shipped) + `$DATA_DIR/plugins/`
  (user, survives upgrades); manifest + R0–R2 risk, hot-reload,
  `text_stats` + `unit_convert` examples; see `docs/PLUGINS.md`.
- **i18n (Swahili-first)**: complete `sw` dictionary (nav, titles,
  topbar, palette, greetings), browser-locale default, Settings switch,
  key-parity test guard, `<html lang>` switching.
- **Tests**: 63 unit + 54 live E2E + 30 frontend + 211 router-eval,
  all green; tsc clean; dist rebuilt; version 1.2.0.

## v1.1.0 — 2026-09-09 — providers, hardening, cloud

- **Real provider delivery**: new `providers.py` — Telegram Bot API, SMTP
  (TLS/SSL, client-email resolution), Discord/Slack webhooks, generic
  WhatsApp provider hook; per-platform `sandbox|live` modes with validated,
  redacted credentials; live connection tests; bus + activity logging with
  mode tags; Gateway UI config panels + live-delivery simulator.
- **Approvals tell the truth**: sends split into `sent`/`errors`, failure
  notifications, inline error toasts; disconnected channels fail fast
  instead of fake-"queued".
- **Hardening**: per-IP sliding-window rate limits (chat/API/upload, `429` +
  `Retry-After`), payload caps (message/attachments/file/request, `413`s),
  security headers, CORS modes (open default ↔ explicit lockdown),
  secret-scrubbed grounding, write-only credentials.
- **Cloud model wiring**: OpenAI-compatible fallback honoring `AURA_PRIVACY`
  (`local-first`/`hybrid`/`cloud` chains); sensitive/private memories
  withheld (`redacted_memories` count); credential scrubbing; engine-labeled
  results (`builtin`/`ollama`/`cloud`); health shows cloud state.
- **Tests**: 37 unit (mocked providers/SMTP/cloud, limiter, caps, CORS) +
  45 live E2E (engine field, redaction roundtrip, live validation, caps).

## v1.0.0 — 2026-09-09

First complete release: all views, journeys, automations, gateway, backups,
and voice working end-to-end against real state (no mocks).

**Hardening pass (this release):**

- Intent routing: fixed ordering/plural traps (`run a backup`, `new project X`,
  `draft follow-ups`, `gateway status`, `show my automations`, `new client X`,
  `how are my projects doing`, `practice guitar`); create-intents outrank review.
- Task toggle: `done with X`, quoted titles, trailing status words, numeric IDs.
- Task creation echoes the created title; interview prep extracts the role.
- Approvals: empty-draft plans skip card creation; edited drafts override,
  send, and persist as `drafts_sent`; bad decisions → `400`.
- Backups: added verified **restore** (integrity check, safety copy, upload
  merge) + restorable-file listing + UI.
- Dashboard: sleep/mood-delta/spending insights computed from real data
  (or honestly empty); KES-only totals.
- Gateway test latency measured (was hardcoded); personal totals KES-only.
- Seed guard covers tasks+memories+clients; vector probe can't 500 health.
- Docker: Ollama moved to `--profile lfm` so default `up` stays light.
- Frontend: mic-track leak fixed, conversation history in palette, editable
  approval cards, composer guards, keyboard-accessible rows, skeleton
  loaders, mobile bottom nav, error boundary, resume export links.

**Tests:** 25 backend unit + 44 live E2E (`scripts/e2e_check.py`) + `tsc` +
production build — all green. **Docs:** full set (setup, user, commands, API,
architecture, operations, testing, roadmap).
