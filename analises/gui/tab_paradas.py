# gui/tab_paradas.py

from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QListWidget, QListWidgetItem,
    QDialog, QFormLayout
)
from datetime import datetime, timedelta
from core.operations_logic import salvar_parada_finalizada
from core.database_manager import DatabaseManager

class FinalizarParadaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Finalizar Parada em Andamento")
        self.layout = QFormLayout(self)

        self.data_retorno_input = QLineEdit()
        self.data_retorno_input.setPlaceholderText("dd/mm/aaaa (Opcional)")
        self.data_retorno_input.setInputMask("00/00/0000")
        self.layout.addRow("Data de Retorno (Opcional):", self.data_retorno_input)

        self.hora_retorno_input = QLineEdit()
        self.hora_retorno_input.setPlaceholderText("HH:MM")
        self.hora_retorno_input.setInputMask("00:00")
        self.layout.addRow("Hora de Retorno:", self.hora_retorno_input)

        btn_box = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        btn_box.addWidget(self.ok_button)
        btn_box.addWidget(self.cancel_button)
        self.layout.addRow(btn_box)

    def get_data(self):
        return self.data_retorno_input.text(), self.hora_retorno_input.text()


class ParadasAbertasTab(QWidget):
    parada_finalizada = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_paradas_em_andamento()

    def init_ui(self):
        layout = QVBoxLayout(self)

        title_label = QLabel("PARADAS EM ANDAMENTO")
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        info_label = QLabel(
            "Selecione uma parada na lista e clique em 'Finalizar Parada' "
            "para registrar o retorno da máquina."
        )
        layout.addWidget(info_label)

        self.list_paradas_abertas = QListWidget()
        layout.addWidget(self.list_paradas_abertas)

        btn_finalizar = QPushButton("Finalizar Parada Selecionada")
        btn_finalizar.setObjectName("PrimaryButton")
        btn_finalizar.clicked.connect(self.finalizar_parada)
        layout.addWidget(btn_finalizar, alignment=QtCore.Qt.AlignCenter)

    def load_paradas_em_andamento(self):
        self.list_paradas_abertas.clear()
        try:
            query = """
                SELECT id, Data, Turno, Frente, Frota, Motivo, Parou_Hora
                FROM RELATORIO_OPERACAO_DIARIA
                WHERE Status_Parada = 'Em Andamento'
                ORDER BY id
            """
            paradas = DatabaseManager.execute_select(query)
            for parada in paradas:
                texto = (
                    f"ID:{parada[0]} | Data Turno: {parada[1]} (T{parada[2]}) | "
                    f"Frente: {parada[3]} | Frota: {parada[4]} | Início: {parada[6]} | Motivo: {parada[5]}"
                )
                item = QListWidgetItem(texto)
                item.setData(QtCore.Qt.UserRole, parada)
                self.list_paradas_abertas.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao carregar paradas em andamento: {e}")

    def finalizar_parada(self):
        item = self.list_paradas_abertas.currentItem()
        if not item:
            QMessageBox.warning(self, "Aviso", "Selecione uma parada para finalizar.")
            return

        parada = item.data(QtCore.Qt.UserRole)
        id_parada, data_db, turno, frente, frota, motivo, hora_parada = parada

        data_inicio = datetime.strptime(data_db, "%d-%m-%Y").strftime("%d/%m/%Y")
        motivo_base = motivo.replace(" (INÍCIO)", "")

        dialog = FinalizarParadaDialog(self)
        if dialog.exec_():
            data_ret, hora_ret = dialog.get_data()
            if not hora_ret.strip().replace(":", "").replace("_", ""):
                QMessageBox.warning(self, "Erro", "A Hora de Retorno é obrigatória.")
                return

            # Calcula data de retorno quando não informado
            if not data_ret.strip().replace("/", "").replace("_", ""):
                try:
                    dt_inicio = datetime.strptime(f"{data_inicio} {hora_parada}", "%d/%m/%Y %H:%M")
                    dt_retorno = datetime.strptime(hora_ret, "%H:%M").replace(
                        year=dt_inicio.year, month=dt_inicio.month, day=dt_inicio.day
                    )
                    if turno == "2" and dt_inicio.hour < 18:
                        dt_inicio += timedelta(days=1)
                    if dt_retorno <= dt_inicio:
                        dt_retorno += timedelta(days=1)
                    data_ret = dt_retorno.strftime("%d/%m/%Y")
                except Exception:
                    QMessageBox.warning(
                        self, "Erro de Formato",
                        "Verifique se a Data de Início e as Horas estão em formatos válidos."
                    )
                    return

            # Busca dados extras
            try:
                query_extra = """
                    SELECT Fundo_Agricola, Chuva, Incendio
                    FROM RELATORIO_OPERACAO_DIARIA
                    WHERE id = ?
                """
                extras = DatabaseManager.execute_select(query_extra, (id_parada,))
                fundo, chuva, incidencia = extras[0] if extras else ("", "", "")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao buscar dados extras: {e}")
                return

            success, msg = salvar_parada_finalizada(
                data_inicio, frente, turno, frota, motivo_base,
                hora_parada, data_ret, hora_ret,
                fundo, chuva, incidencia,
                id_parada
            )
            if success:
                self.load_paradas_em_andamento()
                self.parada_finalizada.emit()
            else:
                QMessageBox.critical(self, "Erro", msg)
