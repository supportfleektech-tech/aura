#!/usr/bin/env python3
"""AURA OS production-readiness check — deployment posture, not behavior.

E2E (scripts/e2e_check.py) proves the app *works*; this proves it is *shippable*:
versions consistent, prod build present, deploy files in place, data dir healthy,
DB integral, services online, backups fresh, secrets sane.

Usage:  python3 scripts/prod_check.py [BASE_URL]   (default http://127.0.0.1:8000)
Exit code 0 = ready (warnings allowed), 1 = failures. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL, WARN = [], [], []


def check(name, fn):
    try:
        msg = fn()
        PASS.append(name)
        print(f"  PASS {name}" + (f" — {msg}" if msg else ""))
    except AssertionError as e:
        FAIL.append(name)
        print(f"  FAIL {name} — {e}")
    except Exception as e:  # noqa: BLE001 — a crashing check is a failure
        FAIL.append(name)
        print(f"  FAIL {name} — error: {e}")


def warn(name, msg):
    WARN.append(name)
    print(f"  WARN {name} — {msg}")


def req(path, timeout=15):
    r = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        raise AssertionError(f"unreachable ({e})")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------- local files ---
def _t_versions():
    cfg = _read("backend/app/config.py")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', cfg)
    assert m, "APP_VERSION not found in backend/app/config.py"
    v = m.group(1)
    pkg = json.loads(_read("frontend/package.json"))
    assert pkg.get("version") == v, f"package.json {pkg.get('version')} != {v}"
    foot = _read("frontend/src/App.tsx")
    assert f"v{v}" in foot, f"App.tsx footer missing v{v}"
    e2e = _read("scripts/e2e_check.py")
    assert f'== "{v}"' in e2e, f"e2e version assert missing {v}"
    clog = _read("docs/CHANGELOG.md")
    assert f"## v{v} " in clog or f"## v{v}\n" in clog, f"CHANGELOG missing v{v} entry"
    return f"v{v} consistent (config/pkg/footer/e2e/changelog)"


def _t_dist():
    dist = os.path.join(ROOT, "frontend", "dist")
    assert os.path.isdir(dist), "frontend/dist missing — run: npm run build"
    idx = os.path.join(dist, "index.html")
    assert os.path.isfile(idx), "frontend/dist/index.html missing — stale build?"
    for f in ("manifest.webmanifest", "sw.js", "icons/icon-192.png"):
        assert os.path.isfile(os.path.join(dist, f)), f"dist missing {f}"
    return "index + manifest + sw + icons present"


def _t_deploy_files():
    for f in ("Dockerfile", "docker-compose.yml", "entrypoint.sh",
              "litestream.yml", ".github/workflows/ci.yml"):
        assert os.path.isfile(os.path.join(ROOT, f)), f"{f} missing"
    return "docker/compose/entrypoint/litestream/ci present"


def _t_data_dir():
    data = os.environ.get("AURA_DATA_DIR", os.path.join(ROOT, "data"))
    assert os.path.isdir(data), f"data dir missing: {data}"
    probe = os.path.join(data, ".writetest")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return f"writable: {data}"


def _t_db_integrity():
    dbp = os.environ.get("AURA_DB_PATH", os.path.join(ROOT, "data", "aura.db"))
    assert os.path.isfile(dbp), f"db missing: {dbp}"
    con = sqlite3.connect(dbp)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        assert row and row[0] == "ok", f"integrity_check: {row}"
        n = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    finally:
        con.close()
    return f"{n} tables, integrity ok"


# ------------------------------------------------------------------- live ---
def _t_health():
    s, d = req("/api/health")
    assert s == 200, f"HTTP {s}"
    bad = [x["name"] for x in d.get("services", []) if x.get("status") == "offline"]
    assert not bad, f"offline services: {bad}"
    deg = [x["name"] for x in d.get("services", []) if x.get("status") not in ("online", "degraded")]
    assert not deg, f"bad states: {deg}"
    return f"{len(d.get('services', []))} services, none offline"


def _t_live_version():
    s, d = req("/api/system")
    assert s == 200, f"HTTP {s}"
    cfg = _read("backend/app/config.py")
    v = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', cfg).group(1)
    assert d.get("version") == v, f"live {d.get('version')} != code {v} (restart?)"
    return f"live v{d.get('version')}"


def _t_backup_fresh():
    try:
        s, d = req("/api/backup/history")
    except AssertionError as e:
        warn("backup recency", f"history unreadable: {e}")
        return
    assert s == 200, f"HTTP {s}"
    files = d.get("files", []) if isinstance(d, dict) else []
    if not files:
        warn("backup recency", "no restorable archives yet — run a backup before prod")
        return
    newest = max(files, key=lambda f: f.get("created_at", ""))
    try:
        age_days = (time.time() - time.mktime(time.strptime(
            newest["created_at"][:19], "%Y-%m-%dT%H:%M:%S"))) / 86400
    except Exception:
        warn("backup recency", "unparseable timestamp")
        return
    if age_days > 7:
        warn("backup recency", f"newest archive {age_days:.0f}d old")
        return
    return f"newest archive {age_days:.1f}d old"


def _t_push_ready():
    s, d = req("/api/push/vapid-public-key")
    if s != 200 or not d.get("configured"):
        warn("push ready", "VAPID unconfigured — browser push disabled (run gen_vapid.py)")
        return
    return "VAPID configured"


def _t_cloud_sane():
    s, d = req("/api/settings")
    assert s == 200, f"HTTP {s}"
    vals, secs = d.get("values", {}), d.get("secrets", {})
    if vals.get("privacy") != "local-first":
        prov = vals.get("cloud_provider", "?")
        key = {"openrouter": "openrouter_key", "openai": "openai_key"}.get(prov, "custom_key")
        if not secs.get(key):
            warn("cloud sane", f"privacy={vals.get('privacy')} but no {prov} key — chain falls back")
            return
    return f"privacy={vals.get('privacy')}"


print("== prod files ==")
check("versions consistent", _t_versions)
check("prod build present", _t_dist)
check("deploy files present", _t_deploy_files)
check("data dir writable", _t_data_dir)
check("db integrity", _t_db_integrity)
def _t_machine_room():
    dbp = os.environ.get("AURA_DB_PATH", os.path.join(ROOT, "data", "aura.db"))
    con = sqlite3.connect(dbp)
    try:
        tabs = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"ollama_models", "terminal_runs", "feeds", "feed_items", "calls",
                "scripts", "watched_files"}
        assert need <= tabs, f"missing v1.14 tables: {sorted(need - tabs)}"
    finally:
        con.close()
    s, d = req("/api/ollama/status")
    assert s == 200, f"ollama status HTTP {s}"
    s, d = req("/api/terminal/config")
    assert s == 200 and "enabled" in d, f"terminal config HTTP {s}"
    s, d = req("/api/feeds")
    assert s == 200 and "feeds" in d, f"feeds HTTP {s}"
    s, d = req("/api/scripts")
    assert s == 200 and "scripts" in d, f"scripts HTTP {s}"
    s, d = req("/api/watch")
    assert s == 200 and "paths" in d and "default_dir" in d, f"watch HTTP {s}"
    s2, o = req("/api/ollama/status")
    tag = "" if o.get("reachable") else " · ollama offline — cached catalog, builtin engine covers"
    return f"v1.14 tables + endpoints live{tag}"


print("== prod live ==")
check("health, none offline", _t_health)
check("live version matches code", _t_live_version)
check("backup recency", _t_backup_fresh)
check("push ready", _t_push_ready)
check("cloud sane", _t_cloud_sane)
check("machine room (v1.14)", _t_machine_room)

print("\n================ SUMMARY ================")
print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}   WARN: {len(WARN)}")
for n in FAIL:
    print(f"  FAIL {n}")
sys.exit(1 if FAIL else 0)
