"""Restaura um dump do Sistema de Notas em um banco PostgreSQL temporario.

O banco operacional nunca e alterado. Por padrao, o drill so aceita PostgreSQL
local e sempre remove o banco temporario ao terminar.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import unquote, urlparse

import psycopg
from psycopg import sql


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app_config import DATABASE_URL  # noqa: E402
from agricola_shared.demo_safety import assert_demo_database_target
from database import _find_pg_tool  # noqa: E402


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _connection_kwargs(parsed, database: str) -> dict[str, object]:
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": database,
    }


def _run_pg_restore(dump: Path, parsed, database: str) -> None:
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    command = [
        _find_pg_tool("pg_restore"),
        "--exit-on-error",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host",
        parsed.hostname or "127.0.0.1",
        "--port",
        str(parsed.port or 5432),
        "--username",
        unquote(parsed.username or ""),
        "--dbname",
        database,
        str(dump),
    ]
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "pg_restore falhou").strip()
        raise RuntimeError(message)


def run_drill(dump: Path, *, allow_remote: bool = False) -> dict[str, object]:
    dump = dump.resolve(strict=True)
    if not DATABASE_URL:
        raise RuntimeError("APP_NOTAS_DATABASE_URL nao configurada.")

    parsed = urlparse(DATABASE_URL)
    host = (parsed.hostname or "127.0.0.1").lower()
    if host not in LOCAL_HOSTS:
        raise RuntimeError("Drill recusado: o PostgreSQL configurado nao e local.")
    assert_demo_database_target(DATABASE_URL)

    source_database = parsed.path.lstrip("/")
    if not source_database:
        raise RuntimeError("Banco de origem ausente na configuracao.")

    temporary_database = f"oa_demo_restore_drill_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(**_connection_kwargs(parsed, "postgres"), autocommit=True)
    created = False
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            allowed = cursor.fetchone()
            if not allowed or not bool(allowed[0]):
                raise RuntimeError("A credencial configurada nao pode criar o banco temporario.")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(temporary_database)))
            created = True

        _run_pg_restore(dump, parsed, temporary_database)

        with psycopg.connect(**_connection_kwargs(parsed, temporary_database)) as restored:
            with restored.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.notas') IS NOT NULL")
                if not bool(cursor.fetchone()[0]):
                    raise RuntimeError("Dump restaurado sem a tabela obrigatoria notas.")
                cursor.execute("SELECT COUNT(*) FROM notas")
                notes = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
                )
                tables = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT numero, motorista_nome FROM notas "
                    "WHERE numero IN (31, 32, 33) AND motorista_nome LIKE 'Teste %' "
                    "ORDER BY numero"
                )
                test_markers = [
                    {"numero": int(row[0]), "motorista": str(row[1])}
                    for row in cursor.fetchall()
                ]

        return {
            "ok": True,
            "dump": dump.name,
            "bytes": dump.stat().st_size,
            "database": source_database,
            "tables": tables,
            "notes": notes,
            "accidentalTestMarkers": test_markers,
            "temporaryDatabaseRemoved": True,
        }
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (temporary_database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(temporary_database)))
        admin.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", required=True, type=Path)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    try:
        result = run_drill(args.dump, allow_remote=args.allow_remote)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
