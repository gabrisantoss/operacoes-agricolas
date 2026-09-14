from __future__ import annotations

from collections import Counter
from datetime import datetime

from .base import RelatorioFormatacaoMixin


class RelatorioDataService(RelatorioFormatacaoMixin):
    def __init__(self, conn):
        self.conn = conn

    def coletar_dados_pdf_plantio_detalhado(self, d_ini, d_fim):
        sql = """
            SELECT
                numero,
                data_colheita,
                data_plantio,
                faz_plantio_cod,
                faz_plantio_nome,
                talhao,
                variedade_nome
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
            ORDER BY
                data_colheita,
                data_plantio,
                faz_plantio_nome,
                talhao,
                numero
        """
        rows = self.conn.execute(sql, (d_ini, d_fim)).fetchall()
        if not rows:
            return None

        linhas = []
        propriedades = set()
        talhoes = set()
        variedades = set()
        campos_pendentes = 0

        for row in rows:
            codigo = self._texto_relatorio(row[3])
            nome = self._texto_relatorio(row[4])
            propriedade = self._label_fazenda_relatorio(codigo, nome) if codigo or nome else "-"
            talhao = self._texto_relatorio(row[5], "-")
            variedade = self._texto_relatorio(row[6], "-")
            data_colheita = self._formatar_data_relatorio(row[1])
            data_plantio = self._formatar_data_relatorio(row[2])

            campos_pendentes += sum(
                valor == "-"
                for valor in (data_colheita, data_plantio, propriedade, talhao, variedade)
            )
            if propriedade != "-":
                propriedades.add(self._chave_relatorio(propriedade))
            if talhao != "-":
                talhoes.add(self._chave_relatorio(talhao))
            if variedade != "-":
                variedades.add(self._chave_relatorio(variedade))

            linhas.append(
                {
                    "nota": self._texto_relatorio(row[0], "-"),
                    "data_colheita": data_colheita,
                    "data_plantio": data_plantio,
                    "propriedade": propriedade,
                    "talhao": talhao,
                    "variedade": variedade,
                }
            )

        return {
            "linhas": linhas,
            "total_geral": len(linhas),
            "metricas": {
                "propriedades": len(propriedades),
                "talhoes": len(talhoes),
                "variedades": len(variedades),
                "campos_pendentes": campos_pendentes,
            },
        }

    def _formatar_data_relatorio(self, valor):
        texto = self._texto_relatorio(valor)
        if not texto:
            return "-"
        try:
            return datetime.strptime(texto, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return texto

    def coletar_dados_pdf_diario(self, d_ini, d_fim):
        sql = """
            SELECT data_colheita, faz_plantio_nome, variedade_nome, COUNT(*)
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
            GROUP BY data_colheita, faz_plantio_nome, variedade_nome
            ORDER BY data_colheita
        """
        rows = self.conn.execute(sql, (d_ini, d_fim)).fetchall()
        if not rows:
            return None

        linhas = []
        total_geral = 0
        for row in rows:
            data_referencia = self._texto_relatorio(row[0], "-")
            if data_referencia != "-":
                try:
                    data_referencia = datetime.strptime(data_referencia, "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    pass

            qtd = int(row[3] or 0)
            linhas.append(
                {
                    "data": data_referencia,
                    "fazenda": self._texto_relatorio(row[1], "-"),
                    "variedade": self._texto_relatorio(row[2], "-"),
                    "qtd": qtd,
                }
            )
            total_geral += qtd

        return {
            "linhas": linhas,
            "total_geral": total_geral,
        }

    def coletar_dados_pdf_simplificado(self, d_ini, d_fim):
        sql = """
            SELECT
                faz_muda_cod,
                faz_muda_nome,
                faz_plantio_cod,
                faz_plantio_nome
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
        """
        rows = self.conn.execute(sql, (d_ini, d_fim)).fetchall()
        if not rows:
            return None

        origens = {}
        destinos = {}
        cruzamentos = {}
        sem_origem = 0
        sem_destino = 0
        registros_completos = 0

        for row in rows:
            cod_origem = self._texto_relatorio(row[0], "")
            nome_origem = self._texto_relatorio(row[1], "")
            cod_destino = self._texto_relatorio(row[2], "")
            nome_destino = self._texto_relatorio(row[3], "")
            origem_disponivel = bool(cod_origem or nome_origem)
            destino_disponivel = bool(cod_destino or nome_destino)
            nome_origem_base = nome_origem or "NÃO INFORMADA"
            nome_destino_base = nome_destino or "NÃO INFORMADO"

            if origem_disponivel:
                origem_key = cod_origem or self._chave_relatorio(nome_origem_base, "NÃO INFORMADA")
                if origem_key not in origens:
                    origens[origem_key] = {
                        "codigo": cod_origem or "-",
                        "nomes": Counter(),
                        "qtd": 0,
                        "destinos": set(),
                    }
                origens[origem_key]["nomes"][nome_origem_base] += 1
                origens[origem_key]["qtd"] += 1
            else:
                sem_origem += 1

            if destino_disponivel:
                destino_key = cod_destino or self._chave_relatorio(nome_destino_base, "NÃO INFORMADO")
                if destino_key not in destinos:
                    destinos[destino_key] = {
                        "codigo": cod_destino or "-",
                        "nomes": Counter(),
                        "qtd": 0,
                        "origens": set(),
                    }
                destinos[destino_key]["nomes"][nome_destino_base] += 1
                destinos[destino_key]["qtd"] += 1
            else:
                sem_destino += 1

            if origem_disponivel and destino_disponivel:
                registros_completos += 1
                origem_key = cod_origem or self._chave_relatorio(nome_origem_base, "NÃO INFORMADA")
                destino_key = cod_destino or self._chave_relatorio(nome_destino_base, "NÃO INFORMADO")

                if origem_key not in cruzamentos:
                    cruzamentos[origem_key] = {
                        "codigo": cod_origem or "-",
                        "nomes": Counter(),
                        "qtd": 0,
                        "destinos": {},
                    }

                cruzamentos[origem_key]["nomes"][nome_origem_base] += 1
                cruzamentos[origem_key]["qtd"] += 1
                if destino_key not in cruzamentos[origem_key]["destinos"]:
                    cruzamentos[origem_key]["destinos"][destino_key] = {
                        "codigo": cod_destino or "-",
                        "nomes": Counter(),
                        "qtd": 0,
                    }
                cruzamentos[origem_key]["destinos"][destino_key]["nomes"][nome_destino_base] += 1
                cruzamentos[origem_key]["destinos"][destino_key]["qtd"] += 1
                origens[origem_key]["destinos"].add(destino_key)
                destinos[destino_key]["origens"].add(origem_key)

        origens_lista = []
        for origem in origens.values():
            nome = origem["nomes"].most_common(1)[0][0]
            origens_lista.append(
                {
                    "codigo": origem["codigo"],
                    "nome": nome,
                    "label": self._label_origem_relatorio(origem["codigo"], nome),
                    "qtd": origem["qtd"],
                    "percentual": (origem["qtd"] / len(rows) * 100) if rows else 0,
                    "destinos": len(origem["destinos"]),
                }
            )

        destinos_lista = []
        for destino in destinos.values():
            nome = destino["nomes"].most_common(1)[0][0]
            destinos_lista.append(
                {
                    "codigo": destino["codigo"],
                    "nome": nome,
                    "label": self._label_origem_relatorio(destino["codigo"], nome),
                    "qtd": destino["qtd"],
                    "percentual": (destino["qtd"] / len(rows) * 100) if rows else 0,
                    "origens": len(destino["origens"]),
                }
            )

        cruzamentos_lista = []
        for origem in cruzamentos.values():
            nome_origem = origem["nomes"].most_common(1)[0][0]
            destinos_origem = []
            for destino in origem["destinos"].values():
                nome_destino = destino["nomes"].most_common(1)[0][0]
                destinos_origem.append(
                    {
                        "codigo": destino["codigo"],
                        "nome": nome_destino,
                        "label": self._label_origem_relatorio(destino["codigo"], nome_destino),
                        "qtd": destino["qtd"],
                        "percentual": (destino["qtd"] / origem["qtd"] * 100) if origem["qtd"] else 0,
                    }
                )

            destinos_rankeados = sorted(
                destinos_origem,
                key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"]))
            )
            destinos_ordenados = sorted(
                destinos_origem,
                key=lambda item: self._sort_key_codigo_relatorio(item["codigo"], item["nome"])
            )
            cruzamentos_lista.append(
                {
                    "codigo": origem["codigo"],
                    "nome": nome_origem,
                    "origem": self._label_origem_relatorio(origem["codigo"], nome_origem),
                    "qtd": origem["qtd"],
                    "percentual": (origem["qtd"] / len(rows) * 100) if rows else 0,
                    "destinos_ativos": len(destinos_origem),
                    "destino_principal": destinos_rankeados[0] if destinos_rankeados else None,
                    "destinos": destinos_ordenados,
                }
            )

        origens_rankeadas = sorted(
            origens_lista,
            key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"]))
        )
        destinos_rankeados = sorted(
            destinos_lista,
            key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"]))
        )
        cruzamentos_rankeados = sorted(
            cruzamentos_lista,
            key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"]))
        )
        origens_ordenadas = sorted(
            origens_lista,
            key=lambda item: self._sort_key_codigo_relatorio(item["codigo"], item["nome"])
        )
        destinos_ordenados = sorted(
            destinos_lista,
            key=lambda item: self._sort_key_codigo_relatorio(item["codigo"], item["nome"])
        )
        cruzamentos_ordenados = sorted(
            cruzamentos_lista,
            key=lambda item: self._sort_key_codigo_relatorio(item["codigo"], item["nome"])
        )

        return {
            "total_geral": len(rows),
            "metricas": {
                "origens_ativas": len(origens_ordenadas),
                "destinos_ativos": len(destinos_ordenados),
                "cruzamentos_ativos": len(cruzamentos_ordenados),
                "registros_completos": registros_completos,
                "registros_incompletos": len(rows) - registros_completos,
            },
            "pendencias": {
                "sem_origem": sem_origem,
                "sem_destino": sem_destino,
            },
            "origens": origens_ordenadas,
            "destinos": destinos_ordenados,
            "cruzamentos": cruzamentos_ordenados,
            "executivo": {
                "origem_top": origens_rankeadas[0] if origens_rankeadas else None,
                "destino_top": destinos_rankeados[0] if destinos_rankeados else None,
                "cruzamento_top": cruzamentos_rankeados[0] if cruzamentos_rankeados else None,
            },
            "tops": {
                "origens": [
                    {
                        "label": item["label"],
                        "qtd": item["qtd"],
                        "subtitle": f"{item['destinos']} destinos mapeados",
                    }
                    for item in origens_rankeadas[:5]
                ],
                "destinos": [
                    {
                        "label": item["label"],
                        "qtd": item["qtd"],
                        "subtitle": f"{item['origens']} origens atendidas",
                    }
                    for item in destinos_rankeados[:5]
                ],
            },
        }

    def coletar_dados_pdf_fechamento_safra(self, d_ini, d_fim):
        metricas_sql = """
            SELECT
                COUNT(*) AS total,
                MIN(data_colheita) AS primeira_data,
                MAX(data_colheita) AS ultima_data,
                COUNT(DISTINCT NULLIF(TRIM(faz_muda_cod), '')) AS origens,
                COUNT(DISTINCT NULLIF(TRIM(faz_plantio_cod), '')) AS destinos,
                COUNT(DISTINCT NULLIF(TRIM(variedade_nome), '')) AS variedades
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
        """
        metricas_row = self.conn.execute(metricas_sql, (d_ini, d_fim)).fetchone()
        total_geral = int(metricas_row[0] or 0) if metricas_row else 0
        if not total_geral:
            return None

        primeira_data = datetime.strptime(metricas_row[1], "%Y-%m-%d")
        ultima_data = datetime.strptime(metricas_row[2], "%Y-%m-%d")

        origens = self._coletar_ranking_fazenda_fechamento(
            campo_cod="faz_muda_cod",
            campo_nome="faz_muda_nome",
            campo_apoio_cod="faz_plantio_cod",
            campo_apoio_nome="faz_plantio_nome",
            d_ini=d_ini,
            d_fim=d_fim,
            apoio_label="destinos",
            campo_data_ref="data_colheita",
            ordenar_por_data=True,
            fixar_inicio_e_fim=True,
        )
        destinos = self._coletar_ranking_fazenda_fechamento(
            campo_cod="faz_plantio_cod",
            campo_nome="faz_plantio_nome",
            campo_apoio_cod="faz_muda_cod",
            campo_apoio_nome="faz_muda_nome",
            d_ini=d_ini,
            d_fim=d_fim,
            apoio_label="origens",
            campo_data_ref="data_plantio",
            ordenar_por_data=True,
            fixar_inicio_e_fim=True,
        )
        variedades = self._coletar_ranking_variedades_fechamento(d_ini, d_fim, total_geral)
        motoristas = self._coletar_ranking_pessoas_fechamento(
            campo_nome="motorista_nome",
            campo_apoio="caminhao",
            d_ini=d_ini,
            d_fim=d_fim,
            apoio_label="caminhoes",
        )
        operadores = self._coletar_ranking_pessoas_fechamento(
            campo_nome="operador_nome",
            campo_apoio="colhedora",
            d_ini=d_ini,
            d_fim=d_fim,
            apoio_label="colhedoras",
        )
        fluxos = self._coletar_fluxos_fechamento(d_ini, d_fim)

        return {
            "total_geral": total_geral,
            "periodo": {
                "primeira_data": primeira_data,
                "ultima_data": ultima_data,
            },
            "metricas": {
                "origens_ativas": int(metricas_row[3] or 0),
                "destinos_ativos": int(metricas_row[4] or 0),
                "variedades_ativas": int(metricas_row[5] or 0),
                "blocos_fluxo": len(fluxos),
            },
            "rankings": {
                "origens": origens,
                "destinos": destinos,
                "variedades": variedades,
                "motoristas": motoristas,
                "operadores": operadores,
            },
            "fluxos": fluxos,
            "destaques": {
                "origem_top": max(origens, key=lambda item: item["qtd"]) if origens else None,
                "destino_top": max(destinos, key=lambda item: item["qtd"]) if destinos else None,
                "variedade_top": variedades[0] if variedades else None,
                "motorista_top": motoristas[0] if motoristas else None,
                "operador_top": operadores[0] if operadores else None,
            },
        }

    def _coletar_ranking_fazenda_fechamento(
        self,
        campo_cod,
        campo_nome,
        campo_apoio_cod,
        campo_apoio_nome,
        d_ini,
        d_fim,
        apoio_label,
        campo_data_ref="data_colheita",
        ordenar_por_data=False,
        fixar_inicio_e_fim=False,
    ):
        sql = f"""
            SELECT
                COALESCE(NULLIF(TRIM({campo_cod}), ''), '-') AS codigo,
                COALESCE(NULLIF(TRIM({campo_nome}), ''), 'NÃO INFORMADA') AS nome,
                {campo_data_ref},
                COALESCE(NULLIF(TRIM({campo_apoio_cod}), ''), NULLIF(TRIM({campo_apoio_nome}), '')) AS apoio,
                NULLIF(TRIM(variedade_nome), '') AS variedade
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND {campo_nome} IS NOT NULL
              AND TRIM({campo_nome}) <> ''
            ORDER BY {campo_nome}, data_colheita
        """

        grupos = {}
        for row in self.conn.execute(sql, (d_ini, d_fim)).fetchall():
            codigo = self._texto_relatorio(row[0], "-")
            nome = self._texto_relatorio(row[1], "NÃO INFORMADA")
            chave = codigo if codigo != "-" else self._chave_relatorio(nome, "NÃO INFORMADA")
            data_ref = datetime.strptime(row[2], "%Y-%m-%d")
            if chave not in grupos:
                grupos[chave] = {
                    "codigo": codigo,
                    "nomes": Counter(),
                    "primeira_data": data_ref,
                    "ultima_data": data_ref,
                    "qtd": 0,
                    "apoios": set(),
                    "variedades": set(),
                }

            grupo = grupos[chave]
            grupo["nomes"][nome] += 1
            grupo["primeira_data"] = min(grupo["primeira_data"], data_ref)
            grupo["ultima_data"] = max(grupo["ultima_data"], data_ref)
            grupo["qtd"] += 1
            apoio = self._texto_relatorio(row[3])
            variedade = self._texto_relatorio(row[4])
            if apoio:
                grupo["apoios"].add(apoio)
            if variedade:
                grupo["variedades"].add(variedade)

        itens = []
        for grupo in grupos.values():
            nome = grupo["nomes"].most_common(1)[0][0]
            itens.append(
                {
                    "codigo": grupo["codigo"],
                    "nome": nome,
                    "label": self._label_origem_relatorio(grupo["codigo"], nome),
                    "qtd": grupo["qtd"],
                    "primeira_data": grupo["primeira_data"],
                    "ultima_data": grupo["ultima_data"],
                    apoio_label: len(grupo["apoios"]),
                    "variedades": len(grupo["variedades"]),
                }
            )

        if ordenar_por_data:
            if fixar_inicio_e_fim:
                itens = self._ordenar_linha_tempo_inicio_fim(itens)
            else:
                itens.sort(
                    key=lambda item: (
                        item["primeira_data"],
                        item["ultima_data"],
                        self._sort_key_texto(item["nome"]),
                        -item["qtd"],
                    )
                )
        else:
            itens.sort(key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"])))
        return itens

    def _ordenar_linha_tempo_inicio_fim(self, itens):
        if len(itens) <= 1:
            return itens

        primeiro = min(
            itens,
            key=lambda item: (
                item["primeira_data"],
                item["ultima_data"],
                self._sort_key_texto(item["nome"]),
                -item["qtd"],
            ),
        )
        restantes = [item for item in itens if item is not primeiro]
        ultimo = max(
            restantes,
            key=lambda item: (
                item["ultima_data"],
                item["primeira_data"],
                item["qtd"],
                self._sort_key_texto(item["nome"]),
            ),
        )
        meio = [item for item in restantes if item is not ultimo]
        meio.sort(
            key=lambda item: (
                item["ultima_data"],
                item["primeira_data"],
                self._sort_key_texto(item["nome"]),
                -item["qtd"],
            )
        )
        return [primeiro, *meio, ultimo]

    def _coletar_ranking_variedades_fechamento(self, d_ini, d_fim, total_geral):
        sql = """
            SELECT
                COALESCE(NULLIF(TRIM(variedade_nome), ''), 'NÃO INFORMADA') AS nome,
                COUNT(*) AS qtd,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(faz_muda_cod), ''), NULLIF(TRIM(faz_muda_nome), ''))) AS origens,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(faz_plantio_cod), ''), NULLIF(TRIM(faz_plantio_nome), ''))) AS destinos
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND variedade_nome IS NOT NULL
              AND TRIM(variedade_nome) <> ''
            GROUP BY COALESCE(NULLIF(TRIM(variedade_nome), ''), 'NÃO INFORMADA')
            ORDER BY qtd DESC, nome
        """
        itens = []
        for row in self.conn.execute(sql, (d_ini, d_fim)).fetchall():
            qtd = int(row[1] or 0)
            itens.append(
                {
                    "nome": self._texto_relatorio(row[0], "NÃO INFORMADA"),
                    "qtd": qtd,
                    "percentual": (qtd / total_geral * 100) if total_geral else 0,
                    "origens": int(row[2] or 0),
                    "destinos": int(row[3] or 0),
                }
            )
        return itens

    def _coletar_ranking_pessoas_fechamento(self, campo_nome, campo_apoio, d_ini, d_fim, apoio_label):
        sql = f"""
            SELECT
                MIN(TRIM({campo_nome})) AS nome,
                COUNT(*) AS qtd,
                GROUP_CONCAT(DISTINCT NULLIF(TRIM({campo_apoio}), '')) AS apoio
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND {campo_nome} IS NOT NULL
              AND TRIM({campo_nome}) <> ''
            GROUP BY UPPER(TRIM({campo_nome}))
            ORDER BY qtd DESC, nome
            LIMIT 10
        """
        itens = []
        for row in self.conn.execute(sql, (d_ini, d_fim)).fetchall():
            apoio = [
                self._texto_relatorio(item)
                for item in str(row[2] or "").split(",")
                if self._texto_relatorio(item)
            ]
            itens.append(
                {
                    "nome": self._texto_relatorio(row[0], "NÃO INFORMADO"),
                    "qtd": int(row[1] or 0),
                    apoio_label: sorted(set(apoio), key=self._sort_key_texto),
                }
            )
        return itens

    def _coletar_fluxos_fechamento(self, d_ini, d_fim):
        sql = """
            SELECT
                faz_muda_cod,
                faz_muda_nome,
                variedade_nome,
                faz_plantio_cod,
                faz_plantio_nome,
                COUNT(*) as qtd,
                MIN(data_colheita) as data_inicio,
                MAX(data_colheita) as data_fim,
                GROUP_CONCAT(talhao) as talhoes
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND faz_muda_nome IS NOT NULL
              AND TRIM(faz_muda_nome) <> ''
              AND faz_plantio_nome IS NOT NULL
              AND TRIM(faz_plantio_nome) <> ''
              AND variedade_nome IS NOT NULL
              AND TRIM(variedade_nome) <> ''
            GROUP BY
                faz_muda_cod,
                faz_muda_nome,
                variedade_nome,
                faz_plantio_cod,
                faz_plantio_nome
        """
        rows = self.conn.execute(sql, (d_ini, d_fim)).fetchall()
        grupos = {}

        for row in rows:
            cod_origem = self._texto_relatorio(row[0], "-")
            nome_origem = self._texto_relatorio(row[1], "NÃO INFORMADA")
            variedade = self._texto_relatorio(row[2], "-")
            cod_destino = self._texto_relatorio(row[3], "")
            nome_destino = self._texto_relatorio(row[4], "NÃO INFORMADO")
            qtd = int(row[5] or 0)
            grupo_key = (
                cod_origem if cod_origem != "-" else self._chave_relatorio(nome_origem, "NÃO INFORMADA"),
                self._chave_relatorio(variedade, "-"),
            )

            if grupo_key not in grupos:
                grupos[grupo_key] = {
                    "codigo_origem": cod_origem,
                    "nomes_origem": Counter(),
                    "variedades": Counter(),
                    "inicio": datetime.strptime(row[6], "%Y-%m-%d"),
                    "fim": datetime.strptime(row[7], "%Y-%m-%d"),
                    "total": 0,
                    "talhoes": set(),
                    "destinos": {},
                }

            grupo = grupos[grupo_key]
            grupo["nomes_origem"][nome_origem] += qtd
            grupo["variedades"][variedade] += qtd
            grupo["inicio"] = min(grupo["inicio"], datetime.strptime(row[6], "%Y-%m-%d"))
            grupo["fim"] = max(grupo["fim"], datetime.strptime(row[7], "%Y-%m-%d"))
            grupo["total"] += qtd

            for talhao in str(row[8] or "").split(","):
                talhao_limpo = self._texto_relatorio(talhao)
                if talhao_limpo:
                    grupo["talhoes"].add(talhao_limpo)

            destino_key = cod_destino or self._chave_relatorio(nome_destino, "NÃO INFORMADO")
            if destino_key not in grupo["destinos"]:
                grupo["destinos"][destino_key] = {
                    "codigo": cod_destino or "-",
                    "nomes": Counter(),
                    "qtd": 0,
                }
            grupo["destinos"][destino_key]["nomes"][nome_destino] += qtd
            grupo["destinos"][destino_key]["qtd"] += qtd

        fluxos = []
        for grupo in grupos.values():
            nome_origem = grupo["nomes_origem"].most_common(1)[0][0]
            variedade = grupo["variedades"].most_common(1)[0][0]
            destinos = []
            for destino in grupo["destinos"].values():
                nome_destino = destino["nomes"].most_common(1)[0][0]
                destinos.append(
                    {
                        "codigo": destino["codigo"],
                        "nome": nome_destino,
                        "qtd": destino["qtd"],
                        "percentual": (destino["qtd"] / grupo["total"] * 100) if grupo["total"] else 0,
                    }
                )

            fluxos.append(
                {
                    "codigo_origem": grupo["codigo_origem"],
                    "nome_origem": nome_origem,
                    "origem": self._label_origem_relatorio(grupo["codigo_origem"], nome_origem),
                    "variedade": variedade,
                    "inicio": grupo["inicio"],
                    "fim": grupo["fim"],
                    "total": grupo["total"],
                    "talhoes": sorted(grupo["talhoes"], key=self._sort_key_texto),
                    "destinos": sorted(destinos, key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"]))),
                }
            )

        fluxos.sort(
            key=lambda item: (
                -item["total"],
                self._sort_key_texto(item["nome_origem"]),
                self._sort_key_texto(item["variedade"]),
            )
        )
        return fluxos

    def coletar_dados_pdf_fazendas_muda(self, d_ini, d_fim):
        sql_periodo = """
            SELECT
                faz_muda_cod,
                faz_muda_nome,
                data_colheita
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND faz_muda_nome IS NOT NULL
              AND TRIM(faz_muda_nome) <> ''
            ORDER BY data_colheita, numero
        """
        rows_periodo = self.conn.execute(sql_periodo, (d_ini, d_fim)).fetchall()
        if not rows_periodo:
            return None

        fazendas = {}
        total_geral = len(rows_periodo)
        fazendas_ativas = set()

        for row in rows_periodo:
            cod_origem = self._texto_relatorio(row[0], "-")
            nome_origem = self._texto_relatorio(row[1], "NÃO INFORMADA")
            data_colheita = datetime.strptime(self._texto_relatorio(row[2]), "%Y-%m-%d")
            fazenda_key = (
                cod_origem if cod_origem != "-" else self._chave_relatorio(nome_origem, "NÃO INFORMADA")
            )

            if fazenda_key not in fazendas:
                fazendas[fazenda_key] = {
                    "codigo": cod_origem,
                    "nomes": Counter(),
                    "primeira_data": data_colheita,
                    "ultima_data": data_colheita,
                    "qtd": 0,
                }

            fazenda = fazendas[fazenda_key]
            fazenda["nomes"][nome_origem] += 1
            fazenda["qtd"] += 1
            fazendas_ativas.add(fazenda_key)

        sql_historico = """
            SELECT
                faz_muda_cod,
                faz_muda_nome,
                data_colheita
            FROM notas
            WHERE faz_muda_nome IS NOT NULL
              AND TRIM(faz_muda_nome) <> ''
            ORDER BY data_colheita, numero
        """
        rows_historico = self.conn.execute(sql_historico).fetchall()
        primeira_data_periodo = None
        ultima_data_periodo = None

        for row in rows_historico:
            cod_origem = self._texto_relatorio(row[0], "-")
            nome_origem = self._texto_relatorio(row[1], "NÃO INFORMADA")
            data_colheita = datetime.strptime(self._texto_relatorio(row[2]), "%Y-%m-%d")
            fazenda_key = (
                cod_origem if cod_origem != "-" else self._chave_relatorio(nome_origem, "NÃO INFORMADA")
            )
            if fazenda_key not in fazendas_ativas:
                continue
            fazenda = fazendas.get(fazenda_key)
            if not fazenda:
                continue

            fazenda["primeira_data"] = min(fazenda["primeira_data"], data_colheita)
            fazenda["ultima_data"] = max(fazenda["ultima_data"], data_colheita)
            primeira_data_periodo = (
                data_colheita
                if primeira_data_periodo is None
                else min(primeira_data_periodo, data_colheita)
            )
            ultima_data_periodo = (
                data_colheita
                if ultima_data_periodo is None
                else max(ultima_data_periodo, data_colheita)
            )

        fazendas_lista = []
        for fazenda in fazendas.values():
            nome = fazenda["nomes"].most_common(1)[0][0]
            fazendas_lista.append(
                {
                    "codigo": fazenda["codigo"],
                    "nome": nome,
                    "label": self._label_fazenda_relatorio(fazenda["codigo"], nome, "MUDA"),
                    "primeira_data": fazenda["primeira_data"],
                    "ultima_data": fazenda["ultima_data"],
                    "qtd": fazenda["qtd"],
                }
            )

        fazendas_lista.sort(
            key=lambda item: (
                item["primeira_data"],
                item["ultima_data"],
                self._sort_key_codigo_relatorio(item["codigo"], item["nome"]),
            )
        )

        return {
            "total_geral": total_geral,
            "fazendas": fazendas_lista,
            "metricas": {
                "fazendas_ativas": len(fazendas_lista),
                "primeira_data_registrada": primeira_data_periodo,
                "ultima_data_registrada": ultima_data_periodo,
            },
        }

    def coletar_dados_pdf_geral(self, d_ini, d_fim):
        sql = """
            SELECT
                faz_muda_cod,
                faz_muda_nome,
                variedade_nome,
                faz_plantio_cod,
                faz_plantio_nome,
                COUNT(*) as qtd,
                MIN(data_colheita) as data_inicio,
                MAX(data_colheita) as data_fim,
                GROUP_CONCAT(talhao) as talhoes
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND faz_muda_nome IS NOT NULL
              AND TRIM(faz_muda_nome) <> ''
              AND faz_plantio_nome IS NOT NULL
              AND TRIM(faz_plantio_nome) <> ''
              AND variedade_nome IS NOT NULL
              AND TRIM(variedade_nome) <> ''
            GROUP BY
                faz_muda_cod,
                faz_muda_nome,
                variedade_nome,
                faz_plantio_cod,
                faz_plantio_nome
        """
        rows = self.conn.execute(sql, (d_ini, d_fim)).fetchall()

        grupos = {}
        total_geral = 0

        for row in rows:
            cod_origem = self._texto_relatorio(row[0], "-")
            nome_origem = self._texto_relatorio(row[1], "NÃO INFORMADA")
            variedade = self._texto_relatorio(row[2], "-")
            cod_destino = self._texto_relatorio(row[3], "")
            nome_destino = self._texto_relatorio(row[4], "NÃO INFORMADO")
            qtd = int(row[5] or 0)
            dt_inicio = datetime.strptime(row[6], "%Y-%m-%d")
            dt_fim = datetime.strptime(row[7], "%Y-%m-%d")
            grupo_key = (
                cod_origem if cod_origem != "-" else self._chave_relatorio(nome_origem, "NÃO INFORMADA"),
                self._chave_relatorio(variedade, "-"),
            )

            if grupo_key not in grupos:
                grupos[grupo_key] = {
                    "codigo_origem": cod_origem,
                    "nomes_origem": Counter(),
                    "variedades": Counter(),
                    "inicio": dt_inicio,
                    "fim": dt_fim,
                    "total": 0,
                    "talhoes": set(),
                    "destinos": {},
                }

            grupo = grupos[grupo_key]
            grupo["nomes_origem"][nome_origem] += qtd
            grupo["variedades"][variedade] += qtd
            grupo["inicio"] = min(grupo["inicio"], dt_inicio)
            grupo["fim"] = max(grupo["fim"], dt_fim)
            grupo["total"] += qtd
            total_geral += qtd

            for talhao in str(row[8] or "").split(","):
                talhao_limpo = self._texto_relatorio(talhao)
                if talhao_limpo:
                    grupo["talhoes"].add(talhao_limpo)

            destino_key = cod_destino or self._chave_relatorio(nome_destino, "NÃO INFORMADO")
            if destino_key not in grupo["destinos"]:
                grupo["destinos"][destino_key] = {
                    "codigo": cod_destino or "-",
                    "nomes": Counter(),
                    "qtd": 0,
                }
            grupo["destinos"][destino_key]["nomes"][nome_destino] += qtd
            grupo["destinos"][destino_key]["qtd"] += qtd

        grupos_finais = []
        for grupo in grupos.values():
            nome_origem = grupo["nomes_origem"].most_common(1)[0][0]
            variedade = grupo["variedades"].most_common(1)[0][0]
            destinos = []
            for destino in grupo["destinos"].values():
                nome_destino = destino["nomes"].most_common(1)[0][0]
                percentual = (destino["qtd"] / grupo["total"] * 100) if grupo["total"] else 0
                destinos.append(
                    {
                        "codigo": destino["codigo"],
                        "nome": nome_destino,
                        "qtd": destino["qtd"],
                        "percentual": percentual,
                    }
                )

            destinos.sort(key=lambda item: (-item["qtd"], self._sort_key_texto(item["nome"])))
            talhoes = sorted(grupo["talhoes"], key=self._sort_key_texto)

            grupos_finais.append(
                {
                    "codigo_origem": grupo["codigo_origem"],
                    "nome_origem": nome_origem,
                    "variedade": variedade,
                    "inicio": grupo["inicio"],
                    "fim": grupo["fim"],
                    "total": grupo["total"],
                    "talhoes": talhoes,
                    "destinos": destinos,
                }
            )

        grupos_finais.sort(
            key=lambda item: (
                -item["total"],
                self._sort_key_texto(item["nome_origem"]),
                self._sort_key_texto(item["variedade"]),
            )
        )

        origens_totais = {}
        variedades_totais = {}
        destinos_totais = {}

        for grupo in grupos_finais:
            origem_key = grupo["codigo_origem"] if grupo["codigo_origem"] != "-" else self._chave_relatorio(grupo["nome_origem"])
            if origem_key not in origens_totais:
                origens_totais[origem_key] = {
                    "label": self._label_fazenda_relatorio(grupo["codigo_origem"], grupo["nome_origem"], "MUDA"),
                    "qtd": 0,
                }
            origens_totais[origem_key]["qtd"] += grupo["total"]

            var_key = self._chave_relatorio(grupo["variedade"], "-")
            if var_key not in variedades_totais:
                variedades_totais[var_key] = {
                    "label": grupo["variedade"],
                    "qtd": 0,
                    "origens": set(),
                    "destinos": set(),
                    "blocos": 0,
                }
            variedades_totais[var_key]["qtd"] += grupo["total"]
            variedades_totais[var_key]["origens"].add(origem_key)
            variedades_totais[var_key]["blocos"] += 1

            for destino in grupo["destinos"]:
                dest_key = destino["codigo"] if destino["codigo"] != "-" else self._chave_relatorio(destino["nome"])
                variedades_totais[var_key]["destinos"].add(dest_key)
                if dest_key not in destinos_totais:
                    destinos_totais[dest_key] = {
                        "label": self._label_fazenda_relatorio(destino["codigo"], destino["nome"], "PLANTIO"),
                        "qtd": 0,
                    }
                destinos_totais[dest_key]["qtd"] += destino["qtd"]

        top_grupos = [
            {
                "label": self._label_fazenda_relatorio(item["codigo_origem"], item["nome_origem"], "MUDA"),
                "subtitle": f"Variedade: {self._texto_relatorio(item['variedade'])}",
                "qtd": item["total"],
            }
            for item in grupos_finais[:5]
        ]

        top_origens = sorted(origens_totais.values(), key=lambda item: (-item["qtd"], self._sort_key_texto(item["label"])))[:5]
        variedades_ranking = []
        for item in variedades_totais.values():
            origens_qtd = len(item["origens"])
            destinos_qtd = len(item["destinos"])
            blocos_qtd = int(item["blocos"] or 0)
            variedades_ranking.append(
                {
                    "label": item["label"],
                    "qtd": item["qtd"],
                    "percentual": (item["qtd"] / total_geral * 100) if total_geral else 0,
                    "subtitle": (
                        f"{origens_qtd} origem{'s' if origens_qtd != 1 else ''} | "
                        f"{destinos_qtd} destino{'s' if destinos_qtd != 1 else ''} | "
                        f"{blocos_qtd} bloco{'s' if blocos_qtd != 1 else ''}"
                    ),
                }
            )
        variedades_ranking.sort(key=lambda item: (-item["qtd"], self._sort_key_texto(item["label"])))
        top_variedades = variedades_ranking[:5]
        top_destinos = sorted(destinos_totais.values(), key=lambda item: (-item["qtd"], self._sort_key_texto(item["label"])))[:5]

        pendencias_sql = """
            SELECT
                SUM(CASE WHEN variedade_nome IS NULL OR TRIM(variedade_nome) = '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN faz_plantio_nome IS NULL OR TRIM(faz_plantio_nome) = '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN faz_muda_nome IS NULL OR TRIM(faz_muda_nome) = '' THEN 1 ELSE 0 END)
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
        """
        pendencias = self.conn.execute(pendencias_sql, (d_ini, d_fim)).fetchone()

        pendencias_detalhes = {
            "sem_variedade": [],
            "sem_destino": [],
            "sem_origem": [],
        }

        pendencias_detalhes_sql = """
            SELECT
                numero,
                data_colheita,
                faz_muda_cod,
                faz_muda_nome,
                variedade_nome,
                faz_plantio_cod,
                faz_plantio_nome
            FROM notas
            WHERE data_colheita BETWEEN ? AND ?
              AND (
                    variedade_nome IS NULL OR TRIM(variedade_nome) = ''
                 OR faz_plantio_nome IS NULL OR TRIM(faz_plantio_nome) = ''
                 OR faz_muda_nome IS NULL OR TRIM(faz_muda_nome) = ''
              )
            ORDER BY data_colheita, numero
        """
        for row in self.conn.execute(pendencias_detalhes_sql, (d_ini, d_fim)).fetchall():
            numero = self._texto_relatorio(row[0], "-")
            data_ref = self._texto_relatorio(row[1], "-")
            if data_ref != "-":
                try:
                    data_ref = datetime.strptime(data_ref, "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    pass

            origem_label = self._label_fazenda_relatorio(row[2], row[3], "MUDA")
            destino_label = self._label_fazenda_relatorio(row[5], row[6], "PLANTIO")
            variedade = self._texto_relatorio(row[4], "-")

            if not self._texto_relatorio(row[4]):
                pendencias_detalhes["sem_variedade"].append(
                    {
                        "nota": numero,
                        "data": data_ref,
                        "referencia": origem_label,
                        "detalhe": destino_label,
                    }
                )

            if not self._texto_relatorio(row[6]):
                pendencias_detalhes["sem_destino"].append(
                    {
                        "nota": numero,
                        "data": data_ref,
                        "referencia": origem_label,
                        "detalhe": f"Variedade: {variedade}",
                    }
                )

            if not self._texto_relatorio(row[3]):
                pendencias_detalhes["sem_origem"].append(
                    {
                        "nota": numero,
                        "data": data_ref,
                        "referencia": f"Variedade: {variedade}",
                        "detalhe": destino_label,
                    }
                )

        if not rows and not any(pendencias_detalhes.values()):
            return None

        return {
            "total_geral": total_geral,
            "grupos": grupos_finais,
            "metricas": {
                "origens_ativas": len(origens_totais),
                "variedades_ativas": len(variedades_totais),
                "destinos_ativos": len(destinos_totais),
                "blocos_analiticos": len(grupos_finais),
            },
            "pendencias": {
                "sem_variedade": int(pendencias[0] or 0),
                "sem_destino": int(pendencias[1] or 0),
                "sem_origem": int(pendencias[2] or 0),
            },
            "pendencias_detalhes": pendencias_detalhes,
            "tops": {
                "origens": top_origens,
                "variedades": top_variedades,
                "destinos": top_destinos,
                "grupos": top_grupos,
            },
            "variedades": variedades_ranking,
        }
