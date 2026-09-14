import logging
import os
import subprocess
import sys
from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets
import qtawesome as qta
from fpdf import FPDF

from core.cnh_management import ACOMPANHAMENTO_LABELS, listar_acompanhamentos_cnh, listar_historico_cnh
from funcoes_colaboradores import (
    DB_PATH,
    adicionar_documento,
    listar_documentos_por_colaborador,
    listar_observacoes_para_cadastro,
    obter_colaborador_por_codigo,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _pdf_latin1_text(value) -> str:
    return str(value if value is not None else "").encode("latin-1", "replace").decode("latin-1")


def _measure_profile_pdf_row(pdf, label, value, label_width=50, line_height=6, min_height=8):
    padding = 1
    value_width = pdf.w - pdf.r_margin - pdf.l_margin - label_width
    label_text = _pdf_latin1_text(f"{label}:")
    value_text = _pdf_latin1_text(value)

    pdf.set_font("Arial", "B", 10)
    label_lines = pdf.multi_cell(
        max(label_width - (2 * padding), 1), line_height, label_text, split_only=True
    )
    pdf.set_font("Arial", "", 10)
    value_lines = pdf.multi_cell(
        max(value_width - (2 * padding), 1), line_height, value_text, split_only=True
    )
    row_height = max(
        min_height,
        (max(len(label_lines), len(value_lines), 1) * line_height) + (2 * padding),
    )
    return label_text, value_text, value_width, row_height


def _draw_profile_section_header(pdf, title):
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, _pdf_latin1_text(title), 1, 1, "L", fill=True)


def _draw_profile_pdf_row(
    pdf,
    label,
    value,
    label_width=50,
    line_height=6,
    min_height=8,
    continuation_section=None,
):
    padding = 1
    x_start = pdf.l_margin
    label_text, value_text, value_width, row_height = _measure_profile_pdf_row(
        pdf,
        label,
        value,
        label_width,
        line_height,
        min_height,
    )

    if pdf.get_y() + row_height > pdf.page_break_trigger:
        pdf.add_page()
        if continuation_section:
            _draw_profile_section_header(pdf, continuation_section)

    y_start = pdf.get_y()
    pdf.rect(x_start, y_start, label_width, row_height)
    pdf.rect(x_start + label_width, y_start, value_width, row_height)

    pdf.set_font("Arial", "B", 10)
    pdf.set_xy(x_start + padding, y_start + padding)
    pdf.multi_cell(max(label_width - (2 * padding), 1), line_height, label_text, border=0)
    pdf.set_font("Arial", "", 10)
    pdf.set_xy(x_start + label_width + padding, y_start + padding)
    pdf.multi_cell(max(value_width - (2 * padding), 1), line_height, value_text, border=0)
    pdf.set_xy(x_start, y_start + row_height)
    return row_height


def _build_chip(texto: str, tone: str, compact: bool = False) -> QtWidgets.QLabel:
    chip = QtWidgets.QLabel(texto)
    chip.setObjectName("statusChip")
    chip.setProperty("tone", tone)
    chip.setProperty("compact", compact)
    chip.setAlignment(QtCore.Qt.AlignCenter)
    chip.setMinimumHeight(22 if compact else 28)
    chip.setContentsMargins(10, 4, 10, 4)
    return chip


class ProfileWindow(QtWidgets.QDialog):
    def __init__(self, codigo_colaborador, parent=None):
        super().__init__(parent)
        self.codigo_colaborador = codigo_colaborador
        self.colab_data = {}

        self.setObjectName("profileWindow")
        self.setWindowTitle(f"Perfil - {codigo_colaborador}")
        self.setMinimumSize(980, 760)

        try:
            self._setup_ui()
            self.carregar_dados()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Falha ao abrir perfil: {e}")

    def _acomp_tone(self, status: str) -> str:
        return {
            "Regularizado": "success",
            "Em andamento": "secondary",
            "Agendado": "caution",
            "Sem retorno": "warning",
            "Aguardando documento": "warning",
            "Sem ação": "neutral",
        }.get(status, "neutral")

    def _refresh_chip(self, chip: QtWidgets.QLabel, texto: str, tone: str):
        chip.setText(texto)
        chip.setProperty("tone", tone)
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        chip.update()

    def _formatar_data(self, valor) -> str:
        texto = str(valor or "").strip()
        if not texto:
            return "-"
        for formato in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(texto, formato).strftime("%d/%m/%Y")
            except ValueError:
                pass
        return texto

    def _formatar_salario(self, valor) -> str:
        if valor in (None, ""):
            return "-"
        try:
            return f"R$ {float(valor):.2f}"
        except (TypeError, ValueError):
            return str(valor)

    def _criar_form_group(self, titulo: str, campos: list[tuple[str, str]]) -> tuple[QtWidgets.QGroupBox, dict]:
        group = QtWidgets.QGroupBox(titulo)
        group.setObjectName("panelGroup")
        form = QtWidgets.QFormLayout(group)
        form.setSpacing(12)
        widgets = {}
        for rotulo, chave in campos:
            valor = QtWidgets.QLabel("-")
            valor.setObjectName("detailValue")
            valor.setWordWrap(True)
            valor.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            form.addRow(f"{rotulo}:", valor)
            widgets[chave] = valor
        return group, widgets

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(16)

        hero = QtWidgets.QFrame()
        hero.setObjectName("profileHero")
        hero_layout = QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(16)

        icon_wrap = QtWidgets.QFrame()
        icon_wrap.setObjectName("iconBadge")
        icon_layout = QtWidgets.QVBoxLayout(icon_wrap)
        icon_layout.setContentsMargins(12, 12, 12, 12)
        icon_layout.setAlignment(QtCore.Qt.AlignCenter)
        icon_label = QtWidgets.QLabel()
        try:
            icon_label.setPixmap(qta.icon("fa5s.user-circle", color="#31576f").pixmap(42, 42))
        except Exception:
            icon_label.setText("Perfil")
        icon_layout.addWidget(icon_label)
        hero_layout.addWidget(icon_wrap, alignment=QtCore.Qt.AlignTop)

        titles_layout = QtWidgets.QVBoxLayout()
        titles_layout.setSpacing(6)
        eyebrow = QtWidgets.QLabel("Ficha operacional")
        eyebrow.setObjectName("heroEyebrow")
        self.lbl_nome_header = QtWidgets.QLabel("Carregando...")
        self.lbl_nome_header.setObjectName("heroTitle")
        self.lbl_cargo_header = QtWidgets.QLabel("-")
        self.lbl_cargo_header.setObjectName("heroSubtitle")
        self.lbl_meta_header = QtWidgets.QLabel("Abrindo dados do colaborador.")
        self.lbl_meta_header.setObjectName("detailHint")
        self.lbl_meta_header.setWordWrap(True)
        titles_layout.addWidget(eyebrow)
        titles_layout.addWidget(self.lbl_nome_header)
        titles_layout.addWidget(self.lbl_cargo_header)
        titles_layout.addWidget(self.lbl_meta_header)
        hero_layout.addLayout(titles_layout, stretch=1)

        botoes = QtWidgets.QVBoxLayout()
        botoes.setSpacing(10)
        self.btn_pdf = QtWidgets.QPushButton("Gerar ficha PDF")
        self.btn_pdf.setObjectName("secondaryAction")
        try:
            self.btn_pdf.setIcon(qta.icon("fa5s.file-pdf", color="white"))
        except Exception:
            pass
        self.btn_pdf.clicked.connect(self.gerar_ficha_pdf)
        self.btn_close = QtWidgets.QPushButton("Fechar")
        self.btn_close.setObjectName("ghostAction")
        self.btn_close.clicked.connect(self.accept)
        botoes.addWidget(self.btn_pdf)
        botoes.addWidget(self.btn_close)
        botoes.addStretch()
        hero_layout.addLayout(botoes)

        main_layout.addWidget(hero)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("profileTabs")

        self.tab_dados = QtWidgets.QWidget()
        self._setup_tab_dados()
        self.tabs.addTab(self.tab_dados, "Dados")

        self.tab_docs = QtWidgets.QWidget()
        self._setup_tab_docs()
        self.tabs.addTab(self.tab_docs, "Documentos")

        self.tab_hist = QtWidgets.QWidget()
        self._setup_tab_hist()
        self.tabs.addTab(self.tab_hist, "Histórico")

        self.tab_cnh = QtWidgets.QWidget()
        self._setup_tab_cnh()
        self.tabs.addTab(self.tab_cnh, "CNH")

        main_layout.addWidget(self.tabs)

    def _setup_tab_dados(self):
        layout = QtWidgets.QVBoxLayout(self.tab_dados)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setSpacing(14)

        grupo_pessoal, campos_pessoais = self._criar_form_group(
            "Dados pessoais",
            [
                ("Matrícula", "codigo_colaborador"),
                ("Nome completo", "nome"),
                ("CPF", "cpf"),
                ("RG", "rg"),
                ("Data de nascimento", "nascimento"),
                ("Cidade", "municipio"),
                ("Telefone", "telefone"),
            ],
        )
        grupo_profissional, campos_profissionais = self._criar_form_group(
            "Dados profissionais",
            [
                ("Função", "funcao"),
                ("Gestor responsável", "gestor_responsavel"),
                ("Setor / local", "local_trabalho"),
                ("Data de admissão", "data_admissao"),
                ("Salário", "salario"),
            ],
        )
        grupo_cnh, campos_cnh = self._criar_form_group(
            "CNH e acompanhamento",
            [
                ("Registro CNH", "registro_cnh"),
                ("Categoria CNH", "categoria_cnh"),
                ("Validade CNH", "validade_cnh"),
                ("Primeira CNH", "primeira_cnh"),
                ("Status acompanhamento", "status_cnh_acompanhamento"),
                ("Último contato", "ultimo_contato_cnh"),
                ("Data prevista", "data_prevista_regularizacao_cnh"),
            ],
        )

        self.campos_visualizacao = {}
        self.campos_visualizacao.update(campos_pessoais)
        self.campos_visualizacao.update(campos_profissionais)
        self.campos_visualizacao.update(campos_cnh)

        content_layout.addWidget(grupo_pessoal)
        content_layout.addWidget(grupo_profissional)
        content_layout.addWidget(grupo_cnh)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _setup_tab_docs(self):
        layout = QtWidgets.QVBoxLayout(self.tab_docs)
        layout.setSpacing(12)

        titulo = QtWidgets.QLabel("Documentos anexados")
        titulo.setObjectName("sectionTitle")
        layout.addWidget(titulo)

        self.lista_docs = QtWidgets.QListWidget()
        self.lista_docs.setAlternatingRowColors(True)
        layout.addWidget(self.lista_docs)

        btns_layout = QtWidgets.QHBoxLayout()
        self.btn_abrir_doc = QtWidgets.QPushButton("Abrir arquivo")
        self.btn_abrir_doc.setObjectName("secondaryAction")
        self.btn_abrir_doc.clicked.connect(self.abrir_documento)
        self.btn_add_doc = QtWidgets.QPushButton("Anexar novo")
        self.btn_add_doc.setObjectName("primaryAction")
        self.btn_add_doc.clicked.connect(self.anexar_documento_rapido)
        btns_layout.addStretch()
        btns_layout.addWidget(self.btn_abrir_doc)
        btns_layout.addWidget(self.btn_add_doc)
        layout.addLayout(btns_layout)

    def _setup_tab_hist(self):
        layout = QtWidgets.QVBoxLayout(self.tab_hist)
        layout.setSpacing(12)
        titulo = QtWidgets.QLabel("Observações registradas")
        titulo.setObjectName("sectionTitle")
        layout.addWidget(titulo)
        self.txt_obs = QtWidgets.QTextBrowser()
        layout.addWidget(self.txt_obs)

    def _setup_tab_cnh(self):
        layout = QtWidgets.QVBoxLayout(self.tab_cnh)
        layout.setSpacing(14)

        resumo_group = QtWidgets.QGroupBox("Resumo operacional de CNH")
        resumo_group.setObjectName("panelGroup")
        resumo_layout = QtWidgets.QVBoxLayout(resumo_group)
        resumo_layout.setSpacing(12)

        chips = QtWidgets.QHBoxLayout()
        self.lbl_status_cnh = _build_chip("Sem ação", "neutral")
        chips.addWidget(self.lbl_status_cnh)
        self.lbl_contato_chip = _build_chip("Sem contato", "neutral")
        chips.addWidget(self.lbl_contato_chip)
        chips.addStretch()
        resumo_layout.addLayout(chips)

        resumo_form = QtWidgets.QFormLayout()
        self.lbl_ultimo_contato_cnh = QtWidgets.QLabel("-")
        self.lbl_ultimo_contato_cnh.setObjectName("detailValue")
        self.lbl_prevista_cnh = QtWidgets.QLabel("-")
        self.lbl_prevista_cnh.setObjectName("detailValue")
        self.lbl_observacao_cnh = QtWidgets.QLabel("-")
        self.lbl_observacao_cnh.setObjectName("detailHint")
        self.lbl_observacao_cnh.setWordWrap(True)
        resumo_form.addRow("Último contato:", self.lbl_ultimo_contato_cnh)
        resumo_form.addRow("Data prevista:", self.lbl_prevista_cnh)
        resumo_form.addRow("Observação:", self.lbl_observacao_cnh)
        resumo_layout.addLayout(resumo_form)
        layout.addWidget(resumo_group)

        titulo_hist = QtWidgets.QLabel("Histórico de renovações")
        titulo_hist.setObjectName("sectionTitle")
        layout.addWidget(titulo_hist)
        self.table_historico_cnh = QtWidgets.QTableWidget()
        self.table_historico_cnh.setObjectName("queueTable")
        self.table_historico_cnh.setColumnCount(5)
        self.table_historico_cnh.setHorizontalHeaderLabels(
            ["Data/Hora", "Validade anterior", "Nova validade", "Categoria", "Responsável"]
        )
        self.table_historico_cnh.horizontalHeader().setStretchLastSection(True)
        self.table_historico_cnh.verticalHeader().setVisible(False)
        self.table_historico_cnh.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table_historico_cnh.setAlternatingRowColors(True)
        self.table_historico_cnh.setShowGrid(False)
        layout.addWidget(self.table_historico_cnh)

        titulo_timeline = QtWidgets.QLabel("Timeline de acompanhamento")
        titulo_timeline.setObjectName("sectionTitle")
        layout.addWidget(titulo_timeline)
        self.table_timeline_cnh = QtWidgets.QTableWidget()
        self.table_timeline_cnh.setObjectName("queueTable")
        self.table_timeline_cnh.setColumnCount(5)
        self.table_timeline_cnh.setHorizontalHeaderLabels(
            ["Data/Hora", "Status", "Responsável", "Data prevista", "Observação"]
        )
        self.table_timeline_cnh.horizontalHeader().setStretchLastSection(True)
        self.table_timeline_cnh.verticalHeader().setVisible(False)
        self.table_timeline_cnh.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table_timeline_cnh.setAlternatingRowColors(True)
        self.table_timeline_cnh.setShowGrid(False)
        layout.addWidget(self.table_timeline_cnh)

    def carregar_dados(self):
        try:
            dados = obter_colaborador_por_codigo(self.codigo_colaborador)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro DB", f"Falha na consulta: {e}")
            return

        if not dados:
            QtWidgets.QMessageBox.warning(self, "Erro", "Colaborador não encontrado no banco de dados.")
            self.close()
            return

        self.colab_data = dados

        nome = str(dados.get("nome") or "Sem nome")
        funcao = str(dados.get("funcao") or dados.get("funcao_safra") or "Sem função")
        cod = str(dados.get("codigo_colaborador") or "")
        gestor = str(dados.get("gestor_responsavel") or "Gestor não informado")
        local = str(dados.get("local_trabalho") or dados.get("frente_safra") or "Sem frente definida")

        self.lbl_nome_header.setText(nome)
        self.lbl_cargo_header.setText(f"{funcao} | Matrícula {cod}")
        self.lbl_meta_header.setText(f"{gestor} | {local}")

        for db_key, widget in self.campos_visualizacao.items():
            valor = dados.get(db_key)
            if db_key == "salario":
                texto = self._formatar_salario(valor)
            elif any(x in db_key for x in ("data", "nascimento", "validade", "primeira")):
                texto = self._formatar_data(valor)
            else:
                texto = str(valor or "-")
            widget.setText(texto)

        self.carregar_docs()
        self.carregar_obs()
        self.carregar_cnh()

    def carregar_obs(self):
        try:
            obs_lista = listar_observacoes_para_cadastro(self.codigo_colaborador)
            texto_final = ""
            if isinstance(obs_lista, dict):
                for _, item in sorted(obs_lista.items()):
                    texto = item.get("texto", "")
                    if texto:
                        texto_final += f"• {texto}\n"
            elif isinstance(obs_lista, str):
                texto_final = obs_lista
            self.txt_obs.setText(texto_final if texto_final else "Nenhuma observação registrada.")
        except Exception as e:
            logging.error("Erro ao carregar observações: %s", e)

    def carregar_docs(self):
        try:
            self.lista_docs.clear()
            docs = listar_documentos_por_colaborador(self.codigo_colaborador)
            for doc in docs:
                try:
                    icon_qta = qta.icon("fa5s.file-alt", color="#31576f")
                except Exception:
                    icon_qta = QtGui.QIcon()
                item = QtWidgets.QListWidgetItem(icon_qta, f"{doc['tipo_documento']} - {doc['nome_arquivo']}")
                item.setData(QtCore.Qt.UserRole, doc["caminho_arquivo"])
                self.lista_docs.addItem(item)
        except Exception as e:
            logging.error("Erro ao carregar documentos: %s", e)

    def carregar_cnh(self):
        status_codigo = str(self.colab_data.get("status_cnh_acompanhamento") or "").strip().upper()
        status_label = ACOMPANHAMENTO_LABELS.get(status_codigo, "Sem ação")
        self._refresh_chip(self.lbl_status_cnh, status_label, self._acomp_tone(status_label))

        houve_contato = bool(self.colab_data.get("ultimo_contato_cnh"))
        contato_label = "Contato registrado" if houve_contato else "Sem contato"
        self._refresh_chip(self.lbl_contato_chip, contato_label, "secondary" if houve_contato else "neutral")

        responsavel = str(self.colab_data.get("responsavel_ultimo_contato_cnh") or "-")
        self.lbl_ultimo_contato_cnh.setText(
            f"{self._formatar_data(self.colab_data.get('ultimo_contato_cnh'))} | {responsavel}"
        )
        self.lbl_prevista_cnh.setText(self._formatar_data(self.colab_data.get("data_prevista_regularizacao_cnh")))
        self.lbl_observacao_cnh.setText(str(self.colab_data.get("observacao_cnh") or "-"))

        historico = listar_historico_cnh(DB_PATH, self.codigo_colaborador)
        self.table_historico_cnh.setRowCount(len(historico))
        for row_idx, item in enumerate(historico):
            valores = [
                item.get("data_hora", ""),
                item.get("validade_anterior_formatada", "") or "-",
                item.get("validade_nova_formatada", "") or "-",
                item.get("categoria_nova") or item.get("categoria_anterior") or "-",
                item.get("responsavel", "") or "-",
            ]
            for col, valor in enumerate(valores):
                self.table_historico_cnh.setItem(row_idx, col, QtWidgets.QTableWidgetItem(str(valor)))

        timeline = listar_acompanhamentos_cnh(DB_PATH, self.codigo_colaborador)
        self.table_timeline_cnh.setRowCount(len(timeline))
        for row_idx, item in enumerate(timeline):
            self.table_timeline_cnh.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(str(item.get("data_hora", ""))))
            status = str(item.get("status_label", "") or "-")
            self.table_timeline_cnh.setCellWidget(row_idx, 1, _build_chip(status, self._acomp_tone(status), True))
            self.table_timeline_cnh.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(str(item.get("responsavel", "") or "-")))
            self.table_timeline_cnh.setItem(
                row_idx, 3, QtWidgets.QTableWidgetItem(str(item.get("data_prevista_formatada", "") or "-"))
            )
            self.table_timeline_cnh.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(str(item.get("observacao", "") or "-")))

        self.table_historico_cnh.resizeColumnsToContents()
        self.table_timeline_cnh.resizeColumnsToContents()

    def abrir_documento(self):
        item = self.lista_docs.currentItem()
        if not item:
            return

        caminho = item.data(QtCore.Qt.UserRole)
        if os.path.exists(caminho):
            if sys.platform == "win32":
                os.startfile(caminho)
            else:
                subprocess.call(["xdg-open", caminho])
        else:
            QtWidgets.QMessageBox.warning(self, "Erro", "Arquivo não encontrado no disco.")

    def anexar_documento_rapido(self):
        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Selecionar documento")
        if not caminho:
            return

        tipo, ok = QtWidgets.QInputDialog.getItem(
            self, "Tipo", "Selecione:", ["CNH", "RG", "CPF", "Outros"], 0, False
        )
        if not ok or not tipo:
            return

        try:
            sucesso, mensagem = adicionar_documento(self.codigo_colaborador, tipo, caminho)
            if not sucesso:
                raise RuntimeError(mensagem)
            self.carregar_docs()
            QtWidgets.QMessageBox.information(self, "Sucesso", mensagem)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Erro ao anexar: {e}")

    def gerar_ficha_pdf(self):
        try:
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Salvar ficha cadastral",
                f"Ficha_{str(self.colab_data.get('nome', 'Colaborador')).replace(' ', '_')}.pdf",
                "PDF Files (*.pdf)",
            )
            if not filename:
                return

            pdf = FPDF()
            pdf.add_page()

            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Ficha Cadastral de Colaborador", 0, 1, "C")
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 1, "C")
            pdf.ln(5)

            pending_section = None
            current_section = None

            def add_section(title):
                nonlocal pending_section, current_section
                pending_section = title
                current_section = title

            def add_row(label, value):
                nonlocal pending_section
                if pending_section:
                    _, _, _, row_height = _measure_profile_pdf_row(pdf, label, value)
                    if pdf.get_y() + 8 + row_height > pdf.page_break_trigger:
                        pdf.add_page()
                    _draw_profile_section_header(pdf, pending_section)
                    pending_section = None
                _draw_profile_pdf_row(
                    pdf,
                    label,
                    value,
                    continuation_section=current_section,
                )

            add_section("Dados Pessoais")
            add_row("Nome Completo", self.colab_data.get("nome"))
            add_row("CPF", self.colab_data.get("cpf"))
            add_row("RG", self.colab_data.get("rg"))
            add_row("Data Nascimento", self.colab_data.get("nascimento"))
            add_row("Cidade/Endereço", self.colab_data.get("municipio"))
            add_row("Telefone", self.colab_data.get("telefone"))
            pdf.ln(5)

            add_section("Dados Profissionais")
            add_row("Matrícula (Código)", self.colab_data.get("codigo_colaborador"))
            add_row("Função/Cargo", self.colab_data.get("funcao"))
            add_row("Data Admissão", self.colab_data.get("data_admissao"))
            add_row("Setor/Fazenda", self.colab_data.get("local_trabalho"))
            add_row("Gestor Responsável", self.colab_data.get("gestor_responsavel"))
            sal = self.colab_data.get("salario", 0)
            add_row("Salário Base", f"R$ {float(sal):.2f}" if sal else "0.00")
            pdf.ln(5)

            add_section("Dados de Habilitação (CNH)")
            add_row("Número Registro", self.colab_data.get("registro_cnh"))
            add_row("Categoria", self.colab_data.get("categoria_cnh"))
            add_row("Data de Validade", self.colab_data.get("validade_cnh"))
            add_row("Status Acompanhamento", ACOMPANHAMENTO_LABELS.get(str(self.colab_data.get("status_cnh_acompanhamento") or "").upper(), "Sem ação"))

            pdf.ln(10)
            signature_y = pdf.h - 50
            if pdf.get_y() > signature_y - 5:
                pdf.add_page()
            pdf.set_y(signature_y)
            pdf.set_font("Arial", "", 10)
            pdf.cell(90, 0, "_" * 40, 0, 0, "C")
            pdf.cell(90, 0, "_" * 40, 0, 1, "C")
            pdf.ln(5)
            pdf.cell(90, 5, "Assinatura do Colaborador", 0, 0, "C")
            pdf.cell(90, 5, "Responsável RH", 0, 1, "C")

            pdf.output(filename)
            QtWidgets.QMessageBox.information(self, "Sucesso", f"Ficha gerada com sucesso.\nSalvo em: {filename}")

            if sys.platform == "win32":
                os.startfile(filename)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erro", f"Erro ao gerar PDF: {e}")
            logging.error("Erro PDF: %s", e)
