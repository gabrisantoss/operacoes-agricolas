from __future__ import annotations

import tests as _tests_bootstrap  # noqa: F401 - fixa SQLite antes dos imports do app

import re
import unittest
from datetime import datetime

from reporting import (
    RelatorioPdfDiarioBuilder,
    RelatorioPdfFechamentoBuilder,
    RelatorioPdfGeralBuilder,
    RelatorioPdfPlantioDetalhadoBuilder,
    RelatorioPdfSimplificadoBuilder,
)


class RelatorioPdfBuildersTestCase(unittest.TestCase):
    def _assert_pdf_renderizado(self, pdf, min_paginas=1):
        self.assertIsNotNone(pdf)
        self.assertGreaterEqual(pdf.page_no(), min_paginas)
        conteudo = pdf.output()
        self.assertIsInstance(conteudo, bytearray)
        self.assertGreater(len(conteudo), 1000)

    def test_pdf_diario_renderiza_multiplas_paginas(self):
        linhas = []
        total_geral = 0
        for dia in range(1, 6):
            data = f"{dia:02d}/04/2026"
            for indice in range(18):
                linhas.append(
                    {
                        "data": data,
                        "fazenda": f"FAZENDA DE PLANTIO {indice:02d} COM NOME OPERACIONAL EXTENSO",
                        "variedade": f"RB{indice:03d} VARIEDADE AMPLIADA",
                        "qtd": indice + 1,
                    }
                )
                total_geral += indice + 1

        pdf = RelatorioPdfDiarioBuilder().criar_pdf_resumo_diario(
            {
                "linhas": linhas,
                "total_geral": total_geral,
            }
        )

        self._assert_pdf_renderizado(pdf, min_paginas=2)

    def test_pdf_plantio_detalhado_renderiza_multiplas_paginas(self):
        linhas = [
            {
                "nota": str(1000 + indice),
                "data_colheita": "01/04/2026",
                "data_plantio": "02/04/2026",
                "propriedade": f"200-{indice:03d} - FAZENDA DE PLANTIO COM NOME OPERACIONAL {indice:02d}",
                "talhao": f"TALHAO-{indice:02d}",
                "variedade": f"RB{indice:04d} VARIEDADE DE TESTE",
            }
            for indice in range(70)
        ]
        pdf = RelatorioPdfPlantioDetalhadoBuilder().criar_pdf_plantio_detalhado(
            "2026-04-01",
            "2026-04-30",
            {
                "linhas": linhas,
                "total_geral": len(linhas),
                "metricas": {
                    "propriedades": 70,
                    "talhoes": 70,
                    "variedades": 70,
                    "campos_pendentes": 0,
                },
            },
        )

        self._assert_pdf_renderizado(pdf, min_paginas=3)

    def test_pdf_geral_quebra_bloco_longo_sem_falhar(self):
        destinos = [
            {
                "codigo": f"{200000 + indice}",
                "nome": f"FAZENDA DE PLANTIO {indice:02d} COM COMPLEMENTO EXTENSO PARA TABELA",
                "qtd": indice + 1,
                "percentual": 1.0,
            }
            for indice in range(55)
        ]
        grupo = {
            "codigo_origem": "104933",
            "nome_origem": "FAZENDA DEMO HORIZONTE",
            "variedade": "RB123456 VARIEDADE DE TESTE",
            "inicio": datetime(2026, 1, 1),
            "fim": datetime(2026, 4, 15),
            "total": sum(item["qtd"] for item in destinos),
            "talhoes": [f"TALHAO-{indice:02d}" for indice in range(1, 25)],
            "destinos": destinos,
        }
        pendencias = [
            {
                "nota": f"{3000 + indice}",
                "data": "15/04/2026",
                "referencia": f"REFERENCIA OPERACIONAL {indice:02d}",
                "detalhe": "VARIEDADE NAO INFORMADA",
            }
            for indice in range(8)
        ]
        dados = {
            "total_geral": grupo["total"],
            "metricas": {
                "origens_ativas": 1,
                "variedades_ativas": 1,
                "destinos_ativos": len(destinos),
            },
            "pendencias": {
                "sem_variedade": len(pendencias),
                "sem_destino": 0,
                "sem_origem": 0,
            },
            "tops": {
                "origens": [{"label": "(MUDA) [104-933] FAZENDA DEMO HORIZONTE", "qtd": grupo["total"], "subtitle": "55 destinos"}],
                "variedades": [{"label": "RB123456 VARIEDADE DE TESTE", "qtd": grupo["total"], "subtitle": "1 bloco"}],
                "destinos": [{"label": "(PLANTIO) [200-000] FAZENDA DE PLANTIO 00", "qtd": destinos[0]["qtd"], "subtitle": "Destino com maior volume"}],
                "grupos": [{"label": "(MUDA) [104-933] FAZENDA DEMO HORIZONTE", "qtd": grupo["total"], "subtitle": "Variedade: RB123456 VARIEDADE DE TESTE"}],
            },
            "grupos": [grupo],
            "pendencias_detalhes": {
                "sem_variedade": pendencias,
                "sem_destino": [],
                "sem_origem": [],
            },
        }

        pdf = RelatorioPdfGeralBuilder().criar_pdf_geral_fazenda("2026-01-01", "2026-04-15", dados)

        pagina_continuacao = bytes(pdf.pages[4].contents).decode("latin-1")
        self.assertIn("(200-033)", pagina_continuacao)
        self.assertRegex(
            pagina_continuacao,
            r"q 28\.35 [^\r\n]+\(COD\.\) Tj ET Q",
            "Cabecalho da tabela de continuacao saiu da margem esquerda.",
        )
        indice_linha = pagina_continuacao.index("(200-033)")
        cores_anteriores = re.findall(
            r"(?:^|\s)([0-9.]+ [0-9.]+ [0-9.]+ rg)",
            pagina_continuacao[:indice_linha],
        )
        self.assertTrue(cores_anteriores)
        self.assertNotEqual(
            "1 1 1 rg",
            cores_anteriores[-1],
            "Linha da continuacao ficou branca sobre fundo claro.",
        )

        self._assert_pdf_renderizado(pdf, min_paginas=3)

    def test_pdf_simplificado_renderiza_cruzamentos_extensos(self):
        cruzamento_destinos = [
            {
                "codigo": f"{300000 + indice}",
                "nome": f"FAZENDA DE PLANTIO {indice:02d} COM NOME MUITO GRANDE PARA TESTE",
                "label": f"[{300000 + indice}] DESTINO {indice:02d}",
                "qtd": indice + 2,
                "percentual": 2.5,
            }
            for indice in range(60)
        ]
        origens = [
            {
                "codigo": f"{100000 + indice}",
                "nome": f"ORIGEM {indice:02d} DE MUDA COM NOME GRANDE",
                "label": f"[{100000 + indice}] ORIGEM {indice:02d}",
                "qtd": 80 - indice,
                "percentual": 1.0,
                "destinos": 12 + indice,
            }
            for indice in range(28)
        ]
        destinos = [
            {
                "codigo": f"{200000 + indice}",
                "nome": f"DESTINO {indice:02d} DE PLANTIO COM NOME GRANDE",
                "label": f"[{200000 + indice}] DESTINO {indice:02d}",
                "qtd": 60 - indice,
                "percentual": 1.0,
                "origens": 7 + indice,
            }
            for indice in range(28)
        ]
        cruzamentos = [
            {
                "codigo": "100111",
                "nome": "ORIGEM PRINCIPAL COM NOME MUITO GRANDE",
                "origem": "[100-111] ORIGEM PRINCIPAL COM NOME MUITO GRANDE",
                "qtd": sum(item["qtd"] for item in cruzamento_destinos),
                "percentual": 100.0,
                "destinos_ativos": len(cruzamento_destinos),
                "destino_principal": cruzamento_destinos[-1],
                "destinos": cruzamento_destinos,
            }
        ]
        dados = {
            "total_geral": 1250,
            "metricas": {
                "origens_ativas": len(origens),
                "destinos_ativos": len(destinos),
                "cruzamentos_ativos": len(cruzamentos),
                "registros_completos": 1240,
                "registros_incompletos": 10,
            },
            "pendencias": {
                "sem_origem": 3,
                "sem_destino": 7,
            },
            "origens": origens,
            "destinos": destinos,
            "cruzamentos": cruzamentos,
            "executivo": {
                "origem_top": origens[0],
                "destino_top": destinos[0],
                "cruzamento_top": cruzamentos[0],
            },
            "tops": {
                "origens": [
                    {"label": item["label"], "qtd": item["qtd"], "subtitle": f"{item['destinos']} destinos mapeados"}
                    for item in origens[:5]
                ],
                "destinos": [
                    {"label": item["label"], "qtd": item["qtd"], "subtitle": f"{item['origens']} origens atendidas"}
                    for item in destinos[:5]
                ],
            },
        }

        pdf = RelatorioPdfSimplificadoBuilder().criar_pdf_simplificado("2026-01-01", "2026-04-15", dados)

        self._assert_pdf_renderizado(pdf, min_paginas=4)

    def test_pdf_fechamento_safra_renderiza_capa_sumario_e_equipe(self):
        origem = {
            "codigo": "100001",
            "nome": "FAZENDA DE MUDA TESTE",
            "label": "[100-001] FAZENDA DE MUDA TESTE",
            "qtd": 12,
            "primeira_data": datetime(2026, 1, 21),
            "ultima_data": datetime(2026, 4, 23),
            "destinos": 2,
            "variedades": 1,
        }
        destino = {
            "codigo": "200001",
            "nome": "FAZENDA DE PLANTIO TESTE",
            "label": "[200-001] FAZENDA DE PLANTIO TESTE",
            "qtd": 12,
            "primeira_data": datetime(2026, 1, 21),
            "ultima_data": datetime(2026, 4, 23),
            "origens": 1,
            "variedades": 1,
        }
        variedade = {
            "nome": "CTC 04",
            "qtd": 12,
            "percentual": 100.0,
            "origens": 1,
            "destinos": 1,
        }
        fluxo = {
            "codigo_origem": "100001",
            "nome_origem": "FAZENDA DE MUDA TESTE",
            "origem": "[100-001] FAZENDA DE MUDA TESTE",
            "variedade": "CTC 04",
            "inicio": datetime(2026, 1, 21),
            "fim": datetime(2026, 4, 23),
            "total": 12,
            "talhoes": ["1", "2"],
            "destinos": [
                {
                    "codigo": "200001",
                    "nome": "FAZENDA DE PLANTIO TESTE",
                    "qtd": 12,
                    "percentual": 100.0,
                }
            ],
        }
        motorista = {"nome": "MOTORISTA TESTE", "qtd": 12, "caminhoes": ["101"]}
        operador = {"nome": "OPERADOR TESTE", "qtd": 12, "colhedoras": ["C1"]}
        dados = {
            "total_geral": 12,
            "periodo": {
                "primeira_data": datetime(2026, 1, 21),
                "ultima_data": datetime(2026, 4, 23),
            },
            "metricas": {
                "origens_ativas": 1,
                "destinos_ativos": 1,
                "variedades_ativas": 1,
                "blocos_fluxo": 1,
            },
            "rankings": {
                "origens": [origem],
                "destinos": [destino],
                "variedades": [variedade],
                "motoristas": [motorista],
                "operadores": [operador],
            },
            "fluxos": [fluxo],
            "destaques": {
                "origem_top": origem,
                "destino_top": destino,
                "variedade_top": variedade,
                "motorista_top": motorista,
                "operador_top": operador,
            },
        }

        pdf = RelatorioPdfFechamentoBuilder().criar_pdf_fechamento_safra("2026-01-21", "2026-04-23", dados)

        self._assert_pdf_renderizado(pdf, min_paginas=8)
