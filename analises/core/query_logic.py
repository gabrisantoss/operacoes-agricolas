# core/query_logic.py

from PyQt5.QtCore import QDate
from core.database_manager import DatabaseManager
from core.date_utils import sql_date_expr
from core.operational_fleet import operational_fleet_sql
from datetime import datetime

def get_distinct_items(column_name):
    """
    Retorna lista de valores distintos de uma coluna na tabela RELATORIO_OPERACAO_DIARIA.
    """
    query = f"""
        SELECT DISTINCT {column_name}
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE COALESCE({column_name}, '') != ''
        ORDER BY {column_name}
    """
    rows = DatabaseManager.execute_select(query)
    return [str(row[0]) for row in rows]

def buscar_registros_operacao(filtros: dict):
    """
    Busca registros de operação com base em filtros recebidos em dicionário:
    'data_inicial', 'data_final', 'frente', 'turno', 'frota', 'pesquisa_texto'.
    Retorna tupla de linhas para exibição.
    """
    base_query = """
        SELECT Data, Frente, Turno, Frota, Motivo,
               Parou_Hora, Voltou_Hora, Total_Hora_Parado,
               Eficiencia, Fundo_Agricola, Chuva, Incendio
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE 1=1
          AND {operational_fleet_filter}
    """
    base_query = base_query.format(
        operational_fleet_filter=operational_fleet_sql("Frota")
    )
    params = []

    # Filtro data inicial
    data_inicial = filtros.get('data_inicial')
    if data_inicial and data_inicial.isValid():
        base_query += f" AND {sql_date_expr('Data')} >= ?"
        params.append(data_inicial.toString("yyyy-MM-dd"))

    # Filtro data final
    data_final = filtros.get('data_final')
    if data_final and data_final.isValid():
        base_query += f" AND {sql_date_expr('Data')} <= ?"
        params.append(data_final.toString("yyyy-MM-dd"))

    # Filtro de frente, turno e frota
    for key in ('frente', 'turno', 'frota'):
        valor = filtros.get(key)
        if valor:
            coluna = 'Frente' if key == 'frente' else 'Turno' if key == 'turno' else 'Frota'
            base_query += f" AND {coluna} = ?"
            params.append(valor)

    # Filtro de texto em múltiplas colunas
    texto = filtros.get('pesquisa_texto')
    if texto:
        termo = f"%{texto}%"
        base_query += """
            AND (Motivo LIKE ?
                 OR Fundo_Agricola LIKE ?
                 OR Chuva LIKE ?
                 OR Incendio LIKE ?)
        """
        params.extend([termo] * 4)

    # Ordenação final
    base_query += """
        ORDER BY {date_expr} DESC,
                 Frente, Turno
    """
    base_query = base_query.format(date_expr=sql_date_expr("Data"))

    return DatabaseManager.execute_select(base_query, params)

def buscar_registro_por_id(id_registro: int):
    """
    Busca um registro de operação completo pelo seu ID.
    Retorna um dicionário com os dados formatados para edição.
    """
    query = """
        SELECT id, Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora,
               Fundo_Agricola, Chuva, Incendio
        FROM RELATORIO_OPERACAO_DIARIA
        WHERE id = ?
    """
    rows = DatabaseManager.execute_select(query, (id_registro,))

    if not rows:
        return None

    # Converte a tupla (row) do banco para um dicionário
    row = rows[0]

    # Converte a data do formato DB (dd-mm-yyyy) para o formato de exibição (dd/mm/yyyy)
    try:
        data_display = datetime.strptime(row[1], "%d-%m-%Y").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        data_display = row[1] # Fallback caso a data já esteja em outro formato

    dados = {
        'id': row[0],
        'data': data_display,
        'frente': row[2],
        'turno': row[3],
        'frota': row[4],
        'motivo': row[5],
        'parou_hora': row[6],
        'voltou_hora': row[7],
        'fundo_agricola': row[8],
        'chuva': row[9],
        'incendio': row[10],
    }
    return dados
