import logging
import os
import sys
import traceback

from app_config import get_runtime_config


def configurar_ambiente_qt() -> None:
    if os.getenv("QT_QPA_PLATFORM"):
        return

    runtime_config = get_runtime_config()
    configured_platform = str(runtime_config.get("qt_platform") or "").strip()
    if configured_platform:
        os.environ["QT_QPA_PLATFORM"] = configured_platform
        return

    session_type = os.getenv("XDG_SESSION_TYPE", "").strip().lower()
    if sys.platform.startswith("linux") and session_type == "wayland" and os.getenv("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


configurar_ambiente_qt()

from PyQt5 import QtWidgets

# Função para gravar a "caixa-preta" em caso de erro fatal
def gravar_relatorio_de_crash(exctype, value, tb):
    """Grava qualquer exceção não tratada em um arquivo de log."""
    agora = traceback.format_exc()
    logging.basicConfig(filename='crash_report.log', level=logging.ERROR, filemode='w')
    logging.critical("A aplicação encontrou um erro fatal e foi encerrada.")
    logging.critical(agora)
    # Mostra o erro para o usuário também, se possível
    error_message = f"Ocorreu um erro crítico:\n\n{agora}"
    QtWidgets.QMessageBox.critical(None, "Erro Fatal", error_message)

# Instala nosso gravador de crash como o manipulador padrão de exceções
sys.excepthook = gravar_relatorio_de_crash

def executar_aplicacao() -> int:
    from melhorias_programa import (
        configurar_logger,
        aplicar_melhorias_globais,
        verificar_dependencias_obrigatorias,
    )
    from funcoes_colaboradores import garantir_schema_banco
    from MainWindow import MainWindow

    configurar_logger()
    runtime_config = get_runtime_config()
    logging.info("Engine do banco: %s", runtime_config["db_engine"])
    logging.info("Banco ativo: %s", runtime_config["db_target"])
    logging.info("Storage raiz: %s", runtime_config["storage_root"])
    logging.info("QT_QPA_PLATFORM: %s", os.getenv("QT_QPA_PLATFORM", "auto"))
    verificar_dependencias_obrigatorias()
    garantir_schema_banco()

    app = QtWidgets.QApplication(sys.argv)
    aplicar_melhorias_globais(app)
    logging.info("Plataforma Qt em uso: %s", app.platformName())

    window = MainWindow()
    window.show()

    return app.exec_()


def main() -> int:
    try:
        return executar_aplicacao()
    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        gravar_relatorio_de_crash(exc_type, exc_value, exc_traceback)
        return 1


if __name__ == "__main__":
    sys.exit(main())
