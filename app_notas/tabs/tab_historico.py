from __future__ import annotations

import re
import sys
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from app_logging import get_logger
from styles import aplicar_icone, configure_table
from table_models import HistoricoTableModel, TextFilterProxyModel
from workers import BackgroundTask

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from agricola_shared.report_security import neutralize_dataframe


LOGGER = get_logger(__name__)

HISTORICO_HEADERS = [
    "Nota",
    "C.Mot",
    "Motorista",
    "Cam",
    "C.Op",
    "Operador",
    "Col",
    "C.FM",
    "Faz.Muda",
    "Talhao",
    "C.FP",
    "Faz.Plantio",
    "Var",
    "Dt.Col",
    "Dt.Pla",
]


class TabHistorico(QtWidgets.QWidget):
    def __init__(self, db, main_window):
        super().__init__()
        self.db = db
        self.main = main_window
        self._usar_filtro_atual = False
        self._busca_por_nota_ativa = False
        self.export_worker = None
        self._progress_dialog = None
        self._dados_carregados = False
        self.model = HistoricoTableModel(HISTORICO_HEADERS, parent=self)
        self.proxy = TextFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("PageRoot")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        topo = QtWidgets.QFrame()
        topo.setObjectName("ToolbarCard")
        topo_layout = QtWidgets.QHBoxLayout(topo)
        topo_layout.setContentsMargins(14, 10, 14, 10)
        topo_layout.setSpacing(12)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(3)

        titulo = QtWidgets.QLabel("Historico Operacional")
        titulo.setObjectName("PageTitle")
        subtitulo = QtWidgets.QLabel("Filtre, revise e exporte as notas lancadas no periodo.")
        subtitulo.setObjectName("PageSubtitle")
        subtitulo.setWordWrap(True)
        title_box.addWidget(titulo)
        title_box.addWidget(subtitulo)

        resumo_layout = QtWidgets.QHBoxLayout()
        resumo_layout.setContentsMargins(0, 0, 0, 0)
        resumo_layout.setSpacing(8)
        self.lbl_total_registros = QtWidgets.QLabel("Registros: 0")
        self.lbl_periodo = QtWidgets.QLabel("Periodo: todos")
        self.lbl_visiveis = QtWidgets.QLabel("Visiveis: 0")
        for label in (self.lbl_total_registros, self.lbl_periodo, self.lbl_visiveis):
            label.setObjectName("SummaryBadge")
            resumo_layout.addWidget(label)

        topo_layout.addLayout(title_box, 1)
        topo_layout.addLayout(resumo_layout)
        layout.addWidget(topo)

        filtros = QtWidgets.QFrame()
        filtros.setObjectName("ToolbarCard")
        filtros_layout = QtWidgets.QVBoxLayout(filtros)
        filtros_layout.setContentsMargins(14, 12, 14, 12)
        filtros_layout.setSpacing(10)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        self.ed_pesq = QtWidgets.QLineEdit()
        self.ed_pesq.setPlaceholderText("Pesquisar por nota, motorista, operador, origem ou destino...")
        self.ed_pesq.returnPressed.connect(self._aplicar_busca_digitada)
        self.ed_pesq.setMinimumHeight(40)

        self.cb_campo = QtWidgets.QComboBox()
        self.cb_campo.addItems(
            ["Todos os campos", "Nota", "Motorista", "Operador", "Origem", "Destino", "Variedade"]
        )
        self.cb_campo.currentIndexChanged.connect(self._aplicar_busca_digitada)
        self.cb_campo.setMinimumHeight(40)

        self.dt_de = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addDays(-7))
        self.dt_de.setCalendarPopup(True)
        self.dt_de.setDisplayFormat("dd/MM/yyyy")
        self.dt_ate = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.dt_ate.setCalendarPopup(True)
        self.dt_ate.setDisplayFormat("dd/MM/yyyy")
        for campo_data in (self.dt_de, self.dt_ate):
            campo_data.setMinimumHeight(40)
            campo_data.setMinimumWidth(120)

        btn_filtrar = QtWidgets.QPushButton(" Filtrar")
        btn_filtrar.setObjectName("PrimaryButton")
        btn_filtrar.clicked.connect(lambda: self.carregar_dados(True))
        btn_todos = QtWidgets.QPushButton(" Todos")
        btn_todos.setObjectName("SecondaryButton")
        btn_todos.clicked.connect(lambda: self.carregar_dados(False))
        btn_hoje = QtWidgets.QPushButton(" Hoje")
        btn_hoje.setObjectName("QuickFilterButton")
        btn_hoje.clicked.connect(self.filtrar_hoje)
        btn_7d = QtWidgets.QPushButton(" 7 dias")
        btn_7d.setObjectName("QuickFilterButton")
        btn_7d.clicked.connect(lambda: self.aplicar_periodo_rapido(7))
        btn_30d = QtWidgets.QPushButton(" 30 dias")
        btn_30d.setObjectName("QuickFilterButton")
        btn_30d.clicked.connect(lambda: self.aplicar_periodo_rapido(30))
        self.btn_exportar = QtWidgets.QPushButton(" Excel")
        self.btn_exportar.setObjectName("SuccessButton")
        self.btn_exportar.clicked.connect(self.exportar)

        for botao in (btn_filtrar, btn_todos, btn_hoje, btn_7d, btn_30d, self.btn_exportar):
            botao.setMinimumHeight(40)

        aplicar_icone(self.btn_exportar, "fa5s.file-excel")
        aplicar_icone(btn_filtrar, "fa5s.filter")
        aplicar_icone(btn_todos, "fa5s.list")
        aplicar_icone(btn_hoje, "fa5s.calendar-day")
        aplicar_icone(btn_7d, "fa5s.calendar-week")
        aplicar_icone(btn_30d, "fa5s.calendar-alt")

        top.addWidget(self.ed_pesq, 2)
        top.addWidget(self.cb_campo)
        top.addWidget(btn_todos)
        filtros_layout.addLayout(top)

        row_periodo = QtWidgets.QHBoxLayout()
        row_periodo.setSpacing(10)
        lbl_de = QtWidgets.QLabel("De:")
        lbl_de.setObjectName("FormLabel")
        lbl_ate = QtWidgets.QLabel("Ate:")
        lbl_ate.setObjectName("FormLabel")
        row_periodo.addWidget(lbl_de)
        row_periodo.addWidget(self.dt_de)
        row_periodo.addWidget(lbl_ate)
        row_periodo.addWidget(self.dt_ate)
        row_periodo.addSpacing(8)
        row_periodo.addWidget(btn_filtrar)
        row_periodo.addWidget(btn_hoje)
        row_periodo.addWidget(btn_7d)
        row_periodo.addWidget(btn_30d)
        row_periodo.addStretch()
        row_periodo.addWidget(self.btn_exportar)
        filtros_layout.addLayout(row_periodo)
        layout.addWidget(filtros)

        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy)
        configure_table(self.table, stretch_last=True)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.menu_contexto)
        self.table.doubleClicked.connect(lambda *_: self.editar_selecionado())
        self.table.setMinimumHeight(320)
        larguras = {
            0: 92,
            1: 72,
            2: 190,
            3: 72,
            4: 72,
            5: 190,
            6: 64,
            7: 86,
            8: 180,
            9: 72,
            10: 86,
            11: 200,
            12: 120,
            13: 100,
        }
        for coluna, largura in larguras.items():
            self.table.setColumnWidth(coluna, largura)
        layout.addWidget(self.table, 1)

        self._atualizar_resumo(0, "aguardando abertura da aba")

    def _periodo_sql(self) -> tuple[str, str]:
        return (
            self.dt_de.date().toString("yyyy-MM-dd"),
            self.dt_ate.date().toString("yyyy-MM-dd"),
        )

    def _buscar_registros(self, usar_filtro: bool = False, numero_prefixo: str | None = None):
        if usar_filtro:
            return self.db.buscar_notas_historico(*self._periodo_sql(), numero_prefixo=numero_prefixo)
        return self.db.buscar_notas_historico(numero_prefixo=numero_prefixo)

    def _linhas_modelo(self, rows) -> list[list[str]]:
        return [["" if value in (None, "") else str(value) for value in row] for row in rows]

    def _periodo_atual(self) -> str:
        if not self._usar_filtro_atual:
            return "todos"
        return (
            f"{self.dt_de.date().toString('dd/MM/yyyy')} a "
            f"{self.dt_ate.date().toString('dd/MM/yyyy')}"
        )

    def _definir_rows(self, rows, periodo: str | None = None) -> None:
        self.model.set_rows(self._linhas_modelo(rows))
        self._atualizar_resumo(len(rows), periodo or self._periodo_atual())

    def _recarregar_base_atual(self) -> None:
        rows = self._buscar_registros(self._usar_filtro_atual)
        self._busca_por_nota_ativa = False
        self._definir_rows(rows)

    def carregar_dados(self, usar_filtro: bool = False) -> None:
        self._dados_carregados = True
        self._usar_filtro_atual = usar_filtro
        rows = self._buscar_registros(usar_filtro)
        self._busca_por_nota_ativa = False
        self._definir_rows(rows, self._periodo_atual())
        self.filtrar(self.ed_pesq.text())

    def carregar_inicial(self) -> None:
        if not self._dados_carregados:
            self.carregar_dados(False)

    def _aplicar_busca_digitada(self) -> None:
        self.filtrar(self.ed_pesq.text())

    @staticmethod
    def _extrair_prefixo_nota(texto: str) -> tuple[bool, str]:
        texto_limpo = (texto or "").strip()
        if not texto_limpo:
            return False, ""
        return True, "".join(re.findall(r"\d+", texto_limpo))

    def filtrar(self, texto: str) -> None:
        if not self._dados_carregados:
            self.carregar_dados(False)

        campo = self.cb_campo.currentText()
        mapa_campos = {
            "Nota": [0],
            "Motorista": [2],
            "Operador": [5],
            "Origem": [8],
            "Destino": [11],
            "Variedade": [12],
        }

        if campo == "Nota":
            possui_busca, prefixo = self._extrair_prefixo_nota(texto)
            if not possui_busca:
                if self._busca_por_nota_ativa:
                    self._recarregar_base_atual()
                self.proxy.set_filter_columns([0])
                self.proxy.set_filter_text("")
                self.lbl_visiveis.setText(f"Visiveis: {self.proxy.rowCount()}")
                return

            rows = self._buscar_registros(self._usar_filtro_atual, numero_prefixo=prefixo or "__sem_resultado__")
            self._busca_por_nota_ativa = True
            self._definir_rows(rows)
            self.proxy.set_filter_columns([0])
            self.proxy.set_filter_text("")
            self.lbl_visiveis.setText(f"Visiveis: {self.proxy.rowCount()}")
            return

        if self._busca_por_nota_ativa:
            self._recarregar_base_atual()

        colunas = mapa_campos.get(campo, list(range(self.model.columnCount())))
        self.proxy.set_filter_columns(colunas)
        self.proxy.set_filter_text(texto or "")
        self.lbl_visiveis.setText(f"Visiveis: {self.proxy.rowCount()}")

    def _dados_visiveis_para_exportacao(self) -> list[dict[str, str]]:
        headers = self.model.headers()
        dados = []
        for row_index in range(self.proxy.rowCount()):
            registro = {}
            for col_index, header in enumerate(headers):
                index = self.proxy.index(row_index, col_index)
                registro[header] = str(self.proxy.data(index) or "")
            dados.append(registro)
        return dados

    def _criar_dialogo_progresso(self, titulo: str, mensagem: str, worker: BackgroundTask) -> QtWidgets.QProgressDialog:
        dialog = QtWidgets.QProgressDialog(mensagem, "Cancelar", 0, 100, self)
        dialog.setWindowTitle(titulo)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(worker.cancelar)
        return dialog

    def exportar(self) -> None:
        if self.export_worker and self.export_worker.isRunning():
            QtWidgets.QMessageBox.information(self, "Aguarde", "Ja existe uma exportacao em andamento.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar Excel",
            "Historico.xlsx",
            "Excel (*.xlsx)",
        )
        if not caminho:
            return

        dados = self._dados_visiveis_para_exportacao()
        if not dados:
            QtWidgets.QMessageBox.information(
                self,
                "Sem dados",
                "Nao ha linhas visiveis para exportar com o filtro atual.",
            )
            return

        self.btn_exportar.setEnabled(False)
        self.export_worker = BackgroundTask(self._exportar_excel_tarefa, dados, caminho)
        self._progress_dialog = self._criar_dialogo_progresso(
            "Exportando historico",
            "Preparando planilha...",
            self.export_worker,
        )
        self.export_worker.progresso.connect(self._atualizar_progresso_exportacao)
        self.export_worker.concluido.connect(self._on_exportar_concluido)
        self.export_worker.erro.connect(self._on_exportar_erro)
        self.export_worker.cancelado.connect(self._on_exportar_cancelado)
        self.export_worker.finished.connect(self._finalizar_exportacao)
        self.export_worker.start()
        self._progress_dialog.show()

    @staticmethod
    def _exportar_excel_tarefa(dados, caminho, progress, is_cancelled):
        if is_cancelled():
            return None
        progress(15, "Montando DataFrame...")
        import pandas as pd

        df = pd.DataFrame(dados)
        if is_cancelled():
            return None
        progress(70, "Gravando arquivo Excel...")
        neutralize_dataframe(df).to_excel(caminho, index=False)
        progress(100, "Exportacao concluida.")
        return caminho

    def _atualizar_progresso_exportacao(self, valor: int, mensagem: str) -> None:
        dialog = self._progress_dialog
        if dialog is None:
            return
        dialog.setValue(valor)
        if mensagem:
            dialog.setLabelText(mensagem)

    def _on_exportar_concluido(self, caminho) -> None:
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Historico exportado com sucesso.\n\n{caminho}")

    def _on_exportar_erro(self, mensagem: str) -> None:
        LOGGER.exception("Falha ao exportar historico")
        QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel exportar:\n{mensagem}")

    def _on_exportar_cancelado(self, mensagem: str) -> None:
        QtWidgets.QMessageBox.information(self, "Cancelado", mensagem)

    def _finalizar_exportacao(self) -> None:
        self.btn_exportar.setEnabled(True)
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None
        if self.export_worker:
            self.export_worker.deleteLater()
            self.export_worker = None

    def aplicar_periodo_rapido(self, dias: int) -> None:
        hoje = QtCore.QDate.currentDate()
        self.dt_ate.setDate(hoje)
        self.dt_de.setDate(hoje.addDays(-(dias - 1)))
        self.carregar_dados(True)

    def filtrar_hoje(self) -> None:
        hoje = QtCore.QDate.currentDate()
        self.dt_de.setDate(hoje)
        self.dt_ate.setDate(hoje)
        self.carregar_dados(True)

    def _atualizar_resumo(self, total: int, periodo: str) -> None:
        self.lbl_total_registros.setText(f"Registros: {total}")
        self.lbl_periodo.setText(f"Periodo: {periodo}")
        self.lbl_visiveis.setText(f"Visiveis: {self.proxy.rowCount()}")

    def menu_contexto(self, posicao) -> None:
        menu = QtWidgets.QMenu()
        menu.addAction("Editar no lancamento").triggered.connect(self.editar_selecionado)
        menu.addAction("Excluir").triggered.connect(self.excluir)
        menu.exec_(self.table.viewport().mapToGlobal(posicao))

    def _numero_nota_selecionada(self) -> str | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        source_index = self.proxy.mapToSource(index)
        return self.model.row_values(source_index.row())[0]

    def editar_selecionado(self) -> None:
        numero = self._numero_nota_selecionada()
        if not numero:
            return
        self.main.tab_lanc.carregar_nota_para_edicao(numero)

    def excluir(self) -> None:
        numero = self._numero_nota_selecionada()
        if not numero:
            return

        resposta = QtWidgets.QMessageBox.question(
            self,
            "Excluir registro",
            "Deseja excluir a nota selecionada?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if resposta != QtWidgets.QMessageBox.Yes:
            return

        try:
            self.db.excluir_nota(numero)
            self.carregar_dados(self._usar_filtro_atual)
            self.main._atualizar_contadores()
            self.main.status.showMessage("Nota excluida com sucesso.", 2500)
        except Exception as exc:
            LOGGER.exception("Falha ao excluir nota")
            QtWidgets.QMessageBox.critical(self, "Erro", f"Nao foi possivel excluir a nota:\n{exc}")
