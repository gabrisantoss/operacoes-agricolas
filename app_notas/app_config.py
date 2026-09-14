from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_ROOT = _app_root()
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT)).resolve()
ENV_PATH = APP_ROOT / "app_notas.env"


def _load_local_env(env_path: Path = ENV_PATH) -> None:
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except OSError:
        pass


def _env(nome: str, padrao: str = "") -> str:
    valor = os.getenv(nome, "").strip()
    return valor or padrao


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(_env(nome, str(padrao)))
    except ValueError:
        return padrao


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(_env(nome, str(padrao)))
    except ValueError:
        return padrao


def _env_path(nome: str, padrao: Path) -> Path:
    valor = _env(nome)
    if not valor:
        return padrao
    caminho = Path(os.path.expandvars(valor)).expanduser()
    if not caminho.is_absolute():
        caminho = APP_ROOT / caminho
    return caminho


def _resource_path(nome: str, arquivo_padrao: str) -> Path:
    valor = _env(nome)
    if valor:
        return _env_path(nome, APP_ROOT / arquivo_padrao)

    caminho_local = APP_ROOT / arquivo_padrao
    if caminho_local.exists():
        return caminho_local
    return RESOURCE_ROOT / arquivo_padrao


def _default_backup_drive_path() -> Path:
    return APP_ROOT.parent / ".demo" / "backups" / "notas"


_load_local_env()

DB_PATH = _env_path("APP_NOTAS_DB_PATH", APP_ROOT / "transporte.db")
# Engine de producao e PostgreSQL. O padrao e postgres para nao cair
# silenciosamente no SQLite legado caso o .env nao carregue. Use SQLite apenas
# definindo APP_NOTAS_DB_ENGINE=sqlite explicitamente.
_DB_ENGINE_RAW = _env("APP_NOTAS_DB_ENGINE", "postgresql").lower()
DB_ENGINE = "postgresql" if _DB_ENGINE_RAW in {"postgres", "postgresql", "pg"} else _DB_ENGINE_RAW
DATABASE_URL = _env("APP_NOTAS_DATABASE_URL")

if DB_ENGINE == "postgresql" and not DATABASE_URL:
    raise RuntimeError(
        "APP_NOTAS_DB_ENGINE=postgresql exige APP_NOTAS_DATABASE_URL definida. "
        "Configure a URL do PostgreSQL no app_notas.env ou defina "
        "APP_NOTAS_DB_ENGINE=sqlite explicitamente para usar o banco local."
    )
BALANCA_DB_PATH = _env_path(
    "APP_NOTAS_BALANCA_DB_PATH",
    APP_ROOT.parent / "balanca-audit" / "apps" / "api" / "data" / "balanca.db",
)
BALANCA_API_URL = _env("APP_NOTAS_BALANCA_API_URL")
BALANCA_API_TOKEN = _env("APP_NOTAS_BALANCA_API_TOKEN")
BALANCA_API_EMAIL = _env("APP_NOTAS_BALANCA_API_EMAIL")
BALANCA_API_PASSWORD = _env("APP_NOTAS_BALANCA_API_PASSWORD")
BALANCA_API_TIMEOUT_SECONDS = _env_float("APP_NOTAS_BALANCA_API_TIMEOUT_SECONDS", 20.0)
EXCEL_ORIGEM = _resource_path("APP_NOTAS_EXCEL_ORIGEM", "transporte-ficticio.xlsx")
BACKUP_DRIVE_PATH = _env_path("APP_NOTAS_BACKUP_PATH", _default_backup_drive_path())
MAX_BACKUPS = _env_int("APP_NOTAS_MAX_BACKUPS", 50)
MAX_LOCAL_BACKUPS = _env_int("APP_NOTAS_MAX_LOCAL_BACKUPS", MAX_BACKUPS)
SQLITE_BUSY_TIMEOUT_MS = _env_int("APP_NOTAS_SQLITE_BUSY_TIMEOUT_MS", 5000)
LOG_LEVEL = _env("APP_NOTAS_LOG_LEVEL", "INFO").upper()
LOG_DIR = APP_ROOT / "logs"
LOG_PATH = LOG_DIR / "app_notas.log"
