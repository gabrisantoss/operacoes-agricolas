from PyQt5 import QtCore, QtGui, QtWidgets
import qtawesome as qta
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.cnh_management import STATUS_TECNICO_LABELS, STATUS_TECNICO_ORDER, gerar_resumo_cnh
from funcoes_colaboradores import DB_PATH


def _chip_label(texto: str, tone: str) -> QtWidgets.QLabel:
    chip = QtWidgets.QLabel(texto)
    chip.setObjectName("statusChip")
    chip.setProperty("tone", tone)
    chip.setAlignment(QtCore.Qt.AlignCenter)
    chip.setMinimumHeight(26)
    chip.setContentsMargins(10, 4, 10, 4)
    return chip


class KPICard(QtWidgets.QFrame):
    def __init__(self, titulo: str, icone: str, accent: str, severity: str):
        super().__init__()
        self.setObjectName("summaryCard")
        self.setProperty("severity", severity)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        icon_wrap = QtWidgets.QFrame()
        icon_wrap.setObjectName("iconBadge")
        icon_wrap.setProperty("severity", severity)
        icon_layout = QtWidgets.QVBoxLayout(icon_wrap)
        icon_layout.setContentsMargins(10, 10, 10, 10)
        icon_layout.setAlignment(QtCore.Qt.AlignCenter)

        lbl_icon = QtWidgets.QLabel()
        lbl_icon.setPixmap(qta.icon(icone, color=accent).pixmap(24, 24))
        lbl_icon.setAlignment(QtCore.Qt.AlignCenter)
        icon_layout.addWidget(lbl_icon)
        layout.addWidget(icon_wrap)

        texto = QtWidgets.QVBoxLayout()
        self.lbl_valor = QtWidgets.QLabel("0")
        self.lbl_valor.setObjectName("metricValue")
        self.lbl_titulo = QtWidgets.QLabel(titulo)
        self.lbl_titulo.setObjectName("metricLabel")
        texto.addWidget(self.lbl_valor)
        texto.addWidget(self.lbl_titulo)
        layout.addLayout(texto)

    def set_valor(self, valor: int):
        self.lbl_valor.setText(str(valor))


class TabDashboard(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._setup_ui()
        self.carregar_dados()

    def _setup_ui(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        content = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(content)
        self.layout.setSpacing(18)

        hero = QtWidgets.QFrame()
        hero.setObjectName("dashboardHero")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(8)

        eyebrow = QtWidgets.QLabel("Monitoramento diário")
        eyebrow.setObjectName("heroEyebrow")
        hero_layout.addWidget(eyebrow)

        titulo = QtWidgets.QLabel("Painel operacional de CNH")
        titulo.setObjectName("heroTitle")
        hero_layout.addWidget(titulo)

        subtitulo = QtWidgets.QLabel(
            "Leitura rápida das pendências, gargalos por frente e concentração por gestor. "
            "Use este painel para decidir onde agir primeiro."
        )
        subtitulo.setObjectName("heroSubtitle")
        subtitulo.setWordWrap(True)
        hero_layout.addWidget(subtitulo)

        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(_chip_label("Vencida", "danger"))
        chips.addWidget(_chip_label("7 dias", "warning"))
        chips.addWidget(_chip_label("30 dias", "caution"))
        chips.addWidget(_chip_label("Regular", "success"))
        chips.addStretch()
        self.btn_ir_central = QtWidgets.QPushButton("Abrir Central de CNH")
        self.btn_ir_central.setObjectName("secondaryAction")
        self.btn_ir_central.clicked.connect(lambda: self.main_window.tabs.setCurrentWidget(self.main_window.tab_cnh))
        chips.addWidget(self.btn_ir_central)
        hero_layout.addLayout(chips)

        self.layout.addWidget(hero)

        self.kpi_layout = QtWidgets.QHBoxLayout()
        self.card_pendentes = KPICard("Pendências operacionais", "fa5s.exclamation-circle", "#c64b3f", "danger")
        self.card_vencidas = KPICard("CNHs vencidas", "fa5s.id-card", "#d64545", "danger")
        self.card_criticas = KPICard("Vencem em 7 dias", "fa5s.clock", "#d48806", "warning")
        self.card_alerta = KPICard("Vencem em 30 dias", "fa5s.calendar-alt", "#f0b429", "caution")
        self.card_incons = KPICard("Inconsistências", "fa5s.search", "#7f5af0", "neutral")
        for card in (
            self.card_pendentes,
            self.card_vencidas,
            self.card_criticas,
            self.card_alerta,
            self.card_incons,
        ):
            self.kpi_layout.addWidget(card)
        self.layout.addLayout(self.kpi_layout)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        self.fig_status = Figure(figsize=(5, 4), dpi=100)
        self.ax_status = self.fig_status.add_subplot(111)
        self.canvas_status = FigureCanvas(self.fig_status)
        self.canvas_status.setObjectName("chartCanvas")
        box_status = QtWidgets.QGroupBox("Distribuição técnica da CNH")
        box_status.setObjectName("panelGroup")
        box_status_layout = QtWidgets.QVBoxLayout(box_status)
        box_status_layout.addWidget(self.canvas_status)

        self.fig_frentes = Figure(figsize=(5, 4), dpi=100)
        self.ax_frentes = self.fig_frentes.add_subplot(111)
        self.canvas_frentes = FigureCanvas(self.fig_frentes)
        self.canvas_frentes.setObjectName("chartCanvas")
        box_frentes = QtWidgets.QGroupBox("Pendências por frente")
        box_frentes.setObjectName("panelGroup")
        box_frentes_layout = QtWidgets.QVBoxLayout(box_frentes)
        box_frentes_layout.addWidget(self.canvas_frentes)

        self.fig_gestores = Figure(figsize=(5, 4), dpi=100)
        self.ax_gestores = self.fig_gestores.add_subplot(111)
        self.canvas_gestores = FigureCanvas(self.fig_gestores)
        self.canvas_gestores.setObjectName("chartCanvas")
        box_gestores = QtWidgets.QGroupBox("Pendências por gestor")
        box_gestores.setObjectName("panelGroup")
        box_gestores_layout = QtWidgets.QVBoxLayout(box_gestores)
        box_gestores_layout.addWidget(self.canvas_gestores)

        box_criticos = QtWidgets.QGroupBox("Casos mais críticos")
        box_criticos.setObjectName("panelGroup")
        box_criticos_layout = QtWidgets.QVBoxLayout(box_criticos)
        self.table_criticos = QtWidgets.QTableWidget()
        self.table_criticos.setObjectName("queueTable")
        self.table_criticos.setColumnCount(5)
        self.table_criticos.setHorizontalHeaderLabels(["Nome", "Validade", "Status", "Frente", "Telefone"])
        self.table_criticos.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_criticos.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table_criticos.setAlternatingRowColors(True)
        self.table_criticos.setShowGrid(False)
        self.table_criticos.horizontalHeader().setStretchLastSection(True)
        self.table_criticos.verticalHeader().setVisible(False)
        self.table_criticos.doubleClicked.connect(self._abrir_caso_critico)
        box_criticos_layout.addWidget(self.table_criticos)

        grid.addWidget(box_status, 0, 0)
        grid.addWidget(box_frentes, 0, 1)
        grid.addWidget(box_gestores, 1, 0)
        grid.addWidget(box_criticos, 1, 1)
        self.layout.addLayout(grid)

        btn_refresh = QtWidgets.QPushButton("Atualizar Dashboard")
        btn_refresh.setObjectName("ghostAction")
        btn_refresh.clicked.connect(self.carregar_dados)
        self.layout.addWidget(btn_refresh, alignment=QtCore.Qt.AlignRight)
        self.layout.addStretch()

        scroll.setWidget(content)
        main_box = QtWidgets.QVBoxLayout(self)
        main_box.addWidget(scroll)

    def _preparar_eixo(self, eixo):
        paleta = self._paleta_dashboard()
        eixo.set_facecolor(paleta["chart_bg"])
        eixo.spines["top"].set_visible(False)
        eixo.spines["right"].set_visible(False)
        eixo.spines["left"].set_color(paleta["spine"])
        eixo.spines["bottom"].set_color(paleta["spine"])
        eixo.tick_params(colors=paleta["text"])

    def _paleta_dashboard(self) -> dict:
        tema = self.main_window.settings.value("tema", "claro") if hasattr(self.main_window, "settings") else "claro"
        if tema == "escuro":
            return {
                "chart_bg": "#182127",
                "figure_bg": "#182127",
                "spine": "#34434b",
                "text": "#c8d7df",
                "empty": "#91a5b0",
                "grid": "#2a3941",
            }
        return {
            "chart_bg": "#fffaf2",
            "figure_bg": "#fffaf2",
            "spine": "#d9d0c3",
            "text": "#41505d",
            "empty": "#52606d",
            "grid": "#ede5d8",
        }

    def _plotar_status_tecnico(self, resumo: dict):
        self.ax_status.clear()
        self._preparar_eixo(self.ax_status)
        paleta = self._paleta_dashboard()
        self.fig_status.patch.set_facecolor(paleta["figure_bg"])

        contagem = resumo["contagem_tecnica"]
        labels = []
        valores = []
        cores = []
        mapa_cores = {
            "VENCIDA": "#c64b3f",
            "DATA_INVALIDA": "#8d6e63",
            "SEM_VALIDADE": "#9aa5b1",
            "CRITICA_7_DIAS": "#d48806",
            "ALERTA_30_DIAS": "#f0b429",
            "REGULAR": "#2d7a46",
        }

        for status in STATUS_TECNICO_ORDER:
            valor = contagem.get(status, 0)
            if valor:
                labels.append(STATUS_TECNICO_LABELS[status])
                valores.append(valor)
                cores.append(mapa_cores[status])

        if valores:
            self.ax_status.pie(
                valores,
                labels=labels,
                autopct="%1.0f%%",
                startangle=90,
                colors=cores,
                wedgeprops={"width": 0.42, "edgecolor": paleta["chart_bg"]},
                textprops={"color": paleta["text"]},
            )
        else:
            self.ax_status.text(0.5, 0.5, "Sem dados", ha="center", va="center", color=paleta["empty"])
        self.canvas_status.draw()

    def _plotar_barras(self, eixo, canvas, fig, dados: list[tuple], titulo_vazio: str, cor: str):
        eixo.clear()
        self._preparar_eixo(eixo)
        paleta = self._paleta_dashboard()
        fig.patch.set_facecolor(paleta["figure_bg"])
        top = dados[:8]
        if top:
            labels = [item[0] for item in top]
            valores = [item[1] for item in top]
            posicoes = list(range(len(top)))
            barras = eixo.bar(posicoes, valores, color=cor, width=0.58)
            eixo.set_xticks(posicoes)
            eixo.set_xticklabels(labels, rotation=18, ha="right")
            eixo.bar_label(barras, color=paleta["text"])
            eixo.grid(axis="y", color=paleta["grid"], linestyle="-", linewidth=0.8)
        else:
            eixo.text(0.5, 0.5, titulo_vazio, ha="center", va="center", color=paleta["empty"])
        canvas.draw()

    def _critico_tone(self, status: str) -> str:
        if status == "Vencida":
            return "danger"
        if status == "Vence em 7 dias":
            return "warning"
        if status == "Vence em 30 dias":
            return "caution"
        return "neutral"

    def _preencher_criticos(self, resumo: dict):
        criticos = resumo["criticos"]
        self.table_criticos.setRowCount(len(criticos))
        for row_idx, item in enumerate(criticos):
            nome = QtWidgets.QTableWidgetItem(str(item.get("nome", "")))
            nome.setData(QtCore.Qt.UserRole, item.get("codigo_colaborador"))
            self.table_criticos.setItem(row_idx, 0, nome)
            self.table_criticos.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(str(item.get("validade_cnh_formatada", "-"))))
            self.table_criticos.setCellWidget(row_idx, 2, _chip_label(item.get("status_tecnico_label", ""), self._critico_tone(item.get("status_tecnico_label", ""))))
            self.table_criticos.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(str(item.get("frente_exibicao", ""))))
            self.table_criticos.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(str(item.get("telefone", ""))))
        self.table_criticos.resizeColumnsToContents()

    def carregar_dados(self):
        resumo = gerar_resumo_cnh(DB_PATH)

        self.card_pendentes.set_valor(resumo["pendentes"])
        self.card_vencidas.set_valor(resumo["contagem_tecnica"]["VENCIDA"])
        self.card_criticas.set_valor(resumo["contagem_tecnica"]["CRITICA_7_DIAS"])
        self.card_alerta.set_valor(resumo["contagem_tecnica"]["ALERTA_30_DIAS"])
        self.card_incons.set_valor(resumo["inconsistencias"])

        self._plotar_status_tecnico(resumo)
        self._plotar_barras(self.ax_frentes, self.canvas_frentes, self.fig_frentes, resumo["por_frente"], "Sem pendências por frente", "#d48806")
        self._plotar_barras(self.ax_gestores, self.canvas_gestores, self.fig_gestores, resumo["por_gestor"], "Sem pendências por gestor", "#1f5f73")
        self._preencher_criticos(resumo)

    def _abrir_caso_critico(self, item):
        codigo = self.table_criticos.item(item.row(), 0).data(QtCore.Qt.UserRole)
        if codigo:
            self.main_window.ir_para_cnh(codigo)
