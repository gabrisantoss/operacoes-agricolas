# core/database.py
from .config import DatabaseConfig
from .date_utils import sql_date_expr

def setup_main_database():
    """
    Configura as tabelas principais do banco de dados
    usando a conexão centralizada.
    """
    conn = None
    try:
        conn = DatabaseConfig.get_connection()
        cursor = conn.cursor()
        if DatabaseConfig.DB_ENGINE in {"postgres", "postgresql"}:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION strftime(fmt text, value text)
                RETURNS text
                LANGUAGE sql
                IMMUTABLE
                AS $$
                    SELECT CASE WHEN fmt = '%%Y-%%m-%%d' THEN value ELSE value END
                $$;
                """
            )

        # Tabela para Relatório de Operação Diária com restrição UNIQUE
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS RELATORIO_OPERACAO_DIARIA (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Data TEXT NOT NULL,
                Frente TEXT NOT NULL,
                Turno TEXT NOT NULL,
                Frota TEXT,
                Motivo TEXT,
                Parou_Hora TEXT,
                Voltou_Hora TEXT,
                Total_Hora_Parado TEXT,
                Eficiencia REAL,
                Fundo_Agricola TEXT,
                Chuva TEXT,
                Incendio TEXT,
                Status_Parada TEXT DEFAULT 'Finalizada',
                UNIQUE(Data, Frente, Turno, Frota, Parou_Hora)
            )
        """)

        # Tabela para Cadastro de Frotas por Frente
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS FROTAS_POR_FRENTE (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Frente TEXT NOT NULL,
                Frota TEXT NOT NULL,
                UNIQUE(Frente, Frota)
            )
        """)

        # Tabela para Colheita Mecanizada
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS COLHEITA_MECANIZADA (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Data TEXT NOT NULL,
                Frente TEXT NOT NULL,
                Turno TEXT NOT NULL,
                Fazenda TEXT NOT NULL,
                Area_Colhida REAL,
                Produtividade REAL,
                Viagens INTEGER
            )
        """)

        # Tabela para o dicionário personalizado
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS CUSTOM_DICTIONARY (
                word TEXT PRIMARY KEY NOT NULL
            )
        """)

        # Tabela para Treinamento do OCR
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS OCR_TRAINING (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT,
                data_extraida TEXT,
                parou_hora TEXT,
                voltou_hora TEXT,
                frente TEXT,
                frota TEXT,
                motivo TEXT
            )
        """)

        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")

        date_expr = sql_date_expr("Data")
        date_index_expr = f"({date_expr})" if DatabaseConfig.DB_ENGINE in {"postgres", "postgresql"} else date_expr
        indexes = [
            f"""
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_data_iso
            ON RELATORIO_OPERACAO_DIARIA ({date_index_expr})
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_filtros
            ON RELATORIO_OPERACAO_DIARIA (Frente, Turno, Status_Parada, Frota)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_frota
            ON RELATORIO_OPERACAO_DIARIA (Frota)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_status
            ON RELATORIO_OPERACAO_DIARIA (Status_Parada)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_frente_data
            ON RELATORIO_OPERACAO_DIARIA (Frente, Data)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relatorio_operacao_motivo
            ON RELATORIO_OPERACAO_DIARIA (Motivo)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_colheita_mecanizada_data_frente
            ON COLHEITA_MECANIZADA (Data, Frente)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_colheita_mecanizada_fazenda
            ON COLHEITA_MECANIZADA (Fazenda)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_frotas_por_frente_frente
            ON FROTAS_POR_FRENTE (Frente)
            """,
        ]
        for statement in indexes:
            cursor.execute(statement)

        cursor.execute("PRAGMA optimize")

        conn.commit()
    except Exception as e:
        print(f"Erro ao configurar o banco de dados principal: {e}")
        if conn:
            conn.rollback()
        raise RuntimeError("Falha ao configurar o banco principal de Analises.") from e
    finally:
        if conn:
            conn.close()
