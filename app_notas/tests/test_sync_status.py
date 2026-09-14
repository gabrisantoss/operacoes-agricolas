from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import json
import shutil
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from database import DB
from web_app.server import build_sync_status_payload, compact_sync_status


class SyncStatusTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"sync_status_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "notas.db"
        self.log_dir = self.temp_dir / "logs"
        self.log_dir.mkdir()
        self.db = DB(self.db_path, seed_from_excel=False)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_sync(self, synced_at: datetime) -> None:
        conn = self.db.conn
        conn.execute(
            """
            INSERT INTO fazendas (
                codigo, nome, id_mestre, codigo_mestre, fonte_mestre, sincronizado_em
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("100-001", "FAZ TESTE", "farm-1", "100-001", "balanca", synced_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            """
            INSERT INTO talhoes (
                id, fazenda_id_mestre, fazenda_codigo, fazenda_codigo_mestre,
                fazenda_nome, codigo, nome, fonte, sincronizado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("field-1", "farm-1", "100-001", "100-001", "FAZ TESTE", "1", "T1", "balanca", synced_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            """
            INSERT INTO sincronizacoes_cadastros (
                fonte, sincronizado_em, fazendas_lidas, fazendas_alteradas,
                talhoes_lidos, talhoes_alterados, origem, detalhes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "balanca",
                synced_at.strftime("%Y-%m-%d %H:%M:%S"),
                1,
                0,
                1,
                1,
                "http://127.0.0.1:8833/farms",
                json.dumps(
                    {
                        "source": "api",
                        "dry_run": False,
                        "talhoes_processados": 1,
                        "talhoes_inseridos": 1,
                        "talhoes_atualizados": 0,
                        "talhoes_removidos": 0,
                        "talhoes_ignorados_sem_fazenda": 0,
                    }
                ),
            ),
        )
        conn.commit()
        (self.log_dir / "sync-notas-balanca-20260609.log").write_text("ok\n", encoding="utf-8")

    def test_sync_status_ok_when_counts_match_and_recent(self):
        self._seed_sync(datetime.now() - timedelta(hours=1))

        payload = build_sync_status_payload(self.db_path, self.log_dir)

        self.assertTrue(payload["ok"])
        self.assertEqual("online", payload["status"])
        self.assertEqual("api", payload["sync"]["source"])
        self.assertEqual(1, payload["counts"]["fazendasBalanca"])
        self.assertEqual(1, payload["counts"]["talhoesBalanca"])
        self.assertEqual(1, payload["sync"]["fieldsSynced"])
        self.assertEqual(1, payload["sync"]["fieldsChanged"])
        self.assertEqual(1, payload["sync"]["fieldsInserted"])
        self.assertEqual(0, payload["sync"]["fieldsUpdated"])
        self.assertEqual(0, payload["sync"]["fieldsRemoved"])
        self.assertTrue(payload["recommendedCommands"]["dryRun"].endswith("--dry-run"))
        self.assertTrue(payload["log"]["path"].endswith("sync-notas-balanca-20260609.log"))

        compact = compact_sync_status(payload)
        self.assertTrue(compact["ok"])
        self.assertEqual("api", compact["source"])
        self.assertEqual(1, compact["counts"]["talhoesBalanca"])

    def test_sync_status_alert_when_stale(self):
        self._seed_sync(datetime.now() - timedelta(hours=30))

        payload = build_sync_status_payload(self.db_path, self.log_dir)

        self.assertFalse(payload["ok"])
        self.assertEqual("alerta", payload["status"])
        self.assertTrue(any("Ultima sincronizacao" in issue for issue in payload["issues"]))

        compact = compact_sync_status(payload)
        self.assertFalse(compact["ok"])
        self.assertTrue(compact["issues"])
        self.assertIn("dry-run", compact["recommendedCommands"]["dryRun"])


if __name__ == "__main__":
    unittest.main()
