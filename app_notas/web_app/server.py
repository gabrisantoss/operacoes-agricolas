from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import threading
import time
import mimetypes
from contextlib import contextmanager
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen


APP_ROOT = Path(__file__).resolve().parents[1]
ROOT_DIR = APP_ROOT.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
GENERATED_DIR = Path(__file__).resolve().parent / "generated"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_config import BACKUP_DRIVE_PATH, DATABASE_URL, DB_ENGINE, DB_PATH  # noqa: E402
from agricola_shared.audit_spool import DurableAuditSpool  # noqa: E402
from agricola_shared.db_compat import connect as connect_postgres_db  # noqa: E402
from agricola_shared.portal_auth import read_portal_session  # noqa: E402
from agricola_shared.report_security import allocate_report_path, neutralize_dataframe  # noqa: E402
from database import CorrectionPreviewConflict, DB, backup_sqlite_file  # noqa: E402

try:
    from colaboradores_reference import get_colaboradores_provider  # noqa: E402
except ModuleNotFoundError:
    get_colaboradores_provider = None


DEFAULT_PORT = int(os.environ.get("APP_NOTAS_WEB_PORT", "8891"))
AUDIT_URL = os.environ.get("AGRICOLA_AUDIT_URL", "http://127.0.0.1:8890/api/audit/event")
SESSION_COOKIE = os.environ.get("AGRICOLA_SESSION_COOKIE", "oa_demo_session")
LAUNCHER_AUTH_DB = Path(os.environ.get("LAUNCHER_AUTH_DB", APP_ROOT.parent / "launcher_web" / "launcher_auth.db"))
LAUNCHER_LOGIN_URL = os.environ.get("AGRICOLA_LOGIN_URL", "http://localhost:8890/login.html")
DB_INSTANCE: DB | None = None
DB_LOCK = threading.RLock()
SESSION_CACHE_TTL_SECONDS = 10
SESSION_CACHE: dict[str, tuple[float, dict | None]] = {}
SESSION_CACHE_LOCK = threading.Lock()
HEALTH_CACHE_TTL_SECONDS = float(os.environ.get("APP_NOTAS_HEALTH_CACHE_TTL_SECONDS", "5"))
HEALTH_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}
HEALTH_CACHE_LOCK = threading.Lock()
MAX_JSON_BODY_BYTES = int(os.environ.get("APP_NOTAS_MAX_JSON_BODY_BYTES", str(1024 * 1024)))
REPORT_RETENTION_SECONDS = float(os.environ.get("APP_NOTAS_REPORT_RETENTION_SECONDS", str(24 * 60 * 60)))
AUDIT_SPOOL = DurableAuditSpool(APP_ROOT / "logs" / "audit-spool")
SYNC_STALE_HOURS = float(os.environ.get("APP_NOTAS_SYNC_STALE_HOURS", "24"))
SYNC_LOG_DIR = APP_ROOT.parent / "logs" / "backend-sync"
HISTORICAL_MUTATION_ENV = "APP_NOTAS_ALLOW_HISTORICAL_NOTE_MUTATIONS"
SYNC_RECOMMENDED_COMMANDS = {
    "dryRun": r".\.venv\Scripts\python.exe sync_balanca_cadastros.py --source api --dry-run",
    "apply": r".\.venv\Scripts\python.exe sync_balanca_cadastros.py --source api",
}
COLABORADORES_RECOMMENDED_ACTIONS = [
    "Verificar app_colaboradores/app_config.json.",
    "Confirmar PostgreSQL e psql.exe disponiveis.",
    "Revisar APP_NOTAS_COLABORADORES_REFERENCIAS e APP_NOTAS_COLABORADORES_CONFIG_PATH.",
]


class RequestBodyTooLarge(Exception):
    pass

HISTORICO_HEADERS = [
    "numero",
    "motorista_cod",
    "motorista_nome",
    "caminhao",
    "operador_cod",
    "operador_nome",
    "colhedora",
    "faz_muda_cod",
    "faz_muda_nome",
    "talhao",
    "faz_plantio_cod",
    "faz_plantio_nome",
    "variedade_nome",
    "data_colheita",
    "data_plantio",
]

HISTORICO_FIELD_MAP = {
    "nota": ["numero"],
    "motorista": ["motorista_nome", "motorista_cod"],
    "operador": ["operador_nome", "operador_cod"],
    "origem": ["faz_muda_nome", "faz_muda_cod"],
    "destino": ["faz_plantio_nome", "faz_plantio_cod"],
    "variedade": ["variedade_nome"],
    "todos": HISTORICO_HEADERS,
}

REFERENCE_CONFIG = {
    "motoristas": {"id": "codigo", "required_name": "Motorista"},
    "fazendas": {"id": "codigo", "required_name": "Fazenda"},
    "talhoes": {"id": "codigo", "required_name": "Talhao"},
    "variedades": {"id": "id", "required_name": "Variedade"},
}

CADASTRO_TABLES = {"motoristas", "fazendas", "variedades"}
ACOES_CORRECAO = {
    "colheita_para_plantio",
    "definir_colheita",
    "definir_plantio",
    "definir_ambas",
}


def get_db() -> DB:
    global DB_INSTANCE
    with DB_LOCK:
        if DB_INSTANCE is not None and not DB_INSTANCE.is_connection_usable():
            DB_INSTANCE.close()
            DB_INSTANCE = None
        if DB_INSTANCE is None:
            DB_INSTANCE = DB()
        return DB_INSTANCE


def close_db() -> None:
    global DB_INSTANCE
    with DB_LOCK:
        if DB_INSTANCE is not None:
            DB_INSTANCE.close()
            DB_INSTANCE = None


def row_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def redact_database_url(value: str) -> str:
    if not value or "@" not in value:
        return value
    prefix, suffix = value.split("@", 1)
    if ":" not in prefix:
        return value
    user = prefix.split("://", 1)[-1].split(":", 1)[0]
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "postgres"
    return f"{scheme}://{user}:***@{suffix}"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "nao", "no", "off"}


def historical_note_mutations_allowed() -> bool:
    return env_flag(HISTORICAL_MUTATION_ENV, default=False)


def should_block_existing_note_mutation(existente, same_edit: bool, strategy: str) -> bool:
    if not existente:
        return False
    if strategy == "duplicate" and not same_edit:
        return False
    return not historical_note_mutations_allowed()


def historical_protection_response(action: str) -> dict:
    return {
        "ok": False,
        "code": "HISTORY_PROTECTED",
        "message": (
            f"{action} bloqueada: notas ja lancadas ficam preservadas como historico. "
            "Use duplicar ou a correcao segura quando aplicavel."
        ),
        "overrideEnv": HISTORICAL_MUTATION_ENV,
    }


def get_lan_ip() -> str:
    return "127.0.0.1"


def parse_date_param(params: dict[str, list[str]], name: str, fallback: str) -> str:
    value = (params.get(name, [fallback])[0] or fallback).strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return fallback


def parse_int_query(params: dict[str, list[str]], name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    value = (params.get(name, [str(default)])[0] or str(default)).strip()
    try:
        parsed = int(value)
    except ValueError:
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def paginate_items(items: list, limit: int, offset: int) -> list:
    if limit <= 0:
        return items[offset:]
    return items[offset : offset + limit]


def today_sql() -> str:
    return date.today().isoformat()


def send_portal_audit(headers, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
    cookie = headers.get("Cookie", "")
    payload = {
        "module": "notas",
        "eventType": event_type,
        "entityType": entity_type,
        "entityId": str(entity_id or ""),
        "summary": summary,
        "details": details or {},
    }
    try:
        AUDIT_SPOOL.enqueue(payload)
    except OSError:
        return
    if not cookie:
        return

    def deliver(item: dict) -> None:
        body = json.dumps(item, ensure_ascii=False).encode("utf-8")
        request = Request(
            AUDIT_URL,
            data=body,
            headers={"Content-Type": "application/json", "Cookie": cookie},
            method="POST",
        )
        with urlopen(request, timeout=1.5) as response:
            response.read(32)

    try:
        AUDIT_SPOOL.flush(deliver, max_items=5)
    except OSError:
        pass


def parse_cookies(header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in (header or "").split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def current_portal_user(headers) -> dict | None:
    cookie_header = headers.get("Cookie")
    token = parse_cookies(cookie_header).get(SESSION_COOKIE)
    if not token:
        return None
    now = time.time()
    with SESSION_CACHE_LOCK:
        cached = SESSION_CACHE.get(token)
        if cached and cached[0] > now:
            return dict(cached[1]) if cached[1] else None

    user = read_portal_session(cookie_header)
    if user:
        user.setdefault("status", "approved")
    with SESSION_CACHE_LOCK:
        if len(SESSION_CACHE) > 500:
            SESSION_CACHE.clear()
        SESSION_CACHE[token] = (time.time() + SESSION_CACHE_TTL_SECONDS, user)
    return user


def build_health_payload(include_operational_details: bool = False) -> dict:
    db_path = Path(DB_PATH)
    min_free_bytes = 500 * 1024 * 1024
    db_info = {
        "engine": "postgresql" if DB_ENGINE in {"postgres", "postgresql"} else "sqlite",
        "exists": True if DB_ENGINE in {"postgres", "postgresql"} else db_path.exists(),
        "quickCheck": "nao encontrado",
        "journalMode": "",
    }
    if include_operational_details:
        if DB_ENGINE in {"postgres", "postgresql"}:
            db_info["target"] = redact_database_url(DATABASE_URL)
        else:
            db_info["path"] = str(db_path)
            db_info["sizeBytes"] = db_path.stat().st_size if db_path.exists() else 0
            db_info["modifiedAt"] = int(db_path.stat().st_mtime) if db_path.exists() else None
    disk_info = {"freeBytes": 0, "minFreeBytes": min_free_bytes, "ok": False}

    try:
        usage = shutil.disk_usage(db_path.parent if db_path.parent.exists() else APP_ROOT)
        disk_info["freeBytes"] = usage.free
        disk_info["ok"] = usage.free >= min_free_bytes
    except OSError as exc:
        disk_info["message"] = str(exc)

    try:
        if DB_ENGINE in {"postgres", "postgresql"}:
            db = get_db()
            row = db._fetchone("SELECT COUNT(*) AS total FROM notas")
            db_info["journalMode"] = "postgresql"
            db_info["quickCheck"] = "ok"
            db_info["notas"] = int(row["total"] if row else 0)
            try:
                schema_row = db._fetchone("SELECT MAX(version) AS version FROM schema_migrations")
                db_info["schemaVersion"] = schema_row["version"] if schema_row else None
            except Exception:
                db_info["schemaVersion"] = None
        else:
            with sqlite3.connect(db_path, timeout=2) as conn:
                conn.execute("PRAGMA busy_timeout = 2000")
                db_info["journalMode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
                db_info["quickCheck"] = conn.execute("PRAGMA quick_check").fetchone()[0]
                db_info["notas"] = conn.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
    except Exception as exc:
        db_info["quickCheck"] = f"erro: {exc}"

    ok = bool(db_info["exists"] and str(db_info["quickCheck"]).lower() == "ok" and disk_info["ok"])
    warnings = []
    payload = {
        "ok": ok,
        "app": "Sistema de Notas",
        "status": "online" if ok else "alerta",
        "message": "Sistema de Notas online" if ok else "Sistema de Notas com alerta no health check",
        "checkedAt": datetime.now().isoformat(timespec="seconds"),
        "database": db_info,
        "disk": disk_info,
    }
    if not include_operational_details:
        return payload

    references = compact_sync_status(build_sync_status_payload(db_path=db_path))
    colaboradores = build_colaboradores_status_payload()
    if not references.get("ok"):
        warnings.extend(f"Referencias: {issue}" for issue in references.get("issues", []))
    if not colaboradores.get("ok"):
        warnings.extend(f"Colaboradores: {issue}" for issue in colaboradores.get("issues", []))
    if ok and warnings:
        payload["message"] = "Sistema de Notas online com alerta de referencias"
    payload["references"] = references
    payload["colaboradores"] = colaboradores
    payload["warnings"] = warnings
    return payload


def cached_health_payload() -> dict:
    now = time.time()
    with HEALTH_CACHE_LOCK:
        payload = HEALTH_CACHE.get("payload")
        if isinstance(payload, dict) and float(HEALTH_CACHE.get("expires_at", 0.0)) > now:
            return payload

    payload = build_health_payload()
    with HEALTH_CACHE_LOCK:
        HEALTH_CACHE["payload"] = payload
        HEALTH_CACHE["expires_at"] = time.time() + HEALTH_CACHE_TTL_SECONDS
    return payload


def parse_sync_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip().split(".")[0], fmt)
        except ValueError:
            continue
    return None


def latest_sync_log(log_dir: Path = SYNC_LOG_DIR) -> Path | None:
    try:
        files = sorted(log_dir.glob("sync-notas-balanca-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return files[0] if files else None


def build_sync_status_payload(db_path: str | Path = DB_PATH, log_dir: Path = SYNC_LOG_DIR) -> dict:
    path = Path(db_path)
    now = datetime.now()
    result = {
        "ok": False,
        "status": "alerta",
        "message": "Sincronizacao Balança -> Notas sem leitura.",
        "checkedAt": now.isoformat(timespec="seconds"),
        "staleAfterHours": SYNC_STALE_HOURS,
        "sync": None,
        "counts": {
            "fazendasBalanca": 0,
            "talhoesBalanca": 0,
        },
        "log": None,
        "issues": [],
        "recommendedCommands": SYNC_RECOMMENDED_COMMANDS,
    }

    log_path = latest_sync_log(log_dir)
    if log_path:
        try:
            result["log"] = {
                "path": str(log_path),
                "modifiedAt": datetime.fromtimestamp(log_path.stat().st_mtime).isoformat(timespec="seconds"),
                "sizeBytes": log_path.stat().st_size,
            }
        except OSError:
            result["log"] = {"path": str(log_path)}

    if DB_ENGINE not in {"postgres", "postgresql"} and not path.exists():
        result["issues"].append("Banco do App Notas nao encontrado.")
        return result

    try:
        if DB_ENGINE in {"postgres", "postgresql"}:
            db = get_db()
            fazendas_row = db._fetchone("SELECT COUNT(*) AS total FROM fazendas WHERE fonte_mestre = 'balanca'")
            talhoes_row = db._fetchone("SELECT COUNT(*) AS total FROM talhoes WHERE fonte = 'balanca'")
            sync = db._fetchone(
                """
                SELECT fonte, sincronizado_em, fazendas_lidas, fazendas_alteradas,
                       talhoes_lidos, talhoes_alterados, origem, detalhes
                FROM sincronizacoes_cadastros
                WHERE fonte = 'balanca'
                """
            )
            fazendas_balanca = int(fazendas_row["total"] if fazendas_row else 0)
            talhoes_balanca = int(talhoes_row["total"] if talhoes_row else 0)
        else:
            with sqlite3.connect(path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout = 2000")
                quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
                if str(quick_check).lower() != "ok":
                    result["issues"].append(f"SQLite quick_check: {quick_check}")

                fazendas_balanca = int(
                    conn.execute("SELECT COUNT(*) FROM fazendas WHERE fonte_mestre = 'balanca'").fetchone()[0] or 0
                )
                talhoes_balanca = int(
                    conn.execute("SELECT COUNT(*) FROM talhoes WHERE fonte = 'balanca'").fetchone()[0] or 0
                )
                sync = conn.execute(
                    """
                    SELECT fonte, sincronizado_em, fazendas_lidas, fazendas_alteradas,
                           talhoes_lidos, talhoes_alterados, origem, detalhes
                    FROM sincronizacoes_cadastros
                    WHERE fonte = 'balanca'
                    """
                ).fetchone()
    except Exception as exc:
        result["issues"].append(f"Erro ao consultar sincronizacao: {exc}")
        return result

    result["counts"] = {
        "fazendasBalanca": fazendas_balanca,
        "talhoesBalanca": talhoes_balanca,
    }

    if not sync:
        result["issues"].append("Nenhuma sincronizacao Balança -> Notas registrada.")
        return result

    details = {}
    try:
        details = json.loads(sync["detalhes"] or "{}")
    except json.JSONDecodeError:
        details = {"raw": sync["detalhes"]}

    synced_at = str(sync["sincronizado_em"] or "")
    synced_dt = parse_sync_datetime(synced_at)
    age_hours = None
    if synced_dt:
        age_hours = round((now - synced_dt).total_seconds() / 3600, 2)
        if age_hours > SYNC_STALE_HOURS:
            result["issues"].append(f"Ultima sincronizacao ha {age_hours} horas.")
    else:
        result["issues"].append("Data da ultima sincronizacao invalida.")

    if int(sync["fazendas_lidas"] or 0) != fazendas_balanca:
        result["issues"].append("Total de fazendas sincronizadas diverge do cadastro local.")
    if int(sync["talhoes_lidos"] or 0) != talhoes_balanca:
        result["issues"].append("Total de talhoes sincronizados diverge do cadastro local.")

    source = str(details.get("source") or ("api" if str(sync["origem"] or "").startswith("http") else "sqlite"))
    result["sync"] = {
        "source": source,
        "origin": sync["origem"],
        "syncedAt": synced_at,
        "ageHours": age_hours,
        "farmsRead": int(sync["fazendas_lidas"] or 0),
        "farmsChanged": int(sync["fazendas_alteradas"] or 0),
        "fieldsRead": int(sync["talhoes_lidos"] or 0),
        "fieldsSynced": int(details.get("talhoes_processados") or sync["talhoes_lidos"] or 0),
        "fieldsChanged": int(sync["talhoes_alterados"] or 0),
        "fieldsInserted": int(details.get("talhoes_inseridos") or 0),
        "fieldsUpdated": int(details.get("talhoes_atualizados") or 0),
        "fieldsRemoved": int(details.get("talhoes_removidos") or 0),
        "fieldsSkipped": int(details.get("talhoes_ignorados_sem_fazenda") or 0),
        "dryRun": bool(details.get("dry_run")),
    }

    result["ok"] = not result["issues"]
    result["status"] = "online" if result["ok"] else "alerta"
    if result["ok"]:
        result["message"] = f"Sincronizacao Balança -> Notas em dia via {source}."
    else:
        result["message"] = "Sincronizacao Balança -> Notas requer atencao."
    return result


def compact_sync_status(payload: dict) -> dict:
    sync = payload.get("sync") or {}
    return {
        "ok": bool(payload.get("ok")),
        "status": payload.get("status") or ("online" if payload.get("ok") else "alerta"),
        "message": payload.get("message") or "",
        "issues": list(payload.get("issues") or []),
        "source": sync.get("source"),
        "syncedAt": sync.get("syncedAt"),
        "ageHours": sync.get("ageHours"),
        "counts": payload.get("counts") or {},
        "log": payload.get("log"),
        "recommendedCommands": payload.get("recommendedCommands") or SYNC_RECOMMENDED_COMMANDS,
    }


def build_colaboradores_status_payload() -> dict:
    if get_colaboradores_provider is None:
        return {
            "ok": False,
            "status": "alerta",
            "source": "portal_colaboradores",
            "message": "Modulo de consulta ao Portal Colaboradores indisponivel.",
            "issues": ["Modulo colaboradores_reference.py nao foi carregado."],
            "recommendedActions": COLABORADORES_RECOMMENDED_ACTIONS,
        }

    try:
        provider = get_colaboradores_provider()
        payload = provider.status()
    except Exception as exc:
        payload = {
            "ok": False,
            "status": "alerta",
            "source": "portal_colaboradores",
            "message": "Falha ao diagnosticar Portal Colaboradores.",
            "issues": [str(exc)],
        }
    payload["recommendedActions"] = COLABORADORES_RECOMMENDED_ACTIONS
    return payload


def date_days_between(d_ini: str, d_fim: str) -> int:
    try:
        return (date.fromisoformat(d_fim) - date.fromisoformat(d_ini)).days + 1
    except ValueError:
        return 1


def first_note_date(db: DB) -> str:
    row = db._fetchone(
        """
        SELECT MIN(data_colheita) AS inicio
        FROM notas
        WHERE data_colheita IS NOT NULL
          AND TRIM(data_colheita) <> ''
        """
    )
    value = str(row["inicio"] or "") if row else ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return today_sql()


def resolve_reference(db: DB, tabela: str, value: str | None):
    value = (value or "").strip()
    if not value:
        return None
    config = REFERENCE_CONFIG[tabela]
    return db.resolver_referencia(tabela, value, col_id=config["id"])


def resolve_field(db: DB, value: str | None, farm_row=None):
    value = (value or "").strip()
    if not value:
        return None
    farm_code = farm_row["codigo"] if farm_row else None
    return db.buscar_talhao(value, fazenda_codigo=farm_code)


def format_reference(row, id_col: str) -> str:
    if row is None:
        return ""
    codigo = row[id_col]
    nome = row["nome"]
    return f"{codigo} - {nome}"


def row_value(row, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        if key in row.keys():
            return row[key]
    except (AttributeError, KeyError, IndexError):
        pass
    return default


def reference_source(kind: str, row) -> str:
    if row is None:
        return "nao_resolvido"
    if kind == "motoristas":
        return row_value(row, "fonte") or "cadastro_local_notas"
    if kind == "fazendas":
        return row_value(row, "fonte_mestre") or "cadastro_local_notas"
    if kind == "talhoes":
        return row_value(row, "fonte") or "digitado"
    if kind == "variedades":
        return "cadastro_local_notas"
    return "desconhecido"


def reference_audit_item(kind: str, row, id_col: str = "codigo") -> dict:
    if row is None:
        return {"fonte": "nao_resolvido"}

    item = {
        "fonte": reference_source(kind, row),
        "codigo": row_value(row, id_col),
        "nome": row_value(row, "nome"),
    }
    if kind == "fazendas":
        item["codigoMestre"] = row_value(row, "codigo_mestre")
    elif kind == "talhoes":
        item["fazendaCodigo"] = row_value(row, "fazenda_codigo")
        item["fazendaCodigoMestre"] = row_value(row, "fazenda_codigo_mestre")
        item["fazendaNome"] = row_value(row, "fazenda_nome")
    return {key: value for key, value in item.items() if value not in (None, "")}


def build_note_payload(db: DB, dados: dict) -> dict:
    numero_raw = str(dados.get("numero") or "").strip()
    if not numero_raw.isdigit():
        raise ValueError("Numero da nota obrigatorio.")

    motorista = resolve_reference(db, "motoristas", dados.get("motorista"))
    operador = resolve_reference(db, "motoristas", dados.get("operador"))
    fazenda_muda = resolve_reference(db, "fazendas", dados.get("faz_muda"))
    fazenda_plantio = resolve_reference(db, "fazendas", dados.get("faz_plantio"))
    variedade = resolve_reference(db, "variedades", dados.get("variedade"))
    talhao_raw = str(dados.get("talhao") or "").strip()
    talhao = resolve_field(db, talhao_raw, fazenda_muda or fazenda_plantio)

    missing = []
    if motorista is None:
        missing.append("motorista")
    if fazenda_plantio is None:
        missing.append("fazenda de plantio")
    if variedade is None:
        missing.append("variedade")
    if missing:
        raise ValueError("Confira os cadastros obrigatorios: " + ", ".join(missing) + ".")

    referencias_origem = {
        "motorista": reference_audit_item("motoristas", motorista),
        "operador": (
            reference_audit_item("motoristas", operador)
            if operador
            else {"fonte": "nao_informado"}
        ),
        "fazendaMuda": (
            reference_audit_item("fazendas", fazenda_muda)
            if fazenda_muda
            else {"fonte": "nao_informado"}
        ),
        "fazendaPlantio": reference_audit_item("fazendas", fazenda_plantio),
        "talhao": (
            reference_audit_item("talhoes", talhao)
            if talhao
            else {"fonte": "digitado_sem_referencia", "codigo": talhao_raw}
            if talhao_raw
            else {"fonte": "nao_informado"}
        ),
        "variedade": reference_audit_item("variedades", variedade, id_col="id"),
    }

    return {
        "numero": int(numero_raw),
        "motorista_cod": motorista["codigo"],
        "motorista_nome": motorista["nome"],
        "caminhao": str(dados.get("caminhao") or "").strip(),
        "operador_cod": operador["codigo"] if operador else None,
        "operador_nome": operador["nome"] if operador else None,
        "colhedora": str(dados.get("colhedora") or "").strip(),
        "faz_muda_cod": fazenda_muda["codigo"] if fazenda_muda else None,
        "faz_muda_nome": fazenda_muda["nome"] if fazenda_muda else None,
        "talhao": talhao["codigo"] if talhao else talhao_raw,
        "faz_plantio_cod": fazenda_plantio["codigo"],
        "faz_plantio_nome": fazenda_plantio["nome"],
        "variedade_id": variedade["id"],
        "variedade_nome": variedade["nome"],
        "data_colheita": str(dados.get("data_colheita") or today_sql()).strip(),
        "data_plantio": str(dados.get("data_plantio") or today_sql()).strip(),
        "_referencias_origem": referencias_origem,
    }


def public_note(row) -> dict | None:
    if not row:
        return None
    data = row_dict(row)
    data["motorista_label"] = DB._formatar_codigo_nome(data.get("motorista_cod"), data.get("motorista_nome"))
    data["operador_label"] = DB._formatar_codigo_nome(data.get("operador_cod"), data.get("operador_nome"))
    data["faz_muda_label"] = DB._formatar_codigo_nome(data.get("faz_muda_cod"), data.get("faz_muda_nome"))
    data["faz_plantio_label"] = DB._formatar_codigo_nome(data.get("faz_plantio_cod"), data.get("faz_plantio_nome"))
    data["variedade_label"] = DB._formatar_codigo_nome(data.get("variedade_id"), data.get("variedade_nome"))
    return data


def public_reference_audit_entries(db: DB, numero: str | int, limit: int = 20) -> list[dict]:
    return db.listar_referencias_auditoria(int(numero), limit=limit)


def backup_id_for_path(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return hashlib.sha256(str(resolved).casefold().encode("utf-8")).hexdigest()[:16]


def backup_public_item(file: Path, origem: str, include_path: bool = False) -> dict:
    stat = file.stat()
    item = {
        "id": backup_id_for_path(file),
        "origem": origem,
        "nome": file.name,
        "mtime": stat.st_mtime,
        "data": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        "size": stat.st_size,
    }
    if include_path:
        item["path"] = str(file)
    return item


def list_backups(include_path: bool = False) -> list[dict]:
    items: list[dict] = []
    folders = [("Local", APP_ROOT / "backups"), ("Drive", Path(BACKUP_DRIVE_PATH))]
    for origem, folder in folders:
        if not folder.exists():
            continue
        for pattern in ("*.db", "*.dump"):
            for file in folder.glob(pattern):
                try:
                    items.append(backup_public_item(file, origem, include_path=include_path))
                except OSError:
                    continue
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


def backup_path_allowed(raw_value: str) -> Path:
    token = str(raw_value or "").strip()
    if not token:
        raise ValueError("Backup nao informado.")
    for item in list_backups(include_path=True):
        path = Path(item["path"])
        if token == item["id"]:
            return path
    raise ValueError("Backup nao encontrado na lista de backups disponiveis.")


def unique_backup_path(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    sequence = 1
    while True:
        numbered = folder / f"{stem}_{sequence}{suffix}"
        if not numbered.exists():
            return numbered
        sequence += 1


def create_pre_restore_backup(db: DB) -> dict:
    backup_dir = APP_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = ".dump" if DB_ENGINE in {"postgres", "postgresql"} else ".db"
    rollback_path = unique_backup_path(backup_dir, f"pre_restore_{timestamp}{suffix}")
    rollback_path = db.create_backup(rollback_path)
    return backup_public_item(rollback_path, "Local")


def restore_backup_with_rollback(db: DB, backup_token: str) -> dict:
    source_path = backup_path_allowed(backup_token)
    rollback_item = create_pre_restore_backup(db)
    db.restore_from_backup(source_path)
    return {
        "ok": True,
        "message": "Backup restaurado com sucesso. Backup de seguranca criado antes da restauracao.",
        "restoredBackup": {
            "id": backup_id_for_path(source_path),
            "nome": source_path.name,
        },
        "rollbackBackup": rollback_item,
    }


def restore_confirmation_present(data: dict) -> bool:
    return data.get("confirmRestore") is True


def delete_confirmation_present(data: dict) -> bool:
    return data.get("confirmDelete") is True


def correction_confirmation_present(data: dict) -> bool:
    return data.get("confirmCorrection") is True


def create_manual_backup(db: DB) -> dict:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    local_dir = APP_ROOT / "backups"
    drive_dir = Path(BACKUP_DRIVE_PATH)
    local_dir.mkdir(parents=True, exist_ok=True)
    items = []

    suffix = ".dump" if DB_ENGINE in {"postgres", "postgresql"} else ".db"
    local_path = unique_backup_path(local_dir, f"transporte_web_{timestamp}{suffix}")
    local_path = db.create_backup(local_path)
    items.append(backup_public_item(local_path, "Local"))

    try:
        drive_dir.mkdir(parents=True, exist_ok=True)
        drive_path = unique_backup_path(drive_dir, f"transporte_web_{timestamp}{suffix}")
        drive_backup = db.create_backup(drive_path)
        db.create_backup(drive_dir / f"transporte_ATUAL{suffix}")
        items.append(backup_public_item(drive_backup, "Drive"))
    except Exception:
        return {
            "ok": True,
            "partial": True,
            "items": items,
            "message": "Backup local criado. Falha ao gravar backup no Drive configurado.",
        }

    return {"ok": True, "partial": False, "items": items, "message": "Backup criado com sucesso."}


def generated_path(filename: str, user: dict | None = None) -> Path:
    requested = Path(filename)
    return allocate_report_path(
        GENERATED_DIR,
        requested.stem,
        requested.suffix or ".bin",
        user=user,
        retention_seconds=REPORT_RETENTION_SECONDS,
    )


@contextmanager
def independent_report_connection():
    """Give each report request its own connection/transaction."""
    if DB_ENGINE in {"postgres", "postgresql"}:
        if not DATABASE_URL:
            raise RuntimeError("APP_NOTAS_DATABASE_URL nao configurada para PostgreSQL.")
        conn = connect_postgres_db(DATABASE_URL, row_factory=sqlite3.Row)
        is_postgres = True
    else:
        conn = sqlite3.connect(DB_PATH)
        is_postgres = False
    try:
        yield conn
    finally:
        if is_postgres:
            try:
                conn.rollback()
            except Exception:
                pass
        conn.close()


class AppNotasWebHandler(SimpleHTTPRequestHandler):
    server_version = "AppNotasWeb/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        try:
            message = "[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args)
            encoding = sys.stdout.encoding or "utf-8"
            safe_message = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
            sys.stdout.write(safe_message)
            sys.stdout.flush()
        except (OSError, UnicodeError):
            pass

    def end_headers(self) -> None:
        self.send_security_headers()
        super().end_headers()

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST, **extra) -> None:
        self.send_json({"ok": False, "message": message, **extra}, status)

    def audit(self, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
        send_portal_audit(self.headers, event_type, summary, entity_type, entity_id, details)

    def portal_user(self) -> dict | None:
        return current_portal_user(self.headers)

    def auth_required(self, path: str) -> bool:
        if path == "/api/health":
            return False
        return True

    def ensure_authenticated(self, path: str) -> bool:
        if not self.auth_required(path):
            return True
        if self.portal_user():
            return True
        if path.startswith("/api/"):
            self.send_error_json("Login necessario pelo Portal Agricola.", HTTPStatus.UNAUTHORIZED, loginUrl=LAUNCHER_LOGIN_URL)
            return False
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", LAUNCHER_LOGIN_URL)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def send_file_response(self, path: Path, filename: str, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_static_file(self, relative_path: str) -> None:
        target = (STATIC_DIR / relative_path.lstrip("/")).resolve()
        static_root = STATIC_DIR.resolve()
        if not str(target).startswith(str(static_root)) or not target.exists() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND, "Arquivo nao encontrado")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if target.suffix.lower() in {".html", ".css", ".js"} else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        if not self.ensure_authenticated(path):
            return
        try:
            if path == "/api/health":
                health = cached_health_payload()
                return self.send_json(health, HTTPStatus.OK if health.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE)
            if path == "/api/status":
                return self.handle_status()
            if path == "/api/sync/status":
                return self.handle_sync_status()
            if path == "/api/colaboradores/status":
                return self.handle_colaboradores_status()
            if path == "/api/references":
                return self.handle_references(params)
            if path == "/api/historico":
                return self.handle_historico(params)
            if path == "/api/dashboard":
                return self.handle_dashboard(params)
            if path.startswith("/api/notas/") and path.endswith("/referencias-auditoria"):
                _, _, rest = path.partition("/api/notas/")
                numero, _, _ = rest.partition("/")
                return self.handle_note_reference_audit(unquote(numero))
            if path.startswith("/api/notas/"):
                numero = path.rsplit("/", 1)[-1]
                return self.handle_get_nota(numero)
            if path.startswith("/api/cadastros/"):
                tabela = path.rsplit("/", 1)[-1]
                return self.handle_list_cadastro(tabela, params)
            if path == "/api/backups":
                return self.send_json({"ok": True, "items": list_backups()})
            if path == "/api/correcoes/logs":
                return self.handle_correction_logs()
            if path == "/api/relatorios/export":
                return self.handle_export(params)
            if path == "/api/relatorios/pdf":
                return self.handle_pdf(params)
            if path.startswith("/api/"):
                return self.send_error_json("Endpoint nao encontrado.", HTTPStatus.NOT_FOUND)
            if path in {"", "/"}:
                return self.send_static_file("index.html")
            return self.send_static_file(unquote(path))
        except Exception as exc:
            return self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not self.ensure_authenticated(path):
            return
        try:
            payload = self.read_json()
            if path == "/api/notas":
                return self.handle_save_nota(payload)
            if path.startswith("/api/cadastros/"):
                tabela = path.rsplit("/", 1)[-1]
                return self.handle_create_cadastro(tabela, payload)
            if path == "/api/backups/create":
                return self.handle_create_backup()
            if path == "/api/backups/restore":
                return self.handle_restore_backup(payload)
            if path == "/api/correcoes/preview":
                return self.handle_correction_preview(payload)
            if path == "/api/correcoes/apply":
                return self.handle_correction_apply(payload)
            return self.send_error_json("Endpoint nao encontrado.", HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError:
            return self.send_error_json("JSON invalido.")
        except RequestBodyTooLarge:
            return self.send_error_json("Requisicao muito grande.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except Exception as exc:
            return self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not self.ensure_authenticated(path):
            return
        try:
            payload = self.read_json()
            if path.startswith("/api/notas/"):
                numero = path.rsplit("/", 1)[-1]
                if not historical_note_mutations_allowed():
                    return self.send_json(
                        historical_protection_response("Exclusao direta de nota"),
                        HTTPStatus.FORBIDDEN,
                    )
                db = get_db()
                if not db.buscar_nota(numero):
                    return self.send_error_json("Nota nao encontrada.", HTTPStatus.NOT_FOUND)
                db.excluir_nota(numero)
                self.audit("nota.delete", f"Excluiu nota {numero}", entity_type="nota", entity_id=numero)
                return self.send_json({"ok": True, "message": "Nota excluida."})
            if path.startswith("/api/cadastros/"):
                _, _, rest = path.partition("/api/cadastros/")
                tabela, _, raw_id = rest.partition("/")
                return self.handle_delete_cadastro(tabela, unquote(raw_id), payload)
            return self.send_error_json("Endpoint nao encontrado.", HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError:
            return self.send_error_json("JSON invalido.")
        except RequestBodyTooLarge:
            return self.send_error_json("Requisicao muito grande.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except Exception as exc:
            return self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_status(self) -> None:
        db = get_db()
        hoje = today_sql()
        inicio = first_note_date(db)
        host = get_lan_ip()
        references = compact_sync_status(build_sync_status_payload())
        colaboradores = build_colaboradores_status_payload()
        self.send_json(
            {
                "ok": True,
                "app": "Sistema de Notas",
                "dbPath": str(DB_PATH),
                "server": {
                    "name": socket.gethostname(),
                    "networkUrl": f"http://{host}:{self.server.server_port}",
                    "port": self.server.server_port,
                },
                "metrics": {
                    "total": db.contar_notas_total(),
                    "hoje": db.contar_notas_data(hoje),
                },
                "defaultPeriod": {
                    "start": inicio,
                    "end": hoje,
                },
                "references": references,
                "colaboradores": colaboradores,
                "today": hoje,
            }
        )

    def handle_sync_status(self) -> None:
        payload = build_sync_status_payload()
        self.send_json(payload, HTTPStatus.OK if payload.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE)

    def handle_colaboradores_status(self) -> None:
        payload = build_colaboradores_status_payload()
        self.send_json(payload, HTTPStatus.OK if payload.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE)

    def handle_references(self, params: dict[str, list[str]]) -> None:
        tabela = (params.get("tabela", [""])[0] or "").strip()
        q = (params.get("q", [""])[0] or "").strip().lower()
        limit = parse_int_query(params, "limit", 25, minimum=1, maximum=100)
        if tabela not in REFERENCE_CONFIG:
            return self.send_error_json("Tabela de referencia invalida.")
        db = get_db()
        id_col = REFERENCE_CONFIG[tabela]["id"]
        if tabela == "motoristas":
            rows = db.listar_referencias_filtradas(tabela, q=q, limit=limit)
        elif tabela == "talhoes":
            fazenda_valor = (params.get("fazenda", [""])[0] or "").strip()
            fazenda = resolve_reference(db, "fazendas", fazenda_valor) if fazenda_valor else None
            fazenda_codigo = fazenda["codigo"] if fazenda else fazenda_valor
            rows = db.listar_talhoes_filtrados(fazenda_codigo=fazenda_codigo, q=q, limit=limit)
            items = []
            for row in rows:
                nome = row["nome"] or row["codigo"]
                label = DB._formatar_codigo_nome(row["codigo"], nome)
                items.append(
                    {
                        "id": row["codigo"],
                        "nome": nome,
                        "label": label,
                        "fazenda": row["fazenda_codigo"],
                        "fazendaNome": row["fazenda_nome"],
                    }
                )
            return self.send_json({"ok": True, "items": items})
        elif q:
            rows = db._fetchall(
                f"""
                SELECT {id_col}, nome
                FROM {tabela}
                WHERE CAST({id_col} AS TEXT) LIKE ?
                   OR UPPER(nome) LIKE UPPER(?)
                ORDER BY nome
                LIMIT ?
                """,
                (f"%{q}%", f"%{q}%", limit),
            )
        else:
            rows = db._fetchall(
                f"SELECT {id_col}, nome FROM {tabela} ORDER BY nome LIMIT ?",
                (limit,),
            )
        items = [
            {"id": row[id_col], "nome": row["nome"], "label": f"{row[id_col]} - {row['nome']}"}
            for row in rows
        ]
        self.send_json({"ok": True, "items": items})

    def handle_get_nota(self, numero: str) -> None:
        db = get_db()
        nota = public_note(db.buscar_nota(numero))
        if not nota:
            return self.send_error_json("Nota nao encontrada.", HTTPStatus.NOT_FOUND)
        self.send_json({"ok": True, "nota": nota})

    def handle_note_reference_audit(self, numero: str) -> None:
        numero_txt = str(numero or "").strip()
        if not numero_txt.isdigit():
            return self.send_error_json("Numero da nota invalido.", HTTPStatus.UNPROCESSABLE_ENTITY)

        db = get_db()
        if not db.buscar_nota(numero_txt):
            return self.send_error_json("Nota nao encontrada.", HTTPStatus.NOT_FOUND)

        items = public_reference_audit_entries(db, numero_txt)
        self.send_json(
            {
                "ok": True,
                "numero": int(numero_txt),
                "total": len(items),
                "items": items,
            }
        )

    def handle_save_nota(self, data: dict) -> None:
        db = get_db()
        try:
            payload = build_note_payload(db, data)
        except ValueError as exc:
            return self.send_error_json(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY)

        numero = int(payload["numero"])
        edit_original = data.get("edit_original")
        strategy = (data.get("strategy") or "").strip()
        existente = db.buscar_nota(numero)
        same_edit = edit_original and str(edit_original) == str(numero)

        if existente and not same_edit and strategy not in {"overwrite", "duplicate"}:
            return self.send_json(
                {
                    "ok": False,
                    "code": "DUPLICATE",
                    "message": f"Nota {numero} ja existe. Para preservar o historico, use duplicar.",
                    "existente": public_note(existente),
                    "numeroDuplicado": db.gerar_numero_duplicado(numero),
                },
                HTTPStatus.CONFLICT,
            )

        if should_block_existing_note_mutation(existente, same_edit=bool(same_edit), strategy=strategy):
            return self.send_json(
                historical_protection_response("Alteracao direta de nota existente"),
                HTTPStatus.FORBIDDEN,
            )

        try:
            if existente and not same_edit and strategy == "duplicate":
                payload["numero"] = db.gerar_numero_duplicado(numero)
                payload["duplicado"] = 1
                event_type = "nota.duplicate"
                payload["_audit_event"] = event_type
                db.inserir_nota(payload)
                saved = payload["numero"]
            elif existente:
                event_type = "nota.update"
                payload["_audit_event"] = event_type
                db.inserir_nota(payload, force=True)
                saved = numero
            else:
                event_type = "nota.create"
                payload["_audit_event"] = event_type
                db.inserir_nota(payload)
                saved = numero
        except Exception as exc:
            return self.send_error_json(f"Nao foi possivel salvar a nota: {exc}")

        self.audit(
            event_type,
            f"Salvou nota {saved}",
            entity_type="nota",
            entity_id=saved,
            details={
                "motorista": payload.get("motorista_nome"),
                "caminhao": payload.get("caminhao"),
                "operador": payload.get("operador_nome"),
                "colhedora": payload.get("colhedora"),
                "fazendaMuda": payload.get("faz_muda_nome"),
                "fazendaPlantio": payload.get("faz_plantio_nome"),
                "talhao": payload.get("talhao"),
                "dataColheita": payload.get("data_colheita"),
                "dataPlantio": payload.get("data_plantio"),
                "referenciasOrigem": payload.get("_referencias_origem"),
            },
        )
        self.send_json({"ok": True, "message": f"Nota {saved} salva com sucesso.", "numero": saved})

    def handle_historico(self, params: dict[str, list[str]]) -> None:
        db = get_db()
        start = params.get("start", [""])[0] or None
        end = params.get("end", [""])[0] or None
        q = (params.get("q", [""])[0] or "").strip()
        field = (params.get("field", ["todos"])[0] or "todos").strip()
        limit = parse_int_query(params, "limit", 1000, minimum=1, maximum=5000)
        offset = parse_int_query(params, "offset", 0, minimum=0)
        use_period = bool(start and end)

        if field == "nota" and q:
            rows = db.buscar_notas_historico(start if use_period else None, end if use_period else None, numero_prefixo=q)
        else:
            rows = db.buscar_notas_historico(start if use_period else None, end if use_period else None)
            if q:
                columns = HISTORICO_FIELD_MAP.get(field, HISTORICO_HEADERS)
                q_lc = q.lower()
                rows = [
                    row
                    for row in rows
                    if any(q_lc in str(row[col] or "").lower() for col in columns)
                ]

        total = len(rows)
        items = [row_dict(row) for row in paginate_items(rows, limit, offset)]
        self.send_json({"ok": True, "items": items, "total": total, "limit": limit, "offset": offset})

    def handle_dashboard(self, params: dict[str, list[str]]) -> None:
        db = get_db()
        d_fim = parse_date_param(params, "end", today_sql())
        d_ini = parse_date_param(params, "start", first_note_date(db))
        days = max(1, date_days_between(d_ini, d_fim))
        total = db.contar_notas_periodo(d_ini, d_fim)
        rankings = {}
        for key, coluna in {
            "motoristas": "motorista_nome",
            "operadores": "operador_nome",
            "colhedoras": "colhedora",
            "variedades": "variedade_nome",
            "origens": "faz_muda_nome",
            "destinos": "faz_plantio_nome",
        }.items():
            rankings[key] = [
                {"nome": str(row["nome"] or "-"), "qtd": int(row["qtd"] or 0)}
                for row in db.top_por_coluna(coluna, d_ini, d_fim, limit=5)
            ]
        self.send_json(
            {
                "ok": True,
                "periodo": {"start": d_ini, "end": d_fim},
                "metrics": {
                    "total": total,
                    "media": round(total / days, 1),
                    "diasAtivos": db.contar_dias_ativos_periodo(d_ini, d_fim),
                },
                "rankings": rankings,
            }
        )

    def handle_list_cadastro(self, tabela: str, params: dict[str, list[str]]) -> None:
        if tabela not in CADASTRO_TABLES:
            return self.send_error_json("Cadastro invalido.")
        q = (params.get("q", [""])[0] or "").strip().lower()
        db = get_db()
        id_col = REFERENCE_CONFIG[tabela]["id"]
        if q:
            rows = db._fetchall(
                f"""
                SELECT {id_col}, nome
                FROM {tabela}
                WHERE CAST({id_col} AS TEXT) LIKE ?
                   OR UPPER(nome) LIKE UPPER(?)
                ORDER BY nome
                LIMIT 500
                """,
                (f"%{q}%", f"%{q}%"),
            )
        else:
            rows = db._fetchall(
                f"SELECT {id_col}, nome FROM {tabela} ORDER BY nome LIMIT 500",
            )
        items = [
            {"id": row[id_col], "nome": row["nome"], "label": f"{row[id_col]} - {row['nome']}"}
            for row in rows
        ]
        self.send_json({"ok": True, "items": items})

    def handle_create_cadastro(self, tabela: str, data: dict) -> None:
        if tabela not in CADASTRO_TABLES:
            return self.send_error_json("Cadastro invalido.")
        db = get_db()
        nome = str(data.get("nome") or "").strip()
        codigo = str(data.get("codigo") or "").strip()
        if tabela in {"motoristas", "fazendas"} and (not codigo or not nome):
            return self.send_error_json("Informe codigo e nome.")
        if tabela == "variedades" and not nome:
            return self.send_error_json("Informe o nome da variedade.")
        if tabela == "motoristas":
            db.adicionar_motorista(codigo, nome)
        elif tabela == "fazendas":
            db.adicionar_fazenda(codigo, nome)
        else:
            db.adicionar_variedade(nome)
        self.audit(
            "cadastro.create",
            f"Criou cadastro em {tabela}: {nome}",
            entity_type=tabela,
            entity_id=codigo or nome,
            details={"codigo": codigo, "nome": nome},
        )
        self.send_json({"ok": True, "message": "Cadastro salvo."})

    def handle_delete_cadastro(self, tabela: str, raw_id: str, data: dict) -> None:
        if tabela not in CADASTRO_TABLES:
            return self.send_error_json("Cadastro invalido.")
        if not raw_id:
            return self.send_error_json("ID invalido.")
        if not delete_confirmation_present(data):
            return self.send_error_json(
                "Confirmacao explicita obrigatoria para excluir cadastro.",
                HTTPStatus.PRECONDITION_REQUIRED,
                code="CADASTRO_DELETE_CONFIRMATION_REQUIRED",
            )
        db = get_db()
        db.excluir_cadastro(tabela, raw_id)
        self.audit("cadastro.delete", f"Excluiu cadastro em {tabela}", entity_type=tabela, entity_id=raw_id)
        self.send_json({"ok": True, "message": "Cadastro excluido."})

    def handle_create_backup(self) -> None:
        result = create_manual_backup(get_db())
        if result.get("ok", True):
            created_items = result.get("items") or []
            entity_id = created_items[0].get("nome") if created_items else ""
            self.audit("backup.create", "Criou backup do Sistema de Notas", entity_type="backup", entity_id=entity_id)
        self.send_json(result)

    def handle_restore_backup(self, data: dict) -> None:
        if not restore_confirmation_present(data):
            return self.send_error_json(
                "Confirmacao explicita obrigatoria para restaurar backup.",
                HTTPStatus.PRECONDITION_REQUIRED,
                code="RESTORE_CONFIRMATION_REQUIRED",
            )
        result = restore_backup_with_rollback(
            get_db(),
            str(data.get("backupId") or data.get("id") or ""),
        )
        restored = result.get("restoredBackup") or {}
        rollback = result.get("rollbackBackup") or {}
        self.audit(
            "backup.restore",
            "Restaurou backup do Sistema de Notas",
            entity_type="backup",
            entity_id=str(restored.get("nome") or ""),
            details={
                "backupId": restored.get("id"),
                "rollbackBackupId": rollback.get("id"),
                "rollbackBackup": rollback.get("nome"),
            },
        )
        self.send_json(result)

    def parse_correction_payload(self, data: dict) -> tuple[list[int], str, str | None, str]:
        numeros = sorted({int(item) for item in data.get("numeros", []) if str(item).strip().isdigit()})
        acao = str(data.get("acao") or "")
        nova_data = data.get("nova_data")
        motivo = str(data.get("motivo") or "").strip()
        if not numeros:
            raise ValueError("Informe ao menos uma nota.")
        if acao not in ACOES_CORRECAO:
            raise ValueError("Acao de correcao invalida.")
        if acao == "colheita_para_plantio":
            nova_data = None
        return numeros, acao, nova_data, motivo

    def handle_correction_preview(self, data: dict) -> None:
        numeros, acao, nova_data, _motivo = self.parse_correction_payload(data)
        result = get_db().preview_correcao_notas(numeros, acao, nova_data)
        result["previewToken"] = result.pop("preview_token")
        self.send_json({"ok": True, **result})

    def handle_correction_apply(self, data: dict) -> None:
        if not correction_confirmation_present(data):
            return self.send_error_json(
                "Confirmacao explicita obrigatoria para aplicar correcao.",
                HTTPStatus.PRECONDITION_REQUIRED,
                code="CORRECTION_CONFIRMATION_REQUIRED",
            )
        numeros, acao, nova_data, motivo = self.parse_correction_payload(data)
        preview_token = str(data.get("previewToken") or "").strip()
        if not preview_token:
            return self.send_error_json(
                "Gere e revise uma prévia antes de aplicar a correção.",
                HTTPStatus.PRECONDITION_REQUIRED,
                code="CORRECTION_PREVIEW_REQUIRED",
            )
        try:
            result = get_db().aplicar_correcao_notas(
                numeros,
                acao,
                nova_data=nova_data,
                motivo=motivo,
                expected_preview_token=preview_token,
            )
        except CorrectionPreviewConflict as exc:
            return self.send_error_json(
                str(exc), HTTPStatus.CONFLICT, code="CORRECTION_PREVIEW_STALE"
            )
        self.audit(
            "nota.bulk_correction",
            f"Aplicou correcao em {len(numeros)} nota(s)",
            entity_type="nota",
            entity_id=",".join(str(numero) for numero in numeros[:20]),
            details={"acao": acao, "novaData": nova_data, "motivo": motivo, "resultado": result},
        )
        self.send_json({"ok": True, "message": "Correcao aplicada.", "resultado": result})

    def handle_correction_logs(self) -> None:
        items = [row_dict(row) for row in get_db().listar_logs_correcao(limit=50)]
        self.send_json({"ok": True, "items": items})

    def get_period_params(self, params: dict[str, list[str]]) -> tuple[str, str]:
        d_fim = parse_date_param(params, "end", today_sql())
        d_ini = parse_date_param(params, "start", first_note_date(get_db()))
        return d_ini, d_fim

    def handle_export(self, params: dict[str, list[str]]) -> None:
        tipo = (params.get("type", ["bruto"])[0] or "bruto").strip()
        d_ini, d_fim = self.get_period_params(params)
        db = get_db()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if tipo == "fluxo":
            df = db.dataframe_fluxo(d_ini, d_fim)
            filename = f"Fluxo_{d_ini}_a_{d_fim}_{timestamp}.xlsx"
        else:
            df = db.dataframe_historico(d_ini, d_fim)
            filename = f"Dados_Brutos_{d_ini}_a_{d_fim}_{timestamp}.xlsx"
        if df.empty:
            return self.send_error_json("Sem dados no periodo.", HTTPStatus.NOT_FOUND)
        path = generated_path(filename, self.portal_user())
        neutralize_dataframe(df).to_excel(path, index=False)
        self.send_file_response(path, path.name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def handle_pdf(self, params: dict[str, list[str]]) -> None:
        from reporting import (
            RelatorioDataService,
            RelatorioPdfDiarioBuilder,
            RelatorioPdfFazendasMudaBuilder,
            RelatorioPdfFechamentoBuilder,
            RelatorioPdfGeralBuilder,
            RelatorioPdfPlantioDetalhadoBuilder,
            RelatorioPdfSimplificadoBuilder,
        )

        tipo = (params.get("type", ["diario"])[0] or "diario").strip()
        d_ini, d_fim = self.get_period_params(params)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with independent_report_connection() as conn:
            service = RelatorioDataService(conn)
            if tipo == "geral":
                dados = service.coletar_dados_pdf_geral(d_ini, d_fim)
                builder = RelatorioPdfGeralBuilder()
                pdf = builder.criar_pdf_geral_fazenda(d_ini, d_fim, dados) if dados else None
                filename = f"Relatorio_Fluxo_{d_ini}_a_{d_fim}_{timestamp}.pdf"
            elif tipo == "mudas":
                dados = service.coletar_dados_pdf_fazendas_muda(d_ini, d_fim)
                builder = RelatorioPdfFazendasMudaBuilder()
                pdf = builder.criar_pdf_fazendas_muda(d_ini, d_fim, dados) if dados else None
                filename = f"Historico_Fazendas_Muda_{d_ini}_a_{d_fim}_{timestamp}.pdf"
            elif tipo == "simples":
                dados = service.coletar_dados_pdf_simplificado(d_ini, d_fim)
                builder = RelatorioPdfSimplificadoBuilder()
                pdf = builder.criar_pdf_simplificado(d_ini, d_fim, dados) if dados else None
                filename = f"Relatorio_Simplificado_{d_ini}_a_{d_fim}_{timestamp}.pdf"
            elif tipo == "plantio_detalhado":
                dados = service.coletar_dados_pdf_plantio_detalhado(d_ini, d_fim)
                builder = RelatorioPdfPlantioDetalhadoBuilder()
                pdf = builder.criar_pdf_plantio_detalhado(d_ini, d_fim, dados) if dados else None
                filename = f"Relatorio_Plantio_Detalhado_{d_ini}_a_{d_fim}_{timestamp}.pdf"
            elif tipo == "fechamento":
                ano = date.fromisoformat(d_fim).year
                dados = service.coletar_dados_pdf_fechamento_safra(f"{ano}-01-01", f"{ano}-12-31")
                builder = RelatorioPdfFechamentoBuilder()
                pdf = builder.criar_pdf_fechamento_safra(f"{ano}-01-01", f"{ano}-12-31", dados) if dados else None
                filename = f"Relatorio_Final_Safra_{ano}_{timestamp}.pdf"
            else:
                dados = service.coletar_dados_pdf_diario(d_ini, d_fim)
                builder = RelatorioPdfDiarioBuilder()
                pdf = builder.criar_pdf_resumo_diario(dados) if dados else None
                filename = f"Resumo_Diario_{d_ini}_a_{d_fim}_{timestamp}.pdf"
        if pdf is None:
            return self.send_error_json("Sem dados no periodo.", HTTPStatus.NOT_FOUND)
        path = generated_path(filename, self.portal_user())
        pdf.output(str(path))
        self.send_file_response(path, path.name, "application/pdf")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sistema de Notas Web")
    parser.add_argument("--host", default=os.environ.get("APP_NOTAS_HOST", os.environ.get("APP_BIND_HOST", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


class FastThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    server = FastThreadingHTTPServer((args.host, args.port), AppNotasWebHandler)
    lan = get_lan_ip()
    print("Sistema de Notas Web iniciado.")
    print(f"Local: http://localhost:{args.port}")
    print(f"Rede:  http://{lan}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        close_db()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
