from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from app_logging import get_logger


LOGGER = get_logger(__name__)

try:
    import qtawesome as qta

    ICONS_AVAILABLE = True
except Exception:
    qta = None
    ICONS_AVAILABLE = False


_ICON_CACHE = {}


def get_icon(nome_icone: str, cor: str = "white"):
    if not ICONS_AVAILABLE or not nome_icone:
        return None
    key = (str(nome_icone), str(cor))
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    icon = qta.icon(nome_icone, color=cor)
    _ICON_CACHE[key] = icon
    return icon


def aplicar_icone(botao, nome_icone, cor="white", size=18):
    icon = get_icon(nome_icone, cor=cor)
    if icon is None:
        return False
    botao.setIcon(icon)
    botao.setIconSize(QtCore.QSize(int(size), int(size)))
    return True


def set_state(widget: QtWidgets.QWidget, state: str = ""):
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def configure_table(
    table: QtWidgets.QTableWidget | QtWidgets.QTableView,
    *,
    stretch_last: bool = False,
    alternating: bool = True,
) -> None:
    table.setAlternatingRowColors(alternating)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setWordWrap(False)
    table.setMouseTracking(True)
    table.setShowGrid(True)
    table.setFocusPolicy(QtCore.Qt.NoFocus)
    table.setCornerButtonEnabled(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setStretchLastSection(stretch_last)


def apply_theme(app_or_widget):
    if app_or_widget is None:
        LOGGER.warning("apply_theme chamado antes da criacao da QApplication")
        return False

    try:
        app_or_widget.setStyleSheet(PREMIUM_STYLESHEET)
        LOGGER.info("Tema visual aplicado com sucesso")
        return True
    except Exception:
        LOGGER.exception("Erro ao aplicar tema visual")
        return False


class StatusDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter, option, index):
        texto = index.data()
        texto_upper = str(texto).upper() if texto else ""

        cor_fundo = None
        if texto_upper == "ATIVO":
            cor_fundo = QtGui.QColor("#2e8b57")
        elif texto_upper in ["MANUTENCAO", "MANUTENÇÃO", "QUEBRADO"]:
            cor_fundo = QtGui.QColor("#b4493e")
        elif texto_upper == "DUPLICADO":
            cor_fundo = QtGui.QColor("#bb8740")

        if cor_fundo:
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            rect = option.rect.adjusted(4, 4, -4, -4)
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect), 7, 7)
            painter.fillPath(path, cor_fundo)
            painter.setPen(QtGui.QColor("white"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(rect, QtCore.Qt.AlignCenter, str(texto))
            painter.restore()
        else:
            super().paint(painter, option, index)


PREMIUM_STYLESHEET = """
* {
    font-family: "Segoe UI", "Roboto", sans-serif;
}

QWidget {
    background-color: #0d1116;
    color: #d8dde4;
    font-size: 11pt;
}

QWidget#PageRoot {
    background-color: #0d1116;
}

QToolTip {
    background-color: #0a0e13;
    color: #eef2f6;
    border: 1px solid #334154;
    padding: 8px;
    border-radius: 6px;
}

QFrame#Card {
    background-color: #121821;
    border: 1px solid #253243;
    border-radius: 14px;
    margin: 5px;
}

QFrame#ToolbarCard,
QFrame#SummaryCard,
QFrame#MetricCard,
QFrame#ChartCard,
QFrame#SummaryHeroCard {
    background-color: #121821;
    border: 1px solid #253243;
    border-radius: 16px;
}

QFrame#CardSoft {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #111925, stop:1 #0f141c);
    border: 1px solid #223041;
    border-radius: 16px;
}

QFrame#ToolbarCard {
    background-color: #111821;
}

QFrame#SummaryCard {
    background-color: #101722;
}

QFrame#MetricCard {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #121b27, stop:1 #0f151d);
    border: 1px solid #263648;
}

QFrame#ChartCard {
    background-color: #121821;
}

QFrame#SummaryHeroCard {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #121a25, stop:1 #0f151d);
}

QLabel#WindowTitle {
    font-size: 16pt;
    font-weight: 800;
    color: #f2f5f8;
}

QLabel#WindowSubtitle {
    font-size: 9pt;
    color: #8ea1b5;
}

QLabel#PageTitle {
    font-size: 15pt;
    font-weight: 800;
    color: #f2f5f8;
}

QLabel#PageSubtitle {
    font-size: 9pt;
    color: #8fa2b6;
}

QLabel#SectionTitle {
    font-size: 11pt;
    font-weight: 800;
    color: #eef2f6;
}

QLabel#SectionHint {
    font-size: 9pt;
    color: #91a5b8;
}

QLabel#FormLabel {
    font-size: 8.8pt;
    font-weight: 700;
    color: #94a8bc;
    letter-spacing: 0.4px;
}

QLabel#SummaryBadge {
    font-size: 9pt;
    font-weight: 700;
    color: #d8dde4;
    background-color: #0f151d;
    border: 1px solid #223143;
    border-radius: 10px;
    padding: 5px 10px;
}

QLabel#ChartTitle {
    font-size: 12pt;
    font-weight: 800;
    color: #eef2f6;
}

QLabel#SplashSubtitle {
    color: #7ec8e3;
    font-weight: 700;
}

QLabel#StatusChipOnline, QLabel#StatusChipOffline, QLabel#StatusChipNeutral,
QLabel#StatusMetricGreen, QLabel#StatusMetricBlue {
    font-weight: 700;
    border-radius: 9px;
    padding: 3px 9px;
}

QLabel#StatusChipOnline {
    background-color: #143928;
    color: #8fddb0;
    border: 1px solid #1f6944;
}

QLabel#StatusChipOffline {
    background-color: #412411;
    color: #ffc48a;
    border: 1px solid #8d532a;
}

QLabel#StatusChipNeutral {
    background-color: #142334;
    color: #9bc4f0;
    border: 1px solid #315377;
}

QLabel#StatusMetricGreen {
    background-color: #10271b;
    color: #89d2a6;
    border: 1px solid #24593b;
    margin-left: 6px;
}

QLabel#StatusMetricBlue {
    background-color: #112235;
    color: #8bbbe9;
    border: 1px solid #264f76;
    margin-left: 6px;
}

QGroupBox {
    border: 1px solid #263547;
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 10px;
    background-color: #121821;
    font-weight: 700;
    color: #d8dde4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    background-color: #121821;
    padding: 0 5px 0 5px;
    color: #eef2f6;
}

QTabWidget::pane {
    border: 1px solid #243446;
    background-color: #121821;
    border-radius: 14px;
    margin-top: -1px;
}

QTabBar::tab {
    background-color: #10161f;
    color: #7b8fa2;
    padding: 10px 18px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 4px;
    font-weight: 700;
    border: 1px solid #223142;
    border-bottom: none;
}

QTabBar::tab:hover {
    color: #bfd0e2;
    background-color: #141d28;
}

QTabBar::tab:selected {
    background-color: #162231;
    color: #eef2f6;
    border: 1px solid #42688d;
}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit {
    padding: 4px 10px;
    border: 1px solid #243243;
    border-radius: 10px;
    background-color: #0b1118;
    color: #e2e5ea;
    font-size: 10pt;
    min-height: 30px;
    selection-background-color: #30597b;
    selection-color: #ffffff;
}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #6ca6d8;
    background-color: #0a1017;
}

QLineEdit#NoteNumberInput {
    color: #8fb4ff;
    border: 1px solid #4c70c3;
    background-color: #0d1522;
    font-size: 15pt;
    font-weight: 800;
    min-height: 38px;
}

QLineEdit#NoteNumberInput:focus {
    border: 1px solid #7aa9ff;
    background-color: #101a2b;
}

QLineEdit[state="error"], QComboBox[state="error"], QDateEdit[state="error"],
QTimeEdit[state="error"], QTextEdit[state="error"], QPlainTextEdit[state="error"] {
    border: 1px solid #d05a5a;
    background-color: #1a1010;
}

QLineEdit[state="ok"], QComboBox[state="ok"], QDateEdit[state="ok"],
QTimeEdit[state="ok"], QTextEdit[state="ok"], QPlainTextEdit[state="ok"] {
    border: 1px solid #6bbf7a;
    background-color: #101a12;
}

QLineEdit[state="warn"], QComboBox[state="warn"], QDateEdit[state="warn"],
QTimeEdit[state="warn"], QTextEdit[state="warn"], QPlainTextEdit[state="warn"] {
    border: 1px solid #caa64a;
    background-color: #19150c;
}

QLineEdit[state="locked"], QComboBox[state="locked"], QDateEdit[state="locked"],
QTimeEdit[state="locked"], QTextEdit[state="locked"], QPlainTextEdit[state="locked"] {
    border: 1px solid #2b3b4c;
    background-color: #10161f;
    color: #65788d;
}

QCheckBox {
    color: #d8dde4;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #243243;
    border-radius: 4px;
    background-color: #0b1118;
}

QCheckBox::indicator:checked {
    background-color: #6ca6d8;
    border: 2px solid #6ca6d8;
    image: none;
}

QPushButton {
    font-weight: 700;
    border-radius: 10px;
    padding: 8px 16px;
    font-size: 10pt;
    border: 1px solid transparent;
    min-height: 36px;
}

QPushButton:hover {
    border: 1px solid #4a617a;
}

QPushButton:pressed {
    padding-top: 12px;
    padding-bottom: 8px;
}

QPushButton:disabled {
    background-color: #24262d;
    color: #7a818c;
    border: 1px solid #2a2d34;
}

QPushButton#PrimaryButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #31577b, stop:1 #203b54);
    color: #eef2f6;
    border: 1px solid #47729a;
}

QPushButton#PrimaryButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3c678f, stop:1 #264866);
}

QPushButton#SecondaryButton {
    background-color: #151d28;
    color: #d8dde4;
    border: 1px solid #263547;
}

QPushButton#SecondaryButton:hover {
    background-color: #1b2532;
}

QPushButton#QuickFilterButton {
    background-color: #111821;
    color: #c7d3df;
    border: 1px solid #253648;
    min-height: 34px;
    padding: 7px 14px;
}

QPushButton#QuickFilterButton:hover {
    background-color: #162130;
    border: 1px solid #395776;
}

QPushButton#SuccessButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2e7254, stop:1 #1f513b);
    color: #eef2f6;
    border: 1px solid #2f7a59;
}

QPushButton#SuccessButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #388661, stop:1 #245d45);
}

QPushButton#DangerButton {
    background-color: #6a2d2d;
    color: #f3f3f3;
    border: 1px solid #8a4646;
}

QPushButton#DangerButton:hover {
    background-color: #7b3737;
}

QPushButton#PurpleButton {
    background-color: #2a314f;
    color: #eef2f6;
    border: 1px solid #465989;
}

QPushButton#PurpleButton:hover {
    background-color: #324064;
}

QTableWidget, QTableView {
    background-color: #111720;
    alternate-background-color: #0e141c;
    color: #e2e5ea;
    gridline-color: #233142;
    border: 1px solid #233142;
    selection-background-color: #244561;
    selection-color: #ffffff;
    border-radius: 12px;
}

QHeaderView::section {
    background-color: #0d131b;
    padding: 9px 8px;
    border: none;
    border-bottom: 2px solid #31495f;
    font-weight: 700;
    color: #9eb4c7;
    text-transform: uppercase;
    font-size: 9pt;
}

QTableView::item, QTableWidget::item {
    padding: 6px;
}

QLabel#KPI {
    font-size: 28pt;
    font-weight: 800;
    color: #eff4f8;
}

QLabel#KPITitle {
    font-size: 11pt;
    font-weight: 700;
    color: #86a0b7;
    text-transform: uppercase;
}

QProgressBar {
    border: 2px solid #243243;
    border-radius: 8px;
    text-align: center;
    background-color: #111720;
    color: #eef2f6;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5f95c6, stop:1 #77c59a);
    border-radius: 6px;
}

QScrollBar:vertical {
    background: #111720;
    width: 14px;
    border-radius: 7px;
}

QScrollBar::handle:vertical {
    background: #2c3d50;
    border-radius: 7px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #3d5872;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QStatusBar {
    background-color: #0f151d;
    color: #9eb4c7;
    border-top: 1px solid #243243;
}

QMenu {
    background-color: #121821;
    color: #d8dde4;
    border: 1px solid #243243;
    padding: 6px;
}

QMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}

QMenu::item:selected {
    background-color: #20364b;
}

QWidget#TickerBar {
    background-color: #0f151d;
    border-top: 1px solid #203a50;
}

QSplashScreen {
    background: transparent;
}
"""

AGRICOLA_STANDARD_OVERRIDES = """
/* Operacoes Agricolas visual foundation. Keep this at the end so older screens
   inherit the standard without changing their business code. */
QWidget {
    background-color: #f6f7f3;
    color: #26322f;
    font-size: 10pt;
}

QWidget#PageRoot {
    background-color: #f6f7f3;
}

QToolTip {
    background-color: #26322f;
    color: #ffffff;
    border: 1px solid #3d4a45;
    padding: 8px;
    border-radius: 6px;
}

QFrame#Card,
QFrame#ToolbarCard,
QFrame#SummaryCard,
QFrame#MetricCard,
QFrame#ChartCard,
QFrame#SummaryHeroCard,
QFrame#CardSoft {
    background-color: #ffffff;
    border: 1px solid #d9e1d8;
    border-radius: 8px;
}

QLabel#WindowTitle,
QLabel#PageTitle,
QLabel#ChartTitle {
    color: #1f342d;
}

QLabel#WindowSubtitle,
QLabel#PageSubtitle,
QLabel#SectionHint {
    color: #657268;
}

QLabel#SectionTitle,
QGroupBox::title {
    color: #26322f;
}

QLabel#FormLabel {
    color: #56645d;
    letter-spacing: 0px;
}

QLabel#SummaryBadge,
QLabel#StatusChipNeutral,
QLabel#StatusMetricBlue {
    color: #31576f;
    background-color: #eef5f8;
    border: 1px solid #c8d8df;
    border-radius: 8px;
}

QLabel#StatusChipOnline,
QLabel#StatusMetricGreen {
    color: #1f5f40;
    background-color: #e7f4eb;
    border: 1px solid #b8d7c0;
    border-radius: 8px;
}

QLabel#StatusChipOffline {
    color: #8a530e;
    background-color: #fff3d9;
    border: 1px solid #e4c178;
    border-radius: 8px;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d9e1d8;
    border-radius: 8px;
    color: #26322f;
    margin-top: 0px;
    padding-top: 0px;
}

QGroupBox::title {
    background-color: #ffffff;
}

QGroupBox#LaunchGroup,
QGroupBox#CargoGroup {
    border-left: 3px solid #7f8d83;
}

QGroupBox#CargoGroup[locked="true"] {
    border-left: 3px solid #26734d;
    background-color: #fbfdfb;
}

QTabWidget::pane {
    border: 1px solid #d9e1d8;
    background-color: #ffffff;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #eef2ec;
    color: #4d5b52;
    border: 1px solid #d9e1d8;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 9px 16px;
    min-width: 112px;
}

QTabBar::tab:hover {
    background-color: #e3ebdf;
    color: #26322f;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #1f342d;
    border: 1px solid #26734d;
}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit {
    padding: 6px 10px;
    border: 1px solid #c8d3c7;
    border-radius: 8px;
    background-color: #ffffff;
    color: #26322f;
    selection-background-color: #26734d;
    selection-color: #ffffff;
}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QTextEdit:focus, QPlainTextEdit:focus {
    border: 2px solid #26734d;
    background-color: #fbfdfb;
}

QLineEdit#NoteNumberInput {
    color: #1f5f40;
    border: 1px solid #26734d;
    background-color: #f6fbf7;
}

QLineEdit#NoteNumberInput:focus {
    color: #1f5f40;
    border: 2px solid #26734d;
    background-color: #fbfdfb;
}

QLineEdit[state="error"], QComboBox[state="error"], QDateEdit[state="error"],
QTimeEdit[state="error"], QTextEdit[state="error"], QPlainTextEdit[state="error"] {
    border: 1px solid #b6463a;
    background-color: #fff4f1;
}

QLineEdit[state="ok"], QComboBox[state="ok"], QDateEdit[state="ok"],
QTimeEdit[state="ok"], QTextEdit[state="ok"], QPlainTextEdit[state="ok"] {
    border: 1px solid #26734d;
    background-color: #f2fbf5;
}

QLineEdit[state="warn"], QComboBox[state="warn"], QDateEdit[state="warn"],
QTimeEdit[state="warn"], QTextEdit[state="warn"], QPlainTextEdit[state="warn"] {
    border: 1px solid #c99a32;
    background-color: #fff8e8;
}

QLineEdit[state="locked"], QComboBox[state="locked"], QDateEdit[state="locked"],
QTimeEdit[state="locked"], QTextEdit[state="locked"], QPlainTextEdit[state="locked"] {
    border: 1px solid #d9e1d8;
    background-color: #eef2ec;
    color: #6d776f;
}

QCheckBox {
    color: #26322f;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #c8d3c7;
    border-radius: 4px;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #26734d;
    border: 2px solid #26734d;
}

QPushButton {
    border-radius: 8px;
    padding: 8px 14px;
    color: #26322f;
}

QPushButton#PrimaryButton,
QPushButton#SuccessButton {
    background-color: #26734d;
    color: #ffffff;
    border: 1px solid #26734d;
    font-weight: 700;
}

QPushButton#PrimaryButton:hover,
QPushButton#SuccessButton:hover {
    background-color: #1f5f40;
    border-color: #1f5f40;
}

QPushButton#SecondaryButton,
QPushButton#QuickFilterButton,
QPushButton#PurpleButton {
    background-color: #ffffff;
    color: #31576f;
    border: 1px solid #c8d3c7;
    font-weight: 700;
}

QPushButton#SecondaryButton:hover,
QPushButton#QuickFilterButton:hover,
QPushButton#PurpleButton:hover {
    background-color: #eef2ec;
    border-color: #b7c7b5;
}

QPushButton#DangerButton {
    background-color: #b6463a;
    color: #ffffff;
    border: 1px solid #b6463a;
}

QPushButton#DangerButton:hover {
    background-color: #9d372e;
    border-color: #9d372e;
}

QPushButton:disabled {
    background-color: #eef2ec;
    color: #97a197;
    border: 1px solid #d9e1d8;
}

QTableWidget, QTableView {
    background-color: #ffffff;
    alternate-background-color: #f8faf7;
    color: #26322f;
    gridline-color: #e6ece4;
    border: 1px solid #d9e1d8;
    selection-background-color: #dcefe3;
    selection-color: #1f342d;
    border-radius: 8px;
}

QHeaderView::section {
    background-color: #eef2ec;
    color: #4d5b52;
    border: none;
    border-bottom: 1px solid #d9e1d8;
    padding: 8px;
}

QLabel#KPI {
    color: #1f342d;
    font-size: 26pt;
}

QLabel#KPITitle {
    color: #657268;
    font-size: 9pt;
}

QProgressBar {
    border: 1px solid #c8d3c7;
    border-radius: 8px;
    background-color: #eef2ec;
    color: #26322f;
}

QProgressBar::chunk {
    background-color: #26734d;
    border-radius: 7px;
}

QStatusBar {
    background-color: #ffffff;
    color: #657268;
    border-top: 1px solid #d9e1d8;
}

QScrollArea#PageScroll {
    background-color: #f6f7f3;
    border: none;
}

QScrollBar:vertical {
    background: #eef2ec;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #b8c8b7;
    border-radius: 6px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #98ad97;
}

QMenu {
    background-color: #ffffff;
    color: #26322f;
    border: 1px solid #d9e1d8;
}

QMenu::item:selected {
    background-color: #dcefe3;
}

QWidget#TickerBar {
    background-color: #ffffff;
    border-top: 1px solid #d9e1d8;
}
"""

PREMIUM_STYLESHEET = PREMIUM_STYLESHEET + AGRICOLA_STANDARD_OVERRIDES
