from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from database import DB
from web_app.server import (
    backup_path_allowed,
    create_manual_backup,
    list_backups,
    restore_backup_with_rollback,
    restore_confirmation_present,
)


class BackupApiSafetyTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"backup_api_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.app_root = self.temp_dir / "app_notas"
        self.drive_root = self.temp_dir / "drive"
        self.backup_dir = self.app_root / "backups"
        self.backup_dir.mkdir(parents=True)
        self.drive_root.mkdir()
        self.db_path = self.temp_dir / "transporte.db"
        self.db = DB(self.db_path, seed_from_excel=False)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_backup(self, name: str) -> Path:
        path = self.backup_dir / name
        self.db.create_backup(path)
        return path

    def _insert_note(self, motorista_nome: str) -> None:
        self.db.inserir_nota(
            {
                "numero": 77,
                "motorista_cod": "77",
                "motorista_nome": motorista_nome,
                "caminhao": "AAA-7777",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "950",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "1",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "RB001",
                "data_colheita": "2026-06-11",
                "data_plantio": "2026-06-11",
            },
            force=True,
        )

    def test_list_backups_hides_path_by_default_and_resolves_by_id(self):
        backup_path = self._write_backup("transporte_web_2026-06-11.db")

        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                items = list_backups()
                internal_items = list_backups(include_path=True)
                resolved = backup_path_allowed(items[0]["id"])

        self.assertEqual(1, len(items))
        self.assertIn("id", items[0])
        self.assertNotIn("path", items[0])
        self.assertIn("path", internal_items[0])
        self.assertEqual(backup_path.resolve(), resolved.resolve())

    def test_list_backups_includes_postgres_dump_files(self):
        dump_path = self.backup_dir / "transporte_web_2026-06-11.dump"
        dump_path.write_bytes(b"PGDMP fixture")

        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                items = list_backups()

        self.assertEqual([dump_path.name], [item["nome"] for item in items])

    def test_restore_token_rejects_raw_backup_path(self):
        backup_path = self._write_backup("transporte_web_2026-06-11.db")

        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                with self.assertRaises(ValueError):
                    backup_path_allowed(str(backup_path))

    def test_create_manual_backup_returns_sanitized_items(self):
        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                with patch("web_app.server.DB_PATH", self.db_path):
                    result = create_manual_backup(self.db)

        self.assertTrue(result["ok"])
        self.assertIn("items", result)
        self.assertNotIn("paths", result)
        self.assertTrue(result["items"])
        self.assertNotIn("path", result["items"][0])
        self.assertTrue(all(item.get("id") for item in result["items"]))

    def test_create_manual_backup_does_not_overwrite_same_minute_backup(self):
        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                with patch("web_app.server.DB_PATH", self.db_path):
                    with patch("web_app.server.datetime") as fake_datetime:
                        fake_datetime.now.return_value.strftime.return_value = "2026-06-11_08-55"
                        fake_datetime.fromtimestamp.side_effect = __import__("datetime").datetime.fromtimestamp
                        first = create_manual_backup(self.db)
                        second = create_manual_backup(self.db)

        first_names = {item["nome"] for item in first["items"]}
        second_names = {item["nome"] for item in second["items"]}

        self.assertEqual({"transporte_web_2026-06-11_08-55.db"}, first_names)
        self.assertIn("transporte_web_2026-06-11_08-55_1.db", second_names)
        self.assertTrue((self.backup_dir / "transporte_web_2026-06-11_08-55.db").exists())
        self.assertTrue((self.backup_dir / "transporte_web_2026-06-11_08-55_1.db").exists())

    def test_restore_requires_explicit_boolean_confirmation(self):
        self.assertTrue(restore_confirmation_present({"confirmRestore": True}))
        self.assertFalse(restore_confirmation_present({}))
        self.assertFalse(restore_confirmation_present({"confirmRestore": False}))
        self.assertFalse(restore_confirmation_present({"confirmRestore": "true"}))

    def test_restore_backup_creates_sanitized_pre_restore_rollback(self):
        self._insert_note("Estado do backup")
        source_backup = self._write_backup("transporte_web_source.db")
        self._insert_note("Estado atual antes do restore")

        with patch("web_app.server.APP_ROOT", self.app_root):
            with patch("web_app.server.BACKUP_DRIVE_PATH", self.drive_root):
                source_id = list_backups()[0]["id"]
                self.assertEqual(source_backup.name, list_backups()[0]["nome"])
                result = restore_backup_with_rollback(self.db, source_id)

        restored = self.db.buscar_nota(77)
        self.assertEqual("Estado do backup", restored["motorista_nome"])
        self.assertIn("rollbackBackup", result)
        self.assertNotIn("path", result["rollbackBackup"])
        self.assertTrue(result["rollbackBackup"]["nome"].startswith("pre_restore_"))

        rollback_path = self.backup_dir / result["rollbackBackup"]["nome"]
        rollback_db = DB(rollback_path, seed_from_excel=False)
        try:
            rollback_note = rollback_db.buscar_nota(77)
            self.assertEqual("Estado atual antes do restore", rollback_note["motorista_nome"])
        finally:
            rollback_db.close()


if __name__ == "__main__":
    unittest.main()
