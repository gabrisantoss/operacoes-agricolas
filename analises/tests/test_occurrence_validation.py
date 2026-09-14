import unittest

from core.validation import (
    ValidationError,
    build_finalized_occurrence_metrics,
    normalize_occurrence_payload,
    normalize_web_occurrence_payload,
)


class NormalizeOccurrencePayloadTests(unittest.TestCase):
    def test_web_payload_uses_same_normalization(self):
        payload = normalize_web_occurrence_payload(
            {
                "data": "2026-04-05",
                "turno": "1",
                "frente": "01",
                "frota": " colhedora 931 ",
                "motivo": " manutencao ",
                "status": "Em Andamento",
                "parou_hora": "08:30",
            }
        )

        self.assertEqual(payload["data_db"], "05-04-2026")
        self.assertEqual(payload["frente"], "1")
        self.assertEqual(payload["frota"], "COLHEDORA 931")
        self.assertTrue(payload["em_andamento"])

    def test_web_payload_rejects_unknown_status(self):
        with self.assertRaisesRegex(ValidationError, "status válido"):
            normalize_web_occurrence_payload({"status": "Pendente"})

    def test_normalizes_valid_simple_occurrence(self):
        payload = normalize_occurrence_payload(
            {
                "data": "05/04/2026",
                "turno": "1",
                "frente": "01",
                "fundo": "  talhao   7 ",
                "chove": "SIM",
                "incendio": "NÃO",
                "frota": "  colhedora   931 ",
                "motivo": "  troca   de  turno ",
                "parou_hora": "",
                "voltou_hora": "",
                "em_andamento": False,
            }
        )

        self.assertEqual(payload["data_db"], "05-04-2026")
        self.assertEqual(payload["frente"], "1")
        self.assertEqual(payload["frota"], "COLHEDORA 931")
        self.assertEqual(payload["motivo"], "troca de turno")
        self.assertEqual(payload["fundo"], "talhao 7")
        self.assertEqual(payload["parou_hora"], "")
        self.assertEqual(payload["voltou_hora"], "")

    def test_rejects_non_numeric_front(self):
        with self.assertRaisesRegex(ValidationError, "apenas números inteiros"):
            normalize_occurrence_payload(
                {
                    "data": "05/04/2026",
                    "turno": "1",
                    "frente": "A1",
                    "frota": "COLHEDORA 931",
                    "motivo": "Teste",
                    "parou_hora": "",
                    "voltou_hora": "",
                    "em_andamento": False,
                }
            )

    def test_requires_start_time_for_ongoing_stop(self):
        with self.assertRaisesRegex(ValidationError, "parada em andamento"):
            normalize_occurrence_payload(
                {
                    "data": "05/04/2026",
                    "turno": "1",
                    "frente": "5",
                    "frota": "COLHEDORA 931",
                    "motivo": "Em manutenção",
                    "parou_hora": "",
                    "voltou_hora": "",
                    "em_andamento": True,
                }
            )

    def test_requires_start_time_before_return_time(self):
        with self.assertRaisesRegex(ValidationError, "Informe a 'Hora que Parou'"):
            normalize_occurrence_payload(
                {
                    "data": "05/04/2026",
                    "turno": "1",
                    "frente": "5",
                    "frota": "COLHEDORA 931",
                    "motivo": "Teste",
                    "parou_hora": "",
                    "voltou_hora": "08:30",
                    "em_andamento": False,
                }
            )

    def test_requires_return_time_for_completed_stop(self):
        with self.assertRaisesRegex(ValidationError, "Hora que Voltou"):
            normalize_occurrence_payload(
                {
                    "data": "05/04/2026",
                    "turno": "1",
                    "frente": "5",
                    "frota": "COLHEDORA 931",
                    "motivo": "Teste",
                    "parou_hora": "08:30",
                    "voltou_hora": "",
                    "em_andamento": False,
                }
            )


class BuildFinalizedOccurrenceMetricsTests(unittest.TestCase):
    def test_returns_none_for_simple_occurrence(self):
        total_parado, eficiencia = build_finalized_occurrence_metrics(
            "05/04/2026", "", "", lambda *args: ("99:99", 0)
        )

        self.assertIsNone(total_parado)
        self.assertIsNone(eficiencia)

    def test_uses_injected_calculator(self):
        total_parado, eficiencia = build_finalized_occurrence_metrics(
            "05/04/2026",
            "23:30",
            "01:00",
            lambda *args: ("01:30", 85.0),
        )

        self.assertEqual(total_parado, "01:30")
        self.assertEqual(eficiencia, 85.0)


if __name__ == "__main__":
    unittest.main()
