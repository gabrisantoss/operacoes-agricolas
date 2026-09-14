# gui/tab_frotas.py
import sqlite3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                           QPushButton, QHeaderView, QMessageBox, QHBoxLayout,
                           QLineEdit, QComboBox, QLabel, QGroupBox, QFormLayout)
from PyQt5.QtCore import pyqtSignal, Qt
from core.database_manager import DatabaseManager
from core.config import DatabaseConfig
from core.sql_compat import numeric_text_order_sql

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - SQLite-only environments
    psycopg = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

class FrotasTab(QWidget):
    frota_modificada = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.todas_as_frotas = []
        self.init_ui()
        self.load_data_frota()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        management_group = QGroupBox("Adicionar Nova Frota")
        management_layout = QFormLayout(management_group)

        self.input_tipo = QComboBox()
        self.input_tipo.addItems([
            "COLHEDORA", "TRANSBORDO", "GUINCHO",
            "CAMINHAO D'AGUA", "CAMINHAO CORINGA"
        ])
        self.input_numero = QLineEdit(placeholderText="Ex: 974")
        self.input_frente = QLineEdit(placeholderText="Ex: 1 (ou 'SEM FRENTE')")

        btn_adicionar = QPushButton("Adicionar Frota")
        btn_adicionar.setObjectName("PrimaryButton")
        btn_adicionar.clicked.connect(self.adicionar_frota)

        management_layout.addRow(QLabel("Tipo:"), self.input_tipo)
        management_layout.addRow(QLabel("Número:"), self.input_numero)
        management_layout.addRow(QLabel("Frente:"), self.input_frente)
        management_layout.addRow(btn_adicionar)
        main_layout.addWidget(management_group)

        display_group = QGroupBox("Lista de Frotas Cadastradas")
        display_layout = QVBoxLayout(display_group)

        filter_layout = QHBoxLayout()

        self.filtro_tipo = QComboBox()
        self.filtro_tipo.addItems([
            "TODOS OS TIPOS", "COLHEDORA", "TRANSBORDO", "GUINCHO",
            "CAMINHAO D'AGUA", "CAMINHAO CORINGA"
        ])
        self.filtro_tipo.currentTextChanged.connect(self.filtrar_tabela)
        filter_layout.addWidget(QLabel("Filtrar por Tipo:"))
        filter_layout.addWidget(self.filtro_tipo)
        filter_layout.addStretch()

        self.search_bar = QLineEdit(placeholderText="Pesquisar por número ou frente...")
        self.search_bar.textChanged.connect(self.filtrar_tabela)
        filter_layout.addWidget(QLabel("Pesquisa Rápida:"))
        filter_layout.addWidget(self.search_bar)

        display_layout.addLayout(filter_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Frente", "Frota"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        display_layout.addWidget(self.table)

        table_actions_layout = QHBoxLayout()

        btn_remover = QPushButton("Remover Frota Selecionada")
        btn_remover.setObjectName("SecondaryButton")
        btn_remover.clicked.connect(self.remover_frota)
        table_actions_layout.addWidget(btn_remover)

        table_actions_layout.addStretch()

        btn_zerar_tudo = QPushButton("Zerar Todas as Frotas")
        btn_zerar_tudo.setObjectName("DeleteButton")
        btn_zerar_tudo.clicked.connect(self.zerar_todas_as_frotas)
        table_actions_layout.addWidget(btn_zerar_tudo)

        display_layout.addLayout(table_actions_layout)

        main_layout.addWidget(display_group)

    def zerar_todas_as_frotas(self):
        reply = QMessageBox.question(self, 'Confirmação Crítica', "Você tem certeza que deseja apagar TODAS as frotas cadastradas?\n\nEsta ação não pode ser desfeita e a lista terá que ser inserida novamente.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                DatabaseManager.execute_non_query("DELETE FROM FROTAS_POR_FRENTE")
                QMessageBox.information(self, "Sucesso", "Todas as frotas foram removidas do banco de dados.")
                self.load_data_frota()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível zerar a lista de frotas: {e}")

    def load_data_frota(self):
        try:
            front_order = numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE)
            rows = DatabaseManager.execute_select(
                f"SELECT Frente, Frota FROM FROTAS_POR_FRENTE ORDER BY {front_order}, Frota"
            )
            self.todas_as_frotas = [{"frente": r[0], "frota": r[1]} for r in rows]
            self.filtrar_tabela()
            self.frota_modificada.emit()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao carregar dados da frota: {e}")

    def populate_table(self, frotas_para_exibir):
        self.table.setRowCount(0)
        self.table.setRowCount(len(frotas_para_exibir))
        for i, f in enumerate(frotas_para_exibir):
            self.table.setItem(i, 0, QTableWidgetItem(f["frente"]))
            self.table.setItem(i, 1, QTableWidgetItem(f["frota"]))

    def filtrar_tabela(self):
        tipo_selecionado = self.filtro_tipo.currentText()
        texto_pesquisa = self.search_bar.text().lower()
        frotas_filtradas = self.todas_as_frotas
        if tipo_selecionado != "TODOS OS TIPOS":
            frotas_filtradas = [f for f in frotas_filtradas if f['frota'].startswith(tipo_selecionado)]
        if texto_pesquisa:
            frotas_filtradas = [f for f in frotas_filtradas if texto_pesquisa in f['frente'].lower() or texto_pesquisa in f['frota'].lower()]
        self.populate_table(frotas_filtradas)

    def adicionar_frota(self):
        tipo = self.input_tipo.currentText()
        numero = self.input_numero.text().strip()
        frente = self.input_frente.text().strip()
        if not all([numero, frente]):
            QMessageBox.warning(self, "Atenção", "Os campos 'Número' e 'Frente' são obrigatórios.")
            return
        nome_frota = f"{tipo} {numero}"
        try:
            query = "INSERT INTO FROTAS_POR_FRENTE (Frente, Frota) VALUES (?, ?)"
            DatabaseManager.execute_non_query(query, (frente, nome_frota))
            QMessageBox.information(self, "Sucesso", f"Frota '{nome_frota}' adicionada à frente '{frente}'.")
            self.load_data_frota()
            self.input_numero.clear()
            self.input_frente.clear()
        except INTEGRITY_ERRORS:
             QMessageBox.warning(self, "Erro", f"A frota '{nome_frota}' na frente '{frente}' já está cadastrada.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Não foi possível adicionar a frota: {e}")

    def remover_frota(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Atenção", "Selecione uma frota na tabela para remover.")
            return
        current_row = selected_items[0].row()
        frente = self.table.item(current_row, 0).text()
        frota = self.table.item(current_row, 1).text()
        reply = QMessageBox.question(self, 'Confirmação', f"Tem certeza que deseja remover a frota '{frota}' da frente '{frente}'?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                query = "DELETE FROM FROTAS_POR_FRENTE WHERE Frente = ? AND Frota = ?"
                DatabaseManager.execute_non_query(query, (frente, frota))
                self.load_data_frota()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível remover a frota: {e}")

    def get_frota_list(self):
        return self.todas_as_frotas
