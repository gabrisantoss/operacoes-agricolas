import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_DIR = PROJECT_ROOT.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agricola_shared.db_compat import connect as connect_postgres_db
from agricola_shared.db_compat import connect_sqlite as connect_sqlite_db


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key.strip():
            os.environ.setdefault(key.strip(), value)


_load_env(PROJECT_ROOT / "analises.env")


class DatabaseConfig:
    """Configuracoes centrais do banco de dados."""

    DB_PATH = str(PROJECT_ROOT / "operacao_agricola.db")
    DB_ENGINE = os.environ.get("ANALISES_DB_ENGINE", "sqlite").strip().lower()
    DATABASE_URL = os.environ.get("ANALISES_DATABASE_URL", "").strip()
    TIMEOUT = 30

    @classmethod
    def get_connection(cls):
        if cls.DB_ENGINE in {"postgres", "postgresql"}:
            if not cls.DATABASE_URL:
                raise RuntimeError("ANALISES_DATABASE_URL nao configurada para PostgreSQL.")
            return connect_postgres_db(cls.DATABASE_URL, row_factory=sqlite3.Row)
        return connect_sqlite_db(cls.DB_PATH, timeout=cls.TIMEOUT, row_factory=None)
