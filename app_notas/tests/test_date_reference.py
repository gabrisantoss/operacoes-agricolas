from __future__ import annotations
import tests as _bootstrap
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
from PyPDF2 import PdfReader
from database import DB
from date_reference import date_column
from reporting import RelatorioDataService
from web_app import server

class DateReferenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="notas_date_test_"))
        self.db = DB(self.tmp / "synthetic.db", seed_from_excel=False)
        for num, harvest, plant in [(1,"2026-01-31","2026-02-02"),(2,"2026-02-02","2026-03-01"),(3,"2026-01-30","2026-02-03"),(4,"2025-12-31","2026-01-01")]:
            self.db.inserir_nota(dict(numero=num,motorista_cod=1,motorista_nome="Pessoa ficticia",caminhao="DEMO",operador_cod=1,operador_nome="Operador ficticio",colhedora="DEMO",faz_muda_cod="100001",faz_muda_nome="Origem ficticia",talhao="T-ORIGEM",faz_plantio_cod="200001",faz_plantio_nome="Destino ficticio",variedade_id=1,variedade_nome="VAR-DEMO",data_colheita=harvest,data_plantio=plant))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def params(self, reference):
        return {"start":["2026-02-01"],"end":["2026-02-28"],"date_reference":[reference]}

    def test_consultas_indicadores_exportacoes_e_padrao(self):
        start,end="2026-02-01","2026-02-28"
        self.assertEqual([2], [r["numero"] for r in self.db.buscar_notas_historico(start,end)])
        for ref, numbers in [("data_colheita",{2}),("data_plantio",{1,3})]:
            with self.subTest(reference=ref):
                self.assertEqual(numbers,{r["numero"] for r in self.db.buscar_notas_historico(start,end,date_reference=ref)})
                self.assertEqual(len(numbers),self.db.contar_notas_periodo(start,end,ref))
                self.assertEqual(len(numbers),self.db.contar_dias_ativos_periodo(start,end,ref))
                for column in ["motorista_nome","faz_muda_nome","faz_plantio_nome"]:
                    self.assertEqual(len(numbers),sum(r["qtd"] for r in self.db.top_por_coluna(column,start,end,date_reference=ref)))
                self.assertEqual(numbers,set(self.db.dataframe_historico(start,end,ref)["numero"]))
                flow=self.db.dataframe_fluxo(start,end,ref)
                self.assertEqual(len(numbers),int(flow["Qtd"].sum()))
                self.assertEqual({"T-ORIGEM"},set(flow["Talhao de origem"]))
                data=RelatorioDataService(self.db.conn,ref)
                for kind in ["diario","simplificado","geral","plantio_detalhado","fazendas_muda","fechamento_safra"]:
                    report=getattr(data,"coletar_dados_pdf_"+kind)(start,end)
                    self.assertEqual(len(numbers),report["total_geral"],kind)
                detail=data.coletar_dados_pdf_plantio_detalhado(start,end)
                self.assertEqual(numbers,{int(r["nota"]) for r in detail["linhas"]})
        daily=RelatorioDataService(self.db.conn,"data_plantio").coletar_dados_pdf_diario(start,end)
        self.assertEqual({"02/02/2026","03/02/2026"},{r["data"] for r in daily["linhas"]})
        self.assertEqual(4,self.db.contar_notas_total())

    def test_api_historico_dashboard_e_exportacoes(self):
        for ref,count in [("data_colheita",1),("data_plantio",2)]:
            params=self.params(ref)
            handler=Mock()
            with patch.object(server,"get_db",return_value=self.db):
                server.AppNotasWebHandler.handle_historico(handler,params)
                self.assertEqual(count,handler.send_json.call_args.args[0]["total"])
                server.AppNotasWebHandler.handle_dashboard(handler,params)
                self.assertEqual(count,handler.send_json.call_args.args[0]["metrics"]["total"])
                for kind in ["bruto","fluxo"]:
                    target=self.tmp / (ref+kind+".xlsx")
                    handler.get_period_params.return_value=("2026-02-01","2026-02-28")
                    with patch.object(server,"generated_path",return_value=target):
                        server.AppNotasWebHandler.handle_export(handler,{**params,"type":[kind]})
                    frame=pd.read_excel(target)
                    self.assertEqual(count, len(frame) if kind=="bruto" else int(frame["Qtd"].sum()))
                    self.assertEqual({"Data de plantio" if ref=="data_plantio" else "Data de colheita"},set(frame["Data de referencia"]))

    def test_pdfs_informam_criterio_em_todas_as_paginas(self):
        from contextlib import nullcontext
        handler=Mock()
        handler.get_period_params.return_value=("2026-02-01","2026-02-28")
        for kind in ["diario","geral","simples","plantio_detalhado","mudas","fechamento"]:
            target=self.tmp / (kind+".pdf")
            with patch.object(server,"independent_report_connection",return_value=nullcontext(self.db.conn)),patch.object(server,"generated_path",return_value=target):
                server.AppNotasWebHandler.handle_pdf(handler,{**self.params("data_plantio"),"type":[kind]})
            pdf=PdfReader(target)
            for page in pdf.pages:
                self.assertIn("Referencia: Data de plantio",page.extract_text(),kind)
            if kind=="plantio_detalhado":
                text="".join(p.extract_text() for p in pdf.pages)
                self.assertIn("TALHAO ORIGEM",text)
                self.assertIn("31/01/2026",text)
                self.assertIn("02/02/2026",text)

    def test_desktop_historico_e_relatorios_usam_escolha(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from types import SimpleNamespace
        from PyQt5 import QtWidgets, QtCore
        from tabs.tab_historico import TabHistorico
        from tabs.tab_relatorios import AbaRelatorios
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        history = TabHistorico(self.db, SimpleNamespace())
        history.dt_de.setDate(QtCore.QDate(2026,2,1))
        history.dt_ate.setDate(QtCore.QDate(2026,2,28))
        history.carregar_dados(True)
        self.assertEqual(1,history.model.rowCount())
        history.cb_date_reference.setCurrentIndex(1)
        self.assertEqual(2,history.model.rowCount())
        self.assertEqual({"Data de plantio"},{r["Data de referencia"] for r in history._dados_visiveis_para_exportacao()})
        report = AbaRelatorios(self.db, SimpleNamespace())
        report.cb_date_reference.blockSignals(True)
        report.cb_date_reference.setCurrentIndex(1)
        report.cb_date_reference.blockSignals(False)
        with patch.object(report,"_iniciar_tarefa") as start_task:
            report.gerar_dashboard(False)
            self.assertEqual("data_plantio",start_task.call_args.args[0].kwargs["date_reference"])
        target=self.tmp / "desktop.xlsx"
        report._tarefa_excel_fluxo(self.db,"2026-02-01","2026-02-28",str(target),lambda *a: None,lambda: False,date_reference="data_plantio")
        frame=pd.read_excel(target)
        self.assertEqual(2,int(frame["Qtd"].sum()))
        self.assertEqual({"Data de plantio"},set(frame["Data de referencia"]))
        history.deleteLater()
        report.deleteLater()
        app.processEvents()

    def test_historico_antigo_sem_plantio_nao_e_preenchido(self):
        self.db._execute("UPDATE notas SET data_plantio = NULL WHERE numero = 4")
        self.db.conn.commit()
        data=RelatorioDataService(self.db.conn,"data_plantio")
        report=data.coletar_dados_pdf_fazendas_muda("2026-02-01","2026-02-28")
        self.assertEqual(2,report["total_geral"])
        self.assertIsNone(self.db.buscar_nota(4)["data_plantio"])
        self.assertEqual(4,self.db.contar_notas_total())

    def test_data_invalida_rejeitada(self):
        for ref in ["numero", "data_colheita; DROP TABLE notas", ""]:
            with self.assertRaises(ValueError): date_column(ref)
        self.assertEqual(4,self.db.contar_notas_total())
