from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from app_config import (
    BALANCA_API_EMAIL,
    BALANCA_API_PASSWORD,
    BALANCA_API_TIMEOUT_SECONDS,
    BALANCA_API_TOKEN,
    BALANCA_API_URL,
    BALANCA_DB_PATH,
    DB_ENGINE,
    DB_PATH,
)
from database import backup_sqlite_file
from master_data_sync import create_sync_backup, sync_balanca_master_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza fazendas e talhoes oficiais da Balanca Auditoria para o app Notas."
    )
    parser.add_argument("--notas-db", default=str(DB_PATH), help="Caminho do transporte.db.")
    parser.add_argument("--balanca-db", default=str(BALANCA_DB_PATH), help="Caminho do balanca.db.")
    parser.add_argument(
        "--source",
        choices=("auto", "sqlite", "api"),
        default="api",
        help="Fonte dos cadastros mestres. SQLite exige selecao explicita; auto e alias legado de API.",
    )
    parser.add_argument("--balanca-api-url", default=BALANCA_API_URL, help="Base URL da API da Balanca.")
    parser.add_argument("--balanca-api-token", default=BALANCA_API_TOKEN, help="Bearer token da API da Balanca.")
    parser.add_argument("--balanca-api-email", default=BALANCA_API_EMAIL, help="E-mail da conta de servico da Balanca.")
    parser.add_argument(
        "--balanca-api-password",
        default=BALANCA_API_PASSWORD,
        help="Senha da conta de servico da Balanca.",
    )
    parser.add_argument(
        "--balanca-api-timeout",
        type=float,
        default=BALANCA_API_TIMEOUT_SECONDS,
        help="Timeout em segundos para consultar a API da Balanca.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula a sincronizacao sem gravar dados.")
    parser.add_argument("--no-backup", action="store_true", help="Nao cria backup antes de gravar.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        if DB_ENGINE in {"postgres", "postgresql"}:
            result = sync_balanca_master_data(
                notas_db_path=args.notas_db,
                balanca_db_path=args.balanca_db,
                balanca_api_url=args.balanca_api_url,
                balanca_api_token=args.balanca_api_token,
                balanca_api_email=args.balanca_api_email,
                balanca_api_password=args.balanca_api_password,
                balanca_api_timeout=args.balanca_api_timeout,
                source=args.source,
                dry_run=True,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        with tempfile.TemporaryDirectory(prefix="app-notas-sync-dry-run-") as temp_dir:
            temp_db = Path(temp_dir) / "notas-dry-run.db"
            backup_sqlite_file(args.notas_db, temp_db)
            result = sync_balanca_master_data(
                notas_db_path=temp_db,
                balanca_db_path=args.balanca_db,
                balanca_api_url=args.balanca_api_url,
                balanca_api_token=args.balanca_api_token,
                balanca_api_email=args.balanca_api_email,
                balanca_api_password=args.balanca_api_password,
                balanca_api_timeout=args.balanca_api_timeout,
                source=args.source,
                dry_run=False,
            )
            result["dry_run"] = True
            result["destino"] = str(Path(args.notas_db))
            result["simulado_em"] = str(temp_db)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

    backup_path: Path | None = None
    if not args.no_backup:
        backup_path = create_sync_backup(args.notas_db)

    result = sync_balanca_master_data(
        notas_db_path=args.notas_db,
        balanca_db_path=args.balanca_db,
        balanca_api_url=args.balanca_api_url,
        balanca_api_token=args.balanca_api_token,
        balanca_api_email=args.balanca_api_email,
        balanca_api_password=args.balanca_api_password,
        balanca_api_timeout=args.balanca_api_timeout,
        source=args.source,
        dry_run=False,
    )
    if backup_path:
        result["backup"] = str(backup_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
