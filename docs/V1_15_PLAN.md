# v1.15.0 — Fortress Hardening (plan + completion record)

Owner brief (repeat): *"what other features… add more integrations and
automations… run commands/scripts on my pc… connect everything… review the
whole project, fix errors and bugs, update and finalize end-to-end."* The
named capabilities shipped in v1.14.0; v1.15.0 completes the story — the
machine layer becomes safe to live with day-to-day and gains the workflow
features it was missing.

## Tracks (all shipped)

### 1. Origin guard — the hole v1.14 opened, v1.15 closes
With `CORS=*` and no login, any page in the user's browser could POST to
`/api/terminal/exec` (drive-by / DNS-rebinding). `app/guard.py`
(outermost middleware): state-changing `/api/*` requests with a foreign
`Origin` → 403 before any handler runs. Same-origin passes; origin-less
clients (provider webhooks, curl, cron) pass; GETs pass; extra front-ends
via `AURA_ALLOWED_ORIGINS`. Proven both ways in e2e.

### 2. Script library — `scripts.py`
`scripts` table (name UNIQUE, command, machine, description, counters).
`save()` runs the terminal danger gate + host validation; `run()` re-runs
the full classifier (a script can't become a footgun later); `{placeholder}`
args filled via `shlex.quote`; every exec lands in `terminal_runs`
(`source=ui|chat|automation`). Surfaces: `/api/scripts` CRUD + run, tools
`scripts.list|run|save`, automation `script` action kind (validated at
creation), chat "run my X script" via the new `__terminal_or_script__`
pseudo-step (falls back to raw command when no script matches), Terminal →
Scripts panel.

### 3. Folder watch — `watch.py`
Prefs: `watch_enabled` (default **off** — we don't silently scan your
disk), `watch_paths` (JSON; dirs must exist; under the data dir can be
auto-created), `watch_ingest` (index into memory), `watch_scan_interval_s`
(30–3600, default 120). Scheduler hook `maybe_scan()`; extension whitelist;
depth 2; dotfiles skipped; 25 MB cap. Change detection = mtime+size vs
`watched_files`. Per event: files row + extract + memory + notification +
`file`-kind automations (`contains` or fnmatch pattern on name/path).
Endpoints: state/paths/scan/reset; Files screen hosts the panel.

### 4. Machine liveness + small QoL
`terminal.check_machine()` TCP probe (1.5 s) — host[:port] parsed from the
ssh target — exposed at `GET /api/terminal/check`, "Check" button per
machine row. Recent Calls panel (Voice screen) with summaries + delete +
start-call CTA. Terminal ↑/↓ recall seeded from the audit history. Home
gains a "Call AURA" chip.

### 5. Proactive: disk guard
`_d_disk_low` — DATA_DIR volume <10 GB free or <8% → opportunity with exact
numbers; self-clears. Detector count now 11.

## Bugs fixed while reviewing
1. `feed` automations got a daily `next_run` after firing (double-execution
   trap). `_next_run` now treats `manual|event|feed|file` as one-shot.
2. e2e approval case flaked against the v1.13 comms dedupe when re-run
   inside 60 s — unique recipients + the assertion now accepts a
   dedupe as a clean pipeline outcome.
3. (carried from this session) eval harness UTC vs user-tz day seeding;
   `INSERT OR IGNORE` lastrowid counting; Atom namespace; docstring
   placement; health connector count.

## Gates (v1.15.0)
- backend `python3 -m unittest tests.test_aura` → **261/261 OK** (1 skip: optional server-voice deps)
- frontend `npx vitest run` → **85/85** (20 files) · `tsc --noEmit` clean · `vite build` ok
- E2E live → **101 PASS / 0 FAIL / 1 WARN** (warn = Whisper not installed here)
- prod check → **11 PASS / 0 FAIL / 1 WARN** (warn = VAPID unset — documented off-state)
- router **299/299** · agent **27/27** · benchmark **all medians within budget**
- migration self-test OK; `schema.sql` additive-only (`scripts`, `watched_files`)

## Out of scope (owner constraints unchanged)
auth/multi-user, native mobile, plugin marketplace UI, isolated reasoning
subagents.
