# AURA OS — Changelog

## v1.16.0 — Missions that actually move, plus the queue, board and commands

### The bug that mattered most: missions never advanced

`missions.tick_missions()` and `missions.tick_schedules()` had **no call sites
outside `backend/tests/`**. `hermes.start_scheduler_loop` only ever called
`tick_automations()`, so a mission started from the UI or from chat sat at
`status='running'` with every step `pending`, indefinitely, and the test suite
stayed green because the tests called `tick_missions()` by hand. A background
function is not wired until something in `app/` calls it.

Fixed by the new `workers.scheduler_pass()` — the single 30-second pass the
scheduler loop body calls, and nothing else. It ticks automations, schedules and
missions, runs a due consolidation pass, then drains the job queue.

### Worker pool and persistent queue (`worker_jobs`)

- Claim with a single `UPDATE ... RETURNING`, not SELECT → UPDATE → re-SELECT.
  The three-statement form double-claims under concurrency: two threads select
  the same id, both update (the second is a no-op, not a failure), then both run
  the job. Realised in a probe by widening the select→update gap to 20 ms —
  4 concurrent claimers, 4 winners.
- Retry with exponential backoff (`2^attempts * 5s`, capped at 5 min), then a
  dead-letter with the error preserved.
- `attempts` counts executions, not failures, so `max_retries: 3` runs a job at
  most 4 times. `or 0` not `or 3` when reading the pref: 0 is a legal "never
  retry".
- Interrupted `running` jobs are re-queued once at startup, so a restart loses
  nothing.
- The mission cycle runs **through the queue**, so the pool is real: jobs
  persist, survive a restart, and retry with backoff. One `mission_cycle` job
  rather than two, because `drain` runs a claimed batch concurrently and the
  schedules-before-missions ordering would not survive it. A test greps
  `backend/app/` for an `enqueue` caller, because this branch wrote the rule
  "a background function is not wired until something in `app/` calls it" after
  a mission tick turned out to have no production caller while its tests were
  green — and must not repeat it with its own flagship subsystem.

### Mission board (`/api/board`)

A drag-drop view over mission status — four columns derived from the statuses
that already existed, with every move going through `missions.set_status` so it
cannot bypass the approval flow. There is no move *into* `done` that completes a
mission: a drag to Finished **cancels**, because the only legitimate route to
`done` is a mission actually finishing.

### Slash commands (`/api/slash`)

26 built-ins across six categories plus custom commands, reachable three ways:
`GET /api/slash` (catalog, Python handlers stripped), `POST /api/slash/execute`,
and a leading `/` in the chat stream, which short-circuits **before** the
orchestrator and emits a single `slash` SSE event. `execute` never raises — a bad
command is a `200` with `ok: false` and the reason in `text`, because a `500`
would abort the stream it was fired from. `/` in the Composer opens a palette;
the full cheat sheet with custom-command CRUD is in Settings → Commands.

### Memory consolidation (`/api/consolidation`)

Nightly dedupe, importance re-scoring and archival. Every write is a soft delete
or a `supersedes_id` pointer. Re-scoring is the idempotent pass and the one that
needed care: both signals are gated on a whole-second `consolidate_last_run`
watermark, because scored on bare presence they re-apply forever and pin
importance at its cap. Both sides of that comparison must resolve on the same
one-second grid — a fractional parse makes a stamp written *during* a pass read
newer than the watermark that pass ends by writing.

### Fact extraction from tool results

`MemoryEngine.observe` already mined facts out of *chat text*; it never looked at
what tools returned. An email address handed back by `clients.create` or a due
date from `tasks.create` is exactly the kind of durable fact that used to exist
only until the chat scrolled away.

Only high-signal structured fields are promoted (≤3 per result, contact details,
dates, identifiers) — a tool's free-text output is `observe`'s job, and mining
both would double-count. Two payload shapes have to be recognised because the
routes return both: a wrapper (`{"clients": rows}` from `list_*`) and a bare row
(from `create_*`/`update_*`/`get_*`). A bare row is discriminated on the entity's
own columns, never on the tool name — within one family `clients.list` returns a
wrapper and `clients.create` returns a row, so the name does not say which.

### Performance: in-process cache + SSE token batching

- TTL + LRU cache with Redis-equivalent semantics for hot read paths, including
  the Ollama model catalog. The catalog cache is keyed on the base URL and
  deep-copied on read: keying it on a constant served one machine's model list to
  another, and handing out the live list let a caller mutate the cache in place.
- Streamed tokens are coalesced on a `sse_batch_ms` window (default 40 ms, 0 =
  every token). The event shape is unchanged, so no client had to change.

### Performance panel (`/perf`)

Queue depth, throughput, error rate, dead letters, per-kind counts, and the
consolidation state — plus the honest-empties above, which are load-bearing
rather than cosmetic.

### Tests

- `scripts/e2e_check.py` gains five checks covering consolidation, the worker
  queue, the board's move guards, the slash catalog/execute/custom lifecycle, and
  the `slash` SSE short-circuit — the last of which is a genuinely different code
  path from `POST /api/slash/execute`.
- `frontend/src/__tests__/perf.test.tsx` covers the panel, including that a drain
  which dead-letters a job warns rather than celebrates.

## Unreleased — deployment + integration audit pass

A second pass driven by actually running the thing: building the Docker image,
running the CI scripts, and driving the UI in a real browser. All of the
`scripts/e2e_check.py` failures turned out to be real defects, not script noise.

### Deployment (the image shipped with no UI)

- **The container never served the frontend.** `main.py` resolved
  `frontend/dist` as `Path(__file__).parent.parent.parent / …`, which is
  correct in a source checkout (`<repo>/frontend/dist`) but resolves to
  `/frontend/dist` in the image, where the assets are at `/app/frontend/dist`.
  The container served the API and returned 404 for `/`. `_resolve_dist()` now
  probes both layouts, honours `AURA_FRONTEND_DIST`, and verifies `index.html`
  exists; it also rejects a crafted SPA path that escapes the dist directory.
  Verified by building the image and asserting `GET /` returns 200 with assets.

### Integration bugs (each silently broke a feature)

- **`GET /tasks/overdue/list` returned the wrong key.** It returned
  `{tasks: …}`, but `api.ts` declares `{overdue, count}`, `orchestrator` reads
  `data.get("overdue")` during its memory harvest, and `e2e_check` asserts
  `overdue`. The overdue list was therefore empty in the UI, in the plan
  grounding, and in follow-up drafting.
- **`POST /projects/{id}/milestones` did not exist.** `add_milestone()` was
  written but never decorated, so the frontend's `api.projects.milestone()`
  404'd. Now registered, with validation, plus `PATCH`/`DELETE` for a
  milestone.
- **Plugins loaded zero of them unless CWD was `backend/`.** `load_plugins()`
  used the relative `Path("app/plugins")`. Discovery is now anchored to the
  package directory.
- **`POST /api/gateway/simulate` returned 500.** It read `e.event_id`, but
  `emit_gateway()` returns a plain dict. `emit_gateway` now returns the new
  event's id.
- **`career.interview_questions` was three hardcoded strings.** Now generates a
  role-aware set of 7 that folds in terms lifted from the job description.
- **`scripts.save` still passed the args dict as `name`.** Fixed with a proper
  adapter; the R0/R1 tool probe and the AST unbound-name sweep are both clean.
- **Webhook validation allowed http only for loopback.** https is still
  required for any remote target, so a self-hosted integration on the same box
  works without letting cleartext leave the machine.

### Hygiene

- Removed the per-turn `DEBUG ORCH` prints. They ran on every chat turn and
  dumped the first 50 characters of **every retrieved memory** to stdout, which
  in Docker is the container log.
- `scripts/e2e_check.py` now reports the failing source line; bare `assert`s
  printed an empty message, hiding which step broke. Also updated two stale
  assertions (the `kokoro` engine added in v1.15, and positional engine lookup)
  and made the folder-watch test ask the server for its watch path instead of
  hardcoding `<repo>/data/inbox` — that only worked when `AURA_DATA_DIR` was
  unset.
- Labelled 10 unlabelled `<select>` elements and 2 hidden file inputs found by
  the browser accessibility pass.

### Verification

Backend 344/344 · frontend 175/175 · `tsc` clean · `npm run build` clean ·
router eval 299/299 · agent eval 33/33 · `e2e_check.py` 101/101 (was 93/101) ·
`prod_check.py` 11/11 · `pip-audit` clean · `npm audit --omit=dev` clean ·
Docker image builds, serves API + UI, and passes the full smoke suite ·
browser walkthrough green at 390/820/1600 px with no console errors.

## Unreleased — correctness + security audit pass

The backend suite is green again (344 tests). This pass fixed real defects
rather than adding features; the security and correctness items are listed first.

### Security

- **`local-first` could send data to the cloud (privacy regression).**
  `ModelRouter.chain()` appended `"cloud"` to the local-first chain whenever a
  key was configured, so `hybrid`-style fallback leaked user content off-machine
  while the UI still said "local-first". `chain()` now never puts cloud in
  local-first, and no longer constructs a cloud client at all in that mode.
- **Cloud grounding was unredacted.** `filter_cloud_memories` was imported by
  the orchestrator but never called, so `sensitive`/`private` memories were sent
  verbatim to the provider. Cloud turns now build a separate redacted message
  set (the local model still sees everything), and `result.redacted_memories`
  reports the count.
- **Automations were persisted without validation.** `automations.create` wrote
  any action config straight to the table, so a `terminal` action could hold
  `rm -rf /` and a `webhook` action could hold `ftp://` or any non-https URL.
  Actions are now validated before insert *and* on `PATCH` against the merged
  config: webhook must be https, terminal must not classify as `dangerous`,
  home ids must be `domain.object_id`, scripts must resolve.
- **Home Assistant identifiers** are charset-validated before reaching the
  gateway, so a metacharacter-laden `entity_id` can no longer be forwarded.
- **The entire cloud chat path was dead.** `run_turn` referenced an undefined
  `purpose` name inside the cloud branch; the `NameError` was swallowed and
  every hybrid/cloud turn silently degraded to the builtin composer. Fixed, and
  a non-streaming retry now covers gateways that reject or ignore `stream: true`.

### Correctness

- **Dead Hermes tools.** Nine registered tools pointed at functions that do not
  exist (`scripts.list`/`save` → wrong module, `weather.now` → `now`, not
  `current`; `system.undo` → `undo`, not `sync`; `home.entities` →
  `list_entities`; `proactive.scan`, `briefing.now`, `system.backup`,
  `scripts.run_script`) and silently failed at call time. All are wired to real
  implementations.
- **Positional-arg tool adapters.** `_lazy(mod, fn)` passes the whole args dict
  as `fn`'s first parameter, so tools whose function takes a plain argument
  (`web.fetch(url)`, `career.interview_questions(job_description, role)`,
  `tasks.update`, `projects.update`) could never work. Each now has a real
  adapter; `vision.look` accepts and validates `image_b64`.
- **Undo did not cover creates or updates.** Only deletes were journaled, so
  "undo that" after adding a task said "Nothing to undo". Task create/update
  are now journaled; the undo preview reports the true total instead of
  disagreeing with the apply response.
- **Dry-run was a no-op wrapper.** `/api/hermes/tools/{name}/dry-run` and
  `POST /api/automations/{id}/run?dry_run=true` returned a bare tool result and
  — for automations — actually resolved *approvals*. Both now return
  `{dry_run, result|fired, blocked}`, and `db.notify`/`comms.send` report the
  side effects they withheld instead of silently succeeding.
- **Event-triggered automations were unaudited.** Feed and file-watch triggers
  have `next_run IS NULL`, so they bypassed `tick_automations` and called
  `_fire_one` directly — never updating `last_run`/`success_count`. They now
  route through `fire_event`, which shares the same bookkeeping as a scheduled
  fire. Webhooks also gained HMAC-SHA256 signing and an idempotency key, and
  failures now back off exponentially instead of retrying every tick.
- **Two undefined-name bugs** that only fired on rare paths: `missions.py` used
  `prefs` without importing it (every mission failed on its first step), and
  `orchestrator.py` called `prefs.get(...)` when the import was aliased
  `_prefs` (follow-up approvals were never created).
- **`prefs.get()` was called with a second argument** in four places, raising
  `TypeError` at runtime.
- **Chat terminal commands were unusable.** A redundant R3 approval gate in
  `run_turn` short-circuited every terminal request, and the composer then
  reported "the command did not run" rather than that approval was pending.
  `terminal.exec_command` remains the single audited safety boundary.
- **`comms.send` deduplicates repeat sends** and previews before dedup, so a
  dry run can no longer suppress the real send it was previewing.
- Gateway inbound/outbound messages are now recorded in a dedicated
  `gateway_events` table (the `/api/gateway/status` `events` feed previously
  returned raw activity rows with no `platform`).
- Three placeholder tools are implemented for real: `draft_followups`,
  `prioritize_tasks`, `unread_count`.
- `briefing.now` was rated R2 (external call), so running a briefing demanded
  approval; it is R1 — it composes locally and notifies the owner only.
- Client hang-up mid-stream now closes the upstream LLM connection instead of
  leaking it (previously verified only by a test written against a
  never-implemented tuple-yielding contract).
- Blank/whitespace task titles are rejected; the terminal's `danger_reason()`
  had an unreachable return inside its `for` loop that only checked the first
  pattern.

### Tests

- Backend: 344/344 pass (was 47 failures at `8f04748`).
- Frontend: 175/175 pass; `testTimeout` raised to 20s — a heavy `SettingsView`
  render failed spuriously when the backend suite ran concurrently.
- Router eval 299/299, agent eval 33/33 against real Ollama `llama3.1:8b`.
- `agent_cases.json` case `undo` updated: it asserted the old behaviour where
  creates were not undoable.
- Two tests were corrected where they, not the code, were wrong:
  `test_journey_followup_approval` (needed an overdue task to have anything to
  approve) and `test_first_token_precedes_…` (asserted a tuple contract the
  production code has never had).

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
