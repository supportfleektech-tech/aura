# AURA OS enhancement review

## Scope and status

This review addresses the requested AI, MCP/integration, web, entertainment, sound, and camera enhancements. AI cost-mode selection and Docker builds were not part of the current request, and no cost-mode defect has been reproduced. No implementation changes have been made for this new enhancement request; findings below are based on source inspection and documentation, not newly executed runtime tests.

## Prioritized findings

### 1. Retrieval can miss older relevant memories — highest-value first fix

Evidence: `backend/app/memory.py:155–215` limits the candidate pool to the newest 400 records. Older full-text matches cannot enter the final ranking if absent from that pool.

Recommended deliverable: a regression dataset with more than 400 memories and one uniquely relevant older record; verify failure, include full-text candidates independently of recency, then rerun retrieval and agent evaluations. Preserve privacy filtering and deterministic ranking. This is a concrete improvement to factual recall, not a claim of general intelligence.

### 2. Chat streaming does not provide genuine early answer tokens

Evidence: `backend/app/orchestrator.py:619–665` emits answer tokens after generation completes.

Recommended deliverable: propagate provider chunks as they arrive, with bounded buffering, cancellation, and explicit partial-response handling. Measure time to first token separately from total response time. Preserve approval gates and do not claim a cancelled browser request necessarily stops provider inference.

### 3. MCP needs an explicit permission boundary

Evidence: `backend/app/hermes.py:834–887` provides a tool runtime, but no application MCP connection manager was found in the inspected implementation. Existing Python plugins execute in-process during import (`backend/app/hermes.py:1063–1114`); they are not sandboxed.

Recommended deliverable: disabled-by-default server connections, tool discovery, per-tool enablement, argument validation, secret references, timeouts, audit history, and approval enforcement on every execution path. Do not automatically trust a server's declared read-only status or install every available plugin.

The supplied ChatGPT catalog was fetched successfully. It demonstrates a connector-catalog experience, not evidence that its integrations can all be imported into AURA or used free of charge. Each provider requires separate compatibility, authorization, licensing, and quota verification.

### 4. Extend existing web tools rather than duplicate them

Evidence: `backend/app/browse.py:97–138` implements page reading; `backend/app/browse.py:141–247` implements search.

Recommended deliverable: bounded multi-source research with source URLs, retrieved dates, evidence-linked answers, caching, and honest unavailable states. Treat page content as untrusted data. Strengthen response-size and destination checks before increasing browsing volume.

### 5. Entertainment should start with user-controlled playback

No dedicated entertainment player or playlist subsystem was found in the inspected application.

Recommended deliverable: user-selected local audio/video, queue management, play/pause/seek, volume, supported-format errors, and permitted public stream URLs. Add provider adapters only after verifying terms and actual playback rights. Free search or metadata does not imply free full-track streaming.

### 6. Sounds need shared playback and lifecycle controls

Evidence: `frontend/src/alerts.ts:20–82` already implements an opt-in chime and quiet-hours behavior. The dashboard already has a time-based greeting.

Recommended deliverable: a shared audio controller for media, speech, and short sound effects; volume/mute/quiet hours; a user-activated welcome; and explicit End session cleanup. Browser autoplay restrictions apply. Tab closure cannot reliably finish a shutdown sound or stop the operating system/backend.

### 7. Improve existing camera/vision workflows

Evidence: `frontend/src/views2.tsx:797–878`, `backend/app/main.py:467–487`, and `backend/app/vision.py:46–116` already cover camera snapshots, image analysis, and optional persistence.

Recommended deliverable: verify the configured model actually supports vision, default capture persistence to explicit consent, validate image dimensions/decoding, and test permission rejection and late camera-start cleanup. Snapshot analysis is not continuous video understanding. No face-identification subsystem is proposed.

## Verification evidence and limits

Previous enhancement round, before this request:
- Backend suite: 291 tests ran, 2 skipped.
- Frontend suite: 161 tests passed; TypeScript and production build passed.
- Router evaluation: 299/299; agent evaluation: 33/33.
- Eight isolated Chromium checks passed using intercepted API fixtures; these were not live third-party integration tests.
- Main JavaScript chunk: about 259 kB, with additional lazy-loaded chunks.
- Local Ollama replied successfully; Kokoro produced valid WAV output. Warm Kokoro synthesis took about 49 seconds under concurrent load, so real-time voice performance has not been achieved.

Current request:
- Source inventory and official MCP architecture documentation inspected.
- ChatGPT plugin catalog fetched.
- The attempted media-service probe did not run because it used the wrong interpreter path. Neither candidate service was verified.
- No new implementation, performance benchmark, or end-to-end claim is made.

## Decision

Proceed with the older-memory retrieval regression as the next single implementation deliverable. Complete its failing test, minimal fix, and isolated verification before expanding into MCP or media subsystems. Retain the existing single-user SQLite architecture. Do not promise master-level intelligence, all-free integrations, or error-free operation.
