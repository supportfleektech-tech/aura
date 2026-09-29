#!/usr/bin/env python3
"""AURA OS end-to-end live check — exercises every route + chat journey.

Usage:  python3 scripts/e2e_check.py [BASE_URL]
Default: http://127.0.0.1:8000   (backend must be running)

Self-cleaning: all test rows are prefixed E2E and deleted afterwards.
Exit code 0 = all green, 1 = failures. Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import time
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS, FAIL, WARN = [], [], []


def req(method, path, body=None, raw=None, ctype=None):
    data, headers = None, {}
    if raw is not None:
        data, headers = raw, {"Content-Type": ctype}
    elif body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    r = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            txt = resp.read().decode("utf-8", "ignore")
            try:
                return resp.status, json.loads(txt), {k.lower(): v for k, v in resp.headers.items()}
            except Exception:
                return resp.status, txt, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(txt), {k.lower(): v for k, v in e.headers.items()}
        except Exception:
            return e.code, txt, {k.lower(): v for k, v in e.headers.items()}


def sse(body: str) -> dict:
    evs: dict = {}
    for part in body.split("\n\n"):
        name, data = None, ""
        for ln in part.split("\n"):
            if ln.startswith("event:"):
                name = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if name and data:
            try:
                evs.setdefault(name, []).append(json.loads(data))
            except Exception:
                pass
    return evs


def chat(msg):
    st, body, _ = req("POST", "/api/chat/stream", {"message": msg})
    assert st == 200, f"chat HTTP {st}"
    ev = sse(body if isinstance(body, str) else "")
    intent = (ev.get("plan") or [{}])[0].get("intent", "?")
    res = (ev.get("result") or [{}])[0]
    text = res.get("text") or "".join(t.get("text", "") for t in ev.get("token", []))
    return intent, text


def check(name, fn):
    import traceback
    try:
        fn()
        PASS.append(name)
        print(f"  ✓ {name}")
    except AssertionError as e:
        # Bare `assert` failures give an empty message, which hides which step
        # broke. Report the source line so CI output is actionable.
        line = ""
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            frame = tb[-1]
            line = f" @{Path(frame.filename).name}:{frame.lineno} `{frame.line}`"
        FAIL.append((name, (str(e)[:220] + line).strip()))
        print(f"  ✗ {name} — {str(e)[:220]}{line}")
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {str(e)[:200]}"))
        print(f"  ✗ {name} — {type(e).__name__}: {str(e)[:200]}")


def warn(name, msg):
    WARN.append((name, msg))
    print(f"  ! {name} — {msg}")


print(f"AURA E2E  →  {BASE}\n== meta ==")
def _t_health():
    s, d, _ = req("GET", "/api/health")
    assert s == 200 and d["ok"] is True and len(d["services"]) >= 13, d
    lfm = [x for x in d["services"] if x["name"] == "Local LFM"][0]
    assert "cloud:" in lfm["detail"], lfm["detail"]
    emb = [x for x in d["services"] if x["name"] == "Embeddings"][0]
    assert "active=" in emb["detail"], emb["detail"]
    names = {x["name"] for x in d["services"]}
    assert {"Model Room", "Terminal", "Feeds", "Weather"} <= names, names
check("health ok + machine-room services", _t_health)


def _t_system():
    s, d, _ = req("GET", "/api/system")
    assert s == 200 and "runs_24h" in d["metrics"] and d["version"] == "1.15.0"
check("system metrics", _t_system)
def _t_me_tools():
    s1, d1, _ = req("GET", "/api/me")
    s2, d2, _ = req("GET", "/api/tools")
    assert s1 == 200 and d1["name"], d1
    assert s2 == 200 and len(d2["tools"]) >= 20, len(d2.get("tools", []))
check("me + tools", _t_me_tools)


def _t_dash():
    s, d, _ = req("GET", "/api/dashboard")
    assert s == 200
    for k in ("priorities", "counts", "projects", "insights"):
        assert k in d, f"missing {k}"
    assert d["insights"].get("sleep") != "7h 48m", "fabricated sleep!"
    assert d["insights"].get("mood_delta") != "+12%", "fabricated delta!"
    assert "spending_dir" in d["insights"]
check("dashboard real insights", _t_dash)

print("== search + sessions ==")


def _t_search():
    s, d, _ = req("GET", "/api/search?q=Brian")
    assert s == 200 and isinstance(d["results"], list) and d["ms"] >= 0
check("universal search", _t_search)


def _t_search_filters():
    s, d, _ = req("GET", "/api/search?q=e2e&type=task")
    assert s == 200 and all(r["type"] == "task" for r in d["results"]), d
    for r in d["results"]:
        assert r.get("matched"), r
    s, d2, _ = req("GET", "/api/search?q=e2e&type=memory")
    assert s == 200 and all(r["type"] == "memory" for r in d2["results"]), d2
    s, d3, _ = req("GET", "/api/search?q=e2e&frm=2000-01-01&to=2030-01-01")
    assert s == 200 and isinstance(d3["results"], list), d3
check("search type filter + matched explainability", _t_search_filters)


def _t_sessions():
    s, d, _ = req("GET", "/api/sessions")
    assert s == 200 and isinstance(d["sessions"], list)
    s, d, _ = req("POST", "/api/sessions", {"title": "E2E session"})
    assert s == 200 and d["id"]
    s, d, _ = req("GET", f"/api/sessions/{d['id']}")
    assert s == 200 and d["messages"] == []
check("sessions crud", _t_sessions)

print("== chat journeys ==")
JOURNEYS = [
    ("hello there", "greet", None),
    ("what can you do", "help", None),
    ("plan my day", "plan_day", None),
    ("remind me to E2E ping", "task_create", "E2E ping"),
    ("show my tasks", "task_list", "E2E ping"),
    ("done with E2E ping", "task_toggle", "completed"),
    ("new project E2E Proj", "project_create", "E2E Proj"),
    ("new client E2E Client", "client_create", "E2E Client"),
    ("how are my projects doing", "project_status", None),
    ("review my clients", "client_review", None),
    ("remember that E2E marker is 42", "memory_store", None),
    ("what do you remember about E2E marker", "memory_search", "42"),
    ("forget the E2E marker", "memory_search", None),
    ("resume tips for ATS", "resume_help", None),
    ("interview prep for nurse role", "interview_prep", "Nurse"),
    ("log mood 8/10", "health_log", None),
    ("journal E2E reflection line", "journal", None),
    ("add expense 500 lunch", "finance", None),
    ("run a backup", "backup_run", "Backup complete"),
    ("gateway status", "gateway", "Gateway status"),
    ("show my automations", "automation", "automation"),
    ("system status", "system_status", "System status"),
    ("prepare a meeting brief for Brian", "meeting_prep", "Meeting brief"),
    ("draft follow-ups", "followup_draft", None),
    ("brief me", "briefing", None),
    ("check my email", "email_check", None),
    ("what is on my calendar today", "calendar_today", None),
    ("schedule E2E lunch tomorrow 1pm", "calendar_create", "Scheduled"),
]
for msg, intent, keyword in JOURNEYS:
    def _t(m=msg, i=intent, k=keyword):
        got, text = chat(m)
        assert got == i, f"intent {got} != {i} :: {text[:100]}"
        assert len(text) > 10, "empty answer"
        if k:
            assert k.lower() in text.lower(), f"missing {k!r} :: {text[:120]}"
    check(f"chat:{intent} :: {msg[:34]}", _t)


def _t_toggle_state():
    s, d, _ = req("GET", "/api/tasks?q=E2E%20ping")
    assert s == 200 and d["tasks"] and d["tasks"][0]["status"] == "completed"
    req("DELETE", f"/api/tasks/{d['tasks'][0]['id']}")
check("toggle persisted + cleanup", _t_toggle_state)

def _t_e2e_event_cleanup():
    s, d, _ = req("GET", "/api/calendar/week")
    assert s == 200 and isinstance(d["events"], list)
    for e in d["events"]:
        if "E2E lunch" in (e.get("title") or ""):
            r, _, _ = req("DELETE", f"/api/calendar/events/{e['id']}")
            assert r == 200, r
check("calendar journey cleanup", _t_e2e_event_cleanup)


def _t_engine():
    s, body, _ = req("POST", "/api/chat/stream", {"message": "hello engine check"})
    ev = sse(body if isinstance(body, str) else "")
    res = (ev.get("result") or [{}])[0]
    assert res.get("engine") in ("builtin", "ollama", "cloud"), res
    assert isinstance(res.get("redacted_memories"), int), res
check("result engine field", _t_engine)

print("== approvals ==")


def _t_approvals():
    s, d, _ = req("GET", "/api/approvals")
    assert s == 200
    if not d["approvals"]:
        warn("approvals", "none pending (no overdue tasks) — skipped")
        return
    a = d["approvals"][0]
    req("POST", "/api/gateway/email/connect", {"account": "e2e"})
    s, r, _ = req("POST", f"/api/approvals/{a['id']}/resolve",
                  {"decision": "approved", "drafts": [{"to": f"E2E-{int(time.time())}", "subject": f"E {int(time.time())}", "body": "E2E edited"}]})
    assert s == 200 and r["decision"] == "approved", (s, r)
    ok_path = len(r.get("sent", [])) >= 1 or any(
        "already sent" in str(x).lower() or "duplicate" in str(x).lower() for x in (r.get("errors") or []))
    assert ok_path, r  # fresh send OR an honest dedupe — both prove the pipeline
    bad, _, _ = req("POST", "/api/approvals/99999/resolve", {"decision": "maybe"})
    assert bad == 400, f"bad decision -> {bad}"
check("approval resolve + validation", _t_approvals)

print("== crud sweeps ==")


def _t_tasks():
    s, t, _ = req("POST", "/api/tasks", {"title": "E2E task", "priority": "HIGH", "status": "In Progress"})
    assert s == 200 and t["id"]
    tid = t["id"]
    s, d, _ = req("GET", "/api/tasks?q=E2E%20task")
    assert d["tasks"] and d["tasks"][0]["priority"] == "high" and d["tasks"][0]["status"] == "in_progress"
    s, _, _ = req("PATCH", f"/api/tasks/{tid}", {"status": "completed"})
    assert s == 200
    s, d, _ = req("GET", "/api/tasks/overdue/list")
    assert s == 200 and "overdue" in d
    req("DELETE", f"/api/tasks/{tid}")
check("tasks crud + normalize", _t_tasks)


def _t_clients_projects():
    s, c, _ = req("POST", "/api/clients", {"name": "E2E Client2", "org": "E2E Org"})
    assert s == 200 and c["id"]
    cid = c["id"]
    s, d, _ = req("GET", f"/api/clients/{cid}")
    assert s == 200 and d["name"] == "E2E Client2" and "projects" in d
    req("PATCH", f"/api/clients/{cid}", {"health": "watch"})
    s, p, _ = req("POST", "/api/projects", {"name": "E2E Proj2", "client_id": cid})
    assert s == 200 and p["id"]
    pid = p["id"]
    s, m, _ = req("POST", f"/api/projects/{pid}/milestones", {"title": "E2E MS"})
    assert s == 200 and m["id"]
    req("PATCH", f"/api/projects/{pid}", {"progress": 50})
    s, d, _ = req("GET", "/api/projects")
    assert any(x["id"] == pid and x["milestones"] for x in d["projects"])
    req("DELETE", f"/api/projects/{pid}")
    req("DELETE", f"/api/clients/{cid}")
    # cleanup chat-created rows too
    s, d, _ = req("GET", "/api/projects")
    for x in d["projects"]:
        if x["name"].startswith("E2E "):
            req("DELETE", f"/api/projects/{x['id']}")
    s, d, _ = req("GET", "/api/clients")
    for x in d["clients"]:
        if x["name"].startswith("E2E "):
            req("DELETE", f"/api/clients/{x['id']}")
check("clients + projects crud", _t_clients_projects)


def _t_career():
    s, d, _ = req("GET", "/api/career/overview")
    assert s == 200 and "pipeline" in d
    s, d, _ = req("POST", "/api/career/resumes/analyze",
                  {"text": "E2E Tester\nBuilt dashboards. Increased revenue by 20% using Python.",
                   "job_description": "Python dashboards revenue", "name": "E2E"})
    assert s == 200 and d["ats_score"] >= 0 and d["resume_id"]
    rid = d["resume_id"]
    s, _, h = req("GET", f"/api/career/resumes/{rid}/download")
    assert s == 200 and "attachment" in h.get("content-disposition", "")
    s, a, _ = req("POST", "/api/career/applications", {"company": "E2E Corp", "role": "Tester"})
    assert s == 200 and a["id"]
    req("PATCH", f"/api/career/applications/{a['id']}", {"stage": "interview"})
    s, iv, _ = req("POST", "/api/career/interviews", {"company": "E2E", "role": "Tester", "score": 8})
    assert s == 200 and iv["id"]
    s, d, _ = req("GET", "/api/career/interviews/questions?role=Nurse")
    assert s == 200 and len(d["questions"]) >= 5 and d["role"] == "Nurse"
    s, d, _ = req("GET", "/api/career/blocks")
    assert s == 200
    s, d, _ = req("POST", "/api/career/blocks/plan", {})
    assert s == 200
    s, b, _ = req("POST", "/api/career/blocks",
                  {"title": "E2E block", "starts_at": "2030-01-01T09:00:00", "ends_at": "2030-01-01T10:00:00"})
    assert s == 200 and b["id"]
    req("DELETE", f"/api/career/blocks/{b['id']}")
check("career full loop", _t_career)


def _t_personal():
    s, d, _ = req("GET", "/api/personal/overview")
    assert s == 200 and isinstance(d["spending_total"], (int, float))
    s, _, _ = req("POST", "/api/personal/journal", {"body": "E2E journal", "mood": "8/10"})
    assert s == 200
    s, _, _ = req("POST", "/api/personal/mood", {"mood": "7", "note": "E2E"})
    assert s == 200
    s, _, _ = req("POST", "/api/personal/expenses", {"amount": 250, "category": "food", "note": "E2E"})
    assert s == 200
    s, g, _ = req("POST", "/api/personal/goals", {"title": "E2E goal", "target": "done"})
    assert s == 200 and g["id"]
    req("PATCH", f"/api/personal/goals/{g['id']}", {"progress": 50})
    s, h, _ = req("POST", "/api/personal/habits", {"name": "E2E habit"})
    assert s == 200 and h["id"]
    req("POST", f"/api/personal/habits/{h['id']}/done", {})
check("personal full loop", _t_personal)


def _t_memory():
    s, m, _ = req("POST", "/api/memories", {"title": "E2E mem", "content": "E2E marker content", "importance": 0.9})
    assert s == 200 and m["id"]
    mid = m["id"]
    s, d, _ = req("POST", "/api/memories/search", {"query": "E2E marker", "limit": 5})
    assert s == 200 and any("E2E" in r["title"] for r in d["results"])
    s, d, _ = req("GET", "/api/memories?q=E2E")
    assert s == 200 and d["stats"]["total"] >= 1
    req("PATCH", f"/api/memories/{mid}", {"importance": 0.5})
    req("DELETE", f"/api/memories/{mid}")
    s, d, _ = req("POST", "/api/memories/forget", {"topic": "E2E marker"})
    assert s == 200 and d["forgotten"] >= 0
check("memory full loop", _t_memory)


def _t_auto():
    s, a, _ = req("POST", "/api/automations", {"name": "E2E auto", "trigger_kind": "manual", "action_kind": "notify",
                                               "trigger": {}, "action": {"message": "E2E"}})
    assert s == 200 and a["id"]
    aid = a["id"]
    req("PATCH", f"/api/automations/{aid}", {"status": "paused"})
    req("PATCH", f"/api/automations/{aid}", {"status": "active"})
    s, d, _ = req("POST", f"/api/automations/{aid}/run", {})
    assert s == 200 and "ran" in d
    req("DELETE", f"/api/automations/{aid}")
check("automations full loop", _t_auto)


def _t_activity_notes():
    s, d, _ = req("GET", "/api/activity?limit=5")
    assert s == 200 and isinstance(d["activity"], list)
    s, d, _ = req("GET", "/api/activity?kind=task&limit=5")
    assert s == 200
    s, d, _ = req("GET", "/api/notifications")
    assert s == 200 and "unread" in d
    if d["notifications"]:
        req("POST", f"/api/notifications/{d['notifications'][0]['id']}/read", {})
    s, _, _ = req("POST", "/api/notifications/read-all", {})
    assert s == 200
check("activity + notifications", _t_activity_notes)


def _t_gateway():
    s, d, _ = req("GET", "/api/gateway/status")
    assert s == 200 and len(d["integrations"]) == 6 and isinstance(d["events"], list)
    tg = [x for x in d["integrations"] if x["platform"] == "telegram"][0]
    assert tg["mode"] == "sandbox"
    s, _, _ = req("POST", "/api/gateway/telegram/connect",
                  {"account": "E2E", "config": {"bot_token": "E2ESECRET"}})
    assert s == 200
    s, d, _ = req("GET", "/api/gateway/status")
    assert "E2ESECRET" not in json.dumps(d), "secret leaked in status!"
    s, _, _ = req("POST", "/api/gateway/telegram/connect", {"mode": "live"})
    assert s == 200
    req("POST", "/api/gateway/slack/disconnect", {"forget": True})
    s, _, _ = req("POST", "/api/gateway/slack/connect", {"mode": "live"})
    assert s == 400, "live without creds must 400"
    s, _, _ = req("POST", "/api/gateway/telegram/connect", {"mode": "sandbox"})
    assert s == 200
    s, d, _ = req("POST", "/api/gateway/telegram/test", {})
    assert s == 200 and d["ok"] is True and d["latency_ms"] >= 1
    s, d, _ = req("POST", "/api/gateway/simulate", {"platform": "telegram", "text": "E2E hello"})
    assert s == 200 and d["event_id"]
    s, d, _ = req("POST", "/api/gateway/simulate",
                  {"platform": "telegram", "text": "E2E live path", "send_live": True})
    assert s == 200 and d.get("sent") is True
    req("POST", "/api/gateway/telegram/disconnect", {"forget": True})
    s, d, _ = req("GET", "/api/gateway/status")
    tg = [x for x in d["integrations"] if x["platform"] == "telegram"][0]
    assert tg["configured"] is False
check("gateway loop", _t_gateway)


def _t_files():
    boundary = "----E2EBOUNDARY"
    payload = ("--%s\r\nContent-Disposition: form-data; name=\"files\"; filename=\"e2e.txt\"\r\n"
               "Content-Type: text/plain\r\n\r\nE2E file body for indexing\r\n--%s--\r\n" % (boundary, boundary)).encode()
    s, d, _ = req("POST", "/api/files/upload", raw=payload, ctype=f"multipart/form-data; boundary={boundary}")
    assert s == 200 and d["files"] and d["files"][0]["indexed_chars"] > 0, d
    fid = d["files"][0]["id"]
    s, d, _ = req("GET", "/api/files")
    assert s == 200 and any(f["id"] == fid for f in d["files"])
    s, body, _ = req("GET", f"/api/files/{fid}")
    assert s == 200 and "E2E file body" in body
    s, _, _ = req("GET", "/api/files/999999")
    assert s == 404
check("files upload+index+download", _t_files)


def _t_voice_backup():
    s, _, _ = req("POST", "/api/voice/log", {"transcript": "E2E voice", "domain": "general"})
    assert s == 200
    s, d, _ = req("GET", "/api/voice/config")
    assert s == 200 and d["language"] == "en-KE"
    s, d, _ = req("POST", "/api/backup/run", {"target": "local"})
    assert s == 200 and d["ok"] and len(d["sha256"]) == 64
    s, d, _ = req("GET", "/api/backup/history")
    assert s == 200 and len(d["files"]) >= 1
    s, d, _ = req("POST", "/api/backup/restore", {"file": "nope.tar.gz"})
    assert s == 200 and d["ok"] is False
check("voice + backup", _t_voice_backup)


def _t_hermes():
    s, d, _ = req("POST", "/api/hermes/tools/system.status", {"args": {}})
    assert s == 200 and d.get("ok") in (True, None) or "services" in str(d)
    s, _, _ = req("POST", "/api/hermes/tools/comms.send", {"args": {}})
    assert s == 403, f"R2 passthrough must be blocked, got {s}"
    s, _, _ = req("POST", "/api/hermes/tools/nope.nope", {"args": {}})
    assert s == 404
    s, d, _ = req("POST", "/api/hermes/skills/meeting_prep", {"args": {"who": "Brian"}})
    assert s == 200
check("hermes gating + skills", _t_hermes)


def _t_negatives():
    s, _, _ = req("POST", "/api/chat/stream", {"message": "   "})
    assert s == 400, f"empty chat -> {s}"
    s, _, _ = req("POST", "/api/chat/stream", {"message": "x" * 10})
    assert s == 200
    s, _, _ = req("POST", "/api/chat/stream", {"message": "x" * 60000})
    assert s == 413, f"oversize chat -> {s}"
    s, _, _ = req("POST", "/api/chat/stream", {"message": "hi", "attachments": [{"a": 1}] * 11})
    assert s == 400
check("negatives", _t_negatives)

print("== v1.2 batch ==")

def _t_sleep():
    s, body, _ = req("POST", "/api/chat/stream", {"message": "E2E probe slept 11pm to 6am"})
    assert s == 200 and "7.0h" in body, body[:300]
    s, d, _ = req("POST", "/api/personal/sleep", {"hours": 99})
    assert s == 400, f"bad sleep -> {s}"
    s, d, _ = req("GET", "/api/dashboard")
    assert s == 200 and d["insights"]["sleep"].endswith("h") and d["insights"]["sleep_state"] in ("Good", "Okay", "Low")
    s, d, _ = req("GET", "/api/personal/overview")
    assert s == 200 and any("hours" in r for r in d["sleep"])
check("sleep chat+api+dashboard", _t_sleep)


def _t_webhook():
    s, a, _ = req("POST", "/api/automations", {"name": "E2E webhook", "trigger_kind": "schedule",
                                               "trigger": {"every": "daily"}, "action_kind": "webhook",
                                               "action": {"url": BASE + "/api/voice/log", "payload": {"e2e": True}}})
    assert s == 200 and a["id"], a
    aid = a["id"]
    s, d, _ = req("POST", f"/api/automations/{aid}/run", {})
    mine = next(r for r in d["ran"] if r["id"] == aid)
    assert s == 200 and mine["ok"], mine
    s, d, _ = req("POST", "/api/automations", {"name": "E2E bad", "trigger_kind": "schedule",
                                               "trigger": {}, "action_kind": "webhook", "action": {"url": "gopher://x"}})
    assert s == 400, f"bad webhook -> {s}"
    req("PATCH", f"/api/automations/{aid}", {"action_config": {"url": BASE + "/api/voice/log", "secret": "e2e-secret"}})
    s, d, _ = req("GET", "/api/automations")
    mine = next(a for a in d["automations"] if a["id"] == aid)
    import json as _js
    assert _js.loads(mine["action_config"])["secret"] == "***", mine["action_config"]
    req("DELETE", f"/api/automations/{aid}")
check("webhook self-fire + validation", _t_webhook)


def _t_plugins():
    s, d, _ = req("GET", "/api/tools")
    names = [x["name"] for x in d["tools"]]
    assert s == 200 and "plugin.text_stats" in names and "plugin.unit_convert" in names
    assert "plugin.text_stats" in d["plugins"]["loaded"]
    s, d, _ = req("POST", "/api/hermes/tools/plugin.unit_convert", {"args": {"value": 5, "from": "km", "to": "mi"}})
    assert s == 200 and abs(d["data"]["result"] - 3.1069) < 0.001, d
check("plugin tools live", _t_plugins)


def _t_embeddings():
    s, d, _ = req("GET", "/api/system")
    emb = next((x for x in d["services"] if x["name"] == "Embeddings"), None)
    assert s == 200 and emb and "active=" in emb["detail"], d
check("embeddings health", _t_embeddings)


def _t_push():
    sub = {"endpoint": "https://e2e.local/sub1", "keys": {"p256dh": "D", "auth": "A"}}
    s, d, _ = req("POST", "/api/push/subscribe", sub)
    assert s == 200 and d["ok"]
    s, d, _ = req("POST", "/api/push/test", {"title": "E2E", "body": "ping"})
    assert s == 200 and {"sent", "dropped", "skipped"} <= set(d), d
    s, d, _ = req("GET", "/api/push/vapid-public-key")
    assert s == 200 and "configured" in d
    req("POST", "/api/push/unsubscribe", {"endpoint": sub["endpoint"]})
check("push subscribe+test+unsubscribe", _t_push)


def _t_voicelive():
    s, d, _ = req("GET", "/api/voice/status")
    assert s == 200 and "whisper_model" in d
    if not d["stt_installed"]:
        warn("voice-live", "whisper not installed — skipped")
        return
    import io, struct, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<" + "h" * 8000, *([0] * 8000)))
    boundary = "----E2EVOICE"
    payload = (("--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"silence.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n" % boundary).encode() + buf.getvalue() +
               ("\r\n--%s--\r\n" % boundary).encode())
    s, d, _ = req("POST", "/api/voice/transcribe", raw=payload, ctype=f"multipart/form-data; boundary={boundary}")
    assert s == 200 and "text" in d, (s, d)
    s, body, h = req("POST", "/api/voice/speak", {"text": "End to end voice check"})
    if s == 503:
        warn("voice-live", "piper not installed — TTS skipped")
    else:
        assert s == 200 and h.get("content-type") == "audio/wav" and body[:4] == "RIFF", (s, h)
check("voice live transcribe+speak", _t_voicelive)


def _t_pwa():
    s, d, _ = req("GET", "/manifest.webmanifest")
    assert s == 200 and d["short_name"] == "AURA", (s, d)
    s, body, _ = req("GET", "/sw.js")
    assert s == 200 and "showNotification" in body
    s, body, h = req("GET", "/icons/icon-192.png")
    assert s == 200 and h.get("content-type") == "image/png"
check("PWA manifest+sw+icons", _t_pwa)


def _t_docx():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>E2E docx unique WQ12</w:t></w:r></w:p></w:body></w:document>')
    boundary = "----E2EDOCX"
    payload = (("--%s\r\nContent-Disposition: form-data; name=\"files\"; filename=\"e2e.docx\"\r\n"
                "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n" % boundary).encode() +
               buf.getvalue() + ("\r\n--%s--\r\n" % boundary).encode())
    s, d, _ = req("POST", "/api/files/upload", raw=payload, ctype=f"multipart/form-data; boundary={boundary}")
    assert s == 200 and d["files"][0]["indexed_chars"] > 0, d
    s, d, _ = req("POST", "/api/memories/search", {"query": "WQ12", "limit": 3})
    assert s == 200 and any("WQ12" in h["content"] for h in d["results"]), d
check("docx upload+index+search", _t_docx)


def _t_replica():
    s, d, _ = req("GET", "/api/backup/history")
    assert s == 200 and "litestream" in d and d["litestream"]["enabled"] is False
check("backup history replica field", _t_replica)
print("== v1.3 batch ==")

def _t_settings_shape():
    s, d, _ = req("GET", "/api/settings")
    assert s == 200 and "values" in d and "secrets" in d and "sources" in d, (s, d)
    assert d["values"]["cloud_provider"] == "openrouter", d["values"]
    assert "openrouter_key" in d["secrets"] and "openrouter_key" not in d["values"]
check("settings GET shape", _t_settings_shape)


def _t_settings_roundtrip():
    s, d, _ = req("PATCH", "/api/settings", {"voice_rate": 1.25, "chat_timestamps": True})
    assert s == 200 and d["values"]["voice_rate"] == 1.25, (s, d)
    s, _, _ = req("PATCH", "/api/settings", {"privacy": "mars"})
    assert s == 400, s
    s, _, _ = req("PATCH", "/api/settings", {"nope": 1})
    assert s == 400, s
    s, d, _ = req("GET", "/api/voice/config")
    assert s == 200 and d["language"] == "en-KE", d
    s, d, _ = req("PATCH", "/api/settings", {"voice_lang": "sw-KE"})
    assert s == 200
    s, d, _ = req("GET", "/api/voice/config")
    assert s == 200 and d["language"] == "sw-KE", d
check("settings PATCH roundtrip + validation", _t_settings_roundtrip)


def _t_settings_secrets():
    s, d, _ = req("PATCH", "/api/settings", {"openrouter_key": "sk-or-E2EMARKER"})
    assert s == 200 and d["secrets"]["openrouter_key"] is True, (s, d)
    assert "E2EMARKER" not in json.dumps(d)
    s, d, _ = req("GET", "/api/settings")
    assert "E2EMARKER" not in json.dumps(d)
    s, d, _ = req("PATCH", "/api/settings", {"openrouter_key": ""})
    assert s == 200 and d["secrets"]["openrouter_key"] is False, (s, d)
check("settings secrets write-only", _t_settings_secrets)


def _t_cloud_models():
    s, d, _ = req("GET", "/api/cloud/models")
    assert s == 200 and d["count"] >= 8 and all("id" in m for m in d["models"]), (s, d)
check("cloud models catalog", _t_cloud_models)


def _t_cloud_test_unconfigured():
    s, d, _ = req("POST", "/api/cloud/test", {"provider": "custom", "model": "x"})
    assert s == 200 and d["ok"] is False and "missing" in d["error"], (s, d)
    s, _, _ = req("POST", "/api/cloud/test", {"provider": "mars"})
    assert s == 400, s
check("cloud test unconfigured + bad provider", _t_cloud_test_unconfigured)


def _t_cloud_fallback_chain():
    req("PATCH", "/api/settings", {"privacy": "hybrid", "cloud_provider": "openai",
                                   "openai_key": "E2E-FAKE", "openai_model": "nope"})
    try:
        intent, text = chat("hello e2e cloud fallback")
        assert text.strip(), "empty reply"
    finally:
        req("DELETE", "/api/settings")
check("cloud fail-open fallback chain", _t_cloud_fallback_chain)


def _t_settings_reset():
    s, d, _ = req("DELETE", "/api/settings")
    assert s == 200 and d["values"]["privacy"] == "local-first", (s, d)
    assert d["values"]["voice_rate"] == 1.0 and d["values"]["chat_timestamps"] is False
check("settings DELETE reset", _t_settings_reset)



print("== connections ==")

def _t_briefings_e2e():
    s, d, _ = req("POST", "/api/briefings", {"name": "E2E Brief", "kind": "morning"})
    assert s == 200 and d["id"], (s, d)
    bid = d["id"]
    try:
        s, run, _ = req("POST", f"/api/briefings/{bid}/run", {})
        assert s == 200 and run["output"].strip(), (s, run)
        s, runs, _ = req("GET", "/api/briefings/runs/list")
        assert s == 200 and len(runs["runs"]) >= 1
        s, _, _ = req("POST", "/api/briefings/run-now", {"kind": "evening"})
        assert s == 200, s
        s, _, _ = req("POST", "/api/briefings", {"name": "x", "kind": "nope"})
        assert s == 400, s
        s, _, _ = req("PATCH", "/api/briefings/99999999", {"name": "x"})
        assert s == 404, s
    finally:
        req("DELETE", f"/api/briefings/{bid}")
check("briefings crud + run + run-now + validation", _t_briefings_e2e)


def _t_mail_e2e():
    s, a, _ = req("POST", "/api/mail/accounts", {"name": "E2E Box"})
    assert s == 200 and a["id"], (s, a)
    aid = a["id"]
    try:
        s, accts, _ = req("GET", "/api/mail/accounts")
        assert s == 200 and any(x["id"] == aid for x in accts["accounts"])
        s, sy, _ = req("POST", f"/api/mail/accounts/{aid}/sync", {})
        assert s == 200 and sy["ok"] and sy["new"] == 8, (s, sy)
        s, sy2, _ = req("POST", f"/api/mail/accounts/{aid}/sync", {})
        assert sy2["new"] == 0
        s, t, _ = req("POST", "/api/mail/triage", {"account_id": aid})
        assert s == 200 and t["triaged"] >= 6, (s, t)
        s, em, _ = req("GET", f"/api/mail/emails?account_id={aid}")
        assert s == 200 and len(em["emails"]) == 8 and "body" not in em["emails"][0]
        mid = em["emails"][0]["id"]
        s, full, _ = req("GET", f"/api/mail/emails/{mid}")
        assert s == 200 and "body" in full
        req("PATCH", f"/api/mail/emails/{mid}", {"seen": True, "triage": "done"})
        s, em2, _ = req("GET", f"/api/mail/emails?account_id={aid}&unread_only=true")
        assert len(em2["emails"]) == 7, (s, em2)
        s, _, _ = req("PATCH", f"/api/mail/emails/{mid}", {"triage": "nope"})
        assert s == 400, s
        s, _, _ = req("GET", "/api/mail/emails?triage=nope")
        assert s == 400, s
        s, _, _ = req("POST", "/api/mail/accounts", {"name": "E2E Live", "mode": "live"})
        assert s == 400, s
    finally:
        req("DELETE", f"/api/mail/accounts/{aid}")
check("mail sandbox sync + triage + reader + validation", _t_mail_e2e)


def _t_calendar_e2e():
    s, cals, _ = req("GET", "/api/calendar/calendars")
    assert s == 200 and any(c["source"] == "local" for c in cals["calendars"])
    s, e, _ = req("POST", "/api/calendar/events", {
        "title": "E2E Sync Test",
        "starts_at": "2030-01-02T10:00:00Z",
        "ends_at": "2030-01-02T11:00:00Z"})
    assert s == 200 and e["id"], (s, e)
    eid = e["id"]
    try:
        s, ev, _ = req("GET", "/api/calendar/events?start=2030-01-01T00:00:00Z"
                             "&end=2030-01-03T00:00:00Z")
        assert s == 200 and any(x["id"] == eid for x in ev["events"]), (s, ev)
        s, _, _ = req("PATCH", f"/api/calendar/events/{eid}", {"location": "E2E Room"})
        assert s == 200, s
        s, w, _ = req("GET", "/api/calendar/week")
        assert s == 200 and isinstance(w["events"], list)
        s, _, _ = req("POST", "/api/calendar/events",
                      {"title": "bad", "starts_at": "nope", "ends_at": "x"})
        assert s == 400, s
        s, land, _ = req("GET", "/api/calendar/google/landing?code=E2E123")
        assert s == 200 and "E2E123" in land, (s, str(land)[:100])
    finally:
        req("DELETE", f"/api/calendar/events/{eid}")
check("calendar crud + week + validation + oauth landing", _t_calendar_e2e)


def _t_sync_e2e():
    s, b, _ = req("GET", "/api/sync/export?device=e2e")
    assert s == 200 and b.get("format") == "aura-sync/1", (s, str(b)[:120])
    s, r, _ = req("POST", "/api/sync/import", {"bundle": b, "device": "e2e-self"})
    assert s == 200 and r["inserted"] == 0, (s, r)
    s, _, _ = req("POST", "/api/sync/import", {"bundle": {"format": "nope"}, "device": "e2e"})
    assert s == 400, s
    s, log, _ = req("GET", "/api/sync/log")
    assert s == 200 and isinstance(log["log"], list) and len(log["log"]) >= 1
check("sync export + self-import + bad bundle + log", _t_sync_e2e)



print("== onboarding ==")

def _t_onboarding_e2e():
    s, me0, _ = req("GET", "/api/me")
    assert s == 200 and me0["name"], (s, me0)
    s, v0, _ = req("GET", "/api/settings")
    assert s == 200
    orig = v0["values"]
    try:
        s, me, _ = req("PATCH", "/api/me", {"name": "E2E Onboard", "location": "E2E Town"})
        assert s == 200 and me["name"] == "E2E Onboard" and me["location"] == "E2E Town", (s, me)
        s, _, _ = req("PATCH", "/api/me", {"nickname": "x"})
        assert s == 400, s
        s, _, _ = req("PATCH", "/api/me", {})
        assert s == 400, s
        s, r, _ = req("PATCH", "/api/settings", {"onboarded": True, "domain_career": False,
                                                  "timezone": "Europe/Paris"})
        assert s == 200, (s, r)
        s, v1, _ = req("GET", "/api/settings")
        assert v1["values"]["onboarded"] is True and v1["values"]["domain_career"] is False
        assert v1["values"]["timezone"] == "Europe/Paris"
        s, _, _ = req("PATCH", "/api/settings", {"timezone": "Mars/Olympus"})
        assert s == 400, s
    finally:
        restore = {"name": me0["name"]}
        if me0.get("role"):
            restore["role"] = me0["role"]
        if me0.get("location"):
            restore["location"] = me0["location"]
        req("PATCH", "/api/me", restore)
        req("PATCH", "/api/settings", {"onboarded": orig["onboarded"],
                                          "domain_career": orig["domain_career"],
                                          "timezone": orig["timezone"]})
check("onboarding identity + prefs + validation", _t_onboarding_e2e)


def _t_proactive_e2e():
    s, r, _ = req("GET", "/api/proactive")
    assert s == 200 and "opportunities" in r, (s, r)
    s, r, _ = req("POST", "/api/proactive/scan", {})
    assert s == 200 and {"opportunities", "notified"} <= set(r), (s, r)
    for o in r["opportunities"]:
        assert {"key", "type", "title", "detail", "reasons", "score"} <= set(o), o
    if r["opportunities"]:
        k = r["opportunities"][0]["key"]
        s, d, _ = req("PATCH", f"/api/proactive/{k}/dismiss", {"dismissed": True})
        assert s == 200 and d.get("key") == k and d.get("dismissed") is True, (s, d)
        req("PATCH", f"/api/proactive/{k}/dismiss", {"dismissed": False})
    s, _, _ = req("PATCH", "/api/proactive/nope:nope/dismiss", {"dismissed": True})
    assert s == 404, s
    yday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    s, t, _ = req("POST", "/api/tasks", {"title": "e2e proactive follow up", "due_at": yday})
    assert s in (200, 201) and t.get("id"), (s, t)
    tid, pkey = t["id"], f"followup-task-{t['id']}"
    try:
        s, r, _ = req("POST", "/api/proactive/scan", {})
        assert pkey in [o["key"] for o in r["opportunities"]], pkey
        o = [x for x in r["opportunities"] if x["key"] == pkey][0]
        assert o["action"]["kind"] == "open" and o["action"]["view"] == "inbox", o
        s, d, _ = req("POST", f"/api/proactive/{pkey}/snooze", {"hours": 24})
        assert s == 200, (s, d)
        s, r, _ = req("POST", "/api/proactive/scan", {})
        assert pkey not in [o["key"] for o in r["opportunities"]]
        s, _, _ = req("PATCH", f"/api/proactive/{pkey}/dismiss", {"dismissed": False})
        assert s == 200, s
        s, r, _ = req("POST", "/api/proactive/scan", {})
        assert pkey in [o["key"] for o in r["opportunities"]]
        s, d, _ = req("POST", f"/api/proactive/{pkey}/act", {})
        assert s == 200 and d["kind"] == "open", (s, d)
        s, d, _ = req("POST", "/api/proactive/nope:nope/act", {})
        assert s == 200 and d.get("gone") is True, (s, d)
        s, d, _ = req("GET", "/api/proactive/resolved")
        assert s == 200 and isinstance(d["resolved"], list), (s, d)
    finally:
        req("DELETE", f"/api/tasks/{tid}")
    s, r, _ = req("POST", "/api/proactive/scan", {})
    assert pkey not in [o["key"] for o in r["opportunities"]]
    s, d, _ = req("GET", "/api/proactive/resolved")
    assert pkey in [x["key"] for x in d["resolved"]], d
    s, a, _ = req("POST", "/api/automations",
                  {"name": "e2e proactive", "trigger_kind": "manual", "action_kind": "proactive"})
    assert s in (200, 201) and a.get("id"), (s, a)
    s, run, _ = req("POST", f"/api/automations/{a['id']}/run", {})
    assert s == 200, (s, run)
    req("DELETE", f"/api/automations/{a['id']}")
check("proactive list + scan + dismiss + snooze + act + resolve + automation", _t_proactive_e2e)


def _t_proactive_mission_e2e():
    # 3 identical manual tasks -> repeated_manual opportunity -> mission action
    ids = []
    for _ in range(3):
        s, t, _ = req("POST", "/api/tasks", {"title": "e2e repeat chore mission"})
        assert s in (200, 201) and t.get("id"), (s, t)
        ids.append(t["id"])
    mid = None
    try:
        s, r, _ = req("POST", "/api/proactive/scan", {})
        assert s == 200, (s, r)
        opp = next((o for o in r["opportunities"]
                    if o["type"] == "repeated_manual" and "e2e repeat chore" in o["title"]), None)
        assert opp is not None and opp["action"]["kind"] == "mission", r
        assert opp["action"]["every"] == "weekly", opp["action"]
        s, a, _ = req("POST", f"/api/proactive/{opp['key']}/act", {})
        assert s == 200 and a.get("ok") and a.get("kind") == "mission", (s, a)
        assert a["mission"].get("id"), a
        mid = a["mission"]["id"]
        s, m, _ = req("GET", f"/api/missions/{mid}")
        assert s == 200 and m.get("goal"), (s, m)
        assert "weekly" in (m.get("schedule_json") or "") and m.get("next_run_at"), m
        assert m["status"] in ("running", "draft", "awaiting"), m
        s, d, _ = req("GET", "/api/proactive/resolved")
        assert opp["key"] in [x["key"] for x in d["resolved"]], d
    finally:
        for tid in ids:
            req("DELETE", f"/api/tasks/{tid}")
        if mid:
            req("POST", f"/api/missions/{mid}/control", {"action": "cancel"})
check("proactive → scheduled mission (repeated chore)", _t_proactive_mission_e2e)


def _t_analytics_e2e():
    s, r, _ = req("GET", "/api/analytics/overview")
    assert s == 200, (s, r)
    assert {"spending", "tasks", "habits", "sleep", "mood", "activity", "forecast"} <= set(r), r
    assert {"by_currency", "by_day", "by_category"} <= set(r["spending"]), r["spending"]
    assert {"done_14d", "created_30", "done_30", "completion_rate", "overdue_now", "by_status"} <= set(r["tasks"]), r["tasks"]
    assert {"spending_next_7d", "task_velocity_per_day", "tasks_next_7d", "sleep_trend", "mood_trend"} <= set(r["forecast"]), r["forecast"]
check("analytics overview shape", _t_analytics_e2e)


def _t_messaging_e2e():
    s, r, _ = req("POST", "/api/gateway/telegram/poll", {})
    assert s == 200 and "ok" in r and ("inbound" in r or "error" in r), (s, r)
    s, r, _ = req("POST", "/api/gateway/telegram/webhook", {"ping": 1})
    assert s == 200 and r.get("handled") is False, (s, r)
    s, r, _ = req("GET", "/api/gateway/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1")
    assert s == 403, (s, r)
    s, r, _ = req("POST", "/api/gateway/whatsapp/webhook", {"entry": []})
    assert s == 200 and r.get("ok") is True and r.get("inbound") == [], (s, r)
check("messaging poll + webhooks shape", _t_messaging_e2e)


def _t_voiceloop_e2e():
    s, r, _ = req("GET", "/api/voice/loop/status")
    assert s == 200, (s, r)
    assert {"wake_available", "wake_model", "wake_enabled", "whisper", "tts", "ws"} <= set(r), r
    assert r["ws"] == "/api/voice/loop"
check("voice loop status shape", _t_voiceloop_e2e)


def _t_missions_e2e():
    s, r, _ = req("POST", "/api/missions", {"goal": "E2E weekly review"})
    assert s == 200 and len(r["steps"]) == 3 and r["needs_review"] is False, (s, r)
    mid = r["id"]
    s, r, _ = req("GET", "/api/missions")
    assert s == 200 and any(m["id"] == mid for m in r["missions"]), (s, r)
    s, r, _ = req("POST", f"/api/missions/{mid}/control", {"action": "launch"})
    assert s == 400, (s, r)
    s, r, _ = req("POST", "/api/missions", {"goal": "E2E x", "planner": "bogus"})
    assert s == 400, (s, r)
    s, r, _ = req("POST", f"/api/missions/{mid}/control", {"action": "start"})
    assert s == 200 and r["status"] == "running", (s, r)
    s, r, _ = req("POST", f"/api/missions/{mid}/control", {"action": "cancel"})
    assert s == 200 and r["status"] == "cancelled", (s, r)
check("missions plan + control", _t_missions_e2e)


def _t_home_e2e():
    s, r, _ = req("GET", "/api/home/status")
    assert s == 200 and r.get("platform") == "homeassistant" and "configured" in r, (s, r)
    s, r, _ = req("GET", "/api/home/entities")
    assert s == 200 and "entities" in r and "mode" in r, (s, r)
    s, r, _ = req("POST", "/api/home/service", {"domain": "", "service": ""})
    assert s == 200 and r.get("ok") is False, (s, r)
check("home status + entities shape", _t_home_e2e)


def _t_look_e2e():
    s, r, _ = req("GET", "/api/vision/status")
    assert s == 200, (s, r)
    assert {"ollama_model", "ollama_online", "cloud_configured", "available"} <= set(r), r
check("vision status shape", _t_look_e2e)


def _t_webread_e2e():
    s, body, _ = req("POST", "/api/chat/stream", {"message": "read https://example.com/ for me"})
    assert s == 200, (s, body[:200])
    assert "web_read" in body and "event: result" in body, body[:300]
check("chat reads a pasted link (web_read)", _t_webread_e2e)


def _t_websearch_e2e():
    s, body, _ = req("POST", "/api/chat/stream", {"message": "search the web for Nairobi weather"})
    assert s == 200, (s, body[:200])
    ev = sse(body if isinstance(body, str) else "")
    intent = (ev.get("plan") or [{}])[0].get("intent", "?")
    assert intent == "web_search", intent
    assert "event: result" in body, body[:300]
    res = (ev.get("result") or [{}])[0]
    assert len(res.get("text", "")) > 10, res
check("chat web search (web_search intent)", _t_websearch_e2e)


def _t_mission_status_e2e():
    s, r, _ = req("POST", "/api/missions", {"goal": "e2e mission status probe plan my day"})
    assert s == 200 and r.get("id"), (s, r)
    mid = r["id"]
    try:
        s, body, _ = req("POST", "/api/chat/stream", {"message": "how are my missions going"})
        assert s == 200, (s, body[:200])
        ev = sse(body if isinstance(body, str) else "")
        intent = (ev.get("plan") or [{}])[0].get("intent", "?")
        assert intent == "mission_status", intent
        assert "event: mission" in body, body[:300]
        mids = [m.get("id") for m in ev.get("mission", [])]
        assert mid in mids, mids
    finally:
        req("POST", f"/api/missions/{mid}/control", {"action": "cancel"})
check("chat mission status streams progress", _t_mission_status_e2e)


def _t_sched_e2e():
    s, r, _ = req("POST", "/api/missions", {"goal": "e2e schedule probe plan my day"})
    assert s == 200, (s, r)
    mid = r["id"]
    s, r, _ = req("POST", f"/api/missions/{mid}/schedule", {"every": "daily"})
    assert s == 200 and "daily" in r["schedule_json"] and r["next_run_at"], (s, r)
    s, r, _ = req("POST", f"/api/missions/{mid}/schedule", {"every": "minutely"})
    assert s == 400, (s, r)
    s, r, _ = req("GET", f"/api/missions/{mid}/runs")
    assert s == 200 and isinstance(r["runs"], list), (s, r)
    s, r, _ = req("POST", f"/api/missions/{mid}/schedule", {"every": "off"})
    assert s == 200 and r["next_run_at"] == "", (s, r)
check("mission schedule round-trip + runs", _t_sched_e2e)


def _t_undo_dry_e2e():
    s, t, _ = req("POST", "/api/tasks", {"title": "e2e-undo-probe"})
    assert s in (200, 201) and t.get("id"), (s, t)
    s, u, _ = req("GET", "/api/undo")
    assert s == 200 and u.get("undoable"), (s, u)
    s, r, _ = req("POST", "/api/undo", {"steps": 1})
    assert s == 200 and r["undone"] and "removed" in r["undone"][0]["result"], (s, r)
    s, lst, _ = req("GET", "/api/tasks?q=e2e-undo-probe")
    assert s == 200 and not [x for x in lst["tasks"] if x["id"] == t["id"]], (s, lst)
    s, d, _ = req("POST", "/api/hermes/tools/tasks.create/dry-run",
                  {"args": {"title": "e2e-dry-probe"}, "ctx": {}})
    assert s == 200 and d.get("dry_run") and d["result"]["title"] == "e2e-dry-probe", (s, d)
    s, lst, _ = req("GET", "/api/tasks?q=e2e-dry-probe")
    assert s == 200 and not lst["tasks"], (s, lst)
    s, a, _ = req("POST", "/api/automations", {"name": "e2e dryrun", "trigger_kind": "manual",
                                               "action_kind": "notify", "action": {"title": "x", "body": "y"}})
    assert s in (200, 201) and a.get("id"), (s, a)
    try:
        s, f, _ = req("POST", f"/api/automations/{a['id']}/run?dry_run=true", {})
        assert s == 200 and f.get("dry_run") and f["fired"]["ok"], (s, f)
        assert any("push:" in x for x in f["blocked"]), (s, f)
        s, g, _ = req("GET", "/api/automations")
        row = [x for x in g["automations"] if x["id"] == a["id"]][0]
        assert row["last_run"] is None, row
    finally:
        req("DELETE", f"/api/automations/{a['id']}")
check("undo roundtrip + tool/automation dry-run", _t_undo_dry_e2e)


def _t_sessions_e2e():
    s, c, _ = req("POST", "/api/sessions", {"title": "e2e sess probe"})
    assert s in (200, 201) and c.get("id"), (s, c)
    sid = c["id"]
    try:
        s, r, _ = req("POST", "/api/chat/stream", {"message": "e2e hello world", "session_id": sid})
        assert s == 200, s
        s, _, _ = req("PATCH", f"/api/sessions/{sid}", {"title": "e2e sess renamed"})
        assert s == 200, s
        s, p, _ = req("POST", f"/api/sessions/{sid}/pin", {})
        assert s == 200 and p.get("pinned") is True, (s, p)
        s, b, _ = req("POST", f"/api/sessions/{sid}/branch", {})
        assert s in (200, 201) and b.get("id") and b["id"] != sid, (s, b)
        bs = b["id"]
        s, d, _ = req("GET", f"/api/sessions/{bs}")
        assert s == 200 and len(d["messages"]) >= 2, (s, d)
        s, k, _ = req("POST", f"/api/sessions/{sid}/compact", {})
        assert s == 200 and k.get("compacted") is False, (s, k)
        s, lst, _ = req("GET", "/api/sessions?q=e2e%20sess")
        assert s == 200 and len(lst["sessions"]) >= 2, (s, lst)
        assert lst["sessions"][0]["pinned"] in (1, True), lst
        req("DELETE", f"/api/sessions/{bs}")
    finally:
        req("DELETE", f"/api/sessions/{sid}")
    s, _, _ = req("PATCH", "/api/sessions/nope", {"title": "x"})
    assert s == 404, s
check("session ops + branch + compact + search", _t_sessions_e2e)


print("== costs ==")


def _t_costs_e2e():
    s, d, _ = req("GET", "/api/costs")
    assert s == 200 and "today" in d and "month" in d and "budgets" in d, (s, d)
    assert set(d["today"]) >= {"calls", "cost_usd", "unknown_pricing"}, d["today"]
    s, c, _ = req("GET", "/api/costs/calls?limit=5")
    assert s == 200 and isinstance(c.get("calls"), list), (s, c)
    s, p, _ = req("PATCH", "/api/settings", {"cost_daily_cap_usd": 1.0})
    assert s == 200 and p["values"]["cost_daily_cap_usd"] == 1.0, (s, p)
    s, d, _ = req("GET", "/api/costs")
    assert d["budgets"]["daily_cap_usd"] == 1.0, d
    req("PATCH", "/api/settings", {"cost_daily_cap_usd": 0.0})
check("costs summary + calls + budget prefs", _t_costs_e2e)


print("== vision ==")


def _t_vision_e2e():
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000a49444154789c63000100000500010d0a2db4"
                        "0000000049454e44ae426082")
    boundary = "----E2EVISION"
    payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"e2e.png\"\r\n"
               f"Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
    s, d, _ = req("POST", "/api/files/upload", raw=payload, ctype=f"multipart/form-data; boundary={boundary}")
    assert s == 200 and d["files"], d
    fid = d["files"][0]["id"]
    s, d, _ = req("POST", f"/api/files/{fid}/analyze", {"question": "what is this?"})
    assert s in (200, 503), (s, d)
    if s == 503:
        assert "vision" in str(d).lower(), d
    else:
        assert d.get("description") and d.get("model"), d
    s, d, _ = req("GET", f"/api/files/{fid}/analyses")
    assert s == 200 and isinstance(d.get("analyses"), list), (s, d)
    s, _, _ = req("POST", "/api/files/999999/analyze", {})
    assert s == 404, s
    s, _, _ = req("POST", "/api/files/999999/analyze", {"question": "x" * 600})
    assert s == 404, s
    s, body, _ = req("POST", "/api/chat/stream", {"message": "e2e look at this",
                                                  "attachments": [{"id": fid, "name": "e2e.png"}]})
    assert s == 200, s
    ev = sse(body if isinstance(body, str) else "")
    res = (ev.get("result") or [{}])[0]
    assert "Attached images:" in res.get("text", ""), res
    assert [e["status"] for e in ev.get("vision", [])] == ["analyzing", "unavailable"], ev.get("vision")
    s, d, _ = req("GET", "/api/files")
    row = [f for f in d["files"] if f["id"] == fid][0]
    assert row.get("analysis_count") == 0, row
check("vision analyze + history + validation", _t_vision_e2e)


print("== voice v2 ==")


def _t_voice_v2_e2e():
    s, d, _ = req("GET", "/api/voice/engines")
    # browser, piper, kokoro, edge — kokoro was added in v1.15 and must stay listed
    # even when its assets are absent, so the UI can explain how to get it.
    assert s == 200 and [e["id"] for e in d["engines"]] == ["browser", "piper", "kokoro", "edge"], (s, d)
    assert len(d["emotions"]) == 6, d
    # Look engines up by id, not index — adding an engine shifts every position.
    by_id = {e["id"]: e for e in d["engines"]}
    assert len(by_id["edge"]["voices"]) == 8, d
    assert len(by_id["kokoro"]["voices"]) >= 2, d
    s, _, _ = req("POST", "/api/voice/speak", {"text": "x", "engine": "nope"})
    assert s == 400, s
    s, _, _ = req("POST", "/api/voice/speak", {"text": "  ", "engine": "piper"})
    assert s == 400, s
    req("PATCH", "/api/settings", {"privacy": "local-first"})
    try:
        s, d, _ = req("POST", "/api/voice/speak", {"text": "hi", "engine": "edge"})
        assert s == 403, (s, d)
        s, _, _ = req("PATCH", "/api/settings", {"privacy": "hybrid"})
        assert s == 200, s
        s, body, headers = req("POST", "/api/voice/speak", {"text": "Jambo! Voice check one two.",
                                                             "engine": "edge", "emotion": "cheerful"})
        assert s == 200 and len(body) > 1000, (s, len(body) if isinstance(body, str) else body)
        assert headers.get("content-type") == "audio/mpeg", headers
    finally:
        req("PATCH", "/api/settings", {"privacy": "local-first"})
check("voice engines + speak validation + privacy gate + live edge", _t_voice_v2_e2e)


# ================= v1.14 machine room =================
print("== machine room ==")


def _t_ollama_e2e():
    s, d, _ = req("GET", "/api/ollama/status")
    assert s == 200 and {"reachable", "model_count", "chat_model", "auto_sync", "base_url"} <= set(d), d
    s, d, _ = req("GET", "/api/ollama/models")
    assert s == 200 and isinstance(d["models"], list), d
    s, d, _ = req("POST", "/api/ollama/sync", {})
    assert s in (200, 502), s  # 502 = honest offline answer when no ollama on this box
    if s == 502:
        assert d.get("error"), d
    s, d, _ = req("POST", "/api/ollama/default", {"role": "chat", "model": "ghost:not-there"})
    assert s == 400, (s, d)
check("ollama model room status + validation", _t_ollama_e2e)


def _t_terminal_e2e():
    s, cfg, _ = req("GET", "/api/terminal/config")
    assert s == 200 and "enabled" in cfg, cfg
    s, d, _ = req("POST", "/api/terminal/exec", {"command": "echo e2e-term-ok"})
    assert s == 200 and d.get("ok") and "e2e-term-ok" in d.get("output", ""), (s, d)
    assert d.get("risk") in ("safe", "guarded"), d
    s, d, _ = req("POST", "/api/terminal/exec", {"command": "rm -rf / --no-preserve-root"})
    assert s == 200 and d.get("denied") is True, d
    s, d, _ = req("POST", "/api/terminal/exec", {"command": "mkfs.ext4 /dev/sda1"})
    assert s == 200 and d.get("denied") is True, d
    s, d, _ = req("GET", "/api/terminal/history?limit=5")
    assert s == 200 and any("e2e-term-ok" in r["command"] for r in d["runs"]), d
    denied = [r for r in d["runs"] if r["status"] == "denied"]
    assert denied, "denied runs must be audited too"
check("terminal exec + denial + audit trail", _t_terminal_e2e)


def _t_terminal_chat_e2e():
    intent, text = chat("run `echo e2e-through-chat` in the terminal")
    assert intent == "terminal_run", intent
    assert "e2e-through-chat" in text, text[:200]
    assert "exit 0" in text, text[:200]
check("chat → terminal → real shell output", _t_terminal_chat_e2e)


def _t_machines_e2e():
    s, d, _ = req("PUT", "/api/terminal/machines", {"machines": [{"name": "e2ebox", "host": "user@10.0.0.9"}]})
    assert s == 200 and any(m["name"] == "e2ebox" for m in d["machines"]), d
    s, d, _ = req("PUT", "/api/terminal/machines", {"machines": [{"name": "bad", "host": "rm -rf /; evil"}]})
    assert s == 400, (s, d)
    s, d, _ = req("POST", "/api/terminal/exec", {"command": "echo x", "machine": "ghost"})
    assert s == 200 and "unknown machine" in d.get("error", ""), d
    s, d, _ = req("PUT", "/api/terminal/machines", {"machines": []})
    assert s == 200 and len(d["machines"]) == 1, d
check("machines register + host validation", _t_machines_e2e)


def _t_feeds_e2e():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>E2E Feed</title>'
           b'<item><guid>e2e-1</guid><title>E2E feed item one</title>'
           b'<link>http://127.0.0.1:1/x</link><pubDate>' + now.encode() + b'</pubDate></item>'
           b'</channel></rss>')

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(rss)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{port}/rss"
        s, d, _ = req("POST", "/api/feeds", {"url": url})
        assert s == 200 and d.get("items", 0) >= 1, (s, d)
        fid = d["id"]
        s, d, _ = req("GET", "/api/feeds")
        assert s == 200 and any(f["id"] == fid for f in d["feeds"]), d
        assert any("E2E feed item one" in i["title"] for i in d["items"]), d["items"][:2]
        s, d, _ = req("POST", "/api/feeds/refresh", {})
        assert s == 200 and d["new_items"] == 0, d  # dedupe by guid
        s, _, _ = req("DELETE", f"/api/feeds/{fid}")
        assert s == 200, s
        s, d, _ = req("POST", "/api/feeds", {"url": "javascript:alert(1)"})
        assert s == 400, (s, d)
    finally:
        srv.shutdown()
check("feeds follow + dedupe + validation", _t_feeds_e2e)


def _t_weather_calls_e2e():
    s, d, _ = req("GET", "/api/weather")
    assert s == 200 and ("reason" in d or d.get("ok")), d
    tx = "You: e2e call test\nAURA: Received, all systems nominal."
    s, d, _ = req("POST", "/api/voice/calls", {"transcript": tx, "mode": "browser"})
    assert s == 200 and d.get("id"), (s, d)
    cid = d["id"]
    s, d, _ = req("GET", "/api/voice/calls?limit=5")
    assert s == 200 and any(c["id"] == cid for c in d["calls"]), d
    s, d, _ = req("GET", f"/api/voice/calls/{cid}")
    assert s == 200 and d["turns"] == 1, d
    s, _, _ = req("DELETE", f"/api/voice/calls/{cid}")
    assert s == 200, s
check("weather off-state + call save/list/get/delete", _t_weather_calls_e2e)


def _t_auto_kinds_e2e():
    s, d, _ = req("POST", "/api/automations", {"name": "E2E auto-term", "trigger_kind": "manual",
                                                "action_kind": "terminal", "action": {"command": "echo e2e-auto-fired"}})
    assert s == 200 and d.get("id"), (s, d)
    aid = d["id"]
    s, d, _ = req("POST", f"/api/automations/{aid}/run", {})
    assert s == 200, (s, d)
    seen = False
    for _ in range(20):  # poll: scheduler may consume the fire before/after us
        s, d, _ = req("GET", "/api/terminal/history?limit=10")
        if any(r["source"] == "automation" and "e2e-auto-fired" in r["command"] for r in d["runs"]):
            seen = True
            break
        import time as _t
        _t.sleep(0.4)
    assert seen, "terminal automation never showed up in the audit trail"
    s, d, _ = req("POST", "/api/automations", {"name": "E2E auto-bad", "trigger_kind": "manual",
                                               "action_kind": "terminal", "action": {"command": "rm -rf /"}})
    assert s == 400 and "dangerous" in str(d), (s, d)
    req("DELETE", f"/api/automations/{aid}")
check("automation terminal action fires + dangerous refused", _t_auto_kinds_e2e)


def _t_ollama_om_e2e():
    intent, text = chat("list my ollama models")
    assert intent == "ollama_models", intent
    assert ("Model room" in text) or ("can't see Ollama" in text) or ("no models" in text.lower()), text[:200]
check("chat ollama model inventory (online or honest off)", _t_ollama_om_e2e)


# ================= v1.15 fortress layer =================
print("== fortress ==")


def _t_guard_e2e():
    r = urllib.request.Request(
        BASE + "/api/tasks", method="POST",
        data=json.dumps({"title": "E2E-fort-guard"}).encode(),
        headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
    try:
        urllib.request.urlopen(r, timeout=30)
        raise AssertionError("cross-site POST was allowed — guard is broken!")
    except urllib.error.HTTPError as e:
        assert e.code == 403, f"expected 403, got {e.code}"
    # same-origin + originless must still work
    s, d, _ = req("POST", "/api/tasks", {"title": "E2E-fort-passthru"})
    assert s == 200, (s, d)
    req("DELETE", f"/api/tasks/{d['id']}")
check("origin guard blocks cross-site mutations", _t_guard_e2e)


def _t_scripts_e2e():
    s, d, _ = req("POST", "/api/scripts", {"name": "e2e-fort", "command": "echo e2e-script-live",
                                            "description": "e2e"})
    assert s == 200 and d.get("id"), (s, d)
    sid = d["id"]
    s, d, _ = req("POST", f"/api/scripts/{sid}/run", {})
    assert s == 200 and d.get("ok") and "e2e-script-live" in d.get("output", ""), (s, d)
    assert d.get("script") == "e2e-fort", d
    s, d, _ = req("POST", "/api/scripts", {"name": "e2e-bad", "command": "rm -rf /"})
    assert s == 400, (s, d)
    intent, text = chat("run my e2e-fort script")
    assert intent == "terminal_run", intent
    assert "e2e-script-live" in text and "Ran script" in text, text[:200]
    s, d, _ = req("GET", "/api/scripts")
    assert s == 200 and any(x["name"] == "e2e-fort" and x["run_count"] >= 2 for x in d["scripts"]), d
    req("DELETE", f"/api/scripts/{sid}")
check("script library: save/run/deny/chat + counters", _t_scripts_e2e)


def _t_watch_e2e():
    import os as _os
    import time as _tm
    # Ask the server where it actually watches. Hardcoding <repo>/data/inbox
    # only works when AURA_DATA_DIR is unset, so this failed on any isolated run.
    s, w, _ = req("GET", "/api/watch")
    inbox = (w.get("paths") or [w.get("default_dir")])[0]
    assert s == 200 and inbox, w
    _os.makedirs(inbox, exist_ok=True)
    name = f"e2e-watch-{int(_tm.time())}.txt"
    fpath = _os.path.join(inbox, name)
    with open(fpath, "w") as fh:
        fh.write(f"e2e watch probe {name}\n")
    try:
        s, d, _ = req("POST", "/api/watch/scan", {})
        assert s == 200 and d.get("new", 0) >= 1, (s, d)
        s, d, _ = req("GET", "/api/watch")
        hit = [r for r in d["recent"] if r["path"].endswith(name)]
        assert hit and hit[0]["ingested"], d["recent"][:3]
        s, d, _ = req("POST", "/api/watch/scan", {})  # unchanged → silent
        assert s == 200 and d.get("new", 0) == 0 and d.get("changed", 0) == 0, d
        s, d, _ = req("PUT", "/api/watch/paths", {"paths": ["/definitely/not/real"]})
        assert s == 400, d
    finally:
        _os.remove(fpath)
        s, d, _ = req("POST", "/api/watch/reset", {})
        assert s == 200
check("folder watch: scan, index, dedupe, validation", _t_watch_e2e)


def _t_mcheck_e2e():
    s, d, _ = req("GET", "/api/terminal/check?machine=local")
    assert s == 200 and d.get("ok"), d
    s, d, _ = req("GET", "/api/terminal/check?machine=ghosty")
    assert s == 200 and "unknown machine" in str(d.get("error", "")), d
check("machine liveness check", _t_mcheck_e2e)


print("\n================ SUMMARY ================")
print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}   WARN: {len(WARN)}")
for n, e in FAIL:
    print(f"  FAIL {n}: {e}")
sys.exit(1 if FAIL else 0)
