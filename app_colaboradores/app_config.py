from __future__ import annotations

import getpass
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)).resolve() if IS_FROZEN else APP_DIR
BASE_DIR = APP_DIR
DEFAULT_CONFIG = {
    "db_engine": "sqlite",
    "sqlite_path": "colaboradores.db",
    "database_url": "",
    "postgres_host": "127.0.0.1",
    "postgres_port": 5432,
    "postgres_database": "app_colaboradores",
    "postgres_user": getpass.getuser(),
    "postgres_password": "",
    "qt_platform": "",
    "storage_root": ".",
    "backup_dir": "backups_db",
}
ENV_OVERRIDES = {
    "db_engine": "APP_COLAB_DB_ENGINE",
    "sqlite_path": "APP_COLAB_SQLITE_PATH",
    "database_url": "APP_COLAB_DATABASE_URL",
    "postgres_host": "APP_COLAB_POSTGRES_HOST",
    "postgres_port": "APP_COLAB_POSTGRES_PORT",
    "postgres_database": "APP_COLAB_POSTGRES_DATABASE",
    "postgres_user": "APP_COLAB_POSTGRES_USER",
    "postgres_password": "APP_COLAB_POSTGRES_PASSWORD",
    "qt_platform": "APP_COLAB_QT_PLATFORM",
    "storage_root": "APP_COLAB_STORAGE_ROOT",
    "backup_dir": "APP_COLAB_BACKUP_DIR",
}


def _get_config_file_path() -> Path:
    custom_path = os.getenv("APP_COLAB_CONFIG_FILE")
    if not custom_path:
        return APP_DIR / "app_config.json"

    candidate = Path(custom_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _load_file_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}

    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Nao foi possivel carregar %s: %s", config_path, exc)
        return {}

    if not isinstance(data, dict):
        logging.warning("Arquivo de configuracao ignorado: raiz precisa ser um objeto JSON.")
        return {}
    return data


def _resolve_path(raw_value: str, base_dir: Path) -> Path:
    path = Path(str(raw_value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _build_postgres_url(config: dict[str, Any]) -> str:
    explicit_url = str(config.get("database_url") or "").strip()
    if explicit_url:
        return explicit_url

    host = str(config.get("postgres_host") or "").strip() or "127.0.0.1"
    port = int(config.get("postgres_port") or 5432)
    database = str(config.get("postgres_database") or "app_colaboradores").strip()
    user = str(config.get("postgres_user") or getpass.getuser()).strip()
    password = str(config.get("postgres_password") or "")

    auth = user
    if password:
        auth += f":{password}"

    if host.startswith("/"):
        return f"postgresql://{auth}@/{database}?host={host}"
    return f"postgresql://{auth}@{host}:{port}/{database}"


def _redact_connection_target(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.password is None:
        return value

    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}:***@" if username else "***@"
    return urlunparse(parsed._replace(netloc=f"{auth}{host}{port}"))


CONFIG_FILE_PATH = _get_config_file_path()
CONFIG_BASE_DIR = CONFIG_FILE_PATH.parent if CONFIG_FILE_PATH.parent else BASE_DIR
_runtime_config = dict(DEFAULT_CONFIG)
_runtime_config.update(_load_file_config(CONFIG_FILE_PATH))

for key, env_var in ENV_OVERRIDES.items():
    env_value = os.getenv(env_var)
    if env_value not in (None, ""):
        _runtime_config[key] = env_value

DB_ENGINE = str(_runtime_config["db_engine"]).strip().lower()
SQLITE_PATH = str(_resolve_path(str(_runtime_config["sqlite_path"]), CONFIG_BASE_DIR))
DATABASE_URL = _build_postgres_url(_runtime_config)
DB_PATH = DATABASE_URL if DB_ENGINE == "postgresql" else SQLITE_PATH
STORAGE_ROOT = str(_resolve_path(str(_runtime_config["storage_root"]), CONFIG_BASE_DIR))
BACKUP_FOLDER_DEFAULT = str(_resolve_path(str(_runtime_config["backup_dir"]), CONFIG_BASE_DIR))


def ensure_runtime_directories() -> None:
    if DB_ENGINE == "sqlite":
        Path(SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(STORAGE_ROOT).mkdir(parents=True, exist_ok=True)
    Path(BACKUP_FOLDER_DEFAULT).mkdir(parents=True, exist_ok=True)


def get_runtime_config() -> dict[str, str]:
    db_target = DB_PATH if DB_ENGINE != "postgresql" else _redact_connection_target(DB_PATH)
    database_url = _redact_connection_target(DATABASE_URL)
    return {
        "app_dir": str(APP_DIR),
        "resource_dir": str(RESOURCE_DIR),
        "config_file": str(CONFIG_FILE_PATH),
        "db_engine": DB_ENGINE,
        "db_target": db_target,
        "sqlite_path": SQLITE_PATH,
        "database_url": database_url,
        "qt_platform": str(_runtime_config.get("qt_platform") or ""),
        "storage_root": STORAGE_ROOT,
        "backup_dir": BACKUP_FOLDER_DEFAULT,
    }


ensure_runtime_directories()
