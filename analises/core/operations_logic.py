# core/operations_logic.py
import sqlite3
from datetime import datetime, timedelta
from core.database_manager import DatabaseManager
from core.settings import get_setting

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - SQLite-only environments
    psycopg = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())


DUPLICATE_OPERATION_MESSAGE = (
    "Já existe uma ocorrência com a mesma Data, Frente, Turno, Frota e Hora que Parou."
)


def _build_integrity_message(exc):
    if "RELATORIO_OPERACAO_DIARIA" in str(exc):
        return DUPLICATE_OPERATION_MESSAGE
    return "Os dados informados violam uma regra do banco de dados."

def calcular_parada_e_eficiencia(data_inicio_str, hora_parada_str, data_retorno_str, hora_retorno_str):
    """
    Calcula o tempo total de parada e a eficiência com base nas datas e horas.
    Retorna uma tupla: (total_hora_parado_str, eficiencia_float).
    """
    try:
        # Tenta usar o formato DD/MM/YYYY primeiro, que vem da interface
        dt_inicio = datetime.strptime(f"{data_inicio_str} {hora_parada_str}", "%d/%m/%Y %H:%M")
        dt_retorno = datetime.strptime(f"{data_retorno_str} {hora_retorno_str}", "%d/%m/%Y %H:%M")

        if dt_retorno <= dt_inicio:
            # Assume que, se o retorno for antes ou igual ao início, a operação virou o dia
            dt_retorno += timedelta(days=1)

        total_parado_delta = dt_retorno - dt_inicio
        total_minutos_parados = int(total_parado_delta.total_seconds() // 60)

        horas = total_minutos_parados // 60
        minutos = total_minutos_parados % 60
        total_hora_parado_str = f"{horas:02}:{minutos:02}"

        tempo_operacao_minutos = int(get_setting('tempo_operacao_minutos', '600'))

        eficiencia = 0.0
        if tempo_operacao_minutos > 0:
            eficiencia = max(0.0, (1 - total_minutos_parados / tempo_operacao_minutos) * 100)

        return total_hora_parado_str, eficiencia
    except Exception as e:
        print(f"Erro ao calcular parada e eficiência: {e}")
        return "00:00", 0.0

def verificar_duplicidade(data_db, frente, turno, frota, parou_hora, ignore_id=None):
    """
    Verifica se já existe um registro idêntico no banco de dados.
    Retorna o ID do registro duplicado se encontrado, senão None.
    """
    try:
        # Altera de 'SELECT COUNT(*)' para 'SELECT id'
        base_query = """
            SELECT id FROM RELATORIO_OPERACAO_DIARIA
            WHERE Data = ? AND Frente = ? AND Turno = ? AND Frota = ?
        """
        params = [data_db, frente, turno, frota]

        if parou_hora and parou_hora != ":":
            # Se 'Parou_Hora' foi fornecida, procura por ela
            base_query += " AND Parou_Hora = ?"
            params.append(parou_hora)
        else:
            # Se 'Parou_Hora' está vazia, procura por registros onde ela é NULL ou vazia
            base_query += " AND (Parou_Hora IS NULL OR Parou_Hora = '' OR Parou_Hora = ':')"

        if ignore_id is not None:
            base_query += " AND id <> ?"
            params.append(ignore_id)

        base_query += " LIMIT 1" # Só precisamos do primeiro ID que encontrar

        result = DatabaseManager.execute_select(base_query, params)

        if result and result[0]:
            return result[0][0]  # Retorna o ID (ex: 123)

    except Exception as e:
        print(f"Erro ao verificar duplicidade: {e}")
        return None # Retorna None em caso de erro para evitar falso positivo

    return None # Nenhum duplicado encontrado

def salvar_registro_simples(data_str, frente, turno, frota, motivo, fundo, chuva, incidencia):
    """ Salva um registro simples (sem parada) """
    try:
        query = "INSERT INTO RELATORIO_OPERACAO_DIARIA (Data, Frente, Turno, Frota, Motivo, Fundo_Agricola, Chuva, Incendio, Status_Parada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Finalizada')"
        params = (data_str, frente, turno, frota, motivo, fundo, chuva, incidencia)
        DatabaseManager.execute_non_query(query, params)
        return True, "Registro simples cadastrado com sucesso!"
    except INTEGRITY_ERRORS as exc:
        return False, _build_integrity_message(exc)
    except Exception as e:
        print(f"Erro ao salvar registro simples: {e}")
        return False, "Não foi possível salvar o registro simples no banco de dados."

def salvar_parada_em_andamento(data_str, frente, turno, frota, motivo, hora_parada_str, fundo, chuva, incidencia):
    """ Salva uma parada em andamento """
    try:
        query = "INSERT INTO RELATORIO_OPERACAO_DIARIA (Data, Frente, Turno, Frota, Motivo, Parou_Hora, Fundo_Agricola, Chuva, Incendio, Status_Parada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Em Andamento')"
        params = (data_str, frente, turno, frota, motivo, hora_parada_str, fundo, chuva, incidencia)
        DatabaseManager.execute_non_query(query, params)
        return True, "Parada em andamento registrada com sucesso!"
    except INTEGRITY_ERRORS as exc:
        return False, _build_integrity_message(exc)
    except Exception as e:
        print(f"Erro ao salvar parada em andamento: {e}")
        return False, "Não foi possível salvar a parada em andamento no banco de dados."

def salvar_parada_finalizada(data_inicio_turno_str, frente, turno_inicial, frota, motivo_base, hora_parada_str, data_retorno_str, hora_retorno_str, fundo, chuva, incidencia, id_parada_original_a_deletar):
    """ Finaliza uma parada em andamento """
    try:
        delete_query = "DELETE FROM RELATORIO_OPERACAO_DIARIA WHERE id = ?"
        DatabaseManager.execute_non_query(delete_query, (id_parada_original_a_deletar,))

        total_hora_parado_str, eficiencia = calcular_parada_e_eficiencia(
            data_inicio_turno_str, hora_parada_str, data_retorno_str, hora_retorno_str
        )

        insert_query = "INSERT INTO RELATORIO_OPERACAO_DIARIA (Data, Frente, Turno, Frota, Motivo, Parou_Hora, Voltou_Hora, Total_Hora_Parado, Eficiencia, Fundo_Agricola, Chuva, Incendio, Status_Parada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Finalizada')"
        params = (data_inicio_turno_str, frente, turno_inicial, frota, motivo_base, hora_parada_str, hora_retorno_str, total_hora_parado_str, f"{eficiencia:.2f}", fundo, chuva, incidencia)
        DatabaseManager.execute_non_query(insert_query, params)

        return True, "Parada finalizada e registro salvo com sucesso!"
    except Exception as e:
        return False, f"Erro ao finalizar parada: {e}"
