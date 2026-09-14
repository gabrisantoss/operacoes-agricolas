from collections import Counter, defaultdict
from datetime import date, datetime
from textwrap import shorten

import pandas as pd

from db import get_db_connection
from melhorias_programa import (
    caminho_publicacao_atomica,
    corrigir_nome_arquivo_excel,
    salvar_df_excel_com_total,
)
from agricola_shared.report_security import neutralize_dataframe


STATUS_TECNICO_ORDER = [
    "VENCIDA",
    "DATA_INVALIDA",
    "SEM_VALIDADE",
    "CRITICA_7_DIAS",
    "ALERTA_30_DIAS",
    "REGULAR",
]

STATUS_TECNICO_LABELS = {
    "VENCIDA": "Vencida",
    "DATA_INVALIDA": "Data inválida",
    "SEM_VALIDADE": "Sem validade",
    "CRITICA_7_DIAS": "Vence em 7 dias",
    "ALERTA_30_DIAS": "Vence em 30 dias",
    "REGULAR": "Regular",
}

ACOMPANHAMENTO_ORDER = [
    "SEM_ACAO",
    "AGUARDANDO_DOCUMENTO",
    "AGENDADO",
    "EM_ANDAMENTO",
    "SEM_RETORNO",
    "REGULARIZADO",
]

ACOMPANHAMENTO_LABELS = {
    "SEM_ACAO": "Sem ação",
    "AGUARDANDO_DOCUMENTO": "Aguardando documento",
    "AGENDADO": "Agendado",
    "EM_ANDAMENTO": "Em andamento",
    "SEM_RETORNO": "Sem retorno",
    "REGULARIZADO": "Regularizado",
}

STATUS_PENDENTES = {
    "VENCIDA",
    "DATA_INVALIDA",
    "SEM_VALIDADE",
    "CRITICA_7_DIAS",
    "ALERTA_30_DIAS",
}


def normalizar_status_acompanhamento(status: str | None) -> str:
    texto = (status or "").strip().upper()
    return texto if texto in ACOMPANHAMENTO_LABELS else "SEM_ACAO"


def _parse_data_iso(valor: str | None) -> date | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass

    try:
        return pd.to_datetime(texto, errors="raise").date()
    except Exception:
        return None


def _formatar_data_br(valor: str | None) -> str:
    data = _parse_data_iso(valor)
    if data is None:
        return str(valor or "").strip()
    return data.strftime("%d/%m/%Y")


def _valor_data_excel(valor):
    """Converte datas válidas para células Excel; preserva texto inválido para revisão."""
    if valor is None or not str(valor).strip():
        return None
    data = _parse_data_iso(valor)
    if data is None:
        return str(valor).strip()
    return datetime.combine(data, datetime.min.time())


def classificar_status_tecnico(validade_cnh: str | None, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    texto = str(validade_cnh or "").strip()

    if not texto:
        return {
            "status": "SEM_VALIDADE",
            "label": STATUS_TECNICO_LABELS["SEM_VALIDADE"],
            "dias_para_vencer": None,
            "validade_formatada": "-",
            "descricao": "Validade não informada",
            "ordem": STATUS_TECNICO_ORDER.index("SEM_VALIDADE"),
        }

    validade = _parse_data_iso(texto)
    if validade is None:
        return {
            "status": "DATA_INVALIDA",
            "label": STATUS_TECNICO_LABELS["DATA_INVALIDA"],
            "dias_para_vencer": None,
            "validade_formatada": texto,
            "descricao": "Formato de data inválido",
            "ordem": STATUS_TECNICO_ORDER.index("DATA_INVALIDA"),
        }

    dias_para_vencer = (validade - hoje).days
    validade_formatada = validade.strftime("%d/%m/%Y")

    if dias_para_vencer < 0:
        status = "VENCIDA"
        descricao = f"Vencida há {abs(dias_para_vencer)} dia(s)"
    elif dias_para_vencer <= 7:
        status = "CRITICA_7_DIAS"
        descricao = f"Vence em {dias_para_vencer} dia(s)"
    elif dias_para_vencer <= 30:
        status = "ALERTA_30_DIAS"
        descricao = f"Vence em {dias_para_vencer} dia(s)"
    else:
        status = "REGULAR"
        descricao = f"Vence em {dias_para_vencer} dia(s)"

    return {
        "status": status,
        "label": STATUS_TECNICO_LABELS[status],
        "dias_para_vencer": dias_para_vencer,
        "validade_formatada": validade_formatada,
        "descricao": descricao,
        "ordem": STATUS_TECNICO_ORDER.index(status),
    }


def _construir_inconsistencias(row: dict, status_info: dict) -> list[str]:
    inconsistencias = []
    categoria = str(row.get("categoria_cnh") or "").strip()
    situacao = str(row.get("situacao") or "").strip().upper()
    caminho_pdf = str(row.get("caminho_cnh_pdf") or row.get("caminho_comprovante_cnh") or "").strip()
    status_acompanhamento = normalizar_status_acompanhamento(row.get("status_cnh_acompanhamento"))

    if status_info["status"] == "SEM_VALIDADE":
        inconsistencias.append("Validade da CNH não informada")
    elif status_info["status"] == "DATA_INVALIDA":
        inconsistencias.append("Validade da CNH com formato inválido")

    if not categoria:
        inconsistencias.append("Categoria da CNH não informada")

    if status_info["status"] in {"VENCIDA", "CRITICA_7_DIAS", "ALERTA_30_DIAS"} and situacao == "ATIVO":
        inconsistencias.append("Colaborador ativo com CNH pendente")

    if status_info["status"] != "SEM_VALIDADE" and not caminho_pdf:
        inconsistencias.append("CNH sem PDF/comprovante anexado")

    if status_acompanhamento == "REGULARIZADO" and status_info["status"] in STATUS_PENDENTES:
        inconsistencias.append("Marcado como regularizado, mas a validade ainda está pendente")

    return inconsistencias


def _prioridade_operacional(status_info: dict, inconsistencias: list[str]) -> tuple[int, str]:
    status = status_info["status"]

    if status in {"VENCIDA", "DATA_INVALIDA", "SEM_VALIDADE"}:
        return 0, "Alta"
    if status == "CRITICA_7_DIAS":
        return 1, "Alta"
    if inconsistencias:
        return 2, "Média"
    if status == "ALERTA_30_DIAS":
        return 3, "Planejamento"
    return 4, "OK"


def _inconsistencias_criticas(inconsistencias: list[str]) -> list[str]:
    return [msg for msg in inconsistencias if msg != "CNH sem PDF/comprovante anexado"]


def listar_painel_cnh(
    db_path: str,
    filtro_busca: str = "",
    filtro_status_tecnico: str = "",
    filtro_status_acompanhamento: str = "",
    filtro_frente: str = "",
    filtro_gestor: str = "",
    somente_com_inconsistencias: bool = False,
    somente_pendentes: bool = False,
    limit: int = 0,
    offset: int = 0,
) -> tuple[list[dict], int]:
    from datetime import date, timedelta
    from db import get_db_connection
    from typing import Any

    hoje = date.today()
    hoje_iso = hoje.isoformat()
    d7_iso = (hoje + timedelta(days=7)).isoformat()
    d30_iso = (hoje + timedelta(days=30)).isoformat()

    busca = filtro_busca.strip().lower()
    status_tecnico_filtro = filtro_status_tecnico.strip().upper()
    status_acomp_filtro = normalizar_status_acompanhamento(filtro_status_acompanhamento) if filtro_status_acompanhamento else ""
    frente_filtro = filtro_frente.strip().lower()
    gestor_filtro = filtro_gestor.strip().lower()

    query_conditions = ["COALESCE(oculto_operacao, 0) = 0"]
    params = []

    if busca:
        termos = busca.split()
        for termo in termos:
            query_conditions.append("(LOWER(COALESCE(codigo_colaborador, '')) LIKE ? OR LOWER(COALESCE(nome, '')) LIKE ? OR LOWER(COALESCE(gestor_responsavel, '')) LIKE ? OR LOWER(COALESCE(frente_safra, '')) LIKE ? OR LOWER(COALESCE(horario, '')) LIKE ?)")
            params.extend([f"%{termo}%"] * 5)

    if frente_filtro:
        query_conditions.append("LOWER(COALESCE(frente_safra, 'SEM ESCALA')) = ?")
        params.append(frente_filtro)

    if gestor_filtro:
        if gestor_filtro == "não informado":
            query_conditions.append("(gestor_responsavel IS NULL OR gestor_responsavel = '')")
        else:
            query_conditions.append("LOWER(gestor_responsavel) = ?")
            params.append(gestor_filtro)

    if status_tecnico_filtro:
        if status_tecnico_filtro == "VENCIDA":
            query_conditions.append("validade_cnh < ? AND validade_cnh IS NOT NULL AND validade_cnh != ''")
            params.append(hoje_iso)
        elif status_tecnico_filtro == "CRITICA_7_DIAS":
            query_conditions.append("validade_cnh >= ? AND validade_cnh <= ?")
            params.extend([hoje_iso, d7_iso])
        elif status_tecnico_filtro == "ALERTA_30_DIAS":
            query_conditions.append("validade_cnh > ? AND validade_cnh <= ?")
            params.extend([d7_iso, d30_iso])
        elif status_tecnico_filtro == "REGULAR":
            query_conditions.append("validade_cnh > ?")
            params.append(d30_iso)
        elif status_tecnico_filtro == "SEM_VALIDADE":
            query_conditions.append("(validade_cnh IS NULL OR validade_cnh = '')")

    if status_acomp_filtro:
        query_conditions.append("UPPER(COALESCE(status_cnh_acompanhamento, 'SEM_ACAO')) = ?")
        params.append(status_acomp_filtro)

    where_clause = " AND ".join(query_conditions)

    with get_db_connection(dict_rows=True, db_target=db_path) as conn:
        cursor = conn.cursor()

        sql = f"""
            SELECT
                codigo_colaborador,
                nome,
                cidade,
                municipio,
                validade_cnh,
                categoria_cnh,
                frente_safra,
                turno_safra,
                horario,
                funcao_safra,
                funcao,
                gestor_responsavel,
                status_cnh_acompanhamento,
                ultima_acao_cnh,
                ultimo_contato_cnh,
                responsavel_ultimo_contato_cnh,
                data_prevista_regularizacao_cnh,
                observacao_cnh,
                caminho_comprovante_cnh,
                caminho_cnh_pdf,
                situacao,
                local_trabalho
            FROM colaboradores
            WHERE {where_clause}
            ORDER BY nome, codigo_colaborador
        """
        cursor.execute(sql, params)
        base_rows = [dict(row) for row in cursor.fetchall()]

    linhas = []
    for row in base_rows:
        status_info = classificar_status_tecnico(row.get("validade_cnh"))
        inconsistencias = _construir_inconsistencias(row, status_info)
        inconsistencias_criticas = _inconsistencias_criticas(inconsistencias)
        prioridade_ordem, prioridade_label = _prioridade_operacional(status_info, inconsistencias_criticas)

        cidade = row.get("cidade") or row.get("municipio") or ""
        funcao = row.get("funcao_safra") or row.get("funcao") or ""
        gestor = str(row.get("gestor_responsavel") or "").strip()
        frente = str(row.get("frente_safra") or "").strip() or "SEM ESCALA"
        acompanhamento = normalizar_status_acompanhamento(row.get("status_cnh_acompanhamento"))
        pendencia_operacional = status_info["status"] in STATUS_PENDENTES or bool(inconsistencias_criticas)

        linha = {
            **row,
            "cidade_exibicao": cidade,
            "funcao_exibicao": funcao,
            "frente_exibicao": frente,
            "gestor_exibicao": gestor or "Não informado",
            "status_tecnico": status_info["status"],
            "status_tecnico_label": status_info["label"],
            "status_tecnico_descricao": status_info["descricao"],
            "dias_para_vencer": status_info["dias_para_vencer"],
            "validade_cnh_formatada": status_info["validade_formatada"],
            "status_acompanhamento": acompanhamento,
            "status_acompanhamento_label": ACOMPANHAMENTO_LABELS[acompanhamento],
            "inconsistencias": inconsistencias,
            "inconsistencias_texto": " | ".join(inconsistencias) if inconsistencias else "",
            "prioridade_ordem": prioridade_ordem,
            "prioridade_label": prioridade_label,
            "pendencia_operacional": pendencia_operacional,
        }

        if somente_com_inconsistencias and not linha["inconsistencias"]:
            continue
        if somente_pendentes and not linha["pendencia_operacional"]:
            continue

        linhas.append(linha)

    linhas.sort(
        key=lambda item: (
            item["prioridade_ordem"],
            item["dias_para_vencer"] if item["dias_para_vencer"] is not None else 999999,
            str(item.get("nome") or ""),
            str(item.get("codigo_colaborador") or ""),
        )
    )
    total_records = len(linhas)
    start = max(0, int(offset or 0))
    if limit and int(limit) > 0:
        linhas = linhas[start : start + int(limit)]
    elif start:
        linhas = linhas[start:]
    return linhas, total_records


def listar_opcoes_painel_cnh(db_path: str) -> dict:
    linhas, _ = listar_painel_cnh(db_path)
    frentes = sorted({linha["frente_exibicao"] for linha in linhas if linha["frente_exibicao"]})
    gestores = sorted({linha["gestor_exibicao"] for linha in linhas if linha["gestor_exibicao"] and linha["gestor_exibicao"] != "Não informado"})
    return {"frentes": frentes, "gestores": gestores}


def gerar_resumo_cnh(db_path: str) -> dict:
    linhas, _ = listar_painel_cnh(db_path)
    contagem_tecnica = Counter(linha["status_tecnico"] for linha in linhas)
    contagem_acompanhamento = Counter(linha["status_acompanhamento"] for linha in linhas)

    por_frente = defaultdict(int)
    por_gestor = defaultdict(int)
    por_categoria = defaultdict(int)
    criticos = []

    for linha in linhas:
        if linha["pendencia_operacional"]:
            por_frente[linha["frente_exibicao"]] += 1
            por_gestor[linha["gestor_exibicao"]] += 1

        categoria = str(linha.get("categoria_cnh") or "").strip() or "Sem categoria"
        por_categoria[categoria] += 1

        if linha["pendencia_operacional"]:
            criticos.append(linha)

    return {
        "total": len(linhas),
        "pendentes": sum(1 for linha in linhas if linha["pendencia_operacional"]),
        "inconsistencias": sum(1 for linha in linhas if linha["inconsistencias"]),
        "contagem_tecnica": {status: contagem_tecnica.get(status, 0) for status in STATUS_TECNICO_ORDER},
        "contagem_acompanhamento": {status: contagem_acompanhamento.get(status, 0) for status in ACOMPANHAMENTO_ORDER},
        "por_frente": sorted(por_frente.items(), key=lambda item: item[1], reverse=True),
        "por_gestor": sorted(por_gestor.items(), key=lambda item: item[1], reverse=True),
        "por_categoria": sorted(por_categoria.items(), key=lambda item: item[1], reverse=True),
        "criticos": criticos[:10],
    }


def listar_historico_cnh(db_path: str, codigo_colaborador: str) -> list[dict]:
    with get_db_connection(dict_rows=True, db_target=db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM cnh_historico
            WHERE codigo_colaborador = ?
            ORDER BY data_hora DESC, id DESC
            """,
            (codigo_colaborador,),
        )
        itens = [dict(row) for row in cursor.fetchall()]

    for item in itens:
        item["validade_anterior_formatada"] = _formatar_data_br(item.get("validade_anterior"))
        item["validade_nova_formatada"] = _formatar_data_br(item.get("validade_nova"))
    return itens


def listar_acompanhamentos_cnh(db_path: str, codigo_colaborador: str) -> list[dict]:
    with get_db_connection(dict_rows=True, db_target=db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM cnh_acompanhamentos
            WHERE codigo_colaborador = ?
            ORDER BY data_hora DESC, id DESC
            """,
            (codigo_colaborador,),
        )
        itens = [dict(row) for row in cursor.fetchall()]

    for item in itens:
        status = normalizar_status_acompanhamento(item.get("status"))
        item["status_label"] = ACOMPANHAMENTO_LABELS[status]
        item["data_prevista_formatada"] = _formatar_data_br(item.get("data_prevista"))
    return itens


def _montar_dataframe_operacional(linhas: list[dict]) -> pd.DataFrame:
    registros = []
    for linha in linhas:
        registros.append(
            {
                "Prioridade": linha["prioridade_label"],
                "Código": linha.get("codigo_colaborador", ""),
                "Nome": linha.get("nome", ""),
                "Cidade": linha.get("cidade_exibicao", ""),
                "Frente": linha.get("frente_exibicao", ""),
                "Gestor": linha.get("gestor_exibicao", ""),
                "Função": linha.get("funcao_exibicao", ""),
                "Turno": linha.get("turno_safra", ""),
                "Horário": linha.get("horario", ""),
                "Categoria CNH": linha.get("categoria_cnh", ""),
                "Validade CNH": _valor_data_excel(linha.get("validade_cnh")),
                "Status Técnico": linha.get("status_tecnico_label", ""),
                "Status Acompanhamento": linha.get("status_acompanhamento_label", ""),
                "Último Contato": _valor_data_excel(linha.get("ultimo_contato_cnh")),
                "Responsável Contato": linha.get("responsavel_ultimo_contato_cnh", ""),
                "Data Prevista": _valor_data_excel(linha.get("data_prevista_regularizacao_cnh")),
                "Observação": linha.get("observacao_cnh", ""),
                "Inconsistências": linha.get("inconsistencias_texto", ""),
            }
        )
    return pd.DataFrame(registros)


def _tipo_cobranca_cnh(linha: dict) -> str:
    status = linha.get("status_tecnico")
    if status == "VENCIDA":
        return "CNH vencida"
    if status in {"CRITICA_7_DIAS", "ALERTA_30_DIAS"}:
        return "CNH a vencer"
    if status in {"SEM_VALIDADE", "DATA_INVALIDA"}:
        return "Corrigir validade"
    return "Revisar cadastro"


def _prazo_cnh(linha: dict) -> str:
    dias = linha.get("dias_para_vencer")
    if dias is None:
        return "-"
    if dias < 0:
        return f"Vencida ha {abs(dias)} dias"
    if dias == 0:
        return "Vence hoje"
    return f"Faltam {dias} dias"


def _montar_dataframe_cobranca(linhas: list[dict]) -> pd.DataFrame:
    registros = []
    for linha in sorted(
        linhas,
        key=lambda item: (
            str(item.get("frente_exibicao") or "SEM ESCALA"),
            item.get("prioridade_ordem", 999),
            item.get("dias_para_vencer") if item.get("dias_para_vencer") is not None else 999999,
            str(item.get("nome") or ""),
        ),
    ):
        registros.append(
            {
                "Tipo de cobrança": _tipo_cobranca_cnh(linha),
                "Prioridade": linha.get("prioridade_label", ""),
                "Frente": linha.get("frente_exibicao", ""),
                "Código": linha.get("codigo_colaborador", ""),
                "Nome": linha.get("nome", ""),
                "Função": linha.get("funcao_exibicao", ""),
                "Turno": linha.get("turno_safra", ""),
                "Horário": linha.get("horario", ""),
                "Categoria": linha.get("categoria_cnh", ""),
                "Validade CNH": _valor_data_excel(linha.get("validade_cnh")),
                "Situação CNH": linha.get("status_tecnico_label", ""),
                "Prazo": _prazo_cnh(linha),
                "Gestor": linha.get("gestor_exibicao", ""),
                "Status da cobrança": linha.get("status_acompanhamento_label", ""),
                "Último contato": _valor_data_excel(linha.get("ultimo_contato_cnh")),
                "Próxima ação": _valor_data_excel(linha.get("data_prevista_regularizacao_cnh")),
                "Observação RH": linha.get("observacao_cnh", ""),
                "Inconsistências": linha.get("inconsistencias_texto", ""),
            }
        )
    return pd.DataFrame(registros)


def _nome_aba_frente(frente: str, nomes_usados: set[str] | None = None) -> str:
    base = corrigir_nome_arquivo_excel(
        str(frente or "SEM ESCALA").strip() or "SEM ESCALA",
        nomes_usados,
    )
    return base[:31] or "SEM ESCALA"


def _aplicar_formato_tabela_cobranca(workbook, worksheet, df: pd.DataFrame, titulo: str, subtitulo: str) -> None:
    total_cols = max(len(df.columns), 1)
    last_col = total_cols - 1
    title_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 16,
            "font_color": "#202467",
            "align": "left",
            "valign": "vcenter",
        }
    )
    subtitle_format = workbook.add_format({"font_color": "#52635d", "font_size": 10})
    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#ffffff",
            "bg_color": "#202467",
            "border": 1,
            "border_color": "#D9E2DC",
            "align": "center",
            "valign": "vcenter",
        }
    )
    cell_format = workbook.add_format({"border": 1, "border_color": "#E4EBE6", "valign": "top"})
    text_wrap = workbook.add_format({"border": 1, "border_color": "#E4EBE6", "valign": "top", "text_wrap": True})
    date_format = workbook.add_format({"border": 1, "border_color": "#E4EBE6", "valign": "top", "num_format": "dd/mm/yyyy"})
    red_fill = workbook.add_format({"bg_color": "#FCE4E4", "font_color": "#8A1F1F"})
    amber_fill = workbook.add_format({"bg_color": "#FFF0CC", "font_color": "#7A4B00"})
    green_fill = workbook.add_format({"bg_color": "#E8F3EC", "font_color": "#1F6B43"})

    worksheet.hide_gridlines(2)
    worksheet.merge_range(0, 0, 0, last_col, titulo, title_format)
    worksheet.merge_range(1, 0, 1, last_col, subtitulo, subtitle_format)
    worksheet.merge_range(2, 0, 2, last_col, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_format)

    for col_num, value in enumerate(df.columns.values):
        worksheet.write(4, col_num, value, header_format)

    worksheet.freeze_panes(5, 0)
    if not df.empty:
        worksheet.autofilter(4, 0, len(df) + 4, last_col)

    wide_columns = {"Nome": 28, "Função": 24, "Observação RH": 34, "Inconsistências": 38}
    compact_columns = {"Código": 10, "Turno": 10, "Categoria": 10, "Prazo": 16, "Telefone": 16}
    date_columns = {"Validade CNH", "Último contato", "Próxima ação"}
    for col_num, col in enumerate(df.columns):
        if col in date_columns:
            width = 13
            fmt = date_format
        elif col in wide_columns:
            width = wide_columns[col]
            fmt = text_wrap
        elif col in compact_columns:
            width = compact_columns[col]
            fmt = cell_format
        else:
            serie = df[col].map(lambda valor: "" if pd.isna(valor) else str(valor)) if not df.empty else pd.Series(dtype=str)
            width = min(max((serie.map(len).max() if not serie.empty else 0), len(str(col))) + 2, 24)
            fmt = cell_format
        worksheet.set_column(col_num, col_num, width, fmt)

    if "Situação CNH" in df.columns and not df.empty:
        status_col = df.columns.get_loc("Situação CNH")
        first_row = 5
        last_row = len(df) + 4
        worksheet.conditional_format(first_row, status_col, last_row, status_col, {"type": "text", "criteria": "containing", "value": "Vencida", "format": red_fill})
        worksheet.conditional_format(first_row, status_col, last_row, status_col, {"type": "text", "criteria": "containing", "value": "7 dias", "format": amber_fill})
        worksheet.conditional_format(first_row, status_col, last_row, status_col, {"type": "text", "criteria": "containing", "value": "30 dias", "format": amber_fill})
        worksheet.conditional_format(first_row, status_col, last_row, status_col, {"type": "text", "criteria": "containing", "value": "Regular", "format": green_fill})


def _salvar_cobranca_por_frente_excel(linhas: list[dict], caminho_saida: str) -> None:
    try:
        import xlsxwriter  # noqa: F401
    except ImportError:
        salvar_df_excel_com_total(_montar_dataframe_cobranca(linhas), caminho_saida, "Cobrança CNH")
        return

    df_geral = neutralize_dataframe(_montar_dataframe_cobranca(linhas))
    with caminho_publicacao_atomica(caminho_saida) as caminho_temporario, pd.ExcelWriter(
        caminho_temporario,
        engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False}},
        date_format="dd/mm/yyyy",
        datetime_format="dd/mm/yyyy",
    ) as writer:
        workbook = writer.book
        title_format = workbook.add_format({"bold": True, "font_size": 18, "font_color": "#202467"})
        label_format = workbook.add_format({"bold": True, "font_color": "#26302D", "bg_color": "#E8F3EC", "border": 1, "border_color": "#D9E2DC"})
        value_format = workbook.add_format({"border": 1, "border_color": "#D9E2DC"})
        header_format = workbook.add_format({"bold": True, "font_color": "#ffffff", "bg_color": "#202467", "border": 1})

        resumo = workbook.add_worksheet("Resumo")
        resumo.hide_gridlines(2)
        resumo.write(0, 0, "Operacoes Agricolas - Cobrança de CNH", title_format)
        resumo.write(1, 0, f"CNHs vencidas, a vencer e pendências por frente. Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

        status_counter = Counter(linha.get("status_tecnico") for linha in linhas)
        resumo_rows = [
            ("Total para cobrança", len(linhas)),
            ("CNH vencida", status_counter.get("VENCIDA", 0)),
            ("Vence em até 7 dias", status_counter.get("CRITICA_7_DIAS", 0)),
            ("Vence em até 30 dias", status_counter.get("ALERTA_30_DIAS", 0)),
            ("Sem validade/data inválida", status_counter.get("SEM_VALIDADE", 0) + status_counter.get("DATA_INVALIDA", 0)),
            ("Frentes envolvidas", len({linha.get("frente_exibicao") for linha in linhas})),
        ]
        resumo.write(3, 0, "Indicador", header_format)
        resumo.write(3, 1, "Quantidade", header_format)
        for row_num, (label, value) in enumerate(resumo_rows, start=4):
            resumo.write(row_num, 0, label, label_format)
            resumo.write(row_num, 1, value, value_format)

        frente_counter = Counter(linha.get("frente_exibicao") or "SEM ESCALA" for linha in linhas)
        resumo.write(3, 3, "Frente", header_format)
        resumo.write(3, 4, "Pendências", header_format)
        for row_num, (frente, total) in enumerate(sorted(frente_counter.items(), key=lambda item: (-item[1], item[0])), start=4):
            resumo.write(row_num, 3, frente, value_format)
            resumo.write(row_num, 4, total, value_format)
        resumo.set_column(0, 0, 28)
        resumo.set_column(1, 1, 14)
        resumo.set_column(3, 3, 24)
        resumo.set_column(4, 4, 12)

        df_geral.to_excel(writer, sheet_name="Geral", index=False, startrow=5, header=False)
        _aplicar_formato_tabela_cobranca(
            workbook,
            writer.sheets["Geral"],
            df_geral,
            "Cobrança CNH - Geral",
            "Lista consolidada para cobrança, ordenada por frente e prioridade.",
        )

        nomes_usados = {"Resumo", "Geral"}
        for frente, linhas_frente in sorted(
            defaultdict(list, {frente: [linha for linha in linhas if (linha.get("frente_exibicao") or "SEM ESCALA") == frente] for frente in frente_counter}).items(),
            key=lambda item: item[0],
        ):
            sheet_name = _nome_aba_frente(frente, nomes_usados)
            df_frente = neutralize_dataframe(_montar_dataframe_cobranca(linhas_frente))
            df_frente.to_excel(writer, sheet_name=sheet_name, index=False, startrow=5, header=False)
            _aplicar_formato_tabela_cobranca(
                workbook,
                writer.sheets[sheet_name],
                df_frente,
                f"Cobrança CNH - {frente}",
                "Colaboradores desta frente com CNH vencida, a vencer ou pendência operacional.",
            )


def _pdf_escape(value: str) -> str:
    texto = str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return texto.encode("latin-1", "replace").decode("latin-1")


def _pdf_text(x: int, y: int, text: str, size: int = 9, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET\n"


def _pdf_text_rgb(
    x: int,
    y: int,
    text: str,
    size: int = 9,
    bold: bool = False,
    rgb: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> str:
    font = "F2" if bold else "F1"
    red, green, blue = rgb
    return f"q {red:.3f} {green:.3f} {blue:.3f} rg BT /{font} {size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET Q\n"


def _pdf_line(x1: int, y1: int, x2: int, y2: int, gray: float = 0.82) -> str:
    return f"q {gray:.2f} G 0.7 w {x1} {y1} m {x2} {y2} l S Q\n"


def _pdf_line_rgb(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    rgb: tuple[float, float, float] = (0.74, 0.78, 0.74),
    width: float = 0.7,
) -> str:
    red, green, blue = rgb
    return f"q {red:.3f} {green:.3f} {blue:.3f} RG {width:.1f} w {x1} {y1} m {x2} {y2} l S Q\n"


def _pdf_fill_rect(x: int, y: int, width: int, height: int, gray: float = 0.96) -> str:
    return f"q {gray:.2f} g {x} {y} {width} {height} re f Q\n"


def _pdf_fill_rect_rgb(
    x: int,
    y: int,
    width: int,
    height: int,
    rgb: tuple[float, float, float] = (0.96, 0.97, 0.96),
) -> str:
    red, green, blue = rgb
    return f"q {red:.3f} {green:.3f} {blue:.3f} rg {x} {y} {width} {height} re f Q\n"


def _write_pdf(path: str, pages: list[str]) -> None:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    font_regular_id = 3
    font_bold_id = 4
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    kids = []
    for page_content in pages:
        page_id = len(objects) + 1
        content_id = page_id + 1
        kids.append(f"{page_id} 0 R")
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")
        content_bytes = page_content.encode("latin-1", "replace")
        content_obj = b"<< /Length " + str(len(content_bytes)).encode("ascii") + b" >>\nstream\n" + content_bytes + b"endstream"
        objects.append(page_obj)
        objects.append(content_obj)

    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode("latin-1")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    with open(path, "wb") as file:
        file.write(output)


def _numero_frente_relatorio(frente: str) -> int:
    numero = "".join(ch for ch in str(frente or "") if ch.isdigit())
    return int(numero) if numero else 999


def _dias_vencida_cnh(linha: dict) -> int:
    dias = linha.get("dias_para_vencer")
    if isinstance(dias, int):
        return abs(dias) if dias < 0 else 0

    validade = _parse_data_iso(linha.get("validade_cnh"))
    if not validade:
        return 0
    return max((date.today() - validade).days, 0)


def _texto_dias_vencida(linha: dict) -> str:
    dias = _dias_vencida_cnh(linha)
    if dias == 1:
        return "1 dia"
    return f"{dias} dias"


def _texto_contato_cnh(linha: dict) -> str:
    responsavel = str(linha.get("responsavel_ultimo_contato_cnh") or "").strip()
    gestor = str(linha.get("gestor_exibicao") or linha.get("gestor_responsavel") or "").strip()
    previsao = linha.get("data_prevista_regularizacao_cnh")
    partes = []
    if responsavel:
        partes.append(f"Resp.: {responsavel}")
    elif gestor and gestor != "Não informado":
        partes.append(f"Gestor: {gestor}")
    if previsao:
        partes.append(f"Prev.: {_formatar_data_br(previsao)}")
    return " | ".join(partes) or "-"


def _texto_acompanhamento_cnh(linha: dict) -> str:
    return str(linha.get("status_acompanhamento_label") or linha.get("status_acompanhamento") or "Sem ação")


def _ordenar_linhas_pdf_cnh(linhas: list[dict]) -> list[dict]:
    return sorted(
        linhas,
        key=lambda item: (
            -_dias_vencida_cnh(item),
            str(item.get("funcao_exibicao") or ""),
            str(item.get("nome") or ""),
        ),
    )


def _pdf_metric_card(
    x: int,
    y: int,
    width: int,
    label: str,
    value: str,
    accent: tuple[float, float, float],
) -> str:
    page = _pdf_fill_rect_rgb(x, y - 27, width, 38, (0.972, 0.982, 0.972))
    page += _pdf_fill_rect_rgb(x, y - 27, 4, 38, accent)
    page += _pdf_text_rgb(x + 10, y, label.upper(), 6, True, (0.33, 0.39, 0.36))
    page += _pdf_text_rgb(x + 10, y - 17, shorten(value, width=24, placeholder="..."), 12, True, (0.08, 0.13, 0.11))
    return page


def _cabecalho_tabela_cnh_vencida(y: int) -> tuple[str, int]:
    page = _pdf_fill_rect_rgb(38, y - 5, 520, 16, (0.115, 0.126, 0.360))
    page += _pdf_text_rgb(42, y, "Código", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(82, y, "Nome", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(230, y, "Função/Frota", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(330, y, "Turno", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(378, y, "Validade", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(435, y, "Vencida", 7, True, (1, 1, 1))
    page += _pdf_text_rgb(492, y, "Acomp.", 7, True, (1, 1, 1))
    return page, y - 16


def _linha_tabela_cnh_vencida(linha: dict, y: int, row_index: int = 0) -> tuple[str, int]:
    page = ""
    background = (0.986, 0.990, 0.986) if row_index % 2 == 0 else (1, 1, 1)
    accent = (0.690, 0.212, 0.212) if _dias_vencida_cnh(linha) >= 60 else (0.783, 0.635, 0.290)
    page += _pdf_fill_rect_rgb(38, y - 15, 520, 21, background)
    page += _pdf_fill_rect_rgb(38, y - 15, 3, 21, accent)
    page += _pdf_text_rgb(45, y, shorten(str(linha.get("codigo_colaborador") or "-"), width=8, placeholder="..."), 7, True, (0.12, 0.14, 0.33))
    page += _pdf_text_rgb(82, y, shorten(str(linha.get("nome") or "-"), width=34, placeholder="..."), 7, True, (0.08, 0.12, 0.10))
    page += _pdf_text_rgb(230, y, shorten(str(linha.get("funcao_exibicao") or "-"), width=24, placeholder="..."), 7, False, (0.18, 0.24, 0.22))
    page += _pdf_text_rgb(330, y, shorten(str(linha.get("turno_safra") or "-"), width=8, placeholder="..."), 7, False, (0.18, 0.24, 0.22))
    page += _pdf_text_rgb(378, y, str(linha.get("validade_cnh_formatada") or "-"), 7, False, (0.18, 0.24, 0.22))
    page += _pdf_text_rgb(435, y, _texto_dias_vencida(linha), 7, True, (0.58, 0.16, 0.16))
    page += _pdf_text_rgb(492, y, shorten(_texto_acompanhamento_cnh(linha), width=16, placeholder="..."), 7, False, (0.18, 0.24, 0.22))
    y -= 10
    page += _pdf_text_rgb(82, y, shorten(_texto_contato_cnh(linha), width=78, placeholder="..."), 6, False, (0.38, 0.45, 0.42))
    y -= 7
    page += _pdf_line_rgb(38, y + 2, 558, y + 2, (0.90, 0.93, 0.91), 0.5)
    return page, y - 4


def gerar_pdf_cnh_vencidas_por_frente(db_path: str, caminho_saida: str) -> int:
    linhas = [
        linha
        for linha in listar_painel_cnh(db_path)[0]
        if linha.get("status_tecnico") == "VENCIDA"
        and str(linha.get("frente_exibicao") or "").strip().upper().startswith("FRENTE")
    ]
    por_frente: dict[str, list[dict]] = defaultdict(list)
    for linha in linhas:
        por_frente[linha.get("frente_exibicao") or "SEM ESCALA"].append(linha)

    def frente_key(item: tuple[str, list[dict]]) -> tuple[int, str]:
        texto = item[0]
        return (_numero_frente_relatorio(texto), texto)

    pages: list[str] = []
    page = ""
    y = 800

    def new_page(title: str) -> None:
        nonlocal page, y
        if page:
            pages.append(page)
        page = ""
        y = 794
        page += _pdf_fill_rect_rgb(0, 812, 595, 30, (0.115, 0.126, 0.360))
        page += _pdf_text_rgb(38, 824, "Operacoes Agricolas | Gestor de Colaboradores", 12, True, (1, 1, 1))
        page += _pdf_text_rgb(430, 824, datetime.now().strftime("Gerado em %d/%m/%Y %H:%M"), 8, False, (0.90, 0.93, 1.0))
        page += _pdf_text_rgb(38, y, title, 14, True, (0.08, 0.13, 0.11))
        y -= 14
        page += _pdf_text_rgb(38, y, f"Total vencidas: {len(linhas)} | Frentes impactadas: {len(por_frente)}", 8, False, (0.36, 0.43, 0.40))
        y -= 10
        page += _pdf_line_rgb(38, y, 558, y, (0.200, 0.490, 0.310), 1.0)
        y -= 20

    new_page("Relatório de CNHs vencidas por frente")
    if not linhas:
        page += _pdf_text(42, y, "Nenhuma CNH vencida encontrada no momento.", 11)
    else:
        maiores_frentes = sorted(por_frente.items(), key=lambda item: (-len(item[1]), frente_key(item)))
        maior_frente, maior_grupo = maiores_frentes[0]
        com_previsao = sum(1 for linha in linhas if linha.get("data_prevista_regularizacao_cnh"))
        maior_vencimento = max((_dias_vencida_cnh(linha) for linha in linhas), default=0)

        page += _pdf_text_rgb(42, y, "Resumo operacional", 11, True, (0.08, 0.13, 0.11))
        y -= 16
        resumo_itens = [
            ("Total vencidas", str(len(linhas))),
            ("Frentes", str(len(por_frente))),
            ("Maior concentração", f"{maior_frente} ({len(maior_grupo)})"),
            ("Mais antiga", f"{maior_vencimento} dias"),
            ("Com previsão", str(com_previsao)),
        ]
        for idx, (rotulo, valor) in enumerate(resumo_itens):
            x = 42 + (idx % 3) * 170
            if idx and idx % 3 == 0:
                y -= 44
            accent = (0.690, 0.212, 0.212) if idx in {0, 3} else (0.200, 0.490, 0.310)
            page += _pdf_metric_card(x, y, 154, rotulo, valor, accent)

        y -= 58
        page += _pdf_text_rgb(42, y, "Resumo por frente", 11, True, (0.08, 0.13, 0.11))
        y -= 15
        page += _pdf_fill_rect_rgb(42, y - 5, 480, 15, (0.115, 0.126, 0.360))
        page += _pdf_text_rgb(48, y, "Frente", 8, True, (1, 1, 1))
        page += _pdf_text_rgb(210, y, "Vencidas", 8, True, (1, 1, 1))
        page += _pdf_text_rgb(292, y, "Mais antiga", 8, True, (1, 1, 1))
        page += _pdf_text_rgb(390, y, "Gestores/Responsáveis", 8, True, (1, 1, 1))
        y -= 15

        for row_index, (frente, itens) in enumerate(sorted(por_frente.items(), key=frente_key)):
            if y < 60:
                new_page("Relatório de CNHs vencidas por frente")
                page += _pdf_text_rgb(42, y, "Resumo por frente", 11, True, (0.08, 0.13, 0.11))
                y -= 15
            if row_index % 2 == 0:
                page += _pdf_fill_rect_rgb(42, y - 5, 480, 13, (0.986, 0.990, 0.986))
            gestores = sorted(
                {
                    str(item.get("gestor_exibicao") or item.get("gestor_responsavel") or "").strip()
                    for item in itens
                    if str(item.get("gestor_exibicao") or item.get("gestor_responsavel") or "").strip()
                    and str(item.get("gestor_exibicao") or item.get("gestor_responsavel") or "").strip() != "Não informado"
                }
            )
            page += _pdf_text_rgb(48, y, shorten(frente, width=28, placeholder="..."), 8, True, (0.12, 0.14, 0.33))
            page += _pdf_text_rgb(220, y, str(len(itens)), 8, True, (0.58, 0.16, 0.16))
            page += _pdf_text_rgb(292, y, f"{max(_dias_vencida_cnh(item) for item in itens)} dias", 8, False, (0.18, 0.24, 0.22))
            page += _pdf_text_rgb(390, y, shorten(", ".join(gestores) or "-", width=32, placeholder="..."), 8, False, (0.18, 0.24, 0.22))
            y -= 12

        for frente, itens in sorted(por_frente.items(), key=frente_key):
            new_page(f"{frente} | CNHs vencidas")
            maior_dias_frente = max((_dias_vencida_cnh(item) for item in itens), default=0)
            com_previsao_frente = sum(1 for item in itens if item.get("data_prevista_regularizacao_cnh"))
            page += _pdf_metric_card(42, y, 150, "Vencidas", str(len(itens)), (0.690, 0.212, 0.212))
            page += _pdf_metric_card(208, y, 150, "Mais antiga", f"{maior_dias_frente} dias", (0.783, 0.635, 0.290))
            page += _pdf_metric_card(374, y, 150, "Com previsão", str(com_previsao_frente), (0.115, 0.126, 0.360))
            y -= 50
            page += _pdf_text_rgb(42, y, "Lista de cobrança da frente", 10, True, (0.08, 0.13, 0.11))
            y -= 14
            header, y = _cabecalho_tabela_cnh_vencida(y)
            page += header
            for row_index, linha in enumerate(_ordenar_linhas_pdf_cnh(itens)):
                if y < 62:
                    new_page("Relatório de CNHs vencidas por frente")
                    page += _pdf_text_rgb(42, y, f"{frente} | continuação", 11, True, (0.08, 0.13, 0.11))
                    y -= 14
                    header, y = _cabecalho_tabela_cnh_vencida(y)
                    page += header
                row_content, y = _linha_tabela_cnh_vencida(linha, y, row_index)
                page += row_content

    pages.append(page)
    _write_pdf(caminho_saida, pages)
    return len(linhas)


def exportar_lista_cobranca_excel(
    db_path: str,
    caminho_saida: str,
    filtro_status_tecnico: str = "",
    filtro_status_acompanhamento: str = "",
    filtro_frente: str = "",
    filtro_gestor: str = "",
) -> int:
    linhas, _ = listar_painel_cnh(
        db_path,
        filtro_status_tecnico=filtro_status_tecnico,
        filtro_status_acompanhamento=filtro_status_acompanhamento,
        filtro_frente=filtro_frente,
        filtro_gestor=filtro_gestor,
        somente_pendentes=True,
    )
    _salvar_cobranca_por_frente_excel(linhas, caminho_saida)
    return len(linhas)


def exportar_painel_cnh_excel(db_path: str, caminho_saida: str) -> int:
    linhas, _ = listar_painel_cnh(db_path)
    df = _montar_dataframe_operacional(linhas)
    salvar_df_excel_com_total(df, caminho_saida, "Painel CNH")
    return len(linhas)


def agrupar_pendencias_por_gestor(db_path: str) -> dict[str, list[dict]]:
    linhas, _ = listar_painel_cnh(db_path, somente_pendentes=True)
    grupos = defaultdict(list)
    for linha in linhas:
        grupos[linha["gestor_exibicao"]].append(linha)
    return dict(sorted(grupos.items(), key=lambda item: item[0]))
