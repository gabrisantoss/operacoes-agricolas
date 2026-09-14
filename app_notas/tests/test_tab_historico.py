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

import pandas as pd
from PyQt5 import QtWidgets

from database import DB
from tabs.tab_historico import TabHistorico


class TabHistoricoTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"historico_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)

        notas = [
            {
                "numero": 1001,
                "motorista_cod": 1,
                "motorista_nome": "Joao Silva",
                "caminhao": "AAA-0001",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "1",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem A",
                "talhao": "T1",
                "faz_plantio_cod": "200-001",
                "faz_plantio_nome": "Destino A",
                "variedade_id": 1,
                "variedade_nome": "RB001",
                "data_colheita": "2026-04-10",
                "data_plantio": "2026-04-08",
            },
            {
                "numero": 1002,
                "motorista_cod": 2,
                "motorista_nome": "Maria Costa",
                "caminhao": "BBB-0002",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "2",
                "faz_muda_cod": "100-002",
                "faz_muda_nome": "Origem B",
                "talhao": "T2",
                "faz_plantio_cod": "200-002",
                "faz_plantio_nome": "Destino B",
                "variedade_id": 2,
                "variedade_nome": "RB002",
                "data_colheita": "2026-04-11",
                "data_plantio": "2026-04-09",
            },
        ]

        for nota in notas:
            self.db.inserir_nota(nota)

        self.widget = TabHistorico(self.db, SimpleNamespace())

    def tearDown(self):
        self.widget.deleteLater()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_exportar_respeita_filtro_visivel(self):
        destino = self.temp_dir / "historico_filtrado.xlsx"
        self.widget.cb_campo.setCurrentText("Motorista")
        self.widget.filtrar("joao")

        with (
            mock.patch.object(
                QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=(str(destino), "Excel (*.xlsx)"),
            ),
            mock.patch.object(QtWidgets.QMessageBox, "information"),
            mock.patch.object(QtWidgets.QMessageBox, "critical"),
        ):
            self.widget.exportar()
            limite = time.time() + 5
            while self.widget.export_worker is not None and time.time() < limite:
                self.app.processEvents()

        self.assertTrue(destino.exists())
        df = pd.read_excel(destino)

        self.assertEqual(1, len(df))
        self.assertEqual(1001, int(df.iloc[0]["Nota"]))
        self.assertEqual("Joao Silva", df.iloc[0]["Motorista"])

    def test_busca_por_nota_recarrega_modelo_com_consulta_direta(self):
        self.widget.cb_campo.setCurrentText("Nota")
        self.widget.filtrar("1001")

        self.assertEqual(1, self.widget.model.rowCount())
        self.assertEqual(1, self.widget.proxy.rowCount())
        self.assertEqual("1001", self.widget.model.row_values(0)[0])
        self.assertEqual("Visiveis: 1", self.widget.lbl_visiveis.text())

        self.widget.cb_campo.setCurrentText("Motorista")
        self.widget.filtrar("maria")

        self.assertEqual(2, self.widget.model.rowCount())
        self.assertEqual(1, self.widget.proxy.rowCount())
        index = self.widget.proxy.index(0, 0)
        self.assertEqual("1002", str(self.widget.proxy.data(index)))
