from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import os
import unittest
from unittest.mock import patch

from web_app.server import (
    HISTORICAL_MUTATION_ENV,
    correction_confirmation_present,
    delete_confirmation_present,
    historical_note_mutations_allowed,
    should_block_existing_note_mutation,
)


class WebServerSafetyTestCase(unittest.TestCase):
    def test_bloqueia_mutacao_de_nota_existente_por_padrao(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(HISTORICAL_MUTATION_ENV, None)

            self.assertTrue(
                should_block_existing_note_mutation(object(), same_edit=True, strategy="")
            )
            self.assertTrue(
                should_block_existing_note_mutation(object(), same_edit=False, strategy="overwrite")
            )
            self.assertFalse(
                should_block_existing_note_mutation(object(), same_edit=False, strategy="duplicate")
            )
            self.assertFalse(
                should_block_existing_note_mutation(None, same_edit=False, strategy="")
            )

    def test_env_libera_mutacao_somente_quando_explicita(self):
        with patch.dict(os.environ, {HISTORICAL_MUTATION_ENV: "1"}, clear=False):
            self.assertTrue(historical_note_mutations_allowed())
            self.assertFalse(
                should_block_existing_note_mutation(object(), same_edit=True, strategy="")
            )

    def test_exclusao_de_cadastro_exige_confirmacao_booleana(self):
        self.assertTrue(delete_confirmation_present({"confirmDelete": True}))
        self.assertFalse(delete_confirmation_present({}))
        self.assertFalse(delete_confirmation_present({"confirmDelete": False}))
        self.assertFalse(delete_confirmation_present({"confirmDelete": "true"}))

    def test_correcao_em_lote_exige_confirmacao_booleana(self):
        self.assertTrue(correction_confirmation_present({"confirmCorrection": True}))
        self.assertFalse(correction_confirmation_present({}))
        self.assertFalse(correction_confirmation_present({"confirmCorrection": False}))
        self.assertFalse(correction_confirmation_present({"confirmCorrection": "true"}))


if __name__ == "__main__":
    unittest.main()
