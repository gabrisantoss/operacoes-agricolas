# gui/tab_dados.py
from PyQt5 import QtCore
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                           QPushButton, QTableWidget, QTableWidgetItem,
                           QMessageBox, QHeaderView, QComboBox) # Adicionado QComboBox
from datetime import datetime
from core.database_manager import DatabaseManager
from core.config import DatabaseConfig
from core.date_utils import sql_date_expr
from core.sql_compat import numeric_text_order_sql

class DadosTab(QWidget):
    # (Sinais permanecem os mesmos)
    editar_registro = QtCore.pyqtSignal(dict)
    dados_alterados = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- NOVO: Dicionário de Opções de Ordenação ---
        # Mapeia o texto amigável para a cláusula SQL real
        date_order = sql_date_expr("Data")
        front_order = numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE)
        self.sort_options = {
            "Mais Recentes (Data e Frente)": f"ORDER BY {date_order} DESC, {front_order} ASC",
            "Mais Antigos (Data e Frente)": f"ORDER BY {date_order} ASC, {front_order} ASC",
            "Por Frente (Crescente)": f"ORDER BY {front_order} ASC, {date_order} DESC",
            "ID (Ordem de Lançamento)": "ORDER BY id DESC"
        }

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        title_label = QLabel("BANCO DE DADOS (OPERAÇÃO DIÁRIA)")
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        # --- INÍCIO DAS NOVAS ADIÇÕES (Controles de Ordenação) ---
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("Ordenar por:"))

        self.combo_sort_order = QComboBox()
        self.combo_sort_order.addItems(self.sort_options.keys())
        controls_layout.addWidget(self.combo_sort_order)

        self.btn_refresh = QPushButton("Atualizar Tabela")
        self.btn_refresh.clicked.connect(self.load_data) # Conecta o botão à função de carregar
        controls_layout.addWidget(self.btn_refresh)

        controls_layout.addStretch() # Empurra os controles para a esquerda

        layout.addLayout(controls_layout) # Adiciona os controles à UI

        # Quando o usuário muda a seleção, a tabela recarrega automaticamente
        self.combo_sort_order.currentIndexChanged.connect(self.load_data)
        # --- FIM DAS NOVAS ADIÇÕES ---

        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "ID", "Data", "Frente", "Turno", "Frota", "Motivo", "Parou Hora", "Voltou Hora",
            "Total Hora Parado", "Eficiência (%)", "Fundo Agrícola", "Choveu", "Incendio", "Status"
        ])
        self.table.hideColumn(0)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        btn_editar = QPushButton("Editar Selecionado")
        btn_editar.setObjectName("EditButton")
        btn_editar.clicked.connect(self.editar_selecionado)

        btn_excluir = QPushButton("Excluir Selecionado")
        btn_excluir.setObjectName("DeleteButton")
        btn_excluir.clicked.connect(self.excluir_selecionado)

        btn_layout.addWidget(btn_editar)
        btn_layout.addWidget(btn_excluir)

        layout.addLayout(btn_layout)

    def load_data(self):
        try:
            # --- INÍCIO DA ALTERAÇÃO (Lógica de Ordenação) ---

            # 1. Pega a opção selecionada no ComboBox
            selected_option = self.combo_sort_order.currentText()

            # 2. Busca a cláusula SQL correspondente no dicionário
            order_by_clause = self.sort_options.get(selected_option, "ORDER BY id DESC") # Usa ID como fallback

            # 3. Monta a query dinamicamente
            query = f"""
                SELECT id, Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora,
                       Total_Hora_Parado, Eficiencia, Fundo_Agricola, Chuva, Incendio, Status_Parada
                FROM RELATORIO_OPERACAO_DIARIA
                {order_by_clause}
            """
            # --- FIM DA ALTERAÇÃO ---

            rows = DatabaseManager.execute_select(query)

            self.table.setRowCount(0)
            for row in rows:
                row_position = self.table.rowCount()
                self.table.insertRow(row_position)

                display_row = list(row)
                try:
                    date_obj = datetime.strptime(display_row[1], "%d-%m-%Y")
                    display_row[1] = date_obj.strftime("%d/%m/%Y")
                except (ValueError, TypeError):
                    pass

                for column_index, value in enumerate(display_row):
                    item = QTableWidgetItem(str(value))
                    self.table.setItem(row_position, column_index, item)

            self.table.resizeColumnsToContents()

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao carregar dados: {e}")

    def editar_selecionado(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Aviso", "Selecione um registro para editar.")
            return

        status = self.table.item(current_row, 13).text()
        if status != 'Finalizada':
            QMessageBox.information(
                self, "Aviso",
                "A edição só é permitida para registros 'Finalizados'.\n"
                "Paradas 'Em Andamento' devem ser finalizadas na aba 'Paradas em Andamento'."
            )
            return

        dados = {
            'id': int(self.table.item(current_row, 0).text()),
            'data': self.table.item(current_row, 1).text(),
            'frente': self.table.item(current_row, 2).text(),
            'turno': self.table.item(current_row, 3).text(),
            'frota': self.table.item(current_row, 4).text(),
            'motivo': self.table.item(current_row, 5).text(),
            'parou_hora': self.table.item(current_row, 6).text(),
            'voltou_hora': self.table.item(current_row, 7).text(),
            'fundo_agricola': self.table.item(current_row, 10).text(),
            'chuva': self.table.item(current_row, 11).text(),
            'incendio': self.table.item(current_row, 12).text(),
        }
        self.editar_registro.emit(dados)

    def excluir_selecionado(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Aviso", "Selecione um registro para excluir.")
            return

        row_id = int(self.table.item(current_row, 0).text())

        if QMessageBox.question(
            self, "Confirmação", "Deseja excluir este registro permanentemente?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            try:
                query = "DELETE FROM RELATORIO_OPERACAO_DIARIA WHERE id=?"
                DatabaseManager.execute_non_query(query, (row_id,))

                # 'load_data()' agora recarrega com a ordenação selecionada
                self.load_data()
                self.dados_alterados.emit()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao excluir registro: {e}")
