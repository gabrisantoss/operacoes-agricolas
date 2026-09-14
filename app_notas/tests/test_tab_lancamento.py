from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import os
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from database import DB
from tabs.tab_lancamento import TabLancamento


class TabLancamentoTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"lancamento_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)
        self.main_window = SimpleNamespace(
            status=QtWidgets.QStatusBar(),
            tabs=QtWidgets.QTabWidget(),
            _atualizar_contadores=lambda: None,
            tab_hist=SimpleNamespace(
                carregar_dados=lambda *_args, **_kwargs: None,
                _usar_filtro_atual=False,
            ),
        )
        self.widget = TabLancamento(self.db, self.main_window)

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _processar_ui(self):
        self.app.processEvents()
        self.app.processEvents()

    def test_layout_nao_usa_barra_de_rolagem_propria(self):
        self.widget.resize(1200, 700)
        self.widget.show()
        self._processar_ui()

        self.assertFalse(hasattr(self.widget, "scroll_area"))
        self.assertIsInstance(self.widget.layout(), QtWidgets.QVBoxLayout)

    def test_layout_alterna_para_modo_compacto_em_largura_reduzida(self):
        self.widget.show()
        self.widget.resize(1200, 700)
        self.widget._atualizar_layout_responsivo(1200)
        self._processar_ui()

        self.assertEqual(self.widget.form_layout.direction(), QtWidgets.QBoxLayout.LeftToRight)
        self.assertEqual(self.widget.header_layout.direction(), QtWidgets.QBoxLayout.LeftToRight)
        self.assertEqual(self.widget.botoes_layout.direction(), QtWidgets.QBoxLayout.LeftToRight)

        self.widget.resize(680, 700)
        self.widget._atualizar_layout_responsivo(680)
        self._processar_ui()

        self.assertEqual(self.widget.form_layout.direction(), QtWidgets.QBoxLayout.TopToBottom)
        self.assertEqual(self.widget.header_layout.direction(), QtWidgets.QBoxLayout.TopToBottom)
        self.assertEqual(self.widget.botoes_layout.direction(), QtWidgets.QBoxLayout.TopToBottom)
