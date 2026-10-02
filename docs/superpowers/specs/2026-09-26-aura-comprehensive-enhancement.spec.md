# Feature: AURA OS Comprehensive Enhancement

## Overview
Major enhancement to AURA OS adding: persistent cross-session memory, Kanban workflow automation, agentic slash commands, improved chat UX (thinking style, auto-scroll, emoji picker), and performance optimizations.

---

## 1. Persistent Cross-Session Memory

### Overview
Enhance the existing memory system to persist across conversations/sessions with semantic retrieval, automatic consolidation, and user-controlled retention.

### Functional Requirements

**FR-MEM-001: Session Persistence**
While a user has an active session, when messages are exchanged, the system shall automatically store relevant facts, preferences, and context as structured memories with domain tags.

**FR-MEM-002: Cross-Session Retrieval**
While a user starts a new session, when they ask a question, the system shall retrieve relevant memories from all previous sessions using hybrid search (FTS5 + vector + rerank).

**FR-MEM-003: Memory Consolidation**
While memories accumulate, when a consolidation job runs (daily), the system shall merge duplicate memories, update importance scores based on access frequency, and archive low-importance memories.

**FR-MEM-004: User Memory Controls**
While viewing the Memory panel, when the user interacts with memories, the system shall allow: edit, delete, pin, export, and sensitivity labeling.

**FR-MEM-005: Automatic Fact Extraction**
While processing assistant responses, when tool results contain factual information, the system shall extract and store key facts as semantic memories.

### Non-Functional Requirements
- Memory retrieval latency: < 100ms p95
- Support 100k+ memories per user
- Vector index rebuild: < 30s for 10k memories

### Acceptance Criteria
- **AC-MEM-001**: Given a user has 50+ memories across 10 sessions, when they ask "what did I say about project X?", then relevant memories from all sessions are retrieved and cited.
- **AC-MEM-002**: Given duplicate memories exist, when consolidation runs, then duplicates are merged with combined importance.
- **AC-MEM-003**: Given a memory is marked "private", when cloud model is used, then that memory is excluded from context.

---

## 2. Kanban Workflow Automation Board

### Overview
Visual Kanban board for creating, managing, and monitoring automation missions with drag-and-drop, real-time progress, and approval workflows.

### Functional Requirements

**FR-KAN-001: Kanban Board View**
While in Automations view, when the user selects "Kanban" tab, the system shall display missions as cards in columns: Backlog → Planned → Running → Awaiting Review → Done.

**FR-KAN-002: Drag-and-Drop**
While viewing the Kanban board, when the user drags a mission card, the system shall allow moving between columns and reordering within columns, persisting the new status.

**FR-KAN-003: Mission Card Details**
When clicking a mission card, the system shall show a modal with: steps, approvals, run history, schedule, and manual controls (start/pause/cancel).

**FR-KAN-004: Real-Time Progress**
While a mission is running, the system shall stream step status updates to the card (running/awaiting/done/failed) with visual indicators.

**FR-KAN-005: Quick Create**
While in Kanban view, when the user clicks "Add Card" in a column, the system shall open a quick-create form with goal, schedule, and risk level.

### Non-Functional Requirements
- Drag operations: 60fps
- Status updates: < 500ms latency via SSE
- Support 500+ concurrent missions

### Acceptance Criteria
- **AC-KAN-001**: Given 10 missions in various states, when viewed in Kanban, then all appear in correct columns with correct status badges.
- **AC-KAN-002**: Given a running mission, when a step completes, then the card updates within 1 second without refresh.
- **AC-KAN-003**: Given a card is dragged from Planned to Running, then mission status updates and run starts automatically.

### Delivered (v1.16.0) — and where it differs from the spec above

Shipped as four columns, not five: **Backlog → Running → Needs you → Finished**
(`views2/kanban.tsx`, `routes/kanban.py`). `Planned` was dropped because a mission
has no "planned" status — `draft` already lives in Backlog, and adding a column
that mirrors an existing status would be a second source of truth for it.
`Awaiting Review` shipped as **Needs you** (missions parked on an approval).

Beyond column naming, three requirements were deliberately not built, and the
reason is the same in each case: a *view* must not become a second write path
into mission status.

- **AC-KAN-002 (live card updates)** — the board refetches on demand; there is no
  SSE subscription per card. Chat already streams per-step progress for
  `mission_status` (`orchestrator`), and the automations panel shows it.
- **Reordering within a column (FR-KAN-002, second clause)** — would need a
  persisted per-user column order. It is the first entry in Open Questions below.
- **FR-KAN-005 (quick create with a risk level)** — the board is a view over
  existing missions; creating one goes through the mission planner, which
  derives risk per step from the Hermes tool registry rather than being told it.

Dragging a card to Finished **cancels** it. The only legitimate route to
`done` is a mission actually completing, and no path sets `status='done'`
directly.

---

## 3. Agentic Slash Commands

### Overview
Command palette accessible via `/` in chat input, providing agentic actions like tool invocation, navigation, memory ops, and system control.

### Functional Requirements

**FR-CMD-001: Command Trigger**
While focused in Composer, when the user types `/`, the system shall show a command palette with filtered suggestions.

**FR-CMD-002: Built-in Commands**
The system shall support these command categories:
- Navigation: `/home`, `/career`, `/clients`, `/personal`, `/memory`, `/voice`, `/automations`, `/settings`
- Memory: `/remember <fact>`, `/forget <topic>`, `/search <query>`, `/memories`
- Tasks: `/task <title>`, `/tasks`, `/done <task>`
- Automation: `/mission <goal>`, `/missions`, `/run <automation>`
- System: `/status`, `/backup`, `/models`, `/health`, `/logs`
- AI: `/think <prompt>`, `/ask <model> <prompt>`, `/switch <model>`

**FR-CMD-003: Command Arguments**
When a command requires arguments, the system shall show inline argument hints and validate before execution.

**FR-CMD-004: Custom Commands**
Users can define custom slash commands in Settings that map to prompts or tool sequences.

**FR-CMD-005: Cheat Sheet**
Settings page shall display a searchable, categorized cheat sheet of all available commands with descriptions and examples.

### Non-Functional Requirements
- Palette opens: < 50ms
- Fuzzy search: < 20ms for 100 commands
- Keyboard navigation: full arrow key support

### Acceptance Criteria
- **AC-CMD-001**: Given user types `/tas`, then "Create Task" command appears as top suggestion.
- **AC-CMD-002**: Given user selects `/task "Review PR"`, then a task is created and confirmation shown.
- **AC-CMD-003**: Given user opens Settings → Commands, then all commands are listed with categories, descriptions, and examples.

---

## 4. Chat UX Improvements

### 4.1 Thinking vs Final Response Styling

**FR-CHAT-001: Thinking Style**
While the model is in "thinking" phase (planning, tool calls, retrieval), the system shall display thinking tokens in a distinct style: monospace, muted color, collapsible, with "🤔 Thinking…" indicator.

**FR-CHAT-002: Final Response Style**
When the final response begins streaming, the system shall render in normal prose style with markdown, syntax highlighting, and normal typography.

**FR-CHAT-003: Phase Transition**
When transitioning from thinking to final, the system shall show a smooth visual transition (fade/slide) and auto-scroll to the new content.

### 4.2 Auto-Scroll

**FR-CHAT-004: Smart Auto-Scroll**
While new tokens arrive, if the user is scrolled to bottom (within 100px), the system shall auto-scroll to keep the latest message visible. If user has scrolled up, show a "↓ New messages" toast/button.

### 4.3 Emoji Picker

**FR-CHAT-005: Emoji Selector**
While in Composer, when the user clicks the emoji button (or types `:`), the system shall show a searchable emoji picker with categories, recent, and skin tone support.

### 4.4 Chat Container Fix

**FR-CHAT-006: Fixed Chat Area**
The chat thread shall have a fixed height container with internal scrolling only, no page-level scroll interference. Margin between chat scrollbar and page scrollbar.

### Non-Functional Requirements
- First token render: < 100ms
- Smooth 60fps scrolling
- Emoji picker opens: < 50ms

### Acceptance Criteria
- **AC-CHAT-001**: Given a long conversation, when new messages arrive, chat stays fixed and scrolls internally.
- **AC-CHAT-002**: Given thinking phase, when final response starts, thinking block collapses and final renders with different style.
- **AC-CHAT-003**: Given user scrolled up 5 messages, when new message arrives, "↓ New messages" indicator appears.
- **AC-CHAT-004**: Given user clicks emoji button, when they select an emoji, it inserts at cursor position.

---

## 5. Cowork/Workers for Task Automation

### Overview
Background worker system for running automation missions, scheduled tasks, and async operations with queue management, retry logic, and observability.

### Functional Requirements

**FR-WRK-001: Worker Pool**
The system shall maintain a configurable worker pool (default 3) for executing missions and async tasks.

**FR-WRK-002: Task Queue**
When a mission starts or automation triggers, the system shall enqueue steps with priority, dependencies, and retry policy.

**FR-WRK-003: Retry & Dead Letter**
Failed steps shall retry with exponential backoff (max 3). After max retries, move to dead letter queue with alert.

**FR-WRK-004: Worker Observability**
Dashboard shall show: active workers, queue depth, throughput, error rate, and per-mission timing.

**FR-WRK-005: Scheduled Job Runner**
Cron-like scheduler for recurring automations (hourly/daily/weekly) with timezone support and catch-up logic.

### Non-Functional Requirements
- Worker startup: < 2s
- Queue latency: < 100ms p99
- Zero message loss (persistent queue)

### Acceptance Criteria
- **AC-WRK-001**: Given 5 missions triggered simultaneously, with 3 workers, then all complete with correct ordering.
- **AC-WRK-002**: Given a step fails, then it retries 3 times with backoff before dead-lettering.
- **AC-WRK-003**: Given daily automation at 9am, when 9am passes, then it runs within 60 seconds.

---

## 6. Performance Optimization

### Overview
System-wide performance improvements targeting latency, bundle size, memory usage, and database query optimization.

### Functional Requirements

**FR-PERF-001: Frontend Bundle Optimization**
Code-split all views, lazy-load heavy components (Three.js, charts), target main chunk < 150KB gzipped.

**FR-PERF-002: Database Query Optimization**
Add indexes for common query patterns, use connection pooling, enable WAL mode, optimize memory retrieval queries.

**FR-PERF-003: Caching Layer**
Implement Redis-compatible cache for: model catalog, health probes, session data, and frequent API responses.

**FR-PERF-004: SSE Optimization**
Batch token events, compress SSE stream, implement backpressure handling for slow clients.

**FR-PERF-005: Memory Management**
Implement LRU cache for embeddings, periodic GC for old sessions, streaming JSON for large responses.

### Non-Functional Requirements
- Page load: < 1.5s (LCP)
- API p95: < 200ms
- Memory usage: < 512MB backend, < 100MB frontend
- Bundle size: < 150KB main chunk

### Acceptance Criteria
- **AC-PERF-001**: Given cold start, when loading home page, then LCP < 1.5s on 3G.
- **AC-PERF-002**: Given 10k memories, when searching, then results return < 200ms.
- **AC-PERF-003**: Given 100 concurrent chat streams, then all receive tokens with < 500ms latency.

---

## 7. End-to-End Testing

### Overview
Comprehensive test coverage including unit, integration, and E2E tests for all new features.

### Implementation TODO

> All items closed in v1.16.0. See `docs/CHANGELOG.md`.

### Backend

- [x] Optimize database indexes — 12 `CREATE INDEX` in `schema.sql`
- [x] Add memory consolidation job — `app/consolidate.py`, daily-gated, exposed over HTTP
- [x] Add fact extraction pipeline — `app/facts.py`; chat text was already covered by `MemoryEngine.observe`
- [x] Implement Kanban mission status endpoints — `app/routes/kanban.py`; columns derived from existing statuses
- [x] Add slash command router — `app/routes/slash.py`, all 26 `FR-CMD-002` commands
- [x] Implement worker pool with queue — `app/workers.py`; persistent queue, retry, dead-letter
- [x] Add scheduled job runner — `workers.scheduler_pass()` is the one 30s loop body; the mission tick is now wired into it
- [x] Add caching layer — `app/cache.py`; in-process TTL+LRU, Redis-equivalent semantics
- [x] Optimize SSE streaming — `orchestrator.TokenBatcher`, event shape unchanged

### Frontend

- [x] Fix ChatThread container (flex, min-height: 0) — `frontend/src/ui.tsx:527`
- [x] Add thinking/final message styling — `ui.tsx:555-572`, `backend/app/orchestrator.py:1263`
- [x] Implement auto-scroll with "new messages" indicator — `ui.tsx:487-513` and `ui.tsx:585`
- [x] Add emoji picker component — `ui.tsx:650-728`
- [x] Implement slash command palette in Composer — `CommandPalette.tsx` (`SlashPalette`)
- [x] Create Kanban board component with drag-drop — `views2/kanban.tsx`
- [x] Add mission card modal with real-time updates — superseded: `views2/automations.tsx:30` shows per-step state; the v1.16 perf panel (`views2/perf.tsx`) shows live queue state
- [x] Create Commands cheat sheet in Settings — `views2/commands.tsx`, mounted in settings
- [x] Add performance monitoring — `views2/perf.tsx`

### Testing
- [x] Unit tests for memory consolidation — `backend/tests/test_consolidation.py`
- [x] Unit tests for command parser — `backend/tests/test_slash.py`
- [x] Integration tests for Kanban API — `backend/tests/test_kanban.py`
- [x] E2E tests for slash commands — `e2e_check.py`, two checks: the HTTP round-trip and the chat-stream SSE short-circuit, which is a different code path from `POST /api/slash/execute`
- [ ] E2E tests for chat UX (auto-scroll, thinking style) — NOT automated. The chat
  stream is covered by the `chat:<intent>` journeys plus the `plan`/`result`/`done`
  frame asserts in `e2e_check.py`, but auto-scroll and the thinking/final styling are
  visual behaviours verified only by the Playwright pass, not by any assertion. Left
  unticked deliberately: a ticked box here would claim a regression guard that does not
  exist. Shipped code at `ui.tsx:487-572`. by the `chat:<intent>` journeys plus the `plan`/`result`/`done` frame asserts in `e2e_check.py`. Auto-scroll and the thinking/final styling are visual behaviours: verified by the Playwright pass recorded in `AGENTS.md`, not by an automated assertion. Shipped in `ui.tsx:487-572`.
- [x] Load tests for worker pool — `backend/tests/test_workers.py` covers concurrent claim, priority order, backoff and recovery
- [x] Performance benchmarks — `scripts/benchmark.py --ci` gained a `token_batch` gate

---

## Error Handling

| Error Condition | HTTP Code | User Message |
|-----------------|-----------|--------------|
| Memory consolidation failed | 500 | "Memory consolidation failed, will retry" |
| Kanban drag invalid state | 400 | "Cannot move mission to that state" |
| Slash command not found | 404 | "Unknown command. Type / for suggestions" |
| Worker pool exhausted | 503 | "System busy, please try again" |
| Emoji picker load failed | 500 | "Emoji picker unavailable" |
| Auto-scroll blocked | - | Silent fallback |

---

## Out of Scope
- Multi-user collaboration on Kanban boards
- Voice command recognition for slash commands
- AI-generated custom command suggestions
- Cross-device memory sync (handled by existing sync feature)

---

## Open Questions
- [ ] Should slash commands support piping (e.g., `/task "X" | /assign @user`)?
- [x] Worker pool: in-process threads vs separate processes? — **threads.** The
  DB layer is one pooled SQLite connection behind an RLock, so N threads writing
  concurrently serialise on that lock anyway; what genuinely parallelises is tool
  execution, which releases the lock while it waits on the network. Converting to
  asyncio later would risk deadlocking on the RLock for no throughput gain.
- [x] Memory consolidation: LLM-based vs rule-based? — **rule-based.** A nightly
  job must not depend on a model being reachable, and its writes must be
  reproducible and auditable. Dedupe is token Jaccard against the same threshold
  and same strict comparison the store uses; re-scoring reads two columns that
  already exist. No access counter was added — scoring on bare presence would
  re-apply forever and pin importance at its cap.
- [ ] Kanban: persist column order per user? — still open; reordering within a
  column was deliberately not built (see §2).

### Missions never advanced in production (found 2026-09-30)

`missions.tick_missions()` and `missions.tick_schedules()` had no call sites
outside `backend/tests/`. `hermes.start_scheduler_loop` only called
`hermes.tick_automations()`, so a mission started from the UI or chat sat at
`status='running'` with every step `pending`, indefinitely. The suite passed
because the tests called `tick_missions()` by hand. Closed by Task 4 of
`docs/superpowers/plans/2026-09-30-aura-completion.md`.