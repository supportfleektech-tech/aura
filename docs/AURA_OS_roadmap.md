# AURA OS — Full-Scale End-to-End Build & Refactor Roadmap

> **Product:** AURA OS — Multimodal AI Sidekick  
> **Primary Runtime:** Hermes Agent  
> **Memory:** SQLite + ChromaDB (with FTS5/hybrid retrieval)  
> **Experience:** 3D Aura Orb + command center + multimodal chat  
> **Domains:** Career & Work / Clients & Projects / Personal Life  
> **Connectivity:** Web/Desktop + Telegram + Discord + Slack + WhatsApp + Email + extensible gateway  
> **Inference:** Local-first, LFM-capable, hybrid local/cloud routing  
> **Status:** Architecture and implementation master plan

---

## 0. Executive Definition

AURA OS is not simply a chatbot with three screens. It should be built as a **persistent personal operating system for AI-assisted life and work**, with Hermes Agent acting as the execution/runtime substrate and AURA acting as the product, state, memory, orchestration, visualization, domain, and integration layer.

The system should:

- maintain continuity across sessions and communication platforms;
- understand the user as a whole while enforcing domain boundaries;
- combine conversational interaction with deterministic application workflows;
- use structured application state for facts and ChromaDB/semantic retrieval for context;
- support text, voice, images, files, and future video/audio workflows;
- execute tasks through Hermes tools, skills, delegation, scheduling, and sandboxes;
- operate locally wherever practical, with cloud fallback where useful or required;
- provide transparent, auditable agent behavior instead of a black-box automation engine;
- distinguish **suggestion**, **draft**, **simulation**, and **executed action**;
- allow high-risk actions to require explicit confirmation;
- scale from a single-user laptop deployment to a self-hosted or hosted multi-device architecture without rewriting the domain layer.

### Core product principle

> **AURA remembers, understands, plans, acts, explains, and learns — while remaining controllable by the user.**

---

# 1. Product Vision

## 1.1 North Star

AURA should feel like a combination of:

1. personal command center;
2. executive assistant;
3. project operations system;
4. searchable second brain;
5. multimodal AI workspace;
6. automation engine;
7. private local AI companion.

The user should be able to say:

> “AURA, review my current client workload, find anything overdue, draft follow-ups, identify the three most important tasks for tomorrow, and remind me at 7:30 AM.”

AURA should be able to:

- retrieve relevant memories;
- inspect structured client/project state;
- query calendars/tasks/messages where authorized;
- reason over the result;
- generate drafts;
- ask for approval only when needed;
- create the reminder;
- record the outcome;
- update memory where appropriate;
- explain what it did.

## 1.2 Product Layers

AURA should be decomposed into seven conceptual layers:

```text
┌─────────────────────────────────────────────────────────┐
│                    AURA EXPERIENCE                      │
│  Orb • Chat • Panels • Search • Timeline • Settings    │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│                    AURA PRODUCT CORE                    │
│ Identity • Domains • Workspaces • Tasks • Projects     │
│ Clients • Goals • Routines • Preferences • Policies     │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│                AURA ORCHESTRATION LAYER                │
│ Intent • Context • Memory • Planning • Approval        │
│ Routing • Workflow • Event Bus • State Transitions     │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│                    HERMES RUNTIME                      │
│ Agent Loop • Tools • Skills • Delegation • Cron        │
│ Session Runtime • Sandboxes • Gateway • MCP            │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│             AI / MULTIMODAL MODEL LAYER                │
│ Local LFM • Cloud Models • Embeddings • STT • TTS      │
│ Vision • Reranking • Classification • Extraction       │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│                DATA & INTEGRATION LAYER                │
│ SQLite • ChromaDB • Files • Cache • Connectors         │
│ Telegram • Discord • Slack • WhatsApp • Email • APIs  │
└─────────────────────────────────────────────────────────┘
```

---

# 2. Guiding Architecture Decisions

## 2.1 Hermes remains the agent runtime

Do not fork Hermes into a second competing agent framework unless a hard technical limitation is demonstrated.

AURA should wrap Hermes with adapters and policy layers.

Current Hermes already exposes multi-platform gateway operation, persistent memory, skills, scheduling, delegation, toolsets, MCP integration, and sandboxed execution. citeturn105020search0turn105020search2turn105020search4

### AURA owns

- product domain logic;
- domain/panel state;
- user experience;
- AURA-specific permissions;
- structured entities;
- context assembly;
- memory policy;
- semantic indexing strategy;
- model-routing policy;
- approval/confirmation UX;
- cross-platform identity mapping;
- unified activity/audit timeline;
- analytics;
- local LFM service abstraction;
- application APIs;
- dashboard visualizations;
- backup/restore orchestration;
- integration configuration;
- health and diagnostics.

### Hermes owns

Where the installed/version-pinned Hermes implementation supports them:

- agent loop;
- tool invocation;
- skills;
- toolsets;
- delegated subagents;
- cron/scheduled jobs;
- gateway adapters;
- terminal/sandbox backends;
- session/runtime mechanics;
- MCP support;
- agent execution policy.

The exact v2.0.0 API must be locked during repository reconnaissance. Do not code against undocumented assumptions. The official repository and documentation should be treated as the source of truth for the pinned version. citeturn299431search3turn299431search5

## 2.2 Structured state + semantic memory + session history

Never make ChromaDB the source of truth for operational records.

Use:

- **SQLite** for transactional application truth;
- **FTS5** for lexical/session search where appropriate;
- **ChromaDB** for vector/semantic retrieval;
- **filesystem/object storage** for original attachments;
- **event/audit tables** for traceability.

SQLite FTS5 is designed for efficient full-text search, making it suitable for exact-term and historical session retrieval alongside semantic search. citeturn299431search8

## 2.3 Local-first, hybrid-capable

Local processing should be preferred for:

- private memory retrieval;
- routine classification;
- simple extraction;
- local embeddings;
- lightweight conversation turns;
- sensitive data processing where practical;
- offline operation;
- low-latency UI interactions.

Cloud inference should remain available for:

- heavier reasoning;
- difficult multimodal tasks;
- long-context synthesis;
- image/video workloads beyond local hardware;
- provider-specific capabilities.

LFM models are particularly suitable to AURA's local-first positioning because Liquid AI describes LFM families as designed for efficient deployment on CPU/GPU/NPU devices, including text, vision-language, audio, and encoder/embedding models. citeturn299431search0turn299431search7

---

# 3. Architecture Target

## 3.1 Recommended deployment model

### Development

```text
Browser/Desktop
      │
      ▼
AURA Web App
      │
      ▼
AURA API / BFF
      │
      ├──────────────► SQLite
      │
      ├──────────────► ChromaDB
      │
      ├──────────────► File Storage
      │
      ├──────────────► Local LFM Service
      │
      └──────────────► Hermes Runtime
                             │
                             ├── Tools
                             ├── Skills
                             ├── Delegation
                             ├── Scheduling
                             └── Gateway
```

### Production / self-hosted

```text
                         ┌───────────────┐
                         │ Web / Desktop │
                         └───────┬───────┘
                                 │
                         ┌───────▼───────┐
                         │ API Gateway   │
                         │ Auth + RBAC   │
                         └───────┬───────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
┌───────▼────────┐      ┌────────▼────────┐      ┌──────▼────────┐
│ AURA App Core  │      │ Hermes Runtime  │      │ Media Service │
└───────┬────────┘      └────────┬────────┘      └──────┬────────┘
        │                        │                        │
   ┌────▼────┐             ┌─────▼─────┐            ┌───▼────┐
   │ SQLite  │             │ Tool/Skill│            │ Files  │
   └────┬────┘             └─────┬─────┘            └────────┘
        │                        │
   ┌────▼────┐             ┌─────▼──────┐
   │ Chroma  │             │ Integrations│
   └─────────┘             └────────────┘

                 ┌─────────────────────────┐
                 │ Local / Cloud AI Router │
                 └─────────────────────────┘
```

## 3.2 Process boundaries

Prefer separate processes/services for components that have different failure or security characteristics:

1. `aura-api` — application API and orchestration;
2. `aura-web` — user interface;
3. `hermes-runtime` — agent runtime;
4. `aura-inference` — local LFM inference gateway;
5. `aura-worker` — asynchronous indexing, extraction, notifications, maintenance;
6. `aura-gateway` — optional isolated external messaging gateway;
7. SQLite database;
8. ChromaDB;
9. file/object storage.

For a small installation these may run in one host/container group. The boundaries should still exist in code.

---

# 4. Technology Blueprint

## 4.1 Backend

Recommended baseline:

- Python 3.11+ for AURA services if aligning with Hermes's current Python environment;
- FastAPI for HTTP APIs;
- Pydantic for schemas;
- SQLAlchemy or SQLModel for DB access;
- Alembic for migrations;
- SQLite for default single-user deployment;
- PostgreSQL-compatible repository abstraction later if true multi-user scale is required;
- ChromaDB for semantic retrieval;
- Redis optional for distributed queue/cache deployments;
- WebSockets or Server-Sent Events for streaming UI events;
- background worker system for ingestion, indexing, reminders, media processing.

Hermes' current contributor setup documents Python 3.11 and its own managed environment. Preserve compatibility with the pinned Hermes version rather than upgrading the whole runtime arbitrarily. citeturn299431search3

## 4.2 Frontend

Recommended:

- React + TypeScript;
- Vite for fast SPA development;
- Tailwind CSS or CSS Modules;
- Radix/shadcn-style accessible primitives;
- Framer Motion for interaction animation;
- Three.js / React Three Fiber for the Aura Orb;
- Zustand for lightweight client state;
- TanStack Query for server state;
- Zod for frontend schema validation;
- Recharts/Visx for data visualization;
- Web Audio APIs for microphone/audio streaming;
- MediaRecorder for voice notes.

## 4.3 Desktop

Primary option:

- Tauri for a lightweight local desktop shell.

Alternative:

- Electron if deep Node ecosystem integration becomes more important than footprint.

The desktop client should not contain business logic. It should host the same AURA UI and connect to the local AURA runtime.

## 4.4 Local model layer

Create a provider-neutral interface:

```python
class InferenceProvider(Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse: ...
    async def stream(self, request: ChatRequest) -> AsyncIterator[TokenEvent]: ...
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...
    async def transcribe(self, request: AudioRequest) -> Transcript: ...
    async def synthesize(self, request: SpeechRequest) -> AudioArtifact: ...
    async def vision(self, request: VisionRequest) -> VisionResponse: ...
```

Implement adapters for:

- LFM local inference;
- cloud LLM provider;
- embedding provider;
- STT provider;
- TTS provider;
- optional multimodal provider.

Do not hard-code a model name throughout the product.

---

# 5. Monorepo Structure

Recommended repository structure:

```text
/aura-os
│
├── apps/
│   ├── web/
│   ├── desktop/
│   └── api/
│
├── services/
│   ├── aura-orchestrator/
│   ├── aura-inference/
│   ├── aura-worker/
│   ├── aura-gateway/
│   └── aura-media/
│
├── packages/
│   ├── domain/
│   ├── db/
│   ├── memory/
│   ├── hermes_adapter/
│   ├── ai_router/
│   ├── integrations/
│   ├── security/
│   ├── observability/
│   ├── events/
│   ├── policies/
│   └── schemas/
│
├── skills/
│   ├── career/
│   ├── clients/
│   ├── personal/
│   ├── system/
│   └── shared/
│
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   ├── evals/
│   └── security/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── workflows/
│   ├── operations/
│   └── decisions/
│
├── infra/
│   ├── docker/
│   ├── compose/
│   ├── systemd/
│   └── deployment/
│
├── scripts/
├── .env.example
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── package.json
└── README.md
```

### Architecture rule

Domain code must not import UI code, and the Hermes adapter must not become the domain layer.

---

# 6. Domain Model

## 6.1 Core entities

### Identity

- `User`
- `UserProfile`
- `Identity`
- `PlatformIdentity`
- `Session`
- `Device`
- `Preference`
- `Permission`
- `Policy`

### Work

- `CareerProfile`
- `Resume`
- `JobOpportunity`
- `Application`
- `Interview`
- `Skill`
- `Goal`
- `Habit`
- `TimeBlock`
- `WorkItem`

### Clients

- `Client`
- `Contact`
- `Organization`
- `Project`
- `ProjectMilestone`
- `ProjectTask`
- `Deliverable`
- `Invoice`
- `ClientCommunication`
- `Asset`
- `BackupJob`
- `ServiceCredentialReference`

### Personal

- `Routine`
- `JournalEntry`
- `PersonalGoal`
- `FinanceEntry`
- `RelationshipNote`
- `WellbeingEntry`
- `Reflection`

> Sensitive personal data requires a separate privacy/security design, consent model, encryption policy, retention policy, and access-control boundary. Do not treat it as generic chatbot context.

### AI state

- `Conversation`
- `Message`
- `Attachment`
- `Memory`
- `MemoryChunk`
- `MemoryLink`
- `SkillRecord`
- `AgentTask`
- `ToolCall`
- `ToolResult`
- `Plan`
- `ApprovalRequest`
- `WorkflowRun`
- `Event`
- `Notification`
- `ScheduledJob`
- `AuditEntry`

---

# 7. Database Architecture

## 7.1 SQLite tables

Recommended logical groups:

```text
identity_*
domain_career_*
domain_client_*
domain_personal_*
ai_*        
integration_*
event_*
audit_*
settings_*
system_*
```

## 7.2 Critical identifiers

Every entity gets:

- UUID/ULID primary key;
- created timestamp;
- updated timestamp;
- owner/user scope;
- source metadata when imported;
- soft-delete state where appropriate;
- optimistic version number for concurrent updates.

## 7.3 Event history

Use append-oriented events where workflow traceability matters.

Example:

```text
PROJECT_CREATED
TASK_CREATED
TASK_COMPLETED
CLIENT_CONTACT_UPDATED
MEMORY_CREATED
MEMORY_REINFORCED
MEMORY_ARCHIVED
MESSAGE_RECEIVED
MESSAGE_SENT
TOOL_EXECUTED
APPROVAL_REQUESTED
APPROVAL_GRANTED
APPROVAL_REJECTED
AUTOMATION_TRIGGERED
MODEL_ROUTED
```

## 7.4 Full-text indexes

Add SQLite FTS5 virtual tables for:

- conversations;
- messages;
- memory text;
- notes;
- client communications;
- documents metadata/full extracted text.

FTS5 should supplement semantic retrieval rather than replace it. citeturn299431search8

---

# 8. Memory System — Full Design

The memory layer is the core differentiator of AURA.

## 8.1 Memory types

### Episodic memory

What happened.

Examples:

- a client meeting happened;
- the user rejected a strategy;
- a job application was submitted;
- a project milestone was completed.

### Semantic memory

What is believed to be true.

Examples:

- preferred working hours;
- recurring client requirements;
- technology preferences.

### Procedural memory

How something should be done.

Examples:

- preferred proposal workflow;
- backup procedure;
- interview preparation routine.

### Preference memory

What the user prefers.

Examples:

- concise notifications;
- preferred meeting windows;
- preferred writing tone.

### Context memory

Temporary context with expiration.

Examples:

- current campaign;
- active job search;
- current sprint goal.

## 8.2 Memory record

```json
{
  "id": "mem_...",
  "type": "preference",
  "domain": "career",
  "content": "Prefers concise CV summaries with quantified outcomes.",
  "source": "conversation",
  "source_ref": "msg_...",
  "confidence": 0.94,
  "importance": 0.81,
  "sensitivity": "normal",
  "valid_from": "2026-09-01T00:00:00Z",
  "valid_until": null,
  "last_confirmed": "2026-09-08T...",
  "access_count": 14,
  "created_at": "..."
}
```

## 8.3 Retrieval pipeline

Use hybrid retrieval:

```text
User request
   │
   ▼
Intent + entities
   │
   ├──── lexical query ────► SQLite FTS5
   │
   ├──── semantic query ───► ChromaDB
   │
   └──── structured lookup ─► SQLite/domain service
                │
                ▼
        candidate evidence
                │
                ▼
      dedupe + metadata filters
                │
                ▼
          reranking
                │
                ▼
       temporal weighting
                │
                ▼
       confidence weighting
                │
                ▼
        context budgeter
                │
                ▼
       model context packet
```

## 8.4 Relevance scoring

Recommended initial formula:

```text
score =
  0.35 * semantic_similarity
+ 0.20 * lexical_score
+ 0.15 * recency_score
+ 0.10 * importance
+ 0.10 * confidence
+ 0.05 * domain_match
+ 0.05 * relationship_match
```

Then calibrate with offline retrieval evaluations.

## 8.5 Memory write pipeline

Never save every message as long-term memory.

```text
Conversation completed
       │
       ▼
Event extraction
       │
       ▼
Candidate memories
       │
       ├── sensitive check
       ├── duplicate check
       ├── contradiction check
       ├── confidence estimate
       └── importance estimate
       │
       ▼
Persistence policy
       │
       ├── discard
       ├── session-only
       ├── long-term memory
       └── skill/procedure candidate
```

## 8.6 Contradiction management

AURA must not silently overwrite contradictory memories.

Example:

```text
OLD: User prefers meetings after 2 PM.
NEW: User says mornings are now preferred.
```

Store:

- old memory as superseded;
- new memory as active;
- effective timestamp;
- reason/source;
- confidence.

## 8.7 Memory controls

UI requirements:

- inspect what AURA remembers;
- edit memory;
- delete memory;
- forget a topic;
- export memory;
- disable memory for a conversation;
- mark a memory private/sensitive;
- see source conversation when possible;
- show why a memory was used.

---

# 9. Context Engine

The Context Engine assembles the smallest useful context set instead of dumping the entire memory database into the prompt.

## 9.1 Context layers

```text
Layer 0: system policy
Layer 1: active user/domain profile
Layer 2: current conversation
Layer 3: active task/plan state
Layer 4: structured domain records
Layer 5: retrieved memory
Layer 6: relevant documents/files
Layer 7: tool results
Layer 8: execution history
```

## 9.2 Context budgeter

The engine should score each context item for:

- relevance;
- token cost;
- freshness;
- confidence;
- sensitivity;
- redundancy.

Then fit the best evidence inside the configured model budget.

## 9.3 Context modes

### Focus mode

Only the selected panel/domain.

### Global mode

Cross-panel retrieval is allowed.

### Private mode

No persistent memory write unless explicitly enabled.

### Task mode

Context centered on a single project/workflow.

---

# 10. AURA Agent Orchestration

## 10.1 Agent pipeline

```text
INPUT
  │
  ▼
Normalize
  │
  ├── text
  ├── voice
  ├── image
  ├── document
  └── external platform event
  │
  ▼
Intent Classification
  │
  ▼
Domain Routing
  │
  ▼
Risk Classification
  │
  ▼
Context Assembly
  │
  ▼
Plan / Act Decision
  │
  ├── answer directly
  ├── retrieve memory
  ├── use tool
  ├── create plan
  └── request approval
  │
  ▼
Hermes Execution
  │
  ▼
Validate Results
  │
  ▼
Response Composer
  │
  ▼
UI / Gateway Delivery
  │
  ▼
Memory + Audit + Analytics
```

## 10.2 Intent classes

Initial classifier:

- conversation;
- retrieval;
- knowledge question;
- planning;
- task creation;
- task mutation;
- project operation;
- client operation;
- career operation;
- personal operation;
- automation;
- communication;
- file operation;
- finance operation;
- system/admin;
- high-risk action.

## 10.3 Risk levels

```text
R0  informational
R1  reversible local mutation
R2  external communication / meaningful change
R3  financial / destructive / privileged action
R4  prohibited or unsupported
```

Examples:

- “Create a task” → R1
- “Draft an email” → R1
- “Send the email” → R2
- “Delete all client backups” → R3
- “Transfer funds” → R3

R2/R3 actions should support explicit approval policies.

---

# 11. Plan Engine

AURA should be able to expose its action plan at a useful level without exposing hidden reasoning.

Use structured plan summaries:

```json
{
  "goal": "Prepare client follow-up",
  "steps": [
    {"id":"1","action":"retrieve project status","status":"complete"},
    {"id":"2","action":"identify overdue items","status":"complete"},
    {"id":"3","action":"draft follow-up","status":"complete"},
    {"id":"4","action":"ask approval before sending","status":"pending"}
  ]
}
```

Do not expose chain-of-thought. Expose:

- intended actions;
- tool names/categories;
- results;
- blockers;
- required approvals;
- final outcome.

---

# 12. Hermes Adapter

Create a strict adapter interface.

```python
class HermesAdapter:
    async def create_session(...): ...
    async def send_message(...): ...
    async def stream_run(...): ...
    async def execute_tool(...): ...
    async def invoke_skill(...): ...
    async def delegate(...): ...
    async def schedule(...): ...
    async def cancel_run(...): ...
    async def health(...): ...
```

## 12.1 Adapter responsibilities

- translate AURA context into Hermes-compatible session/input;
- map AURA policies into tool availability;
- map Hermes events into AURA events;
- attach trace IDs;
- capture tool calls/results;
- normalize errors;
- prevent direct UI coupling;
- isolate version-specific Hermes code.

## 12.2 Version pinning

The requested architecture mentions Hermes Agent v2.0.0, but upstream Hermes evolves rapidly and the current upstream repository contains capabilities beyond older releases. Therefore:

1. explicitly pin the exact Hermes commit/tag/version;
2. generate a compatibility manifest;
3. run a startup capability check;
4. fail gracefully when optional capabilities are absent;
5. avoid depending on undocumented internals;
6. keep the adapter isolated so Hermes can be upgraded independently.

The public repository documents the broader runtime and extension model; use the exact pinned source for implementation details. citeturn299431search3turn105020search10

---

# 13. Skills Architecture

Use skills as procedural knowledge rather than duplicating domain code.

Current Hermes skills are designed as on-demand knowledge documents with progressive disclosure and an open-standard-compatible approach. citeturn105020search9

## 13.1 AURA skill categories

```text
skills/
├── career/
│   ├── resume-review
│   ├── resume-tailoring
│   ├── interview-prep
│   ├── job-tracking
│   └── time-blocking
│
├── clients/
│   ├── client-intake
│   ├── project-health-check
│   ├── client-followup
│   ├── delivery-checklist
│   └── backup-audit
│
├── personal/
│   ├── weekly-review
│   ├── routine-planning
│   ├── reflection
│   └── personal-organization
│
└── system/
    ├── memory-maintenance
    ├── data-backup
    ├── system-health
    └── privacy-audit
```

## 13.2 Skill lifecycle

```text
Discover
  ↓
Install
  ↓
Validate
  ↓
Use
  ↓
Measure
  ↓
Improve
  ↓
Version
  ↓
Rollback
```

Agent-created skills must not automatically become trusted system skills.

Use:

- draft;
- test;
- user-approved;
- trusted;
- deprecated.

---

# 14. Three-Panel Product Architecture

## 14.1 Shared shell

The AURA shell contains:

- Aura Orb;
- global command bar;
- current mode/domain;
- universal search;
- notifications;
- quick capture;
- voice button;
- activity timeline;
- profile/settings.

## 14.2 Career & Work Panel

### Dashboard

- today's priorities;
- workload;
- calendar/time blocks;
- applications pipeline;
- career goals;
- skill development;
- resume health;
- AI recommendations.

### Resume Workspace

- resume versions;
- job-description matching;
- ATS-oriented checks;
- quantified achievement suggestions;
- tailored cover letter;
- export-ready document generation.

### Interview workspace

- company research;
- role-specific question bank;
- mock interview mode;
- voice interview mode;
- answer scoring;
- feedback history;
- improvement areas.

### Time Blocking

- tasks;
- calendar integration;
- energy-aware suggestions;
- protected focus periods;
- auto-rescheduling.

## 14.3 Clients & Projects Panel

### Client directory

- organization profile;
- contacts;
- communication timeline;
- contracts/notes references;
- health score;
- outstanding tasks.

### Project tracker

- status;
- milestones;
- tasks;
- blockers;
- deadlines;
- deliverables;
- activity timeline;
- project memory.

### Backup management

- backup targets;
- schedules;
- last-success;
- failure history;
- retention;
- integrity checks;
- restore workflows;
- encrypted backup policy.

### Client AI actions

- weekly project summary;
- risk detection;
- overdue follow-up detection;
- status report drafting;
- meeting preparation;
- action-item extraction.

## 14.4 Personal Life Panel

This panel must be designed with stronger privacy controls.

Modules:

- routines;
- journaling/reflection;
- wellbeing tracking;
- personal goals;
- finances;
- relationships/contacts;
- personal reminders;
- life dashboard.

Avoid clinical claims or automated diagnosis. AURA can organize user-provided information and surface patterns for review, but sensitive health-related insights should be framed as non-diagnostic assistance.

---

# 15. Global Command Center

The main interaction pattern should be:

```text
                AURA ORB
                   ●
          ┌────────┼────────┐
          │        │        │
       Career   Clients  Personal
          │        │        │
          └────────┼────────┘
                   │
             Global Command
                   │
       “What should I do next?”
```

Global actions:

- ask;
- search memory;
- capture;
- create task;
- create project;
- start voice session;
- upload file/image;
- open workspace;
- run workflow;
- schedule automation;
- inspect recent activity.

---

# 16. 3D Aura Orb

The orb is a functional status visualization, not decorative wallpaper.

## 16.1 Orb states

```text
IDLE
LISTENING
THINKING
RETRIEVING
WORKING
WAITING_APPROVAL
SUCCESS
WARNING
ERROR
OFFLINE
```

## 16.2 Orb visual semantics

Use animation parameters tied to system state:

| State | Motion | Glow | Audio cue |
|---|---|---|---|
| Idle | slow breathing | low | none |
| Listening | responsive pulse | medium | subtle |
| Thinking | internal swirl | medium-high | subtle |
| Working | orbital movement | high | optional |
| Approval | rhythmic pulse | high | notification |
| Success | expansion then settle | bright | soft |
| Error | brief distortion | warning | short tone |

Do not overload the orb with text. Detailed state belongs in the status panel.

## 16.3 WebGL constraints

- reduce particle count on low-power devices;
- pause render loop when not visible;
- respect reduced-motion accessibility settings;
- provide 2D fallback;
- monitor GPU/frame time;
- cap visual effects under thermal/battery pressure.

---

# 17. UI / UX Design System

## 17.1 Design language

Target feel:

- premium;
- futuristic;
- calm;
- intelligent;
- minimal but information-rich;
- tactile;
- high contrast;
- dark-mode first with a light theme supported;
- no “generic SaaS dashboard” appearance.

## 17.2 Layout

Desktop:

```text
┌─────────────────────────────────────────────────────────────┐
│ AURA      Search / Command                  Mic  Bell Avatar│
├───────────────┬─────────────────────────────┬───────────────┤
│               │                             │               │
│ DOMAIN NAV    │         AURA ORB            │ CONTEXT       │
│               │                             │ PANEL         │
│ Career        │        Conversation        │               │
│ Clients       │                             │ Tasks         │
│ Personal      │                             │ Memory        │
│ Memory        │                             │ Activity      │
│ Automations   │                             │               │
│ Integrations  │                             │               │
│ Settings      │                             │               │
│               │                             │               │
├───────────────┴─────────────────────────────┴───────────────┤
│ Composer: text / voice / attach / quick action             │
└─────────────────────────────────────────────────────────────┘
```

Mobile:

- Orb/chat primary;
- bottom navigation for domains;
- context sheets instead of persistent sidebars;
- large voice control;
- touch-first cards.

## 17.3 Components

Build a reusable design system:

- `AuraOrb`
- `CommandBar`
- `ChatThread`
- `MessageBubble`
- `ToolActivity`
- `MemoryChip`
- `EntityCard`
- `TaskCard`
- `ProjectCard`
- `ClientCard`
- `Timeline`
- `StatusPill`
- `ApprovalDialog`
- `PlanStepper`
- `SearchResult`
- `VoiceWaveform`
- `AttachmentTray`
- `NotificationCenter`
- `DataTable`
- `EmptyState`
- `Skeleton`
- `ErrorBoundary`

---

# 18. Voice Architecture

## 18.1 Voice input

```text
Microphone
   ↓
Browser/OS capture
   ↓
VAD / chunking
   ↓
Noise suppression
   ↓
STT
   ↓
Transcript normalization
   ↓
AURA intent pipeline
```

## 18.2 Voice output

```text
Assistant response
   ↓
Sentence/semantic chunking
   ↓
TTS
   ↓
Audio streaming
   ↓
Playback
```

## 18.3 Voice UX

- push-to-talk;
- hands-free option;
- interrupt speech;
- live transcription;
- transcript correction;
- language selection;
- playback controls;
- voice activity visualization.

> **Status (v1.14.0):** every item above ships. Push-to-talk + always-on
> loop (v1.9) and, since v1.14, the **Call screen** — a ChatGPT-style
> full-duplex conversation: continuous listening with live captions,
> interruption (barge-in cancels AURA mid-sentence), spoken replies through
> the configured TTS engine, mute, and end-of-call transcript + summary
> persisted to memory (`/api/voice/calls`). Vision/voice both feed the same
> canonical message objects.

## 18.4 Voice continuity

Voice input should become the same canonical message object as typed input.

```text
Message
├── modality: text | voice | image | file | multimodal
├── transcript
├── original_asset
├── confidence
├── source_platform
└── metadata
```

---

# 19. Multimodal Input

## 19.1 File ingestion

Support:

- PDF;
- DOCX;
- XLSX/CSV;
- TXT/Markdown;
- images;
- audio;
- video later.

Pipeline:

```text
Upload
  ↓
MIME verification
  ↓
Malware/security scan
  ↓
Metadata extraction
  ↓
Text/media extraction
  ↓
Chunking
  ↓
Embedding
  ↓
Chroma index
  ↓
Structured entity extraction
  ↓
Link to user/domain/project
```

## 19.2 Image understanding

Use a vision-capable provider when enabled.

Outputs may include:

- description;
- OCR/extracted text;
- structured fields;
- visual facts;
- user-requested analysis.

Store original image separately from derived text.

---

# 20. Multi-Platform Gateway

Hermes currently supports a broad multi-platform gateway architecture and documents platforms including Telegram, Discord, Slack, WhatsApp, Email, and others. citeturn105020search0turn105020search2

AURA should unify platform-specific traffic into a canonical event model.

## 20.1 Canonical inbound event

```json
{
  "event_id": "evt_...",
  "platform": "telegram",
  "platform_account": "acct_...",
  "platform_user": "user_...",
  "conversation": "conv_...",
  "message": {
    "text": "Review my client work",
    "attachments": []
  },
  "received_at": "..."
}
```

## 20.2 Outbound event

```json
{
  "conversation": "conv_...",
  "content": {
    "text": "I found 4 overdue items..."
  },
  "actions": [],
  "threading": {},
  "delivery_policy": {}
}
```

## 20.3 Cross-platform continuity

The same user should be able to:

- start a task in the web app;
- continue in Telegram;
- receive a reminder in Slack;
- approve a draft from mobile;
- inspect the completed workflow in AURA.

The platform identity mapping layer is therefore essential.

---

# 21. Integrations Framework

Use a common connector interface:

```python
class Integration(Protocol):
    name: str
    capabilities: set[str]

    async def connect(self, config): ...
    async def health(self): ...
    async def fetch(self, request): ...
    async def execute(self, action): ...
    async def disconnect(self): ...
```

Capabilities should be declarative:

```text
calendar.read
calendar.write
messages.read
messages.write
contacts.read
files.read
files.write
tasks.read
tasks.write
```

Potential integrations:

- Google Calendar;
- Outlook Calendar;
- Gmail;
- Slack;
- Telegram;
- Discord;
- WhatsApp;
- Notion;
- Google Drive;
- OneDrive;
- GitHub;
- GitLab;
- cloud storage;
- accounting tools;
- backup targets.

Do not grant every integration full tool access automatically.

---

# 22. Tool Security

Every tool should declare:

```yaml
name: send_email
action_class: external_write
risk: R2
requires_approval: true
scopes:
  - email.send
data_classes:
  - communication
```

## 22.1 Credential design

Never expose secrets directly to model prompts.

Use:

- environment/secret store;
- encrypted local credential store;
- short-lived tokens where possible;
- scoped integration credentials;
- redaction middleware;
- credential-independent tool interfaces.

Hermes's current security documentation includes command approval, DM pairing, container isolation, sandbox backends, and an egress credential-injection concept; use those native safety features where the pinned Hermes version provides them. citeturn105020search1

---

# 23. Approval System

## 23.1 Approval request UI

```text
┌─────────────────────────────────────────┐
│ AURA needs approval                     │
│                                         │
│ Action: Send client email               │
│ Recipient: client@example.com           │
│                                         │
│ Draft:                                   │
│ “Hello …”                                │
│                                         │
│ [ Edit ] [ Reject ] [ Approve & Send ]  │
└─────────────────────────────────────────┘
```

Approval must include:

- action;
- target;
- affected data;
- expected consequence;
- exact payload where relevant;
- expiration;
- source session;
- approving identity.

---

# 24. Automation System

AURA should provide natural-language scheduling on top of Hermes scheduling where supported.

Examples:

> “Every Friday at 5 PM, summarize this week's client activity.”

> “Every morning at 7 AM, tell me my top three priorities.”

> “Every night, verify backups succeeded.”

## 24.1 Automation model

```text
Automation
├── trigger
├── schedule
├── condition
├── workflow
├── permissions
├── delivery target
├── retry policy
├── timeout
├── approval policy
├── last run
└── next run
```

## 24.2 Failure policy

- retry transient errors;
- exponential backoff;
- circuit break repeatedly failing connectors;
- alert user after threshold;
- preserve logs;
- never loop indefinitely.

---

# 25. Workflow Engine

AURA should represent business workflows explicitly rather than forcing the model to recreate them each turn.

Example client health workflow:

```text
Load client
   ↓
Load active projects
   ↓
Collect overdue tasks
   ↓
Check communication recency
   ↓
Check milestone health
   ↓
Check unpaid/blocked items if authorized
   ↓
Compute risk score
   ↓
Generate summary
   ↓
Create recommendations
   ↓
Ask approval for external actions
```

A workflow should be:

- resumable;
- observable;
- retryable;
- idempotent;
- cancellable.

---

# 26. Event-Driven Internal Architecture

Use an internal event bus even in a single-user installation.

Events:

```text
conversation.message.received
conversation.message.completed
memory.candidate.created
memory.index.requested
memory.index.completed
client.updated
project.updated
task.updated
workflow.started
workflow.step.completed
workflow.failed
tool.started
tool.completed
approval.requested
approval.completed
notification.created
integration.connected
integration.error
backup.completed
```

This reduces coupling between core state changes and secondary actions.

---

# 27. Observability

## 27.1 Structured logging

Every operation should carry:

- `trace_id`;
- `span_id`;
- `session_id`;
- `user_id`;
- `workflow_id`;
- `tool_call_id`;
- `model_id`.

## 27.2 Metrics

Track:

### Product

- DAU/WAU;
- sessions/day;
- messages/day;
- tasks created/completed;
- projects active;
- memory retrieval usage;
- automation success rate.

### AI

- model latency;
- first-token latency;
- completion latency;
- token usage where available;
- tool-call success;
- retrieval hit rate;
- grounded response rate;
- hallucination/error reports.

### System

- CPU;
- RAM;
- GPU/VRAM;
- queue depth;
- disk usage;
- Chroma latency;
- SQLite lock contention;
- WebSocket connection count.

---

# 28. Health & Diagnostics

Create `/health`, `/ready`, and a diagnostic report.

```text
AURA HEALTH
──────────────────────
API                  ✓
SQLite               ✓
Chroma               ✓
Hermes               ✓
Local LFM            ✓
STT                  ✓
TTS                  ✓
Gateway              ✓
Storage              ✓
Scheduler             ✓
Last backup           12m ago
Memory index queue    0
```

A `aura doctor` command should check:

- runtime versions;
- config validity;
- database integrity;
- index integrity;
- storage permissions;
- model availability;
- Hermes capabilities;
- gateway connectivity;
- encryption/secret configuration;
- backup health.

---

# 29. Backup and Restore

Back up at minimum:

- SQLite DB;
- Chroma persistent data;
- configuration;
- user-approved uploaded files;
- skills;
- integration metadata;
- exportable audit log.

## 29.1 Backup rules

- encrypted;
- versioned;
- integrity checked;
- retention configurable;
- periodic restore verification;
- no plaintext secrets in backups;
- atomic snapshot process.

## 29.2 Recovery objectives

Initial targets:

- RPO: ≤ 24h default, configurable;
- RTO: ≤ 4h for standard single-host deployment.

Optimize these targets once operational characteristics are measured.

---

# 30. Privacy Architecture

Because the system will contain career, client, financial, relationship, and potentially sensitive health/wellbeing data, privacy cannot be an afterthought.

## 30.1 Data classes

```text
PUBLIC
NORMAL
PRIVATE
SENSITIVE
RESTRICTED
```

## 30.2 Rules

Sensitive data should:

- have explicit storage policy;
- have access restrictions;
- be excluded from unnecessary analytics;
- be excluded from external-model calls unless permitted;
- be redacted from logs;
- have retention controls;
- have deletion workflows.

## 30.3 Privacy modes

### Standard

Normal assistant behavior.

### Private

Minimize external model calls and persistent memory.

### Local-only

No cloud inference/integrations unless explicitly enabled.

### Ephemeral

No long-term memory retention.

---

# 31. Search Experience

Global search should unify:

- memories;
- messages;
- projects;
- clients;
- documents;
- tasks;
- sessions;
- automations.

Filters:

- domain;
- date range;
- entity type;
- source;
- sensitivity;
- relevance;
- archived/active.

Search results should show why a result matched:

```text
92% relevant
Semantic match • same client • recent project activity
```

> **Status (v1.13.0):** `/api/search` supports `type` (entity-kind),
> `frm`/`to` (date) filters and every result now carries a `matched`
> explainability string; the command palette surfaces it.

---

# 32. Activity Timeline

Build a unified timeline with filters.

Example:

```text
10:31  Client project updated
10:35  AURA indexed meeting notes
10:36  Memory created: client prefers Monday status reports
10:40  Task created: send progress report
11:15  Telegram message received
11:16  AURA prepared weekly summary
```

This becomes the user's operational audit trail.

---

# 33. Notifications

Channels:

- in-app;
- desktop;
- push later;
- Telegram;
- email;
- Slack.

Notification types:

- reminder;
- approval;
- workflow completion;
- failure;
- client risk;
- deadline;
- backup result;
- memory conflict;
- integration expiration.

Support notification preferences by type and channel.

---

# 34. API Design

## 34.1 Public API groups

```text
/api/v1/auth
/api/v1/chat
/api/v1/sessions
/api/v1/memory
/api/v1/search
/api/v1/career
/api/v1/clients
/api/v1/projects
/api/v1/personal
/api/v1/tasks
/api/v1/workflows
/api/v1/automations
/api/v1/integrations
/api/v1/files
/api/v1/notifications
/api/v1/activity
/api/v1/settings
/api/v1/system
```

## 34.2 Streaming API

Use WebSocket/SSE events:

```text
message.started
message.delta
thinking.status
retrieval.started
retrieval.completed
tool.started
tool.completed
approval.required
message.completed
message.error
```

Do not stream internal hidden reasoning. Stream user-safe execution status.

---

# 35. Authentication & Authorization

For the first single-user release:

- local login/session;
- optional passkey/2FA later;
- device pairing;
- trusted devices.

For multi-user evolution:

- RBAC;
- tenant isolation;
- organization workspaces;
- service accounts;
- policy engine.

Roles:

```text
OWNER
ADMIN
MEMBER
READ_ONLY
SERVICE
```

Permissions should be capability-based as well as role-based.

---

# 36. Frontend State Architecture

Split state into:

### Server state

TanStack Query:

- projects;
- tasks;
- clients;
- memories;
- conversations;
- notifications.

### Session UI state

Zustand:

- active panel;
- selected conversation;
- orb state;
- modal state;
- input mode;
- voice state.

### Local transient state

React local state for:

- text input;
- temporary selections;
- form draft state.

Never keep authoritative records solely in client state.

---

# 37. Accessibility

Required:

- keyboard navigation;
- screen-reader labels;
- focus management;
- high-contrast mode;
- reduced-motion mode;
- captions/transcripts;
- form error semantics;
- accessible charts where practical;
- no information conveyed only through color.

The Aura Orb must have a textual status equivalent.

---

# 38. Performance Strategy

## 38.1 UI

Targets:

- initial interactive load: < 2.5s on a typical modern machine;
- route transitions: < 200ms where cached;
- chat visual response begins within 250–500ms when backend is healthy;
- orb maintains 60 FPS on capable devices and degrades gracefully.

## 38.2 AI

Targets:

- local intent classification under ~200ms where feasible;
- retrieval under ~300ms for warm indexes;
- first token under ~1.5s for typical local/cloud models depending on hardware/provider;
- voice turn latency optimized separately.

These are engineering targets, not guarantees; benchmark against actual hardware/models before finalizing SLAs.

> **Status (v1.13.0):** `scripts/benchmark.py` measures the hot paths
> offline + deterministically and gates them in CI (`--ci` exits non-zero on
> a median over budget) — the benchmark now exists and runs on every push.

## 38.3 Memory

- batch embeddings;
- cache hot queries;
- async index writes;
- deduplicate content hashes;
- prune redundant vectors;
- lazy-load large documents.

---

# 39. Reliability & Idempotency

Every external side effect must have an idempotency strategy.

Example:

```text
send_email(idempotency_key)
create_calendar_event(idempotency_key)
backup_project(idempotency_key)
```

Never let a model retry create duplicate real-world actions unintentionally.

Implement:

- idempotency keys;
- transactional outbox where necessary;
- retries only for safe/transient operations;
- dead-letter queue for persistent failures.

> **Status (v1.13.0):** idempotency keys shipped for external side effects —
> webhook fires carry a stable `X-Aura-Idempotency-Key` (`_fire_id` survives
> retries), `comms.send` suppresses identical duplicates within 60s
> (`send_dedupe` table), and retries are already limited to safe/transient
> webhook POSTs with exponential backoff. A full transactional outbox and
> dead-letter queue remain future hardening.

---

# 40. Testing Strategy

## 40.1 Unit tests

Cover:

- domain services;
- policy engine;
- memory scoring;
- retrieval filters;
- context budgeter;
- model routing;
- event handling;
- parsers;
- integration adapters.

## 40.2 Integration tests

Test:

- AURA ↔ Hermes;
- SQLite migrations;
- Chroma indexing;
- worker queue;
- inference adapter;
- voice pipeline;
- gateway adapters;
- connector authentication.

## 40.3 Contract tests

For every external connector:

- input schema;
- output schema;
- auth failure;
- rate-limit handling;
- timeout;
- retry semantics;
- pagination.

## 40.4 End-to-end tests

Golden workflows:

1. New user onboarding;
2. Career profile creation;
3. Resume upload and analysis;
4. Job application tracking;
5. Client creation;
6. Project creation;
7. Task creation/completion;
8. Memory creation and retrieval;
9. Voice conversation;
10. Telegram message continuity;
11. Scheduled automation;
12. Backup and restore;
13. Approval-required external action.

---

# 41. AI Evaluation Framework

Do not rely on subjective demos.

Create a benchmark suite with datasets covering:

### Memory

- correct retrieval;
- irrelevant retrieval rejection;
- temporal conflicts;
- stale memory handling;
- sensitivity boundaries.

### Agent

- correct tool selection;
- correct tool arguments;
- tool retry discipline;
- appropriate approvals;
- cancellation behavior.

### Domain

- career recommendations;
- project health calculations;
- client follow-up generation;
- scheduling quality.

### Multimodal

- voice transcript quality;
- image extraction;
- document ingestion;
- file-grounded responses.

### Safety

- secret leakage;
- unauthorized external action;
- prompt injection;
- malicious documents;
- tool misuse;
- data-boundary violations.

Track evaluation scores per release.

---

# 42. Prompt / Policy Architecture

Do not create one enormous system prompt.

Use layers:

```text
base policy
+ identity policy
+ domain policy
+ workflow policy
+ tool policy
+ memory context
+ current request
```

Keep rules in versioned files/configuration where practical.

Every prompt template should have:

- version;
- purpose;
- input schema;
- output schema;
- evaluation cases.

---

# 43. Prompt Injection Defense

Treat all retrieved content as untrusted data unless it comes from a trusted policy source.

Documents, web pages, emails, Slack messages, PDFs, and client notes can contain instructions intended to manipulate the agent.

Use clear boundaries:

```text
SYSTEM POLICY

TRUSTED APPLICATION STATE

UNTRUSTED EXTERNAL CONTENT

USER REQUEST
```

Tool authorization must never be based solely on text inside retrieved external content.

---

# 44. Model Router

Build an explicit router:

```text
                 REQUEST
                    │
              classify workload
                    │
      ┌─────────────┼─────────────┐
      ▼             ▼             ▼
   tiny/local    local capable   cloud heavy
      │             │             │
      ▼             ▼             ▼
  fast LFM       larger LFM      provider
```

Routing features:

- task type;
- privacy level;
- latency target;
- model availability;
- hardware load;
- context length;
- expected reasoning complexity.

## 44.1 Example policy

```yaml
simple_chat:
  preferred: local

memory_classification:
  preferred: local

sensitive_document:
  preferred: local

complex_research:
  preferred: cloud_or_large_local

voice_transcription:
  preferred: local_or_low_latency

vision_heavy:
  preferred: multimodal_provider
```

---

# 45. LFM Integration Plan

Liquid AI currently lists LFM families covering text, vision-language, audio, embedding, and other specialized models, with an explicit emphasis on efficient CPU/GPU/NPU deployment. citeturn299431search0

## 45.1 Local inference service

Expose OpenAI-like internal APIs where practical:

```text
POST /v1/chat/completions
POST /v1/embeddings
POST /v1/audio/transcriptions
POST /v1/audio/speech
POST /v1/vision/analyze
GET  /v1/models
GET  /health
```

This keeps AURA independent from a specific runtime implementation.

## 45.2 Model lifecycle

```text
download
  ↓
verify checksum
  ↓
register
  ↓
benchmark
  ↓
activate
  ↓
monitor
  ↓
replace/rollback
```

Do not silently download multi-gigabyte models from the application request path.

---

# 46. Data Import

AURA should have a data import subsystem for:

- existing notes;
- resumes;
- spreadsheets;
- project files;
- exported conversations;
- documents;
- bookmarks;
- client lists.

Import flow:

```text
Select source
  ↓
Preview
  ↓
Classify
  ↓
Map fields
  ↓
Deduplicate
  ↓
Validate
  ↓
Import
  ↓
Index
  ↓
Report
```

Every imported record needs source provenance.

---

# 47. Migration / Refactor Strategy for an Existing Codebase

When an existing AURA codebase is provided, do not immediately rewrite it.

## Phase A — Reconnaissance

Inspect:

- repository tree;
- package managers;
- application entry points;
- routes;
- components;
- services;
- database schema;
- migrations;
- state management;
- auth;
- environment variables;
- Hermes integration;
- model integrations;
- tests;
- Docker/deployment files;
- CI/CD;
- logging;
- analytics;
- dead code;
- TODO/FIXME;
- security risks;
- duplicate utilities.

## Phase B — Current-state map

Produce:

```text
CURRENT
├── working
├── partially working
├── stubbed
├── broken
├── duplicated
├── insecure
├── missing
└── obsolete
```

## Phase C — Gap matrix

```text
Feature                Existing    Target    Action
---------------------------------------------------------
Auth                   partial     full      refactor
Memory                 weak        hybrid    rebuild
Orb                    exists      stateful   enhance
Career                 stub        full      build
Clients                partial     full      refactor
Personal               missing     full      build
Gateway                partial     full      integrate
Voice                  missing     full      add
LFM                    partial     routed    refactor
Search                 weak        hybrid    rebuild
Audit                  missing     full      add
Backups                partial     reliable  refactor
```

## Phase D — Incremental refactor

Use vertical slices, not one giant rewrite.

1. foundation;
2. data model;
3. memory;
4. agent orchestration;
5. UI shell;
6. each domain panel;
7. voice;
8. gateway;
9. automation;
10. hardening.

---

# 48. Implementation Phases

## Phase 0 — Repository Audit & Architecture Lock

### Deliverables

- architecture decision record;
- dependency inventory;
- Hermes version compatibility report;
- threat model;
- data classification map;
- API inventory;
- existing feature map;
- technical debt backlog;
- target repository structure.

### Exit criteria

- no critical unknown architecture areas;
- Hermes compatibility confirmed;
- persistence strategy fixed;
- model-provider abstraction agreed.

---

## Phase 1 — Foundation

### Build

- monorepo organization;
- environment configuration;
- logging;
- error model;
- database;
- migrations;
- event bus;
- API shell;
- frontend shell;
- auth/session baseline;
- health checks;
- CI pipeline.

### Exit criteria

A developer can clone the repository, run one documented setup flow, and reach a working AURA shell.

---

## Phase 2 — Core AURA Conversation

### Build

- conversation model;
- session model;
- streaming response;
- Hermes adapter;
- tool event display;
- cancellation;
- retry;
- conversation persistence.

### Exit criteria

User can chat with AURA through the web UI and all events are persisted and observable.

---

## Phase 3 — Memory 1.0

### Build

- memory schema;
- Chroma collections;
- embedding service;
- FTS5 indexes;
- hybrid retrieval;
- memory write policy;
- memory explorer UI;
- delete/edit/forget operations.

### Exit criteria

AURA can correctly recall previously established preferences and project context across sessions with measurable retrieval quality.

---

## Phase 4 — Context & Orchestration

### Build

- intent router;
- domain router;
- context engine;
- risk engine;
- plan engine;
- approval framework;
- tool policy mapping.

### Exit criteria

AURA can distinguish simple responses, retrieval, tool actions, multi-step workflows, and approval-required operations.

---

## Phase 5 — Aura Orb & Command Center

### Build

- 3D orb;
- state animation;
- activity feed;
- command bar;
- responsive layout;
- accessibility mode;
- reduced-motion support.

### Exit criteria

Orb accurately mirrors runtime state and falls back cleanly on unsupported devices.

---

## Phase 6 — Career Panel

### Build

- profile;
- resumes;
- job tracking;
- interview workflows;
- skills/goals;
- time blocking;
- career memory.

### Exit criteria

At least three complete end-to-end career workflows pass E2E tests.

---

## Phase 7 — Clients & Projects

### Build

- client directory;
- project tracking;
- project timeline;
- deliverables;
- task boards;
- status summaries;
- backup management;
- client health checks.

### Exit criteria

User can manage a client/project lifecycle and AURA can reason over it using both structured data and memory.

---

## Phase 8 — Personal Panel

### Build

- routines;
- reflections;
- personal goals;
- wellbeing organization;
- finance records;
- relationship notes;
- privacy mode.

### Exit criteria

Sensitive data is isolated according to the privacy policy and does not accidentally leak into unrelated domains/models/logs.

---

## Phase 9 — Voice & Multimodal

### Build

- microphone UX;
- STT;
- TTS;
- voice interruption;
- image upload;
- document upload;
- ingestion pipeline;
- multimodal memory.

### Exit criteria

Voice becomes a first-class modality, not a separate code path.

---

## Phase 10 — Multi-Platform Gateway

### Build

- platform identity mapping;
- Telegram;
- Discord;
- Slack;
- WhatsApp;
- Email;
- webhook API;
- unified delivery policies.

Hermes already provides broad gateway support in current versions; use its native adapters where compatible instead of reimplementing each transport. citeturn105020search0turn105020search2

### Exit criteria

A task started on one platform can be continued and completed on another without losing state.

---

## Phase 11 — Automation & Workflows

### Build

- scheduler UI;
- recurring workflows;
- notification rules;
- workflow editor;
- retries;
- failure handling;
- approval steps.

### Exit criteria

Scheduled workflows run reliably, record outcomes, and recover from transient failures.

---

## Phase 12 — Local LFM & Hybrid Intelligence

### Build

- local inference service;
- model registry;
- model router;
- benchmark harness;
- cloud fallback;
- privacy-aware routing.

### Exit criteria

AURA can complete defined workflows offline/local-first and route difficult work to approved external providers when policy permits.

---

## Phase 13 — Security Hardening

### Build

- secret management;
- permission matrix;
- tool-risk classification;
- approval enforcement;
- sandbox policy;
- prompt-injection protections;
- audit log;
- sensitive-data redaction.

### Exit criteria

No critical security findings in the defined threat model and security regression suite.

---

## Phase 14 — Performance & Reliability

### Build

- profiling;
- query optimization;
- vector index tuning;
- caching;
- background workers;
- rate-limit handling;
- backpressure;
- crash recovery;
- restore testing.

### Exit criteria

Performance benchmarks meet target ranges on supported hardware.

---

## Phase 15 — Production Readiness

### Build

- release pipeline;
- versioning;
- migration tooling;
- backups;
- disaster recovery;
- monitoring;
- admin diagnostics;
- support bundle;
- documentation.

### Exit criteria

A clean installation and a restore-from-backup installation both produce a functioning system.

---

# 49. Milestone Definition of Done

A feature is not complete when the UI appears.

Every feature must satisfy:

```text
UI
✓
API
✓
Domain logic
✓
Persistence
✓
Memory impact evaluated
✓
Permissions
✓
Audit event
✓
Error handling
✓
Loading states
✓
Empty states
✓
Retry behavior
✓
Tests
✓
Accessibility
✓
Observability
✓
Documentation
✓
Backup/restore impact
✓
```

---

# 50. Prioritized Backlog

## P0 — Must exist

- application shell;
- auth/session;
- Hermes adapter;
- conversation engine;
- SQLite;
- memory system;
- hybrid search;
- context engine;
- career panel;
- clients/projects panel;
- personal panel;
- orb;
- tool events;
- approval system;
- audit log;
- backup/restore;
- health checks.

## P1 — Important

- voice;
- document ingestion;
- multimodal workflows;
- Telegram;
- Discord;
- Slack;
- WhatsApp;
- automation UI;
- local LFM router;
- desktop shell.

## P2 — Advanced

- ~~deeper agent delegation~~ — shipped v1.12.0 (`web.search` + `web_search` intent) and v1.13.0 (parallel R0 step execution);
- ~~advanced proactive intelligence~~ — shipped v1.12.0 (opportunity → scheduled-mission auto-action);
- ~~autonomous skill improvement~~ — shipped v1.13.0 (`routine_mission` detector → one-click routine scheduling);
- ~~advanced analytics~~ — shipped v1.13.0 (`forecast`: spend/tasks/sleep/mood projections);
- ~~hands-free voice calls~~ — shipped v1.14.0 (Call screen: Web Speech loop, barge-in, call summaries);
- ~~local machine control~~ — shipped v1.14.0 (audited terminal + ssh machines + Ollama model room), hardened v1.15.0 (origin guard, script library, drop-zone watch, machine liveness);
- mobile app — not planned; the PWA already covers install/offline/push (incl. the v1.14 call mode);
- plugin marketplace — drop-in plugins ship (`text_stats`, `unit_convert`); a browse/install registry is future work;
- multi-user organizations — deferred (single-user retained);
- federated/shared workspaces — deferred (single-user retained).

---

# 51. Proactive Intelligence Roadmap

Once the core is stable, AURA should evolve from reactive assistant to proactive assistant.

## 51.1 Opportunity detector

Examples:

- missed follow-up;
- deadline risk;
- stale client relationship;
- overloaded week;
- conflicting appointments;
- repeated manual task;
- missing backup;
- recurring expense anomaly.

## 51.2 Proactive policy

Never spam the user.

Rank opportunities using:

```text
importance
× urgency
× confidence
× user preference
× disruption cost
```

Then deliver only above a configurable threshold.

> **Status (v1.12.0):** detectors, ranking, snooze/dismiss, and per-type
> actions shipped in v1.8.0; v1.12.0 added the *auto-action* close-out —
> repeated-chore and stale-backup opportunities resolve into a scheduled
> mission in one click.

---

# 52. Personal Operating System Graph

The long-term architecture should support an entity graph:

```text
User
 ├── Career
 │    ├── Goal
 │    ├── Job
 │    ├── Resume
 │    └── Skill
 │
 ├── Clients
 │    ├── Client
 │    ├── Project
 │    ├── Task
 │    └── Communication
 │
 └── Personal
      ├── Goal
      ├── Routine
      ├── Finance
      └── Reflection
```

Cross-links:

```text
Client ── Project ── Task
   │                  │
   └── Communication  └── TimeBlock

CareerGoal ── TimeBlock

PersonalGoal ── Routine

Memory ── Entity

Conversation ── Entity
```

This graph enables questions such as:

> “What is competing for my attention this week?”

AURA can then reason over time blocks, projects, career goals, deadlines, and routines together.

---

# 53. Data Lineage

Every AI-derived fact should have provenance where feasible.

```text
Claim
 ↓
Derived from
 ├── message
 ├── document
 ├── structured record
 ├── tool result
 └── user confirmation
```

This supports trustworthy answers and debugging.

---

# 54. Explainability UX

Provide compact explanations such as:

> “I recommended this because the project deadline is tomorrow, two tasks are overdue, and the client has not received a status update in 6 days.”

This is more useful than exposing hidden model reasoning.

---

# 55. Internationalization

Design for i18n from the beginning.

- locale-aware dates;
- timezone support;
- localized number/currency formatting;
- translated UI strings;
- multilingual STT/TTS;
- language preference memory.

Never hard-code date formatting in business logic.

---

# 56. Time & Scheduling

Store timestamps internally in UTC.

Store user timezone separately:

```text
user.timezone = Africa/Nairobi
```

Render in local timezone.

Automation rules must be timezone-aware and robust around daylight-saving transitions for users in regions that use them.

---

# 57. File and Attachment Strategy

Use content-addressed storage when practical:

```text
sha256(file) → storage key
```

Benefits:

- deduplication;
- integrity verification;
- safer caching;
- reproducible references.

Attachment metadata:

- MIME;
- size;
- checksum;
- source;
- owner;
- sensitivity;
- extracted text status;
- embedding status;
- retention status.

---

# 58. Error UX

Errors should be actionable.

Bad:

> “Internal server error.”

Better:

> “Telegram is disconnected. I saved your message and will retry once the connection is restored.”

Include:

- what failed;
- what was preserved;
- what AURA will do next;
- whether user action is required.

---

# 59. Offline Mode

AURA should remain useful offline.

Available offline:

- local conversations;
- local memory search;
- local tasks/projects;
- local LFM chat;
- local file search;
- local notes;
- local reminders.

Unavailable/deferred:

- cloud integrations;
- remote communication;
- cloud-only models;
- some external searches.

Queue deferred actions safely and visibly.

---

# 60. Deployment Profiles

## Profile A — Local Personal

One device:

- SQLite;
- Chroma;
- local Hermes;
- local LFM;
- local filesystem;
- optional internet connectors.

## Profile B — Home Server

- Docker Compose;
- persistent volumes;
- remote mobile/browser access;
- scheduled backups.

## Profile C — Cloud VPS

- reverse proxy;
- TLS;
- AURA API;
- Hermes runtime;
- Chroma;
- encrypted backup target.

## Profile D — Scaled

- PostgreSQL;
- separate queue;
- distributed workers;
- object storage;
- observability stack;
- separate inference cluster.

The product should not require Profile D to ship the first production version.

---

# 61. CI/CD

Pipeline:

```text
commit
 ↓
lint
 ↓
type check
 ↓
unit tests
 ↓
integration tests
 ↓
security scan
 ↓
build
 ↓
E2E smoke tests
 ↓
artifact publish
 ↓
staged deploy
 ↓
health validation
```

Use migration checks to prevent destructive schema changes without explicit approval.

---

# 62. Release Strategy

Use semantic release discipline:

```text
MAJOR.MINOR.PATCH
```

Maintain:

- changelog;
- migration notes;
- model compatibility matrix;
- Hermes compatibility matrix;
- rollback instructions.

Never upgrade Hermes, the model runtime, or the database engine in the same release as a large feature unless necessary.

---

# 63. Documentation Set

The project should include:

```text
docs/
├── README.md
├── architecture.md
├── data-model.md
├── memory.md
├── agent-runtime.md
├── hermes-integration.md
├── lfm-inference.md
├── voice.md
├── gateway.md
├── security.md
├── privacy.md
├── workflows.md
├── integrations.md
├── deployment.md
├── backup-restore.md
├── operations.md
├── testing.md
├── evaluation.md
└── troubleshooting.md
```

Also include Architecture Decision Records:

```text
docs/decisions/
├── ADR-001-hermes-runtime.md
├── ADR-002-sqlite-source-of-truth.md
├── ADR-003-chroma-semantic-layer.md
├── ADR-004-local-first-model-routing.md
├── ADR-005-event-driven-workflows.md
└── ADR-006-approval-security-model.md
```

---

# 64. Developer Experience

One-command development target:

```bash
make setup
make dev
```

Useful commands:

```bash
make test
make test-e2e
make lint
make typecheck
make db-migrate
make db-reset
make seed
make index-rebuild
make aura-doctor
make backup
make restore
make hermes-check
make eval
```

---

# 65. Seed / Demo Mode

Provide demo data for development.

Example:

- 3 clients;
- 5 projects;
- 20 tasks;
- 2 careers/resumes;
- mock schedule;
- sample memories;
- sample automations;
- sample notifications.

This is required for visual and workflow development without using real personal data.

---

# 66. Security Threat Model

Explicitly evaluate:

### Threats

- prompt injection;
- malicious files;
- malicious web content;
- stolen tokens;
- unauthorized platform account access;
- local filesystem abuse;
- arbitrary shell execution;
- destructive tools;
- memory poisoning;
- cross-domain data leakage;
- cross-user data leakage;
- backup theft;
- logging of sensitive data.

### Controls

- least privilege;
- sandboxing;
- tool scopes;
- approvals;
- credential isolation;
- audit logging;
- input sanitization;
- content trust boundaries;
- encrypted storage;
- secret redaction;
- network egress control;
- retention/deletion policies.

---

# 67. Memory Poisoning Defense

Because AURA writes long-term memory from user interactions, an attacker could attempt to establish malicious “facts.”

Mitigations:

- provenance tracking;
- confidence;
- explicit user confirmation for sensitive memories;
- contradiction detection;
- source weighting;
- expiration;
- memory review UI;
- no policy changes based solely on memory.

Memory must never override hard security policy.

---

# 68. Domain Isolation Rules

An important architectural invariant:

> **Cross-domain context is allowed; uncontrolled cross-domain mutation is not.**

Example:

A career task may read:

- schedule;
- selected personal availability;
- relevant preferences.

But a career workflow should not automatically read detailed private financial records merely because they exist in memory.

Implement domain scopes:

```text
career.read
career.write
clients.read
clients.write
personal.read
personal.write
memory.global.read
memory.sensitive.read
```

---

# 69. AURA Tool Registry

Create a centralized registry:

```python
ToolDefinition(
    name="create_task",
    domain="core",
    risk="R1",
    permissions=["tasks.write"],
    idempotent=True,
    supports_dry_run=True,
)
```

The model receives only the tools allowed for the current context.

---

# 70. Dry Run Mode

Every mutating workflow that can safely support it should have a dry-run mode.

Example:

> “Show me what AURA would do before doing it.”

Output:

```text
DRY RUN
1. Identify 4 overdue tasks
2. Draft client follow-up
3. Schedule reminder for tomorrow 09:00
4. No external message will be sent
```

This improves trust and lowers operational risk.

---

# 71. Undo / Reversal

Where technically possible:

- task edits → history + restore;
- notes → version history;
- project changes → audit + reversal;
- scheduled jobs → unschedule;
- outbound messages → cannot truly undo externally, so approval and preview matter more.

---

# 72. Search / Retrieval Evaluation Targets

Establish measurable baselines.

Suggested initial targets:

- top-5 semantic recall ≥ 85% on curated benchmark;
- top-5 hybrid recall ≥ 92%;
- duplicate retrieval rate < 10%;
- stale-memory usage < 5% in benchmark;
- unsupported memory claim rate near zero for known adversarial cases.

These are initial quality targets and should be revised from empirical benchmarks.

---

# 73. Chat UX Details

Each assistant response can optionally include:

```text
Answer
  ↓
Sources / memory used
  ↓
Actions taken
  ↓
Pending approvals
  ↓
Follow-up suggestions
```

Example compact footer:

> Used: 2 project records, 3 memories, 1 calendar event.  
> Action: created 2 tasks.  
> Approval needed: sending client email.

---

# 74. Session Continuity

Sessions should support:

- rename;
- archive;
- pin;
- search;
- export;
- delete;
- branch/fork;
- continue from another platform.

Do not confuse session history with long-term memory.

Session history answers:

> “What did we talk about?”

Memory answers:

> “What should AURA remember?”

---

# 75. Conversation Compaction

Long sessions should be compacted into summaries while preserving important state.

Compaction output:

```text
Conversation summary
Active goals
Open tasks
Decisions
Important facts
Unresolved questions
Memory candidates
```

Use structured summaries instead of relying only on raw transcript truncation.

---

# 76. Agent Delegation Strategy

Use Hermes delegation where supported for parallel work.

Example:

```text
Main AURA task
   ├── subagent: review project status
   ├── subagent: inspect client communications
   └── subagent: analyze upcoming calendar
                  ↓
             aggregate results
                  ↓
              final answer
```

Delegated agents must receive only required context and permissions.

Never give every subagent unrestricted access by default.

> **Status (v1.15.0):** mission delegation (v1.9.0), the LLM mission planner
> (v1.10.0), `web.search` (v1.12.0), parallel execution of R0 read-only
> steps in chat plans (v1.13.0, pool of 4), the machine layer — `system.run`
> on the host + named ssh machines (v1.14) — and the script library with an
> origin guard and danger-gated saves (v1.15) — cover the delegation
> spectrum. Machine-executing tools are deliberately capped at
> R3: visible and approvable in chat, never eligible for unattended mission
> plans. Fully-isolated *reasoning* subagents (separate model instances that
> deliberate and report back) remain future work.

Hermes currently documents isolated delegation/subagent execution and parallelized workflows. citeturn105020search10turn105020search2

---

# 77. Cost Controls

For cloud models:

- per-request budget;
- daily/monthly budget;
- provider fallback;
- cache reusable outputs;
- local-model preference;
- limit unnecessary long-context calls;
- report estimated usage.

Expose:

```text
This month
Local inference: 82%
Cloud inference: 18%
Estimated cloud cost: …
```

---

# 78. Resource-Aware Intelligence

The router should consider hardware state.

Example:

```text
GPU utilization high
↓
route tiny classification tasks to CPU
↓
queue large generation
```

Battery mode:

- lower orb frame rate;
- reduce background embeddings;
- disable unnecessary proactive jobs;
- prefer smaller local models.

---

# 79. Startup Sequence

AURA startup:

```text
Load config
   ↓
Validate environment
   ↓
Initialize logging
   ↓
Open SQLite
   ↓
Validate migrations
   ↓
Connect Chroma
   ↓
Initialize inference providers
   ↓
Probe Hermes
   ↓
Load skills
   ↓
Load integrations
   ↓
Start workers
   ↓
Start API
   ↓
Start UI
```

The system should report partial availability rather than crashing because an optional integration is offline.

---

# 80. Shutdown / Recovery

On shutdown:

- stop accepting new work;
- finish safe in-flight operations;
- checkpoint jobs;
- flush logs;
- close DB connections;
- close provider sessions.

On restart:

- recover queued workflows;
- mark stale tool calls appropriately;
- re-run safe jobs only if idempotent;
- surface unresolved approvals.

---

# 81. Operational Runbooks

Create runbooks for:

- DB corruption;
- Chroma failure;
- Hermes unavailable;
- LFM unavailable;
- stuck workflow;
- gateway disconnected;
- expired integration token;
- full disk;
- failed backup;
- restore;
- security incident;
- model rollback.

---

# 82. UX States That Must Be Designed

For every screen:

- loading;
- empty;
- populated;
- partial data;
- offline;
- permission denied;
- error;
- retrying;
- syncing;
- destructive confirmation;
- first-run onboarding.

Never leave these to generic error handling.

---

# 83. Onboarding

Onboarding should be progressive.

### Step 1

Identity + timezone.

### Step 2

Choose primary domains:

- Career;
- Clients;
- Personal.

### Step 3

Choose memory mode.

### Step 4

Configure local model / provider.

### Step 5

Connect optional platforms.

### Step 6

Set notification style.

### Step 7

Create first goals/projects.

End with:

> “Ask AURA anything.”

---

# 84. First-Run Demo

AURA should immediately demonstrate its value.

Example:

```text
AURA:
“I can help you organize your career, clients, and personal priorities.
I can also remember useful preferences across sessions.

Try:
‘Show me what needs my attention today.’”
```

Then demonstrate a real workflow using seeded or user-provided data.

---

# 85. Accessibility + Trust Together

The orb should not be the only “AI presence.”

Provide a clear textual runtime indicator:

```text
● Ready
● Listening
● Working on 2 tasks
● Waiting for your approval
```

Users must always know whether the system is merely answering or actually doing something.

---

# 86. Product Analytics

Measure:

- time to first successful workflow;
- percentage of sessions using memory;
- approval acceptance rate;
- tool failure rate;
- automation success;
- user corrections;
- user-requested “forget” actions;
- model routing distribution;
- voice usage;
- gateway usage.

Do not collect sensitive content for analytics merely because it is technically available.

---

# 87. Success Metrics

## Product

- >70% of repeat sessions benefit from memory;
- >80% of core workflows complete without manual intervention except required approvals;
- <5% critical workflow failure;
- <2% cross-domain data leakage in red-team benchmark, with target ultimately zero.

## UX

- user can complete core task in ≤3 interactions after onboarding;
- command bar discoverability >80% in usability testing;
- core dashboard usable on desktop and mobile.

## Engineering

- meaningful automated test coverage;
- reproducible local setup;
- successful migration/restore test;
- documented rollback path for each production release.

---

# 88. Recommended Build Order Within Each Feature

For every module:

```text
1. domain schema
2. migration
3. domain service
4. API contract
5. authorization
6. event/audit
7. UI read path
8. UI write path
9. AI tool
10. memory behavior
11. integration
12. tests
13. observability
14. documentation
```

This prevents the common failure mode of building beautiful UI over incomplete business logic.

---

# 89. Refactoring Rules

When refactoring existing code:

### Preserve

- working features;
- stable external contracts where practical;
- user data;
- migration compatibility.

### Replace

- duplicate abstractions;
- giant components;
- direct DB access from UI;
- hard-coded model calls;
- hard-coded integrations;
- global mutable state;
- silent exception handling;
- hidden background jobs.

### Extract

- domain services;
- adapters;
- policies;
- event handlers;
- reusable components;
- provider interfaces.

---

# 90. Code Quality Standards

Require:

- type annotations;
- clear module boundaries;
- deterministic business logic;
- explicit error types;
- dependency injection for external services;
- no secrets in code;
- small cohesive functions;
- tests for behavior, not implementation details;
- comments explaining *why*, not what.

---

# 91. Architectural Invariants

These are non-negotiable:

1. SQLite/domain stores are authoritative for structured application state.
2. Vector stores are retrieval indexes, not transactional truth.
3. Hermes remains behind an adapter.
4. AI cannot bypass the authorization layer.
5. External side effects have explicit risk/approval policies.
6. Long-term memory is selective, not a transcript dump.
7. Sensitive data has policy-aware routing.
8. Every meaningful side effect produces an audit event.
9. Every background workflow is observable.
10. UI never becomes the source of truth.
11. External content is untrusted by default.
12. All irreversible operations require stronger confirmation.
13. Model providers are swappable.
14. Local inference is a first-class capability, not a fallback afterthought.
15. The product must remain functional without the 3D orb.

---

# 92. Definition of AURA OS “Complete”

AURA OS should not be declared complete simply because the three panels render.

The system reaches **v1 production completeness** when it can demonstrate the following end-to-end loop:

```text
User asks something
       ↓
AURA understands intent
       ↓
Chooses appropriate domain
       ↓
Retrieves structured state
       ↓
Retrieves relevant memory
       ↓
Selects model/provider
       ↓
Creates a bounded plan
       ↓
Executes via Hermes/tools
       ↓
Requests approval where needed
       ↓
Performs action
       ↓
Validates result
       ↓
Updates application state
       ↓
Records audit event
       ↓
Updates appropriate memory
       ↓
Shows concise result
       ↓
Makes it available from another platform
```

That loop is the real product.

> **Status (v1.12.0):** every step of the loop is implemented and exercised
> by the live E2E suite — understanding (intent router), domain choice,
> structured retrieval, memory retrieval, model/provider selection
> (privacy-ordered chain), bounded planning, Hermes/tool execution,
> approvals, action, validation, state updates, audit events, memory
> writes, concise results, and cross-platform reachability (gateway +
> push). The only unshipped surfaces are the user-supplied live credentials
> (Telegram/WhatsApp/HA tokens) and the physical always-on host — both
> documented in `docs/REMOTE_ACCESS.md`.

---

# 93. Example End-to-End Scenarios

## Scenario A — Career

> “AURA, tailor my CV for this job and tell me what gaps I have.”

Expected:

1. ingest job description;
2. identify relevant resume;
3. retrieve career preferences;
4. analyze skill match;
5. produce gap analysis;
6. generate tailored CV draft;
7. show changes;
8. allow export;
9. record useful career memory only where appropriate.

## Scenario B — Client

> “Prepare tomorrow's status update for Acme.”

Expected:

1. retrieve client;
2. retrieve project(s);
3. inspect completed/overdue tasks;
4. inspect recent communications;
5. identify blockers;
6. draft status update;
7. request approval before sending;
8. send through authorized platform;
9. record action.

## Scenario C — Personal

> “Help me plan tomorrow around work, exercise, and my important personal tasks.”

Expected:

1. retrieve schedule;
2. retrieve applicable personal preferences;
3. retrieve work priorities;
4. create proposed time blocks;
5. resolve conflicts;
6. ask approval before calendar mutation;
7. schedule after confirmation.

## Scenario D — Voice

User speaks:

> “What did we agree with the client last Tuesday?”

Expected:

1. STT;
2. temporal intent resolution;
3. client identification;
4. session/search retrieval;
5. memory retrieval;
6. answer with provenance.

## Scenario E — Cross-platform

1. User starts workflow on web.
2. AURA waits for approval.
3. Approval arrives in Telegram.
4. AURA continues workflow.
5. Completion appears in web activity timeline.

---

# 94. Final Architecture Summary

```text
                           AURA OS
                              │
             ┌────────────────┴────────────────┐
             │                                 │
       EXPERIENCE LAYER                  GATEWAY LAYER
             │                                 │
   ┌─────────┼─────────┐              Telegram / Discord
   │         │         │              Slack / WhatsApp
  Chat      Orb     Panels            Email / Webhooks
   │         │         │                     │
   └─────────┼─────────┘                     │
             ▼                               ▼
                 AURA ORCHESTRATOR
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
     Context           Policy          Workflow
     Engine            Engine            Engine
        │                │                 │
        └────────────────┼─────────────────┘
                         │
                     HERMES ADAPTER
                         │
                 ┌───────┼────────┐
                 │       │        │
              Tools    Skills   Delegation
                 │       │        │
                 └───────┼────────┘
                         │
                  MODEL ROUTER
                         │
             ┌───────────┼───────────┐
             │           │           │
          Local LFM   Cloud LLM    Multimodal
             │           │           │
             └───────────┼───────────┘
                         │
                  DATA + MEMORY
                         │
       ┌────────────┬────┴─────┬──────────────┐
       │            │          │              │
    SQLite       Chroma     File Store      Events
       │            │          │              │
       └────────────┴──────────┴──────────────┘
```

---

# 95. Immediate Execution Checklist

When implementation begins, execute in exactly this order:

## Step 1 — Audit

- inspect repository;
- inventory dependencies;
- identify current Hermes integration;
- identify existing DB/schema;
- identify existing UI;
- identify model integrations;
- identify broken/stubbed features.

## Step 2 — Freeze architecture

- write ADRs;
- pin Hermes version/commit;
- define provider interfaces;
- define domain boundaries;
- define memory policy;
- define security model.

## Step 3 — Establish foundation

- monorepo cleanup;
- environment management;
- migrations;
- logging;
- API shell;
- event bus;
- health endpoints;
- CI.

## Step 4 — Build the real conversation core

- message schema;
- session schema;
- Hermes adapter;
- stream events;
- tool activity;
- cancellation;
- audit.

## Step 5 — Build memory correctly

- SQLite memory tables;
- FTS5;
- Chroma;
- embedding service;
- retrieval scoring;
- memory UI;
- contradiction handling.

## Step 6 — Build the shell

- navigation;
- command bar;
- Orb;
- conversation;
- activity;
- notifications;
- responsive layouts.

## Step 7 — Build the three domains

- Career;
- Clients/Projects;
- Personal.

Build each as a complete vertical slice rather than a collection of incomplete screens.

## Step 8 — Add multimodality

- voice;
- image;
- file ingestion;
- LFM routing.

## Step 9 — Add gateways

- Telegram;
- Discord;
- Slack;
- WhatsApp;
- Email.

## Step 10 — Harden

- approvals;
- permissions;
- sandboxing;
- prompt injection defenses;
- secrets;
- backups;
- audit.

## Step 11 — Optimize

- latency;
- memory retrieval;
- DB indexes;
- vector indexes;
- model routing;
- worker concurrency;
- GPU/CPU utilization.

## Step 12 — Validate

- unit;
- integration;
- E2E;
- AI evals;
- security tests;
- recovery tests;
- performance tests.

---

# 96. Research / Compatibility Notes

This roadmap is intentionally architecture-first. Specific Hermes APIs, configuration keys, and tool names must be validated against the exact pinned release rather than copied from a moving upstream branch.

Current upstream Hermes documentation describes:

- multi-platform gateway capabilities;
- persistent memory and session search;
- skills;
- cron scheduling;
- delegation;
- MCP integrations;
- multiple sandbox backends;
- toolsets and platform-specific tool configuration. citeturn105020search0turn105020search2turn105020search4turn105020search10

Current Liquid AI documentation lists LFM2/LFM2.5 text, vision-language, audio, embedding, and related model families designed for efficient inference across CPU, GPU, and NPU environments. citeturn299431search0turn299431search7

SQLite FTS5 is suitable for the lexical side of AURA's hybrid memory/session search architecture. citeturn299431search8

---

# 97. Final Engineering Principle

> **Do not build AURA as “an AI wrapped in a dashboard.” Build it as a real software system in which AI is one powerful runtime inside a reliable operating architecture.**

The final product should feel magical on the surface and extremely disciplined underneath:

```text
MAGIC
  = multimodal UX
  + persistent context
  + proactive assistance
  + 3D presence
  + natural language
  + cross-platform continuity

TRUST
  = deterministic state
  + provenance
  + policy enforcement
  + approvals
  + auditability
  + backups
  + privacy controls

SCALE
  = modular architecture
  + provider abstraction
  + event-driven workflows
  + isolated runtimes
  + asynchronous workers
  + measurable AI quality
```

That combination is the target architecture for AURA OS.

---

## Appendix A — Suggested Initial Environment Variables

```env
# Application
AURA_ENV=development
AURA_HOST=0.0.0.0
AURA_PORT=8000
AURA_LOG_LEVEL=INFO
AURA_TIMEZONE=Africa/Nairobi

# Database
AURA_DATABASE_URL=sqlite:///./data/aura.db
AURA_DB_POOL_SIZE=5

# Chroma
AURA_CHROMA_URL=http://localhost:8001
AURA_CHROMA_COLLECTION_PREFIX=aura_

# Hermes
HERMES_HOME=~/.hermes
HERMES_VERSION_PIN=v2.0.0
HERMES_RUNTIME_URL=http://localhost:8002

# AI routing
AURA_AI_MODE=hybrid
AURA_LOCAL_MODEL=...
AURA_CLOUD_PROVIDER=...
AURA_CLOUD_MODEL=...

# Voice
AURA_STT_PROVIDER=local
AURA_TTS_PROVIDER=local

# Storage
AURA_STORAGE_PATH=./data/storage
AURA_BACKUP_PATH=./data/backups

# Security
AURA_SESSION_SECRET=...
AURA_ENCRYPTION_KEY=...
```

Actual variable names should be finalized during implementation and secret storage should use environment/secret-management practices appropriate to the deployment.

---

## Appendix B — Initial API Resource Matrix

| Resource | Read | Write | AI Tool | Audit | Memory |
|---|---:|---:|---:|---:|---:|
| Career Profile | ✓ | ✓ | ✓ | ✓ | ✓ |
| Resume | ✓ | ✓ | ✓ | ✓ | ✓ |
| Job | ✓ | ✓ | ✓ | ✓ | ✓ |
| Client | ✓ | ✓ | ✓ | ✓ | ✓ |
| Project | ✓ | ✓ | ✓ | ✓ | ✓ |
| Task | ✓ | ✓ | ✓ | ✓ | selective |
| Personal Goal | ✓ | ✓ | ✓ | ✓ | sensitive-aware |
| Routine | ✓ | ✓ | ✓ | ✓ | selective |
| Finance | ✓ | ✓ | restricted | ✓ | restricted |
| Memory | ✓ | ✓ | ✓ | ✓ | n/a |
| Conversation | ✓ | ✓ | ✓ | ✓ | source |
| Workflow | ✓ | ✓ | ✓ | ✓ | n/a |
| Automation | ✓ | ✓ | ✓ | ✓ | n/a |
| Integration | ✓ | ✓ | ✓ | ✓ | no |
| Backup | ✓ | ✓ | ✓ | ✓ | no |

---

## Appendix C — First Release Acceptance Checklist

```text
[x] Fresh install works                    (onboarding wizard + seed/demo, v1.5.0)
[x] Existing-user migration works          (startup ALTER migrations, live-verified)
[x] User can chat with AURA
[x] Streaming works                        (SSE plan/step/token/result)
[x] Conversations persist                  (sessions + compaction)
[x] AURA recalls approved long-term memories
[x] User can inspect/delete memory
[x] Global search works                    (FTS5 + vector hybrid)
[x] Career panel works end-to-end
[x] Client/project panel works end-to-end
[x] Personal panel works with privacy controls
[x] Orb reflects runtime state
[x] Voice input works                      (browser + server STT)
[x] Voice output works                     (browser/Piper/Edge engines)
[x] File upload works
[x] Document indexing works                (PDF/DOCX/XLSX/PPTX/images)
[x] Local LFM works                        (optional; builtin engine always available)
[x] Cloud fallback policy works            (privacy-ordered chain)
[ ] Telegram continuity works              (token-ready; blocked on live token)
[ ] Discord continuity works               (token-ready; blocked on live webhook)
[ ] Slack continuity works                 (token-ready; blocked on live webhook)
[x] WhatsApp path validated or marked beta (send + Meta handshake code, marked beta)
[x] Email integration validated or marked beta (sandbox inbox + live IMAP)
[x] Approval system works
[x] Audit trail works
[x] Scheduled automation works             (incl. scheduled missions, v1.11-1.12)
[x] Backup succeeds
[x] Restore succeeds
[x] Offline mode behaves predictably       (builtin composer, honest off-states)
[x] Security tests pass                    (rate limits, SSRF guards, redaction)
[x] AI eval suite passes thresholds        (router 299/299, agent 27/27, v1.14)
[x] Performance benchmarks pass            (scripts/benchmark.py, CI-gated, all budgets met v1.14.0)
[x] Documentation is complete
[ ] Release rollback verified              (documented in RELEASE.md; needs a GitHub tag)
```

Blocks on live credentials and the physical always-on host are the only
remaining user-supplied items — see `docs/REMOTE_ACCESS.md` §4.

---

# Conclusion

AURA OS should become a **persistent, multimodal, local-first AI operating layer** over the user's work and personal world. Hermes provides the agentic execution foundation; AURA supplies the structured operating model, memory intelligence, domain workflows, product UX, security boundaries, integrations, observability, and long-term orchestration needed to turn that runtime into a reliable personal OS.

The implementation should proceed from **foundation → memory → orchestration → domains → multimodality → gateways → automation → local intelligence → hardening → scale**, with every feature built as a complete end-to-end slice.

The decisive quality criterion is not how futuristic the orb looks or how many integrations exist. It is whether AURA can reliably move from **understanding → retrieving → planning → acting → validating → remembering**, across sessions and surfaces, while keeping the user in control.
