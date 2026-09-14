from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from database import DB
from web_app.server import public_reference_audit_entries


class ReferenceAuditApiTestCase(unittest.TestCase):
    def setUp(self):
        self._old_colab_env = os.environ.get("APP_NOTAS_COLABORADORES_REFERENCIAS")
        os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = "0"
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"reference_audit_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.temp_dir / "notas.db", seed_from_excel=False)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self._old_colab_env is None:
            os.environ.pop("APP_NOTAS_COLABORADORES_REFERENCIAS", None)
        else:
            os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = self._old_colab_env

    def _insert_note(self, numero: int, referencias=None):
        payload = {
            "numero": numero,
            "motorista_cod": "953",
            "motorista_nome": "ADAIL ALVES DE ARAUJO",
            "caminhao": "ABC-1234",
            "operador_cod": None,
            "operador_nome": None,
            "colhedora": "950",
            "faz_muda_cod": "100-001",
            "faz_muda_nome": "Fazenda Origem",
            "talhao": "1",
            "faz_plantio_cod": "100-002",
            "faz_plantio_nome": "Fazenda Destino",
            "variedade_id": 1,
            "variedade_nome": "RB001",
            "data_colheita": "2026-06-11",
            "data_plantio": "2026-06-11",
        }
        if referencias:
            payload["_audit_event"] = "nota.create"
            payload["_referencias_origem"] = referencias
        self.db.inserir_nota(payload)

    def test_public_reference_audit_entries_returns_origin_trace(self):
        self._insert_note(
            100,
            {
                "motorista": {
                    "fonte": "portal_colaboradores",
                    "codigo": "953",
                    "nome": "ADAIL ALVES DE ARAUJO",
                },
                "talhao": {
                    "fonte": "balanca",
                    "codigo": "1",
                    "fazendaCodigo": "100-001",
                },
            },
        )

        items = public_reference_audit_entries(self.db, 100)

        self.assertEqual(1, len(items))
        self.assertEqual("nota.create", items[0]["evento"])
        self.assertEqual("portal_colaboradores", items[0]["referencias"]["motorista"]["fonte"])
        self.assertEqual("balanca", items[0]["referencias"]["talhao"]["fonte"])

    def test_public_reference_audit_entries_returns_empty_for_old_note(self):
        self._insert_note(101)

        self.assertEqual([], public_reference_audit_entries(self.db, 101))


if __name__ == "__main__":
    unittest.main()
