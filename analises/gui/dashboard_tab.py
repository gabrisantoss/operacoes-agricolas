from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                           QComboBox, QGroupBox, QMessageBox, QScrollArea, QDateEdit, QSizePolicy)
from PyQt5.QtCore import Qt, QDate, QSettings
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from reporting.dashboard_report import (
    build_dashboard_context,
    generate_dashboard_report_pdf,
    render_dashboard_figure,
)
from core.database_manager import DatabaseManager

try:
    from core.settings import get_setting
except ImportError:
    def get_setting(key, default):
        if key == 'tempo_operacao_minutos':
            return '480'
        if key == 'report_default_path':
            return '.'
        return default

class DashboardTab(QWidget):

    def __init__(self):
        super().__init__()
        self.settings = QSettings("AgriSolutions", "AgriDashboardApp")
        self.figure = plt.figure(figsize=(18, 8), tight_layout=True)
        self.figure.set_facecolor('#ffffff')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(460)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.main_tab_layout = QVBoxLayout(self)
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.scroll_content_widget = QWidget()
        self.scroll_content_layout = QVBoxLayout(self.scroll_content_widget)

        title_label = QLabel("DASHBOARD DE OPERAÇÕES E COLHEITA")
        title_label.setObjectName("SectionTitle")
        title_label.setAlignment(Qt.AlignCenter)
        self.scroll_content_layout.addWidget(title_label)

        filter_group_box = QGroupBox("Filtros do Dashboard")
        filter_layout = QHBoxLayout(filter_group_box)

        filter_layout.addWidget(QLabel("Data Inicial:"))
        self.date_start = QDateEdit(QDate.currentDate().addDays(-30))
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("dd/MM/yyyy")
        filter_layout.addWidget(self.date_start)

        filter_layout.addWidget(QLabel("Data Final:"))
        self.date_end = QDateEdit(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("dd/MM/yyyy")
        filter_layout.addWidget(self.date_end)

        filter_layout.addWidget(QLabel("Frente:"))
        self.filter_frente_combo = QComboBox()
        self.filter_frente_combo.addItem("Todas")
        filter_layout.addWidget(self.filter_frente_combo)

        filter_layout.addWidget(QLabel("Frota:"))
        self.filter_frota_combo = QComboBox()
        self.filter_frota_combo.addItem("Todas")
        filter_layout.addWidget(self.filter_frota_combo)

        filter_layout.addWidget(QLabel("Comparar Período:"))
        self.comparison_period_combo = QComboBox()
        self.comparison_period_combo.addItems([
            "Nenhuma Comparação", "Mês Passado", "Trimestre Passado", "Ano Passado"
        ])
        filter_layout.addWidget(self.comparison_period_combo)

        btn_apply_filters = QPushButton("Aplicar Filtros")
        btn_apply_filters.setObjectName("PrimaryButton")
        btn_apply_filters.clicked.connect(self.load_dashboard_data)
        filter_layout.addWidget(btn_apply_filters)

        btn_generate_pdf = QPushButton("Gerar PDF do Dashboard")
        btn_generate_pdf.setObjectName("ExportButton")
        btn_generate_pdf.clicked.connect(self.generate_dashboard_pdf)
        filter_layout.addWidget(btn_generate_pdf)

        self.scroll_content_layout.addWidget(filter_group_box)

        # Container para gráficos. Fica acima das métricas para usar a largura inteira da tela.
        charts_container = QGroupBox("Gráficos")
        charts_layout = QVBoxLayout(charts_container)
        charts_layout.setContentsMargins(10, 14, 10, 10)
        charts_layout.setSpacing(6)
        charts_layout.addWidget(self.toolbar)
        charts_layout.addWidget(self.canvas, 1)
        self.scroll_content_layout.addWidget(charts_container, 1)

        # Grupo de Métricas
        metrics_group_box = QGroupBox("Métricas Chave")
        metrics_layout = QGridLayout(metrics_group_box)
        metrics_layout.setHorizontalSpacing(18)
        metrics_layout.setVerticalSpacing(10)

        def add_metric_section(row, column, title, labels):
            section_layout = QVBoxLayout()
            section_layout.setSpacing(4)
            section_title = QLabel(title)
            section_title.setObjectName("MetricSectionTitle")
            section_layout.addWidget(section_title)
            for label in labels:
                label.setWordWrap(True)
                section_layout.addWidget(label)
            section_layout.addStretch(1)
            metrics_layout.addLayout(section_layout, row, column)

        self.label_total_registros = QLabel("Total de Registros: -")
        self.label_media_eficiencia = QLabel("Eficiência Média: -%")
        self.label_area_total_colhida = QLabel("Área Total Colhida: - ha")
        self.label_produtividade_media = QLabel("Produtividade Média: - ton/ha")
        self.label_produtividade_total_colhida = QLabel("Produtividade Total: - ton")

        self.label_utilizacao_equipamentos = QLabel("Disponibilidade de Equipamentos: -%")
        self.label_eficiencia_colhedora = QLabel("Eficiência Frota (Colhedora): -%")
        self.label_eficiencia_transbordo = QLabel("Eficiência Frota (Transbordo): -%")

        self.label_tempo_medio_parada = QLabel("Maior Tempo Médio de Parada: -")
        self.label_percentual_tempo_parado = QLabel("Maior % Tempo Parado por Motivo: -")

        self.label_eficiencia_por_turno = QLabel("Eficiência Média por Turno: -%")
        self.label_desvio_padrao_eficiencia = QLabel("Desvio Padrão da Eficiência: -")

        self.label_top3_frentes = QLabel("Top 3 Frentes Mais Produtivas: -")
        self.label_turno_mais_eficiente = QLabel("Turno Mais Eficiente: -")
        self.label_turno_menos_eficiente = QLabel("Turno Menos Eficiente: -")

        add_metric_section(0, 0, "Visão Geral", [
            self.label_total_registros,
            self.label_media_eficiencia,
            self.label_area_total_colhida,
            self.label_produtividade_media,
            self.label_produtividade_total_colhida,
        ])
        add_metric_section(0, 1, "Desempenho da Frota", [
            self.label_utilizacao_equipamentos,
            self.label_eficiencia_colhedora,
            self.label_eficiencia_transbordo,
        ])
        add_metric_section(0, 2, "Análise de Paradas", [
            self.label_tempo_medio_parada,
            self.label_percentual_tempo_parado,
        ])
        add_metric_section(1, 0, "Tendências e Variações", [
            self.label_eficiencia_por_turno,
            self.label_desvio_padrao_eficiencia,
        ])
        add_metric_section(1, 1, "Ranking", [
            self.label_top3_frentes,
            self.label_turno_mais_eficiente,
            self.label_turno_menos_eficiente,
        ])
        metrics_layout.setColumnStretch(0, 1)
        metrics_layout.setColumnStretch(1, 1)
        metrics_layout.setColumnStretch(2, 1)

        self.scroll_content_layout.addWidget(metrics_group_box)

        self.populate_filter_comboboxes()

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content_widget)

        self.main_tab_layout.addWidget(self.scroll_area)

    def generate_dashboard_pdf(self):
        QApplication.setOverrideCursor(Qt.BusyCursor)
        try:
            start_date_str = self.date_start.date().toString("dd-MM-yyyy")
            end_date_str = self.date_end.date().toString("dd-MM-yyyy")
            frente = self.filter_frente_combo.currentText()
            frota = self.filter_frota_combo.currentText()
            comparison = self.comparison_period_combo.currentText()
            report_path = get_setting('report_default_path', '.') or '.'

            generated_filename = generate_dashboard_report_pdf(
                start_date=start_date_str,
                end_date=end_date_str,
                frente=None if frente == "Todas" else frente,
                frota=None if frota == "Todas" else frota,
                comparison_type=comparison,
                output_path=report_path,
            )

            if generated_filename:
                QMessageBox.information(
                    self, "Sucesso",
                    f"Relatório do Dashboard gerado com sucesso!\n\nArquivo salvo como:\n{generated_filename}"
                )
            else:
                QMessageBox.warning(
                    self, "Aviso",
                    "Não foi possível gerar o relatório. Verifique se há dados para o período selecionado."
                )

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Ocorreu um erro ao gerar o PDF do Dashboard:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def populate_filter_comboboxes(self):
        try:
            current_frente = self.filter_frente_combo.currentText() if hasattr(self, "filter_frente_combo") else "Todas"
            current_frota = self.filter_frota_combo.currentText() if hasattr(self, "filter_frota_combo") else "Todas"

            # Popula Frentes
            query_frentes = "SELECT DISTINCT Frente FROM RELATORIO_OPERACAO_DIARIA ORDER BY Frente"
            frentes = [item[0] for item in DatabaseManager.execute_select(query_frentes) if item[0]]

            self.filter_frente_combo.clear()
            self.filter_frente_combo.addItem("Todas")
            self.filter_frente_combo.addItems(frentes)
            if current_frente in ["Todas"] + frentes:
                self.filter_frente_combo.setCurrentText(current_frente)

            # Popula Frotas
            query_frotas = "SELECT DISTINCT Frota FROM RELATORIO_OPERACAO_DIARIA WHERE Frota IS NOT NULL ORDER BY Frota"
            frotas = [item[0] for item in DatabaseManager.execute_select(query_frotas) if item[0]]

            self.filter_frota_combo.clear()
            self.filter_frota_combo.addItem("Todas")
            self.filter_frota_combo.addItems(frotas)
            if current_frota in ["Todas"] + frotas:
                self.filter_frota_combo.setCurrentText(current_frota)

        except Exception as e:
            print(f"Erro ao popular comboboxes: {e}")

    def load_settings(self):
        # Carrega as configurações salvas, se houver
        start_date_str = self.settings.value("dashboard/start_date")
        end_date_str = self.settings.value("dashboard/end_date")

        start_date = (
            QDate.fromString(start_date_str, Qt.ISODate)
            if start_date_str else QDate.currentDate().addDays(-30)
        )
        end_date = (
            QDate.fromString(end_date_str, Qt.ISODate)
            if end_date_str else QDate.currentDate()
        )

        self.date_start.setDate(start_date)
        self.date_end.setDate(end_date)
        self.filter_frente_combo.setCurrentText(self.settings.value("dashboard/frente", "Todas"))
        self.filter_frota_combo.setCurrentText(self.settings.value("dashboard/frota", "Todas"))
        self.comparison_period_combo.setCurrentText(self.settings.value("dashboard/comparison", "Nenhuma Comparação"))

    def save_settings(self):
        # Salva os filtros atuais para a próxima vez que o programa abrir
        self.settings.setValue("dashboard/start_date", self.date_start.date().toString(Qt.ISODate))
        self.settings.setValue("dashboard/end_date", self.date_end.date().toString(Qt.ISODate))
        self.settings.setValue("dashboard/frente", self.filter_frente_combo.currentText())
        self.settings.setValue("dashboard/frota", self.filter_frota_combo.currentText())
        self.settings.setValue("dashboard/comparison", self.comparison_period_combo.currentText())

    def load_dashboard_data(self, show_empty_message=True):
        QApplication.setOverrideCursor(Qt.BusyCursor)
        self.save_settings()
        self.populate_filter_comboboxes()

        start_date_str = self.date_start.date().toString("dd-MM-yyyy")
        end_date_str = self.date_end.date().toString("dd-MM-yyyy")
        frente = self.filter_frente_combo.currentText()
        frota = self.filter_frota_combo.currentText()
        comparison_type = self.comparison_period_combo.currentText()

        frente_filter = frente if frente != "Todas" else None
        frota_filter = frota if frota != "Todas" else None

        current_data, op_data, _, comparison_data, _ = build_dashboard_context(
            start_date_str, end_date_str, frente_filter, frota_filter, comparison_type
        )

        if not current_data or current_data.get('total_registros', 0) == 0:
            if show_empty_message:
                QMessageBox.information(self, "Sem Dados", "Nenhum dado encontrado para os filtros selecionados.")
            self.figure.clear()
            self.canvas.draw()
            QApplication.restoreOverrideCursor()
            return

        # ATUALIZAÇÃO DAS LABELS DE MÉTRICAS
        self.label_total_registros.setText(f"Total de Registros: {current_data.get('total_registros', 0)}")
        self.label_media_eficiencia.setText(f"Eficiência Média: {current_data.get('media_eficiencia', 0):.2f}%")
        self.label_area_total_colhida.setText(f"Área Total Colhida: {current_data.get('area_total_colhida', 0):.2f} ha")

        produtividade_media = current_data.get('produtividade_media', 0)
        self.label_produtividade_media.setText(
            f"Produtividade Média: {produtividade_media:,.2f} ton/ha".replace(",", "X").replace(".", ",").replace("X", ".")
        )

        total_ton_colhida = current_data.get('total_ton_colhida', 0)
        self.label_produtividade_total_colhida.setText(
            f"Produtividade Total: {total_ton_colhida:,.2f} ton".replace(",", "X").replace(".", ",").replace("X", ".")
        )

        self.label_utilizacao_equipamentos.setText(
            f"Disponibilidade de Equipamentos: {current_data.get('utilizacao_equipamentos', 0):.2f}%"
        )
        self.label_eficiencia_colhedora.setText(
            f"Eficiência Frota (Colhedora): {current_data.get('eficiencia_colhedora', 0):.2f}%"
        )
        self.label_eficiencia_transbordo.setText(
            f"Eficiência Frota (Transbordo): {current_data.get('eficiencia_transbordo', 0):.2f}%"
        )
        self.label_desvio_padrao_eficiencia.setText(
            f"Desvio Padrão da Eficiência: {current_data.get('desvio_padrao_eficiencia', 0):.2f}"
        )

        # Análise de Paradas
        maior_tempo_medio_parada = current_data.get('maior_tempo_medio_parada', "Nenhum")
        maior_tempo_medio_parada_valor = current_data.get('maior_tempo_medio_parada_valor', 0) / 60  # Em horas
        self.label_tempo_medio_parada.setText(
            f"Maior Tempo Médio de Parada: {maior_tempo_medio_parada} ({maior_tempo_medio_parada_valor:.2f}h)"
        )

        maior_perc_tempo_parado = current_data.get('maior_percentual_tempo_parado', "Nenhum")
        maior_perc_tempo_parado_valor = current_data.get('maior_percentual_tempo_parado_valor', 0)
        self.label_percentual_tempo_parado.setText(
            f"Maior % Tempo Parado: {maior_perc_tempo_parado} ({maior_perc_tempo_parado_valor:.2f}%)"
        )

        # Análise de Turnos e Frentes
        eff_by_turn = current_data.get('efficiency_by_turn', {})
        turnos_text = []
        avg_eff_by_turn = {}

        for turno, data in eff_by_turn.items():
            if data['count'] > 0:
                avg_eff = data['total_eff'] / data['count']
                avg_eff_by_turn[turno] = avg_eff
                turnos_text.append(f"{turno}: {avg_eff:.2f}%")

        self.label_eficiencia_por_turno.setText(
            f"Eficiência Média por Turno: {'; '.join(turnos_text) if turnos_text else 'N/A'}"
        )

        if avg_eff_by_turn:
            turno_mais_eficiente = max(avg_eff_by_turn, key=avg_eff_by_turn.get)
            turno_menos_eficiente = min(avg_eff_by_turn, key=avg_eff_by_turn.get)
            self.label_turno_mais_eficiente.setText(
                f"Turno Mais Eficiente: {turno_mais_eficiente} ({avg_eff_by_turn[turno_mais_eficiente]:.2f}%)"
            )
            self.label_turno_menos_eficiente.setText(
                f"Turno Menos Eficiente: {turno_menos_eficiente} ({avg_eff_by_turn[turno_menos_eficiente]:.2f}%)"
            )
        else:
            self.label_turno_mais_eficiente.setText("Turno Mais Eficiente: N/A")
            self.label_turno_menos_eficiente.setText("Turno Menos Eficiente: N/A")

        prod_by_frente = current_data.get('productivity_by_frente', {})
        sorted_frentes = sorted(prod_by_frente.items(), key=lambda item: item[1]['total_ton'], reverse=True)
        top3_frentes = [f[0] for f in sorted_frentes[:3]]
        self.label_top3_frentes.setText(f"Top 3 Frentes Mais Produtivas: {', '.join(top3_frentes) if top3_frentes else 'N/A'}")

        render_dashboard_figure(
            self.figure,
            current_data,
            op_data,
            start_date_str,
            end_date_str,
            comparison_type=comparison_type,
            comparison_data=comparison_data,
            dark_theme=False,
        )
        self.canvas.draw()

        QApplication.restoreOverrideCursor()
