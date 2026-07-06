#!/usr/bin/env bash
# Genera el binario Linux de ROBOWIN 2.
# Requisitos: pip install pyinstaller (y requirements.txt instalado)
# Resultado: robowin2/dist/ROBOWIN2 (autocontenido)
#
# Notas:
# - El DBC va embebido; un mft06.dbc junto al binario tiene prioridad.
# - Los logs .db van a ~/.local/share/ROBOWIN2.
# - Para leer el puerto serie: sudo usermod -aG dialout $USER (cerrar sesión y volver).
set -euo pipefail
cd "$(dirname "$0")/.."

python -m PyInstaller --noconfirm --onefile --windowed --name ROBOWIN2 \
    --paths . \
    --distpath robowin2/dist \
    --workpath robowin2/build \
    --specpath robowin2 \
    --add-data "assets/mft06.dbc:." \
    --exclude-module PyQt5 \
    --exclude-module PyQt6 \
    --exclude-module matplotlib \
    --exclude-module tkinter \
    robowin2/main.py

echo "Binario en robowin2/dist/ROBOWIN2"
