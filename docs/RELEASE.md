# AURA OS — Release Process

Master plan §62 (release strategy) + Phase 15 (production readiness).

## Versioning

SemVer (`MAJOR.MINOR.PATCH`). `APP_VERSION` in `backend/app/config.py` is the
source of truth; it is mirrored in `frontend/package.json` (+ lock),
the `App.tsx` footer, the E2E version assert, and `docs/CHANGELOG.md`.
`scripts/prod_check.py` fails the release if any of them disagree.

## Cutting a release

1. Land the work with all gates green: backend unit, `scripts/eval_router.py`,
   `scripts/eval_agent.py` (golden tasks + groundedness; scores tracked in
   `eval_runs`), `tsc --noEmit`, `vitest run`, `scripts/e2e_check.py`.
2. Write the `docs/CHANGELOG.md` entry (top) and the `docs/ROADMAP.md`
   "Shipped in vX.Y.Z" section with current suite counts.
3. Bump the version in all mirrors (config, package.json + lock, App footer,
   frontend test fixtures, E2E assert).
4. Rebuild the prod bundle (`npm run build` in `frontend/`) and restart the
   backend so it serves the fresh `dist/`.
5. Run `scripts/prod_check.py` against the live backend — exit 0 required
   (warnings allowed, must be understood).
6. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The `release`
   workflow re-runs unit tests, rebuilds `dist/`, and publishes the bundle
   tarball (+ SHA-256) to the GitHub Release.

CI (`ci.yml`) runs on every push/PR: backend, frontend, E2E (live server +
`e2e_check.py` + `prod_check.py`), security audit, and the migration guard.

## Migration notes

- Schema changes live in `backend/app/schema.sql`. The `migrate-check` CI
  job diffs it against the base branch and **fails on dropped tables or
  columns** unless the commit message contains `[allow-destructive-schema]`.
- Existing databases are migrated at startup in the `db.init` path
  (precedent: `memories.embedding_model` ALTER). Never ship a destructive
  schema change without the matching startup migration + a note below.
- Guard parser fixtures: `python3 scripts/migration_check.py --self-test`.

| Release | Schema / migration impact |
|---|---|
| v1.15.0 | Additive (`scripts`, `watched_files` tables via `schema.sql`, created by `init_db`). No backfill. New env knob `AURA_ALLOWED_ORIGINS` (optional). The origin guard starts rejecting cross-site mutations on upgrade — same-origin app + webhooks unaffected. |
| v1.14.0 | Additive (`ollama_models`, `terminal_runs`, `feeds`, `feed_items`, `calls` tables via `schema.sql`, created by `init_db` on startup). No backfill, no ALTERs. New settings keys ship with defaults — terminal is enabled-on-first-run by owner design (single-user fortress), dangerous commands refused unless toggled. |
| v1.13.0 | Additive (`send_dedupe` table via `schema.sql`, created by `init_db` on startup). No backfill needed. |
| v1.12.0 | None — code only (web search tool + intent, proactive mission action, chat mission SSE). No DDL. |
| v1.11.0 | Additive (`mission_runs` table via `init_db`; `missions.schedule_json` + `missions.next_run_at` via startup ALTER). No backfill needed. |
| v1.10.0 | None — code + prefs reads only (`ollama_vision_model`), no DDL. |
| v1.9.0 | Additive (`missions` table via `init_db`; `homeassistant` integration row seeded; voice prefs). No backfill needed. |
| v1.8.0 | Additive (`opportunities.resolved`, `resolved_at`, `snoozed_until` via startup ALTER; analytics/messaging reuse existing tables + `config_json`). No backfill needed. |
| v1.7.0 | None — settings keys only (`voice_engine`, `voice_*`), no DDL. |
| v1.6.0 | Additive (`llm_usage`, `vision_results` tables + `cost_*`, `vision_*` settings keys). Created by `init_db` on startup; no backfill needed. |
| v1.5.0 | None — settings keys only (`onboarded`, `timezone`, `domain_*`), no DDL. |
| v1.4.0 | Additive (briefings/mail/calendar/sync tables + settings keys). |
| v1.3.0 | Additive (`settings` table). |

## Model compatibility

| Provider | Default / tested | Notes |
|---|---|---|
| OpenRouter | `:free` roster via live catalog (`/api/cloud/models`) | Roster rotates; Test-button validates before save. |
| OpenAI | `gpt-4o-mini` | Any chat-completions model ID works. |
| Ollama (local) | `llama3.1` chat @ `localhost:11434` | Optional; builtin engine covers absence. |
| Custom | any OpenAI-compatible base URL | Key optional (some endpoints are keyless). |

## Hermes compatibility

| AURA | Embedded Hermes runtime | Plugin API |
|---|---|---|
| v1.5.x | v2.0.0 (34 tools) | R0–R2 manifests, see `docs/PLUGINS.md` |

Never upgrade Hermes, the model runtime, or the database engine in the same
release as a large feature unless necessary.

## Rollback

1. Stop the backend.
2. Check out the previous tag (`git checkout vX.Y.(Z-1)`).
3. If the release had **no** schema change: nothing else data-wise.
   If it had an **additive** change: old code ignores the new tables/columns.
   If it had a **destructive** change: restore `data/aura.db` from the
   pre-release backup (`data/backups/` or the Litestream replica) — this is
   mandatory, not optional.
4. Rebuild the frontend (`npm ci && npm run build`) when the UI changed.
5. Restart, then run `scripts/e2e_check.py` and `scripts/prod_check.py`.
