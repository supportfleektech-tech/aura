#!/usr/bin/env python3
"""Agent eval — golden tasks through real run_turn on scratch DBs.

Each case runs 1-2 chat turns against a FRESH seeded database with the model
chain forced offline (builtin composer only: deterministic, no network, fast).
Checks per case: intent, required tools fired, answer contains/must-not,
optional DB-state asserts, and a groundedness score (bold/number claims in
the answer must appear in tool outputs + user text + memories).

Run:  python3 scripts/eval_agent.py [--min 1.0] [--case ID] [--no-record]
Exit 1 when pass-rate drops below --min (default 1.0: any failure fails).
Scores persist to eval_runs in the DEV database for per-release tracking.

When ADDING intents/tools or tuning compose, update
backend/tests/agent_cases.json first (cases encode INTENDED behavior),
then make the agent pass.
"""
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / "backend" / "tests" / "agent_cases.json").read_text())

DEV_DB = os.environ.get("AURA_DB_PATH") or str(ROOT / "data" / "aura.db")
_tmp = tempfile.mkdtemp(prefix="eval-agent-")
os.environ["AURA_DB_PATH"] = os.path.join(_tmp, "eval.db")
sys.path.insert(0, str(ROOT / "backend"))

from app import db, config  # noqa: E402
from app import orchestrator as orch  # noqa: E402
from app.hermes import hermes  # noqa: E402
from app.inference import router as model_router  # noqa: E402
from app.memory import memory_engine  # noqa: E402
from app import calendar_sync as _cal  # noqa: E402

# ---- determinism: chain forced offline -> builtin composer only ----
_OFFLINE = {"local_lfm": {"online": False, "note": "eval-offline", "model": ""},
            "cloud": {"configured": False, "model": "", "base": "", "provider": ""},
            "builtin": {"online": True, "note": "grounded composer"},
            "privacy": "local-first"}
model_router.probe = lambda: _OFFLINE  # noqa: E731

# ---- tool-result capture for the groundedness checker (eval-only) ----
FIRED: dict = {}
_orig_exec = hermes.execute_tool
_orig_pseudo = orch.exec_pseudo


def _rec_exec(name, args=None, ctx=None, run_id=0):
    r = _orig_exec(name, args or {}, ctx or {}, run_id)
    try:
        FIRED[name] = r.get("data")
    except Exception:
        pass
    return r


def _rec_pseudo(name, args, ctx, run_id):
    res = _orig_pseudo(name, args, ctx, run_id)
    try:
        FIRED[name] = res
    except Exception:
        pass
    return res


hermes.execute_tool = _rec_exec  # type: ignore[method-assign]
orch.exec_pseudo = _rec_pseudo  # type: ignore[assignment]

# Static template copy that is not a factual claim (excluded from groundedness).
# Keep entries specific multi-word phrases: generic words here would mask real misses.
STATIC_OK = {"run now", "automation center", "inbox", "personal life panel",
             "things i can do", "your automations", "system status",
             "spending", "morning briefing", "evening briefing",
             "worth a look", "client workload review", "draft follow-ups",
             "overdue tasks", "related records", "open tasks",
             "search memory for …", "create a task to …"}


def _norm_span(b: str) -> str:
    b = b.strip().strip("\"'“”`").rstrip(":").strip()
    b = re.sub(r"^\d+\.\s+", "", b)  # leading list numbering: "1. Eval x" -> "Eval x"
    return b


def sse_events(body: str) -> dict:
    evs: dict = {}
    for part in body.split("\n\n"):
        name, data = None, ""
        for ln in part.split("\n"):
            if ln.startswith("event:"):
                name = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if name and data:
            evs.setdefault(name, []).append(json.loads(data))
    return evs


def _user_today():
    """Seed on the USER'S calendar day (prefs tz), matching _user_day windows —
    date.today() (UTC) can be a day off from e.g. Africa/Nairobi near midnight."""
    try:
        from app import prefs as _p
        return datetime.now(_p.user_tz()).date()
    except Exception:
        return date.today()


def seed_db() -> None:
    _ut = _user_today()
    tmr = (_ut + timedelta(days=1)).isoformat()
    db.run("INSERT INTO tasks (user_id,title,status,due_at,domain) VALUES (1,'Eval report','open',?,'general')", (tmr,))
    db.run("INSERT INTO tasks (user_id,title,status,due_at) VALUES (1,'Eval overdue filing','open','2026-09-01')")
    cid = db.run("INSERT INTO clients (user_id,name) VALUES (1,'EvalCorp')")
    db.run("INSERT INTO projects (user_id,name,client_id,status) VALUES (1,'EvalPortal',?,'active')", (cid,))
    memory_engine.store("Eval satellite", "the eval satellite codename is BlueKite",
                        "general", "semantic", "eval", 0.8, 0.7)
    cal_id = _cal.ensure_default_calendar()
    today = _ut.isoformat()
    _cal.create_event(cal_id, "Eval standup", f"{today}T09:00:00", f"{today}T09:30:00")
    db.run("INSERT INTO automations (user_id,name,trigger_kind,action_kind,status,next_run)"
           " VALUES (1,'Eval morning nudge','schedule','notify','active','2030-01-01T08:00:00')")
    db.run("INSERT INTO email_accounts (user_id,name,mode,status) VALUES (1,'EvalBox','sandbox','active')")
    db.run("DELETE FROM write_journal")  # seeded writes are not user actions


def seed_conversation(n: int) -> str:
    sid = "evalconv01"
    db.run("INSERT INTO sessions (id, user_id, title, domain) VALUES (?,?,?,?)",
           (sid, 1, "T-EvalConv long", "general"))
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        db.run("INSERT INTO messages (session_id, role, kind, content, meta_json) VALUES (?,?,?,?,?)",
               (sid, role, "text", f"T-EvalConv msg {i}",
                '{"intent": "task_list"}' if role == "assistant" else "{}"))
    return sid


def fresh_db(case_id: str) -> None:
    p = os.path.join(_tmp, f"{case_id}.db")
    if os.path.exists(p):
        os.remove(p)
    config.DB_PATH = p
    db.reset()
    db.init_db()
    seed_db()


def _words(s: str) -> list[str]:
    return [w for w in (re.sub(r"[^a-z0-9]", "", x) for x in s.casefold().split())
            if len(w) > 2]


def claims(text: str) -> tuple[list[str], list[float]]:
    bolds = []
    for b in re.findall(r"\*\*(.+?)\*\*", text):
        n = _norm_span(b)
        if len(n) > 2 and n.casefold() not in STATIC_OK:
            bolds.append(n)
    nums: list[float] = []
    for m in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text):
        try:
            nums.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return bolds, nums


def grounded_score(text: str, user_texts: list[str]) -> tuple[float, list[str]]:
    ground = json.dumps(FIRED, ensure_ascii=False, default=str) + "\n" + "\n".join(user_texts)
    try:
        mems = db.q("SELECT title, content FROM memories WHERE deleted_at IS NULL LIMIT 50")
        ground += "\n" + json.dumps(mems, ensure_ascii=False, default=str)
    except Exception:
        pass
    bolds, nums = claims(text)
    gnums = [float(m.replace(",", "")) for m in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", ground)]
    misses: list[str] = []
    total = len(bolds) + len(nums)
    if not total:
        return 1.0, []
    gfold = ground.casefold()
    for b in bolds:
        if b.casefold() in gfold:
            continue
        words = _words(b)
        if words and all(w in gfold for w in words):
            continue  # all significant words evidenced, different order/affixes
        misses.append(f"bold:{b[:60]}")
    for n in nums:
        if not any(abs(n - g) < 1e-9 for g in gnums):
            misses.append(f"num:{n:g}")
    return (total - len(misses)) / total, misses


def run_case(case: dict) -> dict:
    t0 = time.time()
    fresh_db(case["id"])
    sid = seed_conversation(case["seed_messages"]) if case.get("seed_messages") else None
    evs: dict = {}
    for text in case["turns"]:
        FIRED.clear()
        body = "".join(orch.run_turn(text, sid))
        evs = sse_events(body)
        plans = evs.get("plan", [])
        if plans:
            sid = plans[0].get("session_id", sid)
    exp = case.get("expect", {})
    fails: list[str] = []
    intent = (evs.get("plan", [{}])[0] or {}).get("intent")
    if exp.get("intent") and intent != exp["intent"]:
        fails.append(f"intent want={exp['intent']} got={intent}")
    fired = {t.get("tool") for t in evs.get("tool", [])}
    for tool in exp.get("tools", []):
        if tool not in fired:
            fails.append(f"tool {tool} never fired (fired={sorted(fired)})")
    text = ((evs.get("result", [{}])[0] or {}).get("text") or "")
    for s in exp.get("contains", []):
        if s not in text:
            fails.append(f"answer missing {s!r}")
    for s in exp.get("not", []):
        if s in text:
            fails.append(f"answer contains banned {s!r}")
    for chk in exp.get("db", []):
        try:
            row = db.qone(chk["sql"]) or {}
            got = row.get(chk["col"])
        except Exception as e:
            fails.append(f"db check {chk['sql'][:50]} errored: {e}")
            continue
        if got != chk["want"]:
            fails.append(f"db {chk['sql'][:60]} want={chk['want']!r} got={got!r}")
    gmin = float(exp.get("ground_min", 0.75))
    gscore, misses = grounded_score(text, case["turns"])
    if gscore < gmin:
        fails.append(f"grounded {gscore:.2f} < {gmin} misses={misses[:4]}")
    return {"id": case["id"], "ok": not fails, "fails": fails,
            "grounded": round(gscore, 3), "ms": int((time.time() - t0) * 1000),
            "answer": text[:300]}


def record_run(version: str, results: list[dict], ms: int) -> None:
    try:
        config.DB_PATH = DEV_DB
        db.reset()
        db.init_db()
        passed = sum(1 for r in results if r["ok"])
        g = sum(r["grounded"] for r in results) / len(results) if results else 0
        db.run("INSERT INTO eval_runs (version, suite, total, passed, acc, grounded, ms, details_json)"
               " VALUES (?,?,?,?,?,?,?,?)",
               (version, "agent", len(results), passed,
                round(passed / len(results), 4) if results else 0,
                round(g, 4), ms, db.jdump(results)))
        print(f"recorded: eval_runs version={version} {passed}/{len(results)}")
    except Exception as e:
        print(f"record skipped: {e}")


def main() -> int:
    args = sys.argv[1:]
    min_acc = float(args[args.index("--min") + 1]) if "--min" in args else 1.0
    only = args[args.index("--case") + 1] if "--case" in args else None
    norec = "--no-record" in args
    cases = [c for c in CASES["cases"] if not only or c["id"] == only]
    version = config.APP_VERSION
    t0 = time.time()
    results = []
    for c in cases:
        try:
            r = run_case(c)
        except Exception as e:
            r = {"id": c["id"], "ok": False, "fails": [f"EXCEPTION: {e!r}"[:300]],
                 "grounded": 0.0, "ms": 0, "answer": ""}
        results.append(r)
        mark = "ok " if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['id']} g={r['grounded']} {r['ms']}ms")
        for f in r["fails"]:
            print(f"         - {f}")
    passed = sum(1 for r in results if r["ok"])
    acc = passed / len(results) if results else 0
    total_ms = int((time.time() - t0) * 1000)
    print(f"agent eval: {passed}/{len(results)} correct ({acc:.1%}) in {total_ms}ms")
    if not norec:
        record_run(version, results, total_ms)
    return 0 if acc >= min_acc else 1


if __name__ == "__main__":
    sys.exit(main())
