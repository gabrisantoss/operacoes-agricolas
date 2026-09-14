# ui/TabCadastro.py (Versão Corrigida - Ícones Atualizados)

import os
import sys
import subprocess
from PyQt5 import QtWidgets, QtCore, QtGui
import qtawesome as qta
import logging

# Tente importar de funcoes_colaboradores, se falhar, define caminho local
try:
    from funcoes_colaboradores import (
        adicionar_colaborador, atualizar_colaborador, colaborador_existe,
        excluir_colaborador, obter_colaborador_por_codigo,
        adicionar_documento, listar_documentos_por_colaborador, excluir_documento,
        listar_observacoes_para_cadastro, salvar_observacoes_do_cadastro,
        validar_dados_colaborador,
        get_db_connection,
        DB_PATH # Importante pegar o caminho do banco
    )
except ImportError:
    # Fallback caso não ache (apenas para evitar crash imediato no IDE)
    DB_PATH = "colaboradores.db"
    get_db_connection = None
    def validar_dados_colaborador(dados):
        return dados, {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

STYLE_ERROR = "border: 1px solid red; border-radius: 4px;"
STYLE_NORMAL = "border: 1px solid #ccc; border-radius: 4px;"
DATE_EMPTY = QtCore.QDate(1900, 1, 1)


class OptionalDateEdit(QtWidgets.QDateEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd/MM/yyyy")
        self.setSpecialValueText("Sem data")
        self.setMinimumDate(DATE_EMPTY)
        self.setDate(DATE_EMPTY)

    def clear(self):
        self.setDate(self.minimumDate())

    def is_empty(self) -> bool:
        return self.date() == self.minimumDate()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)


class TabCadastro(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.colaborador_sendo_editado_codigo = None

        # Mapa dos campos
        self.campos_cadastro_config = {
            "Informações Pessoais": [
                {"label": "Nome", "db_name": "nome", "type": "QLineEdit", "required": True},
                {"label": "Data Nascimento", "db_name": "nascimento", "type": "QDateEdit"},
                {"label": "CPF", "db_name": "cpf", "type": "QLineEdit"},
                {"label": "RG", "db_name": "rg", "type": "QLineEdit"},
                {"label": "Cidade", "db_name": "municipio", "type": "QLineEdit"}, # Autocomplete aqui
                {"label": "Telefone", "db_name": "telefone", "type": "QLineEdit"},
            ],
            "Dados Profissionais": [
                {"label": "Código (Matrícula)", "db_name": "codigo_colaborador", "type": "QLineEdit", "required": True},
                {"label": "Função", "db_name": "funcao", "type": "QLineEdit"}, # Autocomplete aqui
                {"label": "Gestor Responsável", "db_name": "gestor_responsavel", "type": "QLineEdit"},
                {"label": "Data Admissão", "db_name": "data_admissao", "type": "QDateEdit"},
                {"label": "Salário (R$)", "db_name": "salario", "type": "QLineEdit"},
                {"label": "Local de Trabalho (Fazenda)", "db_name": "local_trabalho", "type": "QLineEdit"},
            ],
            "Documentação (CNH)": [
                {"label": "Nº Registro CNH", "db_name": "registro_cnh", "type": "QLineEdit"},
                {"label": "Categoria CNH", "db_name": "categoria_cnh", "type": "QComboBox", "options": ["", "A", "B", "AB", "C", "D", "E", "AD", "AE"]},
                {"label": "Validade CNH", "db_name": "validade_cnh", "type": "QDateEdit"},
                {"label": "Primeira Habilitação", "db_name": "primeira_cnh", "type": "QDateEdit"},
            ]
        }

        self.entradas = {}
        self.ui_to_db_map = {}

        self._setup_ui()
        self._configurar_autocompletes() # Carrega sugestões do banco

    def _setup_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)

        # --- Coluna da Esquerda (Formulário) ---
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)

        form_widget = QtWidgets.QWidget()
        self.form_layout = QtWidgets.QVBoxLayout(form_widget)
        self.form_layout.setSpacing(15)

        # Título
        lbl_titulo = QtWidgets.QLabel("Ficha de Cadastro")
        lbl_titulo.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin-bottom: 10px;")
        self.form_layout.addWidget(lbl_titulo)

        # Gerar Campos
        for grupo, campos in self.campos_cadastro_config.items():
            group_box = QtWidgets.QGroupBox(grupo)
            group_layout = QtWidgets.QGridLayout(group_box)

            row = 0
            col = 0
            for campo in campos:
                lbl = QtWidgets.QLabel(campo["label"])

                if campo["type"] == "QLineEdit":
                    widget = QtWidgets.QLineEdit()
                elif campo["type"] == "QDateEdit":
                    widget = OptionalDateEdit()
                elif campo["type"] == "QComboBox":
                    widget = QtWidgets.QComboBox()
                    widget.addItems(campo.get("options", []))

                if campo["db_name"] == "cpf" and isinstance(widget, QtWidgets.QLineEdit):
                    widget.setPlaceholderText("Somente números")
                elif campo["db_name"] == "telefone" and isinstance(widget, QtWidgets.QLineEdit):
                    widget.setPlaceholderText("DDD + número")
                elif campo["db_name"] == "salario" and isinstance(widget, QtWidgets.QLineEdit):
                    widget.setPlaceholderText("Ex: 2500,00")

                self.entradas[campo["label"]] = widget
                self.ui_to_db_map[campo["label"]] = campo["db_name"]

                group_layout.addWidget(lbl, row, col)
                group_layout.addWidget(widget, row + 1, col)

                col += 1
                if col > 1:
                    col = 0
                    row += 2

            self.form_layout.addWidget(group_box)

        # Botões de Ação
        btn_layout = QtWidgets.QHBoxLayout()

        # CORREÇÃO AQUI: Mudado de 'fa.save' para 'fa5s.save'
        self.btn_salvar = QtWidgets.QPushButton(" Salvar Cadastro")
        self.btn_salvar.setIcon(qta.icon('fa5s.save', color='white'))
        self.btn_salvar.setStyleSheet("background-color: #27ae60; color: white; padding: 10px; font-weight: bold;")
        self.btn_salvar.clicked.connect(self.salvar_colaborador)

        # CORREÇÃO AQUI: Mudado de 'fa.eraser' para 'fa5s.eraser'
        self.btn_limpar = QtWidgets.QPushButton(" Novo / Limpar")
        self.btn_limpar.setIcon(qta.icon('fa5s.eraser', color='white'))
        self.btn_limpar.setStyleSheet("background-color: #f39c12; color: white; padding: 10px;")
        self.btn_limpar.clicked.connect(self.limpar_formulario)

        # CORREÇÃO AQUI: Mudado de 'fa.trash' para 'fa5s.trash'
        self.btn_excluir = QtWidgets.QPushButton(" Excluir Colaborador")
        self.btn_excluir.setIcon(qta.icon('fa5s.trash', color='white'))
        self.btn_excluir.setStyleSheet("background-color: #c0392b; color: white; padding: 10px;")
        self.btn_excluir.clicked.connect(self.excluir_atual)
        self.btn_excluir.setVisible(False)

        btn_layout.addWidget(self.btn_salvar)
        btn_layout.addWidget(self.btn_limpar)
        btn_layout.addWidget(self.btn_excluir)

        self.form_layout.addLayout(btn_layout)
        self.form_layout.addStretch() # Empurra tudo pra cima

        scroll_area.setWidget(form_widget)

        # --- Coluna da Direita (Extras: Docs e Obs) ---
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_panel.setFixedWidth(350)
        right_panel.setStyleSheet("background-color: #fcfcfc; border-left: 1px solid #e0e0e0;")

        # Seção Documentos
        right_layout.addWidget(QtWidgets.QLabel("📂 Documentos Digitalizados"))
        self.lista_docs = QtWidgets.QListWidget()
        right_layout.addWidget(self.lista_docs)

        btn_add_doc = QtWidgets.QPushButton("Anexar Documento")
        btn_add_doc.clicked.connect(self.anexar_documento)
        right_layout.addWidget(btn_add_doc)

        btn_open_doc = QtWidgets.QPushButton("Abrir Selecionado")
        btn_open_doc.clicked.connect(self.abrir_documento_selecionado)
        right_layout.addWidget(btn_open_doc)

        btn_del_doc = QtWidgets.QPushButton("Remover Anexo")
        btn_del_doc.clicked.connect(self.remover_documento_selecionado)
        right_layout.addWidget(btn_del_doc)

        right_layout.addSpacing(20)

        # Seção Observações
        right_layout.addWidget(QtWidgets.QLabel("📝 Observações / Histórico"))
        self.txt_observacoes = QtWidgets.QTextEdit()
        self.txt_observacoes.setPlaceholderText("Escreva observações aqui...")
        right_layout.addWidget(self.txt_observacoes)

        main_layout.addWidget(scroll_area, stretch=2)
        main_layout.addWidget(right_panel, stretch=1)

    def _configurar_autocompletes(self):
        """Busca cidades e funções únicas no banco para sugerir ao digitar."""
        try:
            if get_db_connection is None:
                return
            conn = get_db_connection()
            cursor = conn.cursor()

            # Autocomplete Cidades
            cursor.execute("""
                SELECT DISTINCT COALESCE(NULLIF(municipio, ''), NULLIF(cidade, '')) AS valor
                FROM colaboradores
                WHERE COALESCE(NULLIF(municipio, ''), NULLIF(cidade, '')) IS NOT NULL
                  AND COALESCE(oculto_operacao, 0) = 0
                ORDER BY valor
            """)
            cidades = [row[0] for row in cursor.fetchall()]
            if "Cidade" in self.entradas:
                completer_cidade = QtWidgets.QCompleter(cidades, self.entradas["Cidade"])
                completer_cidade.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
                self.entradas["Cidade"].setCompleter(completer_cidade)

            # Autocomplete Funções
            cursor.execute("""
                SELECT DISTINCT COALESCE(NULLIF(funcao, ''), NULLIF(funcao_safra, '')) AS valor
                FROM colaboradores
                WHERE COALESCE(NULLIF(funcao, ''), NULLIF(funcao_safra, '')) IS NOT NULL
                  AND COALESCE(oculto_operacao, 0) = 0
                ORDER BY valor
            """)
            funcoes = [row[0] for row in cursor.fetchall()]
            if "Função" in self.entradas:
                completer_funcao = QtWidgets.QCompleter(funcoes, self.entradas["Função"])
                completer_funcao.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
                self.entradas["Função"].setCompleter(completer_funcao)

            cursor.execute("""
                SELECT DISTINCT gestor_responsavel
                FROM colaboradores
                WHERE gestor_responsavel IS NOT NULL AND gestor_responsavel != ''
                  AND COALESCE(oculto_operacao, 0) = 0
                ORDER BY gestor_responsavel
            """)
            gestores = [row[0] for row in cursor.fetchall()]
            if "Gestor Responsável" in self.entradas:
                completer_gestor = QtWidgets.QCompleter(gestores, self.entradas["Gestor Responsável"])
                completer_gestor.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
                self.entradas["Gestor Responsável"].setCompleter(completer_gestor)

            conn.close()
        except Exception as e:
            logging.error(f"Erro ao configurar autocomplete: {e}")

    def carregar_dados_para_edicao(self, codigo_colaborador):
        self.limpar_formulario()
        colab_data = obter_colaborador_por_codigo(codigo_colaborador)
        if not colab_data:
            QtWidgets.QMessageBox.warning(self, "Erro", "Colaborador não encontrado.")
            return

        self.colaborador_sendo_editado_codigo = codigo_colaborador
        self.btn_salvar.setText(" Atualizar Cadastro")
        self.btn_salvar.setStyleSheet("background-color: #2980b9; color: white; padding: 10px; font-weight: bold;")
        self.btn_excluir.setVisible(True)

        self._set_dados_to_ui(colab_data)
        self._carregar_documentos(codigo_colaborador)
        self._carregar_observacoes(codigo_colaborador)

    def _set_dados_to_ui(self, colab_data: dict):
        fallbacks = {
            "municipio": "cidade",
            "funcao": "funcao_safra",
        }
        for ui_label, widget in self.entradas.items():
            db_name = self.ui_to_db_map.get(ui_label)
            if db_name and db_name in colab_data:
                value = colab_data[db_name]
                if (value is None or value == "") and db_name in fallbacks:
                    value = colab_data.get(fallbacks[db_name])
                if isinstance(widget, QtWidgets.QLineEdit):
                    widget.setText(str(value if value is not None else ""))
                elif isinstance(widget, QtWidgets.QComboBox):
                    index = widget.findText(str(value if value is not None else ""), QtCore.Qt.MatchFixedString)
                    widget.setCurrentIndex(index if index >= 0 else 0)
                elif isinstance(widget, OptionalDateEdit):
                    if value:
                        data = QtCore.QDate.fromString(str(value), "yyyy-MM-dd")
                        widget.setDate(data if data.isValid() else DATE_EMPTY)
                    else:
                        widget.clear()

    def _date_edit_para_valor(self, widget: OptionalDateEdit):
        return None if widget.is_empty() else widget.date().toString("yyyy-MM-dd")

    def _get_dados_from_ui(self):
        dados = {}
        erros = []
        campo_para_label = {db_name: ui_label for ui_label, db_name in self.ui_to_db_map.items()}

        # Reset styles
        for widget in self.entradas.values():
            widget.setStyleSheet(STYLE_NORMAL)

        for ui_label, widget in self.entradas.items():
            db_name = self.ui_to_db_map.get(ui_label)
            value = None

            if isinstance(widget, QtWidgets.QLineEdit):
                value = widget.text().strip()
            elif isinstance(widget, QtWidgets.QComboBox):
                value = widget.currentText()
            elif isinstance(widget, OptionalDateEdit):
                value = self._date_edit_para_valor(widget)

            # Validação Obrigatória
            required = False
            for group in self.campos_cadastro_config.values():
                for field in group:
                    if field["label"] == ui_label and field.get("required"):
                        required = True
                        break

            if required and not value:
                widget.setStyleSheet(STYLE_ERROR)
                erros.append(f"O campo '{ui_label}' é obrigatório.")

            dados[db_name] = value

        dados_normalizados, erros_validacao = validar_dados_colaborador(dados)
        for campo, mensagem in erros_validacao.items():
            ui_label = campo_para_label.get(campo)
            widget = self.entradas.get(ui_label) if ui_label else None
            if widget:
                widget.setStyleSheet(STYLE_ERROR)
            erros.append(mensagem)

        return dados_normalizados, erros

    def salvar_colaborador(self):
        dados, erros = self._get_dados_from_ui()
        if erros:
            QtWidgets.QMessageBox.warning(self, "Campos Obrigatórios", "\n".join(erros))
            return

        codigo = dados.get('codigo_colaborador')

        try:
            if self.colaborador_sendo_editado_codigo:
                # Modo Edição
                if str(codigo) != str(self.colaborador_sendo_editado_codigo):
                    if colaborador_existe(codigo):
                        QtWidgets.QMessageBox.warning(self, "Erro", "Já existe outro colaborador com este novo código.")
                        return

                sucesso, mensagem = atualizar_colaborador(self.colaborador_sendo_editado_codigo, dados)
                if not sucesso:
                    QtWidgets.QMessageBox.critical(self, "Erro", mensagem)
                    return

                obs_texto = self.txt_observacoes.toPlainText()
                salvar_observacoes_do_cadastro(codigo, obs_texto)

                QtWidgets.QMessageBox.information(self, "Sucesso", mensagem)
                self.limpar_formulario()
                self.main_window.tab_consulta.carregar_dados()
            else:
                # Modo Inserção
                if colaborador_existe(codigo):
                    QtWidgets.QMessageBox.warning(self, "Erro", "Já existe um colaborador com este código.")
                    return

                sucesso, mensagem = adicionar_colaborador(dados)
                if not sucesso:
                    QtWidgets.QMessageBox.critical(self, "Erro", mensagem)
                    return

                obs_texto = self.txt_observacoes.toPlainText()
                if obs_texto:
                    salvar_observacoes_do_cadastro(codigo, obs_texto)

                QtWidgets.QMessageBox.information(self, "Sucesso", mensagem)
                self.limpar_formulario()
                self.main_window.tab_consulta.carregar_dados()

            # Atualiza autocompletes
            self._configurar_autocompletes()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Erro ao salvar: {e}")

    def excluir_atual(self):
        if not self.colaborador_sendo_editado_codigo: return

        confirm = QtWidgets.QMessageBox.question(
            self, "Confirmar Exclusão",
            "Tem certeza que deseja excluir este colaborador e seus documentos?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if confirm == QtWidgets.QMessageBox.Yes:
            sucesso, mensagem = excluir_colaborador(self.colaborador_sendo_editado_codigo)
            if sucesso:
                QtWidgets.QMessageBox.information(self, "Excluído", mensagem)
                self.limpar_formulario()
                self.main_window.tab_consulta.carregar_dados()
            else:
                QtWidgets.QMessageBox.critical(self, "Erro", mensagem)

    def limpar_formulario(self):
        self.colaborador_sendo_editado_codigo = None
        self.btn_salvar.setText(" Salvar Cadastro")
        self.btn_salvar.setStyleSheet("background-color: #27ae60; color: white; padding: 10px; font-weight: bold;")
        self.btn_excluir.setVisible(False)
        self.txt_observacoes.clear()
        self.lista_docs.clear()

        for widget in self.entradas.values():
            widget.setStyleSheet(STYLE_NORMAL)
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.clear()
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentIndex(0)
            elif isinstance(widget, OptionalDateEdit):
                widget.clear()

        if "Código (Matrícula)" in self.entradas:
            self.entradas["Código (Matrícula)"].setFocus()

    # --- Gestão de Documentos (Anexos) ---
    def _carregar_documentos(self, codigo):
        self.lista_docs.clear()
        docs = listar_documentos_por_colaborador(codigo)
        for doc in docs:
            item = QtWidgets.QListWidgetItem(f"{doc['tipo_documento']} - {doc['nome_arquivo']}")
            item.setData(QtCore.Qt.UserRole, doc['caminho_arquivo'])
            item.setData(QtCore.Qt.UserRole + 1, doc['id'])
            self.lista_docs.addItem(item)

    def anexar_documento(self):
        if not self.colaborador_sendo_editado_codigo:
            QtWidgets.QMessageBox.warning(self, "Aviso", "Salve o colaborador primeiro antes de anexar documentos.")
            return

        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Selecionar Documento")
        if caminho:
            tipo, ok = QtWidgets.QInputDialog.getItem(
                self, "Tipo de Documento", "Selecione o tipo:",
                ["CNH", "RG", "CPF", "Comprovante Endereço", "Contrato", "Outros"], 0, False
            )
            if ok and tipo:
                sucesso, mensagem = adicionar_documento(self.colaborador_sendo_editado_codigo, tipo, caminho)
                if sucesso:
                    self._carregar_documentos(self.colaborador_sendo_editado_codigo)
                    QtWidgets.QMessageBox.information(self, "Sucesso", mensagem)
                else:
                    QtWidgets.QMessageBox.critical(self, "Erro", mensagem)

    def abrir_documento_selecionado(self):
        item = self.lista_docs.currentItem()
        if not item: return
        caminho = item.data(QtCore.Qt.UserRole)
        self.abrir_arquivo(caminho)

    def remover_documento_selecionado(self):
        item = self.lista_docs.currentItem()
        if not item: return
        doc_id = item.data(QtCore.Qt.UserRole + 1)

        sucesso, mensagem = excluir_documento(doc_id)
        if sucesso:
            self._carregar_documentos(self.colaborador_sendo_editado_codigo)
        else:
            QtWidgets.QMessageBox.warning(self, "Erro", mensagem)

    def abrir_arquivo(self, caminho_arquivo: str):
        if not caminho_arquivo or not os.path.exists(caminho_arquivo):
            QtWidgets.QMessageBox.critical(self, "Erro", "Arquivo não encontrado no disco.")
            return
        try:
            if sys.platform == 'win32': os.startfile(os.path.normpath(caminho_arquivo))
            else:
                opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
                subprocess.call([opener, caminho_arquivo])
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Não foi possível abrir o arquivo: {e}")

    def _carregar_observacoes(self, codigo):
        obs_lista = listar_observacoes_para_cadastro(codigo)
        if obs_lista:
            if isinstance(obs_lista, dict):
                textos = [item.get('texto', '') for _, item in sorted(obs_lista.items()) if item.get('texto')]
                self.txt_observacoes.setText("\n".join(textos))
            elif isinstance(obs_lista, str):
                self.txt_observacoes.setText(obs_lista)
