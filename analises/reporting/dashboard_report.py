# reporting/dashboard_report.py

import sqlite3
import calendar
import io
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.units import cm
from collections import defaultdict
import os
from datetime import datetime, timedelta
import numpy as np
import matplotlib.pyplot as plt
import statistics
from xml.sax.saxutils import escape

# Importando a lógica de cálculo de perda e configuração
from core.settings import get_setting
from core.config import DatabaseConfig
from core.date_utils import sql_date_expr
from core.operational_fleet import (
    is_colhedora,
    is_transbordo,
    is_operational_fleet as core_is_operational_fleet,
)

# --- INÍCIO DA LÓGICA DE CÁLCULO IMPORTADA ---
# (Esta seção é duplicada de front_efficiency_report.py para que o arquivo funcione)

def _hora_para_minutos(hora_str):
    """Converte uma string 'HH:MM' para um total de minutos."""
    if not hora_str or ':' not in hora_str:
        return 0
    try:
        h, m = map(int, hora_str.split(':'))
        return h * 60 + m
    except (ValueError, TypeError):
        return 0

def _is_operational_fleet(frota):
    """Retorna True para frotas que entram no cálculo operacional."""
    frota_normalizada = (frota or "").upper()
    return core_is_operational_fleet(frota)

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
# --- FIM DA LÓGICA DE CÁLCULO IMPORTADA ---


def _fetch_and_process_data_for_period(start_date_str, end_date_str, frente_filter=None, frota_filter=None):
    """
    Busca e processa dados operacionais e de colheita para um dado período e filtros.
    *** ATUALIZADO: Agora calcula paradas "Em Andamento" proporcionalmente. ***
    """
    conn = DatabaseConfig.get_connection()
    cursor = conn.cursor()

    start_iso = datetime.strptime(start_date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
    end_iso = datetime.strptime(end_date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
    date_expr = sql_date_expr("Data")

    # --- Consulta de Operação (Dividida em Duas) ---

    # 1. Paradas FINALIZADAS
    op_query_final = f"SELECT Data, Total_Hora_Parado, Eficiencia, Motivo, Turno, Frente, Frota FROM RELATORIO_OPERACAO_DIARIA WHERE Status_Parada = 'Finalizada' AND {date_expr} BETWEEN ? AND ?"
    op_params_final = [start_iso, end_iso]
    if frente_filter:
        op_query_final += " AND Frente = ?"
        op_params_final.append(frente_filter)
    if frota_filter:
        op_query_final += " AND Frota = ?"
        op_params_final.append(frota_filter)

    cursor.execute(op_query_final, op_params_final)
    op_data_finalizadas = cursor.fetchall()

    # 2. Paradas EM ANDAMENTO
    op_query_andamento = f"SELECT Data, '00:00', 0.0, Motivo, Turno, Frente, Frota, Parou_Hora FROM RELATORIO_OPERACAO_DIARIA WHERE Status_Parada = 'Em Andamento' AND {date_expr} BETWEEN ? AND ?"
    op_params_andamento = [start_iso, end_iso]
    if frente_filter:
        op_query_andamento += " AND Frente = ?"
        op_params_andamento.append(frente_filter)
    if frota_filter:
        op_query_andamento += " AND Frota = ?"
        op_params_andamento.append(frota_filter)

    cursor.execute(op_query_andamento, op_params_andamento)
    op_data_em_andamento = cursor.fetchall()

    op_data_operacionais_finalizadas = [
        row for row in op_data_finalizadas if _is_operational_fleet(row[6])
    ]
    op_data_operacionais_em_andamento = [
        row for row in op_data_em_andamento if _is_operational_fleet(row[6])
    ]
    op_data_para_graficos = op_data_operacionais_finalizadas + op_data_operacionais_em_andamento

    # --- Consulta de Colheita (Sem Alteração) ---
    colh_query = f"SELECT Area_Colhida, Produtividade, Frente, Data FROM COLHEITA_MECANIZADA WHERE {date_expr} BETWEEN ? AND ?"
    colh_params = [start_iso, end_iso]
    if frente_filter:
        colh_query += " AND Frente = ?"
        colh_params.append(frente_filter)

    cursor.execute(colh_query, colh_params)
    colheita_data = cursor.fetchall()
    conn.close()

    # --- Início dos Cálculos ---
    results = {}
    results['total_registros'] = len(op_data_para_graficos)

    valid_efficiencies = [row[2] for row in op_data_operacionais_finalizadas if row[2] is not None]
    results['media_eficiencia'] = round(statistics.mean(valid_efficiencies), 2) if valid_efficiencies else 0.0
    results['desvio_padrao_eficiencia'] = round(statistics.stdev(valid_efficiencies), 2) if len(valid_efficiencies) > 1 else 0.0

    colhedora_efficiencies = [row[2] for row in op_data_operacionais_finalizadas if is_colhedora(row[6]) and row[2] is not None]
    results['eficiencia_colhedora'] = round(statistics.mean(colhedora_efficiencies), 2) if colhedora_efficiencies else 0.0

    transbordo_efficiencies = [row[2] for row in op_data_operacionais_finalizadas if is_transbordo(row[6]) and row[2] is not None]
    results['eficiencia_transbordo'] = round(statistics.mean(transbordo_efficiencies), 2) if transbordo_efficiencies else 0.0

    results['area_total_colhida'] = sum([row[0] for row in colheita_data if row[0] is not None])
    valid_produtividades = [row[1] for row in colheita_data if row[1] is not None]
    results['produtividade_media'] = statistics.mean(valid_produtividades) if valid_produtividades else 0.0
    total_ton_colhida = sum(row[0] * row[1] for row in colheita_data if row[0] is not None and row[1] is not None)
    results['total_ton_colhida'] = total_ton_colhida

    tempo_op_minutos = int(get_setting('tempo_operacao_minutos', '600'))
    total_operation_minutes_actual = 0
    operation_slots = set()
    downtime_by_reason = {}
    total_downtime_minutes_calculado = 0

    # 1. Processa paradas FINALIZADAS
    for row in op_data_operacionais_finalizadas:
        motivo = row[3] if row[3] else "Não Especificado"
        total_min_parado = _hora_para_minutos(row[1])

        if motivo not in downtime_by_reason:
            downtime_by_reason[motivo] = {'total_minutes': 0, 'count': 0}
        downtime_by_reason[motivo]['total_minutes'] += total_min_parado
        downtime_by_reason[motivo]['count'] += 1

        total_downtime_minutes_calculado += total_min_parado
        operation_slots.add((row[0], row[5], row[4], row[6]))

    # 2. Processa paradas EM ANDAMENTO
    for row in op_data_operacionais_em_andamento:
        motivo = row[3] if row[3] else "Não Especificado"
        perda_pro_rata = 0
        if row[7] and row[7] != ":":
            perda_pro_rata = _calcular_perda_ate_fim_turno(row[0], row[7], row[4]) # row[0]=Data, row[7]=Parou_Hora, row[4]=Turno

        if motivo not in downtime_by_reason:
            downtime_by_reason[motivo] = {'total_minutes': 0, 'count': 0}
        downtime_by_reason[motivo]['total_minutes'] += perda_pro_rata
        downtime_by_reason[motivo]['count'] += 1

        total_downtime_minutes_calculado += perda_pro_rata
        operation_slots.add((row[0], row[5], row[4], row[6]))

    results['downtime_by_reason'] = downtime_by_reason
    results['total_downtime_minutes'] = total_downtime_minutes_calculado
    total_nominal_minutes_available = len(operation_slots) * tempo_op_minutos

    total_operation_minutes_actual = total_nominal_minutes_available - total_downtime_minutes_calculado
    if total_operation_minutes_actual < 0:
        total_operation_minutes_actual = 0

    results['total_operation_minutes_actual'] = total_operation_minutes_actual
    results['utilizacao_equipamentos'] = (total_operation_minutes_actual / total_nominal_minutes_available * 100) if total_nominal_minutes_available > 0 else 0

    max_avg_downtime_reason, max_avg_downtime_value = "Nenhum", 0.0
    for motivo, data in downtime_by_reason.items():
        if data['count'] > 0:
            avg_downtime = data['total_minutes'] / data['count']
            if avg_downtime > max_avg_downtime_value:
                max_avg_downtime_value = avg_downtime
                max_avg_downtime_reason = motivo
    results['maior_tempo_medio_parada'] = max_avg_downtime_reason
    results['maior_tempo_medio_parada_valor'] = max_avg_downtime_value

    max_percent_downtime_reason, max_percent_downtime_value = "Nenhum", 0.0
    if total_nominal_minutes_available > 0:
        for motivo, data in downtime_by_reason.items():
            percent_downtime = (data['total_minutes'] / total_nominal_minutes_available) * 100
            if percent_downtime > max_percent_downtime_value:
                max_percent_downtime_value = percent_downtime
                max_percent_downtime_reason = motivo
    results['maior_percentual_tempo_parado'] = max_percent_downtime_reason
    results['maior_percentual_tempo_parado_valor'] = max_percent_downtime_value

    efficiency_by_turn = {}
    for row in op_data_operacionais_finalizadas:
        turno = row[4] if row[4] else "Não Informado"
        eficiencia = row[2]
        if eficiencia is not None:
            if turno not in efficiency_by_turn:
                efficiency_by_turn[turno] = {'total_eff': 0, 'count': 0}
            efficiency_by_turn[turno]['total_eff'] += eficiencia
            efficiency_by_turn[turno]['count'] += 1
    results['efficiency_by_turn'] = efficiency_by_turn

    productivity_by_frente = {}
    for area, prod, frente, _ in colheita_data:
        if frente not in productivity_by_frente:
            productivity_by_frente[frente] = {'total_ton': 0.0}
        if area is not None and prod is not None:
            productivity_by_frente[frente]['total_ton'] += (area * prod)
    results['productivity_by_frente'] = productivity_by_frente

    # Retorna apenas as frotas operacionais para os gráficos de eficiência.
    return results, op_data_operacionais_finalizadas, colheita_data


def _shift_months(date_obj, months):
    """Desloca uma data por uma quantidade de meses preservando o dia válido."""
    month_index = (date_obj.month - 1) + months
    year = date_obj.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(date_obj.day, calendar.monthrange(year, month)[1])
    return date_obj.replace(year=year, month=month, day=day)


def _get_comparison_period(start_date_str, end_date_str, comparison_type):
    """Retorna o período comparativo equivalente ao filtro atual."""
    if comparison_type == "Nenhuma Comparação":
        return None

    start_date = datetime.strptime(start_date_str, "%d-%m-%Y")
    end_date = datetime.strptime(end_date_str, "%d-%m-%Y")

    months_by_type = {
        "Mês Passado": -1,
        "Trimestre Passado": -3,
        "Ano Passado": -12,
    }
    months_to_shift = months_by_type.get(comparison_type)
    if months_to_shift is None:
        return None

    comparison_start = _shift_months(start_date, months_to_shift)
    comparison_end = _shift_months(end_date, months_to_shift)
    return (
        comparison_start.strftime("%d-%m-%Y"),
        comparison_end.strftime("%d-%m-%Y"),
    )


def build_dashboard_context(start_date_str, end_date_str, frente_filter=None, frota_filter=None, comparison_type="Nenhuma Comparação"):
    """
    Centraliza a coleta de dados do dashboard para a interface e para o PDF.
    """
    current_data, op_data, colheita_data = _fetch_and_process_data_for_period(
        start_date_str, end_date_str, frente_filter, frota_filter
    )

    comparison_period = _get_comparison_period(start_date_str, end_date_str, comparison_type)
    comparison_data = {}
    if comparison_period:
        comparison_data, _, _ = _fetch_and_process_data_for_period(
            comparison_period[0], comparison_period[1], frente_filter, frota_filter
        )

    return current_data, op_data, colheita_data, comparison_data, comparison_period

# ===================================================================
# INÍCIO DAS FUNÇÕES DE PLOTAGEM (QUE FALTAVAM)
# ===================================================================

def set_light_plot_theme(ax):
    """Define um tema claro para o gráfico (não usado no tema escuro)"""
    ax.set_facecolor('white')
    ax.tick_params(colors='black', labelsize=8, pad=5)
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    for spine in ax.spines.values():
        spine.set_color('black')
    ax.grid(True, linestyle='--', alpha=0.7, color='#D0D0D0')

def plot_efficiency_over_time(op_data, start_date_str, end_date_str, fig, subplot_pos):
    """Plota a eficiência média diária ao longo do tempo."""
    ax = fig.add_subplot(subplot_pos)
    daily_efficiency = {}
    try:
        # Converte datas de 'dd-mm-yyyy' para 'dd/mm/yyyy' para o objeto datetime
        start_date_obj = datetime.strptime(start_date_str.replace("-", "/"), "%d/%m/%Y")
        end_date_obj = datetime.strptime(end_date_str.replace("-", "/"), "%d/%m/%Y")
    except ValueError:
        ax.text(0.5, 0.5, "Formato de data inválido.", ha='center', va='center')
        ax.set_title("Eficiência Média Diária (%)", fontsize=10)
        return ax

    for data_str, _, eficiencia, _, _, _, _ in op_data: # op_data aqui são as finalizadas
        if data_str and eficiencia is not None:
            try:
                date_obj = datetime.strptime(data_str, "%d-%m-%Y").date()
                if date_obj not in daily_efficiency:
                    daily_efficiency[date_obj] = []
                daily_efficiency[date_obj].append(eficiencia)
            except ValueError:
                pass # Ignora datas mal formatadas

    all_dates = [start_date_obj + timedelta(days=i) for i in range((end_date_obj - start_date_obj).days + 1)]
    efficiencies_to_plot = [statistics.mean(daily_efficiency.get(d.date(), [0])) for d in all_dates]

    if not all_dates or all(e == 0.0 for e in efficiencies_to_plot):
        ax.text(0.5, 0.5, "Sem dados de eficiência.", ha='center', va='center')
    else:
        labels = [d.strftime('%d/%m') for d in all_dates]
        x_pos = np.arange(len(labels))
        ax.plot(x_pos, efficiencies_to_plot, marker='o', linestyle='-', color='#28A745')

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=60, ha='right', fontsize=7)
        ax.xaxis.set_major_locator(plt.MaxNLocator(nbins=10, integer=True))

    ax.set_title('Eficiência Média Diária (%)', fontsize=10)
    ax.set_ylabel('Eficiência (%)')
    ax.set_ylim(0, 100)
    return ax

def plot_productivity_by_frente(productivity_by_frente, fig, subplot_pos):
    """Plota a produtividade total por frente."""
    ax = fig.add_subplot(subplot_pos)
    if not productivity_by_frente or all(v['total_ton'] == 0 for v in productivity_by_frente.values()):
        ax.text(0.5, 0.5, "Sem dados de produtividade.", ha='center', va='center')
    else:
        sorted_frentes = sorted(productivity_by_frente.items(), key=lambda item: item[1]['total_ton'], reverse=True)
        frentes = [_short_axis_label(item[0], max_chars=18) for item in sorted_frentes]
        total_prod = [item[1]['total_ton'] for item in sorted_frentes]
        ax.bar(frentes, total_prod, color='#007BFF')
    ax.set_title('Produtividade Total por Frente', fontsize=10)
    ax.set_ylabel('Produtividade Total (ton)')
    ax.tick_params(axis='x', labelrotation=25, labelsize=8)
    return ax

def plot_operation_vs_downtime(total_operation_minutes_actual, total_downtime_minutes, fig, subplot_pos):
    """Plota um gráfico de barras de Horas de Operação vs. Paradas."""
    ax = fig.add_subplot(subplot_pos)
    hours = [total_operation_minutes_actual / 60, total_downtime_minutes / 60]
    if sum(hours) == 0:
        ax.text(0.5, 0.5, "Sem dados de operação.", ha='center', va='center')
    else:
        labels = ['Horas de Operação Real', 'Horas Paradas']
        colors = ['#28A745', '#DC3545']
        ax.bar(labels, hours, color=colors)
        for i, v in enumerate(hours):
            ax.text(i, v + (max(hours)*0.02), f"{v:.2f}h", ha='center', va='bottom', fontsize=9)
    ax.set_title('Horas de Operação vs. Paradas', fontsize=10)
    ax.set_ylabel('Total de Horas')
    return ax

def plot_fleet_efficiency_over_time(op_data, start_date_str, end_date_str, fig, subplot_pos):
    """Plota a eficiência das frotas (Colhedora vs. Transbordo) ao longo do tempo."""
    ax = fig.add_subplot(subplot_pos)
    daily_eff_colhedora, daily_eff_transbordo = {}, {}
    try:
        start_date_obj = datetime.strptime(start_date_str.replace("-", "/"), "%d/%m/%Y")
        end_date_obj = datetime.strptime(end_date_str.replace("-", "/"), "%d/%m/%Y")
    except ValueError:
        ax.text(0.5, 0.5, "Formato de data inválido.", ha='center', va='center')
        ax.set_title("Eficiência da Frota", fontsize=10)
        return ax

    for data_str, _, eficiencia, _, _, _, frota in op_data: # op_data são as finalizadas
        if data_str and eficiencia is not None and frota:
            try:
                date_obj = datetime.strptime(data_str, "%d-%m-%Y").date()
                if is_colhedora(frota):
                    if date_obj not in daily_eff_colhedora: daily_eff_colhedora[date_obj] = []
                    daily_eff_colhedora[date_obj].append(eficiencia)
                elif is_transbordo(frota):
                    if date_obj not in daily_eff_transbordo: daily_eff_transbordo[date_obj] = []
                    daily_eff_transbordo[date_obj].append(eficiencia)
            except ValueError:
                pass

    all_dates = [start_date_obj + timedelta(days=i) for i in range((end_date_obj - start_date_obj).days + 1)]
    eff_colhedora = [statistics.mean(daily_eff_colhedora.get(d.date(), [0])) for d in all_dates]
    eff_transbordo = [statistics.mean(daily_eff_transbordo.get(d.date(), [0])) for d in all_dates]

    if not any(e > 0 for e in eff_colhedora) and not any(e > 0 for e in eff_transbordo):
        ax.text(0.5, 0.5, "Sem dados de eficiência de frota.", ha='center', va='center')
    else:
        labels = [d.strftime('%d/%m') for d in all_dates]
        x_pos = np.arange(len(labels))
        ax.plot(x_pos, eff_colhedora, marker='o', linestyle='-', color='#007BFF', label='Colhedora')
        ax.plot(x_pos, eff_transbordo, marker='x', linestyle='--', color='#FFC107', label='Transbordo')

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=60, ha='right', fontsize=7)
        ax.xaxis.set_major_locator(plt.MaxNLocator(nbins=10, integer=True))

        ax.legend(fontsize=8)

    ax.set_title('Eficiência da Frota ao Longo do Tempo', fontsize=10)
    ax.set_ylabel('Eficiência (%)')
    ax.set_ylim(0, 100)
    return ax

def plot_comparison_metrics(current_data, comparison_data, comparison_type, fig, subplot_pos):
    """Plota um gráfico de barras comparando métricas chave."""
    ax = fig.add_subplot(subplot_pos)
    labels = ["Eficiência Média (%)", "Produtividade Total (ton)"]
    current_values = [current_data.get('media_eficiencia', 0), current_data.get('total_ton_colhida', 0)]
    comparison_values = [comparison_data.get('media_eficiencia', 0), comparison_data.get('total_ton_colhida', 0)]

    has_comparison = comparison_type != "Nenhuma Comparação" and bool(comparison_data)

    if sum(current_values) == 0 and sum(comparison_values) == 0:
        ax.text(0.5, 0.5, "Sem dados para comparação.", ha='center', va='center')
    elif not has_comparison:
        ax.bar(labels, current_values, color='#17A2B8')
        ax.set_title('Métricas Chave do Período', fontsize=10)
    else:
        x = np.arange(len(labels))
        width = 0.35
        rects1 = ax.bar(x - width/2, current_values, width, label='Período Atual', color='#17A2B8')
        rects2 = ax.bar(x + width/2, comparison_values, width, label=comparison_type, color='#6C757D')
        ax.set_xticks(x, labels, rotation=15, ha='right', fontsize=8)
        ax.legend(fontsize=8)
        ax.set_title('Comparativo de Métricas Chave', fontsize=10)
    ax.set_ylabel('Valor')
    return ax

def plot_downtime_pareto(downtime_by_reason, fig, subplot_pos):
    """Plota um gráfico de Pareto dos motivos de parada."""
    ax = fig.add_subplot(subplot_pos)
    if not downtime_by_reason or all(v['total_minutes'] == 0 for v in downtime_by_reason.values()):
        ax.text(0.5, 0.5, "Sem dados de tempo de parada.", ha='center', va='center')
    else:
        sorted_downtime = sorted(downtime_by_reason.items(), key=lambda item: item[1]['total_minutes'], reverse=True)
        reasons = [_short_axis_label(item[0], max_chars=20) for item in sorted_downtime][:10] # Limita a top 10
        minutes = [item[1]['total_minutes'] for item in sorted_downtime][:10]
        x_pos = np.arange(len(reasons))

        ax.bar(x_pos, minutes, color='#FF8C00')
        ax2 = ax.twinx()

        # Garante que a soma não seja zero para evitar divisão por zero
        total_minutes_sum = np.sum(minutes)
        if total_minutes_sum > 0:
            cumulative_percentage = np.cumsum(minutes) / total_minutes_sum * 100
            ax2.plot(x_pos, cumulative_percentage, color='#8A2BE2', marker='D', ms=5)

        ax.set_xticks(x_pos)
        ax.set_xticklabels(reasons, rotation=28, ha='right', fontsize=7)
        ax2.set_ylim(0, 105)
        ax2.set_ylabel('Porcentagem Acumulada (%)')
    ax.set_title('Análise de Pareto - Motivos de Parada', fontsize=10)
    ax.set_ylabel('Total de Minutos Parados')
    return ax


def _short_axis_label(value, max_chars=24):
    """Encurta rótulos longos para evitar que os gráficos estourem a tela."""
    label = " ".join(str(value).split())
    if len(label) <= max_chars:
        return label
    return f"{label[:max_chars - 3].rstrip()}..."


def _apply_axis_theme(ax, dark_theme=False):
    """Aplica o tema visual ao eixo do gráfico."""
    if dark_theme:
        background = '#3a3a3a'
        foreground = 'white'
        grid_color = '#666666'
    else:
        background = 'white'
        foreground = 'black'
        grid_color = '#D0D0D0'

    ax.set_facecolor(background)
    ax.tick_params(colors=foreground, labelsize=8)
    ax.xaxis.label.set_color(foreground)
    ax.yaxis.label.set_color(foreground)
    ax.title.set_color(foreground)
    for spine in ax.spines.values():
        spine.set_edgecolor(foreground)
    ax.grid(True, linestyle='--', alpha=0.6, color=grid_color)

    legend = ax.get_legend()
    if legend:
        legend.get_frame().set_facecolor(background)
        legend.get_frame().set_edgecolor(foreground)
        for text in legend.get_texts():
            text.set_color(foreground)


def render_dashboard_figure(fig, current_data, op_data, start_date_str, end_date_str, comparison_type="Nenhuma Comparação", comparison_data=None, dark_theme=False):
    """
    Monta a figura completa do dashboard, reaproveitando a mesma composição na UI e no PDF.
    """
    fig.clear()
    fig.set_facecolor('#2c2c2c' if dark_theme else 'white')

    def themed_plot(plotter):
        axes_before = len(fig.axes)
        plotter()
        new_axes = fig.axes[axes_before:]
        for axis in new_axes:
            _apply_axis_theme(axis, dark_theme=dark_theme)

    themed_plot(lambda: plot_efficiency_over_time(op_data, start_date_str, end_date_str, fig, 231))
    themed_plot(lambda: plot_productivity_by_frente(current_data.get('productivity_by_frente', {}), fig, 232))
    themed_plot(
        lambda: plot_operation_vs_downtime(
            current_data.get('total_operation_minutes_actual', 0),
            current_data.get('total_downtime_minutes', 0),
            fig,
            233,
        )
    )
    themed_plot(lambda: plot_fleet_efficiency_over_time(op_data, start_date_str, end_date_str, fig, 234))
    themed_plot(
        lambda: plot_comparison_metrics(
            current_data,
            comparison_data or {},
            comparison_type,
            fig,
            235,
        )
    )
    themed_plot(lambda: plot_downtime_pareto(current_data.get('downtime_by_reason', {}), fig, 236))

    fig.tight_layout(pad=2.0)
    return fig


def _format_value(value, suffix="", decimals=2):
    """Formata valores numéricos no padrão brasileiro."""
    formatted = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted}{suffix}"


def _build_dashboard_metric_table(current_data, comparison_text, styles):
    body_style = ParagraphStyle(
        'DashboardMetricCell',
        parent=styles['BodyText'],
        fontSize=9,
        leading=11,
        wordWrap='CJK',
    )
    header_style = ParagraphStyle(
        'DashboardMetricHeader',
        parent=body_style,
        fontName='Helvetica-Bold',
        textColor=colors.white,
    )

    produtividade_por_frente = current_data.get('productivity_by_frente', {})
    top3_frentes = sorted(
        produtividade_por_frente.items(),
        key=lambda item: item[1]['total_ton'],
        reverse=True,
    )[:3]
    top3_text = ", ".join(str(item[0]) for item in top3_frentes) if top3_frentes else "N/A"

    raw_rows = [
        ["Métrica", "Valor"],
        ["Total de registros", str(current_data.get('total_registros', 0))],
        ["Eficiência média", _format_value(current_data.get('media_eficiencia', 0), "%")],
        ["Área total colhida", _format_value(current_data.get('area_total_colhida', 0), " ha")],
        ["Produtividade média", _format_value(current_data.get('produtividade_media', 0), " ton/ha")],
        ["Produtividade total", _format_value(current_data.get('total_ton_colhida', 0), " ton")],
        ["Disponibilidade de equipamentos", _format_value(current_data.get('utilizacao_equipamentos', 0), "%")],
        ["Eficiência colhedora", _format_value(current_data.get('eficiencia_colhedora', 0), "%")],
        ["Eficiência transbordo", _format_value(current_data.get('eficiencia_transbordo', 0), "%")],
        [
            "Maior tempo médio de parada",
            f"{current_data.get('maior_tempo_medio_parada', 'Nenhum')} ({_format_value(current_data.get('maior_tempo_medio_parada_valor', 0) / 60, ' h')})",
        ],
        [
            "Maior % de tempo parado",
            f"{current_data.get('maior_percentual_tempo_parado', 'Nenhum')} ({_format_value(current_data.get('maior_percentual_tempo_parado_valor', 0), '%')})",
        ],
        ["Top 3 frentes mais produtivas", top3_text],
        ["Comparação", comparison_text],
    ]
    metric_rows = [
        [
            Paragraph(escape(str(value)), header_style if row_index == 0 else body_style)
            for value in row
        ]
        for row_index, row in enumerate(raw_rows)
    ]

    table = Table(metric_rows, colWidths=[8.5 * cm, 16.5 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F3A5F')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F4F6F8')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#C7D0D9')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor('#EAF0F5')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    return table


def _build_unique_path(base_path):
    """Evita sobrescrever relatórios anteriores."""
    candidate = base_path
    counter = 1
    root, extension = os.path.splitext(base_path)

    while os.path.exists(candidate):
        candidate = f"{root}_{counter}{extension}"
        counter += 1

    return candidate


def generate_dashboard_report_pdf(start_date, end_date, frente=None, frota=None, comparison_type="Nenhuma Comparação", output_path=None):
    """Gera um PDF do dashboard com métricas e visão gráfica consolidada."""
    output_path = output_path or get_setting('report_default_path', '.') or '.'
    os.makedirs(output_path, exist_ok=True)

    current_data, op_data, _, comparison_data, comparison_period = build_dashboard_context(
        start_date, end_date, frente, frota, comparison_type
    )

    if not current_data or current_data.get('total_registros', 0) == 0:
        return None

    file_name = f"Dashboard_Operacional_{start_date}_a_{end_date}.pdf"
    full_path = _build_unique_path(os.path.join(output_path, file_name))

    figure = plt.figure(figsize=(16, 10))
    chart_buffer = io.BytesIO()

    try:
        render_dashboard_figure(
            figure,
            current_data,
            op_data,
            start_date,
            end_date,
            comparison_type=comparison_type,
            comparison_data=comparison_data,
            dark_theme=False,
        )
        figure.savefig(chart_buffer, format='png', dpi=180, bbox_inches='tight', facecolor=figure.get_facecolor())
        chart_buffer.seek(0)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'DashboardTitle',
            parent=styles['Title'],
            fontSize=18,
            textColor=colors.HexColor('#1F3A5F'),
            spaceAfter=8,
        )
        info_style = ParagraphStyle(
            'DashboardInfo',
            parent=styles['BodyText'],
            fontSize=10,
            leading=14,
            spaceAfter=10,
        )

        comparison_text = "Sem comparação"
        if comparison_period:
            comparison_text = (
                f"{comparison_type}: {comparison_period[0]} a {comparison_period[1]}"
            )

        table = _build_dashboard_metric_table(current_data, comparison_text, styles)

        chart_image = Image(chart_buffer, width=24.5 * cm, height=14.5 * cm)
        filters_text = (
            f"<b>Período:</b> {escape(str(start_date))} a {escape(str(end_date))}<br/>"
            f"<b>Frente:</b> {escape(str(frente or 'Todas'))}<br/>"
            f"<b>Frota:</b> {escape(str(frota or 'Todas'))}"
        )

        story = [
            Paragraph("Dashboard Operacional", title_style),
            Paragraph(filters_text, info_style),
            table,
            PageBreak(),
            Paragraph("Gráficos do Período", title_style),
            chart_image,
        ]

        doc = SimpleDocTemplate(
            full_path,
            pagesize=landscape(A4),
            leftMargin=1.2 * cm,
            rightMargin=1.2 * cm,
            topMargin=1.0 * cm,
            bottomMargin=1.0 * cm,
        )
        doc.build(story)
        return full_path
    finally:
        plt.close(figure)
        chart_buffer.close()
