# funcoes_colaboradores.py (Versão com renovação aleatória de CNHs vencidas)

import sqlite3
import subprocess
from datetime import date, datetime, timedelta
import os
import shutil
import logging
import json
from typing import Any
import pandas as pd
import random
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from app_config import DATABASE_URL, DB_ENGINE
from app_config import BACKUP_FOLDER_DEFAULT as CONFIG_BACKUP_FOLDER_DEFAULT
from app_config import DB_PATH as CONFIG_DB_PATH
from db import (
    DatabaseError,
    IntegrityError,
    database_quiescence,
    get_db_connection as open_db_connection,
    is_postgresql,
)
from core.cnh_management import classificar_status_tecnico
from storage_manager import (
    FileMutationJournal,
    get_category_dir,
    is_managed_path,
    normalize_storage_reference,
    resolve_stored_path,
    store_file,
)

# Configura o logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = CONFIG_DB_PATH
DB_TIMEOUT = 30
SCHEMA_VERSION = "002"
BACKUP_FOLDER_DEFAULT = CONFIG_BACKUP_FOLDER_DEFAULT
COLUNAS_ADICIONAIS_COLABORADORES = {
    "cpf": "TEXT",
    "nascimento": "TEXT",
    "municipio": "TEXT",
    "rg": "TEXT",
    "local_trabalho": "TEXT",
    "funcao": "TEXT",
    "data_admissao": "TEXT",
    "salario": "REAL",
    "registro_cnh": "TEXT",
    "primeira_cnh": "TEXT",
    "observacao_1": "TEXT",
    "observacao_2": "TEXT",
    "observacao_3": "TEXT",
    "observacao_4": "TEXT",
    "observacao_5": "TEXT",
    "tem_foto": "TEXT DEFAULT 'NÃO'",
    "gestor_responsavel": "TEXT",
    "status_cnh_acompanhamento": "TEXT",
    "ultima_acao_cnh": "TEXT",
    "ultimo_contato_cnh": "TEXT",
    "responsavel_ultimo_contato_cnh": "TEXT",
    "data_prevista_regularizacao_cnh": "TEXT",
    "observacao_cnh": "TEXT",
    "caminho_comprovante_cnh": "TEXT",
    "oculto_operacao": "INTEGER NOT NULL DEFAULT 0",
    "motivo_ocultacao": "TEXT",
    "ocultado_em": "TEXT",
}
TABELAS_REFERENCIANDO_COLABORADOR = (
    "documentos",
    "atestados",
    "advertencias",
    "cnh_historico",
    "cnh_acompanhamentos",
    "informes_diarios_detalhe",
)
COLABORADOR_DATE_FIELDS = (
    "nascimento",
    "data_admissao",
    "validade_cnh",
    "primeira_cnh",
)
COLABORADOR_TEXT_FIELDS = (
    "codigo_colaborador",
    "nome",
    "cpf",
    "rg",
    "municipio",
    "cidade",
    "telefone",
    "funcao",
    "gestor_responsavel",
    "local_trabalho",
    "registro_cnh",
    "categoria_cnh",
)

def get_db_connection(dict_rows: bool = False, **kwargs):
    try:
        return open_db_connection(dict_rows=dict_rows, **kwargs)
    except DatabaseError as e:
        logging.critical(f"Erro CRÍTICO ao obter conexão com o banco de dados: {e}")
        raise ConnectionError(f"Não foi possível conectar ao banco de dados: {e}.")


def _agora_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalizar_data_iso(valor: str | None) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass

    try:
        return pd.to_datetime(texto, errors="raise").strftime("%Y-%m-%d")
    except Exception:
        return None


def _caminho_foto(codigo_colaborador: str) -> str:
    codigo_seguro = re.sub(r"[^A-Za-z0-9._-]+", "_", str(codigo_colaborador or "").strip()).strip("._")
    return str((get_category_dir("fotos") / f"{codigo_seguro or 'sem_codigo'}.jpg").resolve())


def _tem_foto_armazenada(codigo_colaborador: str) -> bool:
    return os.path.exists(_caminho_foto(codigo_colaborador))


def _preparar_caminho_upload(
    caminho_origem: str | None,
    categoria: str,
    codigo_colaborador: str,
    file_journal: FileMutationJournal | None = None,
) -> str | None:
    texto = str(caminho_origem or "").strip()
    if not texto:
        return None
    if is_managed_path(texto):
        return normalize_storage_reference(texto)
    if file_journal is not None:
        return file_journal.stage_file(texto, categoria, codigo_colaborador)
    return store_file(texto, categoria, codigo_colaborador)


def _normalizar_valor_real(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        texto = texto.replace(".", "").replace(",", ".") if "," in texto and "." in texto else texto.replace(",", ".")
        try:
            return float(texto)
        except ValueError:
            return valor
    return valor


def _somente_digitos(valor) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def _normalizar_codigo_importado(valor) -> str:
    if pd.isna(valor):
        return ""
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))

    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2]:
        return texto[:-2]
    return texto


def _cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    for tamanho in (9, 10):
        soma = sum(int(cpf[indice]) * ((tamanho + 1) - indice) for indice in range(tamanho))
        resto = (soma * 10) % 11
        digito = 0 if resto == 10 else resto
        if digito != int(cpf[tamanho]):
            return False
    return True


def _normalizar_dados_colaborador(dados: dict) -> dict:
    dados_normalizados = dict(dados)
    for campo in COLABORADOR_TEXT_FIELDS:
        if campo in dados_normalizados:
            dados_normalizados[campo] = str(dados_normalizados.get(campo) or "").strip()
    for campo in COLABORADOR_DATE_FIELDS:
        if campo in dados_normalizados:
            dados_normalizados[campo] = _normalizar_data_iso(dados_normalizados.get(campo))
    if "cpf" in dados_normalizados:
        dados_normalizados["cpf"] = _somente_digitos(dados_normalizados.get("cpf"))
    if "telefone" in dados_normalizados:
        dados_normalizados["telefone"] = _somente_digitos(dados_normalizados.get("telefone"))
    if "salario" in dados_normalizados:
        dados_normalizados["salario"] = _normalizar_valor_real(dados_normalizados.get("salario"))
    return dados_normalizados


def validar_dados_colaborador(dados: dict) -> tuple[dict, dict[str, str]]:
    dados_originais = dict(dados)
    dados_normalizados = _normalizar_dados_colaborador(dados_originais)
    erros: dict[str, str] = {}

    codigo = str(dados_normalizados.get("codigo_colaborador") or "").strip()
    nome = str(dados_normalizados.get("nome") or "").strip()
    if not codigo:
        erros["codigo_colaborador"] = "O campo Código é obrigatório."
    if not nome:
        erros["nome"] = "O campo Nome é obrigatório."

    for campo in COLABORADOR_DATE_FIELDS:
        valor_original = dados_originais.get(campo)
        texto_original = str(valor_original or "").strip()
        if texto_original and dados_normalizados.get(campo) is None:
            erros[campo] = f"O campo {campo.replace('_', ' ').title()} está com data inválida."

    cpf = dados_normalizados.get("cpf") or ""
    if cpf and not _cpf_valido(cpf):
        erros["cpf"] = "CPF inválido."

    telefone = dados_normalizados.get("telefone") or ""
    if telefone and len(telefone) not in (10, 11):
        erros["telefone"] = "Telefone deve ter 10 ou 11 dígitos."

    salario_original = dados_originais.get("salario")
    salario_normalizado = dados_normalizados.get("salario")
    if str(salario_original or "").strip():
        if isinstance(salario_normalizado, str):
            erros["salario"] = "Salário inválido."
        elif salario_normalizado is not None and salario_normalizado < 0:
            erros["salario"] = "Salário não pode ser negativo."

    nascimento = dados_normalizados.get("nascimento")
    data_admissao = dados_normalizados.get("data_admissao")
    validade_cnh = dados_normalizados.get("validade_cnh")
    primeira_cnh = dados_normalizados.get("primeira_cnh")
    hoje = date.today()

    if nascimento:
        data_nascimento = datetime.strptime(nascimento, "%Y-%m-%d").date()
        if data_nascimento > hoje:
            erros["nascimento"] = "Nascimento não pode estar no futuro."
    else:
        data_nascimento = None

    if data_admissao:
        data_admissao_date = datetime.strptime(data_admissao, "%Y-%m-%d").date()
        if data_admissao_date > hoje:
            erros["data_admissao"] = "Data de admissão não pode estar no futuro."
        if data_nascimento and data_admissao_date < data_nascimento:
            erros["data_admissao"] = "Data de admissão não pode ser anterior ao nascimento."

    if primeira_cnh and validade_cnh:
        primeira_cnh_date = datetime.strptime(primeira_cnh, "%Y-%m-%d").date()
        validade_cnh_date = datetime.strptime(validade_cnh, "%Y-%m-%d").date()
        if primeira_cnh_date > validade_cnh_date:
            erros["primeira_cnh"] = "Primeira habilitação não pode ser posterior à validade da CNH."

    return dados_normalizados, erros


def _upsert_foto_colaborador(cursor, numero_colab: str, tem_foto: str) -> None:
    if is_postgresql():
        cursor.execute(
            """
            INSERT INTO colaboradores_fotos (numero_colab, tem_foto)
            VALUES (?, ?)
            ON CONFLICT (numero_colab) DO UPDATE SET tem_foto = EXCLUDED.tem_foto
            """,
            (numero_colab, tem_foto),
        )
        return

    cursor.execute(
        "INSERT OR REPLACE INTO colaboradores_fotos (numero_colab, tem_foto) VALUES (?, ?)",
        (numero_colab, tem_foto),
    )


def _insert_pre_cadastro(cursor, codigo_colaborador: str, nome: str, codigo_interno: str | None) -> None:
    if is_postgresql():
        cursor.execute(
            """
            INSERT INTO colaboradores (codigo_colaborador, nome, codigo_interno, situacao)
            VALUES (?, ?, ?, 'PENDENTE')
            ON CONFLICT (codigo_colaborador) DO NOTHING
            """,
            (codigo_colaborador.strip(), nome.strip(), codigo_interno.strip() if codigo_interno else None),
        )
        return

    cursor.execute(
        "INSERT OR IGNORE INTO colaboradores (codigo_colaborador, nome, codigo_interno, situacao) VALUES (?, ?, ?, 'PENDENTE')",
        (codigo_colaborador.strip(), nome.strip(), codigo_interno.strip() if codigo_interno else None),
    )


def _get_existing_columns(cursor, table_name: str) -> set[str]:
    if is_postgresql():
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table_name,),
        )
        return {row[0] for row in cursor.fetchall()}

    cursor.execute(f"PRAGMA table_info({table_name})")
    return {info[1] for info in cursor.fetchall()}


def _registrar_historico_cnh_cursor(
    cursor: Any,
    codigo_colaborador: str,
    validade_anterior: str | None,
    validade_nova: str | None,
    categoria_anterior: str | None,
    categoria_nova: str | None,
    responsavel: str = "",
    observacao: str = "",
    caminho_comprovante: str | None = None,
    origem: str = "MANUAL",
) -> None:
    cursor.execute(
        """
        INSERT INTO cnh_historico (
            codigo_colaborador,
            data_hora,
            validade_anterior,
            validade_nova,
            categoria_anterior,
            categoria_nova,
            responsavel,
            observacao,
            caminho_comprovante,
            origem
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            codigo_colaborador,
            _agora_str(),
            validade_anterior,
            validade_nova,
            categoria_anterior,
            categoria_nova,
            (responsavel or "").strip(),
            (observacao or "").strip(),
            caminho_comprovante,
            origem,
        ),
    )


def _registrar_acompanhamento_cnh_cursor(
    cursor: Any,
    codigo_colaborador: str,
    status: str,
    responsavel: str = "",
    observacao: str = "",
    data_prevista: str | None = None,
    caminho_comprovante: str | None = None,
    houve_contato: bool = False,
    origem: str = "MANUAL",
) -> None:
    status_normalizado = (status or "SEM_ACAO").strip().upper()
    data_hora = _agora_str()
    data_prevista_iso = _normalizar_data_iso(data_prevista)
    if status_normalizado == "REGULARIZADO":
        data_prevista_iso = None

    cursor.execute(
        """
        SELECT
            ultimo_contato_cnh,
            responsavel_ultimo_contato_cnh,
            observacao_cnh,
            caminho_comprovante_cnh
        FROM colaboradores
        WHERE codigo_colaborador = ?
        """,
        (codigo_colaborador,),
    )
    atual = cursor.fetchone() or (None, None, None, None)

    ultimo_contato = data_hora if houve_contato else atual[0]
    responsavel_contato = (responsavel or "").strip() if houve_contato and responsavel else atual[1]
    observacao_snapshot = (observacao or "").strip() if (observacao or "").strip() else (atual[2] or "")
    caminho_snapshot = caminho_comprovante or atual[3]

    cursor.execute(
        """
        INSERT INTO cnh_acompanhamentos (
            codigo_colaborador,
            data_hora,
            status,
            responsavel,
            observacao,
            data_prevista,
            houve_contato,
            caminho_comprovante,
            origem
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            codigo_colaborador,
            data_hora,
            status_normalizado,
            (responsavel or "").strip(),
            (observacao or "").strip(),
            data_prevista_iso,
            1 if houve_contato else 0,
            caminho_comprovante,
            origem,
        ),
    )

    cursor.execute(
        """
        UPDATE colaboradores
        SET
            status_cnh_acompanhamento = ?,
            ultima_acao_cnh = ?,
            ultimo_contato_cnh = ?,
            responsavel_ultimo_contato_cnh = ?,
            data_prevista_regularizacao_cnh = ?,
            observacao_cnh = ?,
            caminho_comprovante_cnh = ?
        WHERE codigo_colaborador = ?
        """,
        (
            status_normalizado,
            f"{status_normalizado} em {data_hora}",
            ultimo_contato,
            responsavel_contato,
            data_prevista_iso,
            observacao_snapshot,
            caminho_snapshot,
            codigo_colaborador,
        ),
    )

def _registrar_log_auditoria_cursor(cursor, tipo_acao: str, entidade_afetada: str, id_entidade: str, detalhes: dict | None = None) -> None:
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detalhes_json = json.dumps(detalhes, ensure_ascii=False) if detalhes else None
    cursor.execute(
        "INSERT INTO log_auditoria (data_hora, tipo_acao, entidade_afetada, id_entidade, detalhes) VALUES (?, ?, ?, ?, ?)",
        (data_hora, tipo_acao, entidade_afetada, id_entidade, detalhes_json),
    )


def registrar_log_auditoria(tipo_acao: str, entidade_afetada: str, id_entidade: str, detalhes: dict | None = None, *, cursor=None) -> None:
    if cursor is not None:
        _registrar_log_auditoria_cursor(cursor, tipo_acao, entidade_afetada, id_entidade, detalhes)
        return
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            _registrar_log_auditoria_cursor(cursor, tipo_acao, entidade_afetada, id_entidade, detalhes)
            conn.commit()
    except DatabaseError as e:
        logging.error(f"Erro ao registrar log de auditoria: {e}")

def garantir_schema_banco() -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            identity_sql = "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if is_postgresql() else "INTEGER PRIMARY KEY AUTOINCREMENT"

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS colaboradores (
                    codigo_colaborador TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    codigo_interno TEXT,
                    situacao TEXT,
                    modalidade TEXT,
                    apelido TEXT,
                    telefone TEXT,
                    cidade TEXT,
                    validade_cnh TEXT,
                    categoria_cnh TEXT,
                    frente_safra TEXT,
                    funcao_safra TEXT,
                    turno_safra TEXT,
                    horario TEXT,
                    cetpp TEXT,
                    restricoes TEXT,
                    arcos TEXT,
                    cetcp TEXT,
                    caminho_cnh_pdf TEXT
                )
                """
            )
            cursor.execute("CREATE TABLE IF NOT EXISTS colaboradores_fotos (numero_colab TEXT PRIMARY KEY, tem_foto TEXT)")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS documentos (
                    id {identity_sql},
                    codigo_colaborador TEXT NOT NULL,
                    nome_documento TEXT NOT NULL,
                    data_validade TEXT,
                    caminho_arquivo TEXT NOT NULL,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores (codigo_colaborador) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS atestados (
                    id {identity_sql},
                    codigo_colaborador TEXT NOT NULL,
                    data_inicio TEXT,
                    data_fim TEXT,
                    motivo TEXT,
                    caminho_atestado_pdf TEXT,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores (codigo_colaborador) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS advertencias (
                    id {identity_sql},
                    codigo_colaborador TEXT NOT NULL,
                    data_infracao TEXT,
                    tipo_infracao TEXT,
                    descricao TEXT,
                    caminho_advertencia_pdf TEXT,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores (codigo_colaborador) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS log_auditoria (
                    id {identity_sql},
                    data_hora TEXT NOT NULL,
                    tipo_acao TEXT NOT NULL,
                    entidade_afetada TEXT NOT NULL,
                    id_entidade TEXT NOT NULL,
                    detalhes TEXT
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS cnh_historico (
                    id {identity_sql},
                    codigo_colaborador TEXT NOT NULL,
                    data_hora TEXT NOT NULL,
                    validade_anterior TEXT,
                    validade_nova TEXT,
                    categoria_anterior TEXT,
                    categoria_nova TEXT,
                    responsavel TEXT,
                    observacao TEXT,
                    caminho_comprovante TEXT,
                    origem TEXT,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores (codigo_colaborador) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS cnh_acompanhamentos (
                    id {identity_sql},
                    codigo_colaborador TEXT NOT NULL,
                    data_hora TEXT NOT NULL,
                    status TEXT NOT NULL,
                    responsavel TEXT,
                    observacao TEXT,
                    data_prevista TEXT,
                    houve_contato INTEGER NOT NULL DEFAULT 0,
                    caminho_comprovante TEXT,
                    origem TEXT,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores (codigo_colaborador) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS informes_diarios_cabecalho (
                    id {identity_sql},
                    mes INTEGER NOT NULL,
                    ano INTEGER NOT NULL,
                    nome_arquivo TEXT,
                    data_importacao TEXT,
                    UNIQUE(mes, ano)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS informes_diarios_detalhe (
                    id {identity_sql},
                    cabecalho_id INTEGER NOT NULL,
                    codigo_colaborador TEXT NOT NULL,
                    nome_colaborador TEXT,
                    codigo_interno TEXT,
                    frente TEXT,
                    turno_safra TEXT,
                    dia INTEGER,
                    valor_ido REAL,
                    tipo_valor TEXT,
                    FOREIGN KEY (cabecalho_id) REFERENCES informes_diarios_cabecalho(id) ON DELETE CASCADE,
                    FOREIGN KEY (codigo_colaborador) REFERENCES colaboradores(codigo_colaborador) ON DELETE CASCADE
                )
                """
            )

            colunas_existentes = _get_existing_columns(cursor, "informes_diarios_detalhe")
            if "frente" not in colunas_existentes:
                cursor.execute("ALTER TABLE informes_diarios_detalhe ADD COLUMN frente TEXT")
            if "turno_safra" not in colunas_existentes:
                cursor.execute("ALTER TABLE informes_diarios_detalhe ADD COLUMN turno_safra TEXT")

            colunas_colaboradores = _get_existing_columns(cursor, "colaboradores")
            for coluna, tipo in COLUNAS_ADICIONAIS_COLABORADORES.items():
                if coluna not in colunas_colaboradores:
                    cursor.execute(f"ALTER TABLE colaboradores ADD COLUMN {coluna} {tipo}")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_nome ON colaboradores (nome)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_codigo_interno ON colaboradores (codigo_interno)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_situacao ON colaboradores (situacao)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_frente ON colaboradores (frente_safra)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_gestor ON colaboradores (gestor_responsavel)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_cidade ON colaboradores (cidade)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_oculto_operacao ON colaboradores (oculto_operacao)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documentos_cod_colab ON documentos (codigo_colaborador)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documentos_validade ON documentos (data_validade)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_validade_cnh ON colaboradores (validade_cnh)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_colaboradores_status_cnh ON colaboradores (status_cnh_acompanhamento)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cnh_historico_cod_colab ON cnh_historico (codigo_colaborador, data_hora DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cnh_acompanhamentos_cod_colab ON cnh_acompanhamentos (codigo_colaborador, data_hora DESC)")
            cursor.execute(
                """
                UPDATE colaboradores
                SET status_cnh_acompanhamento = 'SEM_ACAO'
                WHERE status_cnh_acompanhamento IS NULL OR status_cnh_acompanhamento = ''
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            if is_postgresql():
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (SCHEMA_VERSION, _agora_str()),
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _agora_str()),
                )
            conn.commit()
            logging.info("Schema do banco verificado/criado com sucesso (%s).", DB_ENGINE)
    except DatabaseError as e:
        logging.critical(f"Erro ao conectar, criar ou migrar tabelas no banco de dados: {e}")
        raise


def criar_tabelas_sqlite() -> None:
    garantir_schema_banco()


def _postgres_cli_connection() -> tuple[dict[str, str], list[str]]:
    from agricola_shared.demo_safety import assert_demo_database_target
    assert_demo_database_target(str(DATABASE_URL or ""))
    parsed = urlparse(str(DATABASE_URL or ""))
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.path.lstrip("/"):
        raise ValueError("Configuracao PostgreSQL invalida para backup/restore.")
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    args = [
        "-h", parsed.hostname or "127.0.0.1",
        "-p", str(parsed.port or 5432),
        "-U", unquote(parsed.username or ""),
        "-d", parsed.path.lstrip("/"),
    ]
    return env, args


def _sqlite_quick_check(path: str | Path) -> None:
    database_path = Path(path).resolve()
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).strip().lower() != "ok":
            raise sqlite3.DatabaseError(str(row[0]) if row else "quick_check sem retorno")
    finally:
        connection.close()


def _sqlite_backup_file(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination_path)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    _sqlite_quick_check(destination_path)
    return destination_path


def criar_backup_db(backup_folder: str | None = None) -> tuple[bool, str]:
    try:
        destino_backup = Path(backup_folder or BACKUP_FOLDER_DEFAULT).resolve()
        destino_backup.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if is_postgresql():
            backup_path = destino_backup / f"colaboradores_backup_{timestamp}.dump"
            env, connection_args = _postgres_cli_connection()
            subprocess.run(
                [
                    "pg_dump",
                    *connection_args,
                    "--format=custom",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--encoding=UTF8",
                    "--file",
                    str(backup_path),
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            logging.info(f"Backup PostgreSQL criado com sucesso em: {backup_path}")
            return True, f"Backup PostgreSQL criado com sucesso em:\n{backup_path}"

        if not Path(DB_PATH).exists():
            return False, f"Erro: Arquivo do banco de dados '{DB_PATH}' não encontrado."
        backup_path = destino_backup / f"colaboradores_backup_{timestamp}.db"
        _sqlite_backup_file(DB_PATH, backup_path)
        logging.info(f"Backup do banco de dados criado com sucesso em: {backup_path}")
        return True, f"Backup do banco de dados criado com sucesso em:\n{backup_path}"
    except subprocess.CalledProcessError as e:
        detalhe = e.stderr.strip() if e.stderr else str(e)
        logging.error("Erro ao executar pg_dump: %s", detalhe)
        return False, f"Erro ao executar pg_dump: {detalhe}"
    except Exception as e:
        logging.error(f"Erro inesperado ao criar backup do banco de dados: {e}", exc_info=True)
        return False, f"Erro inesperado ao criar backup do banco de dados: {e}"


def restaurar_backup_db(backup_path: str, criar_backup_seguranca: bool = True) -> tuple[bool, str]:
    try:
        caminho_origem = Path(backup_path).resolve()
        if not caminho_origem.exists() or not caminho_origem.is_file():
            return False, f"Arquivo de backup não encontrado: {caminho_origem}"

        if criar_backup_seguranca:
            ok, mensagem = criar_backup_db()
            if not ok:
                return False, f"Falha ao criar backup de segurança antes da restauração: {mensagem}"

        if is_postgresql():
            env, connection_args = _postgres_cli_connection()
            subprocess.run(
                ["pg_restore", "--list", str(caminho_origem)],
                check=True,
                capture_output=True,
                text=True,
            )
            with database_quiescence():
                subprocess.run(
                    [
                        "pg_restore",
                        *connection_args,
                        "--clean",
                        "--if-exists",
                        "--no-owner",
                        "--no-privileges",
                        "--single-transaction",
                        str(caminho_origem),
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            logging.info("Backup PostgreSQL restaurado com sucesso a partir de: %s", caminho_origem)
            return True, f"Backup PostgreSQL restaurado com sucesso de:\n{caminho_origem}"

        if caminho_origem.suffix.lower() != ".db":
            return False, "Para SQLite, informe um arquivo de backup com extensão .db"
        _sqlite_quick_check(caminho_origem)

        destino = Path(DB_PATH).resolve()
        destino.parent.mkdir(parents=True, exist_ok=True)
        transaction_id = uuid.uuid4().hex
        staged = destino.parent / f".{destino.name}.restore-staging-{transaction_id}.db"
        rollback = destino.parent / f".{destino.name}.restore-rollback-{transaction_id}.db"
        moved_sidecars: list[tuple[Path, Path]] = []
        _sqlite_backup_file(caminho_origem, staged)
        try:
            with database_quiescence():
                try:
                    if destino.exists():
                        destino.replace(rollback)
                    for suffix in ("-wal", "-shm", "-journal"):
                        sidecar = Path(f"{destino}{suffix}")
                        if sidecar.exists():
                            sidecar_rollback = Path(f"{rollback}{suffix}")
                            sidecar.replace(sidecar_rollback)
                            moved_sidecars.append((sidecar_rollback, sidecar))
                    staged.replace(destino)
                    _sqlite_quick_check(destino)
                except Exception:
                    if destino.exists():
                        destino.unlink()
                    if rollback.exists():
                        rollback.replace(destino)
                    for saved, original in moved_sidecars:
                        if saved.exists():
                            saved.replace(original)
                    raise
        finally:
            if staged.exists():
                staged.unlink()
        if rollback.exists():
            rollback.unlink()
        for saved, _original in moved_sidecars:
            if saved.exists():
                saved.unlink()
        logging.info("Backup SQLite restaurado com sucesso a partir de: %s", caminho_origem)
        return True, f"Backup SQLite restaurado com sucesso de:\n{caminho_origem}"
    except subprocess.CalledProcessError as e:
        detalhe = e.stderr.strip() if e.stderr else str(e)
        logging.error("Erro ao restaurar backup do banco: %s", detalhe)
        return False, f"Erro ao restaurar backup do banco: {detalhe}"
    except Exception as e:
        logging.error("Erro inesperado ao restaurar backup do banco: %s", e, exc_info=True)
        return False, f"Erro inesperado ao restaurar backup do banco: {e}"

def colaborador_existe(codigo_colaborador: str) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM colaboradores WHERE codigo_colaborador = ?", (codigo_colaborador,))
            return cursor.fetchone()[0] > 0
    except DatabaseError as e:
        logging.error(f"Erro ao verificar existência do colaborador {codigo_colaborador}: {e}")
        return False

def pre_cadastrar_colaborador_se_nao_existe(codigo_colaborador: str, nome: str, codigo_interno: str | None) -> bool:
    if not codigo_colaborador or not nome: return False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            _insert_pre_cadastro(cursor, codigo_colaborador, nome, codigo_interno)
            if cursor.rowcount > 0:
                registrar_log_auditoria('PRE_CADASTRO', 'COLABORADOR', codigo_colaborador, {'nome': nome})
            conn.commit()
            return True
    except DatabaseError as e:
        logging.error(f"Erro ao pré-cadastrar colaborador {codigo_colaborador}: {e}")
        return False

def obter_valores_unicos_coluna(nome_coluna: str) -> list[str]:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if nome_coluna == "funcao_safra":
                query = """
                    SELECT DISTINCT COALESCE(NULLIF(funcao_safra, ''), NULLIF(funcao, '')) AS valor
                    FROM colaboradores
                    WHERE COALESCE(NULLIF(funcao_safra, ''), NULLIF(funcao, '')) IS NOT NULL
                      AND COALESCE(oculto_operacao, 0) = 0
                    ORDER BY valor
                """
            elif nome_coluna == "cidade":
                query = """
                    SELECT DISTINCT COALESCE(NULLIF(cidade, ''), NULLIF(municipio, '')) AS valor
                    FROM colaboradores
                    WHERE COALESCE(NULLIF(cidade, ''), NULLIF(municipio, '')) IS NOT NULL
                      AND COALESCE(oculto_operacao, 0) = 0
                    ORDER BY valor
                """
            else:
                query = f"SELECT DISTINCT {nome_coluna} FROM colaboradores WHERE COALESCE(oculto_operacao, 0) = 0 AND {nome_coluna} IS NOT NULL AND {nome_coluna} != '' ORDER BY {nome_coluna}"
            cursor.execute(query)
            return [item[0] for item in cursor.fetchall()]
    except DatabaseError as e:
        logging.error(f"Erro ao buscar valores únicos para a coluna {nome_coluna}: {e}")
        return []

def obter_colaborador_por_codigo(codigo_colaborador: str) -> dict | None:
    if not codigo_colaborador: return None
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT c.*, f.tem_foto FROM colaboradores c LEFT JOIN colaboradores_fotos f ON c.codigo_colaborador = f.numero_colab WHERE c.codigo_colaborador = ?"
            cursor.execute(query, (codigo_colaborador,))
            resultado = cursor.fetchone()
            return dict(resultado) if resultado else None
    except DatabaseError as e:
        logging.error(f"Erro ao obter colaborador por código {codigo_colaborador}: {e}")
        return None

def obter_colaboradores(filtro_nome: str = "", filtro_situacao: str = None, cnh_vencida: bool = False, filtro_funcao: str = "", filtro_turno: str = "", filtro_cidade: str = None) -> list[dict]:
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT c.*, f.tem_foto FROM colaboradores c LEFT JOIN colaboradores_fotos f ON c.codigo_colaborador = f.numero_colab WHERE COALESCE(c.oculto_operacao, 0) = 0"
            params = []
            if filtro_nome:
                like = f"%{filtro_nome}%"
                query += """
                    AND (
                        c.nome LIKE ?
                        OR c.codigo_colaborador LIKE ?
                        OR c.cpf LIKE ?
                        OR c.frente_safra LIKE ?
                        OR c.funcao_safra LIKE ?
                        OR c.funcao LIKE ?
                        OR c.situacao LIKE ?
                        OR c.telefone LIKE ?
                        OR c.cidade LIKE ?
                        OR c.municipio LIKE ?
                    )
                """
                params.extend([like] * 10)
            if filtro_situacao and filtro_situacao != "Todas":
                query += " AND c.situacao = ?"
                params.append(filtro_situacao)
            if cnh_vencida:
                query += " AND c.validade_cnh IS NOT NULL AND c.validade_cnh != '' AND c.validade_cnh < ?"
                params.append(date.today().strftime("%Y-%m-%d"))
            if filtro_funcao and filtro_funcao != "Todas":
                query += " AND COALESCE(NULLIF(c.funcao_safra, ''), NULLIF(c.funcao, '')) = ?"
                params.append(filtro_funcao)
            if filtro_turno and filtro_turno != "Todos":
                query += " AND c.turno_safra = ?"
                params.append(filtro_turno)
            if filtro_cidade and filtro_cidade != "Todas":
                query += " AND COALESCE(NULLIF(c.cidade, ''), NULLIF(c.municipio, '')) = ?"
                params.append(filtro_cidade)
            query += " ORDER BY c.nome"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    except DatabaseError as e:
        logging.error(f"Erro ao obter colaboradores com filtros: {e}")
        return []

def adicionar_colaborador(dados: dict) -> tuple[bool, str]:
    if not dados.get('codigo_colaborador') or not dados.get('nome'): return False, "Código e Nome são obrigatórios."
    try:
        with FileMutationJournal() as files:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                dados, erros_validacao = validar_dados_colaborador(dados)
                if erros_validacao:
                    return False, "\n".join(erros_validacao.values())
                if dados.get('caminho_cnh_pdf'):
                    dados['caminho_cnh_pdf'] = _preparar_caminho_upload(
                        dados.get('caminho_cnh_pdf'),
                        "cnh_comprovantes",
                        dados['codigo_colaborador'],
                        files,
                    )
                dados.setdefault('status_cnh_acompanhamento', 'SEM_ACAO')
                cols = list(dados.keys())
                vals = list(dados.values())
                placeholders = ', '.join(['?' for _ in vals])
                query = f"INSERT INTO colaboradores ({', '.join(cols)}) VALUES ({placeholders})"
                cursor.execute(query, vals)
                tem_foto = "SIM" if _tem_foto_armazenada(dados['codigo_colaborador']) else "NÃO"
                _upsert_foto_colaborador(cursor, dados["codigo_colaborador"], tem_foto)
                registrar_log_auditoria(
                    'ADICAO', 'COLABORADOR', dados['codigo_colaborador'],
                    {'nome': dados['nome']}, cursor=cursor,
                )
                files.promote()
                conn.commit()
                files.complete()
                return True, f"Colaborador '{dados['nome']}' adicionado com sucesso!"
    except OSError as e: return False, f"Erro ao preparar arquivo anexado: {e}"
    except IntegrityError: return False, f"Erro: Código '{dados.get('codigo_colaborador')}' já existe."
    except DatabaseError as e: return False, f"Erro no banco de dados: {e}"


def _stage_anexos_colaborador(cursor, files: FileMutationJournal, codigo_colaborador: str, colaborador: dict) -> None:
    """Move every referenced attachment to recoverable trash before cascade delete."""
    for coluna in ("caminho_cnh_pdf", "caminho_comprovante_cnh"):
        files.stage_delete_reference(colaborador.get(coluna))

    referencias = (
        ("documentos", "caminho_arquivo"),
        ("atestados", "caminho_atestado_pdf"),
        ("advertencias", "caminho_advertencia_pdf"),
        ("cnh_historico", "caminho_comprovante"),
        ("cnh_acompanhamentos", "caminho_comprovante"),
    )
    for tabela, coluna in referencias:
        cursor.execute(
            f"SELECT {coluna} FROM {tabela} WHERE codigo_colaborador = ?",
            (codigo_colaborador,),
        )
        for row in cursor.fetchall():
            try:
                referencia = row[coluna]
            except (KeyError, TypeError, IndexError):
                referencia = row[0]
            files.stage_delete_reference(referencia)

def atualizar_colaborador(*args) -> tuple[bool, str]:
    if len(args) == 1:
        dados = args[0]
        codigo_referencia = dados.get('codigo_colaborador')
    elif len(args) == 2:
        codigo_referencia, dados = args
    else:
        raise TypeError("atualizar_colaborador espera um dicionário ou (codigo_original, dicionário).")

    if not isinstance(dados, dict) or not dados.get('codigo_colaborador'):
        return False, "Código é obrigatório."

    try:
        with FileMutationJournal() as files, get_db_connection(dict_rows=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT c.*, f.tem_foto FROM colaboradores c LEFT JOIN colaboradores_fotos f ON c.codigo_colaborador = f.numero_colab WHERE c.codigo_colaborador = ?",
                (codigo_referencia,),
            )
            row_antigo = cursor.fetchone()
            colaborador_antigo = dict(row_antigo) if row_antigo else None
            if not colaborador_antigo:
                return False, "Colaborador não encontrado."

            dados_para_validacao = {k: v for k, v in colaborador_antigo.items() if k != 'tem_foto'}
            dados_para_validacao.update(dict(dados))
            dados, erros_validacao = validar_dados_colaborador(dados_para_validacao)
            if erros_validacao:
                return False, "\n".join(erros_validacao.values())

            codigo_novo = dados['codigo_colaborador']
            codigo_alterado = str(codigo_referencia) != str(codigo_novo)
            if dados.get('caminho_cnh_pdf'):
                dados['caminho_cnh_pdf'] = _preparar_caminho_upload(
                    dados.get('caminho_cnh_pdf'), "cnh_comprovantes", codigo_novo, files,
                )
            if codigo_alterado:
                cursor.execute("SELECT 1 FROM colaboradores WHERE codigo_colaborador = ?", (codigo_novo,))
                if cursor.fetchone():
                    return False, f"Erro: Código '{codigo_novo}' já existe."

                colunas = list(dados.keys())
                valores = [dados[coluna] for coluna in colunas]
                placeholders = ', '.join(['?' for _ in valores])
                cursor.execute(
                    f"INSERT INTO colaboradores ({', '.join(colunas)}) VALUES ({placeholders})",
                    valores,
                )
                for tabela in TABELAS_REFERENCIANDO_COLABORADOR:
                    cursor.execute(
                        f"UPDATE {tabela} SET codigo_colaborador = ? WHERE codigo_colaborador = ?",
                        (codigo_novo, codigo_referencia),
                    )
                cursor.execute(
                    "UPDATE colaboradores_fotos SET numero_colab = ? WHERE numero_colab = ?",
                    (codigo_novo, codigo_referencia),
                )
                files.move_path(_caminho_foto(codigo_referencia), _caminho_foto(codigo_novo))
                cursor.execute("DELETE FROM colaboradores WHERE codigo_colaborador = ?", (codigo_referencia,))
            else:
                set_clauses = ', '.join([f"{col} = ?" for col in dados.keys()])
                cursor.execute(
                    f"UPDATE colaboradores SET {set_clauses} WHERE codigo_colaborador = ?",
                    [*dados.values(), codigo_referencia],
                )

            tem_foto = "SIM" if _tem_foto_armazenada(codigo_novo) else "NÃO"
            _upsert_foto_colaborador(cursor, codigo_novo, tem_foto)

            validade_antiga = colaborador_antigo.get('validade_cnh')
            validade_nova = dados.get('validade_cnh', validade_antiga)
            categoria_antiga = colaborador_antigo.get('categoria_cnh')
            categoria_nova = dados.get('categoria_cnh', categoria_antiga)
            caminho_comprovante = dados.get('caminho_cnh_pdf') or colaborador_antigo.get('caminho_cnh_pdf')
            if (
                str(validade_antiga or "") != str(validade_nova or "")
                or str(categoria_antiga or "") != str(categoria_nova or "")
            ):
                _registrar_historico_cnh_cursor(
                    cursor, codigo_novo, validade_antiga, validade_nova,
                    categoria_antiga, categoria_nova, responsavel="CADASTRO",
                    observacao="Atualização manual do cadastro",
                    caminho_comprovante=caminho_comprovante,
                    origem="CADASTRO_MANUAL",
                )

            detalhes_auditoria = {
                key: {'de': colaborador_antigo.get(key), 'para': value}
                for key, value in dados.items()
                if str(colaborador_antigo.get(key)) != str(value)
            }
            if codigo_alterado:
                detalhes_auditoria['codigo_colaborador'] = {'de': codigo_referencia, 'para': codigo_novo}
            if detalhes_auditoria:
                registrar_log_auditoria(
                    'ATUALIZACAO', 'COLABORADOR', codigo_novo,
                    detalhes_auditoria, cursor=cursor,
                )
            caminho_antigo = colaborador_antigo.get('caminho_cnh_pdf')
            if caminho_antigo and caminho_antigo != dados.get('caminho_cnh_pdf'):
                files.stage_delete_reference(caminho_antigo)
            files.promote()
            conn.commit()
            files.complete()
            return True, f"Colaborador '{dados.get('nome') or colaborador_antigo.get('nome', codigo_novo)}' atualizado com sucesso!"
    except OSError as e: return False, f"Erro ao preparar arquivos do colaborador: {e}"
    except DatabaseError as e: return False, f"Erro no banco de dados: {e}"

def excluir_colaborador(codigo_colaborador: str) -> tuple[bool, str]:
    if not codigo_colaborador: return False, "Código não fornecido."
    try:
        with FileMutationJournal() as files:
            with get_db_connection(dict_rows=True) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM colaboradores WHERE codigo_colaborador = ?", (codigo_colaborador,))
                row = cursor.fetchone()
                colaborador_excluido = dict(row) if row else None
                if not colaborador_excluido:
                    return False, f"Colaborador com código '{codigo_colaborador}' não encontrado."
                _stage_anexos_colaborador(cursor, files, codigo_colaborador, colaborador_excluido)
                foto_path = _caminho_foto(codigo_colaborador)
                files.stage_delete_path(foto_path)
                for categoria in ("documentos", "atestados", "advertencias", "cnh_comprovantes"):
                    files.stage_delete_category(categoria, codigo_colaborador)
                cursor.execute("DELETE FROM colaboradores WHERE codigo_colaborador = ?", (codigo_colaborador,))
                registrar_log_auditoria(
                    'EXCLUSAO', 'COLABORADOR', codigo_colaborador,
                    {'nome_excluido': colaborador_excluido.get('nome') or 'N/A'}, cursor=cursor,
                )
                conn.commit()
                files.complete()
                return True, f"Colaborador '{colaborador_excluido.get('nome', codigo_colaborador)}' excluído!"
    except OSError as e: return False, f"Erro ao excluir arquivos do colaborador: {e}"
    except DatabaseError as e: return False, f"Erro no banco de dados: {e}"

def get_dashboard_summary() -> dict:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT situacao, COUNT(*) FROM colaboradores WHERE COALESCE(oculto_operacao, 0) = 0 GROUP BY situacao")
            summary = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
            cursor.execute("SELECT COUNT(*) FROM colaboradores WHERE COALESCE(oculto_operacao, 0) = 0")
            summary['total'] = cursor.fetchone()[0]
            return summary
    except DatabaseError: return {}

def get_documentos_a_vencer(dias: int = 30) -> list[dict]:
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            data_hoje = date.today().strftime("%Y-%m-%d")
            data_limite = (date.today() + timedelta(days=dias)).strftime("%Y-%m-%d")
            query = """
                SELECT c.codigo_colaborador, c.nome AS nome_colaborador, 'CNH' AS nome_documento, c.validade_cnh AS data_validade FROM colaboradores c WHERE COALESCE(c.oculto_operacao, 0) = 0 AND c.validade_cnh IS NOT NULL AND c.validade_cnh != '' AND c.validade_cnh BETWEEN ? AND ?
                UNION ALL
                SELECT d.codigo_colaborador, c.nome AS nome_colaborador, d.nome_documento, d.data_validade FROM documentos d JOIN colaboradores c ON d.codigo_colaborador = c.codigo_colaborador WHERE COALESCE(c.oculto_operacao, 0) = 0 AND d.data_validade IS NOT NULL AND d.data_validade != '' AND d.data_validade BETWEEN ? AND ?
                ORDER BY data_validade ASC, nome_colaborador ASC;
            """
            cursor.execute(query, (data_hoje, data_limite, data_hoje, data_limite))
            return [dict(row) for row in cursor.fetchall()]
    except DatabaseError: return []

def get_summary_by_cidade() -> list[tuple]:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT COALESCE(NULLIF(cidade, ''), NULLIF(municipio, '')) AS cidade_resumo, COUNT(*)
                FROM colaboradores
                WHERE COALESCE(NULLIF(cidade, ''), NULLIF(municipio, '')) IS NOT NULL
                  AND COALESCE(oculto_operacao, 0) = 0
                GROUP BY cidade_resumo ORDER BY COUNT(*) DESC LIMIT 10
            """
            cursor.execute(query)
            return cursor.fetchall()
    except DatabaseError as e:
        logging.error(f"Erro ao obter resumo por cidade: {e}")
        return []

def adicionar_documento(codigo_colaborador: str, nome_documento: str, *args) -> tuple[bool, str]:
    if len(args) == 1:
        data_validade = None
        caminho_arquivo = args[0]
    elif len(args) == 2:
        data_validade, caminho_arquivo = args
    else:
        raise TypeError("adicionar_documento espera (codigo, nome, caminho) ou (codigo, nome, data_validade, caminho).")

    try:
        with FileMutationJournal() as files, get_db_connection() as conn:
            caminho_arquivo_salvo = _preparar_caminho_upload(
                caminho_arquivo, "documentos", codigo_colaborador, files,
            )
            cursor = conn.cursor()
            cursor.execute("INSERT INTO documentos (codigo_colaborador, nome_documento, data_validade, caminho_arquivo) VALUES (?, ?, ?, ?)", (codigo_colaborador, nome_documento, data_validade, caminho_arquivo_salvo))
            registrar_log_auditoria(
                'ADICAO', 'DOCUMENTO', codigo_colaborador,
                {'nome_doc': nome_documento}, cursor=cursor,
            )
            files.promote()
            conn.commit()
            files.complete()
            return True, "Documento adicionado."
    except OSError as e: return False, f"Erro ao copiar documento: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def listar_documentos_por_colaborador(codigo_colaborador: str) -> list[dict]:
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documentos WHERE codigo_colaborador = ? ORDER BY nome_documento", (codigo_colaborador,))
            documentos = [dict(row) for row in cursor.fetchall()]
            for documento in documentos:
                caminho_resolvido = resolve_stored_path(documento.get('caminho_arquivo'))
                documento['caminho_arquivo_db'] = documento.get('caminho_arquivo', '')
                documento['caminho_arquivo'] = caminho_resolvido
                documento['tipo_documento'] = documento.get('nome_documento', '')
                documento['nome_arquivo'] = os.path.basename(caminho_resolvido or documento.get('caminho_arquivo_db', ''))
            return documentos
    except DatabaseError: return []

def excluir_documento(id_documento: int) -> tuple[bool, str]:
    try:
        with FileMutationJournal() as files, get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT codigo_colaborador, nome_documento, caminho_arquivo FROM documentos WHERE id = ?", (id_documento,))
            detalhes = cursor.fetchone()
            if not detalhes:
                return False, "Documento não encontrado."
            files.stage_delete_reference(detalhes[2])
            cursor.execute("DELETE FROM documentos WHERE id = ?", (id_documento,))
            registrar_log_auditoria(
                'EXCLUSAO', 'DOCUMENTO', detalhes[0],
                {'id_doc': id_documento, 'nome_doc': detalhes[1]}, cursor=cursor,
            )
            conn.commit()
            files.complete()
            return True, "Documento excluído."
    except OSError as e: return False, f"Erro ao excluir documento: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def adicionar_atestado(dados: dict) -> tuple[bool, str]:
    try:
        dados = dict(dados)
        with FileMutationJournal() as files, get_db_connection() as conn:
            dados['caminho_atestado_pdf'] = _preparar_caminho_upload(
                dados.get('caminho_atestado_pdf'),
                "atestados",
                dados.get('codigo_colaborador', ''),
                files,
            )
            cursor = conn.cursor()
            cursor.execute("INSERT INTO atestados (codigo_colaborador, data_inicio, data_fim, motivo, caminho_atestado_pdf) VALUES (?, ?, ?, ?, ?)", (dados.get('codigo_colaborador'), dados.get('data_inicio'), dados.get('data_fim'), dados.get('motivo'), dados.get('caminho_atestado_pdf')))
            registrar_log_auditoria(
                'ADICAO', 'ATESTADO', dados['codigo_colaborador'],
                {'motivo': dados.get('motivo')}, cursor=cursor,
            )
            files.promote()
            conn.commit()
            files.complete()
            return True, "Atestado adicionado."
    except OSError as e: return False, f"Erro ao copiar atestado: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def listar_atestados_por_colaborador(codigo_colaborador: str) -> list[dict]:
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM atestados WHERE codigo_colaborador = ? ORDER BY data_inicio DESC", (codigo_colaborador,))
            atestados = [dict(row) for row in cursor.fetchall()]
            for atestado in atestados:
                atestado['caminho_atestado_pdf_resolvido'] = resolve_stored_path(atestado.get('caminho_atestado_pdf'))
            return atestados
    except DatabaseError: return []

def excluir_atestado(id_atestado: int) -> tuple[bool, str]:
    try:
        with FileMutationJournal() as files, get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT codigo_colaborador, motivo, caminho_atestado_pdf FROM atestados WHERE id = ?", (id_atestado,))
            detalhes = cursor.fetchone()
            if not detalhes:
                return False, "Atestado não encontrado."
            files.stage_delete_reference(detalhes[2])
            cursor.execute("DELETE FROM atestados WHERE id = ?", (id_atestado,))
            registrar_log_auditoria(
                'EXCLUSAO', 'ATESTADO', detalhes[0],
                {'id_atestado': id_atestado, 'motivo': detalhes[1]}, cursor=cursor,
            )
            conn.commit()
            files.complete()
            return True, "Atestado excluído."
    except OSError as e: return False, f"Erro ao excluir atestado: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def adicionar_advertencia(dados: dict) -> tuple[bool, str]:
    try:
        dados = dict(dados)
        with FileMutationJournal() as files, get_db_connection() as conn:
            dados['caminho_advertencia_pdf'] = _preparar_caminho_upload(
                dados.get('caminho_advertencia_pdf'),
                "advertencias",
                dados.get('codigo_colaborador', ''),
                files,
            )
            cursor = conn.cursor()
            cursor.execute("INSERT INTO advertencias (codigo_colaborador, data_infracao, tipo_infracao, descricao, caminho_advertencia_pdf) VALUES (?, ?, ?, ?, ?)", (dados.get('codigo_colaborador'), dados.get('data_infracao'), dados.get('tipo_infracao'), dados.get('descricao'), dados.get('caminho_advertencia_pdf')))
            registrar_log_auditoria(
                'ADICAO', 'ADVERTENCIA', dados['codigo_colaborador'],
                {'tipo': dados.get('tipo_infracao')}, cursor=cursor,
            )
            files.promote()
            conn.commit()
            files.complete()
            return True, "Advertência adicionada."
    except OSError as e: return False, f"Erro ao copiar advertência: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def listar_advertencias_por_colaborador(codigo_colaborador: str) -> list[dict]:
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM advertencias WHERE codigo_colaborador = ? ORDER BY data_infracao DESC", (codigo_colaborador,))
            advertencias = [dict(row) for row in cursor.fetchall()]
            for advertencia in advertencias:
                advertencia['caminho_advertencia_pdf_resolvido'] = resolve_stored_path(advertencia.get('caminho_advertencia_pdf'))
            return advertencias
    except DatabaseError: return []

def excluir_advertencia(id_advertencia: int) -> tuple[bool, str]:
    try:
        with FileMutationJournal() as files, get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT codigo_colaborador, tipo_infracao, caminho_advertencia_pdf FROM advertencias WHERE id = ?", (id_advertencia,))
            detalhes = cursor.fetchone()
            if not detalhes:
                return False, "Advertência não encontrada."
            files.stage_delete_reference(detalhes[2])
            cursor.execute("DELETE FROM advertencias WHERE id = ?", (id_advertencia,))
            registrar_log_auditoria(
                'EXCLUSAO', 'ADVERTENCIA', detalhes[0],
                {'id_adv': id_advertencia, 'tipo': detalhes[1]}, cursor=cursor,
            )
            conn.commit()
            files.complete()
            return True, "Advertência excluída."
    except OSError as e: return False, f"Erro ao excluir advertência: {e}"
    except DatabaseError as e: return False, f"Erro DB: {e}"

def resetar_todas_escalas() -> tuple[bool, str]:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE colaboradores SET frente_safra = 'SEM ESCALA', turno_safra = NULL, funcao_safra = NULL, horario = NULL")
            conn.commit()
            registrar_log_auditoria('RESET', 'ESCALA', 'TODOS', {'acao_massa': 'reset_escalas'})
            return True, "Escalas resetadas."
    except DatabaseError as e: return False, f"Erro DB: {e}"

def atualizar_escala_por_nome(codigo_colaborador: str, nome_colaborador: str, frente_safra: str, turno_safra: str | None, funcao_safra: str | None, horario: str | None) -> tuple[bool, str]:
    if not codigo_colaborador: return False, "Código não fornecido."
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            colaborador_antigo = obter_colaborador_por_codigo(codigo_colaborador)
            cursor.execute(
                "UPDATE colaboradores SET frente_safra = ?, turno_safra = ?, funcao_safra = ?, horario = ? WHERE codigo_colaborador = ?",
                (frente_safra, turno_safra, funcao_safra, horario, codigo_colaborador)
            )
            conn.commit()
            if cursor.rowcount > 0:
                detalhes_auditoria = {
                    'frente_safra': {'de': colaborador_antigo.get('frente_safra'), 'para': frente_safra},
                    'turno_safra': {'de': colaborador_antigo.get('turno_safra'), 'para': turno_safra},
                }
                registrar_log_auditoria('ATUALIZACAO_ESCALA', 'COLABORADOR', codigo_colaborador, detalhes_auditoria)
                return True, "Escala atualizada."
            return False, "Colaborador não encontrado."
    except DatabaseError as e: return False, f"Erro DB: {e}"

def importar_observacoes_do_excel(caminho_arquivo: str) -> tuple[bool, str]:
    if not os.path.exists(caminho_arquivo):
        return False, f"Arquivo Excel não encontrado: {caminho_arquivo}"
    try:
        df = pd.read_excel(caminho_arquivo, sheet_name="Dados")
        df.columns = [str(c).upper().strip() for c in df.columns]
        if 'CODIGO' not in df.columns:
            return False, "A planilha 'Dados' precisa ter uma coluna chamada 'CODIGO' para identificar os funcionários."
        total_registros_importados = 0
        logs_erro = []
        data_importacao = datetime.now().strftime('%Y-%m-%d')
        for indice, linha in df.iterrows():
            codigo = linha.get('CODIGO')
            if pd.isna(codigo):
                continue
            codigo_str = _normalizar_codigo_importado(codigo)
            if not codigo_str:
                continue
            for i in range(1, 6):
                col_obs = f'OBSERVAÇAO {i}'
                if col_obs in df.columns and pd.notna(linha[col_obs]):
                    descricao = linha[col_obs]
                    dados_advertencia = {
                        'codigo_colaborador': codigo_str,
                        'data_infracao': data_importacao,
                        'tipo_infracao': 'Ocorrência Importada',
                        'descricao': str(descricao),
                        'caminho_advertencia_pdf': None
                    }
                    adicionar_advertencia(dados_advertencia)
                    total_registros_importados += 1
        mensagem_final = f"Importação concluída! {total_registros_importados} registros de observação importados."
        if logs_erro:
            mensagem_final += "\n\nOcorrências durante a importação:\n" + "\n".join(logs_erro)
        return True, mensagem_final
    except ValueError as ve:
        if "Worksheet 'Dados' not found" in str(ve):
            return False, "Erro: A planilha Excel não contém uma aba (planilha) chamada 'Dados'. Por favor, verifique o nome da aba."
        else:
            logging.exception("Erro de valor na importação de observações")
            return False, f"Ocorreu um erro de valor durante a importação: {ve}"
    except Exception as e:
        logging.exception("Erro na importação de observações")
        return False, f"Ocorreu um erro crítico durante a importação: {e}"

def listar_observacoes_para_cadastro(codigo_colaborador: str) -> dict:
    observacoes = {}
    if not codigo_colaborador:
        return observacoes
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, descricao FROM advertencias
                WHERE codigo_colaborador = ? AND (tipo_infracao = 'Observação Manual' OR tipo_infracao = 'Ocorrência Importada')
                ORDER BY data_infracao DESC, id DESC LIMIT 5
            """, (codigo_colaborador,))
            rows = cursor.fetchall()
            for i, row in enumerate(rows):
                observacoes[i + 1] = {'id': row['id'], 'texto': row['descricao']}
        return observacoes
    except DatabaseError as e:
        logging.error(f"Erro ao listar observações para cadastro: {e}")
        return {}

def salvar_observacoes_do_cadastro(codigo_colaborador: str, novas_observacoes):
    if not codigo_colaborador:
        return
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM advertencias
                WHERE codigo_colaborador = ? AND tipo_infracao = 'Observação Manual'
            """, (codigo_colaborador,))
            data_hoje = datetime.now().strftime('%Y-%m-%d')
            observacoes_normalizadas = {}
            if isinstance(novas_observacoes, str):
                texto = novas_observacoes.strip()
                if texto:
                    observacoes_normalizadas[1] = texto
            elif isinstance(novas_observacoes, dict):
                for chave, valor in novas_observacoes.items():
                    try:
                        indice = int(chave)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(valor, dict):
                        texto = str(valor.get('texto', '')).strip()
                    else:
                        texto = str(valor).strip()
                    if texto:
                        observacoes_normalizadas[indice] = texto

            for i in range(1, 6):
                texto_obs = observacoes_normalizadas.get(i)
                if texto_obs and texto_obs.strip():
                    cursor.execute(
                        """
                        INSERT INTO advertencias (
                            codigo_colaborador,
                            data_infracao,
                            tipo_infracao,
                            descricao,
                            caminho_advertencia_pdf
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            codigo_colaborador,
                            data_hoje,
                            'Observação Manual',
                            texto_obs,
                            None,
                        ),
                    )
            conn.commit()
    except DatabaseError as e:
        logging.error(f"Erro ao salvar observações do cadastro: {e}")


def registrar_acompanhamento_cnh(
    codigo_colaborador: str,
    status: str,
    responsavel: str = "",
    observacao: str = "",
    data_prevista: str | None = None,
    caminho_comprovante: str | None = None,
    houve_contato: bool = False,
    origem: str = "PAINEL_CNH",
) -> tuple[bool, str]:
    if not codigo_colaborador:
        return False, "Código do colaborador não informado."
    if not colaborador_existe(codigo_colaborador):
        return False, "Colaborador não encontrado."

    data_prevista_iso = _normalizar_data_iso(data_prevista) if data_prevista else None
    if data_prevista and not data_prevista_iso:
        return False, "Data prevista inválida."

    try:
        caminho_comprovante_salvo = _preparar_caminho_upload(
            caminho_comprovante,
            "cnh_comprovantes",
            codigo_colaborador,
        )
        with get_db_connection() as conn:
            cursor = conn.cursor()
            _registrar_acompanhamento_cnh_cursor(
                cursor,
                codigo_colaborador,
                status=status,
                responsavel=responsavel,
                observacao=observacao,
                data_prevista=data_prevista_iso,
                caminho_comprovante=caminho_comprovante_salvo,
                houve_contato=houve_contato,
                origem=origem,
            )
            conn.commit()

        registrar_log_auditoria(
            'ACOMPANHAMENTO_CNH',
            'COLABORADOR',
            codigo_colaborador,
            {
                'status': (status or '').strip().upper(),
                'responsavel': responsavel,
                'houve_contato': houve_contato,
                'data_prevista': data_prevista_iso,
                'origem': origem,
            },
        )
        return True, "Acompanhamento de CNH registrado."
    except OSError as e:
        logging.error(f"Erro ao preparar comprovante de CNH: {e}")
        return False, f"Erro ao copiar comprovante: {e}"
    except DatabaseError as e:
        logging.error(f"Erro ao registrar acompanhamento de CNH: {e}")
        return False, f"Erro no banco de dados: {e}"


def registrar_renovacao_cnh(
    codigo_colaborador: str,
    nova_validade: str,
    categoria_nova: str | None = None,
    responsavel: str = "",
    observacao: str = "",
    caminho_comprovante: str | None = None,
    origem: str = "PAINEL_CNH",
) -> tuple[bool, str]:
    if not codigo_colaborador:
        return False, "Código do colaborador não informado."

    nova_validade_iso = _normalizar_data_iso(nova_validade)
    if not nova_validade_iso:
        return False, "Data de validade inválida."

    colaborador = obter_colaborador_por_codigo(codigo_colaborador)
    if not colaborador:
        return False, "Colaborador não encontrado."

    categoria_final = categoria_nova if categoria_nova not in (None, "") else colaborador.get('categoria_cnh')

    try:
        caminho_comprovante_salvo = _preparar_caminho_upload(
            caminho_comprovante,
            "cnh_comprovantes",
            codigo_colaborador,
        )
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE colaboradores
                SET
                    validade_cnh = ?,
                    categoria_cnh = ?,
                    caminho_comprovante_cnh = COALESCE(?, caminho_comprovante_cnh),
                    caminho_cnh_pdf = COALESCE(?, caminho_cnh_pdf)
                WHERE codigo_colaborador = ?
                """,
                (nova_validade_iso, categoria_final, caminho_comprovante_salvo, caminho_comprovante_salvo, codigo_colaborador),
            )

            _registrar_historico_cnh_cursor(
                cursor,
                codigo_colaborador,
                colaborador.get('validade_cnh'),
                nova_validade_iso,
                colaborador.get('categoria_cnh'),
                categoria_final,
                responsavel=responsavel,
                observacao=observacao or "Renovação de CNH registrada",
                caminho_comprovante=caminho_comprovante_salvo or colaborador.get('caminho_comprovante_cnh'),
                origem=origem,
            )

            status_info = classificar_status_tecnico(nova_validade_iso)
            status_acomp = "REGULARIZADO" if status_info["status"] == "REGULAR" else "EM_ANDAMENTO"
            _registrar_acompanhamento_cnh_cursor(
                cursor,
                codigo_colaborador,
                status=status_acomp,
                responsavel=responsavel,
                observacao=observacao or "Validade de CNH atualizada",
                data_prevista=None,
                caminho_comprovante=caminho_comprovante_salvo,
                houve_contato=False,
                origem=origem,
            )

            conn.commit()

        registrar_log_auditoria(
            'RENOVACAO_CNH',
            'COLABORADOR',
            codigo_colaborador,
            {
                'validade_anterior': colaborador.get('validade_cnh'),
                'validade_nova': nova_validade_iso,
                'categoria_anterior': colaborador.get('categoria_cnh'),
                'categoria_nova': categoria_final,
                'responsavel': responsavel,
                'origem': origem,
            },
        )
        return True, "Renovação da CNH registrada com sucesso."
    except OSError as e:
        logging.error(f"Erro ao preparar comprovante de renovação: {e}")
        return False, f"Erro ao copiar comprovante: {e}"
    except DatabaseError as e:
        logging.error(f"Erro ao registrar renovação de CNH: {e}")
        return False, f"Erro no banco de dados: {e}"

def atualizar_validade_cnh_em_massa(caminho_arquivo: str) -> tuple[bool, str]:
    try:
        df = pd.read_excel(caminho_arquivo, sheet_name="Dados")
        df.columns = [str(c).upper().strip() for c in df.columns]

        if 'CODIGO' not in df.columns or 'VALIDADE CNH' not in df.columns:
            return False, "A planilha 'Dados' precisa ter as colunas 'CODIGO' e 'VALIDADE CNH'."

        logs_erro = []
        total_atualizados = 0
        categoria_coluna = 'CATEGORIA CNH' if 'CATEGORIA CNH' in df.columns else None

        for indice, linha in df.iterrows():
            codigo = linha.get('CODIGO')
            validade_cnh = linha.get('VALIDADE CNH')

            if pd.isna(codigo) or pd.isna(validade_cnh):
                continue

            codigo_str = _normalizar_codigo_importado(codigo)
            if not codigo_str:
                logs_erro.append(f"Linha {indice + 2}: Código inválido.")
                continue

            try:
                data_db = pd.to_datetime(validade_cnh).strftime('%Y-%m-%d')
                categoria_nova = None
                if categoria_coluna and pd.notna(linha.get(categoria_coluna)):
                    categoria_nova = str(linha.get(categoria_coluna)).strip()

                sucesso, mensagem = registrar_renovacao_cnh(
                    codigo_colaborador=codigo_str,
                    nova_validade=data_db,
                    categoria_nova=categoria_nova,
                    responsavel="IMPORTAÇÃO EXCEL",
                    observacao=f"Atualização em massa a partir de {os.path.basename(caminho_arquivo)}",
                    origem="IMPORTACAO_EXCEL",
                )
                if sucesso:
                    total_atualizados += 1
                else:
                    logs_erro.append(f"Linha {indice + 2}: {mensagem}")
            except (ValueError, TypeError):
                logs_erro.append(f"Linha {indice + 2}: Data de validade '{validade_cnh}' inválida para o código {codigo_str}.")

        if total_atualizados == 0 and logs_erro:
            return False, "Nenhum registro válido para atualização foi encontrado na planilha.\n" + "\n".join(logs_erro)

        if total_atualizados == 0:
            return False, "Nenhum registro válido para atualização foi encontrado na planilha."

        mensagem_final = f"Atualização concluída! {total_atualizados} registros de CNH atualizados."
        if logs_erro:
            mensagem_final += "\n\nAvisos:\n" + "\n".join(logs_erro)

        return True, mensagem_final

    except ValueError as ve:
        if "Worksheet 'Dados' not found" in str(ve):
            return False, "Erro: A planilha Excel não contém uma aba chamada 'Dados'."
        else:
            return False, f"Ocorreu um erro de valor: {ve}"
    except Exception as e:
        logging.exception("Erro na atualização em massa de CNH")
        return False, f"Ocorreu um erro crítico: {e}"

# --- FUNÇÃO ADICIONADA ---
def renovar_cnhs_vencidas_aleatoriamente() -> tuple[bool, str]:
    """
    Busca por todas as CNHs vencidas e atualiza a data de validade para
    uma data aleatória no ano de 2032.
    """
    try:
        colaboradores_vencidos = obter_colaboradores(cnh_vencida=True)

        if not colaboradores_vencidos:
            return True, "Nenhuma CNH vencida foi encontrada para renovar."

        updates_para_fazer = []
        for colab in colaboradores_vencidos:
            ano = 2032
            mes = random.randint(1, 12)
            dia = random.randint(1, 28)

            nova_data = f"{ano}-{mes:02d}-{dia:02d}"
            codigo = colab.get('codigo_colaborador')
            updates_para_fazer.append((nova_data, codigo))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE colaboradores SET validade_cnh = ?
                WHERE codigo_colaborador = ?
            """, updates_para_fazer)
            conn.commit()

            registrar_log_auditoria(
                'ATUALIZACAO_MASSA',
                'COLABORADOR',
                'TODOS_VENCIDOS',
                {'descricao': f'{len(updates_para_fazer)} CNHs vencidas foram renovadas para datas aleatórias em 2032.'}
            )

        return True, f"{len(updates_para_fazer)} CNHs vencidas foram renovadas com sucesso para datas aleatórias em 2032."

    except Exception as e:
        logging.exception("Erro ao renovar CNHs vencidas")
        return False, f"Ocorreu um erro crítico: {e}"
