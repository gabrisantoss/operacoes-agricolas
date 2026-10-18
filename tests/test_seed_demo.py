from __future__ import annotations

import sys
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import seed_demo  # noqa: E402  (reads .demo/runtime.json, created by demo.py setup)
except (RuntimeError, ModuleNotFoundError) as error:  # pragma: no cover - only before setup
    seed_demo = None
    SKIP_REASON = str(error)


@unittest.skipIf(seed_demo is None, "execute demo.py setup antes deste teste")
class SeedDemoConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows: dict[str, list[dict]] = {}

        def capture(_conn, table, **values):
            self.rows.setdefault(table, []).append(values)

        with patch.object(seed_demo, "insert", capture):
            seed_demo.balance(None)

    def test_closed_orders_end_after_their_last_linked_weighing(self) -> None:
        closed = {row["id"]: row for row in self.rows["harvest_orders"] if row["status"] == "CLOSED"}
        self.assertEqual(sorted(row["number"] for row in closed.values()), ["90007", "90008"])

        for order_id, order in closed.items():
            entries = [row["entry_date"] for row in self.rows["cane_entries"] if row["order_id"] == order_id]
            self.assertTrue(entries)
            for offset in (timezone.utc, timezone(timedelta(hours=-3))):
                end_day = order["end_date"].astimezone(offset).date()
                self.assertGreaterEqual(end_day, max(entries), f"OS {order['number']} encerrada antes da ultima pesagem")
                self.assertGreaterEqual(min(entries), order["start_date"])


if __name__ == "__main__":
    unittest.main()
