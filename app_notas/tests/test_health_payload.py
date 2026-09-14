from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from database import DB
from web_app import server
from web_app.server import build_health_payload, independent_report_connection


class FakeWebDb:
    def __init__(self, usable: bool):
        self.usable = usable
        self.closed = False

    def is_connection_usable(self) -> bool:
        return self.usable

    def close(self) -> None:
        self.closed = True


class FakeReportConnection:
    def __init__(self):
        self.rolled_back = False
        self.closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class HealthPayloadTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"health_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "notas.db"
        self.db = DB(self.db_path, seed_from_excel=False)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_public_health_payload_is_sanitized(self):
        with patch("web_app.server.DB_PATH", self.db_path):
            payload = build_health_payload()

        self.assertTrue(payload["ok"])
        self.assertNotIn("path", payload["database"])
        self.assertNotIn("references", payload)
        self.assertNotIn("colaboradores", payload)
        self.assertNotIn(str(self.temp_dir), json.dumps(payload, ensure_ascii=False))

    def test_internal_health_payload_can_include_operational_details(self):
        sync_payload = {
            "ok": True,
            "status": "online",
            "message": "Sync OK.",
            "issues": [],
            "counts": {"fazendasBalanca": 1, "talhoesBalanca": 1},
            "sync": {"source": "sqlite", "syncedAt": "2026-06-11 06:19:10"},
        }
        colaboradores_payload = {
            "ok": False,
            "status": "alerta",
            "issues": ["falha simulada"],
            "message": "Portal Colaboradores requer atencao.",
        }

        with patch("web_app.server.DB_PATH", self.db_path):
            with patch("web_app.server.build_sync_status_payload", return_value=sync_payload):
                with patch("web_app.server.build_colaboradores_status_payload", return_value=colaboradores_payload):
                    payload = build_health_payload(include_operational_details=True)

        self.assertIn("path", payload["database"])
        self.assertIn("references", payload)
        self.assertIn("colaboradores", payload)
        self.assertTrue(any("Colaboradores" in item for item in payload["warnings"]))

    def test_get_db_replaces_an_unusable_shared_connection(self):
        stale_db = FakeWebDb(usable=False)
        fresh_db = FakeWebDb(usable=True)

        with patch.object(server, "DB_INSTANCE", stale_db):
            with patch.object(server, "DB", return_value=fresh_db) as db_factory:
                result = server.get_db()

        self.assertIs(result, fresh_db)
        self.assertTrue(stale_db.closed)
        db_factory.assert_called_once_with()

    def test_postgres_report_uses_a_separate_connection_and_releases_it(self):
        report_conn = FakeReportConnection()
        with patch.object(server, "DB_ENGINE", "postgresql"):
            with patch.object(server, "DATABASE_URL", "postgresql://example.invalid/notas"):
                with patch.object(server, "connect_postgres_db", return_value=report_conn) as connector:
                    with independent_report_connection() as yielded:
                        self.assertIs(report_conn, yielded)

        connector.assert_called_once()
        self.assertTrue(report_conn.rolled_back)
        self.assertTrue(report_conn.closed)


if __name__ == "__main__":
    unittest.main()
