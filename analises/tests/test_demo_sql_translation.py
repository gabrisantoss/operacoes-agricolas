import unittest
from agricola_shared.db_compat import translate_sql
from agricola_shared.demo_safety import assert_demo_database_target


class DemoSqlTranslationTests(unittest.TestCase):
    def test_like_wildcards_and_question_mark_parameters(self):
        self.assertEqual("SELECT 1 WHERE nome ILIKE '%%COLH%%' AND frente = %s",
                         translate_sql("SELECT 1 WHERE nome LIKE '%COLH%' AND frente = ?"))

    def test_literal_question_mark_and_modulo(self):
        self.assertEqual("SELECT '?' AS literal, 7 %% 3", translate_sql("SELECT '?' AS literal, 7 % 3"))

    def test_database_guard(self):
        assert_demo_database_target("postgresql://oa_demo@localhost:55439/oa_demo_tests")
        for url in ["postgresql://oa_demo@localhost:5432/oa_demo_tests",
                    "postgresql://oa_demo@192.0.2.10:55439/oa_demo_tests",
                    "postgresql://oa_demo@localhost:55439/production"]:
            with self.assertRaises(RuntimeError):
                assert_demo_database_target(url)
