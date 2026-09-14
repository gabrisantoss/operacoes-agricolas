from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import os
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from database import DB
from main_window import MainWindow


class MainWindowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"main_window_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self._aguardar_workers()
            self.window._allow_close = True
            self.window.close()
            self.window.deleteLater()
            self.window = None
            self.app.processEvents()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _aguardar_workers(self, timeout: float = 5.0) -> None:
        limite = time.time() + timeout
        while time.time() < limite:
            self.app.processEvents()
            worker = getattr(getattr(self.window, "tab_rel", None), "worker_tarefa", None)
            if worker is None:
                return
        self.fail("Worker de dashboard nao finalizou no tempo esperado.")

    def test_exibicao_nao_forca_geometria_manual(self):
        with mock.patch.object(
            MainWindow,
            "setGeometry",
            side_effect=AssertionError("Exibicao nao deve forcar setGeometry()"),
        ):
            self.window = MainWindow(self.db, internet_ok=True)
            self.assertEqual((1, 1), (self.window.minimumSize().width(), self.window.minimumSize().height()))
            self.window.showFullScreen()
            self._aguardar_workers()

        self.assertTrue(self.window.isFullScreen())
