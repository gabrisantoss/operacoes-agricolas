"""Restore operacional, explicito e transacional do PostgreSQL do Sistema de Notas."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlparse

import psycopg


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent
for path in (WORKSPACE_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app_config import DATABASE_URL  # noqa: E402
from agricola_shared.demo_safety import assert_demo_database_target
from database import _find_pg_tool, run_pg_dump  # noqa: E402
try:  # modulo durante testes; script durante operacao manual
    from .restore_drill_postgres import run_drill  # type: ignore[import-not-found]  # noqa: E402
except ImportError:
    from restore_drill_postgres import run_drill  # noqa: E402


CONFIRMATION = "RESTORE_APP_NOTAS"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _pg_env(parsed) -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    return env


def _base_command(tool: str, parsed, database: str) -> list[str]:
    return [
        _find_pg_tool(tool),
        "--host",
        parsed.hostname or "127.0.0.1",
        "--port",
        str(parsed.port or 5432),
        "--username",
        unquote(parsed.username or ""),
        "--dbname",
        database,
    ]


def _verify_dump(dump: Path, parsed) -> int:
    completed = subprocess.run(
        [_find_pg_tool("pg_restore"), "--list", str(dump)],
        env=_pg_env(parsed),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Dump invalido").strip())
    entries = sum(1 for line in completed.stdout.splitlines() if line and not line.startswith(";"))
    if entries < 1:
        raise RuntimeError("Dump sem entradas restauraveis.")
    return entries


def _write_sha256_sidecar(path: Path) -> tuple[str, Path]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    temporary = sidecar.with_suffix(sidecar.suffix + ".tmp")
    temporary.write_text(f"{value}  {path.name}\n", encoding="ascii")
    temporary.replace(sidecar)
    return value, sidecar


def _connection_kwargs(parsed, database: str) -> dict[str, object]:
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": database,
    }


def restore(dump: Path, backup_dir: Path, confirmation: str) -> dict[str, object]:
    if confirmation != CONFIRMATION:
        raise RuntimeError(f"Confirmacao invalida; use exatamente {CONFIRMATION}.")
    if not DATABASE_URL:
        raise RuntimeError("APP_NOTAS_DATABASE_URL nao configurada.")

    dump = dump.resolve(strict=True)
    parsed = urlparse(DATABASE_URL)
    host = (parsed.hostname or "127.0.0.1").lower()
    database = parsed.path.lstrip("/")
    if host not in LOCAL_HOSTS:
        raise RuntimeError("Restore recusado: o PostgreSQL configurado nao e local.")
    if database != "oa_demo_notas":
        raise RuntimeError("Restore recusado: o alvo configurado nao e oa_demo_notas.")
    assert_demo_database_target(DATABASE_URL)

    drill = run_drill(dump)
    source_entries = _verify_dump(dump, parsed)

    maintenance = psycopg.connect(**_connection_kwargs(parsed, "postgres"))
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            active_sessions = int(cursor.fetchone()[0])
    finally:
        maintenance.close()
    if active_sessions:
        raise RuntimeError(f"Restore recusado: {active_sessions} sessao(oes) ativa(s) em app_notas.")

    backup_dir = backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rollback_dump = backup_dir / f"pre_restore_app_notas_{timestamp}.dump"
    run_pg_dump(DATABASE_URL, rollback_dump)
    rollback_entries = _verify_dump(rollback_dump, parsed)
    rollback_sha256, rollback_sidecar = _write_sha256_sidecar(rollback_dump)

    command = _base_command("pg_restore", parsed, database)
    command[1:1] = [
        "--exit-on-error",
        "--single-transaction",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
    ]
    command.append(str(dump))
    completed = subprocess.run(
        command,
        env=_pg_env(parsed),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "pg_restore falhou").strip())

    with psycopg.connect(**_connection_kwargs(parsed, database)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.notas') IS NOT NULL")
            if not bool(cursor.fetchone()[0]):
                raise RuntimeError("Restore concluiu sem a tabela obrigatoria notas.")
            cursor.execute("SELECT COUNT(*) FROM notas")
            notes = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT numero, motorista_nome FROM notas "
                "WHERE numero IN (31, 32, 33) AND motorista_nome LIKE 'Teste %' ORDER BY numero"
            )
            markers = [
                {"numero": int(row[0]), "motorista": str(row[1])}
                for row in cursor.fetchall()
            ]

    return {
        "ok": True,
        "database": database,
        "sourceDump": dump.name,
        "sourceEntries": source_entries,
        "sourceDrill": drill,
        "rollbackDump": str(rollback_dump),
        "rollbackEntries": rollback_entries,
        "rollbackSha256": rollback_sha256,
        "rollbackSidecar": str(rollback_sidecar),
        "notes": notes,
        "testMarkers": markers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    try:
        result = restore(args.dump, args.backup_dir, args.confirm)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
