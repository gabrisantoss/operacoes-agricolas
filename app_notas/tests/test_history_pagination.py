from __future__ import annotations
import tests as _bootstrap
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from database import DB
from web_app import server

class HistoryPaginationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="history_page_"))
        self.db = DB(self.tmp / "synthetic.db", seed_from_excel=False)
        self.records = []
        for i in range(123):
            row = (5000+i, "PESSOA FICTICIA", "100001" if i%2 else "100002", "ORIGEM ÁGUA" if i%2 else "ORIGEM CAMPO", "200001" if i%3 else "200002", "DESTINO SUL" if i%3 else "DESTINO NORTE", "VAR-DEMO-A" if i%5 else "VAR-DEMO-B", "T-ORIGEM", "2026-04-30", "2026-05-02")
            self.records.append(row)
        self.insert(self.records)

    def insert(self, records):
        self.db.conn.executemany("INSERT INTO notas (numero,motorista_nome,faz_muda_cod,faz_muda_nome,faz_plantio_cod,faz_plantio_nome,variedade_nome,talhao,data_colheita,data_plantio) VALUES (?,?,?,?,?,?,?,?,?,?)", records)
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_paginas_sem_sobreposicao_e_total(self):
        pages=[self.db.buscar_historico_paginado(limit=50,offset=i) for i in (0,50,100)]
        self.assertEqual([50,50,23],[len(p["items"]) for p in pages])
        self.assertTrue(all(p["total"]==123 for p in pages))
        numbers=[r["numero"] for p in pages for r in p["items"]]
        self.assertEqual(sorted((r[0] for r in self.records),reverse=True),numbers)
        self.assertEqual(123,len(set(numbers)))
        last=self.db.buscar_historico_paginado(limit=50,offset=99999)
        self.assertEqual(100,last["offset"])
        self.assertEqual(23,len(last["items"]))

    def test_mais_de_mil_notas_sao_alcancaveis(self):
        self.insert([(10000+i,*self.records[0][1:]) for i in range(1001)])
        last=self.db.buscar_historico_paginado(limit=50,offset=1100)
        self.assertEqual(1124,last["total"])
        self.assertEqual(24,len(last["items"]))
        self.assertEqual(5000,last["items"][-1]["numero"])

    def test_filtros_combinados_busca_e_periodos(self):
        expected={r[0] for r in self.records if r[2]=="100001" and r[4]=="200001" and r[6]=="VAR-DEMO-A"}
        result=self.db.buscar_historico_paginado(origem="100001",destino="sul",variedade="DEMO-A",q="pessoa",limit=50)
        self.assertEqual(expected,{r["numero"] for r in result["items"]})
        self.assertEqual(len(expected),result["total"])
        for ref,start,end,count in [("data_colheita","2026-04-01","2026-04-30",len(expected)),("data_colheita","2026-05-01","2026-05-31",0),("data_plantio","2026-04-01","2026-04-30",0),("data_plantio","2026-05-01","2026-05-31",len(expected))]:
            filtered=self.db.buscar_historico_paginado(start,end,origem="100001",destino="sul",variedade="DEMO-A",date_reference=ref)
            self.assertEqual(count,filtered["total"])
        self.assertEqual(123,self.db.buscar_historico_paginado("2026-04-01","2026-04-30")["total"])
        empty=self.db.buscar_historico_paginado(origem="ÁGUA",destino="inexistente",offset=50)
        self.assertEqual((0,0,[]),(empty["total"],empty["offset"],empty["items"]))

    def test_busca_geral_prefixo_unicode_e_caracteres_literais(self):
        result=self.db.buscar_historico_paginado(q="água",campo="origem")
        self.assertEqual(61,result["total"])
        self.assertEqual(61,self.db.buscar_historico_paginado(origem="água")["total"])
        result=self.db.buscar_historico_paginado(q="501",campo="nota")
        self.assertEqual(set(range(5010,5020)),{r["numero"] for r in result["items"]})
        self.assertEqual(0,self.db.buscar_historico_paginado(q="nao-numerico",campo="nota")["total"])
        for literal in ("%","_","!","' OR 1=1 --"):
            self.assertEqual(0,self.db.buscar_historico_paginado(q=literal)["total"])
        self.assertEqual(123,self.db.contar_notas_total())

    def test_api_pagina_e_filtros_independentes(self):
        handler=Mock()
        params={"limit":["10"],"offset":["10"],"origem":["100001"],"destino":["sul"],"variedade":["DEMO-A"],"start":["2026-05-01"],"end":["2026-05-31"],"date_reference":["data_plantio"]}
        with patch.object(server,"get_db",return_value=self.db):
            server.AppNotasWebHandler.handle_historico(handler,params)
        result=handler.send_json.call_args.args[0]
        expected=[r for r in reversed(self.records) if r[2]=="100001" and r[4]=="200001" and r[6]=="VAR-DEMO-A"]
        self.assertEqual(len(expected),result["total"])
        self.assertEqual([r[0] for r in expected[10:20]],[r["numero"] for r in result["items"]])
        self.assertEqual(10,result["offset"])
        self.assertEqual("data_plantio",result["date_reference"])
