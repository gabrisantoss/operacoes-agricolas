from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from database import DB
from reporting import RelatorioDataService


class RelatorioDataServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"case_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste_reporting.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)
        self.service = RelatorioDataService(self.db.conn)

    def tearDown(self):
        if getattr(self, "db", None) is not None:
            self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _inserir_nota(self, numero: int, faz_muda_cod: str, faz_muda_nome: str, data_colheita: str) -> None:
        self.db.inserir_nota(
            {
                "numero": numero,
                "motorista_cod": numero,
                "motorista_nome": f"Motorista {numero}",
                "caminhao": f"AAA-{numero:04d}",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": str(numero),
                "faz_muda_cod": faz_muda_cod,
                "faz_muda_nome": faz_muda_nome,
                "talhao": f"T{numero}",
                "faz_plantio_cod": "200-001",
                "faz_plantio_nome": "Destino Base",
                "variedade_id": 1,
                "variedade_nome": "RB001",
                "data_colheita": data_colheita,
                "data_plantio": data_colheita,
            }
        )

    def test_coletar_dados_pdf_fazendas_muda_retorna_primeira_e_ultima_data_por_fazenda(self):
        self._inserir_nota(0, "104933", "FAZENDA DEMO HORIZONTE", "2025-12-31")
        self._inserir_nota(1, "104933", "FAZENDA DEMO HORIZONTE", "2026-02-02")
        self._inserir_nota(2, "104933", "FAZENDA DEMO HORIZONTE", "2026-04-04")
        self._inserir_nota(3, "200111", "FAZENDA SANTA RITA", "2026-03-01")
        self._inserir_nota(4, "104933", "FAZENDA DEMO HORIZONTE", "2026-04-10")
        self._inserir_nota(5, "777777", "FAZENDA FORA DO FILTRO", "2025-01-01")

        dados = self.service.coletar_dados_pdf_fazendas_muda("2026-01-01", "2026-04-06")

        self.assertIsNotNone(dados)
        self.assertEqual(3, dados["total_geral"])
        self.assertEqual(2, dados["metricas"]["fazendas_ativas"])
        self.assertEqual("2025-12-31", dados["metricas"]["primeira_data_registrada"].strftime("%Y-%m-%d"))
        self.assertEqual("2026-04-10", dados["metricas"]["ultima_data_registrada"].strftime("%Y-%m-%d"))

        fazendas = {item["codigo"]: item for item in dados["fazendas"]}
        self.assertEqual("2025-12-31", fazendas["104933"]["primeira_data"].strftime("%Y-%m-%d"))
        self.assertEqual("2026-04-10", fazendas["104933"]["ultima_data"].strftime("%Y-%m-%d"))
        self.assertEqual(2, fazendas["104933"]["qtd"])
        self.assertEqual("2026-03-01", fazendas["200111"]["primeira_data"].strftime("%Y-%m-%d"))
        self.assertEqual("2026-03-01", fazendas["200111"]["ultima_data"].strftime("%Y-%m-%d"))
        self.assertNotIn("777777", fazendas)

    def test_coletar_dados_pdf_plantio_detalhado_retorna_campos_da_nota(self):
        self._inserir_nota(10, "100001", "Origem A", "2026-04-01")
        self.db._execute(
            """
            UPDATE notas
            SET data_plantio = ?, faz_plantio_cod = ?, faz_plantio_nome = ?, talhao = ?, variedade_nome = ?
            WHERE numero = ?
            """,
            ("2026-04-03", "200999", "Destino Especial", "T-42", "RB867515", 10),
        )
        self.db.conn.commit()

        dados = self.service.coletar_dados_pdf_plantio_detalhado("2026-04-01", "2026-04-30")

        self.assertIsNotNone(dados)
        self.assertEqual(1, dados["total_geral"])
        self.assertEqual(1, dados["metricas"]["propriedades"])
        self.assertEqual(1, dados["metricas"]["talhoes"])
        self.assertEqual(1, dados["metricas"]["variedades"])
        self.assertEqual(0, dados["metricas"]["campos_pendentes"])
        self.assertEqual(
            {
                "nota": "10",
                "data_colheita": "01/04/2026",
                "data_plantio": "03/04/2026",
                "propriedade": "[200-999] Destino Especial",
                "talhao": "T-42",
                "variedade": "RB867515",
            },
            dados["linhas"][0],
        )

    def test_coletar_dados_pdf_fazendas_muda_ordena_por_primeira_ultima_data_e_codigo(self):
        self._inserir_nota(1, "300999", "FAZENDA Z", "2026-02-01")
        self._inserir_nota(2, "300999", "FAZENDA Z", "2026-03-10")
        self._inserir_nota(3, "100111", "FAZENDA A", "2026-01-01")
        self._inserir_nota(4, "200222", "FAZENDA B", "2026-02-01")
        self._inserir_nota(5, "200222", "FAZENDA B", "2026-03-01")
        self._inserir_nota(6, "100333", "FAZENDA C", "2026-02-01")
        self._inserir_nota(7, "100333", "FAZENDA C", "2026-03-01")

        dados = self.service.coletar_dados_pdf_fazendas_muda("2026-01-01", "2026-04-30")

        self.assertIsNotNone(dados)
        self.assertEqual(
            ["100111", "100333", "200222", "300999"],
            [item["codigo"] for item in dados["fazendas"]],
        )

    def test_coletar_dados_pdf_fechamento_safra_consolida_rankings_e_equipe(self):
        registros = [
            (10, "100001", "Origem A", "200001", "Destino A", "Motorista A", "Operador A", "101", "C1", "RB001"),
            (11, "100001", "Origem A Ajustada", "200002", "Destino B", "Motorista A", "Operador A", "102", "C1", "RB001"),
            (12, "100002", "Origem B", "200002", "Destino B", "Motorista B", "Operador B", "103", "C2", "RB002"),
        ]
        for numero, origem_cod, origem_nome, destino_cod, destino_nome, motorista, operador, caminhao, colhedora, variedade in registros:
            self.db.inserir_nota(
                {
                    "numero": numero,
                    "motorista_cod": numero,
                    "motorista_nome": motorista,
                    "caminhao": caminhao,
                    "operador_cod": numero,
                    "operador_nome": operador,
                    "colhedora": colhedora,
                    "faz_muda_cod": origem_cod,
                    "faz_muda_nome": origem_nome,
                    "talhao": "T1",
                    "faz_plantio_cod": destino_cod,
                    "faz_plantio_nome": destino_nome,
                    "variedade_id": 1,
                    "variedade_nome": variedade,
                    "data_colheita": "2026-04-01",
                    "data_plantio": "2026-04-01",
                }
            )

        dados = self.service.coletar_dados_pdf_fechamento_safra("2026-04-01", "2026-04-30")

        self.assertIsNotNone(dados)
        self.assertEqual(3, dados["total_geral"])
        self.assertEqual(2, dados["metricas"]["origens_ativas"])
        self.assertEqual(2, dados["metricas"]["destinos_ativos"])
        self.assertEqual(2, dados["metricas"]["variedades_ativas"])
        self.assertEqual(2, len(dados["rankings"]["origens"]))
        self.assertEqual("100001", dados["rankings"]["origens"][0]["codigo"])
        self.assertEqual(2, dados["rankings"]["origens"][0]["qtd"])
        self.assertEqual("Motorista A", dados["rankings"]["motoristas"][0]["nome"])
        self.assertEqual(2, dados["rankings"]["motoristas"][0]["qtd"])
        self.assertEqual("Operador A", dados["rankings"]["operadores"][0]["nome"])
        self.assertEqual(2, dados["rankings"]["operadores"][0]["qtd"])
