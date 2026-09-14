# core/front_efficiency_report.py

import sqlite3
import os
from datetime import datetime, timedelta
from collections import defaultdict
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import cm
from core.settings import get_setting
from core.config import DatabaseConfig
from core.date_utils import sql_date_expr
from core.operational_fleet import fleet_type_sql

DB_NAME = "operacao_agricola.db" # (Mantido, embora DatabaseConfig seja usado)

def _hora_para_minutos(hora_str):
    """Converte uma string 'HH:MM' para um total de minutos."""
    if not hora_str or ':' not in hora_str:
        return 0
    try:
        h, m = map(int, hora_str.split(':'))
        return h * 60 + m
    except (ValueError, TypeError):
        return 0

def _minutos_para_hora_formatada(minutos):
    """Converte um total de minutos para o formato 'HHH:MM'."""
    if minutos < 0:
        minutos = 0
    h = int(minutos // 60)
    m = int(minutos % 60)
    return f"{h:02}:{m:02}"

def _sort_key_frente(frente_str):
    """
    Cria uma chave de ordenação que lida com frentes numéricas e textuais.
    """
    try:
        return (0, int(frente_str))
    except ValueError:
        return (1, frente_str)

def _calcular_perda_ate_fim_turno(data_str_db, parou_hora_str, turno_str):
    """
    Calcula a perda real em minutos de uma parada "Em Andamento"
    até o fim do turno correspondente (06:00-18:00 ou 18:00-06:00).
    """
    try:
        parou_dt = datetime.strptime(f"{data_str_db} {parou_hora_str}", "%d-%m-%Y %H:%M")
    except ValueError:
        try:
            parou_dt = datetime.strptime(f"{data_str_db} {parou_hora_str}", "%d/%m/%Y %H:%M")
        except Exception:
            return 0
    perda_minutos = 0

    if turno_str == '1':
        inicio_turno_dt = parou_dt.replace(hour=6, minute=0, second=0, microsecond=0)
        fim_turno_dt = parou_dt.replace(hour=18, minute=0, second=0, microsecond=0)

        if parou_dt < inicio_turno_dt: delta = fim_turno_dt - inicio_turno_dt
        elif parou_dt >= fim_turno_dt: delta = timedelta(minutes=0)
        else: delta = fim_turno_dt - parou_dt
        perda_minutos = int(delta.total_seconds() // 60)

    elif turno_str == '2':
        inicio_turno_dt = parou_dt.replace(hour=18, minute=0, second=0, microsecond=0)
        fim_turno_dt = parou_dt.replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(days=1)

        if parou_dt < inicio_turno_dt: delta = fim_turno_dt - inicio_turno_dt
        elif parou_dt >= fim_turno_dt: delta = timedelta(minutes=0)
        else: delta = fim_turno_dt - parou_dt
        perda_minutos = int(delta.total_seconds() // 60)

    tempo_operacao_minutos = int(get_setting('tempo_operacao_minutos', '600'))
    return min(perda_minutos, tempo_operacao_minutos)


def gerar_relatorio_eficiencia_frentes(data_inicial_str, data_final_str, output_path='.'):
    """
    Gera um relatório em PDF da eficiência de Colheita (Gargalo)
    e do Aproveitamento de Transbordo (Logística).
    """
    conn = DatabaseConfig.get_connection()
    cursor = conn.cursor()

    # 1.A. Carregar contagem de COLHEDORAS
    cursor.execute(f"SELECT Frente, COUNT(id) FROM FROTAS_POR_FRENTE WHERE {fleet_type_sql('COLHEDORA')} GROUP BY Frente")
    contagem_colhedoras = dict(cursor.fetchall())

    # 1.B. Carregar contagem de TRANSBORDOS
    cursor.execute(f"SELECT Frente, COUNT(id) FROM FROTAS_POR_FRENTE WHERE {fleet_type_sql('TRANSBORDO')} GROUP BY Frente")
    contagem_transbordos = dict(cursor.fetchall())

    start_iso = datetime.strptime(data_inicial_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    end_iso = datetime.strptime(data_final_str, "%d/%m/%Y").strftime("%Y-%m-%d")

    paradas_colhedora_dict = defaultdict(int)
    paradas_transbordo_dict = defaultdict(int)

    # 2.A. Buscar paradas FINALIZADAS (COLHEDORA)
    query_final_colh = """
        SELECT Frente, Total_Hora_Parado
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE Status_Parada = 'Finalizada'
          AND {colhedora_filter}
          AND {date_expr} BETWEEN ? AND ?
    """
    query_final_colh = query_final_colh.format(
        colhedora_filter=fleet_type_sql("COLHEDORA"),
        date_expr=sql_date_expr("Data"),
    )
    cursor.execute(query_final_colh, (start_iso, end_iso))
    for frente, total_parado_str in cursor.fetchall():
        paradas_colhedora_dict[frente] += _hora_para_minutos(total_parado_str)

    # 2.B. Buscar paradas FINALIZADAS (TRANSBORDO)
    query_final_transb = """
        SELECT Frente, Total_Hora_Parado
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE Status_Parada = 'Finalizada'
          AND {transbordo_filter}
          AND {date_expr} BETWEEN ? AND ?
    """
    query_final_transb = query_final_transb.format(
        transbordo_filter=fleet_type_sql("TRANSBORDO"),
        date_expr=sql_date_expr("Data"),
    )
    cursor.execute(query_final_transb, (start_iso, end_iso))
    for frente, total_parado_str in cursor.fetchall():
        paradas_transbordo_dict[frente] += _hora_para_minutos(total_parado_str)


    # 3.A. Buscar paradas EM ANDAMENTO (COLHEDORA)
    query_andamento_colh = """
        SELECT Data, Frente, Turno, Parou_Hora
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE Status_Parada = 'Em Andamento'
          AND {colhedora_filter}
          AND {date_expr} BETWEEN ? AND ?
    """
    query_andamento_colh = query_andamento_colh.format(
        colhedora_filter=fleet_type_sql("COLHEDORA"),
        date_expr=sql_date_expr("Data"),
    )
    cursor.execute(query_andamento_colh, (start_iso, end_iso))
    for data_db, frente, turno, parou_hora in cursor.fetchall():
        if parou_hora and parou_hora != ":":
            perda = _calcular_perda_ate_fim_turno(data_db, parou_hora, turno)
            paradas_colhedora_dict[frente] += perda

    # 3.B. Buscar paradas EM ANDAMENTO (TRANSBORDO)
    query_andamento_transb = """
        SELECT Data, Frente, Turno, Parou_Hora
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE Status_Parada = 'Em Andamento'
          AND {transbordo_filter}
          AND {date_expr} BETWEEN ? AND ?
    """
    query_andamento_transb = query_andamento_transb.format(
        transbordo_filter=fleet_type_sql("TRANSBORDO"),
        date_expr=sql_date_expr("Data"),
    )
    cursor.execute(query_andamento_transb, (start_iso, end_iso))
    for data_db, frente, turno, parou_hora in cursor.fetchall():
        if parou_hora and parou_hora != ":":
            perda = _calcular_perda_ate_fim_turno(data_db, parou_hora, turno)
            paradas_transbordo_dict[frente] += perda

    conn.close()

    # 4. Calcular a eficiência para cada frente
    tempo_operacao_minutos = int(get_setting('tempo_operacao_minutos', '600'))
    dias_no_periodo = (datetime.strptime(data_final_str, "%d/%m/%Y") - datetime.strptime(data_inicial_str, "%d/%m/%Y")).days + 1

    dados_relatorio = []

    # Pega todas as frentes que têm colhedora OU transbordo
    todas_frentes = sorted(list(set(contagem_colhedoras.keys()) | set(contagem_transbordos.keys())), key=_sort_key_frente)

    for frente in todas_frentes:

        # --- Cálculo da Colhedora (Gargalo) ---
        num_colh = contagem_colhedoras.get(frente, 0)
        disp_colh = num_colh * tempo_operacao_minutos * 2 * dias_no_periodo
        parado_colh = paradas_colhedora_dict.get(frente, 0)
        operado_colh = max(0, disp_colh - parado_colh)
        eficiencia_frente = (operado_colh / disp_colh * 100) if disp_colh > 0 else 100.0 # Se não há colhedoras, não há perda

        # --- Cálculo do Transbordo (Aproveitamento) ---
        num_transb = contagem_transbordos.get(frente, 0)
        disp_transb = num_transb * tempo_operacao_minutos * 2 * dias_no_periodo
        parado_transb = paradas_transbordo_dict.get(frente, 0)
        operado_transb = max(0, disp_transb - parado_transb)
        aproveitamento_transb = (operado_transb / disp_transb * 100) if disp_transb > 0 else 100.0 # Se não há transbordos, não há perda

        dados_relatorio.append([
            frente,
            num_colh,
            f"{eficiencia_frente:.2f}%",
            num_transb,
            f"{aproveitamento_transb:.2f}%",
            _minutos_para_hora_formatada(parado_colh),    # Coluna opcional de Horas Paradas (Colh)
            _minutos_para_hora_formatada(parado_transb) # Coluna opcional de Horas Paradas (Transb)
        ])

    # 5. Gerar o documento PDF
    nome_arquivo = f"Relatorio_Eficiencia_Frentes_{data_inicial_str.replace('/', '-')}_a_{data_final_str.replace('/', '-')}.pdf"

    os.makedirs(output_path, exist_ok=True)
    caminho_completo = os.path.join(output_path, nome_arquivo)

    doc = SimpleDocTemplate(caminho_completo, pagesize=landscape(A4))
    elementos = []
    styles = getSampleStyleSheet()

    elementos.append(Paragraph("Relatório de Eficiência (Gargalo) e Aproveitamento (Logística)", styles['Title']))
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(Paragraph(f"Período Analisado: {data_inicial_str} a {data_final_str}", styles['Normal']))
    elementos.append(Paragraph(f"Cálculo baseado em {dias_no_periodo} dia(s), 2 turnos por dia e tempo de operação de {tempo_operacao_minutos} minutos por turno.", styles['Normal']))
    elementos.append(Spacer(1, 1 * cm))

    tabela_dados = [
        ["Frente", "Nº Colh.", "Eficiência Frente (%)", "Nº Transb.", "Aproveit. Transb. (%)", "H.Parada (Colh)", "H.Parada (Transb)"]
    ] + dados_relatorio

    t = Table(
        tabela_dados,
        colWidths=[2.5*cm, 2.5*cm, 4*cm, 2.5*cm, 4.5*cm, 3.5*cm, 4*cm],
        repeatRows=1,
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9), # Fonte menor
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        # Destaca as métricas principais
        ('TEXTCOLOR', (2, 1), (2, -1), colors.blue),
        ('TEXTCOLOR', (4, 1), (4, -1), colors.green),
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
        ('FONTNAME', (4, 1), (4, -1), 'Helvetica-Bold'),
    ]))
    elementos.append(t)

    doc.build(elementos)
    print(f"Relatório de eficiência por frente gerado em: {caminho_completo}")
    return caminho_completo
