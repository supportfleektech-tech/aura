# AURA OS — Testing Guide

Five layers, all runnable locally. Unit + eval + frontend need no
Docker, Ollama, or network; E2E needs the running backend.

## 1. Backend unit tests (344 tests, ~40s)

```bash
cd backend && AURA_DATA_DIR="$(mktemp -d)" OLLAMA_BASE_URL=http://127.0.0.1:1 \
  ../venv/bin/python -m unittest discover -s tests
```

**A temporary `AURA_DATA_DIR` is required** — it relocates the DB, uploads and
backups. `AURA_DB_PATH` alone is not enough. `OLLAMA_BASE_URL=http://127.0.0.1:1`
forces the hashed-embedding path so the suite never needs Ollama running.

The suite must be **fully green**; a failing test means the behaviour is
unimplemented, not that the test is optional. Skips drop from 2 to 1 once
`requirements-voice.txt` (edge-tts) is installed. Coverage:

| Area | Tests |
|---|---|
| REST CRUD | tasks / clients / projects / milestones create-read-update-delete |
| Chat journeys | plan_day, task toggle by title + ID, project create, meeting + backup, client follow-ups |
| Routing regressions | Plural/ordering traps: `draft follow-ups`, `gateway status`, `new client X`, `how are my projects doing`, `practice guitar` ≠ interview… |
| Memory | Store → search round-trip, topic forget, retrieval union |
| Approvals | Pending → approve with edited drafts → sent + persisted `drafts_sent` |
| Backups | Run → marker row → restore → marker gone; rejects `../evil` + missing files |
| Dashboard | No fabricated insights (sleep/delta computed or empty) |
| Providers (mocked) | Telegram payload + failure surfacing, SMTP login + client-email resolution, credential redaction, live validation, unknown-recipient errors |
| Cloud (mocked) | Default-off even with key set, hybrid answers + sensitive-memory redaction, failure falls back to builtin |
| Limits | Bucket allow/deny unit test, HTTP `429` + headers integration, upload `413`, chat caps, CORS + security headers |
| Tools registry | All Hermes tools registered with risk levels; every R0/R1 tool survives empty args |
| Sleep | Chat times/duration/clarify, API + dashboard + overview, validation 400s |
| Webhooks | Create validation (https or loopback http), signed fire (HMAC verified), backoff + recover, manual one-shot |
| Automations | Action validation before persist, merged-config validation on PATCH, one-shot event kinds, file/feed fires counted |
| Undo / dry-run | create+update+delete round-trip; dry-run persists nothing and reports `blocked[]` |
| Missions | Template/keyword plans, R2 approval holds and resume, reject skips the step |
| File parsing | DOCX/XLSX/PPTX/PDF/image extraction, upload → memory indexing |
| Embeddings | Model tags, lazy migration to new embedder, legacy-DB ALTER migration |
| Push | Subscribe/unsubscribe/validation, mocked send + 410 prune |
| Voice (mocked) | Status keys, transcribe + speak shapes, 503/400 paths |
| Plugins | Example tools listed + executed, bad file fails safe, loader idempotent |
| Sync config | `litestream.yml` valid, entrypoint branches, history replica field |
| Router guard | Eval-file loader: ≥200 cases + spot-checks |

Separate modules cover streaming cancellation (`test_incremental_streaming.py`),
Kokoro personality, MCP connections, memory retrieval/correction, recovery
isolation, vloop wiring, and guard/limit→inference binding. Add a test in
`backend/tests/test_aura.py` (`AuraTest` class, TestClient `self.c`,
`sse_events()` helper parses chat streams). Run the file's tests after any
orchestrator/inference/hermes change.

> Do **not** run the backend suite and `npx vitest` concurrently — both saturate
> the box and heavy component renders hit their timeout.

## 2. Live end-to-end (101 checks, ~90s)

```bash
# backend must be running on :8000 (uses REAL data dir — self-cleaning)
python3 scripts/e2e_check.py [http://host:8000]
```

A failed check prints the source line (`@e2e_check.py:NN`) so a bare `✗` still
tells you which step broke. It is a **CI gate**, not an optional extra.

Hits the running server over HTTP and asserts behavior, not just status
codes: intent routing per journey, persisted state after toggles, approval →
edited send, file upload → indexed chars → download bytes, Hermes R2 gating
(403) vs R0 passthrough, gateway connect/test/disconnect/simulate, backup
sha256 length, resume download `Content-Disposition`, validation negatives
(400/403/404/413). All rows it creates are prefixed `E2E` and deleted afterwards;
it does leave benign journal/mood/expense/activity rows and one backup
archive behind (by design — it proves the write paths).

> **Check free disk first.** A full disk surfaces as `500` on file upload /
> docx indexing, which looks exactly like a code bug but is not one.

Exit code `0` = all green. Coverage map:

- meta (4): health (9 services), system, me+tools, dashboard honesty
- search + sessions (2)
- chat journeys (24 intents + toggle persistence)
- approvals (1), CRUD sweeps: tasks, clients+projects, career, personal,
  memory, automations, activity+notifications, gateway, files, voice+backup,
  Hermes, negatives
- v1.2 batch: sleep, webhook self-fire + https validation, plugin tools,
  embeddings health, push roundtrip, voice live (skips gracefully without
  models), PWA assets, docx upload+search, replica field
- fortress: origin guard, script library, folder watch (asks the server for
  its watch path, so it works under any `AURA_DATA_DIR`), machine liveness

`scripts/prod_check.py` (11 checks) additionally verifies version consistency
across config/package/footer/changelog, presence of a real `frontend/dist`,
deploy files, DB integrity, and push/VAPID readiness. It needs
`AURA_VAPID_PUBLIC_KEY`, `AURA_VAPID_PRIVATE_KEY` and `AURA_VAPID_SUBJECT`
(`scripts/gen_vapid.py` generates a throwaway pair).

## 3. Frontend checks

```bash
cd frontend
npx tsc --noEmit   # strict-ish typecheck (must be silent)
npm run build      # tsc + vite production bundle into dist/
```

Plus a real harness (see ROADMAP item 9, shipped): **36 Vitest tests**
(`npm test`) — `ago`/`md` helpers, api client (mocked fetch), Button/Panel/
PlanSteps rendering, i18n dictionary parity + language switching, push
helpers + PWA asset validity (manifest/icons/service worker). Correctness is
further guarded by the production build, an error boundary, and the live E2E.

## 4. Router eval (211 utterances, <1s)

```bash
python3 scripts/eval_router.py [--min 1.0]
```

Every `classify()` rule locked against 8 utterances per intent (+ domain
spots). Fails (exit 1) on any misroute — run after touching `INTENT_RULES`.
Cases live in `backend/tests/router_cases.json` and encode *intended*
behavior; a loader unit test guards the file. This harness has already caught
and fixed 5 real routing bugs (see CHANGELOG v1.2.0).

## Manual smoke checklist (before a release)

1. Fresh boot: `rm -rf data/aura.db*` → start → seed data appears.
2. `plan my day` streams plan → steps → answer; orb animates.
3. `draft follow-ups` → approval card → Edit → Approve → toast + notification.
4. Upload a `.txt` via composer → Memory Center shows `File: …`.
5. Backup Manager: run → file appears → Restore → reload works.
6. Automations: create notify automation → Run now → notification arrives.
7. Gateway: connect Telegram → test → simulate inbound → event visible.
8. Mobile width (~390px): bottom nav appears, views usable.
9. With Ollama stopped/started: status flips degraded ↔ online, chat works both ways.

## Suggested CI (GitHub Actions)

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: pip install -r backend/requirements.txt
      - run: cd backend && python -m unittest
      - run: python scripts/eval_router.py
      - run: cd frontend && npm ci && npm test && npm run build
      - run: cd backend && (python -m uvicorn app.main:app --port 8000 &) && sleep 6 && python ../scripts/e2e_check.py
```
