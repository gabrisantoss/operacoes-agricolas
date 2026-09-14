from PyQt5 import QtCore, QtGui, QtWidgets

from core.cnh_management import (
    ACOMPANHAMENTO_LABELS,
    ACOMPANHAMENTO_ORDER,
    STATUS_TECNICO_LABELS,
    STATUS_TECNICO_ORDER,
    exportar_lista_cobranca_excel,
    exportar_painel_cnh_excel,
    gerar_resumo_cnh,
    listar_acompanhamentos_cnh,
    listar_historico_cnh,
    listar_opcoes_painel_cnh,
    listar_painel_cnh,
)
from funcoes_colaboradores import (
    DB_PATH,
    obter_colaborador_por_codigo,
    registrar_acompanhamento_cnh,
    registrar_renovacao_cnh,
)
from ui.ProfileWindow import ProfileWindow


def _build_chip(texto: str, tone: str, compact: bool = False) -> QtWidgets.QLabel:
    chip = QtWidgets.QLabel(texto)
    chip.setObjectName("statusChip")
    chip.setProperty("tone", tone)
    chip.setProperty("compact", compact)
    chip.setAlignment(QtCore.Qt.AlignCenter)
    chip.setMinimumHeight(22 if compact else 28)
    chip.setContentsMargins(10, 4, 10, 4)
    return chip


class ResumoCard(QtWidgets.QFrame):
    def __init__(self, titulo: str, subtitulo: str, severity: str):
        super().__init__()
        self.setObjectName("summaryCard")
        self.setProperty("severity", severity)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self.lbl_titulo = QtWidgets.QLabel(titulo)
        self.lbl_titulo.setObjectName("metricLabel")
        self.lbl_valor = QtWidgets.QLabel("0")
        self.lbl_valor.setObjectName("metricValue")
        self.lbl_subtitulo = QtWidgets.QLabel(subtitulo)
        self.lbl_subtitulo.setObjectName("detailHint")
        self.lbl_subtitulo.setWordWrap(True)

        layout.addWidget(self.lbl_titulo)
        layout.addWidget(self.lbl_valor)
        layout.addWidget(self.lbl_subtitulo)

    def set_valor(self, valor: int):
        self.lbl_valor.setText(str(valor))


class TabCNH(QtWidgets.QWidget):
    def __init__(self, main_window: QtWidgets.QMainWindow):
        super().__init__()
        self.main_window = main_window
        self._linhas = []
        self._comprovante_selecionado = ""
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.carregar_dados)

        self._setup_ui()
        self._carregar_filtros()
        self.carregar_dados()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(18)

        hero = QtWidgets.QFrame()
        hero.setObjectName("heroPanel")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(8)

        eyebrow = QtWidgets.QLabel("Central operacional")
        eyebrow.setObjectName("heroEyebrow")
        hero_layout.addWidget(eyebrow)

        titulo = QtWidgets.QLabel("CNH e pendências com contexto de operação")
        titulo.setObjectName("heroTitle")
        hero_layout.addWidget(titulo)

        subtitulo = QtWidgets.QLabel(
            "A fila abaixo prioriza cobrança, acompanhamento, renovação e regularização sem descartar função, frente, gestor e histórico do colaborador."
        )
        subtitulo.setObjectName("heroSubtitle")
        subtitulo.setWordWrap(True)
        hero_layout.addWidget(subtitulo)

        legenda = QtWidgets.QHBoxLayout()
        legenda.setSpacing(8)
        legenda.addWidget(_build_chip("Vencida", "danger"))
        legenda.addWidget(_build_chip("7 dias", "warning"))
        legenda.addWidget(_build_chip("30 dias", "caution"))
        legenda.addWidget(_build_chip("Regularizada", "success"))
        legenda.addWidget(_build_chip("Sem ação", "neutral"))
        legenda.addStretch()
        hero_layout.addLayout(legenda)
        layout.addWidget(hero)

        self.cards_layout = QtWidgets.QHBoxLayout()
        self.card_pendentes = ResumoCard("Pendências", "Cobrança e regularização em aberto.", "danger")
        self.card_vencidas = ResumoCard("Vencidas", "Casos que já impedem conformidade.", "danger")
        self.card_criticas = ResumoCard("7 dias", "Exigem ação imediata.", "warning")
        self.card_alerta = ResumoCard("30 dias", "Planejamento e agendamento.", "caution")
        self.card_sem_validade = ResumoCard("Sem validade", "Ausência ou data inválida.", "neutral")
        self.card_inconsistencias = ResumoCard("Inconsistências", "Cadastro que precisa revisão.", "neutral")
        for card in (
            self.card_pendentes,
            self.card_vencidas,
            self.card_criticas,
            self.card_alerta,
            self.card_sem_validade,
            self.card_inconsistencias,
        ):
            self.cards_layout.addWidget(card)
        layout.addLayout(self.cards_layout)

        filtros = QtWidgets.QGroupBox("Fila operacional de CNH")
        filtros.setObjectName("filterPanel")
        filtros_layout = QtWidgets.QGridLayout(filtros)

        filtros_layout.addWidget(QtWidgets.QLabel("Busca"), 0, 0)
        self.filtro_busca = QtWidgets.QLineEdit()
        self.filtro_busca.setPlaceholderText("Nome, matrícula, telefone, gestor ou frente")
        filtros_layout.addWidget(self.filtro_busca, 0, 1, 1, 3)

        filtros_layout.addWidget(QtWidgets.QLabel("Status técnico"), 1, 0)
        self.combo_status_tecnico = QtWidgets.QComboBox()
        self.combo_status_tecnico.addItem("Todos", "")
        for status in STATUS_TECNICO_ORDER:
            self.combo_status_tecnico.addItem(STATUS_TECNICO_LABELS[status], status)
        filtros_layout.addWidget(self.combo_status_tecnico, 1, 1)

        filtros_layout.addWidget(QtWidgets.QLabel("Acompanhamento"), 1, 2)
        self.combo_status_acomp = QtWidgets.QComboBox()
        self.combo_status_acomp.addItem("Todos", "")
        for status in ACOMPANHAMENTO_ORDER:
            self.combo_status_acomp.addItem(ACOMPANHAMENTO_LABELS[status], status)
        filtros_layout.addWidget(self.combo_status_acomp, 1, 3)

        filtros_layout.addWidget(QtWidgets.QLabel("Frente"), 2, 0)
        self.combo_frente = QtWidgets.QComboBox()
        self.combo_frente.addItem("Todas", "")
        filtros_layout.addWidget(self.combo_frente, 2, 1)

        filtros_layout.addWidget(QtWidgets.QLabel("Gestor"), 2, 2)
        self.combo_gestor = QtWidgets.QComboBox()
        self.combo_gestor.addItem("Todos", "")
        filtros_layout.addWidget(self.combo_gestor, 2, 3)

        self.check_somente_pendentes = QtWidgets.QCheckBox("Mostrar apenas pendências operacionais")
        self.check_somente_pendentes.setChecked(True)
        filtros_layout.addWidget(self.check_somente_pendentes, 3, 0, 1, 2)

        self.btn_recarregar = QtWidgets.QPushButton("Atualizar fila")
        self.btn_recarregar.setObjectName("ghostAction")
        self.btn_exportar_cobranca = QtWidgets.QPushButton("Exportar lista de cobrança")
        self.btn_exportar_cobranca.setObjectName("secondaryAction")
        self.btn_exportar_painel = QtWidgets.QPushButton("Exportar painel completo")
        self.btn_exportar_painel.setObjectName("ghostAction")
        filtros_layout.addWidget(self.btn_recarregar, 3, 2)
        filtros_layout.addWidget(self.btn_exportar_cobranca, 3, 3)
        filtros_layout.addWidget(self.btn_exportar_painel, 3, 4)
        layout.addWidget(filtros)

        corpo = QtWidgets.QSplitter()
        corpo.setChildrenCollapsible(False)
        corpo.setHandleWidth(10)

        painel_esquerdo = QtWidgets.QWidget()
        painel_esquerdo.setObjectName("operationsPane")
        painel_esquerdo_layout = QtWidgets.QVBoxLayout(painel_esquerdo)
        painel_esquerdo_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_selecao = QtWidgets.QLabel("Selecione um ou mais colaboradores para acompanhar a CNH.")
        self.lbl_selecao.setObjectName("detailHint")
        painel_esquerdo_layout.addWidget(self.lbl_selecao)

        self.tabela = QtWidgets.QTableWidget()
        self.tabela.setObjectName("queueTable")
        self.tabela.setColumnCount(11)
        self.tabela.setHorizontalHeaderLabels(
            [
                "Prioridade",
                "Código",
                "Nome",
                "Validade",
                "Categoria",
                "Status Técnico",
                "Acompanhamento",
                "Frente",
                "Gestor",
                "Telefone",
                "Inconsistências",
            ]
        )
        self.tabela.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tabela.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header = self.tabela.horizontalHeader()
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(10, QtWidgets.QHeaderView.Stretch)
        painel_esquerdo_layout.addWidget(self.tabela)

        painel_direito = QtWidgets.QScrollArea()
        painel_direito.setWidgetResizable(True)
        painel_direito.setObjectName("detailScroll")
        detalhe = QtWidgets.QWidget()
        detalhe_layout = QtWidgets.QVBoxLayout(detalhe)
        detalhe_layout.setSpacing(16)

        self.detail_hero = QtWidgets.QFrame()
        self.detail_hero.setObjectName("profileHero")
        detail_hero_layout = QtWidgets.QVBoxLayout(self.detail_hero)
        detail_hero_layout.setContentsMargins(20, 18, 20, 18)
        detail_hero_layout.setSpacing(8)
        self.lbl_nome = QtWidgets.QLabel("-")
        self.lbl_nome.setObjectName("heroTitle")
        self.lbl_codigo = QtWidgets.QLabel("-")
        self.lbl_codigo.setObjectName("heroSubtitle")
        detail_hero_layout.addWidget(self.lbl_nome)
        detail_hero_layout.addWidget(self.lbl_codigo)
        chip_row = QtWidgets.QHBoxLayout()
        self.detail_status_chip = _build_chip("-", "neutral")
        self.detail_acomp_chip = _build_chip("-", "neutral")
        chip_row.addWidget(self.detail_status_chip)
        chip_row.addWidget(self.detail_acomp_chip)
        chip_row.addStretch()
        detail_hero_layout.addLayout(chip_row)
        detalhe_layout.addWidget(self.detail_hero)

        group_detalhe = QtWidgets.QGroupBox("Contexto operacional")
        group_detalhe.setObjectName("panelGroup")
        detalhe_grid = QtWidgets.QGridLayout(group_detalhe)
        self.lbl_funcao = QtWidgets.QLabel("-")
        self.lbl_funcao.setObjectName("detailValue")
        self.lbl_local = QtWidgets.QLabel("-")
        self.lbl_local.setObjectName("detailValue")
        self.lbl_contato = QtWidgets.QLabel("-")
        self.lbl_contato.setObjectName("detailValue")
        self.lbl_cnh = QtWidgets.QLabel("-")
        self.lbl_cnh.setObjectName("detailValue")
        self.lbl_acomp = QtWidgets.QLabel("-")
        self.lbl_acomp.setObjectName("detailValue")
        self.lbl_inconsistencias = QtWidgets.QLabel("-")
        self.lbl_inconsistencias.setObjectName("detailHint")
        self.lbl_inconsistencias.setWordWrap(True)
        campos = [
            ("Função", self.lbl_funcao),
            ("Frente e gestor", self.lbl_local),
            ("Contato", self.lbl_contato),
            ("CNH", self.lbl_cnh),
            ("Acompanhamento", self.lbl_acomp),
            ("Inconsistências", self.lbl_inconsistencias),
        ]
        for idx, (rotulo, widget) in enumerate(campos):
            detalhe_grid.addWidget(QtWidgets.QLabel(rotulo), idx, 0)
            detalhe_grid.addWidget(widget, idx, 1)

        acoes_rapidas = QtWidgets.QHBoxLayout()
        self.btn_ver_ficha = QtWidgets.QPushButton("Abrir ficha")
        self.btn_ver_ficha.setObjectName("ghostAction")
        self.btn_editar_cadastro = QtWidgets.QPushButton("Editar cadastro")
        self.btn_editar_cadastro.setObjectName("ghostAction")
        acoes_rapidas.addWidget(self.btn_ver_ficha)
        acoes_rapidas.addWidget(self.btn_editar_cadastro)
        detalhe_grid.addLayout(acoes_rapidas, len(campos), 0, 1, 2)
        detalhe_layout.addWidget(group_detalhe)

        group_acomp = QtWidgets.QGroupBox("Acompanhamento")
        group_acomp.setObjectName("panelGroup")
        acomp_layout = QtWidgets.QGridLayout(group_acomp)
        self.form_status_acomp = QtWidgets.QComboBox()
        for status in ACOMPANHAMENTO_ORDER:
            self.form_status_acomp.addItem(ACOMPANHAMENTO_LABELS[status], status)
        self.form_responsavel = QtWidgets.QLineEdit()
        self.form_responsavel.setPlaceholderText("Ex: RH / Liderança")
        self.check_data_prevista = QtWidgets.QCheckBox("Definir data prevista")
        self.form_data_prevista = QtWidgets.QDateEdit(calendarPopup=True)
        self.form_data_prevista.setDisplayFormat("dd/MM/yyyy")
        self.form_data_prevista.setDate(QtCore.QDate.currentDate())
        self.form_data_prevista.setEnabled(False)
        self.form_houve_contato = QtWidgets.QCheckBox("Registrar contato nesta ação")
        self.form_observacao = QtWidgets.QTextEdit()
        self.form_observacao.setPlaceholderText("Resumo do contato, retorno do colaborador, documentos pendentes...")
        self.form_observacao.setMaximumHeight(130)
        self.btn_salvar_acomp = QtWidgets.QPushButton("Aplicar acompanhamento")
        self.btn_salvar_acomp.setObjectName("primaryAction")
        self.btn_quick_contato = QtWidgets.QPushButton("Sem retorno")
        self.btn_quick_contato.setObjectName("warningAction")
        self.btn_quick_agendado = QtWidgets.QPushButton("Agendado")
        self.btn_quick_agendado.setObjectName("secondaryAction")
        self.btn_quick_andamento = QtWidgets.QPushButton("Em andamento")
        self.btn_quick_andamento.setObjectName("ghostAction")

        acomp_layout.addWidget(QtWidgets.QLabel("Status"), 0, 0)
        acomp_layout.addWidget(self.form_status_acomp, 0, 1)
        acomp_layout.addWidget(QtWidgets.QLabel("Responsável"), 1, 0)
        acomp_layout.addWidget(self.form_responsavel, 1, 1)
        acomp_layout.addWidget(self.check_data_prevista, 2, 0)
        acomp_layout.addWidget(self.form_data_prevista, 2, 1)
        acomp_layout.addWidget(self.form_houve_contato, 3, 0, 1, 2)
        acomp_layout.addWidget(self.btn_quick_contato, 4, 0)
        acomp_layout.addWidget(self.btn_quick_agendado, 4, 1)
        acomp_layout.addWidget(self.btn_quick_andamento, 5, 0, 1, 2)
        acomp_layout.addWidget(self.form_observacao, 6, 0, 1, 2)
        acomp_layout.addWidget(self.btn_salvar_acomp, 7, 0, 1, 2)
        detalhe_layout.addWidget(group_acomp)

        group_renovacao = QtWidgets.QGroupBox("Renovação e regularização")
        group_renovacao.setObjectName("panelGroup")
        renov_layout = QtWidgets.QGridLayout(group_renovacao)
        self.form_nova_validade = QtWidgets.QDateEdit(calendarPopup=True)
        self.form_nova_validade.setDisplayFormat("dd/MM/yyyy")
        self.form_nova_validade.setDate(QtCore.QDate.currentDate())
        self.form_categoria_nova = QtWidgets.QComboBox()
        self.form_categoria_nova.addItems(["", "A", "B", "AB", "C", "D", "E", "AD", "AE"])
        self.btn_escolher_comprovante = QtWidgets.QPushButton("Anexar comprovante")
        self.btn_escolher_comprovante.setObjectName("ghostAction")
        self.lbl_comprovante = QtWidgets.QLabel("Nenhum arquivo selecionado.")
        self.lbl_comprovante.setObjectName("detailHint")
        self.lbl_comprovante.setWordWrap(True)
        self.btn_registrar_renovacao = QtWidgets.QPushButton("Registrar renovação")
        self.btn_registrar_renovacao.setObjectName("successAction")

        renov_layout.addWidget(QtWidgets.QLabel("Nova validade"), 0, 0)
        renov_layout.addWidget(self.form_nova_validade, 0, 1)
        renov_layout.addWidget(QtWidgets.QLabel("Categoria"), 1, 0)
        renov_layout.addWidget(self.form_categoria_nova, 1, 1)
        renov_layout.addWidget(self.btn_escolher_comprovante, 2, 0, 1, 2)
        renov_layout.addWidget(self.lbl_comprovante, 3, 0, 1, 2)
        renov_layout.addWidget(self.btn_registrar_renovacao, 4, 0, 1, 2)
        detalhe_layout.addWidget(group_renovacao)

        hist_titulo = QtWidgets.QLabel("Histórico de renovações")
        hist_titulo.setObjectName("sectionTitle")
        detalhe_layout.addWidget(hist_titulo)
        self.hist_renovacoes = QtWidgets.QTableWidget()
        self.hist_renovacoes.setColumnCount(5)
        self.hist_renovacoes.setHorizontalHeaderLabels(
            ["Data/Hora", "Validade Anterior", "Nova Validade", "Categoria", "Responsável"]
        )
        self.hist_renovacoes.horizontalHeader().setStretchLastSection(True)
        self.hist_renovacoes.verticalHeader().setVisible(False)
        self.hist_renovacoes.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.hist_renovacoes.setAlternatingRowColors(True)
        detalhe_layout.addWidget(self.hist_renovacoes)

        timeline_titulo = QtWidgets.QLabel("Timeline de acompanhamento")
        timeline_titulo.setObjectName("sectionTitle")
        detalhe_layout.addWidget(timeline_titulo)
        self.hist_acomp = QtWidgets.QTableWidget()
        self.hist_acomp.setColumnCount(5)
        self.hist_acomp.setHorizontalHeaderLabels(
            ["Data/Hora", "Status", "Responsável", "Data Prevista", "Observação"]
        )
        self.hist_acomp.horizontalHeader().setStretchLastSection(True)
        self.hist_acomp.verticalHeader().setVisible(False)
        self.hist_acomp.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.hist_acomp.setAlternatingRowColors(True)
        detalhe_layout.addWidget(self.hist_acomp)
        detalhe_layout.addStretch()

        painel_direito.setWidget(detalhe)

        corpo.addWidget(painel_esquerdo)
        corpo.addWidget(painel_direito)
        corpo.setStretchFactor(0, 3)
        corpo.setStretchFactor(1, 2)
        layout.addWidget(corpo)

        self.filtro_busca.textChanged.connect(lambda: self._search_timer.start(250))
        self.combo_status_tecnico.currentIndexChanged.connect(self.carregar_dados)
        self.combo_status_acomp.currentIndexChanged.connect(self.carregar_dados)
        self.combo_frente.currentIndexChanged.connect(self.carregar_dados)
        self.combo_gestor.currentIndexChanged.connect(self.carregar_dados)
        self.check_somente_pendentes.stateChanged.connect(self.carregar_dados)
        self.btn_recarregar.clicked.connect(self.carregar_dados)
        self.btn_exportar_cobranca.clicked.connect(self._exportar_lista_cobranca)
        self.btn_exportar_painel.clicked.connect(self._exportar_painel)
        self.tabela.itemSelectionChanged.connect(self._on_selection_changed)
        self.tabela.customContextMenuRequested.connect(self._abrir_menu_contexto)
        self.btn_ver_ficha.clicked.connect(self._abrir_ficha)
        self.btn_editar_cadastro.clicked.connect(self._editar_cadastro)
        self.check_data_prevista.toggled.connect(self.form_data_prevista.setEnabled)
        self.btn_salvar_acomp.clicked.connect(self._aplicar_acompanhamento)
        self.btn_quick_contato.clicked.connect(lambda: self._aplicar_preset("SEM_RETORNO", True))
        self.btn_quick_agendado.clicked.connect(lambda: self._aplicar_preset("AGENDADO", True))
        self.btn_quick_andamento.clicked.connect(lambda: self._aplicar_preset("EM_ANDAMENTO", False))
        self.btn_escolher_comprovante.clicked.connect(self._escolher_comprovante)
        self.btn_registrar_renovacao.clicked.connect(self._registrar_renovacao)

    def _carregar_filtros(self):
        opcoes = listar_opcoes_painel_cnh(DB_PATH)
        for combo, itens in ((self.combo_frente, opcoes["frentes"]), (self.combo_gestor, opcoes["gestores"])):
            atual = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Todas" if combo is self.combo_frente else "Todos", "")
            for item in itens:
                combo.addItem(item, item)
            indice = combo.findData(atual)
            combo.setCurrentIndex(indice if indice >= 0 else 0)
            combo.blockSignals(False)

    def _resumo_para_cards(self, resumo: dict):
        contagem = resumo["contagem_tecnica"]
        self.card_pendentes.set_valor(resumo["pendentes"])
        self.card_vencidas.set_valor(contagem["VENCIDA"])
        self.card_criticas.set_valor(contagem["CRITICA_7_DIAS"])
        self.card_alerta.set_valor(contagem["ALERTA_30_DIAS"])
        self.card_sem_validade.set_valor(contagem["SEM_VALIDADE"] + contagem["DATA_INVALIDA"])
        self.card_inconsistencias.set_valor(resumo["inconsistencias"])

    def _row_background(self, linha: dict) -> QtGui.QColor:
        tema = self.main_window.settings.value("tema", "claro") if hasattr(self.main_window, "settings") else "claro"
        if tema == "escuro":
            mapa = {
                "VENCIDA": "#3a2322",
                "DATA_INVALIDA": "#352b28",
                "SEM_VALIDADE": "#2b2d2f",
                "CRITICA_7_DIAS": "#3a2c1f",
                "ALERTA_30_DIAS": "#39331f",
                "REGULAR": "#131d22",
            }
            return QtGui.QColor(mapa.get(linha["status_tecnico"], "#131d22"))

        status = linha["status_tecnico"]
        if status in {"VENCIDA", "DATA_INVALIDA"}:
            return QtGui.QColor("#fff0ed")
        if status == "SEM_VALIDADE":
            return QtGui.QColor("#f1efe9")
        if status == "CRITICA_7_DIAS":
            return QtGui.QColor("#fff5e7")
        if status == "ALERTA_30_DIAS":
            return QtGui.QColor("#fffbea")
        return QtGui.QColor("#fffdf9")

    def _priority_tone(self, prioridade: str) -> str:
        return {
            "Alta": "danger",
            "Média": "warning",
            "Planejamento": "caution",
            "OK": "success",
        }.get(prioridade, "neutral")

    def _status_tone(self, status: str) -> str:
        return {
            "Vencida": "danger",
            "Data inválida": "neutral",
            "Sem validade": "neutral",
            "Vence em 7 dias": "warning",
            "Vence em 30 dias": "caution",
            "Regular": "success",
        }.get(status, "neutral")

    def _acomp_tone(self, status: str) -> str:
        return {
            "Regularizado": "success",
            "Em andamento": "secondary",
            "Agendado": "caution",
            "Sem retorno": "warning",
            "Aguardando documento": "warning",
            "Sem ação": "neutral",
        }.get(status, "neutral")

    def _refresh_chip(self, chip: QtWidgets.QLabel, texto: str, tone: str):
        chip.setText(texto)
        chip.setProperty("tone", tone)
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        chip.update()

    def carregar_dados(self):
        codigos_anteriores = self.codigos_selecionados()
        self._carregar_filtros()
        self._linhas = listar_painel_cnh(
            DB_PATH,
            filtro_busca=self.filtro_busca.text().strip(),
            filtro_status_tecnico=self.combo_status_tecnico.currentData() or "",
            filtro_status_acompanhamento=self.combo_status_acomp.currentData() or "",
            filtro_frente=self.combo_frente.currentData() or "",
            filtro_gestor=self.combo_gestor.currentData() or "",
            somente_pendentes=self.check_somente_pendentes.isChecked(),
        )
        self._preencher_tabela()
        self._resumo_para_cards(gerar_resumo_cnh(DB_PATH))

        if codigos_anteriores:
            self.selecionar_codigo(codigos_anteriores[0])
        else:
            self._on_selection_changed()

    def _preencher_tabela(self):
        self.tabela.setSortingEnabled(False)
        self.tabela.setRowCount(len(self._linhas))
        for row_idx, linha in enumerate(self._linhas):
            cor = self._row_background(linha)

            campos = {
                1: str(linha.get("codigo_colaborador", "")),
                2: str(linha.get("nome", "")),
                3: linha.get("validade_cnh_formatada", "-"),
                4: str(linha.get("categoria_cnh", "") or "-"),
                7: linha.get("frente_exibicao", ""),
                8: linha.get("gestor_exibicao", ""),
                9: str(linha.get("telefone", "")),
                10: linha.get("inconsistencias_texto", ""),
            }
            for col, texto in campos.items():
                item = QtWidgets.QTableWidgetItem(texto)
                item.setBackground(cor)
                if col == 1:
                    item.setData(QtCore.Qt.UserRole, linha.get("codigo_colaborador"))
                if col == 10 and texto:
                    item.setForeground(QtGui.QColor("#8a5d1d"))
                self.tabela.setItem(row_idx, col, item)

            self.tabela.setCellWidget(row_idx, 0, _build_chip(linha["prioridade_label"], self._priority_tone(linha["prioridade_label"]), True))
            self.tabela.setCellWidget(row_idx, 5, _build_chip(linha["status_tecnico_label"], self._status_tone(linha["status_tecnico_label"]), True))
            self.tabela.setCellWidget(row_idx, 6, _build_chip(linha["status_acompanhamento_label"], self._acomp_tone(linha["status_acompanhamento_label"]), True))

        self.tabela.resizeColumnsToContents()

    def codigos_selecionados(self) -> list[str]:
        codigos = []
        for item in self.tabela.selectedItems():
            codigo = self.tabela.item(item.row(), 1).data(QtCore.Qt.UserRole)
            if codigo and codigo not in codigos:
                codigos.append(codigo)
        return codigos

    def _on_selection_changed(self):
        codigos = self.codigos_selecionados()
        if not codigos:
            self.lbl_selecao.setText("Selecione um ou mais colaboradores para acompanhar a CNH.")
            self._limpar_detalhes()
            return

        self.lbl_selecao.setText(
            f"{len(codigos)} colaborador(es) selecionado(s). O acompanhamento pode ser aplicado em massa; a renovação exige seleção única."
        )
        self._carregar_detalhes(codigos[0])

    def _limpar_detalhes(self):
        self.lbl_nome.setText("Nenhum colaborador selecionado")
        self.lbl_codigo.setText("Escolha uma linha para abrir o contexto operacional.")
        self.lbl_funcao.setText("-")
        self.lbl_local.setText("-")
        self.lbl_contato.setText("-")
        self.lbl_cnh.setText("-")
        self.lbl_acomp.setText("-")
        self.lbl_inconsistencias.setText("-")
        self._refresh_chip(self.detail_status_chip, "Sem status", "neutral")
        self._refresh_chip(self.detail_acomp_chip, "Sem ação", "neutral")
        self.hist_renovacoes.setRowCount(0)
        self.hist_acomp.setRowCount(0)

    def _carregar_detalhes(self, codigo_colaborador: str):
        linha = next((item for item in self._linhas if item.get("codigo_colaborador") == codigo_colaborador), None)
        colaborador = obter_colaborador_por_codigo(codigo_colaborador)
        if not linha or not colaborador:
            self._limpar_detalhes()
            return

        self.lbl_nome.setText(str(colaborador.get("nome") or "-"))
        self.lbl_codigo.setText(
            f"Código {colaborador.get('codigo_colaborador', '-')} | {linha.get('funcao_exibicao', '-')} | {linha.get('cidade_exibicao', '-')}"
        )
        self._refresh_chip(self.detail_status_chip, linha.get("status_tecnico_label", "-"), self._status_tone(linha.get("status_tecnico_label", "")))
        self._refresh_chip(self.detail_acomp_chip, linha.get("status_acompanhamento_label", "-"), self._acomp_tone(linha.get("status_acompanhamento_label", "")))

        self.lbl_funcao.setText(str(linha.get("funcao_exibicao") or "-"))
        self.lbl_local.setText(f"{linha.get('frente_exibicao', '-')} | {linha.get('gestor_exibicao', '-')}")
        self.lbl_contato.setText(f"{linha.get('telefone') or '-'} | {linha.get('cidade_exibicao') or '-'}")
        self.lbl_cnh.setText(
            f"{linha.get('categoria_cnh') or '-'} | {linha.get('validade_cnh_formatada') or '-'} | {linha.get('status_tecnico_descricao') or '-'}"
        )
        self.lbl_acomp.setText(
            f"{linha.get('status_acompanhamento_label') or '-'} | Último contato: {linha.get('ultimo_contato_cnh') or '-'}"
        )
        self.lbl_inconsistencias.setText(linha.get("inconsistencias_texto") or "Nenhuma inconsistência detectada.")

        idx_status = self.form_status_acomp.findData(linha.get("status_acompanhamento"))
        self.form_status_acomp.setCurrentIndex(idx_status if idx_status >= 0 else 0)
        self.form_categoria_nova.setCurrentText(str(linha.get("categoria_cnh") or ""))

        data_validade = QtCore.QDate.fromString(str(linha.get("validade_cnh") or ""), "yyyy-MM-dd")
        self.form_nova_validade.setDate(data_validade if data_validade.isValid() else QtCore.QDate.currentDate())

        data_prevista = str(linha.get("data_prevista_regularizacao_cnh") or "")
        if data_prevista:
            self.check_data_prevista.setChecked(True)
            data_prevista_qt = QtCore.QDate.fromString(data_prevista, "yyyy-MM-dd")
            self.form_data_prevista.setDate(data_prevista_qt if data_prevista_qt.isValid() else QtCore.QDate.currentDate())
        else:
            self.check_data_prevista.setChecked(False)
            self.form_data_prevista.setDate(QtCore.QDate.currentDate())

        self.form_observacao.setPlainText(str(linha.get("observacao_cnh") or ""))
        self._carregar_historicos(codigo_colaborador)

    def _carregar_historicos(self, codigo_colaborador: str):
        historico = listar_historico_cnh(DB_PATH, codigo_colaborador)
        self.hist_renovacoes.setRowCount(len(historico))
        for row_idx, item in enumerate(historico):
            valores = [
                item.get("data_hora", ""),
                item.get("validade_anterior_formatada", "-"),
                item.get("validade_nova_formatada", "-"),
                item.get("categoria_nova") or item.get("categoria_anterior") or "-",
                item.get("responsavel", ""),
            ]
            for col, valor in enumerate(valores):
                self.hist_renovacoes.setItem(row_idx, col, QtWidgets.QTableWidgetItem(str(valor)))

        timeline = listar_acompanhamentos_cnh(DB_PATH, codigo_colaborador)
        self.hist_acomp.setRowCount(len(timeline))
        for row_idx, item in enumerate(timeline):
            self.hist_acomp.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(str(item.get("data_hora", ""))))
            self.hist_acomp.setCellWidget(row_idx, 1, _build_chip(item.get("status_label", ""), self._acomp_tone(item.get("status_label", "")), True))
            self.hist_acomp.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(str(item.get("responsavel", ""))))
            self.hist_acomp.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(str(item.get("data_prevista_formatada", ""))))
            self.hist_acomp.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(str(item.get("observacao", ""))))

        self.hist_renovacoes.resizeColumnsToContents()
        self.hist_acomp.resizeColumnsToContents()

    def _aplicar_preset(self, status: str, houve_contato: bool):
        idx = self.form_status_acomp.findData(status)
        if idx >= 0:
            self.form_status_acomp.setCurrentIndex(idx)
        self.form_houve_contato.setChecked(houve_contato)

    def _aplicar_acompanhamento(self):
        codigos = self.codigos_selecionados()
        if not codigos:
            QtWidgets.QMessageBox.warning(self, "CNH", "Selecione pelo menos um colaborador.")
            return

        data_prevista = None
        if self.check_data_prevista.isChecked():
            data_prevista = self.form_data_prevista.date().toString("yyyy-MM-dd")

        sucesso = 0
        erros = []
        for codigo in codigos:
            ok, mensagem = registrar_acompanhamento_cnh(
                codigo_colaborador=codigo,
                status=self.form_status_acomp.currentData(),
                responsavel=self.form_responsavel.text().strip(),
                observacao=self.form_observacao.toPlainText().strip(),
                data_prevista=data_prevista,
                houve_contato=self.form_houve_contato.isChecked(),
                origem="CENTRAL_CNH",
            )
            if ok:
                sucesso += 1
            else:
                erros.append(f"{codigo}: {mensagem}")

        self._recarregar_telas(codigos)
        mensagem = f"Acompanhamento aplicado em {sucesso} colaborador(es)."
        if erros:
            mensagem += "\n\nFalhas:\n" + "\n".join(erros)
        QtWidgets.QMessageBox.information(self, "CNH", mensagem)

    def _escolher_comprovante(self):
        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Selecionar comprovante da CNH",
            "",
            "Arquivos (*.pdf *.jpg *.jpeg *.png *.doc *.docx);;Todos os arquivos (*)",
        )
        if caminho:
            self._comprovante_selecionado = caminho
            self.lbl_comprovante.setText(caminho)

    def _registrar_renovacao(self):
        codigos = self.codigos_selecionados()
        if not codigos:
            QtWidgets.QMessageBox.warning(self, "CNH", "Selecione um colaborador.")
            return
        if len(codigos) > 1:
            QtWidgets.QMessageBox.warning(self, "CNH", "Selecione apenas um colaborador para registrar a renovação.")
            return

        codigo = codigos[0]
        ok, mensagem = registrar_renovacao_cnh(
            codigo_colaborador=codigo,
            nova_validade=self.form_nova_validade.date().toString("yyyy-MM-dd"),
            categoria_nova=self.form_categoria_nova.currentText(),
            responsavel=self.form_responsavel.text().strip(),
            observacao=self.form_observacao.toPlainText().strip(),
            caminho_comprovante=self._comprovante_selecionado or None,
            origem="CENTRAL_CNH",
        )
        if not ok:
            QtWidgets.QMessageBox.warning(self, "CNH", mensagem)
            return

        self._comprovante_selecionado = ""
        self.lbl_comprovante.setText("Nenhum arquivo selecionado.")
        self._recarregar_telas([codigo])
        QtWidgets.QMessageBox.information(self, "CNH", mensagem)

    def _exportar_lista_cobranca(self):
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar lista de cobrança",
            "lista_cobranca_cnh.xlsx",
            "Arquivos Excel (*.xlsx)",
        )
        if not caminho:
            return

        total = exportar_lista_cobranca_excel(
            DB_PATH,
            caminho,
            filtro_status_tecnico=self.combo_status_tecnico.currentData() or "",
            filtro_status_acompanhamento=self.combo_status_acomp.currentData() or "",
            filtro_frente=self.combo_frente.currentData() or "",
            filtro_gestor=self.combo_gestor.currentData() or "",
        )
        QtWidgets.QMessageBox.information(self, "CNH", f"Lista de cobrança exportada com {total} registro(s).")

    def _exportar_painel(self):
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar painel operacional",
            "painel_cnh.xlsx",
            "Arquivos Excel (*.xlsx)",
        )
        if not caminho:
            return

        total = exportar_painel_cnh_excel(DB_PATH, caminho)
        QtWidgets.QMessageBox.information(self, "CNH", f"Painel operacional exportado com {total} registro(s).")

    def _abrir_menu_contexto(self, position):
        item = self.tabela.itemAt(position)
        if not item:
            return

        menu = QtWidgets.QMenu(self)
        acao_ficha = menu.addAction("Abrir ficha completa")
        acao_editar = menu.addAction("Editar cadastro")
        acao = menu.exec_(self.tabela.mapToGlobal(position))

        if acao == acao_ficha:
            self._abrir_ficha()
        elif acao == acao_editar:
            self._editar_cadastro()

    def _abrir_ficha(self):
        codigos = self.codigos_selecionados()
        if not codigos:
            return
        janela = ProfileWindow(codigos[0], self)
        janela.exec_()

    def _editar_cadastro(self):
        codigos = self.codigos_selecionados()
        if not codigos:
            return
        self.main_window.ir_para_cadastro_e_carregar(codigos[0])

    def selecionar_codigo(self, codigo_colaborador: str):
        for row in range(self.tabela.rowCount()):
            item = self.tabela.item(row, 1)
            if item and item.data(QtCore.Qt.UserRole) == codigo_colaborador:
                self.tabela.clearSelection()
                self.tabela.selectRow(row)
                self.tabela.scrollToItem(item)
                self._on_selection_changed()
                return

    def _recarregar_telas(self, codigos: list[str]):
        self.carregar_dados()
        if codigos:
            self.selecionar_codigo(codigos[0])

        if hasattr(self.main_window, "tab_dashboard"):
            self.main_window.tab_dashboard.carregar_dados()
        if hasattr(self.main_window, "tab_consulta"):
            self.main_window.tab_consulta.carregar_dados()
