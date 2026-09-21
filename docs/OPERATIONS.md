# AURA OS — Operations

## Production checklist

Automated first: `python3 scripts/prod_check.py [BASE_URL]` — versions
consistent, prod bundle present, deploy files in place, data dir writable,
DB integral, services online, backups fresh, secrets sane. Exit 0 required;
understand every warning. Release flow (versioning, migration notes, compat
matrices, rollback): `docs/RELEASE.md`.

Manual items `prod_check` cannot verify for you:

- **VAPID keys** generated (`scripts/gen_vapid.py`) and exported, or push
  stays disabled by design.
- **Backups scheduled** (nightly `POST /api/backup/run` or cron) with at
  least one verified restore; Litestream replica configured for off-box.
- **CORS locked down** if the API leaves localhost; reverse proxy (TLS)
  in front; firewall allows only 80/443 (and SSH).
- **Cloud keys** present when `privacy != local-first`, else the chain
  silently falls back to local/builtin.
- **Onboarding completed** (`onboarded=true`) so identity/timezone/domains
  are set; replay anytime from Settings → Data.

## Security posture (read before exposing)

AURA v1 is a **single-user, local-first** app: no login, all rows `user_id=1`.

- **Safe default**: bind to localhost / run behind a firewall or Tailscale.
  Do NOT put `:8000` on the open internet as-is.
- If you must expose it, terminate TLS in a reverse proxy (Caddy/nginx) with
  basic-auth or SSO in front, and restrict `AURA_CORS` to your exact origin
  (the default also allows `*` so sandboxed previews work).
- **Blast-radius controls that already exist**: R2+ tools refuse direct HTTP
  execution (`403`) and only run inside an approved resolution; backup
  restore is basename-guarded + integrity-checked; uploads are filename
  sanitized; chat attachments are stored, never executed.
- **Audit trail**: `activity`, `runs`, `toolcalls`, `audit` tables record
  what ran, what was sent, and what was approved — queryable via
  `/api/activity` and the Activity view.
- Secrets: none required. If you later wire cloud models, keep keys in env,
  never in `data/`.

## Backups

- **Manual**: Clients → Backup Manager → Run Backup Now, or
  `POST /api/backup/run`. Artifact:
  `data/backups/aura-backup-<UTC-ts>.tar.gz` (SQLite snapshot + uploads).
- **Scheduled**: create a `backup`-action automation (nightly recommended).
- **Verify**: each run records `size_bytes` + `sha256:…` note; the E2E suite
  asserts hash length. Spot-check restores on a scratch copy
  (`AURA_DATA_DIR=/tmp/aura-probe`).
- **Restore**: Backup Manager → Restore (or `POST /api/backup/restore`).
  Integrity-checked first; current data is safety-copied to
  `.pre-restore-*.db`; the UI reloads afterwards. Restore is single-user:
  don't chat mid-restore.
- **Retention**: keep the newest 3–7 archives off-machine; prune old ones —
  nothing auto-deletes.

## Litestream replication

- **Enable**: `AURA_LITESTREAM_REPLICA` (+ `AWS_*` creds, or
  `LITESTREAM_S3_ENDPOINT` for R2/MinIO) in Docker. Entrypoint restores when
  `/data/aura.db` is missing, then replicates (10s cadence).
- **Monitor**: `GET /api/backup/history → litestream.enabled`; container log
  line `litestream: replica …` on boot. Validation runs hourly.
- **Recover**: point a fresh container at the same replica URL — boot
  restores automatically. Point-in-time: `litestream restore -timestamp …`
  (see Litestream docs). Keep periodic `.tar.gz` snapshots too — they cover
  `uploads/`, which replication doesn't.
- **Local test**: `AURA_LITESTREAM_REPLICA=file:///tmp/rep/aura.db` exercises
  the whole path without S3.

## Push & plugins ops

- **Push**: keys via `scripts/gen_vapid.py`; never commit the private key.
  `POST /api/push/test` verifies end-to-end. Dead endpoints (410) prune
  themselves; `push_subscriptions` is covered by normal backups.
- **Plugins**: only install `*.py` files you reviewed into
  `$DATA_DIR/plugins/` (they run in-process). `/api/tools → plugins.failed`
  shows load errors. Shipped `app/plugins/` are overwritten on upgrade —
  keep yours in the data dir.

## Gateway live mode

Each platform runs in `sandbox` (default: audited, zero network calls) or
`live` (real delivery). Configure in Multi-Platform → Configure, or
`POST /gateway/{platform}/connect {mode, config}`:

| Platform | Live credentials | Notes |
|---|---|---|
| Telegram | `bot_token` (from @BotFather), `default_chat_id` | Sends via Bot API `sendMessage`; test = `getMe` (no message) |
| Email | `smtp_host`, `smtp_port` (587/465), `smtp_user`, `smtp_pass`, `from_addr` | STARTTLS (587) or SSL (465); recipients resolve `Name` → client email, or use raw addresses |
| Discord / Slack | `webhook_url` | Incoming-webhook POST; test delivers one real test message |
| WhatsApp | `webhook_url` (+ optional `headers`, `default_to`) | Generic provider POST `{to, text}` — bring Twilio/Business-Cloud/etc. |

Rules: live mode refuses to save until required fields validate (`400`
listing what's missing); Test in live mode validates without spamming
(except webhook platforms, where the test IS one message); every live send
lands on the event bus + activity log with `mode: live`; failures surface
as approval `errors` (never silent) and persist as the platform's
`last_error`. Forget credentials anytime (Disconnect → Forget creds).

## Cloud fallback ops

- Modes: `local-first` (default, cloud never called), `hybrid`
  (Ollama → cloud → builtin), `cloud` (cloud first). Unknown values fail
  closed to local-first.
- Redaction: `sensitive`/`private` memories are withheld from cloud prompts
  (`result.redacted_memories` counts them) and credential-like patterns are
  scrubbed from grounding. Tool-result grounding (your tasks/projects) IS
  sent in hybrid/cloud — that's the documented tradeoff of cloud answers.
- Monitoring: System status `cloud: ready|disabled`; Activity logs each
  cloud answer; `runs.model` starts with `cloud/`.
- Cost control: max ~900 completion tokens/turn, temperature 0.6; no
  background cloud calls exist (embeddings stay local).

## Observability

- `GET /api/health` — 8 service probes (Hermes, LFM, memory, vector, SQLite,
  gateway, voice, scheduler) + `runs_24h`, `avg_run_ms`, `tools_ok/err`,
  `disk_free_gb`. `ok:false` means a core service is down (LFM degraded
  doesn't count — fallback is by design).
- Activity view — every run, tool call, approval, backup, gateway event.
- Logs: uvicorn stdout (requests + scheduler errors). In Docker:
  `docker compose logs -f aura`.
- Alerting (DIY): cron a `curl /api/health` and page when `.ok == false` or
  `tools_err` climbs.

## Maintenance

| Task | How |
|---|---|
| Move data dir | Stop → move dir → set `AURA_DATA_DIR` → start |
| Reset to seed demo | Stop → `rm -rf data/aura.db*` → start |
| SQLite vacuum | `sqlite3 data/aura.db "VACUUM;"` (stop backend first) |
| Disk check | Health `disk_free_gb` + `du -sh data/*` (uploads/backups grow) |
| Upgrade | `git pull` → reinstall deps → rebuild frontend → restart (schema is idempotent) |
| Ollama models | `docker compose exec ollama ollama pull llama3.1` (or `ollama pull` natively) |

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `ok:false` + SQLite offline | DB file locked/missing → check `AURA_DB_PATH`, disk, permissions |
| Runs suddenly slow | Ollama reachable but overloaded → `avg_run_ms` confirms; fallback still works |
| Scheduler quiet | Automations `paused` or `next_run` in future → check Automation Center |
| Approval never arrives | No overdue tasks → drafts empty → plan skips by design; chat says so |
| Gateway "queued in outbox" | Platform not connected → connect it first |
| Restore fails integrity | Truncated download/copy → use an older archive |
| 400 on chat | Empty message — client should guard (UI does) |
| 403 on hermes tool | R2+ tool needs the approval flow, not direct call |

## Performance notes

- Typical chat turn: <100 ms builtin (retrieval + tools + compose), +model
  time with Ollama. E2E suite (44 checks incl. 24 chats) runs in ~1s.
- FTS5 + hashed vectors are comfortable to ~100k memories on modest hardware;
  add ChromaDB beyond that or for persistent collections.
- SQLite WAL keeps readers unblocked; writers serialize on one lock — fine
  for one user + the 30s scheduler.
