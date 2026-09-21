# v1.14.0 — The Machine Room (plan + completion record)

Owner brief: *"What else can we add — more integrations and automations; it
should access and run commands/scripts on my pc — add a terminal, connect it
to my machines; all ollama models on my pc synced into Aura; connect
everything; add the ChatGPT-style call feature for hands-free voice; review
the whole project, fix bugs, finalize end-to-end."*

Constraints kept: single-user, no login (Tailscale/VPN fortress-local), no
native mobile app, no multi-user/federation.

## Tracks (all shipped)

### 1. Ollama model sync — `backend/app/ollama_sync.py`
- `GET /api/tags` → normalized catalog (name, family, size, params, quant,
  modified) + capability inference (`chat/vision/embed/tools` via curated
  family tables; `deepseek-r1`/`qwen3` get a "reasoning is slow" note).
- SQLite cache `ollama_models`; outage → last-known list with `stale`.
- Scheduler auto-sync (prefs `ollama_auto_sync`, `ollama_sync_interval_min`).
- `set_default(role, name)` validated against the catalog (live fallback when
  cache empty; refuses "cannot verify" rather than silently pointing at a
  ghost model).
- API: `GET /api/ollama/status`, `GET /api/ollama/models`,
  `POST /api/ollama/sync` (502 + reason when unreachable),
  `POST /api/ollama/default`.
- Chat intents: `ollama_models`, `ollama_switch` (catalog-guarded).
- Settings → Model Room screen; vision/embed/chat model pickers per model.
- `ollama_embed_model` pref now actually feeds `OllamaClient.embed` +
  `embed_fn` naming (was hardcoded env).

### 2. Terminal — `backend/app/terminal.py`
- Exec model: `/bin/sh -lc` (or `bash`) as the AURA user, `cwd` from
  `terminal_cwd`, timeout clamp 1–600s, output capped at
  `terminal_max_out_kb` (default 64KB, truncation marked in-band).
- Risk tiers: `safe` (read-only allowlist **with subcommand + arg checks**:
  git/ollama/docker/systemctl/pip/brew/npm + `find -delete` / `curl -XPOST`
  denied; redirect or `$()` anywhere ⇒ `guarded`), `guarded` (runs, flagged),
  `dangerous` (footgun regex list — refused unless `terminal_allow_dangerous`,
  and refused *at automation-creation time* regardless).
- Audit: `terminal_runs` (source ui/chat/automation/test, machine, command,
  cwd, exit, ms, out_bytes, risk, status ok|error|denied|timeout|disabled).
- Machines: `terminal_machines` JSON; `ssh -o BatchMode=yes
  -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new`; hosts must match
  `[A-Za-z0-9@._:\[\]-]+`; `local` reserved.
- Dry-run safety: `db.DRY_RUN` never executes (`{dry_run, would}`).
- Chat: `terminal_run` intent + `parse_inline` (backticks, `terminal:`,
  `run|execute … command:` extraction); `system.run` tool is R3 → excluded
  from unattended mission plans, available in chat/UI.
- UI: Terminal screen — machine picker, prompt bar, output pane, cwd,
  machine registry, execution log; disabled state is a clear CTA.

### 3. Integrations & automations
- **Feeds** (`feeds.py`): stdlib RSS2.0/Atom parser, `feeds`/`feed_items`
  tables, guid-dedupe, per-feed error, scheduler auto-refresh
  (`feeds_refresh_min`), notify on new items, morning-brief lines, tools
  `feeds.latest` / `feeds.follow`, chat intents `feeds_latest` /
  `feed_follow`, Feeds screen with suggested feeds.
- **Weather** (`weather.py`): Open-Meteo (no key), lat/lon from settings,
  15-min cache, honest off-state, `weather.now` tool + `weather` intent,
  umbrella line in the builtin + model briefs.
- **Automation action kinds**: `terminal` (validated: dangerous rejected),
  `home` (HA domain/service/entity validated with regexes); **trigger kind
  `feed`** (per-feed + `contains` keyword) fires matched actives on
  discovery.
- Health: Model Room / Terminal / Feeds / Weather services; off-states are
  `degraded`, and `/api/health.ok` ignores optional surfaces.

### 4. Voice Call — ChatGPT-style hands-free
- Frontend `CallOverlay` (views4): continuous Web-Speech recognition with
  interim captions; final utterance → `chatStream` (session-continuous,
  memory-grounded) → TTS (browser speechSynthesis or configured engine);
  barge-in cancels speech when the user talks; mute; auto-restart of the
  recognizer between turns.
- No Web Speech (FF/Safari): 5s hold-to-talk via MediaRecorder →
  `/api/voice/transcribe` (Whisper), honestly labeled fallback.
- End-of-call: transcript → `POST /api/voice/calls` → `calls.py` stores +
  counts turns/seconds + asks the model router for a 1–2 sentence summary
  (deterministic digest fallback offline; `call_summary` pref) + stores a
  memory so call topics remain searchable.
- Call history: `GET /api/voice/calls`, `GET|DELETE /api/voice/calls/{id}`;
  Voice screen CTA + palette action.

## Review findings fixed along the way
1. eval_agent seeded events on UTC day vs app's tz day → near-midnight runs
   failed; harness now seeds on the user's day.
2. feeds counted new items via `lastrowid` (stale on OR-IGNORE) → pre-check.
3. terminal classifier allowed `python3 anything`/`git push` as "safe" →
   subcommand/arg validation + redirect downgrade.
4. Atom parser used the dead `purl.org/Atom` ns → derived from root.
5. `fire_webhook` docstring after a statement → moved.
6. `health` detail said "5 connectors" → 6.

## Gates (v1.14.0)
- backend `python3 -m unittest tests.test_aura` → **248/248 OK** (1 skip: server voice deps)
- frontend `npx vitest run` → **80/80** (19 files) · `npx tsc --noEmit` clean · `npm run build` ok
- E2E `scripts/e2e_check.py` → **97 PASS / 0 FAIL / 1 WARN** (warn = VAPID off-state)
- router eval → **299/299**, agent eval → **27/27**, benchmark `--ci` → all medians in budget
- `prod_check` → **11 PASS / 0 FAIL / 1 WARN**

## Explicitly not done (owner constraints)
- login / multi-user / per-user scoping — single-user fortress by decision
- native mobile app; plugin marketplace registry; isolated reasoning subagents
