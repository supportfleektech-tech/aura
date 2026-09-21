"""AURA Terminal — run commands & scripts on the fortress machine (and over SSH).

Single-user by design: this is YOUR machine, behind YOUR door (Tailscale/VPN).
AURA therefore executes with your user's privileges — but never blindly:

  * every exec is classified (safe | guarded | dangerous) and audited
    (terminal_runs) with exit code + duration + output size;
  * dangerous patterns (rm -rf /, mkfs, dd→disk, fork bombs, shutdown,
    curl|sh …) are REFUSED unless `terminal_allow_dangerous` is explicitly on;
  * remote machines = `ssh -o BatchMode=yes` targets from `terminal_machines`;
    key-based auth only (we never prompt for passwords);
  * dry-run previews (db.DRY_RUN) never execute;
  * `terminal_enabled: false` turns the whole surface off.

Long output is truncated to `terminal_max_out_kb` with an honest marker.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from . import db, prefs

_SHELL = os.environ.get("AURA_SHELL", "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh")

# Read-only commands AURA may run without ceremony (used for risk labels;
# `safe` skips the confirm hint in the UI). Interpreters, writers, and
# anything with side-effecting subcommands are deliberately NOT here —
# tools with a mixed personality (git, ollama, docker…) must also pass the
# subcommand allowlist below or they downgrade to `guarded`.
_SAFE_FIRST = {
    "ls", "pwd", "whoami", "uname", "date", "hostname", "uptime", "df", "du",
    "free", "ps", "top", "htop", "which", "whereis", "type", "echo", "printf",
    "cat", "head", "tail", "wc", "sort", "uniq", "grep", "rg", "ag", "fd",
    "stat", "file", "id", "printenv", "ping", "traceroute", "dig", "nslookup",
    "jq", "column", "tree", "nproc", "lscpu", "lsblk", "history", "sw_vers",
    "system_profiler", "ifconfig", "netstat", "ss", "lsof", "journalctl",
    "du", "lsof", "uptime", "readlink", "basename", "dirname", "realpath",
}
_SUB_SAFE = {
    "git": {"status", "log", "branch", "diff", "show", "remote", "blame", "shortlog",
            "describe", "rev-parse", "config", "ls-files"},
    "ollama": {"list", "ls", "show", "version"},
    "docker": {"ps", "images", "version", "inspect"},
    "systemctl": {"status", "list-units", "is-active", "is-enabled", "show"},
    "pip": {"list", "show", "freeze"}, "pip3": {"list", "show", "freeze"},
    "npm": {"ls", "list", "view"}, "pnpm": {"ls", "list", "view"}, "yarn": {"list", "info"},
    "brew": {"list", "info", "search"},
    "find": {"*"},  # any args, but see _ARGS_DENY below
    "ip": {"show", "a", "r", "l"},
    "curl": {"*"}, "wget": {"*"}, "env": {"*"},
}
_ARGS_DENY = {
    "find": (re.compile(r"-(delete|exec|execdir|ok|okdir)\b", re.I),),
    "curl": (re.compile(r"-(X|request)\s+(POST|PUT|DELETE|PATCH)", re.I), re.compile(r"-T\b|--upload")),
    "wget": (re.compile(r"--post-|--method", re.I),),
    "env": (re.compile(r"\b[A-Za-z_]+=|(-i|--unset)", re.I),),
    "git": (re.compile(r"\s-c\b|--exec-path|--output", re.I),),
    "docker": (re.compile(r"\s(exec|run|cp)\b", re.I),),
}

# Refuse-by-default footguns. Patterns run against the raw command text.
_DANGER = [
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+(/|~|\$HOME)(\s|$)", "recursive delete of a root/home path"),
    (r"\brm\s+-rf?\s*/\s*\*?", "recursive delete of /"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bmkfs(\.\w+)?\b", "format a filesystem"),
    (r"\bdd\b[^\n|;&]*\bof=/dev/", "raw write to a block device"),
    (r">\s*/dev/(sd|nvme|disk)", "raw write to a disk device"),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "power state change"),
    (r"\b(curl|wget)\b[^\n|;&]*\|\s*(sudo\s+)?(ba)?sh\b", "pipe-to-shell"),
    (r"\bchmod\s+(-[a-z]+\s+)*-?R.*\s+777\s+/(\s|$)", "world-writable / recursively"),
    (r"\bchown\b.*\s-R\s.*/(\s|$)", "recursive chown from /"),
    (r"\bgit\s+clean\s+-[a-z]*f", "git clean -f (deletes untracked files)"),
    (r"\bDROP\s+(TABLE|DATABASE)\b", "drop table/database"),
    (r"\bINSERT\s+OVERWRITE\b|\bTRUNCATE\s+TABLE\b", "bulk destructive SQL"),
    (r"\bhistory\s+-c\b", "wipe shell history"),
    (r"\bkill\s+-9\s+(-1|1)\b", "kill every process"),
]
_COMPILED_DANGER = [(re.compile(p, re.I), why) for p, why in _DANGER]


def _seg_ok(seg: str) -> bool:
    toks = seg.split()
    if not toks:
        return False
    head = toks[0].strip("'\"")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", head):  # VAR=x cmd prefix
        return False
    rest = seg[len(toks[0]):].strip()
    subs = _SUB_SAFE.get(head)
    if head in _SAFE_FIRST:
        if subs is not None and "*" not in subs:
            return bool(toks[1:]) and toks[1] in subs
    elif subs is not None:
        if "*" not in subs:
            return bool(toks[1:]) and toks[1] in subs
    else:
        return False
    for pat in _ARGS_DENY.get(head, ()):
        if pat.search(rest):
            return False
    return True


def classify(command: str) -> tuple[str, str]:
    """(risk, why). risk ∈ safe|guarded|dangerous."""
    low = " ".join((command or "").split())
    for pat, why in _COMPILED_DANGER:
        if pat.search(low):
            return "dangerous", why
    if re.search(r"(?<![0-9&])>(?!&)", low) or "$(" in low or "`" in low:
        return "guarded", "redirects / command substitution — run from the Terminal screen"
    segs = [s.strip() for s in re.split(r"[|;&]+", low) if s.strip()]
    if segs and all(_seg_ok(s) for s in segs):
        return "safe", "read-only command set"
    return "guarded", "not in the read-only allowlist"


def danger_reason(command: str) -> str:
    low = " ".join((command or "").split())
    for pat, why in _COMPILED_DANGER:
        if pat.search(low):
            return why
    return ""


# ---------------------------------------------------------------- machines ---
def machines() -> list[dict]:
    raw = prefs.get("terminal_machines") or "[]"
    try:
        rows = json.loads(raw)
    except ValueError:
        return []
    out = [{"name": "local", "host": "local", "kind": "local"}]
    for r in rows if isinstance(rows, list) else []:
        name, host = str(r.get("name", "")).strip(), str(r.get("host", "")).strip()
        if name and host and name != "local":
            out.append({"name": name, "host": host, "kind": "ssh",
                        "ssh_ready": shutil.which("ssh") is not None})
    return out


def save_machines(rows: list[dict]) -> None:
    clean = []
    seen = set()
    for r in rows if isinstance(rows, list) else []:
        name = str(r.get("name", "")).strip()
        host = str(r.get("host", "")).strip()
        if not name or not host or name == "local" or name in seen:
            raise ValueError("each machine needs a unique non-'local' name and a host "
                             "(user@ip or bare hostname)")
        if not re.fullmatch(r"[A-Za-z0-9@._:\[\]-]+", host):
            raise ValueError(f"invalid ssh host: {host!r}")
        seen.add(name)
        clean.append({"name": name, "host": host})
    prefs.set_many({"terminal_machines": json.dumps(clean)})


def _resolve(machine: str) -> dict | None:
    """local → None; else the ssh host string for `machine`."""
    if not machine or machine == "local":
        return None
    for m in machines():
        if m["name"] == machine and m["kind"] == "ssh":
            return m["host"]
    raise ValueError(f"unknown machine: {machine} — configure it in Settings → Terminal")


# ------------------------------------------------------------------ exec ---
def _cwd() -> str:
    raw = str(prefs.get("terminal_cwd") or "").strip()
    if not raw:
        return str(Path.home())
    p = Path(os.path.expanduser(raw))
    return str(p) if p.is_dir() else str(Path.home())


def ssh_argv(host: str, command: str) -> list[str]:
    """argv for a non-interactive ssh exec. Key auth only (BatchMode)."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new", "--", host, command]


def _truncate(data: bytes, kb: int) -> tuple[str, bool]:
    cap = max(1, kb) * 1024
    clipped = len(data) > cap
    txt = data[:cap].decode("utf-8", "replace")
    if clipped:
        txt += f"\n… output truncated at {kb} KB"
    return txt, clipped


def _log(source: str, machine: str, command: str, cwd: str, risk: str, status: str,
         exit_code: int | None = None, ms: int = 0, out_bytes: int = 0, note: str = "") -> None:
    try:
        db.run("INSERT INTO terminal_runs (source,machine,command,cwd,risk,status,exit_code,"
               "duration_ms,out_bytes,note) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (source, machine, command[:2000], cwd, risk, status, exit_code, ms, out_bytes, note[:300]))
    except Exception:
        pass


def exec_command(command: str, machine: str = "local", source: str = "ui",
                 timeout: float | None = None) -> dict:
    """Run ONE command. Returns a rich dict — never raises for control flow."""
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "empty command"}
    if not prefs.get("terminal_enabled"):
        _log(source, machine, command, "", "", "disabled", note="terminal disabled in settings")
        return {"ok": False, "denied": True, "error": "Terminal is disabled — enable it in Settings → Terminal."}
    if db.DRY_RUN:
        db.blocked(f"terminal: {command[:120]}")
        return {"dry_run": True, "would": command[:300]}
    risk, why = classify(command)
    if risk == "dangerous" and not prefs.get("terminal_allow_dangerous"):
        _log(source, machine, command, _cwd(), risk, "denied", note=why)
        db.log_activity("system", f"Terminal denied: {command[:80]}", why, "general", "error")
        return {"ok": False, "denied": True, "risk": risk,
                "error": f"refused — {why}. If you really mean it, toggle "
                         f"Settings → Terminal → allow dangerous."}
    try:
        ssh_host = _resolve(machine)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    to = float(timeout if timeout else prefs.get("terminal_timeout_s") or 30)
    to = min(max(to, 1.0), 600.0)
    kb = int(prefs.get("terminal_max_out_kb") or 64)
    cwd = _cwd()
    if ssh_host:
        if shutil.which("ssh") is None:
            return {"ok": False, "error": "ssh binary not found on the AURA host"}
        argv, run_cwd = ssh_argv(ssh_host, command), cwd
    else:
        argv, run_cwd = [_SHELL, "-lc", command], cwd
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=run_cwd, capture_output=True, timeout=to,
                           env={**os.environ, "TERM": "dumb", "LANG": os.environ.get("LANG", "C.UTF-8")})
        ms = int((time.time() - t0) * 1000)
        raw = (p.stdout or b"") + ((b"\n" + p.stderr) if p.stderr else b"")
        out, clipped = _truncate(raw, kb)
        status = "ok" if p.returncode == 0 else "error"
        _log(source, machine or "local", command, cwd, risk, status, p.returncode, ms, len(raw))
        return {"ok": p.returncode == 0, "exit_code": p.returncode, "output": out,
                "duration_ms": ms, "machine": machine or "local", "cwd": cwd,
                "risk": risk, "risk_note": why, "truncated": clipped}
    except subprocess.TimeoutExpired:
        ms = int((time.time() - t0) * 1000)
        _log(source, machine or "local", command, cwd, risk, "timeout", None, ms, note=f">{to:.0f}s")
        return {"ok": False, "error": f"timeout after {to:.0f}s", "duration_ms": ms,
                "exit_code": None, "machine": machine or "local", "cwd": cwd, "risk": risk}
    except FileNotFoundError:
        _log(source, machine or "local", command, cwd, risk, "unavailable", note="binary missing")
        return {"ok": False, "error": "shell binary not found on this host"}
    except OSError as e:
        _log(source, machine or "local", command, cwd, risk, "error", note=str(e)[:200])
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:180]}",
                "exit_code": None, "machine": machine or "local", "cwd": cwd, "risk": risk}


def history(limit: int = 50) -> list[dict]:
    rows = db.q("SELECT * FROM terminal_runs ORDER BY id DESC LIMIT ?",
                (min(max(int(limit or 50), 1), 200),))
    for r in rows:
        r["out_kb"] = round((r.get("out_bytes") or 0) / 1024, 1)
    return rows


def set_cwd(path: str) -> str:
    """Validate + persist a working directory (must exist after ~ expansion)."""
    p = Path(os.path.expanduser((path or "").strip() or str(Path.home())))
    if not p.is_dir():
        raise ValueError(f"not a directory: {p}")
    prefs.set_many({"terminal_cwd": str(p)})
    return str(p)


def check_machine(name: str, port: int | None = None, timeout: float = 1.5) -> dict:
    """TCP liveness probe — is the machine answering at all? (key auth not needed)."""
    if not name or name == "local":
        return {"machine": "local", "kind": "local", "ok": True, "detail": "this is the AURA host"}
    host = None
    for m in machines():
        if m["name"] == name and m["kind"] == "ssh":
            host = m["host"]
            break
    if host is None:
        return {"ok": False, "error": f"unknown machine: {name}"}
    pure = host.rsplit("@", 1)[-1].strip("[]")
    if ":" in pure:  # host:port notation wins
        pure, _, pstr = pure.rpartition(":")
        if pstr.isdigit():
            port = int(pstr)
    import socket
    t0 = time.time()
    try:
        with socket.create_connection((pure, int(port or 22)), timeout=timeout):
            return {"machine": name, "host": pure, "port": int(port or 22), "ok": True,
                    "ms": int((time.time() - t0) * 1000), "detail": "tcp connect ok — ssh likely reachable"}
    except OSError as e:
        return {"machine": name, "host": pure, "port": int(port or 22), "ok": False,
                "ms": int((time.time() - t0) * 1000), "detail": f"{type(e).__name__}: {str(e)[:120]}"}


def parse_inline(text: str) -> str:
    """Extract a command from chat text: 'run `ls -la`', 'terminal: git status'…"""
    m = re.search(r"[`'\"](.+?)[`'\"]", text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(?:run|exec|execute)\b\s+(?:in\s+(?:the\s+|my\s+)?terminal\s*)?"
                  r"(?:the\s+)?(?:command)?\s*[:>]?\s*(.+)$", text, re.I | re.S)
    if m:
        return m.group(1).strip().rstrip(".!")
    m = re.search(r"\b(?:terminal|shell|bash)\s*[:>]\s*(.+)$", text, re.I | re.S)
    if m:
        return m.group(1).strip()
    return ""
