from __future__ import annotations
import tests as _bootstrap
import unittest
from unittest.mock import Mock, patch
from web_app import server
from reporting import RelatorioPdfPlantioDetalhadoBuilder

class TalhaoOrigemTest(unittest.TestCase):
    def payload(self, origem):
        driver = {"codigo": 1, "nome": "Pessoa ficticia"}
        destino = {"codigo": "200-001", "nome": "Destino ficticio"}
        variedade = {"id": 1, "nome": "Variedade ficticia"}
        with patch.object(server, "resolve_reference", side_effect=[driver, None, origem, destino, variedade]), patch.object(server, "resolve_field", return_value=None) as resolver:
            result = server.build_note_payload(Mock(), {"numero": "1", "talhao": "T-ORIGEM"})
        return result, resolver

    def test_sem_origem_preserva_digitado_sem_resolver_no_destino(self):
        result, resolver = self.payload(None)
        resolver.assert_not_called()
        self.assertEqual("T-ORIGEM", result["talhao"])
        self.assertEqual("200-001", result["faz_plantio_cod"])
        self.assertEqual("digitado_sem_referencia", result["_referencias_origem"]["talhao"]["fonte"])

    def test_resolucao_recebe_somente_fazenda_de_origem(self):
        origem = {"codigo": "100-001", "nome": "Origem ficticia"}
        result, resolver = self.payload(origem)
        self.assertEqual(origem, resolver.call_args.args[2])
        self.assertEqual("100-001", result["faz_muda_cod"])
        self.assertEqual("200-001", result["faz_plantio_cod"])

    def test_autocomplete_sem_origem_nao_lista_talhoes_de_outras_fazendas(self):
        handler, db = Mock(), Mock()
        with patch.object(server, "get_db", return_value=db):
            server.AppNotasWebHandler.handle_references(handler, {"tabela": ["talhoes"]})
        db.listar_talhoes_filtrados.assert_not_called()
        handler.send_json.assert_called_once_with({"ok": True, "items": []})

    def test_pdf_distingue_origem_talhao_e_destino(self):
        dados = {"total_geral": 1, "metricas": {"propriedades": 1, "talhoes": 1, "variedades": 1, "campos_pendentes": 0}, "linhas": [{"nota": "1", "data_colheita": "01/04/2026", "data_plantio": "02/04/2026", "origem": "ORIGEM-FICTICIA", "propriedade": "DESTINO-FICTICIO", "talhao": "T-ORIGEM", "variedade": "V-FICTICIA"}]}
        pdf = RelatorioPdfPlantioDetalhadoBuilder().criar_pdf_plantio_detalhado("2026-04-01", "2026-04-30", dados)
        pdf.set_compression(False)
        content = bytes(pdf.output())
        for label in (b"FAZENDA ORIGEM", b"FAZENDA DESTINO", b"TALHAO ORIGEM", b"ORIGEM-FICTICIA", b"DESTINO-FICTICIO", b"T-ORIGEM"):
            self.assertIn(label, content)

if __name__ == "__main__":
    unittest.main()
