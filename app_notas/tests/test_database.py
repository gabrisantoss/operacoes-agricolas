from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import shutil
import unittest
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from database import (
    CorrectionPreviewConflict,
    DB,
    DatabaseCorruptionError,
    backup_sqlite_file,
    restore_sqlite_backup,
)


class FakeColaboradoresProvider:
    def __init__(self, rows):
        self.rows = rows

    def listar_referencias(self, q: str = "", limit: int | None = None):
        q_txt = str(q or "").strip().upper()
        rows = list(self.rows)
        if q_txt:
            rows = [
                row
                for row in rows
                if q_txt in str(row["codigo"]).upper() or q_txt in str(row["nome"]).upper()
            ]
        if limit is not None:
            return rows[: int(limit)]
        return rows

    def buscar_referencia(self, valor):
        valor_txt = str(valor or "").strip()
        valor_norm = valor_txt.upper()
        for row in self.rows:
            if str(row["codigo"]).strip() == valor_txt:
                return row
        for row in self.rows:
            if str(row["nome"]).strip().upper() == valor_norm:
                return row
        return None


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._old_colab_env = os.environ.get("APP_NOTAS_COLABORADORES_REFERENCIAS")
        os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = "0"
        self.temp_root = _tests_bootstrap.test_temp_root()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.temp_root / f"case_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "teste.db"
        self.db = DB(path=self.db_path, seed_from_excel=False)

    def tearDown(self):
        if getattr(self, "db", None) is not None:
            self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self._old_colab_env is None:
            os.environ.pop("APP_NOTAS_COLABORADORES_REFERENCIAS", None)
        else:
            os.environ["APP_NOTAS_COLABORADORES_REFERENCIAS"] = self._old_colab_env

    def test_salva_nota_e_contadores(self):
        self.db.adicionar_motorista(101, "Joao")
        self.db.adicionar_fazenda("100-001", "Fazenda Aurora")
        self.db.adicionar_variedade("RB001")

        motorista = self.db.resolver_referencia("motoristas", "101 - Joao")
        fazenda = self.db.resolver_referencia("fazendas", "Fazenda Aurora")
        variedade = self.db.resolver_referencia("variedades", "RB001", col_id="id")

        self.assertIsNotNone(motorista)
        self.assertIsNotNone(fazenda)
        self.assertIsNotNone(variedade)

        self.db.inserir_nota(
            {
                "numero": 1,
                "motorista_cod": motorista["codigo"],
                "motorista_nome": motorista["nome"],
                "caminhao": "ABC-1234",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "12",
                "faz_muda_cod": fazenda["codigo"],
                "faz_muda_nome": fazenda["nome"],
                "talhao": "T1",
                "faz_plantio_cod": fazenda["codigo"],
                "faz_plantio_nome": fazenda["nome"],
                "variedade_id": variedade["id"],
                "variedade_nome": variedade["nome"],
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-20",
            }
        )

        nota = self.db.buscar_nota(1)
        self.assertEqual("Joao", nota["motorista_nome"])
        self.assertEqual(1, self.db.contar_notas_total())
        self.assertEqual(1, self.db.contar_notas_data("2026-03-27"))
        self.assertEqual([], self.db.listar_referencias_auditoria(1))

    def test_registra_origem_das_referencias_da_nota(self):
        self.db.inserir_nota(
            {
                "numero": 10,
                "motorista_cod": "953",
                "motorista_nome": "ADAIL ALVES DE ARAUJO",
                "caminhao": "ABC-1234",
                "operador_cod": "950",
                "operador_nome": "OPERADOR TESTE",
                "colhedora": "950",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Fazenda Origem",
                "talhao": "1",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Fazenda Destino",
                "variedade_id": 1,
                "variedade_nome": "RB001",
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-20",
                "_audit_event": "nota.create",
                "_referencias_origem": {
                    "motorista": {
                        "fonte": "portal_colaboradores",
                        "codigo": "953",
                        "nome": "ADAIL ALVES DE ARAUJO",
                    },
                    "talhao": {
                        "fonte": "balanca",
                        "codigo": "1",
                        "fazendaCodigo": "100-001",
                    },
                },
            }
        )

        registros = self.db.listar_referencias_auditoria(10)

        self.assertEqual(1, len(registros))
        self.assertEqual("nota.create", registros[0]["evento"])
        self.assertEqual(
            "portal_colaboradores",
            registros[0]["referencias"]["motorista"]["fonte"],
        )
        self.assertEqual("balanca", registros[0]["referencias"]["talhao"]["fonte"])

    def test_force_update_de_nota_existente(self):
        self.db.inserir_nota(
            {
                "numero": 2,
                "motorista_cod": 1,
                "motorista_nome": "Motorista A",
                "caminhao": "AAA-0001",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "1",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "X1",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-A",
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-21",
            }
        )

        self.db.inserir_nota(
            {
                "numero": 2,
                "motorista_cod": 2,
                "motorista_nome": "Motorista B",
                "caminhao": "BBB-0002",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "2",
                "faz_muda_cod": "100-010",
                "faz_muda_nome": "Nova Origem",
                "talhao": "Y1",
                "faz_plantio_cod": "100-020",
                "faz_plantio_nome": "Novo Destino",
                "variedade_id": 2,
                "variedade_nome": "VAR-B",
                "data_colheita": "2026-03-28",
                "data_plantio": "2026-03-22",
            },
            force=True,
        )

        nota = self.db.buscar_nota(2)
        self.assertEqual("Motorista B", nota["motorista_nome"])
        self.assertEqual("BBB-0002", nota["caminhao"])
        self.assertEqual("2026-03-28", nota["data_colheita"])

    def test_motorista_do_colaboradores_tem_prioridade_sem_reescrever_local(self):
        self.db.adicionar_motorista(502, "NOME ANTIGO DO NOTAS")
        provider = FakeColaboradoresProvider(
            [{"codigo": "502", "nome": "NOME ATUAL DO PORTAL"}]
        )

        with patch("database.get_colaboradores_provider", return_value=provider):
            row = self.db.resolver_referencia("motoristas", "502")

        self.assertEqual("502", str(row["codigo"]))
        self.assertEqual("NOME ATUAL DO PORTAL", row["nome"])

        local = self.db.conn.execute(
            "SELECT nome FROM motoristas WHERE codigo = ?",
            (502,),
        ).fetchone()
        self.assertEqual("NOME ANTIGO DO NOTAS", local["nome"])

    def test_listar_motoristas_usa_colaboradores_como_fonte_autoritativa(self):
        self.db.adicionar_motorista(502, "NOME ANTIGO DO NOTAS")
        self.db.adicionar_motorista(777, "MOTORISTA SOMENTE LOCAL")
        provider = FakeColaboradoresProvider(
            [{"codigo": "502", "nome": "NOME ATUAL DO PORTAL"}]
        )

        with patch("database.get_colaboradores_provider", return_value=provider):
            rows = self.db.listar_referencias_filtradas("motoristas")

        por_codigo = {str(row["codigo"]): row["nome"] for row in rows}
        self.assertEqual("NOME ATUAL DO PORTAL", por_codigo["502"])
        self.assertNotIn("777", por_codigo)

    def test_busca_historico_por_prefixo_numerico(self):
        for numero in (12, 123, 1234, 456):
            self.db.inserir_nota(
                {
                    "numero": numero,
                    "motorista_cod": 1,
                    "motorista_nome": f"Motorista {numero}",
                    "caminhao": "AAA-0001",
                    "operador_cod": None,
                    "operador_nome": None,
                    "colhedora": "1",
                    "faz_muda_cod": "100-001",
                    "faz_muda_nome": "Origem",
                    "talhao": "T1",
                    "faz_plantio_cod": "100-002",
                    "faz_plantio_nome": "Destino",
                    "variedade_id": 1,
                    "variedade_nome": "VAR-A",
                    "data_colheita": "2026-03-27",
                    "data_plantio": "2026-03-21",
                }
            )

        rows = self.db.buscar_notas_historico(numero_prefixo="12")

        self.assertEqual([1234, 123, 12], [int(row["numero"]) for row in rows])
        self.assertEqual([], self.db.buscar_notas_historico(numero_prefixo="abc"))

    def test_gerar_numero_duplicado_pula_colisoes(self):
        for numero in (15, 1501, 1502):
            self.db.inserir_nota(
                {
                    "numero": numero,
                    "motorista_cod": 1,
                    "motorista_nome": "Duplicado",
                    "caminhao": "DDD-0001",
                    "operador_cod": None,
                    "operador_nome": None,
                    "colhedora": "5",
                    "faz_muda_cod": "100-001",
                    "faz_muda_nome": "Origem",
                    "talhao": "D1",
                    "faz_plantio_cod": "100-002",
                    "faz_plantio_nome": "Destino",
                    "variedade_id": 1,
                    "variedade_nome": "VAR-D",
                    "data_colheita": "2026-03-27",
                    "data_plantio": "2026-03-20",
                }
            )

        self.assertEqual(1503, self.db.gerar_numero_duplicado(15))

    def test_indices_por_codigo_sao_criados(self):
        rows = self.db.conn.execute("PRAGMA index_list('notas')").fetchall()
        nomes = {row[1] for row in rows}

        self.assertIn("idx_notas_faz_muda_cod", nomes)
        self.assertIn("idx_notas_faz_plantio_cod", nomes)
        self.assertIn("idx_notas_data_colheita_faz_muda_cod", nomes)
        self.assertIn("idx_notas_data_colheita_faz_plantio_cod", nomes)

    def test_top_por_coluna_fazenda_agrupa_por_codigo_e_exibe_codigo(self):
        for numero, destino_cod in (
            (41, "1132450"),
            (42, "1132450"),
            (43, "1132458"),
        ):
            self.db.inserir_nota(
                {
                    "numero": numero,
                    "motorista_cod": 1,
                    "motorista_nome": "Motorista",
                    "caminhao": "AAA-0001",
                    "operador_cod": None,
                    "operador_nome": None,
                    "colhedora": "1",
                    "faz_muda_cod": "100-001",
                    "faz_muda_nome": "Origem",
                    "talhao": "T1",
                    "faz_plantio_cod": destino_cod,
                    "faz_plantio_nome": "FAZENDA DEMO SOL",
                    "variedade_id": 1,
                    "variedade_nome": "VAR-A",
                    "data_colheita": "2026-03-27",
                    "data_plantio": "2026-03-27",
                }
            )

        ranking = self.db.top_por_coluna("faz_plantio_nome", "2026-03-01", "2026-03-31", limit=5)

        self.assertEqual(["1132450", "1132458"], [item["codigo"] for item in ranking])
        self.assertEqual([2, 1], [item["qtd"] for item in ranking])
        self.assertEqual(
            ["1132450 - FAZENDA DEMO SOL", "1132458 - FAZENDA DEMO SOL"],
            [item["nome"] for item in ranking],
        )

    def test_preview_e_aplicacao_de_correcao_gravam_auditoria(self):
        self.db.inserir_nota(
            {
                "numero": 31,
                "motorista_cod": 1,
                "motorista_nome": "Teste Correcao",
                "caminhao": "CCC-0031",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "3",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "C1",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-C",
                "data_colheita": "2026-03-20",
                "data_plantio": "2026-03-27",
            }
        )

        preview = self.db.preview_correcao_notas([31, 999], "colheita_para_plantio")
        self.assertEqual([999], preview["faltantes"])
        self.assertEqual("2026-03-27", preview["preview"][0]["data_colheita_nova"])
        self.assertTrue(preview["preview"][0]["alterado"])

        resultado = self.db.aplicar_correcao_notas(
            [31, 999],
            "colheita_para_plantio",
            motivo="Ajuste em lote",
        )

        self.assertEqual(1, resultado["quantidade_alterada"])
        self.assertEqual(1, resultado["quantidade_faltante"])
        self.assertTrue(Path(resultado["backup_path"]).exists())

        nota = self.db.buscar_nota(31)
        self.assertEqual("2026-03-27", nota["data_colheita"])
        self.assertEqual("2026-03-27", nota["data_plantio"])

        logs = self.db.listar_logs_correcao(limit=5)
        self.assertEqual(1, len(logs))
        self.assertEqual(31, logs[0]["nota_numero"])
        self.assertEqual("Ajuste em lote", logs[0]["motivo"])

    def test_correcao_rejeita_preview_obsoleto_sem_alterar_nota(self):
        self.db.inserir_nota(
            {
                "numero": 32,
                "motorista_cod": 1,
                "motorista_nome": "Teste Concorrencia",
                "caminhao": "CCC-0032",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "3",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "C2",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-C",
                "data_colheita": "2026-03-20",
                "data_plantio": "2026-03-27",
            }
        )
        preview = self.db.preview_correcao_notas([32], "colheita_para_plantio")
        self.db.conn.execute(
            "UPDATE notas SET data_plantio = ? WHERE numero = ?",
            ("2026-03-28", 32),
        )
        self.db.conn.commit()

        with self.assertRaises(CorrectionPreviewConflict):
            self.db.aplicar_correcao_notas(
                [32],
                "colheita_para_plantio",
                expected_preview_token=preview["preview_token"],
            )

        nota = self.db.buscar_nota(32)
        self.assertEqual("2026-03-20", nota["data_colheita"])
        self.assertEqual("2026-03-28", nota["data_plantio"])
        self.assertEqual([], self.db.listar_logs_correcao(limit=5))

    def test_correcao_aplica_mesmo_snapshot_validado(self):
        self.db.inserir_nota(
            {
                "numero": 33,
                "motorista_cod": 1,
                "motorista_nome": "Teste Token",
                "caminhao": "CCC-0033",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "3",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "C3",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-C",
                "data_colheita": "2026-03-20",
                "data_plantio": "2026-03-27",
            }
        )
        preview = self.db.preview_correcao_notas([33], "colheita_para_plantio")

        result = self.db.aplicar_correcao_notas(
            [33],
            "colheita_para_plantio",
            expected_preview_token=preview["preview_token"],
        )

        self.assertEqual(1, result["quantidade_alterada"])
        self.assertEqual("2026-03-27", self.db.buscar_nota(33)["data_colheita"])

    def test_inserir_nota_rejeita_data_colheita_futura(self):
        data_futura = (date.today() + timedelta(days=1)).isoformat()

        with self.assertRaisesRegex(ValueError, "data atual do sistema"):
            self.db.inserir_nota(
                {
                    "numero": 20,
                    "motorista_cod": 1,
                    "motorista_nome": "Motorista Futuro",
                    "caminhao": "AAA-2020",
                    "operador_cod": None,
                    "operador_nome": None,
                    "colhedora": "20",
                    "faz_muda_cod": "100-001",
                    "faz_muda_nome": "Origem",
                    "talhao": "F1",
                    "faz_plantio_cod": "100-002",
                    "faz_plantio_nome": "Destino",
                    "variedade_id": 1,
                    "variedade_nome": "VAR-20",
                    "data_colheita": data_futura,
                    "data_plantio": date.today().isoformat(),
                }
            )

        self.assertIsNone(self.db.buscar_nota(20))

    def test_inserir_nota_rejeita_data_plantio_futura(self):
        data_futura = (date.today() + timedelta(days=1)).isoformat()

        with self.assertRaisesRegex(ValueError, "data atual do sistema"):
            self.db.inserir_nota(
                {
                    "numero": 21,
                    "motorista_cod": 1,
                    "motorista_nome": "Plantio Futuro",
                    "caminhao": "BBB-2021",
                    "operador_cod": None,
                    "operador_nome": None,
                    "colhedora": "21",
                    "faz_muda_cod": "100-001",
                    "faz_muda_nome": "Origem",
                    "talhao": "F2",
                    "faz_plantio_cod": "100-002",
                    "faz_plantio_nome": "Destino",
                    "variedade_id": 1,
                    "variedade_nome": "VAR-21",
                    "data_colheita": date.today().isoformat(),
                    "data_plantio": data_futura,
                }
            )

        self.assertIsNone(self.db.buscar_nota(21))

    def test_backup_e_restore(self):
        self.db.inserir_nota(
            {
                "numero": 3,
                "motorista_cod": 1,
                "motorista_nome": "Original",
                "caminhao": "CAM-001",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "1",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "A1",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-1",
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-20",
            }
        )

        backup_path = self.temp_dir / "backup.db"
        self.db.create_backup(backup_path)

        self.db.inserir_nota(
            {
                "numero": 3,
                "motorista_cod": 2,
                "motorista_nome": "Alterado",
                "caminhao": "CAM-999",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "9",
                "faz_muda_cod": "100-010",
                "faz_muda_nome": "Outra Origem",
                "talhao": "Z9",
                "faz_plantio_cod": "100-020",
                "faz_plantio_nome": "Outro Destino",
                "variedade_id": 9,
                "variedade_nome": "VAR-9",
                "data_colheita": "2026-03-29",
                "data_plantio": "2026-03-25",
            },
            force=True,
        )

        self.db.restore_from_backup(backup_path)
        nota = self.db.buscar_nota(3)
        self.assertEqual("Original", nota["motorista_nome"])
        self.assertEqual("CAM-001", nota["caminhao"])

    def test_backup_sqlite_file_copia_banco(self):
        self.db.inserir_nota(
            {
                "numero": 4,
                "motorista_cod": 1,
                "motorista_nome": "Teste",
                "caminhao": "XYZ-0001",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "3",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "B2",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-2",
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-18",
            }
        )

        copia = self.temp_dir / "externo.db"
        backup_sqlite_file(self.db_path, copia)

        db_copia = DB(path=copia, seed_from_excel=False)
        try:
            nota = db_copia.buscar_nota(4)
            self.assertIsNotNone(nota)
            self.assertEqual("Teste", nota["motorista_nome"])
        finally:
            db_copia.close()

    def test_abertura_falha_quando_arquivo_esta_corrompido(self):
        corrompido = self.temp_dir / "corrompido.db"
        corrompido.write_bytes(b"isso nao eh um sqlite valido")

        with self.assertRaises(DatabaseCorruptionError):
            DB(path=corrompido, seed_from_excel=False)

    def test_restore_sqlite_backup_substitui_arquivo_corrompido(self):
        self.db.inserir_nota(
            {
                "numero": 5,
                "motorista_cod": 1,
                "motorista_nome": "Backup Integro",
                "caminhao": "RST-5000",
                "operador_cod": None,
                "operador_nome": None,
                "colhedora": "5",
                "faz_muda_cod": "100-001",
                "faz_muda_nome": "Origem",
                "talhao": "C3",
                "faz_plantio_cod": "100-002",
                "faz_plantio_nome": "Destino",
                "variedade_id": 1,
                "variedade_nome": "VAR-5",
                "data_colheita": "2026-03-27",
                "data_plantio": "2026-03-17",
            }
        )

        backup_path = self.temp_dir / "backup_integro.db"
        self.db.create_backup(backup_path)

        destino = self.temp_dir / "destino_corrompido.db"
        destino.write_bytes(b"conteudo quebrado")

        restaurado, quarantined = restore_sqlite_backup(destino, backup_path)
        self.assertEqual(destino, restaurado)
        self.assertIsNotNone(quarantined)
        self.assertTrue(quarantined.exists())

        db_restaurado = DB(path=destino, seed_from_excel=False)
        try:
            nota = db_restaurado.buscar_nota(5)
            self.assertIsNotNone(nota)
            self.assertEqual("Backup Integro", nota["motorista_nome"])
        finally:
            db_restaurado.close()


if __name__ == "__main__":
    unittest.main()
