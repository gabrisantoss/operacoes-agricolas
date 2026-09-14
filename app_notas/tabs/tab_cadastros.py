from __future__ import annotations

import re

from PyQt5 import QtCore, QtWidgets

from app_logging import get_logger
from backup_manager import executar_backup, listar_backups_disponiveis
from database import DB
from styles import aplicar_icone, configure_table
from table_models import GenericTableModel, TextFilterProxyModel
from workers import BackgroundTask


LOGGER = get_logger(__name__)

ACOES_CORRECAO = {
    "Data de colheita = data de plantio": "colheita_para_plantio",
    "Definir data de colheita": "definir_colheita",
    "Definir data de plantio": "definir_plantio",
    "Definir as duas datas": "definir_ambas",
}


class TabCadastros(QtWidgets.QWidget):
    def __init__(self, db, main_window=None):
        super().__init__()
        self.db = db
        self.main = main_window
        self.worker = None
        self._progress_dialog = None
        self._dados_carregados = False
        self._correcao_preview_token = None
        self._setup_models()
        self._setup_ui()

    def _setup_models(self) -> None:
        self.model_mot = GenericTableModel(["Codigo", "Nome"], parent=self)
        self.proxy_mot = TextFilterProxyModel(self)
        self.proxy_mot.setSourceModel(self.model_mot)

        self.model_faz = GenericTableModel(["Codigo", "Nome"], parent=self)
        self.proxy_faz = TextFilterProxyModel(self)
        self.proxy_faz.setSourceModel(self.model_faz)

        self.model_var = GenericTableModel(["ID", "Nome"], parent=self)
        self.proxy_var = TextFilterProxyModel(self)
        self.proxy_var.setSourceModel(self.model_var)

        self.model_preview_correcao = GenericTableModel(
            [
                "Nota",
                "Origem",
                "Destino",
                "Colheita atual",
                "Colheita nova",
                "Plantio atual",
                "Plantio novo",
                "Alterado",
            ],
            parent=self,
        )
        self.proxy_preview_correcao = TextFilterProxyModel(self)
        self.proxy_preview_correcao.setSourceModel(self.model_preview_correcao)

        self.model_logs_correcao = GenericTableModel(
            [
                "Aplicado em",
                "Nota",
                "Acao",
                "Motivo",
                "Colheita ant.",
                "Colheita nova",
                "Plantio ant.",
                "Plantio nova",
                "Backup",
            ],
            parent=self,
        )

    def _setup_ui(self) -> None:
        self.setObjectName("PageRoot")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        hero = QtWidgets.QFrame()
        hero.setObjectName("ToolbarCard")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(14, 10, 14, 10)
        hero_layout.setSpacing(4)
        titulo = QtWidgets.QLabel("Administracao do Sistema")
        titulo.setObjectName("PageTitle")
        subtitulo = QtWidgets.QLabel("Gerencie backups, referencias e correcoes operacionais sem sair do painel principal.")
        subtitulo.setObjectName("PageSubtitle")
        subtitulo.setWordWrap(True)
        hero_layout.addWidget(titulo)
        hero_layout.addWidget(subtitulo)
        layout.addWidget(hero)

        gb_admin = QtWidgets.QFrame()
        gb_admin.setObjectName("ToolbarCard")
        layout_admin = QtWidgets.QVBoxLayout(gb_admin)
        layout_admin.setContentsMargins(14, 12, 14, 12)
        layout_admin.setSpacing(10)

        linha_backup = QtWidgets.QHBoxLayout()
        linha_backup.setSpacing(8)
        lbl_info = QtWidgets.QLabel("Backup e recuperacao")
        lbl_info.setObjectName("SectionTitle")

        self.btn_backup = QtWidgets.QPushButton(" Fazer backup agora")
        self.btn_backup.setObjectName("PrimaryButton")
        self.btn_backup.setCursor(QtCore.Qt.PointingHandCursor)
        aplicar_icone(self.btn_backup, "fa5s.cloud-upload-alt")
        self.btn_backup.clicked.connect(self.fazer_backup_manual)

        self.btn_refresh_backups = QtWidgets.QPushButton(" Atualizar lista")
        self.btn_refresh_backups.setObjectName("SecondaryButton")
        aplicar_icone(self.btn_refresh_backups, "fa5s.sync-alt")
        self.btn_refresh_backups.clicked.connect(self.carregar_backups_disponiveis)

        self.btn_restore = QtWidgets.QPushButton(" Restaurar selecionado")
        self.btn_restore.setObjectName("DangerButton")
        aplicar_icone(self.btn_restore, "fa5s.history")
        self.btn_restore.clicked.connect(self.restaurar_backup_selecionado)

        self.cb_backups = QtWidgets.QComboBox()
        self.cb_backups.setMinimumWidth(260)
        self.cb_backups.setMinimumHeight(40)
        self.cb_backups.setMinimumContentsLength(24)
        self.cb_backups.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.lbl_backup_status = QtWidgets.QLabel("")
        self.lbl_backup_status.setObjectName("WindowSubtitle")
        self.lbl_backup_status.setWordWrap(True)

        for botao in (self.btn_backup, self.btn_refresh_backups, self.btn_restore):
            botao.setMinimumHeight(40)
            botao.setMinimumWidth(0)

        linha_backup.addWidget(lbl_info)
        linha_backup.addWidget(self.btn_backup)
        linha_backup.addWidget(self.btn_refresh_backups)
        linha_backup.addStretch()

        linha_restore = QtWidgets.QHBoxLayout()
        linha_restore.setSpacing(8)
        lbl_restore = QtWidgets.QLabel("Backups disponiveis:")
        lbl_restore.setObjectName("FormLabel")
        linha_restore.addWidget(lbl_restore)
        linha_restore.addWidget(self.cb_backups, 1)
        linha_restore.addWidget(self.btn_restore)

        layout_admin.addLayout(linha_backup)
        layout_admin.addLayout(linha_restore)
        layout_admin.addWidget(self.lbl_backup_status)
        layout.addWidget(gb_admin)

        self.tabs_internas = QtWidgets.QTabWidget()
        self.tabs_internas.setDocumentMode(True)
        layout.addWidget(self.tabs_internas, 1)

        self.tab_motoristas = QtWidgets.QWidget()
        self._setup_motoristas()
        self.tabs_internas.addTab(self.tab_motoristas, "Motoristas")

        self.tab_fazendas = QtWidgets.QWidget()
        self._setup_fazendas()
        self.tabs_internas.addTab(self.tab_fazendas, "Fazendas")

        self.tab_variedades = QtWidgets.QWidget()
        self._setup_variedades()
        self.tabs_internas.addTab(self.tab_variedades, "Variedades")

        self.tab_correcoes = QtWidgets.QWidget()
        self._setup_correcoes()
        self.tabs_internas.addTab(self.tab_correcoes, "Correcoes")

        self.lbl_backup_status.setText("Backups serao carregados ao abrir esta aba.")

    def _criar_dialogo_progresso(self, titulo: str, mensagem: str, worker: BackgroundTask) -> QtWidgets.QProgressDialog:
        dialog = QtWidgets.QProgressDialog(mensagem, "Cancelar", 0, 100, self)
        dialog.setWindowTitle(titulo)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(worker.cancelar)
        return dialog

    def _iniciar_worker(
        self,
        *,
        worker: BackgroundTask,
        titulo: str,
        mensagem: str,
        on_success,
        on_error,
        on_cancel=None,
        disable_main: bool = False,
    ) -> None:
        if self.worker and self.worker.isRunning():
            QtWidgets.QMessageBox.information(self, "Aguarde", "Ja existe uma operacao em andamento.")
            return

        self.worker = worker
        for botao in (
            self.btn_backup,
            self.btn_restore,
            self.btn_preview_correcao,
            self.btn_aplicar_correcao,
            self.btn_logs_correcao,
        ):
            botao.setEnabled(False)
        self._progress_dialog = self._criar_dialogo_progresso(titulo, mensagem, worker)
        worker.progresso.connect(self._atualizar_progresso)
        worker.concluido.connect(on_success)
        worker.erro.connect(on_error)
        worker.cancelado.connect(on_cancel or self._on_operacao_cancelada)
        worker.finished.connect(lambda: self._finalizar_worker(disable_main=disable_main))
        if disable_main and self.main and hasattr(self.main, "setEnabled"):
            self.main.setEnabled(False)
        worker.start()
        self._progress_dialog.show()

    def _atualizar_progresso(self, valor: int, mensagem: str) -> None:
        dialog = self._progress_dialog
        if dialog is None:
            return
        dialog.setValue(valor)
        if mensagem:
            dialog.setLabelText(mensagem)

    def _finalizar_worker(self, disable_main: bool = False) -> None:
        if disable_main and self.main and hasattr(self.main, "setEnabled"):
            self.main.setEnabled(True)
        for botao in (
            self.btn_backup,
            self.btn_restore,
            self.btn_preview_correcao,
            self.btn_aplicar_correcao,
            self.btn_logs_correcao,
        ):
            botao.setEnabled(True)
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None
        if self.worker:
            self.worker.deleteLater()
            self.worker = None

    def _on_operacao_cancelada(self, mensagem: str) -> None:
        QtWidgets.QMessageBox.information(self, "Cancelado", mensagem)

    def fazer_backup_manual(self) -> None:
        self._iniciar_worker(
            worker=BackgroundTask(self._tarefa_backup_manual),
            titulo="Fazendo backup",
            mensagem="Preparando backup...",
            on_success=self.on_backup_finished,
            on_error=self._on_backup_error,
        )

    @staticmethod
    def _tarefa_backup_manual(progress, is_cancelled):
        mensagem, sucesso = executar_backup(progress=progress, is_cancelled=is_cancelled)
        return {"mensagem": mensagem, "sucesso": sucesso}

    def on_backup_finished(self, resultado: dict) -> None:
        self.btn_backup.setEnabled(True)
        self.carregar_backups_disponiveis()
        mensagem = resultado["mensagem"]
        if resultado["sucesso"]:
            QtWidgets.QMessageBox.information(self, "Backup concluido", mensagem)
        else:
            QtWidgets.QMessageBox.warning(self, "Falha no backup", mensagem)

    def _on_backup_error(self, mensagem: str) -> None:
        self.btn_backup.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel concluir o backup:\n{mensagem}")

    def carregar_backups_disponiveis(self) -> None:
        self.cb_backups.clear()
        backups = listar_backups_disponiveis()
        for item in backups:
            data_txt = QtCore.QDateTime.fromSecsSinceEpoch(int(item["mtime"])).toString("dd/MM/yyyy HH:mm")
            label = f"{item['origem']} | {data_txt} | {item['nome']}"
            self.cb_backups.addItem(label, str(item["path"]))

        if backups:
            self.lbl_backup_status.setText(f"{len(backups)} backup(s) disponiveis para restauracao.")
        else:
            self.lbl_backup_status.setText("Nenhum backup encontrado ainda.")

    def restaurar_backup_selecionado(self) -> None:
        caminho = self.cb_backups.currentData()
        if not caminho:
            QtWidgets.QMessageBox.warning(self, "Aviso", "Selecione um backup para restaurar.")
            return

        resposta = QtWidgets.QMessageBox.question(
            self,
            "Restaurar backup",
            "Essa acao substitui os dados atuais pelos dados do backup selecionado.\n\nDeseja continuar?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if resposta != QtWidgets.QMessageBox.Yes:
            return

        self._iniciar_worker(
            worker=BackgroundTask(self._tarefa_restaurar_backup, caminho),
            titulo="Restaurando backup",
            mensagem="Preparando restauracao...",
            on_success=self._on_restore_finished,
            on_error=self._on_restore_error,
            disable_main=True,
        )

    def _tarefa_restaurar_backup(self, caminho: str, progress, is_cancelled):
        if is_cancelled():
            return None
        progress(20, "Fechando conexoes e restaurando banco...")
        self.db.restore_from_backup(caminho)
        progress(100, "Backup restaurado.")
        return {"caminho": caminho}

    def _on_restore_finished(self, _resultado: dict) -> None:
        self.recarregar_tabelas()
        if self.main:
            self.main.recarregar_dados_apos_restore()
        QtWidgets.QMessageBox.information(self, "Sucesso", "Backup restaurado com sucesso.")

    def _on_restore_error(self, mensagem: str) -> None:
        LOGGER.exception("Falha ao restaurar backup")
        QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel restaurar o backup:\n{mensagem}")

    def _setup_motoristas(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.tab_motoristas)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form_card = QtWidgets.QFrame()
        form_card.setObjectName("ToolbarCard")
        form_card_layout = QtWidgets.QVBoxLayout(form_card)
        form_card_layout.setContentsMargins(12, 10, 12, 10)
        form_card_layout.setSpacing(8)

        form_layout = QtWidgets.QHBoxLayout()
        form_layout.setSpacing(8)
        self.ed_mot_cod = QtWidgets.QLineEdit()
        self.ed_mot_cod.setPlaceholderText("Codigo (ex: 1050)")
        self.ed_mot_cod.setMinimumHeight(40)
        self.ed_mot_nome = QtWidgets.QLineEdit()
        self.ed_mot_nome.setPlaceholderText("Nome do motorista")
        self.ed_mot_nome.setMinimumHeight(40)
        btn_add = QtWidgets.QPushButton("Adicionar")
        btn_add.setObjectName("SuccessButton")
        btn_add.setMinimumHeight(40)
        btn_add.clicked.connect(self.add_motorista)

        self.ed_mot_busca = QtWidgets.QLineEdit()
        self.ed_mot_busca.setPlaceholderText("Filtrar motoristas...")
        self.ed_mot_busca.setMinimumHeight(40)
        self.ed_mot_busca.textChanged.connect(lambda text: self._filtrar_proxy(self.proxy_mot, text))

        lbl_cod = QtWidgets.QLabel("Cod:")
        lbl_cod.setObjectName("FormLabel")
        lbl_nome = QtWidgets.QLabel("Nome:")
        lbl_nome.setObjectName("FormLabel")
        form_layout.addWidget(lbl_cod)
        form_layout.addWidget(self.ed_mot_cod)
        form_layout.addWidget(lbl_nome)
        form_layout.addWidget(self.ed_mot_nome)
        form_layout.addWidget(btn_add)
        form_card_layout.addLayout(form_layout)
        form_card_layout.addWidget(self.ed_mot_busca)
        layout.addWidget(form_card)

        self.tb_mot = QtWidgets.QTableView()
        self.tb_mot.setModel(self.proxy_mot)
        self.tb_mot.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        configure_table(self.tb_mot, stretch_last=True)
        self.tb_mot.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.tb_mot, 1)

        btn_del = QtWidgets.QPushButton("Excluir selecionado")
        btn_del.setObjectName("SecondaryButton")
        btn_del.setMinimumHeight(40)
        btn_del.clicked.connect(lambda: self.excluir_item("motoristas", self.tb_mot, self.proxy_mot, self.model_mot))
        layout.addWidget(btn_del)

    def add_motorista(self) -> None:
        codigo = self.ed_mot_cod.text().strip()
        nome = self.ed_mot_nome.text().strip()
        if not codigo or not nome:
            return
        try:
            self.db.adicionar_motorista(codigo, nome)
            self.carregar_motoristas()
            self.ed_mot_cod.clear()
            self.ed_mot_nome.clear()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Erro", str(exc))

    def carregar_motoristas(self) -> None:
        self.model_mot.set_rows([[str(row[0]), str(row[1])] for row in self.db.listar_motoristas()])

    def _setup_fazendas(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.tab_fazendas)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form_card = QtWidgets.QFrame()
        form_card.setObjectName("ToolbarCard")
        form_card_layout = QtWidgets.QVBoxLayout(form_card)
        form_card_layout.setContentsMargins(12, 10, 12, 10)
        form_card_layout.setSpacing(8)

        form_layout = QtWidgets.QHBoxLayout()
        form_layout.setSpacing(8)
        self.ed_faz_cod = QtWidgets.QLineEdit()
        self.ed_faz_cod.setPlaceholderText("Codigo (ex: 100-001)")
        self.ed_faz_cod.setMinimumHeight(40)
        self.ed_faz_nome = QtWidgets.QLineEdit()
        self.ed_faz_nome.setPlaceholderText("Nome da fazenda")
        self.ed_faz_nome.setMinimumHeight(40)
        btn_add = QtWidgets.QPushButton("Adicionar")
        btn_add.setObjectName("SuccessButton")
        btn_add.setMinimumHeight(40)
        btn_add.clicked.connect(self.add_fazenda)

        self.ed_faz_busca = QtWidgets.QLineEdit()
        self.ed_faz_busca.setPlaceholderText("Filtrar fazendas...")
        self.ed_faz_busca.setMinimumHeight(40)
        self.ed_faz_busca.textChanged.connect(lambda text: self._filtrar_proxy(self.proxy_faz, text))

        lbl_cod = QtWidgets.QLabel("Cod:")
        lbl_cod.setObjectName("FormLabel")
        lbl_nome = QtWidgets.QLabel("Nome:")
        lbl_nome.setObjectName("FormLabel")
        form_layout.addWidget(lbl_cod)
        form_layout.addWidget(self.ed_faz_cod)
        form_layout.addWidget(lbl_nome)
        form_layout.addWidget(self.ed_faz_nome)
        form_layout.addWidget(btn_add)
        form_card_layout.addLayout(form_layout)
        form_card_layout.addWidget(self.ed_faz_busca)
        layout.addWidget(form_card)

        self.tb_faz = QtWidgets.QTableView()
        self.tb_faz.setModel(self.proxy_faz)
        self.tb_faz.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        configure_table(self.tb_faz, stretch_last=True)
        self.tb_faz.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.tb_faz, 1)

        btn_del = QtWidgets.QPushButton("Excluir selecionado")
        btn_del.setObjectName("SecondaryButton")
        btn_del.setMinimumHeight(40)
        btn_del.clicked.connect(lambda: self.excluir_item("fazendas", self.tb_faz, self.proxy_faz, self.model_faz))
        layout.addWidget(btn_del)

    def add_fazenda(self) -> None:
        codigo = self.ed_faz_cod.text().strip()
        nome = self.ed_faz_nome.text().strip()
        if not codigo or not nome:
            return
        try:
            self.db.adicionar_fazenda(codigo, nome)
            self.carregar_fazendas()
            self.ed_faz_cod.clear()
            self.ed_faz_nome.clear()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Erro", str(exc))

    def carregar_fazendas(self) -> None:
        self.model_faz.set_rows([[str(row[0]), str(row[1])] for row in self.db.listar_fazendas()])

    def _setup_variedades(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.tab_variedades)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form_card = QtWidgets.QFrame()
        form_card.setObjectName("ToolbarCard")
        form_card_layout = QtWidgets.QVBoxLayout(form_card)
        form_card_layout.setContentsMargins(12, 10, 12, 10)
        form_card_layout.setSpacing(8)

        form_layout = QtWidgets.QHBoxLayout()
        form_layout.setSpacing(8)
        self.ed_var_nome = QtWidgets.QLineEdit()
        self.ed_var_nome.setPlaceholderText("Nome da variedade")
        self.ed_var_nome.setMinimumHeight(40)
        btn_add = QtWidgets.QPushButton("Adicionar")
        btn_add.setObjectName("SuccessButton")
        btn_add.setMinimumHeight(40)
        btn_add.clicked.connect(self.add_variedade)

        self.ed_var_busca = QtWidgets.QLineEdit()
        self.ed_var_busca.setPlaceholderText("Filtrar variedades...")
        self.ed_var_busca.setMinimumHeight(40)
        self.ed_var_busca.textChanged.connect(lambda text: self._filtrar_proxy(self.proxy_var, text))

        lbl_nome = QtWidgets.QLabel("Nome:")
        lbl_nome.setObjectName("FormLabel")
        form_layout.addWidget(lbl_nome)
        form_layout.addWidget(self.ed_var_nome)
        form_layout.addWidget(btn_add)
        form_card_layout.addLayout(form_layout)
        form_card_layout.addWidget(self.ed_var_busca)
        layout.addWidget(form_card)

        self.tb_var = QtWidgets.QTableView()
        self.tb_var.setModel(self.proxy_var)
        self.tb_var.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        configure_table(self.tb_var, stretch_last=True)
        self.tb_var.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.tb_var, 1)

        btn_del = QtWidgets.QPushButton("Excluir selecionado")
        btn_del.setObjectName("SecondaryButton")
        btn_del.setMinimumHeight(40)
        btn_del.clicked.connect(lambda: self.excluir_item("variedades", self.tb_var, self.proxy_var, self.model_var))
        layout.addWidget(btn_del)

    def add_variedade(self) -> None:
        nome = self.ed_var_nome.text().strip()
        if not nome:
            return
        try:
            self.db.adicionar_variedade(nome)
            self.carregar_variedades()
            self.ed_var_nome.clear()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Erro", str(exc))

    def carregar_variedades(self) -> None:
        self.model_var.set_rows([[str(row[0]), str(row[1])] for row in self.db.listar_variedades()])

    def _setup_correcoes(self) -> None:
        outer_layout = QtWidgets.QVBoxLayout(self.tab_correcoes)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)

        content_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        card = QtWidgets.QFrame()
        card.setObjectName("SummaryCard")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        titulo = QtWidgets.QLabel("Correcao segura de datas")
        titulo.setObjectName("SectionTitle")
        subtitulo = QtWidgets.QLabel(
            "Selecione as notas, visualize o antes/depois, gere backup automatico e grave auditoria da alteracao."
        )
        subtitulo.setObjectName("SectionHint")
        subtitulo.setWordWrap(True)
        card_layout.addWidget(titulo)
        card_layout.addWidget(subtitulo)
        layout.addWidget(card)

        form_card = QtWidgets.QFrame()
        form_card.setObjectName("ToolbarCard")
        form_card_layout = QtWidgets.QVBoxLayout(form_card)
        form_card_layout.setContentsMargins(12, 10, 12, 10)
        form_card_layout.setSpacing(8)

        form = QtWidgets.QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        lbl_notas = QtWidgets.QLabel("Notas:")
        lbl_notas.setObjectName("FormLabel")
        self.txt_correcao_notas = QtWidgets.QPlainTextEdit()
        self.txt_correcao_notas.setPlaceholderText("Cole numeros separados por virgula, espaco ou uma nota por linha.")
        self.txt_correcao_notas.setMaximumHeight(88)

        lbl_acao = QtWidgets.QLabel("Acao:")
        lbl_acao.setObjectName("FormLabel")
        self.cb_correcao_acao = QtWidgets.QComboBox()
        self.cb_correcao_acao.addItems(ACOES_CORRECAO.keys())
        self.cb_correcao_acao.currentIndexChanged.connect(self._atualizar_estado_data_correcao)
        self.cb_correcao_acao.setMinimumHeight(40)

        lbl_data = QtWidgets.QLabel("Nova data:")
        lbl_data.setObjectName("FormLabel")
        self.dt_correcao = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.dt_correcao.setCalendarPopup(True)
        self.dt_correcao.setDisplayFormat("dd/MM/yyyy")
        self.dt_correcao.setMinimumHeight(40)

        lbl_motivo = QtWidgets.QLabel("Motivo:")
        lbl_motivo.setObjectName("FormLabel")
        self.ed_correcao_motivo = QtWidgets.QLineEdit()
        self.ed_correcao_motivo.setPlaceholderText("Ex.: data digitada errada na carga inicial")
        self.ed_correcao_motivo.setMinimumHeight(40)

        self.btn_preview_correcao = QtWidgets.QPushButton(" Prever alteracoes")
        self.btn_preview_correcao.setObjectName("PrimaryButton")
        self.btn_preview_correcao.setMinimumHeight(40)
        aplicar_icone(self.btn_preview_correcao, "fa5s.search")
        self.btn_preview_correcao.clicked.connect(self.previsualizar_correcao)

        self.btn_aplicar_correcao = QtWidgets.QPushButton(" Aplicar correcao")
        self.btn_aplicar_correcao.setObjectName("DangerButton")
        self.btn_aplicar_correcao.setMinimumHeight(40)
        aplicar_icone(self.btn_aplicar_correcao, "fa5s.check-circle")
        self.btn_aplicar_correcao.clicked.connect(self.aplicar_correcao)

        self.btn_logs_correcao = QtWidgets.QPushButton(" Atualizar logs")
        self.btn_logs_correcao.setObjectName("SecondaryButton")
        self.btn_logs_correcao.setMinimumHeight(40)
        aplicar_icone(self.btn_logs_correcao, "fa5s.history")
        self.btn_logs_correcao.clicked.connect(self.carregar_logs_correcao)

        self.lbl_correcao_status = QtWidgets.QLabel("Informe as notas e gere uma previsao antes de aplicar.")
        self.lbl_correcao_status.setObjectName("WindowSubtitle")
        self.lbl_correcao_status.setWordWrap(True)

        form.addWidget(lbl_notas, 0, 0)
        form.addWidget(self.txt_correcao_notas, 0, 1, 2, 3)
        form.addWidget(lbl_acao, 2, 0)
        form.addWidget(self.cb_correcao_acao, 2, 1)
        form.addWidget(lbl_data, 2, 2)
        form.addWidget(self.dt_correcao, 2, 3)
        form.addWidget(lbl_motivo, 3, 0)
        form.addWidget(self.ed_correcao_motivo, 3, 1, 1, 3)
        form.addWidget(self.btn_preview_correcao, 4, 1)
        form.addWidget(self.btn_aplicar_correcao, 4, 2)
        form.addWidget(self.btn_logs_correcao, 4, 3)
        form_card_layout.addLayout(form)
        form_card_layout.addWidget(self.lbl_correcao_status)
        layout.addWidget(form_card)

        lbl_preview = QtWidgets.QLabel("Preview da correcao")
        lbl_preview.setObjectName("SectionTitle")
        layout.addWidget(lbl_preview)

        self.tb_preview_correcao = QtWidgets.QTableView()
        self.tb_preview_correcao.setModel(self.proxy_preview_correcao)
        self.tb_preview_correcao.setMinimumHeight(120)
        self.tb_preview_correcao.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        configure_table(self.tb_preview_correcao, stretch_last=True)
        self.tb_preview_correcao.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.tb_preview_correcao, 1)

        lbl_logs = QtWidgets.QLabel("Auditoria recente")
        lbl_logs.setObjectName("SectionTitle")
        layout.addWidget(lbl_logs)

        self.tb_logs_correcao = QtWidgets.QTableView()
        self.tb_logs_correcao.setModel(self.model_logs_correcao)
        self.tb_logs_correcao.setMinimumHeight(120)
        self.tb_logs_correcao.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        configure_table(self.tb_logs_correcao, stretch_last=True)
        self.tb_logs_correcao.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.tb_logs_correcao, 1)

        self._atualizar_estado_data_correcao()

        scroll.setWidget(content_widget)
        outer_layout.addWidget(scroll)

    def _filtrar_proxy(self, proxy: TextFilterProxyModel, text: str) -> None:
        proxy.set_filter_columns([0, 1])
        proxy.set_filter_text(text)

    def _parse_numeros_correcao(self) -> list[int]:
        texto = self.txt_correcao_notas.toPlainText()
        numeros = [int(item) for item in re.findall(r"\d+", texto)]
        return sorted(set(numeros))

    def _acao_correcao_codigo(self) -> str:
        return ACOES_CORRECAO[self.cb_correcao_acao.currentText()]

    def _nova_data_correcao_sql(self) -> str | None:
        acao = self._acao_correcao_codigo()
        if acao == "colheita_para_plantio":
            return None
        return self.dt_correcao.date().toString("yyyy-MM-dd")

    def _atualizar_estado_data_correcao(self) -> None:
        precisa_data = self._acao_correcao_codigo() != "colheita_para_plantio"
        self.dt_correcao.setEnabled(precisa_data)

    def previsualizar_correcao(self) -> None:
        numeros = self._parse_numeros_correcao()
        if not numeros:
            QtWidgets.QMessageBox.warning(self, "Aviso", "Informe ao menos uma nota para a correcao.")
            return

        try:
            resultado = self.db.preview_correcao_notas(
                numeros,
                self._acao_correcao_codigo(),
                self._nova_data_correcao_sql(),
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel gerar o preview:\n{exc}")
            return

        rows = []
        for item in resultado["preview"]:
            rows.append(
                [
                    str(item["numero"]),
                    item["faz_muda"],
                    item["faz_plantio"],
                    item["data_colheita_atual"] or "",
                    item["data_colheita_nova"] or "",
                    item["data_plantio_atual"] or "",
                    item["data_plantio_nova"] or "",
                    "Sim" if item["alterado"] else "Nao",
                ]
            )
        self.model_preview_correcao.set_rows(rows)
        self._correcao_preview_token = resultado.get("preview_token")

        faltantes = resultado["faltantes"]
        alterados = sum(1 for item in resultado["preview"] if item["alterado"])
        partes = [f"{len(resultado['preview'])} nota(s) encontrada(s)", f"{alterados} com alteracao real"]
        if faltantes:
            partes.append(f"{len(faltantes)} nao encontrada(s): {', '.join(str(numero) for numero in faltantes[:10])}")
        self.lbl_correcao_status.setText(" | ".join(partes))

    def aplicar_correcao(self) -> None:
        numeros = self._parse_numeros_correcao()
        if not numeros:
            QtWidgets.QMessageBox.warning(self, "Aviso", "Informe ao menos uma nota para a correcao.")
            return
        if not self._correcao_preview_token:
            QtWidgets.QMessageBox.warning(
                self,
                "Aviso",
                "Gere a prévia antes de aplicar a correção.",
            )
            return

        resposta = QtWidgets.QMessageBox.question(
            self,
            "Aplicar correcao",
            "A correcao vai gerar backup automatico antes de alterar os registros.\n\nDeseja continuar?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if resposta != QtWidgets.QMessageBox.Yes:
            return

        self._iniciar_worker(
            worker=BackgroundTask(
                self._tarefa_aplicar_correcao,
                numeros,
                self._acao_correcao_codigo(),
                self._nova_data_correcao_sql(),
                self.ed_correcao_motivo.text().strip(),
                self._correcao_preview_token,
            ),
            titulo="Aplicando correcao",
            mensagem="Gerando backup preventivo...",
            on_success=self._on_correcao_finished,
            on_error=self._on_correcao_error,
            disable_main=True,
        )

    def _tarefa_aplicar_correcao(
        self, numeros, acao, nova_data, motivo, preview_token, progress, is_cancelled
    ):
        if is_cancelled():
            return None
        # A conexao principal pertence a thread da UI. A tarefa de fundo usa
        # uma conexao propria, e o token e revalidado sob lock transacional.
        background_db = DB(path=self.db.path, seed_from_excel=False)
        try:
            progress(40, "Validando prévia e gerando backup preventivo...")
            resultado = background_db.aplicar_correcao_notas(
                numeros,
                acao,
                nova_data=nova_data,
                motivo=motivo,
                expected_preview_token=preview_token,
            )
            progress(100, "Correcao aplicada.")
            return {"resultado": resultado}
        finally:
            background_db.close()

    def _on_correcao_finished(self, payload: dict) -> None:
        self._correcao_preview_token = None
        self.recarregar_tabelas()
        self.carregar_logs_correcao()
        self.previsualizar_correcao()
        if self.main:
            try:
                if hasattr(self.main, "tab_hist"):
                    self.main.tab_hist.carregar_dados(self.main.tab_hist._usar_filtro_atual)
                if hasattr(self.main, "tab_rel"):
                    self.main.tab_rel.gerar_dashboard()
                if hasattr(self.main, "_atualizar_contadores"):
                    self.main._atualizar_contadores()
            except Exception:
                LOGGER.exception("Falha ao recarregar telas apos correcao")

        resultado = payload["resultado"]
        mensagem = (
            f"Correcao aplicada em {resultado['quantidade_alterada']} nota(s).\n\n"
            f"Backup: {resultado['backup_path']}"
        )
        if resultado["quantidade_faltante"]:
            faltantes = ", ".join(str(numero) for numero in resultado["faltantes"][:10])
            mensagem += f"\n\nNotas nao encontradas: {faltantes}"
        QtWidgets.QMessageBox.information(self, "Correcao concluida", mensagem)

    def _on_correcao_error(self, mensagem: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel aplicar a correcao:\n{mensagem}")

    def carregar_logs_correcao(self) -> None:
        rows = []
        for row in self.db.listar_logs_correcao(limit=50):
            rows.append(
                [
                    str(row["aplicado_em"] or ""),
                    str(row["nota_numero"] or ""),
                    str(row["acao"] or ""),
                    str(row["motivo"] or ""),
                    str(row["data_colheita_ant"] or ""),
                    str(row["data_colheita_nova"] or ""),
                    str(row["data_plantio_ant"] or ""),
                    str(row["data_plantio_nova"] or ""),
                    str(row["backup_path"] or ""),
                ]
            )
        self.model_logs_correcao.set_rows(rows)

    def recarregar_tabelas(self) -> None:
        self._dados_carregados = True
        self.carregar_motoristas()
        self.carregar_fazendas()
        self.carregar_variedades()
        self.carregar_backups_disponiveis()
        self.carregar_logs_correcao()

    def carregar_inicial(self) -> None:
        if not self._dados_carregados:
            self.recarregar_tabelas()

    def excluir_item(self, tabela: str, widget_tabela, proxy: TextFilterProxyModel, model: GenericTableModel) -> None:
        index = widget_tabela.currentIndex()
        if not index.isValid():
            QtWidgets.QMessageBox.warning(self, "Aviso", "Selecione uma linha.")
            return

        source_index = proxy.mapToSource(index)
        valor_id = model.row_values(source_index.row())[0]
        resposta = QtWidgets.QMessageBox.question(
            self,
            "Confirmacao",
            "Tem certeza que deseja excluir o item selecionado?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if resposta != QtWidgets.QMessageBox.Yes:
            return

        try:
            self.db.excluir_cadastro(tabela, valor_id)
            if tabela == "motoristas":
                self.carregar_motoristas()
            elif tabela == "fazendas":
                self.carregar_fazendas()
            elif tabela == "variedades":
                self.carregar_variedades()
        except Exception as exc:
            LOGGER.exception("Falha ao excluir item de %s", tabela)
            QtWidgets.QMessageBox.critical(self, "Erro", f"Erro ao excluir item:\n{exc}")
