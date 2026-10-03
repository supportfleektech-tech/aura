#!/usr/bin/env python3
"""AURA OS migration guard — blocks destructive schema changes in CI.

Compares backend/app/schema.sql between two git refs (default: the
remote's default branch)
vs HEAD) and fails on:
  - dropped tables (CREATE TABLE present in base, gone in head)
  - dropped columns (column in base table, gone in head table)
  - explicit DROP TABLE / DROP COLUMN statements in the new schema

Additive changes (new tables/columns) always pass. Destructive changes pass
only when the head commit message contains the approval token:
    [allow-destructive-schema]

Usage:
  python3 scripts/migration_check.py [--base REF] [--head REF]
                                     [--file backend/app/schema.sql]
  python3 scripts/migration_check.py --self-test   # fixture tests, no git

Exit code 0 = safe, 1 = destructive (or git/file error). Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import sys

ALLOW_TOKEN = "[allow-destructive-schema]"
DEFAULT_FILE = "backend/app/schema.sql"

_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)[\"'`\]]?\s*\((.*?)\);",
    re.IGNORECASE | re.DOTALL)
_DROP_STMT = re.compile(r"\bDROP\s+(TABLE|COLUMN)\b", re.IGNORECASE)
_COL = re.compile(r"^[\"'`\[]?(\w+)[\"'`\]]?\s+(TEXT|INTEGER|REAL|BLOB|NUMERIC|DATETIME|DATE|TIME|BOOLEAN)\b",
                  re.IGNORECASE)
_CONSTRAINT_LEADERS = ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")


def parse_schema(sql: str) -> dict[str, set[str]]:
    """Parse CREATE TABLE blocks -> {table: {lowercased columns}}."""
    tables: dict[str, set[str]] = {}
    for m in _CREATE.finditer(sql or ""):
        cols: set[str] = set()
        for part in m.group(2).split(","):
            line = part.strip()
            if not line or line.split(None, 1)[0].upper().rstrip(",") in _CONSTRAINT_LEADERS:
                continue
            cm = _COL.match(line)
            if cm:
                cols.add(cm.group(1).lower())
        tables[m.group(1).lower()] = cols
    return tables


def destructive_changes(old_sql: str, new_sql: str) -> list[str]:
    """Describe destructive diffs from old -> new schema. Empty = safe."""
    problems: list[str] = []
    for stmt in _DROP_STMT.findall(new_sql or ""):
        problems.append(f"explicit DROP {stmt} statement in new schema")
    old, new = parse_schema(old_sql), parse_schema(new_sql)
    for table in sorted(old):
        if table not in new:
            problems.append(f"table dropped: {table}")
            continue
        for col in sorted(old[table] - new[table]):
            problems.append(f"column dropped: {table}.{col}")
    return problems


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()[:200]}")
    return p.stdout


def check_refs(base: str, ref: str, path: str) -> tuple[list[str], bool]:
    """Return (problems, token_allowed). Missing base file = nothing to drop."""
    try:
        old_sql = _git("show", f"{base}:{path}")
    except RuntimeError as e:
        if "does not exist" in str(e) or "bad revision" in str(e) or "exists on disk" in str(e):
            return [], False
        raise
    new_sql = _git("show", f"{ref}:{path}")
    problems = destructive_changes(old_sql, new_sql)
    allowed = False
    if problems:
        try:
            msg = _git("log", "-1", "--format=%B", ref)
            allowed = ALLOW_TOKEN in msg
        except RuntimeError:
            allowed = False
    return problems, allowed


def self_test() -> int:
    fails = 0

    def check(name: str, cond: bool, extra: str = ""):
        nonlocal fails
        print(("  PASS " if cond else "  FAIL ") + name + (f" — {extra}" if extra and not cond else ""))
        fails += 0 if cond else 1

    base = ("CREATE TABLE IF NOT EXISTS tasks (\n  id INTEGER PRIMARY KEY,\n"
            "  title TEXT NOT NULL,\n  due_at TEXT,\n"
            "  CONSTRAINT ck CHECK (id > 0)\n);\n"
            "CREATE TABLE notes (\n  id INTEGER PRIMARY KEY,\n  body TEXT\n);\n")
    check("parse tables+cols",
          parse_schema(base) == {"tasks": {"id", "title", "due_at"}, "notes": {"id", "body"}})
    additive = base + "CREATE TABLE tags (\n  id INTEGER PRIMARY KEY,\n  name TEXT\n);\n"
    additive = additive.replace("  due_at TEXT,\n", "  due_at TEXT,\n  priority TEXT DEFAULT 'med',\n")
    check("additive change passes", destructive_changes(base, additive) == [])
    drop_col = base.replace("  due_at TEXT,\n", "")
    probs = destructive_changes(base, drop_col)
    check("dropped column flagged", probs == ["column dropped: tasks.due_at"], str(probs))
    drop_table = "CREATE TABLE notes (\n  id INTEGER PRIMARY KEY,\n  body TEXT\n);\n"
    probs = destructive_changes(base, drop_table)
    check("dropped table flagged", probs == ["table dropped: tasks"], str(probs))
    check("case-insensitive + quoted idents",
          destructive_changes(base, base.replace("tasks", '"TASKS"')) == [])
    dropped_stmt = base + "DROP TABLE notes;\n"
    check("explicit DROP flagged",
          destructive_changes(base, dropped_stmt) != [], "no problems reported")
    check("column rename flagged as drop+add-safe",
          destructive_changes(base, base.replace("due_at", "deadline"))
          == ["column dropped: tasks.due_at"])
    print(f"migration_check self-test: {'OK' if fails == 0 else f'{fails} FAILURES'}")
    return 1 if fails else 0


def _default_base() -> str:
    """Pick the branch to diff against instead of assuming `main`.

    The repo's default branch is `master`, and a hardcoded `origin/main` made this
    script fail on CI with "invalid object name" rather than doing its job. Prefer
    whatever the remote HEAD actually points at, then the two common names, then
    let the caller pass --base explicitly.
    """
    import subprocess

    def _rev_parse(ref: str) -> bool:
        return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                              capture_output=True).returncode == 0

    if _rev_parse("origin/HEAD"):
        return "origin/HEAD"
    try:
        out = subprocess.run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
                             capture_output=True, text=True).stdout.strip()
        if out:
            return out
    except OSError:
        pass
    for cand in ("origin/main", "origin/master"):
        if _rev_parse(cand):
            return cand
    return "origin/main"


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    base, ref, path = _default_base(), "HEAD", DEFAULT_FILE
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--base" and args:
            base = args.pop(0)
        elif a == "--head" and args:
            ref = args.pop(0)
        elif a == "--file" and args:
            path = args.pop(0)
        else:
            print(f"unknown arg: {a}")
            return 2
    try:
        problems, allowed = check_refs(base, ref, path)
    except RuntimeError as e:
        print(f"migration_check ERROR: {e}")
        return 1
    if not problems:
        print(f"migration_check OK: no destructive changes ({base}..{ref} {path})")
        return 0
    for p in problems:
        print(f"  DESTRUCTIVE: {p}")
    if allowed:
        print(f"migration_check WARN: destructive changes approved via {ALLOW_TOKEN}")
        return 0
    print(f"migration_check FAIL: approve with {ALLOW_TOKEN} in the commit message, or keep it additive")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
