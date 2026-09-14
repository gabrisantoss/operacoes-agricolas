from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse


@dataclass(frozen=True)
class PostgresTarget:
    host: str
    port: str
    database: str
    user: str
    password: str
    label: str


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key.strip():
            data[key.strip()] = value
    return data


def redact_postgres_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.password is None:
        return value

    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}:***@" if username else "***@"
    return urlunparse(parsed._replace(netloc=f"{auth}{host}{port}"))


def target_from_url(database_url: str, default_database: str) -> PostgresTarget:
    parsed = urlparse(str(database_url or "").strip())
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("DATABASE_URL PostgreSQL invalida")

    return PostgresTarget(
        host=parsed.hostname or "127.0.0.1",
        port=str(parsed.port or 5432),
        database=unquote(parsed.path.lstrip("/") or default_database),
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        label=redact_postgres_url(database_url),
    )


def find_pg_tool(name: str) -> str | None:
    candidate = shutil.which(name)
    if candidate:
        return candidate

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for path in sorted(program_files.glob(f"PostgreSQL/*/bin/{name}.exe"), reverse=True):
        if path.exists():
            return str(path)
    return None


def run_pg_tool(target: PostgresTarget, tool_name: str, args: list[str]) -> str:
    executable = find_pg_tool(tool_name)
    if not executable:
        raise RuntimeError(f"{tool_name}.exe nao encontrado")

    env = os.environ.copy()
    env["PGPASSWORD"] = target.password
    completed = subprocess.run(
        [executable, *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def psql_scalar(target: PostgresTarget, query: str) -> str:
    return run_pg_tool(
        target,
        "psql",
        [
            "-h",
            target.host,
            "-p",
            target.port,
            "-U",
            target.user,
            "-d",
            target.database,
            "-tAc",
            query,
        ],
    )


def psql_execute(target: PostgresTarget, sql: str) -> str:
    return run_pg_tool(
        target,
        "psql",
        [
            "-h",
            target.host,
            "-p",
            target.port,
            "-U",
            target.user,
            "-d",
            target.database,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-c",
            sql,
        ],
    )


def psql_file(target: PostgresTarget, file_path: Path) -> str:
    return run_pg_tool(
        target,
        "psql",
        [
            "-h",
            target.host,
            "-p",
            target.port,
            "-U",
            target.user,
            "-d",
            target.database,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-f",
            str(file_path),
        ],
    )
