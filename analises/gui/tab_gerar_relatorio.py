import csv
import os
from PyQt5 import QtCore
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                           QMessageBox, QComboBox, QFileDialog, QGridLayout,
                           QGroupBox, QHeaderView, QDateEdit, QApplication, QFormLayout)
from PyQt5.QtCore import QDate, QSettings
from datetime import datetime
from core.query_logic import buscar_registros_operacao, get_distinct_items
from core.operational_fleet import is_operational_fleet
from reporting.daily_operations_report import gerar_relatorio
from reporting.database_excel_export import export_database_to_excel
from reporting.front_efficiency_report import gerar_relatorio_eficiencia_frentes
from core.settings import get_setting
from agricola_shared.report_security import neutralize_csv_row

class GerarRelatorioTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("SuaEmpresa", "AppRelatoriosAgricolas")
        self.init_ui()
        self.populate_filter_combos()

    def init_ui(self):
        layout = QVBoxLayout(self)

        title_label = QLabel("ANÁLISE E CONSULTA DE OPERAÇÕES")
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        # Grupo de Filtros
        filtros_group_box = QGroupBox("Filtros de Relatório")
        filtros_grid = QGridLayout(filtros_group_box)

        self.filtro_data_inicial = QDateEdit(calendarPopup=True)
        self.filtro_data_inicial.setDisplayFormat("dd/MM/yyyy")
        self.filtro_data_inicial.setDate(QDate.currentDate())
        filtros_grid.addWidget(QLabel("Data Inicial:"), 0, 0)
        filtros_grid.addWidget(self.filtro_data_inicial, 0, 1)

        self.filtro_data_final = QDateEdit(calendarPopup=True)
        self.filtro_data_final.setDisplayFormat("dd/MM/yyyy")
        self.filtro_data_final.setDate(QDate.currentDate())
        filtros_grid.addWidget(QLabel("Data Final:"), 0, 2)
        filtros_grid.addWidget(self.filtro_data_final, 0, 3)

        self.filtro_frente = QComboBox()
        filtros_grid.addWidget(QLabel("Frente:"), 1, 0)
        filtros_grid.addWidget(self.filtro_frente, 1, 1)

        self.filtro_turno = QComboBox()
        self.filtro_turno.addItems(["Todos", "1", "2"])
        filtros_grid.addWidget(QLabel("Turno:"), 1, 2)
        filtros_grid.addWidget(self.filtro_turno, 1, 3)

        self.filtro_frota = QComboBox()
        filtros_grid.addWidget(QLabel("Frota:"), 2, 0)
        filtros_grid.addWidget(self.filtro_frota, 2, 1)

        self.filtro_pesquisa_texto = QLineEdit(placeholderText="Pesquisar no motivo, fundo...")
        filtros_grid.addWidget(QLabel("Pesquisa em Texto:"), 2, 2)
        filtros_grid.addWidget(self.filtro_pesquisa_texto, 2, 3)

        layout.addWidget(filtros_group_box)

        # Painel de Resumo
        summary_group_box = QGroupBox("Resumo do Filtro")
        summary_layout = QFormLayout(summary_group_box)

        self.lbl_total_ocorrencias = QLabel("0")
        self.lbl_total_horas_paradas = QLabel("00:00")
        self.lbl_eficiencia_media = QLabel("0.00 %")

        summary_layout.addRow("Total de Ocorrências:", self.lbl_total_ocorrencias)
        summary_layout.addRow("Total de Horas Paradas:", self.lbl_total_horas_paradas)
        summary_layout.addRow("Eficiência Média Operacional:", self.lbl_eficiencia_media)

        layout.addWidget(summary_group_box)

        # Botões de Ação
        botoes = QHBoxLayout()

        btn_salvar_filtro = QPushButton("Salvar Filtros")
        btn_salvar_filtro.setObjectName("SecondaryButton")
        btn_salvar_filtro.clicked.connect(self.save_filters)

        btn_carregar_filtro = QPushButton("Carregar Filtros")
        btn_carregar_filtro.setObjectName("SecondaryButton")
        btn_carregar_filtro.clicked.connect(self.load_filters)

        btn_limpar = QPushButton("Limpar Filtros")
        btn_limpar.setObjectName("SecondaryButton")
        btn_limpar.clicked.connect(self.limpar_filtros)

        btn_tabela = QPushButton("Gerar Tabela")
        btn_tabela.setObjectName("PrimaryButton")
        btn_tabela.clicked.connect(self.gerar_tabela_relatorio)

        btn_pdf_operacao = QPushButton("Gerar PDF (Operação)")
        btn_pdf_operacao.setObjectName("ExportButton")
        btn_pdf_operacao.clicked.connect(self.gerar_pdf_relatorio)

        btn_pdf_eficiencia = QPushButton("PDF (Eficiência por Frente)")
        btn_pdf_eficiencia.setObjectName("ExportButton")
        btn_pdf_eficiencia.clicked.connect(self.gerar_pdf_eficiencia_frente)

        btn_excel_banco = QPushButton("Exportar Banco Excel")
        btn_excel_banco.setObjectName("ExportButton")
        btn_excel_banco.clicked.connect(self.exportar_banco_excel)

        botoes.addWidget(btn_salvar_filtro)
        botoes.addWidget(btn_carregar_filtro)
        botoes.addStretch()
        botoes.addWidget(btn_limpar)
        botoes.addWidget(btn_tabela)
        botoes.addWidget(btn_pdf_operacao)
        botoes.addWidget(btn_pdf_eficiencia)
        botoes.addWidget(btn_excel_banco)

        layout.addLayout(botoes)

        # Tabela de Resultados
        self.table_resultado = QTableWidget()
        self.table_resultado.setColumnCount(12)
        self.table_resultado.setHorizontalHeaderLabels([
            "Data", "Frente", "Turno", "Frota", "Motivo", "Parou Hora", "Voltou Hora",
            "Total Hora Parado", "Eficiência (%)", "Fundo Agrícola", "Choveu", "Incendio"
        ])
        self.table_resultado.setSortingEnabled(True)
        self.table_resultado.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_resultado.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_resultado.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.table_resultado)
        layout.setStretchFactor(self.table_resultado, 1)

        btn_export = QPushButton("Exportar para CSV")
        btn_export.setObjectName("ExportButton")
        btn_export.clicked.connect(self.exportar_csv)
        layout.addWidget(btn_export, alignment=QtCore.Qt.AlignRight)

    def populate_filter_combos(self):
        """Preenche os QComboBox de filtros com dados do banco."""
        try:
            frentes = get_distinct_items("Frente")
            frotas = [
                frota for frota in get_distinct_items("Frota")
                if is_operational_fleet(frota)
            ]

            self.filtro_frente.addItems(["Todas"] + sorted(frentes))
            self.filtro_frota.addItems(["Todas"] + sorted(frotas))
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Erro ao carregar filtros: {e}")

    def limpar_filtros(self):
        self.filtro_data_inicial.setDate(QDate.currentDate())
        self.filtro_data_final.setDate(QDate.currentDate())
        self.filtro_frente.setCurrentIndex(0)
        self.filtro_turno.setCurrentIndex(0)
        self.filtro_frota.setCurrentIndex(0)
        self.filtro_pesquisa_texto.clear()
        self.table_resultado.setRowCount(0)
        self.update_summary_panel([])

    def save_filters(self):
        self.settings.setValue("filtro/data_inicial", self.filtro_data_inicial.date())
        self.settings.setValue("filtro/data_final", self.filtro_data_final.date())
        self.settings.setValue("filtro/frente", self.filtro_frente.currentText())
        self.settings.setValue("filtro/turno", self.filtro_turno.currentText())
        self.settings.setValue("filtro/frota", self.filtro_frota.currentText())
        self.settings.setValue("filtro/texto", self.filtro_pesquisa_texto.text())
        QMessageBox.information(self, "Filtros", "Conjunto de filtros salvo com sucesso!")

    def load_filters(self):
        data_inicial = self.settings.value("filtro/data_inicial", QDate.currentDate())
        data_final = self.settings.value("filtro/data_final", QDate.currentDate())

        self.filtro_data_inicial.setDate(data_inicial if isinstance(data_inicial, QDate) else QDate.currentDate())
        self.filtro_data_final.setDate(data_final if isinstance(data_final, QDate) else QDate.currentDate())
        self.filtro_frente.setCurrentText(self.settings.value("filtro/frente", "Todas"))
        self.filtro_turno.setCurrentText(self.settings.value("filtro/turno", "Todos"))
        self.filtro_frota.setCurrentText(self.settings.value("filtro/frota", "Todas"))
        self.filtro_pesquisa_texto.setText(self.settings.value("filtro/texto", ""))

        QMessageBox.information(self, "Filtros", "Filtros carregados. Clique em 'Gerar Tabela'.")

    def coletar_filtros(self):
        """Coleta os filtros da UI e retorna um dicionário."""
        return {
            'data_inicial': self.filtro_data_inicial.date(),
            'data_final': self.filtro_data_final.date(),
            'frente': self.filtro_frente.currentText() if self.filtro_frente.currentText() != "Todas" else None,
            'turno': self.filtro_turno.currentText() if self.filtro_turno.currentText() != "Todos" else None,
            'frota': self.filtro_frota.currentText() if self.filtro_frota.currentText() != "Todas" else None,
            'pesquisa_texto': self.filtro_pesquisa_texto.text().strip()
        }

    def update_summary_panel(self, rows):
        """Calcula e exibe as métricas de resumo."""
        num_ocorrencias = len(rows)
        total_minutos_parados = 0
        eficiencias = []

        for row in rows:
            # Coluna 3: Frota, Coluna 7: Total Hora Parado, Coluna 8: Eficiencia
            frota = row[3]
            total_parado_str = row[7]
            eficiencia = row[8]

            if total_parado_str and ':' in total_parado_str:
                try:
                    horas, minutos = map(int, total_parado_str.split(':'))
                    total_minutos_parados += horas * 60 + minutos
                except (ValueError, TypeError):
                    pass

            if is_operational_fleet(frota) and eficiencia is not None:
                try:
                    eficiencias.append(float(eficiencia))
                except (ValueError, TypeError):
                    pass

        horas = total_minutos_parados // 60
        minutos = total_minutos_parados % 60
        total_horas_paradas_str = f"{horas:02}:{minutos:02}"

        eficiencia_media = sum(eficiencias) / len(eficiencias) if eficiencias else 0.0

        self.lbl_total_ocorrencias.setText(str(num_ocorrencias))
        self.lbl_total_horas_paradas.setText(total_horas_paradas_str)
        self.lbl_eficiencia_media.setText(f"{eficiencia_media:.2f} %")

    def gerar_tabela_relatorio(self):
        QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.table_resultado.setSortingEnabled(False)

        try:
            filtros = self.coletar_filtros()
            rows = buscar_registros_operacao(filtros)
            self.update_summary_panel(rows)

            self.table_resultado.setRowCount(0)
            for row_data in rows:
                row_index = self.table_resultado.rowCount()
                self.table_resultado.insertRow(row_index)

                for col_index, cell_data in enumerate(row_data):
                    item = QTableWidgetItem()
                    # A coluna de eficiência é a de índice 8
                    if col_index == 8 and cell_data is not None:
                        try:
                            num_val = float(cell_data)
                            item.setData(QtCore.Qt.DisplayRole, f"{num_val:.2f}")
                        except (ValueError, TypeError):
                            item.setText(str(cell_data))
                    else:
                        item.setText(str(cell_data))

                    self.table_resultado.setItem(row_index, col_index, item)

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar tabela: {e}")
        finally:
            self.table_resultado.setSortingEnabled(True)
            QApplication.restoreOverrideCursor()

    def gerar_pdf_relatorio(self):
        filtros = self.coletar_filtros()
        data_inicial_str = filtros['data_inicial'].toString("dd-MM-yyyy") if filtros['data_inicial'].isValid() else None
        data_final_str = filtros['data_final'].toString("dd-MM-yyyy") if filtros['data_final'].isValid() else None
        report_path = get_setting('report_default_path', '.')

        try:
            caminho_arquivo = gerar_relatorio(
                data_inicial=data_inicial_str,
                data_final=data_final_str,
                frente_filtro=filtros['frente'],
                turno_filtro=filtros['turno'],
                frota_filtro=filtros['frota'],
                pesquisa_geral_texto=filtros['pesquisa_texto'],
                output_path=report_path
            )
            if caminho_arquivo:
                QMessageBox.information(self, "PDF", f"PDF de Operações gerado com sucesso!\n\nSalvo em: {caminho_arquivo}")
            else:
                QMessageBox.warning(self, "PDF", "Nenhum dado de colhedora ou transbordo foi encontrado para os filtros aplicados.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao gerar PDF de Operações:\n{e}")

    def gerar_pdf_eficiencia_frente(self):
        data_inicial = self.filtro_data_inicial.date()
        data_final = self.filtro_data_final.date()

        if not data_inicial.isValid() or not data_final.isValid():
            QMessageBox.warning(self, "Aviso", "Por favor, selecione uma Data Inicial e uma Data Final válidas.")
            return

        if data_inicial > data_final:
            QMessageBox.warning(self, "Aviso", "A Data Inicial não pode ser maior que a Data Final.")
            return

        data_inicial_str = data_inicial.toString("dd/MM/yyyy")
        data_final_str = data_final.toString("dd/MM/yyyy")
        report_path = get_setting('report_default_path', '.')

        try:
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            caminho_arquivo = gerar_relatorio_eficiencia_frentes(
                data_inicial_str,
                data_final_str,
                output_path=report_path
            )
            QMessageBox.information(self, "Sucesso", f"Relatório de Eficiência por Frente gerado com sucesso!\n\nSalvo em: {caminho_arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao gerar o PDF de Eficiência por Frente:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def exportar_csv(self):
        if self.table_resultado.rowCount() == 0:
            QMessageBox.warning(self, "Aviso", "Não há dados na tabela para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Salvar CSV", "relatorio.csv", "CSV (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file, delimiter=';')
                headers = [
                    self.table_resultado.horizontalHeaderItem(i).text()
                    for i in range(self.table_resultado.columnCount())
                ]
                writer.writerow(neutralize_csv_row(headers))

                for row in range(self.table_resultado.rowCount()):
                    row_data = [
                        self.table_resultado.item(row, col).text()
                        for col in range(self.table_resultado.columnCount())
                    ]
                    writer.writerow(neutralize_csv_row(row_data))

            QMessageBox.information(self, "Sucesso", "CSV exportado com sucesso!")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao exportar CSV:\n{e}")

    def exportar_banco_excel(self):
        report_path = get_setting('report_default_path', '.') or '.'
        default_name = f"backup_banco_operacional_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        default_path = os.path.join(report_path, default_name)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Excel completo do banco",
            default_path,
            "Excel (*.xlsx)"
        )
        if not path:
            return

        try:
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            caminho_arquivo = export_database_to_excel(path)
            QMessageBox.information(
                self,
                "Sucesso",
                f"Excel completo do banco gerado com sucesso!\n\nSalvo em: {caminho_arquivo}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao exportar banco para Excel:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()
