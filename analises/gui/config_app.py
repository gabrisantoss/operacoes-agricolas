import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QPushButton, QMessageBox, QGroupBox,
                           QFormLayout, QFileDialog)
from PyQt5.QtCore import Qt
from core.settings import save_setting, get_setting

class ConfigApp(QWidget):

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        """Inicializa a interface do usuário para a aba de configurações."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel("CONFIGURAÇÕES DO SISTEMA")
        title_label.setObjectName("SectionTitle")
        main_layout.addWidget(title_label)

        # Bloco de Configurações Gerais
        general_settings_group = QGroupBox("Configurações Gerais")
        general_form_layout = QFormLayout(general_settings_group)

        self.input_tempo_operacao = QLineEdit()
        self.input_tempo_operacao.setPlaceholderText("Ex: 600 para 10 horas")
        self.input_tempo_operacao.setToolTip(
            "Defina o tempo total de operação em minutos para um turno, usado no cálculo de eficiência."
        )
        general_form_layout.addRow("Tempo de Operação por Turno (min):", self.input_tempo_operacao)

        self.input_report_path = QLineEdit()
        self.input_report_path.setPlaceholderText("Selecione a pasta onde os relatórios PDF serão salvos")
        self.input_report_path.setToolTip("Onde os relatórios PDF serão salvos por padrão.")
        general_form_layout.addRow("Pasta Padrão para Relatórios:", self._build_path_selector(
            self.input_report_path,
            self.select_report_path,
            "Selecionar Pasta",
        ))

        ocr_settings_group = QGroupBox("Configurações de OCR")
        ocr_form_layout = QFormLayout(ocr_settings_group)

        self.input_tesseract_path = QLineEdit()
        self.input_tesseract_path.setPlaceholderText("Ex: /usr/bin/tesseract ou C:/Program Files/Tesseract-OCR/tesseract.exe")
        self.input_tesseract_path.setToolTip("Executável do Tesseract usado para ler imagens e documentos.")
        ocr_form_layout.addRow("Executável do Tesseract:", self._build_path_selector(
            self.input_tesseract_path,
            self.select_tesseract_path,
            "Selecionar Arquivo",
        ))

        self.input_poppler_path = QLineEdit()
        self.input_poppler_path.setPlaceholderText("Ex: /usr/bin ou C:/poppler/Library/bin")
        self.input_poppler_path.setToolTip("Pasta contendo os binários do Poppler para conversão de PDF.")
        ocr_form_layout.addRow("Pasta do Poppler (PDF):", self._build_path_selector(
            self.input_poppler_path,
            self.select_poppler_path,
            "Selecionar Pasta",
        ))

        main_layout.addWidget(general_settings_group)
        main_layout.addWidget(ocr_settings_group)

        # Botão Salvar Configurações
        btn_save_settings = QPushButton("Salvar Todas as Configurações")
        btn_save_settings.setObjectName("PrimaryButton")
        btn_save_settings.clicked.connect(self.save_settings)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(btn_save_settings)
        main_layout.addLayout(button_layout)

        main_layout.addStretch()

    def load_settings(self):
        """Carrega as configurações salvas para a interface."""
        self.input_tempo_operacao.setText(get_setting('tempo_operacao_minutos', '600'))
        self.input_report_path.setText(get_setting('report_default_path', ''))
        self.input_tesseract_path.setText(get_setting('tesseract_path', ''))
        self.input_poppler_path.setText(get_setting('poppler_path', ''))

    def save_settings(self):
        """Salva as configurações da interface no banco de dados."""
        save_setting('tempo_operacao_minutos', self.input_tempo_operacao.text())
        save_setting('report_default_path', self.input_report_path.text())
        save_setting('tesseract_path', self.input_tesseract_path.text())
        save_setting('poppler_path', self.input_poppler_path.text())
        QMessageBox.information(self, "Configurações", "Configurações salvas com sucesso!")

    def _build_path_selector(self, line_edit, callback, button_label):
        """Monta uma linha com campo de caminho e botão de seleção."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)

        button = QPushButton(button_label)
        button.setObjectName("SecondaryButton")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return container

    def select_report_path(self):
        current_path = self.input_report_path.text().strip() or "."
        selected_dir = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Relatórios", current_path)
        if selected_dir:
            self.input_report_path.setText(selected_dir)

    def select_tesseract_path(self):
        current_path = self.input_tesseract_path.text().strip() or "."
        file_path, _ = QFileDialog.getOpenFileName(self, "Selecionar Executável do Tesseract", current_path)
        if file_path:
            self.input_tesseract_path.setText(file_path)

    def select_poppler_path(self):
        current_path = self.input_poppler_path.text().strip() or "."
        selected_dir = QFileDialog.getExistingDirectory(self, "Selecionar Pasta do Poppler", current_path)
        if selected_dir:
            self.input_poppler_path.setText(selected_dir)
