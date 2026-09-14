# ui/TabRelatorios.py (Versão Completa com Relatórios Prontos e Adicionais)

from PyQt5 import QtWidgets, QtCore
from datetime import datetime
from fpdf import FPDF
from core.cnh_management import agrupar_pendencias_por_gestor, exportar_lista_cobranca_excel, exportar_painel_cnh_excel
from core.cnh_reports import carregar_registros_cnh, gerar_pdf_categoria, gerar_relatorios_cnh
from funcoes_colaboradores import DB_PATH, obter_colaboradores, get_documentos_a_vencer

class PDFRelatorio(FPDF):
    def __init__(self, orientation='P', unit='mm', format='A4', titulo='Relatório'):
        super().__init__(orientation, unit, format)
        self.titulo = titulo
        self._table_context = None
        # Habilita a quebra de página automática com uma margem inferior de 2cm
        self.set_auto_page_break(auto=True, margin=20)

    def set_table_context(self, col_widths, header, section_title=None, header_font_size=10):
        self._table_context = {
            "col_widths": list(col_widths),
            "header": [str(value) for value in header],
            "section_title": str(section_title) if section_title else None,
            "header_font_size": header_font_size,
        }

    def clear_table_context(self):
        self._table_context = None

    def _draw_table_context(self):
        context = self._table_context
        if not context:
            return
        if context["section_title"]:
            self.set_font('Arial', 'B', 12)
            self.set_x(self.l_margin)
            self.multi_cell(0, 7, context["section_title"], border=0, align='L')
        self.set_font('Arial', 'B', context["header_font_size"])
        self.set_x(self.l_margin)
        for width, value in zip(context["col_widths"], context["header"]):
            self.cell(width, 8, value, 1, 0, 'C')
        self.ln(8)

    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, self.titulo, 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
        self.cell(0, 10, f'Gerado em: {data_geracao}', 0, 1, 'C')
        self.ln(5)
        self._draw_table_context()

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')


class TabRelatorios(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("📄 Relatórios Prontos")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)

        group_cnh = QtWidgets.QGroupBox("Relatórios de CNH por Frente")
        cnh_layout = QtWidgets.QGridLayout(group_cnh)

        self.spin_dias_alerta_cnh = QtWidgets.QSpinBox()
        self.spin_dias_alerta_cnh.setRange(1, 365)
        self.spin_dias_alerta_cnh.setValue(30)
        self.check_incluir_sem_escala_cnh = QtWidgets.QCheckBox("Incluir colaboradores sem escala")

        cnh_layout.addWidget(QtWidgets.QLabel("Janela de alerta (dias):"), 0, 0)
        cnh_layout.addWidget(self.spin_dias_alerta_cnh, 0, 1)
        cnh_layout.addWidget(self.check_incluir_sem_escala_cnh, 0, 2, 1, 2)

        btn_cnh = QtWidgets.QPushButton("CNHs Vencidas por Frente")
        btn_cnh.clicked.connect(self._gerar_notificacao_cnh_vencida)
        cnh_layout.addWidget(btn_cnh, 1, 0, 1, 2)

        btn_cnh_vencer = QtWidgets.QPushButton("CNHs a Vencer por Frente")
        btn_cnh_vencer.clicked.connect(self._gerar_relatorio_cnh_a_vencer)
        cnh_layout.addWidget(btn_cnh_vencer, 1, 2, 1, 2)

        btn_cnh_validas = QtWidgets.QPushButton("CNHs Válidas por Frente")
        btn_cnh_validas.clicked.connect(self._gerar_relatorio_cnh_validas)
        cnh_layout.addWidget(btn_cnh_validas, 2, 0, 1, 2)

        btn_pacote_cnh = QtWidgets.QPushButton("Pacote Completo de CNH")
        btn_pacote_cnh.clicked.connect(self._gerar_pacote_relatorios_cnh)
        cnh_layout.addWidget(btn_pacote_cnh, 2, 2, 1, 2)

        group = QtWidgets.QGroupBox("Outros Relatórios")
        vbox = QtWidgets.QVBoxLayout(group)

        btn_ativos = QtWidgets.QPushButton("Colaboradores Ativos")
        btn_ativos.clicked.connect(self._gerar_relatorio_ativos)
        vbox.addWidget(btn_ativos)

        btn_frente = QtWidgets.QPushButton("Colaboradores por Frente e Turno")
        btn_frente.clicked.connect(self._gerar_relatorio_por_frente)
        vbox.addWidget(btn_frente)

        btn_sem_cnh = QtWidgets.QPushButton("Colaboradores Sem CNH ou Categoria")
        btn_sem_cnh.clicked.connect(self._gerar_relatorio_sem_cnh)
        vbox.addWidget(btn_sem_cnh)

        btn_docs_vencer = QtWidgets.QPushButton("Documentos a Vencer em 30 Dias")
        btn_docs_vencer.clicked.connect(self._gerar_relatorio_docs_a_vencer)
        vbox.addWidget(btn_docs_vencer)

        group_operacao = QtWidgets.QGroupBox("Operação de CNH")
        oper_layout = QtWidgets.QVBoxLayout(group_operacao)

        btn_cobranca_excel = QtWidgets.QPushButton("Lista de Cobrança CNH (Excel)")
        btn_cobranca_excel.clicked.connect(self._exportar_lista_cobranca_cnh)
        oper_layout.addWidget(btn_cobranca_excel)

        btn_painel_excel = QtWidgets.QPushButton("Painel Operacional CNH (Excel)")
        btn_painel_excel.clicked.connect(self._exportar_painel_operacional_cnh)
        oper_layout.addWidget(btn_painel_excel)

        btn_gestor_pdf = QtWidgets.QPushButton("Pendências de CNH por Gestor (PDF)")
        btn_gestor_pdf.clicked.connect(self._gerar_relatorio_pendencias_por_gestor)
        oper_layout.addWidget(btn_gestor_pdf)

        scroll_layout.addWidget(group_cnh)
        scroll_layout.addWidget(group)
        scroll_layout.addWidget(group_operacao)
        scroll_layout.addStretch()

        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

    # <<< INÍCIO DA ALTERAÇÃO FINAL: Função compatível com versões antigas do FPDF >>>
    def _draw_multi_line_row(self, pdf, col_widths, data_row, line_height=6):
        """
        Desenha uma linha na tabela com quebra de linha automática e altura de linha sincronizada,
        evitando que a linha seja cortada entre as páginas.
        """
        cell_padding = 1

        # 1. Calcula a altura máxima que a linha ocupará
        num_lines_per_cell = []
        for i, txt in enumerate(data_row):
            inner_width = max(col_widths[i] - (2 * cell_padding), 1)
            lines = pdf.multi_cell(inner_width, line_height, str(txt), split_only=True)
            num_lines_per_cell.append(max(1, len(lines)))

        max_lines = max(num_lines_per_cell) if num_lines_per_cell else 1
        row_height = (max_lines * line_height) + (2 * cell_padding)

        # 2. Verifica se a altura da linha cabe no espaço restante da página
        space_left = pdf.h - pdf.get_y() - pdf.b_margin
        if row_height > space_left:
            pdf.add_page()

        # 3. Desenha a linha, gerenciando a posição de cada célula manualmente
        y_start_of_row = pdf.get_y()
        x_start_of_row = pdf.get_x()

        for i, txt in enumerate(data_row):
            # Calcula a posição X da célula atual
            current_x = x_start_of_row + sum(col_widths[:i])
            pdf.rect(current_x, y_start_of_row, col_widths[i], row_height)
            pdf.set_xy(current_x + cell_padding, y_start_of_row + cell_padding)
            pdf.multi_cell(
                max(col_widths[i] - (2 * cell_padding), 1),
                line_height,
                str(txt),
                border=0,
                align='L',
            )

        # Move o cursor para baixo da linha que acabamos de desenhar
        pdf.set_xy(x_start_of_row, y_start_of_row + row_height)
    # <<< FIM DA ALTERAÇÃO FINAL >>>

    def _dias_alerta_cnh(self):
        return self.spin_dias_alerta_cnh.value()

    def _subtitulo_relatorio_cnh(self):
        escopo = "incluindo sem escala" if self.check_incluir_sem_escala_cnh.isChecked() else "somente com frente de safra"
        return f"Janela de alerta: {self._dias_alerta_cnh()} dia(s) | {escopo}"

    def _carregar_dados_relatorio_cnh(self):
        return carregar_registros_cnh(
            DB_PATH,
            dias_alerta=self._dias_alerta_cnh(),
            incluir_sem_escala=self.check_incluir_sem_escala_cnh.isChecked(),
        )

    def _gerar_relatorio_categoria_cnh(self, categoria, titulo, nome_padrao, mensagem_vazia):
        dados = self._carregar_dados_relatorio_cnh()
        itens = dados["categorias"][categoria]
        if not itens:
            QtWidgets.QMessageBox.information(self, "Relatório", mensagem_vazia)
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar PDF", nome_padrao, "Arquivos PDF (*.pdf)")
        if not caminho:
            return

        gerar_pdf_categoria(itens, caminho, titulo, self._subtitulo_relatorio_cnh())
        QtWidgets.QMessageBox.information(
            self,
            "Sucesso",
            f"Relatório salvo com sucesso em:\n{caminho}\n\nTotal de colaboradores: {len(itens)}",
        )

    def _gerar_notificacao_cnh_vencida(self):
        self._gerar_relatorio_categoria_cnh(
            categoria="vencidas",
            titulo="CNHs Vencidas por Frente",
            nome_padrao="cnhs_vencidas_por_frente.pdf",
            mensagem_vazia="Nenhuma CNH vencida foi encontrada para o filtro atual.",
        )

    def _gerar_relatorio_cnh_a_vencer(self):
        self._gerar_relatorio_categoria_cnh(
            categoria="a_vencer",
            titulo=f"CNHs a Vencer em até {self._dias_alerta_cnh()} dias por Frente",
            nome_padrao=f"cnhs_a_vencer_{self._dias_alerta_cnh()}_dias_por_frente.pdf",
            mensagem_vazia=f"Nenhuma CNH a vencer nos próximos {self._dias_alerta_cnh()} dias foi encontrada para o filtro atual.",
        )

    def _gerar_relatorio_cnh_validas(self):
        self._gerar_relatorio_categoria_cnh(
            categoria="validas",
            titulo="CNHs Válidas por Frente",
            nome_padrao="cnhs_validas_por_frente.pdf",
            mensagem_vazia="Nenhuma CNH válida foi encontrada para o filtro atual.",
        )

    def _gerar_pacote_relatorios_cnh(self):
        pasta = QtWidgets.QFileDialog.getExistingDirectory(self, "Escolher pasta de saída")
        if not pasta:
            return

        resultado = gerar_relatorios_cnh(
            db_path=DB_PATH,
            pasta_saida=pasta,
            dias_alerta=self._dias_alerta_cnh(),
            incluir_sem_escala=self.check_incluir_sem_escala_cnh.isChecked(),
        )

        arquivos = [caminho for caminho in resultado["arquivos"].values() if caminho]
        if not arquivos:
            QtWidgets.QMessageBox.information(self, "Relatórios CNH", "Nenhum PDF foi gerado para o filtro atual.")
            return

        linhas = [
            f"Relatórios gerados em:\n{pasta}",
            "",
            f"CNHs vencidas: {resultado['categorias']['vencidas']}",
            f"CNHs a vencer em {self._dias_alerta_cnh()} dias: {resultado['categorias']['a_vencer']}",
            f"CNHs válidas: {resultado['categorias']['validas']}",
            f"Sem escala ignorados: {resultado['resumo']['sem_escala_ignorados']}",
        ]
        QtWidgets.QMessageBox.information(self, "Sucesso", "\n".join(linhas))

    def _gerar_relatorio_ativos(self):
        colaboradores = obter_colaboradores(filtro_situacao="ATIVO")
        if not colaboradores:
            QtWidgets.QMessageBox.information(self, "Relatório", "Nenhum colaborador ATIVO encontrado.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar PDF", "colaboradores_ativos.pdf", "Arquivos PDF (*.pdf)")
        if not caminho:
            return

        pdf = PDFRelatorio(titulo="Colaboradores Ativos")

        col_widths = [60, 30, 40, 30, 30]
        line_height = 6
        header = ["Nome", "Código", "Função", "Turno", "Frente"]

        pdf.set_table_context(col_widths, header)
        pdf.add_page()

        pdf.set_font('Arial', '', 9)
        for c in colaboradores:
            nome = c.get('nome', '').encode('latin-1', 'replace').decode('latin-1')
            codigo = str(c.get('codigo_colaborador', ''))
            funcao = str(c.get('funcao_safra', ''))
            turno = str(c.get('turno_safra', ''))
            frente = str(c.get('frente_safra', ''))

            data_row = [nome, codigo, funcao, turno, frente]
            self._draw_multi_line_row(pdf, col_widths, data_row, line_height)

        pdf.output(caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Relatório salvo com sucesso em:\n{caminho}")

    def _gerar_relatorio_por_frente(self):
        colaboradores = obter_colaboradores()
        if not colaboradores:
            QtWidgets.QMessageBox.information(self, "Relatório", "Nenhum colaborador encontrado.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar PDF", "colaboradores_por_frente.pdf", "Arquivos PDF (*.pdf)")
        if not caminho:
            return

        pdf = PDFRelatorio(titulo="Colaboradores por Frente")
        grupos = {}
        for c in colaboradores:
            chave = f"{c.get('frente_safra') or 'Sem Frente'} - {c.get('turno_safra') or 'Sem Turno'}"
            grupos.setdefault(chave, []).append(c)

        col_widths = [80, 30, 40, 30]
        line_height = 6
        header = ["Nome", "Código", "Função", "Horário"]

        for grupo, lista in sorted(grupos.items()):
            pdf.set_table_context(col_widths, header, section_title=grupo)
            pdf.add_page()

            pdf.set_font('Arial', '', 9)
            for c in lista:
                nome = c.get('nome', '').encode('latin-1', 'replace').decode('latin-1')
                codigo = str(c.get('codigo_colaborador', ''))
                funcao = str(c.get('funcao_safra', ''))
                horario = str(c.get('horario', ''))

                data_row = [nome, codigo, funcao, horario]
                self._draw_multi_line_row(pdf, col_widths, data_row, line_height)

        pdf.output(caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Relatório salvo com sucesso em:\n{caminho}")

    def _gerar_relatorio_sem_cnh(self):
        colaboradores = [c for c in obter_colaboradores() if not c.get('validade_cnh') or not c.get('categoria_cnh')]
        if not colaboradores:
            QtWidgets.QMessageBox.information(self, "Relatório", "Nenhum colaborador sem CNH ou categoria encontrado.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar PDF", "colaboradores_sem_cnh.pdf", "Arquivos PDF (*.pdf)")
        if not caminho:
            return

        pdf = PDFRelatorio(titulo="Colaboradores Sem CNH ou Categoria")

        col_widths = [60, 30, 40, 30, 30]
        line_height = 6
        header = ["Nome", "Código", "Função", "Turno", "Frente"]

        pdf.set_table_context(col_widths, header)
        pdf.add_page()

        pdf.set_font('Arial', '', 9)
        for c in colaboradores:
            nome = c.get('nome', '').encode('latin-1', 'replace').decode('latin-1')
            codigo = str(c.get('codigo_colaborador', ''))
            funcao = str(c.get('funcao_safra', ''))
            turno = str(c.get('turno_safra', ''))
            frente = str(c.get('frente_safra', ''))

            data_row = [nome, codigo, funcao, turno, frente]
            self._draw_multi_line_row(pdf, col_widths, data_row, line_height)

        pdf.output(caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Relatório salvo com sucesso em:\n{caminho}")

    def _gerar_relatorio_docs_a_vencer(self):
        documentos = get_documentos_a_vencer(dias=30)
        if not documentos:
            QtWidgets.QMessageBox.information(self, "Relatório", "Nenhum documento a vencer nos próximos 30 dias encontrado.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar PDF", "documentos_a_vencer.pdf", "Arquivos PDF (*.pdf)")
        if not caminho:
            return

        pdf = PDFRelatorio(titulo="Documentos a Vencer em até 30 dias")

        col_widths = [60, 30, 60, 30]
        line_height = 6
        header = ["Nome", "Código", "Documento", "Validade"]

        pdf.set_table_context(col_widths, header)
        pdf.add_page()

        pdf.set_font('Arial', '', 9)
        for doc in documentos:
            nome = doc.get('nome_colaborador', '').encode('latin-1', 'replace').decode('latin-1')
            codigo = str(doc.get('codigo_colaborador', ''))
            nome_doc = doc.get('nome_documento', '-')
            validade = doc.get('data_validade', '-')

            data_row = [nome, codigo, nome_doc, validade]
            self._draw_multi_line_row(pdf, col_widths, data_row, line_height)

        pdf.output(caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Relatório salvo com sucesso em:\n{caminho}")

    def _exportar_lista_cobranca_cnh(self):
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar lista de cobrança",
            "lista_cobranca_cnh.xlsx",
            "Arquivos Excel (*.xlsx)",
        )
        if not caminho:
            return

        total = exportar_lista_cobranca_excel(DB_PATH, caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Lista de cobrança exportada com {total} registro(s).")

    def _exportar_painel_operacional_cnh(self):
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar painel operacional",
            "painel_operacional_cnh.xlsx",
            "Arquivos Excel (*.xlsx)",
        )
        if not caminho:
            return

        total = exportar_painel_cnh_excel(DB_PATH, caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Painel operacional exportado com {total} registro(s).")

    def _gerar_relatorio_pendencias_por_gestor(self):
        grupos = agrupar_pendencias_por_gestor(DB_PATH)
        if not grupos:
            QtWidgets.QMessageBox.information(self, "Relatório", "Nenhuma pendência de CNH foi encontrada.")
            return

        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Salvar relatório",
            "pendencias_cnh_por_gestor.pdf",
            "Arquivos PDF (*.pdf)",
        )
        if not caminho:
            return

        pdf = PDFRelatorio(titulo="Pendências de CNH por Gestor")
        col_widths = [50, 22, 27, 36, 28, 27]
        header = ["Nome", "Código", "Validade", "Status", "Frente", "Telefone"]

        for gestor, itens in grupos.items():
            pdf.set_table_context(
                col_widths,
                header,
                section_title=f"Gestor: {gestor} ({len(itens)} pendência(s))",
                header_font_size=9,
            )
            pdf.add_page()

            pdf.set_font('Arial', '', 8)
            for item in itens:
                data_row = [
                    item.get('nome', '').encode('latin-1', 'replace').decode('latin-1'),
                    str(item.get('codigo_colaborador', '')),
                    item.get('validade_cnh_formatada', '-'),
                    item.get('status_tecnico_label', ''),
                    item.get('frente_exibicao', ''),
                    str(item.get('telefone', '')),
                ]
                self._draw_multi_line_row(pdf, col_widths, data_row, 6)

        pdf.output(caminho)
        QtWidgets.QMessageBox.information(self, "Sucesso", f"Relatório salvo com sucesso em:\n{caminho}")
