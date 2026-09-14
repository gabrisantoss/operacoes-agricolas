# MainWindow.py (Versão Final - Todas as Funcionalidades Ativas)

import logging

from PyQt5 import QtWidgets, QtCore

# Importamos TODAS as abas
from ui.TabCadastro import TabCadastro
from ui.TabCNH import TabCNH
from ui.TabConsulta import TabConsulta
from ui.TabEscala import TabEscala
from ui.TabRelatorios import TabRelatorios
from ui.TabAuditoria import TabAuditoria
from ui.TabDashboard import TabDashboard # <--- Nova aba!

from funcoes_colaboradores import atualizar_validade_cnh_em_massa, garantir_schema_banco, get_documentos_a_vencer
from melhorias_programa import carregar_qss_personalizado

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent_selector=None):
        super().__init__()
        self.parent_selector = parent_selector
        garantir_schema_banco()
        self.setObjectName("mainWindow")
        self.setWindowTitle("Operacoes Agricolas | Gestor de Colaboradores")
        self._configurar_janela_inicial()
        self.statusBar().showMessage("Sistema iniciado.", 2000)
        self.statusBar().setObjectName("mainStatusBar")
        self.footer_credit = QtWidgets.QLabel("Desenvolvido por Gabriel Barbosa dos Santos")
        self.footer_credit.setObjectName("footerCredit")
        self.statusBar().addPermanentWidget(self.footer_credit)

        self.settings = QtCore.QSettings("SuaEmpresa", "SistemaColaboradores")
        self._carregar_tema()
        self._criar_barra_menus()
        self._setup_system_tray()

        self.central_widget = QtWidgets.QWidget()
        self.central_widget.setObjectName("mainShell")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(14)

        header = QtWidgets.QFrame()
        header.setObjectName("heroPanel")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(12)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(2)
        title = QtWidgets.QLabel("Operacoes Agricolas")
        title.setObjectName("heroTitle")
        subtitle = QtWidgets.QLabel("Gestor de Colaboradores | cadastro, documentos, CNH e escala")
        subtitle.setObjectName("heroSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        module_chip = QtWidgets.QLabel("RH")
        module_chip.setObjectName("statusChip")
        module_chip.setProperty("tone", "secondary")

        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(module_chip, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.main_layout.addWidget(header)

        # Abas
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)

        self.tab_dashboard = TabDashboard(self) # <---
        self.tab_cnh = TabCNH(self)
        self.tab_cadastro = TabCadastro(self)
        self.tab_consulta = TabConsulta(self)
        self.tab_escala = TabEscala(self)
        self.tab_relatorios = TabRelatorios(self)
        self.tab_auditoria = TabAuditoria(self)

        self.tabs.addTab(self.tab_dashboard, "Dashboard")
        self.tabs.addTab(self.tab_cnh, "Central CNH")
        self.tabs.addTab(self.tab_consulta, "Consulta")
        self.tabs.addTab(self.tab_escala, "Escala")
        self.tabs.addTab(self.tab_cadastro, "Cadastro")
        self.tabs.addTab(self.tab_relatorios, "Relatórios")
        self.tabs.addTab(self.tab_auditoria, "Auditoria")

        self.main_layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setCurrentWidget(self.tab_cnh)

        # Verificação Inicial
        QtCore.QTimer.singleShot(1000, self.verificar_notificacoes_inicio)

    def _configurar_janela_inicial(self):
        tela = QtWidgets.QApplication.primaryScreen()
        if tela is None:
            self.setMinimumSize(980, 620)
            self.resize(1120, 700)
            return

        area = tela.availableGeometry()
        largura_minima = min(980, max(760, area.width() - 80))
        altura_minima = min(620, max(520, area.height() - 80))
        self.setMinimumSize(largura_minima, altura_minima)

        largura = min(1120, max(largura_minima, int(area.width() * 0.82)), area.width())
        altura = min(700, max(altura_minima, int(area.height() * 0.82)), area.height())
        self.resize(largura, altura)

        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

    def _setup_system_tray(self):
        self.tray_icon = None
        app = QtWidgets.QApplication.instance()
        if app and app.platformName() in {"offscreen", "minimal"}:
            logging.info("System tray desativado para plataforma Qt '%s'.", app.platformName())
            return
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            logging.info("System tray indisponível neste ambiente.")
            return

        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.show()

    def verificar_notificacoes_inicio(self):
        docs = get_documentos_a_vencer(dias=30)
        if docs and self.tray_icon:
            self.tray_icon.showMessage(
                "Alertas do Sistema",
                f"{len(docs)} documentos vencem em breve!",
                QtWidgets.QSystemTrayIcon.Warning, 5000
            )

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget == self.tab_consulta:
            self.tab_consulta.carregar_dados()
        elif widget == self.tab_cnh:
            self.tab_cnh.carregar_dados()
        elif widget == self.tab_escala:
            self.tab_escala.carregar_escala()
        elif widget == self.tab_dashboard:
            self.tab_dashboard.carregar_dados()
        elif widget == self.tab_auditoria:
            self.tab_auditoria.atualizar_tabela_auditoria()

    def ir_para_cadastro_e_carregar(self, codigo):
        self.tabs.setCurrentWidget(self.tab_cadastro)
        self.tab_cadastro.carregar_dados_para_edicao(codigo)

    def ir_para_cnh(self, codigo):
        self.tabs.setCurrentWidget(self.tab_cnh)
        self.tab_cnh.selecionar_codigo(codigo)

    def _criar_barra_menus(self):
        menubar = self.menuBar()
        menu_arq = menubar.addMenu("Arquivo")

        acao_att = QtWidgets.QAction("Importar CNHs (Excel)", self)
        acao_att.triggered.connect(self._iniciar_atualizacao_cnh)
        menu_arq.addAction(acao_att)

        acao_sair = QtWidgets.QAction("Sair", self)
        acao_sair.triggered.connect(self.close)
        menu_arq.addAction(acao_sair)

    def _iniciar_atualizacao_cnh(self):
        caminho_arquivo, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Selecionar planilha de atualização de CNH",
            "",
            "Planilhas (*.xlsx *.xls)",
        )
        if not caminho_arquivo:
            return

        sucesso, mensagem = atualizar_validade_cnh_em_massa(caminho_arquivo)
        if sucesso:
            QtWidgets.QMessageBox.information(self, "Atualização de CNH", mensagem)
            self.statusBar().showMessage("Validades de CNH atualizadas.", 5000)
            self.tab_consulta.carregar_dados()
            self.tab_dashboard.carregar_dados()
        else:
            QtWidgets.QMessageBox.warning(self, "Atualização de CNH", mensagem)

    def _carregar_tema(self):
        tema = self.settings.value("tema", "claro")
        carregar_qss_personalizado(self, tema)

    # ... Copiar os outros métodos auxiliares se necessário,
    # mas o principal está aqui.
