# ROBOWIN 2 — Plan de reconstrucción del dashboard

Decisiones cerradas: **Python 3.11+ / PySide6 / pyqtgraph**, log crudo en **SQLite + export CSV**,
alcance v1 = **todas las funciones actuales + analizador de bus CAN**, protocolo serie **sin cambios**
(compatible con las placas ya flasheadas).

## 1. Objetivos

- **Velocidad**: arranque < 2 s, UI fluida a 20 FPS, análisis offline de logs grandes sin congelarse.
  El caudal en vivo lo limita LoRa (pocos frames/s), pero el diseño soporta 1–5k frames/s para
  futuras fuentes cableadas.
- **Portabilidad total Windows + Linux**: misma base de código, mismo comportamiento, detección
  determinista del receptor ESP32 en cualquier equipo.
- **Cero pérdida de datos**: log crudo append-only desde que arranca la app; todo lo demás
  (señales decodificadas, CSV, sesiones) son vistas derivadas regenerables.

## 2. Arquitectura

```
robowin2/
  core/                  # SIN imports de Qt — testeable headless con pytest
    sources.py           # SerialSource (protocolo CSV actual) | ReplaySource (desde .db o CSV)
    ports.py             # descubrimiento por USB VID, apertura sin reset (DTR/RTS pre-open)
    decoder.py           # cantools + mft06.dbc; IDs desconocidos quedan marcados, no se pierden
    bus_stats.py         # por ID: contador, Hz rodante, jitter, último payload, bytes cambiados
    datastore.py         # ring buffers numpy por señal; snapshots thread-safe para la UI
    lapstore.py          # lógica laptimer: vueltas, sesiones, nota FS skidpad, filtro doble pulso
    rawlog.py            # escritor SQLite (WAL, inserts por lotes cada 250 ms)
    pipeline.py          # hilo lector -> decodificador -> datastore/stats/rawlog
  ui/                    # PySide6; solo presentación, lee snapshots del core a 10–20 Hz
    theme.py             # paletas MFT claro/oscuro (portar el sistema de clases QSS actual)
    pages/               # dashboard.py, senales.py, laptimer.py, bus_can.py, offline.py
    widgets/             # tarjetas métricas, plot con eje mm:ss, crosshair, marcadores de vuelta
  io_/
    exporters.py         # CSV combinado (formato actual, retrocompatible), CSV de sesiones
    importers.py         # CSVs antiguos de Robowin 1 -> .db
  main.py
  tests/                 # pytest: core sin Qt + integración por replay + smoke UI offscreen
```

Regla de oro: `core/` no importa Qt jamás. La UI consume snapshots; no hay señales Qt dentro
de la lógica. Esto hace el 80 % del código testeable sin pantalla y evita el monolito actual.

## 3. Pipeline de datos

1. **Hilo lector** (threading.Thread): lee líneas del puerto, parsea `ID,B0,B1,...` →
   `RawFrame(t_mono_us, can_id, data)`. Nunca imprime en el bucle (lección aprendida).
2. **RawLog**: cada frame va a SQLite en lotes (WAL). Se registra ANTES de decodificar:
   un DBC incorrecto nunca pierde datos.
3. **Decoder**: cantools sobre el DBC; señales → datastore; frame (conocido o no) → bus_stats.
4. **UI**: QTimer a 50 ms pide snapshots (igual que ahora, que funciona bien).

`ReplaySource` reproduce un `.db` o CSV antiguo a velocidad xN por el mismo pipeline:
desarrollo y tests sin hardware.

## 4. Esquema SQLite (un archivo por día: `robowin_YYYYMMDD.db`)

```sql
runs     (id, started_utc, dbc_sha1, app_version)
frames   (run_id, t_us INTEGER, can_id INTEGER, len, data BLOB)   -- índice (run_id, t_us)
laps     (run_id, session_id, lap_no, t_us, lap_time_s, source)
sessions (id, run_id, name, mode, started_utc, ended_utc, fs_time_s)
meta     (key, value)
```

- Los `.db` viven en el directorio de datos del usuario (`platformdirs`), **nunca en OneDrive**
  (las reversiones de sincronización ya nos han mordido).
- Export CSV combinado idéntico al formato actual → los CSVs viejos y nuevos son intercambiables.

## 5. Portabilidad del puerto serie (el 90 % del problema real)

- **Detección por USB VID**, no por nombre: Espressif nativo `0x303A`, CP210x `0x10C4`,
  CH340 `0x1A86`, FTDI `0x0403`. Los puertos Bluetooth/placa base no aparecen como candidatos.
- **Apertura sin reset**: DTR/RTS fijados a False ANTES de `open()` (el auto-reset del ESP32
  está cableado a esas líneas).
- **Nunca cerrar un puerto por silencio**: se muestra staleness en la UI en su lugar
  (lección del bucle de reinicios). Si hay varios candidatos, el usuario elige; se recuerda
  el último puerto bueno en la config.
- Linux: ESP32-S3 es `/dev/ttyACM*` sin drivers; documentar `sudo usermod -aG dialout $USER`.
  Windows: CDC nativo sin drivers desde Win10; CP210x documentado por si acaso.

## 6. Páginas v1

| Página | Contenido |
|---|---|
| **Dashboard** | Tarjetas críticas con umbrales (ECT/OIL/BATT), gráfica combinada temps + RPM, estado laptimer |
| **Señales** | Tarjeta de valor + gráfica por señal activa, buscador, ejes X enlazados |
| **Lap Timer** | Sesiones skidpad/autocross/endurance, nota FS, historial, autosave en el .db |
| **Bus CAN** *(nuevo)* | Tabla en vivo por ID: nombre DBC o UNKNOWN resaltado, contador, Hz, jitter, staleness coloreado, payload hex con bytes cambiados resaltados, % de ancho de banda; pausa/snapshot; clic en ID → traza filtrada o señales; sparkline de frecuencia |
| **Offline** | Abrir `.db` (slicing SQL rápido) o CSV legado; vínculo vuelta↔telemetría; comparador de vueltas; export |

Tema MFT (paletas actuales claro/oscuro, clases QSS) se porta desde el día 1: es lo único
del código actual que se traslada casi tal cual, junto con la lógica FS del skidpad.

## 7. Rendimiento

- Ring buffers numpy → `setData` con arrays, no listas.
- Decimación pico antes de dibujar cuando hay >50k puntos visibles.
- Antialiasing activado; una sola escena por página; ejes enlazados como ahora.
- Presupuesto: tick UI < 15 ms con 12 gráficas activas.

## 8. Empaquetado

- PyInstaller onefile por SO con spec versionado (patrón `build_exe.ps1` actual + equivalente `.sh`).
- Exclusiones conocidas: PyQt5/matplotlib; incluir `PySide6` hooks, DBC y assets embebidos con
  override externo junto al ejecutable (patrón BUNDLE_DIR/SCRIPT_DIR actual).
- Rutas escribibles vía `platformdirs` (config TOML + datos), nunca la carpeta del exe en
  instalaciones de solo lectura.
- Opcional fase 5: GitHub Actions con matriz windows/ubuntu que compila artefactos en cada tag.

## 9. Tests

- `core/` al 100 % sin Qt: parser de líneas (incluye basura/corrupción), stats por ID,
  filtro de doble pulso, nota FS, round-trip SQLite→CSV→SQLite.
- Integración: replay de un log real grabado en pista y verificación de conteos exactos.
- UI: smoke offscreen (construcción, cambio de tema, alta/baja de gráficas) como ahora.

## 10. Fases

1. **Core + logging**: pipeline, SQLite, replay, tests. *Sin UI todavía; se valida con replay.*
2. **Shell UI + Bus CAN + Dashboard/Señales**: navbar, tema, las tres páginas en vivo.
3. **Lap Timer**: sesiones, FS, persistencia en .db.
4. **Offline**: lector .db + importador CSV legado, comparador de vueltas.
5. **Empaquetado + guía de campo**: exe/binario, permisos Linux, checklist de pista.

Cada fase termina con tests en verde y la app arrancable; Robowin 1 sigue disponible
hasta que la fase 4 alcance paridad.
