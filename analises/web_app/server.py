import argparse
import json
import mimetypes
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - SQLite-only environments
    psycopg = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_DIR = PROJECT_ROOT.parent
STATIC_DIR = PROJECT_ROOT / "web_app" / "static"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agricola_shared.portal_auth import read_portal_session
from agricola_shared.audit_spool import DurableAuditSpool

AUDIT_URL = os.environ.get("AGRICOLA_AUDIT_URL", "http://127.0.0.1:8890/api/audit/event")
SESSION_COOKIE = os.environ.get("AGRICOLA_SESSION_COOKIE", "oa_demo_session")
LAUNCHER_AUTH_DB = Path(os.environ.get("LAUNCHER_AUTH_DB", PROJECT_ROOT.parent / "launcher_web" / "launcher_auth.db"))
LAUNCHER_LOGIN_URL = os.environ.get("AGRICOLA_LOGIN_URL", "http://localhost:8890/login.html")
SESSION_CACHE_TTL_SECONDS = 10
SESSION_CACHE: dict[str, tuple[float, dict]] = {}
HEALTH_CACHE_TTL_SECONDS = float(os.environ.get("ANALISES_HEALTH_CACHE_TTL_SECONDS", "5"))
HEALTH_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}
HEALTH_CACHE_LOCK = threading.Lock()
OPTIONS_CACHE_TTL_SECONDS = 300
OPTIONS_CACHE: dict[str, object] = {"expires_at": 0.0, "data": None}
OPTIONS_CACHE_LOCK = threading.Lock()
MAX_JSON_BODY_BYTES = int(os.environ.get("ANALISES_MAX_JSON_BODY_BYTES", str(1024 * 1024)))


class RequestBodyTooLarge(Exception):
    pass

os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import DatabaseConfig
from core.database import setup_main_database
from core.date_utils import sql_date_expr
from core.operational_fleet import (
    operational_fleet_sql,
)
from core.operations_logic import calcular_parada_e_eficiencia
from core.sql_compat import hhmm_minutes_sql, numeric_text_order_sql
from core.settings import setup_settings_database
from core.validation import (
    ValidationError,
    build_finalized_occurrence_metrics,
    normalize_web_occurrence_payload,
)
from reporting.daily_operations_report import gerar_relatorio
from reporting.database_excel_export import export_database_to_excel
from reporting.front_efficiency_report import gerar_relatorio_eficiencia_frentes

DatabaseConfig.DB_PATH = str(PROJECT_ROOT / "operacao_agricola.db")
AUDIT_SPOOL = DurableAuditSpool(PROJECT_ROOT / "logs" / "audit-spool")


def db_connect():
    conn = DatabaseConfig.get_connection()
    conn.row_factory = sqlite3.Row
    return conn


def json_default(value):
    if isinstance(value, sqlite3.Row):
        return dict(value)
    return str(value)


def send_portal_audit(headers, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None):
    cookie = headers.get("Cookie", "")
    payload = {
        "module": "analises",
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
        body = json.dumps(item, ensure_ascii=False, default=json_default).encode("utf-8")
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
    cached = SESSION_CACHE.get(token)
    if cached and cached[0] > now:
        return dict(cached[1])

    user = read_portal_session(cookie_header)
    if not user:
        SESSION_CACHE.pop(token, None)
        return None
    user.setdefault("status", "approved")
    SESSION_CACHE[token] = (now + SESSION_CACHE_TTL_SECONDS, user)
    return user


def parse_date_param(value, output_format="%Y-%m-%d"):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime(output_format)
        except ValueError:
            pass
    return None


def display_to_report_date(value, separator="-"):
    fmt = "%d-%m-%Y" if separator == "-" else "%d/%m/%Y"
    return parse_date_param(value, fmt)


def hhmm_from_minutes(total):
    total = max(0, int(total or 0))
    return f"{total // 60:02}:{total % 60:02}"


def int_param(value, default=0, minimum=0, maximum=1000):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def sql_hhmm_minutes(column):
    return hhmm_minutes_sql(column, DatabaseConfig.DB_ENGINE)


def build_filters(params):
    clauses = [operational_fleet_sql("Frota")]
    values = []
    date_expr = sql_date_expr("Data")

    start = parse_date_param(params.get("start"))
    end = parse_date_param(params.get("end"))
    if start:
        clauses.append(f"{date_expr} >= ?")
        values.append(start)
    if end:
        clauses.append(f"{date_expr} <= ?")
        values.append(end)

    field_param_names = {
        "Frente": "frente",
        "Turno": "turno",
        "Frota": "frota",
        "Status_Parada": "status",
    }
    for field, param_name in field_param_names.items():
        value = params.get(param_name)
        if value:
            clauses.append(f"{field} = ?")
            values.append(value)

    search = params.get("q")
    if search:
        like = f"%{search}%"
        clauses.append(
            "(Data LIKE ? OR Frente LIKE ? OR Frota LIKE ? OR Motivo LIKE ? "
            "OR Fundo_Agricola LIKE ? OR Chuva LIKE ? OR Incendio LIKE ?)"
        )
        values.extend([like] * 7)

    return " AND ".join(clauses), values


def invalidate_options_cache():
    with OPTIONS_CACHE_LOCK:
        OPTIONS_CACHE["expires_at"] = 0.0
        OPTIONS_CACHE["data"] = None


def get_options():
    now = time.time()
    with OPTIONS_CACHE_LOCK:
        cached = OPTIONS_CACHE.get("data")
        if cached and float(OPTIONS_CACHE.get("expires_at") or 0) > now:
            return cached

    date_expr = sql_date_expr("Data")
    frente_order = numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE)
    with db_connect() as conn:
        frentes = [
            row[0]
            for row in conn.execute(
                f"""
                SELECT Frente
                FROM RELATORIO_OPERACAO_DIARIA
                WHERE COALESCE(Frente, '') != ''
                GROUP BY Frente
                ORDER BY {frente_order}, Frente
                """
            )
        ]
        frotas = [
            row[0]
            for row in conn.execute(
                f"""
                SELECT DISTINCT Frota
                FROM RELATORIO_OPERACAO_DIARIA
                WHERE COALESCE(Frota, '') != ''
                  AND {operational_fleet_sql("Frota")}
                ORDER BY Frota
                """
            )
        ]
        turnos = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT Turno
                FROM RELATORIO_OPERACAO_DIARIA
                WHERE COALESCE(Turno, '') != ''
                ORDER BY Turno
                """
            )
        ]
        date_range = conn.execute(
            f"""
            SELECT MIN({date_expr}) AS start, MAX({date_expr}) AS end
            FROM RELATORIO_OPERACAO_DIARIA
            WHERE {operational_fleet_sql("Frota")}
            """
        ).fetchone()
    data = {
        "frentes": frentes,
        "frotas": frotas,
        "turnos": turnos,
        "date_range": {
            "start": date_range["start"] if date_range else "",
            "end": date_range["end"] if date_range else "",
        },
    }
    with OPTIONS_CACHE_LOCK:
        OPTIONS_CACHE["data"] = data
        OPTIONS_CACHE["expires_at"] = now + OPTIONS_CACHE_TTL_SECONDS
    return data


def get_summary(params):
    where_sql, values = build_filters(params)
    minutes_expr = sql_hhmm_minutes("Total_Hora_Parado")
    summary_query = f"""
        SELECT
            COUNT(*) AS total_registros,
            COALESCE(SUM({minutes_expr}), 0) AS total_minutos,
            AVG(CASE
                WHEN Status_Parada = 'Finalizada' AND Eficiencia IS NOT NULL
                THEN CAST(Eficiencia AS REAL)
            END) AS eficiencia_media,
            SUM(CASE WHEN UPPER(COALESCE(Frota, '')) LIKE '%COLHEDORA%' THEN 1 ELSE 0 END) AS colhedora,
            SUM(CASE WHEN UPPER(COALESCE(Frota, '')) LIKE '%TRANSBORDO%' THEN 1 ELSE 0 END) AS transbordo,
            SUM(CASE WHEN Status_Parada = 'Em Andamento' THEN 1 ELSE 0 END) AS em_andamento
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE {where_sql}
    """
    reasons_query = f"""
        SELECT COALESCE(NULLIF(TRIM(Motivo), ''), 'Sem motivo') AS motivo,
               COUNT(*) AS count,
               COALESCE(SUM({minutes_expr}), 0) AS minutes
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE {where_sql}
        GROUP BY COALESCE(NULLIF(TRIM(Motivo), ''), 'Sem motivo')
        ORDER BY minutes DESC, count DESC
        LIMIT 8
    """
    turn_query = f"""
        SELECT COALESCE(NULLIF(TRIM(Turno), ''), 'N/A') AS turno,
               AVG(CAST(Eficiencia AS REAL)) AS eficiencia,
               COUNT(*) AS registros
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE {where_sql}
          AND Status_Parada = 'Finalizada'
          AND Eficiencia IS NOT NULL
        GROUP BY COALESCE(NULLIF(TRIM(Turno), ''), 'N/A')
        ORDER BY turno
    """
    pending_query = f"""
        SELECT id, Data, Frente, Turno, Frota, Motivo, Parou_Hora
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE {where_sql}
          AND Status_Parada = 'Em Andamento'
        ORDER BY {sql_date_expr("Data")} DESC, id DESC
        LIMIT 8
    """
    with db_connect() as conn:
        summary = conn.execute(summary_query, values).fetchone()
        top_reasons = [dict(row) for row in conn.execute(reasons_query, values).fetchall()]
        turnos = [dict(row) for row in conn.execute(turn_query, values).fetchall()]
        for turno in turnos:
            turno["eficiencia"] = round(float(turno["eficiencia"] or 0), 2)
        pending_rows = [dict(row) for row in conn.execute(pending_query, values).fetchall()]

    return {
        "total_registros": int(summary["total_registros"] or 0),
        "total_horas_paradas": hhmm_from_minutes(summary["total_minutos"] or 0),
        "eficiencia_media": round(float(summary["eficiencia_media"] or 0), 2),
        "colhedora": int(summary["colhedora"] or 0),
        "transbordo": int(summary["transbordo"] or 0),
        "em_andamento": int(summary["em_andamento"] or 0),
        "criterio": "Somente COLHEDORA e TRANSBORDO, 600 min por turno",
        "top_motivos": top_reasons,
        "eficiencia_por_turno": turnos,
        "paradas_em_andamento": pending_rows,
    }


def list_operations(params):
    where_sql, values = build_filters(params)
    limit = int_param(params.get("limit"), default=200, minimum=1, maximum=1000)
    offset = int_param(params.get("offset"), default=0, minimum=0, maximum=1_000_000)
    date_expr = sql_date_expr("Data")
    frente_order = numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE)
    query = f"""
        SELECT id, Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora,
               Total_Hora_Parado, Eficiencia, Fundo_Agricola, Chuva, Incendio, Status_Parada
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE {where_sql}
        ORDER BY {date_expr} DESC, {frente_order}, Turno, Frota
        LIMIT ? OFFSET ?
    """
    count_query = f"SELECT COUNT(*) FROM RELATORIO_OPERACAO_DIARIA WHERE {where_sql}"
    with db_connect() as conn:
        total = conn.execute(count_query, values).fetchone()[0]
        rows = conn.execute(query, values + [limit, offset]).fetchall()
    return {
        "rows": [dict(row) for row in rows],
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + len(rows) < total,
    }


def create_operation(payload):
    try:
        occurrence = normalize_web_occurrence_payload(payload)
    except ValidationError as exc:
        return {"ok": False, "message": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY

    data = occurrence["data_db"]
    frente = occurrence["frente"]
    turno = occurrence["turno"]
    frota = occurrence["frota"]
    motivo = occurrence["motivo"]
    parou = occurrence["parou_hora"]
    voltou = occurrence["voltou_hora"]
    fundo = occurrence["fundo"]
    chuva = occurrence["chove"]
    incendio = occurrence["incendio"]
    status = occurrence["status"]

    total_hora = None
    eficiencia = None
    if status == "Finalizada":
        data_display = data.replace("-", "/")
        total_hora, eficiencia = build_finalized_occurrence_metrics(
            data_display, parou, voltou, calcular_parada_e_eficiencia
        )

    query = """
        INSERT INTO RELATORIO_OPERACAO_DIARIA
            (Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora,
             Total_Hora_Parado, Eficiencia, Fundo_Agricola, Chuva, Incendio, Status_Parada)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        data,
        frente,
        turno,
        frota,
        motivo,
        parou or None,
        voltou or None,
        total_hora,
        f"{eficiencia:.2f}" if eficiencia is not None else None,
        fundo,
        chuva,
        incendio,
        status,
    )

    try:
        with db_connect() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            new_id = cursor.lastrowid
        invalidate_options_cache()
    except INTEGRITY_ERRORS:
        return {
            "ok": False,
            "message": "Ja existe uma ocorrencia com a mesma Data, Frente, Turno, Frota e Hora que Parou.",
        }, HTTPStatus.CONFLICT

    return {"ok": True, "id": new_id, "message": "Registro salvo com sucesso."}, HTTPStatus.CREATED


def make_operation_report(params):
    start = display_to_report_date(params.get("start"), "-")
    end = display_to_report_date(params.get("end"), "-")
    with tempfile.TemporaryDirectory() as tmp:
        path = gerar_relatorio(
            data_inicial=start,
            data_final=end,
            frente_filtro=params.get("frente") or None,
            turno_filtro=params.get("turno") or None,
            frota_filtro=params.get("frota") or None,
            pesquisa_geral_texto=params.get("q") or None,
            output_path=tmp,
        )
        return Path(path).read_bytes(), Path(path).name


def make_efficiency_report(params):
    start = display_to_report_date(params.get("start"), "/")
    end = display_to_report_date(params.get("end"), "/")
    if not start or not end:
        date_range = get_options().get("date_range", {})
        start = start or display_to_report_date(date_range.get("start"), "/")
        end = end or display_to_report_date(date_range.get("end"), "/")
    if not start or not end:
        raise ValueError("Informe data inicial e final.")
    with tempfile.TemporaryDirectory() as tmp:
        path = gerar_relatorio_eficiencia_frentes(start, end, output_path=tmp)
        return Path(path).read_bytes(), Path(path).name


def make_database_excel():
    with tempfile.TemporaryDirectory() as tmp:
        path = export_database_to_excel(Path(tmp) / "backup_banco_operacional.xlsx")
        return Path(path).read_bytes(), Path(path).name


def read_log_tail(path, max_lines=12):
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [line for line in lines[-max_lines:] if line.strip()]
    except OSError:
        return []


def get_system_status(deep_check: bool = False):
    db_path = Path(DatabaseConfig.DB_PATH)
    min_free_bytes = 500 * 1024 * 1024
    is_postgres = DatabaseConfig.DB_ENGINE in {"postgres", "postgresql"}
    db_info = {
        "engine": "postgresql" if is_postgres else "sqlite",
        "path": "" if is_postgres else str(db_path),
        "exists": True if is_postgres else db_path.exists(),
        "size_mb": 0 if is_postgres else round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0,
        "modified_at": "" if is_postgres else datetime.fromtimestamp(db_path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S") if db_path.exists() else "",
        "mode": "deep" if deep_check else "fast",
    }
    disk_info = {"free_bytes": 0, "min_free_bytes": min_free_bytes, "ok": False}
    try:
        usage = shutil.disk_usage(db_path.parent if db_path.parent.exists() else PROJECT_ROOT)
        disk_info["free_bytes"] = usage.free
        disk_info["ok"] = usage.free >= min_free_bytes
    except OSError as exc:
        disk_info["message"] = str(exc)

    try:
        with db_connect() as conn:
            db_info["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            db_info["operacoes"] = conn.execute("SELECT COUNT(*) FROM RELATORIO_OPERACAO_DIARIA").fetchone()[0]
            try:
                db_info["schema_version"] = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            except Exception:
                db_info["schema_version"] = None
            db_info["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0] if deep_check else "ok"
    except Exception as exc:
        db_info["quick_check"] = f"erro: {exc}"

    ok = bool(db_info.get("exists") and str(db_info.get("quick_check", "")).lower() == "ok" and disk_info["ok"])
    return {
        "ok": ok,
        "app": "Analises Operacionais",
        "status": "online" if ok else "alerta",
        "message": "Analises Operacionais online" if ok else "Analises Operacionais com alerta no health check",
        "checked_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "database": db_info,
        "disk": disk_info,
        "recent_errors": read_log_tail(PROJECT_ROOT / "web_analises.err.log"),
        "recent_start": read_log_tail(PROJECT_ROOT / "web_analises.log", 5),
    }


def cached_system_status(deep_check: bool = False) -> dict:
    if deep_check:
        return get_system_status(deep_check=True)

    now = time.time()
    with HEALTH_CACHE_LOCK:
        payload = HEALTH_CACHE.get("payload")
        if isinstance(payload, dict) and float(HEALTH_CACHE.get("expires_at", 0.0)) > now:
            return payload

    payload = get_system_status()
    with HEALTH_CACHE_LOCK:
        HEALTH_CACHE["payload"] = payload
        HEALTH_CACHE["expires_at"] = time.time() + HEALTH_CACHE_TTL_SECONDS
    return payload


class AgricolaWebHandler(BaseHTTPRequestHandler):
    server_version = "Operacoes AgricolasWeb/0.1"

    def end_headers(self):
        self.send_security_headers()
        super().end_headers()

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def audit(self, event_type: str, summary: str, entity_type: str = "", entity_id: str = "", details: dict | None = None):
        send_portal_audit(self.headers, event_type, summary, entity_type, entity_id, details)

    def portal_user(self) -> dict | None:
        return current_portal_user(self.headers)

    def ensure_authenticated(self, path: str) -> bool:
        if path == "/api/health":
            return True
        if self.portal_user():
            return True
        if path.startswith("/api/"):
            self.send_json({"ok": False, "message": "Login necessario pelo Portal Agricola.", "loginUrl": LAUNCHER_LOGIN_URL}, HTTPStatus.UNAUTHORIZED)
            return False
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", LAUNCHER_LOGIN_URL)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False

    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        try:
            self.route_post()
        except RequestBodyTooLarge:
            self.send_json({"ok": False, "message": "Requisicao muito grande."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}

        if not self.ensure_authenticated(path):
            return

        if path == "/":
            return self.send_static_file("index.html")
        if path.startswith("/static/"):
            return self.send_static_file(path.removeprefix("/static/"))
        if path == "/api/health":
            deep_check = str(params.get("deep", "")).strip().lower() in {"1", "true", "sim", "yes"}
            health = cached_system_status(deep_check=deep_check)
            return self.send_json(health, HTTPStatus.OK if health.get("ok") else HTTPStatus.SERVICE_UNAVAILABLE)
        if path == "/api/options":
            return self.send_json(get_options())
        if path == "/api/summary":
            return self.send_json(get_summary(params))
        if path == "/api/operations":
            return self.send_json(list_operations(params))
        if path == "/api/system/status":
            return self.send_json(get_system_status())
        if path == "/api/reports/operations":
            content, name = make_operation_report(params)
            return self.send_file(content, name, "application/pdf")
        if path == "/api/reports/efficiency":
            content, name = make_efficiency_report(params)
            return self.send_file(content, name, "application/pdf")
        if path == "/api/export/database":
            content, name = make_database_excel()
            return self.send_file(
                content,
                name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        self.send_error(HTTPStatus.NOT_FOUND)

    def route_post(self):
        parsed = urlparse(self.path)
        if not self.ensure_authenticated(parsed.path):
            return
        if parsed.path != "/api/operations":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        response, status = create_operation(payload)
        if status < 400:
            self.audit(
                "operation.create",
                "Registrou apontamento operacional",
                entity_type="operation",
                entity_id=response.get("id") or payload.get("id") or "",
                details={
                    "data": payload.get("data"),
                    "equipamento": payload.get("equipamento"),
                    "tipoEquipamento": payload.get("tipo_equipamento"),
                    "motivo": payload.get("motivo"),
                    "frente": payload.get("frente"),
                    "turno": payload.get("turno"),
                },
            )
        self.send_json(response, status)

    def send_json(self, payload, status=HTTPStatus.OK):
        content = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_file(self, content, filename, content_type):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content)

    def send_static_file(self, relative_path):
        safe_path = (STATIC_DIR / relative_path).resolve()
        if not str(safe_path).startswith(str(STATIC_DIR.resolve())) or not safe_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = safe_path.read_bytes()
        content_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


class FastThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


def tcp_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Operacoes Agricolas web server")
    parser.add_argument("--host", default=os.environ.get("ANALISES_HOST", os.environ.get("APP_BIND_HOST", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()

    if tcp_port_open(args.host, args.port):
        print(f"Operacoes Agricolas Web ja esta rodando em http://{args.host}:{args.port}")
        return

    setup_main_database()
    setup_settings_database()

    server = FastThreadingHTTPServer((args.host, args.port), AgricolaWebHandler)
    print(f"Operacoes Agricolas Web rodando em http://{args.host}:{args.port}")
    print("Na rede local, use o IP deste computador com a mesma porta.")
    server.serve_forever()


if __name__ == "__main__":
    main()
