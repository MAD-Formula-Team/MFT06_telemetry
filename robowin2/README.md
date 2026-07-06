# ROBOWIN 2

Reconstrucción del dashboard de telemetría MFT06. Plan completo en
[`../ROBOWIN2_PLAN.md`](../ROBOWIN2_PLAN.md).

## Estado

- [x] **Fase 1 — Núcleo** (`core/`): parser del protocolo serie, puertos por
  USB VID sin auto-reset, fuentes serie/replay, decodificador DBC, estadísticas
  de bus por ID, datastore numpy, laptimer con filtro de doble pulso, log crudo
  SQLite. Sin ningún import de Qt.
- [x] **Fase 2 — UI en vivo** (`ui/`): shell PySide6 con tema MFT claro/oscuro,
  selector de puerto por VID + conectar/desconectar, replay de logs `.db` desde
  la UI, y tres páginas: Dashboard (tarjetas con umbrales + gráficas), Señales
  (buscador + filas tarjeta|gráfica) y **Bus CAN** (análisis en vivo por ID).
  Arranque: `python -m robowin2.main`
- [x] **Fase 3 — Lap Timer** (`core/sessions.py`, `ui/pages/laptimer.py`):
  sesiones SKIDPAD/AUTOCROSS/ENDURANCE con crono, tabla de vueltas en vivo,
  auto-finalizado del skidpad a las 4 vueltas con nota FS, historial, y
  persistencia de sesiones + vueltas en el .db.
- [x] **Fase 4 — Offline** (`io_/offline.py`, `ui/pages/offline.py`): abrir
  logs `.db` (se reconstruyen decodificando los frames crudos), importar los
  CSV combinados de ROBOWIN 1, vincular vuelta↔telemetría (clic en vuelta =
  zoom + región resaltada) y exportar CSV compatible con R1.
- [x] **Fase 5 — Empaquetado**: `build_exe.ps1` (Windows) y `build_linux.sh`
  producen un ejecutable autocontenido en `robowin2/dist/` con el DBC embebido
  (un `mft06.dbc` junto al ejecutable tiene prioridad). Guía de pista en
  [`GUIA_CAMPO.md`](GUIA_CAMPO.md).

## Probar la app

```
pip install -r robowin2/requirements.txt   # solo la primera vez
python -m robowin2.demo                    # genera un log de demostración
python -m robowin2.main                    # arranca la app
```

- **En vivo**: conecta el receptor, elígelo en el desplegable de puertos
  (aparece primero, con el nombre del chip) y pulsa CONECTAR. El log crudo se
  graba solo en `%LOCALAPPDATA%\\ROBOWIN2` (Linux: `~/.local/share/ROBOWIN2`).
- **Sin hardware**: ABRIR LOG y elige `robowin_demo.db` (o cualquier log
  grabado): toda la app lo reproduce como si fuera en vivo.
- **CSV antiguos o del data logger**: página OFFLINE → IMPORTAR CSV (detecta
  solo el formato: combinado de ROBOWIN 1 o CSV del logger de a bordo con
  timestamps absolutos). Zoom con rueda/arrastre sobre las gráficas; los ejes
  de todas las gráficas van enlazados.
- Linux: añade tu usuario a `dialout` (`sudo usermod -aG dialout $USER`).

## Tests

```
python -m pytest robowin2/tests
```

Todo el núcleo se prueba headless (sin pantalla, sin hardware): la fuente
`ReplaySource` reproduce frames grabados o sintéticos por el mismo pipeline
que los datos en vivo.

## Rendimiento medido (fase 1)

Pipeline completo (decode DBC + stats + datastore + log SQLite):
**~85.000 frames/s** en un portátil — más de 15× el techo de diseño
(1–5k frames/s) y órdenes de magnitud sobre el caudal real de LoRa.
