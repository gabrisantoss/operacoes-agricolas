from contextlib import contextmanager
from .config import DatabaseConfig

class DatabaseManager:
    """Gerencia conexões e execuções de queries com o banco de dados"""

    @staticmethod
    @contextmanager
    def get_connection():
        """Context manager para gerenciar conexões com o banco"""
        conn = None
        try:
            conn = DatabaseConfig.get_connection()
            yield conn
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    @staticmethod
    def execute_select(query, params=None):
        """Executa uma query SELECT e retorna os resultados"""
        with DatabaseManager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or [])
            return cursor.fetchall()

    @staticmethod
    def execute_non_query(query, params=None):
        """Executa uma query que não retorna dados (INSERT, UPDATE, DELETE)"""
        with DatabaseManager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or [])
            return cursor.rowcount
