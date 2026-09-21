"""Backup & restore — SQLite snapshot + uploads archive with integrity hash."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from . import config, db


def run_backup(target: str = "local") -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = config.BACKUP_DIR / f"aura-backup-{ts}.tar.gz"
    tmp = config.BACKUP_DIR / f".snap-{ts}.db"
    try:
        bid = db.run("INSERT INTO backups (user_id, target, status) VALUES (1,?,'running')", (target,))
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(str(tmp))
        src.backup(dst)
        dst.close()
        src.close()
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(tmp, arcname="aura.db")
            if config.UPLOAD_DIR.exists():
                tar.add(config.UPLOAD_DIR, arcname="uploads")
        tmp.unlink(missing_ok=True)
        size = dest.stat().st_size
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        db.run("UPDATE backups SET status='ok', size_bytes=?, note=?, finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
               (size, f"sha256:{h.hexdigest()[:16]}", bid))
        db.log_activity("backup", "Backup completed", f"{dest.name} · {size/1024:.0f} KB", "general", "success")
        return {"ok": True, "file": dest.name, "size_bytes": size, "sha256": h.hexdigest()}
    except Exception as e:
        db.run("UPDATE backups SET status='failed', note=? WHERE target=? AND status='running'", (str(e)[:200], target))
        db.log_activity("backup", "Backup failed", str(e)[:200], "general", "error")
        return {"ok": False, "error": str(e)[:300]}


def available_files(limit: int = 20) -> list[dict]:
    """Snapshot archives physically present (DB rows alone can't restore)."""
    try:
        files = sorted(config.BACKUP_DIR.glob("aura-backup-*.tar.gz"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []
    out = []
    for f in files[:limit]:
        try:
            st = f.stat()
            out.append({"name": f.name, "size_bytes": st.st_size,
                        "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()})
        except Exception:
            continue
    return out


def restore_backup(filename: str) -> dict:
    """Restore DB + uploads from a snapshot. Safety-copies live data first."""
    name = Path(filename or "").name
    if not (name.startswith("aura-backup-") and name.endswith(".tar.gz")):
        return {"ok": False, "error": "not an AURA backup file"}
    src = config.BACKUP_DIR / name
    if not src.is_file():
        return {"ok": False, "error": "backup file not found"}
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="aura-restore-"))
    try:
        with tarfile.open(src, "r:gz") as tar:
            members = tar.getmembers()
            if not any(m.name == "aura.db" for m in members):
                return {"ok": False, "error": "archive has no database snapshot"}
            for m in members:  # path-traversal guard
                if m.name.startswith(("/", "..")) or ".." in m.name.split("/"):
                    return {"ok": False, "error": "unsafe archive paths"}
            tar.extractall(work)
        snap = work / "aura.db"
        probe = sqlite3.connect(str(snap))
        try:
            integrity = probe.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            probe.close()
        if integrity != "ok" or not {"users", "tasks", "memories"} <= tables:
            return {"ok": False, "error": "snapshot failed integrity check"}
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        pre = config.BACKUP_DIR / f".pre-restore-{ts}.db"
        live = sqlite3.connect(config.DB_PATH)
        try:
            live.backup(sqlite3.connect(str(pre)))
        finally:
            live.close()
        db.reset()
        shutil.copy2(snap, config.DB_PATH)
        for suf in ("-wal", "-shm", "-journal"):
            Path(str(config.DB_PATH) + suf).unlink(missing_ok=True)
        db.qone("SELECT 1")
        n_up = 0
        updir = work / "uploads"
        if updir.is_dir():
            config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            for f in updir.rglob("*"):
                if f.is_file():
                    dest = config.UPLOAD_DIR / f.name
                    if not dest.exists():
                        shutil.copy2(f, dest)
                        n_up += 1
        db.log_activity("backup", "Backup restored", f"{name} · {n_up} file(s)", "general", "success")
        return {"ok": True, "file": name, "uploads_restored": n_up, "safety_copy": pre.name}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def history(limit: int = 20) -> list[dict]:
    return db.q("SELECT * FROM backups WHERE user_id=1 ORDER BY id DESC LIMIT ?", (limit,))
