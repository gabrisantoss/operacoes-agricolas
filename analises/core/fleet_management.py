# core/fleet_management.py

import sqlite3
from .database_manager import DatabaseManager

# A lista completa de frotas que você forneceu
fleet_data = {
    "COLHEDORA": {
        "1": ["974", "950", "951"], "2": ["954", "952", "953"], "3": ["963", "933", "962"],
        "4": ["957", "956", "979", "980", "981"], "5": ["930", "931", "932"], "6": ["937", "947", "941"],
        "7": ["984", "982", "983"], "8": ["936", "935", "960", "976"], "9": ["955", "959", "977", "975"],
        "10": ["940", "985", "961", "967"], "11": ["965", "966", "964", "945"], "12": ["942", "943", "968", "969"],
        "13": ["958", "946", "972", "970"], "14": ["949", "971", "948", "978"]
    },
    "TRANSBORDO": {
        "1": ["1572", "1573", "1574", "1575", "1576", "1577"], "2": ["1051", "1052", "1053", "1054", "1055", "1056", "403", "404"],
        "3": ["411", "1122", "1061", "413", "1120", "1124", "1123", "1121"], "4": ["1062", "1127", "1125", "1126", "1129", "1128", "1513"],
        "5": ["1560", "1561", "1562", "1563", "1564", "1565"], "6": ["1566", "1567", "1568", "1569", "1570", "1571"],
        "7": ["1579", "1580", "1581", "1582", "1583", "1584"], "8": ["1069", "1070", "1071", "1072", "1073", "1074", "417", "418"],
        "9": ["1057", "1092", "1093", "1058", "1059", "1060", "406", "405"], "10": ["1063", "1064", "1065", "1066", "1067", "1068", "425", "426"],
        "11": ["1084", "1085", "1075", "1076", "1077", "429", "439"], "12": ["1078", "1079", "1080", "1081", "1100", "1101", "441", "440"],
        "13": ["1082", "1083", "1087", "1088", "1091", "1089", "446", "447"], "14": ["1094", "1095", "1096", "1097", "1098", "1099", "443", "445"]
    },
    "GUINCHO": {
        "1": ["851"], "2": ["801"], "3": ["803"], "4": ["822"], "5": ["807"], "6": ["814"], "7": ["806"],
        "8": ["811"], "9": ["852"], "10": ["815"], "11": ["817"], "12": ["816"], "13": ["896"], "14": ["841"]
    },
    "CAMINHAO D'AGUA": {
        "1": ["334"], "2": ["1104"], "3": ["339"], "4": ["369"], "5": ["374"], "6": ["343"], "7": ["378"],
        "8": ["370"], "9": ["1103"], "10": ["340"], "11": ["368"], "12": ["353"], "13": ["1102"], "14": ["1105"]
    },
    "CAMINHAO CORINGA": {
        "SEM FRENTE": ["414", "416", "419", "420", "421", "422", "428", "430", "431", "402"]
    }
}

def populate_initial_fleets():
    """
    Limpa a tabela FROTAS_POR_FRENTE e a preenche com a lista completa.
    Esta função deve ser executada apenas uma vez.
    """
    print("INFO: Iniciando o povoamento da tabela de frotas...")
    try:
        # 1. Limpa a tabela para evitar duplicatas
        DatabaseManager.execute_non_query("DELETE FROM FROTAS_POR_FRENTE")
        print("INFO: Tabela de frotas anterior foi limpa.")

        # 2. Itera sobre os dados e insere no banco
        fleet_entries = []
        for tipo, frentes in fleet_data.items():
            for frente, numeros in frentes.items():
                for numero in numeros:
                    # Formata o nome completo da frota
                    frota_nome = f"{tipo} {numero.strip()}"
                    fleet_entries.append((frente, frota_nome))

        query = "INSERT INTO FROTAS_POR_FRENTE (Frente, Frota) VALUES (?, ?)"
        with DatabaseManager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, fleet_entries)

        print(f"SUCESSO: {len(fleet_entries)} registros de frotas foram inseridos no banco de dados.")
        return True
    except Exception as e:
        print(f"ERRO: Falha ao popular a tabela de frotas: {e}")
        return False
