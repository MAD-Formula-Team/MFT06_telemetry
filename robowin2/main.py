"""Punto de entrada de ROBOWIN 2: `python -m robowin2.main`."""
from __future__ import annotations

import sys


def main() -> int:
    from robowin2 import paths

    dbc = paths.find_dbc()
    if dbc is None:
        print("ERROR: no se encontró mft06.dbc (junto al ejecutable, en robowin2/assets o en UI/)")
        return 1

    # El orden importa: PySide6 debe importarse antes que pyqtgraph
    from PySide6.QtWidgets import QApplication

    from robowin2.app_context import AppContext
    from robowin2.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    ctx = AppContext(str(dbc))
    window = MainWindow(ctx)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
