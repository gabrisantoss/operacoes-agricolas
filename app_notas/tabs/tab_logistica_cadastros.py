from PyQt5 import QtWidgets, QtCore, QtGui
from datetime import date
from styles import aplicar_icone, StatusDelegate, configure_table

class TabLogisticaCadastros(QtWidgets.QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        hero = QtWidgets.QFrame()
        hero.setObjectName("ToolbarCard")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(4)

        lbl = QtWidgets.QLabel("Central de Logistica (C.O.L.)")
        lbl.setObjectName("PageTitle")
        hero_layout.addWidget(lbl)

        lbl_desc = QtWidgets.QLabel("Cadastros basicos, localizacao diaria e escala de viagens em um unico fluxo.")
        lbl_desc.setObjectName("PageSubtitle")
        hero_layout.addWidget(lbl_desc)

        layout.addWidget(hero)

        self.tabs_internas = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs_internas)

        self.tab_frota = QtWidgets.QWidget(); self._setup_frota(); self.tabs_internas.addTab(self.tab_frota, "Frota")
        self.tab_cidades = QtWidgets.QWidget(); self._setup_cidades(); self.tabs_internas.addTab(self.tab_cidades, "Cidades")
        self.tab_frentes = QtWidgets.QWidget(); self._setup_frentes(); self.tabs_internas.addTab(self.tab_frentes, "Frentes")
        self.tab_local = QtWidgets.QWidget(); self._setup_localizacao(); self.tabs_internas.addTab(self.tab_local, "Localizacao das Frentes")
        self.tab_escala = QtWidgets.QWidget(); self._setup_escala(); self.tabs_internas.addTab(self.tab_escala, "Escala de Viagem")

    # ==========================
    # 1. FROTA
    # ==========================
    def _setup_frota(self):
        l = QtWidgets.QVBoxLayout(self.tab_frota)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(10)
        form = QtWidgets.QHBoxLayout()
        self.ed_bus_num = QtWidgets.QLineEdit(); self.ed_bus_num.setPlaceholderText("Número (ex: 709)")
        self.ed_bus_placa = QtWidgets.QLineEdit(); self.ed_bus_placa.setPlaceholderText("Placa")
        self.cb_bus_st = QtWidgets.QComboBox(); self.cb_bus_st.addItems(["ATIVO", "MANUTENÇÃO"])
        btn = QtWidgets.QPushButton("Adicionar"); btn.clicked.connect(self.add_frota); btn.setObjectName("SuccessButton")
        form.addWidget(QtWidgets.QLabel("Nº:")); form.addWidget(self.ed_bus_num); form.addWidget(self.ed_bus_placa); form.addWidget(self.cb_bus_st); form.addWidget(btn)
        l.addLayout(form)

        # Cria a tabela
        self.tb_frota = self._criar_tabela(["ID", "Número", "Placa", "Status"])

        # --- APLICA A MELHORIA VISUAL (BADGE) NA COLUNA 3 (STATUS) ---
        self.tb_frota.setItemDelegateForColumn(3, StatusDelegate(self.tb_frota))

        l.addWidget(self.tb_frota)
        self.carregar_frota()

    def add_frota(self):
        try: self.db.conn.execute("INSERT INTO frota (numero, placa, status) VALUES (?,?,?)", (self.ed_bus_num.text(), self.ed_bus_placa.text(), self.cb_bus_st.currentText())); self.db.conn.commit(); self.carregar_frota()
        except Exception as e: QtWidgets.QMessageBox.warning(self, "Erro", str(e))
    def carregar_frota(self): self._load_table(self.tb_frota, "SELECT id, numero, placa, status FROM frota ORDER BY numero")

    # ==========================
    # 2. CIDADES
    # ==========================
    def _setup_cidades(self):
        l = QtWidgets.QVBoxLayout(self.tab_cidades)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(10)
        form = QtWidgets.QHBoxLayout()
        self.ed_cid_nome = QtWidgets.QLineEdit(); self.ed_cid_nome.setPlaceholderText("Cidade (ex: Cruz)")
        btn = QtWidgets.QPushButton("Adicionar"); btn.clicked.connect(self.add_cidade); btn.setObjectName("SuccessButton")
        form.addWidget(QtWidgets.QLabel("Nome:")); form.addWidget(self.ed_cid_nome); form.addWidget(btn)
        l.addLayout(form)
        self.tb_cidades = self._criar_tabela(["ID", "Nome"]); l.addWidget(self.tb_cidades)
        self.carregar_cidades()

    def add_cidade(self):
        try: self.db.conn.execute("INSERT INTO cidades (nome) VALUES (?)", (self.ed_cid_nome.text(),)); self.db.conn.commit(); self.carregar_cidades()
        except Exception as e: QtWidgets.QMessageBox.warning(self, "Erro", str(e))
    def carregar_cidades(self): self._load_table(self.tb_cidades, "SELECT id, nome FROM cidades")

    # ==========================
    # 3. FRENTES
    # ==========================
    def _setup_frentes(self):
        l = QtWidgets.QVBoxLayout(self.tab_frentes)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(10)
        form = QtWidgets.QHBoxLayout()
        self.ed_fr_nome = QtWidgets.QLineEdit(); self.ed_fr_nome.setPlaceholderText("Nome (ex: Frente 1)")
        btn = QtWidgets.QPushButton("Criar Frente"); btn.clicked.connect(self.add_frente); btn.setObjectName("SuccessButton")
        form.addWidget(QtWidgets.QLabel("Nome:")); form.addWidget(self.ed_fr_nome); form.addWidget(btn)
        l.addLayout(form)
        self.tb_frentes = self._criar_tabela(["ID", "Nome"]); l.addWidget(self.tb_frentes)
        self.carregar_frentes()

    def add_frente(self):
        try: self.db.conn.execute("INSERT INTO frentes (nome) VALUES (?)", (self.ed_fr_nome.text(),)); self.db.conn.commit(); self.carregar_frentes()
        except Exception as e: QtWidgets.QMessageBox.warning(self, "Erro", str(e))
    def carregar_frentes(self): self._load_table(self.tb_frentes, "SELECT id, nome FROM frentes")

    # ==========================
    # 4. LOCALIZAÇÃO DIÁRIA (SETUP)
    # ==========================
    def _setup_localizacao(self):
        l = QtWidgets.QVBoxLayout(self.tab_local)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(10)

        # Formulário
        gb = QtWidgets.QGroupBox("Definir Local de Hoje"); form = QtWidgets.QHBoxLayout(gb)
        self.dt_loc = QtWidgets.QDateEdit(date.today()); self.dt_loc.setCalendarPopup(True)

        self.cb_loc_frente = QtWidgets.QComboBox() # Carregar Frentes
        self.cb_loc_fazenda = QtWidgets.QComboBox() # Carregar Fazendas (do banco principal)
        self.cb_loc_fazenda.setEditable(True) # Para digitar e buscar

        btn = QtWidgets.QPushButton("Definir Local"); btn.clicked.connect(self.add_localizacao); btn.setObjectName("SuccessButton")

        form.addWidget(QtWidgets.QLabel("Data:")); form.addWidget(self.dt_loc)
        form.addWidget(QtWidgets.QLabel("Frente:")); form.addWidget(self.cb_loc_frente)
        form.addWidget(QtWidgets.QLabel("Está na Fazenda:")); form.addWidget(self.cb_loc_fazenda)
        form.addWidget(btn)

        l.addWidget(gb)
        self.tb_local = self._criar_tabela(["ID", "Data", "Frente", "Fazenda Atual"]); l.addWidget(self.tb_local)

        btn_att = QtWidgets.QPushButton("Atualizar listas"); btn_att.setObjectName("SecondaryButton"); btn_att.clicked.connect(self.carregar_combos_local); l.addWidget(btn_att)

        self.carregar_combos_local()
        self.carregar_localizacao()

    def carregar_combos_local(self):
        self.cb_loc_frente.clear(); self.cb_loc_fazenda.clear()
        # Frentes
        for r in self.db.conn.execute("SELECT id, nome FROM frentes").fetchall():
            self.cb_loc_frente.addItem(r[1], r[0])
        # Fazendas (Tabela original)
        for r in self.db.conn.execute("SELECT codigo, nome FROM fazendas ORDER BY nome").fetchall():
            self.cb_loc_fazenda.addItem(f"{r[0]} - {r[1]}", r[0])

    def add_localizacao(self):
        dt = self.dt_loc.date().toString("yyyy-MM-dd")
        fr_id = self.cb_loc_frente.currentData()
        faz_cod = self.cb_loc_fazenda.currentData()

        if not fr_id or not faz_cod: return

        try:
            # Remove anterior se houver para essa frente/data
            self.db.conn.execute("DELETE FROM localizacao_frentes WHERE data=? AND frente_id=?", (dt, fr_id))
            self.db.conn.execute("INSERT INTO localizacao_frentes (data, frente_id, fazenda_cod) VALUES (?,?,?)", (dt, fr_id, faz_cod))
            self.db.conn.commit(); self.carregar_localizacao()
            QtWidgets.QMessageBox.information(self, "Sucesso", "Localização definida!")
        except Exception as e: QtWidgets.QMessageBox.critical(self, "Erro", str(e))

    def carregar_localizacao(self):
        dt = self.dt_loc.date().toString("yyyy-MM-dd")
        sql = """
            SELECT lf.id, lf.data, fr.nome, fz.nome
            FROM localizacao_frentes lf
            JOIN frentes fr ON lf.frente_id = fr.id
            JOIN fazendas fz ON lf.fazenda_cod = fz.codigo
            WHERE lf.data = ?
        """
        self._load_table(self.tb_local, sql, (dt,))

    # ==========================
    # 5. ESCALA DE VIAGEM (VÍNCULO)
    # ==========================
    def _setup_escala(self):
        l = QtWidgets.QVBoxLayout(self.tab_escala)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(10)

        gb = QtWidgets.QGroupBox("Programar Viagem"); form = QtWidgets.QGridLayout(gb)

        self.cb_esc_bus = QtWidgets.QComboBox()
        self.cb_esc_frente = QtWidgets.QComboBox()
        self.cb_esc_cidade = QtWidgets.QComboBox()
        self.te_ida = QtWidgets.QTimeEdit(QtCore.QTime(5, 30))
        self.te_volta = QtWidgets.QTimeEdit(QtCore.QTime(16, 0))

        btn = QtWidgets.QPushButton("Salvar Escala"); btn.clicked.connect(self.add_escala); btn.setObjectName("SuccessButton")

        form.addWidget(QtWidgets.QLabel("Ônibus:"), 0, 0); form.addWidget(self.cb_esc_bus, 0, 1)
        form.addWidget(QtWidgets.QLabel("Atende a Frente:"), 0, 2); form.addWidget(self.cb_esc_frente, 0, 3)
        form.addWidget(QtWidgets.QLabel("Sai de (Cidade):"), 1, 0); form.addWidget(self.cb_esc_cidade, 1, 1)
        form.addWidget(QtWidgets.QLabel("Hora Saída:"), 1, 2); form.addWidget(self.te_ida, 1, 3)
        form.addWidget(QtWidgets.QLabel("Hora Volta:"), 2, 2); form.addWidget(self.te_volta, 2, 3)
        form.addWidget(btn, 2, 0, 1, 2)

        l.addWidget(gb)
        self.tb_escala = self._criar_tabela(["ID", "Ônibus", "Frente", "Origem", "Ida", "Volta"]); l.addWidget(self.tb_escala)

        btn_att = QtWidgets.QPushButton("Atualizar listas"); btn_att.setObjectName("SecondaryButton"); btn_att.clicked.connect(self.carregar_combos_escala); l.addWidget(btn_att)

        self.carregar_combos_escala()
        self.carregar_escala()

    def carregar_combos_escala(self):
        self.cb_esc_bus.clear(); self.cb_esc_frente.clear(); self.cb_esc_cidade.clear()
        # Onibus
        for r in self.db.conn.execute("SELECT id, numero, placa FROM frota").fetchall():
            self.cb_esc_bus.addItem(f"{r[1]} ({r[2]})", r[0])
        # Frentes
        for r in self.db.conn.execute("SELECT id, nome FROM frentes").fetchall():
            self.cb_esc_frente.addItem(r[1], r[0])
        # Cidades
        for r in self.db.conn.execute("SELECT id, nome FROM cidades").fetchall():
            self.cb_esc_cidade.addItem(r[1], r[0])

    def add_escala(self):
        bus_id = self.cb_esc_bus.currentData()
        fr_id = self.cb_esc_frente.currentData()
        cid_id = self.cb_esc_cidade.currentData()
        h_ida = self.te_ida.time().toString("HH:mm")
        h_volta = self.te_volta.time().toString("HH:mm")

        if not bus_id or not fr_id or not cid_id: return

        try:
            self.db.conn.execute("INSERT INTO escala_viagem (onibus_id, frente_id, cidade_id, hora_ida, hora_volta) VALUES (?,?,?,?,?)",
                                 (bus_id, fr_id, cid_id, h_ida, h_volta))
            self.db.conn.commit(); self.carregar_escala()
        except Exception as e: QtWidgets.QMessageBox.critical(self, "Erro", str(e))

    def carregar_escala(self):
        sql = """
            SELECT e.id, frota.numero, fr.nome, cid.nome, e.hora_ida, e.hora_volta
            FROM escala_viagem e
            JOIN frota ON e.onibus_id = frota.id
            JOIN frentes fr ON e.frente_id = fr.id
            JOIN cidades cid ON e.cidade_id = cid.id
        """
        self._load_table(self.tb_escala, sql)

    # ==========================
    # UTILITÁRIOS
    # ==========================
    def _criar_tabela(self, headers):
        t = QtWidgets.QTableWidget(); t.setColumnCount(len(headers)); t.setHorizontalHeaderLabels(headers)
        configure_table(t, stretch_last=True)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        return t

    def _load_table(self, table, sql, params=()):
        rows = self.db.conn.execute(sql, params).fetchall()
        table.setRowCount(0); table.setSortingEnabled(False)
        for r, row in enumerate(rows):
            table.insertRow(r)
            for c, val in enumerate(row):
                texto = str(val)
                item = QtWidgets.QTableWidgetItem(texto)
                item.setToolTip(texto)
                table.setItem(r, c, item)
        table.setSortingEnabled(True)
