# AURA OS — Roadmap: what it still needs

Honest assessment after a full audit. Ordered by impact. Single-user is a
deliberate design choice (item 1 deferred by owner). Items 2–15 all shipped;
v1.14 added the machine layer, v1.15 hardened it (261 unit + 85 frontend +
101 E2E + 299 router-eval + 27 agent-eval green).

## Shipped in v1.15.0 — Fortress hardening

- ~~**CSRF/drive-by protection**~~ — `OriginGuardMiddleware`: cross-site
  mutations (incl. terminal exec) 403 unless same-origin or explicitly
  allowed via `AURA_ALLOWED_ORIGINS`; webhooks and local scripts unaffected.
- ~~**Named scripts**~~ — save/run/delete rituals by name from UI, chat
  (“run my X script”) or automations (`script` action kind); danger-gated at
  save and every run; `{arg}` slots shell-quoted.
- ~~**Folder watch**~~ — drop files into `<data>/inbox` (or any dir):
  auto-registered, text-indexed into memory, notified, and fires `file`
  automations; change-detection via mtime+size; manual scan/reset.
- ~~**Machine liveness**~~ — `/api/terminal/check` TCP probe per configured
  machine; Check button in the Terminal screen.
- ~~**Disk guard**~~ — `disk_low` proactive detector with self-clear.
- QoL — Recent Calls panel + ↑ command recall; fixed `feed` automations
  double-firing daily (event kinds stay one-shot).

## Shipped in v1.14.0 — The Machine Room

- ~~**Local terminal**~~ — `system.run` tool + Terminal screen: commands run
  on the AURA host through a safe/guarded/dangerous classifier (dangerous
  refused, all audited in `terminal_runs`), cwd control, quick commands.
- ~~**Multi-machine**~~ — named ssh targets (`ssh` BatchMode, key auth only)
  selectable per-command; host strings validated; unavailable binary degrades
  honestly.
- ~~**Ollama model sync**~~ — every model on the box inventoried
  (`ollama_models` cache + capabilities inference), one-tap chat/vision/embed
  defaults, background auto-sync, `ollama_embed_model` now honored.
- ~~**Hands-free voice calls**~~ — ChatGPT-advanced-voice-style overlay:
  continuous listen → caption → answer → speak, barge-in, mute, call
  transcript + summary persisted (`calls` table, memory-linked).
- ~~**More integrations**~~ — RSS/Atom feeds (zero-key, guid-deduped,
  notification + brief-integrated) and Open-Meteo weather (no key at all).
- ~~**More automations**~~ — new action kinds `terminal` + `home`, new event
  trigger kind `feed` (keyword-matched, fires on discovery), weather+feeds
  inside the morning brief.
- **Bug fixes** — eval harness timezone seeding, feeds INSERT-OR-IGNORE
  lastrowid overcount, terminal classifier subcommand holes, Atom namespace,
  `fire_webhook` docstring placement.

## Shipped in v1.13.0

- ~~**Performance benchmarks + CI gate (§38)**~~ — `scripts/benchmark.py`
  gates the hot paths (chat turn, tools, memory/search, DB, planning) in CI.
- ~~**Idempotency (§39)**~~ — webhook `X-Aura-Idempotency-Key` (`_fire_id`)
  + `comms.send` 60s duplicate suppression (`send_dedupe` table).
- ~~**Search filters + explainability (§31)**~~ — `type`/`frm`/`to` filters
  and a `matched` reason on every result.
- ~~**Autonomous skill improvement (§50)**~~ — `routine_mission` detector
  proposes turning 3×-run missions into scheduled routines.
- ~~**Advanced analytics (§50)**~~ — `forecast` (spend/tasks/sleep/mood) with
  honest nulls + Forecast panel.
- ~~**Parallel subagents (§76)**~~ — concurrent R0 step execution in chat
  plans (`chat_parallel_steps` pref).

## Shipped in v1.12.0

- ~~**Advanced proactive intelligence (auto-action)**~~ — the repeated-chore
  and stale-backup opportunities now resolve into a **scheduled mission** in
  one click: mission created (auto planner + concrete fallback), schedule
  applied, R0/R1 plans auto-start, opportunity resolved. The detect → act
  loop is now closed end-to-end.
- ~~**Deeper agent delegation (web search)**~~ — `web.search` R0 Hermes tool
  + `web_search` chat intent: keyless DuckDuckGo search, SSRF-guarded,
  capped, honest off-state; results render as titled links + snippets and
  the tool is available to mission plans + the LLM planner.
- ~~**Mission visibility in chat**~~ — `mission_status` intent streams live
  per-step progress as SSE `mission` events into the chat thread.

## Shipped in v1.11.0

- ~~**Scheduled missions**~~ — `POST /api/missions/{mid}/schedule
  {every: off|hourly|daily|weekly}` relaunches finished missions on the 30s
  scheduler tick (same trigger format as automations). Drafts still need
  review; paused/running/awaiting left alone; stepless missions clear their
  schedule. `mission_runs` history (`GET /{mid}/runs`) opens on start and
  closes on done/fail; mission completion fans out via Web Push. UI repeat
  picker + next/last run per mission card.

## Shipped in v1.10.0

- ~~**LLM mission planner**~~ — `POST /api/missions {goal, planner=llm}`
  drafts novel multi-step plans from the R0–R2 tool catalog (always
  `needs_review`).
- ~~**Live senses**~~ — `POST /api/vision/look` (frame + optional question)
  with an honest capability report; Files-view Look panel.
- ~~**Web reader**~~ — paste a link in chat → `web_read` fetches (SSRF
  guards, ≤2 pages) and grounds the reply.

## Shipped in v1.9.0

- ~~**Always-on voice loop**~~ — "hey jarvis" wake word + full-duplex
  `WS /api/voice/loop`; tap-to-talk + browser-TTS fallbacks.
- ~~**Missions (goal delegation)**~~ — plan a Hermes tool chain from a goal;
  R0/R1 run unattended, R2+ park in `awaiting`; every transition notifies.
- ~~**Routine learning**~~ — briefing `routines[]` + `routine_drift` detector.
- ~~**Smart Home**~~ — Home Assistant gateway (`base_url`+token,
  sandbox/live), Smart Home view, `home.entities`/`home.control` tools.
- ~~**Reachability**~~ — `docs/REMOTE_ACCESS.md`: always-on host, Tailscale
  + `serve` HTTPS, Funnel for bot webhooks, go-live checklists.

## Shipped in v1.8.0

- ~~**Advanced proactive intelligence**~~ — 8 detectors with per-type
  executable actions, snooze, auto-resolution + history.
- ~~**Analytics dashboards**~~ — read-only overview (spend, tasks, streaks,
  sleep, mood, activity) with honest empty states.
- ~~**Messaging bots via gateway**~~ — Telegram polling + secret webhook,
  WhatsApp Cloud send + Meta handshake, inbound on the event bus;
  token-ready off-states until live credentials are added.

## Shipped in v1.7.0

- ~~**Human-like voices (Voice v2)**~~ — Browser/Piper/Edge Neural engines,
  6 emotion presets, SSML smart breaks, per-engine pickers, live
  synthesis E2E.

## Shipped in v1.6.0

- ~~**Proactive engine + explainability**~~ — `/api/proactive`
  scan/list/dismiss; plan-trace SSE, memory citations, redaction counts.
- ~~**Dry-run + undo**~~ — tool dry-runs, automation `dry_run`, journaled
  `/api/undo`.
- ~~**Sessions + compaction**~~ — lifecycle (pin/star/branch/search) +
  rolling summaries.
- ~~**Agent/AI eval framework**~~ — 27 golden tasks, grounded scoring,
  `eval_runs` tracking.
- ~~**Cloud cost controls**~~ — `llm_usage` journal, live pricing snapshot,
  daily/monthly caps, costs UI.
- ~~**Image understanding**~~ — Ollama→cloud vision chain, file analysis,
  chat image attachments.

## Shipped in v1.5.0

- ~~**GitHub CI + release pipeline**~~ — backend/frontend/E2E/security/
  migrate-check jobs, dist artifacts, tag releases with checksums.
- ~~**Migration guard + prod check**~~ — destructive-DDL CI gate with
  approval token; 10-gate readiness script (versions, bundle, DB, backups).
- ~~**First-run onboarding**~~ — 7-step wizard (§83) + demo prompt (§84),
  real settings/rows, EN/SW, replayable; `PATCH /api/me`.
- ~~**Timezone + domain settings**~~ — IANA timezone drives quiet hours,
  briefings, calendar; domain prefs filter brief task sections.
- ~~**Release docs**~~ — `RELEASE.md` (process, compat matrices, rollback)
  + operations production checklist.

## Shipped in v1.4.0

- ~~**Scheduled LLM briefings**~~ — saved configs + run-now + history through
  the effective cloud chain; `brief` automation action; `brief me` in chat.
- ~~**Email reading + triage**~~ — sandbox sample inbox + live IMAP,
  rule/LLM triage, reader UI; `check my email` in chat.
- ~~**Calendar: local + CalDAV + Google**~~ — local CRUD + CalDAV pull/push +
  Google OAuth code flow; week agenda UI; `schedule …` in chat.
- ~~**Hermes tool growth (34)**~~ — `email_*`, `cal_*`, `briefing_now`,
  `tasks_prioritize` + 4 new intents.
- ~~**Multi-device sync**~~ — `aura-sync/1` bundles, natural-key merge,
  local-wins conflicts, `sync_log`; 4 merge bugs fixed; Settings
  export/import.
- ~~**PWA + mobile polish**~~ — install prompt, offline SW fallback, touch
  targets, safe-area nav, EN/SW strings.

## Shipped in v1.3.0

- ~~**OpenRouter provider + settings system**~~ — first-class OpenRouter cloud
  backend (free `:free` models, live catalog + curated fallback, connection
  tester, custom IDs), validated settings store (`GET/PATCH/DELETE
  /api/settings`, secrets write-only, hot-reload, env overlay); appearance
  prefs (themes/accents/density/font scale); chat/voice/notification/data
  settings (streaming, autoplay, quiet hours, retention pruning).
- ~~**Dead workspace views fixed**~~ — Career, Clients & Projects, Personal
  crashed on load (hooks after loading return); fixed + jsdom smoke tests.

## Shipped in v1.2.1 (hardening)

- ~~**Redaction + validation + limits patch**~~ — webhook-secret masking in
  automation lists, kind-switch validation, voice in strict rate bucket
  (400 on corrupt audio), streaming XLSX reads.

## Shipped in v1.2.0

- ~~**Webhook automation actions**~~ — signed HMAC POST + payload, exp
  backoff retry (5m→2h), validation at create/update, self-fire E2E;
  manual/event automations are one-shot now.
- ~~**Sleep tracking**~~ — `sleep_logs`, chat (`slept 11pm to 6am`),
  `POST /personal/sleep`, dashboard insight, Personal UI panel.
- ~~**Richer file parsing**~~ — `extract.py`: PDF (pypdf), DOCX, XLSX, PPTX,
  images (metadata), same `indexed_text` pipeline, per-file error field.
- ~~**Server-side voice**~~ — optional faster-whisper STT + Piper TTS
  (`requirements-voice.txt`), lazy model download, Voice UI panels,
  loop-verified live (speak → transcribe).
- ~~**Frontend tests**~~ — Vitest + Testing Library, 30 tests (helpers,
  api client, primitives, i18n, push/PWA assets).
- ~~**Router eval harness**~~ — `scripts/eval_router.py` + 211 utterances
  (100%); also fixed 5 real routing bugs it exposed.
- ~~**Ollama embeddings by default**~~ — `embedding_model` tags + lazy
  re-embed migration (5/search), legacy-DB ALTER migration, health row.
- ~~**PWA + push**~~ — manifest, icons, service worker (shell cache +
  push/click), VAPID Web Push, notify-automation fan-out, Settings toggle.
- ~~**Litestream sync config**~~ — `litestream.yml` + entrypoint
  (restore-on-boot, replicate wrap), compose docs, history field.
- ~~**Plugin tools**~~ — `app/plugins/` + `$DATA_DIR/plugins/` drop-ins
  (manifest + R0–R2), 2 examples, hot-reload, `docs/PLUGINS.md`.
- ~~**i18n**~~ — Swahili-first: full `sw` dictionary, auto-detect,
  Settings switch, key-parity test guard.

## Shipped in v1.1.0

- ~~**Real provider delivery**~~ — `providers.py`: Telegram Bot API, SMTP,
  Discord/Slack webhooks, generic WhatsApp provider POST; per-platform
  `sandbox|live` modes, validated credentials, redacted status, live tests.
- ~~**Rate limiting + hardening**~~ — per-IP sliding windows (chat/API/upload),
  payload caps (`413`s), security headers, CORS modes (open default, explicit
  lockdown), startup posture log line.
- ~~**Cloud model wiring**~~ — OpenAI-compatible fallback (fits OpenAI, Groq,
  DeepSeek, OpenRouter…); `AURA_PRIVACY` chain enforcement; sensitive-memory
  withholding + credential scrubbing; engine-labeled answers + activity log.

## P0 — before any multi-user use (deferred: single-user retained)

1. **Authentication + user scoping.** No login; everything is `user_id=1` and
   several UPDATE/DELETE paths don't scope by user. If multi-user is ever
   wanted: session/token auth, per-user rows, per-user data dirs.

## P1 — makes it materially better

5. **~~Webhook automation actions.~~** Schema advertises `webhook` but only
   `notify|backup|chat` execute. Implement signed POST actions + retry.
6. **~~Sleep tracking.~~** The dashboard honestly shows "no data" — add a tiny
   sleep log (chat: `slept 11pm to 6am`) and compute the insight for real.
7. **~~Richer file parsing.~~** PDF extraction is a regex fragment scan; DOCX/XLSX
   aren't parsed. Add `pypdf` + `python-docx`/`openpyxl` extractors behind the
   same `indexed_text` pipeline.
8. **~~Server-side voice option.~~** Browser STT/TTS is great on desktop but
   absent on some mobile browsers. Optional Whisper + Piper endpoints with
   the same `/voice/*` shapes would close the gap.
9. **~~Frontend tests.~~** Backend is well covered; add Vitest + Testing Library
   for the store (SSE parsing, toasts), palette filtering, and approval-card
   state transitions.

## P2 — growth & delight

10. **~~Eval harness for the router.~~** A YAML suite of ~200 utterances → expected
    intents run in CI, so rule edits can't regress routing silently (today:
    hand-picked regression asserts — good, but small).
11. **~~Ollama embeddings by default.~~** When `nomic-embed-text` is present, use
    it for memory vectors (migration: re-embed on read) instead of hashed
    vectors.
12. **~~PWA + push.~~** Manifest, service worker, and Web Push for automation
    notifications when the tab is closed.
13. **~~Multi-device sync.~~** SQLite + Litestream (or a sync protocol) for
    laptop + home-server setups.
14. **~~Plugin tools.~~** A `tools/` drop-in folder (manifest + risk level) so new
    Hermes tools don't require editing core.
15. **~~i18n.~~** Swahili-first UI strings (greetings already understand
    `habari`/`mambo`).

## Explicitly NOT recommended

- **Microservices / Postgres rewrite.** A single process + SQLite is the
  correct architecture for a personal OS; scale problems here are imaginary.
- **Vector-DB-first memory.** FTS5 + hashed vectors already beat pure-vector
  recall for personal data; Chroma is an optional upgrade, not a fix.
- **Removing the builtin engine.** The Ollama-independent path is what makes
  AURA robust, testable, and cheap. Neural should stay an upgrade, never a
  requirement.
