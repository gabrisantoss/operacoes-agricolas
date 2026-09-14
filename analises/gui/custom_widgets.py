from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtCore import Qt, pyqtSignal
from core.settings import add_word_to_dictionary, get_custom_dictionary_words

try:
    from spellchecker import SpellChecker
    SPELLCHECKER_AVAILABLE = True
except ImportError:
    SPELLCHECKER_AVAILABLE = False

class SmartLineEdit(QLineEdit):
    """
    QLineEdit com verificação ortográfica opcional.
    Se o módulo spellchecker não estiver disponível,
    o comportamento cai para um QLineEdit normal.
    """
    dictionary_updated = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("spellcheckState", "normal")
        if SPELLCHECKER_AVAILABLE:
            self.spell = SpellChecker(language='pt')
            self.load_custom_dictionary()
            self.textChanged.connect(self.check_spelling)
            self.dictionary_updated.connect(self.on_dictionary_update)

    def _set_spellcheck_state(self, state):
        if self.property("spellcheckState") == state:
            return
        self.setProperty("spellcheckState", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def load_custom_dictionary(self):
        """
        Carrega palavras adicionais do dicionário customizado.
        """
        if not SPELLCHECKER_AVAILABLE:
            return
        custom_words = get_custom_dictionary_words()
        self.spell.word_frequency.load_words(custom_words)

    def on_dictionary_update(self):
        """
        Recarrega o dicionário customizado quando atualizado.
        """
        if not SPELLCHECKER_AVAILABLE:
            return
        self.load_custom_dictionary()
        self.check_spelling(self.text())

    def check_spelling(self, text):
        """
        Verifica a ortografia do último termo digitado.
        Realça o campo em vermelho se a palavra estiver incorreta.
        """
        if not SPELLCHECKER_AVAILABLE:
            return

        words = text.split()
        if not text.endswith(' ') and words:
            last_word = words[-1]
            if last_word and self.spell.unknown([last_word.lower()]):
                self._set_spellcheck_state("invalid")
            else:
                self._set_spellcheck_state("normal")
        else:
            self._set_spellcheck_state("normal")

    def contextMenuEvent(self, event):
        """
        Adiciona opção de 'Adicionar ao Dicionário' ao menu de contexto
        quando o corretor ortográfico detecta uma palavra desconhecida.
        """
        menu = self.createStandardContextMenu()
        if SPELLCHECKER_AVAILABLE:
            cursor_pos = self.cursorPosition()
            text = self.text()
            start = text.rfind(' ', 0, cursor_pos) + 1
            end = text.find(' ', cursor_pos)
            if end == -1:
                end = len(text)

            word_under_cursor = text[start:end]
            if word_under_cursor and self.spell.unknown([word_under_cursor.lower()]):
                menu.addSeparator()
                action = menu.addAction(f"Adicionar '{word_under_cursor.upper()}' ao Dicionário")
                action.triggered.connect(lambda: self.add_word(word_under_cursor))

        menu.exec_(event.globalPos())

    def add_word(self, word):
        """
        Adiciona uma nova palavra ao dicionário customizado
        e recarrega o corretor ortográfico.
        """
        add_word_to_dictionary(word)
        if SPELLCHECKER_AVAILABLE:
            self.load_custom_dictionary()
            self.check_spelling(self.text())
