# Genera el ejecutable de Windows del dashboard ROBOWIN.
# Requisitos: pip install pyinstaller
# Resultado: dist\ROBOWIN.exe (autocontenido, un solo archivo)
#
# Notas:
# - El DBC (mft06.dbc) y assets/ van embebidos en el .exe. Si se coloca un
#   mft06.dbc o assets\logo.png JUNTO al .exe, tienen prioridad sobre los
#   embebidos (permite actualizarlos sin recompilar).
# - sessions_autosave.csv se escribe junto al .exe.
# - Para icono propio: añadir --icon "assets\logo.ico" cuando exista.

Set-Location $PSScriptRoot

python -m PyInstaller --noconfirm --onefile --windowed --name ROBOWIN `
    --add-data "mft06.dbc;." `
    --add-data "assets;assets" `
    --exclude-module PyQt5 `
    --exclude-module PySide6 `
    --exclude-module matplotlib `
    --collect-submodules PyQt6.uic `
    Robowin.py
