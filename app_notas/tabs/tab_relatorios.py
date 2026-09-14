from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from PyQt5 import QtCore, QtWidgets

from app_config import DB_ENGINE
from app_logging import get_logger
from database import DB
from agricola_shared.report_security import neutralize_dataframe
from reporting import (
    RelatorioDataService,
    RelatorioFormatacaoMixin,
    RelatorioPdfDiarioBuilder,
    RelatorioPdfFazendasMudaBuilder,
    RelatorioPdfFechamentoBuilder,
    RelatorioPdfGeralBuilder,
    RelatorioPdfSimplificadoBuilder,
)
from styles import aplicar_icone
from workers import BackgroundTask

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    MATPLOTLIB_INSTALADO = True
except ImportError:
    MATPLOTLIB_INSTALADO = False


LOGGER = get_logger(__name__)


@contextmanager
def report_connection(db_path):
    if DB_ENGINE in {"postgres", "postgresql"}:
        db = DB(seed_from_excel=False)
        try:
            yield db.conn
        finally:
            db.close()
        return

    with sqlite3.connect(db_path) as conn:
        yield conn


class AbaRelatorios(RelatorioFormatacaoMixin, QtWidgets.QWidget):
    def __init__(self, db, main_window_ref):
        super().__init__()
        self.db = db
        self.main_window = main_window_ref
        self.graficos = []
        self.worker_tarefa = None
        self._dashboard_carregado = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("PageRoot")
        layout_principal = QtWidgets.QVBoxLayout(self)
        layout_principal.setContentsMargins(12, 10, 12, 10)
        layout_principal.setSpacing(10)

        hero = QtWidgets.QFrame()
        hero.setObjectName("ToolbarCard")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(14, 10, 14, 10)
        hero_layout.setSpacing(4)
        titulo = QtWidgets.QLabel("Controle e Analise")
        titulo.setObjectName("PageTitle")
        subtitulo = QtWidgets.QLabel("Acompanhe o periodo, exporte relatorios e destaque os principais rankings.")
        subtitulo.setObjectName("PageSubtitle")
        subtitulo.setWordWrap(True)
        hero_layout.addWidget(titulo)
        hero_layout.addWidget(subtitulo)
        layout_principal.addWidget(hero)

        filter_box = QtWidgets.QFrame()
        filter_box.setObjectName("ToolbarCard")
        filter_layout = QtWidgets.QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setSpacing(10)

        self.dt_inicio = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addDays(-30))
        self.dt_inicio.setCalendarPopup(True)
        self.dt_inicio.setDisplayFormat("dd/MM/yyyy")
        self.dt_inicio.setMinimumWidth(120)
        self.dt_inicio.setMinimumHeight(40)

        self.dt_fim = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.dt_fim.setCalendarPopup(True)
        self.dt_fim.setDisplayFormat("dd/MM/yyyy")
        self.dt_fim.setMinimumWidth(120)
        self.dt_fim.setMinimumHeight(40)

        self.cb_visao = QtWidgets.QComboBox()
        self.cb_visao.addItems(["Diario", "Mensal", "Anual"])
        self.cb_visao.currentIndexChanged.connect(lambda *_: self.gerar_dashboard(show_feedback=False))
        self.cb_visao.setMinimumWidth(120)
        self.cb_visao.setMinimumHeight(40)

        self.btn_atualizar = QtWidgets.QPushButton(" Atualizar dados")
        self.btn_atualizar.setObjectName("PrimaryButton")
        aplicar_icone(self.btn_atualizar, "fa5s.sync-alt")
        self.btn_atualizar.clicked.connect(lambda: self.gerar_dashboard(show_feedback=True))
        self.btn_atualizar.setMinimumHeight(40)

        self.btn_excel = QtWidgets.QPushButton(" Excel fluxo")
        self.btn_excel.setObjectName("SuccessButton")
        aplicar_icone(self.btn_excel, "fa5s.file-excel")
        self.btn_excel.clicked.connect(self.gerar_excel_fluxo)

        self.btn_excel_bruto = QtWidgets.QPushButton(" Excel bruto")
        self.btn_excel_bruto.setObjectName("SuccessButton")
        aplicar_icone(self.btn_excel_bruto, "fa5s.database")
        self.btn_excel_bruto.clicked.connect(self.gerar_excel_bruto)

        self.btn_pdf_diario = QtWidgets.QPushButton(" PDF diario")
        self.btn_pdf_diario.setObjectName("SecondaryButton")
        aplicar_icone(self.btn_pdf_diario, "fa5s.file-pdf")
        self.btn_pdf_diario.clicked.connect(self.gerar_pdf_resumo)

        self.btn_pdf_geral = QtWidgets.QPushButton(" PDF geral")
        self.btn_pdf_geral.setObjectName("SecondaryButton")
        aplicar_icone(self.btn_pdf_geral, "fa5s.file-alt")
        self.btn_pdf_geral.clicked.connect(self.gerar_pdf_geral_fazenda)

        self.btn_pdf_mudas = QtWidgets.QPushButton(" Hist. mudas")
        self.btn_pdf_mudas.setObjectName("SecondaryButton")
        aplicar_icone(self.btn_pdf_mudas, "fa5s.file-pdf")
        self.btn_pdf_mudas.clicked.connect(self.gerar_pdf_fazendas_muda)

        self.btn_pdf_simplificado = QtWidgets.QPushButton(" PDF simples")
        self.btn_pdf_simplificado.setObjectName("SecondaryButton")
        aplicar_icone(self.btn_pdf_simplificado, "fa5s.list-alt")
        self.btn_pdf_simplificado.clicked.connect(self.gerar_pdf_simplificado)

        self.btn_pdf_fechamento = QtWidgets.QPushButton(" Final safra")
        self.btn_pdf_fechamento.setObjectName("PrimaryButton")
        aplicar_icone(self.btn_pdf_fechamento, "fa5s.file-signature")
        self.btn_pdf_fechamento.clicked.connect(self.gerar_pdf_fechamento_safra)

        self._botoes_tarefa = [
            self.btn_atualizar,
            self.btn_excel,
            self.btn_excel_bruto,
            self.btn_pdf_diario,
            self.btn_pdf_geral,
            self.btn_pdf_mudas,
            self.btn_pdf_simplificado,
            self.btn_pdf_fechamento,
        ]
        for botao in self._botoes_tarefa:
            botao.setMinimumHeight(40)
            botao.setMinimumWidth(0)
            botao.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Fixed,
            )

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(10)
        lbl_de = QtWidgets.QLabel("De:")
        lbl_de.setObjectName("FormLabel")
        lbl_ate = QtWidgets.QLabel("Ate:")
        lbl_ate.setObjectName("FormLabel")
        lbl_visao = QtWidgets.QLabel("Visao:")
        lbl_visao.setObjectName("FormLabel")
        row1.addWidget(lbl_de)
        row1.addWidget(self.dt_inicio)
        row1.addSpacing(15)
        row1.addWidget(lbl_ate)
        row1.addWidget(self.dt_fim)
        row1.addSpacing(15)
        row1.addWidget(lbl_visao)
        row1.addWidget(self.cb_visao)
        row1.addSpacing(20)
        row1.addWidget(self.btn_atualizar, 1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self.btn_excel)
        row2.addWidget(self.btn_excel_bruto)
        row2.addWidget(self.btn_pdf_diario)
        row2.addWidget(self.btn_pdf_geral)
        row2.addWidget(self.btn_pdf_mudas)
        row2.addWidget(self.btn_pdf_simplificado)
        row2.addWidget(self.btn_pdf_fechamento)

        self.lbl_execucao = QtWidgets.QLabel("")
        self.lbl_execucao.setObjectName("WindowSubtitle")
        self.lbl_execucao.hide()

        self.progress_execucao = QtWidgets.QProgressBar()
        self.progress_execucao.setRange(0, 100)
        self.progress_execucao.hide()

        self.btn_cancelar_tarefa = QtWidgets.QPushButton(" Cancelar")
        self.btn_cancelar_tarefa.setObjectName("DangerButton")
        aplicar_icone(self.btn_cancelar_tarefa, "fa5s.times")
        self.btn_cancelar_tarefa.clicked.connect(self._cancelar_tarefa_atual)
        self.btn_cancelar_tarefa.hide()

        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(10)
        row3.addWidget(self.lbl_execucao, 1)
        row3.addWidget(self.progress_execucao, 2)
        row3.addWidget(self.btn_cancelar_tarefa)

        filter_layout.addLayout(row1)
        filter_layout.addLayout(row2)
        filter_layout.addLayout(row3)
        layout_principal.addWidget(filter_box)

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 16)
        self.content_layout.setSpacing(12)

        kpi_container = QtWidgets.QWidget()
        kpi_layout = QtWidgets.QHBoxLayout(kpi_container)
        kpi_layout.setContentsMargins(0, 2, 0, 0)
        kpi_layout.setSpacing(12)

        self.lbl_kpi_total = QtWidgets.QLabel("0")
        self.lbl_kpi_total.setObjectName("KPI")
        self.lbl_kpi_total.setAlignment(QtCore.Qt.AlignCenter)

        self.lbl_kpi_media = QtWidgets.QLabel("0")
        self.lbl_kpi_media.setObjectName("KPI")
        self.lbl_kpi_media.setAlignment(QtCore.Qt.AlignCenter)

        self.lbl_kpi_dias = QtWidgets.QLabel("0")
        self.lbl_kpi_dias.setObjectName("KPI")
        self.lbl_kpi_dias.setAlignment(QtCore.Qt.AlignCenter)

        kpi_layout.addWidget(self._criar_card_kpi("TOTAL DE VIAGENS", self.lbl_kpi_total))
        kpi_layout.addWidget(self._criar_card_kpi("MEDIA NO PERIODO", self.lbl_kpi_media))
        kpi_layout.addWidget(self._criar_card_kpi("DIAS COM MOVIMENTO", self.lbl_kpi_dias))
        self.content_layout.addWidget(kpi_container)

        if MATPLOTLIB_INSTALADO:
            titulos = [
                "TOP 5 MOTORISTAS",
                "TOP 5 MAQUINISTAS / OPERADORES",
                "TOP 5 COLHEDORAS",
                "VARIEDADES MAIS PLANTADAS",
                "FAZENDAS COM MAIS COLHEITA (ORIGEM)",
                "FAZENDAS COM MAIS PLANTIO (DESTINO)",
            ]
            for titulo in titulos:
                self._adicionar_espaco_grafico(titulo)
        else:
            sem_graf = QtWidgets.QLabel("Instale matplotlib para habilitar os graficos.\nEx.: pip install matplotlib")
            sem_graf.setAlignment(QtCore.Qt.AlignCenter)
            sem_graf.setWordWrap(True)
            self.content_layout.addWidget(sem_graf)

        self.content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout_principal.addWidget(scroll)

    def _criar_card_kpi(self, titulo: str, widget_valor: QtWidgets.QLabel) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("MetricCard")
        card.setMinimumHeight(104)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        label_titulo = QtWidgets.QLabel(titulo)
        label_titulo.setObjectName("KPITitle")
        label_titulo.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label_titulo)
        layout.addWidget(widget_valor, alignment=QtCore.Qt.AlignCenter)
        return card

    def _adicionar_espaco_grafico(self, titulo: str) -> None:
        fig = Figure(figsize=(10, 3.2), dpi=100)
        fig.patch.set_facecolor("#ffffff")
        canvas = FigureCanvas(fig)
        canvas.setMinimumHeight(280)

        card = QtWidgets.QFrame()
        card.setObjectName("ChartCard")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        label_titulo = QtWidgets.QLabel(titulo)
        label_titulo.setObjectName("ChartTitle")
        card_layout.addWidget(label_titulo)
        card_layout.addWidget(canvas)

        self.graficos.append(
            {
                "titulo": titulo,
                "fig": fig,
                "canvas": canvas,
                "ax": fig.add_subplot(111),
                "card": card,
            }
        )
        self.content_layout.addWidget(card)

    def _get_datas_sql(self) -> tuple[str, str]:
        return (
            self.dt_inicio.date().toString("yyyy-MM-dd"),
            self.dt_fim.date().toString("yyyy-MM-dd"),
        )

    def _ensure_date_range(self) -> None:
        if self.dt_inicio.date() > self.dt_fim.date():
            self.dt_inicio.setDate(self.dt_fim.date())

    def _cancelar_tarefa_atual(self) -> None:
        if self.worker_tarefa and self.worker_tarefa.isRunning():
            self.worker_tarefa.cancelar()

    def _iniciar_tarefa(self, worker: BackgroundTask, mensagem_inicial: str, on_success) -> bool:
        if self.worker_tarefa and self.worker_tarefa.isRunning():
            QtWidgets.QMessageBox.information(self, "Aguarde", "Ja existe uma tarefa em andamento nesta aba.")
            return False

        self.worker_tarefa = worker
        for botao in self._botoes_tarefa:
            botao.setEnabled(False)

        self.lbl_execucao.setText(mensagem_inicial)
        self.lbl_execucao.show()
        self.progress_execucao.setValue(0)
        self.progress_execucao.show()
        self.btn_cancelar_tarefa.show()

        worker.progresso.connect(self._atualizar_progresso)
        worker.concluido.connect(on_success)
        worker.erro.connect(self._on_tarefa_erro)
        worker.cancelado.connect(self._on_tarefa_cancelada)
        worker.finished.connect(self._finalizar_tarefa)
        worker.start()
        return True

    def _atualizar_progresso(self, valor: int, mensagem: str) -> None:
        self.progress_execucao.setValue(valor)
        if mensagem:
            self.lbl_execucao.setText(mensagem)

    def _finalizar_tarefa(self) -> None:
        for botao in self._botoes_tarefa:
            botao.setEnabled(True)
        self.progress_execucao.hide()
        self.btn_cancelar_tarefa.hide()
        self.lbl_execucao.hide()
        if self.worker_tarefa:
            self.worker_tarefa.deleteLater()
            self.worker_tarefa = None

    def _on_tarefa_erro(self, mensagem: str) -> None:
        if str(mensagem).startswith("Sem "):
            QtWidgets.QMessageBox.warning(self, "Aviso", mensagem)
            return
        QtWidgets.QMessageBox.critical(self, "Erro", mensagem)

    def _on_tarefa_cancelada(self, mensagem: str) -> None:
        QtWidgets.QMessageBox.information(self, "Cancelado", mensagem)

    def _tarefa_dashboard(self, d_ini: str, d_fim: str, dias_intervalo: int, progress, is_cancelled):
        if not MATPLOTLIB_INSTALADO:
            return None

        progress(5, "Consultando rankings...")
        colunas = [
            "motorista_nome",
            "operador_nome",
            "colhedora",
            "variedade_nome",
            "faz_muda_nome",
            "faz_plantio_nome",
        ]
        dados_graficos = []
        for index, coluna in enumerate(colunas, start=1):
            if is_cancelled():
                return None
            ranking = self.db.top_por_coluna(coluna, d_ini, d_fim, limit=5)
            nomes = [str(row["nome"]).strip() for row in ranking]
            qtds = [int(row["qtd"]) for row in ranking]
            dados_graficos.append((nomes, qtds))
            progress(10 + index * 10, f"Processando {coluna.replace('_', ' ')}...")

        if is_cancelled():
            return None

        total = self.db.contar_notas_periodo(d_ini, d_fim)
        media = total / dias_intervalo if dias_intervalo > 0 else 0
        dias_ativos = self.db.contar_dias_ativos_periodo(d_ini, d_fim)
        progress(100, "Dashboard atualizado.")
        return {
            "dados_graficos": dados_graficos,
            "total": total,
            "media": media,
            "dias_ativos": dias_ativos,
        }

    def _aplicar_dashboard(self, resultado: dict | None) -> None:
        if not resultado:
            return

        self.lbl_kpi_total.setText(f"{resultado['total']:,}".replace(",", "."))
        self.lbl_kpi_media.setText(f"{resultado['media']:.1f}/dia")
        self.lbl_kpi_dias.setText(str(resultado["dias_ativos"]))

        cores = ["#26734d", "#31576f", "#5b7f43", "#7a6a38", "#4f8461", "#6f7d8a"]
        for index, item in enumerate(self.graficos):
            ax = item["ax"]
            canvas = item["canvas"]
            fig = item["fig"]
            nomes, qtds = resultado["dados_graficos"][index]
            cor = cores[index % len(cores)]

            ax.clear()
            if nomes:
                bars = ax.barh(nomes, qtds, color=cor, height=0.62)
                if hasattr(ax, "bar_label"):
                    try:
                        ax.bar_label(bars, color="#1f342d", padding=5, fontsize=10, fontweight="bold")
                    except Exception:
                        pass
                ax.invert_yaxis()
                ax.tick_params(axis="y", labelsize=10, labelcolor="#26322f")
                ax.tick_params(axis="x", labelsize=9, labelcolor="#657268")
            else:
                ax.text(
                    0.5,
                    0.5,
                    "Sem dados\nno periodo",
                    ha="center",
                    va="center",
                    color="#657268",
                    fontsize=13,
                    transform=ax.transAxes,
                )

            ax.set_facecolor("#ffffff")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["bottom"].set_color("#d9e1d8")
            ax.spines["left"].set_color("#d9e1d8")
            ax.grid(axis="x", color="#e6ece4", linewidth=0.8, alpha=0.9)
            fig.subplots_adjust(left=0.28, right=0.94, top=0.9, bottom=0.15)
            canvas.draw()

    def gerar_dashboard(self, show_feedback: bool = True) -> None:
        if not MATPLOTLIB_INSTALADO:
            return

        self._dashboard_carregado = True
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        dias_intervalo = (self.dt_fim.date().toPyDate() - self.dt_inicio.date().toPyDate()).days + 1
        if show_feedback:
            self.lbl_execucao.setText("Atualizando dashboard...")
        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_dashboard, d_ini, d_fim, dias_intervalo),
            "Atualizando dashboard...",
            self._aplicar_dashboard,
        )

    def carregar_inicial(self) -> None:
        if not self._dashboard_carregado:
            self.gerar_dashboard(show_feedback=False)

    @staticmethod
    def _tarefa_excel_fluxo(db, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(15, "Coletando dados do fluxo...")
        df = db.dataframe_fluxo(d_ini, d_fim)
        if df.empty:
            raise ValueError("Sem dados no periodo.")
        if is_cancelled():
            return None
        progress(75, "Gravando arquivo Excel...")
        neutralize_dataframe(df).to_excel(caminho, index=False)
        progress(100, "Excel concluido.")
        return caminho

    @staticmethod
    def _tarefa_excel_bruto(db, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(15, "Coletando dados brutos...")
        df = db.dataframe_historico(d_ini, d_fim)
        if df.empty:
            raise ValueError("Sem dados brutos no periodo.")
        if is_cancelled():
            return None
        progress(75, "Gravando arquivo Excel...")
        neutralize_dataframe(df).to_excel(caminho, index=False)
        progress(100, "Excel concluido.")
        return caminho

    @classmethod
    def _tarefa_pdf_diario(cls, db_path, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(10, "Coletando dados do PDF diario...")
        with report_connection(db_path) as conn:
            service = RelatorioDataService(conn)
            dados = service.coletar_dados_pdf_diario(d_ini, d_fim)
        if not dados:
            raise ValueError("Sem dados no periodo.")
        if is_cancelled():
            return None
        progress(65, "Renderizando PDF diario...")
        pdf = RelatorioPdfDiarioBuilder().criar_pdf_resumo_diario(dados)
        pdf.output(caminho)
        progress(100, "PDF diario concluido.")
        return caminho

    @classmethod
    def _tarefa_pdf_geral(cls, db_path, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(10, "Coletando dados do PDF analitico...")
        with report_connection(db_path) as conn:
            service = RelatorioDataService(conn)
            dados = service.coletar_dados_pdf_geral(d_ini, d_fim)
        if not dados:
            raise ValueError("Sem dados no periodo.")
        if is_cancelled():
            return None
        progress(65, "Renderizando PDF analitico...")
        pdf = RelatorioPdfGeralBuilder().criar_pdf_geral_fazenda(d_ini, d_fim, dados)
        pdf.output(caminho)
        progress(100, "PDF analitico concluido.")
        return caminho

    @classmethod
    def _tarefa_pdf_mudas(cls, db_path, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(10, "Coletando historico de fazendas...")
        with report_connection(db_path) as conn:
            service = RelatorioDataService(conn)
            dados = service.coletar_dados_pdf_fazendas_muda(d_ini, d_fim)
        if not dados:
            raise ValueError("Sem fazendas de muda com notas no periodo.")
        if is_cancelled():
            return None
        progress(65, "Renderizando PDF historico...")
        pdf = RelatorioPdfFazendasMudaBuilder().criar_pdf_fazendas_muda(d_ini, d_fim, dados)
        pdf.output(caminho)
        progress(100, "PDF historico concluido.")
        return caminho

    @classmethod
    def _tarefa_pdf_simplificado(cls, db_path, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(10, "Coletando dados do PDF simplificado...")
        with report_connection(db_path) as conn:
            service = RelatorioDataService(conn)
            dados = service.coletar_dados_pdf_simplificado(d_ini, d_fim)
        if not dados:
            raise ValueError("Sem dados no periodo.")
        if is_cancelled():
            return None
        progress(65, "Renderizando PDF simplificado...")
        pdf = RelatorioPdfSimplificadoBuilder().criar_pdf_simplificado(d_ini, d_fim, dados)
        pdf.output(caminho)
        progress(100, "PDF simplificado concluido.")
        return caminho

    @classmethod
    def _tarefa_pdf_fechamento(cls, db_path, d_ini: str, d_fim: str, caminho: str, progress, is_cancelled):
        progress(10, "Coletando dados do fechamento de safra...")
        with report_connection(db_path) as conn:
            service = RelatorioDataService(conn)
            dados = service.coletar_dados_pdf_fechamento_safra(d_ini, d_fim)
        if not dados:
            raise ValueError("Sem dados no periodo.")
        if is_cancelled():
            return None
        progress(65, "Renderizando PDF final de safra...")
        pdf = RelatorioPdfFechamentoBuilder().criar_pdf_fechamento_safra(d_ini, d_fim, dados)
        pdf.output(caminho)
        progress(100, "PDF final de safra concluido.")
        return caminho

    def _on_arquivo_concluido(self, caminho: str) -> None:
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Arquivo gerado com sucesso.\n\n{caminho}")

    def gerar_excel_fluxo(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar Excel",
            f"Fluxo_{d_ini}_a_{d_fim}.xlsx",
            "Excel (*.xlsx)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_excel_fluxo, self.db, d_ini, d_fim, caminho),
            "Gerando Excel de fluxo...",
            self._on_arquivo_concluido,
        )

    def gerar_excel_bruto(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        nome_arquivo = f"Dados_Brutos_{d_ini}_a_{d_fim}.xlsx"
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar Dados Brutos",
            nome_arquivo,
            "Excel (*.xlsx)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_excel_bruto, self.db, d_ini, d_fim, caminho),
            "Gerando Excel bruto...",
            self._on_arquivo_concluido,
        )

    def gerar_pdf_resumo(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar PDF",
            f"Resumo_Diario_{d_ini}_a_{d_fim}.pdf",
            "PDF (*.pdf)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_pdf_diario, self.db.path, d_ini, d_fim, caminho),
            "Gerando PDF diario...",
            self._on_arquivo_concluido,
        )

    def gerar_pdf_geral_fazenda(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar PDF Analitico",
            f"Relatorio_Fluxo_{d_ini}_a_{d_fim}.pdf",
            "PDF (*.pdf)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_pdf_geral, self.db.path, d_ini, d_fim, caminho),
            "Gerando PDF analitico...",
            self._on_arquivo_concluido,
        )

    def gerar_pdf_fazendas_muda(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar PDF Historico de Fazendas de Muda",
            f"Relatorio_Historico_Fazendas_Muda_{d_ini}_a_{d_fim}.pdf",
            "PDF (*.pdf)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_pdf_mudas, self.db.path, d_ini, d_fim, caminho),
            "Gerando PDF historico de mudas...",
            self._on_arquivo_concluido,
        )

    def gerar_pdf_simplificado(self) -> None:
        self._ensure_date_range()
        d_ini, d_fim = self._get_datas_sql()
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar PDF Simplificado",
            f"Relatorio_Simplificado_{d_ini}_a_{d_fim}.pdf",
            "PDF (*.pdf)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_pdf_simplificado, self.db.path, d_ini, d_fim, caminho),
            "Gerando PDF simplificado...",
            self._on_arquivo_concluido,
        )

    def gerar_pdf_fechamento_safra(self) -> None:
        self._ensure_date_range()
        ano_safra = self.dt_fim.date().year()
        d_ini = f"{ano_safra}-01-01"
        d_fim = f"{ano_safra}-12-31"
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar PDF Final de Safra",
            f"Relatorio_Final_Safra_{ano_safra}.pdf",
            "PDF (*.pdf)",
        )
        if not caminho:
            return

        self._iniciar_tarefa(
            BackgroundTask(self._tarefa_pdf_fechamento, self.db.path, d_ini, d_fim, caminho),
            "Gerando PDF final de safra...",
            self._on_arquivo_concluido,
        )
