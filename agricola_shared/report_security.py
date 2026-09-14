from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping


FORMULA_PREFIXES = ("=", "+", "-", "@")
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def neutralize_spreadsheet_value(value: Any) -> Any:
    """Keep user-controlled strings from being interpreted as spreadsheet formulas."""

    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def neutralize_dataframe(dataframe):
    """Return a copy with formula-like strings neutralized in every column."""

    safe = dataframe.copy()
    for column in safe.columns:
        safe[column] = safe[column].map(neutralize_spreadsheet_value)
    return safe


def neutralize_csv_row(values):
    return [neutralize_spreadsheet_value(value) for value in values]


def _safe_segment(value: str, fallback: str) -> str:
    segment = _SAFE_SEGMENT.sub("_", str(value or "").strip()).strip("._")
    return segment or fallback


def report_owner_key(user: Mapping[str, Any] | None) -> str:
    identity = ""
    if user:
        for key in ("id", "email", "username", "name"):
            identity = str(user.get(key) or "").strip()
            if identity:
                break
    digest = hashlib.sha256((identity or "authenticated-user").casefold().encode("utf-8")).hexdigest()
    return digest[:16]


def cleanup_generated_reports(root: str | Path, *, retention_seconds: float, now: float | None = None) -> int:
    """Remove only expired files below a dedicated generated-report directory."""

    base = Path(root).resolve()
    if not base.exists() or retention_seconds <= 0:
        return 0
    cutoff = (time.time() if now is None else float(now)) - float(retention_seconds)
    removed = 0
    for item in base.rglob("*"):
        if not item.is_file():
            continue
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
                removed += 1
        except OSError:
            continue
    for directory in sorted((item for item in base.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def allocate_report_path(
    root: str | Path,
    filename_prefix: str,
    extension: str,
    *,
    user: Mapping[str, Any] | None,
    retention_seconds: float,
) -> Path:
    """Allocate an isolated, collision-resistant report path for one portal user."""

    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    cleanup_generated_reports(base, retention_seconds=retention_seconds)
    owner_dir = base / report_owner_key(user)
    owner_dir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_segment(filename_prefix, "relatorio")
    suffix = _safe_segment(str(extension).lstrip("."), "bin")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return owner_dir / f"{prefix}_{stamp}_{uuid.uuid4().hex}.{suffix}"
