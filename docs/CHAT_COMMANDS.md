# AURA OS — Chat Command Reference

AURA routes every message to one **intent** (first rule that matches wins),
runs a tool plan, and streams the answer. Phrases below are examples — wording
is flexible. Anything unmatched falls back to `general_ask` (memory-grounded
answer).

## Tasks

| Say | Intent | What happens |
|---|---|---|
| `remind me to call Brian` | `task_create` | Creates task, echoes the title back |
| `add task prepare slides for Friday` | `task_create` | Priority/status words are normalized |
| `show my tasks` / `what's due` | `task_list` | Open tasks, overdue first |
| `done with Morning workout` | `task_toggle` | Marks the matching task completed |
| `mark "Q3 report" as in progress` | `task_toggle` | Exact title in quotes = exact match |
| `complete task 6` | `task_toggle` | Numeric IDs resolve directly |

## Clients & projects

| Say | Intent | What happens |
|---|---|---|
| `new project NORERN Phase 2` | `project_create` | Creates project, opens tracker hint |
| `new client Acme Ltd` | `client_create` | Creates client record |
| `how are my projects doing` | `project_status` | Progress, deadlines, at-risk flags |
| `review my clients` | `client_review` | Workload review + who needs attention |
| `draft follow-ups` | `followup_draft` | Drafts for overdue items → **approval card** |
| `prepare a meeting brief for Brian` | `meeting_prep` | Memories + open tasks about them |

> Approvals are never skipped: nothing is sent until you Approve (optionally
> after editing). Approving with zero drafts is impossible — empty plans short-circuit.

## Career

| Say | Intent | What happens |
|---|---|---|
| `resume tips for ATS` / `help with my cv` | `resume_help` | Guides you to the analyzer + rewrite loop |
| `interview prep for nurse role` | `interview_prep` | 6 role-aware questions (`for X role`, `as a Y`) |
| `mock interview` | `interview_prep` | Same bank, practice framing |

## Personal

| Say | Intent | What happens |
|---|---|---|
| `log mood 8/10` / `i feel great` | `health_log` | Mood journaled; numeric scores drive the trend |
| `log workout 5k run` | `health_log` | Workout entry |
| `slept 11pm to 6am` / `log sleep 7.5 hours` / `track my sleep` | `sleep_log` | Night logged (overnight-aware); dashboard insight updates |
| `journal today was a win because…` | `journal` | Free-form journal entry |
| `add expense 500 lunch` | `finance` | Expense logged (amount + category) |
| `how is my spending` | `finance` | Totals + month-over-month momentum |

## Memories

| Say | Intent | What happens |
|---|---|---|
| `remember that the gate code is 4402` | `memory_store` | Stored (also: `note that…`, `don't forget…`, `save this`) |
| `what do you remember about NORERN` | `memory_search` | Hybrid FTS5 + vector recall with citations |
| `forget the gate code` | `memory_search` | Finds it; permanent erase via Memory Center or `POST /memories/forget` |

## Day planning

| Say | Intent | What happens |
|---|---|---|
| `plan my day` / `morning brief` | `plan_day` | Overdue-first priorities + AI time-blocks today |

## Mail, calendar & briefings

| Say | Intent | What happens |
|---|---|---|
| `brief me` / `evening briefing` | `briefing` | Runs a briefing through the cloud chain |
| `check my email` / `triage my inbox` | `email_check` | Unread summary + triage state |
| `what's on today` / `my schedule` | `calendar_today` | Today's agenda |
| `schedule lunch Friday 1pm` | `calendar_create` | Parses day/time, creates the event |

## Search & missions

| Say | Intent | What happens |
|---|---|---|
| `search the web for Nairobi weather` | `web_search` | Keyless DuckDuckGo search — titled links + snippets (honest off-state if unreachable) |
| `look up best laptops online` / `google it` | `web_search` | Same search tool, memory-grounded |
| `read https://example.com/article` | `web_read` | Fetches the page (SSRF-guarded) and grounds the reply |
| `make a mission to plan my day` | *(mission API)* | Plans a tool chain; open Automations → Missions to review/start |
| `how are my missions going` | `mission_status` | Streams each mission's step progress live into chat |

## System & ops

| Say | Intent | What happens |
|---|---|---|
| `run a backup` / `take a backup` | `backup_run` | Snapshot + uploads archive + SHA-256 |
| `gateway status` | `gateway` | Per-platform connection state |
| `system status` / `are you healthy` | `system_status` | All 8 services + runs/tools metrics |
| `show my automations` | `automation` | Automations + success rates |
| `schedule a morning brief` | `automation` | Points to the Automation Center |
| `hello` / `habari` | `greet` | Greeting (EN + Swahili) |
| `what can you do` / `help` | `help` | Capability summary |
| `read that back` / `say it` | `voice_note` | Voice-mode hint (mic + TTS playback) |

## Tips

- **Be specific with titles**: `done with report` matches any task containing
  "report" — use quotes for exact titles.
- **Conversation memory**: follow-ups in the same chat reuse the last turns
  (`and make it urgent` after creating a task works when Ollama is on; the
  builtin engine answers each turn from fresh retrieval).
- **History**: every chat auto-titles and persists — reopen it from Ctrl/⌘+K →
  Recent conversations.
- **Attachments**: paperclip anything — text files are indexed into memory and
  included in the turn.
