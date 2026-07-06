"""Rutas portables Windows/Linux.

Los datos (logs .db, config) van SIEMPRE al directorio de datos del usuario,
nunca junto al código ni a carpetas sincronizadas (OneDrive ya nos ha
revertido archivos a mitad de sesión).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

APP_DIR_NAME = "ROBOWIN2"


def data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    """Un archivo de log por día."""
    return data_dir() / f"robowin_{date.today():%Y%m%d}.db"


def find_dbc() -> Path | None:
    """Busca mft06.dbc, por prioridad:

    1. Junto al ejecutable (permite actualizar el DBC sin recompilar)
    2. Embebido en el paquete PyInstaller (_MEIPASS)
    3. robowin2/assets (ejecución desde código)
    4. UI/ legado (repo de desarrollo)
    """
    here = Path(__file__).resolve().parent
    candidates: list[Path | None] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "mft06.dbc")
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            candidates.append(Path(bundle) / "mft06.dbc")
    candidates.append(here / "assets" / "mft06.dbc")
    candidates.append(here.parent / "UI" / "mft06.dbc")

    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return None
