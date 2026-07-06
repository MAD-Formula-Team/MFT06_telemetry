# Genera el ejecutable de Windows de ROBOWIN 2.
# Requisitos: pip install pyinstaller (y requirements.txt instalado)
# Resultado: robowin2\dist\ROBOWIN2.exe (autocontenido)
#
# Notas:
# - El DBC va embebido; un mft06.dbc JUNTO al .exe tiene prioridad (se puede
#   actualizar sin recompilar).
# - Los logs .db y la config van a %LOCALAPPDATA%\ROBOWIN2, nunca junto al exe.
# - Se excluyen PyQt5/PyQt6 (ROBOWIN 1) para que pyqtgraph use PySide6.

Set-Location (Join-Path $PSScriptRoot "..")

python -m PyInstaller --noconfirm --onefile --windowed --name ROBOWIN2 `
    --paths . `
    --distpath robowin2\dist `
    --workpath robowin2\build `
    --specpath robowin2 `
    --add-data "assets\mft06.dbc;." `
    --exclude-module PyQt5 `
    --exclude-module PyQt6 `
    --exclude-module matplotlib `
    --exclude-module tkinter `
    robowin2\main.py
