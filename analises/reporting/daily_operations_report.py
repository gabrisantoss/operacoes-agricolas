from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import cm
from collections import defaultdict
import os
from datetime import datetime
from xml.sax.saxutils import escape

# --- ALTERADO: Importando configurações de forma centralizada ---
from core.config import DatabaseConfig
from core.settings import get_setting
from core.date_utils import format_date_for_display, sortable_date, sql_date_expr
from core.operational_fleet import is_colhedora, is_transbordo, is_operational_fleet, operational_fleet_sql
from core.sql_compat import numeric_text_order_sql

# Usando o caminho do banco de dados a partir da configuração central
DB_PATH = DatabaseConfig.DB_PATH


def carregar_frotas_por_frente():
    """
    Carrega as informações de frotas por frente do banco de dados.
    Retorna um dicionário onde a chave é a frente e o valor é uma lista de frotas.
    """
    conn = DatabaseConfig.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='FROTAS_POR_FRENTE'")
    if cursor.fetchone() is None:
        print("Aviso: Tabela 'FROTAS_POR_FRENTE' não encontrada. O cálculo de eficiência pode ser impreciso.")
        conn.close()
        return defaultdict(list)

    cursor.execute("SELECT Frente, Frota FROM FROTAS_POR_FRENTE")
    frotas = cursor.fetchall()
    conn.close()

    estrutura = defaultdict(list)
    for frente, frota in frotas:
        estrutura[str(frente)].append(frota.upper())
    return estrutura

def minutos_para_horas(minutos):
    """
    Converte um total de minutos para o formato HH:MM.
    """
    h = int(minutos // 60)
    m = int(minutos % 60)
    return f"{h:02}:{m:02}"


def format_database_date(date_str):
    return format_date_for_display(date_str)


def get_sortable_date_string(date_str):
    """
    Converte uma data em DD-MM-YYYY para YYYY-MM-DD para ordenação.
    """
    if not date_str:
        return "9999-12-31"
    sortable = sortable_date(date_str)
    if sortable == "9999-12-31":
        print(f"Aviso: Data '{date_str}' com formato inválido para ordenação.")
    return sortable


def _sort_key_frente(frente):
    value = str(frente or "")
    try:
        return (0, int(value), value)
    except ValueError:
        return (1, value.casefold(), value)

def gerar_relatorio(data_inicial=None, data_final=None, frente_filtro=None, turno_filtro=None, frota_filtro=None, pesquisa_geral_texto=None, output_path='.'):
    """
    Gera um relatório em PDF dos dados de RELATORIO_OPERACAO_DIARIA
    com base nos filtros fornecidos.
    """
    conn = DatabaseConfig.get_connection()
    cursor = conn.cursor()

    query = """
    SELECT Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora, Total_Hora_Parado,
           Eficiencia, Fundo_Agricola, Chuva, Incendio
    FROM RELATORIO_OPERACAO_DIARIA
    WHERE 1=1
      AND {operational_fleet_filter}
    """
    query = query.format(
        operational_fleet_filter=operational_fleet_sql("Frota")
    )
    params = []

    if data_inicial:
        try:
            data_inicial_iso = datetime.strptime(data_inicial, "%d-%m-%Y").strftime("%Y-%m-%d")
            query += f" AND {sql_date_expr('Data')} >= ?"
            params.append(data_inicial_iso)
        except ValueError:
            print(f"Aviso: Formato de data inicial inválido para filtro: {data_inicial}")

    if data_final:
        try:
            data_final_iso = datetime.strptime(data_final, "%d-%m-%Y").strftime("%Y-%m-%d")
            query += f" AND {sql_date_expr('Data')} <= ?"
            params.append(data_final_iso)
        except ValueError:
            print(f"Aviso: Formato de data final inválido para filtro: {data_final}")

    if frente_filtro:
        query += " AND Frente=?"
        params.append(frente_filtro)
    if turno_filtro:
        query += " AND Turno=?"
        params.append(turno_filtro)
    if frota_filtro:
        query += " AND Frota LIKE ?"
        params.append(f"%{frota_filtro}%")

    if pesquisa_geral_texto:
        query += """ AND (Data LIKE ? OR Frente LIKE ? OR Frota LIKE ? OR Motivo LIKE ? OR Fundo_Agricola LIKE ? OR Chuva LIKE ? OR Incendio LIKE ?) """
        search_term = f"%{pesquisa_geral_texto}%"
        params.extend([search_term] * 7)

    query += """
    ORDER BY {date_expr}, {frente_order}, Turno
    """
    query = query.format(
        date_expr=sql_date_expr("Data"),
        frente_order=numeric_text_order_sql("Frente", DatabaseConfig.DB_ENGINE),
    )

    cursor.execute(query, params)
    dados = cursor.fetchall()
    conn.close()

    if not dados:
        print("Nenhum dado encontrado para os filtros aplicados.")
        return

    agrupados = defaultdict(list)
    resumo_dados = defaultdict(lambda: {"total": 0, "colhedora": 0, "transbordo": 0})

    for row in dados:
        data, frente, turno, frota = row[0], str(row[1]), row[2], row[3].upper() if row[3] else ""
        key = (data, frente)
        agrupados[key].append(row)

        total_parado_str = row[7]
        minutos = 0
        if total_parado_str and ':' in total_parado_str:
            try:
                h, m = map(int, total_parado_str.split(':'))
                minutos = h * 60 + m
            except (ValueError, TypeError):
                minutos = 0

        resumo_key = (data, frente, turno)
        resumo_dados[resumo_key]["total"] += minutos
        if is_colhedora(frota):
            resumo_dados[resumo_key]["colhedora"] += minutos
        elif is_transbordo(frota):
            resumo_dados[resumo_key]["transbordo"] += minutos

    data_nome_arquivo = ""
    if data_inicial and data_final:
        data_nome_arquivo = f"{data_inicial}_a_{data_final}"
    elif data_inicial:
        data_nome_arquivo = data_inicial
    else:
        data_nome_arquivo = "Todas_Datas"

    turno_nome = f"_Turno_{turno_filtro}" if turno_filtro else "_Geral"
    nome_base = f"Relatorio_Operacao_{data_nome_arquivo.replace('/', '-')}{turno_nome}.pdf"

    output_path = output_path or '.'
    os.makedirs(output_path, exist_ok=True)
    caminho_completo = os.path.join(output_path, nome_base)

    contador = 1
    nome_arquivo_final = caminho_completo
    while os.path.exists(nome_arquivo_final):
        base, ext = os.path.splitext(caminho_completo)
        nome_arquivo_final = f"{base}_{contador}{ext}"
        contador += 1

    doc = SimpleDocTemplate(nome_arquivo_final, pagesize=A4, rightMargin=1*cm, leftMargin=1*cm, topMargin=1*cm, bottomMargin=1*cm)
    elementos = []
    styles = getSampleStyleSheet()
    estilo_motivo = ParagraphStyle(name='motivo_style', parent=styles['BodyText'], fontSize=8, alignment=1, wordWrap='CJK')

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.drawCentredString(A4[0]/2.0, 1*cm, f"Página {doc.page}")
        canvas.restoreState()

    elementos.append(Paragraph("<b>RELATÓRIO DE OPERAÇÃO DIÁRIA MECANIZADA</b>", styles["Title"]))

    filtros_detalhes = []
    if data_inicial: filtros_detalhes.append(f"Data Inicial: {data_inicial.replace('-', '/')}")
    if data_final: filtros_detalhes.append(f"Data Final: {data_final.replace('-', '/')}")
    if frente_filtro: filtros_detalhes.append(f"Frente: {frente_filtro}")
    if turno_filtro: filtros_detalhes.append(f"Turno: {turno_filtro}")

    filtro_info_text = "Filtros Aplicados: " + (", ".join(filtros_detalhes) if filtros_detalhes else "Nenhum")
    elementos.append(Paragraph(escape(filtro_info_text), styles["Normal"]))
    elementos.append(Spacer(1, 0.5*cm))

    cabecalho = ['FRENTE', 'TURNO', 'FROTA', 'MOTIVO', 'PAROU', 'VOLTOU', 'TOTAL H', 'EFICIÊNCIA']
    sorted_agrupados_keys = sorted(
        agrupados.keys(),
        key=lambda x: (get_sortable_date_string(x[0]), _sort_key_frente(x[1])),
    )

    for data, frente in sorted_agrupados_keys:
        registros = agrupados[(data, frente)]
        primeiro = registros[0]
        data_exibicao = format_database_date(data)
        info = (
            f"<b>DATA:</b> {escape(str(data_exibicao or ''))}  "
            f"<b>FUNDO AGRÍCOLA:</b> {escape(str(primeiro[9] or ''))}  "
            f"<b>CHOVEU:</b> {escape(str(primeiro[10] or ''))}  "
            f"<b>INCÊNDIO:</b> {escape(str(primeiro[11] or ''))}"
        )
        elementos.append(Paragraph(info, styles["Normal"]))
        elementos.append(Spacer(1, 0.3*cm))

        tabela_dados = [cabecalho]
        for row in registros:
            motivo = Paragraph(escape(str(row[4] or "")), estilo_motivo)
            eficiencia_formatada = f"{row[8]:.2f}%" if row[8] is not None else ""
            nova_row = [row[1], row[2], row[3], motivo, row[5], row[6], row[7], eficiencia_formatada]
            tabela_dados.append(nova_row)

        t = Table(tabela_dados, repeatRows=1, colWidths=[2*cm, 1.5*cm, 3*cm, 5*cm, 2*cm, 2*cm, 2*cm, 2*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elementos.append(t)
        elementos.append(Spacer(1, 0.8*cm))

    # Pagina de resumo
    elementos.append(PageBreak())
    elementos.append(Paragraph("<b>RESUMO DE OPERAÇÃO DIÁRIA POR FRENTE</b>", styles["Title"]))
    elementos.append(Spacer(1, 0.4*cm))
    tabela_resumo = [['DATA', 'FRENTE', 'TURNO', 'TOTAL PARADO', 'COLHEDORA', 'TRANSBORDO', 'EFICIÊNCIA (%)']]

    # Carrega a lista completa de frotas para o cálculo preciso da eficiência
    frotas_cadastradas = carregar_frotas_por_frente()

    # Busca a configuração de tempo de operação
    tempo_operacao_configurado = int(get_setting('tempo_operacao_minutos', '600'))

    sorted_resumo_keys = sorted(
        resumo_dados.keys(),
        key=lambda x: (get_sortable_date_string(x[0]), _sort_key_frente(x[1]), x[2]),
    )

    for key_tuple in sorted_resumo_keys:
        data, frente, turno = key_tuple
        info_data = resumo_dados[key_tuple]
        data_exibicao = format_database_date(data)

        total_min = info_data['total']
        colh_min = info_data['colhedora']
        trans_min = info_data['transbordo']

        # Eficiência operacional considera apenas colhedoras e transbordos.
        eficiencia = "N/A"
        frotas_na_frente = frotas_cadastradas.get(frente, [])
        maquinas = len([frota for frota in frotas_na_frente if is_operational_fleet(frota)])
        parada_operacional_min = colh_min + trans_min

        if maquinas > 0:
            tempo_total_esperado = maquinas * tempo_operacao_configurado
            if tempo_total_esperado > 0:
                eficiencia_calculada = max(0, ((tempo_total_esperado - parada_operacional_min) / tempo_total_esperado) * 100)
                eficiencia = f"{eficiencia_calculada:.2f}%"
            else:
                eficiencia = "0.00%"

        tabela_resumo.append([
            data_exibicao, frente, turno,
            minutos_para_horas(total_min),
            minutos_para_horas(colh_min),
            minutos_para_horas(trans_min),
            eficiencia
        ])

    t_resumo = Table(tabela_resumo, repeatRows=1, colWidths=[2.5*cm, 2*cm, 2*cm, 3*cm, 3*cm, 3*cm, 3*cm])
    t_resumo.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(t_resumo)

    doc.build(elementos, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"Relatorio PDF gerado com sucesso: {nome_arquivo_final}")
    return nome_arquivo_final
