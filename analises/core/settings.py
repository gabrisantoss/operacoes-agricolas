# core/settings.py
from .config import DatabaseConfig
from .database_manager import DatabaseManager

def setup_settings_database():
    """
    Garante que a tabela SETTINGS exista, usando a conexão centralizada.
    """
    query = """
        CREATE TABLE IF NOT EXISTS SETTINGS (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """
    conn = None
    try:
        # Precisa de conexão direta aqui para garantir que a tabela exista
        # antes do DatabaseManager ser usado
        conn = DatabaseConfig.get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        conn.commit()
    except Exception as e:
        print(f"Erro ao configurar tabela de settings: {e}")
        if conn:
            conn.rollback()
        raise RuntimeError("Falha ao configurar settings de Analises.") from e
    finally:
        if conn:
            conn.close()


def save_setting(key, value):
    """
    Salva uma configuração no banco de dados usando o DatabaseManager.
    """
    query = """
        INSERT INTO SETTINGS (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """
    DatabaseManager.execute_non_query(query, (key, str(value)))

def get_setting(key, default=None):
    """
    Busca uma configuração do banco de dados usando o DatabaseManager.
    """
    query = "SELECT value FROM SETTINGS WHERE key = ?"
    result = DatabaseManager.execute_select(query, (key,))
    return result[0][0] if result else default

def add_word_to_dictionary(word):
    """
    Adiciona uma palavra ao dicionário customizado.
    """
    query = "INSERT OR IGNORE INTO CUSTOM_DICTIONARY (word) VALUES (?)"
    DatabaseManager.execute_non_query(query, (word.upper(),))

def get_custom_dictionary_words():
    """
    Busca todas as palavras do dicionário customizado.
    """
    query = "SELECT word FROM CUSTOM_DICTIONARY"
    rows = DatabaseManager.execute_select(query)
    return {row[0] for row in rows}
