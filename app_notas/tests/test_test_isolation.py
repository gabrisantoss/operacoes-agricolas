from __future__ import annotations

import os
import unittest

import tests as _tests_bootstrap  # noqa: F401

import app_config


class TestDatabaseIsolationTests(unittest.TestCase):
    def test_unit_suite_cannot_inherit_production_postgres(self):
        self.assertEqual("sqlite", app_config.DB_ENGINE)
        self.assertEqual("", app_config.DATABASE_URL)
        self.assertEqual("sqlite", os.environ.get("APP_NOTAS_DB_ENGINE"))
        self.assertEqual("", os.environ.get("APP_NOTAS_DATABASE_URL"))


if __name__ == "__main__":
    unittest.main()
