import math
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph

from core.date_utils import sql_date_expr
from reporting import daily_operations_report as daily_report
from reporting import dashboard_report
from reporting import database_excel_export
from reporting import front_efficiency_report


def _connect_to(path):
    return lambda: sqlite3.connect(path)


def _create_operational_tables(connection):
    connection.executescript(
        """
        CREATE TABLE RELATORIO_OPERACAO_DIARIA (
            id INTEGER PRIMARY KEY,
            Data TEXT,
            Frente TEXT,
            Turno TEXT,
            Frota TEXT,
            Motivo TEXT,
            Parou_Hora TEXT,
            Voltou_Hora TEXT,
            Total_Hora_Parado TEXT,
            Eficiencia REAL,
            Fundo_Agricola TEXT,
            Chuva TEXT,
            Incendio TEXT,
            Status_Parada TEXT
        );
        CREATE TABLE FROTAS_POR_FRENTE (
            id INTEGER PRIMARY KEY,
            Frente TEXT,
            Frota TEXT
        );
        CREATE TABLE COLHEITA_MECANIZADA (
            id INTEGER PRIMARY KEY,
            Data TEXT,
            Frente TEXT,
            Area_Colhida REAL,
            Produtividade REAL
        );
        """
    )


class DateQueryRegressionTests(unittest.TestCase):
    def test_sql_date_expression_normalizes_legacy_slash_and_iso_dates(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE sample (Data TEXT)")
        connection.executemany(
            "INSERT INTO sample VALUES (?)",
            [("01-08-2026",), ("02/08/2026",), ("2026-08-03",)],
        )

        rows = connection.execute(
            f"SELECT Data, {sql_date_expr('Data')} FROM sample ORDER BY {sql_date_expr('Data')}"
        ).fetchall()
        connection.close()

        self.assertEqual(
            [
                ("01-08-2026", "2026-08-01"),
                ("02/08/2026", "2026-08-02"),
                ("2026-08-03", "2026-08-03"),
            ],
            rows,
        )


class DailyReportRegressionTests(unittest.TestCase):
    def test_text_front_escaped_fields_iso_date_and_missing_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "daily.sqlite"
            output_path = temporary_path / "nested" / "reports"
            connection = sqlite3.connect(database_path)
            _create_operational_tables(connection)
            connection.executemany(
                "INSERT INTO FROTAS_POR_FRENTE VALUES (?, ?, ?)",
                [(1, "NORTE", "COLHEDORA 1"), (2, "NORTE", "TRANSBORDO 1")],
            )
            connection.executemany(
                "INSERT INTO RELATORIO_OPERACAO_DIARIA VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        1, "01-08-2026", "NORTE", "1", "COLHEDORA 1",
                        "Sensor <TRAVA> & correia", "08:00", "09:00", "01:00",
                        90.0, "Talhao <NORTE> & Sul", "NAO", "NAO", "Finalizada",
                    ),
                    (
                        2, "2026-08-02", "NORTE", "2", "TRANSBORDO 1",
                        "Registro ISO", "20:00", "20:30", "00:30",
                        95.0, "Talhao QA", "NAO", "NAO", "Finalizada",
                    ),
                ],
            )
            connection.commit()
            connection.close()

            captured_paragraphs = []
            real_paragraph = daily_report.Paragraph

            def capture_paragraph(text, style, *args, **kwargs):
                captured_paragraphs.append(text)
                return real_paragraph(text, style, *args, **kwargs)

            with (
                patch.object(daily_report.DatabaseConfig, "DB_ENGINE", "sqlite"),
                patch.object(
                    daily_report.DatabaseConfig,
                    "get_connection",
                    side_effect=_connect_to(database_path),
                ),
                patch.object(daily_report, "get_setting", return_value="600"),
                patch.object(daily_report, "Paragraph", side_effect=capture_paragraph),
            ):
                generated = daily_report.gerar_relatorio(
                    data_inicial="01-08-2026",
                    data_final="03-08-2026",
                    output_path=str(output_path),
                )

            self.assertTrue(Path(generated).is_file())
            self.assertTrue(any("Sensor &lt;TRAVA&gt; &amp; correia" in text for text in captured_paragraphs))
            self.assertTrue(any("Talhao &lt;NORTE&gt; &amp; Sul" in text for text in captured_paragraphs))
            self.assertTrue(any("Registro ISO" in text for text in captured_paragraphs))


class FrontEfficiencyRegressionTests(unittest.TestCase):
    def test_generated_table_repeats_header_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "front.sqlite"
            connection = sqlite3.connect(database_path)
            _create_operational_tables(connection)
            connection.executemany(
                "INSERT INTO FROTAS_POR_FRENTE VALUES (?, ?, ?)",
                [(index, str(index), f"COLHEDORA {index}") for index in range(1, 40)],
            )
            connection.commit()
            connection.close()

            captured_tables = []
            real_table = front_efficiency_report.Table

            def capture_table(*args, **kwargs):
                table = real_table(*args, **kwargs)
                captured_tables.append(table)
                return table

            with (
                patch.object(
                    front_efficiency_report.DatabaseConfig,
                    "get_connection",
                    side_effect=_connect_to(database_path),
                ),
                patch.object(front_efficiency_report, "get_setting", return_value="600"),
                patch.object(front_efficiency_report, "Table", side_effect=capture_table),
            ):
                front_efficiency_report.gerar_relatorio_eficiencia_frentes(
                    "01/08/2026", "01/08/2026", str(temporary_path / "reports")
                )

            self.assertEqual(1, captured_tables[-1].repeatRows)


class DashboardRegressionTests(unittest.TestCase):
    def test_duplicate_event_in_same_equipment_shift_does_not_inflate_availability(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "dashboard.sqlite"
            connection = sqlite3.connect(database_path)
            _create_operational_tables(connection)
            connection.execute(
                "INSERT INTO RELATORIO_OPERACAO_DIARIA VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    1, "01-08-2026", "1", "1", "COLHEDORA 1", "A",
                    "08:00", "09:00", "01:00", 90.0, "QA", "NAO", "NAO", "Finalizada",
                ),
            )
            connection.commit()
            connection.close()

            with (
                patch.object(
                    dashboard_report.DatabaseConfig,
                    "get_connection",
                    side_effect=_connect_to(database_path),
                ),
                patch.object(dashboard_report, "get_setting", return_value="600"),
            ):
                one_event = dashboard_report._fetch_and_process_data_for_period(
                    "01-08-2026", "01-08-2026"
                )[0]

                connection = sqlite3.connect(database_path)
                connection.execute(
                    "INSERT INTO RELATORIO_OPERACAO_DIARIA VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        2, "01-08-2026", "1", "1", "COLHEDORA 1", "B",
                        "09:00", "09:00", "00:00", 100.0, "QA", "NAO", "NAO", "Finalizada",
                    ),
                )
                connection.commit()
                connection.close()
                two_events = dashboard_report._fetch_and_process_data_for_period(
                    "01-08-2026", "01-08-2026"
                )[0]

            self.assertEqual(90.0, one_event["utilizacao_equipamentos"])
            self.assertEqual(90.0, two_events["utilizacao_equipamentos"])
            self.assertEqual(
                600,
                two_events["total_operation_minutes_actual"] + two_events["total_downtime_minutes"],
            )

    def test_long_top_three_fronts_are_wrapped_as_paragraphs(self):
        current_data = {
            "productivity_by_frente": {
                f"FRENTE {index} COM NOME EXTENSO " + ("X" * 80): {"total_ton": 100 - index}
                for index in range(3)
            }
        }
        table = dashboard_report._build_dashboard_metric_table(
            current_data,
            "Sem comparação",
            getSampleStyleSheet(),
        )

        top_three_cell = table._cellvalues[11][1]
        self.assertIsInstance(top_three_cell, Paragraph)
        width, height = top_three_cell.wrap(16.5 * cm - 12, 1000)
        self.assertLessEqual(width, 16.5 * cm - 12)
        self.assertGreater(height, 11)
        self.assertLessEqual(table.wrap(27.3 * cm, 1000)[0], 27.3 * cm)


class DatabaseExcelExportRegressionTests(unittest.TestCase):
    def test_full_export_handles_nonfinite_values_quoted_identifiers_and_sheet_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "source.sqlite"
            output_path = temporary_path / "export.xlsx"
            connection = sqlite3.connect(database_path)
            connection.execute('CREATE TABLE "He said ""Hi""" (id INTEGER PRIMARY KEY, value REAL)')
            connection.execute('INSERT INTO "He said ""Hi""" VALUES (1, ?)', (math.inf,))
            connection.execute('CREATE TABLE "A?B" (id INTEGER PRIMARY KEY, value TEXT)')
            connection.execute('INSERT INTO "A?B" VALUES (1, "=2+2")')
            connection.execute('CREATE TABLE "a/b" (id INTEGER PRIMARY KEY, value TEXT)')
            connection.execute('INSERT INTO "a/b" VALUES (1, "safe")')
            connection.commit()
            connection.close()

            with (
                patch.object(database_excel_export.DatabaseConfig, "DB_PATH", str(database_path)),
                patch.object(
                    database_excel_export.DatabaseConfig,
                    "get_connection",
                    side_effect=_connect_to(database_path),
                ),
            ):
                generated = database_excel_export.export_database_to_excel(output_path)

            namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            with zipfile.ZipFile(generated) as archive:
                xml_parts = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name.endswith((".xml", ".rels"))
                }
                parsed_parts = {name: ET.fromstring(content) for name, content in xml_parts.items()}
                workbook = parsed_parts["xl/workbook.xml"]
                sheet_names = [node.attrib["name"] for node in workbook.findall(".//m:sheet", namespace)]
                worksheet_xml = b"".join(
                    content
                    for name, content in xml_parts.items()
                    if name.startswith("xl/worksheets/")
                )

            self.assertEqual(len(sheet_names), len({name.casefold() for name in sheet_names}))
            self.assertIn('He said "Hi"', sheet_names)
            self.assertNotIn(b"<v>inf</v>", worksheet_xml)
            self.assertIn(b">inf</t>", worksheet_xml)
            self.assertNotIn(b"<f>", worksheet_xml)
            self.assertIn(b"=2+2", worksheet_xml)


if __name__ == "__main__":
    unittest.main()
