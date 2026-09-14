from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app_config import APP_ROOT
from app_logging import get_logger


LOGGER = get_logger(__name__)
DEFAULT_TTL_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 5.0


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "nao", "no", "off"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class ReferenceRecord(dict):
    """Dict compatible with sqlite Row-like numeric access used by legacy UI code."""

    _order = ("codigo", "nome")

    def __getitem__(self, key):
        if isinstance(key, int):
            return super().__getitem__(self._order[key])
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


@dataclass(frozen=True)
class PostgresTarget:
    host: str
    port: str
    database: str
    user: str
    password: str


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _target_from_config(config_path: Path) -> PostgresTarget | None:
    config = _load_json_config(config_path)
    engine = str(config.get("db_engine") or "sqlite").strip().lower()
    if engine not in {"postgres", "postgresql"}:
        return None

    explicit_url = str(config.get("database_url") or "").strip()
    if explicit_url:
        from agricola_shared.demo_safety import assert_demo_database_target
        assert_demo_database_target(explicit_url)
        parsed = urlparse(explicit_url)
        return PostgresTarget(
            host=parsed.hostname or "127.0.0.1",
            port=str(parsed.port or 5432),
            database=(parsed.path or "/app_colaboradores").lstrip("/"),
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
        )

    return PostgresTarget(
        host=str(config.get("postgres_host") or "127.0.0.1").strip(),
        port=str(config.get("postgres_port") or 5432),
        database=str(config.get("postgres_database") or "app_colaboradores").strip(),
        user=str(config.get("postgres_user") or "").strip(),
        password=str(config.get("postgres_password") or ""),
    )


def _find_psql() -> str | None:
    candidate = shutil.which("psql")
    if candidate:
        return candidate
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for path in sorted(program_files.glob("PostgreSQL/*/bin/psql.exe"), reverse=True):
        if path.exists():
            return str(path)
    return None


class ColaboradoresReferenceProvider:
    def __init__(
        self,
        config_path: Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        timeout_seconds: float | None = None,
    ):
        self.config_path = config_path or Path(
            os.getenv(
                "APP_NOTAS_COLABORADORES_CONFIG_PATH",
                str(APP_ROOT.parent / "app_colaboradores" / "app_config.json"),
            )
        )
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else _env_float(
            "APP_NOTAS_COLABORADORES_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
        )
        self._lock = threading.Lock()
        self._cache_expires_at = 0.0
        self._cache: list[ReferenceRecord] | None = None
        self._last_fetch_at = 0.0
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        return _env_flag("APP_NOTAS_COLABORADORES_REFERENCIAS", True)

    @property
    def last_error(self) -> str:
        return self._last_error

    def _run_psql_json(self, sql: str) -> list[dict[str, Any]]:
        target = _target_from_config(self.config_path)
        if target is None:
            return []
        psql = _find_psql()
        if not psql:
            raise RuntimeError("psql.exe nao encontrado para consultar Colaboradores.")

        env = os.environ.copy()
        env["PGPASSWORD"] = target.password
        env["PGCLIENTENCODING"] = "UTF8"
        completed = subprocess.run(
            [
                psql,
                "-h",
                target.host,
                "-p",
                target.port,
                "-U",
                target.user,
                "-d",
                target.database,
                "-tA",
                "-c",
                sql,
            ],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(self.timeout_seconds)),
        )
        raw = completed.stdout.strip()
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []

    def _fetch_all(self) -> list[ReferenceRecord]:
        sql = """
            SELECT COALESCE(json_agg(row_to_json(q))::text, '[]')
            FROM (
                SELECT
                    codigo_colaborador AS codigo,
                    nome,
                    COALESCE(frente_safra, '') AS frente_safra,
                    COALESCE(funcao_safra, funcao, '') AS funcao_safra,
                    COALESCE(turno_safra, '') AS turno_safra,
                    COALESCE(situacao, '') AS situacao
                FROM colaboradores
                WHERE BTRIM(COALESCE(codigo_colaborador, '')) <> ''
                  AND BTRIM(COALESCE(nome, '')) <> ''
                  AND UPPER(BTRIM(COALESCE(situacao, ''))) = 'ATIVO'
                ORDER BY nome
            ) q;
        """
        records: list[ReferenceRecord] = []
        for row in self._run_psql_json(sql):
            if not isinstance(row, dict):
                continue
            codigo = _clean(row.get("codigo"))
            nome = _clean(row.get("nome"))
            if not codigo or not nome:
                continue
            records.append(
                ReferenceRecord(
                    codigo=codigo,
                    nome=nome,
                    fonte="portal_colaboradores",
                    frente_safra=_clean(row.get("frente_safra")),
                    funcao_safra=_clean(row.get("funcao_safra")),
                    turno_safra=_clean(row.get("turno_safra")),
                    situacao=_clean(row.get("situacao")),
                )
            )
        return records

    def listar_referencias(self, q: str = "", limit: int | None = None) -> list[ReferenceRecord]:
        if not self.enabled:
            return []

        try:
            now = time.monotonic()
            with self._lock:
                if self._cache is None or now >= self._cache_expires_at:
                    self._cache = self._fetch_all()
                    self._cache_expires_at = now + self.ttl_seconds
                    self._last_fetch_at = time.time()
                    self._last_error = ""
                rows = list(self._cache)
        except Exception as exc:
            self._last_error = str(exc)
            LOGGER.warning("Falha ao consultar referencias do Portal Colaboradores: %s", exc)
            return []

        query = _normalize(q)
        if query:
            rows = [
                row
                for row in rows
                if query in _normalize(row.get("codigo")) or query in _normalize(row.get("nome"))
            ]
        rows.sort(key=lambda item: (_normalize(item.get("nome")), _clean(item.get("codigo"))))
        if limit is not None:
            return rows[: max(0, int(limit))]
        return rows

    def buscar_referencia(self, valor: Any) -> ReferenceRecord | None:
        text = _clean(valor)
        if not text or not self.enabled:
            return None
        if " - " in text:
            codigo, nome = text.split(" - ", 1)
            return self.buscar_referencia(codigo) or self.buscar_referencia(nome)

        normalized = _normalize(text)
        if not normalized:
            return None

        for row in self.listar_referencias():
            if _clean(row.get("codigo")) == text:
                return row
        for row in self.listar_referencias():
            if _normalize(row.get("nome")) == normalized:
                return row
        return None

    def status(self) -> dict[str, Any]:
        target = _target_from_config(self.config_path)
        psql = _find_psql()
        cache_size = len(self._cache or [])
        cache_age_seconds = (
            round(time.time() - self._last_fetch_at, 2)
            if self._last_fetch_at
            else None
        )
        result: dict[str, Any] = {
            "ok": False,
            "status": "alerta",
            "source": "portal_colaboradores",
            "enabled": self.enabled,
            "configPath": str(self.config_path),
            "configExists": self.config_path.exists(),
            "targetConfigured": target is not None,
            "target": {
                "host": target.host,
                "port": target.port,
                "database": target.database,
            }
            if target
            else None,
            "psqlFound": bool(psql),
            "timeoutSeconds": max(1.0, float(self.timeout_seconds)),
            "cached": self._cache is not None,
            "cacheSize": cache_size,
            "cacheAgeSeconds": cache_age_seconds,
            "totalReferences": cache_size,
            "lastError": self._last_error,
            "issues": [],
        }

        if not result["enabled"]:
            result["status"] = "desativado"
            result["issues"].append("Consulta ao Portal Colaboradores desativada por configuracao.")
        elif target is None:
            result["issues"].append("Configuracao do Portal Colaboradores nao aponta para PostgreSQL.")
        elif not psql:
            result["issues"].append("psql.exe nao encontrado para consultar o Portal Colaboradores.")
        else:
            rows = self.listar_referencias()
            result["totalReferences"] = len(rows)
            result["cached"] = self._cache is not None
            result["cacheSize"] = len(self._cache or [])
            result["cacheAgeSeconds"] = (
                round(time.time() - self._last_fetch_at, 2)
                if self._last_fetch_at
                else None
            )
            result["lastError"] = self._last_error
            if self._last_error:
                result["issues"].append(f"Falha ao consultar Portal Colaboradores: {self._last_error}")
            elif not rows:
                result["issues"].append("Nenhum colaborador ativo com codigo foi retornado pelo Portal Colaboradores.")

        result["ok"] = not result["issues"]
        if result["ok"]:
            result["status"] = "online"
            result["message"] = f"Portal Colaboradores disponivel com {result['totalReferences']} referencia(s)."
        else:
            result["message"] = "Portal Colaboradores requer atencao para novas notas."
        return result


_PROVIDER: ColaboradoresReferenceProvider | None = None
_PROVIDER_LOCK = threading.Lock()


def get_colaboradores_provider() -> ColaboradoresReferenceProvider:
    global _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is None:
            _PROVIDER = ColaboradoresReferenceProvider()
        return _PROVIDER
