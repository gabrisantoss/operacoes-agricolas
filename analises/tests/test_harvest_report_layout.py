import unittest

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph

from reporting.harvest_report import _build_harvest_detail_table


class HarvestReportLayoutTests(unittest.TestCase):
    def test_detail_table_repeats_wrapped_header_on_continuation_pages(self):
        rows = [
            (
                "01-08-2026",
                "F1",
                "T1",
                "Fazenda de Validacao com Denominacao Extensa",
                12.34,
                78.9,
                7,
            )
        ]

        table = _build_harvest_detail_table(rows, getSampleStyleSheet())

        self.assertEqual(1, table.repeatRows)
        self.assertTrue(all(isinstance(cell, Paragraph) for cell in table._cellvalues[0]))
        self.assertEqual("Viagens", table._cellvalues[0][-1].text)
        self.assertGreater(table._colWidths[-1], 30)


if __name__ == "__main__":
    unittest.main()
