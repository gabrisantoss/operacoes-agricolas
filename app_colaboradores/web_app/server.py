from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import webbrowser
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
ROOT_DIR = PROJECT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agricola_shared.portal_auth import (
    evaluate_portal_access,
    read_portal_session,
    resolve_path_within_root,
)
from agricola_shared.audit_spool import DurableAuditSpool
from agricola_shared.report_security import allocate_report_path

STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated"
AUDIT_URL = os.environ.get("AGRICOLA_AUDIT_URL", "http://127.0.0.1:8890/api/audit/event")
LAUNCHER_AUTH_DB = Path(os.environ.get("AGRICOLA_LAUNCHER_AUTH_DB", ROOT_DIR / "launcher_web" / "launcher_auth.db"))
SESSION_COOKIE = os.environ.get("AGRICOLA_SESSION_COOKIE", "oa_demo_session")
MAINTENANCE_MODE = os.environ.get("COLABORADORES_MAINTENANCE_MODE", "1").strip().lower() not in {"0", "false", "no", "off"}
LAUNCHER_LOGIN_URL = os.environ.get("AGRICOLA_LOGIN_URL", "http://localhost:8890/login.html")
REPORT_RETENTION_SECONDS = float(os.environ.get("COLABORADORES_REPORT_RETENTION_SECONDS", str(7 * 24 * 60 * 60)))
SESSION_CACHE_TTL_SECONDS = 10
SESSION_CACHE: dict[str, tuple[float, dict | None]] = {}
SESSION_CACHE_LOCK = threading.Lock()
HEALTH_CACHE_TTL_SECONDS = float(os.environ.get("COLABORADORES_HEALTH_CACHE_TTL_SECONDS", "5"))
HEALTH_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}
HEALTH_CACHE_LOCK = threading.Lock()
MAX_JSON_BODY_BYTES = int(os.environ.get("COLABORADORES_MAX_JSON_BODY_BYTES", str(1024 * 1024)))
MAX_MULTIPART_BODY_BYTES = int(os.environ.get("COLABORADORES_MAX_MULTIPART_BODY_BYTES", str(25 * 1024 * 1024)))
AUDIT_SPOOL = DurableAuditSpool(PROJECT_DIR / "logs" / "audit-spool")


class RequestBodyTooLarge(Exception):
    pass

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app_config import DB_PATH, STORAGE_ROOT, get_runtime_config  # noqa: E402
from db import DatabaseError, get_db_connection  # noqa: E402
from funcoes_colaboradores import (  # noqa: E402
    adicionar_advertencia,
    adicionar_atestado,
    adicionar_colaborador,
    adicionar_documento,
    atualizar_colaborador,
    atualizar_escala_por_nome,
    excluir_advertencia,
    excluir_atestado,
    excluir_colaborador,
    excluir_documento,
    garantir_schema_banco,
    get_dashboard_summary,
    get_documentos_a_vencer,
    get_summary_by_cidade,
    listar_advertencias_por_colaborador,
    listar_atestados_por_colaborador,
    listar_documentos_por_colaborador,
    obter_colaborador_por_codigo,
    obter_colaboradores,
    obter_valores_unicos_coluna,
    registrar_acompanhamento_cnh,
    registrar_renovacao_cnh,
)
from core.cnh_management import (  # noqa: E402
    ACOMPANHAMENTO_LABELS,
    ACOMPANHAMENTO_ORDER,
    STATUS_TECNICO_LABELS,
    STATUS_TECNICO_ORDER,
    exportar_lista_cobranca_excel,
    exportar_painel_cnh_excel,
    gerar_pdf_cnh_vencidas_por_frente,
    gerar_resumo_cnh,
    listar_acompanhamentos_cnh,
    listar_historico_cnh,
    listar_opcoes_painel_cnh,
    listar_painel_cnh,
)
COLABORADOR_FIELDS = {
    "codigo_colaborador",
    "nome",
    "codigo_interno",
    "situacao",
    "modalidade",
    "apelido",
    "telefone",
    "cidade",
    "validade_cnh",
    "categoria_cnh",
    "observacao_1",
    "frente_safra",
    "funcao_safra",
    "turno_safra",
    "cetpp",
    "restricoes",
    "observacao_2",
    "observacao_3",
    "observacao_4",
    "observacao_5",
    "arcos",
    "cetcp",
    "caminho_cnh_pdf",
    "horario",
    "municipio",
    "rg",
    "local_trabalho",
    "funcao",
    "data_admissao",
    "salario",
    "registro_cnh",
    "primeira_cnh",
    "cpf",
    "nascimento",
    "gestor_responsavel",
    "status_cnh_acompanhamento",
    "ultima_acao_cnh",
    "ultimo_contato_cnh",
    "responsavel_ultimo_contato_cnh",
    "data_prevista_regularizacao_cnh",
    "observacao_cnh",
    "caminho_comprovante_cnh",
}


def fix_text(value):
    if isinstance(value, str) and ("Ã" in value or "Â" in value):
        try:
            return value.encode("latin1").decode("utf-8")
        except UnicodeError:
            return value
    if isinstance(value, list):
        return [fix_text(item) for item in value]
    if isinstance(value, tuple):
        return [fix_text(item) for item in value]
    if isinstance(value, dict):
        return {key: fix_text(item) for key, item in value.items()}
    return value


def bool_from_query(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "sim", "yes", "on"}


def send_portal_audit(headers, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
    cookie = headers.get("Cookie", "")
    payload = {
        "module": "colaboradores",
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


def is_admin_session(headers) -> bool:
    user = current_portal_user(headers)
    return bool(user and user.get("role") == "admin")


def clean_payload(payload: dict) -> dict:
    data = {}
    for key in COLABORADOR_FIELDS:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value == "":
            value = None
        if key == "salario" and value not in (None, ""):
            try:
                value = float(str(value).replace(",", "."))
            except ValueError:
                value = None
        data[key] = value
    return data


def limited(items: list, limit: int) -> list:
    if limit <= 0:
        return items
    return items[:limit]


def parse_int_query(params: dict[str, list[str]], key: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    value = get_query_value(params, key, str(default)).strip()
    try:
        parsed = int(value or default)
    except ValueError:
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def pagination_payload(items: list, params: dict[str, list[str]], default_limit: int = 500, max_limit: int = 5000) -> dict:
    limit = parse_int_query(params, "limit", default_limit, minimum=1, maximum=max_limit)
    offset = parse_int_query(params, "offset", 0, minimum=0)
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "data": items[offset : offset + limit],
    }


def build_health_payload(deep_check: bool = False) -> dict:
    runtime = get_runtime_config()
    db_engine = str(runtime.get("db_engine") or "").lower()
    min_free_bytes = 500 * 1024 * 1024
    disk_root = Path(STORAGE_ROOT)
    disk_info = {"freeBytes": 0, "minFreeBytes": min_free_bytes, "ok": False}

    try:
        usage = shutil.disk_usage(disk_root if disk_root.exists() else PROJECT_DIR)
        disk_info["freeBytes"] = usage.free
        disk_info["ok"] = usage.free >= min_free_bytes
    except OSError as exc:
        disk_info["message"] = str(exc)

    if db_engine == "postgresql":
        db_info = {
            "engine": "postgresql",
            "target": runtime.get("db_target"),
            "exists": False,
            "quickCheck": "nao conectado",
            "mode": "deep" if deep_check else "fast",
            "journalMode": "postgresql",
        }
        try:
            with get_db_connection() as conn:
                db_info["colaboradores"] = conn.execute("SELECT COUNT(*) FROM colaboradores").fetchone()[0]
                try:
                    db_info["schemaVersion"] = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                except Exception:
                    db_info["schemaVersion"] = None
            db_info["exists"] = True
            db_info["quickCheck"] = "ok"
        except Exception as exc:
            db_info["quickCheck"] = f"erro: {exc}"
    else:
        db_path = Path(str(DB_PATH))
        db_info = {
            "engine": "sqlite",
            "path": str(db_path),
            "exists": db_path.exists(),
            "sizeBytes": db_path.stat().st_size if db_path.exists() else 0,
            "modifiedAt": int(db_path.stat().st_mtime) if db_path.exists() else None,
            "quickCheck": "nao encontrado",
            "mode": "deep" if deep_check else "fast",
            "journalMode": "",
        }
        try:
            with sqlite3.connect(db_path, timeout=2) as conn:
                conn.execute("PRAGMA busy_timeout = 2000")
                db_info["journalMode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
                db_info["colaboradores"] = conn.execute("SELECT COUNT(*) FROM colaboradores").fetchone()[0]
                db_info["quickCheck"] = conn.execute("PRAGMA quick_check").fetchone()[0] if deep_check else "ok"
        except Exception as exc:
            db_info["quickCheck"] = f"erro: {exc}"

    ok = bool(db_info["exists"] and str(db_info["quickCheck"]).lower() == "ok" and disk_info["ok"])
    return {
        "ok": ok,
        "app": "Gestor de Colaboradores",
        "status": "online" if ok else "alerta",
        "message": "Gestor de Colaboradores online" if ok else "Gestor de Colaboradores com alerta no health check",
        "checkedAt": datetime.now().isoformat(timespec="seconds"),
        "database": db_info,
        "disk": disk_info,
    }


def cached_health_payload(deep_check: bool = False) -> dict:
    if deep_check:
        return build_health_payload(deep_check=True)

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


def get_query_value(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[0] if values else default


def list_auditoria(params: dict[str, list[str]]) -> list[dict]:
    tipo_acao = get_query_value(params, "tipo_acao")
    entidade = get_query_value(params, "entidade")
    id_entidade = get_query_value(params, "id")
    data_inicio = get_query_value(params, "inicio")
    data_fim = get_query_value(params, "fim")
    try:
        limit = int(get_query_value(params, "limit", "200"))
    except ValueError:
        limit = 200

    query = "SELECT * FROM log_auditoria WHERE 1=1"
    args: list[str] = []
    if tipo_acao:
        query += " AND tipo_acao = ?"
        args.append(tipo_acao)
    if entidade:
        query += " AND entidade_afetada = ?"
        args.append(entidade)
    if id_entidade:
        query += " AND id_entidade LIKE ?"
        args.append(f"%{id_entidade}%")
    if data_inicio:
        query += " AND data_hora >= ?"
        args.append(data_inicio)
    if data_fim:
        query += " AND data_hora <= ?"
        args.append(data_fim)
    query += " ORDER BY data_hora DESC LIMIT ?"
    args.append(limit)

    with get_db_connection(dict_rows=True) as conn:
        cursor = conn.cursor()
        cursor.execute(query, args)
        return [dict(row) for row in cursor.fetchall()]


def _numero_frente(frente: str) -> int:
    match = re.search(r"\d+", str(frente or ""))
    return int(match.group(0)) if match else 999


def _numero_frota(frota: str) -> tuple[int, str]:
    match = re.search(r"\d+", str(frota or ""))
    return (int(match.group(0)) if match else 999999, str(frota or ""))


def escala_payload() -> dict:
    with get_db_connection(dict_rows=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                codigo_colaborador,
                nome,
                situacao,
                telefone,
                COALESCE(NULLIF(frente_safra, ''), 'SEM ESCALA') AS frente_safra,
                turno_safra,
                COALESCE(NULLIF(funcao_safra, ''), NULLIF(funcao, '')) AS funcao_exibicao,
                funcao_safra,
                funcao,
                horario,
                cidade,
                municipio
            FROM colaboradores
            WHERE COALESCE(oculto_operacao, 0) = 0
            ORDER BY frente_safra, funcao_safra, turno_safra, nome
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]

    grupos: dict[str, list[dict]] = {}
    fora_escala = 0
    for row in rows:
        frente = row.get("frente_safra") or "SEM ESCALA"
        if str(frente).strip().upper() == "SEM ESCALA":
            fora_escala += 1
            continue
        grupos.setdefault(frente, []).append(row)

    grupos_payload = []
    for frente, items in sorted(grupos.items(), key=lambda item: _numero_frente(item[0])):
        turnos = Counter(item.get("turno_safra") or "Sem turno" for item in items)
        horarios_por_turno: dict[str, set[str]] = {}
        frotas: dict[str, list[dict]] = {}
        for item in sorted(
            items,
            key=lambda row: (_numero_frota(row.get("funcao_exibicao")), row.get("turno_safra") or "", row.get("nome") or ""),
        ):
            frota = item.get("funcao_exibicao") or "Sem frota"
            frotas.setdefault(frota, []).append(item)
            turno = item.get("turno_safra") or "Sem turno"
            horario = str(item.get("horario") or "").strip()
            if horario:
                horarios_por_turno.setdefault(turno, set()).add(horario)
        grupos_payload.append(
            {
                "frente": frente,
                "total": len(items),
                "turnos": dict(turnos),
                "horariosPorTurno": {
                    turno: " / ".join(sorted(horarios))
                    for turno, horarios in sorted(horarios_por_turno.items())
                },
                "frotas": [
                    {"frota": frota, "total": len(colaboradores), "colaboradores": colaboradores}
                    for frota, colaboradores in sorted(frotas.items(), key=lambda item: _numero_frota(item[0]))
                ],
            }
        )

    return {
        "total": sum(group["total"] for group in grupos_payload),
        "resumo": {
            "frentes": len(grupos_payload),
            "foraEscala": fora_escala,
            "turnos": dict(Counter((row.get("turno_safra") or "Sem turno") for items in grupos.values() for row in items)),
        },
        "grupos": grupos_payload,
    }


def opcoes_payload() -> dict:
    cnh_options = listar_opcoes_painel_cnh(DB_PATH)
    funcoes = sorted(
        {
            str(item).strip()
            for item in (
                obter_valores_unicos_coluna("funcao") + obter_valores_unicos_coluna("funcao_safra")
            )
            if str(item).strip()
        }
    )
    cidades = sorted(
        {
            str(item).strip()
            for item in obter_valores_unicos_coluna("cidade")
            if str(item).strip()
        }
    )
    return {
        "situacoes": obter_valores_unicos_coluna("situacao"),
        "funcoes": funcoes,
        "turnos": obter_valores_unicos_coluna("turno_safra"),
        "cidades": cidades,
        "frentes": cnh_options.get("frentes", []),
        "gestores": cnh_options.get("gestores", []),
        "statusTecnico": [
            {"value": key, "label": STATUS_TECNICO_LABELS.get(key, key)}
            for key in STATUS_TECNICO_ORDER
        ],
        "statusAcompanhamento": [
            {"value": key, "label": ACOMPANHAMENTO_LABELS.get(key, key)}
            for key in ACOMPANHAMENTO_ORDER
        ],
    }


def dashboard_payload() -> dict:
    resumo_cnh = gerar_resumo_cnh(DB_PATH)
    resumo_colab = get_dashboard_summary()
    return {
        "colaboradores": resumo_colab,
        "cnh": resumo_cnh,
        "documentosAVencer": get_documentos_a_vencer(30),
        "porCidade": get_summary_by_cidade(),
        "runtime": get_runtime_config(),
    }


def save_report(filename_prefix: str, builder, extension: str = "xlsx", *, owner: dict | None = None) -> Path:
    path = allocate_report_path(
        GENERATED_DIR,
        filename_prefix,
        extension,
        user=owner,
        retention_seconds=REPORT_RETENTION_SECONDS,
    )
    builder(str(path))
    return path


def safe_file_path(raw_path: str) -> Path | None:
    return resolve_path_within_root(STORAGE_ROOT, raw_path)


ATTACHMENT_FILE_SOURCES = {
    "documento": ("documentos", "caminho_arquivo"),
    "atestado": ("atestados", "caminho_atestado_pdf"),
    "advertencia": ("advertencias", "caminho_advertencia_pdf"),
}


def attachment_file_path(kind: str, raw_id: str) -> Path | None:
    source = ATTACHMENT_FILE_SOURCES.get(str(kind or "").strip().lower())
    identifier = str(raw_id or "").strip()
    if source is None or not identifier.isdigit():
        return None
    table, column = source
    with get_db_connection() as conn:
        row = conn.execute(f"SELECT {column} FROM {table} WHERE id = ?", (int(identifier),)).fetchone()
    if not row or not row[0]:
        return None
    return safe_file_path(str(row[0]))


class ColaboradoresHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        try:
            sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
            sys.stdout.flush()
        except OSError:
            pass

    def end_headers(self) -> None:
        self.send_security_headers()
        self.send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def allowed_cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return None
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        current_host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            "localhost",
            socket.gethostname().lower(),
            current_host,
        }
        if parsed.scheme in {"http", "https"} and host in allowed_hosts:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.allowed_cors_origin()
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(fix_text(payload), ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"ok": False, "message": fix_text(message)}, status)

    def send_maintenance_page(self) -> None:
        body = b"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gestor de Colaboradores em manutencao</title>
  <style>
    :root{color-scheme:light;font-family:Inter,Segoe UI,Arial,sans-serif;color:#17231f;background:#edf2ef}
    body{min-height:100vh;margin:0;display:grid;place-items:center;padding:24px;background:linear-gradient(135deg,#f7faf8,#dfe8e3)}
    main{max-width:520px;border:1px solid #d7e2dc;border-radius:18px;background:#fff;padding:34px;box-shadow:0 22px 48px rgba(27,53,41,.14)}
    span{display:inline-flex;margin-bottom:16px;border-radius:999px;background:#fff3cc;color:#6d4a08;padding:7px 12px;font-size:12px;font-weight:900;text-transform:uppercase}
    h1{margin:0 0 10px;font-size:28px;line-height:1.1;color:#17231f}
    p{margin:0;color:#52625b;line-height:1.55}
    a{display:inline-flex;margin-top:22px;border-radius:10px;background:#2f3192;color:#fff;padding:11px 16px;text-decoration:none;font-weight:800}
  </style>
</head>
<body>
  <main>
    <span>Manutencao</span>
    <h1>Gestor de Colaboradores indisponivel</h1>
    <p>Este portal esta temporariamente restrito ao administrador para ajustes internos.</p>
    <a href="http://localhost:8890">Voltar ao launcher</a>
  </main>
</body>
</html>"""
        self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "3600")
        self.end_headers()
        self.wfile.write(body)

    def ensure_admin_access(self, path: str) -> bool:
        user = current_portal_user(self.headers)
        decision = evaluate_portal_access(user, maintenance_mode=MAINTENANCE_MODE)
        if decision.allowed:
            return True
        if decision.reason == "authentication_required":
            if path.startswith("/api/"):
                self.send_error_json(
                    "Login necessario pelo Portal Agricola.",
                    HTTPStatus.UNAUTHORIZED,
                )
            else:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", LAUNCHER_LOGIN_URL)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            return False
        if path.startswith("/api/"):
            self.send_error_json(
                "Gestor de Colaboradores em manutencao. Acesso restrito ao administrador.",
                HTTPStatus.FORBIDDEN,
            )
        else:
            self.send_maintenance_page()
        return False

    def portal_user(self) -> dict | None:
        return current_portal_user(self.headers)

    def audit(self, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
        send_portal_audit(self.headers, event_type, summary, entity_type, entity_id, details)

    def parse_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def parse_multipart_body(self) -> tuple[dict, dict[str, str]]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_MULTIPART_BODY_BYTES:
            raise RequestBodyTooLarge
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        fields: dict[str, str] = {}
        files: dict[str, str] = {}

        for key in form.keys():
            item = form[key]
            if isinstance(item, list):
                item = item[0]
            if getattr(item, "filename", None):
                suffix = Path(item.filename).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    shutil.copyfileobj(item.file, tmp)
                    files[key] = tmp.name
            else:
                fields[key] = item.value
        return fields, files

    def parse_body(self) -> tuple[dict, dict[str, str]]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return self.parse_multipart_body()
        return self.parse_json_body(), {}

    def cleanup_temp_files(self, files: dict[str, str]) -> None:
        for path in files.values():
            try:
                os.remove(path)
            except OSError:
                pass

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            deep_check = get_query_value(params, "deep").strip().lower() in {"1", "true", "sim", "yes"}
            health = cached_health_payload(deep_check=deep_check)
            self.send_json(health, HTTPStatus.OK if health.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if not self.ensure_admin_access(path):
            return

        try:
            if path == "/api/status":
                runtime = get_runtime_config()
                self.send_json(
                    {
                        "ok": True,
                        "status": "online",
                        "dbEngine": runtime.get("db_engine"),
                        "dbPath": runtime.get("db_target"),
                    }
                )
                return
            if path == "/api/dashboard":
                self.send_json({"ok": True, "data": dashboard_payload()})
                return
            if path == "/api/opcoes":
                self.send_json({"ok": True, "data": opcoes_payload()})
                return
            if path == "/api/cnh":
                limit = parse_int_query(params, "limit", 500, minimum=1, maximum=5000)
                offset = parse_int_query(params, "offset", 0, minimum=0)

                rows, total = listar_painel_cnh(
                    DB_PATH,
                    filtro_busca=get_query_value(params, "q"),
                    filtro_status_tecnico=get_query_value(params, "status_tecnico"),
                    filtro_status_acompanhamento=get_query_value(params, "status_acompanhamento"),
                    filtro_frente=get_query_value(params, "frente"),
                    filtro_gestor=get_query_value(params, "gestor"),
                    somente_com_inconsistencias=bool_from_query(get_query_value(params, "com_inconsistencias")),
                    somente_pendentes=bool_from_query(get_query_value(params, "pendentes")),
                    limit=limit,
                    offset=offset
                )
                self.send_json({"ok": True, "data": rows, "total": total, "limit": limit, "offset": offset})
                return
            if path == "/api/colaboradores":
                rows = obter_colaboradores(
                    filtro_nome=get_query_value(params, "q"),
                    filtro_situacao=get_query_value(params, "situacao") or None,
                    cnh_vencida=bool_from_query(get_query_value(params, "cnh_vencida")),
                    filtro_funcao=get_query_value(params, "funcao"),
                    filtro_turno=get_query_value(params, "turno"),
                    filtro_cidade=get_query_value(params, "cidade") or None,
                )
                self.send_json({"ok": True, **pagination_payload(rows, params)})
                return
            if path.startswith("/api/colaboradores/"):
                codigo = path.split("/")[-1]
                colaborador = obter_colaborador_por_codigo(codigo)
                if not colaborador:
                    self.send_error_json("Colaborador nao encontrado.", HTTPStatus.NOT_FOUND)
                    return
                self.send_json(
                    {
                        "ok": True,
                        "data": {
                            "colaborador": colaborador,
                            "documentos": listar_documentos_por_colaborador(codigo),
                            "atestados": listar_atestados_por_colaborador(codigo),
                            "advertencias": listar_advertencias_por_colaborador(codigo),
                            "historicoCnh": listar_historico_cnh(DB_PATH, codigo),
                            "acompanhamentosCnh": listar_acompanhamentos_cnh(DB_PATH, codigo),
                        },
                    }
                )
                return
            if path == "/api/escala":
                self.send_json({"ok": True, "data": escala_payload()})
                return
            if path == "/api/auditoria":
                self.send_json({"ok": True, "data": list_auditoria(params)})
                return
            if path == "/api/exportar/painel-cnh":
                file_path = save_report("painel_cnh", lambda output: exportar_painel_cnh_excel(DB_PATH, output), owner=self.portal_user())
                self.send_file(file_path, download_name=file_path.name)
                return
            if path == "/api/exportar/cobranca-cnh":
                file_path = save_report("cobranca_cnh", lambda output: exportar_lista_cobranca_excel(DB_PATH, output), owner=self.portal_user())
                self.send_file(file_path, download_name=file_path.name)
                return
            if path == "/api/exportar/cnh-vencidas-pdf":
                file_path = save_report("cnh_vencidas_por_frente", lambda output: gerar_pdf_cnh_vencidas_por_frente(DB_PATH, output), "pdf", owner=self.portal_user())
                self.send_file(file_path, download_name=file_path.name)
                return
            if path == "/api/arquivo":
                file_path = attachment_file_path(
                    get_query_value(params, "type"),
                    get_query_value(params, "id"),
                )
                if not file_path or not file_path.exists() or not file_path.is_file():
                    self.send_error_json("Arquivo nao encontrado.", HTTPStatus.NOT_FOUND)
                    return
                self.send_file(file_path, download_name=file_path.name)
                return
        except Exception as exc:
            self.send_error_json(f"Erro inesperado: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        files: dict[str, str] = {}
        if not self.ensure_admin_access(path):
            return

        try:
            payload, files = self.parse_body()
            if path == "/api/colaboradores":
                original_codigo = payload.get("original_codigo") or payload.get("codigo_original")
                data = clean_payload(payload)
                if not data.get("codigo_colaborador") or not data.get("nome"):
                    self.send_error_json("Codigo e nome sao obrigatorios.")
                    return
                codigo = str(data["codigo_colaborador"])
                existed = bool(obter_colaborador_por_codigo(codigo))
                if original_codigo:
                    ok, message = atualizar_colaborador(str(original_codigo), data)
                    event_type = "colaborador.update"
                elif existed:
                    ok, message = atualizar_colaborador(codigo, data)
                    event_type = "colaborador.update"
                else:
                    ok, message = adicionar_colaborador(data)
                    event_type = "colaborador.create"
                if ok:
                    self.audit(
                        event_type,
                        f"Salvou colaborador {data.get('nome')}",
                        entity_type="colaborador",
                        entity_id=codigo,
                        details={
                            "nome": data.get("nome"),
                            "frente": data.get("frente_safra"),
                            "turno": data.get("turno_safra"),
                            "funcao": data.get("funcao_safra") or data.get("funcao"),
                        },
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/escala":
                codigo = str(payload.get("codigo_colaborador") or "")
                nome = str(payload.get("nome") or "")
                ok, message = atualizar_escala_por_nome(
                    codigo,
                    nome,
                    str(payload.get("frente_safra") or "SEM ESCALA"),
                    payload.get("turno_safra") or None,
                    payload.get("funcao_safra") or None,
                    payload.get("horario") or None,
                )
                if ok:
                    self.audit(
                        "escala.update",
                        f"Atualizou escala de {nome or codigo}",
                        entity_type="colaborador",
                        entity_id=codigo,
                        details={
                            "frente": payload.get("frente_safra"),
                            "turno": payload.get("turno_safra"),
                            "funcao": payload.get("funcao_safra"),
                            "horario": payload.get("horario"),
                        },
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/cnh/acompanhamento":
                codigo = str(payload.get("codigo_colaborador") or "")
                ok, message = registrar_acompanhamento_cnh(
                    codigo_colaborador=codigo,
                    status=str(payload.get("status") or "SEM_ACAO"),
                    responsavel=str(payload.get("responsavel") or ""),
                    observacao=str(payload.get("observacao") or ""),
                    data_prevista=payload.get("data_prevista") or None,
                    caminho_comprovante=files.get("arquivo") or payload.get("caminho_comprovante"),
                    houve_contato=bool_from_query(str(payload.get("houve_contato") or "")),
                    origem="WEB",
                )
                if ok:
                    self.audit(
                        "cnh.followup",
                        f"Registrou acompanhamento de CNH {codigo}",
                        entity_type="colaborador",
                        entity_id=codigo,
                        details={"status": payload.get("status"), "responsavel": payload.get("responsavel"), "dataPrevista": payload.get("data_prevista")},
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/cnh/acompanhamento-lote":
                codigos_raw = payload.get("codigos") or payload.get("codigo_colaborador") or []
                if isinstance(codigos_raw, str):
                    codigos = [item.strip() for item in codigos_raw.split(",") if item.strip()]
                else:
                    codigos = [str(item).strip() for item in codigos_raw if str(item).strip()]
                codigos = list(dict.fromkeys(codigos))
                if not codigos:
                    self.send_error_json("Selecione ao menos um colaborador para aplicar acompanhamento.")
                    return
                if len(codigos) > 500:
                    self.send_error_json("Limite de 500 colaboradores por lote.", HTTPStatus.BAD_REQUEST)
                    return

                status = str(payload.get("status") or "SEM_ACAO")
                responsavel = str(payload.get("responsavel") or "")
                observacao = str(payload.get("observacao") or "")
                data_prevista = payload.get("data_prevista") or None
                houve_contato = bool_from_query(str(payload.get("houve_contato") or ""))
                results = []
                success_count = 0
                for codigo in codigos:
                    ok, message = registrar_acompanhamento_cnh(
                        codigo_colaborador=codigo,
                        status=status,
                        responsavel=responsavel,
                        observacao=observacao,
                        data_prevista=data_prevista,
                        caminho_comprovante=None,
                        houve_contato=houve_contato,
                        origem="WEB_LOTE",
                    )
                    if ok:
                        success_count += 1
                    results.append({"codigo": codigo, "ok": ok, "message": message})

                if success_count:
                    self.audit(
                        "cnh.followup.bulk",
                        f"Registrou acompanhamento de CNH em lote para {success_count} colaborador(es)",
                        entity_type="colaborador",
                        entity_id=",".join(codigos[:20]),
                        details={"status": status, "responsavel": responsavel, "total": len(codigos), "success": success_count},
                    )
                message = f"Acompanhamento aplicado em {success_count} de {len(codigos)} colaborador(es)."
                self.send_json(
                    {"ok": success_count == len(codigos), "message": message, "results": results},
                    HTTPStatus.OK if success_count else HTTPStatus.BAD_REQUEST,
                )
                return
            if path == "/api/cnh/renovacao":
                codigo = str(payload.get("codigo_colaborador") or "")
                ok, message = registrar_renovacao_cnh(
                    codigo_colaborador=codigo,
                    nova_validade=str(payload.get("nova_validade") or ""),
                    categoria_nova=payload.get("categoria_nova") or None,
                    responsavel=str(payload.get("responsavel") or ""),
                    observacao=str(payload.get("observacao") or ""),
                    caminho_comprovante=files.get("arquivo") or payload.get("caminho_comprovante"),
                    origem="WEB",
                )
                if ok:
                    self.audit(
                        "cnh.renewal",
                        f"Registrou renovacao de CNH {codigo}",
                        entity_type="colaborador",
                        entity_id=codigo,
                        details={"validade": payload.get("nova_validade"), "categoria": payload.get("categoria_nova"), "responsavel": payload.get("responsavel")},
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/documentos":
                codigo = str(payload.get("codigo_colaborador") or "")
                ok, message = adicionar_documento(
                    codigo,
                    str(payload.get("nome_documento") or "Documento"),
                    payload.get("data_validade") or None,
                    files.get("arquivo") or payload.get("caminho_arquivo"),
                )
                if ok:
                    self.audit(
                        "documento.create",
                        f"Adicionou documento para {codigo}",
                        entity_type="colaborador",
                        entity_id=codigo,
                        details={"documento": payload.get("nome_documento"), "validade": payload.get("data_validade")},
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/atestados":
                data = {
                    "codigo_colaborador": payload.get("codigo_colaborador"),
                    "data_inicio": payload.get("data_inicio"),
                    "data_fim": payload.get("data_fim"),
                    "motivo": payload.get("motivo"),
                    "caminho_atestado_pdf": files.get("arquivo") or payload.get("caminho_atestado_pdf"),
                }
                ok, message = adicionar_atestado(data)
                if ok:
                    self.audit(
                        "atestado.create",
                        f"Adicionou atestado para {data.get('codigo_colaborador')}",
                        entity_type="colaborador",
                        entity_id=data.get("codigo_colaborador"),
                        details={"inicio": data.get("data_inicio"), "fim": data.get("data_fim"), "motivo": data.get("motivo")},
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/advertencias":
                data = {
                    "codigo_colaborador": payload.get("codigo_colaborador"),
                    "data_infracao": payload.get("data_infracao"),
                    "tipo_infracao": payload.get("tipo_infracao"),
                    "descricao": payload.get("descricao"),
                    "caminho_advertencia_pdf": files.get("arquivo") or payload.get("caminho_advertencia_pdf"),
                }
                ok, message = adicionar_advertencia(data)
                if ok:
                    self.audit(
                        "advertencia.create",
                        f"Adicionou advertencia para {data.get('codigo_colaborador')}",
                        entity_type="colaborador",
                        entity_id=data.get("codigo_colaborador"),
                        details={"data": data.get("data_infracao"), "tipo": data.get("tipo_infracao")},
                    )
                self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
                return
        except json.JSONDecodeError:
            self.send_error_json("JSON invalido.")
            return
        except RequestBodyTooLarge:
            self.send_error_json("Requisicao muito grande.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except Exception as exc:
            self.send_error_json(f"Erro inesperado: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        finally:
            self.cleanup_temp_files(files)

        self.send_error_json("Rota nao encontrada.", HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not self.ensure_admin_access(path):
            return

        try:
            if path.startswith("/api/colaboradores/"):
                entity = path.split("/")[-1]
                ok, message = excluir_colaborador(entity)
                event_type = "colaborador.delete"
                entity_type = "colaborador"
            elif path.startswith("/api/documentos/"):
                entity = path.split("/")[-1]
                ok, message = excluir_documento(int(entity))
                event_type = "documento.delete"
                entity_type = "documento"
            elif path.startswith("/api/atestados/"):
                entity = path.split("/")[-1]
                ok, message = excluir_atestado(int(entity))
                event_type = "atestado.delete"
                entity_type = "atestado"
            elif path.startswith("/api/advertencias/"):
                entity = path.split("/")[-1]
                ok, message = excluir_advertencia(int(entity))
                event_type = "advertencia.delete"
                entity_type = "advertencia"
            else:
                self.send_error_json("Rota nao encontrada.", HTTPStatus.NOT_FOUND)
                return
            if ok:
                self.audit(event_type, f"Excluiu {entity_type} {entity}", entity_type=entity_type, entity_id=entity)
            self.send_json({"ok": ok, "message": message}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_error_json(f"Erro inesperado: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def send_file(self, file_path: Path, download_name: str | None = None) -> None:
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gestor de Colaboradores Web")
    parser.add_argument("--host", default=os.environ.get("APP_COLAB_HOST", os.environ.get("APP_BIND_HOST", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_COLAB_PORT", "8892")))
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


class FastThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


def tcp_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> None:
    args = parse_args()
    if tcp_port_open(args.host, args.port):
        print(f"Gestor de Colaboradores Web ja esta rodando em http://{args.host}:{args.port}")
        return

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    garantir_schema_banco()
    httpd = FastThreadingHTTPServer((args.host, args.port), ColaboradoresHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Gestor de Colaboradores Web rodando em {url}")
    if not args.no_browser and os.environ.get("APP_COLAB_NO_BROWSER") != "1":
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Encerrando servidor...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
