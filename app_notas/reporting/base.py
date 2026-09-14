from __future__ import annotations

import re
import os
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from app_config import APP_ROOT, RESOURCE_ROOT


def formatar_periodo_br(d_ini: str, d_fim: str) -> str:
    dt_i_str = datetime.strptime(d_ini, "%Y-%m-%d").strftime("%d/%m/%Y")
    dt_f_str = datetime.strptime(d_fim, "%Y-%m-%d").strftime("%d/%m/%Y")
    return f"{dt_i_str} a {dt_f_str}"


class PDFRelatorio(FPDF):
    COLOR_PRIMARY = (76, 70, 170)
    COLOR_PRIMARY_DARK = (55, 49, 132)
    COLOR_NAVY = COLOR_PRIMARY_DARK
    COLOR_SLATE = COLOR_PRIMARY
    COLOR_SLATE_LIGHT = (248, 250, 252)
    COLOR_BORDER = (226, 232, 240)
    COLOR_TEXT = (30, 41, 59)
    COLOR_MUTED = (100, 116, 139)
    COLOR_BLUE = COLOR_PRIMARY
    COLOR_BLUE_SOFT = COLOR_PRIMARY
    COLOR_GREEN = (34, 197, 94)
    COLOR_AMBER = (245, 158, 11)
    COLOR_RED = (239, 68, 68)
    DEFAULT_LOGO_CANDIDATES = (
        "assets/logo_Operacoes Agricolas_pdf.svg",
        "assets/logo_Operacoes Agricolas_pdf.png",
        "assets/logo_Operacoes Agricolas_pdf_white.svg",
        "assets/logo_Operacoes Agricolas_pdf_white.png",
        "assets/logo.png",
        "assets/logo_relatorios.png",
        "logo.png",
    )

    def __init__(self, titulo, periodo, total_viagens, logo_path=None, orientation="P"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.titulo = titulo
        self.periodo = periodo
        self.total_viagens = total_viagens
        self.gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.logo_path = self._resolver_logo_path(logo_path)

    def _safe(self, texto):
        return str(texto or "").encode("latin-1", "replace").decode("latin-1")

    def _resolver_logo_path(self, logo_path=None):
        candidatos = [logo_path] if logo_path else self.DEFAULT_LOGO_CANDIDATES
        bases = (APP_ROOT, RESOURCE_ROOT)

        for candidato in candidatos:
            if not candidato:
                continue
            caminho = Path(os.path.expandvars(str(candidato))).expanduser()
            if not caminho.is_absolute():
                for base_dir in bases:
                    caminho_base = base_dir / caminho
                    if caminho_base.exists():
                        return str(caminho_base)
                continue
            if caminho.exists():
                return str(caminho)
        return None

    def fit_text_to_width(self, text, max_width):
        texto = self._safe(text)
        if not texto or self.get_string_width(texto) <= max_width:
            return texto

        elipse = "..."
        base = texto
        while base and self.get_string_width(base.rstrip() + elipse) > max_width:
            base = base[:-1]
        return (base.rstrip() + elipse) if base else elipse

    def draw_header_chip(self, x, y, max_w, text, accent=(96, 165, 250)):
        texto = self.fit_text_to_width(text, max_w - 9)
        w = min(max_w, max(24, self.get_string_width(texto) + 9))

        self.set_draw_color(*accent)
        self.set_fill_color(30, 41, 59)
        self.rect(x, y, w, 6, "DF")
        self.set_fill_color(*accent)
        self.rect(x, y, 2.2, 6, "F")

        self.set_xy(x + 4.2, y + 1.2)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(255, 255, 255)
        self.cell(w - 5.2, 3.6, texto, 0, 0, "L")

    def draw_table_header(self, columns, row_height=6, accent=None, fill=None):
        accent = accent or self.COLOR_PRIMARY_DARK
        fill = fill or self.COLOR_PRIMARY
        x, y = self.get_x(), self.get_y()
        total_w = sum(width for width, *_ in columns)

        self.set_fill_color(*fill)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 8)
        for idx, (width, label, align) in enumerate(columns):
            self.cell(width, row_height, self._safe(label), 0, 1 if idx == len(columns) - 1 else 0, align, True)

        self.set_fill_color(*accent)
        self.rect(x, y + row_height - 0.35, total_w, 0.35, "F")

    def cell(
        self,
        w=None,
        h=None,
        text="",
        border=0,
        ln="DEPRECATED",
        align="",
        fill=False,
        link="",
        center=False,
        markdown=False,
        new_x=XPos.RIGHT,
        new_y=YPos.TOP,
    ):
        if ln != "DEPRECATED":
            if ln == 0:
                new_x, new_y = XPos.RIGHT, YPos.TOP
            elif ln == 1:
                new_x, new_y = XPos.LMARGIN, YPos.NEXT
            elif ln == 2:
                new_x, new_y = XPos.LEFT, YPos.NEXT

        return super().cell(
            w=w,
            h=h,
            text=text,
            border=border,
            align=align,
            fill=fill,
            link=link,
            center=center,
            markdown=markdown,
            new_x=new_x,
            new_y=new_y,
        )

    def text_height(self, width, text, line_height):
        texto = self._safe(text)
        if not texto:
            return float(line_height)

        x_atual, y_atual = self.get_x(), self.get_y()
        altura = self.multi_cell(
            width,
            line_height,
            texto,
            dry_run=True,
            output=MethodReturnValue.HEIGHT,
        )
        self.set_xy(x_atual, y_atual)
        return float(altura or line_height)

    def ensure_space(self, altura, redraw=None):
        if self.get_y() + altura <= self.page_break_trigger:
            return False

        self.add_page()
        if redraw:
            redraw()
        return True

    def _draw_logo_header(self):
        if not self.logo_path:
            return 0

        try:
            self.image(self.logo_path, x=self.w - 34, y=5.2, w=22)
            return 34
        except Exception:
            return 0

    def header(self):
        self.set_fill_color(255, 255, 255)
        self.rect(0, 0, self.w, 28, "F")
        self.set_fill_color(*self.COLOR_PRIMARY)
        self.rect(0, 0, self.w, 2.2, "F")
        self._draw_logo_header()

        self.set_xy(10, 6.2)
        self.set_text_color(18, 24, 33)
        self.set_font("Helvetica", "B", 9.5)
        title_width = self.w - 80
        self.cell(title_width, 4.8, self.fit_text_to_width(self.titulo, title_width), 0, 1)

        detalhes = []
        if self.periodo:
            detalhes.append(f"Periodo {self.periodo}")
        if self.total_viagens is not None:
            detalhes.append(f"Total: {self.total_viagens} viagens")
        subtitulo = " | ".join(detalhes)
        if subtitulo:
            self.set_x(10)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(73, 80, 87)
            self.cell(title_width, 4.2, self.fit_text_to_width(subtitulo, title_width), 0, 1)

        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, 25.8, self.w - 10, 25.8)
        self.set_y(32)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, self.h - 15.5, self.w - 10, self.h - 15.5)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(90, 98, 108)
        self.cell(self.w - 20, 10, self._safe(f"Pagina {self.page_no()}/{{nb}}"), 0, 0, "R")

    def section_title(self, titulo, subtitulo=""):
        self.ensure_space(16 if subtitulo else 11)
        y = self.get_y()
        self.set_fill_color(*self.COLOR_PRIMARY)
        self.rect(10, y + 1.2, 2.4, 9.4 if subtitulo else 6.6, "F")
        self.set_xy(15, y)
        self.set_text_color(*self.COLOR_TEXT)
        self.set_font("Helvetica", "B", 13.5)
        content_width = self.w - 25
        self.cell(content_width, 6.2, self._safe(titulo), 0, 1)

        if subtitulo:
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*self.COLOR_MUTED)
            self.set_x(15)
            self.multi_cell(
                content_width,
                4.5,
                self._safe(subtitulo),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        self.set_draw_color(*self.COLOR_BORDER)
        self.line(10, self.get_y() + 1, self.w - 10, self.get_y() + 1)
        self.ln(4)

    def metric_card(self, x, y, w, h, titulo, valor, subtitulo="", accent=(59, 64, 74)):
        self.set_fill_color(*self.COLOR_SLATE_LIGHT)
        self.rect(x, y, w, h, "F")
        self.set_fill_color(*accent)
        self.rect(x, y, 2.2, h, "F")

        self.set_xy(x + 5, y + 3)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.COLOR_MUTED)
        self.cell(w - 8, 4, self._safe(titulo.upper()), 0, 2)

        self.set_x(x + 5)
        self.set_font("Helvetica", "B", 13 if h >= 16 else 11)
        self.set_text_color(*self.COLOR_NAVY)
        self.cell(w - 8, 6, self._safe(valor), 0, 2)

        if subtitulo:
            self.set_x(x + 5)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(*self.COLOR_MUTED)
            self.multi_cell(
                w - 8,
                3.2,
                self._safe(subtitulo),
                new_x=XPos.LEFT,
                new_y=YPos.TOP,
            )


class RelatorioFormatacaoMixin:
    def _normalizar_texto_relatorio(self, texto: str) -> str:
        substituicoes = {
            "\u2013": "-",
            "\u2014": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2022": "-",
            "\u00a0": " ",
            "\ufffd": " ",
        }
        for antigo, novo in substituicoes.items():
            texto = texto.replace(antigo, novo)
        texto = re.sub(r"\s+\?\s+", " / ", texto)
        texto = re.sub(r"\s+/\s+", " / ", texto)
        return texto

    def _latin1_safe(self, s: str) -> str:
        texto = self._normalizar_texto_relatorio(s or "")
        return texto.encode("latin-1", "replace").decode("latin-1")

    def _fmt_int(self, valor) -> str:
        try:
            return f"{int(valor):,}".replace(",", ".")
        except Exception:
            return str(valor)

    def _formatar_codigo_relatorio(self, codigo) -> str:
        codigo = self._texto_relatorio(codigo, "-")
        if codigo == "-":
            return codigo

        codigo_limpo = re.sub(r"\s+", "", codigo)
        if "-" in codigo_limpo or len(codigo_limpo) <= 3:
            return codigo_limpo

        return f"{codigo_limpo[:3]}-{codigo_limpo[3:]}"

    def _texto_relatorio(self, valor, padrao="") -> str:
        texto = "" if valor is None else str(valor)
        texto = self._normalizar_texto_relatorio(texto)
        texto = texto.replace("\r", " ").replace("\n", " ")
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto or padrao

    def _chave_relatorio(self, valor, padrao="") -> str:
        return self._texto_relatorio(valor, padrao).upper()

    def _sort_key_texto(self, valor):
        partes = re.split(r"(\d+)", self._texto_relatorio(valor))
        return [int(p) if p.isdigit() else p.upper() for p in partes]

    def _sort_key_codigo_relatorio(self, codigo, nome=""):
        codigo_limpo = self._texto_relatorio(codigo, "-")
        if codigo_limpo == "-":
            return (1, self._sort_key_texto(nome))
        return (
            0,
            self._sort_key_texto(self._formatar_codigo_relatorio(codigo_limpo)),
            self._sort_key_texto(nome),
        )

    def _resumir_texto(self, texto, limite=52) -> str:
        texto = self._texto_relatorio(texto, "-")
        if len(texto) <= limite:
            return texto
        return texto[: limite - 3].rstrip() + "..."

    def _resumir_lista(self, itens, limite=10) -> str:
        itens = [self._texto_relatorio(item) for item in itens if self._texto_relatorio(item)]
        if not itens:
            return "-"
        if len(itens) <= limite:
            return ", ".join(itens)
        return ", ".join(itens[:limite]) + f" +{len(itens) - limite}"

    def _label_origem_relatorio(self, codigo, nome) -> str:
        codigo = self._formatar_codigo_relatorio(codigo)
        nome = self._texto_relatorio(nome, "NÃO INFORMADA")
        return f"[{codigo}] {nome}" if codigo != "-" else nome

    def _label_fazenda_relatorio(self, codigo, nome, tipo="") -> str:
        base = self._label_origem_relatorio(codigo, nome)
        if tipo:
            return f"({tipo.upper()}) {base}"
        return base
