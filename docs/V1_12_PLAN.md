# v1.12.0 — Autonomy: proactive missions, web search, mission visibility

Closes the two remaining non-deferred P2 backlog items (§51 advanced
proactive intelligence, §76 deeper agent delegation) plus chat-side mission
visibility (§34.2 streaming / §54 explainability).

## WS-A — Proactive → auto-mission (advanced proactive intelligence)
- `repeated_manual` detector now offers **Automate as mission** (weekly).
- Stale backups offer **Automate daily backup** (daily) instead of only a
  one-shot run.
- `act()` gains a `mission` kind: creates the mission (auto planner),
  falls back to a concrete `tasks.create` step when no template matches,
  applies the schedule, auto-starts (R0/R1 steps only), resolves the
  opportunity, and journals an activity event.

## WS-B — Web search (deeper agent delegation, R0 read-only)
- New `browse.search()`: keyless DuckDuckGo HTML search, SSRF-guarded,
  time-boxed (10s), capped (≤6), honest off-state (never fabricates).
- New Hermes tool `web.search` (R0).
- New `web_search` chat intent → search + memory grounding; builtin
  composer renders titled links + snippets (or the honest error).

## WS-C — Mission visibility in chat
- New `mission_status` chat intent ("how are my missions") → streams each
  mission's step progress as SSE `mission` events and summarizes in chat.
- Frontend renders live mission progress in the chat thread.

## Non-goals (unchanged by design)
- Auth/multi-user (deferred), desktop shell, mobile app, plugin
  marketplace, federated workspaces.
- No new runtime dependencies; no schema/DDL changes.
