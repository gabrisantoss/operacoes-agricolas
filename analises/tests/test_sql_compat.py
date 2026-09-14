import unittest

from core.sql_compat import hhmm_minutes_sql, numeric_text_order_sql


class SqlCompatTests(unittest.TestCase):
    def test_postgres_hhmm_uses_no_sqlite_instr(self):
        sql = hhmm_minutes_sql("Total_Hora_Parado", "postgresql")
        self.assertNotIn("INSTR", sql.upper())
        self.assertIn("split_part", sql)

    def test_postgres_numeric_order_is_null_safe(self):
        sql = numeric_text_order_sql("Frente", "postgres")
        self.assertIn("regexp_replace", sql)
        self.assertIn("NULLS LAST", sql)

    def test_sqlite_fragments_remain_compatible(self):
        self.assertIn("INSTR", hhmm_minutes_sql("duration", "sqlite"))
        self.assertEqual(numeric_text_order_sql("Frente", "sqlite"), "CAST(Frente AS INTEGER)")


if __name__ == "__main__":
    unittest.main()
