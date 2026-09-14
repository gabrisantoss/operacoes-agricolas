import atexit
from datetime import date, timedelta
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from PyPDF2 import PdfReader


def _configure_isolated_runtime() -> None:
    existing = os.environ.get("APP_COLAB_TEST_RUNTIME")
    if existing:
        runtime = Path(existing)
    else:
        runtime = Path(tempfile.mkdtemp(prefix="app-colaboradores-tests-"))
        os.environ["APP_COLAB_TEST_RUNTIME"] = str(runtime)
        atexit.register(shutil.rmtree, runtime, ignore_errors=True)
    os.environ["APP_COLAB_CONFIG_FILE"] = str(runtime / "missing-config.json")
    os.environ["APP_COLAB_DB_ENGINE"] = "sqlite"
    os.environ["APP_COLAB_SQLITE_PATH"] = str(runtime / "colaboradores.db")
    os.environ["APP_COLAB_STORAGE_ROOT"] = str(runtime / "storage")
    os.environ["APP_COLAB_BACKUP_DIR"] = str(runtime / "backups")


_configure_isolated_runtime()

from core.cnh_management import listar_painel_cnh  # noqa: E402
from core.cnh_reports import CNHReportRow, gerar_pdf_categoria  # noqa: E402


SELECTED_COLUMNS = (
    "codigo_colaborador", "nome", "cidade", "municipio", "validade_cnh",
    "categoria_cnh", "frente_safra", "turno_safra", "horario", "funcao_safra",
    "funcao", "gestor_responsavel", "status_cnh_acompanhamento", "ultima_acao_cnh",
    "ultimo_contato_cnh", "responsavel_ultimo_contato_cnh",
    "data_prevista_regularizacao_cnh", "observacao_cnh", "caminho_comprovante_cnh",
    "caminho_cnh_pdf", "situacao", "local_trabalho", "oculto_operacao",
)


class CnhPaginationTests(unittest.TestCase):
    def test_post_filters_and_priority_order_run_before_pagination(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "cnh.db"
            connection = sqlite3.connect(database)
            definitions = ", ".join(
                f"{column} {'INTEGER' if column == 'oculto_operacao' else 'TEXT'}"
                for column in SELECTED_COLUMNS
            )
            connection.execute(f"CREATE TABLE colaboradores ({definitions})")

            future = (date.today() + timedelta(days=120)).isoformat()
            rows = [
                {"codigo_colaborador": "1", "nome": "Zulu Regular", "validade_cnh": future,
                 "categoria_cnh": "B", "caminho_cnh_pdf": "ok.pdf", "situacao": "ATIVO"},
                {"codigo_colaborador": "2", "nome": "Beta Sem Categoria", "validade_cnh": future,
                 "categoria_cnh": "", "caminho_cnh_pdf": "ok.pdf", "situacao": "ATIVO"},
                {"codigo_colaborador": "3", "nome": "Alpha Sem Validade", "validade_cnh": "",
                 "categoria_cnh": "B", "situacao": "ATIVO"},
            ]
            placeholders = ", ".join("?" for _ in SELECTED_COLUMNS)
            for row in rows:
                values = [row.get(column, 0 if column == "oculto_operacao" else "") for column in SELECTED_COLUMNS]
                connection.execute(
                    f"INSERT INTO colaboradores ({', '.join(SELECTED_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            connection.commit()
            connection.close()

            page, total = listar_painel_cnh(
                str(database), somente_com_inconsistencias=True, limit=1, offset=1
            )
            self.assertEqual(2, total)
            self.assertEqual(["2"], [row["codigo_colaborador"] for row in page])

    def test_pdf_repeats_headers_and_wraps_long_cells_on_every_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "cnh.pdf"
            rows = [
                CNHReportRow(
                    codigo_colaborador=f"C{index:04d}",
                    nome=f"Colaborador de Validacao com Nome Muito Extenso Numero {index:03d}",
                    frente_safra="Frente 1",
                    turno_safra="Turno 1",
                    funcao_safra="Operador de Maquinas Agricolas e Equipamentos",
                    validade_cnh="31/08/2026",
                    dias_para_vencer=-index,
                )
                for index in range(1, 81)
            ]

            gerar_pdf_categoria(rows, str(destination), "CNHs Vencidas", "Amostra controlada")
            pages = PdfReader(str(destination)).pages

            self.assertGreater(len(pages), 1)
            for page in pages:
                text = page.extract_text()
                self.assertIn("Frente: Frente 1", text)
                self.assertIn("Nome", text)
                self.assertIn("Codigo", text)
                self.assertIn("Funcao", text)


if __name__ == "__main__":
    unittest.main()
