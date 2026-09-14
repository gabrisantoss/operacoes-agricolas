from __future__ import annotations

from .base import PDFRelatorio, RelatorioFormatacaoMixin


class RelatorioPdfFazendasMudaBuilder(RelatorioFormatacaoMixin):
    def criar_pdf_fazendas_muda(self, d_ini, d_fim, dados):
        if not dados:
            return None

        primeira_data = dados["metricas"]["primeira_data_registrada"]
        ultima_data = dados["metricas"]["ultima_data_registrada"]
        periodo_real = f"{primeira_data.strftime('%d/%m/%Y')} a {ultima_data.strftime('%d/%m/%Y')}"

        pdf = PDFRelatorio(
            titulo="RELATORIO HISTORICO DE FAZENDAS DE MUDA",
            periodo=periodo_real,
            total_viagens=None,
        )
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.section_title(
            "Fazendas de Muda",
            "Lista historica com a primeira data de corte e o ultimo registro de cada fazenda, ordenada por inicio e fechamento do historico.",
        )
        self._desenhar_tabela_pdf_fazendas_muda(pdf, dados["fazendas"])

        return pdf

    def _desenhar_cabecalho_tabela_pdf_fazendas_muda(self, pdf):
        pdf.draw_table_header(
            [
                (30, "CODIGO", "C"),
                (94, "FAZENDA DE MUDA", "L"),
                (33, "INICIO CORTE", "C"),
                (33, "ULT. REGISTRO", "C"),
            ]
        )

    def _desenhar_tabela_pdf_fazendas_muda(self, pdf, fazendas):
        self._desenhar_cabecalho_tabela_pdf_fazendas_muda(pdf)

        fill = False
        for item in fazendas:
            if pdf.get_y() + 6 > pdf.page_break_trigger:
                pdf.add_page()
                self._desenhar_cabecalho_tabela_pdf_fazendas_muda(pdf)

            if fill:
                pdf.set_fill_color(248, 250, 252)
            else:
                pdf.set_fill_color(255, 255, 255)

            y = pdf.get_y()
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(
                30,
                6,
                self._latin1_safe(self._formatar_codigo_relatorio(item["codigo"])),
                0,
                0,
                "C",
                fill,
            )
            pdf.cell(
                94,
                6,
                self._latin1_safe(self._resumir_texto(item["nome"], 52)),
                0,
                0,
                "L",
                fill,
            )
            pdf.cell(
                33,
                6,
                item["primeira_data"].strftime("%d/%m/%Y"),
                0,
                0,
                "C",
                fill,
            )
            pdf.cell(
                33,
                6,
                item["ultima_data"].strftime("%d/%m/%Y"),
                0,
                1,
                "C",
                fill,
            )
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + 6, 200, y + 6)
            fill = not fill
