from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from app_config import (
    APP_ROOT,
    BALANCA_API_EMAIL,
    BALANCA_API_PASSWORD,
    BALANCA_API_TIMEOUT_SECONDS,
    BALANCA_API_TOKEN,
    BALANCA_API_URL,
    BALANCA_DB_PATH,
    DB_ENGINE,
    DB_PATH,
)
from database import DB
from repositories import MasterDataRepository


SOURCE_NAME = "balanca"
SYNC_SOURCES = {"auto", "sqlite", "api"}


def compact_farm_code(value: str | None) -> str:
    return str(value or "").strip().replace("-", "")


def candidate_farm_codes(official_code: str) -> list[str]:
    official = str(official_code or "").strip()
    compact = compact_farm_code(official)
    candidates = [official]
    if compact and compact != official:
        candidates.append(compact)
    return [item for item in candidates if item]


def _connect_readonly(path: str | Path) -> sqlite3.Connection:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Banco mestre da Balanca nao encontrado: {source}")
    conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_master_farms(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            id,
            code,
            name
        FROM farms
        WHERE code IS NOT NULL
          AND TRIM(code) != ''
        ORDER BY code
        """
    ).fetchall()


def _read_master_fields(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            fld.id,
            fld.code,
            fld.name,
            fld.farm_id,
            fld.area_ha,
            fld.area_alq,
            fld.planted_area_ha,
            fld.crop_year,
            fld.area_type,
            fld.active,
            farm.code AS farm_code,
            farm.name AS farm_name
        FROM fields fld
        JOIN farms farm ON farm.id = fld.farm_id
        WHERE farm.code IS NOT NULL
          AND TRIM(farm.code) != ''
          AND fld.code IS NOT NULL
          AND TRIM(fld.code) != ''
        ORDER BY farm.code, CAST(fld.code AS INTEGER), fld.code
        """
    ).fetchall()


def _sqlite_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _read_master_data_from_sqlite(path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    with _connect_readonly(path) as master_conn:
        farms = [_sqlite_row_to_dict(row) for row in _read_master_farms(master_conn)]
        fields = [_sqlite_row_to_dict(row) for row in _read_master_fields(master_conn)]
    return farms, fields, str(Path(path))


def _farm_api_url(base_url: str) -> str:
    clean = base_url.strip().rstrip("/")
    if not clean:
        raise ValueError("APP_NOTAS_BALANCA_API_URL nao configurado.")
    return clean if clean.endswith("/farms") else f"{clean}/farms"


def _request_json(
    url: str,
    *,
    token: str = "",
    timeout_seconds: float = BALANCA_API_TIMEOUT_SECONDS,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Falha ao consultar Balanca API ({exc.code}) em {url}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Balanca API indisponivel em {url}: {exc.reason}") from exc


def _login_balanca_api(
    api_url: str,
    email: str,
    password: str,
    timeout_seconds: float = BALANCA_API_TIMEOUT_SECONDS,
) -> str:
    clean = api_url.strip().rstrip("/")
    if clean.endswith("/farms"):
        clean = clean[: -len("/farms")]
    payload = _request_json(
        f"{clean}/auth/login",
        timeout_seconds=timeout_seconds,
        method="POST",
        payload={"email": email, "password": password},
    )
    token = payload.get("token") if isinstance(payload, dict) else None
    if not token:
        raise RuntimeError("Login na Balanca API nao retornou token.")
    return str(token)


def _read_master_data_from_api(
    api_url: str,
    token: str = "",
    email: str = "",
    password: str = "",
    timeout_seconds: float = BALANCA_API_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    url = _farm_api_url(api_url)
    auth_token = token
    if not auth_token and email and password:
        auth_token = _login_balanca_api(api_url, email, password, timeout_seconds=timeout_seconds)
    payload = _request_json(url, token=auth_token, timeout_seconds=timeout_seconds)
    farms_payload = payload.get("farms") if isinstance(payload, dict) else None
    if not isinstance(farms_payload, list):
        raise RuntimeError("Resposta da Balanca API nao contem lista 'farms'.")

    farms: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []

    for farm in farms_payload:
        if not isinstance(farm, dict):
            continue
        official_code = str(farm.get("code") or "").strip()
        if not official_code:
            continue
        farm_id = str(farm.get("id") or official_code)
        farm_name = str(farm.get("name") or official_code).strip()
        farms.append(
            {
                "id": farm_id,
                "code": official_code,
                "name": farm_name,
            }
        )

        for field in farm.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_code = str(field.get("code") or "").strip()
            if not field_code:
                continue
            fields.append(
                {
                    "id": str(field.get("id") or f"{farm_id}:{field_code}"),
                    "code": field_code,
                    "name": field.get("name"),
                    "farm_id": str(field.get("farmId") or farm_id),
                    "area_ha": field.get("areaHa"),
                    "area_alq": field.get("areaAlq"),
                    "planted_area_ha": field.get("plantedAreaHa"),
                    "crop_year": field.get("cropYear"),
                    "area_type": field.get("areaType"),
                    "active": 1 if field.get("active", True) is not False else 0,
                    "farm_code": official_code,
                    "farm_name": farm_name,
                }
            )

    farms.sort(key=lambda item: str(item["code"]))
    fields.sort(key=lambda item: (str(item["farm_code"]), str(item["code"])))
    return farms, fields, url


def _read_master_data(
    *,
    source: str,
    balanca_db_path: str | Path,
    balanca_api_url: str,
    balanca_api_token: str,
    balanca_api_email: str,
    balanca_api_password: str,
    balanca_api_timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    selected_source = source.strip().lower() or "auto"
    if selected_source not in SYNC_SOURCES:
        raise ValueError(f"Fonte de sincronizacao invalida: {source}")

    if selected_source == "sqlite":
        farms, fields, origin = _read_master_data_from_sqlite(balanca_db_path)
        return farms, fields, origin, "sqlite"

    # `auto` is kept as a backwards-compatible alias for API, but it never
    # downgrades silently to a potentially stale local SQLite snapshot.
    if not balanca_api_url.strip():
        raise ValueError(
            "APP_NOTAS_BALANCA_API_URL deve ser configurado; use source=sqlite "
            "explicitamente para a fonte local."
        )
    farms, fields, origin = _read_master_data_from_api(
        balanca_api_url,
        token=balanca_api_token,
        email=balanca_api_email,
        password=balanca_api_password,
        timeout_seconds=balanca_api_timeout,
    )
    return farms, fields, origin, "api"


def sync_balanca_master_data(
    *,
    notas_db_path: str | Path = DB_PATH,
    balanca_db_path: str | Path = BALANCA_DB_PATH,
    balanca_api_url: str = BALANCA_API_URL,
    balanca_api_token: str = BALANCA_API_TOKEN,
    balanca_api_email: str = BALANCA_API_EMAIL,
    balanca_api_password: str = BALANCA_API_PASSWORD,
    balanca_api_timeout: float = BALANCA_API_TIMEOUT_SECONDS,
    source: str = "api",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sincroniza fazendas e talhoes oficiais da Balanca para o app Notas."""

    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notas_db = DB(notas_db_path, seed_from_excel=False)

    try:
        master_farms, master_fields, origin, source_used = _read_master_data(
            source=source,
            balanca_db_path=balanca_db_path,
            balanca_api_url=balanca_api_url,
            balanca_api_token=balanca_api_token,
            balanca_api_email=balanca_api_email,
            balanca_api_password=balanca_api_password,
            balanca_api_timeout=balanca_api_timeout,
        )
        if not master_farms:
            raise RuntimeError("Fonte mestre da Balanca retornou zero fazendas; sincronizacao recusada.")

        conn = notas_db.conn
        repository = MasterDataRepository(conn)
        conn.execute("BEGIN")

        farm_id_to_local_code: dict[str, str] = {}
        farms_changed = 0

        for farm in master_farms:
            official_code = str(farm["code"]).strip()
            local_code = repository.find_local_farm_code(candidate_farm_codes(official_code)) or official_code
            values = {
                "nome": str(farm["name"]).strip(),
                "id_mestre": str(farm["id"]),
                "codigo_mestre": official_code,
                "fonte_mestre": SOURCE_NAME,
                "sincronizado_em": synced_at,
            }

            if repository.upsert_farm(local_code, values):
                farms_changed += 1

            farm_id_to_local_code[str(farm["id"])] = local_code

        farms_retired = repository.retire_stale_farms(
            source=SOURCE_NAME,
            active_codes=set(farm_id_to_local_code.values()),
            synced_at=synced_at,
        )

        field_stats = repository.replace_fields(
            source=SOURCE_NAME,
            fields=master_fields,
            farm_id_to_local_code=farm_id_to_local_code,
            synced_at=synced_at,
        )

        details = {
            "talhoes_processados": field_stats["processed"],
            "talhoes_inseridos": field_stats["inserted"],
            "talhoes_atualizados": field_stats["updated"],
            "talhoes_removidos": field_stats["removed"],
            "talhoes_ignorados_sem_fazenda": field_stats["skipped"],
            "dry_run": dry_run,
            "source": source_used,
            "fazendas_desativadas": farms_retired,
        }
        repository.record_sync_status(
            source=SOURCE_NAME,
            synced_at=synced_at,
            farms_read=len(master_farms),
            farms_changed=farms_changed,
            fields_read=len(master_fields),
            fields_changed=field_stats["changed"],
            origin=origin,
            details=details,
        )

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

        return {
            "dry_run": dry_run,
            "sincronizado_em": synced_at,
            "origem": origin,
            "fonte_sincronizacao": source_used,
        "destino": "postgresql" if DB_ENGINE in {"postgres", "postgresql"} else str(Path(notas_db_path)),
            "fazendas_lidas": len(master_farms),
            "fazendas_alteradas": farms_changed,
            "fazendas_desativadas": farms_retired,
            "talhoes_lidos": len(master_fields),
            "talhoes_processados": field_stats["processed"],
            "talhoes_sincronizados": field_stats["processed"],
            "talhoes_alterados": field_stats["changed"],
            "talhoes_inseridos": field_stats["inserted"],
            "talhoes_atualizados": field_stats["updated"],
            "talhoes_removidos": field_stats["removed"],
            "talhoes_ignorados_sem_fazenda": field_stats["skipped"],
        }
    except Exception:
        try:
            notas_db.conn.rollback()
        except Exception:
            pass
        raise
    finally:
        notas_db.close()


def create_sync_backup(notas_db_path: str | Path = DB_PATH) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if DB_ENGINE in {"postgres", "postgresql"}:
        backup_path = APP_ROOT / "backups" / f"app_notas.before-balanca-sync-{timestamp}.dump"
    else:
        source = Path(notas_db_path)
        backup_dir = source.parent / "backups"
        backup_path = backup_dir / f"{source.stem}.before-balanca-sync-{timestamp}{source.suffix}"
    db = DB(notas_db_path, seed_from_excel=False)
    try:
        return db.create_backup(backup_path)
    finally:
        db.close()
