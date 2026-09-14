from __future__ import annotations

from .base import PDFRelatorio, RelatorioFormatacaoMixin


class PDFRelatorioFechamento(PDFRelatorio):
    COLOR_PRIMARY = (76, 70, 170)
    COLOR_PRIMARY_DARK = (55, 49, 132)
    COLOR_INK = (18, 24, 33)
    COLOR_MUTED = (73, 80, 87)
    COLOR_BORDER = (225, 229, 235)
    COLOR_SOFT = (249, 250, 251)

    DEFAULT_LOGO_CANDIDATES = (
        "assets/logo_Operacoes Agricolas_pdf.svg",
        "assets/logo_Operacoes Agricolas_pdf.png",
        "assets/logo_Operacoes Agricolas_pdf_white.svg",
        "assets/logo_Operacoes Agricolas_pdf_white.png",
        "assets/logo.png",
    )

    def __init__(self, titulo, safra, total_viagens, logo_path=None):
        super().__init__(titulo, "", total_viagens, logo_path=logo_path)
        self.safra = safra
        self.modo_capa = False
        self.paginas_sem_rodape = set()
        self.set_margins(10, 24, 10)
        self.set_line_width(0.25)

    def header(self):
        if self.modo_capa:
            return

        self.set_fill_color(255, 255, 255)
        self.rect(0, 0, 210, 28, "F")
        self.set_fill_color(*self.COLOR_PRIMARY)
        self.rect(0, 0, 210, 2.2, "F")

        if self.logo_path:
            try:
                self.image(self.logo_path, x=176, y=5.2, w=22)
            except Exception:
                pass

        self.set_xy(10, 6.2)
        self.set_text_color(*self.COLOR_INK)
        self.set_font("Helvetica", "B", 9.5)
        self.cell(130, 4.8, self._safe(self.titulo), 0, 1)

        self.set_x(10)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*self.COLOR_MUTED)
        self.cell(
            130,
            4.2,
            self._safe(f"Safra {self.safra} | Total: {self.total_viagens} viagens"),
            0,
            1,
        )

        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, 25.8, 200, 25.8)
        self.set_y(32)

    def footer(self):
        if self.page_no() in self.paginas_sem_rodape:
            return

        self.set_y(-14)
        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, self.h - 14.5, 200, self.h - 14.5)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(90, 98, 108)
        self.cell(190, 8, self._safe(f"Pagina {self.page_no()}/{{nb}}"), 0, 0, "R")

    def draw_table_header(self, columns, row_height=6.6, accent=None, fill=None):
        x, y = self.get_x(), self.get_y()
        total_w = sum(width for width, *_ in columns)
        self.set_fill_color(*(fill or self.COLOR_PRIMARY))
        self.rect(x, y, total_w, row_height, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 8.2)
        for idx, (width, label, align) in enumerate(columns):
            self.cell(width, row_height, self._safe(label), 0, 1 if idx == len(columns) - 1 else 0, align, False)
        self.set_draw_color(*(accent or self.COLOR_PRIMARY_DARK))
        self.line(x, y + row_height, x + total_w, y + row_height)

    def section_title(self, titulo, subtitulo=""):
        self.ensure_space(16 if subtitulo else 11)
        y = self.get_y()
        self.set_fill_color(*self.COLOR_PRIMARY)
        self.rect(10, y + 1.2, 2.4, 9.4 if subtitulo else 6.6, "F")
        self.set_xy(15, y)
        self.set_text_color(*self.COLOR_INK)
        self.set_font("Helvetica", "B", 13.5)
        self.cell(185, 6.2, self._safe(titulo), 0, 1)
        if subtitulo:
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*self.COLOR_MUTED)
            self.set_x(15)
            self.multi_cell(185, 4.5, self._safe(subtitulo), 0)
        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, self.get_y() + 1, 200, self.get_y() + 1)
        self.ln(4)


class RelatorioPdfFechamentoBuilder(RelatorioFormatacaoMixin):
    def criar_pdf_fechamento_safra(self, d_ini, d_fim, dados):
        if not dados:
            return None

        safra = d_fim[:4]
        titulo = f"RELATORIO FINAL DO PLANTIO DE CANA - SAFRA {safra}"
        pdf = PDFRelatorioFechamento(
            titulo=titulo,
            safra=safra,
            total_viagens=self._fmt_int(dados["total_geral"]),
        )
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)

        pdf.modo_capa = True
        pdf.add_page()
        pdf.paginas_sem_rodape.add(pdf.page_no())
        self._desenhar_capa(pdf, d_ini, d_fim, dados)

        pdf.modo_capa = False
        pdf.add_page()
        self._desenhar_sumario(pdf)

        pdf.add_page()
        self._desenhar_resumo_executivo(pdf, dados)

        pdf.add_page()
        self._desenhar_ranking_mudas(pdf, dados["rankings"]["origens"])

        pdf.add_page()
        self._desenhar_ranking_destinos(pdf, dados["rankings"]["destinos"])

        pdf.add_page()
        self._desenhar_variedades(pdf, dados["rankings"]["variedades"])

        pdf.add_page()
        self._desenhar_equipe(pdf, dados["rankings"]["motoristas"], dados["rankings"]["operadores"])

        pdf.add_page()
        self._desenhar_fluxos(pdf, dados["fluxos"])

        return pdf

    def _fmt_data(self, data):
        return data.strftime("%d/%m/%Y")

    def _desenhar_capa(self, pdf, d_ini, d_fim, dados):
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(0, 0, 210, 297, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.rect(0, 0, 210, 10, "F")
        pdf.rect(0, 286, 210, 11, "F")
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(28, 101, 182, 101)
        pdf.line(54, 185, 156, 185)

        if pdf.logo_path:
            try:
                pdf.image(pdf.logo_path, x=58, y=32, w=94)
            except Exception:
                pass

        pdf.set_xy(18, 116)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.set_font("Helvetica", "B", 24)
        pdf.cell(174, 10, "RELATORIO FINAL", 0, 1, "C")
        pdf.set_x(18)
        pdf.set_font("Helvetica", "B", 17)
        pdf.cell(174, 8, f"PLANTIO DE CANA - SAFRA {d_fim[:4]}", 0, 1, "C")

        y = 154
        self._desenhar_card_capa(pdf, 55, y, 100, 28, "Total de viagens", self._fmt_int(dados["total_geral"]))

    def _desenhar_card_capa(self, pdf, x, y, w, h, titulo, valor):
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(x + 12, y, x + w - 12, y)
        pdf.line(x + 12, y + h, x + w - 12, y + h)
        pdf.set_xy(x + 3, y + 5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*pdf.COLOR_MUTED)
        pdf.cell(w - 6, 4, self._latin1_safe(titulo.upper()), 0, 2, "C")
        pdf.set_x(x + 3)
        pdf.set_font("Helvetica", "B", 32)
        pdf.set_text_color(*pdf.COLOR_PRIMARY)
        pdf.cell(w - 6, 13, self._latin1_safe(valor), 0, 0, "C")

    def _desenhar_sumario(self, pdf):
        pdf.section_title("Sumario", "Estrutura do fechamento operacional de plantio.")
        itens = [
            ("1", "Resumo Executivo", "Indicadores gerais e principais destaques da safra."),
            ("2", "Ranking de Fazendas de Muda", "Origens com maior volume de viagens e intervalo operacional."),
            ("3", "Ranking de Fazendas de Plantio", "Destinos que mais receberam mudas na safra."),
            ("4", "Variedades Plantadas", "Participacao de cada variedade no volume total."),
            ("5", "Equipe", "Top 10 motoristas e maquinistas por quantidade de viagens."),
            ("6", "Fluxos de Muda para Plantio", "Fazendas de muda agrupadas com seus destinos de plantio."),
        ]

        primeiro_y = pdf.get_y() + 3
        ultimo_y = primeiro_y + (len(itens) - 1) * 18 + 6
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(17, primeiro_y, 17, ultimo_y)

        for numero, titulo, descricao in itens:
            y = pdf.get_y()
            pdf.set_fill_color(*pdf.COLOR_PRIMARY)
            pdf.ellipse(13.5, y + 2.5, 7, 7, "F")
            pdf.set_xy(13.5, y + 3.8)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(7, 4.2, numero, 0, 0, "C")
            pdf.set_xy(27, y + 1.5)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(*pdf.COLOR_INK)
            pdf.cell(160, 4.5, self._latin1_safe(titulo), 0, 1)
            pdf.set_x(27)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*pdf.COLOR_MUTED)
            pdf.cell(160, 4.5, self._latin1_safe(descricao), 0, 1)
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(27, y + 14, 200, y + 14)
            pdf.set_y(y + 18)

    def _desenhar_resumo_executivo(self, pdf, dados):
        pdf.section_title(
            "Resumo Executivo",
            "Fechamento consolidado do plantio de cana com base nas notas lancadas na safra.",
        )

        metricas = [
            ("Viagens", self._fmt_int(dados["total_geral"])),
            ("Inicio", self._fmt_data(dados["periodo"]["primeira_data"])),
            ("Ultimo registro", self._fmt_data(dados["periodo"]["ultima_data"])),
            ("Origens", self._fmt_int(dados["metricas"]["origens_ativas"])),
            ("Destinos", self._fmt_int(dados["metricas"]["destinos_ativos"])),
            ("Variedades", self._fmt_int(dados["metricas"]["variedades_ativas"])),
        ]
        base_y = pdf.get_y()
        for idx, (titulo, valor) in enumerate(metricas):
            x = 10 + (idx % 3) * 64
            y = base_y + (idx // 3) * 22
            self._desenhar_card_resumo(pdf, x, y, 58, 16, titulo, valor)
        pdf.set_y(base_y + 48)

        destaques = dados.get("destaques", {})
        linhas = [
            ("Maior fazenda de muda", destaques.get("origem_top")),
            ("Maior fazenda de plantio", destaques.get("destino_top")),
            ("Variedade mais plantada", destaques.get("variedade_top")),
            ("Motorista com mais viagens", destaques.get("motorista_top")),
            ("Operador com mais viagens", destaques.get("operador_top")),
        ]
        pdf.section_title("Principais Destaques")
        for titulo, item in linhas:
            if not item:
                continue
            label = item.get("label") or item.get("nome") or "-"
            detalhe = f"{self._fmt_int(item['qtd'])} viagens"
            self._desenhar_linha_destaque(pdf, titulo, label, detalhe)

    def _desenhar_card_resumo(self, pdf, x, y, w, h, titulo, valor):
        pdf.set_fill_color(*pdf.COLOR_SOFT)
        pdf.rect(x, y, w, h, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.rect(x, y, 2.2, h, "F")
        pdf.set_xy(x + 3, y + 2.3)
        pdf.set_font("Helvetica", "", 7.8)
        pdf.set_text_color(*pdf.COLOR_MUTED)
        pdf.cell(w - 6, 3.5, self._latin1_safe(titulo.upper()), 0, 2)
        pdf.set_x(x + 3)
        pdf.set_font("Helvetica", "B", 11.5)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.cell(w - 6, 5.5, self._latin1_safe(valor), 0, 2)

    def _desenhar_linha_destaque(self, pdf, titulo, label, detalhe):
        pdf.ensure_space(9)
        y = pdf.get_y()
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(10, y + 8.6, 200, y + 8.6)
        pdf.set_xy(13, y + 1.7)
        pdf.set_font("Helvetica", "B", 8.3)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.cell(45, 4, self._latin1_safe(titulo), 0, 0)
        pdf.set_font("Helvetica", "", 8.3)
        pdf.cell(106, 4, self._latin1_safe(self._resumir_texto(label, 68)), 0, 0)
        pdf.set_font("Helvetica", "B", 8.3)
        pdf.set_text_color(*pdf.COLOR_PRIMARY)
        pdf.cell(32, 4, self._latin1_safe(detalhe), 0, 1, "R")
        pdf.set_y(y + 10)

    def _desenhar_ranking_mudas(self, pdf, itens):
        pdf.section_title(
            "Ranking de Fazendas de Muda",
            "Linha do tempo: primeiro corte no topo e ultimo registro de muda no final.",
        )
        colunas = [
            (10, "#", "C"),
            (23, "COD.", "C"),
            (83, "FAZENDA DE MUDA", "L"),
            (22, "VIAGENS", "R"),
            (26, "INICIO", "C"),
            (26, "ULT. REG.", "C"),
        ]
        self._desenhar_tabela_generica(pdf, itens, colunas, self._linha_muda)

    def _desenhar_ranking_destinos(self, pdf, itens):
        pdf.section_title(
            "Ranking de Fazendas de Plantio",
            "Linha do tempo: primeiro registro no topo e ultimo registro de plantio no final.",
        )
        colunas = [
            (10, "#", "C"),
            (23, "COD.", "C"),
            (83, "FAZENDA DE PLANTIO", "L"),
            (22, "VIAGENS", "R"),
            (26, "INICIO", "C"),
            (26, "ULT. REG.", "C"),
        ]
        self._desenhar_tabela_generica(pdf, itens, colunas, self._linha_destino)

    def _desenhar_variedades(self, pdf, itens):
        pdf.section_title(
            "Variedades Plantadas",
            "Volume consolidado de viagens por variedade.",
        )
        colunas = [
            (12, "#", "C"),
            (140, "VARIEDADE", "L"),
            (38, "VIAGENS", "R"),
        ]
        self._desenhar_tabela_generica(pdf, itens, colunas, self._linha_variedade)

    def _desenhar_tabela_generica(self, pdf, itens, colunas, montar_linha):
        pdf.draw_table_header(colunas)
        fill = False
        altura_linha = 6.6
        for idx, item in enumerate(itens, start=1):
            if pdf.get_y() + altura_linha > pdf.page_break_trigger:
                pdf.add_page()
                pdf.draw_table_header(colunas)
            y = pdf.get_y()
            if fill:
                pdf.set_fill_color(*pdf.COLOR_SOFT)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(*pdf.COLOR_INK)
            pdf.set_font("Helvetica", "", 8)
            for width, texto, align in montar_linha(idx, item):
                pdf.cell(width, altura_linha, self._latin1_safe(texto), 0, 0, align, fill)
            pdf.ln()
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + altura_linha, 200, y + altura_linha)
            fill = not fill

    def _linha_muda(self, idx, item):
        return [
            (10, str(idx), "C"),
            (23, self._formatar_codigo_relatorio(item["codigo"]), "C"),
            (83, self._resumir_texto(item["nome"], 50), "L"),
            (22, self._fmt_int(item["qtd"]), "R"),
            (26, self._fmt_data(item["primeira_data"]), "C"),
            (26, self._fmt_data(item["ultima_data"]), "C"),
        ]

    def _linha_destino(self, idx, item):
        return [
            (10, str(idx), "C"),
            (23, self._formatar_codigo_relatorio(item["codigo"]), "C"),
            (83, self._resumir_texto(item["nome"], 50), "L"),
            (22, self._fmt_int(item["qtd"]), "R"),
            (26, self._fmt_data(item["primeira_data"]), "C"),
            (26, self._fmt_data(item["ultima_data"]), "C"),
        ]

    def _linha_variedade(self, idx, item):
        return [
            (12, str(idx), "C"),
            (140, self._resumir_texto(item["nome"], 82), "L"),
            (38, self._fmt_int(item["qtd"]), "R"),
        ]

    def _desenhar_fluxos(self, pdf, fluxos):
        pdf.section_title(
            "Fluxos de Muda para Plantio",
            "Fazendas de muda agrupadas com os destinos de plantio logo abaixo.",
        )
        if not fluxos:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(190, 6, "Nenhum fluxo completo encontrado na safra.", 0, 1)
            return

        for indice, fluxo in enumerate(fluxos, start=1):
            if indice > 1:
                pdf.ensure_space(10, lambda: self._redesenhar_fluxos_pagina(pdf))
                pdf.ln(4)

            pdf.ensure_space(30, lambda: self._redesenhar_fluxos_pagina(pdf))
            self._desenhar_cabecalho_bloco_fluxo(pdf, indice, fluxo)
            self._desenhar_cabecalho_destinos_fluxo(pdf)

            fill = False
            for destino in fluxo["destinos"]:
                pdf.ensure_space(
                    7.2,
                    lambda indice=indice, fluxo=fluxo: self._redesenhar_fluxo_continuacao(pdf, indice, fluxo),
                )
                self._desenhar_linha_destino_fluxo(pdf, destino, fill)
                fill = not fill

    def _redesenhar_fluxos_pagina(self, pdf):
        pdf.section_title("Fluxos de Muda para Plantio", "Continuidade dos fluxos operacionais.")

    def _redesenhar_fluxo_continuacao(self, pdf, indice, fluxo):
        self._redesenhar_fluxos_pagina(pdf)
        self._desenhar_cabecalho_bloco_fluxo(pdf, indice, fluxo, continuidade=True)
        self._desenhar_cabecalho_destinos_fluxo(pdf)

    def _desenhar_variedade_marca_texto(self, pdf, x, y, variedade, max_w=36):
        label = "Variedade:"
        valor = pdf.fit_text_to_width(
            self._latin1_safe(self._texto_relatorio(variedade, "-")),
            max_w - 2,
        )

        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "", 8.4)
        pdf.set_text_color(*pdf.COLOR_MUTED)
        label_w = pdf.get_string_width(label) + 1.2
        pdf.cell(label_w, 4.3, label, 0, 0)

        valor_w = min(max_w, max(14, pdf.get_string_width(valor) + 2.6))
        marca_x = x + label_w + 0.5
        pdf.set_fill_color(255, 238, 128)
        pdf.rect(marca_x, y + 0.65, valor_w, 3.3, "F")

        pdf.set_xy(marca_x + 1.2, y)
        pdf.set_font("Helvetica", "B", 8.4)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.cell(valor_w - 1.8, 4.3, valor, 0, 0)
        return marca_x + valor_w

    def _desenhar_cabecalho_bloco_fluxo(self, pdf, indice, fluxo, continuidade=False):
        y = pdf.get_y()
        altura = 18.2
        pdf.set_fill_color(255, 248, 248)
        pdf.rect(10, y, 190, altura, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.rect(10, y, 3, altura, "F")
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(10, y + altura, 200, y + altura)

        codigo = self._formatar_codigo_relatorio(fluxo["codigo_origem"])
        nome = self._texto_relatorio(fluxo["nome_origem"], "NÃO INFORMADA")
        origem = f"{codigo} {nome}" if codigo != "-" else nome
        titulo = f"MUDA: {origem}"
        if continuidade:
            titulo = f"{titulo} (continua)"

        pdf.set_xy(16, y + 2.2)
        pdf.set_font("Helvetica", "B", 12.8)
        pdf.set_text_color(*pdf.COLOR_PRIMARY)
        pdf.cell(181, 5.3, pdf.fit_text_to_width(self._latin1_safe(titulo), 181), 0, 1)

        detalhe_y = y + 10.3
        fim_variedade_x = self._desenhar_variedade_marca_texto(
            pdf,
            16,
            detalhe_y,
            self._resumir_texto(fluxo["variedade"], 28),
        )

        datas_txt = f"Inicio: {self._fmt_data(fluxo['inicio'])}    Ult. reg.: {self._fmt_data(fluxo['fim'])}"
        datas_x = fim_variedade_x + 4
        datas_w = max(20, 132 - datas_x)
        pdf.set_xy(datas_x, detalhe_y)
        pdf.set_font("Helvetica", "", 8.4)
        pdf.set_text_color(*pdf.COLOR_MUTED)
        pdf.cell(datas_w, 4.3, pdf.fit_text_to_width(self._latin1_safe(datas_txt), datas_w), 0, 0)

        pdf.set_xy(135, detalhe_y)
        pdf.set_font("Helvetica", "B", 8.4)
        pdf.set_text_color(*pdf.COLOR_PRIMARY)
        total_txt = f"Total: {self._fmt_int(fluxo['total'])} viagens"
        pdf.cell(62, 4.3, self._latin1_safe(total_txt), 0, 1, "R")
        pdf.set_y(y + altura)

    def _desenhar_cabecalho_destinos_fluxo(self, pdf):
        pdf.draw_table_header(
            [
                (156, "DESTINO DE PLANTIO", "L"),
                (34, "VIAGENS", "R"),
            ]
        )

    def _desenhar_linha_destino_fluxo(self, pdf, destino, fill):
        altura_linha = 6.8
        y = pdf.get_y()
        pdf.set_fill_color(*pdf.COLOR_SOFT) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.set_font("Helvetica", "", 8)

        destino_label = self._label_origem_relatorio(destino["codigo"], destino["nome"])
        destino_txt = self._resumir_texto(destino_label, 88)

        pdf.cell(156, altura_linha, self._latin1_safe(destino_txt), 0, 0, "L", fill)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(34, altura_linha, self._fmt_int(destino["qtd"]), 0, 1, "R", fill)
        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.line(10, y + altura_linha, 200, y + altura_linha)

    def _desenhar_equipe(self, pdf, motoristas, operadores):
        pdf.section_title(
            "Equipe",
            "Top 10 motoristas e maquinistas por quantidade de viagens.",
        )
        self._desenhar_tabela_equipe(
            pdf,
            "Top 10 Motoristas",
            motoristas,
        )
        pdf.ln(6)
        self._desenhar_tabela_equipe(
            pdf,
            "Top 10 Maquinistas",
            operadores,
        )

    def _desenhar_tabela_equipe(self, pdf, titulo, itens):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*pdf.COLOR_INK)
        pdf.cell(190, 6, self._latin1_safe(titulo), 0, 1)
        colunas = [
            (12, "#", "C"),
            (148, "NOME", "L"),
            (30, "VIAGENS", "R"),
        ]
        pdf.draw_table_header(colunas)
        fill = False
        altura_linha = 6.6
        for idx, item in enumerate(itens, start=1):
            if pdf.get_y() + altura_linha > pdf.page_break_trigger:
                pdf.add_page()
                pdf.draw_table_header(colunas)
            y = pdf.get_y()
            pdf.set_fill_color(*pdf.COLOR_SOFT) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(*pdf.COLOR_INK)
            pdf.set_font("Helvetica", "", 8.2)
            pdf.cell(12, altura_linha, str(idx), 0, 0, "C", fill)
            pdf.cell(148, altura_linha, self._latin1_safe(self._resumir_texto(item["nome"], 88)), 0, 0, "L", fill)
            pdf.set_font("Helvetica", "B", 8.2)
            pdf.cell(30, altura_linha, self._fmt_int(item["qtd"]), 0, 1, "R", fill)
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + altura_linha, 200, y + altura_linha)
            fill = not fill
