from __future__ import annotations

from .base import PDFRelatorio, RelatorioFormatacaoMixin, formatar_periodo_br


class RelatorioPdfGeralBuilder(RelatorioFormatacaoMixin):
    def criar_pdf_geral_fazenda(self, d_ini, d_fim, dados):
        if not dados:
            return None

        pdf = PDFRelatorio(
            titulo="RELATORIO ANALITICO DE FLUXO",
            periodo=formatar_periodo_br(d_ini, d_fim),
            total_viagens=dados["total_geral"],
        )
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        self._desenhar_resumo_pdf_geral(pdf, dados)
        if dados.get("variedades") or dados.get("tops", {}).get("variedades"):
            pdf.add_page()
            self._desenhar_destaques_variedades_pdf_geral(pdf, dados)

        if dados["grupos"]:
            pdf.add_page()
            pdf.section_title(
                "Detalhamento por Origem e Variedade",
                "",
            )

            total_blocos = len(dados["grupos"])
            for indice, grupo in enumerate(dados["grupos"], start=1):
                altura_contexto = self._altura_contexto_bloco_pdf_geral(pdf, grupo)
                if pdf.get_y() + altura_contexto > pdf.page_break_trigger:
                    pdf.add_page()
                    pdf.section_title(
                        "Detalhamento por Origem e Variedade",
                        "Continuidade dos blocos validos de muda + variedade.",
                    )
                self._desenhar_bloco_pdf_geral(pdf, indice, total_blocos, grupo)

        self._desenhar_pendencias_pdf_geral(pdf, dados)

        return pdf

    def _desenhar_ranking_pdf(self, pdf, x, y, w, titulo, itens, total_geral):
        itens = itens[:5]
        alturas = [9 if item.get("subtitle") else 7 for item in itens] or [7]
        h = 12 + sum(alturas)

        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x, y, w, h, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.rect(x, y, w, 8, "F")
        pdf.set_fill_color(*pdf.COLOR_PRIMARY_DARK)
        pdf.rect(x, y, 3, 8, "F")

        pdf.set_xy(x + 3, y + 1.5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(w - 6, 5, self._latin1_safe(titulo), 0, 1)

        atual_y = y + 8
        if not itens:
            pdf.set_xy(x + 3, atual_y + 2)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(w - 6, 5, "Sem dados no periodo.", 0, 1)
            return h + 4

        for idx, item in enumerate(itens, start=1):
            altura_item = 9 if item.get("subtitle") else 7
            fill = idx % 2 == 0
            if fill:
                pdf.set_fill_color(248, 250, 252)
                pdf.rect(x + 1, atual_y, w - 2, altura_item, "F")

            percentual = (item["qtd"] / total_geral * 100) if total_geral else 0
            label = self._resumir_texto(item["label"], 32 if w < 100 else 54)
            subtitle_raw = item.get("subtitle")
            subtitle = self._resumir_texto(subtitle_raw, 32 if w < 100 else 54) if subtitle_raw else ""

            pdf.set_xy(x + 3, atual_y + 0.9)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(8, 4, f"{idx}.", 0, 0)

            pdf.set_font("Helvetica", "", 8)
            pdf.cell(w - 38, 4, self._latin1_safe(label), 0, 0)

            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(12, 4, self._fmt_int(item["qtd"]), 0, 0, "R")

            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(100, 116, 139)
            pdf.cell(12, 4, f"{percentual:.1f}%", 0, 0, "R")

            if subtitle:
                pdf.set_xy(x + 11, atual_y + 4.7)
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(w - 20, 3, self._latin1_safe(subtitle), 0, 0)

            atual_y += altura_item

        return h + 4


    def _accent_variedade_pdf_geral(self, indice):
        cores = [
            (22, 163, 74),
            (37, 99, 235),
            (217, 119, 6),
            (14, 165, 233),
            (79, 70, 229),
            (190, 24, 93),
        ]
        return cores[(indice - 1) % len(cores)]


    def _percentual_item_pdf_geral(self, item, total_geral):
        percentual = item.get("percentual")
        if percentual is not None:
            return float(percentual or 0)
        return (item["qtd"] / total_geral * 100) if total_geral else 0


    def _desenhar_card_variedade_pdf_geral(self, pdf, x, y, w, h, indice, item, total_geral, maior_qtd):
        accent = self._accent_variedade_pdf_geral(indice)
        qtd = int(item.get("qtd") or 0)
        percentual = self._percentual_item_pdf_geral(item, total_geral)
        proporcao = (qtd / maior_qtd) if maior_qtd else 0
        label = self._resumir_texto(item.get("label"), 50 if indice == 1 else 60)
        subtitle = self._resumir_texto(item.get("subtitle"), 72) if item.get("subtitle") else ""

        pdf.set_draw_color(*pdf.COLOR_BORDER)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x, y, w, h, "DF")
        pdf.set_fill_color(*accent)
        pdf.rect(x, y, 3, h, "F")

        if indice == 1:
            pdf.set_xy(x + 8, y + 4)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*accent)
            pdf.cell(96, 4, "01. VARIEDADE EM DESTAQUE", 0, 1)

            pdf.set_x(x + 8)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*pdf.COLOR_TEXT)
            pdf.cell(112, 6, self._latin1_safe(label), 0, 0)

            pdf.set_xy(x + w - 55, y + 6)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*pdf.COLOR_TEXT)
            pdf.cell(48, 6, self._fmt_int(qtd), 0, 2, "R")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*pdf.COLOR_MUTED)
            pdf.cell(48, 4, f"{percentual:.1f}% do total", 0, 2, "R")

            if subtitle:
                pdf.set_xy(x + 8, y + 16)
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*pdf.COLOR_MUTED)
                pdf.cell(112, 4, self._latin1_safe(subtitle), 0, 0)

            bar_x = x + 8
            bar_y = y + h - 8
            bar_w = w - 16
            bar_h = 3.2
        else:
            pdf.set_fill_color(*accent)
            pdf.rect(x + 7, y + 4.4, 9, 8, "F")
            pdf.set_xy(x + 7, y + 5.5)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(9, 4, f"{indice:02d}", 0, 0, "C")

            pdf.set_xy(x + 20, y + 3)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*pdf.COLOR_TEXT)
            pdf.cell(w - 76, 4.5, self._latin1_safe(label), 0, 0)

            pdf.set_xy(x + w - 52, y + 3)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*pdf.COLOR_TEXT)
            pdf.cell(45, 4.5, self._fmt_int(qtd), 0, 0, "R")

            pdf.set_xy(x + 20, y + 8)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*pdf.COLOR_MUTED)
            pdf.cell(w - 76, 3.5, self._latin1_safe(subtitle), 0, 0)

            pdf.set_xy(x + w - 52, y + 8)
            pdf.cell(45, 3.5, f"{percentual:.1f}%", 0, 0, "R")

            bar_x = x + 20
            bar_y = y + h - 5
            bar_w = w - 72
            bar_h = 2.4

        pdf.set_fill_color(226, 232, 240)
        pdf.rect(bar_x, bar_y, bar_w, bar_h, "F")
        if proporcao > 0:
            pdf.set_fill_color(*accent)
            pdf.rect(bar_x, bar_y, max(2, bar_w * min(1, proporcao)), bar_h, "F")


    def _desenhar_destaques_variedades_pdf_geral(self, pdf, dados):
        variedades = dados.get("variedades") or dados.get("tops", {}).get("variedades", [])
        total_geral = dados["total_geral"]
        pdf.section_title(
            "Destaque das Variedades",
            "Leitura rapida das variedades com maior volume no periodo. O detalhamento completo continua nos blocos por origem e destino.",
        )

        if not variedades:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*pdf.COLOR_MUTED)
            pdf.cell(190, 6, "Nenhuma variedade encontrada no periodo.", 0, 1)
            return

        principais = variedades[:12]
        maior_qtd = max(int(item.get("qtd") or 0) for item in principais)

        for indice, item in enumerate(principais, start=1):
            altura = 30 if indice == 1 else 17
            if pdf.get_y() + altura + 4 > pdf.page_break_trigger:
                pdf.add_page()
                pdf.section_title(
                    "Destaque das Variedades",
                    "Continuidade das variedades com maior volume no periodo.",
                )

            y = pdf.get_y()
            self._desenhar_card_variedade_pdf_geral(
                pdf,
                10,
                y,
                190,
                altura,
                indice,
                item,
                total_geral,
                maior_qtd,
            )
            pdf.set_y(y + altura + 3)

        restantes = len(variedades) - len(principais)
        if restantes > 0:
            pdf.ln(1)
            pdf.set_fill_color(*pdf.COLOR_SLATE_LIGHT)
            pdf.set_text_color(*pdf.COLOR_MUTED)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(
                190,
                6,
                self._latin1_safe(
                    f"Mais {self._fmt_int(restantes)} variedade(s) aparecem no detalhamento por origem e variedade."
                ),
                0,
                1,
                "C",
                True,
            )


    def _desenhar_resumo_pdf_geral(self, pdf, dados):
        pdf.section_title(
            "Resumo Executivo",
            "Panorama do periodo com volumes, destinos mais ativos e pontos que merecem revisao.",
        )

        metricas = [
            ("Total de Viagens", self._fmt_int(dados["total_geral"]), "Somente viagens completas entram no detalhamento", (59, 64, 74)),
            ("Origens Ativas", self._fmt_int(dados["metricas"]["origens_ativas"]), "Origens com expedicao", (59, 130, 246)),
            ("Variedades Ativas", self._fmt_int(dados["metricas"]["variedades_ativas"]), "Variedades registradas", (22, 163, 74)),
            ("Destinos Ativos", self._fmt_int(dados["metricas"]["destinos_ativos"]), "Destinos de plantio", (217, 119, 6)),
        ]

        x_positions = [10, 108, 10, 108]
        y_positions = [50, 50, 72, 72]
        for idx, (titulo, valor, subtitulo, accent) in enumerate(metricas):
            pdf.metric_card(x_positions[idx], y_positions[idx], 92, 18, titulo, valor, subtitulo, accent=accent)

        pdf.set_y(96)
        pdf.section_title("Pendencias de Cadastro", "Campos em aberto que podem ser revisados antes da proxima exportacao.")

        pendencias = [
            ("Sem Variedade", self._fmt_int(dados["pendencias"]["sem_variedade"]), "Afeta agrupamento por variedade", (220, 38, 38)),
            ("Sem Destino", self._fmt_int(dados["pendencias"]["sem_destino"]), "Aparece como nao informado", (202, 138, 4)),
            ("Sem Origem", self._fmt_int(dados["pendencias"]["sem_origem"]), "Prejudica rastreabilidade", (79, 70, 229)),
        ]
        pend_y = pdf.get_y()
        x_cards = [10, 74, 138]
        for idx, (titulo, valor, subtitulo, accent) in enumerate(pendencias):
            pdf.metric_card(x_cards[idx], pend_y, 62, 16, titulo, valor, subtitulo, accent=accent)

        pdf.set_y(pend_y + 20)
        resumo_y = pdf.get_y()
        esquerda_h = self._desenhar_ranking_pdf(pdf, 10, resumo_y, 92, "Top Origens", dados["tops"]["origens"], dados["total_geral"])
        direita_h = self._desenhar_ranking_pdf(pdf, 108, resumo_y, 92, "Top Variedades", dados["tops"]["variedades"], dados["total_geral"])

        pdf.set_y(resumo_y + max(esquerda_h, direita_h) + 2)
        topo_y = pdf.get_y()
        esquerda_h = self._desenhar_ranking_pdf(pdf, 10, topo_y, 92, "Top Destinos", dados["tops"]["destinos"], dados["total_geral"])
        direita_h = self._desenhar_ranking_pdf(pdf, 108, topo_y, 92, "Top Blocos", dados["tops"]["grupos"], dados["total_geral"])
        pdf.set_y(topo_y + max(esquerda_h, direita_h))


    def _desenhar_info_bloco_pdf_geral(self, pdf, x, y, w, titulo, valor, accent=None, destaque=False):
        accent = accent or pdf.COLOR_PRIMARY
        if destaque:
            pdf.set_fill_color(240, 253, 244)
        else:
            pdf.set_fill_color(248, 250, 252)
        pdf.rect(x, y, w, 11, "F")
        pdf.set_fill_color(*accent)
        pdf.rect(x, y, 2, 11, "F")

        pdf.set_xy(x + 3, y + 1.2)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*accent if destaque else (100, 116, 139))
        pdf.cell(w - 6, 3, self._latin1_safe(titulo.upper()), 0, 2)

        pdf.set_x(x + 3)
        pdf.set_font("Helvetica", "B", 9 if destaque else 8)
        pdf.set_text_color(30, 41, 59)
        limite = 54 if destaque else (34 if w <= 50 else 50)
        pdf.cell(w - 6, 4, self._latin1_safe(self._resumir_texto(valor, limite)), 0, 2)


    def _desenhar_cabecalho_pendencias_pdf_geral(self, pdf, titulo, descricao, quantidade, accent):
        pdf.set_fill_color(*accent)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(190, 7, self._latin1_safe(f"{titulo} ({self._fmt_int(quantidade)})"), ln=1, fill=True)

        pdf.set_fill_color(*pdf.COLOR_SLATE_LIGHT)
        pdf.set_text_color(*pdf.COLOR_MUTED)
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(190, 5, self._latin1_safe(descricao), ln=1, fill=True)

        pdf.draw_table_header(
            [
                (20, "NOTA", "C"),
                (24, "DATA", "C"),
                (73, "REFERENCIA", "L"),
                (73, "DETALHE", "L"),
            ],
            accent=accent,
        )


    def _desenhar_pendencias_pdf_geral(self, pdf, dados):
        categorias = [
            (
                "sem_variedade",
                "Pendencias: Sem Variedade",
                "Notas com origem e/ou destino definidos, mas sem variedade preenchida.",
                (220, 38, 38),
            ),
            (
                "sem_destino",
                "Pendencias: Sem Destino",
                "Notas que ainda precisam receber a fazenda de plantio.",
                (202, 138, 4),
            ),
            (
                "sem_origem",
                "Pendencias: Sem Origem",
                "Notas sem fazenda de muda informada, o que prejudica a rastreabilidade.",
                (79, 70, 229),
            ),
        ]

        detalhes = dados.get("pendencias_detalhes", {})
        if not any(detalhes.get(chave) for chave, *_ in categorias):
            return

        pdf.add_page()
        pdf.section_title(
            "Pendencias Detalhadas",
            "Notas com cadastro incompleto para revisao mais rapida.",
        )

        for chave, titulo, descricao, accent in categorias:
            itens = detalhes.get(chave, [])
            if not itens:
                continue

            if pdf.get_y() + 18 > pdf.page_break_trigger:
                pdf.add_page()
                pdf.section_title(
                    "Pendencias Detalhadas",
                    "Continuidade das notas com informacoes pendentes.",
                )

            self._desenhar_cabecalho_pendencias_pdf_geral(pdf, titulo, descricao, len(itens), accent)

            fill = False
            for item in itens:
                if pdf.get_y() + 6 > pdf.page_break_trigger:
                    pdf.add_page()
                    pdf.section_title(
                        "Pendencias Detalhadas",
                        "Continuidade das notas com informacoes pendentes.",
                    )
                    self._desenhar_cabecalho_pendencias_pdf_geral(pdf, titulo, descricao, len(itens), accent)

                if fill:
                    pdf.set_fill_color(248, 250, 252)
                else:
                    pdf.set_fill_color(255, 255, 255)

                y = pdf.get_y()
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(51, 65, 85)
                pdf.cell(20, 6, self._latin1_safe(self._resumir_texto(item["nota"], 10)), 0, 0, "C", fill)
                pdf.cell(24, 6, self._latin1_safe(item["data"]), 0, 0, "C", fill)
                pdf.cell(73, 6, self._latin1_safe(self._resumir_texto(item["referencia"], 44)), 0, 0, "L", fill)
                pdf.cell(73, 6, self._latin1_safe(self._resumir_texto(item["detalhe"], 44)), 0, 1, "L", fill)
                pdf.set_draw_color(*pdf.COLOR_BORDER)
                pdf.line(10, y + 6, 200, y + 6)
                fill = not fill

            pdf.ln(4)


    def _desenhar_cabecalho_destinos_pdf_geral(self, pdf):
        # multi_cell pode deixar o cursor na borda direita. A tabela sempre
        # ocupa a largura util inteira e precisa recomecar na margem esquerda.
        pdf.set_x(pdf.l_margin)
        pdf.draw_table_header(
            [
                (24, "COD.", "C"),
                (126, "FAZENDA DE PLANTIO", "L"),
                (40, "VIAGENS", "C"),
            ]
        )

    def _altura_talhoes_pdf_geral(self, pdf, grupo):
        talhoes_preview = self._resumir_lista(grupo["talhoes"], limite=12)
        pdf.set_font("Helvetica", "", 7)
        return pdf.text_height(190, f"Talhoes observados: {talhoes_preview}", 4.5)

    def _altura_contexto_bloco_pdf_geral(self, pdf, grupo, continuidade=False):
        altura = 8
        if continuidade:
            altura += 6 + 6
        else:
            altura += 1 + 12 + self._altura_talhoes_pdf_geral(pdf, grupo) + 1 + 6
        return altura

    def _desenhar_contexto_bloco_pdf_geral(self, pdf, indice, total_blocos, grupo, continuidade=False):
        pdf.set_fill_color(*pdf.COLOR_PRIMARY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)

        titulo_origem = f"{indice:02d}. {self._label_fazenda_relatorio(grupo['codigo_origem'], grupo['nome_origem'], 'MUDA')}"
        if continuidade:
            titulo_origem += " (CONT.)"
        pdf.cell(190, 8, self._latin1_safe(self._resumir_texto(titulo_origem, 96)), border=0, ln=1, fill=True)

        if continuidade:
            pdf.set_fill_color(248, 250, 252)
            pdf.set_text_color(73, 80, 87)
            pdf.set_font("Helvetica", "", 7)
            resumo = (
                f"Variedade: {grupo['variedade']} | "
                f"Periodo: {grupo['inicio'].strftime('%d/%m/%Y')} a {grupo['fim'].strftime('%d/%m/%Y')} | "
                f"Bloco {indice}/{total_blocos}"
            )
            pdf.multi_cell(190, 4.5, self._latin1_safe(self._resumir_texto(resumo, 116)), border=0, fill=True)
        else:
            cards_y = pdf.get_y() + 1
            self._desenhar_info_bloco_pdf_geral(
                pdf,
                10,
                cards_y,
                82,
                "Variedade",
                grupo["variedade"],
                accent=(22, 163, 74),
                destaque=True,
            )
            self._desenhar_info_bloco_pdf_geral(
                pdf,
                96,
                cards_y,
                52,
                "Periodo",
                f"{grupo['inicio'].strftime('%d/%m/%Y')} a {grupo['fim'].strftime('%d/%m/%Y')}",
            )
            self._desenhar_info_bloco_pdf_geral(
                pdf,
                152,
                cards_y,
                48,
                "Resumo",
                f"{self._fmt_int(grupo['total'])} viagens | {self._fmt_int(len(grupo['destinos']))} destinos",
            )
            pdf.set_y(cards_y + 12)

            talhoes_preview = self._resumir_lista(grupo["talhoes"], limite=12)
            pdf.set_fill_color(248, 250, 252)
            pdf.set_text_color(73, 80, 87)
            pdf.set_font("Helvetica", "", 7)
            pdf.multi_cell(
                190,
                4.5,
                self._latin1_safe(f"Talhoes observados: {talhoes_preview}"),
                border=0,
                fill=True,
            )

            pdf.ln(1)

        self._desenhar_cabecalho_destinos_pdf_geral(pdf)


    def _desenhar_bloco_pdf_geral(self, pdf, indice, total_blocos, grupo):
        self._desenhar_contexto_bloco_pdf_geral(pdf, indice, total_blocos, grupo)

        def redraw_contexto():
            pdf.section_title(
                "Detalhamento por Origem e Variedade",
                "Continuidade das origens e variedades com seus destinos.",
            )
            self._desenhar_contexto_bloco_pdf_geral(pdf, indice, total_blocos, grupo, continuidade=True)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(51, 65, 85)
        fill = False
        for destino in grupo["destinos"]:
            pdf.ensure_space(6, redraw_contexto)
            # O callback de continuidade desenha cabecalhos em branco. Reponha
            # explicitamente o estado das linhas apos toda quebra de pagina.
            pdf.set_x(pdf.l_margin)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(51, 65, 85)
            if fill:
                pdf.set_fill_color(248, 250, 252)
            else:
                pdf.set_fill_color(255, 255, 255)
            y = pdf.get_y()
            pdf.cell(24, 6, self._latin1_safe(self._formatar_codigo_relatorio(destino["codigo"])), border=0, align="C", fill=fill)
            pdf.cell(126, 6, self._latin1_safe(self._resumir_texto(destino["nome"], 72)), border=0, fill=fill)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(40, 6, self._fmt_int(destino["qtd"]), border=0, ln=1, align="C", fill=fill)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_draw_color(*pdf.COLOR_BORDER)
            pdf.line(10, y + 6, 200, y + 6)
            fill = not fill

        pdf.ensure_space(9, redraw_contexto)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(190, 5, f"Bloco {indice}/{total_blocos}", ln=1, align="R")
        pdf.ln(4)
