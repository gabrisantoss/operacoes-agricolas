from PyQt5 import QtCore
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                           QPushButton, QTableWidget, QTableWidgetItem, QMessageBox,
                           QComboBox, QGridLayout, QGroupBox, QHeaderView)
from datetime import datetime
from reporting.harvest_report import gerar_relatorio_colheita
from core.settings import get_setting
from .custom_widgets import SmartLineEdit
from core.database_manager import DatabaseManager

class ColheitaTab(QWidget):
    registro_salvo = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editando_colheita_id = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        current_date = datetime.now().strftime("%d/%m/%Y")

        title_colheita = QLabel("LANÇAMENTO DE COLHEITA MECANIZADA")
        title_colheita.setObjectName("SectionTitle")
        main_layout.addWidget(title_colheita)

        filtros_group_box = QGroupBox("Filtros para Tabela e Relatório")
        filtros_layout = QGridLayout(filtros_group_box)

        filtros_layout.addWidget(QLabel("Data:"), 0, 0)
        self.filtro_colheita_data = QLineEdit()
        self.filtro_colheita_data.setInputMask("00/00/0000")
        self.filtro_colheita_data.setPlaceholderText("dd/mm/aaaa")
        self.filtro_colheita_data.setText(current_date)
        filtros_layout.addWidget(self.filtro_colheita_data, 0, 1)

        filtros_layout.addWidget(QLabel("Frente:"), 0, 2)
        self.filtro_colheita_frente = QLineEdit()
        filtros_layout.addWidget(self.filtro_colheita_frente, 0, 3)

        filtros_layout.addWidget(QLabel("Turno:"), 0, 4)
        self.filtro_colheita_turno = QComboBox()
        self.filtro_colheita_turno.addItems(["", "1", "2"])
        filtros_layout.addWidget(self.filtro_colheita_turno, 0, 5)

        filtros_layout.addWidget(QLabel("Fazenda:"), 1, 0)
        self.filtro_colheita_fazenda = QLineEdit()
        filtros_layout.addWidget(self.filtro_colheita_fazenda, 1, 1)

        botoes_filtro_layout = QHBoxLayout()
        botoes_filtro_layout.addStretch()
        btn_filtrar = QPushButton("Filtrar Tabela")
        btn_filtrar.setObjectName("PrimaryButton")
        btn_filtrar.clicked.connect(self.load_data_colheita_mecanizada)
        botoes_filtro_layout.addWidget(btn_filtrar)
        filtros_layout.addLayout(botoes_filtro_layout, 1, 2, 1, 4)

        main_layout.addWidget(filtros_group_box)

        input_group_box = QGroupBox("Lançamento de Colheita Mecanizada")
        input_grid_layout = QGridLayout(input_group_box)

        input_grid_layout.addWidget(QLabel("Data:"), 0, 0)
        self.input_colheita_data = QLineEdit()
        self.input_colheita_data.setInputMask("00/00/0000")
        self.input_colheita_data.setPlaceholderText("dd/mm/aaaa")
        self.input_colheita_data.setText(current_date)
        input_grid_layout.addWidget(self.input_colheita_data, 0, 1)

        input_grid_layout.addWidget(QLabel("Frente:"), 0, 2)
        self.input_colheita_frente = SmartLineEdit()
        self.input_colheita_frente.setPlaceholderText("Número da Frente")
        input_grid_layout.addWidget(self.input_colheita_frente, 0, 3)

        input_grid_layout.addWidget(QLabel("Turno:"), 0, 4)
        self.input_colheita_turno = QComboBox()
        self.input_colheita_turno.addItems(["", "1", "2"])
        input_grid_layout.addWidget(self.input_colheita_turno, 0, 5)

        input_grid_layout.addWidget(QLabel("Fazenda:"), 1, 0)
        self.input_colheita_fazenda = SmartLineEdit()
        self.input_colheita_fazenda.setPlaceholderText("Nome da Fazenda")
        input_grid_layout.addWidget(self.input_colheita_fazenda, 1, 1)

        input_grid_layout.addWidget(QLabel("Área Colhida (ha):"), 1, 2)
        self.input_colheita_area = QLineEdit()
        self.input_colheita_area.setPlaceholderText("0.00")
        input_grid_layout.addWidget(self.input_colheita_area, 1, 3)

        input_grid_layout.addWidget(QLabel("Produtividade (ton/ha):"), 1, 4)
        self.input_colheita_produtividade = QLineEdit()
        self.input_colheita_produtividade.setPlaceholderText("0.00")
        input_grid_layout.addWidget(self.input_colheita_produtividade, 1, 5)

        input_grid_layout.addWidget(QLabel("Viagens:"), 2, 0)
        self.input_colheita_viagens = QLineEdit()
        self.input_colheita_viagens.setPlaceholderText("0")
        input_grid_layout.addWidget(self.input_colheita_viagens, 2, 1)

        botoes_salvar_layout = QHBoxLayout()
        botoes_salvar_layout.addStretch()
        btn_salvar_colheita = QPushButton("Salvar Lançamento")
        btn_salvar_colheita.setObjectName("PrimaryButton")
        btn_salvar_colheita.clicked.connect(self.salvar_ou_atualizar_colheita)
        botoes_salvar_layout.addWidget(btn_salvar_colheita)
        input_grid_layout.addLayout(botoes_salvar_layout, 2, 2, 1, 4)

        main_layout.addWidget(input_group_box)

        self.table_colheita = QTableWidget()
        self.table_colheita.setColumnCount(8)
        self.table_colheita.setHorizontalHeaderLabels([
            "ID", "Data", "Frente", "Turno", "Fazenda",
            "Área Colhida (ha)", "Produtividade (ton/ha)", "Viagens"
        ])
        self.table_colheita.hideColumn(0)
        main_layout.addWidget(self.table_colheita)
        main_layout.setStretchFactor(self.table_colheita, 1)

        self.table_colheita.cellClicked.connect(self.carregar_colheita_selecionada)

        btn_colheita_layout = QHBoxLayout()

        btn_editar_colheita = QPushButton("Editar Selecionado")
        btn_editar_colheita.setObjectName("EditButton")
        btn_editar_colheita.clicked.connect(self.editar_colheita_selecionada)

        btn_excluir_colheita = QPushButton("Excluir Selecionado")
        btn_excluir_colheita.setObjectName("DeleteButton")
        btn_excluir_colheita.clicked.connect(self.excluir_colheita_selecionada)

        btn_pdf_colheita = QPushButton("Gerar PDF de Colheita")
        btn_pdf_colheita.setObjectName("ExportButton")
        btn_pdf_colheita.clicked.connect(self.gerar_pdf_colheita)

        btn_colheita_layout.addWidget(btn_editar_colheita)
        btn_colheita_layout.addWidget(btn_excluir_colheita)
        btn_colheita_layout.addWidget(btn_pdf_colheita)

        main_layout.addLayout(btn_colheita_layout)

    def salvar_ou_atualizar_colheita(self):
        data_input = self.input_colheita_data.text().strip()
        frente = self.input_colheita_frente.text().strip()
        turno = self.input_colheita_turno.currentText().strip()
        fazenda = self.input_colheita_fazenda.text().strip()
        area_str = self.input_colheita_area.text().strip().replace(',', '.')
        prod_str = self.input_colheita_produtividade.text().strip().replace(',', '.')
        viagens_str = self.input_colheita_viagens.text().strip()

        try:
            data_db_format = datetime.strptime(data_input, "%d/%m/%Y").strftime("%d-%m-%Y")
        except ValueError:
            QMessageBox.warning(self, "Aviso", "Formato de Data inválido. Use DD/MM/AAAA.")
            return

        if not all([data_input, frente, turno, fazenda, area_str, prod_str, viagens_str]):
            QMessageBox.warning(self, "Aviso", "Todos os campos da Colheita são obrigatórios.")
            return

        try:
            area = float(area_str)
            prod = float(prod_str)
            viagens = int(viagens_str)
        except ValueError:
            QMessageBox.warning(self, "Aviso", "Área, Produtividade e Viagens devem ser números.")
            return

        if area <= 0:
            QMessageBox.warning(self, "Aviso", "A Área Colhida deve ser maior que zero.")
            return

        if prod < 0 or viagens < 0:
            QMessageBox.warning(self, "Aviso", "Produtividade e Viagens não podem ser negativas.")
            return

        try:
            if self.editando_colheita_id:
                query = """
                    UPDATE COLHEITA_MECANIZADA
                    SET Data=?, Frente=?, Turno=?, Fazenda=?, Area_Colhida=?, Produtividade=?, Viagens=?
                    WHERE id=?
                """
                params = (data_db_format, frente, turno, fazenda, area, prod, viagens, self.editando_colheita_id)
                DatabaseManager.execute_non_query(query, params)
                QMessageBox.information(self, "Sucesso", "Registro de colheita atualizado!")
            else:
                query = """
                    INSERT INTO COLHEITA_MECANIZADA (Data, Frente, Turno, Fazenda, Area_Colhida, Produtividade, Viagens)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                params = (data_db_format, frente, turno, fazenda, area, prod, viagens)
                DatabaseManager.execute_non_query(query, params)
                QMessageBox.information(self, "Sucesso", "Registro de colheita cadastrado!")

            self.clear_tab_colheita()
            self.registro_salvo.emit()

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao salvar registro de colheita:\n{e}")

    def clear_tab_colheita(self):
        self.editando_colheita_id = None
        self.input_colheita_data.setText(datetime.now().strftime("%d/%m/%Y"))
        self.input_colheita_frente.clear()
        self.input_colheita_turno.setCurrentIndex(0)
        self.input_colheita_fazenda.clear()
        self.input_colheita_area.clear()
        self.input_colheita_produtividade.clear()
        self.input_colheita_viagens.clear()
        self.input_colheita_frente.setFocus()

    def load_data_colheita_mecanizada(self):
        base_query = """
            SELECT id, Data, Frente, Turno, Fazenda, Area_Colhida, Produtividade, Viagens
            FROM COLHEITA_MECANIZADA WHERE 1=1
        """
        params = []

        data_filtro = self.filtro_colheita_data.text().strip()
        frente_filtro = self.filtro_colheita_frente.text().strip()
        turno_filtro = self.filtro_colheita_turno.currentText().strip()
        fazenda_filtro = self.filtro_colheita_fazenda.text().strip()

        if data_filtro:
            try:
                data_db = datetime.strptime(data_filtro, "%d/%m/%Y").strftime("%d-%m-%Y")
                base_query += " AND Data = ?"
                params.append(data_db)
            except ValueError:
                QMessageBox.warning(self, "Aviso", "Formato de data do filtro inválido. Use dd/mm/aaaa.")
                return

        if frente_filtro:
            base_query += " AND Frente LIKE ?"
            params.append(f"%{frente_filtro}%")

        if turno_filtro:
            base_query += " AND Turno = ?"
            params.append(turno_filtro)

        if fazenda_filtro:
            base_query += " AND Fazenda LIKE ?"
            params.append(f"%{fazenda_filtro}%")

        base_query += " ORDER BY id DESC"

        try:
            rows = DatabaseManager.execute_select(base_query, params)

            self.table_colheita.setRowCount(0)
            for row in rows:
                row_position = self.table_colheita.rowCount()
                self.table_colheita.insertRow(row_position)

                display_row = list(row)
                try:
                    display_row[1] = datetime.strptime(display_row[1], "%d-%m-%Y").strftime("%d/%m/%Y")
                except (ValueError, TypeError):
                    pass

                for column_index, value in enumerate(display_row):
                    self.table_colheita.setItem(row_position, column_index, QTableWidgetItem(str(value)))

            self.table_colheita.resizeColumnsToContents()

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao carregar dados de colheita: {e}")

    def carregar_colheita_selecionada(self, row, col):
        self.editando_colheita_id = int(self.table_colheita.item(row, 0).text())
        self.input_colheita_data.setText(self.table_colheita.item(row, 1).text())
        self.input_colheita_frente.setText(self.table_colheita.item(row, 2).text())
        self.input_colheita_turno.setCurrentText(self.table_colheita.item(row, 3).text())
        self.input_colheita_fazenda.setText(self.table_colheita.item(row, 4).text())

        area = self.table_colheita.item(row, 5).text().replace('.', ',')
        prod = self.table_colheita.item(row, 6).text().replace('.', ',')

        self.input_colheita_area.setText(area)
        self.input_colheita_produtividade.setText(prod)
        self.input_colheita_viagens.setText(self.table_colheita.item(row, 7).text())

    def editar_colheita_selecionada(self):
        current_row = self.table_colheita.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Aviso", "Selecione um registro de colheita para editar.")
            return
        self.carregar_colheita_selecionada(current_row, 0)

    def excluir_colheita_selecionada(self):
        current_row = self.table_colheita.currentRow()
        if current_row < 0:
            return

        row_id = int(self.table_colheita.item(current_row, 0).text())

        if QMessageBox.question(
            self, "Confirmação", "Deseja excluir este registro?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            try:
                query = "DELETE FROM COLHEITA_MECANIZADA WHERE id=?"
                DatabaseManager.execute_non_query(query, (row_id,))
                self.load_data_colheita_mecanizada()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao excluir registro: {e}")

    def gerar_pdf_colheita(self):
        data_filtro = self.filtro_colheita_data.text().strip() or None
        frente_filtro = self.filtro_colheita_frente.text().strip() or None
        turno_filtro = self.filtro_colheita_turno.currentText().strip() or None
        fazenda_filtro = self.filtro_colheita_fazenda.text().strip() or None

        report_path = get_setting('report_default_path', '.') or '.'

        if data_filtro and not data_filtro.replace("/", "").replace("_", "").strip():
            data_filtro = None

        if data_filtro:
            try:
                datetime.strptime(data_filtro, "%d/%m/%Y")
            except ValueError:
                QMessageBox.warning(self, "Aviso", "A data do filtro deve estar no formato DD/MM/AAAA.")
                return

        try:
            caminho_arquivo = gerar_relatorio_colheita(
                data_inicial=data_filtro, data_final=data_filtro,
                frente=frente_filtro, turno=turno_filtro, fazenda=fazenda_filtro,
                output_path=report_path
            )
            QMessageBox.information(self, "PDF Colheita", f"PDF de Colheita gerado com sucesso!\n\nSalvo em: {caminho_arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao gerar PDF de Colheita:\n{e}")
