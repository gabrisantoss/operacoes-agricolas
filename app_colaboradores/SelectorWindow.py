# SelectorWindow.py (Versão Final com 2 Módulos)

from PyQt5 import QtWidgets, QtCore, QtGui
from MainWindow import MainWindow  # Importa a janela de Colaboradores
from gerador_relatorio import ReportGenerator # <-- IMPORTA A NOVA JANELA

class SelectorWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Seleção de Módulos - Sistema Agrícola")
        self.setFixedSize(600, 400)

        self.opened_window = None
        self._setup_ui()
        self._load_theme()

    def _load_theme(self):
        settings = QtCore.QSettings("SuaEmpresa", "SistemaColaboradores")
        tema = settings.value("tema", "claro")
        if tema == "escuro":
            filepath = "assets/dark_theme.qss"
        else:
            filepath = "assets/style.qss"

        try:
            with open(filepath, "r", encoding='utf-8') as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Erro ao carregar tema na janela de seleção: {e}")

    def _setup_ui(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title_label = QtWidgets.QLabel("Selecione um Módulo")
        title_label.setObjectName("mainTitle")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title_label)

        # Botão para Gestão de Colaboradores
        btn_colaboradores = QtWidgets.QPushButton("📊 Gestão de Colaboradores")
        btn_colaboradores.setIconSize(QtCore.QSize(32, 32))
        btn_colaboradores.setMinimumHeight(60)
        btn_colaboradores.clicked.connect(self._abrir_gestao_colaboradores)
        layout.addWidget(btn_colaboradores)

        # <-- NOVO BOTÃO ADICIONADO AQUI
        btn_gerador = QtWidgets.QPushButton("📄 Gerador de Relatórios (Excel)")
        btn_gerador.setIconSize(QtCore.QSize(32, 32))
        btn_gerador.setMinimumHeight(60)
        btn_gerador.clicked.connect(self._abrir_gerador_relatorio)
        layout.addWidget(btn_gerador)

        layout.addStretch()

    def _abrir_gestao_colaboradores(self):
        """Abre a janela de gestão de colaboradores."""
        self.opened_window = MainWindow(parent_selector=self)
        self.opened_window.show()
        self.hide()

    # <-- NOVO MÉTODO ADICIONADO AQUI
    def _abrir_gerador_relatorio(self):
        """Abre a janela do gerador de relatórios."""
        self.opened_window = ReportGenerator(parent_selector=self)
        self.opened_window.show()
        self.hide()
