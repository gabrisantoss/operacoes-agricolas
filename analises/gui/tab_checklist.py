from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                           QPushButton, QGroupBox, QDateEdit, QTableWidget,
                           QTableWidgetItem, QHeaderView, QMessageBox)
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QColor
from datetime import datetime, timedelta
from core.config import DatabaseConfig
from core.database_manager import DatabaseManager
from core.date_utils import sql_date_expr
from core.sql_compat import numeric_text_order_sql

class ChecklistTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        title_label = QLabel("CHECKLIST DE ENVIO DE RELATÓRIOS POR FRENTE E TURNO")
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        # Filtros redesenhados para aceitar um período
        controles_group_box = QGroupBox("Filtro de Verificação")
        controles_layout = QHBoxLayout(controles_group_box)

        controles_layout.addWidget(QLabel("Data Inicial:"))
        self.date_start = QDateEdit(calendarPopup=True)
        self.date_start.setDate(QDate.currentDate())
        self.date_start.setDisplayFormat("dd/MM/yyyy")
        controles_layout.addWidget(self.date_start)

        controles_layout.addWidget(QLabel("Data Final:"))
        self.date_end = QDateEdit(calendarPopup=True)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setDisplayFormat("dd/MM/yyyy")
        controles_layout.addWidget(self.date_end)

        btn_verificar = QPushButton("Verificar Período")
        btn_verificar.setObjectName("PrimaryButton")
        btn_verificar.clicked.connect(self.verificar_frentes_enviadas)
        controles_layout.addWidget(btn_verificar)

        controles_layout.addStretch()
        layout.addWidget(controles_group_box)

        # Tabela para um resultado mais detalhado
        self.table_checklist = QTableWidget()
        self.table_checklist.setColumnCount(4)
        self.table_checklist.setHorizontalHeaderLabels(["Data", "Frente", "Status Turno 1", "Status Turno 2"])
        self.table_checklist.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_checklist)

    def verificar_frentes_enviadas(self):
        self.table_checklist.setRowCount(0)

        start_date = self.date_start.date()
        end_date = self.date_end.date()

        if start_date > end_date:
            QMessageBox.warning(self, "Erro de Data", "A data inicial não pode ser posterior à data final.")
            return

        # Gera a lista de datas no período selecionado
        datas_periodo = []
        current_date = start_date
        while current_date <= end_date:
            datas_periodo.append(current_date)
            current_date = current_date.addDays(1)

        try:
            # 1. Busca todas as frentes que deveriam reportar
            frente_order = numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE)
            query_frentes = (
                "SELECT Frente FROM FROTAS_POR_FRENTE "
                f"GROUP BY Frente ORDER BY {frente_order}, Frente"
            )
            todas_as_frentes = [row[0] for row in DatabaseManager.execute_select(query_frentes)]

            # 2. Busca todos os relatórios enviados no período
            query_relatorios = f"""
                SELECT Data, Frente, Turno
                FROM RELATORIO_OPERACAO_DIARIA
                WHERE {sql_date_expr('Data')}
                BETWEEN ? AND ?
            """
            params = (start_date.toString("yyyy-MM-dd"), end_date.toString("yyyy-MM-dd"))
            relatorios_data = DatabaseManager.execute_select(query_relatorios, params)

            # Cria um conjunto para busca rápida de relatórios enviados
            relatorios_enviados = set((row[0], row[1], row[2]) for row in relatorios_data)

            # 3. Monta a tabela de resultados dia a dia, frente a frente
            for data in datas_periodo:
                data_str_db = data.toString("dd-MM-yyyy")  # Formato do banco
                data_str_display = data.toString("dd/MM/yyyy")  # Formato de exibição

                for frente in todas_as_frentes:
                    # Verifica o status de cada turno
                    status_t1 = "Enviado" if (data_str_db, frente, '1') in relatorios_enviados else "Faltando"
                    status_t2 = "Enviado" if (data_str_db, frente, '2') in relatorios_enviados else "Faltando"

                    # Adiciona a linha na tabela apenas se houver alguma pendência
                    if status_t1 == "Faltando" or status_t2 == "Faltando":
                        row_position = self.table_checklist.rowCount()
                        self.table_checklist.insertRow(row_position)

                        self.table_checklist.setItem(row_position, 0, QTableWidgetItem(data_str_display))
                        self.table_checklist.setItem(row_position, 1, QTableWidgetItem(frente))

                        item_t1 = QTableWidgetItem(status_t1)
                        item_t1.setTextAlignment(Qt.AlignCenter)
                        item_t1.setForeground(QColor('green' if status_t1 == "Enviado" else 'red'))
                        self.table_checklist.setItem(row_position, 2, item_t1)

                        item_t2 = QTableWidgetItem(status_t2)
                        item_t2.setTextAlignment(Qt.AlignCenter)
                        item_t2.setForeground(QColor('green' if status_t2 == "Enviado" else 'red'))
                        self.table_checklist.setItem(row_position, 3, item_t2)

            self.table_checklist.resizeRowsToContents()

        except Exception as e:
            QMessageBox.critical(self, "Erro de Banco de Dados", f"Não foi possível verificar as frentes:\n{e}")
