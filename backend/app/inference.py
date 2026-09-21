"""AURA Model Router — provider-neutral inference layer.

Routing order (local-first):
  1. Local LFM via Ollama (/api/chat) when reachable and capable.
  2. Cloud LLM when configured (OpenAI-compatible chat endpoint).
  3. Built-in AuraEngine — deterministic, retrieval-grounded composer that
     turns orchestrator tool results + memory context into useful answers.
     This guarantees AURA is fully operational with zero model downloads.

Also exposes embeddings (Ollama -> hashed fallback) and capability probes
used by System Status / diagnostics.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterator

import httpx

from . import config, costs, db, prefs
from .memory import Embedding, hashed_embed, valid_embedding


def conversational_messages(messages: list[dict], purpose: str = "chat") -> list[dict]:
    if purpose != "chat":
        return messages
    choices = {
        "ai_warmth": {"neutral": "Use a neutral, respectful tone.", "warm": "Be warm and approachable without flattery.", "supportive": "Be supportive, acknowledge difficulty without assuming feelings."},
        "ai_humour": {"off": "Avoid jokes.", "light": "Use occasional light humour when appropriate.", "playful": "Use gentle playful humour, never at the user's expense."},
        "ai_style": {"conversational": "Use natural conversational language and contractions, not canned greetings.", "professional": "Use clear professional language.", "direct": "Be direct: lead with the answer, avoid filler."},
        "ai_pacing": {"concise": "Keep replies concise unless detail is requested.", "balanced": "Use balanced pacing: a short answer followed by useful detail.", "unhurried": "Use unhurried pacing, short paragraphs and one question at a time."},
    }
    tone = " ".join(options.get(prefs.get(key), options[prefs.SCHEMA[key][0]]) for key, options in choices.items())
    policy = ("AURA conversational delivery: " + tone + " These are style preferences only. "
              "Never claim feelings or consciousness, a human identity, or personal experiences. "
              "Never fabricate actions, tool results, memories, or completed work; distinguish suggestions from verified actions. "
              "Keep factual uncertainty explicit. Respect all existing grounding, approval and privacy rules; "
              "style never overrides them. Avoid humour in serious or sensitive situations.")
    result = [dict(m) for m in messages]
    if result and result[0].get("role") == "system" and isinstance(result[0].get("content"), str):
        result[0]["content"] += "\n\n" + policy
    else:
        result.insert(0, {"role": "system", "content": policy})
    return result


class OllamaClient:
    def __init__(self, base: str | None = None):
        self._base = base

    @property
    def base(self) -> str:
        return (self._base or prefs.get("ollama_base_url")).rstrip("/")

    @property
    def model(self) -> str:
        return prefs.get("ollama_chat_model")

    def healthy(self, timeout: float = 1.2) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.base}/api/tags", timeout=timeout)
            if r.status_code == 200:
                models = [m.get("name", "") for m in r.json().get("models", [])]
                return True, ", ".join(models[:4]) or "no models pulled"
            return False, f"http {r.status_code}"
        except Exception as e:
            return False, str(e)[:80]

    def chat(self, messages: list[dict], model: str | None = None,
             stream_cb: Callable[[str], None] | None = None, timeout: float = 120.0,
             purpose: str = "chat", images: list[str] | None = None) -> str:
        out: list[str] = []
        stream = self.chat_stream(messages, model, timeout, purpose, images)
        try:
            for tok in stream:
                out.append(tok)
                if stream_cb:
                    stream_cb(tok)
        finally:
            stream.close()
        return "".join(out)

    def chat_stream(self, messages: list[dict], model: str | None = None,
                    timeout: float = 120.0, purpose: str = "chat",
                    images: list[str] | None = None) -> Iterator[str]:
        if db.DRY_RUN:
            db.blocked("llm: ollama chat skipped")
            yield "[dry-run: LLM response withheld]"
            return
        messages = [dict(m) for m in conversational_messages(messages, purpose)]
        if images:
            messages[-1]["images"] = [u.split(",", 1)[-1] if "base64," in u else u for u in images[:4]]
        payload = {"model": model or self.model, "messages": messages, "stream": True,
                   "options": {"temperature": 0.6}}
        stats: dict = {}
        t0 = time.time()
        with httpx.stream("POST", f"{self.base}/api/chat", json=payload, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.strip().startswith("{"):
                    continue
                import json as _j
                d = _j.loads(line)
                if d.get("error"):
                    raise RuntimeError("Ollama generation failed")
                tok = ((d.get("message") or {}).get("content")) or ""
                if tok:
                    yield tok
                if d.get("done"):
                    stats = d
                    break
            else:
                raise RuntimeError("Ollama stream ended before completion")
        costs.record("ollama", payload["model"], purpose, int(stats.get("prompt_eval_count", 0) or 0),
                     int(stats.get("eval_count", 0) or 0), int((time.time() - t0) * 1000))

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        try:
            r = httpx.post(f"{self.base}/api/embeddings",
                           json={"model": model or prefs.get("ollama_embed_model")
                                 or config.OLLAMA_EMBED_MODEL, "prompt": text}, timeout=15)
            if r.status_code == 200:
                return list(r.json().get("embedding", []))
        except Exception:
            pass
        return None
_SECRET_RE = re.compile(r'(?i)("?(?:password|passwd|api[_-]?key|apikey|token|secret|smtp[_-]?pass|bot[_-]?token|webhook[_-]?url|authorization)"?\s*[:=]\s*"?)([^",}\s]{3,})')


def scrub_secrets(text: str) -> str:
    """Redact likely credential values before anything leaves the machine."""
    return _SECRET_RE.sub(r"\1***", text or "")


def filter_cloud_memories(memories: list[dict] | None, policy: str | None = None) -> tuple[list[dict], int]:
    """Keep only shareable memories for cloud grounding. Returns (kept, redacted_count).

    strict (default): withhold sensitive + private. relaxed: withhold private only.
    policy=None resolves the cloud_memory_policy setting."""
    if policy is None:
        try:
            policy = prefs.get("cloud_memory_policy")
        except Exception:
            policy = "strict"
    withheld = ("private",) if policy == "relaxed" else ("sensitive", "private")
    kept, n = [], 0
    for m in memories or []:
        if (m.get("sensitivity") or "normal") in withheld:
            n += 1
        else:
            kept.append(m)
    return kept, n


class CloudClient:
    """OpenAI-compatible chat endpoint: OpenRouter (default), OpenAI, or custom.

    Only ever called when the privacy setting allows it AND a key is configured.
    Callers must pass pre-redacted messages (see filter_cloud_memories)."""

    def __init__(self, base: str | None = None, api_key: str | None = None,
                 model: str | None = None, provider: str | None = None,
                 temperature: float | None = None, max_tokens: int | None = None):
        self._base, self._key, self._model = base, api_key, model
        self._provider = provider
        self._temp, self._max = temperature, max_tokens

    @property
    def provider(self) -> str:
        return self._provider or prefs.get("cloud_provider")

    @property
    def base(self) -> str:
        if self._base:
            return self._base.rstrip("/")
        if self.provider == "openrouter":
            return config.OPENROUTER_BASE_URL
        if self.provider == "custom":
            return (prefs.get("custom_base_url") or "").rstrip("/")
        return config.CLOUD_BASE_URL

    @property
    def key(self) -> str:
        if self._key is not None:
            return self._key
        if self.provider == "openrouter":
            return prefs.get("openrouter_key")
        if self.provider == "custom":
            return prefs.get("custom_key")
        return prefs.get("openai_key")

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        if self.provider == "openrouter":
            return prefs.get("openrouter_model")
        if self.provider == "custom":
            return prefs.get("custom_model")
        return prefs.get("openai_model")

    @property
    def temperature(self) -> float:
        return self._temp if self._temp is not None else prefs.get("cloud_temperature")

    @property
    def max_tokens(self) -> int:
        return self._max if self._max is not None else prefs.get("cloud_max_tokens")

    def headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.key}"}
        if self.provider == "openrouter":
            h["HTTP-Referer"] = config.OPENROUTER_REFERER
            h["X-Title"] = config.OPENROUTER_TITLE
        return h

    def configured(self) -> bool:
        return bool(self.key and self.model and self.base)

    def chat(self, messages: list[dict], stream_cb: Callable[[str], None] | None = None,
             timeout: float = 60.0, max_tokens: int | None = None, purpose: str = "chat",
             images: list[str] | None = None) -> str:
        if db.DRY_RUN:
            db.blocked("llm: cloud chat skipped")
            return "[dry-run: LLM response withheld]"
        messages = conversational_messages(messages, purpose)
        if images:
            messages = [dict(m) for m in messages]
            last = messages[-1]
            parts: list[dict] = ([{"type": "text", "text": last.get("content", "")}]
                                 if isinstance(last.get("content"), str) else list(last.get("content") or []))
            parts += [{"type": "image_url", "image_url": {"url": u}} for u in images[:4]]
            last["content"] = parts
        allowed, why = costs.check()
        if not allowed:
            costs.record(self.provider, self.model, purpose, 0, 0, 0, ok=False, error=why)
            raise costs.BudgetExceeded(why)
        t0 = time.time()
        try:
            r = httpx.post(f"{self.base}/chat/completions",
                           headers=self.headers(),
                           json={"model": self.model, "messages": messages,
                                 "temperature": self.temperature,
                                 "max_tokens": max_tokens or self.max_tokens},
                           timeout=timeout)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            costs.record(self.provider, self.model, purpose, 0, 0,
                         int((time.time() - t0) * 1000), ok=False,
                         error=f"{type(e).__name__}: {e}"[:200])
            raise
        text = (((d.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        u = d.get("usage", {}) or {}
        costs.record(self.provider, self.model, purpose, int(u.get("prompt_tokens", 0) or 0),
                     int(u.get("completion_tokens", 0) or 0), int((time.time() - t0) * 1000))
        if text and stream_cb:
            stream_cb(text)
        return text


def get_cloud_client(provider: str | None = None, model: str | None = None,
                     api_key: str | None = None) -> CloudClient:
    """Build a cloud client from effective settings, with optional overrides
    (used by the connection tester so candidates can be tried before saving)."""
    return CloudClient(provider=provider, model=model or None,
                       api_key=api_key if api_key is not None else None)


# -- OpenRouter model catalog (public endpoint, cached; curated fallback) ------

# Curated free-tier presets, verified live 2026-09-09 (21 free of 431). The live catalog is authoritative —
# free models rotate; GET /api/cloud/models refreshes from OpenRouter.
OPENROUTER_FREE_PRESETS = [
    {"id": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B", "context_length": 262144,
     "note": "multimodal general"},
    {"id": "openrouter/free", "name": "Free Models Router", "context_length": 200000,
     "note": "auto-picks a free model"},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "Nemotron 3 Ultra", "context_length": 1000000,
     "note": "1M-context reasoning"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "Nemotron 3 Super", "context_length": 262144,
     "note": "long-context reasoning"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "name": "Nemotron 3 Omni", "context_length": 256000,
     "note": "multimodal reasoning"},
    {"id": "nvidia/nemotron-3.5-lightning:free", "name": "Nemotron 3.5 Lightning", "context_length": 1000000,
     "note": "fast 1M general"},
    {"id": "google/gemma-4-26b-a4b-it:free", "name": "Gemma 4 26B", "context_length": 262144,
     "note": "fast multimodal"},
    {"id": "thinkingmachines/inkling:free", "name": "Inkling", "context_length": 1048576,
     "note": "1M general"},
    {"id": "cohere/north-mini-code:free", "name": "North Mini Code", "context_length": 256000,
     "note": "coding"},
    {"id": "poolside/laguna-s-2.1:free", "name": "Laguna S 2.1", "context_length": 262144,
     "note": "coding agent"},
    {"id": "poolside/laguna-xs-2.1:free", "name": "Laguna XS 2.1", "context_length": 262144,
     "note": "fast coding"},
    {"id": "liquid/lfm-2.5-2.6b:free", "name": "LFM 2.5 2.6B", "context_length": 65536,
     "note": "tiny + fast"},
]

_catalog_cache: dict = {"at": 0.0, "models": []}
CATALOG_TTL_S = 3600.0


def _norm_model(m: dict) -> dict:
    mid = m.get("id", "")
    price = m.get("pricing") or {}
    try:
        free = float(price.get("prompt", "1") or 0) == 0 and float(price.get("completion", "1") or 0) == 0
    except (TypeError, ValueError):
        free = mid.endswith(":free")
    return {"id": mid, "name": m.get("name", mid), "context_length": m.get("context_length", 0),
            "free": free or mid.endswith(":free")}


def fetch_openrouter_models(refresh: bool = False, timeout: float = 20.0) -> dict:
    """Live OpenRouter catalog (public, no key needed). Falls back to curated
    presets when offline. Never raises — returns {models, cached, stale, ...}."""
    import time as _t
    now = _t.time()
    if not refresh and _catalog_cache["models"] and now - _catalog_cache["at"] < CATALOG_TTL_S:
        return {"models": _catalog_cache["models"], "cached": True, "stale": False,
                "count": len(_catalog_cache["models"]), "updated_at": _catalog_cache["at"]}
    try:
        r = httpx.get(f"{config.OPENROUTER_BASE_URL}/models", timeout=timeout)
        r.raise_for_status()
        raw = r.json().get("data", [])
        costs.cache_openrouter_pricing(raw)
        models = [_norm_model(m) for m in raw if m.get("id")]
        models.sort(key=lambda m: (not m["free"], m["id"]))
        if models:
            _catalog_cache.update({"at": now, "models": models})
            return {"models": models, "cached": False, "stale": False,
                    "count": len(models), "updated_at": now}
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:120]}"
    else:
        err = "empty catalog"
    if _catalog_cache["models"]:
        return {"models": _catalog_cache["models"], "cached": True, "stale": True,
                "count": len(_catalog_cache["models"]), "updated_at": _catalog_cache["at"],
                "error": err}
    fb = [{**m, "free": True} for m in OPENROUTER_FREE_PRESETS]
    return {"models": fb, "cached": False, "stale": True, "count": len(fb),
            "updated_at": 0.0, "error": err,
            "note": "offline — curated presets; connect to refresh the live list"}


def test_cloud(provider: str | None = None, model: str | None = None,
               api_key: str | None = None, timeout: float = 25.0) -> dict:
    """Try a minimal completion through saved config or candidate overrides.
    Never echoes the key. Returns {ok, latency_ms, model, provider, error?}."""
    t0 = time.time()
    client = get_cloud_client(provider, model, api_key)
    if not client.configured():
        missing = [n for n, v in (("api key", client.key), ("model", client.model),
                                  ("base url", client.base)) if not v]
        return {"ok": False, "provider": client.provider, "model": client.model,
                "error": f"not configured — missing: {', '.join(missing)}"}
    try:
        text = client.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                           timeout=timeout, max_tokens=8, purpose="test")
    except Exception as e:
        return {"ok": False, "provider": client.provider, "model": client.model,
                "latency_ms": max(1, int((time.time() - t0) * 1000)),
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
    ms = max(1, int((time.time() - t0) * 1000))
    return {"ok": bool(text.strip()), "provider": client.provider, "model": client.model,
            "latency_ms": ms, "reply": text.strip()[:60]}


class BuiltinEngine:
    """Deterministic grounded composer. Never hallucinates tool data —
    it renders exactly what the orchestrator retrieved/executed."""

    name = "aura-builtin-1.0"

    def compose(self, user_text: str, intent: str, plan: list[dict],
                tool_results: dict[str, Any], memories: list[dict], entities: dict,
                history: list[dict] | None = None, summary: str = "") -> str:
        parts: list[str] = []
        if intent == "greet":
            return ("Hello! I'm ready. You can ask me to **plan your day**, **review client workload**, "
                    "**optimize your resume**, **log a journal entry**, or **search memory** — or just talk.")
        if intent == "plan_day":
            return self._plan_day(tool_results)
        if intent == "client_review":
            return self._client_review(tool_results)
        if intent == "task_create":
            made = [t for t in (tool_results.get("tasks_created", []) or []) if isinstance(t, dict)]
            titles = [t.get("title", "") for t in made if t.get("title")]
            if len(made) == 1 and titles:
                return f"Done — added **{titles[0][:100]}** to your inbox." + self._mem_note(memories)
            n = len(made)
            return f"Done — I created **{n} task{'s' if n!=1 else ''}** and added {'them' if n!=1 else 'it'} to your inbox." + self._mem_note(memories)
        if intent == "task_toggle":
            upd = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            if upd.get("matched"):
                icon = "✅" if upd.get("status") == "completed" else "🔄"
                return f"{icon} Done — **{upd.get('title', 'task')}** is now *{upd.get('status', 'updated')}*."
            return "I couldn't find an open task matching that. Try the exact title from Today's priorities."
        if intent == "task_list":
            return self._task_list(entities) + self._mem_note(memories)
        if intent == "project_status":
            return self._project_status(entities) + self._mem_note(memories)
        if intent == "memory_search":
            return self._memory_answer(memories, user_text)
        if intent == "memory_store":
            return "Saved to memory. I'll recall it in future conversations and planning."
        if intent == "resume_help":
            return self._resume_help(tool_results, entities)
        if intent == "interview_prep":
            return self._interview_prep(tool_results, entities)
        if intent == "followup_draft":
            return self._followup(tool_results)
        if intent == "health_log":
            return "Logged. Your Personal Life panel and insights are updated."
        if intent == "sleep_log":
            s1 = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            if s1.get("hours"):
                span = f" ({s1['bedtime']} \u2192 {s1['wake_at']})" if s1.get("bedtime") else ""
                q = f" Quality: {s1['quality']}." if s1.get("quality") else ""
                return f"Logged **{float(s1['hours']):.1f}h** of sleep{span}.{q} Your dashboard insights are updated."
            return "How long did you sleep? e.g. `slept 11pm to 6am` or `log sleep 7.5 hours`."
        if intent == "journal":
            return "Journaled. I've kept the reflection in your private Personal domain."
        if intent == "finance":
            return self._finance(tool_results, entities)
        if intent == "system_status":
            return self._sys_status(tool_results)
        if intent == "terminal_run":
            return self._terminal(tool_results)
        if intent == "ollama_models":
            return self._ollama_models(tool_results)
        if intent == "ollama_switch":
            sw = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            if sw.get("ok"):
                return f"Done — local {sw.get('role', 'chat')} generation now uses **{sw.get('model')}**. Say “system status” to confirm the switch."
            return f"I couldn't switch models: {sw.get('error', 'unknown error')}."
        if intent == "feed_follow":
            ff = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            if ff.get("id"):
                verb = "already followed" if ff.get("already_existed") else "following"
                return f"Feed {verb} — **{ff.get('title', 'untitled')}** ({ff.get('items', 0)} new items pulled). It will refresh automatically and can trigger automations."
            return "I couldn't add that feed — double-check the URL (it must be an RSS/Atom endpoint)."
        if intent == "feeds_latest":
            return self._feeds(tool_results)
        if intent == "weather":
            return self._weather(tool_results)
        if intent == "help":
            return self._help()
        if intent == "project_create":
            p = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            return f"Created project **{p.get('name', 'Untitled')}**. Open Clients & Projects to set the deadline, milestones, and progress."
        if intent == "client_create":
            c = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            return f"Added client **{c.get('name', 'Untitled')}**. Ask me for a meeting brief anytime, e.g. meeting prep for them."
        if intent == "backup_run":
            b = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            if b.get("ok"):
                kb = (b.get("size_bytes", 0) or 0) / 1024
                return f"Backup complete: **{b.get('file', 'snapshot')}** ({kb:.0f} KB, sha256 `{b.get('sha256', '')[:12]}...`). Integrity recorded in Backup Manager."
            return f"Backup failed: {b.get('error', 'unknown error')}. Nothing was deleted - retry from Clients, Backup tab."
        if intent == "meeting_prep":
            mp = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            who = mp.get("who", "your contact")
            lines = [f"**Meeting brief - {who}**", ""]
            mems = mp.get("memories", []) or []
            if mems:
                lines.append("What I remember:")
                lines += [f"- **{(m.get('title') or '')[:60]}** - {(m.get('content') or '')[:130]}" for m in mems[:4]]
                lines.append("")
            tasks = mp.get("open_tasks", []) or []
            if tasks:
                lines.append("Open items touching them:")
                lines += [f"- **{t.get('title', '')}** ({t.get('status', '')})" for t in tasks[:5]]
            else:
                lines.append("No open tasks mention them - a clean slate.")
            lines += ["", "Want me to draft an agenda or a follow-up afterwards?"]
            return "\n".join(lines)
        if intent == "automation":
            s1 = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            autos = s1.get("automations", []) or []
            if not autos:
                return "No automations yet. Open the Automation Center to create scheduled reminders, briefs, or backups."
            lines = ["**Your automations:**", ""]
            for a in autos[:10]:
                okc, failc = (a.get("success_count", 0) or 0), (a.get("fail_count", 0) or 0)
                rate = f"{round(okc / (okc + failc) * 100)}%" if (okc + failc) else "-"
                lines.append(f"- **{a.get('name', '')}** - {a.get('status', '')} - {a.get('action_kind', '')} {a.get('trigger_kind', '')} - success {rate}")
            lines += ["", "Use **Run now** in the Automation Center to fire one immediately."]
            return "\n".join(lines)
        if intent == "email_check":
            return self._email_check(tool_results)
        if intent == "calendar_today":
            return self._calendar_today(tool_results)
        if intent == "calendar_create":
            return self._calendar_create(tool_results)
        if intent == "briefing":
            s1 = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            out = (s1.get("output") or "").strip()
            if out:
                return out + f"\n\n_Drafted in {s1.get('ms', 0)}ms via {s1.get('model', '?')}._"
            return "I couldn't generate a briefing right now. Try again in a moment."
        if intent == "gateway":
            rows = db.q("SELECT platform, status, account FROM integrations WHERE user_id=1")
            lines = ["**Gateway status:**", ""]
            for g in rows:
                dot = "online" if g["status"] == "connected" else "offline"
                acc = (f" - {g['account']}") if g["account"] else ""
                lines.append(f"[{dot}] **{g['platform'].capitalize()}** - {g['status']}{acc}")
            lines += ["", "Open Multi-Platform to connect, test, or simulate inbound messages."]
            return "\n".join(lines)
        if intent == "voice_note":
            return "Voice is ready - tap the microphone and speak. I'll transcribe, act, and can read the answer back. See Voice & Audio for controls."
        if intent == "web_search":
            return self._web_search(tool_results, user_text)
        if intent == "mission_status":
            return self._mission_status(tool_results)
        if intent == "undo":
            s1 = tool_results.get("s1", {}) if isinstance(tool_results.get("s1"), dict) else {}
            done = s1.get("undone", []) or []
            if not done:
                return "Nothing to undo — no recent changes on record."
            lines = ["Undone:"]
            for u in done:
                lines.append(f"- {u.get('result', u.get('summary', ''))}")
            if s1.get("remaining"):
                lines.append(f"\n({s1['remaining']} earlier change(s) still on record — say **undo** again.)")
            return "\n".join(lines)
        if intent == "general_ask" and not memories and (history or summary):
            topic = ""
            if summary:
                topic = summary.split(";")[0].replace("Previously: ", "").replace("Topic: ", "")[:140]
            if not topic and history:
                topic = next(((h.get("content") or "") for h in history if h.get("role") == "user"), "")[:140]
            if topic:
                return (f"Picking up our thread on **{topic}** — I don't have grounded facts for that one. "
                        "Try **“search memory for …”**, **“create a task to …”**, or rephrase with a name or date.")
        # default grounded answer
        if memories:
            top = memories[0]
            parts.append(f"From your memory — **{top.get('title','')}**: {top.get('content','')}")
            if len(memories) > 1:
                parts.append(f"\n\nI found {len(memories)} related memories; the most relevant is shown first.")
            parts.append(self._mem_note(memories, skip_first=True))
            return "\n".join(parts)
        lk = tool_results.get("s2", {}) if isinstance(tool_results.get("s2"), dict) else {}
        found = [f"task: {t.get('title', '')}" for t in (lk.get("tasks") or [])[:3]]
        found += [f"project: {p.get('name', '')}" for p in (lk.get("projects") or [])[:3]]
        if found:
            return ("I found related records: **" + "**, **".join(found) + "**. "
                    "Want details on one - or should I create a task from this?")
        return ("I've noted that. To act on it, try: **“create a task to …”**, **“plan my day”**, "
                "**“review my clients”**, **“log …”**, or **“remember that …”**.")

    # ---- composers ----
    def _mem_note(self, memories: list[dict], skip_first: bool = False) -> str:
        ms = memories[1:] if skip_first else memories
        if not ms:
            return ""
        n = min(2, len(ms))
        return "\n\n*Grounded in " + str(len(ms)) + " memor" + ("y" if len(ms) == 1 else "ies") + ".*"

    def _plan_day(self, tr: dict) -> str:
        over = tr.get("overdue", []) or []
        over_ids = {t.get("id") for t in over}
        tasks = list(over) + [t for t in (tr.get("open_tasks", []) or []) if t.get("id") not in over_ids]
        blocks = tr.get("timeblocks", [])
        lines = ["Here's your plan for today, prioritized by deadline and importance:\n"]
        if not tasks:
            lines.append("• Your task list is clear — enjoy the open road, or tell me what matters most today.")
        else:
            for i, t in enumerate(tasks[:6], 1):
                due = f" (due {t['due_at'][:10]})" if t.get("due_at") else ""
                lines.append(f"**{i}. {t['title']}** — {t.get('priority','medium')} priority{due}")
        if blocks:
            lines.append("\n**Time blocks:**")
            for b in blocks[:6]:
                lines.append(f"• {b['starts_at'][11:16]}–{b['ends_at'][11:16]} — {b['title']}")
        misses = tr.get("overdue", [])
        if misses:
            lines.append(f"\n⚠️ **{len(misses)} overdue** — I put the riskiest one first.")
        opps = (tr.get("opportunities", {}) or {}).get("opportunities", []) if isinstance(tr.get("opportunities"), dict) else (tr.get("opportunities") or [])
        opps = [o for o in opps if isinstance(o, dict)][:2]
        if opps:
            lines.append("\n🔮 **Worth a look:**")
            for o in opps:
                why = (o.get("reasons") or [""])[0]
                lines.append(f"• {o.get('title', '?')}" + (f" — {why}" if why else ""))
        return "\n".join(lines)

    def _client_review(self, tr: dict) -> str:
        clients = tr.get("clients", [])
        overdue = tr.get("overdue_tasks", [])
        projects = tr.get("projects", [])
        if not clients and not projects:
            return "You have no clients or projects yet. Say **“add client Acme”** or **“new project Website”** to begin."
        lines = ["**Client workload review**\n"]
        for p in projects:
            bar = "🟢" if p.get("health") == "on_track" else ("🟡" if p.get("health") == "at_risk" else "🔴")
            lines.append(f"{bar} **{p['name']}** — {p.get('progress',0)}% · {p.get('status','active')}")
        if overdue:
            lines.append(f"\n⚠️ **{len(overdue)} overdue task(s):**")
            for t in overdue[:5]:
                lines.append(f"• {t['title']}")
            lines.append("\nSay **“draft follow-ups”** and I'll prepare messages for approval.")
        else:
            lines.append("\nNothing overdue. Your client work is on track. ✅")
        return "\n".join(lines)

    def _task_list(self, entities: dict) -> str:
        tasks = entities.get("tasks", [])
        if not tasks:
            return "No tasks match. Say **“create a task to …”** to add one."
        lines = [f"**{len(tasks)} task(s):**\n"]
        for t in tasks[:12]:
            box = "✅" if t["status"] == "completed" else "⬜"
            lines.append(f"{box} **{t['title']}** — {t['status']} · {t.get('priority','medium')}")
        return "\n".join(lines)

    def _project_status(self, entities: dict) -> str:
        projects = entities.get("projects", [])
        if not projects:
            return "No projects yet. Say **“new project …”** to create one."
        return "\n".join(f"**{p['name']}** — {p.get('progress',0)}% · {p.get('status')}" for p in projects[:10])

    def _memory_answer(self, memories: list[dict], q: str) -> str:
        if not memories:
            return "I searched your memory and found nothing relevant yet. Tell me something with **“remember that …”**."
        lines = [f"I found **{len(memories)}** relevant memor{'y' if len(memories)==1 else 'ies'}:\n"]
        for m in memories[:5]:
            lines.append(f"• **{m.get('title','')}** — {m.get('content','')}  _(relevance {m.get('relevance',0)})_")
        return "\n".join(lines)

    def _resume_help(self, tr: dict, entities: dict) -> str:
        resumes = entities.get("resumes", [])
        base = resumes[0] if resumes else None
        score = tr.get("ats_score")
        lines = ["**Resume analysis**\n"]
        if base:
            lines.append(f"Active resume: **{base['name']} v{base['version']}** (ATS score {base.get('ats_score',0)}/100).")
        if score is not None:
            lines.append(f"Latest analysis: **ATS {score}/100**.")
        lines += ["", "**Recommendations:**",
                  "1. Quantify achievements — add numbers (%, KES, users, latency) to every bullet.",
                  "2. Mirror the job description's top 8 keywords in a Skills section.",
                  "3. Keep it to 2 pages; most recent role gets the most space.",
                  "4. Start bullets with strong verbs: built, led, shipped, cut, grew.",
                  "5. Add a 3-line summary targeting the exact role title.",
                  "", "Open **Career & Work → Resume** to upload a new version or export."]
        return "\n".join(lines)

    def _interview_prep(self, tr: dict, entities: dict) -> str:
        s1 = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        _qs = s1.get("questions", []) or []
        _role = s1.get("role", "your role")
        _lines = [f"**Interview prep - {_role}**", ""]
        _lines += [f"**Q{i}.** {q}" for i, q in enumerate(_qs[:6], 1)]
        _lines += ["", "Open **Career & Work, Interviews tab** to log a scored practice session."]
        return "\n".join(_lines)

    def _interview_prep_legacy(self, tr: dict, entities: dict) -> str:
        lines = ["**Interview prep** — here are 5 questions to practice:\n",
                 "1. Walk me through your most impactful project in 2 minutes.",
                 "2. Describe a conflict with a stakeholder and how you resolved it.",
                 "3. How do you prioritize when everything is urgent?",
                 "4. Tell me about a failure and what you changed afterwards.",
                 "5. Why this company, and why this role, right now?",
                 "", "Say **“mock interview”** and I'll quiz you one question at a time with scoring."]
        return "\n".join(lines)

    def _followup(self, tr: dict) -> str:
        drafts = tr.get("drafts", [])
        if not drafts:
            return "Nothing overdue — no follow-ups needed. Your clients are in good shape."
        lines = ["I've drafted follow-ups. **Review and approve** each before anything is sent:\n"]
        for d in drafts[:5]:
            lines.append(f"**To {d['to']}** — _{d['subject']}_\n> {d['body']}\n")
        lines.append("Open the **approval card** above (or Activity → Approvals) to approve, edit, or reject.")
        return "\n".join(lines)

    def _finance(self, tr: dict, entities: dict) -> str:
        ex = entities.get("expenses", [])
        total = sum(float(e.get("amount", 0)) for e in ex)
        cur = (ex[0].get("currency") if ex else "KES") or "KES"
        lines = [f"**Spending:** {cur} {total:,.0f} across {len(ex)} expense(s)."]
        by: dict[str, float] = {}
        for e in ex:
            by[e.get("category", "other")] = by.get(e.get("category", "other"), 0) + float(e.get("amount", 0))
        for c, v in sorted(by.items(), key=lambda x: -x[1])[:6]:
            lines.append(f"• {c}: {cur} {v:,.0f}")
        return "\n".join(lines)

    def _email_check(self, tr: dict) -> str:
        s3 = tr.get("s3", {}) if isinstance(tr.get("s3"), dict) else {}
        n = s3.get("unread", 0)
        top = s3.get("top", []) or []
        if not n:
            return "📭 Inbox zero — nothing unread. Nicely done."
        lines = [f"📬 **{n} unread** — top of the pile:", ""]
        for m in top[:5]:
            tag = {"action": "🔴", "waiting": "🟡", "fyi": "🔵"}.get(m.get("triage", ""), "⚪")
            lines.append(f"{tag} **{(m.get('subject') or '')[:70]}** — {(m.get('sender') or '')[:40]}")
        lines += ["", "Open **Inbox** to read, or say `triage my inbox` again after sync."]
        return "\n".join(lines)

    def _calendar_today(self, tr: dict) -> str:
        s1 = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        evs = s1.get("events", []) or []
        if not evs:
            return "📅 Nothing on the calendar today — a clear runway. Say `schedule lunch tomorrow 1pm` to add something."
        lines = ["📅 **Today:**", ""]
        for e in evs:
            t = (e.get("starts_at") or "")[11:16]
            loc = f" @ {e['location']}" if e.get("location") else ""
            lines.append(f"- **{t}** {e.get('title', '')}{loc}")
        return "\n".join(lines)

    def _calendar_create(self, tr: dict) -> str:
        s1 = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        if not s1.get("created"):
            return s1.get("error", "I couldn't create that event.") + " e.g. `schedule dentist friday 9am`."
        t = (s1.get("starts_at") or "")[:16].replace("T", " ")
        return f"📅 Scheduled **{s1.get('title', 'event')}** ({t} UTC). Say `my schedule` anytime to see the day."

    def _sys_status(self, tr: dict) -> str:
        svcs = tr.get("services", [])
        lines = ["**System status:**"]
        for s in svcs:
            dot = "🟢" if s["status"] == "online" else ("🟡" if s["status"] == "degraded" else "🔴")
            lines.append(f"{dot} {s['name']}: {s['status']}")
        return "\n".join(lines)

    def _terminal(self, tr: dict) -> str:
        r = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        if r.get("denied"):
            return f"🛑 I refused to run that — {r.get('error', 'safety policy')}."
        if r.get("dry_run"):
            return f"(dry-run) I would run: `{r.get('would', '')[:200]}`"
        if "exit_code" not in r:
            return f"Terminal error: {r.get('error', 'the command did not run')}."
        out = (r.get("output") or "").strip() or "(no output)"
        if len(out) > 1200:
            out = out[:1200] + "\n…"
        code = r.get("exit_code")
        head = f"exit {code}" if code != 0 else "exit 0"
        machine = r.get("machine", "local")
        tag = "" if machine == "local" else f" on **{machine}**"
        what = f"script **{r['script']}**" if r.get("script") else "command"
        return (f"**Ran {what}{tag}** in {r.get('duration_ms', 0)} ms · {head}"
                f" · {r.get('cwd', '')}\n\n```\n{out[:2400]}\n```")

    def _ollama_models(self, tr: dict) -> str:
        r = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        if not r.get("reachable") and not r.get("models"):
            return (f"I can't see Ollama at {r.get('base_url', 'localhost:11434')} — is it running? "
                     f"({r.get('error', 'unreachable')})")
        models = r.get("models", [])
        if not models:
            return f"Ollama is reachable at {r.get('base_url')} but has no models pulled yet. `ollama pull llama3.1` then ask me again."
        lines = [f"**Model room** — {len(models)} local model(s) at {r.get('base_url', '')}:", ""]
        for m in models[:12]:
            caps = ", ".join(m.get("capabilities", []))
            lines.append(f"• **{m['name']}** · {m.get('size', '?')} · {m.get('parameter_size', '')} "
                         f"{m.get('quantization', '')} · {caps}")
        if len(models) > 12:
            lines.append(f"… {len(models) - 12} more")
        if not r.get("reachable"):
            lines.append("\n(cached catalog — Ollama not answering right now)")
        return "\n".join(lines)

    def _feeds(self, tr: dict) -> str:
        r = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        items = r.get("items", [])
        if not items:
            return ("You're not following any feeds yet. Add one on the Feeds screen, or say "
                    "“follow https://hnrss.org/frontpage”.")
        lines = [f"**{len(items)} latest feed item(s):**", ""]
        for it in items[:8]:
            date = (it.get("published") or it.get("fetched_at") or "")[:10]
            lines.append(f"• **{it.get('title', '')[:110]}** — {it.get('feed_title') or ''} {date}".rstrip())
        return "\n".join(lines)

    def _weather(self, tr: dict) -> str:
        w = tr.get("s1", {}) if isinstance(tr.get("s1"), dict) else {}
        if not w.get("ok"):
            extra = " Enable it in Settings → Weather." if w.get("configured") is False else ""
            return f"No weather yet — {w.get('reason', 'unavailable')}.{extra}"
        lines = [f"**{w.get('place')}** · {w.get('temp_c')}°C (feels {w.get('feels_c')}°C), {w.get('condition')}, wind {w.get('wind_kmh')} km/h"]
        for d in w.get("today", [])[:3]:
            lines.append(f"• {d['date']}: {d.get('low_c')}–{d.get('high_c')}°C, {d.get('condition')}, rain {d.get('rain_pct')}%")
        return "\n".join(lines)

    def _web_search(self, tr: dict, user_text: str) -> str:
        results = tr.get("search_results", []) or []
        if results:
            lines = ["**Web search results:**", ""]
            for r in results[:5]:
                snip = (r.get("snippet") or "").strip()
                lines.append(f"- **{(r.get('title') or '')[:100]}** — {r.get('link', '')}")
                if snip:
                    lines.append(f"  _{snip[:180]}_")
            lines += ["", "Tap any link to open it. Want me to **read one for you**? Paste the URL."]
            return "\n".join(lines)
        err = tr.get("search_error", "") or "no results"
        return (f"I couldn't complete that web search right now ({err}). "
                "Try pasting a direct URL instead — I can read pages for you.")

    def _mission_status(self, tr: dict) -> str:
        missions = tr.get("missions", []) or []
        if not missions:
            return ("No missions yet. Say “make a mission to …” or open **Automations → Missions** "
                    "to plan one — then ask me again and I'll stream its progress here.")
        lines = ["**Your missions:**", ""]
        icon = {"done": "✅", "failed": "❌", "running": "🔄", "awaiting": "⏸", "cancelled": "✖"}
        for m in missions[:8]:
            st = m.get("status", "draft")
            steps = m.get("steps") or []
            done_n = sum(1 for s in steps if s.get("status") == "done")
            prog = f"{done_n}/{len(steps)}" if steps else "—"
            nxt = f" · next {m.get('next_run_at', '')[:16]}" if m.get("next_run_at") else ""
            lines.append(f"{icon.get(st, '📋')} **{(m.get('goal') or '')[:80]}** — {st} ({prog} steps){nxt}")
            if st in ("running", "awaiting") and steps:
                for s in steps[:6]:
                    mark = {"done": "✓", "running": "▸", "awaiting": "…", "failed": "✗"}.get(s.get("status"), "·")
                    note = f" — {s.get('note')[:60]}" if s.get("note") else ""
                    lines.append(f"    {mark} {s.get('label', '')}{note}")
        lines += ["", "Open **Automations → Missions** to start, pause, or schedule them."]
        return "\n".join(lines)

    def _help(self) -> str:
        return ("**Things I can do:**\n"
                "• **Plan** — “plan my day”, “what's overdue?”, “prioritize my tasks”\n"
                "• **Clients** — “review my clients”, “draft follow-ups”, “new project X”\n"
                "• **Career** — “optimize my resume”, “prep me for interviews”, “track application at Y”\n"
                "• **Personal** — “log mood 8”, “add expense 1500 food”, “journal: …”, “slept 11pm to 6am”\n"
                "• **Memory** — “remember that …”, “what do you remember about …”, “forget …”\n"
                "• **Search & missions** — “search the web for …”, “how are my missions?”\n"
                "• **System** — “system status”, “run backup”, “test telegram”\n"
                "• **Terminal** — “run `git status` in my terminal”, “run my backup-prod script”,\n"
                "  “which ollama models do I have?”, “switch to qwen2.5”\n"
                "• **Watch** — drop files in the inbox folder and AURA indexes + reacts (Settings)\n"
                "• **Feeds & weather** — “what's new on my feeds?”, “follow <rss url>”,”weather”\n"
                "• **Mail & calendar** — “check email”, “triage inbox”, “my schedule”,\n"
                "  “schedule lunch friday 1pm”, “brief me”, “evening briefing”")


class ModelRouter:
    """Routes generation across local LFM -> cloud -> builtin."""

    def __init__(self):
        self.ollama = OllamaClient()
        self.builtin = BuiltinEngine()
        self._ollama_ok: bool | None = None
        self._ollama_note = ""
        self._checked_at = 0.0

    @property
    def cloud(self) -> CloudClient:
        """Fresh client per access so settings changes apply without restart."""
        return get_cloud_client()

    def probe(self) -> dict:
        now = time.time()
        if self._ollama_ok is None or now - self._checked_at > 20:
            self._ollama_ok, self._ollama_note = self.ollama.healthy()
            self._checked_at = now
        cloud = self.cloud
        return {"local_lfm": {"online": self._ollama_ok, "note": self._ollama_note,
                              "model": self.ollama.model},
                "cloud": {"configured": cloud.configured(), "model": cloud.model,
                          "base": cloud.base, "provider": cloud.provider},
                "builtin": {"online": True, "note": "grounded composer"},
                "privacy": prefs.get("privacy")}

    def chain(self) -> list[str]:
        """Backend order honoring the privacy setting. Unknown modes fail closed to local-first."""
        mode = (prefs.get("privacy") or "local-first").lower()
        if mode == "cloud":
            return ["cloud", "ollama", "builtin"]
        if mode == "hybrid":
            return ["ollama", "cloud", "builtin"]
        return ["ollama", "builtin"]

    def embed_fn(self):
        """Return best embedding function (Ollama -> hashed)."""
        probe = self.probe()
        if probe["local_lfm"]["online"]:
            def _emb(text: str):
                model = prefs.get('ollama_embed_model') or config.OLLAMA_EMBED_MODEL
                v = self.ollama.embed(text, model=model)
                if valid_embedding(v) and len(v) >= 32 and any(v):
                    return Embedding(v, f"ollama:{model}")
                return Embedding(hashed_embed(text), "hashed:192")
            _emb._emb_name = f"ollama:{prefs.get('ollama_embed_model') or config.OLLAMA_EMBED_MODEL}"
            return _emb
        return hashed_embed

    def generate(self, messages: list[dict], stream_cb=None, purpose: str = "chat") -> tuple[str, str]:
        """Returns (text, model_name) following the privacy-ordered chain."""
        probe = self.probe()
        last_error = None
        for backend in self.chain():
            if backend == "ollama" and probe["local_lfm"]["online"]:
                try:
                    text = self.ollama.chat(messages, stream_cb=stream_cb, purpose=purpose)
                    if text.strip():
                        db.log_activity("run", "Local LFM generation", self.ollama.model, "general")
                        return text, f"ollama/{self.ollama.model}"
                except Exception as e:
                    last_error = e
                    db.log_activity("run", "Local LFM failed, continuing chain", str(e)[:120], "general", "warn")
            elif backend == "cloud" and probe["cloud"]["configured"]:
                try:
                    safe = [{**m, "content": scrub_secrets(m.get("content", ""))} for m in messages]
                    text = self.cloud.chat(safe, stream_cb=stream_cb, purpose=purpose)
                    if text.strip():
                        db.log_activity("run", "Cloud LFM generation", self.cloud.model, "general")
                        return text, f"cloud/{self.cloud.model}"
                except Exception as e:
                    last_error = e
                    db.log_activity("run", "Cloud failed, continuing chain", str(e)[:120], "general", "warn")
        # All backends failed - raise to let caller handle fallback with full context
        raise RuntimeError(f"All model backends failed: {last_error}")


router = ModelRouter()
