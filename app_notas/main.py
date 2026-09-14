from __future__ import annotations

import os
import sys

if (
    not os.environ.get("QT_QPA_PLATFORM")
    and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    and os.environ.get("DISPLAY")
    and not os.environ.get("APP_NOTAS_USE_NATIVE_WAYLAND")
):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

import requests
from PyQt5 import QtCore, QtWidgets

from app_logging import get_logger, setup_logging
from app_config import DB_ENGINE, DB_PATH
from backup_manager import BackupWorker, encontrar_backup_recente_integro
from database import DB, DatabaseCorruptionError, restore_sqlite_backup
from main_window import MainWindow
from styles import apply_theme


LOGGER = get_logger(__name__)


class SplashScreen(QtWidgets.QSplashScreen):
    def __init__(self):
        super().__init__()
        self.setFixedSize(540, 320)
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(24, 24, 24, 24)

        self.frame = QtWidgets.QFrame()
        self.frame.setObjectName("Card")

        frame_layout = QtWidgets.QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(34, 34, 34, 34)

        self.lbl_titulo = QtWidgets.QLabel("SISTEMA DE TRANSPORTE")
        titulo_font = self.lbl_titulo.font()
        titulo_font.setPointSize(24)
        titulo_font.setBold(True)
        self.lbl_titulo.setFont(titulo_font)
        self.lbl_titulo.setAlignment(QtCore.Qt.AlignCenter)

        self.lbl_subtitulo = QtWidgets.QLabel("Safra 2026 | Operacao de Campo")
        subtitulo_font = self.lbl_subtitulo.font()
        subtitulo_font.setPointSize(11)
        subtitulo_font.setBold(True)
        self.lbl_subtitulo.setFont(subtitulo_font)
        self.lbl_subtitulo.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_subtitulo.setObjectName("SplashSubtitle")

        self.lbl_status = QtWidgets.QLabel("Iniciando componentes...")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(18)

        frame_layout.addStretch(1)
        frame_layout.addWidget(self.lbl_titulo, alignment=QtCore.Qt.AlignCenter)
        frame_layout.addWidget(self.lbl_subtitulo, alignment=QtCore.Qt.AlignCenter)
        frame_layout.addStretch(1)
        frame_layout.addWidget(self.lbl_status)
        frame_layout.addWidget(self.progress)
        frame_layout.addStretch(1)

        self.layout.addWidget(self.frame)

    def update_progress(self, value: int, message: str) -> None:
        self.progress.setValue(int(value))
        self.lbl_status.setText(message)
        QtWidgets.QApplication.processEvents()


class InternetChecker(QtCore.QThread):
    finished = QtCore.pyqtSignal(bool)

    def run(self) -> None:
        try:
            requests.get("https://clients3.google.com/generate_204", timeout=2)
            self.finished.emit(True)
        except Exception:
            LOGGER.info("Aplicacao iniciou em modo offline", exc_info=True)
            self.finished.emit(False)


def _mostrar_erro_fatal(titulo: str, mensagem: str) -> None:
    caixa = QtWidgets.QMessageBox()
    caixa.setIcon(QtWidgets.QMessageBox.Critical)
    caixa.setWindowTitle(titulo)
    caixa.setText(mensagem)
    caixa.exec_()


def _tentar_recuperar_banco_corrompido(exc: DatabaseCorruptionError) -> DB | None:
    if DB_ENGINE in {"postgres", "postgresql"}:
        _mostrar_erro_fatal(
            "Banco indisponivel",
            (
                "O Sistema de Notas esta configurado para PostgreSQL.\n\n"
                "A recuperacao automatica por arquivo SQLite nao se aplica neste modo.\n"
                "Pare os sistemas e restaure um dump PostgreSQL pelo procedimento operacional de banco."
            ),
        )
        return None

    backup = encontrar_backup_recente_integro()
    if not backup:
        _mostrar_erro_fatal(
            "Banco corrompido",
            (
                "O banco de dados atual esta corrompido e nenhum backup integro foi encontrado.\n\n"
                f"Arquivo afetado:\n{exc.path}\n\n"
                f"Detalhes:\n{exc.details}"
            ),
        )
        return None

    data_txt = QtCore.QDateTime.fromSecsSinceEpoch(int(backup["mtime"])).toString(
        "dd/MM/yyyy HH:mm"
    )
    resposta = QtWidgets.QMessageBox.question(
        None,
        "Banco corrompido",
        (
            "Foi detectada corrupcao no banco de dados principal.\n\n"
            f"Arquivo:\n{exc.path}\n\n"
            f"Detalhes:\n{exc.details}\n\n"
            "Foi encontrado um backup integro mais recente:\n"
            f"{backup['origem']} | {data_txt} | {backup['nome']}\n\n"
            "Deseja restaurar esse backup agora?\n"
            "O arquivo atual sera preservado com o sufixo '.corrompido_<data>'."
        ),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.Yes,
    )
    if resposta != QtWidgets.QMessageBox.Yes:
        return None

    try:
        _, quarantined = restore_sqlite_backup(DB_PATH, backup["path"])
        if quarantined:
            LOGGER.warning(
                "Banco corrompido movido para quarentena em %s e restaurado a partir de %s",
                quarantined,
                backup["path"],
            )
        else:
            LOGGER.warning(
                "Banco restaurado a partir de %s sem arquivo anterior para quarentena",
                backup["path"],
            )
        return DB()
    except Exception as restore_exc:
        LOGGER.exception("Falha ao restaurar backup automaticamente")
        _mostrar_erro_fatal(
            "Falha na recuperacao",
            "Nao foi possivel restaurar o backup automaticamente.\n\n"
            f"Backup usado:\n{backup['path']}\n\n"
            f"Erro:\n{restore_exc}",
        )
        return None


def main() -> int:
    setup_logging()
    LOGGER.info("Inicializando aplicacao")

    app = QtWidgets.QApplication(sys.argv)
    apply_theme(app)
    LOGGER.info("Qt platform em uso: %s", app.platformName())

    splash = SplashScreen()
    splash.show()
    splash.update_progress(10, "Carregando banco de dados...")

    try:
        db = DB()
    except DatabaseCorruptionError as exc:
        LOGGER.exception("Banco corrompido detectado na inicializacao")
        db = _tentar_recuperar_banco_corrompido(exc)
        if db is None:
            return 1
    except Exception as exc:
        LOGGER.exception("Erro fatal ao iniciar banco")
        _mostrar_erro_fatal("Erro ao abrir banco", f"Nao foi possivel abrir o banco:\n{exc}")
        return 1

    refs: dict[str, object] = {"window": None, "backup_thread": None}

    def start_backup(window: MainWindow) -> None:
        if refs.get("backup_thread") is not None:
            return

        backup_thread = BackupWorker()
        refs["backup_thread"] = backup_thread
        backup_thread.finalizado.connect(
            lambda msg, sucesso: LOGGER.info(
                "Backup automatico: %s | sucesso=%s",
                msg,
                sucesso,
            )
        )
        backup_thread.finalizado.connect(
            lambda msg, _sucesso: window.status.showMessage(msg, 5000)
        )
        backup_thread.start()

    def start_main_app() -> None:
        try:
            splash.update_progress(100, "Abrindo sistema...")
            splash.close()

            window = MainWindow(db, internet_ok=None)
            refs["window"] = window
            window.show()
            QtCore.QTimer.singleShot(1200, lambda: start_backup(window))

            checker = InternetChecker()
            refs["checker"] = checker
            checker.finished.connect(on_check_finished)
            checker.start()
        except Exception as exc:
            LOGGER.exception("Erro fatal ao abrir janela principal")
            _mostrar_erro_fatal("Erro ao abrir sistema", f"Nao foi possivel abrir a janela principal:\n{exc}")
            app.quit()

    def on_check_finished(is_connected: bool) -> None:
        window = refs.get("window")
        if isinstance(window, MainWindow):
            window.set_internet_status(is_connected)
            if is_connected:
                window.status.showMessage("Conexao verificada.", 3000)
            else:
                window.status.showMessage("Modo offline ativo. O sistema continua disponivel.", 5000)
            return

    start_main_app()

    exit_code = app.exec_()
    try:
        db.close()
    except Exception:
        LOGGER.exception("Falha ao fechar conexao com banco")
    LOGGER.info("Aplicacao encerrada")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
