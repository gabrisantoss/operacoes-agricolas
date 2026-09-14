from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


def sqlite_integrity_check(path: Path) -> str:
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return str(result[0] if result else "sem retorno")
    finally:
        conn.close()


def backup_sqlite_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source, timeout=30)
    dst = sqlite3.connect(target, timeout=30)
    try:
        src.execute("PRAGMA busy_timeout = 30000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def build_database_manifest(name: str, source: Path, backup_file: Path) -> dict:
    stat = backup_file.stat()
    return {
        "name": name,
        "path": str(source),
        "backup_file": str(backup_file),
        "size_bytes": stat.st_size,
        "integrity_check": sqlite_integrity_check(backup_file),
    }


def ensure_db_backup_before_migration(db_path: Path, backup_root: Path, reason: str) -> Path | None:
    if not db_path.exists():
        return None
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in reason.lower())[:48]
    target_dir = backup_root / f"pre-migration-{safe_reason}-{timestamp}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / db_path.name
    backup_sqlite_database(db_path, target)
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "database": build_database_manifest(db_path.name, db_path, target),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
