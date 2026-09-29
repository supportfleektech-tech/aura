"""Folder watch — drop files into a watched directory, AURA handles them.

The scheduler scans configured folders (default: `<data>/inbox`) every
`watch_scan_interval_s` seconds. New or changed files are:
  1. registered as AURA files (extracted text indexed into memory),
  2. announced as a notification,
  3. fired against automations with trigger_kind='file' (optional `contains`).

State is the `watched_files` table (path + size + mtime) — a file only
re-triggers when it actually changes, and `reset` re-arms everything.
"""
from __future__ import annotations

import fnmatch
import json
import time
from pathlib import Path

from . import config, db, prefs

MAX_BYTES = 25 * 1024 * 1024
EXTS = {".pdf", ".txt", ".md", ".markdown", ".docx", ".xlsx", ".pptx", ".csv",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".py", ".sh", ".json", ".log"}


def default_dir() -> Path:
    d = Path(config.DATA_DIR) / "inbox"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def paths() -> list[str]:
    raw = str(prefs.get("watch_paths") or "[]")
    try:
        rows = json.loads(raw)
    except ValueError:
        rows = []
    out = [str(p) for p in rows if isinstance(p, str) and p.strip()]
    return out or [str(default_dir())]


def save_paths(paths: list[str]) -> list[str]:
    clean: list[str] = []
    data_root = str(Path(config.DATA_DIR).resolve())
    for p in paths if isinstance(paths, list) else []:
        pp = Path(str(p).strip()).expanduser()
        if not str(p).strip():
            continue
        try:
            rp = pp.resolve()
        except OSError:
            raise ValueError(f"bad path: {p}")
        if rp.is_dir() or (str(rp).startswith(data_root) and not rp.exists()):
            rp.mkdir(parents=True, exist_ok=True)
            if str(rp) not in clean:
                clean.append(str(rp))
        else:
            raise ValueError(f"not a readable directory (or outside data dir): {p}")
    prefs.set_many({"watch_paths": json.dumps(clean)})
    return clean


def _candidates() -> list[Path]:
    out: list[Path] = []
    for base in paths():
        bp = Path(base)
        if not bp.is_dir():
            continue
        try:
            entries = sorted(bp.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_file() and not e.name.startswith("."):
                out.append(e)
            elif e.is_dir() and not e.name.startswith("."):  # one level deep only
                try:
                    out.extend(x for x in sorted(e.iterdir()) if x.is_file() and not x.name.startswith("."))
                except OSError:
                    pass
    return out


def fire_file_automations(fp: Path, event: str) -> int:
    blob = f"{fp.name} {fp} {event}".lower()
    fired = 0
    for a in db.q("SELECT * FROM automations WHERE user_id=1 AND status='active' "
                  "AND trigger_kind='file'"):
        trig = db.jload(a["trigger_config"], {}) or {}
        kw = str(trig.get("contains", "") or trig.get("pattern", "")).lower().strip()
        if kw and not (kw in blob or fnmatch.fnmatch(fp.name.lower(), kw)):
            continue
        from .hermes import hermes
        res = hermes.fire_event(a, fire_id=f"file-{a['id']}-{fp.name}")
        fired += 1 if res.get("ok") else 0
    return fired


def _ingest(fp: Path) -> dict | None:
    """Register + memory-index one file. Returns the files row info."""
    try:
        data = fp.read_bytes()
    except OSError as e:
        return {"error": str(e)[:120]}
    if len(data) > MAX_BYTES:
        return {"error": f"too large ({len(data)} bytes)"}
    import mimetypes
    from .extract import extract_text
    from .memory import memory_engine
    safe = "".join(c if c.isalnum() or c in "._-#" else "_" for c in fp.name)[:120]
    dest = config.UPLOAD_DIR / f"w{int(fp.stat().st_mtime)}_{safe}"
    try:
        dest.write_bytes(data)
    except OSError as e:
        return {"error": f"copy failed: {str(e)[:80]}"}
    ex = extract_text(data, fp.name, mimetypes.guess_type(fp.name)[0] or "")
    text = (ex.get("text") or "").strip()
    fid = db.run("INSERT INTO files (user_id,name,mime,size,path,domain,indexed_text) "
                 "VALUES (1,?,?,?,?,?,?)",
                 (fp.name, mimetypes.guess_type(fp.name)[0] or "", len(data), str(dest),
                  "general", text[:200000]))
    if text and prefs.get("watch_ingest"):
        memory_engine.store(f"Watched file: {fp.name}", text[:1500], "general",
                            "context", "folder-watch", 0.75, 0.5)
    return {"file_id": fid, "chars": len(text)}


def scan_once(source: str = "scheduler") -> dict:
    if db.DRY_RUN:
        db.blocked("watch: scan skipped")
        return {"dry_run": True}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new = changed = skipped = errors = 0
    for fp in _candidates():
        if fp.suffix.lower() not in EXTS:
            skipped += 1
            continue
        try:
            st = fp.stat()
        except OSError:
            continue
        row = db.qone("SELECT * FROM watched_files WHERE path=?", (str(fp),))
        event = ""
        if not row:
            new += 1
            event = "new"
        elif int(row["mtime"]) != int(st.st_mtime) or int(row["size"]) != st.st_size:
            changed += 1
            event = "changed"
        else:
            continue
        ing = _ingest(fp) if prefs.get("watch_ingest") else {"file_id": None, "chars": 0}
        err = (ing or {}).get("error", "")
        if err:
            errors += 1
        db.run("INSERT INTO watched_files (path,size,mtime,file_id,ingested,first_seen,last_event) "
               "VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET size=excluded.size, "
               "mtime=excluded.mtime, file_id=excluded.file_id, ingested=excluded.ingested, "
               "last_event=excluded.last_event",
               (str(fp), st.st_size, int(st.st_mtime), (ing or {}).get("file_id"),
                1 if (ing or {}).get("file_id") else 0, row["first_seen"] if row else now, f"{event} {now}"))
        db.notify(f"Watch: {event} file", f"{fp.name} · {st.st_size/1024:.0f} KB — indexed"
                  if not err else f"{fp.name} — {err}")
        db.log_activity("system", f"Watch {event}: {fp.name}", f"via {source}", "general")
        fire_file_automations(fp, event)
    return {"new": new, "changed": changed, "skipped_ext": skipped, "errors": errors,
            "scanned_at": now}


def recent(limit: int = 15) -> list[dict]:
    return db.q("SELECT path, size, mtime, file_id, ingested, last_event FROM watched_files "
                "ORDER BY last_event DESC LIMIT ?", (min(max(int(limit or 15), 1), 100),))


def reset_state() -> int:
    n = db.qone("SELECT COUNT(*) c FROM watched_files") or {"c": 0}
    db.run("DELETE FROM watched_files")
    return int(n.get("c") or 0)


_LAST = {"ts": 0.0}


def maybe_scan() -> dict | None:
    if not prefs.get("watch_enabled"):
        return None
    every = max(30, int(prefs.get("watch_scan_interval_s") or 120))
    if time.time() - _LAST["ts"] < every:
        return None
    _LAST["ts"] = time.time()
    return scan_once()
