# AURA OS — API Reference

Base URL `http://localhost:8000`. All JSON unless noted. Single-user: no auth
headers (see OPERATIONS for exposure guidance). Interactive docs at
`/docs` (Swagger) and `/redoc` when the backend runs.

Conventions: `200` + object on success; `400` validation, `403` risk-gated
tool, `404` unknown id/tool. Timestamps are UTC ISO-8601.

## Meta

- `GET /api/health` → `{ok, services[8], metrics:{uptime_s, db_latency_ms, runs_24h, avg_run_ms, tools_ok, tools_err, disk_free_gb}, version, hermes}`
- `GET /api/system` → same payload without the `ok` rollup
- `GET /api/me` → `{name, role, location, version}`
- `PATCH /api/me` `{name?≤80, role?≤120, location?≤120}` → updated identity (non-empty; unknown/empty → `400`)
- `GET /api/tools` → `{tools: [{name, risk, description, domain}], hermes}` (39 core + 2 plugin tools)
- `GET /api/dashboard` → `{priorities[5], counts:{overdue, done_week, memories, unread, pending_approvals, spending(KES)}, projects, clients, activity, notifications, gateway, timeblocks, insights:{sleep, sleep_state, mood, mood_delta, spending_state, spending_dir, spending_other}, memory_by_domain}`

## Chat (SSE)

`POST /api/chat/stream` `{message, session_id?, domain?, attachments?[]}` →
`text/event-stream`. Empty message + no attachments → `400`; message over
50k chars → `413`; over 10 attachments → `400`. `result` carries
`{text, model, engine: builtin|ollama|cloud, redacted_memories, …}` —
`engine` tells you which backend answered (privacy chain, see SETUP).

| Event | Payload | Meaning |
|---|---|---|
| `orb` | `{state}` | Drive the orb: thinking, retrieving, working, waiting_approval… |
| `plan` | `{trace_id, session_id, intent, domain, steps[]}` | The committed plan |
| `step` | `{id, status}` | pending → running → done / waiting_approval |
| `tool` | `{id, tool, ok}` | Hermes tool executed |
| `token` | `{text}` | Answer chunk (builtin engine sends one) |
| `approval` | `{id, risk, title, drafts[]}` | Human decision required, turn pauses here |
| `mission` | `{id, goal, status, step_idx, steps[]}` | Live mission progress (streamed for `mission_status`) |
| `slash` | `{handled, ok, command, result, text, view}` | A leading `/` short-circuited the turn; no model call, no `result` follows |
| `result` | `{text}` | Final rendered answer (markdown) |
| `done` | `{session_id}` | Always last; resume with this id |

```bash
curl -N -X POST localhost:8000/api/chat/stream -H 'Content-Type: application/json' \
  -d '{"message":"plan my day"}'
```

## Sessions & search

- `GET /api/sessions[?q=&limit=30]` → pinned-first `{id, title, domain, created_at, updated_at, pinned, starred, has_summary, n(messages)}`
- `GET /api/sessions/{id}` → `{messages: [{role, content}…]}`
- `POST /api/sessions` `{title?, domain?}` → `{id}`
- `PATCH /api/sessions/{id}` `{title?, domain?}` → `{ok}` (empty title → `400`, unknown → `404`); `DELETE` → `{ok}` (messages cascade)
- `POST /api/sessions/{id}/branch` `{title?}` → `{id}` — copies messages + rolling summary into a new session
- `POST /api/sessions/{id}/pin` `{pinned?}` / `…/star` `{starred?}` → toggles when omitted
- `POST /api/sessions/{id}/compact` → `{compacted, summary?, through?, chunk?}` — rolls everything older than `chat_context_window` (12) into the stored summary once past `chat_compact_after` (30 msgs); LLM when reachable, extractive heuristic offline. Chat turns auto-compact; summary is injected into generation context.
- `GET /api/search?q=&domain?=&limit=12&type?=&frm?=&to?` → `{results:[{type, id, title, snippet, domain, relevance, matched, meta?}], ms, pipelines:["sqlite","fts5","vector","rerank"]}` — searches tasks, projects, clients, journal, files, applications + memory engine. `type` narrows to one kind (`task|project|client|journal|file|application|memory`); `frm`/`to` bound `created_at` (ISO date/timestamp). Every result carries a `matched` explainability string ("title matches …", "semantic memory match (relevance 0.87)").

## Costs — `/api/costs`

- `GET /api/costs` → `{today, month, by_model[≤20], by_day[7], budgets}` — per-bucket `{calls, prompt_tokens, completion_tokens, cost_usd, unknown_pricing}`; `budgets:{daily_cap_usd, monthly_cap_usd, daily_over, monthly_over}`. Day/month boundaries are UTC.
- `GET /api/costs/calls?limit=50` → `{calls: [{id, at, provider, model, purpose, prompt_tokens, completion_tokens, cost_usd, ms, ok, error}…]}` newest-first (limit 1–200). `cost_usd:null` = provider didn't report usage or pricing is unknown — tokens are still recorded.
- Budgets are prefs (`cost_daily_cap_usd`, `cost_monthly_cap_usd`, `0` = unlimited) set via `PATCH /api/settings` or Settings → Cloud costs. Only metered providers (OpenRouter/OpenAI/custom) enforce caps; Ollama is tracked at $0. Over-budget cloud calls fail closed with `BudgetExceeded` (chat falls back down the chain; the block is journaled as an `ok:0` row).

## Vision — files (`/api/files/{id}`) + live (`/api/vision`)

- `POST /api/files/{id}/analyze` `{question?≤500}` → `{id, file_id, question, description, model, ms}` — describes with the Ollama vision model first, cloud vision second (only when the privacy mode allows cloud). Unknown file → `404`, non-image → `400`, no reachable vision model → `503` with an honest error (never a fabricated description). The description is also stored as a `vision`-source memory.
- `GET /api/files/{id}/analyses` → `{analyses: [{id, file_id, question, description, model, ms, created_at}…]}` (≤20, newest-first).
- Chat: `POST /api/chat/stream` attachments shaped `{"file_id": N}` (≤3 per turn; composer upload results `{"id", "name", …}` also accepted) are analyzed with your message as the question and grounded into the reply; progress streams as `vision` SSE events (`analyzing` → `done`/`unavailable`) with an orb `seeing` state; images over 3 MB are downscaled (≤1568px JPEG) before sending. Toggle: `vision_enabled` pref; local model: `ollama_vision_model` (default `llava`). Vision calls are journaled to `/api/costs` with `purpose:"vision"`.
- `GET /api/vision/status` → `{ollama_model, ollama_online, cloud_configured, available}` — honest capability report for live senses.
- `POST /api/vision/look` multipart (`frame`, `question?`, `remember?=1`) → `{description, model, ms}` — describe a camera frame/screenshot; stored as memory unless `remember=0`. Empty → `400`, oversize → `413`, no reachable model → `503`. Hermes tool: `vision.look` (R0, `{image_b64!, mime?, question?}`, 8MB cap).

## Web reader — chat `web_read` + `web.fetch`

- Paste any `http(s)` link in chat → the `web_read` intent fetches it (≤2 pages) and grounds the reply in the extracted text. Fetch guardrails: public hosts only (private/loopback/link-local blocked, redirects re-checked), HTML/text only, 1.5MB cap, 15s timeout — failures return an honest `error`, never fabricated content.
- Hermes tool: `web.fetch` (R0, `{url!}`) → `{url, title, text≤6000, links≤20}` or `{url, error}`. No new dependencies (httpx + stdlib parser).

## Web search — chat `web_search` + `web.search`

- `search the web for X` / `google it` → `web_search` intent runs a keyless
  DuckDuckGo HTML search and grounds the reply in titled links + snippets
  (`{query, results:[{title, link, snippet}], provider}`). Guardrails: 10s
  timeout, ≤6 results, honest error (never fabricated) when unreachable or
  unparseable. Provider override: `AURA_SEARCH_URL`.
- Hermes tool: `web.search` (R0, `{query!, limit?}`) — usable from mission
  steps and the LLM planner.

## Tasks — `/api/tasks`

- `GET ""?status=&domain=&q=` → `{tasks[]}` (client/project names joined)
- `POST ""` `{title!, description?, status?, priority?, due_at?, project_id?, client_id?, domain?, tags?[], recurrence?}` — status/priority normalized (`In Progress`→`in_progress`, `HIGH`→`high`)
- `PATCH /{tid}` partial → updated row; `DELETE /{tid}` → `{ok}`
- `GET /overdue/list` → `{overdue[], count}`. The key is `overdue`, not `tasks` — `api.ts`, the orchestrator's memory harvest and `e2e_check` all read `overdue`.

Task status: `inbox|planned|in_progress|blocked|waiting|completed|cancelled`.
Priority: `low|medium|high|urgent`.

## Clients — `/api/clients`

- `GET ""` → `{clients[]}` with `open_projects`, `open_tasks` counts
- `POST ""` `{name!, org?, email?, phone?, health?, notes?, contract_value?}`
- `GET /{cid}` → client + `projects[]` + open `tasks[]`
- `PATCH /{cid}` allow-listed fields → row; `DELETE /{cid}` → `{ok}`

## Projects — `/api/projects`

- `GET ""` → `{projects[]}` each with `milestones[]`, client names
- `POST ""` `{name!, client_id?, status?, progress?, deadline?, description?, health?}`
- `PATCH /{pid}` → via Hermes; `DELETE /{pid}` → `{ok}`
- `POST /{pid}/milestones` `{title!, status?, due_at?}` → stored milestone row; blank title `400`, unknown project `404`. `PATCH`/`DELETE /{pid}/milestones/{mid}` → row / `{ok}`

## Career — `/api/career`

- `GET /overview` → `{resumes, applications, interviews, today_blocks, tasks, pipeline:{stage: n}}`
- `POST /resumes/analyze` `{text!, job_description?, name?}` → `{ats_score, word_count, quantified_bullets, action_verbs, recommendations[], resume_id}` (versioned store)
- `GET /resumes` → full rows; `GET /resumes/{rid}/download` → markdown attachment
- `POST /applications` `{company, role, stage?, url?, notes?}` → `{id}`; `PATCH /applications/{aid}` allow-listed
- `POST /interviews` `{company, role, scheduled_at?, score?, feedback?, qa?}` → `{id}`
- `GET /interviews/questions?role=` → `{questions[7], role, count}`. Deterministic and offline; when a `job_description` is supplied its distinctive terms are folded into one question.
- `GET /blocks?date=` → `{date, blocks[]}`; `POST /blocks/plan` `{…}` → `{created[]}` (AI day plan); `POST /blocks` `{title?, starts_at!, ends_at!, kind?}` → `{id}`; `DELETE /blocks/{bid}`

## Personal — `/api/personal`

- `GET /overview` → `{journal[10], goals, expenses[60], habits, sleep[7], spending_total(KES), currency}`
- `POST /journal` `{title?, body?, mood?}` · `POST /mood` `{mood!, note?}` (also accepts title) · `POST /expenses` `{amount!, category?, currency?, note?}`
- `POST /goals` `{domain?, title?, target?, progress?}` → `{id}`; `PATCH /goals/{gid}` allow-listed
- `POST /habits` `{name?}` → `{id}`; `POST /habits/{hid}/done` → streak+1, `{ok}`
- `POST /sleep` `{hours? | bedtime?+wake_at?, quality?, note?}` → `{ok, hours, bedtime, wake_at}`; bad input → `400`

## Memory — `/api/memories`

- `GET ""?domain=&mtype=&q=&limit=100` → `{memories[] (excludes soft-deleted), stats:{total, by_domain}}`
- `POST ""` `{title?, content?, domain?, mtype?, source?, confidence?, importance?}` → stored row
- `POST /search` `{query!, domain?, mtype?, limit?}` → `{results[]}` (FTS5 + vector + rerank)
- `PATCH /{mid}` → `memory_engine.update` result; `DELETE /{mid}` → soft-delete `{ok}`
- `POST /forget` `{topic!}` → `{forgotten: n}` (hard erase by topic match)

## Memory consolidation — `/api/consolidation`

Nightly housekeeping over your memory table: dedupe, importance re-scoring, and
archival of low-signal rows. Every write is a **soft** delete (`deleted_at`) or a
`supersedes_id` pointer — there is no login here, so there is no way to prove a
hard delete was intended.

- `GET ""` → `{enabled, due, last_run}` — `due` is true at most once per 24h and
  only while `consolidate_enabled` is on; `last_run` is the most recent
  `Consolidation pass` activity row, or `null`.
- `POST /run` → `{scanned, merged, archived, rescored, duration_ms}` — runs one
  pass immediately and moves the `consolidate_last_run` watermark to now.
- Re-scoring is the idempotent pass and the one the watermark guards: it scores
  a signal (`last_confirmed`, or a `user-corrected:` source) only when the
  signal's whole-second timestamp is strictly newer than the watermark, so
  back-to-back passes cannot ratchet importance toward its cap. Dedupe and
  archival stay stateful by design — merging and retiring rows is the point.
- Archival only touches rows older than 30 days that are low-importance,
  low-confidence, never re-confirmed and `normal` sensitivity; a row this pass
  re-scored is promoted out of the archive set and picked up by a later one.

## Automations — `/api/automations`

- `GET ""` → `{automations[]}` (incl. success/fail counts, next_run)
- `POST ""` `{name?, trigger_kind?, trigger?, action_kind?, action?, next_run?}` → `{id}` — trigger `schedule|event|manual|feed|file`; only `schedule` gets a `next_run` (every other kind is one-shot), action `notify|backup|chat|webhook|brief|proactive|terminal|home|script`.
- **Actions are validated before the row is written** (and again on `PATCH` against the merged config); a rejected action returns `400` and persists nothing:
  - `webhook` `{url!, secret?, payload?}` — `https` required; `http` is accepted **only** for loopback (`localhost`/`127.0.0.1`/`::1`) so a same-box integration works without cleartext leaving the machine. Fires a signed POST: body `{"event":"automation.fired", "automation_id", "trigger", "data", "idempotency_key"}`, headers `X-Aura-Event`, `X-Aura-Idempotency-Key` and `X-Aura-Signature: sha256=<hmac(secret, exact body bytes)>` when a `secret` is set. Failures back off exponentially (2m→32m, then `next_run` cleared) and record `fail_count` + `_retry_n`; a success clears `_retry_n`.
  - `terminal` `{command!, machine?}` — `400` at creation for `dangerous` patterns; fires through the audited exec path (`source=automation`).
  - `home` `{domain!, service!, entity_id?, data?}` — `entity_id`/`entity` must match `domain.object_id`; every token is `[A-Za-z0-9_]+`, so metacharacters never reach the gateway.
  - `script` `{script_id? | name!}` — must resolve to a real script, else `400 unknown script`.
  - `brief` `{briefing_id? | kind?}` (`morning|evening|weekly|custom`; `custom` needs `prompt`) — runs the briefing and posts a notification.
  - `notify|chat` → `comms.send`, which suppresses an identical send within 60s.
- `PATCH /{aid}` allow-listed (incl. `status` active/paused) → `{ok}`; unknown id → `404`
- `POST /{aid}/run` → forces due + ticks → `{ran: [{id, ok, name, error?}]}`; with `?dry_run=true` → `{dry_run: true, fired: {ok, error?}, blocked[]}` and `last_run`/`next_run` untouched; unknown id → `404`. `DELETE /{aid}` → `{ok}`
- Event kinds (`feed`/`file`) fire through `fire_event`, which shares the scheduled path's counters and audit trail. `proactive` actions call `notify_top(scan())` — `scan()` alone only ranks and never surfaces anything.
- `POST /{aid}/run` → forces due + ticks → `{ran: n}`; `DELETE /{aid}` → `{ok}`

## Missions — `/api/missions`

- `POST /{mid}/schedule` `{every: off|hourly|daily|weekly}` → mission with `schedule_json` + `next_run_at` (bad value → `400`, unknown id → `404`). Due schedules relaunch finished missions (done/failed/cancelled) on the scheduler tick — drafts still need review, paused/running/awaiting are left alone; stepless missions have their schedule cleared instead of launching.
- `GET /{mid}/runs` → `{runs: [{id, mission_id, started_at, finished_at, status, summary}]}` (≤10, newest-first). Runs open on start (manual or scheduled) and close on done/fail, which also notify in-app + Web Push.

- `POST ""` `{goal!, planner?: auto|template|llm}` → `{id, goal, status: draft, steps[], needs_review, message, planner}` — goal delegation. `auto` (default): template → LLM → keyword; `template`: template → keyword (no model call); `llm`: LLM → template → keyword. Full template matches (plan my day, inbox zero, follow up, backup, brief me, weekly review) run on start; LLM plans (JSON-only prompt over the R0–R2 tool catalog, R3/R4 + unknown tools filtered, max 8 steps) and keyword guesses always return `needs_review`; unknown goals return empty steps + hint and refuse to start until steps are set. Bad `planner` → `400`.
- `GET ""` → `{missions[]}`; `GET /{mid}` → mission or `404`.
- `PATCH /{mid}` `{steps[]}` → mission — set steps manually (`{kind: tool, tool, args?, label?}` with known tools only, or `{kind: send_drafts, drafts_from}`); unknown tools are dropped, empty → `400`.
- `POST /{mid}/control` `{action: start|pause|cancel}` → mission — one step executes per scheduler tick. R0/R1 run unattended; R2+ steps and `send_drafts` create approvals and park the mission in `awaiting`; resolving the approval resumes it (`result.mission`). Terminal: `done` (with `result` summary) / `failed` / `cancelled`. Every transition notifies; per-step check-ins via `mission_step_checkins` pref (default off).
- Chat: `how are my missions going` → `mission_status` intent streams per-step progress as SSE `mission` events and summarizes in the reply.
- Routines: briefing digests include `routines[]` (productive weekday, sleep drift, top spend — from `routines.py`, honest empties); proactive gains a `routine_drift` detector (sleep down >1h vs prior week → open Personal).

## Mission board — `/api/board`

A drag-drop **view** over mission status, never a second source of truth: every
move goes through `missions.set_status`, so it cannot bypass the approval flow.

- `GET ""` → `{columns: [{key, label, missions: [{id, goal, status, steps_total, steps_done, next_run_at, created_at, updated_at}]}], counts, total, limit}`. Four fixed columns: `backlog` (`draft`, `paused`), `running`, `awaiting` ("Needs you"), `done` (`done`, `failed`, `cancelled`). Only the newest `limit` (100) missions are loaded, so `counts` is a truncated figure — `total` is the real row count.
- `POST /move` `{mission_id!, column!}` → `{ok, mission}`. `400` unknown column or non-integer `mission_id`, `404` unknown mission, `409` an illegal move. Moving to the column the card is already in is a no-op `200`.
- Legal moves: `backlog→running` (start), `running|awaiting→backlog` (pause), and `backlog|running|awaiting→done` (**cancel**). There is no move *into* `done` that completes a mission — the only route to `done` is a mission actually finishing, so a drag to Finished cancels the card.

## Worker queue — `/api/workers`

A persistent job queue (`worker_jobs`) drained by an in-process `ThreadPoolExecutor`.
Concurrency is threads, not asyncio, because the DB layer is one pooled SQLite
connection behind an RLock; what genuinely parallelises is tool execution, which
releases that lock while it waits on the network.

- `GET ""` → `{stats: {queued, running, done, dead, throughput_per_min, error_rate, by_kind}, pool_size}`. `throughput_per_min` counts only jobs that **settled** (`done` or `dead`) in the last 60s — an enqueue is not throughput. `error_rate` is `dead / (done + dead)`, so it is `0.0` by construction when nothing has settled. `pool_size` is `worker_pool_size` clamped to 1–8.
- `GET /dead[?limit=50]` → `{dead: [{id, kind, attempts, max_retries, last_error, updated_at}]}` — jobs that exhausted their retries, newest first.
- `POST /drain` → `{ran, done, retried, dead}` — claims a batch (`min(limit, pool_size * 4)`), runs it on the pool, and settles each outcome. `retried` means the job is back on the queue with exponential backoff (`2^attempts * 5s`, capped at 5 min); `dead` means it dead-lettered.
- `attempts` counts **executions**, not failures: `claim` increments it, so
  `max_retries: 3` runs a job at most 4 times (3 retries, then dead-letter).
- Interrupted `running` jobs are returned to `queued` once at startup, so a
  restart loses nothing.
- **Known gap:** nothing in production calls `workers.enqueue`, so the counters
  above read zero and a drain is a no-op. The mission and schedule ticks run
  inline on the scheduler thread precisely because enqueuing them would race that
  call and fire a step twice.

## Slash commands — `/api/slash`

26 built-ins across six categories (`Navigation`, `Memory`, `Tasks`, `Automation`,
`System`, `AI`) plus any custom commands. A command is deterministic, so it must
not spend a model call.

- `GET ""` → `{commands: [{name, category, summary, example, arg}]}` — Python
  handlers are stripped; they never cross HTTP.
- `POST /execute` `{text}` → `{handled, ok, command, result, text, view}`.
  `handled: false` means the text was not a command. `execute` never raises: a
  bad command is a `200` with `ok: false` and the reason in `text` (e.g. a
  missing argument returns `Usage: /task <title>`), because a `500` here would
  abort the chat stream it was fired from.
- `POST /custom` `{name!, prompt!, view?}` → `{name, prompt, view}`; `DELETE /custom/{name}` → `{ok}` (accepts `/brief` or `brief`). `400` if the name does not start with `/`, contains whitespace, has no prompt, shadows a built-in, or names a `view` outside the shell's `View` union.
- Chat: a leading `/` in `POST /api/chat/stream` short-circuits **before** the
  orchestrator runs and emits a single `slash` SSE event (plus `done`), never a
  `result`. Matching is at position 0 only, so prose containing a slash mid-
  sentence is untouched, and any attachment disqualifies the shortcut.
- Frontend: `/` in the Composer opens the command palette; the full cheat sheet
  (with custom-command CRUD) lives in Settings → Commands.

## Proactive — `/api/proactive`

- `GET \"\"[?include_dismissed=true]` → `{opportunities[]}` — ranked finds, each `{key, type, title, detail, reasons[], importance, urgency, confidence, disruption, score, ref, action}`; `reasons[]` is the explainability surface ("because …"); `action` is `{kind, label, …}` (`create_task`/`run_backup` execute, `mission` creates + schedules + starts a mission, `draft`/`open`/`chat` are client-handled). Score = `i·u·c·(1−0.5d)`; threshold pref `proactive_threshold` (default 0.1), mute list `proactive_muted`, master switch `proactive_enabled`. Resolved + snoozed items are excluded.
- `POST /scan` → re-runs all detectors, upserts `{opportunities[], notified}` (notified = key pushed this scan, if any; 20h cooldown). Previously-seen keys no longer detected are auto-`resolved` (re-detection un-resolves).
- `PATCH /{key}/dismiss` `{dismissed: bool}` → `{key, dismissed}` (unknown key → `404`); undismiss also clears snooze.
- `POST /{key}/snooze` `{hours?}` → `{key, snoozed_hours}` (1–168, default 24; unknown → `404`, bad hours → `400`).
- `POST /{key}/act` → executes the action: `{ok, kind, task?/result?}` for `create_task` (undo-journaled via Hermes) / `run_backup`; echoes `{ok, kind, action}` for `draft`/`open`/`chat`; `{ok:false, gone:true}` when already resolved.
- `GET /resolved[?limit=20]` → `{resolved[{key, type, title, resolved_at}]}` — auto-resolution history.

## Analytics — `/api/analytics`

- `GET /overview` → `{spending, tasks, habits, sleep, mood, activity, forecast}` — read-only aggregates for dashboards; empty datasets return honest empties (`[]`, `null`), never zeros dressed as data. `spending` = `{by_currency[{currency, month, last_month, delta_pct|null}], by_day[{day, currency, total}] (14d), by_category[{category, currency, total}] (30d)}`; `tasks` = `{done_14d[{day, n}], created_30, done_30, completion_rate|null, overdue_now, by_status{}}`; `habits` = `[{name, streak, last_done, done_today}]`; `sleep` = `{avg_7d|null, nights[{date, hours}]}`; `mood` = `{avg_14d|null, points[{day, score}]}` (journal `n/10` or `mood n`); `activity` = `{runs_14d[{day, n}], messages_14d[{day, n}]}`; `forecast` = `{spending_next_7d|null, task_velocity_per_day|null, tasks_next_7d|null, sleep_trend|null, mood_trend|null}` — least-squares projections, `null` under 3 data points.

## Undo & dry-run — `/api/undo`, `/api/hermes/tools`

- `GET /api/undo` → `{journal[{id, at, tool, op, tbl, row_id, summary}], undoable, remaining}` — last 10 journaled writes shown; `remaining` is the true total (tasks, clients, projects, memories, events; cap 50).
- `POST /api/undo` `{steps?}` → `{undone[{id, summary, result}], remaining}` — applies inverse ops (create→delete, update/delete→restore before-image). Chat: "undo that".
- `POST /api/hermes/tools/{name}/dry-run` `{args?, ctx?}` → `{dry_run, ok, result?, error?, blocked[]}` — executes R0/R1 tools with writes rolled back and LLM/network/file effects suppressed (`blocked[]` lists them, e.g. `"push: notifications not sent"`). Unknown tool → `404`, R2+ → `403`. A dry run never consumes the send-dedup fingerprint, so previewing cannot suppress the real send.

## Activity & notifications

- `GET /api/activity?kind=&domain=&limit=100` → `{activity[]}`
- `GET /api/notifications` → `{notifications[50], unread}`
- `POST /api/notifications/{nid}/read` · `POST /api/notifications/read-all` → `{ok}`

## Approvals — `/api/approvals`

- `GET ""?status=pending` → `{approvals[]}` each with parsed `detail:{drafts[], channel}`
- `POST /{aid}/resolve` `{decision!: approved|rejected|cancelled, drafts?[]}` → `{decision, sent?[]}`. Anything else for `decision` → `400`. Supplied `drafts` **override** the stored ones, are what gets sent, and are persisted as `detail.drafts_sent` (originals kept).

## Gateway — `/api/gateway`

- `GET /status` → `{integrations[6]: {platform, status, account, last_test, mode, configured, missing[], fields (secrets redacted), last_error}, events[20]: {id, platform, actor, direction, text, ts}}` (incl. `homeassistant` control plane). `events` is the canonical `gateway_events` feed — inbound and outbound, always carrying `platform`.
- `POST /{platform}/connect` `{account?, mode?: sandbox|live, config?{...}}` → `{ok, mode}` (platform: telegram|discord|slack|whatsapp|email|homeassistant); live requires credentials or `400` (`missing live credentials: …`); telegram needs `bot_token`, whatsapp needs `webhook_url` **or** Cloud `wa_token`+`phone_number_id`, homeassistant needs `base_url`+`token`.
- `POST /{platform}/disconnect` `{forget?}` → `{ok}`; `POST /{platform}/test` → `{ok, platform, latency_ms, detail?}` (measured, marks connected; webhook platforms get one real test message)
- `POST /simulate` `{platform?, text?, send_live?, to?}` → `{event_id, sent?, mode?}` (inbound simulation onto the bus, or real live delivery)
- `POST /telegram/poll` → `{ok, fetched, inbound[{chat_id, text}], replies}` — getUpdates since stored offset (works behind NAT); honest `{ok:false, error}` when not connected/live.
- `POST /telegram/webhook` (header `x-telegram-bot-api-secret-token` when `webhook_secret` set) → `{ok, handled, replied?}` (bad secret → `403`); needs a public URL.
- `GET /whatsapp/webhook?hub.mode&hub.verify_token&hub.challenge` → challenge text (mismatch → `403`); `POST /whatsapp/webhook` → `{ok, inbound[], replies, skipped}` (Meta Cloud format; always `200`).
- Inbound texts land on the event bus + a `message` notification; `auto_reply` config (empty = off) sends a canned reply via the live sender.

## Home — `/api/home` (Home Assistant control plane)

- Connection reuses the gateway: `POST /api/gateway/homeassistant/connect` (live needs `base_url`+long-lived `token`), `POST …/test` (pings `GET /api/`, expects `API running`), `POST …/disconnect`. `send()` refuses HA politely — it is control, not messaging.
- `GET /status` → `{platform, status, account, last_test, mode, configured, missing[], fields (redacted), last_error}`.
- `GET /entities` → `{entities[{entity_id, state, attributes}], mode}` — sandbox serves 3 labeled demo entities; 401s/network faults return `{entities: [], error}` honestly.
- `POST /service` `{domain!, service!, entity_id?, data?}` → `{ok, mode?, state?, error?}` — calls `POST /api/services/{domain}/{service}`; sandbox flips demo state in memory. Hermes tools: `home.entities` (R0, `{domain?}` filter), `home.control` (R1).

## Files — `/api/files`

- `POST /upload` multipart (`files[]`, `domain?`) → `{files:[{id, name, size, indexed_chars, pages, extract_error}]}` — text/markdown/CSV/JSON/YAML/log (20k chars), **PDF** (pypdf + page count), **DOCX** (paras+tables), **XLSX** (all sheets), **PPTX** (slides+tables), images (format+dimensions). Failures report `extract_error`, never 500. Indexed text is also stored as memory.
- `GET ""` → `{files[]}` (no blobs); `GET /{fid}` → download (404 if missing)

## Voice — `/api/voice`

- `POST /log` `{transcript?, domain?}` → `{ok}` (audit trail; STT happens in-browser)
- `GET /config` → `{stt, tts, voices, language: "en-KE", note}`
- `GET /status` → `{stt_installed, tts_installed, whisper_model, whisper_ready, piper_voice, piper_ready, note}` (server voice; needs `requirements-voice.txt`)
- `POST /transcribe` multipart (`audio`) → `{text, language, duration}`; `503` when deps missing
- `GET /engines` → `{engines: [{id, label, offline, available, voices?, features, note}], emotions[6], current}` — `browser` (system voices), `piper` (5 voices, offline), `edge` (8 neural voices incl. 4 Kenyan, needs Hybrid/Cloud privacy + `edge-tts`)
- `POST /speak` `{text!, engine?, voice?, emotion?, rate?, pitch?}` → `audio/wav` (piper, 1500-char cap) or `audio/mpeg` (edge); engine omitted → `voice_engine` pref (legacy `{text}` → piper). `400` empty/unknown engine/voice, `403` edge under local-first privacy, `503` when deps missing. Markdown is stripped; smart breaks + emotion prosody applied (full mstts acting on Edge US voices).
- `GET /loop/status` → `{wake_available, wake_model: "hey_jarvis_v0.1", wake_enabled, whisper, tts, ws}` — honest capability report for the always-on loop.
- `WS /loop` — full-duplex voice: client streams 16kHz mono PCM16 binary; server emits JSON `{t: hello|state|wake|utterance|transcript|answer|barge|error}` + binary TTS clips. Text commands: `talk` (tap-to-talk), `played` (clip finished → follow-up window), `stop`. States: sleeping → listening → thinking → speaking → listening (6s follow-up) → sleeping. Barge-in is wake-word-only while speaking (no echo cancellation). Without the wake dep the loop runs tap-to-talk; without server TTS the client falls back to browser speech. Prefs: `wake_enabled` (default off), `wake_threshold`, `vad_energy`, `followup_ms`, `barge_in`.

## Ollama model room — `/api/ollama`

- `GET /status` → `{reachable, base_url, model_count, synced_at, stale, error, chat_model, vision_model, embed_model, auto_sync}` — `reachable:false` + cached catalog = honest stale view (never fabricated)
- `GET /models` → `{reachable, base_url, models: [{name, family, size_bytes, size, parameter_size, quantization, capabilities[], modified_at, note}]}` (SQLite-cached catalog synced from Ollama `/api/tags`; capabilities inferred from the family table — `chat|vision|embed|tools`)
- `POST /sync` → `{ok, models, synced_at, base_url, names[]}` — `502 {ok:false, error}` when Ollama is unreachable (previous cache survives)
- `POST /default` `{role: chat|vision|embed, model!}` → `{ok, role, model}` — `400` when the name isn't in your verified catalog (cache first, live probe fallback; refuses when verification is impossible). Prefs: `ollama_base_url`, `ollama_chat_model`, `ollama_vision_model`, `ollama_embed_model` (now honored by the embedder), `ollama_auto_sync` (default on), `ollama_sync_interval_min` (default 30)

## Terminal — `/api/terminal`

Runs commands on the machine AURA lives on (single-user fortress; remote via Tailscale — no login by design). Every exec is classified `safe` (read-only allowlist incl. subcommand checks — `git status` yes / `git push` no / `find -delete` no) | `guarded` | `dangerous` (refused unless `terminal_allow_dangerous`; `git clean -f`, `rm -rf /`, `mkfs`, `dd of=/dev/*`, `curl|sh`, fork bombs, …).

- `GET /config` → `{enabled, cwd, timeout_s, max_out_kb, allow_dangerous}` · `PATCH /config` `{cwd}` → validates dir exists (`~` expanded)
- `POST /exec` `{command!, machine? = "local", timeout?}` → `{ok, exit_code, output, duration_ms, machine, cwd, risk, truncated}`; refusals return `200 {ok:false, denied:true, error}` (reason + how to allow). Output beyond `max_out_kb` is truncated with a marker; timeouts are `ok:false, error:"timeout after Ns"`; dry-run previews return `{dry_run:true, would}` and never execute
- `GET /machines` → `{machines: [{name, host, kind: local|ssh, ssh_ready?}], ssh_available}` · `PUT /machines` `{machines: [{name, host}]}` → `400` on duplicate/`local` names or hosts that aren't `[A-Za-z0-9@._:-]`; ssh runs use `BatchMode=yes` + `ConnectTimeout=8` (key auth only — it will never hang on a password prompt)
- `GET /history?limit=` → `{runs[]}` — full audit trail: `source (ui|chat|automation)`, machine, command, cwd, `exit_code`, `duration_ms`, `out_kb`, risk, `status (ok|error|denied|timeout|disabled)`, note
- Hermes tool `system.run` (R3 — chat-visible, excluded from unattended mission plans); chat intents: `terminal_run` ("run `git status` in my terminal", "execute the command: whoami"), `ollama_models`, `ollama_switch`, `feeds_latest`, `feed_follow`, `weather`

## Feeds — `/api/feeds`

- `GET ""` → `{feeds: [{id, url, title, last_fetched, error, n_items, n_unread}], items: [{id, feed_id, guid, title, link, published, fetched_at, read, feed_title, feed_url}]}` (40 newest items)
- `POST ""` `{url!}` → `{id, title, items}` — http(s) only (`400`), follows + pulls immediately; duplicate URL → `{id, already_existed:true}` · `DELETE /{fid}` → `404` when unknown
- `POST /refresh` → `{feeds, new_items, errors, results[]}` (per-feed `error` is honest; guid dedupe; new items → notification + feed-kind automations fire) · `POST /items/{iid}/read` `{read?}` toggles
- Pref `feeds_refresh_min` (default 30, `0` off); tools `feeds.latest` / `feeds.follow`; morning briefs include a "Fresh from your feeds" line

## Weather — `/api/weather`

- `GET ?refresh=` → Open-Meteo (no key): `{ok:true, place, temp_c, feels_c, humidity_pct, wind_kmh, condition, today: [{date, high_c, low_c, rain_pct, condition}], cached}` — 15-min cache; unconfigured/off → `{ok:false, reason, configured}`. Settings: `weather_enabled`, `weather_lat`, `weather_lon`, `weather_place` (lat+lon both 0 = unset). Morning brief gains a weather line incl. umbrella warning ≥50% rain.

## Script library & folder watch — `/api/scripts`, `/api/watch`

- `GET /scripts` → `{scripts: [{id,name,command,machine,description,run_count,last_run,last_status}]}` · `POST /scripts` `{name!,command!,machine?,description?}` → `{ok,id,name,risk}` — `400` for bad names (2-40 chars lowercase), empty/oversize commands, **dangerous commands**, or unknown machines; re-save upserts by name · `DELETE /scripts/{id}` · `POST /scripts/{id}/run` `{args?}` → same shape as `POST /terminal/exec` plus `script` (name) — audited as `source=ui|chat|automation`, counters updated. `{placeholder}` slots in commands are filled with shell-quoted arg values; hostile payloads still hit the danger gate
- `GET /watch` → `{enabled, ingest, paths[], interval_s, default_dir, recent[{path,size,mtime,file_id,ingested,last_event}]}` · `PUT /watch/paths` `{paths[]}` → `400` for anything not an existing dir (creation only allowed under the data dir) · `POST /watch/scan` → `{new, changed, skipped_ext, errors, scanned_at}` (works even while disabled; scheduler honors `watch_enabled` + `watch_scan_interval_s`) · `POST /watch/reset` → re-arm change detection
- Settings: `watch_enabled` (default off), `watch_ingest` (index text into memory, on), `watch_paths` (JSON list). Automation `trigger_kind="file"` automations fire on new/changed files (`trigger: {contains|pattern}` matched against filename+path, fnmatch supported)
- Tools: `scripts.list` (R0), `scripts.run` (R3), `scripts.save` (R1). Chat “run my X script” routes through `terminal_run` → script-aware step

## Machine liveness — `/api/terminal/check`

- `GET ?machine=name&port=` → `{ok, ms, host, port, detail}` — a 1.5s TCP connect probe of the ssh target (port defaults 22, `host:port` in the saved target wins). `machine=local` → always up (it's the AURA host). Unknown machine → `{ok:false, error:"unknown machine: …"}`

## Security model (v1.15)

- **Origin guard**: any `POST/PUT/PATCH/DELETE` to `/api/*` carrying an `Origin` header whose host ≠ request `Host` is `403` (`AURA_ALLOWED_ORIGINS` env extends it, comma-separated origins/hosts). Browser same-origin app traffic, service workers on the same origin, and non-browser callers (provider webhooks, curl, cron) pass untouched; GETs are never gated.
- Terminal & scripts: danger-pattern gate at exec and at script save; unattended automations never run dangerous commands even with the global allow-on; every exec audited in `terminal_runs`.
- Fortress posture: single-user, no login, bind to LAN/Tailscale only (`0.0.0.0` + your VPN); `AURA_CORS` can still lock origins explicitly for stricter deployments.

## Voice calls — `/api/voice/calls`

- `POST ""` `{transcript!, mode: browser|fortress|tap, started_at?, ended_at?, seconds?}` → `{ok, id, summary, model, call}` — `turns` counted from `You:` lines; summary via the model router (`call_summary` pref) with a deterministic digest fallback offline; transcript stored as a memory (`source=voice_call`). `400` empty transcript / bad mode
- `GET ""?limit=` → `{calls: [{id, started_at, ended_at, mode, seconds, turns, summary, model, source}]}` · `GET /{cid}` → full row + `turns_list` · `DELETE /{cid}`
- The Call screen (voice view → "Call AURA", palette → "Start a voice call") owns the live loop: continuous Web Speech STT with interim captions, barge-in, spoken replies through the configured TTS engine, hold-to-talk fallback via `POST /transcribe`, then this save call on hangup.

## Backups — `/api/backup`

- `POST /run` `{target?}` → `{ok, file?, size_bytes?, sha256?, error?}` — SQLite online snapshot + uploads tarball; failures recorded, never partial
- `GET /history` → `{backups[] (run log), files[] (restorable archives on disk), litestream: {enabled, replica?}}`
- `POST /restore` `{file!}` → `{ok, uploads_restored?, safety_copy?, error?}` — basename-guarded, integrity-checked, live data safety-copied first

## Push — `/api/push`

- `GET /vapid-public-key` → `{key?, configured}` (VAPID; empty until keys set)
- `POST /subscribe` `{endpoint! (https), keys: {p256dh!, auth!}}` → `{ok, subscriptions}`; bad input → `400`
- `POST /unsubscribe` `{endpoint!}` → `{ok}`
- `POST /test` `{title?, body?, url?}` → `{sent, dropped, skipped}` (skipped when VAPID unconfigured; 404/410 endpoints pruned)

## Briefings — `/api/briefings`

- `GET ""` → `{briefings[]}`; `POST ""` `{name!, kind: morning|evening|custom, prompt?}` → `{id}` (bad kind → `400`)
- `PATCH /{bid}` allow-listed → updated; missing → `404`; `DELETE /{bid}` → `{ok}`
- `POST /{bid}/run` `{extra?}` → `{output}` (cloud chain → builtin fallback; posts a notification); `POST /run-now` `{kind?, extra?}` → `{output}` without saving
- `GET /runs/list?briefing_id=&limit=20` → `{runs[]}`

## Mail — `/api/mail`

- `GET /accounts` → `{accounts[]}` (`has_password` flag; secrets never serialized); `POST /accounts` `{name!, mode: sandbox|live, host?, port?, username?, password?}` → `{id}` (live without creds → `400`); `PATCH /accounts/{aid}` (mode→live needs creds); `DELETE /accounts/{aid}` → `{ok}` (cascades emails)
- `POST /accounts/{aid}/sync` → `{ok, new}` (sandbox seeds 8 sample mails, idempotent; live pulls IMAP)
- `GET /emails?account_id=&unread_only=&triage=&limit=50` → `{emails[] (no bodies), unread}` (bad triage → `400`); `GET /emails/{mid}` → full + `body`
- `PATCH /emails/{mid}` `{seen?, triage?}` → updated (bad triage → `400`); `POST /triage` `{account_id?, limit?}` → `{triaged: n}` (rules + optional LLM)

## Calendar — `/api/calendar`

- `GET /calendars` → `{calendars[]}` (local default auto-created; secrets redacted, `secrets_set` flags); `POST /calendars` `{name!, source: local|caldav|google, url?, username?, password?, client_id?, ...}` → `{id}` (caldav needs url, else `400`); `PATCH /calendars/{cid}`; `DELETE /calendars/{cid}` → `{ok}`
- `POST /calendars/{cid}/sync` → `{ok, new}` (CalDAV REPORT pull / Google confirmed-only pull)
- `GET /events?start!&end!` → `{events[]}` (bad range → `400`); `GET /today` · `GET /week` → `{events[]}`
- `POST /events` `{calendar_id?, title?, starts_at!, ends_at!, description?, location?, all_day?}` → `{id}` (bad dates / end<start → `400`); `PATCH /events/{eid}`; `DELETE /events/{eid}` → `{ok}`
- `GET /google/auth-url?calendar_id!&redirect_uri!` → `{url}`; `GET /google/landing?code=` → copy-paste code page (HTML); `POST /google/callback` `{calendar_id!, code!, redirect_uri!}` → `{ok}` (stores refresh token)

## Sync — `/api/sync`

- `GET /export?device=` → `aura-sync/1` `{format, exported_at, tables{}}` (no credentials, no push/observability rows; logs the export)
- `POST /import` `{bundle!, device?}` → `{tables{inserted/skipped/conflicts}, conflicts[], inserted}` — natural-key merge, FK re-link, local-wins; bad bundle → `400`
- `GET /log?limit=20` → `{log[]}` (import/export history with per-table stats)

## Hermes direct — `/api/hermes`

- `POST /tools/{name}` `{args?, ctx?}` → tool result. Unknown → `404`. Tools with risk `R2+` (e.g. `comms.send`) → `403`, must flow through approvals. Plugin tools (`plugin.*`, incl. shipped `text_stats` + `unit_convert`) work here; `/api/tools` also reports `plugins: {loaded[], failed[]}`.
- `POST /skills/{skill}` `{args?, ctx?}` → skill result (`meeting_prep {who}`, `client_followup`, …)

## Risk levels

`R0` read-only · `R1` local write · `R2` external/visible (approval-gated) ·
`R3/R4` reserved for future destructive/privileged tools.
