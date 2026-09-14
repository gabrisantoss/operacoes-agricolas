from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
import qtawesome as qta

from app_config import APP_ROOT
from app_logging import get_logger
from styles import PREMIUM_STYLESHEET
from tabs.tab_cadastros import TabCadastros
from tabs.tab_historico import TabHistorico
from tabs.tab_lancamento import TabLancamento
from tabs.tab_logistica_cadastros import TabLogisticaCadastros
from tabs.tab_relatorios import AbaRelatorios
from workers import BackgroundTask


LOGGER = get_logger(__name__)
BACKUP_DIR = APP_ROOT / "backups"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, db, internet_ok: bool | None = None):
        super().__init__()
        self.db = db
        self.internet_ok = internet_ok
        self._allow_close = False
        self._close_worker = None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        self.setStyleSheet(PREMIUM_STYLESHEET)
        self.setWindowTitle("Operacoes Agricolas | Sistema de Notas e Transporte")
        # Algumas abas geram size hints altos; sem um minimo explicito,
        # o window manager passa a tratar a janela como nao-redimensionavel.
        self.setMinimumSize(1, 1)
        self.resize(1360, 760)

        self._setup_ui()
        self._setup_atalhos()
        self._atualizar_contadores()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return

        if self._close_worker and self._close_worker.isRunning():
            event.ignore()
            return

        self.status.showMessage("Gerando backup final antes de fechar...", 0)
        self._close_worker = BackgroundTask(self._tarefa_backup_fechamento)
        self._close_worker.concluido.connect(self._on_close_backup_done)
        self._close_worker.erro.connect(self._on_close_backup_error)
        self._close_worker.cancelado.connect(self._on_close_backup_cancelled)
        self._close_worker.finished.connect(self._finalizar_fechamento)
        self._close_worker.start()
        event.ignore()

    def _tarefa_backup_fechamento(self, progress, is_cancelled):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        caminho_local = BACKUP_DIR / f"backup_{timestamp}.db"
        if is_cancelled():
            return None
        progress(10, "Criando backup final...")
        self.db.create_backup(caminho_local)
        progress(100, "Backup final concluido.")
        return str(caminho_local)

    def _on_close_backup_done(self, caminho: str | None) -> None:
        if caminho:
            LOGGER.info("Backup final criado em %s", caminho)

    def _on_close_backup_error(self, mensagem: str) -> None:
        LOGGER.exception("Falha ao criar backup local ao fechar janela")
        self.status.showMessage(f"Falha no backup final: {mensagem}", 4000)

    def _on_close_backup_cancelled(self, mensagem: str) -> None:
        LOGGER.warning("Backup final cancelado: %s", mensagem)

    def _finalizar_fechamento(self) -> None:
        if self._close_worker:
            self._close_worker.deleteLater()
            self._close_worker = None
        self._allow_close = True
        self.close()

    def _setup_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("PageRoot")
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        header = QtWidgets.QFrame()
        header.setObjectName("CardSoft")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(12)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QtWidgets.QLabel("Operacoes Agricolas")
        lbl_title.setObjectName("WindowTitle")
        lbl_subtitle = QtWidgets.QLabel("Sistema de Notas e Transporte | safra, historico e relatorios")
        lbl_subtitle.setObjectName("WindowSubtitle")
        lbl_subtitle.setWordWrap(True)
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_subtitle)

        status_box = QtWidgets.QHBoxLayout()
        status_box.setSpacing(8)
        self.lbl_internet = QtWidgets.QLabel()
        self.lbl_backup = QtWidgets.QLabel("Backup local ativo")
        self.lbl_backup.setObjectName("StatusChipNeutral")
        for label in (self.lbl_internet, self.lbl_backup):
            label.setMinimumHeight(34)
            label.setAlignment(QtCore.Qt.AlignCenter)
        status_box.addWidget(self.lbl_internet)
        status_box.addWidget(self.lbl_backup)

        header_layout.addLayout(title_box, 1)
        header_layout.addLayout(status_box)
        layout.addWidget(header)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.tab_lanc = TabLancamento(self.db, self)
        self.tabs.addTab(self.tab_lanc, qta.icon("fa5s.edit"), " Lancamento (F12)")

        self.tab_hist = TabHistorico(self.db, self)
        self.tabs.addTab(self.tab_hist, qta.icon("fa5s.list"), " Historico (F5)")

        self.tab_rel = AbaRelatorios(self.db, self)
        self.tabs.addTab(self.tab_rel, qta.icon("fa5s.chart-line"), " BI e Relatorios")

        self.tab_cad = TabCadastros(self.db, self)
        self.tabs.addTab(self.tab_cad, qta.icon("fa5s.plus-circle"), " Cadastros")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Codigo mantido importado para facilitar futura reativacao.

        self.status = QtWidgets.QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.setStatusBar(self.status)

        self.lbl_hj = QtWidgets.QLabel("Hoje: 0")
        self.lbl_hj.setObjectName("StatusMetricGreen")
        self.lbl_tot = QtWidgets.QLabel("Total: 0")
        self.lbl_tot.setObjectName("StatusMetricBlue")
        self.status.addPermanentWidget(self.lbl_hj)
        self.status.addPermanentWidget(self.lbl_tot)
        self.status.showMessage("Sistema pronto.", 3000)
        self.set_internet_status(self.internet_ok)

    def set_internet_status(self, internet_ok: bool | None) -> None:
        self.internet_ok = internet_ok
        if internet_ok is None:
            texto = "Verificando conexao"
            object_name = "StatusChipNeutral"
        elif internet_ok:
            texto = "Online"
            object_name = "StatusChipOnline"
        else:
            texto = "Offline"
            object_name = "StatusChipOffline"

        self.lbl_internet.setText(texto)
        self.lbl_internet.setObjectName(object_name)
        self.lbl_internet.style().unpolish(self.lbl_internet)
        self.lbl_internet.style().polish(self.lbl_internet)
        self.lbl_internet.update()

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.tab_hist:
            self.tab_hist.carregar_inicial()
        elif widget is self.tab_rel:
            self.tab_rel.carregar_inicial()
        elif widget is self.tab_cad:
            self.tab_cad.carregar_inicial()

    def _setup_atalhos(self) -> None:
        QtWidgets.QShortcut(
            QtGui.QKeySequence("F12"),
            self,
            activated=lambda: self.tabs.setCurrentWidget(self.tab_lanc),
        )
        QtWidgets.QShortcut(
            QtGui.QKeySequence("F5"),
            self,
            activated=lambda: self.tab_hist.carregar_dados(self.tab_hist._usar_filtro_atual),
        )
        QtWidgets.QShortcut(
            QtGui.QKeySequence("Esc"),
            self,
            activated=self._handle_escape,
        )
        QtWidgets.QShortcut(
            QtGui.QKeySequence("F11"),
            self,
            activated=self._toggle_fullscreen,
        )

    def _handle_escape(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
            self.status.showMessage("Modo tela cheia desativado. Pressione F11 para ativar novamente.", 4000)
            return

        self.tab_lanc._limpar()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
            self.status.showMessage("Modo tela cheia desativado.", 3000)
            return

        self.showFullScreen()
        self.status.showMessage("Modo tela cheia ativado.", 3000)

    def _atualizar_contadores(self) -> None:
        try:
            hoje_sql = date.today().strftime("%Y-%m-%d")
            total = self.db.contar_notas_total()
            hoje = self.db.contar_notas_data(hoje_sql)
            self.lbl_tot.setText(f" Total: {total} ")
            self.lbl_hj.setText(f" Hoje: {hoje} ")
        except Exception:
            LOGGER.exception("Falha ao atualizar contadores da janela principal")

    def reabrir_lancamento_para_nota(self, numero) -> None:
        self.tabs.setCurrentWidget(self.tab_lanc)
        self.tab_lanc.carregar_nota_para_edicao(numero)

    def recarregar_dados_apos_restore(self) -> None:
        for action in (
            self.tab_lanc.recarregar_referencias,
            lambda: self.tab_hist.carregar_dados(False),
            self.tab_rel.gerar_dashboard,
            self.tab_cad.recarregar_tabelas,
        ):
            try:
                action()
            except Exception:
                LOGGER.exception("Falha ao recarregar dados apos restauracao")

        self._atualizar_contadores()
        self.status.showMessage("Dados recarregados apos restauracao do backup.", 4000)
