# AURA OS — User Guide

AURA is a local-first AI sidekick: chat with it, and it remembers, plans, and
acts across work, clients, projects, and personal life. Everything lives in
one SQLite database on your machine.

## The 60-second tour

1. **Center**: the Aura Orb pulses with what AURA is doing (idle, thinking,
   retrieving, working, waiting for your approval…).
2. **Bottom**: the composer — type, speak (mic), or attach files.
3. **Top**: command bar — `⌨️ Ctrl/⌘+K` anywhere opens the command palette:
   search everything, jump to views, resume recent conversations.
4. **Right**: live widgets — today's priorities, projects, gateway, insights.
5. **Bell (top bar)**: notifications; click to mark read.

## Talking to AURA

- Just ask — see [CHAT_COMMANDS.md](CHAT_COMMANDS.md) for everything it
  understands, e.g. `plan my day`, `draft follow-ups`, `log mood 8/10`.
- While it works you'll see the **plan stepper** (each step + tool call) and
  **memory citations** behind the answer.
- **Voice**: tap the mic, speak, and AURA transcribes, acts, and can read the
  answer back. Voice runs in your browser (Web Speech API, English-Kenya);
  transcripts are synced to memory. No audio ever leaves your machine except
  to your browser's own speech engine.
- **Files**: attach resumes, notes, CSVs — text is extracted, indexed into
  memory, and included in that turn's reasoning.

## Approvals (nothing sends itself)

Anything externally visible (follow-up messages, gateway sends) pauses at an
**approval card**: review each draft, **Edit** the wording inline, then
**Approve & Send** or **Reject**. Edited text is what gets sent, and both the
original and the sent version are kept for audit. Pending approvals also live
under Activity.

## Workspaces (left sidebar)

| View | What you do there |
|---|---|
| Home | Orb, command bar, domain panels, insights, today's priorities |
| Career & Work | Resume analyzer (ATS score + JD gaps + versions), applications pipeline, interview practice log, today's time-blocks |
| Clients & Projects | Project tracker + milestones, client directory, **Backup Manager** |
| Personal Life | Journal, mood trends, expenses, goals, habit streaks, **sleep log** |
| Memory Center | Browse/edit/delete every memory, sensitivity flags, per-domain stats, topic forget, export |
| Voice & Audio | Mic controls, STT/TTS config, transcript history |
| Multi-Platform | Connect/test/disconnect Telegram, Discord, Slack, WhatsApp, Email; simulate inbound messages; event bus log |
| Automations | Create scheduled/event/manual automations (notify, backup, brief, **webhook**), run-now, history, success rates |
| Inbox | Email accounts (sandbox sample or live IMAP), triage tabs, reader |
| Calendar | Week agenda, event composer, local/CalDAV/Google connections |
| Activity | Everything AURA did: runs, tools, approvals, integrations — filterable |
| Files | Uploaded files: preview, download, indexed-text search |
| Settings | Profile, voice & privacy preferences, system info, multi-device sync |

## Automations

Create one in the Automation Center: a **trigger** (schedule, event, manual)
plus an **action** (send yourself a notification, run a backup, generate a
brief, or **POST to a webhook**). The scheduler ticks every 30 seconds and fires whatever is due;
**Run now** forces immediate execution. Each automation tracks runs, successes
and failures so you can see reliability at a glance. Good starters: a 7 AM
morning brief, a nightly backup, a Friday client-review nudge.
**Webhooks**: pick the `webhook` action, paste a URL (n8n, Zapier, your own
server) and an optional signing secret. Each fire POSTs
`{event, automation_id, automation_name, fired_at, data}` with an
`X-Aura-Signature: sha256=…` HMAC header; failures retry with exponential
backoff (5 min → 2 h). Manual/event automations fire once per Run.

## Mail, calendar & briefings

**Inbox** connects email two ways: a built-in sandbox account with a sample
inbox (sync it and triage away — nothing leaves your machine) or live IMAP
accounts with your own host/username/password. Triage sorts unread into
action/waiting/fyi/done; open any message in the reader. **Calendar** starts
local-first (add events, see today/week), and can also pull from CalDAV
servers or Google (connect → open the auth URL → paste the code).
**Briefings** are saved morning/evening/custom prompts you run on demand or on
a schedule (see Automations). Chat shortcuts: `check my email`,
`what's on today`, `schedule lunch Friday 1pm`, `brief me`.
**Multi-device sync**: Settings → Data names your device and downloads an
`aura-sync/1` bundle; import it on another device to merge (local data always
wins conflicts; history in the sync log).

## Gateway (multi-platform)

Connect any of the five platforms to mark it online, **Test** the connection,
and **Simulate** an inbound message to watch it flow through the event bus.

Each platform has two modes: **sandbox** (default — sends are recorded in the
audit trail, zero network calls) and **live** (real delivery). To go live,
open the platform's **Configure** panel, paste credentials (Telegram bot
token, SMTP login, Discord/Slack webhook… — see OPERATIONS for the full
table), switch to live, Save, then Test. Approving a follow-up in live mode
really sends it; failures come back as explicit errors, never silence. If a
platform isn't connected, sends fail fast with "connect it first" instead of
pretending.

## Sleep, language & push

- **Sleep**: chat `slept 11pm to 6am` (or `log sleep 7.5 hours`), or use
  Personal → Sleep panel (`7.5` or `23:00-06:30`). The dashboard insight
  shows your last night with a Good/Okay/Low state.
- **Language**: Settings → Language switches English ↔ Kiswahili instantly
  (nav, titles, palette, greetings). Browsers set to Swahili default to it.
- **Install as app + push**: Chrome/Edge → Install AURA, then Settings →
  Push Notifications → Enable. Automation notifications arrive even with
  the tab closed. Needs HTTPS (or localhost) + server VAPID keys (SETUP).
- **Server voice**: if the backend has voice deps installed, Voice view
  gains Server STT (record/upload → transcript → send to chat) and Server
  TTS (any text → spoken audio). First use downloads models (~2 min).
- **Voice variety**: Settings → Voice offers three engines (Browser, Piper,
  Edge Neural with Kenyan + Kiswahili voices), 6 emotions, rate/pitch, and
  smart pauses. Edge Neural is the most human; it needs Hybrid/Cloud
  privacy. Test voice previews your pick.
- **Files**: PDF, Word, Excel and PowerPoint uploads are parsed and
  searchable (Memory search finds their contents). Images record metadata.

## Backups & restores

**Clients → Backup Manager**: one click snapshots the database plus all
uploads into a `data/backups/aura-backup-<time>.tar.gz` with a SHA-256 note.
**Restore** verifies integrity first, safety-copies your current data
(`.pre-restore-*.db`), then swaps the database back and reloads. Tip: add a
nightly-backup automation and keep the newest few archives somewhere safe.

## Memory & privacy

- AURA remembers facts, files, preferences, and conversation outcomes —
  always shown as citations, never silently.
- Open Memory Center to correct or delete anything; deleting is a soft-delete
  you can audit, and **Forget topic** wipes a subject entirely.
- Local-first: SQLite + files on your disk, no account, no telemetry, no
  cloud calls unless you wire them. Pointing AURA at Ollama keeps even the
  neural layer on your machine.

## Conversations & history

Every chat auto-titles from your first message and persists with its plan
traces. Reopen any of the last 30 from the palette's **Recent conversations**,
or start fresh with the composer's **New** button.

## Keyboard

| Keys | Action |
|---|---|
| `Ctrl/⌘ + K` | Command palette |
| `Enter` (composer) | Send |
| `Shift + Enter` | New line |
| `Tab / Enter` on rows | Navigate & open (all rows are keyboard-accessible) |
