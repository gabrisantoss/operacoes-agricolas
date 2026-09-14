# gui/tab_digitalizacao.py

import os
import re
from datetime import datetime

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QMessageBox, QDateEdit, QFileDialog, QHBoxLayout
)
from core.database_manager import DatabaseManager
from core.settings import get_setting

# Regex de extração (ajustadas para flexibilidade)
RE_DATE   = re.compile(r"(\d{2}[/.-]\d{2}[/.-]\d{4})")
RE_TIME   = re.compile(r"(\d{2}:\d{2})")
RE_FRENTE = re.compile(r"[Ff]rente[: ]*(\d+)")
RE_FROTA  = re.compile(r"[Ff]rota[: ]*([\w\s\d]+)")
RE_MOTIVO = re.compile(r"[Mm]otivo[: ]*(.+)", re.IGNORECASE | re.DOTALL)

class DigitalizacaoTab(QWidget):
    # Sinal que envia os dados extraídos para outra aba (ex: tab_cadastro)
    dados_extraidos = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_text = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("DIGITALIZAÇÃO DE RELATÓRIOS")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        btn_layout = QHBoxLayout()
        self.btn_select = QPushButton("Selecionar Arquivo (Imagem ou PDF)…")
        self.btn_select.setObjectName("SecondaryButton")
        self.btn_select.clicked.connect(self.select_file)
        btn_layout.addWidget(self.btn_select)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Grupo de campos extraídos
        form_group = QGroupBox("Campos Extraídos (Apenas para Conferência)")
        form_group.setMaximumWidth(800)
        form_layout = QFormLayout(form_group)

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("dd/mm/aaaa")
        self.date_edit.setReadOnly(True)
        form_layout.addRow("Data:", self.date_edit)

        self.line_parou  = QLineEdit()
        self.line_parou.setReadOnly(True)
        form_layout.addRow("Parou Hora:", self.line_parou)

        self.line_voltou = QLineEdit()
        self.line_voltou.setReadOnly(True)
        form_layout.addRow("Voltou Hora:", self.line_voltou)

        self.line_frente = QLineEdit()
        self.line_frente.setReadOnly(True)
        form_layout.addRow("Frente:", self.line_frente)

        self.line_frota  = QLineEdit()
        self.line_frota.setReadOnly(True)
        form_layout.addRow("Frota:", self.line_frota)

        self.text_motivo = QTextEdit()
        self.text_motivo.setFixedHeight(86)
        self.text_motivo.setReadOnly(True)
        form_layout.addRow("Motivo:", self.text_motivo)

        self.btn_confirm = QPushButton("Enviar para Aba de Cadastro")
        self.btn_confirm.setObjectName("PrimaryButton")
        self.btn_confirm.clicked.connect(self.enviar_para_cadastro)
        self.btn_confirm.setEnabled(False)
        form_layout.addRow(self.btn_confirm)

        wrapper = QHBoxLayout()
        wrapper.addStretch()
        wrapper.addWidget(form_group)
        wrapper.addStretch()
        layout.addLayout(wrapper)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher Documento", "",
            "Todos os Arquivos (*.png *.jpg *.jpeg *.bmp *.pdf)"
        )
        if not path:
            return

        if not OCR_AVAILABLE:
            QMessageBox.warning(
                self, "OCR não disponível",
                "O módulo 'pytesseract' não foi encontrado. Verifique a instalação."
            )
            return

        if path.lower().endswith(".pdf") and not PDF2IMAGE_AVAILABLE:
            QMessageBox.warning(
                self, "Conversão de PDF indisponível",
                "O módulo 'pdf2image' não foi encontrado. Instale a dependência para processar arquivos PDF."
            )
            return

        # Busca os caminhos do Tesseract e Poppler das configurações
        tesseract_path = get_setting('tesseract_path')
        poppler_path = get_setting('poppler_path')

        if tesseract_path and os.path.exists(tesseract_path):
             pytesseract.pytesseract.tesseract_cmd = tesseract_path
        else:
             QMessageBox.warning(self, "Erro OCR", "Caminho para o Tesseract não configurado ou inválido. Verifique a aba 'Configurações'.")
             return

        try:
            if path.lower().endswith(".pdf"):
                if not PDF2IMAGE_AVAILABLE:
                    QMessageBox.warning(self, "Leitor de PDF não disponível", "O módulo 'pdf2image' não foi encontrado.")
                    return
                if not poppler_path or not os.path.exists(poppler_path):
                     QMessageBox.warning(self, "Erro PDF", "Caminho para o Poppler (PDF) não configurado ou inválido. Verifique a aba 'Configurações'.")
                     return

                pages = convert_from_path(path, dpi=200, poppler_path=poppler_path)
                text = ""
                for page in pages:
                    text += pytesseract.image_to_string(page, lang="por") + "\n"
            else:
                img = Image.open(path)
                img.verify() # Verifica se é uma imagem válida
                img = Image.open(path) # Reabre a imagem
                text = pytesseract.image_to_string(img, lang="por")
        except Exception as e:
            QMessageBox.critical(
                self, "Erro ao Processar Arquivo",
                f"Ocorreu um erro durante o OCR:\n{type(e).__name__}: {e}"
            )
            return

        self.ocr_text = text
        self.populate_fields(text)


    def populate_fields(self, text):
        data_match = RE_DATE.search(text)
        times = RE_TIME.findall(text)
        frente_match = RE_FRENTE.search(text)
        frota_match = RE_FROTA.search(text)
        motivo_match = RE_MOTIVO.search(text)

        # Limpa e normaliza a data
        data_str = ""
        if data_match:
            data_str = data_match.group(1).replace("-", "/").replace(".", "/")
            try:
                # Tenta normalizar para DD/MM/YYYY
                data_obj = datetime.strptime(data_str, "%d/%m/%Y")
                data_str = data_obj.strftime("%d/%m/%Y")
            except ValueError:
                pass # Mantém a string original se não puder formatar

        self.date_edit.setText(data_str)
        self.line_parou.setText(times[0] if len(times)>0 else "")
        self.line_voltou.setText(times[1] if len(times)>1 else "")
        self.line_frente.setText(frente_match.group(1).strip() if frente_match else "")

        frota_str = ""
        if frota_match:
             # Limpa quebras de linha e espaços extras
             frota_str = " ".join(frota_match.group(1).split()).upper()
        self.line_frota.setText(frota_str)

        motivo_str = ""
        if motivo_match:
            # Limpa quebras de linha e espaços extras
            motivo_str = " ".join(motivo_match.group(1).split())
        self.text_motivo.setPlainText(motivo_str)

        self.btn_confirm.setEnabled(True)

    def enviar_para_cadastro(self):
        """
        Pega os dados dos campos (que o usuário pode ter corrigido)
        e os envia para a aba de cadastro.
        """
        dados = {
            'data': self.date_edit.text(),
            'frente': self.line_frente.text(),
            'frota': self.line_frota.text(),
            'parou_hora': self.line_parou.text(),
            'voltou_hora': self.line_voltou.text(),
            'motivo': self.text_motivo.toPlainText(),
        }

        # Salva o texto bruto e os dados corrigidos na tabela de treino
        self.salvar_para_treino(dados)

        # Emite o sinal para a main_window
        self.dados_extraidos.emit(dados)

        QMessageBox.information(self, "Enviado",
                                "Dados enviados para a 'Aba de Cadastro'.\n\nPor favor, confira os dados e clique em 'Salvar Ocorrência'.")
        self.btn_confirm.setEnabled(False)

    def salvar_para_treino(self, dados_corrigidos):
        """
        Salva o texto bruto do OCR e os dados (potencialmente corrigidos)
        na tabela de treinamento.
        """
        treino_query = """
            INSERT INTO OCR_TRAINING
            (raw_text, data_extraida, parou_hora, voltou_hora, frente, frota, motivo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        treino_params = (
            self.ocr_text,
            dados_corrigidos['data'],
            dados_corrigidos['parou_hora'],
            dados_corrigidos['voltou_hora'],
            dados_corrigidos['frente'],
            dados_corrigidos['frota'],
            dados_corrigidos['motivo']
        )
        try:
            DatabaseManager.execute_non_query(treino_query, treino_params)
        except Exception as e:
            # Falha no treino não bloqueia o fluxo principal
            print(f"Aviso: Não foi possível salvar dados de treino do OCR. Erro: {e}")
