# gui/main_window.py

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QFrame,
    QTableView,
    QTableWidget,
)
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt, QSize, pyqtSignal

# Importa todas as suas abas
from .dashboard_tab import DashboardTab
from .tab_cadastro import CadastroTab
from .tab_dados import DadosTab
# from .tab_paradas import ParadasAbertasTab # (Seu arquivo não foi fornecido, mas mantenha-o se existir)
from .tab_gerar_relatorio import GerarRelatorioTab
from .tab_frotas import FrotasTab
from .tab_colheita import ColheitaTab
from .tab_checklist import ChecklistTab
from .tab_digitalizacao import DigitalizacaoTab
from .config_app import ConfigApp

# Classe 'ParadasAbertasTab' de fallback caso o arquivo não exista no seu projeto
# Se você tem o arquivo, apenas delete esta classe.
try:
    from .tab_paradas import ParadasAbertasTab
except ImportError:
    class ParadasAbertasTab(QWidget):
        parada_finalizada = pyqtSignal()
        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("WIDGET PARADAS EM ANDAMENTO (PLACEHOLDER)"))
        def load_paradas_em_andamento(self):
            pass

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("AppWindow")
        self.setWindowTitle("Operacoes Agricolas | Análises Operacionais")
        self.resize(1240, 760)
        self.apply_agricola_theme()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabWidget")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setIconSize(QSize(0, 0))

        self.layout_principal = QVBoxLayout(self)
        self.layout_principal.setContentsMargins(10, 10, 10, 10)
        self.layout_principal.setSpacing(8)
        self.layout_principal.addWidget(self._build_header())
        self.layout_principal.addWidget(self.tabs, 1)
        self.footer_credit = QLabel("Desenvolvido por Gabriel Barbosa dos Santos")
        self.footer_credit.setObjectName("AppFooterCredit")
        self.footer_credit.setAlignment(Qt.AlignCenter)
        self.layout_principal.addWidget(self.footer_credit)

        # Instancia cada aba
        self.tab_dashboard_widget     = DashboardTab()
        self.tab_cadastro_widget      = CadastroTab()
        self.tab_paradas_widget       = ParadasAbertasTab()
        self.tab_dados_widget         = DadosTab()
        self.tab_gerar_widget         = GerarRelatorioTab()
        self.tab_frotas_widget        = FrotasTab()
        self.tab_colheita_widget      = ColheitaTab()
        self.tab_checklist_widget     = ChecklistTab()
        self.tab_digitalizacao_widget = DigitalizacaoTab()
        self.tab_config_widget        = ConfigApp()

        # Adiciona as abas na ordem desejada
        self.tabs.addTab(self.tab_dashboard_widget,     "Dashboard")
        self.tabs.addTab(self.tab_cadastro_widget,      "Cadastro")
        self.tabs.addTab(self.tab_paradas_widget,       "Paradas")
        self.tabs.addTab(self.tab_dados_widget,         "Dados")
        self.tabs.addTab(self.tab_gerar_widget,         "Relatórios")
        self.tabs.addTab(self.tab_frotas_widget,        "Frotas")
        self.tabs.addTab(self.tab_colheita_widget,      "Colheita")
        self.tabs.addTab(self.tab_checklist_widget,     "Checklist")
        self.tabs.addTab(self.tab_digitalizacao_widget, "Digitalização")
        self.tabs.addTab(self.tab_config_widget,        "Configurações")

        self.connect_signals()
        self._apply_compact_layouts()

        # Carrega dados iniciais
        self.tab_dados_widget.load_data()
        self.tab_paradas_widget.load_paradas_em_andamento()
        self.tab_frotas_widget.load_data_frota()
        self.tab_colheita_widget.load_data_colheita_mecanizada()
        self.tab_dashboard_widget.load_dashboard_data(show_empty_message=False)

        self.tab_cadastro_widget.set_frotas_source(self.tab_frotas_widget)
        self.tabs.setCurrentIndex(0)

    def _build_header(self):
        header_frame = QFrame()
        header_frame.setObjectName("AppChrome")

        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel("Operacoes Agricolas | Análises Operacionais")
        title_label.setObjectName("AppTitle")
        subtitle_label = QLabel(
            "Apontamentos, paradas, frotas, colheita e relatórios em uma interface compacta."
        )
        subtitle_label.setObjectName("AppSubtitle")

        text_layout.addWidget(title_label)
        text_layout.addWidget(subtitle_label)

        badge_label = QLabel("LOCAL")
        badge_label.setObjectName("AppBadge")
        badge_label.setAlignment(Qt.AlignCenter)

        header_layout.addLayout(text_layout, 1)
        header_layout.addWidget(badge_label, 0, Qt.AlignTop | Qt.AlignRight)
        return header_frame

    def connect_signals(self):
        # Sinais da Aba de Cadastro
        self.tab_cadastro_widget.registro_salvo.connect(self.tab_dados_widget.load_data)
        self.tab_cadastro_widget.registro_salvo.connect(self.tab_paradas_widget.load_paradas_em_andamento)
        self.tab_cadastro_widget.registro_salvo.connect(self.tab_checklist_widget.verificar_frentes_enviadas)
        self.tab_cadastro_widget.registro_salvo.connect(lambda: self.tab_dashboard_widget.load_dashboard_data(show_empty_message=False))
        self.tab_cadastro_widget.frota_modificada.connect(self.tab_frotas_widget.load_data_frota)

        # Sinais da Aba de Banco de Dados
        self.tab_dados_widget.dados_alterados.connect(self.tab_paradas_widget.load_paradas_em_andamento)
        self.tab_dados_widget.dados_alterados.connect(self.tab_cadastro_widget.setup_autocomplete)
        self.tab_dados_widget.dados_alterados.connect(lambda: self.tab_dashboard_widget.load_dashboard_data(show_empty_message=False))
        self.tab_dados_widget.editar_registro.connect(self.handle_editar_registro)

        # Sinais da Aba de Paradas
        self.tab_paradas_widget.parada_finalizada.connect(self.tab_dados_widget.load_data)
        self.tab_paradas_widget.parada_finalizada.connect(lambda: self.tab_dashboard_widget.load_dashboard_data(show_empty_message=False))

        # Sinais da Aba de Frotas
        self.tab_frotas_widget.frota_modificada.connect(self.tab_cadastro_widget.update_frota_completer)
        self.tab_frotas_widget.frota_modificada.connect(self.tab_checklist_widget.verificar_frentes_enviadas)

        # Sinais da Aba de Colheita
        self.tab_colheita_widget.registro_salvo.connect(self.tab_colheita_widget.load_data_colheita_mecanizada)
        self.tab_colheita_widget.registro_salvo.connect(lambda: self.tab_dashboard_widget.load_dashboard_data(show_empty_message=False))

        # --- NOVA CONEXÃO (OCR -> CADASTRO) ---
        # Conecta o sinal 'dados_extraidos' da aba de digitalização
        # ao slot 'popular_dados_do_ocr' da aba de cadastro.
        self.tab_digitalizacao_widget.dados_extraidos.connect(self.tab_cadastro_widget.popular_dados_do_ocr)
        # --- FIM DA NOVA CONEXÃO ---


    def handle_editar_registro(self, dados_do_registro):
        # Esta função recebe os dados da tab_dados e os envia para a tab_cadastro
        self.tab_cadastro_widget.popular_dados_para_edicao(dados_do_registro)
        # Muda o foco da interface para a aba de cadastro
        self.tabs.setCurrentWidget(self.tab_cadastro_widget)

    def _apply_compact_layouts(self):
        for widget in [self, *self.findChildren(QWidget)]:
            layout = widget.layout()
            if layout:
                layout.setContentsMargins(8, 8, 8, 8)
                layout.setSpacing(6)

        self.layout_principal.setContentsMargins(10, 10, 10, 10)
        self.layout_principal.setSpacing(8)

        for table in self.findChildren(QTableView):
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setWordWrap(False)
            table.setShowGrid(True)

            horizontal_header = table.horizontalHeader()
            if horizontal_header:
                horizontal_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                horizontal_header.setMinimumSectionSize(52)
                horizontal_header.setSectionResizeMode(QHeaderView.Interactive)

            vertical_header = table.verticalHeader()
            if vertical_header:
                vertical_header.setVisible(False)
                vertical_header.setDefaultSectionSize(24)

        for table in self.findChildren(QTableWidget):
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setWordWrap(False)

    def apply_agricola_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#eef2ee"))
        palette.setColor(QPalette.WindowText, QColor("#17231e"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.AlternateBase, QColor("#f4f7f4"))
        palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
        palette.setColor(QPalette.ToolTipText, QColor("#17231e"))
        palette.setColor(QPalette.Text, QColor("#17231e"))
        palette.setColor(QPalette.Button, QColor("#f7faf7"))
        palette.setColor(QPalette.ButtonText, QColor("#17231e"))
        palette.setColor(QPalette.Highlight, QColor("#26734d"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        QApplication.setPalette(palette)

        self.setStyleSheet("""
            QWidget {
                background-color: #eef2ee;
                color: #17231e;
                font-family: 'Segoe UI', 'Arial';
                font-size: 12px;
                selection-background-color: #26734d;
                selection-color: #ffffff;
            }
            QWidget#AppWindow {
                background-color: #eef2ee;
            }
            QFrame#AppChrome {
                background: #ffffff;
                border: 1px solid #d7e1d8;
                border-radius: 8px;
            }
            QLabel {
                background: transparent;
            }
            QLabel#AppTitle {
                color: #17231e;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#AppSubtitle {
                color: #647164;
                font-size: 12px;
            }
            QLabel#AppFooterCredit {
                color: #78867c;
                font-size: 11px;
                font-weight: 600;
                padding: 0 0 2px 0;
            }
            QLabel#AppBadge {
                background-color: #e7f3ea;
                color: #1f6b45;
                border: 1px solid #bdddc7;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 700;
            }
            QLabel#SectionTitle {
                color: #17231e;
                font-size: 16px;
                font-weight: 700;
                padding: 0 0 4px 0;
            }
            QLabel#MetricSectionTitle {
                color: #1f6b45;
                font-size: 12px;
                font-weight: 700;
                padding: 0 0 2px 0;
            }
            QFrame[frameShape="4"], QFrame[frameShape="5"] {
                color: #d7e1d8;
                background-color: #d7e1d8;
                max-height: 1px;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #d7e1d8;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 10px 8px 10px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 1px 6px;
                background-color: #ffffff;
                color: #31423a;
                border: none;
            }
            QLineEdit, QTextEdit, QComboBox, QDateEdit, QListWidget,
            QTableView, QTableWidget {
                background-color: #ffffff;
                color: #17231e;
                border: 1px solid #cfdacf;
                border-radius: 5px;
                padding: 4px 7px;
                min-height: 24px;
            }
            QTextEdit {
                padding: 6px;
            }
            QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover,
            QListWidget:hover, QTableView:hover, QTableWidget:hover {
                border-color: #95aa98;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus,
            QListWidget:focus, QTableView:focus, QTableWidget:focus {
                border: 1px solid #26734d;
            }
            QComboBox::drop-down, QDateEdit::drop-down {
                width: 22px;
                background-color: #f4f7f4;
                border-left: 1px solid #d7e1d8;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #17231e;
                border: 1px solid #cfdacf;
                selection-background-color: #dff0e5;
                selection-color: #17231e;
                outline: 0;
            }
            QAbstractItemView {
                background-color: #ffffff;
                color: #17231e;
                border: 1px solid #cfdacf;
                selection-background-color: #dff0e5;
                selection-color: #17231e;
                outline: 0;
            }
            QTableView, QTableWidget {
                gridline-color: #e4ebe4;
                alternate-background-color: #f7faf7;
                border-radius: 5px;
            }
            QTableView::item, QTableWidget::item {
                padding: 3px 5px;
            }
            QTableView::item:selected, QTableWidget::item:selected,
            QListWidget::item:selected {
                background-color: #dff0e5;
                color: #17231e;
                border-radius: 3px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #edf2ed;
            }
            QHeaderView::section, QTableCornerButton::section {
                background-color: #edf3ed;
                color: #31423a;
                padding: 5px 6px;
                border: none;
                border-bottom: 1px solid #d7e1d8;
                font-weight: 700;
            }
            QPushButton {
                min-height: 26px;
                background-color: #ffffff;
                color: #17231e;
                border: 1px solid #cbd7cc;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #f3f7f3;
                border-color: #95aa98;
            }
            QPushButton:pressed {
                background-color: #e8efe8;
            }
            QPushButton:disabled {
                background-color: #edf1ed;
                color: #8a958c;
                border-color: #d8e1d8;
            }
            QPushButton#PrimaryButton {
                background-color: #26734d;
                color: #ffffff;
                border-color: #26734d;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #2e8158;
            }
            QPushButton#SecondaryButton {
                background-color: #f7faf7;
                color: #23322c;
                border-color: #cbd7cc;
            }
            QPushButton#ExportButton {
                background-color: #d99a2b;
                color: #1e1609;
                border-color: #d99a2b;
            }
            QPushButton#EditButton {
                background-color: #e7f3ea;
                color: #1f6b45;
                border-color: #b7d9c1;
            }
            QPushButton#DeleteButton {
                background-color: #fff1f0;
                color: #a43c32;
                border-color: #e6b6b1;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid #9bab9d;
                background-color: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #26734d;
                border-color: #26734d;
            }
            QTabWidget::pane {
                border: 1px solid #d7e1d8;
                border-radius: 6px;
                background-color: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #f6f9f6;
                color: #4e5e55;
                padding: 7px 11px;
                margin-right: 3px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                border: 1px solid #d7e1d8;
                border-bottom: none;
                min-width: 0;
            }
            QTabBar::tab:hover {
                background: #eef4ee;
                color: #17231e;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1f6b45;
                font-weight: 700;
            }
            QScrollBar:vertical {
                background: #f1f5f1;
                width: 9px;
                margin: 0;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #a9b9ab;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar:horizontal {
                background: #f1f5f1;
                height: 9px;
                margin: 0;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #a9b9ab;
                min-width: 24px;
                border-radius: 4px;
            }
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page {
                border: none;
                background: none;
            }
            QCalendarWidget QWidget {
                background-color: #ffffff;
                alternate-background-color: #f7faf7;
            }
            QCalendarWidget QToolButton {
                background-color: #f4f7f4;
                color: #17231e;
                border-radius: 5px;
                padding: 4px;
                margin: 2px;
            }
        """)
