from __future__ import annotations

import json
import hashlib
import hmac
import io
import math
import os
import mimetypes
import re
import secrets
import shutil
import socket
from typing import Any
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from contextlib import nullcontext
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape
from email.parser import BytesParser
from email.policy import default as email_policy

from core.logging_config import configure_portal_logging, ensure_log_dirs
from core.request_context import new_request_id
from services.backup_service import sqlite_integrity_check
from services.backup_policy import (
    apply_retention_plan,
    build_retention_plan,
    checksum_sidecar_path,
    replicate_backup_offsite,
    sha256_file,
    verify_checksum_sidecar,
    write_checksum_sidecar,
)
from services.health_service import check_system, check_tcp_port, timestamp_text
from services.system_registry import enabled_systems, load_systems, systems_by_id


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
    except OSError:
        pass


if os.environ.get("PORTAL_SKIP_LOCAL_ENV", "0") != "1":
    load_local_env(BASE_DIR / "launcher_web.env")

from agricola_shared.db_compat import connect as connect_postgres_db

PUBLIC_DIR = BASE_DIR / "public"
SYSTEMS_CONFIG = BASE_DIR / "config" / "systems.json"
LOG_ROOT = ROOT_DIR / "logs"
LOG_DIR = Path(os.environ.get("PORTAL_LOG_DIR", LOG_ROOT / "portal"))
# AUTH_DB (launcher_auth.db) is kept as a reference path for legacy backups only.
# The active database engine is exclusively PostgreSQL.
AUTH_DB = BASE_DIR / "launcher_auth.db"
PORTAL_DATABASE_URL = os.environ.get("PORTAL_DATABASE_URL", "").strip()
PORT = int(os.environ.get("LAUNCHER_WEB_PORT", "8890"))
PORTAL_VERSION = os.environ.get("PORTAL_VERSION", "0.2.1")
PORTAL_SCHEMA_VERSION = "002"
PORTAL_STARTED_AT = time.time()
FRIENDLY_HOST = os.environ.get("LAUNCHER_FRIENDLY_HOST", "localhost").strip() or "localhost"
# Identidade funcional atual. "balanca" permanece como namespace tecnico
# legado em ids, rotas, banco, backups e integracoes para evitar quebra.
SYSTEM_CURRENT_NAME = "Portal de Opera\u00e7\u00f5es Agr\u00edcolas"
SYSTEM_CURRENT_NAME_ASCII = "Portal de Operacoes Agricolas"
SYSTEM_LEGACY_NAMESPACE = "balanca"
SYSTEM_LEGACY_NAMES = ("Balanca Audit", "Auditoria da Balanca")
SESSION_COOKIE = "oa_demo_session"
SESSION_SECONDS = 60 * 60 * 12
REMEMBER_SESSION_SECONDS = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 200_000
AUDIT_EVENT_LIMIT = 200
BACKUP_DIR = Path(os.environ.get("PORTAL_BACKUP_DIR", ROOT_DIR / "backups_portal_agricola"))
BACKUP_INTERVAL_SECONDS = int(os.environ.get("PORTAL_BACKUP_INTERVAL_SECONDS", str(60 * 60 * 6)))
BACKUP_RETENTION_DAILY = max(int(os.environ.get("PORTAL_BACKUP_RETENTION_DAILY", "14")), 0)
BACKUP_RETENTION_WEEKLY = max(int(os.environ.get("PORTAL_BACKUP_RETENTION_WEEKLY", "8")), 0)
BACKUP_RETENTION_MONTHLY = max(int(os.environ.get("PORTAL_BACKUP_RETENTION_MONTHLY", "12")), 0)
BACKUP_RETENTION_APPLY = os.environ.get("PORTAL_BACKUP_RETENTION_APPLY", "0") == "1"
BACKUP_STATE_FILE = BACKUP_DIR / "backup_state.json"
BACKUP_RETENTION_PLAN_FILE = BACKUP_DIR / "backup_retention_plan.json"
BACKUP_TEMP_DIR = BASE_DIR / ".backup_tmp"
_BACKUP_OFFSITE_VALUE = os.environ.get("PORTAL_BACKUP_OFFSITE_DIR", "").strip()
BACKUP_OFFSITE_DIR = Path(_BACKUP_OFFSITE_VALUE) if _BACKUP_OFFSITE_VALUE else None
RESTORE_PREP_DIR = ROOT_DIR / "restauracoes_portal_agricola"
STATUS_TCP_TIMEOUT = float(os.environ.get("LAUNCHER_STATUS_TCP_TIMEOUT", "0.85"))
STATUS_HTTP_TIMEOUT = float(os.environ.get("LAUNCHER_STATUS_HTTP_TIMEOUT", "2.5"))
PROXY_TIMEOUT_SECONDS = float(os.environ.get("LAUNCHER_PROXY_TIMEOUT_SECONDS", "12"))
REPORT_PROXY_TIMEOUT_SECONDS = float(os.environ.get("LAUNCHER_REPORT_PROXY_TIMEOUT_SECONDS", "120"))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("LAUNCHER_MONITOR_INTERVAL_SECONDS", "45"))
APP_START_GRACE_SECONDS = int(os.environ.get("LAUNCHER_APP_START_GRACE_SECONDS", "90"))
AUTOSTART_APPS = os.environ.get("LAUNCHER_AUTOSTART_APPS", "1") == "1"
ADMIN_USER = os.environ.get("LAUNCHER_ADMIN_USER", "admin@example.invalid").strip() or "admin@example.invalid"
ADMIN_PASSWORD = os.environ.get("LAUNCHER_ADMIN_PASSWORD", "").strip()
ADMIN_BOOTSTRAP_FILE = BASE_DIR / "admin-bootstrap.txt"
FULL_ACCESS_ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("PORTAL_FULL_ACCESS_ADMIN_EMAILS", ADMIN_USER).split(",")
    if email.strip()
}
MAINTENANCE_OPEN_SYSTEM_IDS = {
    system_id.strip()
    for system_id in os.environ.get("PORTAL_MAINTENANCE_OPEN_SYSTEM_IDS", "balanca").split(",")
    if system_id.strip()
}
GLOBAL_MAINTENANCE_MESSAGE = os.environ.get(
    "PORTAL_GLOBAL_MAINTENANCE_MESSAGE",
    "Em manutencao. Acesso temporariamente indisponivel.",
)
MAX_JSON_BODY_BYTES = int(os.environ.get("LAUNCHER_MAX_JSON_BODY_BYTES", "65536"))
PROXY_MAX_REQUEST_BODY_BYTES = max(
    int(os.environ.get("LAUNCHER_PROXY_MAX_REQUEST_BODY_BYTES", str(64 * 1024 * 1024))),
    64 * 1024 * 1024,
)
PROXY_MAX_RESPONSE_BODY_BYTES = max(
    int(os.environ.get("LAUNCHER_PROXY_MAX_RESPONSE_BODY_BYTES", str(128 * 1024 * 1024))),
    1024 * 1024,
)
BACKUP_MANIFEST_MAX_BYTES = max(
    int(os.environ.get("PORTAL_BACKUP_MANIFEST_MAX_BYTES", str(1024 * 1024))),
    64 * 1024,
)
PORTAL_HTTPS_ENABLED = os.environ.get("PORTAL_HTTPS_ENABLED", "0") == "1"
TRUSTED_PROXY_IPS = {
    value.strip()
    for value in os.environ.get("PORTAL_TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    if value.strip()
}
PORTAL_ALLOWED_ORIGINS = {
    value.strip().rstrip("/").lower()
    for value in os.environ.get("PORTAL_ALLOWED_ORIGINS", "").split(",")
    if value.strip()
}
LOGIN_WINDOW_SECONDS = int(os.environ.get("LAUNCHER_LOGIN_WINDOW_SECONDS", str(15 * 60)))
LOGIN_ACCOUNT_MAX_ATTEMPTS = int(os.environ.get("LAUNCHER_LOGIN_ACCOUNT_MAX_ATTEMPTS", "6"))
LOGIN_IP_MAX_ATTEMPTS = int(os.environ.get("LAUNCHER_LOGIN_IP_MAX_ATTEMPTS", "20"))
APP_BIND_HOST = os.environ.get("LAUNCHER_APP_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORTAL_DEV_MODE = os.environ.get("PORTAL_DEV_MODE", "0") == "1"
BALANCA_DEV_PROXY = os.environ.get("PORTAL_BALANCA_DEV_PROXY", "0") == "1"
PORTAL_LOGGER = configure_portal_logging(LOG_ROOT, LOG_DIR)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
PYTHON_FALLBACK = Path(
    os.environ.get(
        "PYTHON_EXE",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
    )
)

STARTED_PROCESSES: dict[str, subprocess.Popen] = {}
STARTED_AT: dict[str, float] = {}
DESIRED_WEB_APPS: set[str] = set()
START_LOCK = threading.Lock()
LOGIN_ATTEMPTS: dict[str, dict[str, float | int]] = {}
LOGIN_LOCK = threading.Lock()


def proxy_timeout_for(app_id: str, target_path: str) -> float:
    if app_id == "notas" and ('relatorios' in target_path or 'export' in target_path or 'imports' in target_path):
        return REPORT_PROXY_TIMEOUT_SECONDS
    return PROXY_TIMEOUT_SECONDS


def first_existing_path(*paths: Path) -> Path:
    for candidate in paths:
        if candidate.exists():
            return candidate
    return paths[-1]


class RequestBodyTooLarge(Exception):
    pass


class ProxyResponseTooLarge(Exception):
    pass


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def archive_member_is_safe(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    member = PurePosixPath(normalized)
    return bool(normalized) and not member.is_absolute() and ".." not in member.parts and not member.drive


def read_limited_proxy_response(stream, headers) -> bytes:
    declared_length = headers.get("Content-Length")
    if declared_length:
        try:
            parsed_length = int(declared_length)
            if parsed_length < 0 or parsed_length > PROXY_MAX_RESPONSE_BODY_BYTES:
                raise ProxyResponseTooLarge
        except ValueError as exc:
            raise ProxyResponseTooLarge from exc
    body = stream.read(PROXY_MAX_RESPONSE_BODY_BYTES + 1)
    if len(body) > PROXY_MAX_RESPONSE_BODY_BYTES:
        raise ProxyResponseTooLarge
    return body


SYSTEMS = load_systems(SYSTEMS_CONFIG)
SYSTEMS_BY_ID = systems_by_id(SYSTEMS)
ENABLED_SYSTEMS = enabled_systems(SYSTEMS)


def system_config(system_id: str) -> dict:
    return SYSTEMS_BY_ID.get(system_id, {})


def system_text(system_id: str, key: str, default: str = "") -> str:
    return str(system_config(system_id).get(key, default) or default)


def system_int(system_id: str, key: str, default: int) -> int:
    try:
        return int(system_config(system_id).get(key, default))
    except (TypeError, ValueError):
        return default


APPS = [
    {
        "id": "notas",
        "legacy_ids": ["app_notas"],
        "name": system_text("notas", "name", "Sistema de Notas"),
        "audit_module": "notas",
        "description": "Notas e transporte da safra.",
        "kind": "web",
        "path": ROOT_DIR / "app_notas",
        "launcher": ROOT_DIR / "app_notas" / "start_web.bat",
        "command": [
            str(first_existing_path(ROOT_DIR / "app_notas" / ".venv" / "Scripts" / "python.exe", PYTHON_FALLBACK)),
            str(ROOT_DIR / "app_notas" / "web_app" / "server.py"),
            "--host",
            APP_BIND_HOST,
            "--port",
            str(system_int("notas", "internal_port", 8891)),
        ],
        "web_port": system_int("notas", "internal_port", 8891),
        "public_path": system_text("notas", "public_path", "/notas"),
        "health_path": "/api/health",
        "health_url": system_text("notas", "health_url", "http://127.0.0.1:8891/api/health"),
        "requires_auth": bool(system_config("notas").get("requires_auth", True)),
        "enabled": bool(system_config("notas").get("enabled", True)),
        "stack": system_text("notas", "stack", "Python + PyQt5 + web estatico + SQLite"),
        "button": "Iniciar web",
    },
    {
        "id": "colaboradores",
        "legacy_ids": ["app_colaboradores"],
        "name": system_text("colaboradores", "name", "Gestor de Colaboradores"),
        "audit_module": "colaboradores",
        "description": "Cadastros, CNH e documentos.",
        "kind": "web",
        "path": ROOT_DIR / "app_colaboradores",
        "launcher": ROOT_DIR / "app_colaboradores" / "start_web.bat",
        "command": [
            str(first_existing_path(ROOT_DIR / "app_colaboradores" / ".venv_web" / "Scripts" / "python.exe", PYTHON_FALLBACK)),
            str(ROOT_DIR / "app_colaboradores" / "web_app" / "server.py"),
            "--host",
            APP_BIND_HOST,
            "--port",
            str(system_int("colaboradores", "internal_port", 8892)),
            "--no-browser",
        ],
        "web_port": system_int("colaboradores", "internal_port", 8892),
        "public_path": system_text("colaboradores", "public_path", "/colaboradores"),
        "health_path": "/api/health",
        "health_url": system_text("colaboradores", "health_url", "http://127.0.0.1:8892/api/health"),
        "requires_auth": bool(system_config("colaboradores").get("requires_auth", True)),
        "enabled": bool(system_config("colaboradores").get("enabled", True)),
        "stack": system_text("colaboradores", "stack", "Python + PyQt5 + web estatico + SQLite"),
        "button": "Iniciar web",
        "admin_only": bool(system_config("colaboradores").get("admin_only", True)),
        "allow_granular_permission": bool(system_config("colaboradores").get("allow_granular_permission", True)),
        "maintenance_message": "Em manutencao. Acesso temporariamente restrito ao administrador.",
    },
    {
        "id": "balanca",
        "legacy_ids": ["balanca_audit"],
        "name": system_text("balanca", "name", SYSTEM_CURRENT_NAME),
        "audit_module": "balanca",
        "description": "Colheita, pesagem, PDFs e divergencias operacionais.",
        "kind": "web",
        "path": ROOT_DIR / "balanca-audit",
        "command": ["cmd.exe", "/c", "npm.cmd", "run", "start:api"],
        "dev_command": ["cmd.exe", "/c", "npm.cmd", "run", "start:browser"],
        "web_port": system_int("balanca", "internal_port", 8873),
        "api_port": system_int("balanca", "api_port", 8833),
        "public_path": system_text("balanca", "public_path", "/balanca"),
        "api_public_path": system_text("balanca", "api_path", "/balanca-api"),
        "health_path": "/health",
        "health_port": system_int("balanca", "api_port", 8833),
        "health_url": system_text("balanca", "health_url", "http://127.0.0.1:8833/health"),
        "requires_auth": bool(system_config("balanca").get("requires_auth", True)),
        "enabled": bool(system_config("balanca").get("enabled", True)),
        "stack": system_text("balanca", "stack", "TypeScript + React + Vite + Node.js + Express + PostgreSQL"),
        "static_dist": ROOT_DIR / "balanca-audit" / "apps" / "web" / "dist",
        "dev_proxy": BALANCA_DEV_PROXY or PORTAL_DEV_MODE,
        "button": "Iniciar web",
        "allow_stale_cleanup": True,
    },
    {
        "id": "analises",
        "name": system_text("analises", "name", "Analises Operacionais"),
        "audit_module": "analises",
        "description": "Indicadores da operacao.",
        "kind": "web",
        "path": ROOT_DIR / "analises",
        "launcher": ROOT_DIR / "analises" / "start_web.bat",
        "command": [
            str(
                first_existing_path(
                    ROOT_DIR / "analises" / ".venv312" / "Scripts" / "python.exe",
                    ROOT_DIR / "analises" / "venv" / "Scripts" / "python.exe",
                    PYTHON_FALLBACK,
                )
            ),
            str(ROOT_DIR / "analises" / "web_app" / "server.py"),
            "--host",
            APP_BIND_HOST,
            "--port",
            str(system_int("analises", "internal_port", 8888)),
        ],
        "web_port": system_int("analises", "internal_port", 8888),
        "public_path": system_text("analises", "public_path", "/analises"),
        "health_path": "/api/health",
        "health_url": system_text("analises", "health_url", "http://127.0.0.1:8888/api/health"),
        "requires_auth": bool(system_config("analises").get("requires_auth", True)),
        "enabled": bool(system_config("analises").get("enabled", True)),
        "stack": system_text("analises", "stack", "Python + web estatico + SQLite"),
        "button": "Iniciar web",
    },
]

APPS = [app for app in APPS if app.get("enabled", True)]

# BACKUP_DATABASES (legacy SQLite list) was removed.
# Backup sources are now resolved dynamically by backup_database_sources().

BACKUP_FOLDERS = [
    ("notas_relatorios_web", ROOT_DIR / "app_notas" / "web_app" / "generated"),
    ("colaboradores_documentos", ROOT_DIR / "app_colaboradores" / "documentos"),
    ("colaboradores_relatorios", ROOT_DIR / "app_colaboradores" / "relatorios_gerados"),
    ("colaboradores_relatorios_web", ROOT_DIR / "app_colaboradores" / "web_app" / "generated"),
    ("analises_arquivos_entrada", ROOT_DIR / "analises" / "input_scans"),
    ("balanca_analises", ROOT_DIR / "balanca-audit" / "apps" / "api" / "analysis-files"),
]
BACKUP_FORMAT_VERSION = 2
REQUIRED_BACKUP_DATABASE_LABELS = frozenset({"portal", "notas", "colaboradores", "analises", "balanca"})

BACKUP_LOCK = threading.Lock()
BACKUP_STATUS = {
    "running": False,
    "lastRunAt": None,
    "lastCreatedAt": None,
    "lastFile": "",
    "lastMessage": "Backup ainda nao executado.",
    "lastError": "",
    "offsite": {"configured": bool(BACKUP_OFFSITE_DIR), "ok": None},
    "retention": {},
}


def now_ts() -> int:
    return int(time.time())


def initial_admin_password() -> str:
    if ADMIN_PASSWORD:
        return ADMIN_PASSWORD

    password = secrets.token_urlsafe(18)
    ADMIN_BOOTSTRAP_FILE.write_text(
        (
            f"{SYSTEM_CURRENT_NAME} - senha temporaria do primeiro admin\n"
            f"Usuario: {normalize_email(ADMIN_USER)}\n"
            f"Senha: {password}\n"
            "Use apenas no primeiro acesso e troque a senha pelo painel de liberacoes.\n"
        ),
        encoding="utf-8",
    )
    return password


def iso_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def backup_file_list() -> list[dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(BACKUP_DIR.glob("portal_agricola_*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "createdAt": int(stat.st_mtime),
            }
        )
    return items


def backup_file_by_name(name: str) -> Path:
    safe_name = Path(str(name or "")).name
    if not safe_name.startswith("portal_agricola_") or safe_name.endswith(".tmp") or not safe_name.endswith(".zip"):
        raise ValueError("Arquivo de backup invalido.")
    path = (BACKUP_DIR / safe_name).resolve()
    if not path_is_within(path, BACKUP_DIR) or not path.exists():
        raise ValueError("Backup nao encontrado.")
    return path


def read_key_value_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key.strip():
            values[key.strip()] = value
    return values


def resolve_config_path(base_dir: Path, value: str | None, default_path: Path) -> Path:
    text = str(value or "").strip()
    path = Path(text).expanduser() if text else default_path
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def build_postgres_target_from_url(database_url: str, default_database: str) -> dict[str, str]:
    parsed = urlparse(str(database_url or "").strip())
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("URL PostgreSQL invalida.")
    database = unquote(parsed.path.lstrip("/") or default_database)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "database": database,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "label": redact_database_url(database_url),
    }


def build_colaboradores_postgres_target(config: dict) -> dict[str, str]:
    explicit_url = str(config.get("database_url") or "").strip()
    if explicit_url:
        return build_postgres_target_from_url(explicit_url, "app_colaboradores")

    host = str(config.get("postgres_host") or "127.0.0.1").strip()
    port = str(config.get("postgres_port") or 5432).strip()
    database = str(config.get("postgres_database") or "app_colaboradores").strip()
    user = str(config.get("postgres_user") or os.environ.get("USERNAME") or "").strip()
    password = str(config.get("postgres_password") or "")
    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "label": f"postgresql://{user}:***@{host}:{port}/{database}",
    }


def backup_database_sources() -> list[dict]:
    """Resolve all database sources for backup.
    The portal database is always PostgreSQL. Other subsystems (notas, colaboradores,
    analises, balanca) may be SQLite or PostgreSQL based on their own env files.
    """
    sources: list[dict] = []

    # Portal / launcher_web — always PostgreSQL
    if not PORTAL_DATABASE_URL:
        raise RuntimeError("PORTAL_DATABASE_URL nao configurada. O launcher_web requer PostgreSQL.")
    sources.append(
        {
            "label": "portal",
            "engine": "postgresql",
            "target": build_postgres_target_from_url(PORTAL_DATABASE_URL, "portal_agricola"),
        }
    )

    notas_env_path = ROOT_DIR / "app_notas" / "app_notas.env"
    notas_env = read_key_value_file(notas_env_path)
    notas_engine = str(notas_env.get("APP_NOTAS_DB_ENGINE") or "sqlite").strip().lower()
    if notas_engine in {"postgres", "postgresql"} and notas_env.get("APP_NOTAS_DATABASE_URL"):
        sources.append(
            {
                "label": "notas",
                "engine": "postgresql",
                "target": build_postgres_target_from_url(notas_env["APP_NOTAS_DATABASE_URL"], "app_notas"),
            }
        )
    else:
        sources.append(
            {
                "label": "notas",
                "engine": "sqlite",
                "path": resolve_config_path(notas_env_path.parent, notas_env.get("APP_NOTAS_DB_PATH"), ROOT_DIR / "app_notas" / "transporte.db"),
            }
        )

    colab_config_path = ROOT_DIR / "app_colaboradores" / "app_config.json"
    colab_config = {}
    try:
        colab_config = json.loads(colab_config_path.read_text(encoding="utf-8-sig")) if colab_config_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        colab_config = {}
    colab_engine = str(colab_config.get("db_engine") or "sqlite").strip().lower()
    if colab_engine in {"postgres", "postgresql"}:
        sources.append(
            {
                "label": "colaboradores",
                "engine": "postgresql",
                "target": build_colaboradores_postgres_target(colab_config),
            }
        )
    else:
        sources.append(
            {
                "label": "colaboradores",
                "engine": "sqlite",
                "path": resolve_config_path(colab_config_path.parent, colab_config.get("sqlite_path"), ROOT_DIR / "app_colaboradores" / "colaboradores.db"),
            }
        )

    analises_env_path = ROOT_DIR / "analises" / "analises.env"
    analises_env = read_key_value_file(analises_env_path)
    analises_engine = str(analises_env.get("ANALISES_DB_ENGINE") or "sqlite").strip().lower()
    if analises_engine in {"postgres", "postgresql"} and analises_env.get("ANALISES_DATABASE_URL"):
        sources.append(
            {
                "label": "analises",
                "engine": "postgresql",
                "target": build_postgres_target_from_url(analises_env["ANALISES_DATABASE_URL"], "analises_operacionais"),
            }
        )
    else:
        sources.append(
            {
                "label": "analises",
                "engine": "sqlite",
                "path": resolve_config_path(analises_env_path.parent, analises_env.get("ANALISES_DB_PATH"), ROOT_DIR / "analises" / "operacao_agricola.db"),
            }
        )

    balanca_env_path = ROOT_DIR / "balanca-audit" / "apps" / "api" / ".env"
    balanca_env = read_key_value_file(balanca_env_path)
    balanca_engine = str(balanca_env.get("DATABASE_PROVIDER") or "sqlite").strip().lower()
    if balanca_engine in {"postgres", "postgresql"} and balanca_env.get("DATABASE_URL"):
        sources.append(
            {
                "label": "balanca",
                "engine": "postgresql",
                "target": build_postgres_target_from_url(balanca_env["DATABASE_URL"], "balanca_audit"),
            }
        )
    else:
        raise RuntimeError(
            "Backup da Balanca bloqueado: DATABASE_PROVIDER=postgres e DATABASE_URL sao obrigatorios; "
            "nao sera usado um SQLite antigo como fallback."
        )

    return sources


def find_pg_tool(name: str) -> str | None:
    candidate = shutil.which(name)
    if candidate:
        return candidate

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for path in sorted(program_files.glob(f"PostgreSQL/*/bin/{name}.exe"), reverse=True):
        if path.exists():
            return str(path)
    return None


def run_pg_tool(tool_name: str, args: list[str], password: str) -> str:
    tool = find_pg_tool(tool_name)
    if not tool:
        raise RuntimeError(f"{tool_name}.exe nao encontrado.")

    env = os.environ.copy()
    env["PGPASSWORD"] = password
    completed = subprocess.run(
        [tool, *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return completed.stdout.strip()


def postgres_scalar(target: dict[str, str], query: str) -> str:
    return run_pg_tool(
        "psql",
        [
            "-h",
            target["host"],
            "-p",
            target["port"],
            "-U",
            target["user"],
            "-d",
            target["database"],
            "-tAc",
            query,
        ],
        target["password"],
    )


def postgres_source_signature(source: dict) -> dict:
    target = source["target"]
    signature = postgres_scalar(
        target,
        "SELECT pg_database_size(current_database())::text || '|' || pg_current_wal_lsn()::text;",
    )
    return {
        "type": "postgresql",
        "label": source["label"],
        "signature": signature,
    }


def backup_postgres_database(source: dict, target_dir: Path) -> dict:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = source["target"]
    label = source["label"]
    backup_file = target_dir / f"{label}.dump"

    run_pg_tool(
        "pg_dump",
        [
            "-h",
            target["host"],
            "-p",
            target["port"],
            "-U",
            target["user"],
            "-d",
            target["database"],
            "-Fc",
            "--schema=public",
            "--no-owner",
            "--no-privileges",
            "-f",
            str(backup_file),
        ],
        target["password"],
    )
    restore_list = run_pg_tool("pg_restore", ["-l", str(backup_file)], target["password"])
    stat = backup_file.stat()
    return {
        "name": label,
        "engine": "postgresql",
        "database": target["database"],
        "file": (Path("bancos") / backup_file.name).as_posix(),
        "size_bytes": stat.st_size,
        "sha256": sha256_file(backup_file),
        "pg_restore_list_lines": len([line for line in restore_list.splitlines() if line.strip()]),
    }


def source_signature() -> dict:
    sources = []
    for source in backup_database_sources():
        if source["engine"] == "postgresql":
            try:
                sources.append(postgres_source_signature(source))
            except Exception as exc:
                sources.append(
                    {
                        "type": "postgresql",
                        "label": source["label"],
                        "error": type(exc).__name__,
                    }
                )
            continue

        path = Path(source["path"])
        if path.exists():
            stat = path.stat()
            sources.append({"type": "sqlite", "label": source["label"], "size": stat.st_size, "mtime": stat.st_mtime_ns})
    for label, folder in BACKUP_FOLDERS:
        if not folder.exists():
            continue
        for file in folder.rglob("*"):
            if not file.is_file() or not should_include_backup_file(label, folder, file):
                continue
            try:
                stat = file.stat()
            except OSError:
                continue
            sources.append(
                {
                    "type": "file",
                    "label": label,
                    "relative": file.relative_to(folder).as_posix(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime_ns,
                }
            )
    return {"sources": sorted(sources, key=lambda item: str(item.get("label") or "") + ":" + str(item.get("relative") or ""))}


def read_backup_state() -> dict:
    try:
        return json.loads(BACKUP_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_backup_state(state: dict) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_sqlite_database(source: Path, target: Path) -> None:
    """Backup a SQLite file (used by subsystems that still run on SQLite)."""
    import sqlite3 as _sqlite3
    target.parent.mkdir(parents=True, exist_ok=True)
    src = _sqlite3.connect(str(source), timeout=30)
    dst = _sqlite3.connect(str(target), timeout=30)
    try:
        src.execute("PRAGMA busy_timeout = 30000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def zip_folder(zip_file: zipfile.ZipFile, label: str, folder: Path) -> int:
    if not folder.exists():
        return 0
    count = 0
    for file in folder.rglob("*"):
        if not file.is_file() or not should_include_backup_file(label, folder, file):
            continue
        try:
            arcname = Path("arquivos") / label / file.relative_to(folder)
            zip_file.write(file, arcname.as_posix())
            count += 1
        except OSError:
            if label.startswith("balanca_"):
                raise
    return count


def should_include_backup_file(label: str, folder: Path, file: Path) -> bool:
    return True


def cleanup_old_backups(*, apply: bool | None = None) -> dict:
    paths = [Path(item["path"]) for item in backup_file_list()]
    plan = build_retention_plan(
        paths,
        daily=BACKUP_RETENTION_DAILY,
        weekly=BACKUP_RETENTION_WEEKLY,
        monthly=BACKUP_RETENTION_MONTHLY,
    )
    application = apply_retention_plan(
        BACKUP_DIR,
        plan,
        enabled=BACKUP_RETENTION_APPLY if apply is None else bool(apply),
    )
    result = {**plan, "application": application}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BACKUP_RETENTION_PLAN_FILE.with_name(f".{BACKUP_RETENTION_PLAN_FILE.name}.tmp")
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(BACKUP_RETENTION_PLAN_FILE)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def verify_sqlite_file(path: Path) -> str:
    return sqlite_integrity_check(path)


def verify_postgres_dump_file(path: Path) -> dict:
    try:
        output = run_pg_tool("pg_restore", ["-l", str(path)], "")
        lines = [line for line in output.splitlines() if line.strip()]
        return {"ok": bool(lines), "entries": len(lines)}
    except Exception:
        return {"ok": False, "error": "Dump PostgreSQL invalido ou ilegivel."}


def sanitize_backup_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        return {}
    safe_database_fields = {
        "name",
        "engine",
        "database",
        "file",
        "size_bytes",
        "integrity_check",
        "pg_restore_list_lines",
        "sha256",
    }
    databases = []
    for item in manifest.get("databases") or []:
        if isinstance(item, dict):
            databases.append({key: item[key] for key in safe_database_fields if key in item})
    folders = []
    for item in manifest.get("folders") or []:
        if isinstance(item, dict):
            folders.append({key: item[key] for key in ("label", "files") if key in item})
    return {
        key: manifest[key]
        for key in ("formatVersion", "createdAt", "created_at", "createdAtText")
        if key in manifest
    } | {"databases": databases, "folders": folders}


def validate_backup_manifest(manifest: dict, archive_names: list[str]) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest.json ausente ou invalido."], "warnings": [], "database_files": []}

    try:
        version = int(manifest.get("formatVersion") or 1)
    except (TypeError, ValueError):
        version = 0
        errors.append("Versao do manifesto invalida.")

    database_items = manifest.get("databases")
    if not isinstance(database_items, list):
        return {"ok": False, "errors": errors + ["Lista de bancos ausente no manifesto."], "warnings": warnings, "database_files": []}

    normalized_archive_names = [str(name).replace("\\", "/") for name in archive_names]
    archive_database_files = {
        name for name in normalized_archive_names if name.startswith("bancos/") and (name.endswith(".db") or name.endswith(".dump"))
    }
    manifest_names: list[str] = []
    manifest_files: list[str] = []
    seen_names: set[str] = set()
    seen_files: set[str] = set()

    for item in database_items:
        if not isinstance(item, dict):
            errors.append("Entrada de banco invalida no manifesto.")
            continue
        name = str(item.get("name") or "").strip()
        engine = str(item.get("engine") or "").strip().lower()
        file_name = str(item.get("file") or "").replace("\\", "/")
        if not name or name in seen_names:
            errors.append("Nome de banco ausente ou duplicado no manifesto.")
            continue
        seen_names.add(name)
        manifest_names.append(name)
        expected_suffix = ".dump" if engine == "postgresql" else ".db" if engine == "sqlite" else ""
        expected_file = f"bancos/{name}{expected_suffix}" if expected_suffix else ""
        if not expected_suffix or file_name != expected_file:
            errors.append(f"Arquivo ou engine inconsistente para o banco {name}.")
        if file_name in seen_files:
            errors.append(f"Arquivo duplicado no manifesto para o banco {name}.")
        seen_files.add(file_name)
        manifest_files.append(file_name)
        checksum = str(item.get("sha256") or "").strip().lower()
        if version >= BACKUP_FORMAT_VERSION and not re.fullmatch(r"[0-9a-f]{64}", checksum):
            errors.append(f"Checksum SHA-256 ausente ou invalido para o banco {name}.")

    actual_labels = set(manifest_names)
    if actual_labels != REQUIRED_BACKUP_DATABASE_LABELS:
        missing = sorted(REQUIRED_BACKUP_DATABASE_LABELS - actual_labels)
        unexpected = sorted(actual_labels - REQUIRED_BACKUP_DATABASE_LABELS)
        if missing:
            errors.append("Bancos obrigatorios ausentes: " + ", ".join(missing))
        if unexpected:
            errors.append("Bancos inesperados: " + ", ".join(unexpected))
    if set(manifest_files) != archive_database_files:
        errors.append("O conjunto de dumps do ZIP difere do manifesto.")
    if version < BACKUP_FORMAT_VERSION:
        warnings.append("Backup legado sem checksum SHA-256 obrigatorio por banco.")

    return {
        "ok": not errors,
        "version": version,
        "errors": errors,
        "warnings": warnings,
        "database_files": sorted(set(manifest_files)),
    }


def verify_portal_backup(name: str) -> dict:
    backup_path = backup_file_by_name(name)
    tmp_dir = BACKUP_TEMP_DIR / f"verify_{iso_stamp()}"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_path, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                return {"ok": False, "message": "Backup contem entradas duplicadas.", "file": backup_path.name}
            if any(not archive_member_is_safe(item) for item in names):
                return {"ok": False, "message": "Backup contem caminho de arquivo inseguro.", "file": backup_path.name}
            if "manifest.json" not in names:
                return {"ok": False, "message": "Backup sem manifest.json.", "file": backup_path.name}
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > BACKUP_MANIFEST_MAX_BYTES:
                return {"ok": False, "message": "Manifesto do backup excede o limite seguro.", "file": backup_path.name}
            with archive.open(manifest_info, "r") as manifest_stream:
                manifest_bytes = manifest_stream.read(BACKUP_MANIFEST_MAX_BYTES + 1)
            if len(manifest_bytes) > BACKUP_MANIFEST_MAX_BYTES:
                return {"ok": False, "message": "Manifesto do backup excede o limite seguro.", "file": backup_path.name}
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            validation = validate_backup_manifest(manifest, names)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "message": "Manifesto ou conjunto de bancos invalido.",
                    "file": backup_path.name,
                    "manifest": sanitize_backup_manifest(manifest),
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                    "entries": len(names),
                }
            checksum = verify_checksum_sidecar(
                backup_path,
                require=validation.get("version", 1) >= BACKUP_FORMAT_VERSION,
            )
            if not checksum.get("ok"):
                return {
                    "ok": False,
                    "message": checksum.get("message") or "Checksum do ZIP invalido.",
                    "file": backup_path.name,
                    "manifest": sanitize_backup_manifest(manifest),
                    "checksum": checksum,
                    "entries": len(names),
                }
            if not checksum.get("present"):
                validation["warnings"].append(checksum.get("message") or "Backup legado sem checksum sidecar.")
            bad_file = archive.testzip()
            if bad_file:
                return {"ok": False, "message": f"Arquivo corrompido dentro do backup: {bad_file}"}
            expected_metadata = {
                str(item.get("file") or "").replace("\\", "/"): item
                for item in manifest.get("databases") or []
                if isinstance(item, dict)
            }
            checks = []
            for entry in validation["database_files"]:
                target = tmp_dir / Path(entry).name
                with archive.open(entry, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                metadata = expected_metadata.get(entry) or {}
                expected_size = metadata.get("size_bytes")
                size_ok = expected_size is None or int(expected_size) == target.stat().st_size
                expected_checksum = str(metadata.get("sha256") or "").strip().lower()
                actual_checksum = sha256_file(target)
                checksum_ok = not expected_checksum or hmac.compare_digest(expected_checksum, actual_checksum)
                if entry.endswith(".dump"):
                    result = verify_postgres_dump_file(target)
                    checks.append(
                        {
                            "file": entry,
                            "engine": "postgresql",
                            **result,
                            "size_ok": size_ok,
                            "checksum_ok": checksum_ok,
                            "ok": bool(result.get("ok") and size_ok and checksum_ok),
                        }
                    )
                else:
                    result = verify_sqlite_file(target)
                    checks.append(
                        {
                            "file": entry,
                            "engine": "sqlite",
                            "integrity": result,
                            "size_ok": size_ok,
                            "checksum_ok": checksum_ok,
                            "ok": result.lower() == "ok" and size_ok and checksum_ok,
                        }
                    )
            ok = len(checks) == len(REQUIRED_BACKUP_DATABASE_LABELS) and all(item["ok"] for item in checks)
            return {
                "ok": ok,
                "message": "Backup verificado com sucesso." if ok else "Backup verificado com alertas.",
                "file": backup_path.name,
                "manifest": sanitize_backup_manifest(manifest),
                "checksum": checksum,
                "databases": checks,
                "warnings": validation["warnings"],
                "entries": len(names),
            }
    except Exception:
        return {"ok": False, "message": "Falha ao verificar o backup. Consulte o log do portal.", "file": backup_path.name}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def prepare_portal_restore(name: str) -> dict:
    verification = verify_portal_backup(name)
    if not verification.get("ok"):
        return verification
    backup_path = backup_file_by_name(name)
    target_dir = RESTORE_PREP_DIR / f"restauracao_{iso_stamp()}_{backup_path.stem}"
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_path, "r") as archive:
        for member in archive.infolist():
            if not archive_member_is_safe(member.filename):
                raise ValueError("Backup contem caminho de arquivo inseguro.")
            destination = (target_dir / member.filename).resolve()
            if not path_is_within(destination, target_dir):
                raise ValueError("Backup contem caminho fora da pasta de restauracao.")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)

    database_lines = []
    for source in backup_database_sources():
        if source["engine"] == "postgresql":
            target = source["target"]
            database_lines.append(
                f"- bancos\\{source['label']}.dump -> PostgreSQL {target['label']} "
                "(restaurar com pg_restore apos parar os sistemas)"
            )
        else:
            database_lines.append(f"- bancos\\{source['label']}.db -> {source['path']}")
    folder_lines = []
    for label, source in BACKUP_FOLDERS:
        folder_lines.append(f"- arquivos\\{label}\\ -> {source}")

    instructions = "\n".join(
        [
            "RESTAURACAO SEGURA - PORTAL AGRICOLA",
            "",
            "Esta pasta foi preparada pelo launcher. Nenhum banco ativo foi sobrescrito automaticamente.",
            "Para aplicar a restauracao:",
            "1. Feche o launcher e todos os sistemas web.",
            "2. Copie os arquivos de banco abaixo para os destinos indicados.",
            "3. Substitua as pastas de arquivos somente se precisar restaurar documentos/anexos.",
            "4. Abra o launcher e confira os sistemas.",
            "",
            "Bancos:",
            *database_lines,
            "",
            "Pastas de arquivos:",
            *folder_lines,
            "",
            f"Backup de origem: {backup_path}",
            f"Pasta preparada: {target_dir}",
            f"Gerado em: {time.strftime('%d/%m/%Y %H:%M:%S')}",
        ]
    )
    (target_dir / "LEIA-ME_RESTAURACAO.txt").write_text(instructions, encoding="utf-8")
    return {
        "ok": True,
        "message": "Restauracao preparada com seguranca.",
        "file": backup_path.name,
        "restorePath": str(target_dir),
        "verification": verification,
    }


def cleanup_backup_temp() -> None:
    shutil.rmtree(BACKUP_TEMP_DIR, ignore_errors=True)
    for path in BACKUP_DIR.glob(".tmp_*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass
    for path in BACKUP_DIR.glob("*.zip.tmp"):
        try:
            path.unlink()
        except OSError:
            pass


def create_portal_backup(force: bool = False, request_id: str | None = None, created_by: str = "system") -> dict:
    with BACKUP_LOCK:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_STATUS.update({"running": True, "lastRunAt": now_ts(), "lastError": ""})
        cleanup_backup_temp()
        tmp_dir = BACKUP_TEMP_DIR / f"tmp_{iso_stamp()}"
        created_path = None
        local_backup_committed = False
        try:
            signature = source_signature()
            state = read_backup_state()
            if not force and state.get("signature") == signature:
                last_name = Path(str(state.get("lastFile") or "")).name
                last_path = BACKUP_DIR / last_name if last_name else None
                if last_path and last_path.exists():
                    checksum = verify_checksum_sidecar(last_path, require=True)
                    if not checksum.get("present"):
                        checksum = write_checksum_sidecar(last_path)
                    if not checksum.get("ok"):
                        message = "Backup local existente falhou na validacao SHA-256; nenhuma copia foi sobrescrita."
                        BACKUP_STATUS.update({"running": False, "lastMessage": message, "lastError": message})
                        return {"ok": False, "created": False, "message": message, "file": last_name, "checksum": checksum}
                    offsite = replicate_backup_offsite(last_path, BACKUP_OFFSITE_DIR)
                    retention = cleanup_old_backups()
                    offsite_failed = bool(offsite.get("configured") and not offsite.get("ok"))
                    message = "Sem alteracoes desde o ultimo backup; checksum local confirmado."
                    if offsite_failed:
                        message += " Copia offsite pendente ou com falha."
                    elif offsite.get("configured"):
                        message += " Copia offsite validada."
                    BACKUP_STATUS.update(
                        {
                            "running": False,
                            "lastMessage": message,
                            "lastError": offsite.get("message", "") if offsite_failed else "",
                            "lastFile": last_name,
                            "offsite": offsite,
                            "retention": retention,
                        }
                    )
                    return {
                        "ok": not offsite_failed,
                        "created": False,
                        "localBackupOk": True,
                        "message": message,
                        "file": last_name,
                        "checksum": checksum,
                        "offsite": offsite,
                        "retention": retention,
                    }

            tmp_dir.mkdir(parents=True, exist_ok=True)
            db_dir = tmp_dir / "bancos"
            included_databases = []
            for source in backup_database_sources():
                label = source["label"]
                if source["engine"] == "postgresql":
                    included_databases.append(backup_postgres_database(source, db_dir))
                    continue

                # Subsystem SQLite databases (notas, colaboradores, analises, balanca)
                source_path = Path(source["path"])
                if not source_path.exists():
                    continue
                db_dir.mkdir(parents=True, exist_ok=True)
                target = db_dir / f"{label}.db"
                backup_sqlite_database(source_path, target)
                stat = target.stat()
                manifest_item = {
                    "name": label,
                    "size_bytes": stat.st_size,
                    "sha256": sha256_file(target),
                    "integrity_check": sqlite_integrity_check(target),
                    "engine": "sqlite",
                    "file": (Path("bancos") / f"{label}.db").as_posix(),
                }
                included_databases.append(manifest_item)

            included_labels = {str(item.get("name") or "") for item in included_databases}
            if included_labels != REQUIRED_BACKUP_DATABASE_LABELS:
                missing = sorted(REQUIRED_BACKUP_DATABASE_LABELS - included_labels)
                raise RuntimeError("Backup cancelado: bancos obrigatorios ausentes: " + ", ".join(missing))

            timestamp = iso_stamp()
            zip_path = BACKUP_DIR / f"portal_agricola_{timestamp}.zip"
            tmp_zip = tmp_dir / f"portal_agricola_{timestamp}.zip.tmp"
            included_files = []
            with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for db_file in db_dir.glob("*"):
                    if db_file.is_file():
                        archive.write(db_file, (Path("bancos") / db_file.name).as_posix())
                for label, folder in BACKUP_FOLDERS:
                    count = zip_folder(archive, label, folder)
                    if count:
                        included_files.append({"label": label, "files": count})
                manifest = {
                    "formatVersion": BACKUP_FORMAT_VERSION,
                    "createdAt": now_ts(),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "createdAtText": time.strftime("%d/%m/%Y %H:%M:%S"),
                    "created_by": created_by,
                    "request_id": request_id or "",
                    "databases": included_databases,
                    "folders": included_files,
                }
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

            tmp_zip.replace(zip_path)
            created_path = zip_path
            local_backup_committed = True
            checksum = write_checksum_sidecar(zip_path)
            offsite = replicate_backup_offsite(zip_path, BACKUP_OFFSITE_DIR)
            retention = cleanup_old_backups()
            write_backup_state(
                {
                    "signature": signature,
                    "lastFile": zip_path.name,
                    "lastCreatedAt": now_ts(),
                    "checksum": checksum.get("value"),
                    "offsite": {key: offsite.get(key) for key in ("configured", "ok", "validated", "file")},
                }
            )
            offsite_failed = bool(offsite.get("configured") and not offsite.get("ok"))
            message = f"Backup local criado e validado: {zip_path.name}"
            if offsite_failed:
                message += " Copia offsite falhou; o ZIP local foi preservado."
            elif offsite.get("configured"):
                message += " Copia offsite validada."
            BACKUP_STATUS.update(
                {
                    "running": False,
                    "lastCreatedAt": now_ts(),
                    "lastFile": zip_path.name,
                    "lastMessage": message,
                    "lastError": offsite.get("message", "") if offsite_failed else "",
                    "offsite": offsite,
                    "retention": retention,
                }
            )
            return {
                "ok": not offsite_failed,
                "created": True,
                "localBackupOk": True,
                "message": message,
                "file": zip_path.name,
                "checksum": checksum,
                "offsite": offsite,
                "retention": retention,
            }
        except Exception as exc:
            if created_path and created_path.exists() and not local_backup_committed:
                try:
                    created_path.unlink()
                except OSError:
                    pass
            failure = "Falha apos preservar o backup local." if local_backup_committed else "Falha ao criar backup local."
            BACKUP_STATUS.update({"running": False, "lastError": type(exc).__name__, "lastMessage": failure})
            return {
                "ok": False,
                "created": local_backup_committed,
                "localBackupOk": local_backup_committed,
                "message": failure,
                "errorType": type(exc).__name__,
                "file": created_path.name if created_path else "",
            }
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)


def backup_worker() -> None:
    time.sleep(8)
    while True:
        result = create_portal_backup(force=False)
        if result.get("created") and result.get("ok"):
            PORTAL_LOGGER.info("Backup automatico criado.", extra={"system": "portal", "status": "ok"})
        elif result.get("created"):
            PORTAL_LOGGER.error("Backup local criado com falha de redundancia.", extra={"system": "portal", "status": "degraded"})
        elif not result.get("ok"):
            PORTAL_LOGGER.error("Falha no backup automatico.", extra={"system": "portal", "status": "error"})
        time.sleep(max(BACKUP_INTERVAL_SECONDS, 300))


def backup_public_status() -> dict:
    return {
        **BACKUP_STATUS,
        "dir": str(BACKUP_DIR),
        "intervalSeconds": BACKUP_INTERVAL_SECONDS,
        "retentionPolicy": {
            "daily": BACKUP_RETENTION_DAILY,
            "weekly": BACKUP_RETENTION_WEEKLY,
            "monthly": BACKUP_RETENTION_MONTHLY,
            "applyEnabled": BACKUP_RETENTION_APPLY,
        },
        "offsiteConfigured": bool(BACKUP_OFFSITE_DIR),
        "files": backup_file_list(),
    }


def auth_conn():
    """Return a PostgreSQL connection to the portal database.
    PORTAL_DATABASE_URL must be set; SQLite is no longer supported.
    """
    if not PORTAL_DATABASE_URL:
        raise RuntimeError(
            "PORTAL_DATABASE_URL nao configurada. "
            "Defina-a em launcher_web.env antes de iniciar o servidor."
        )
    return connect_postgres_db(PORTAL_DATABASE_URL)


def redact_database_url(value: str) -> str:
    if not value or "@" not in value:
        return value
    prefix, suffix = value.split("@", 1)
    if "://" not in prefix or ":" not in prefix.split("://", 1)[1]:
        return value
    scheme, auth = prefix.split("://", 1)
    user = auth.split(":", 1)[0]
    return f"{scheme}://{user}:***@{suffix}"


def password_hash_iterations(password_hash: str | None) -> int:
    try:
        iterations_text = (password_hash or "").split("$", 1)[0]
        return max(int(iterations_text), 0)
    except (TypeError, ValueError):
        return 0


def hash_password(password: str, salt: str | None = None, iterations: int | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    cost = max(int(iterations or PASSWORD_ITERATIONS), PASSWORD_ITERATIONS)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), cost)
    return f"{cost}${salt}${digest.hex()}"


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        iterations_text, salt, expected = password_hash.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations_text))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_display_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    accents = str.maketrans("áàãâäéèêëíìîïóòõôöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    normalized = normalized.translate(accents)
    normalized = ".".join(part for part in normalized.split() if part)
    return "".join(ch for ch in normalized if ch.isalnum() or ch == ".")


def normalize_login_email(value: str) -> str:
    login = normalize_email(value)
    if "@" in login:
        return login
    username = normalize_username(login)
    return f"{username}@example.invalid" if username else login


def login_candidates(value: str) -> list[str]:
    raw_login = normalize_email(value)
    candidates: list[str] = []

    def add(candidate: str) -> None:
        candidate = normalize_email(candidate)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(raw_login)
    add(normalize_login_email(raw_login))
    username_source = raw_login.split("@", 1)[0] if "@" in raw_login else raw_login
    username = normalize_username(username_source)

    if username:
        add(username)
        add(f"{username}@example.invalid")
        add(f"{username}@example.invalid")

    return candidates


def find_user_for_login(conn: Any, value: str) -> tuple[Any | None, str]:
    candidates = login_candidates(value)

    for candidate in candidates:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (candidate,)).fetchone()
        if row:
            return row, candidate

        row = conn.execute(
            """
            SELECT u.*
            FROM user_login_aliases a
            JOIN users u ON u.id = a.user_id
            WHERE a.alias = ?
            """,
            (candidate,),
        ).fetchone()
        if row:
            return row, candidate

    return None, candidates[0] if candidates else normalize_login_email(value)


def ensure_default_login_aliases(conn: Any) -> None:
    rows = conn.execute("SELECT id, name, email FROM users").fetchall()
    now = now_ts()

    for row in rows:
        aliases = set(login_candidates(row["email"]))
        name_alias = normalize_username(row["name"])

        if name_alias:
            aliases.update({name_alias, f"{name_alias}@example.invalid", f"{name_alias}@example.invalid"})

        for alias in sorted(aliases):
            if alias == row["email"]:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO user_login_aliases (user_id, alias, created_at)
                VALUES (?, ?, ?)
                """,
                (row["id"], alias, now),
            )


def user_public(row: Any | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "provider": row["provider"],
        "role": row["role"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "approvedAt": row["approved_at"],
        "canManagePortal": is_full_access_admin(row),
    }


def table_exists(conn: Any, table_name: str) -> bool:
    """Check if a table exists in the portal database.
    Uses the CompatConnection native API which queries information_schema.
    """
    return conn.table_exists(table_name)


def table_columns(conn: Any, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return set()
    return {row["name"] for row in rows}


def index_exists(conn: Any, table_name: str, index_name: str) -> bool:
    try:
        if hasattr(conn, "raw"):
            return conn.execute(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = ? AND indexname = ?
                """,
                (table_name, index_name),
            ).fetchone() is not None
        rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
        for row in rows:
            try:
                current_name = row["name"]
            except (KeyError, IndexError, TypeError):
                current_name = row[1] if len(row) > 1 else ""
            if current_name == index_name:
                return True
    except Exception:
        return False
    return False


def auth_schema_needs_migration(conn: Any) -> bool:
    return not table_exists(conn, "system_permissions") or bool(
        {"route", "method", "request_id", "result"} - table_columns(conn, "audit_events")
    )


def record_portal_schema_version(conn: Any) -> None:
    applied_at = datetime.now(timezone.utc)
    if not hasattr(conn, "raw"):
        applied_at = applied_at.isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, applied_at)
        VALUES (?, ?)
        """,
        (PORTAL_SCHEMA_VERSION, applied_at),
    )


def migrate_auth_schema(conn: Any) -> None:
    """Apply incremental schema migrations to the PostgreSQL portal database.
    Migrations are idempotent (IF NOT EXISTS / DO NOTHING), so re-running is safe.
    No file-level backup is performed here; rely on the scheduled pg_dump backup instead.
    """
    record_portal_schema_version(conn)
    if not auth_schema_needs_migration(conn):
        return

    PORTAL_LOGGER.info("Aplicando migracoes de schema ao banco portal.", extra={"system": "portal", "status": "ok"})

    audit_columns = table_columns(conn, "audit_events")
    for name in ("route", "method", "request_id", "result"):
        if name not in audit_columns:
            conn.execute(f"ALTER TABLE audit_events ADD COLUMN {name} TEXT")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS system_permissions (
            user_id INTEGER NOT NULL,
            system_id TEXT NOT NULL,
            can_access INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, system_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_system_permissions_user ON system_permissions(user_id);
        CREATE INDEX IF NOT EXISTS idx_system_permissions_system ON system_permissions(system_id);
        CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_events(request_id);












        """
    )


def default_user_system_ids() -> list[str]:
    return [app["id"] for app in APPS if not app.get("admin_only")]


def grant_default_system_permissions(conn: Any, user_id: int) -> None:
    now = now_ts()
    for system_id in default_user_system_ids():
        conn.execute(
            """
            INSERT OR IGNORE INTO system_permissions (user_id, system_id, can_access, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (user_id, system_id, now, now),
        )


def ensure_default_system_permissions(conn: Any) -> None:
    rows = conn.execute("SELECT id FROM users WHERE role != 'admin' AND status = 'approved'").fetchall()
    for row in rows:
        grant_default_system_permissions(conn, int(row["id"]))


def is_full_access_admin(user: Any | None) -> bool:
    if not user or row_value(user, "role") != "admin":
        return False
    return normalize_email(str(row_value(user, "email", ""))) in FULL_ACCESS_ADMIN_EMAILS


def is_globally_maintenance_restricted(app: dict | None) -> bool:
    if not app:
        return False
    return app.get("id") not in MAINTENANCE_OPEN_SYSTEM_IDS


def maintenance_message_for_app(app: dict | None) -> str:
    if not app:
        return GLOBAL_MAINTENANCE_MESSAGE
    return app.get("maintenance_message") or GLOBAL_MAINTENANCE_MESSAGE


def user_can_access_system(user: Any | None, app: dict | None) -> bool:
    if not app or not app.get("enabled", True):
        return False
    if is_globally_maintenance_restricted(app):
        return is_full_access_admin(user)
    if not app.get("requires_auth", True):
        return True
    if not user:
        return False
    if row_value(user, "role") == "admin":
        return True
    if app.get("admin_only") and not app.get("allow_granular_permission"):
        return False

    user_id = row_value(user, "id")
    if user_id is None:
        return False
    with auth_conn() as conn:
        if not table_exists(conn, "system_permissions"):
            return True
        row = conn.execute(
            "SELECT can_access FROM system_permissions WHERE user_id = ? AND system_id = ?",
            (user_id, app["id"]),
        ).fetchone()
    return bool(row and int(row["can_access"]) == 1)


def permission_system_catalog() -> list[dict]:
    systems = []
    for app in APPS:
        if not app.get("requires_auth", True):
            continue
        systems.append(
            {
                "id": app["id"],
                "name": app["name"],
                "publicPath": app.get("public_path", ""),
                "adminOnly": bool(app.get("admin_only")),
                "allowGranularPermission": bool(app.get("allow_granular_permission", not app.get("admin_only"))),
                "enabled": bool(app.get("enabled", True)),
            }
        )
    return systems


def user_permissions_public(conn: Any, user: Any) -> list[dict]:
    role = row_value(user, "role")
    user_id = row_value(user, "id")
    explicit_rows = {}
    if user_id is not None and table_exists(conn, "system_permissions"):
        rows = conn.execute(
            "SELECT system_id, can_access FROM system_permissions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        explicit_rows = {row["system_id"]: bool(int(row["can_access"])) for row in rows}

    permissions = []
    for system in permission_system_catalog():
        system_id = system["id"]
        explicit = system_id in explicit_rows
        can_access = bool(explicit_rows.get(system_id, False))
        app = find_app(system_id)
        effective = user_can_access_system(user, app) if app else (True if role == "admin" else can_access)
        locked = bool(system["adminOnly"] and not system["allowGranularPermission"])
        permissions.append(
            {
                **system,
                "canAccess": effective,
                "explicitCanAccess": can_access if explicit else None,
                "hasExplicitPermission": explicit,
                "locked": locked,
            }
        )
    return permissions










































































































def setup_auth_db() -> None:
    with auth_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                provider TEXT NOT NULL DEFAULT 'local',
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                approved_at INTEGER,
                approved_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER,
                user_name TEXT,
                user_email TEXT,
                event_type TEXT NOT NULL,
                module TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                summary TEXT NOT NULL,
                details_json TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_login_aliases (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                alias TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_user_login_aliases_user ON user_login_aliases(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(module, entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type, created_at);
            """
        )
        migrate_auth_schema(conn)
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        legacy_admin = conn.execute("SELECT id FROM users WHERE role = 'admin' AND email = ?", ("admin",)).fetchone()
        target_admin = conn.execute("SELECT id FROM users WHERE email = ?", ("admin@example.invalid",)).fetchone()
        if legacy_admin and not target_admin:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", ("admin@example.invalid", legacy_admin["id"]))
        if not admin:
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, provider, role, status, created_at, approved_at)
                VALUES (?, ?, ?, 'local', 'admin', 'approved', ?, ?)
                """,
                ("Administrador", normalize_email(ADMIN_USER), hash_password(initial_admin_password()), now_ts(), now_ts()),
            )
        ensure_default_login_aliases(conn)
        ensure_default_system_permissions(conn)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_ts(),))


def parse_cookies(header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in (header or "").split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def get_session_user(headers) -> dict | None:
    token = parse_cookies(headers.get("Cookie")).get(SESSION_COOKIE)
    if not token:
        return None
    with auth_conn() as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ? AND u.status = 'approved'
            """,
            (token, now_ts()),
        ).fetchone()
    return user_public(row)


def create_session(user_id: int, max_age: int = SESSION_SECONDS) -> str:
    token = secrets.token_urlsafe(32)
    with auth_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now_ts(), now_ts() + max_age),
        )
    return token


def delete_session(headers) -> None:
    token = parse_cookies(headers.get("Cookie")).get(SESSION_COOKIE)
    if not token:
        return
    with auth_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


SENSITIVE_DETAIL_KEYS = {"password", "senha", "token", "secret", "cookie", "authorization"}


def row_value(row: Any | None, key: str, default=None):
    if not row:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def clean_text(value, max_length: int = 180) -> str:
    text = str(value or "").strip()
    return text[:max_length]




def login_client_key(value: str | None) -> str:
    return clean_text(value, 180).lower() or "vazio"


def login_attempt_targets(ip_address: str, email: str) -> list[tuple[str, int]]:
    ip_key = login_client_key(ip_address)
    email_key = login_client_key(email)
    return [
        (f"ip:{ip_key}", LOGIN_IP_MAX_ATTEMPTS),
        (f"account:{ip_key}:{email_key}", LOGIN_ACCOUNT_MAX_ATTEMPTS),
    ]


def cleanup_login_attempts(now: float | None = None) -> None:
    now = now or time.time()
    expired = [
        key
        for key, bucket in LOGIN_ATTEMPTS.items()
        if now - float(bucket.get("first", 0)) > LOGIN_WINDOW_SECONDS and float(bucket.get("blocked_until", 0)) <= now
    ]
    for key in expired:
        LOGIN_ATTEMPTS.pop(key, None)


def login_retry_after(ip_address: str, email: str) -> int:
    now = time.time()
    with LOGIN_LOCK:
        cleanup_login_attempts(now)
        retry_after = 0
        for key, _max_attempts in login_attempt_targets(ip_address, email):
            bucket = LOGIN_ATTEMPTS.get(key)
            blocked_until = float(bucket.get("blocked_until", 0)) if bucket else 0
            if blocked_until > now:
                retry_after = max(retry_after, int(blocked_until - now) + 1)
        return retry_after


def record_login_failure(ip_address: str, email: str) -> None:
    now = time.time()
    with LOGIN_LOCK:
        cleanup_login_attempts(now)
        for key, max_attempts in login_attempt_targets(ip_address, email):
            bucket = LOGIN_ATTEMPTS.get(key)
            if not bucket or now - float(bucket.get("first", 0)) > LOGIN_WINDOW_SECONDS:
                bucket = {"count": 0, "first": now, "blocked_until": 0}
            bucket["count"] = int(bucket.get("count", 0)) + 1
            if int(bucket["count"]) >= max_attempts:
                bucket["blocked_until"] = now + LOGIN_WINDOW_SECONDS
            LOGIN_ATTEMPTS[key] = bucket


def clear_login_failures(ip_address: str, email: str) -> None:
    with LOGIN_LOCK:
        for key, _max_attempts in login_attempt_targets(ip_address, email):
            LOGIN_ATTEMPTS.pop(key, None)


def sanitize_audit_details(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_text = clean_text(key, 80)
            if any(secret in key_text.lower() for secret in SENSITIVE_DETAIL_KEYS):
                clean[key_text] = "[removido]"
            else:
                clean[key_text] = sanitize_audit_details(item)
        return clean
    if isinstance(value, list):
        return [sanitize_audit_details(item) for item in value[:40]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def record_audit_event(
    user,
    event_type: str,
    module: str,
    summary: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    route: str | None = None,
    method: str | None = None,
    request_id: str | None = None,
    result: str | None = None,
    connection: Any | None = None,
) -> None:
    details_json = None
    if details:
        details_json = json.dumps(sanitize_audit_details(details), ensure_ascii=False, sort_keys=True)[:8000]
    with (auth_conn() if connection is None else nullcontext(connection)) as conn:
        columns = table_columns(conn, "audit_events")
        base_columns = [
            "user_id",
            "user_name",
            "user_email",
            "event_type",
            "module",
            "entity_type",
            "entity_id",
            "summary",
            "details_json",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        values = [
            row_value(user, "id"),
            clean_text(row_value(user, "name", "Sistema"), 120),
            clean_text(row_value(user, "email", ""), 180),
            clean_text(event_type, 80),
            clean_text(module, 80),
            clean_text(entity_type, 80) if entity_type else None,
            clean_text(entity_id, 120) if entity_id is not None else None,
            clean_text(summary, 260),
            details_json,
            clean_text(ip_address, 80),
            clean_text(user_agent, 300),
            now_ts(),
        ]
        optional = {
            "route": clean_text(route, 260),
            "method": clean_text(method, 20),
            "request_id": clean_text(request_id, 80),
            "result": clean_text(result, 40),
        }
        for name, value in optional.items():
            if name in columns:
                base_columns.append(name)
                values.append(value)
        placeholders = ", ".join("?" for _ in base_columns)
        conn.execute(
            f"INSERT INTO audit_events ({', '.join(base_columns)}) VALUES ({placeholders})",
            values,
        )


def parse_date_filter(value: str | None, end_of_day: bool = False) -> int | None:
    if not value:
        return None
    try:
        parsed = time.strptime(value[:10], "%Y-%m-%d")
        ts = int(time.mktime(parsed))
        return ts + (86399 if end_of_day else 0)
    except ValueError:
        return None


def audit_filter_options() -> dict:
    with auth_conn() as conn:
        users = conn.execute(
            """
            SELECT COALESCE(user_id, 0) AS user_id, COALESCE(user_name, 'Sistema') AS user_name,
                   COALESCE(user_email, '') AS user_email, COUNT(*) AS total
            FROM audit_events
            GROUP BY COALESCE(user_id, 0), COALESCE(user_name, 'Sistema'), COALESCE(user_email, '')
            ORDER BY user_name COLLATE NOCASE
            """
        ).fetchall()
        modules = conn.execute("SELECT module, COUNT(*) AS total FROM audit_events GROUP BY module ORDER BY module").fetchall()
        event_types = conn.execute("SELECT event_type, COUNT(*) AS total FROM audit_events GROUP BY event_type ORDER BY event_type").fetchall()
    return {
        "users": [
            {
                "id": row["user_id"],
                "name": row["user_name"],
                "email": row["user_email"],
                "total": row["total"],
                "value": str(row["user_id"]) if row["user_id"] else f"email:{row['user_email']}" if row["user_email"] else "system",
            }
            for row in users
        ],
        "modules": [{"module": row["module"], "total": row["total"]} for row in modules],
        "eventTypes": [{"eventType": row["event_type"], "total": row["total"]} for row in event_types],
    }


def audit_query(filters: dict | None = None, limit: int = AUDIT_EVENT_LIMIT) -> dict:
    filters = filters or {}
    limit = max(20, min(int(limit or AUDIT_EVENT_LIMIT), 2000))
    where = []
    params: list = []

    user_filter = clean_text(filters.get("user"), 120)
    if user_filter:
        if user_filter == "system":
            where.append("user_id IS NULL")
        elif user_filter.startswith("email:"):
            where.append("user_email = ?")
            params.append(user_filter.removeprefix("email:"))
        elif user_filter.isdigit():
            where.append("user_id = ?")
            params.append(int(user_filter))

    module_filter = clean_text(filters.get("module"), 80)
    if module_filter:
        where.append("module = ?")
        params.append(module_filter)

    event_filter = clean_text(filters.get("eventType") or filters.get("event_type"), 80)
    if event_filter:
        where.append("event_type = ?")
        params.append(event_filter)

    start_ts = parse_date_filter(filters.get("start"))
    if start_ts:
        where.append("created_at >= ?")
        params.append(start_ts)

    end_ts = parse_date_filter(filters.get("end"), end_of_day=True)
    if end_ts:
        where.append("created_at <= ?")
        params.append(end_ts)

    search = clean_text(filters.get("q"), 120)
    if search:
        like = f"%{search}%"
        where.append(
            """
            (summary LIKE ? OR entity_id LIKE ? OR entity_type LIKE ? OR user_name LIKE ?
             OR user_email LIKE ? OR module LIKE ? OR event_type LIKE ? OR details_json LIKE ?)
            """
        )
        params.extend([like, like, like, like, like, like, like, like])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with auth_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, user_id, user_name, user_email, event_type, module, entity_type,
                   entity_id, summary, details_json, ip_address, created_at
            FROM audit_events
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM audit_events {where_sql}", params).fetchone()

    events = []
    groups: dict[str, dict] = {}
    for row in rows:
        details = {}
        if row["details_json"]:
            try:
                details = json.loads(row["details_json"])
            except json.JSONDecodeError:
                details = {}
        event = {
            "id": row["id"],
            "userId": row["user_id"],
            "userName": row["user_name"] or "Sistema",
            "userEmail": row["user_email"] or "",
            "eventType": row["event_type"],
            "module": row["module"],
            "entityType": row["entity_type"],
            "entityId": row["entity_id"],
            "summary": row["summary"],
            "details": details,
            "ipAddress": row["ip_address"],
            "createdAt": row["created_at"],
        }
        events.append(event)
        key = str(row["user_id"] or row["user_email"] or "system")
        if key not in groups:
            groups[key] = {
                "userId": row["user_id"],
                "userName": row["user_name"] or "Sistema",
                "userEmail": row["user_email"] or "",
                "total": 0,
                "lastAt": row["created_at"],
                "events": [],
            }
        group = groups[key]
        group["total"] += 1
        if len(group["events"]) < 10:
            group["events"].append(event)

    module_count = len({event["module"] for event in events})
    user_count = len(groups)
    return {
        "events": events,
        "groups": list(groups.values()),
        "total": int(total_row["total"] if total_row else len(events)),
        "returned": len(events),
        "summary": {"users": user_count, "modules": module_count, "events": len(events)},
        "filters": audit_filter_options(),
    }


def audit_groups(limit: int = AUDIT_EVENT_LIMIT) -> list[dict]:
    return audit_query(limit=limit)["groups"]


def xlsx_col(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def make_xlsx(headers: list[str], rows: list[list]) -> bytes:
    def cell_xml(row_num: int, col_num: int, value) -> str:
        ref = f"{xlsx_col(col_num)}{row_num}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}"><v>{value}</v></c>'
        text = xml_escape(str(value or ""))
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    sheet_rows = []
    all_rows = [headers, *rows]
    for row_num, row in enumerate(all_rows, start=1):
        cells = "".join(cell_xml(row_num, col_num, value) for col_num, value in enumerate(row, start=1))
        sheet_rows.append(f'<row r="{row_num}">{cells}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Auditoria" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def audit_export_xlsx(filters: dict | None = None) -> bytes:
    data = audit_query(filters=filters, limit=2000)
    headers = ["Data", "Usuario", "E-mail", "Sistema", "Acao", "Tipo", "ID", "Resumo", "Detalhes"]
    rows = []
    for event in data["events"]:
        rows.append(
            [
                time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(event["createdAt"])),
                event["userName"],
                event["userEmail"],
                event["module"],
                event["eventType"],
                event["entityType"] or "",
                event["entityId"] or "",
                event["summary"],
                json.dumps(event.get("details") or {}, ensure_ascii=False),
            ]
        )
    return make_xlsx(headers, rows)


def audit_groups_old(limit: int = AUDIT_EVENT_LIMIT) -> list[dict]:
    with auth_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, user_name, user_email, event_type, module, entity_type,
                   entity_id, summary, created_at
            FROM audit_events
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    groups: dict[str, dict] = {}
    for row in rows:
        key = str(row["user_id"] or row["user_email"] or "system")
        if key not in groups:
            groups[key] = {
                "userId": row["user_id"],
                "userName": row["user_name"] or "Sistema",
                "userEmail": row["user_email"] or "",
                "total": 0,
                "lastAt": row["created_at"],
                "events": [],
            }
        group = groups[key]
        group["total"] += 1
        if len(group["events"]) < 8:
            group["events"].append(
                {
                    "id": row["id"],
                    "eventType": row["event_type"],
                    "module": row["module"],
                    "entityType": row["entity_type"],
                    "entityId": row["entity_id"],
                    "summary": row["summary"],
                    "createdAt": row["created_at"],
                }
            )
    return list(groups.values())


def get_lan_ip() -> str:
    return "127.0.0.1"


def get_client_server_host(headers) -> str:
    raw_host = headers.get("Host", "")
    if raw_host.startswith("["):
        host = raw_host[1:].split("]", 1)[0].strip()
    else:
        host = raw_host.split(":", 1)[0].strip()
    if not host:
        return get_lan_ip()
    return host


def test_tcp_port(host: str, port: int, timeout: float = STATUS_TCP_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def app_public_url(app: dict, server_host: str) -> str:
    public_path = app.get("public_path") or "/"
    return f"http://{server_host}:{PORT}{public_path}"


def app_api_public_url(app: dict, server_host: str) -> str | None:
    api_public_path = app.get("api_public_path")
    if not api_public_path:
        return None
    return f"http://{server_host}:{PORT}{api_public_path}"


def path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def proxy_route_for_path(path: str) -> dict | None:
    for app in APPS:
        api_public_path = app.get("api_public_path")
        if api_public_path and path_matches_prefix(path, api_public_path):
            return {"app": app, "prefix": api_public_path, "port": app.get("api_port"), "api": True}

    for app in APPS:
        if app.get("kind") == "internal":
            continue
        public_path = app.get("public_path")
        if public_path and path_matches_prefix(path, public_path):
            return {"app": app, "prefix": public_path, "port": app.get("web_port"), "api": False}
    return None


def strip_proxy_prefix(path: str, prefix: str) -> str:
    stripped = path[len(prefix) :]
    return stripped if stripped.startswith("/") else f"/{stripped}" if stripped else "/"


def is_text_response(content_type: str) -> bool:
    normalized = content_type.lower()
    return (
        "text/" in normalized
        or "javascript" in normalized
        or "json" in normalized
        or "xml" in normalized
        or "svg" in normalized
    )


def rewrite_proxy_body(body: bytes, content_type: str, prefix: str) -> bytes:
    if not body or not is_text_response(content_type):
        return body

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    attribute_replacements = [
        ('href="/', f'href="{prefix}/'),
        ('src="/', f'src="{prefix}/'),
        ('action="/', f'action="{prefix}/'),
        ('url("/', f'url("{prefix}/'),
        ("url('/", f"url('{prefix}/"),
        ("url(/", f"url({prefix}/"),
    ]
    script_replacements = [
        ('"/api', f'"{prefix}/api'),
        ("'/api", f"'{prefix}/api"),
        ("`/api", f"`{prefix}/api"),
        ('"/assets', f'"{prefix}/assets'),
        ("'/assets", f"'{prefix}/assets"),
        ("`/assets", f"`{prefix}/assets"),
        ('"/static', f'"{prefix}/static'),
        ("'/static", f"'{prefix}/static"),
        ("`/static", f"`{prefix}/static"),
    ]

    for source, target in attribute_replacements + script_replacements:
        text = text.replace(source, target)
    return text.encode("utf-8")


def read_health(app: dict) -> dict:
    system = {
        "id": app.get("id"),
        "name": app.get("name"),
        "enabled": app.get("enabled", True),
        "internal_host": "127.0.0.1",
        "internal_port": app.get("health_port") or app.get("web_port"),
        "health_url": app.get("health_url"),
    }
    status = check_system(system, http_timeout=STATUS_HTTP_TIMEOUT, tcp_timeout=STATUS_TCP_TIMEOUT)
    details = status.get("details") or {}
    message = details.get("message") or details.get("service") or details.get("app") or status["status"]
    return {
        "ok": status["status"] == "online",
        "checked": True,
        "url": app.get("health_url") or app.get("health_path") or "",
        "statusCode": status.get("http_status"),
        "message": message,
        "status": status["status"],
        "latencyMs": status["latency_ms"],
        "lastChecked": status["last_checked"],
        "details": details,
    }


def read_log_tail(path: Path, limit: int = 10) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines[-limit:] if line.strip()]


def database_health(label: str, path: Path) -> dict:
    min_free_bytes = 500 * 1024 * 1024
    item = {
        "label": label,
        "engine": "sqlite",
        "path": str(path),
        "exists": path.exists(),
        "ok": False,
        "integrity": "nao encontrado",
        "size": 0,
        "modifiedAt": None,
        "freeBytes": 0,
        "minFreeBytes": min_free_bytes,
    }
    if not path.exists():
        return item
    try:
        stat = path.stat()
        item["size"] = stat.st_size
        item["modifiedAt"] = int(stat.st_mtime)
        usage = shutil.disk_usage(path.parent)
        item["freeBytes"] = usage.free
        integrity = verify_sqlite_file(path)
        item["integrity"] = integrity
        item["ok"] = integrity.lower() == "ok" and usage.free >= min_free_bytes
    except Exception as exc:
        item["integrity"] = str(exc)
    return item


def database_source_health(source: dict) -> dict:
    if source["engine"] != "postgresql":
        return database_health(source["label"], Path(source["path"]))

    min_free_bytes = 500 * 1024 * 1024
    target = source["target"]
    item = {
        "label": source["label"],
        "engine": "postgresql",
        "path": "",
        "target": target["label"],
        "exists": False,
        "ok": False,
        "integrity": "nao verificado",
        "size": 0,
        "modifiedAt": None,
        "freeBytes": 0,
        "minFreeBytes": min_free_bytes,
    }
    try:
        usage = shutil.disk_usage(BACKUP_DIR if BACKUP_DIR.exists() else ROOT_DIR)
        item["freeBytes"] = usage.free
        tables = int(
            postgres_scalar(
                target,
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';",
            )
            or 0
        )
        size = int(postgres_scalar(target, "SELECT pg_database_size(current_database());") or 0)
        item["exists"] = True
        item["tables"] = tables
        item["size"] = size
        item["integrity"] = "ok" if tables > 0 else "sem tabelas"
        item["ok"] = tables > 0 and usage.free >= min_free_bytes
    except Exception as exc:
        item["integrity"] = str(exc)
    return item


def portal_health() -> dict:
    required_tables = {
        "users",
        "sessions",
        "audit_events",
        "user_login_aliases",
        "system_permissions",
    }
    checks = {
        "database": {"ok": False, "tables": []},
        "directories": {"ok": False, "paths": []},
    }

    try:
        with auth_conn() as conn:
            tables = set(conn.list_tables())
            conn.execute("SELECT 1").fetchone()
            try:
                schema_row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            except Exception:
                schema_row = None
        missing = sorted(required_tables - tables)
        checks["database"] = {
            "ok": not missing,
            "engine": "postgresql",
            "path": "",
            "target": redact_database_url(PORTAL_DATABASE_URL),
            "schemaVersion": schema_row["version"] if schema_row else None,
            "tables": sorted(tables & required_tables),
            "missing": missing,
        }
    except Exception as exc:
        checks["database"] = {
            "ok": False,
            "engine": "postgresql",
            "target": redact_database_url(PORTAL_DATABASE_URL),
            "error": str(exc),
        }

    directory_paths = [LOG_ROOT, LOG_DIR, BACKUP_DIR, RESTORE_PREP_DIR]
    dir_results = []
    for directory in directory_paths:
        try:
            probe = directory
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            ready = probe.is_dir() and os.access(probe, os.W_OK)
            dir_results.append({"ok": ready})
        except OSError:
            dir_results.append({"ok": False})
    checks["directories"] = {"ok": all(item["ok"] for item in dir_results), "paths": dir_results}

    ok = bool(checks["database"]["ok"] and checks["directories"]["ok"])
    return {
        "system": "portal",
        "status": "online" if ok else "degraded",
        "version": PORTAL_VERSION,
        "database": "ok" if checks["database"]["ok"] else "error",
        "uptime_seconds": int(time.time() - PORTAL_STARTED_AT),
        "timestamp": timestamp_text(),
    }


def admin_health_status(server_host: str) -> dict:
    app_items = []
    for app in APPS:
        if app.get("kind") == "internal":
            exists = Path(app["path"]).exists()
            health = {"ok": exists, "checked": False, "message": "Modulo interno disponivel." if exists else "Arquivo nao encontrado."}
            app_items.append(
                {
                    "id": app["id"],
                    "name": app["name"],
                    "status": "online" if exists else "offline",
                    "webPort": None,
                    "apiPort": None,
                    "webRunning": exists,
                    "apiRunning": True,
                    "url": app_public_url(app, server_host),
                    "health": health,
                    "log": read_log_tail(app_log_path(app["id"]), 8),
                    "staticBuild": False,
                }
            )
            continue
        web_port = app.get("web_port")
        api_port = app.get("api_port")
        web_running = static_build_available(app) or (test_tcp_port("127.0.0.1", web_port) if web_port else False)
        api_running = test_tcp_port("127.0.0.1", api_port) if api_port else True
        health = read_health(app) if web_running and api_running else {"ok": False, "checked": False, "message": "Porta ainda nao respondeu."}
        status = "online" if web_running and api_running and (not health.get("checked") or health.get("ok")) else "degraded" if web_running or api_running else "offline"
        app_items.append(
            {
                "id": app["id"],
                "name": app["name"],
                "status": status,
                "webPort": web_port,
                "apiPort": api_port,
                "webRunning": web_running,
                "apiRunning": api_running,
                "url": app_public_url(app, server_host) if web_port else "",
                "health": health,
                "log": read_log_tail(app_log_path(app["id"]), 8),
                "staticBuild": static_build_available(app),
            }
        )

    databases = [database_source_health(source) for source in backup_database_sources()]
    backup = backup_public_status()
    last_backup = (backup.get("files") or [None])[0]
    return {
        "checkedAt": now_ts(),
        "apps": app_items,
        "databases": databases,
        "backup": {
            "running": backup.get("running"),
            "lastMessage": backup.get("lastMessage"),
            "lastError": backup.get("lastError"),
            "lastCreatedAt": backup.get("lastCreatedAt"),
            "intervalSeconds": backup.get("intervalSeconds"),
            "keepFiles": backup.get("keepFiles"),
            "dir": backup.get("dir"),
            "latest": last_backup,
        },
        "summary": {
            "appsOnline": sum(1 for item in app_items if item["status"] == "online"),
            "appsTotal": len(app_items),
            "databasesOk": sum(1 for item in databases if item["ok"]),
            "databasesTotal": len(databases),
            "backupOk": bool(last_backup) and not backup.get("lastError"),
        },
    }


def process_is_running(process: subprocess.Popen | None) -> bool:
    return bool(process and process.poll() is None)






def app_public_data(app: dict, server_host: str, user: dict | None = None) -> dict:
    app_id = app["id"]
    kind = app["kind"]
    exists = Path(app["path"]).exists()
    started = process_is_running(STARTED_PROCESSES.get(app_id))
    running = started
    url = None
    api_url = None
    restricted = not user_can_access_system(user, app)
    has_static_build = static_build_available(app)
    backup = backup_public_status()
    last_backup = (backup.get("files") or [None])[0]
    backup_late = not bool(last_backup) or (
        bool(backup.get("intervalSeconds"))
        and bool(last_backup)
        and now_ts() - int(last_backup.get("createdAt", 0)) > int(backup.get("intervalSeconds", 0)) * 2
    )

    restricted_message = maintenance_message_for_app(app)

    if restricted:
        status = "manutencao"
        health = {"ok": False, "checked": False, "message": restricted_message}
    elif kind == "web":
        web_port_running = test_tcp_port("127.0.0.1", app["web_port"])
        running = has_static_build or web_port_running
        api_port = app.get("api_port")
        api_running = test_tcp_port("127.0.0.1", api_port) if api_port else True
        health = read_health(app) if running and api_running else {"ok": False, "checked": False, "message": "Porta ainda nao respondeu."}
        url = app_public_url(app, server_host)
        api_url = app_api_public_url(app, server_host) if api_port else None
        if running and api_running and (not health.get("checked") or health.get("ok")):
            status = "online"
        elif running and api_running:
            status = "degraded"
        elif has_static_build and api_port and not api_running:
            status = "degraded"
        elif exists:
            status = "pronto"
        else:
            status = "offline"
    elif kind == "internal":
        running = exists
        url = app_public_url(app, server_host)
        status = "online" if exists else "offline"
        health = {"ok": exists, "checked": False, "message": "Modulo interno disponivel." if exists else "Arquivo nao encontrado."}
    else:
        status = "iniciado" if running else "pronto"
        health = {"ok": running, "checked": False, "message": status}

    return {
        "id": app_id,
        "name": app["name"],
        "description": app["description"],
        "kind": kind,
        "button": app["button"],
        "exists": exists,
        "running": running,
        "status": status,
        "url": url,
        "apiUrl": api_url,
        "health": health,
        "restricted": restricted,
        "maintenanceMessage": restricted_message if restricted else app.get("maintenance_message", ""),
        "publicPath": app.get("public_path"),
        "stack": app.get("stack", ""),
        "webPort": app.get("web_port"),
        "apiPort": app.get("api_port"),
        "adminOnly": bool(app.get("admin_only")),
        "allowGranularPermission": bool(app.get("allow_granular_permission", not app.get("admin_only"))),
        "staticBuild": has_static_build,
        "devProxy": bool(app.get("dev_proxy")),
        "lastChecked": health.get("lastChecked"),
        "statusDetail": health.get("message"),
        "apiOffline": bool(app.get("api_port")) and not test_tcp_port("127.0.0.1", app.get("api_port")),
        "backupLate": backup_late,
    }


def find_app(app_id: str) -> dict | None:
    for app in APPS:
        if app["id"] == app_id or app_id in app.get("legacy_ids", []):
            return app
    return None


def app_log_path(app_id: str) -> Path:
    mapping = {
        "notas": LOG_ROOT / "notas" / "notas.log",
        "colaboradores": LOG_ROOT / "colaboradores" / "colaboradores.log",
        "balanca": LOG_ROOT / "balanca-api" / "balanca-api.log",
        "analises": LOG_ROOT / "analises" / "analises.log",
    }
    return mapping.get(app_id, LOG_DIR / f"{app_id}.log")


def open_log(app_id: str):
    path = app_log_path(app_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8", buffering=1)






def static_build_available(app: dict) -> bool:
    static_dist = app.get("static_dist")
    if not static_dist:
        return False
    dist = Path(static_dist)
    return dist.exists() and (dist / "index.html").exists()


def start_app(app: dict[str, Any], mode: str = "web") -> tuple[bool, str]:
    # The demonstration runner owns all processes; the portal never kills or starts services.
    if app_is_fully_online(app):
        return True, "Modulo demonstrativo disponivel."
    return False, "Inicie a demonstracao com python demo.py start."


def app_is_fully_online(app: dict) -> bool:
    if app.get("kind") != "web":
        return process_is_running(STARTED_PROCESSES.get(app["id"]))
    if not static_build_available(app) and not test_tcp_port("127.0.0.1", app["web_port"]):
        return False
    api_port = app.get("api_port")
    if api_port and not test_tcp_port("127.0.0.1", api_port):
        return False
    health = read_health(app)
    return not health.get("checked") or bool(health.get("ok"))






class LauncherHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def handle_one_request(self) -> None:
        self.request_id = new_request_id()
        self.request_started_at = time.time()
        self.response_status = "-"
        self.proxy_system_id = "-"
        try:
            super().handle_one_request()
        finally:
            self.write_request_log()

    def log_message(self, fmt: str, *args) -> None:
        try:
            sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
            sys.stdout.flush()
        except OSError:
            pass

    def send_response(self, code, message=None) -> None:
        self.response_status = int(code)
        super().send_response(code, message)

    def end_headers(self) -> None:
        self.send_header("X-Request-ID", getattr(self, "request_id", ""))
        self.send_security_headers()
        super().end_headers()

    def write_request_log(self) -> None:
        path = getattr(self, "path", "-")
        route = urlparse(path).path if path != "-" else "-"
        user_label = "-"
        try:
            user = self.current_user()
            if user:
                user_label = clean_text(user.get("email") or user.get("name"), 180) or "-"
        except Exception:
            user_label = "-"
        duration_ms = int((time.time() - getattr(self, "request_started_at", time.time())) * 1000)
        PORTAL_LOGGER.info(
            f"request duration_ms={duration_ms}",
            extra={
                "request_id": getattr(self, "request_id", "-"),
                "user": user_label,
                "method": getattr(self, "command", "-"),
                "route": route,
                "status": getattr(self, "response_status", "-"),
                "system": getattr(self, "proxy_system_id", "-"),
            },
        )

    def request_is_https(self) -> bool:
        if PORTAL_HTTPS_ENABLED:
            return True
        client_ip = self.client_address[0] if self.client_address else ""
        forwarded_proto = (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        return client_ip in TRUSTED_PROXY_IPS and forwarded_proto == "https"

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self.request_is_https():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "img-src 'self' data: blob:; "
            "frame-src 'self' blob:; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'",
        )

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        if int(status) >= 400 and "request_id" not in payload:
            payload = {**payload, "request_id": getattr(self, "request_id", "")}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_binary(self, content: bytes, filename: str, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_inline_file(self, path: Path, filename: str, content_type: str) -> None:
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def allowed_cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return None
        normalized_origin = origin.strip().rstrip("/").lower()
        host_header = (self.headers.get("Host") or "").strip().lower()
        if not host_header or any(char in host_header for char in "\r\n/\\"):
            return None
        expected_scheme = "https" if self.request_is_https() else "http"
        expected_origin = f"{expected_scheme}://{host_header}"
        if normalized_origin == expected_origin or normalized_origin in PORTAL_ALLOWED_ORIGINS:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.allowed_cors_origin()
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")

    def reject_untrusted_api_origin(self) -> bool:
        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if fetch_site == "cross-site":
            self.send_json({"ok": False, "message": "Origem da requisicao nao autorizada."}, HTTPStatus.FORBIDDEN)
            return True
        if self.headers.get("Origin") and not self.allowed_cors_origin():
            self.send_json({"ok": False, "message": "Origem da requisicao nao autorizada."}, HTTPStatus.FORBIDDEN)
            return True
        return False

    def audit(self, user, event_type: str, module: str, summary: str, **kwargs) -> None:
        result = kwargs.pop("result", None)
        record_audit_event(
            user,
            event_type,
            module,
            summary,
            ip_address=self.client_address[0] if self.client_address else None,
            user_agent=self.headers.get("User-Agent"),
            route=urlparse(getattr(self, "path", "")).path,
            method=getattr(self, "command", ""),
            request_id=getattr(self, "request_id", ""),
            result=result,
            **kwargs,
        )


    def send_redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            self.rfile.read(min(length, MAX_JSON_BODY_BYTES))
            raise RequestBodyTooLarge
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))


    def set_session_cookie(self, token: str, max_age: int = SESSION_SECONDS) -> str:
        secure = "; Secure" if self.request_is_https() else ""
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"

    def clear_session_cookie(self) -> str:
        secure = "; Secure" if self.request_is_https() else ""
        return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"

    def current_user(self) -> dict | None:
        return get_session_user(self.headers)

    def require_user(self) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_json({"ok": False, "message": "Login necessario."}, HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def require_admin(self) -> dict | None:
        user = self.require_user()
        if not user:
            return None
        if not is_full_access_admin(user):
            self.audit(user, "ACCESS_DENIED", "launcher", "Tentou acessar area administrativa", result="denied")
            self.send_json({"ok": False, "message": "Acesso restrito ao administrador."}, HTTPStatus.FORBIDDEN)
            return None
        return user



    def proxy_auth_failed(self, route: dict) -> None:
        self.proxy_system_id = (route.get("app") or {}).get("id", "-")
        parsed_path = urlparse(self.path).path
        is_api = bool(route.get("api")) or strip_proxy_prefix(parsed_path, route["prefix"]).startswith("/api/")
        if is_api:
            self.send_json({"ok": False, "message": f"Login necessario pelo {SYSTEM_CURRENT_NAME}."}, HTTPStatus.UNAUTHORIZED)
        else:
            self.send_redirect("/login.html")

    def proxy_restricted(self, route: dict) -> None:
        app = route["app"]
        self.proxy_system_id = app.get("id", "-")
        parsed_path = urlparse(self.path).path
        is_api = bool(route.get("api")) or strip_proxy_prefix(parsed_path, route["prefix"]).startswith("/api/")
        message = maintenance_message_for_app(app)
        self.audit(
            self.current_user() or {"name": "Sistema"},
            "ACCESS_DENIED",
            app.get("audit_module", app["id"]),
            message,
            entity_type="app",
            entity_id=app["id"],
            result="denied",
        )
        if is_api:
            self.send_json({"ok": False, "message": message}, HTTPStatus.FORBIDDEN)
            return

        body = f"""
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{xml_escape(app['name'])} | {xml_escape(SYSTEM_CURRENT_NAME)}</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body class="login-page">
  <main class="auth-shell">
    <section class="auth-panel">
      <p class="eyebrow">PORTAL INTERNO</p>
      <h1>{xml_escape(app['name'])}</h1>
      <p>{xml_escape(message)}</p>
      <a class="start-button" href="/">Voltar ao portal</a>
    </section>
  </main>
</body>
</html>
""".strip().encode("utf-8")
        self.send_response(HTTPStatus.FORBIDDEN)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def maybe_proxy_request(self) -> bool:
        parsed = urlparse(self.path)
        route = proxy_route_for_path(parsed.path)
        if not route:
            return False

        prefix = route["prefix"]
        if parsed.path == prefix and self.command in {"GET", "HEAD"}:
            suffix = f"?{parsed.query}" if parsed.query else ""
            self.send_redirect(f"{prefix}/{suffix}")
            return True

        user = self.current_user()
        if not user:
            self.proxy_auth_failed(route)
            return True

        app = route["app"]
        if not user_can_access_system(user, app):
            self.proxy_restricted(route)
            return True

        if self.command in {"GET", "HEAD"} and not route.get("api") and static_build_available(app):
            if strip_proxy_prefix(parsed.path, prefix) in {"/", "/index.html"}:
                self.audit(
                    user,
                    "OPEN_SYSTEM",
                    app.get("audit_module", app["id"]),
                    f"Abriu {app['name']}",
                    entity_type="app",
                    entity_id=app["id"],
                    result="ok",
                )
            self.serve_static_build(route, parsed)
            return True

        if not route.get("api") and app.get("static_dist") and not app.get("dev_proxy"):
            self.send_json(
                {
                    "ok": False,
                    "message": "Build da Balanca nao encontrado. Execute npm run build em balanca-audit/apps/web.",
                },
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return True

        if self.command in {"GET", "HEAD"} and not route.get("api") and strip_proxy_prefix(parsed.path, prefix) in {"/", "/index.html"}:
            self.audit(
                user,
                "OPEN_SYSTEM",
                app.get("audit_module", app["id"]),
                f"Abriu {app['name']}",
                entity_type="app",
                entity_id=app["id"],
                result="ok",
            )

        self.proxy_to_app(route, parsed)
        return True

    def serve_static_build(self, route: dict, parsed) -> None:
        app = route["app"]
        self.proxy_system_id = app.get("id", "-")
        prefix = route["prefix"]
        dist = Path(app["static_dist"]).resolve()
        target_path = strip_proxy_prefix(parsed.path, prefix).lstrip("/")
        if not target_path:
            target_path = "index.html"
        requested = (dist / target_path).resolve()

        if not path_is_within(requested, dist):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.exists() or requested.is_dir():
            requested = dist / "index.html"
        if not requested.exists():
            self.send_json({"ok": False, "message": "Build estatico nao encontrado."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        try:
            content = requested.read_bytes()
        except OSError as exc:
            self.send_json({"ok": False, "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        content_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        if requested.suffix in {".js", ".mjs"}:
            content_type = "text/javascript"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if "/assets/" in requested.as_posix():
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def proxy_to_app(self, route: dict, parsed) -> None:
        self.proxy_system_id = (route.get("app") or {}).get("id", "-")
        port = route.get("port")
        if not port:
            self.send_json({"ok": False, "message": "Proxy nao configurado."}, HTTPStatus.BAD_GATEWAY)
            return

        target_path = strip_proxy_prefix(parsed.path, route["prefix"])
        target_url = f"http://127.0.0.1:{port}{target_path}"
        if parsed.query:
            target_url = f"{target_url}?{parsed.query}"

        body = None
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self.send_json({"ok": False, "message": "Transfer-Encoding nao suportado pelo proxy."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self.send_json({"ok": False, "message": "Content-Length invalido."}, HTTPStatus.BAD_REQUEST)
            return
        if length < 0:
            self.send_json({"ok": False, "message": "Content-Length invalido."}, HTTPStatus.BAD_REQUEST)
            return
        if length > PROXY_MAX_REQUEST_BODY_BYTES:
            self.close_connection = True
            self.send_json({"ok": False, "message": "Requisicao excede o limite do proxy."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        if length > 0:
            body = self.rfile.read(length)
            if len(body) != length:
                self.close_connection = True
                self.send_json({"ok": False, "message": "Corpo da requisicao incompleto."}, HTTPStatus.BAD_REQUEST)
                return

        headers = {}
        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
            "host",
            "content-length",
            "accept-encoding",
        }
        for key, value in self.headers.items():
            if key.lower() not in hop_by_hop:
                headers[key] = value
        headers["Host"] = f"127.0.0.1:{port}"
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https" if self.request_is_https() else "http"
        headers["X-Forwarded-For"] = self.client_address[0] if self.client_address else ""
        headers["X-Forwarded-Prefix"] = route["prefix"]
        headers["X-Request-ID"] = getattr(self, "request_id", "")
        user = self.current_user()
        if user:
            headers["X-Portal-User"] = clean_text(user.get("email"), 180)

        request = Request(target_url, data=body, headers=headers, method=self.command)
        app_id = str((route.get("app") or {}).get("id") or "")
        proxy_timeout = proxy_timeout_for(app_id, target_path)

        try:
            try:
                with urlopen(request, timeout=proxy_timeout) as response:
                    status = response.status
                    response_headers = response.headers
                    response_body = read_limited_proxy_response(response, response_headers)
            except HTTPError as exc:
                try:
                    status = exc.code
                    response_headers = exc.headers
                    response_body = read_limited_proxy_response(exc, response_headers)
                finally:
                    exc.close()
        except ProxyResponseTooLarge:
            self.send_json(
                {"ok": False, "message": "Resposta do sistema interno excede o limite seguro do proxy."},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except (URLError, TimeoutError, OSError) as exc:
            message = f"Sistema interno ainda nao respondeu: {exc}"
            app = route.get("app") or {}
            self.proxy_system_id = app.get("id", "-")
            self.audit(
                self.current_user() or {"name": "Sistema"},
                "PROXY_ERROR",
                app.get("audit_module", "launcher"),
                message,
                entity_type="app",
                entity_id=app.get("id"),
                details={"target": target_url},
                result="error",
            )
            self.send_json({"ok": False, "message": message}, HTTPStatus.BAD_GATEWAY)
            return

        content_type = response_headers.get("Content-Type", "")
        response_body = rewrite_proxy_body(response_body, content_type, route["prefix"])

        self.proxy_system_id = (route.get("app") or {}).get("id", "-")
        self.send_response(status)
        skipped_headers = {
            "connection",
            "content-length",
            "transfer-encoding",
            "content-encoding",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "upgrade",
        }
        for key, value in response_headers.items():
            if key.lower() not in skipped_headers:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)

    def handle_login(self) -> None:
        payload = self.read_json_body()
        raw_login = str(payload.get("email", ""))
        email = normalize_login_email(raw_login)
        password = str(payload.get("password", ""))
        session_age = REMEMBER_SESSION_SECONDS if payload.get("remember") else SESSION_SECONDS
        client_ip = self.client_address[0] if self.client_address else "unknown"
        retry_after = login_retry_after(client_ip, email)
        if retry_after > 0:
            self.audit(
                {"name": "Sistema", "email": email},
                "LOGIN_FAILED",
                "launcher",
                "Bloqueou tentativa repetida de login",
                entity_type="user",
                entity_id=email,
                details={"retryAfterSeconds": retry_after},
            )
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            body = json.dumps(
                {"ok": False, "message": "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente."},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", str(retry_after))
            self.send_header("Cache-Control", "no-store")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return
        with auth_conn() as conn:
            row, matched_login = find_user_for_login(conn, raw_login)
        email = matched_login
        if not row or row["provider"] != "local" or not verify_password(row["password_hash"], password):
            record_login_failure(client_ip, email)
            self.audit(
                {"name": "Sistema", "email": email},
                "LOGIN_FAILED",
                "launcher",
                "Falha de login no portal",
                entity_type="user",
                entity_id=email,
                result="failed",
            )
            self.send_json({"ok": False, "message": "E-mail ou senha incorretos."}, HTTPStatus.UNAUTHORIZED)
            return
        if row["status"] != "approved":
            record_login_failure(client_ip, email)
            self.send_json({"ok": False, "message": "Cadastro aguardando liberacao do administrador.", "status": row["status"]}, HTTPStatus.FORBIDDEN)
            return
        clear_login_failures(client_ip, email)
        token = create_session(row["id"], session_age)
        self.audit(
            row,
            "LOGIN_SUCCESS",
            "launcher",
            "Entrou no portal",
            entity_type="user",
            entity_id=row["id"],
            details={"remember": bool(payload.get("remember"))},
            result="ok",
        )
        body = json.dumps({"ok": True, "user": user_public(row)}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", self.set_session_cookie(token, session_age))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_register(self) -> None:
        payload = self.read_json_body()
        name = str(payload.get("name", "")).strip()
        email = normalize_email(payload.get("email", ""))
        password = str(payload.get("password", ""))
        if len(name) < 3:
            self.send_json({"ok": False, "message": "Informe seu nome completo."}, HTTPStatus.BAD_REQUEST)
            return
        if "@" not in email or "." not in email:
            self.send_json({"ok": False, "message": "Informe um e-mail valido."}, HTTPStatus.BAD_REQUEST)
            return
        if len(password) < 6:
            self.send_json({"ok": False, "message": "A senha precisa ter pelo menos 6 caracteres."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            with auth_conn() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (name, email, password_hash, provider, role, status, created_at)
                    VALUES (?, ?, ?, 'local', 'user', 'pending', ?)
                    """,
                    (name, email, hash_password(password), now_ts()),
                )
        except Exception as exc:
            exc_msg = str(exc).lower()
            if "unique" in exc_msg or "duplicate" in exc_msg or "already exists" in exc_msg:
                self.send_json({"ok": False, "message": "Este e-mail ja possui cadastro."}, HTTPStatus.CONFLICT)
                return
            raise
        self.audit(
            {"id": cursor.lastrowid, "name": name, "email": email},
            "USER_CREATED",
            "launcher",
            "Solicitou acesso ao portal",
            entity_type="user",
            entity_id=cursor.lastrowid,
            result="pending",
        )
        self.send_json({"ok": True, "message": "Cadastro enviado. Aguarde liberacao do administrador."}, HTTPStatus.CREATED)

    def update_own_profile(self) -> None:
        user = self.require_user()
        if not user:
            return

        payload = self.read_json_body()
        if not isinstance(payload, dict):
            self.send_json({"ok": False, "message": "Dados do perfil invalidos."}, HTTPStatus.BAD_REQUEST)
            return
        protected_fields = {"email", "provider", "role", "status", "permissions", "userId", "user_id"}
        if protected_fields.intersection(payload):
            self.send_json(
                {"ok": False, "message": "E-mail, perfil e permissoes nao podem ser alterados por este formulario."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        raw_name = payload.get("name", user.get("name", ""))
        if not isinstance(raw_name, str):
            self.send_json({"ok": False, "message": "Informe um nome de apresentacao valido."}, HTTPStatus.BAD_REQUEST)
            return
        name = normalize_display_name(raw_name)
        if len(name) < 3 or len(name) > 100:
            self.send_json(
                {"ok": False, "message": "O nome de apresentacao precisa ter entre 3 e 100 caracteres."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        current_password = payload.get("currentPassword", "")
        new_password = payload.get("newPassword", "")
        if not isinstance(current_password, str) or not isinstance(new_password, str):
            self.send_json({"ok": False, "message": "Dados de senha invalidos."}, HTTPStatus.BAD_REQUEST)
            return
        password_changed = bool(current_password or new_password)
        if password_changed and not current_password:
            self.send_json({"ok": False, "message": "Informe sua senha atual."}, HTTPStatus.BAD_REQUEST)
            return
        if password_changed and (len(new_password) < 6 or len(new_password) > 128):
            self.send_json(
                {"ok": False, "message": "A nova senha precisa ter entre 6 e 128 caracteres."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        client_ip = self.client_address[0] if getattr(self, "client_address", None) else "unknown"
        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
            if not target or target["status"] != "approved":
                self.send_json({"ok": False, "message": "Sessao invalida. Entre novamente."}, HTTPStatus.UNAUTHORIZED)
                return

            name_changed = name != target["name"]
            if password_changed:
                if target["provider"] != "local" or not target["password_hash"]:
                    self.send_json(
                        {"ok": False, "message": "A senha desta conta integrada nao pode ser alterada pelo portal."},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                retry_after = login_retry_after(client_ip, target["email"])
                if retry_after > 0:
                    self.audit(
                        user,
                        "PROFILE_UPDATE_DENIED",
                        "launcher",
                        "Bloqueou tentativas repetidas de confirmar a senha atual",
                        entity_type="user",
                        entity_id=user["id"],
                        details={"passwordChanged": False, "retryAfterSeconds": retry_after},
                        result="denied",
                        connection=conn,
                    )
                    self.send_json(
                        {"ok": False, "message": "Muitas tentativas. Aguarde alguns minutos e tente novamente."},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                if not verify_password(target["password_hash"], current_password):
                    record_login_failure(client_ip, target["email"])
                    self.audit(
                        user,
                        "PROFILE_UPDATE_DENIED",
                        "launcher",
                        "Falhou ao confirmar a senha atual",
                        entity_type="user",
                        entity_id=user["id"],
                        details={"passwordChanged": False},
                        result="denied",
                        connection=conn,
                    )
                    self.send_json({"ok": False, "message": "A senha atual esta incorreta."}, HTTPStatus.BAD_REQUEST)
                    return
                clear_login_failures(client_ip, target["email"])
                if current_password == new_password:
                    self.send_json(
                        {"ok": False, "message": "A nova senha precisa ser diferente da senha atual."},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return

            if name_changed:
                conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user["id"]))
            if password_changed:
                hash_cost = max(PASSWORD_ITERATIONS, password_hash_iterations(target["password_hash"]))
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(new_password, iterations=hash_cost), user["id"]),
                )
                current_token = parse_cookies(self.headers.get("Cookie")).get(SESSION_COOKIE)
                if current_token:
                    conn.execute(
                        "DELETE FROM sessions WHERE user_id = ? AND token <> ?",
                        (user["id"], current_token),
                    )
            updated = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
            if name_changed or password_changed:
                changed_labels = []
                if name_changed:
                    changed_labels.append("nome de apresentacao")
                if password_changed:
                    changed_labels.append("senha")
                self.audit(
                    updated,
                    "PROFILE_UPDATED",
                    "launcher",
                    f"Atualizou {' e '.join(changed_labels)} do proprio perfil",
                    entity_type="user",
                    entity_id=user["id"],
                    details={"nameChanged": name_changed, "passwordChanged": password_changed},
                    result="ok",
                    connection=conn,
                )
                message = "Perfil atualizado com sucesso."
            else:
                message = "Nenhuma alteracao foi necessaria."

        self.send_json({"ok": True, "message": message, "user": user_public(updated)})

    def list_users(self) -> None:
        with auth_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, email, provider, role, status, created_at, approved_at, approved_by
                FROM users
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, created_at DESC
                """
            ).fetchall()
            users = []
            for row in rows:
                item = user_public(row)
                item["permissions"] = user_permissions_public(conn, row)
                users.append(item)
        self.send_json({"ok": True, "users": users, "systems": permission_system_catalog()})

    def list_activity(self, params: dict[str, list[str]] | None = None) -> None:
        flat_params = {key: values[-1] for key, values in (params or {}).items()}
        limit = int(flat_params.get("limit") or AUDIT_EVENT_LIMIT)
        data = audit_query(flat_params, limit=limit)
        self.send_json({"ok": True, **data})

    def change_user_status(self, user_id: int, status: str, admin: dict) -> None:
        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                self.send_json({"ok": False, "message": "Usuario nao encontrado."}, HTTPStatus.NOT_FOUND)
                return
            if target["role"] == "admin" and status != "approved":
                self.send_json({"ok": False, "message": "Nao e permitido bloquear administrador."}, HTTPStatus.BAD_REQUEST)
                return
            conn.execute(
                "UPDATE users SET status = ?, approved_at = ?, approved_by = ? WHERE id = ?",
                (status, now_ts() if status == "approved" else None, admin["id"] if status == "approved" else None, user_id),
            )
            if status == "approved":
                grant_default_system_permissions(conn, user_id)
            if status != "approved":
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        verb = "Liberou acesso" if status == "approved" else "Bloqueou acesso"
        self.audit(
            admin,
            "PERMISSION_CHANGED" if status == "approved" else "USER_DISABLED",
            "launcher",
            f"{verb} de {target['name']}",
            entity_type="user",
            entity_id=target["id"],
            details={"targetName": target["name"], "targetEmail": target["email"], "status": status},
            result="ok",
        )
        self.send_json({"ok": True})

    def delete_user(self, user_id: int, admin: dict) -> None:
        if user_id == int(admin["id"]):
            self.send_json({"ok": False, "message": "Nao e permitido excluir o proprio usuario logado."}, HTTPStatus.BAD_REQUEST)
            return

        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                self.send_json({"ok": False, "message": "Usuario nao encontrado."}, HTTPStatus.NOT_FOUND)
                return
            if target["role"] == "admin":
                self.send_json({"ok": False, "message": "Nao e permitido excluir administrador."}, HTTPStatus.BAD_REQUEST)
                return

            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_login_aliases WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM system_permissions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        self.audit(
            admin,
            "USER_DELETED",
            "launcher",
            f"Excluiu usuario {target['name']}",
            entity_type="user",
            entity_id=target["id"],
            details={"targetName": target["name"], "targetRole": target["role"], "targetStatus": target["status"]},
            result="ok",
        )
        self.send_json({"ok": True, "message": "Usuario excluido."})

    def change_user_password(self, user_id: int, admin: dict) -> None:
        payload = self.read_json_body()
        password = str(payload.get("password", ""))

        if len(password) < 6:
            self.send_json({"ok": False, "message": "A senha precisa ter pelo menos 6 caracteres."}, HTTPStatus.BAD_REQUEST)
            return

        if len(password) > 128:
            self.send_json({"ok": False, "message": "A senha informada esta muito grande."}, HTTPStatus.BAD_REQUEST)
            return

        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                self.send_json({"ok": False, "message": "Usuario nao encontrado."}, HTTPStatus.NOT_FOUND)
                return

            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
            if user_id != admin["id"]:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        self.audit(
            admin,
            "PERMISSION_CHANGED",
            "launcher",
            f"Alterou senha de {target['name']}",
            entity_type="user",
            entity_id=target["id"],
            details={"targetName": target["name"], "targetEmail": target["email"], "passwordChanged": True},
            result="ok",
        )
        self.send_json({"ok": True, "message": "Senha atualizada."})

    def show_user_permissions(self, user_id: int) -> None:
        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                self.send_json({"ok": False, "message": "Usuario nao encontrado."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(
                {
                    "ok": True,
                    "user": user_public(target),
                    "systems": permission_system_catalog(),
                    "permissions": user_permissions_public(conn, target),
                }
            )

    def change_user_permissions(self, user_id: int, admin: dict) -> None:
        payload = self.read_json_body()
        requested = payload.get("permissions")
        if not isinstance(requested, dict):
            self.send_json({"ok": False, "message": "Permissoes invalidas."}, HTTPStatus.BAD_REQUEST)
            return

        catalog = {system["id"]: system for system in permission_system_catalog()}
        invalid = sorted(system_id for system_id in requested if system_id not in catalog)
        if invalid:
            self.send_json({"ok": False, "message": f"Sistema invalido: {', '.join(invalid)}"}, HTTPStatus.BAD_REQUEST)
            return

        now = now_ts()
        changed = []
        with auth_conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                self.send_json({"ok": False, "message": "Usuario nao encontrado."}, HTTPStatus.NOT_FOUND)
                return
            if target["role"] == "admin":
                self.send_json({"ok": False, "message": "Administrador ja possui acesso total por perfil."}, HTTPStatus.BAD_REQUEST)
                return

            for system_id, value in requested.items():
                system = catalog[system_id]
                if system["adminOnly"] and not system["allowGranularPermission"]:
                    continue
                can_access = 1 if bool(value) else 0
                conn.execute(
                    """
                    INSERT INTO system_permissions (user_id, system_id, can_access, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, system_id)
                    DO UPDATE SET can_access = excluded.can_access, updated_at = excluded.updated_at
                    """,
                    (user_id, system_id, can_access, now, now),
                )
                changed.append({"systemId": system_id, "canAccess": bool(can_access)})

            updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            permissions = user_permissions_public(conn, updated)

        self.audit(
            admin,
            "PERMISSION_CHANGED",
            "launcher",
            f"Atualizou permissoes de {target['name']}",
            entity_type="user",
            entity_id=target["id"],
            details={"targetName": target["name"], "targetEmail": target["email"], "permissions": changed},
            result="ok",
        )
        self.send_json({"ok": True, "permissions": permissions})

    def do_GET(self):
        if self.maybe_proxy_request():
            return

        parsed = urlparse(self.path)
        public_paths = {
            "/login.html",
            "/styles.css",
            "/auth.js",
            "/audit-client.js",
            "/manifest.json",
            "/service-worker.js",
        }

        if parsed.path == "/health":
            self.send_json(portal_health())
            return

        if parsed.path == "/api/session":
            user = self.current_user()
            self.send_json({"ok": True, "authenticated": bool(user), "user": user})
            return

        if parsed.path == "/api/status":
            user = self.require_user()
            if not user:
                return
            server_host = get_client_server_host(self.headers)
            visible_apps = APPS
            self.send_json(
                {
                    "ok": True,
                    "server": {
                        "name": socket.gethostname(),
                    "launcherPort": PORT,
                    "host": server_host,
                    "localUrl": f"http://localhost:{PORT}",
                    "friendlyUrl": f"http://{FRIENDLY_HOST}:{PORT}",
                    "networkUrl": f"http://{get_lan_ip()}:{PORT}",
                    "computerUrl": f"http://{socket.gethostname()}:{PORT}",
                    "lanIp": get_lan_ip(),
                    "friendlyHost": FRIENDLY_HOST,
                    "version": PORTAL_VERSION,
                },
                    "apps": [app_public_data(app, server_host, user) for app in visible_apps],
                }
            )
            return




        if parsed.path == "/api/admin/users":
            if not self.require_admin():
                return
            self.list_users()
            return

        if parsed.path == "/api/admin/activity":
            if not self.require_admin():
                return
            self.list_activity(parse_qs(parsed.query))
            return

        if parsed.path == "/api/admin/activity/export":
            if not self.require_admin():
                return
            filters = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            content = audit_export_xlsx(filters)
            filename = f"auditoria_portal_agricola_{iso_stamp()}.xlsx"
            self.send_binary(content, filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return

        if parsed.path == "/api/admin/health":
            if not self.require_admin():
                return
            server_host = get_client_server_host(self.headers)
            self.send_json({"ok": True, "health": admin_health_status(server_host)})
            return

        if parsed.path == "/api/admin/backups":
            if not self.require_admin():
                return
            self.send_json({"ok": True, "backup": backup_public_status()})
            return

        if len(parts := [part for part in parsed.path.split("/") if part]) == 5 and parts[0] == "api" and parts[1] == "admin" and parts[2] == "users" and parts[4] == "permissions":
            if not self.require_admin():
                return
            try:
                user_id = int(parts[3])
            except ValueError:
                self.send_json({"ok": False, "message": "Usuario invalido."}, HTTPStatus.BAD_REQUEST)
                return
            self.show_user_permissions(user_id)
            return


        if parsed.path == "/":
            if not self.current_user():
                self.send_redirect("/login.html")
                return
            self.path = "/index.html"
        elif parsed.path == "/index.html":
            if not self.current_user():
                self.send_redirect("/login.html")
                return
        elif not (parsed.path in public_paths or parsed.path.startswith("/assets/")):
            if not self.current_user():
                self.send_redirect("/login.html")
                return
        return super().do_GET()

    def do_OPTIONS(self):
        if self.maybe_proxy_request():
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_POST(self):
        if self.reject_untrusted_api_origin():
            return
        if self.maybe_proxy_request():
            return

        try:
            self.handle_post()
        except RequestBodyTooLarge:

            self.send_json({"ok": False, "message": "Requisicao muito grande."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except json.JSONDecodeError:

            self.send_json({"ok": False, "message": "JSON invalido."}, HTTPStatus.BAD_REQUEST)

    def do_PUT(self):
        if self.reject_untrusted_api_origin():
            return
        if not self.maybe_proxy_request():
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self):
        if self.reject_untrusted_api_origin():
            return
        if not self.maybe_proxy_request():
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        if self.reject_untrusted_api_origin():
            return
        if not self.maybe_proxy_request():
            self.send_error(HTTPStatus.NOT_FOUND)

    def handle_post(self):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path.startswith("/api/") and self.reject_untrusted_api_origin():
            return
        if parsed.path == "/api/login":
            self.handle_login()
            return
        if parsed.path == "/api/register":
            self.handle_register()
            return
        if parsed.path == "/api/logout":
            user = self.current_user()
            delete_session(self.headers)
            if user:
                self.audit(user, "LOGOUT", "launcher", "Saiu do portal", entity_type="user", entity_id=user["id"], result="ok")
            body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", self.clear_session_cookie())
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/profile":
            self.update_own_profile()
            return
        if parsed.path == "/api/audit/event":
            user = self.require_user()
            if not user:
                return
            payload = self.read_json_body()
            module = clean_text(payload.get("module"), 80) or "sistema"
            event_type = clean_text(payload.get("eventType") or payload.get("event_type"), 80) or "item.update"
            summary = clean_text(payload.get("summary"), 260) or "Alteracao registrada"
            self.audit(
                user,
                event_type,
                module,
                summary,
                entity_type=payload.get("entityType") or payload.get("entity_type"),
                entity_id=payload.get("entityId") or payload.get("entity_id"),
                details=payload.get("details") if isinstance(payload.get("details"), dict) else None,
            )
            self.send_json({"ok": True})
            return







        if len(parts) == 4 and parts[0] == "api" and parts[1] == "admin" and parts[2] == "users":
            admin = self.require_admin()
            if not admin:
                return
            try:
                user_id = int(parts[3])
            except ValueError:
                self.send_json({"ok": False, "message": "Usuario invalido."}, HTTPStatus.BAD_REQUEST)
                return
            action = (parse_qs(parsed.query).get("action") or [""])[0]
            if action not in {"approve", "block", "delete"}:
                self.send_json({"ok": False, "message": "Acao invalida."}, HTTPStatus.BAD_REQUEST)
                return
            if action == "delete":
                self.delete_user(user_id, admin)
                return
            self.change_user_status(user_id, "approved" if action == "approve" else "blocked", admin)
            return
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "admin" and parts[2] == "users" and parts[4] == "password":
            admin = self.require_admin()
            if not admin:
                return
            try:
                user_id = int(parts[3])
            except ValueError:
                self.send_json({"ok": False, "message": "Usuario invalido."}, HTTPStatus.BAD_REQUEST)
                return
            self.change_user_password(user_id, admin)
            return
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "admin" and parts[2] == "users" and parts[4] == "permissions":
            admin = self.require_admin()
            if not admin:
                return
            try:
                user_id = int(parts[3])
            except ValueError:
                self.send_json({"ok": False, "message": "Usuario invalido."}, HTTPStatus.BAD_REQUEST)
                return
            self.change_user_permissions(user_id, admin)
            return
        if parsed.path == "/api/admin/backups/create":
            admin = self.require_admin()
            if not admin:
                return
            result = create_portal_backup(force=True, request_id=getattr(self, "request_id", ""), created_by=admin.get("email", "admin"))
            self.audit(
                admin,
                "BACKUP_CREATED" if result.get("ok") else "BACKUP_FAILED",
                "launcher",
                result.get("message") or "Backup manual",
                entity_type="backup",
                entity_id=Path(result.get("file", "")).name if result.get("file") else "",
                result="ok" if result.get("ok") else "failed",
            )
            self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/admin/backups/verify":
            admin = self.require_admin()
            if not admin:
                return
            payload = self.read_json_body()
            result = verify_portal_backup(str(payload.get("name") or ""))
            self.audit(
                admin,
                "backup.verify" if result.get("ok") else "backup.verify_failed",
                "launcher",
                result.get("message") or "Verificou backup",
                entity_type="backup",
                entity_id=result.get("file") or payload.get("name") or "",
            )
            self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/admin/backups/prepare-restore":
            admin = self.require_admin()
            if not admin:
                return
            payload = self.read_json_body()
            result = prepare_portal_restore(str(payload.get("name") or ""))
            self.audit(
                admin,
                "RESTORE_STARTED" if result.get("ok") else "RESTORE_FAILED",
                "launcher",
                result.get("message") or "Preparou restauracao",
                entity_type="backup",
                entity_id=result.get("file") or payload.get("name") or "",
                details={"restorePath": result.get("restorePath")},
                result="ok" if result.get("ok") else "failed",
            )
            self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "start":
            user = self.require_user()
            if not user:
                return
            app = find_app(parts[2])
            if app and not user_can_access_system(user, app):
                result = {"ok": False, "message": maintenance_message_for_app(app)}
                self.audit(
                    user,
                    "ACCESS_DENIED",
                    app.get("audit_module", "launcher"),
                    f"Tentou acessar {app['name']} em manutencao",
                    entity_type="app",
                    entity_id=parts[2],
                    details={"message": result["message"], "appName": app["name"], "restricted": True},
                    result="denied",
                )
                self.send_json(result, HTTPStatus.FORBIDDEN)
                return
            result = start_app(parts[2])
            self.audit(
                user,
                "SYSTEM_STARTED" if result["ok"] else "PROXY_ERROR",
                app.get("audit_module", "launcher") if app else "launcher",
                f"{'Iniciou' if result['ok'] else 'Falhou ao iniciar'} {app['name'] if app else parts[2]}",
                entity_type="app",
                entity_id=parts[2],
                details={"message": result.get("message"), "appName": app["name"] if app else parts[2]},
                result="ok" if result["ok"] else "failed",
            )
            status = HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_REQUEST
            self.send_json(result, status)
            return

        self.send_json({"ok": False, "message": "Rota nao encontrada."}, HTTPStatus.NOT_FOUND)


class FastThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    allow_reuse_address = False
    daemon_threads = True


def main() -> None:
    os.chdir(BASE_DIR)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    ensure_log_dirs(LOG_ROOT)
    setup_auth_db()
    server = FastThreadingHTTPServer(("127.0.0.1", PORT), LauncherHandler)
    print(f"Operacoes Agricolas - demonstracao em http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
