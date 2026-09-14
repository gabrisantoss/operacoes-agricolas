from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore

from app_config import APP_ROOT, BACKUP_DRIVE_PATH, DATABASE_URL, DB_ENGINE, DB_PATH, MAX_BACKUPS, MAX_LOCAL_BACKUPS
from app_logging import get_logger
from database import DB, backup_sqlite_file, sqlite_integrity_status


LOGGER = get_logger(__name__)
PASTA_LOCAL = APP_ROOT / "backups"


def listar_backups_disponiveis() -> list[dict]:
    itens: list[dict] = []
    for origem, pasta in (("Local", PASTA_LOCAL), ("Drive", BACKUP_DRIVE_PATH)):
        pasta_path = Path(pasta)
        if not pasta_path.exists():
            continue

        for arquivo in list(pasta_path.glob("*.db")) + list(pasta_path.glob("*.dump")):
            try:
                itens.append(
                    {
                        "origem": origem,
                        "path": arquivo,
                        "nome": arquivo.name,
                        "mtime": arquivo.stat().st_mtime,
                    }
                )
            except OSError:
                LOGGER.exception("Falha ao listar backup em %s", arquivo)

    itens.sort(key=lambda item: item["mtime"], reverse=True)
    return itens


def encontrar_backup_recente_integro() -> dict | None:
    for item in listar_backups_disponiveis():
        try:
            if item["path"].suffix.lower() == ".dump":
                if DB_ENGINE in {"postgres", "postgresql"} and item["path"].stat().st_size > 0:
                    return item
                continue
            if sqlite_integrity_status(item["path"]).lower() == "ok":
                return item
        except Exception:
            LOGGER.exception("Falha ao validar backup %s", item["path"])
    return None


def _limpar_antigos(pasta: Path, limite: int) -> None:
    if limite <= 0 or not pasta.exists():
        return

    arquivos = sorted(
        (
            arquivo
            for padrao in ("transporte_20*.db", "transporte_20*.dump")
            for arquivo in pasta.glob(padrao)
            if arquivo.is_file()
        ),
        key=lambda arquivo: arquivo.stat().st_mtime,
        reverse=True,
    )

    for arquivo in arquivos[limite:]:
        try:
            arquivo.unlink()
        except OSError:
            LOGGER.exception("Falha ao remover backup antigo %s", arquivo)


def executar_backup(
    db_path: str | Path = DB_PATH,
    *,
    progress=None,
    is_cancelled=None,
) -> tuple[str, bool]:
    db_path = Path(db_path)
    is_postgres = DB_ENGINE in {"postgres", "postgresql"}
    if not is_postgres and not db_path.exists():
        return f"Banco de dados '{db_path}' nao encontrado.", False
    if is_postgres and not DATABASE_URL:
        return "APP_NOTAS_DATABASE_URL nao configurada para backup PostgreSQL.", False

    cancelar = is_cancelled or (lambda: False)
    reportar = progress or (lambda *_args, **_kwargs: None)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    extensao = ".dump" if is_postgres else ".db"
    nome_historico = f"transporte_{timestamp}{extensao}"
    local_historico = PASTA_LOCAL / nome_historico
    drive_historico = Path(BACKUP_DRIVE_PATH) / nome_historico
    drive_atual = Path(BACKUP_DRIVE_PATH) / f"transporte_ATUAL{extensao}"

    PASTA_LOCAL.mkdir(parents=True, exist_ok=True)

    sucesso_local = False
    sucesso_drive = False
    erros: list[str] = []

    if cancelar():
        return "Backup cancelado.", False

    reportar(10, "Criando backup local...")
    try:
        if is_postgres:
            db = DB(seed_from_excel=False)
            try:
                db.create_backup(local_historico)
            finally:
                db.close()
        else:
            backup_sqlite_file(db_path, local_historico)
        sucesso_local = True
    except Exception as exc:
        erros.append(f"Local: {exc}")
        LOGGER.exception("Falha ao criar backup local")

    if cancelar():
        return "Backup cancelado.", False

    reportar(55, "Criando backup no Drive...")
    try:
        Path(BACKUP_DRIVE_PATH).mkdir(parents=True, exist_ok=True)
        if is_postgres:
            db = DB(seed_from_excel=False)
            try:
                db.create_backup(drive_historico)
                db.create_backup(drive_atual)
            finally:
                db.close()
        else:
            backup_sqlite_file(db_path, drive_historico)
            backup_sqlite_file(db_path, drive_atual)
        sucesso_drive = True
    except Exception as exc:
        erros.append(f"Drive: {exc}")
        LOGGER.exception("Falha ao criar backup no Drive")

    reportar(85, "Limpando backups antigos...")
    _limpar_antigos(PASTA_LOCAL, MAX_LOCAL_BACKUPS)
    _limpar_antigos(Path(BACKUP_DRIVE_PATH), MAX_BACKUPS)
    reportar(100, "Backup concluido.")

    if sucesso_local or sucesso_drive:
        destinos = []
        if sucesso_local:
            destinos.append("local")
        if sucesso_drive:
            destinos.append("Drive")
        msg = f"Backup concluido com sucesso em {', '.join(destinos)}."
        if erros:
            msg += f" Falhas parciais: {' | '.join(erros)}"
        return msg, True

    return "Falha ao criar backup. " + " | ".join(erros), False


class BackupWorker(QtCore.QThread):
    finalizado = QtCore.pyqtSignal(str, bool)

    def __init__(self, db_path: str | Path = DB_PATH):
        super().__init__()
        self.db_path = Path(db_path)

    def run(self) -> None:
        msg, sucesso = executar_backup(self.db_path)
        self.finalizado.emit(msg, sucesso)
