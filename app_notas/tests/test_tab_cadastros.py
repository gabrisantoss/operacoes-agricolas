from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import os
import shutil
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from database import DB
from tabs.tab_cadastros import TabCadastros


class TabCadastrosTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"cadastros_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)

        self.db.inserir_nota(
            {
                "numero": 501,
                "motorista_cod": 1,
                "motorista_nome": "Teste",
                "caminhao": "AAA-0501",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "5",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "T1",
                "faz_plantio_cod": "200-001",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "RB001",
                "data_colheita": "2026-04-01",
                "data_plantio": "2026-04-07",
            }
        )

        self.widget = TabCadastros(self.db, main_window=SimpleNamespace())

    def tearDown(self):
        self.widget.deleteLater()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_correcao_segura_preview_e_aplicacao(self):
        self.widget.txt_correcao_notas.setPlainText("501\n999")
        self.widget.cb_correcao_acao.setCurrentText("Data de colheita = data de plantio")
        self.widget.ed_correcao_motivo.setText("Teste de auditoria")

        self.widget.previsualizar_correcao()
        self.assertEqual(1, self.widget.model_preview_correcao.rowCount())
        self.assertIn("1 nota(s) encontrada(s)", self.widget.lbl_correcao_status.text())

        with (
            mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes),
            mock.patch.object(QtWidgets.QMessageBox, "information"),
            mock.patch.object(QtWidgets.QMessageBox, "critical"),
        ):
            self.widget.aplicar_correcao()
            limite = time.time() + 5
            while self.widget.worker is not None and time.time() < limite:
                self.app.processEvents()

        nota = self.db.buscar_nota(501)
        self.assertEqual("2026-04-07", nota["data_colheita"])
        self.assertEqual(1, self.widget.model_logs_correcao.rowCount())
