from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets

from core.cnh_management import STATUS_TECNICO_LABELS, STATUS_TECNICO_ORDER, listar_opcoes_painel_cnh, listar_painel_cnh
from funcoes_colaboradores import DB_PATH, obter_valores_unicos_coluna
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


class TabConsulta(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.carregar_dados)
        self.dados_carregados = []

        self._setup_ui()
        self._carregar_filtros_iniciais()
        self.carregar_dados()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(18)

        hero = QtWidgets.QFrame()
        hero.setObjectName("heroPanel")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(8)

        eyebrow = QtWidgets.QLabel("Consulta operacional")
        eyebrow.setObjectName("heroEyebrow")
        hero_layout.addWidget(eyebrow)

        titulo = QtWidgets.QLabel("Busca com contexto de validade e acompanhamento")
        titulo.setObjectName("heroTitle")
        hero_layout.addWidget(titulo)

        subtitulo = QtWidgets.QLabel(
            "Use esta tela para localizar rapidamente colaboradores, filtrar por gestor ou cidade e sair direto para a ficha ou para a central de CNH."
        )
        subtitulo.setObjectName("heroSubtitle")
        subtitulo.setWordWrap(True)
        hero_layout.addWidget(subtitulo)

        legenda = QtWidgets.QHBoxLayout()
        legenda.setSpacing(8)
        legenda.addWidget(_build_chip("Vencida", "danger"))
        legenda.addWidget(_build_chip("7 dias", "warning"))
        legenda.addWidget(_build_chip("30 dias", "caution"))
        legenda.addWidget(_build_chip("Regular", "success"))
        legenda.addStretch()

        self.btn_ir_central = QtWidgets.QPushButton("Abrir Central de CNH")
        self.btn_ir_central.setObjectName("secondaryAction")
        self.btn_ir_central.clicked.connect(lambda: self.main_window.tabs.setCurrentWidget(self.main_window.tab_cnh))
        legenda.addWidget(self.btn_ir_central)
        hero_layout.addLayout(legenda)

        layout.addWidget(hero)

        group_filtros = QtWidgets.QGroupBox("Filtros de consulta")
        group_filtros.setObjectName("filterPanel")
        layout_filtros = QtWidgets.QGridLayout(group_filtros)
        layout_filtros.setHorizontalSpacing(12)
        layout_filtros.setVerticalSpacing(12)

        self.filtro_nome = QtWidgets.QLineEdit()
        self.filtro_nome.setPlaceholderText("Nome, código, gestor ou frente")
        layout_filtros.addWidget(QtWidgets.QLabel("Busca"), 0, 0)
        layout_filtros.addWidget(self.filtro_nome, 0, 1, 1, 3)

        self.combo_filtro_funcao = QtWidgets.QComboBox()
        self.combo_filtro_funcao.addItem("Todas as Funções")
        layout_filtros.addWidget(QtWidgets.QLabel("Função"), 1, 0)
        layout_filtros.addWidget(self.combo_filtro_funcao, 1, 1)

        self.combo_filtro_cidade = QtWidgets.QComboBox()
        self.combo_filtro_cidade.addItem("Todas as Cidades")
        layout_filtros.addWidget(QtWidgets.QLabel("Cidade"), 1, 2)
        layout_filtros.addWidget(self.combo_filtro_cidade, 1, 3)

        self.combo_filtro_status = QtWidgets.QComboBox()
        self.combo_filtro_status.addItem("Todos os Status", "")
        for status in STATUS_TECNICO_ORDER:
            self.combo_filtro_status.addItem(STATUS_TECNICO_LABELS[status], status)
        layout_filtros.addWidget(QtWidgets.QLabel("Status CNH"), 2, 0)
        layout_filtros.addWidget(self.combo_filtro_status, 2, 1)

        self.combo_filtro_gestor = QtWidgets.QComboBox()
        self.combo_filtro_gestor.addItem("Todos os Gestores", "")
        layout_filtros.addWidget(QtWidgets.QLabel("Gestor"), 2, 2)
        layout_filtros.addWidget(self.combo_filtro_gestor, 2, 3)

        self.lbl_total = QtWidgets.QLabel("0 registro(s) encontrados.")
        self.lbl_total.setObjectName("detailHint")
        layout_filtros.addWidget(self.lbl_total, 3, 0, 1, 2)

        botoes = QtWidgets.QHBoxLayout()
        botoes.addStretch()
        self.btn_limpar = QtWidgets.QPushButton("Limpar filtros")
        self.btn_limpar.setObjectName("ghostAction")
        self.btn_ir_cadastro = QtWidgets.QPushButton("Novo cadastro")
        self.btn_ir_cadastro.setObjectName("primaryAction")
        botoes.addWidget(self.btn_limpar)
        botoes.addWidget(self.btn_ir_cadastro)
        layout_filtros.addLayout(botoes, 3, 2, 1, 2)

        layout.addWidget(group_filtros)

        self.tabela = QtWidgets.QTableWidget()
        self.tabela.setObjectName("queueTable")
        self.tabela.setColumnCount(8)
        self.tabela.setHorizontalHeaderLabels(
            ["Cód", "Nome", "Função", "Cidade", "Gestor", "Validade CNH", "Status", "Acompanhamento"]
        )
        self.tabela.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tabela.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setShowGrid(False)
        self.tabela.verticalHeader().setVisible(False)
        header = self.tabela.horizontalHeader()
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QtWidgets.QHeaderView.ResizeToContents)

        self.tabela.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabela.customContextMenuRequested.connect(self._abrir_menu_contexto)
        self.tabela.doubleClicked.connect(self._editar_colaborador)

        layout.addWidget(self.tabela)

        self.filtro_nome.textChanged.connect(lambda: self.search_timer.start(250))
        self.combo_filtro_funcao.currentIndexChanged.connect(self.carregar_dados)
        self.combo_filtro_cidade.currentIndexChanged.connect(self.carregar_dados)
        self.combo_filtro_status.currentIndexChanged.connect(self.carregar_dados)
        self.combo_filtro_gestor.currentIndexChanged.connect(self.carregar_dados)
        self.btn_limpar.clicked.connect(self.limpar_filtros)
        self.btn_ir_cadastro.clicked.connect(lambda: self.main_window.tabs.setCurrentWidget(self.main_window.tab_cadastro))

    def _carregar_filtros_iniciais(self):
        funcoes = obter_valores_unicos_coluna("funcao_safra")
        self.combo_filtro_funcao.addItems(sorted(str(f) for f in funcoes if f))

        cidades = obter_valores_unicos_coluna("cidade")
        self.combo_filtro_cidade.addItems(sorted(str(c) for c in cidades if c))

        opcoes = listar_opcoes_painel_cnh(DB_PATH)
        for gestor in opcoes["gestores"]:
            self.combo_filtro_gestor.addItem(gestor, gestor)

    def _row_background(self, colab: dict) -> QtGui.QColor:
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
            return QtGui.QColor(mapa.get(colab.get("status_tecnico"), "#131d22"))

        status = colab.get("status_tecnico")
        if status in {"VENCIDA", "DATA_INVALIDA"}:
            return QtGui.QColor("#fff0ed")
        if status == "SEM_VALIDADE":
            return QtGui.QColor("#f2efe8")
        if status == "CRITICA_7_DIAS":
            return QtGui.QColor("#fff4e0")
        if status == "ALERTA_30_DIAS":
            return QtGui.QColor("#fff9df")
        return QtGui.QColor("#fffdf9")

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

    def carregar_dados(self):
        try:
            colaboradores = listar_painel_cnh(
                DB_PATH,
                filtro_busca=self.filtro_nome.text().strip(),
                filtro_status_tecnico=self.combo_filtro_status.currentData() or "",
                filtro_gestor=self.combo_filtro_gestor.currentData() or "",
                somente_pendentes=False,
            )

            funcao = self.combo_filtro_funcao.currentText()
            if funcao != "Todas as Funções":
                colaboradores = [c for c in colaboradores if c.get("funcao_exibicao") == funcao]

            cidade = self.combo_filtro_cidade.currentText()
            if cidade != "Todas as Cidades":
                colaboradores = [c for c in colaboradores if c.get("cidade_exibicao") == cidade]

            self.dados_carregados = colaboradores
            self._preencher_tabela(colaboradores)
        except Exception as e:
            print(f"Erro ao carregar dados: {e}")

    def _preencher_tabela(self, colaboradores):
        self.tabela.setSortingEnabled(False)
        self.tabela.setRowCount(len(colaboradores))
        self.lbl_total.setText(f"{len(colaboradores)} registro(s) encontrados.")

        for row, colab in enumerate(colaboradores):
            cor_fundo = self._row_background(colab)
            validade_str = str(colab.get("validade_cnh") or "")

            if validade_str:
                try:
                    validade_fmt = datetime.strptime(validade_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    validade_fmt = validade_str
            else:
                validade_fmt = "-"

            itens = {
                0: str(colab.get("codigo_colaborador", "")),
                1: str(colab.get("nome", "")),
                2: str(colab.get("funcao_exibicao") or ""),
                3: str(colab.get("cidade_exibicao") or ""),
                4: str(colab.get("gestor_exibicao") or ""),
                5: validade_fmt,
            }
            for col, texto in itens.items():
                item = QtWidgets.QTableWidgetItem(texto)
                item.setBackground(cor_fundo)
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, texto)
                self.tabela.setItem(row, col, item)

            status = str(colab.get("status_tecnico_label") or "-")
            acompanhamento = str(colab.get("status_acompanhamento_label") or "-")
            self.tabela.setCellWidget(row, 6, _build_chip(status, self._status_tone(status), True))
            self.tabela.setCellWidget(row, 7, _build_chip(acompanhamento, self._acomp_tone(acompanhamento), True))

        self.tabela.resizeColumnsToContents()

    def limpar_filtros(self):
        self.filtro_nome.clear()
        self.combo_filtro_funcao.setCurrentIndex(0)
        self.combo_filtro_cidade.setCurrentIndex(0)
        self.combo_filtro_status.setCurrentIndex(0)
        self.combo_filtro_gestor.setCurrentIndex(0)
        self.carregar_dados()

    def _abrir_menu_contexto(self, position):
        index = self.tabela.indexAt(position)
        if not index.isValid():
            return

        codigo = self.tabela.item(index.row(), 0).data(QtCore.Qt.UserRole)
        if not codigo:
            return

        menu = QtWidgets.QMenu(self)
        acao_ver = menu.addAction("Abrir ficha completa")
        acao_editar = menu.addAction("Editar cadastro")
        acao_cnh = menu.addAction("Acompanhar CNH")

        acao = menu.exec_(self.tabela.viewport().mapToGlobal(position))
        if acao == acao_ver:
            win = ProfileWindow(codigo, self)
            win.exec_()
        elif acao == acao_editar:
            self.main_window.ir_para_cadastro_e_carregar(codigo)
        elif acao == acao_cnh:
            self.main_window.ir_para_cnh(codigo)

    def _editar_colaborador(self, item):
        codigo = self.tabela.item(item.row(), 0).data(QtCore.Qt.UserRole)
        if codigo:
            self.main_window.ir_para_cadastro_e_carregar(codigo)
