from __future__ import annotations

from .base import PDFRelatorio, RelatorioFormatacaoMixin, formatar_periodo_br


class RelatorioPdfPlantioDetalhadoBuilder(RelatorioFormatacaoMixin):
    COLUNAS = (
        (20, "NOTA", "R"),
        (27, "COLHEITA", "C"),
        (27, "PLANTIO", "C"),
        (100, "PROPRIEDADE", "L"),
        (38, "TALHAO", "L"),
        (65, "VARIEDADE", "L"),
    )

    def criar_pdf_plantio_detalhado(self, d_ini, d_fim, dados):
        if not dados:
            return None

        pdf = PDFRelatorio(
            titulo="RELATORIO DETALHADO DE PLANTIO",
            periodo=formatar_periodo_br(d_ini, d_fim),
            total_viagens=dados["total_geral"],
            orientation="L",
        )
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        self._desenhar_resumo(pdf, dados)
        self._desenhar_tabela(pdf, dados["linhas"])
        return pdf

    def _desenhar_resumo(self, pdf, dados):
        pdf.section_title(
            "Visao geral",
            "Consolidado das notas no periodo selecionado, com rastreabilidade da colheita ao plantio.",
        )
        metricas = dados["metricas"]
        cards = (
            ("Notas", dados["total_geral"], "Registros no periodo", pdf.COLOR_PRIMARY),
            ("Propriedades", metricas["propriedades"], "Fazendas de plantio", pdf.COLOR_GREEN),
            ("Talhoes", metricas["talhoes"], "Talhoes identificados", pdf.COLOR_AMBER),
            ("Variedades", metricas["variedades"], "Variedades identificadas", (14, 165, 164)),
        )
        gap = 4
        card_width = (pdf.w - 20 - gap * 3) / 4
        y = pdf.get_y()
        for indice, (titulo, valor, subtitulo, cor) in enumerate(cards):
            x = 10 + indice * (card_width + gap)
            pdf.metric_card(x, y, card_width, 19, titulo, self._fmt_int(valor), subtitulo, cor)
        pdf.set_y(y + 24)

        if metricas["campos_pendentes"]:
            pdf.set_fill_color(255, 247, 237)
            pdf.set_text_color(154, 52, 18)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(
                pdf.w - 20,
                7,
                self._latin1_safe(
                    f"Atencao: {self._fmt_int(metricas['campos_pendentes'])} campo(s) sem informacao aparecem como '-'."
                ),
                0,
                1,
                "L",
                True,
            )
            pdf.ln(2)

    def _desenhar_cabecalho_tabela(self, pdf):
        pdf.draw_table_header(self.COLUNAS, row_height=7)

    def _desenhar_tabela(self, pdf, linhas):
        pdf.section_title(
            "Detalhamento das notas",
            "Datas de colheita e plantio, propriedade de destino, talhao e variedade.",
        )
        self._desenhar_cabecalho_tabela(pdf)

        def redesenhar_contexto():
            pdf.section_title("Detalhamento das notas", "Continuacao do periodo selecionado.")
            self._desenhar_cabecalho_tabela(pdf)

        fill = False
        for item in linhas:
            pdf.ensure_space(7, redesenhar_contexto)
            pdf.set_fill_color(*(248, 250, 252) if fill else (255, 255, 255))
            pdf.set_text_color(*pdf.COLOR_TEXT)
            pdf.set_font("Helvetica", "", 7.5)
            y = pdf.get_y()
            valores = (
                item["nota"],
                item["data_colheita"],
                item["data_plantio"],
                item["propriedade"],
                item["talhao"],
                item["variedade"],
            )
            for indice, ((largura, _titulo, alinhamento), valor) in enumerate(zip(self.COLUNAS, valores)):
                if indice == 0:
                    pdf.set_font("Helvetica", "B", 7.5)
                else:
                    pdf.set_font("Helvetica", "", 7.5)
                texto = pdf.fit_text_to_width(self._latin1_safe(valor), largura - 3)
                pdf.cell(largura, 7, texto, 0, 1 if indice == len(self.COLUNAS) - 1 else 0, alinhamento, True)
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + 7, pdf.w - 10, y + 7)
            fill = not fill
