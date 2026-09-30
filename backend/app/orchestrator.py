"""AURA Orchestration Layer.

Per-turn pipeline:
  intent -> context assembly (memory + entities + session) -> plan ->
  Hermes tool execution -> approval gate (R2/R3) -> generation ->
  persistence + memory policy + observability.

Exposes run_turn() as an SSE event generator consumed by /api/chat/stream.
Event types: orb, plan, step, tool, approval, token, result, memory, error, done.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Iterator

from . import db, config
from .hermes import hermes
from .inference import router as model_router, filter_cloud_memories, scrub_secrets
from . import prefs as _prefs
from .memory import memory_engine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------- intents ---
INTENT_RULES: list[tuple[str, str, str]] = [
    # (intent, domain, regex)
    (
        "feed_follow",
        "general",
        r"\bfollow\b.{0,24}\b(feed|rss)\b|\badd\b.{0,20}\bfeed\b.{0,60}https?://",
    ),
    ("web_read", "general", r"https?://\S+"),
    (
        "web_search",
        "general",
        r"\b(search|google|look ?up|find|query)\b.{0,40}\b(web|online|internet)\b|\b(web search|search the web|google it)\b",
    ),
    (
        "terminal_run",
        "general",
        r"\b(run|execute|exec)\b.{0,26}\b(command|terminal|shell|script)\b|\b(in|from|on)\s+(my|the)\s+(terminal|shell|command line)\b|\b(terminal|script)\s*[:>]|\bssh\b|\bmy machines?\b.{0,20}\b(ssh|run|connect|status)\b|\b(run|execute)\b.{0,30}\bon (my|the) machines?\b",
    ),
    (
        "ollama_switch",
        "general",
        r"\b(switch|change|set|point)\b.{0,30}\b(model|ollama)\b|\buse (the )?model\b|\b(switch|point|move)\b.{0,18}\b(llama[\w.]*|qwen[\w.]*|gemma[\w.]*|mistral[\w.]*|deepseek[\w.-]*|phi[\d.]*|command-r\d?|llava[\w.]*|minicpm[\w.-]*|hermes\d?)\b",
    ),
    (
        "ollama_models",
        "general",
        r"\b(ollama|local (llms?|models?|llm)|model room)\b|\b(which|what) models?\b|\blist (my |the )?models?\b",
    ),
    (
        "feeds_latest",
        "general",
        r"\b(my feeds?|rss|news digest|feed items?|what'?s new on)\b",
    ),
    (
        "weather",
        "general",
        r"\b(weather|forecast|temperature|raining|rain today|umbrella|how (hot|cold|warm))\b",
    ),
    (
        "mission_status",
        "general",
        r"\b(status|progress|how|update|running|doing|check)\b.{0,30}\b(missions?)\b|\b(missions?)\b.{0,30}\b(status|progress|going|update|running|doing)\b|\bmission status\b|\bhow'?s my mission\b",
    ),
    ("undo", "general", r"\bundo\b"),
    (
        "greet",
        "general",
        r"^(hi|hey|hello|good (morning|afternoon|evening)|habari|mambo)\b",
    ),
    ("help", "general", r"\b(help|what can you do|commands|capabilities)\b"),
    (
        "plan_day",
        "general",
        r"\b(plan my day|today'?s plan|prioritiz(e|ing)?|prioritis(e|ing)?|my day|morning brief|daily brief|need(ing|s)? (my |our )?attention|any risks?|what.*risks?)\b",
    ),
    (
        "calendar_today",
        "general",
        r"\b(my schedule|today'?s schedule|meetings today|today'?s meetings|any meetings?|my agenda|on my calendar|what meetings)\b",
    ),
    (
        "email_check",
        "general",
        r"\b(check|read|triage|scan|show)\b.{0,20}\b(email|mail|inbox)\b|\b(unread|new)\b.{0,10}\b(mails?|emails?|messages?|inbox)\b|\binbox\b|\btriage\b",
    ),
    (
        "followup_draft",
        "clients",
        r"\b(draft|write|prepare|send).{0,30}(follow.?ups?|followups?|emails?|messages?)\b",
    ),
    ("project_create", "clients", r"\b(new|create|start)\b.{0,20}\bproject\b"),
    ("client_create", "clients", r"\b(new|add|create)\b.{0,20}\bclient\b"),
    (
        "client_review",
        "clients",
        r"\b(review|workload|clients?|overdue|follow.?up|status report)\b.*\b(clients?|projects?|work|overdue|follow)\b|\b(review my|my clients|client workload)\b",
    ),
    (
        "task_toggle",
        "general",
        r"\bmark\b.{0,80}\b(completed|complete|done|in progress|in_progress)\b|\b(complete|finish)\b.{0,20}\btask\b|\bdone with\b",
    ),
    (
        "task_create",
        "general",
        r"\b(create|add|new)\b.{0,20}\b(task|todo|to-?do|reminder)\b|\bremind me\b|\btask\b.{0,10}(to|for|:)|^todo[: ]",
    ),
    (
        "task_list",
        "general",
        r"\b(list|show|my|all|open|pending)\b.{0,25}\b(tasks|todos|to-?dos)\b|\bwhat('?s| is) (on|next|due)\b",
    ),
    ("project_status", "clients", r"\b(projects?|milestones?|deadlines?|progress)\b"),
    (
        "memory_store",
        "general",
        r"\bremember that\b|\bnote that\b|\bdon'?t forget\b|\bsave this\b|\bkeep in mind\b",
    ),
    (
        "memory_search",
        "general",
        r"\b(remember|recall|memory|memories|what do you know|forget)\b",
    ),
    (
        "resume_help",
        "career",
        r"\b(resume|cv|ats|cover letter|job description|application)\b",
    ),
    (
        "interview_prep",
        "career",
        r"\b(interview|mock interview|question bank)\b|\bpractice\b.{0,20}\binterview\b",
    ),
    (
        "sleep_log",
        "personal",
        r"\bslept\b|\bsleep\b.{0,24}\d|\b(log|track)(\s+my)?\s+sleep\b|\bsleep\s+(log|last night)\b",
    ),
    (
        "health_log",
        "personal",
        r"\b(log|track).{0,20}(mood|health|workout|sleep|weight|water)\b|\bmood\b.{0,10}\d|\bi feel\b",
    ),
    ("journal", "personal", r"\bjournal\b|\bdear diary\b|\breflect"),
    (
        "finance",
        "personal",
        r"\b(expense|spending|spen[dt]|budget|finance|money|cost|kes\b|paid)\b",
    ),
    (
        "backup_run",
        "general",
        r"\b(run|take|start|trigger|make|do)\b.{0,12}\bbackups?\b|\bbackup now\b|^backups?\s*$",
    ),
    (
        "gateway",
        "general",
        r"\b(telegram|discord|slack|whatsapp|email|gateway|integration|connect)\b",
    ),
    (
        "system_status",
        "general",
        r"^(?!.*\b(cron|automat\w*|schedul\w*|recurring)\b).*\b(system|health|status|diagnostics?|services|backup)\b|\b(are you|is the system)\b.{0,12}\b(healthy|ok|okay|online)\b",
    ),
    (
        "calendar_create",
        "general",
        r"\b(schedule|book|set ?up)\b.{0,30}\b(meeting|call|appointment|event|lunch)\b|\b(add|create)\b.{0,20}\b(meeting|appointment|event|lunch|call)\b|\b(schedule|book)\b.{0,30}\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}\s?(am|pm)|at \d)\b",
    ),
    ("meeting_prep", "clients", r"\b(meeting|call|prep).{0,30}(with|for|about)\b"),
    (
        "automation",
        "general",
        r"\b(automations?|automatic|schedule|cron|recurring|every (day|morning|week|hour))\b",
    ),
    (
        "briefing",
        "general",
        r"\b(brief me|briefing|evening brief|daily digest|shutdown review|weekly review|my briefing)\b",
    ),
    ("voice_note", "general", r"\b(voice|tts|say|speak|pronounce)\b"),
]

DOMAIN_HINTS = [
    ("career", r"\b(resume|cv|interview|job|career|application|ats|offer|salary)\b"),
    ("clients", r"\b(client|project|invoice|contract|deliverable|milestone)\b"),
    (
        "personal",
        r"\b(mood|health|journal|family|workout|sleep|expense|budget|goal|habit|meditat(e|ion)?)\b",
    ),
]


def classify(text: str) -> tuple[str, str]:
    low = text.lower()
    for intent, domain, pat in INTENT_RULES:
        if re.search(pat, low):
            return intent, domain
    for domain, pat in DOMAIN_HINTS:
        if re.search(pat, low):
            return "general_ask", domain
    return "general_ask", "general"


def detect_domain(text: str, fallback: str) -> str:
    low = text.lower()
    for domain, pat in DOMAIN_HINTS:
        if re.search(pat, low):
            return domain
    return fallback


def _terminal_cmd(text: str) -> str:
    """Pull the actual command out of chat text ('run `git status` in terminal')."""
    from .terminal import parse_inline

    return (parse_inline(text) or text.strip())[:900]


# -------------------------------------------------------------- plans ---
def build_plan(intent: str, text: str) -> list[dict]:
    P = [
        ("greet", []),
        ("help", []),
        (
            "undo",
            [
                {
                    "id": "s1",
                    "label": "Undo last change",
                    "tool": "system.undo",
                    "args": {},
                }
            ],
        ),
        (
            "web_read",
            [
                {
                    "id": "s1",
                    "label": "Fetch & read page",
                    "tool": "__fetch_urls_from_text__",
                    "args": {"text": text},
                },
                {
                    "id": "s2",
                    "label": "Retrieve related memories",
                    "tool": "memory.search",
                    "args": {"query": text[:200], "limit": 3},
                },
            ],
        ),
        (
            "web_search",
            [
                {
                    "id": "s1",
                    "label": "Search the web",
                    "tool": "web.search",
                    "args": {"query": text[:300]},
                },
                {
                    "id": "s2",
                    "label": "Retrieve related memories",
                    "tool": "memory.search",
                    "args": {"query": text[:200], "limit": 3},
                },
            ],
        ),
        (
            "terminal_run",
            [
                {
                    "id": "s1",
                    "label": "Run command (or saved script)",
                    "tool": "__terminal_or_script__",
                    "args": {"text": text},
                },
            ],
        ),
        (
            "ollama_models",
            [
                {
                    "id": "s1",
                    "label": "Sync + list local models",
                    "tool": "ollama.models",
                    "args": {"refresh": True},
                },
            ],
        ),
        (
            "ollama_switch",
            [
                {
                    "id": "s1",
                    "label": "Point AURA at the model",
                    "tool": "__set_ollama_model__",
                    "args": {"text": text},
                },
            ],
        ),
        (
            "feed_follow",
            [
                {
                    "id": "s1",
                    "label": "Follow the feed",
                    "tool": "__feed_follow__",
                    "args": {"text": text},
                },
            ],
        ),
        (
            "feeds_latest",
            [
                {
                    "id": "s1",
                    "label": "Fetch latest feed items",
                    "tool": "feeds.latest",
                    "args": {"limit": 8},
                },
            ],
        ),
        (
            "weather",
            [
                {
                    "id": "s1",
                    "label": "Read the sky (Open-Meteo)",
                    "tool": "weather.now",
                    "args": {},
                },
            ],
        ),
        (
            "plan_day",
            [
                {
                    "id": "s1",
                    "label": "Retrieve open tasks",
                    "tool": "tasks.list",
                    "args": {"status": "inbox"},
                },
                {
                    "id": "s2",
                    "label": "Find overdue items",
                    "tool": "tasks.overdue",
                    "args": {},
                },
                {
                    "id": "s3",
                    "label": "Check today's time blocks",
                    "tool": "schedule.blocks",
                    "args": {},
                },
                {
                    "id": "s4",
                    "label": "Retrieve relevant memories",
                    "tool": "memory.search",
                    "args": {"query": text[:200], "limit": 4},
                },
                {
                    "id": "s5",
                    "label": "Scan for opportunities",
                    "tool": "proactive.scan",
                    "args": {"limit": 3},
                },
            ],
        ),
        (
            "client_review",
            [
                {
                    "id": "s1",
                    "label": "Load clients & projects",
                    "tool": "projects.list",
                    "args": {},
                },
                {
                    "id": "s2",
                    "label": "Find overdue items",
                    "tool": "tasks.overdue",
                    "args": {},
                },
                {
                    "id": "s3",
                    "label": "Retrieve client memories",
                    "tool": "memory.search",
                    "args": {"query": text[:200], "limit": 4},
                },
            ],
        ),
        (
            "followup_draft",
            [
                {
                    "id": "s1",
                    "label": "Find overdue items",
                    "tool": "tasks.overdue",
                    "args": {},
                },
                {
                    "id": "s2",
                    "label": "Draft follow-up messages",
                    "tool": "comms.draft_followups",
                    "args": {},
                },
                {
                    "id": "s3",
                    "label": "Request approval to send",
                    "tool": "__approval__",
                    "args": {},
                },
            ],
        ),
        (
            "task_create",
            [
                {
                    "id": "s1",
                    "label": "Create task",
                    "tool": "__create_task_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "task_toggle",
            [
                {
                    "id": "s1",
                    "label": "Find & update task",
                    "tool": "__toggle_task_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "task_list",
            [{"id": "s1", "label": "List tasks", "tool": "tasks.list", "args": {}}],
        ),
        (
            "project_status",
            [
                {
                    "id": "s1",
                    "label": "Load projects",
                    "tool": "projects.list",
                    "args": {},
                },
                {
                    "id": "s2",
                    "label": "Check overdue tasks",
                    "tool": "tasks.overdue",
                    "args": {},
                },
            ],
        ),
        (
            "project_create",
            [
                {
                    "id": "s1",
                    "label": "Create project",
                    "tool": "__create_project_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "client_create",
            [
                {
                    "id": "s1",
                    "label": "Create client",
                    "tool": "__create_client_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "memory_search",
            [
                {
                    "id": "s1",
                    "label": "Hybrid memory search (FTS + vector)",
                    "tool": "memory.search",
                    "args": {"query": text[:300], "limit": 6},
                }
            ],
        ),
        (
            "memory_store",
            [
                {
                    "id": "s1",
                    "label": "Store memory",
                    "tool": "__store_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "resume_help",
            [
                {
                    "id": "s1",
                    "label": "Load resume versions",
                    "tool": "__load_resumes__",
                    "args": {},
                },
                {
                    "id": "s2",
                    "label": "Retrieve career context",
                    "tool": "memory.search",
                    "args": {"query": "resume career job " + text[:150], "limit": 4},
                },
            ],
        ),
        (
            "interview_prep",
            [
                {
                    "id": "s1",
                    "label": "Build question bank",
                    "tool": "career.interview_questions",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "sleep_log",
            [
                {
                    "id": "s1",
                    "label": "Log sleep",
                    "tool": "__log_sleep_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "health_log",
            [
                {
                    "id": "s1",
                    "label": "Log wellbeing",
                    "tool": "__log_health_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "journal",
            [
                {
                    "id": "s1",
                    "label": "Save journal entry",
                    "tool": "__journal_from_text__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "finance",
            [
                {
                    "id": "s1",
                    "label": "Record / review spending",
                    "tool": "__finance_from_text__",
                    "args": {"text": text},
                },
                {
                    "id": "s2",
                    "label": "Load expenses",
                    "tool": "__load_expenses__",
                    "args": {},
                },
            ],
        ),
        (
            "system_status",
            [
                {
                    "id": "s1",
                    "label": "Probe services",
                    "tool": "system.status",
                    "args": {},
                }
            ],
        ),
        (
            "backup_run",
            [
                {
                    "id": "s1",
                    "label": "Run backup",
                    "tool": "system.backup",
                    "args": {"target": "local"},
                }
            ],
        ),
        (
            "meeting_prep",
            [
                {
                    "id": "s1",
                    "label": "Assemble meeting brief",
                    "tool": "__meeting_prep__",
                    "args": {"text": text},
                }
            ],
        ),
        (
            "automation",
            [
                {
                    "id": "s1",
                    "label": "Review automations",
                    "tool": "__load_automations__",
                    "args": {},
                }
            ],
        ),
        (
            "gateway",
            [
                {
                    "id": "s1",
                    "label": "Check gateway status",
                    "tool": "system.status",
                    "args": {},
                }
            ],
        ),
        (
            "email_check",
            [
                {"id": "s1", "label": "Sync inbox", "tool": "email.sync", "args": {}},
                {
                    "id": "s2",
                    "label": "Triage unread",
                    "tool": "email.triage",
                    "args": {},
                },
                {
                    "id": "s3",
                    "label": "Summarize unread",
                    "tool": "email.unread",
                    "args": {"limit": 5},
                },
            ],
        ),
        (
            "calendar_today",
            [
                {
                    "id": "s1",
                    "label": "Load today's events",
                    "tool": "calendar.today",
                    "args": {},
                },
            ],
        ),
        (
            "calendar_create",
            [
                {
                    "id": "s1",
                    "label": "Create event",
                    "tool": "__create_event_from_text__",
                    "args": {"text": text},
                },
            ],
        ),
        (
            "briefing",
            [
                {
                    "id": "s1",
                    "label": "Generate briefing",
                    "tool": "briefing.now",
                    "args": {
                        "kind": (
                            "evening"
                            if "evening" in text.lower() or "shutdown" in text.lower()
                            else "weekly"
                            if "week" in text.lower()
                            else "morning"
                        )
                    },
                },
            ],
        ),
        (
            "mission_status",
            [
                {
                    "id": "s1",
                    "label": "Load missions & progress",
                    "tool": "__load_missions__",
                    "args": {},
                },
                {
                    "id": "s2",
                    "label": "Retrieve related memories",
                    "tool": "memory.search",
                    "args": {"query": text[:200], "limit": 3},
                },
            ],
        ),
    ]
    for name, steps in P:
        if name == intent:
            return [dict(s, status="pending") for s in steps]
    return [
        {
            "id": "s1",
            "label": "Retrieve relevant memories",
            "tool": "memory.search",
            "args": {"query": text[:300], "limit": 4},
            "status": "pending",
        },
        {
            "id": "s2",
            "label": "Look up related records",
            "tool": "__general_lookup__",
            "args": {"text": text},
            "status": "pending",
        },
    ]


# ------------------------------------------- pseudo-tool implementations ---
def _extract_title(text: str, keywords: list[str]) -> str:
    low = text.lower()
    for kw in keywords:
        i = low.find(kw)
        if i != -1:
            frag = text[i + len(kw) :].strip(" :–-")
            frag = re.split(
                r"\b(due|by|tomorrow|today|priority|high|low|urgent)\b", frag, 1
            )[0].strip(" .")
            if frag:
                return frag[:140]
    cleaned = re.sub(
        r"^(please\s+)?(create|add|new)\s+(a\s+)?(task|project|client|todo|to-?do|reminder)\s*(:|to|for|called|named)?\s*",
        "",
        text,
        flags=re.I,
    ).strip()
    return cleaned[:140] or text[:140]


def _extract_priority(text: str) -> str:
    low = text.lower()
    if "urgent" in low:
        return "urgent"
    if "high priority" in low or "important" in low:
        return "high"
    if "low priority" in low or "whenever" in low:
        return "low"
    return "medium"


def exec_pseudo(name: str, args: dict, ctx: dict, run_id: int) -> Any:
    text = args.get("text", "")
    if name == "__fetch_urls_from_text__":
        from .browse import extract_urls, fetch

        pages = [fetch(u) for u in extract_urls(text)]
        return {"pages": pages} if pages else {"pages": [], "error": "no URL found"}
    if name == "__create_task_from_text__":
        title = _extract_title(
            text, ["remind me to", "remind me", "task to", "todo:", "todo", "to do"]
        )
        return hermes.execute_tool(
            "tasks.create",
            {
                "title": title or text[:120],
                "priority": _extract_priority(text),
                "domain": ctx.get("domain", "general"),
            },
            ctx,
            run_id,
        )["data"]
    if name == "__create_event_from_text__":
        from .calendar_sync import (
            ensure_default_calendar,
            event_title_from_text,
            parse_event_time,
        )

        span = parse_event_time(text)
        if not span:
            return {
                "created": False,
                "error": "no time found — try 'tomorrow 2pm' or 'friday 10am'",
            }
        s_iso, e_iso = span
        title = event_title_from_text(text)
        return {
            "created": True,
            **hermes.execute_tool(
                "calendar.create",
                {
                    "calendar_id": ensure_default_calendar(),
                    "title": title,
                    "starts_at": s_iso,
                    "ends_at": e_iso,
                },
                ctx,
                run_id,
            )["data"],
            "title": title,
            "starts_at": s_iso,
        }
    if name == "__toggle_task_from_text__":
        m = re.search(r'"([^"]{3,120})"', text)
        frag = m.group(1) if m else text
        if not m:
            frag = re.sub(r"^.*?mark\s+(the\s+|my\s+)?(task\s+)?", "", frag, flags=re.I)
            frag = re.sub(
                r"^(done with|finished( with)?|complete|finish( up)?)\s+(the\s+|my\s+)?(task\s+)?",
                "",
                frag,
                flags=re.I,
            )
            frag = re.sub(
                r"\s+(as\s+)?(completed?|done|finished|in[- ]progress)\s*$",
                "",
                frag,
                flags=re.I,
            )
            frag = frag.split(" as ")[0].strip()[:120]
        to_status = "in_progress" if "in progress" in text.lower() else "completed"
        if frag and frag.strip().isdigit():
            hit = db.qone(
                "SELECT * FROM tasks WHERE user_id=1 AND id=?", (int(frag.strip()),)
            )
        else:
            hit = (
                db.qone(
                    "SELECT * FROM tasks WHERE user_id=1 AND status != 'cancelled' AND title LIKE ? ORDER BY status='completed', id DESC",
                    (f"%{frag[:60]}%",),
                )
                if frag
                else None
            )
        if not hit:
            return {"matched": False, "fragment": frag}
        hermes.execute_tool(
            "tasks.update", {"id": hit["id"], "status": to_status}, ctx, run_id
        )
        db.log_activity(
            "task",
            f"Task {to_status}: {hit['title'][:60]}",
            "via chat",
            ctx.get("domain", "general"),
            "success",
        )
        return {
            "matched": True,
            "id": hit["id"],
            "title": hit["title"],
            "status": to_status,
        }

    if name == "__create_project_from_text__":
        title = _extract_title(text, ["project called", "project named", "project"])
        return hermes.execute_tool(
            "projects.create", {"name": title or "Untitled project"}, ctx, run_id
        )["data"]
    if name == "__create_client_from_text__":
        title = _extract_title(text, ["client called", "client named", "client"])
        return hermes.execute_tool(
            "clients.create", {"name": title or "Untitled client"}, ctx, run_id
        )["data"]
    if name == "__store_from_text__":
        body = re.sub(
            r"^(please\s+)?(remember that|note that|don'?t forget( that)?|save this|keep in mind( that)?)\s*[:,]?\s*",
            "",
            text,
            flags=re.I,
        ).strip()
        r = hermes.execute_tool(
            "memory.store",
            {
                "title": body[:70],
                "content": body,
                "domain": ctx.get("domain", "general"),
            },
            ctx,
            run_id,
        )
        return r["data"]
    if name == "__load_resumes__":
        return {
            "resumes": db.q(
                "SELECT id,name,version,ats_score,created_at FROM resumes WHERE user_id=1 ORDER BY id DESC LIMIT 10"
            )
        }
    if name == "__load_expenses__":
        return {
            "expenses": db.q(
                "SELECT * FROM expenses WHERE user_id=1 ORDER BY id DESC LIMIT 60"
            )
        }
    if name == "__load_automations__":
        return {
            "automations": db.q(
                "SELECT * FROM automations WHERE user_id=1 ORDER BY id DESC LIMIT 30"
            )
        }
    if name == "__load_missions__":
        from . import missions as _ms

        rows = _ms.list_missions(10)
        for r in rows:
            r["runs"] = _ms.list_runs(r["id"], 3)
        return {"missions": rows}
    if name == "__log_health_from_text__":
        m = re.search(r"mood\s*(\d{1,2})", text.lower())
        mood = m.group(1) if m else ""
        if "workout" in text.lower():
            mood = mood or "workout"
        return hermes.execute_tool(
            "personal.log_mood", {"mood": mood, "note": text[:300]}, ctx, run_id
        )["data"]
    if name == "__log_sleep_from_text__":
        from .hermes import parse_sleep_text

        parsed = parse_sleep_text(text)
        if not parsed.get("parsed"):
            return {
                "parsed": False,
                "hint": parsed.get("hint", "what time did you sleep and wake up?"),
            }
        a = {
            k: parsed.get(k)
            for k in ("hours", "bedtime", "wake_at", "quality")
            if parsed.get(k)
        }
        return hermes.execute_tool("personal.log_sleep", a, ctx, run_id)["data"]
    if name == "__journal_from_text__":
        body = re.sub(r"^journal\s*[:,]?\s*", "", text, flags=re.I).strip()
        return hermes.execute_tool(
            "personal.journal", {"body": body or text}, ctx, run_id
        )["data"]
    if name == "__finance_from_text__":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(kes|ksh|usd|\$)?", text.lower())
        if m and (
            "expense" in text.lower()
            or "spent" in text.lower()
            or "paid" in text.lower()
            or "add" in text.lower()
        ):
            cat = "general"
            for c in (
                "food",
                "transport",
                "rent",
                "airtime",
                "data",
                "shopping",
                "health",
                "school",
                "travel",
            ):
                if c in text.lower():
                    cat = c
            hermes.execute_tool(
                "personal.add_expense",
                {
                    "category": cat,
                    "amount": float(m.group(1)),
                    "currency": (m.group(2) or "KES").upper(),
                    "note": text[:200],
                },
                ctx,
                run_id,
            )
            return {"recorded": True, "amount": float(m.group(1)), "category": cat}
        return {"recorded": False}
    if name == "__meeting_prep__":
        m = re.search(r"(?:with|for|about)\s+([A-Z][\w\s&.\-]{1,40})", text)
        who = m.group(1).strip() if m else text[:60]
        return hermes.run_skill("meeting_prep", {"who": who}, ctx, run_id)
    if name == "__general_lookup__":
        like = f"%{text[:40]}%"
        tasks = db.q(
            "SELECT * FROM tasks WHERE user_id=1 AND (title LIKE ? OR description LIKE ?) LIMIT 5",
            (like, like),
        )
        projects = db.q(
            "SELECT * FROM projects WHERE user_id=1 AND name LIKE ? LIMIT 5", (like,)
        )
        return {"tasks": tasks, "projects": projects}
    if name == "__terminal_or_script__":
        text = args.get("text", "") or ""
        from . import scripts as _sc, terminal as _t

        s, sargs = _sc.find_in_text(text)
        if s:
            return _sc.run(s["id"], source="chat", args=sargs or None)
        return _t.exec_command(_terminal_cmd(text), source="chat")
    if name == "__set_ollama_model__":
        from . import ollama_sync

        t = args.get("text", "") or ""
        role = (
            "vision"
            if re.search(r"\bvision\b", t, re.I)
            else "embed"
            if re.search(r"\bembed", t, re.I)
            else "chat"
        )
        m = re.search(
            r"(?:to|at|use|model)\s+[:=]?\s*([A-Za-z0-9._\-]+(?::[A-Za-z0-9._\-]+)?)", t
        )
        cand = (m.group(1) if m else "").strip()
        if not cand or cand.lower() in ("the", "a", "my", "model", "to"):
            return {"ok": False, "error": "which model? e.g. `switch to llama3.1`"}
        known = {x["name"] for x in ollama_sync.cached()}
        if not known:
            return {
                "ok": False,
                "error": "no synced catalog — try “list my ollama models” first so I know what's on the box",
            }
        if cand not in known and f"{cand}:latest" not in known:
            return {
                "ok": False,
                "error": f"{cand} isn't in your local catalog "
                f"({', '.join(sorted(known)[:5])}{'…' if len(known) > 5 else ''}). "
                "I only point at models Ollama actually has.",
            }
        try:
            res = ollama_sync.set_default(
                role, cand if cand in known else f"{cand}:latest"
            )
        except ValueError as e:
            raise ValueError(str(e)) from e
        return {"ok": True, **res}
    if name == "__feed_follow__":
        from . import feeds as _feeds

        m = re.search(r"https?://\S+", args.get("text", "") or "")
        if not m:
            raise ValueError(
                "give me a feed URL — e.g. follow https://hnrss.org/frontpage"
            )
        return _feeds.add(m.group(0).rstrip(".,);"))
    if name == "__approval__":
        # handled by orchestrator gate, not here
        return {"deferred": True}
    raise KeyError(f"unknown pseudo-tool {name}")


# ------------------------------------------------------------------ turn ---
def _sse(event: str, data: dict) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


def ensure_session(session_id: str | None, domain: str) -> str:
    if session_id:
        s = db.qone("SELECT id FROM sessions WHERE id=?", (session_id,))
        if s:
            db.run(
                "UPDATE sessions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (session_id,),
            )
            return session_id
    sid = uuid.uuid4().hex[:12]
    db.run(
        "INSERT INTO sessions (id, user_id, title, domain) VALUES (?,?,?,?)",
        (sid, 1, "Conversation", domain),
    )
    return sid


def _build_lfm_messages(
    user_text: str,
    hist: list[dict],
    memories: list[dict],
    grounding: str,
    summary: str = "",
) -> list[dict]:
    mem_ctx = "\n".join(f"- {m.get('title')}: {m.get('content')}" for m in memories[:5])
    sys = (
        f"You are AURA, {config.USER_NAME}'s personal AI operating system — precise, warm, "
        "and quietly capable, with a dry one-line wit you use sparingly and never instead of "
        "an answer. Answer using ONLY the grounded tool results and memories provided. Never "
        "invent tasks, projects, numbers, or people. Address him by name when it fits, "
        "remember what matters from Memories, and be concise with short markdown."
    )
    if summary:
        sys += f"\n\nEarlier in this conversation: {summary[:1200]}"
    return [
        {"role": "system", "content": sys},
        *[
            {
                "role": ("user" if h["role"] == "user" else "assistant"),
                "content": (h["content"] or "")[:800],
            }
            for h in hist
        ],
        {
            "role": "user",
            "content": f"User: {user_text}\n\nGrounded facts:\n{grounding}\n\nMemories:\n{mem_ctx or '(none)'}",
        },
    ]


def _parallel_steps_enabled() -> bool:
    try:
        return bool(_prefs.get("chat_parallel_steps"))
    except Exception:
        return True


def _is_parallel_step(step: dict) -> bool:
    from .hermes import TOOLS

    tool = step.get("tool", "")
    if tool.startswith("__"):
        return False
    t = TOOLS.get(tool)
    return bool(t and t.risk == "R0")


def _run_tool(tool: str, args: dict, ctx: dict, run_id: int) -> Any:
    r = hermes.execute_tool(tool, args, ctx, run_id)
    return r["data"] if r.get("ok") else {"error": r.get("error")}


def _harvest(
    tool: str,
    data: Any,
    tool_results: dict,
    memories: list,
    entities: dict,
) -> list[tuple[str, dict]]:
    """Fold a step's output into the turn context. Returns extra SSE events."""
    events: list[tuple[str, dict]] = []
    if isinstance(data, dict):
        if "memories" in data and isinstance(data["memories"], list):
            memories.extend(
                m
                for m in data["memories"]
                if not isinstance(m, dict) or m.get("relevance", 1) >= 0.25
            )
        for k in ("tasks", "projects", "resumes", "expenses", "automations"):
            if k in data and isinstance(data[k], list):
                entities[k].extend(data[k])
    if tool == "tasks.list" and isinstance(data, dict):
        tool_results.setdefault("open_tasks", (data.get("tasks") or [])[:10])
    if tool == "tasks.overdue" and isinstance(data, dict):
        tool_results.setdefault("overdue", data.get("overdue", []))
        tool_results.setdefault("overdue_tasks", data.get("overdue", []))
    if tool == "schedule.blocks" and isinstance(data, dict):
        tool_results.setdefault("timeblocks", data.get("blocks", []))
    if tool == "proactive.scan" and isinstance(data, dict):
        tool_results.setdefault("opportunities", data.get("opportunities", []))
    if tool == "projects.list" and isinstance(data, dict):
        tool_results.setdefault("projects", data.get("projects", []))
        tool_results.setdefault(
            "clients", db.q("SELECT * FROM clients WHERE user_id=1 LIMIT 50")
        )
    if tool == "comms.draft_followups" and isinstance(data, dict):
        tool_results.setdefault("drafts", data.get("drafts", []))
    if tool == "system.status" and isinstance(data, dict):
        tool_results.setdefault("services", (data.get("services") or []))
    if tool == "web.search" and isinstance(data, dict):
        tool_results.setdefault("search_results", (data.get("results") or []))
        tool_results.setdefault("search_error", data.get("error", ""))
    if tool == "__load_missions__" and isinstance(data, dict):
        for _m in (data.get("missions") or [])[:10]:
            events.append(
                (
                    "mission",
                    {
                        "id": _m.get("id"),
                        "goal": (_m.get("goal") or "")[:140],
                        "status": _m.get("status"),
                        "step_idx": _m.get("step_idx", 0),
                        "steps": [
                            {k: s.get(k) for k in ("label", "status", "note")}
                            for s in (_m.get("steps") or [])
                        ][:8],
                    },
                )
            )
        tool_results.setdefault("missions", data.get("missions") or [])
    if tool == "__create_task_from_text__" and isinstance(data, dict):
        tool_results.setdefault("tasks_created", []).append(data)
    if tool == "memory.search" and isinstance(data, list):
        # memory.search returns list of memories directly
        memories.extend(
            m for m in data if isinstance(m, dict) and m.get("relevance", 1) >= 0.25
        )
    elif (
        tool == "memory.search"
        and isinstance(data, dict)
        and "data" in data
        and isinstance(data["data"], list)
    ):
        # memory.search returns {"ok": true, "data": [...memories...]}
        memories.extend(
            m
            for m in data["data"]
            if isinstance(m, dict) and m.get("relevance", 1) >= 0.25
        )
    try:
        from . import facts as _facts

        _stored = _facts.harvest(tool, data)
        if _stored:
            events.append(
                (
                    "facts",
                    {
                        "stored": [
                            {"id": s.get("id"), "title": s.get("title")}
                            for s in _stored
                        ]
                    },
                )
            )
    except Exception:
        pass
    return events


def run_turn(
    user_text: str,
    session_id: str | None = None,
    domain_hint: str | None = None,
    attachments: list[dict] | None = None,
) -> Iterator[str]:
    t0 = time.time()
    trace_id = uuid.uuid4().hex[:12]
    intent, domain = classify(user_text)
    if domain_hint:
        domain = domain_hint
    else:
        domain = detect_domain(user_text, domain)
    sid = ensure_session(session_id, domain)
    if not session_id or not db.qone(
        "SELECT id FROM sessions WHERE id=?", (session_id,)
    ):
        db.run(
            "UPDATE sessions SET title=? WHERE id=?",
            (user_text[:48] or "Conversation", sid),
        )
    db.run(
        "INSERT INTO messages (session_id, role, kind, content) VALUES (?,?,?,?)",
        (sid, "user", "text", user_text),
    )
    run_id = db.run(
        "INSERT INTO runs (trace_id, session_id, user_id, intent, domain, model, status) VALUES (?,?,?,?,?,?,?)",
        (trace_id, sid, 1, intent, domain, "", "running"),
    )
    ctx = {"domain": domain, "ai": True, "session_id": sid, "trace_id": trace_id}
    plan = build_plan(intent, user_text)

    yield _sse("orb", {"state": "thinking"})
    # Send thinking lines for plan
    for step in plan:
        yield _sse("thinking", {"text": f"Planning: {step['label']}"})
    yield _sse(
        "plan",
        {
            "trace_id": trace_id,
            "session_id": sid,
            "intent": intent,
            "domain": domain,
            "steps": [{k: s[k] for k in ("id", "label", "status")} for s in plan],
        },
    )
    yield _sse("orb", {"state": "retrieving"})
    yield _sse("thinking", {"text": "Retrieving relevant memories..."})

    tool_results: dict[str, Any] = {}
    memories: list[dict] = []
    entities: dict[str, Any] = {
        "tasks": [],
        "projects": [],
        "resumes": [],
        "expenses": [],
        "automations": [],
    }
    pending_approval: dict | None = None

    i, n = 0, len(plan)
    while i < n:
        # form a run of consecutive R0 read-only steps → execute in parallel
        j = i
        if _parallel_steps_enabled():
            while j < n and _is_parallel_step(plan[j]):
                j += 1
        batch = plan[i:j]
        if len(batch) >= 2:
            for step in batch:
                step["status"] = "running"
                yield _sse("step", {"id": step["id"], "status": "running"})
                yield _sse("thinking", {"text": f"Running {step['label']}..."})
            yield _sse("orb", {"state": "working"})
            results: dict[str, Any] = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {
                    ex.submit(
                        _run_tool, s["tool"], dict(s.get("args") or {}), ctx, run_id
                    ): s
                    for s in batch
                }
                for fut, step in futs.items():
                    try:
                        results[step["id"]] = fut.result()
                    except Exception as e:  # noqa: BLE001 — per-step error is data
                        results[step["id"]] = {"error": str(e)[:200]}
            for step in batch:
                tool = step["tool"]
                data = results.get(step["id"])
                tool_results[step["id"]] = data
                err = isinstance(data, dict) and "error" in data
                yield _sse("tool", {"id": step["id"], "tool": tool, "ok": not err})
                yield _sse("thinking", {"text": f"Completed {step['label']}"})
                for ev_name, payload in _harvest(
                    tool, data, tool_results, memories, entities
                ):
                    yield _sse(ev_name, payload)
                step["status"] = "error" if err else "done"
                payload = {"id": step["id"], "status": step["status"]}
                if err:
                    payload["error"] = (data or {}).get("error", "")[:200]
                yield _sse("step", payload)
            i = j
            continue
        step = plan[i]
        step["status"] = "running"
        yield _sse("step", {"id": step["id"], "status": "running"})
        yield _sse("thinking", {"text": f"Executing: {step['label']}"})
        yield _sse("orb", {"state": "working"})
        tool, args = step["tool"], dict(step.get("args") or {})
        try:
            if tool == "__approval__":
                drafts = (
                    tool_results.get("s2", {}).get("drafts", [])
                    if isinstance(tool_results.get("s2"), dict)
                    else []
                )
                if not drafts:
                    step["status"] = "done"
                    yield _sse("step", {"id": step["id"], "status": "done"})
                    i += 1
                    continue
                aid = db.run(
                    "INSERT INTO approvals (user_id, risk, title, detail_json, expires_at) VALUES (1,'R2',?,?,datetime('now',?))",
                    (
                        "Send follow-up messages",
                        db.jdump({"drafts": drafts, "channel": "email"}),
                        _prefs.get("approval_timeout"),
                    ),
                )
                pending_approval = {
                    "id": aid,
                    "risk": "R2",
                    "title": "Send follow-up messages",
                    "drafts": drafts,
                }
                yield _sse("approval", pending_approval)
                yield _sse("orb", {"state": "waiting_approval"})
                step["status"] = "waiting_approval"
                yield _sse("step", {"id": step["id"], "status": "waiting_approval"})
                i += 1
                continue
            # NOTE: __terminal_or_script__ deliberately falls through to
            # exec_pseudo. `terminal.exec_command` is the safety boundary — it
            # classifies the command, refuses `dangerous` patterns unless
            # Settings → Terminal → allow dangerous is on, and audits every exec.
            # A second approval gate here made chat terminal commands a dead end
            # without adding any protection.
            if tool.startswith("__"):
                data = exec_pseudo(tool, args, ctx, run_id)
            else:
                data = _run_tool(tool, args, ctx, run_id)
            tool_results[step["id"]] = data
            yield _sse("tool", {"id": step["id"], "tool": tool, "ok": True})
            for ev_name, payload in _harvest(
                tool, data, tool_results, memories, entities
            ):
                yield _sse(ev_name, payload)
            step["status"] = "done"
            yield _sse("step", {"id": step["id"], "status": "done"})
        except Exception as e:
            step["status"] = "error"
            yield _sse(
                "step", {"id": step["id"], "status": "error", "error": str(e)[:200]}
            )
        i += 1

    _cloud_image_urls: list[str] = []
    if attachments:
        from . import vision as _vision
        import base64 as _b64

        _seen = []
        for _a in (attachments or [])[:3]:
            _fid = _a.get("file_id", _a.get("id")) if isinstance(_a, dict) else None
            if not isinstance(_fid, int) or _fid <= 0:
                continue
            _frow = (
                db.qone("SELECT name, path, mime FROM files WHERE id=?", (_fid,)) or {}
            )
            _fname = _frow.get("name") or f"#{_fid}"
            yield _sse("vision", {"file": _fname, "status": "analyzing"})
            yield _sse("orb", {"state": "seeing"})
            _vr = _vision.analyze_file(_fid, user_text)
            yield _sse(
                "vision",
                {
                    "file": _fname,
                    "status": "done" if _vr.get("ok") else "unavailable",
                    "model": _vr.get("model", ""),
                },
            )
            _seen.append(
                {
                    "file": _fname,
                    "description": _vr.get("description", "")
                    if _vr.get("ok")
                    else f"(unavailable: {_vr.get('error', '')})",
                }
            )
            # Build data URL for cloud vision
            _path = _frow.get("path")
            _mime = (_frow.get("mime") or "image/png").split(";")[0].strip()
            if _path:
                try:
                    with open(_path, "rb") as _f:
                        _data = _f.read(3 * 1024 * 1024)
                    _cloud_image_urls.append(
                        f"data:{_mime};base64," + _b64.b64encode(_data).decode()
                    )
                except Exception:
                    pass
        if _seen:
            tool_results["attached_images"] = _seen

    # ---- generation: privacy-ordered chain via ModelRouter.generate ----
    from . import compact as _cx

    _sctx = _cx.session_context(sid)
    _hist = _sctx["history"][:-1]
    grounding_full = json.dumps(
        {"intent": intent, "tool_results": tool_results},
        ensure_ascii=False,
        default=str,
    )[:4000]
    hist = _hist
    messages = _build_lfm_messages(
        user_text, hist, memories, grounding_full, _sctx["summary"]
    )
    # Cloud grounding must never carry sensitive/private memories. Build a
    # separate redacted message set rather than filtering `messages` in place,
    # so the local model still sees everything the user owns.
    cloud_memories, redacted_count = filter_cloud_memories(memories)
    cloud_messages = (
        _build_lfm_messages(
            user_text, hist, cloud_memories, grounding_full, _sctx["summary"]
        )
        if redacted_count
        else messages
    )

    # Streaming generation: use ollama.chat_stream directly for real-time tokens
    probe = model_router.probe()
    final_text = ""
    model_name = ""
    tokens_yielded = False
    token_buffer = []
    stream_failed = False
    # Cost attribution label. A turn carrying images is a vision turn, so it is
    # journaled under "vision" rather than "chat" in llm_usage.
    purpose = "vision" if _cloud_image_urls else "chat"

    try:
        for backend in model_router.chain():
            if backend == "ollama" and probe["local_lfm"]["online"]:
                stream = None
                try:
                    stream = model_router.ollama.chat_stream(messages, purpose=purpose)
                    for tok in stream:
                        token_buffer.append(tok)
                        yield _sse("token", {"text": tok})
                        tokens_yielded = True
                    final_text = "".join(token_buffer)
                    # Use model from probe if available, else from ollama client
                    ollama_model = (
                        probe["local_lfm"].get("model") or model_router.ollama.model
                    )
                    model_name = f"ollama/{ollama_model}"
                    break
                except Exception as e:
                    stream_failed = True
                    db.log_activity(
                        "run",
                        "Local LFM failed, continuing chain",
                        str(e)[:120],
                        "general",
                        "warn",
                    )
                    continue
                finally:
                    # If the client hung up mid-stream (generator closed at a
                    # yield), release the upstream connection instead of leaving
                    # it dangling until GC.
                    _close = getattr(stream, "close", None)
                    if callable(_close):
                        try:
                            _close()
                        except Exception:
                            pass
            elif backend == "cloud" and model_router.cloud.configured():
                safe = [
                    {**m, "content": scrub_secrets(m.get("content", ""))}
                    for m in cloud_messages
                ]
                reasoning = bool(_prefs.get("cloud_reasoning"))
                imgs = _cloud_image_urls if _cloud_image_urls else None
                # Some OpenAI-compatible gateways ignore `stream: true` and
                # answer with a single JSON body, and others reject the SSE
                # request outright. Retry non-streaming before giving up —
                # otherwise the user's chosen model is silently replaced by the
                # builtin composer.
                try:
                    for tok in model_router.cloud.chat_stream(
                        safe, purpose=purpose, reasoning=reasoning, images=imgs
                    ):
                        token_buffer.append(tok)
                        yield _sse("token", {"text": tok})
                        tokens_yielded = True
                except Exception as e:
                    db.log_activity("run", "Cloud stream failed, retrying once",
                                    str(e)[:120], "general", "warn")
                if not tokens_yielded:
                    text = (model_router.cloud.chat(
                        safe, purpose=purpose, images=imgs
                    ) or "").strip()
                    if text:
                        token_buffer.append(text)
                        yield _sse("token", {"text": text})
                        tokens_yielded = True
                if tokens_yielded:
                    final_text = "".join(token_buffer)
                    model_name = f"cloud/{model_router.cloud.model}"
                    break
                raise RuntimeError("cloud returned no content")
        else:
            raise RuntimeError("All model backends failed")

    except Exception as e:
        db.log_activity("run", "Generation failed", str(e)[:150], domain, "warn")
        builtin_text = model_router.builtin.compose(
            user_text,
            intent,
            plan,
            tool_results,
            memories,
            entities,
            history=_hist,
            summary=_sctx["summary"],
        )
        final_text = builtin_text
        model_name = model_router.builtin.name

    if tool_results.get("attached_images") and model_name == model_router.builtin.name:
        _bits = "\n".join(
            f"- {a['file']}: {a['description'][:600]}"
            for a in tool_results["attached_images"]
        )
        final_text = f"{final_text}\n\nAttached images:\n{_bits}"

    # Only replay tokens if NO tokens were streamed (cloud/builtin path)
    if not tokens_yielded:
        yield _sse("orb", {"state": "working"})
        words = final_text.split(" ")
        for i in range(0, len(words), 4):
            buf = " ".join(words[i : i + 4])
            yield _sse("token", {"text": buf + (" " if i + 4 < len(words) else "")})
    engine = (
        "cloud"
        if model_name.startswith("cloud/")
        else ("ollama" if model_name.startswith("ollama/") else "builtin")
    )
    yield _sse(
        "result",
        {
            "text": final_text,
            "model": model_name,
            "engine": engine,
            "redacted_memories": redacted_count if engine == "cloud" else 0,
            "memories_used": [
                {
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "relevance": m.get("relevance"),
                }
                for m in memories[:4]
            ],
            "approval": pending_approval,
        },
    )

    # ---- persistence + memory policy + observability ----
    db.run(
        "INSERT INTO messages (session_id, role, kind, content, meta_json) VALUES (?,?,?,?,?)",
        (
            sid,
            "assistant",
            "text",
            final_text,
            db.jdump({"intent": intent, "model": model_name, "trace_id": trace_id}),
        ),
    )
    try:
        _cx.maybe_compact(sid)
    except Exception:
        pass  # compaction must never break a turn
    ms = int((time.time() - t0) * 1000)
    db.run(
        "UPDATE runs SET status='ok', model=?, duration_ms=? WHERE id=?",
        (model_name, ms, run_id),
    )
    stored = []
    try:
        auto_store = _prefs.get("memory_auto_store")
    except Exception:
        auto_store = True
    if auto_store:
        try:
            stored = memory_engine.observe(user_text, domain, "conversation")
        except Exception:
            pass
    if stored:
        yield _sse(
            "memory",
            {"stored": [{"id": s.get("id"), "title": s.get("title")} for s in stored]},
        )
    if attachments:
        db.log_activity(
            "message", "Multimodal turn", f"{len(attachments)} attachment(s)", domain
        )
    db.log_activity(
        "run",
        f"AURA run: {intent}",
        f"{ms}ms · {model_name} · trace {trace_id}",
        domain,
        "success",
    )
    yield _sse("orb", {"state": "success"})
    yield _sse("done", {"session_id": sid, "trace_id": trace_id, "ms": ms})
