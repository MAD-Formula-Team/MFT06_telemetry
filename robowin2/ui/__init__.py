"""Capa de presentación PySide6 de ROBOWIN 2."""
import os

# Forzar el binding correcto de pyqtgraph aunque PyQt6 (ROBOWIN 1) esté instalado
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
