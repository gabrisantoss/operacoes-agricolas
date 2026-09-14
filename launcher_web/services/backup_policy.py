from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


BACKUP_NAME_RE = re.compile(r"^portal_agricola_(\d{8}_\d{6})\.zip$")
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s{2}([^\r\n]+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_sidecar_path(backup_path: Path) -> Path:
    return backup_path.with_name(backup_path.name + ".sha256")


def write_checksum_sidecar(backup_path: Path) -> dict:
    checksum = sha256_file(backup_path)
    sidecar = checksum_sidecar_path(backup_path)
    temporary = sidecar.with_name(f".{sidecar.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(f"{checksum}  {backup_path.name}\n", encoding="ascii")
        temporary.replace(sidecar)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "algorithm": "sha256", "value": checksum, "file": sidecar.name}


def verify_checksum_sidecar(backup_path: Path, *, require: bool = False) -> dict:
    sidecar = checksum_sidecar_path(backup_path)
    if not sidecar.exists():
        return {
            "ok": not require,
            "present": False,
            "message": "Checksum sidecar ausente." if require else "Backup legado sem checksum sidecar.",
        }
    try:
        content = sidecar.read_text(encoding="ascii").strip()
    except OSError:
        return {"ok": False, "present": True, "message": "Checksum sidecar ilegivel."}
    match = CHECKSUM_RE.fullmatch(content)
    if not match or Path(match.group(2)).name != backup_path.name:
        return {"ok": False, "present": True, "message": "Formato do checksum sidecar invalido."}
    expected = match.group(1).lower()
    actual = sha256_file(backup_path)
    return {
        "ok": expected == actual,
        "present": True,
        "algorithm": "sha256",
        "value": actual,
        "message": "Checksum confirmado." if expected == actual else "Checksum do ZIP nao confere.",
    }


def _backup_datetime(path: Path) -> datetime:
    match = BACKUP_NAME_RE.fullmatch(path.name)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def build_retention_plan(
    backup_paths: list[Path],
    *,
    daily: int = 14,
    weekly: int = 8,
    monthly: int = 12,
) -> dict:
    ordered = sorted(backup_paths, key=_backup_datetime, reverse=True)
    reasons: dict[str, set[str]] = {}

    def keep(path: Path, reason: str) -> None:
        reasons.setdefault(path.name, set()).add(reason)

    if ordered:
        keep(ordered[0], "latest")

    buckets = (
        ("daily", max(daily, 0), lambda stamp: stamp.date().isoformat()),
        ("weekly", max(weekly, 0), lambda stamp: f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"),
        ("monthly", max(monthly, 0), lambda stamp: f"{stamp.year:04d}-{stamp.month:02d}"),
    )
    for reason, limit, key_for in buckets:
        selected: set[str] = set()
        for path in ordered:
            if len(selected) >= limit:
                break
            bucket = key_for(_backup_datetime(path))
            if bucket in selected:
                continue
            selected.add(bucket)
            keep(path, reason)

    keep_names = [path.name for path in ordered if path.name in reasons]
    candidates = [path.name for path in ordered if path.name not in reasons]
    return {
        "policy": {"daily": max(daily, 0), "weekly": max(weekly, 0), "monthly": max(monthly, 0)},
        "total": len(ordered),
        "keep": keep_names,
        "reasons": {name: sorted(values) for name, values in sorted(reasons.items())},
        "deleteCandidates": candidates,
    }


def apply_retention_plan(backup_dir: Path, plan: dict, *, enabled: bool = False) -> dict:
    candidates = [str(name) for name in plan.get("deleteCandidates") or []]
    if not enabled:
        return {"enabled": False, "deleted": [], "planned": candidates}
    deleted: list[str] = []
    errors: list[str] = []
    root = backup_dir.resolve()
    for name in candidates:
        if not BACKUP_NAME_RE.fullmatch(Path(name).name) or Path(name).name != name:
            errors.append(f"Nome de backup recusado: {Path(name).name}")
            continue
        target = (root / name).resolve()
        if target.parent != root or not target.exists():
            errors.append(f"Backup nao encontrado para retencao: {name}")
            continue
        try:
            target.unlink()
            checksum_sidecar_path(target).unlink(missing_ok=True)
            deleted.append(name)
        except OSError:
            errors.append(f"Falha ao remover backup previsto: {name}")
    return {"enabled": True, "deleted": deleted, "planned": candidates, "errors": errors, "ok": not errors}


def replicate_backup_offsite(backup_path: Path, offsite_dir: Path | None) -> dict:
    if offsite_dir is None:
        return {
            "configured": False,
            "ok": None,
            "message": "Offsite nao configurado; defina PORTAL_BACKUP_OFFSITE_DIR para habilitar.",
        }

    try:
        destination_root = offsite_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return {"configured": True, "ok": False, "message": "Diretorio offsite inexistente ou inacessivel."}
    if not destination_root.is_dir():
        return {"configured": True, "ok": False, "message": "Destino offsite nao e um diretorio."}

    local_root = backup_path.parent.resolve()
    if destination_root == local_root or local_root in destination_root.parents or destination_root in local_root.parents:
        return {"configured": True, "ok": False, "message": "Destino offsite deve ficar fora do diretorio local de backups."}

    checksum = verify_checksum_sidecar(backup_path, require=True)
    if not checksum.get("ok"):
        return {"configured": True, "ok": False, "message": "Copia offsite recusada: checksum local invalido."}

    destination = destination_root / backup_path.name
    destination_sidecar = checksum_sidecar_path(destination)
    if destination.exists():
        existing = verify_checksum_sidecar(destination, require=True)
        if existing.get("ok") and existing.get("value") == checksum.get("value"):
            return {
                "configured": True,
                "ok": True,
                "copied": False,
                "validated": True,
                "file": destination.name,
                "message": "Copia offsite ja existia e foi validada.",
            }
        return {"configured": True, "ok": False, "message": "Destino offsite ja possui arquivo divergente; nada foi sobrescrito."}

    try:
        free = shutil.disk_usage(destination_root).free
        if free < backup_path.stat().st_size + 64 * 1024 * 1024:
            return {"configured": True, "ok": False, "message": "Espaco insuficiente no destino offsite."}
    except OSError:
        pass

    partial = destination_root / f".{backup_path.name}.{os.getpid()}.partial"
    partial_sidecar = destination_root / f".{destination_sidecar.name}.{os.getpid()}.partial"
    try:
        shutil.copy2(backup_path, partial)
        copied_checksum = sha256_file(partial)
        if copied_checksum != checksum.get("value"):
            return {"configured": True, "ok": False, "message": "Checksum da copia offsite nao confere."}
        partial_sidecar.write_text(f"{copied_checksum}  {destination.name}\n", encoding="ascii")
        partial.replace(destination)
        partial_sidecar.replace(destination_sidecar)
        return {
            "configured": True,
            "ok": True,
            "copied": True,
            "validated": True,
            "file": destination.name,
            "message": "Copia offsite criada e validada por SHA-256.",
        }
    except OSError:
        return {"configured": True, "ok": False, "message": "Falha de E/S ao copiar o backup para offsite."}
    finally:
        partial.unlink(missing_ok=True)
        partial_sidecar.unlink(missing_ok=True)
