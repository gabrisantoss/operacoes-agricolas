import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from core.config import DatabaseConfig
from core.database import setup_main_database
from core.settings import setup_settings_database
from reporting.database_excel_export import _table_info, _write_table_sheet


class StartupFailClosedTests(unittest.TestCase):
    def test_main_schema_failure_is_not_swallowed(self):
        with patch.object(DatabaseConfig, "get_connection", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "banco principal"):
                setup_main_database()

    def test_settings_schema_failure_is_not_swallowed(self):
        with patch.object(DatabaseConfig, "get_connection", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "settings"):
                setup_settings_database()


class StableExcelExportTests(unittest.TestCase):
    def test_composite_primary_key_drives_stable_chunk_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "source.db"
            output_path = Path(temporary) / "output.xlsx"
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE sample (group_id TEXT, sequence INTEGER, value TEXT, "
                "PRIMARY KEY (group_id, sequence))"
            )
            connection.executemany(
                "INSERT INTO sample VALUES (?, ?, ?)",
                [("b", 2, "last"), ("a", 2, "middle"), ("a", 1, "first")],
            )
            connection.commit()

            info = _table_info(connection, "sample")
            self.assertEqual(["group_id", "sequence"], info["order_columns"])
            with zipfile.ZipFile(output_path, "w") as archive:
                _write_table_sheet(
                    archive, connection, "sheet.xml", "sample", info["columns"],
                    info["order_columns"], 0, 100,
                )
            connection.close()

            with zipfile.ZipFile(output_path) as archive:
                xml = archive.read("sheet.xml").decode("utf-8")
            self.assertLess(xml.index("first"), xml.index("middle"))
            self.assertLess(xml.index("middle"), xml.index("last"))


if __name__ == "__main__":
    unittest.main()
