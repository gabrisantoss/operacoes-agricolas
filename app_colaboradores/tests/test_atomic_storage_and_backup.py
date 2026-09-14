import atexit
from contextlib import nullcontext
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


def _configure_isolated_runtime() -> Path:
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
    return runtime


_configure_isolated_runtime()

import funcoes_colaboradores as colaboradores  # noqa: E402
from storage_manager import FileMutationJournal  # noqa: E402


def _value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM sample").fetchone()[0]
    finally:
        connection.close()


class AtomicStorageAndBackupTests(unittest.TestCase):
    def test_schema_records_current_version_idempotently(self):
        colaboradores.garantir_schema_banco()
        colaboradores.garantir_schema_banco()
        with colaboradores.get_db_connection() as connection:
            rows = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual([(colaboradores.SCHEMA_VERSION,)], [tuple(row) for row in rows])

    def test_schema_failure_is_not_swallowed_at_startup(self):
        with patch.object(
            colaboradores,
            "get_db_connection",
            side_effect=sqlite3.OperationalError("schema unavailable"),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "schema unavailable"):
                colaboradores.garantir_schema_banco()

    def test_file_journal_rolls_back_addition_and_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            source = root / "source.pdf"
            source.write_bytes(b"pdf")

            with self.assertRaises(RuntimeError):
                with FileMutationJournal(storage) as files:
                    relative = files.stage_file(str(source), "documentos", "123")
                    files.promote()
                    self.assertTrue((storage / relative).exists())
                    raise RuntimeError("database commit failed")
            self.assertFalse((storage / relative).exists())

            existing = storage / "documentos" / "123" / "existing.pdf"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(b"old")
            with self.assertRaises(RuntimeError):
                with FileMutationJournal(storage) as files:
                    self.assertTrue(files.stage_delete_path(existing))
                    self.assertFalse(existing.exists())
                    raise RuntimeError("database delete failed")
            self.assertEqual(b"old", existing.read_bytes())

    def test_file_journal_rejects_paths_outside_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = root / "storage"
            outside = root / "outside.pdf"
            outside.write_bytes(b"do not touch")

            with FileMutationJournal(storage) as files:
                with self.assertRaisesRegex(ValueError, "fora do storage"):
                    files.stage_delete_path(outside)
            self.assertEqual(b"do not touch", outside.read_bytes())

    def test_sqlite_backup_includes_wal_and_restore_is_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            live = root / "live.db"
            connection = sqlite3.connect(live)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sample VALUES ('from-wal')")
            connection.commit()

            backup = root / "backup.db"
            colaboradores._sqlite_backup_file(live, backup)
            self.assertEqual("from-wal", _value(backup))
            connection.close()

            replacement = root / "replacement.db"
            replacement_connection = sqlite3.connect(replacement)
            replacement_connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            replacement_connection.execute("INSERT INTO sample VALUES ('restored')")
            replacement_connection.commit()
            replacement_connection.close()

            with (
                patch.object(colaboradores, "DB_PATH", str(live)),
                patch.object(colaboradores, "is_postgresql", return_value=False),
                patch.object(colaboradores, "database_quiescence", nullcontext),
            ):
                ok, _message = colaboradores.restaurar_backup_db(
                    str(replacement), criar_backup_seguranca=False
                )
            self.assertTrue(ok)
            self.assertEqual("restored", _value(live))
            self.assertFalse(list(root.glob("*.restore-*.db")))

    def test_postgres_backup_does_not_put_url_or_password_in_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_url = "postgresql://oa_demo:super-secret@127.0.0.1:55439/oa_demo_tests"
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return None

            with (
                patch.object(colaboradores, "DATABASE_URL", database_url),
                patch.object(colaboradores, "is_postgresql", return_value=True),
                patch.object(colaboradores.subprocess, "run", side_effect=fake_run),
            ):
                ok, _message = colaboradores.criar_backup_db(temporary)
            self.assertTrue(ok)
            command, kwargs = calls[0]
            argv = " ".join(str(item) for item in command)
            self.assertNotIn(database_url, argv)
            self.assertNotIn("super-secret", argv)
            self.assertEqual("super-secret", kwargs["env"]["PGPASSWORD"])
            self.assertIn("--format=custom", command)

    def test_attachment_is_restored_if_database_delete_fails(self):
        colaboradores.garantir_schema_banco()
        code = "atomic-delete-1"
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "document.pdf"
            source.write_bytes(b"important")
            ok, message = colaboradores.adicionar_colaborador(
                {"codigo_colaborador": code, "nome": "Atomic Test"}
            )
            self.assertTrue(ok, message)
            ok, message = colaboradores.adicionar_documento(code, "Documento", str(source))
            self.assertTrue(ok, message)

            with colaboradores.get_db_connection() as connection:
                row = connection.execute(
                    "SELECT id, caminho_arquivo FROM documentos WHERE codigo_colaborador = ?",
                    (code,),
                ).fetchone()
                document_id, stored_reference = int(row[0]), row[1]
                connection.execute(
                    """
                    CREATE TRIGGER block_document_delete
                    BEFORE DELETE ON documentos
                    WHEN OLD.id = %d
                    BEGIN SELECT RAISE(ABORT, 'blocked by test'); END
                    """ % document_id
                )
                connection.commit()

            stored_path = Path(colaboradores.resolve_stored_path(stored_reference))
            ok, _message = colaboradores.excluir_documento(document_id)
            self.assertFalse(ok)
            self.assertEqual(b"important", stored_path.read_bytes())
            with colaboradores.get_db_connection() as connection:
                self.assertEqual(
                    1,
                    connection.execute(
                        "SELECT COUNT(*) FROM documentos WHERE id = ?", (document_id,)
                    ).fetchone()[0],
                )


if __name__ == "__main__":
    unittest.main()
