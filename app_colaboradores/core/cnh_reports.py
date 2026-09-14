import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

from db import get_db_connection
from melhorias_programa import caminho_publicacao_atomica

IGNORED_FRONTS = {"", "SEM ESCALA", "N/A", "NAO DESIGNADO", "NÃO DESIGNADO"}


@dataclass
class CNHReportRow:
    codigo_colaborador: str
    nome: str
    frente_safra: str
    turno_safra: str
    funcao_safra: str
    validade_cnh: str
    dias_para_vencer: int


class PDFRelatorioCNH(FPDF):
    def __init__(self, titulo: str, subtitulo: str = ""):
        super().__init__("L", "mm", "A4")
        self.titulo = titulo
        self.subtitulo = subtitulo
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Arial", "B", 15)
        self.cell(0, 8, self._safe(self.titulo), 0, 1, "C")
        self.set_font("Arial", "", 9)
        self.cell(0, 6, self._safe(datetime.now().strftime("Gerado em: %d/%m/%Y %H:%M:%S")), 0, 1, "C")
        if self.subtitulo:
            self.cell(0, 6, self._safe(self.subtitulo), 0, 1, "C")
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Arial", "I", 8)
        self.cell(0, 6, self._safe(f"Pagina {self.page_no()}"), 0, 0, "C")

    @staticmethod
    def _safe(value: str) -> str:
        return str(value).encode("latin-1", "replace").decode("latin-1")


def _normalizar_frente(frente: str | None) -> str:
    texto = (frente or "").strip()
    return texto or "SEM ESCALA"


def _frente_ignorada(frente: str) -> bool:
    return frente.strip().upper() in IGNORED_FRONTS


def _parse_validade(validade_cnh: str | None) -> date | None:
    if not validade_cnh:
        return None
    texto = str(validade_cnh).strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None


def carregar_registros_cnh(
    db_path: str,
    dias_alerta: int = 30,
    incluir_sem_escala: bool = False,
) -> dict[str, object]:
    hoje = date.today()
    categorias = {
        "vencidas": [],
        "a_vencer": [],
        "validas": [],
    }
    resumo = {
        "total_lidos": 0,
        "sem_validade": 0,
        "datas_invalidas": 0,
        "sem_escala_ignorados": 0,
    }

    with get_db_connection(dict_rows=True, db_target=db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                codigo_colaborador,
                nome,
                frente_safra,
                turno_safra,
                funcao_safra,
                validade_cnh
            FROM colaboradores
            WHERE COALESCE(oculto_operacao, 0) = 0
            ORDER BY nome
            """
        )

        for row in cursor.fetchall():
            resumo["total_lidos"] += 1
            frente = _normalizar_frente(row["frente_safra"])

            if not incluir_sem_escala and _frente_ignorada(frente):
                resumo["sem_escala_ignorados"] += 1
                continue

            validade = _parse_validade(row["validade_cnh"])
            if validade is None:
                if row["validade_cnh"] in (None, "") or not str(row["validade_cnh"]).strip():
                    resumo["sem_validade"] += 1
                else:
                    resumo["datas_invalidas"] += 1
                continue

            dias_para_vencer = (validade - hoje).days
            item = CNHReportRow(
                codigo_colaborador=str(row["codigo_colaborador"] or ""),
                nome=str(row["nome"] or ""),
                frente_safra=frente,
                turno_safra=str(row["turno_safra"] or ""),
                funcao_safra=str(row["funcao_safra"] or ""),
                validade_cnh=validade.strftime("%d/%m/%Y"),
                dias_para_vencer=dias_para_vencer,
            )

            if dias_para_vencer < 0:
                categorias["vencidas"].append(item)
            elif dias_para_vencer <= dias_alerta:
                categorias["a_vencer"].append(item)
            else:
                categorias["validas"].append(item)

    return {
        "dias_alerta": dias_alerta,
        "categorias": categorias,
        "resumo": resumo,
    }


def _agrupar_por_frente(itens: list[CNHReportRow]) -> dict[str, list[CNHReportRow]]:
    grupos: dict[str, list[CNHReportRow]] = defaultdict(list)
    for item in itens:
        grupos[item.frente_safra].append(item)
    return dict(sorted(grupos.items(), key=lambda entry: entry[0]))


def _texto_status(item: CNHReportRow) -> str:
    if item.dias_para_vencer < 0:
        dias = abs(item.dias_para_vencer)
        return f"Vencida ha {dias} dia(s)"
    if item.dias_para_vencer == 0:
        return "Vence hoje"
    return f"Vence em {item.dias_para_vencer} dia(s)"


def _quebrar_texto_celula(pdf: PDFRelatorioCNH, valor: str, largura: float) -> list[str]:
    texto = pdf._safe(valor or "-")
    limite = max(1.0, largura - 3.0)
    palavras = texto.split()
    if not palavras:
        return ["-"]

    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        tentativa = palavra if not atual else f"{atual} {palavra}"
        if pdf.get_string_width(tentativa) <= limite:
            atual = tentativa
            continue

        if atual:
            linhas.append(atual)
            atual = ""

        # Nomes/codigos sem espacos tambem precisam permanecer dentro da celula.
        trecho = ""
        for caractere in palavra:
            if trecho and pdf.get_string_width(trecho + caractere) > limite:
                linhas.append(trecho)
                trecho = caractere
            else:
                trecho += caractere
        atual = trecho

    if atual:
        linhas.append(atual)
    return linhas or ["-"]


def _desenhar_cabecalho_tabela(pdf: PDFRelatorioCNH, col_widths: list[float]) -> None:
    header = ["Nome", "Codigo", "Funcao", "Turno", "Validade", "Status"]
    pdf.set_font("Arial", "B", 9)
    for idx, titulo in enumerate(header):
        pdf.cell(col_widths[idx], 8, pdf._safe(titulo), 1, 0, "C")
    pdf.ln()


def _desenhar_identificacao_frente(
    pdf: PDFRelatorioCNH,
    frente: str,
    quantidade: int,
    continuacao: bool = False,
) -> None:
    sufixo = " - continuacao" if continuacao else ""
    pdf.set_font("Arial", "B", 11)
    pdf.cell(
        0,
        8,
        pdf._safe(f"Frente: {frente} ({quantidade} colaborador(es)){sufixo}"),
        0,
        1,
        "L",
    )
    pdf.ln(1)


def _desenhar_tabela(pdf: PDFRelatorioCNH, itens: list[CNHReportRow], frente: str) -> None:
    col_widths = [78, 24, 58, 28, 28, 44]
    _desenhar_cabecalho_tabela(pdf, col_widths)

    pdf.set_font("Arial", "", 8)
    for item in itens:
        linha = [
            item.nome,
            item.codigo_colaborador,
            item.funcao_safra or "-",
            item.turno_safra or "-",
            item.validade_cnh,
            _texto_status(item),
        ]
        linhas_celulas = [
            _quebrar_texto_celula(pdf, str(valor), col_widths[idx])
            for idx, valor in enumerate(linha)
        ]
        altura_linha = max(7.0, 4.0 * max(len(linhas) for linhas in linhas_celulas) + 2.0)

        if pdf.get_y() + altura_linha > pdf.h - pdf.b_margin:
            pdf.add_page()
            _desenhar_identificacao_frente(pdf, frente, len(itens), continuacao=True)
            _desenhar_cabecalho_tabela(pdf, col_widths)
            pdf.set_font("Arial", "", 8)

        x_inicial = pdf.get_x()
        y_inicial = pdf.get_y()
        x = x_inicial
        for idx, linhas_texto in enumerate(linhas_celulas):
            largura = col_widths[idx]
            pdf.rect(x, y_inicial, largura, altura_linha)
            pdf.set_xy(x + 1.5, y_inicial + 1.0)
            for texto in linhas_texto:
                pdf.cell(largura - 3.0, 4.0, texto, 0, 2, "L")
            x += largura
        pdf.set_xy(x_inicial, y_inicial + altura_linha)


def gerar_pdf_categoria(
    itens: list[CNHReportRow],
    caminho_saida: str,
    titulo: str,
    subtitulo: str,
) -> str | None:
    if not itens:
        return None

    pdf = PDFRelatorioCNH(titulo=titulo, subtitulo=subtitulo)
    grupos = _agrupar_por_frente(sorted(itens, key=lambda item: (item.frente_safra, item.nome)))

    for frente, grupo in grupos.items():
        pdf.add_page()
        _desenhar_identificacao_frente(pdf, frente, len(grupo))
        _desenhar_tabela(pdf, grupo, frente)

    with caminho_publicacao_atomica(caminho_saida) as caminho_temporario:
        pdf.output(caminho_temporario)
    return caminho_saida


def gerar_relatorios_cnh(
    db_path: str,
    pasta_saida: str,
    dias_alerta: int = 30,
    incluir_sem_escala: bool = False,
) -> dict[str, object]:
    os.makedirs(pasta_saida, exist_ok=True)
    dados = carregar_registros_cnh(
        db_path=db_path,
        dias_alerta=dias_alerta,
        incluir_sem_escala=incluir_sem_escala,
    )

    categorias = dados["categorias"]
    subtitulo = f"Relatorio agrupado por frente de safra | Janela de alerta: {dias_alerta} dia(s)"

    especificacoes = {
        "vencidas": (
            "cnhs_vencidas_por_frente.pdf",
            "CNHs Vencidas por Frente",
        ),
        "a_vencer": (
            f"cnhs_a_vencer_{dias_alerta}_dias_por_frente.pdf",
            f"CNHs a Vencer em ate {dias_alerta} dias por Frente",
        ),
        "validas": (
            "cnhs_validas_por_frente.pdf",
            "CNHs Validas por Frente",
        ),
    }

    # Todos os PDFs não vazios são gerados antes de tocar nos arquivos publicados.
    # Assim, uma falha de geração não deixa um pacote parcialmente atualizado.
    arquivos: dict[str, str | None] = {}
    with tempfile.TemporaryDirectory(prefix=".cnh_reports_", dir=pasta_saida) as pasta_temporaria:
        publicacoes: list[tuple[Path, Path]] = []
        obsoletos: set[Path] = set()

        for categoria, (nome_arquivo, titulo) in especificacoes.items():
            destino = Path(pasta_saida) / nome_arquivo
            if categoria == "a_vencer":
                antigos_alertas = Path(pasta_saida).glob("cnhs_a_vencer_*_dias_por_frente.pdf")
                obsoletos.update(path for path in antigos_alertas if path != destino)
            if not categorias[categoria]:
                arquivos[categoria] = None
                obsoletos.add(destino)
                continue

            temporario = Path(pasta_temporaria) / nome_arquivo
            gerar_pdf_categoria(
                categorias[categoria],
                str(temporario),
                titulo,
                subtitulo,
            )
            publicacoes.append((temporario, destino))
            arquivos[categoria] = str(destino)

        for temporario, destino in publicacoes:
            os.replace(temporario, destino)
        for obsoleto in sorted(obsoletos):
            obsoleto.unlink(missing_ok=True)

    return {
        "arquivos": arquivos,
        "categorias": {chave: len(valor) for chave, valor in categorias.items()},
        "resumo": dados["resumo"],
    }
