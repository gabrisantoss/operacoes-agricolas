# main.py
import sys
import matplotlib
from PyQt5.QtWidgets import QApplication

matplotlib.use("Qt5Agg")

from core.database import setup_main_database
from core.settings import setup_settings_database
from gui.main_window import App
#from core.fleet_management import populate_initial_fleets

if __name__ == "__main__":
    app = QApplication(sys.argv)

    setup_main_database()
    setup_settings_database()

    # Lembrete: Descomente a linha abaixo para popular o banco de dados
    # pela primeira vez ou após zerá-lo. Depois, comente novamente.
    # populate_initial_fleets()

    main_app_window = App()
    main_app_window.show()

    sys.exit(app.exec_())
