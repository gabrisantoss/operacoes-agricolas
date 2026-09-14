from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import tests as _tests_bootstrap  # noqa: F401

from tools import restore_drill_postgres, restore_postgres


class RestoreToolSafetyTests(unittest.TestCase):
    def test_restore_requires_exact_confirmation_before_touching_files(self):
        with self.assertRaisesRegex(RuntimeError, "Confirmacao invalida"):
            restore_postgres.restore(
                Path("arquivo-inexistente.dump"),
                Path("backup-inexistente"),
                "INVALID",
            )

    def test_restore_refuses_a_database_other_than_app_notas(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "source.dump"
            dump.write_bytes(b"placeholder")
            with patch.object(
                restore_postgres,
                "DATABASE_URL",
                "postgresql://user:password@127.0.0.1:55439/outro_banco",
            ):
                with self.assertRaisesRegex(RuntimeError, "alvo configurado nao e oa_demo_notas"):
                    restore_postgres.restore(
                        dump,
                        Path(directory) / "backups",
                        restore_postgres.CONFIRMATION,
                    )

    def test_drill_refuses_remote_postgres_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "source.dump"
            dump.write_bytes(b"placeholder")
            with patch.object(
                restore_drill_postgres,
                "DATABASE_URL",
                "postgresql://user:password@192.0.2.10:55439/oa_demo_notas",
            ):
                with self.assertRaisesRegex(RuntimeError, "nao e local"):
                    restore_drill_postgres.run_drill(dump)

    def test_rollback_checksum_sidecar_is_atomic_and_correct(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "rollback.dump"
            dump.write_bytes(b"conteudo-controlado")
            digest, sidecar = restore_postgres._write_sha256_sidecar(dump)
            self.assertEqual(64, len(digest))
            self.assertEqual(f"{digest}  rollback.dump\n", sidecar.read_text(encoding="ascii"))
            self.assertFalse(sidecar.with_suffix(sidecar.suffix + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
