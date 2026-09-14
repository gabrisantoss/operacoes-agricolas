from __future__ import annotations

from .base import PDFRelatorio, RelatorioFormatacaoMixin


class RelatorioPdfDiarioBuilder(RelatorioFormatacaoMixin):
    def criar_pdf_resumo_diario(self, dados):
        if not dados:
            return None

        periodo = self._periodo_diario(dados["linhas"])
        pdf = PDFRelatorio(
            titulo="RELATORIO DIARIO DE PLANTIO",
            periodo=periodo,
            total_viagens=dados["total_geral"],
        )
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        self._desenhar_resumo_diario(pdf, dados["linhas"], dados["total_geral"])
        return pdf

    def _periodo_diario(self, linhas):
        datas = [self._texto_relatorio(item.get("data")) for item in linhas if self._texto_relatorio(item.get("data"))]
        if not datas:
            return ""
        if datas[0] == datas[-1]:
            return datas[0]
        return f"{datas[0]} a {datas[-1]}"

    def _desenhar_faixa_data(self, pdf, data_referencia, continuidade=False):
        pdf.set_fill_color(*pdf.COLOR_SLATE)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        titulo = f"DATA: {data_referencia}"
        if continuidade:
            titulo += " (CONT.)"
        pdf.cell(190, 7, self._latin1_safe(titulo), ln=1, fill=True)

    def _desenhar_cabecalho_tabela(self, pdf):
        pdf.draw_table_header(
            [
                (118, "FAZENDA", "L"),
                (52, "VARIEDADE", "L"),
                (20, "VIAGENS", "R"),
            ]
        )

    def _desenhar_panorama_diario(self, pdf, linhas, total_geral):
        dias_ativos = len({self._texto_relatorio(item["data"], "-") for item in linhas})
        fazendas_ativas = len({self._texto_relatorio(item["fazenda"], "-") for item in linhas})
        resumo = (
            f"{self._fmt_int(total_geral)} viagens registradas em "
            f"{self._fmt_int(dias_ativos)} dias com movimento, cobrindo "
            f"{self._fmt_int(fazendas_ativas)} fazendas de plantio."
        )

        y = pdf.get_y()
        pdf.set_fill_color(247, 247, 252)
        pdf.rect(10, y, 190, 12, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.rect(10, y, 3, 12, "F")

        pdf.set_xy(18, y + 1.6)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(178, 3.2, "PANORAMA OPERACIONAL", 0, 1)

        pdf.set_x(18)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(178, 4, self._latin1_safe(self._resumir_texto(resumo, 116)), 0, 0)
        pdf.set_y(y + 15)

    def _desenhar_resumo_diario(self, pdf, linhas, total_geral):
        pdf.section_title(
            "Resumo Diario",
            "Movimento por dia, fazenda de plantio e variedade.",
        )
        self._desenhar_panorama_diario(pdf, linhas, total_geral)

        data_atual = None

        def redraw_contexto():
            pdf.section_title(
                "Resumo Diario",
                "Continuidade do movimento diario.",
            )
            if data_atual is not None:
                self._desenhar_faixa_data(pdf, data_atual, continuidade=True)
                self._desenhar_cabecalho_tabela(pdf)

        fill = False
        for item in linhas:
            data_item = self._texto_relatorio(item["data"], "-")
            if data_item != data_atual:
                pdf.ensure_space(14, lambda: pdf.section_title("Resumo Diario", "Continuidade do movimento diario."))
                data_atual = data_item
                self._desenhar_faixa_data(pdf, data_atual)
                self._desenhar_cabecalho_tabela(pdf)
                fill = False

            pdf.ensure_space(6, redraw_contexto)

            if fill:
                pdf.set_fill_color(248, 250, 252)
            else:
                pdf.set_fill_color(255, 255, 255)

            y = pdf.get_y()
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(118, 6, self._latin1_safe(self._resumir_texto(item["fazenda"], 68)), 0, 0, "L", fill)
            pdf.cell(52, 6, self._latin1_safe(self._resumir_texto(item["variedade"], 28)), 0, 0, "L", fill)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(20, 6, self._fmt_int(item["qtd"]), 0, 1, "R", fill)
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + 6, 200, y + 6)
            fill = not fill

        pdf.ln(4)
        pdf.ensure_space(10)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*pdf.COLOR_PRIMARY)
        pdf.cell(190, 8, self._latin1_safe(f"TOTAL DO PERIODO: {self._fmt_int(total_geral)}"), 0, 1, "R")
