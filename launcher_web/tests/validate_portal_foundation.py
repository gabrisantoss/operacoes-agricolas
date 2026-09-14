from __future__ import annotations

import json
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "launcher_web"
sys.path.insert(0, str(LAUNCHER))
os.environ.setdefault("PORTAL_SKIP_LOCAL_ENV", "1")

from core.request_context import new_request_id
from services.backup_service import backup_sqlite_database, build_database_manifest
from services.health_service import check_system
from services.system_registry import load_systems
import server


class PortalFoundationValidation(unittest.TestCase):
    def test_systems_json_loads(self) -> None:
        systems = load_systems(LAUNCHER / "config" / "systems.json")
        ids = {system["id"] for system in systems}
        self.assertIn("portal", ids)
        self.assertIn("balanca", ids)
        self.assertEqual(next(system for system in systems if system["id"] == "balanca")["api_path"], "/balanca-api")

    def test_health_service_returns_status(self) -> None:
        result = check_system(
            {
                "id": "offline-test",
                "name": "Offline Test",
                "enabled": True,
                "internal_host": "127.0.0.1",
                "internal_port": 9,
                "health_url": "",
            },
            tcp_timeout=0.1,
        )
        self.assertIn(result["status"], {"offline", "unknown", "degraded", "online"})
        self.assertEqual(result["id"], "offline-test")

    def test_request_id_is_uuid4_shape(self) -> None:
        request_id = new_request_id()
        self.assertEqual(len(request_id), 36)
        self.assertEqual(request_id.count("-"), 4)

    def test_portal_schema_version_is_recorded_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = sqlite3.connect(Path(tmp) / "portal.db")
            try:
                server.record_portal_schema_version(connection)
                server.record_portal_schema_version(connection)
                rows = connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            finally:
                connection.close()
        self.assertEqual([(server.PORTAL_SCHEMA_VERSION,)], rows)

    def test_admin_permission_check(self) -> None:
        app = {"id": "balanca", "enabled": True, "requires_auth": True}
        self.assertTrue(server.user_can_access_system({"id": 1, "role": "admin", "email": server.ADMIN_USER}, app))
        self.assertFalse(server.user_can_access_system(None, app))

    def test_proxy_timeout_is_operationally_bounded(self) -> None:
        self.assertGreater(server.PROXY_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(server.PROXY_TIMEOUT_SECONDS, 15)
        self.assertGreaterEqual(server.REPORT_PROXY_TIMEOUT_SECONDS, 60)
        self.assertLessEqual(server.REPORT_PROXY_TIMEOUT_SECONDS, 180)
        self.assertEqual(
            server.proxy_timeout_for("notas", "/api/relatorios/export"),
            server.REPORT_PROXY_TIMEOUT_SECONDS,
        )
        self.assertEqual(server.proxy_timeout_for("notas", "/api/status"), server.PROXY_TIMEOUT_SECONDS)
        self.assertEqual(
            server.proxy_timeout_for("colaboradores", "/api/relatorios/export"),
            server.PROXY_TIMEOUT_SECONDS,
        )

    def test_backup_manifest_for_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            source = tmp_dir / "source.db"
            backup = tmp_dir / "backup.db"
            conn = sqlite3.connect(source)
            try:
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO sample (name) VALUES ('ok')")
                conn.commit()
            finally:
                conn.close()

            backup_sqlite_database(source, backup)
            manifest = build_database_manifest("sample", source, backup)
            self.assertEqual(manifest["integrity_check"], "ok")
            self.assertGreater(manifest["size_bytes"], 0)
            json.dumps(manifest)

    def test_path_containment_and_archive_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertTrue(server.path_is_within(root / "assets" / "app.js", root))
            self.assertFalse(server.path_is_within(root.parent / "outside.txt", root))
        self.assertTrue(server.archive_member_is_safe("bancos/portal.dump"))
        self.assertFalse(server.archive_member_is_safe("../portal.dump"))
        self.assertFalse(server.archive_member_is_safe("/bancos/portal.dump"))

    def test_backup_manifest_requires_exact_database_set(self) -> None:
        labels = ("portal", "notas", "colaboradores", "analises", "balanca")
        databases = [
            {
                "name": label,
                "engine": "postgresql",
                "file": f"bancos/{label}.dump",
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
            for label in labels
        ]
        manifest = {"formatVersion": server.BACKUP_FORMAT_VERSION, "databases": databases, "folders": []}
        archive_names = ["manifest.json", *(item["file"] for item in databases)]
        self.assertTrue(server.validate_backup_manifest(manifest, archive_names)["ok"])

        incomplete = {**manifest, "databases": databases[:-1]}
        result = server.validate_backup_manifest(incomplete, archive_names[:-1])
        self.assertFalse(result["ok"])
        self.assertTrue(any("ausentes" in item for item in result["errors"]))

    def test_backup_manifest_response_removes_internal_paths(self) -> None:
        manifest = {
            "formatVersion": 2,
            "databases": [
                {
                    "name": "portal",
                    "engine": "postgresql",
                    "file": "bancos/portal.dump",
                    "target": "internal-target",
                    "backup_file": "internal-temp-path",
                    "path": "internal-source-path",
                }
            ],
            "folders": [{"label": "documents", "source": "internal-source", "files": 2}],
            "computer": "internal-host",
        }
        sanitized = server.sanitize_backup_manifest(manifest)
        encoded = json.dumps(sanitized)
        self.assertNotIn("internal-", encoded)
        self.assertNotIn("computer", sanitized)

    def test_full_backup_verifier_accepts_complete_checksummed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_dir = root / "backups"
            backup_dir.mkdir()
            archive_path = backup_dir / "portal_agricola_20260101_000000.zip"
            manifest_databases = []
            database_paths = []
            for label in sorted(server.REQUIRED_BACKUP_DATABASE_LABELS):
                database = root / f"{label}.db"
                conn = sqlite3.connect(database)
                try:
                    conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
                    conn.execute("INSERT INTO sample (value) VALUES ('ok')")
                    conn.commit()
                finally:
                    conn.close()
                entry = f"bancos/{label}.db"
                database_paths.append((database, entry))
                manifest_databases.append(
                    {
                        "name": label,
                        "engine": "sqlite",
                        "file": entry,
                        "size_bytes": database.stat().st_size,
                        "sha256": server.sha256_file(database),
                    }
                )
            manifest = {
                "formatVersion": server.BACKUP_FORMAT_VERSION,
                "databases": manifest_databases,
                "folders": [],
            }
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for database, entry in database_paths:
                    archive.write(database, entry)
                archive.writestr("manifest.json", json.dumps(manifest))
            server.write_checksum_sidecar(archive_path)

            previous_backup_dir = server.BACKUP_DIR
            previous_temp_dir = server.BACKUP_TEMP_DIR
            try:
                server.BACKUP_DIR = backup_dir
                server.BACKUP_TEMP_DIR = root / "verify-temp"
                result = server.verify_portal_backup(archive_path.name)
            finally:
                server.BACKUP_DIR = previous_backup_dir
                server.BACKUP_TEMP_DIR = previous_temp_dir
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(result["databases"]), len(server.REQUIRED_BACKUP_DATABASE_LABELS))
            self.assertTrue(all(item["checksum_ok"] for item in result["databases"]))

    def test_backup_retention_plan_is_non_destructive_by_default(self) -> None:
        paths = [
            Path(f"portal_agricola_202601{day:02d}_120000.zip")
            for day in range(1, 21)
        ]
        plan = server.build_retention_plan(paths, daily=3, weekly=2, monthly=1)
        self.assertEqual(plan["total"], 20)
        self.assertIn("portal_agricola_20260120_120000.zip", plan["keep"])
        self.assertGreater(len(plan["deleteCandidates"]), 0)
        with tempfile.TemporaryDirectory() as tmp:
            result = server.apply_retention_plan(Path(tmp), plan, enabled=False)
        self.assertFalse(result["enabled"])
        self.assertEqual(result["deleted"], [])

    def test_zip_checksum_and_offsite_copy_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "local"
            offsite = root / "offsite"
            local.mkdir()
            offsite.mkdir()
            backup = local / "portal_agricola_20260101_010101.zip"
            backup.write_bytes(b"backup-test")
            checksum = server.write_checksum_sidecar(backup)
            self.assertTrue(checksum["ok"])
            self.assertTrue(server.verify_checksum_sidecar(backup, require=True)["ok"])

            copied = server.replicate_backup_offsite(backup, offsite)
            self.assertTrue(copied["ok"])
            self.assertTrue(copied["validated"])
            self.assertTrue((offsite / backup.name).exists())
            self.assertTrue(server.verify_checksum_sidecar(offsite / backup.name, require=True)["ok"])

            backup.write_bytes(b"backup-alterado")
            self.assertFalse(server.verify_checksum_sidecar(backup, require=True)["ok"])
            refused = server.replicate_backup_offsite(backup, offsite)
            self.assertFalse(refused["ok"])

    def test_proxy_limits_are_bounded(self) -> None:
        self.assertGreater(server.PROXY_MAX_REQUEST_BODY_BYTES, 0)
        self.assertGreater(server.PROXY_MAX_RESPONSE_BODY_BYTES, 0)
        with self.assertRaises(server.ProxyResponseTooLarge):
            server.read_limited_proxy_response(
                source := tempfile.SpooledTemporaryFile(),
                {"Content-Length": str(server.PROXY_MAX_RESPONSE_BODY_BYTES + 1)},
            )
        source.close()

    def test_mutating_requests_check_origin_before_proxy(self) -> None:
        for method_name in ("do_POST", "do_PUT", "do_PATCH", "do_DELETE"):
            source = inspect.getsource(getattr(server.LauncherHandler, method_name))
            self.assertLess(source.index("reject_untrusted_api_origin"), source.index("maybe_proxy_request"))

    def test_public_health_has_no_write_probe_or_detailed_checks(self) -> None:
        source = inspect.getsource(server.portal_health)
        self.assertNotIn(".portal_write_test", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn('"checks": checks', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
