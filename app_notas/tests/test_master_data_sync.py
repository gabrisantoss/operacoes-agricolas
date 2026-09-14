from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import json
import shutil
import sqlite3
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from database import DB
from master_data_sync import _read_master_data, sync_balanca_master_data


class MasterDataSyncTestCase(unittest.TestCase):
    def test_auto_api_failure_does_not_fallback_to_sqlite(self):
        with (
            patch("master_data_sync._read_master_data_from_api", side_effect=RuntimeError("api offline")),
            patch("master_data_sync._read_master_data_from_sqlite") as sqlite_reader,
        ):
            with self.assertRaisesRegex(RuntimeError, "api offline"):
                _read_master_data(
                    source="auto",
                    balanca_db_path=self.balanca_db_path,
                    balanca_api_url="http://127.0.0.1:1",
                    balanca_api_token="",
                    balanca_api_email="",
                    balanca_api_password="",
                    balanca_api_timeout=0.1,
                )

        sqlite_reader.assert_not_called()

    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"sync_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.notas_db_path = self.temp_dir / "notas.db"
        self.balanca_db_path = self.temp_dir / "balanca.db"
        self.api_server = None
        self.api_thread = None
        self._create_balanca_fixture()

    def tearDown(self):
        if self.api_server:
            self.api_server.shutdown()
            self.api_server.server_close()
        if self.api_thread:
            self.api_thread.join(timeout=2)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_balanca_fixture(self) -> None:
        conn = sqlite3.connect(self.balanca_db_path)
        conn.executescript(
            """
            CREATE TABLE farms (
                id TEXT PRIMARY KEY,
                code TEXT,
                name TEXT NOT NULL
            );
            CREATE TABLE fields (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT,
                farm_id TEXT NOT NULL,
                area_ha REAL,
                area_alq REAL,
                planted_area_ha REAL,
                crop_year TEXT,
                area_type TEXT,
                active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            "INSERT INTO farms (id, code, name) VALUES (?, ?, ?)",
            ("farm-1", "100-901", "FAZENDA DEMO AURORA"),
        )
        conn.execute(
            "INSERT INTO farms (id, code, name) VALUES (?, ?, ?)",
            ("farm-2", "200-908", "FAZENDA DEMO PLANALTO"),
        )
        conn.execute(
            """
            INSERT INTO fields (
                id, code, name, farm_id, area_ha, area_alq, planted_area_ha,
                crop_year, area_type, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("field-1", "15", None, "farm-1", 10.0, 4.13, 10.0, "2026", "Reforma", 1),
        )
        conn.execute(
            """
            INSERT INTO fields (
                id, code, name, farm_id, area_ha, area_alq, planted_area_ha,
                crop_year, area_type, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("field-2", "1", None, "farm-2", 2.0, 0.82, 2.0, "2026", "Soca", 1),
        )
        conn.commit()
        conn.close()

    def _start_api_server(
        self,
        payload: dict,
        expected_token: str = "token-teste",
        expected_email: str = "visitante@example.invalid",
        expected_password: str = "senha-teste",
    ) -> str:
        encoded_payload = json.dumps(payload).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/auth/login":
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if body != {"email": expected_email, "password": expected_password}:
                    self.send_response(401)
                    self.end_headers()
                    return
                token_payload = json.dumps({"token": expected_token}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(token_payload)))
                self.end_headers()
                self.wfile.write(token_payload)

            def do_GET(self):
                if self.path != "/farms":
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != f"Bearer {expected_token}":
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded_payload)))
                self.end_headers()
                self.wfile.write(encoded_payload)

            def log_message(self, *_args):
                return

        self.api_server = HTTPServer(("127.0.0.1", 0), Handler)
        self.api_thread = threading.Thread(target=self.api_server.serve_forever, daemon=True)
        self.api_thread.start()
        host, port = self.api_server.server_address
        return f"http://{host}:{port}"

    def test_sync_preserves_existing_local_code_and_loads_fields(self):
        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            db.adicionar_fazenda("100901", "Nome antigo")
        finally:
            db.close()

        result = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        self.assertEqual(2, result["fazendas_lidas"])
        self.assertEqual(2, result["talhoes_sincronizados"])
        self.assertEqual(2, result["talhoes_processados"])
        self.assertEqual(2, result["talhoes_alterados"])
        self.assertEqual(2, result["talhoes_inseridos"])
        self.assertEqual(0, result["talhoes_atualizados"])
        self.assertEqual(0, result["talhoes_removidos"])

        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            fazenda = db.buscar_referencia("fazendas", "100901", col_id="codigo")
            self.assertEqual("100901", fazenda["codigo"])
            self.assertEqual("100-901", fazenda["codigo_mestre"])
            self.assertEqual("FAZENDA DEMO AURORA", fazenda["nome"])

            talhoes = db.listar_talhoes("100901")
            self.assertEqual(1, len(talhoes))
            self.assertEqual("15", talhoes[0]["codigo"])
            talhao = db.buscar_talhao("15", fazenda_codigo="100901")
            self.assertIsNotNone(talhao)
            self.assertEqual("100901", talhao["fazenda_codigo"])
            self.assertIsNone(db.buscar_talhao("15", fazenda_codigo="200908"))

            resumo = db.resumo_cadastros_mestre()
            self.assertEqual(2, resumo["fazendas_balanca"])
            self.assertEqual(2, resumo["talhoes_balanca"])
        finally:
            db.close()

    def test_sync_is_idempotent_for_unchanged_farms(self):
        first = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )
        second = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        self.assertEqual(2, first["fazendas_alteradas"])
        self.assertEqual(0, second["fazendas_alteradas"])
        self.assertEqual(2, second["talhoes_sincronizados"])
        self.assertEqual(2, second["talhoes_processados"])
        self.assertEqual(0, second["talhoes_alterados"])
        self.assertEqual(0, second["talhoes_inseridos"])
        self.assertEqual(0, second["talhoes_atualizados"])
        self.assertEqual(0, second["talhoes_removidos"])

    def test_sync_preserves_but_reclassifies_stale_master_farms(self):
        sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )
        conn = sqlite3.connect(self.balanca_db_path)
        try:
            conn.execute("DELETE FROM fields WHERE farm_id = ?", ("farm-2",))
            conn.execute("DELETE FROM farms WHERE id = ?", ("farm-2",))
            conn.commit()
        finally:
            conn.close()

        result = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        self.assertEqual(1, result["fazendas_desativadas"])
        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            stale = db.conn.execute(
                "SELECT fonte_mestre FROM fazendas WHERE codigo = ?",
                ("200-908",),
            ).fetchone()
            self.assertEqual("historico_balanca", stale["fonte_mestre"])
            active = db.conn.execute(
                "SELECT COUNT(*) FROM fazendas WHERE fonte_mestre = 'balanca'"
            ).fetchone()[0]
            self.assertEqual(1, active)
        finally:
            db.close()

    def test_sync_counts_updated_and_removed_fields(self):
        first = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )
        self.assertEqual(2, first["talhoes_alterados"])

        conn = sqlite3.connect(self.balanca_db_path)
        try:
            conn.execute("UPDATE fields SET area_ha = ? WHERE id = ?", (11.5, "field-1"))
            conn.execute("DELETE FROM fields WHERE id = ?", ("field-2",))
            conn.commit()
        finally:
            conn.close()

        second = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        self.assertEqual(1, second["talhoes_lidos"])
        self.assertEqual(1, second["talhoes_processados"])
        self.assertEqual(2, second["talhoes_alterados"])
        self.assertEqual(0, second["talhoes_inseridos"])
        self.assertEqual(1, second["talhoes_atualizados"])
        self.assertEqual(1, second["talhoes_removidos"])

        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            self.assertEqual(1, len(db.listar_talhoes("100-901")))
            self.assertEqual(0, len(db.listar_talhoes("200-908")))
        finally:
            db.close()

    def test_sync_reconciles_code_swaps_by_master_id(self):
        conn = sqlite3.connect(self.balanca_db_path)
        try:
            conn.execute(
                """
                INSERT INTO fields (
                    id, code, name, farm_id, area_ha, area_alq, planted_area_ha,
                    crop_year, area_type, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("field-3", "16", None, "farm-1", 8.0, 3.3, 8.0, "2026", "Soca", 1),
            )
            conn.commit()
        finally:
            conn.close()

        sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        conn = sqlite3.connect(self.balanca_db_path)
        try:
            conn.execute("UPDATE fields SET code = 'temporario' WHERE id = 'field-1'")
            conn.execute("UPDATE fields SET code = '15' WHERE id = 'field-3'")
            conn.execute("UPDATE fields SET code = '16' WHERE id = 'field-1'")
            conn.commit()
        finally:
            conn.close()

        result = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_db_path=self.balanca_db_path,
            source="sqlite",
        )

        self.assertEqual(0, result["talhoes_inseridos"])
        self.assertEqual(2, result["talhoes_atualizados"])
        self.assertEqual(0, result["talhoes_removidos"])
        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            rows = db.conn.execute(
                "SELECT id, codigo FROM talhoes WHERE id IN (?, ?) ORDER BY id",
                ("field-1", "field-3"),
            ).fetchall()
            self.assertEqual([("field-1", "16"), ("field-3", "15")], [tuple(row) for row in rows])
        finally:
            db.close()

    def test_sync_can_read_farms_from_balanca_api(self):
        api_url = self._start_api_server(
            {
                "farms": [
                    {
                        "id": "farm-api-1",
                        "code": "300-001",
                        "name": "FAZ API",
                        "fields": [
                            {
                                "id": "field-api-1",
                                "code": "7",
                                "name": "Talhao API",
                                "farmId": "farm-api-1",
                                "areaHa": 12.5,
                                "areaAlq": 5.16,
                                "plantedAreaHa": 12.0,
                                "cropYear": "2026",
                                "areaType": "Plantio",
                                "active": True,
                            }
                        ],
                    }
                ]
            }
        )

        result = sync_balanca_master_data(
            notas_db_path=self.notas_db_path,
            balanca_api_url=api_url,
            balanca_api_email="visitante@example.invalid",
            balanca_api_password="senha-teste",
            source="api",
        )

        self.assertEqual("api", result["fonte_sincronizacao"])
        self.assertEqual(1, result["fazendas_lidas"])
        self.assertEqual(1, result["talhoes_sincronizados"])
        self.assertEqual(1, result["talhoes_alterados"])

        db = DB(self.notas_db_path, seed_from_excel=False)
        try:
            fazenda = db.buscar_referencia("fazendas", "300-001", col_id="codigo")
            self.assertEqual("FAZ API", fazenda["nome"])
            talhoes = db.listar_talhoes("300-001")
            self.assertEqual(1, len(talhoes))
            self.assertEqual("7", talhoes[0]["codigo"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
