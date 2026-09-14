from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from styles import PREMIUM_STYLESHEET


class DialogoComparacao(QtWidgets.QDialog):
    def __init__(self, parent, numero, dados_antigos, dados_novos, numero_duplicado=None):
        super().__init__(parent)
        self.setWindowTitle(f"Conflito na nota {numero}")
        self.setModal(True)
        self.resize(750, 400)
        self.setStyleSheet(PREMIUM_STYLESHEET)
        self.resultado = "cancelar"

        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(f"A nota {numero} ja existe.")
        label.setObjectName("PageTitle")
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label)

        hint = QtWidgets.QLabel("Revise as diferencas antes de sobrescrever ou duplicar o registro.")
        hint.setObjectName("PageSubtitle")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(hint)

        tabela = QtWidgets.QTableWidget()
        tabela.setColumnCount(3)
        tabela.setHorizontalHeaderLabels(["CAMPO", "SISTEMA (ANTIGO)", "DIGITADO (NOVO)"])
        tabela.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        tabela.setRowCount(5)

        campos = [
            ("Motorista", "motorista_nome"),
            ("Caminhao", "caminhao"),
            ("Fazenda", "faz_plantio_nome"),
            ("Data", "data_colheita"),
            ("Variedade", "variedade_nome"),
        ]
        dados_antigos = dict(dados_antigos)

        for index, (nome, chave) in enumerate(campos):
            valor_antigo = str(dados_antigos.get(chave, ""))
            valor_novo = str(dados_novos.get(chave, ""))
            tabela.setItem(index, 0, QtWidgets.QTableWidgetItem(nome))
            tabela.setItem(index, 1, QtWidgets.QTableWidgetItem(valor_antigo))
            item = QtWidgets.QTableWidgetItem(valor_novo)
            if valor_antigo != valor_novo:
                item.setBackground(QtGui.QColor("#4d3800"))
                item.setForeground(QtGui.QColor("#ffdd57"))
            tabela.setItem(index, 2, item)

        layout.addWidget(tabela)

        botoes = QtWidgets.QHBoxLayout()
        btn_cancelar = QtWidgets.QPushButton(" Cancelar")
        btn_cancelar.setObjectName("SecondaryButton")
        btn_cancelar.clicked.connect(self.reject)
        btn_sobrescrever = QtWidgets.QPushButton(" Sobrescrever")
        btn_sobrescrever.setObjectName("PrimaryButton")
        btn_sobrescrever.clicked.connect(lambda: self.fim("sobrescrever"))
        if numero_duplicado is None:
            texto_duplicar = " Duplicar com novo numero"
        else:
            texto_duplicar = f" Duplicar ({numero_duplicado})"
        btn_duplicar = QtWidgets.QPushButton(texto_duplicar)
        btn_duplicar.setObjectName("QuickFilterButton")
        btn_duplicar.clicked.connect(lambda: self.fim("duplicar"))
        botoes.addWidget(btn_cancelar)
        botoes.addWidget(btn_sobrescrever)
        botoes.addWidget(btn_duplicar)
        layout.addLayout(botoes)

    def fim(self, acao: str) -> None:
        self.resultado = acao
        self.accept()
