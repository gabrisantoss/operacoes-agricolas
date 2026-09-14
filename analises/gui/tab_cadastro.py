# gui/tab_cadastro.py
import sqlite3
from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QMessageBox, QCompleter, QHBoxLayout,
    QComboBox, QCheckBox, QFrame, QApplication, QStyle
)
from core.database_manager import DatabaseManager
from core.operations_logic import (salvar_parada_em_andamento, salvar_registro_simples,
                                   verificar_duplicidade, calcular_parada_e_eficiencia,
                                   DUPLICATE_OPERATION_MESSAGE)
from core.validation import (
    ValidationError,
    build_finalized_occurrence_metrics,
    normalize_occurrence_payload,
)
from .custom_widgets import SmartLineEdit
from datetime import datetime
# IMPORTAR A NOVA FUNÇÃO DE query_logic
from core.query_logic import buscar_registro_por_id

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - SQLite-only environments
    psycopg = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

class CadastroTab(QWidget):
    registro_salvo = pyqtSignal()
    frota_modificada = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frota_tab = None
        self.editando_id = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title_layout = QHBoxLayout()
        title_icon = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
        title_icon.setPixmap(icon.pixmap(32, 32))

        title = QLabel("CADASTRO DE OCORRÊNCIA DE OPERAÇÃO")
        title.setObjectName("SectionTitle")

        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)

        form_columns_layout = QHBoxLayout()
        main_layout.addLayout(form_columns_layout)

        header_group = QGroupBox("Dados Gerais do Dia")
        header_group.setToolTip("Informações que geralmente se repetem durante o dia.")
        form_columns_layout.addWidget(header_group)
        header_layout = QFormLayout(header_group)
        header_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)

        self.date_edit = QLineEdit()
        self.date_edit.setInputMask("00/00/0000")
        self.date_edit.setText(QDate.currentDate().toString("dd/MM/yyyy"))
        header_layout.addRow("Data:", self.date_edit)

        self.combo_turno = QComboBox()
        self.combo_turno.addItems(["1", "2"])
        header_layout.addRow("Turno:", self.combo_turno)

        self.line_frente = SmartLineEdit()
        header_layout.addRow("Frente:", self.line_frente)
        self.line_frente.editingFinished.connect(self._padronizar_frente_input)

        self.line_fundo = SmartLineEdit()
        self.line_fundo.setPlaceholderText("Opcional")
        header_layout.addRow("Fundo Agrícola:", self.line_fundo)

        self.combo_chove = QComboBox()
        self.combo_chove.addItems(["NÃO", "SIM"])
        header_layout.addRow("Choveu:", self.combo_chove)

        self.combo_incendio = QComboBox()
        self.combo_incendio.addItems(["NÃO", "SIM"])
        header_layout.addRow("Incêndio:", self.combo_incendio)

        occ_group = QGroupBox("Detalhes da Ocorrência")
        form_columns_layout.addWidget(occ_group)
        occ_layout = QFormLayout(occ_group)
        occ_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)

        self.line_frota = SmartLineEdit()
        occ_layout.addRow("Frota:", self.line_frota)

        self.line_parou = QLineEdit()
        self.line_parou.setInputMask("00:00")
        occ_layout.addRow("Parou Hora:", self.line_parou)

        self.line_parou.editingFinished.connect(self._atualizar_turno_automaticamente)

        self.line_voltou = QLineEdit()
        self.line_voltou.setInputMask("00:00")
        occ_layout.addRow("Voltou Hora:", self.line_voltou)

        self.check_parada_andamento = QCheckBox("Marcar se a parada ainda está ocorrendo")
        self.check_parada_andamento.stateChanged.connect(self._on_parada_em_andamento_changed)
        occ_layout.addRow(self.check_parada_andamento)

        self.text_motivo = QTextEdit()
        self.text_motivo.setFixedHeight(96)
        occ_layout.addRow("Motivo da Ocorrência:", self.text_motivo)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)

        btn_layout = QHBoxLayout()
        main_layout.addLayout(btn_layout)
        btn_layout.addStretch()

        self.btn_clear = QPushButton(" Limpar Tudo")
        self.btn_clear.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogResetButton))
        self.btn_clear.setObjectName("SecondaryButton")
        self.btn_clear.clicked.connect(lambda: self.clear_fields(limpar_cabecalho=True))
        btn_layout.addWidget(self.btn_clear)

        self.btn_save = QPushButton(" Salvar Ocorrência")
        self.btn_save.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self.save_occurrence)
        btn_layout.addWidget(self.btn_save)

    def _padronizar_frente_input(self):
        """
        Remove o zero à esquerda de números de frente (ex: '01' vira '1').
        """
        texto_atual = self.line_frente.text().strip()
        try:
            frente_num = int(texto_atual)
            texto_padronizado = str(frente_num)
            self.line_frente.setText(texto_padronizado)
        except ValueError:
            pass

    def _atualizar_turno_automaticamente(self):
        """
        Define o turno automaticamente com base na regra global da operacao.
        Turno 1: 06:00 até 17:59
        Turno 2: 18:00 até 05:59 (do dia seguinte)
        """
        hora_str = self.line_parou.text().strip().replace("_", "")

        if not hora_str or hora_str == ':':
            return

        try:
            hora_obj = datetime.strptime(hora_str, "%H:%M").time()
            turno_calculado = ""

            hora_inicio_t1 = datetime.strptime("06:00", "%H:%M").time()
            hora_inicio_t2 = datetime.strptime("18:00", "%H:%M").time()

            # Se a hora da parada for entre 06:00 (incluso) e 18:00 (excluso)
            if hora_inicio_t1 <= hora_obj < hora_inicio_t2:
                turno_calculado = "1"
            else:
                # Todas as outras horas (18:00 até 05:59)
                turno_calculado = "2"

            if turno_calculado:
                self.combo_turno.setCurrentText(turno_calculado)

        except (ValueError, TypeError):
            # Se a hora for inválida (ex: 25:00), não faz nada
            pass

    def popular_dados_para_edicao(self, dados):
        self.clear_fields(limpar_cabecalho=True)
        self.editando_id = dados.get('id')
        self.date_edit.setText(dados.get('data', ''))
        self.combo_turno.setCurrentText(dados.get('turno', ''))
        self.line_frente.setText(dados.get('frente', ''))
        self.line_fundo.setText(dados.get('fundo_agricola', ''))
        self.combo_chove.setCurrentText(dados.get('chuva', 'NÃO'))
        self.combo_incendio.setCurrentText(dados.get('incendio', 'NÃO'))
        self.line_frota.setText(dados.get('frota', ''))
        self.line_parou.setText(dados.get('parou_hora', ''))
        self.line_voltou.setText(dados.get('voltou_hora', ''))
        self.text_motivo.setPlainText(dados.get('motivo', ''))
        self.check_parada_andamento.setEnabled(False)
        self.btn_save.setText(" Salvar Alterações")

    def popular_dados_do_ocr(self, dados_ocr: dict):
        """
        (NOVO SLOT) Preenche o formulário com dados vindos da aba de OCR.
        """
        self.clear_fields(limpar_cabecalho=False) # Limpa só a ocorrência

        data_str = dados_ocr.get('data', '')
        if data_str:
            try:
                # Tenta formatar a data, caso venha do OCR como YYYY-MM-DD
                data_obj = datetime.strptime(data_str, "%Y-%m-%d")
                self.date_edit.setText(data_obj.strftime("%d/%m/%Y"))
            except ValueError:
                self.date_edit.setText(data_str) # Assume DD/MM/YYYY

        self.line_frente.setText(dados_ocr.get('frente', ''))
        self.line_frota.setText(dados_ocr.get('frota', ''))
        self.line_parou.setText(dados_ocr.get('parou_hora', ''))
        self.line_voltou.setText(dados_ocr.get('voltou_hora', ''))
        self.text_motivo.setPlainText(dados_ocr.get('motivo', ''))

        # Atualiza o turno e foca na aba
        self._atualizar_turno_automaticamente()

        # Foca no campo de motivo para o usuário validar
        self.text_motivo.setFocus()

        # Traz a aba de cadastro para a frente
        # (O 'parent().parent()' pode variar, mas geralmente é o QTabWidget)
        try:
            self.parent().parent().setCurrentWidget(self)
        except Exception as e:
            print(f"Não foi possível focar na aba de cadastro: {e}")

    def _on_parada_em_andamento_changed(self, state):
        is_em_andamento = (state == Qt.Checked)
        self.line_voltou.setEnabled(not is_em_andamento)
        if is_em_andamento:
            self.line_voltou.clear()

    def clear_fields(self, limpar_cabecalho=False):
        self.editando_id = None
        self.line_frota.clear()
        self.line_parou.clear()
        self.line_voltou.clear()
        self.text_motivo.clear()
        self.check_parada_andamento.setChecked(False)
        self.check_parada_andamento.setEnabled(True)
        self.btn_save.setText(" Salvar Ocorrência")
        self.line_frota.setFocus()
        if limpar_cabecalho:
            self.date_edit.setText(QDate.currentDate().toString("dd/MM/yyyy"))
            self.combo_turno.setCurrentIndex(0)
            self.line_frente.clear()
            self.line_fundo.clear()
            self.combo_chove.setCurrentIndex(0)
            self.combo_incendio.setCurrentIndex(0)

    def setup_autocomplete(self):
        self.update_frota_completer()

    def set_frotas_source(self, frota_tab):
        self._frota_tab = frota_tab
        frota_tab.frota_modificada.connect(self.update_frota_completer)
        self.update_frota_completer()

    def update_frota_completer(self):
        if not self._frota_tab: return
        items = [f['frota'] for f in self._frota_tab.get_frota_list()]
        completer = QCompleter(items, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.line_frota.setCompleter(completer)

    def _collect_occurrence_form_data(self):
        return {
            "data": self.date_edit.text(),
            "turno": self.combo_turno.currentText(),
            "frente": self.line_frente.text(),
            "fundo": self.line_fundo.text(),
            "chove": self.combo_chove.currentText(),
            "incendio": self.combo_incendio.currentText(),
            "frota": self.line_frota.text(),
            "motivo": self.text_motivo.toPlainText(),
            "parou_hora": self.line_parou.text(),
            "voltou_hora": self.line_voltou.text(),
            "em_andamento": self.check_parada_andamento.isChecked(),
        }

    def _build_integrity_message(self, exc):
        if "RELATORIO_OPERACAO_DIARIA" in str(exc):
            return DUPLICATE_OPERATION_MESSAGE
        return "Não foi possível salvar a ocorrência porque os dados violam uma regra do banco."

    def save_occurrence(self):
        try:
            occurrence = normalize_occurrence_payload(self._collect_occurrence_form_data())
        except ValidationError as exc:
            QMessageBox.warning(self, "Validação", str(exc))
            return

        self.line_frente.setText(occurrence["frente"])
        self.line_frota.setText(occurrence["frota"])
        self.text_motivo.setPlainText(occurrence["motivo"])

        id_duplicado = verificar_duplicidade(
            occurrence["data_db"],
            occurrence["frente"],
            occurrence["turno"],
            occurrence["frota"],
            occurrence["parou_hora"],
            ignore_id=self.editando_id,
        )

        if id_duplicado:
            if self.editando_id:
                QMessageBox.warning(self, "Registro Duplicado", DUPLICATE_OPERATION_MESSAGE)
            else:
                self.mostrar_dialogo_duplicado(id_duplicado)
            return

        try:
            if self.editando_id:
                total_parado, eficiencia = build_finalized_occurrence_metrics(
                    occurrence["data_display"],
                    occurrence["parou_hora"],
                    occurrence["voltou_hora"],
                    calcular_parada_e_eficiencia,
                )
                query = """
                    UPDATE RELATORIO_OPERACAO_DIARIA
                    SET Data = ?, Turno = ?, Frente = ?, Fundo_Agricola = ?, Chuva = ?, Incendio = ?,
                        Frota = ?, Motivo = ?, Parou_Hora = ?, Voltou_Hora = ?, Total_Hora_Parado = ?,
                        Eficiencia = ?, Status_Parada = 'Finalizada'
                    WHERE id = ?
                """
                params = (
                    occurrence["data_db"],
                    occurrence["turno"],
                    occurrence["frente"],
                    occurrence["fundo"],
                    occurrence["chove"],
                    occurrence["incendio"],
                    occurrence["frota"],
                    occurrence["motivo"],
                    occurrence["parou_hora"],
                    occurrence["voltou_hora"],
                    total_parado,
                    eficiencia,
                    self.editando_id,
                )
                DatabaseManager.execute_non_query(query, params)
                QMessageBox.information(self, "Sucesso", "Registro atualizado com sucesso!")

            else:
                if occurrence["em_andamento"]:
                    success, message = salvar_parada_em_andamento(
                        occurrence["data_db"],
                        occurrence["frente"],
                        occurrence["turno"],
                        occurrence["frota"],
                        occurrence["motivo"],
                        occurrence["parou_hora"],
                        occurrence["fundo"],
                        occurrence["chove"],
                        occurrence["incendio"],
                    )
                elif not occurrence["parou_hora"]:
                    success, message = salvar_registro_simples(
                        occurrence["data_db"],
                        occurrence["frente"],
                        occurrence["turno"],
                        occurrence["frota"],
                        occurrence["motivo"],
                        occurrence["fundo"],
                        occurrence["chove"],
                        occurrence["incendio"],
                    )
                else:
                    total_parado, eficiencia = build_finalized_occurrence_metrics(
                        occurrence["data_display"],
                        occurrence["parou_hora"],
                        occurrence["voltou_hora"],
                        calcular_parada_e_eficiencia,
                    )

                    query = "INSERT INTO RELATORIO_OPERACAO_DIARIA (Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora, Total_Hora_Parado, Eficiencia, Fundo_Agricola, Chuva, Incendio, Status_Parada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Finalizada')"
                    params = (
                        occurrence["data_db"],
                        occurrence["frente"],
                        occurrence["turno"],
                        occurrence["frota"],
                        occurrence["motivo"],
                        occurrence["parou_hora"],
                        occurrence["voltou_hora"],
                        total_parado,
                        eficiencia,
                        occurrence["fundo"],
                        occurrence["chove"],
                        occurrence["incendio"],
                    )
                    DatabaseManager.execute_non_query(query, params)
                    success = True
                    message = "Ocorrência salva com sucesso!"

                if success:
                    QMessageBox.information(self, "Sucesso", message)
                else:
                    QMessageBox.critical(self, "Erro", message)

            self.registro_salvo.emit()
            self.frota_modificada.emit()
            self.clear_fields(limpar_cabecalho=False)

        except INTEGRITY_ERRORS as exc:
            QMessageBox.critical(self, "Erro de Integridade", self._build_integrity_message(exc))
        except Exception as e:
            print(f"Erro inesperado ao salvar ocorrência: {e}")
            QMessageBox.critical(
                self,
                "Erro ao Salvar",
                "Não foi possível concluir o salvamento da ocorrência. Revise os dados e tente novamente.",
            )

    def mostrar_dialogo_duplicado(self, id_duplicado):
        """
        Mostra um pop-up customizado quando um duplicado é encontrado.
        Oferece opções de Editar, Excluir ou Cancelar.
        """
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Warning)
        msgBox.setWindowTitle("Registro Duplicado")
        msgBox.setText("Uma ocorrência idêntica já existe no banco de dados.")
        msgBox.setInformativeText("O que você gostaria de fazer com o registro existente?")

        btn_editar = msgBox.addButton("Editar Existente", QMessageBox.ActionRole)
        btn_excluir = msgBox.addButton("Excluir Existente", QMessageBox.DestructiveRole)
        btn_cancelar = msgBox.addButton("Cancelar", QMessageBox.RejectRole)

        msgBox.exec_()

        clicked_button = msgBox.clickedButton()

        if clicked_button == btn_editar:
            dados = buscar_registro_por_id(id_duplicado)
            if dados:
                self.popular_dados_para_edicao(dados)
            else:
                QMessageBox.critical(self, "Erro", "Não foi possível encontrar os dados do registro para edição.")

        elif clicked_button == btn_excluir:
            confirm = QMessageBox.question(self, "Confirmar Exclusão",
                                           "Tem certeza que deseja excluir o registro existente?",
                                           QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirm == QMessageBox.Yes:
                try:
                    DatabaseManager.execute_non_query("DELETE FROM RELATORIO_OPERACAO_DIARIA WHERE id=?", (id_duplicado,))
                    self.registro_salvo.emit()
                    QMessageBox.information(self, "Sucesso", "O registro duplicado foi excluído.")
                except Exception as e:
                    QMessageBox.critical(self, "Erro", f"Não foi possível excluir o registro: {e}")

        elif clicked_button == btn_cancelar:
            pass
