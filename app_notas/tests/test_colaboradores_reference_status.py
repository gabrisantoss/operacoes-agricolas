from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from colaboradores_reference import ColaboradoresReferenceProvider, ReferenceRecord
from web_app.server import build_colaboradores_status_payload


class ColaboradoresReferenceStatusTestCase(unittest.TestCase):
    def setUp(self):
        self._old_enabled = os.environ.get("APP_NOTAS_COLABORADORES_REFERENCIAS")
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"colab_status_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.temp_dir / "app_config.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self._old_enabled is None:
            os.environ.pop("APP_NOTAS_COLABORADORES_REFERENCIAS", None)
        else:
            os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = self._old_enabled

    def _write_postgres_config(self):
        self.config_path.write_text(
            json.dumps(
                {
                    "db_engine": "postgresql",
                    "postgres_host": "127.0.0.1",
                    "postgres_port": 5432,
                    "postgres_database": "app_colaboradores",
                    "postgres_user": "notas",
                    "postgres_password": "secret",
                }
            ),
            encoding="utf-8",
        )

    def test_status_alerta_quando_desativado(self):
        os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = "0"
        provider = ColaboradoresReferenceProvider(config_path=self.config_path)

        payload = provider.status()

        self.assertFalse(payload["ok"])
        self.assertEqual("desativado", payload["status"])
        self.assertTrue(payload["issues"])

    def test_status_ok_com_referencias_cacheadas(self):
        os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = "1"
        self._write_postgres_config()
        provider = ColaboradoresReferenceProvider(config_path=self.config_path)

        with patch("colaboradores_reference._find_psql", return_value="psql.exe"):
            with patch.object(
                provider,
                "_fetch_all",
                return_value=[
                    ReferenceRecord(
                        codigo="953",
                        nome="ADAIL ALVES DE ARAUJO",
                        fonte="portal_colaboradores",
                    )
                ],
            ):
                payload = provider.status()

        self.assertTrue(payload["ok"])
        self.assertEqual("online", payload["status"])
        self.assertEqual(1, payload["totalReferences"])
        self.assertEqual("portal_colaboradores", payload["source"])
        self.assertFalse(payload["issues"])

    def test_servidor_retorna_alerta_quando_provider_falha(self):
        class BrokenProvider:
            def status(self):
                raise RuntimeError("falha simulada")

        with patch("web_app.server.get_colaboradores_provider", return_value=BrokenProvider()):
            payload = build_colaboradores_status_payload()

        self.assertFalse(payload["ok"])
        self.assertIn("falha simulada", payload["issues"][0])
        self.assertTrue(payload["recommendedActions"])


if __name__ == "__main__":
    unittest.main()
