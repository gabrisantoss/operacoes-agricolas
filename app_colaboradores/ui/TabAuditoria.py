# ui/TabAuditoria.py

from PyQt5 import QtWidgets, QtCore, QtGui
from db import DatabaseError
from funcoes_colaboradores import get_db_connection
from datetime import datetime
import logging
import json # Para carregar os detalhes JSON

class TabAuditoria(QtWidgets.QWidget):
    """
    Aba para visualizar os logs de auditoria do sistema.
    Permite filtrar por tipo de ação, entidade e data.
    """
    def __init__(self, main_window: QtWidgets.QMainWindow):
        super().__init__()
        self.main_window = main_window
        self._setup_ui()
        # Configura o timer para o campo de texto ID da Entidade
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.atualizar_tabela_auditoria)
        self.atualizar_tabela_auditoria() # Carrega os logs ao iniciar a aba

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        title_label = QtWidgets.QLabel("📋 Log de Auditoria")
        title_label.setObjectName("mainTitle")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # --- Frame de Filtros ---
        filter_group = QtWidgets.QGroupBox("Filtros de Log") # Renomeado para mais clareza
        filter_group.setObjectName("filtroFrame") # Reutiliza estilo de filtro
        filter_layout = QtWidgets.QGridLayout(filter_group)

        filter_layout.addWidget(QtWidgets.QLabel("Tipo de Ação:"), 0, 0)
        self.combo_tipo_acao = QtWidgets.QComboBox()
        self.combo_tipo_acao.addItems([
            "Todas",
            "ADICAO",
            "ATUALIZACAO",
            "EXCLUSAO",
            "ATUALIZACAO_CAMPO",
            "RESET",
            "IMPORTACAO",
            "SUBSTITUICAO",
            "ACOMPANHAMENTO_CNH",
            "RENOVACAO_CNH",
        ])
        self.combo_tipo_acao.currentIndexChanged.connect(self.atualizar_tabela_auditoria)
        filter_layout.addWidget(self.combo_tipo_acao, 0, 1)

        filter_layout.addWidget(QtWidgets.QLabel("Entidade Afetada:"), 0, 2)
        self.combo_entidade_afetada = QtWidgets.QComboBox()
        self.combo_entidade_afetada.addItems(["Todas", "COLABORADOR", "DOCUMENTO", "ATESTADO", "ADVERTENCIA", "ESCALA", "IDO_MES"]) # Adicionado IDO_MES
        self.combo_entidade_afetada.currentIndexChanged.connect(self.atualizar_tabela_auditoria)
        filter_layout.addWidget(self.combo_entidade_afetada, 0, 3)

        filter_layout.addWidget(QtWidgets.QLabel("ID da Entidade:"), 1, 0)
        self.entry_id_entidade = QtWidgets.QLineEdit()
        self.entry_id_entidade.setPlaceholderText("Código do Colaborador, ID do Documento, etc.")
        self.entry_id_entidade.textChanged.connect(self._iniciar_timer_busca)
        filter_layout.addWidget(self.entry_id_entidade, 1, 1, 1, 3)

        filter_layout.addWidget(QtWidgets.QLabel("Data Início:"), 2, 0)
        self.date_inicio = QtWidgets.QDateEdit(calendarPopup=True)
        self.date_inicio.setDisplayFormat("dd/MM/yyyy")
        self.date_inicio.setDate(QtCore.QDate(2000, 1, 1)) # Data padrão para "desde o início"
        self.date_inicio.dateChanged.connect(self.atualizar_tabela_auditoria)
        filter_layout.addWidget(self.date_inicio, 2, 1)

        filter_layout.addWidget(QtWidgets.QLabel("Data Fim:"), 2, 2)
        self.date_fim = QtWidgets.QDateEdit(calendarPopup=True)
        self.date_fim.setDisplayFormat("dd/MM/yyyy")
        self.date_fim.setDate(QtCore.QDate.currentDate()) # Data atual como padrão
        self.date_fim.dateChanged.connect(self.atualizar_tabela_auditoria)
        filter_layout.addWidget(self.date_fim, 2, 3)

        self.btn_limpar_filtros = QtWidgets.QPushButton("Limpar Filtros")
        self.btn_limpar_filtros.clicked.connect(self.limpar_filtros)
        filter_layout.addWidget(self.btn_limpar_filtros, 0, 4, 3, 1)


        main_layout.addWidget(filter_group) # Adiciona o grupo de filtros ao layout principal

        # --- Tabela de Logs de Auditoria ---
        self.table_auditoria = QtWidgets.QTableWidget()
        self.table_auditoria.setColumnCount(5) # Data/Hora, Ação, Entidade, ID, Detalhes
        self.table_auditoria.setHorizontalHeaderLabels(["Data/Hora", "Ação", "Entidade", "ID da Entidade", "Detalhes"])
        self.table_auditoria.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_auditoria.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table_auditoria.horizontalHeader().setStretchLastSection(True)
        self.table_auditoria.setSortingEnabled(True)
        self.table_auditoria.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch) # Coluna Detalhes estica

        main_layout.addWidget(self.table_auditoria)

        # Barra de rolagem para a tabela é automática se o layout principal for QVBoxLayout
        # e a tabela for o único widget que se expande.

    def _iniciar_timer_busca(self):
        self.search_timer.start(350)

    def limpar_filtros(self):
        self.combo_tipo_acao.setCurrentIndex(0)
        self.combo_entidade_afetada.setCurrentIndex(0)
        self.entry_id_entidade.clear()
        self.date_inicio.setDate(QtCore.QDate(2000, 1, 1))
        self.date_fim.setDate(QtCore.QDate.currentDate())
        self.atualizar_tabela_auditoria()

    def atualizar_tabela_auditoria(self):
        self.table_auditoria.setSortingEnabled(False)
        self.table_auditoria.setRowCount(0)

        tipo_acao_filtro = self.combo_tipo_acao.currentText()
        if tipo_acao_filtro == "Todas": tipo_acao_filtro = ""

        entidade_filtro = self.combo_entidade_afetada.currentText()
        if entidade_filtro == "Todas": entidade_filtro = ""

        id_entidade_filtro = self.entry_id_entidade.text().strip()

        data_inicio_filtro = self.date_inicio.date().toString("yyyy-MM-dd")
        # Se a data de início é a data padrão de "desde o início", não a filtra.
        # Caso contrário, adiciona 00:00:00 para pegar o início do dia.
        if self.date_inicio.date() == QtCore.QDate(2000, 1, 1):
            data_inicio_filtro = ""
        else:
            data_inicio_filtro += " 00:00:00"

        data_fim_filtro = self.date_fim.date().toString("yyyy-MM-dd")
        # Adiciona 23:59:59 para pegar o final do dia
        data_fim_filtro += " 23:59:59"
        # Não precisa verificar data_fim.date() == QtCore.QDate.currentDate()
        # Apenas garante que seja o final do dia selecionado, mesmo que seja hoje.


        logs = self._obter_logs_auditoria_do_db(
            tipo_acao=tipo_acao_filtro,
            entidade_afetada=entidade_filtro,
            id_entidade=id_entidade_filtro,
            data_inicio=data_inicio_filtro,
            data_fim=data_fim_filtro
        )

        self.table_auditoria.setRowCount(len(logs))
        for row_idx, log in enumerate(logs):
            self.table_auditoria.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(log.get('data_hora', '')))
            self.table_auditoria.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(log.get('tipo_acao', '')))
            self.table_auditoria.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(log.get('entidade_afetada', '')))
            self.table_auditoria.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(log.get('id_entidade', '')))

            detalhes_str = log.get('detalhes', '')
            if detalhes_str:
                try:
                    detalhes_obj = json.loads(detalhes_str)
                    detalhes_legivel = json.dumps(detalhes_obj, indent=2, ensure_ascii=False)
                    self.table_auditoria.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(detalhes_legivel))
                except json.JSONDecodeError:
                    self.table_auditoria.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(detalhes_str))
            else:
                self.table_auditoria.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(""))

        self.table_auditoria.resizeColumnsToContents()
        self.table_auditoria.setSortingEnabled(True)

    def _obter_logs_auditoria_do_db(self, tipo_acao: str = "", entidade_afetada: str = "",
                                    id_entidade: str = "", data_inicio: str = "", data_fim: str = "") -> list[dict]:
        try:
            with get_db_connection(dict_rows=True) as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM log_auditoria WHERE 1=1"
                params = []

                if tipo_acao:
                    query += " AND tipo_acao = ?"
                    params.append(tipo_acao)
                if entidade_afetada:
                    query += " AND entidade_afetada = ?"
                    params.append(entidade_afetada)
                if id_entidade:
                    query += " AND id_entidade LIKE ?"
                    params.append(f"%{id_entidade}%")
                if data_inicio:
                    query += " AND data_hora >= ?"
                    params.append(data_inicio) # Data já inclui hora no filtro

                if data_fim:
                    query += " AND data_hora <= ?"
                    params.append(data_fim) # Data já inclui hora no filtro

                query += " ORDER BY data_hora DESC"

                cursor.execute(query, params)
                logs = [dict(row) for row in cursor.fetchall()]
                return logs
        except DatabaseError as e:
            logging.error(f"Erro ao obter logs de auditoria: {e}")
            return []
        except Exception as e:
            logging.error(f"Erro inesperado ao obter logs de auditoria: {e}")
            return []
