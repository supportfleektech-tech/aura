# v1.13.0 — Finalization & diligence (all tracks)

Closes the last code-completable acceptance item + the remaining diligence
gaps from the master plan (§31, §38, §39, §50, §76).

## WS-A — Benchmark harness + CI gate (§38, Appendix C "benchmarks pass")
- `scripts/benchmark.py` — offline, deterministic: chat-turn latency (builtin),
  tool execution, memory search, universal search, DB write, mission planning.
- `--ci` mode: compare against targets, exit non-zero on regression.
- Wire into `.github/workflows/ci.yml` backend job.

## WS-B — Idempotency (§39)
- New `send_dedupe` table (additive) + `app/idempotency.py` `claim()/prune()`.
- Webhooks: stable `_fire_id` (uuid) per fire survives retries, cleared on
  success → sent as `X-Aura-Idempotency-Key` header + body field so receivers
  can dedupe retries.
- `comms.send`: client-side dedupe (60s window) to prevent double-send.

## WS-C — Search filters + explainability (§31)
- `/api/search` gains `type`, `from`, `to` filters.
- Every result carries a `matched` reason ("title + description match …",
  "semantic memory match", …). Palette shows it.

## WS-D — Autonomous skill improvement (§50 P2)
- New `routine_mission` detector: a mission with ≥3 successful runs and no
  schedule → "make this a routine" opportunity.
- `act()` kind `schedule_mission`: applies the schedule, resolves the item.

## WS-E — Advanced analytics (§50 P2)
- `/api/analytics/overview` gains `forecast`: spending-next-7d, task velocity,
  sleep trend, mood trend — least-squares, honest `null` when data is thin.

## WS-F — Parallel subagents (§76)
- Consecutive R0 read-only steps in a chat plan execute concurrently (pool of
  4), results joined in plan order. Pref `chat_parallel_steps` (default on).

## Non-goals
- Auth/multi-user, mobile app, plugin marketplace (registry), federated
  workspaces — unchanged. No new runtime dependencies; schema change is
  additive (`send_dedupe`).
