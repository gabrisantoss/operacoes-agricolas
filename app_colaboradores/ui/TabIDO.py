# ui/TabIDO.py – versão corrigida

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import pyqtSignal
from datetime import datetime
import pandas as pd
import os
import re
import threading
from openpyxl import load_workbook
import logging
import sys
import tempfile
from pathlib import Path

from funcoes_colaboradores import get_db_connection

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from agricola_shared.report_security import neutralize_dataframe


def _norm(text: str) -> str:
    """Normaliza o texto para comparação: maiúsculo, sem acentos, sem espaços extras."""
    if not isinstance(text, str):
        return ""
    return ' '.join(text.strip().upper().replace('Ç', 'C').replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U').replace('Ã', 'A').replace('Õ', 'O').replace('Â', 'A').replace('Ê', 'E').replace('Ô', 'O').split())


def _prepare_ido_export_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.copy()
    total_column = next((column for column in prepared.columns if _norm(column) == "TOTAL DE INFORMES"), None)
    if total_column is not None:
        numeric = pd.to_numeric(prepared[total_column], errors="coerce")
        if numeric.notna().all() and (numeric % 1 == 0).all():
            numeric = numeric.astype("int64")
        prepared[total_column] = numeric

    period_column = next((column for column in prepared.columns if _norm(column) == "PERIODO"), None)
    if period_column is not None:
        original = prepared[period_column]
        parsed = pd.to_datetime(original, format="%m/%Y", errors="coerce")
        prepared[period_column] = parsed.where(parsed.notna(), original)

    return neutralize_dataframe(prepared)


def _write_ido_excel(dataframe: pd.DataFrame, output_path) -> str:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}.", suffix=".tmp.xlsx", dir=target.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with pd.ExcelWriter(
            temporary_path,
            engine="xlsxwriter",
            datetime_format="mm/yyyy",
            engine_kwargs={"options": {"strings_to_formulas": False}},
        ) as writer:
            dataframe.to_excel(writer, sheet_name="IDO", index=False)
            workbook = writer.book
            worksheet = writer.sheets["IDO"]
            header_format = workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#D9EAF7",
                    "border": 1,
                    "text_wrap": True,
                    "valign": "vcenter",
                }
            )
            integer_format = workbook.add_format({"num_format": "0"})
            period_format = workbook.add_format({"num_format": "mm/yyyy"})

            for column_index, column in enumerate(dataframe.columns):
                worksheet.write(0, column_index, column, header_format)
                rendered = dataframe[column].map(
                    lambda value: "" if pd.isna(value) else str(value)
                ) if not dataframe.empty else pd.Series(dtype=str)
                content_width = rendered.map(len).max() if not rendered.empty else 0
                # XlsxWriter acrescenta aproximadamente 0,71 unidade à largura
                # serializada. Limitar a 41 mantém a largura efetiva abaixo de 42.
                width = min(max(int(content_width or 0), len(str(column))) + 2, 41)
                cell_format = None
                if _norm(column) == "TOTAL DE INFORMES":
                    cell_format = integer_format
                elif _norm(column) == "PERIODO":
                    cell_format = period_format
                worksheet.set_column(column_index, column_index, width, cell_format)

            worksheet.set_row(0, 30)
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, len(dataframe), max(len(dataframe.columns) - 1, 0))

        os.replace(temporary_path, target)
        return str(target)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


class TabIDO(QtWidgets.QWidget):
    importacao_finalizada = pyqtSignal(str, str)  # título, mensagem

    def __init__(self, main_window: QtWidgets.QMainWindow):
        super().__init__()
        self.main_window = main_window
        self.import_thread = None
        self.importacao_finalizada.connect(self._on_importacao_finalizada)

        self._setup_ui()
        self.carregar_dados_da_tabela()

    # --------------------------------------------------------------------- UI
    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # ‣ título
        titulo = QtWidgets.QLabel("📊 Informes Diários de Operação (IDO)")
        titulo.setObjectName("mainTitle")
        titulo.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(titulo)

        # ‣ barra de controles
        controles = QtWidgets.QHBoxLayout()

        controles.addWidget(QtWidgets.QLabel("Visualizar Ano:"))
        self.combo_ano_view = QtWidgets.QComboBox()
        ano_atual = datetime.now().year
        self.combo_ano_view.addItems([str(a) for a in range(ano_atual - 3, ano_atual + 2)])
        self.combo_ano_view.setCurrentText(str(ano_atual))
        self.combo_ano_view.currentIndexChanged.connect(self.carregar_dados_da_tabela)
        controles.addWidget(self.combo_ano_view)

        controles.addWidget(QtWidgets.QLabel("Visualizar Mês:"))
        self.combo_mes_view = QtWidgets.QComboBox()
        self.combo_mes_view.addItems(
            ["Todos", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        )
        self.combo_mes_view.setCurrentIndex(0)
        self.combo_mes_view.currentIndexChanged.connect(self.carregar_dados_da_tabela)
        controles.addWidget(self.combo_mes_view)

        controles.addStretch()

        self.btn_importar = QtWidgets.QPushButton("📁 Importar IDO do Excel")
        self.btn_importar.clicked.connect(self._iniciar_importacao_ido_excel)
        controles.addWidget(self.btn_importar)

        self.btn_exportar = QtWidgets.QPushButton("📤 Exportar para Excel")
        self.btn_exportar.clicked.connect(self._exportar_para_excel)
        controles.addWidget(self.btn_exportar)

        layout.addLayout(controles)

        # ‣ status
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # ‣ tabela
        self.tabela_ido = QtWidgets.QTableWidget()
        self.tabela_ido.setColumnCount(6)
        self.tabela_ido.setHorizontalHeaderLabels(
            ["Nome", "Código", "Matrícula", "Seção", "Total de Informes", "Período"]
        )
        self.tabela_ido.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tabela_ido.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.tabela_ido.setAlternatingRowColors(True)
        self.tabela_ido.setSortingEnabled(True)
        self.tabela_ido.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tabela_ido.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.tabela_ido)

    # ---------------------------------------------------------------- importação
    def _iniciar_importacao_ido_excel(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Selecionar Arquivo IDO", "", "Planilhas (*.xlsx *.xls)"
        )
        if not file_path:
            return

        self.status_label.setText(f"Importando '{os.path.basename(file_path)}'... Aguarde.")
        self.btn_importar.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        self.import_thread = threading.Thread(
            target=self._processar_importacao_ido, args=(file_path,), daemon=True
        )
        self.import_thread.start()

    def _extract_periodo_from_text(self, text: str, meses_map: dict):
        """
        Retorna (mês_int, ano_int) extraídos de “MAIO 2025”, “05/2025”, etc.
        """
        match = re.search(r'(\w+)\s*[ /]\s*(\d{4})', text)
        if not match:
            return None, None

        mes_str, ano_str = match.groups()
        mes = meses_map.get(mes_str.strip().upper())
        ano = int(ano_str.strip())
        return (mes, ano) if mes else (None, None)


    def _processar_importacao_ido(self, file_path: str):
        try:
            meses_map = {"JANEIRO":1,"FEVEREIRO":2,"MARCO":3,"MARÇO":3,"ABRIL":4,"MAIO":5,
                         "JUNHO":6,"JULHO":7,"AGOSTO":8,"SETEMBRO":9,"OUTUBRO":10,"NOVEMBRO":11,"DEZEMBRO":12}
            conn = get_db_connection()
            cursor = conn.cursor()
            total_inseridos = 0

            for sheet_name in pd.ExcelFile(file_path, engine="openpyxl").sheet_names:
                mes, ano = self._extract_periodo_from_text(sheet_name.upper(), meses_map)
                if not (mes and ano):
                    logging.info("Aba %s ignorada: período inválido", sheet_name); continue

                df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine="openpyxl")

                # localiza a linha do cabeçalho → onde aparece “NOME” (caso-insens, sem acento)
                header_row_series = df.apply(lambda row: row.astype(str).str.upper().str.contains("NOME"), axis=1).any(axis=1)
                if not header_row_series.any():
                    logging.warning("Cabeçalho com 'NOME' não encontrado na aba %s. Ignorando.", sheet_name)
                    continue
                header_row = header_row_series.idxmax()

                df.columns = [_norm(str(c)) for c in df.iloc[header_row]]
                df = df.iloc[header_row+1:].reset_index(drop=True)

                # renomeia colunas-chave (usa qualquer variação encontrada)
                col_nome = next((c for c in df.columns if _norm("NOME") in c), None)
                col_cod  = next((c for c in df.columns if _norm("COD") in c), None)
                if not col_nome or not col_cod:
                    logging.warning("Colunas 'NOME' ou 'COD' não encontradas na aba %s. Ignorando.", sheet_name)
                    continue

                col_mat  = next((c for c in df.columns if _norm("MATRICULA") in c), None)
                col_sec  = next((c for c in df.columns if _norm("SECAO") in c or _norm("FRENTE") in c), None)

                dias_cols = [c for c in df.columns if str(c).isdigit()]
                if not dias_cols:
                    logging.warning("Nenhuma coluna de dia (numérica) achada em %s", sheet_name)
                    continue

                df_dias = df[dias_cols]
                df_base = df[[col_nome, col_cod] + ([col_mat] if col_mat else []) + ([col_sec] if col_sec else [])]

                # Garante que as colunas de dias sejam numéricas, tratando erros
                df_dias = df_dias.apply(pd.to_numeric, errors='coerce').fillna(0)

                derretido = (df_dias
                             .ne(0)
                             .astype(int)
                             .stack()
                             .reset_index(name="MARCA")
                             .rename(columns={"level_0": "ROW", "level_1": "DIA"}))

                if derretido.empty or derretido["MARCA"].sum() == 0:
                    logging.warning("Nenhum registro marcado em %s/%s", mes, ano)
                    continue

                derretido["DIA"] = derretido["DIA"].astype(int)
                final = (derretido.join(df_base, on="ROW")
                                   .query("MARCA == 1")
                                   .drop(columns=["ROW","MARCA"]))

                # grava
                cursor.execute("DELETE FROM informes_diarios_detalhe WHERE cabecalho_id IN "
                               "(SELECT id FROM informes_diarios_cabecalho WHERE mes=? AND ano=?)", (mes, ano))
                cursor.execute("DELETE FROM informes_diarios_cabecalho WHERE mes=? AND ano=?", (mes, ano))
                cursor.execute(
                    "INSERT INTO informes_diarios_cabecalho (mes, ano, nome_arquivo, data_importacao) "
                    "VALUES (?,?,?,?) RETURNING id",
                    (mes, ano, os.path.basename(file_path), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                cab_id = cursor.fetchone()[0]

                registros = []
                for _, row in final.iterrows():
                    codigo_limpo = str(row[col_cod]).split('.')[0] if pd.notna(row[col_cod]) else ""
                    if not codigo_limpo: continue

                    registros.append((
                        cab_id,
                        codigo_limpo,
                        row[col_nome] if pd.notna(row[col_nome]) else "",
                        str(row[col_mat]).split('.')[0] if col_mat and pd.notna(row[col_mat]) else "",
                        row[col_sec] if col_sec and pd.notna(row[col_sec]) else "",
                        None,  # turno_safra não disponível aqui
                        int(row["DIA"]),
                        1,
                        "CONTAGEM_DIARIA"
                    ))

                if not registros: continue

                cursor.executemany(
                    "INSERT INTO informes_diarios_detalhe "
                    "(cabecalho_id, codigo_colaborador, nome_colaborador, codigo_interno, frente, "
                    " turno_safra, dia, valor_ido, tipo_valor) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", registros)

                total_inseridos += len(registros)
                logging.info("Inseridos %s registros em %02d/%d", len(registros), mes, ano)

            conn.commit()
            conn.close()
            logging.info("Importação concluída: %d registros ao todo.", total_inseridos)
            self.importacao_finalizada.emit("Sucesso", f"{total_inseridos} registros importados.")

        except Exception as exc:
            logging.exception("Erro durante a importação do IDO")
            self.importacao_finalizada.emit("Erro", f"Ocorreu um erro crítico: {exc}")

    # ---------------------------------------------------------------- sinais
    def _on_importacao_finalizada(self, titulo: str, mensagem: str):
        self.status_label.setText("")
        self.btn_importar.setEnabled(True)

        if titulo == "Erro":
            QtWidgets.QMessageBox.critical(self, titulo, mensagem)
        else:
            QtWidgets.QMessageBox.information(self, titulo, mensagem)

        self.carregar_dados_da_tabela()

    # ---------------------------------------------------------------- consulta
    def carregar_dados_da_tabela(self):
        self.tabela_ido.setSortingEnabled(False)
        self.tabela_ido.setRowCount(0)

        ano = int(self.combo_ano_view.currentText())
        mes_index = self.combo_mes_view.currentIndex()  # 0 = Todos

        conn = get_db_connection()
        cursor = conn.cursor()

        if mes_index == 0:  # todos os meses
            query = """
                SELECT  d.nome_colaborador,
                        d.codigo_colaborador,
                        d.codigo_interno,
                        CAST(c.mes AS TEXT) || '/' || CAST(c.ano AS TEXT) AS periodo,
                        COUNT(*) AS total
                FROM    informes_diarios_detalhe d
                JOIN    informes_diarios_cabecalho c ON c.id = d.cabecalho_id
                WHERE   c.ano = ?
                GROUP BY d.codigo_colaborador, d.nome_colaborador, d.codigo_interno, c.ano, c.mes
                ORDER BY c.ano, c.mes, d.nome_colaborador
            """
            cursor.execute(query, (ano,))
        else:  # mês específico
            query = """
                SELECT  d.nome_colaborador,
                        d.codigo_colaborador,
                        d.codigo_interno,
                        CAST(c.mes AS TEXT) || '/' || CAST(c.ano AS TEXT) AS periodo,
                        COUNT(*) AS total
                FROM    informes_diarios_detalhe d
                JOIN    informes_diarios_cabecalho c ON c.id = d.cabecalho_id
                WHERE   c.mes = ? AND c.ano = ?
                GROUP BY d.codigo_colaborador, d.nome_colaborador, d.codigo_interno, c.ano, c.mes
                ORDER BY d.nome_colaborador
            """
            cursor.execute(query, (mes_index, ano))

        dados = cursor.fetchall()

        # Consulta para obter a seção (frente) mais recente de cada colaborador
        cursor.execute("""
            SELECT codigo_colaborador, frente_safra FROM colaboradores
        """)
        secao_map = {str(row[0]): row[1] for row in cursor.fetchall()}

        conn.close()

        # preencher tabela
        self.tabela_ido.setRowCount(len(dados))
        for i, (nome, codigo, codigo_interno, periodo, total) in enumerate(dados):
            secao = secao_map.get(str(codigo), "N/A")
            self.tabela_ido.setItem(i, 0, QtWidgets.QTableWidgetItem(nome))
            self.tabela_ido.setItem(i, 1, QtWidgets.QTableWidgetItem(str(codigo)))
            self.tabela_ido.setItem(i, 2, QtWidgets.QTableWidgetItem(str(codigo_interno)))
            self.tabela_ido.setItem(i, 3, QtWidgets.QTableWidgetItem(secao))
            self.tabela_ido.setItem(i, 4, QtWidgets.QTableWidgetItem(str(total)))
            self.tabela_ido.setItem(i, 5, QtWidgets.QTableWidgetItem(periodo))

        self.tabela_ido.setSortingEnabled(True)


    # ---------------------------------------------------------------- exportação
    def _exportar_para_excel(self):
        if self.tabela_ido.rowCount() == 0:
            QtWidgets.QMessageBox.information(self, "Exportar", "Não há dados na tabela para exportar.")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Salvar como Excel", "Relatorio_IDO_Consolidado.xlsx", "Arquivos Excel (*.xlsx)"
        )
        if not path:
            return

        try:
            colunas = [self.tabela_ido.horizontalHeaderItem(i).text()
                       for i in range(self.tabela_ido.columnCount())]
            dados = [
                {colunas[col]: self.tabela_ido.item(row, col).text() if self.tabela_ido.item(row, col) else ""
                 for col in range(self.tabela_ido.columnCount())}
                for row in range(self.tabela_ido.rowCount())
            ]
            dataframe = _prepare_ido_export_dataframe(pd.DataFrame(dados))
            _write_ido_excel(dataframe, path)
            QtWidgets.QMessageBox.information(
                self, "Sucesso", f"Relatório exportado com sucesso para:\n{path}"
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Erro ao Exportar", f"Ocorreu um erro ao exportar: {exc}"
            )
