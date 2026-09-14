from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt5 import QtCore

from app_logging import get_logger


LOGGER = get_logger(__name__)


class TaskCancelledError(RuntimeError):
    pass


class BackgroundTask(QtCore.QThread):
    progresso = QtCore.pyqtSignal(int, str)
    concluido = QtCore.pyqtSignal(object)
    erro = QtCore.pyqtSignal(str)
    cancelado = QtCore.pyqtSignal(str)

    def __init__(self, alvo: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.alvo = alvo
        self.args = args
        self.kwargs = kwargs
        self._cancel_event = threading.Event()

    def cancelar(self) -> None:
        self._cancel_event.set()

    def cancelado_pelo_usuario(self) -> bool:
        return self._cancel_event.is_set()

    def reportar_progresso(self, valor: int, mensagem: str = "") -> None:
        progresso = max(0, min(100, int(valor)))
        self.progresso.emit(progresso, str(mensagem))

    def run(self) -> None:
        try:
            resultado = self.alvo(
                *self.args,
                progress=self.reportar_progresso,
                is_cancelled=self.cancelado_pelo_usuario,
                **self.kwargs,
            )
            if self.cancelado_pelo_usuario():
                self.cancelado.emit("Operacao cancelada.")
                return
            self.concluido.emit(resultado)
        except TaskCancelledError as exc:
            self.cancelado.emit(str(exc) or "Operacao cancelada.")
        except Exception as exc:
            LOGGER.exception("Falha em tarefa executada em background")
            self.erro.emit(str(exc))
