"""Configuracao do pacote de testes do App Notas.

IMPORTANTE: os testes unitarios deste pacote rodam em SQLite isolado (um banco
temporario por teste, criado em cada setUp). Isso garante que a suite:

  * NUNCA toque o PostgreSQL de producao (antes, sem este modulo, os testes
    herdavam APP_NOTAS_DATABASE_URL do app_notas.env e escreviam no banco real);
  * seja deterministica e independente do ambiente da maquina.

A cobertura do dialeto PostgreSQL (onde moram bugs como GROUP_CONCAT/CAST) fica
no teste de integracao dedicado `test_postgres_integration.py`, que cria um
schema descartavel proprio e e ignorado automaticamente se o Postgres de teste
nao estiver acessivel.

Este modulo roda no import do pacote `tests`, ANTES de qualquer submodulo
importar `app_config`/`database`, entao consegue fixar o engine como sqlite.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile

# Forca SQLite para a suite unitaria, a menos que o ambiente peca explicitamente
# outro engine para os testes (APP_NOTAS_TEST_DB_ENGINE).
os.environ["APP_NOTAS_DB_ENGINE"] = os.environ.get("APP_NOTAS_TEST_DB_ENGINE", "sqlite")
# Remove a URL de producao do ambiente do processo de teste para nao haver
# qualquer chance de conexao acidental ao banco real.
os.environ.pop("APP_NOTAS_DATABASE_URL", None)
os.environ["APP_NOTAS_DATABASE_URL"] = ""

_TEST_RUNTIME_ROOT = Path(tempfile.gettempdir()) / f"app_notas_tests_{os.getpid()}"


def test_temp_root() -> Path:
    """Retorna a raiz efemera da suite, sempre fora do repositorio."""

    _TEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    return _TEST_RUNTIME_ROOT


atexit.register(shutil.rmtree, _TEST_RUNTIME_ROOT, ignore_errors=True)
