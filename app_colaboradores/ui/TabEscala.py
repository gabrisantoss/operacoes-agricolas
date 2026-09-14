# ui/TabEscala.py (Versão Drag-and-Drop)

from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome as qta
from funcoes_colaboradores import obter_colaboradores, atualizar_colaborador

class EscalaTreeWidget(QtWidgets.QTreeWidget):
    """Árvore customizada que aceita arrastar e soltar funcionários."""

    colaborador_movido = QtCore.pyqtSignal(str, str) # (id_colaborador, nova_frente)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setColumnCount(3)
        self.setHeaderLabels(["Colaborador", "Função", "Turno"])

    def dropEvent(self, event):
        item_arrastado = self.currentItem()
        item_alvo = self.itemAt(event.pos())

        # Validações
        if not item_arrastado or not item_alvo:
            event.ignore()
            return

        # Garante que estamos soltando SOBRE um setor (nó pai) ou DENTRO de um setor
        # Se soltar sobre outro funcionário, pegamos o pai dele (o setor)
        nova_frente = ""

        # Identifica se o alvo é um setor (nível superior) ou funcionário (filho)
        if item_alvo.parent() is None:
            nova_frente = item_alvo.text(0)
        else:
            nova_frente = item_alvo.parent().text(0)

        # Pega ID do colaborador arrastado
        id_colab = item_arrastado.data(0, QtCore.Qt.UserRole)
        nome_colab = item_arrastado.text(0)

        if not id_colab: # Se arrastar um setor inteiro, ignorar
            event.ignore()
            return

        # Pergunta de confirmação
        msg = f"Deseja mover '{nome_colab}' para a frente '{nova_frente}'?"
        reply = QtWidgets.QMessageBox.question(self, "Mover Colaborador", msg,
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:
            # Emite sinal para a tela principal processar o banco
            self.colaborador_movido.emit(id_colab, nova_frente)

            # O padrão da TreeWidget é mover visualmente, mas como vamos recarregar do banco,
            # podemos deixar ou recarregar tudo. Recarregar é mais seguro.
            super().dropEvent(event)
        else:
            event.ignore()


class TabEscala(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._setup_ui()
        self.carregar_escala()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        lbl_info = QtWidgets.QLabel("💡 Dica: Arraste os funcionários para mudar de frente de safra.")
        lbl_info.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(lbl_info)

        self.tree = EscalaTreeWidget()
        self.tree.colaborador_movido.connect(self._processar_mudanca_setor)
        layout.addWidget(self.tree)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

        btn_refresh = QtWidgets.QPushButton("Recarregar Escala")
        btn_refresh.clicked.connect(self.carregar_escala)
        layout.addWidget(btn_refresh)

    def carregar_escala(self):
        self.tree.clear()
        colaboradores = obter_colaboradores()

        # Agrupar por frente de safra
        frentes = {}

        for colab in colaboradores:
            frente = (colab.get('frente_safra') or '').strip() or "SEM ESCALA"
            if frente not in frentes:
                frentes[frente] = []
            frentes[frente].append(colab)

        for nome_frente in sorted(frentes.keys(), key=lambda nome: (nome == "SEM ESCALA", nome)):
            item_frente = QtWidgets.QTreeWidgetItem(self.tree)
            item_frente.setText(0, nome_frente)
            item_frente.setText(1, f"{len(frentes[nome_frente])} colab.")
            item_frente.setBackground(0, QtGui.QColor("#dce4ec"))
            item_frente.setBackground(1, QtGui.QColor("#dce4ec"))
            item_frente.setBackground(2, QtGui.QColor("#dce4ec"))
            item_frente.setFont(0, QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            item_frente.setFlags(item_frente.flags() & ~QtCore.Qt.ItemIsDragEnabled)
            item_frente.setExpanded(True)

            for colab in sorted(frentes[nome_frente], key=lambda item: item.get('nome') or ''):
                item_colab = QtWidgets.QTreeWidgetItem(item_frente)
                item_colab.setText(0, colab.get('nome'))
                item_colab.setText(1, colab.get('funcao_safra') or colab.get('funcao') or "-")
                item_colab.setText(2, colab.get('turno_safra') or "-")
                item_colab.setData(0, QtCore.Qt.UserRole, str(colab.get('codigo_colaborador')))

                item_colab.setIcon(0, qta.icon('fa5s.user', color='#34495e'))

    def _processar_mudanca_setor(self, id_colab, nova_frente):
        try:
            sucesso, mensagem = atualizar_colaborador({
                'codigo_colaborador': id_colab,
                'frente_safra': nova_frente,
            })
            if not sucesso:
                raise RuntimeError(mensagem)

            self.carregar_escala()
            self.main_window.statusBar().showMessage(f"Sucesso: Colaborador movido para {nova_frente}", 3000)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Falha ao mover: {e}")
