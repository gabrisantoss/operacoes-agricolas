"""Run Notas filter tests on the isolated demo PostgreSQL using disposable databases."""
from pathlib import Path
import os
import sys
import unittest
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app_notas"), str(ROOT)]
import demo


def main():
    settings = demo.config()
    demo.ensure_cluster(settings)
    os.environ.update(demo.environment(settings, "notas"))
    import psycopg
    from psycopg import sql
    from agricola_shared.demo_safety import assert_demo_database_target
    base = demo.database_url(settings, "tests")
    assert_demo_database_target(base)
    # The tests package normally selects SQLite. Override only after its bootstrap,
    # before app_config/database are imported, and only with a checked demo target.
    import tests  # noqa: F401
    os.environ["APP_NOTAS_DB_ENGINE"] = "postgresql"
    os.environ["APP_NOTAS_DATABASE_URL"] = base
    from tests.test_date_reference import DateReferenceTest
    from tests.test_history_pagination import HistoryPaginationTest
    import database
    from web_app import server

    sys.path.insert(0, str(ROOT / "scripts"))
    import seed_demo

    class SeedCadastroTest(unittest.TestCase):
        setUp = DateReferenceTest.setUp
        tearDown = DateReferenceTest.tearDown

        def test_cadastro_apos_seed_preserva_sequencia(self):
            seed_demo.notes(self.db.conn.raw)
            seed_demo.align_notes_variety_sequence(self.db.conn.raw)
            self.db.conn.commit()
            self.db.adicionar_variedade("VARIEDADE APOS SEED")
            row = self.db.resolver_referencia("variedades", "VARIEDADE APOS SEED", col_id="id")
            self.assertGreater(row["id"], 3)
            reserved = self.db.conn.raw.execute("SELECT nextval(pg_get_serial_sequence('variedades','id'))").fetchone()[0]
            seed_demo.align_notes_variety_sequence(self.db.conn.raw)
            self.db.conn.commit()
            self.db.adicionar_variedade("VARIEDADE SEGUINTE")
            row = self.db.resolver_referencia("variedades", "VARIEDADE SEGUINTE", col_id="id")
            self.assertGreater(row["id"], reserved)

    suite = unittest.TestSuite()
    for case in (DateReferenceTest, HistoryPaginationTest, SeedCadastroTest):
        original_setup = case.setUp

        def setup(self, original_setup=original_setup):
            name = "oa_demo_tests_notas_" + uuid4().hex
            with psycopg.connect(base, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

            def cleanup():
                with psycopg.connect(base, autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            self.addCleanup(cleanup)
            parts = urlsplit(base)
            target = urlunsplit((parts.scheme, parts.netloc, "/" + name, "", ""))
            assert_demo_database_target(target)
            database.DATABASE_URL = target
            server.DATABASE_URL = target
            original_setup(self)

        case.setUp = setup
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
