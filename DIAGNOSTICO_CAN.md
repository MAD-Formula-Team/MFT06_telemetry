# Diagnóstico: fallo de init del MCP2515 — "Entering Configuration Mode Failure / INIT ERROR - 1"

**Fecha:** 11 julio 2026
**Estado:** NO RESUELTO — descartado software y chips; pendiente verificación física del cableado/alimentación
**Proyecto:** MFT06_telemetry — telemetría de monoplaza (Formula Student), entorno `coche_tx`

---

## 1. Síntoma

Al arrancar el firmware del transmisor del coche (`coche_tx`), el init del CAN falla siempre:

```
[LoRa] OK — ToA=57ms TX_interval=570ms DC=10%     <- LoRa (SX1262, bus SPI aparte) funciona
Entering Configuration Mode Failure...             <- mensaje DEBUG de la libreria mcp_can
[CAN - ERROR] INIT ERROR - 1                       <- CAN_FAILINIT devuelto por CAN0.begin()
```

**Importante:** este sistema FUNCIONÓ el 3-4 de julio de 2026 (hay CSVs de telemetría reales
de esos días en el repo) con el mismo firmware, los mismos pines y la misma librería.
Algo cambió en el mundo físico entre entonces y ahora.

## 2. Hardware

| Elemento | Detalle |
|---|---|
| MCU | Heltec WiFi LoRa 32 **V3** (ESP32-S3FN8, sin PSRAM) |
| Controlador CAN | Módulo MCP2515 + transceptor (típico módulo azul con TJA1050, cristal 8 MHz) |
| Conexión | Cables dupont entre el header de la Heltec y el header del módulo |
| Radio | SX1262 integrado en la Heltec, en bus SPI propio (HSPI) — funciona OK |
| OLED | SSD1306 integrado (no se usa en el target coche_tx) |

### Pines configurados (include/common_config.hpp)

| Señal | GPIO ESP32-S3 | Nota |
|---|---|---|
| CAN_CS | 34 | |
| CAN_SCK | **36** | ⚠️ GPIO36 es también el control de Vext en la Heltec V3 (`OLED_VEXT 36` en el mismo archivo). A pesar de ello, FUNCIONÓ así el 3-4 julio |
| CAN_MISO | 33 | |
| CAN_MOSI | 35 | |
| Bitrate CAN | 500 kbps (`CAN_500KBPS`), cristal `MCP_8MHZ` | |

Init en `src/coche_tx/TX.cpp`:
```cpp
SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);   // FSPI del ESP32-S3
int err = CAN0.begin(MCP_ANY, CAN_SPEED, MCP_8MHZ); // devuelve 1 = CAN_FAILINIT
```
La librería usa SPI a 10 MHz, modo 0 (`SPISettings(10000000, MSBFIRST, SPI_MODE0)`).

## 3. Qué significa el error (análisis del código de la librería)

`CAN0.begin()` de mcp_can (fork coryjfowler) solo devuelve `CAN_OK` (0) o `CAN_FAILINIT` (1).
El mensaje `Entering Configuration Mode Failure...` se imprime en `mcp2515_init()` cuando
`mcp2515_setCANCTRL_Mode(MODE_CONFIG)` falla: escribe los bits REQOP en CANCTRL y **relee
CANSTAT para verificar**. Falla ⇒ la relectura no coincide ⇒ **no hay comunicación SPI válida
con el chip**. Ocurre ANTES de configurar bitrate/filtros: un bus CAN desconectado, sin
terminación, o un cristal mal declarado NO producen este error.

## 4. Diagnóstico realizado (firmware instrumentado)

Se añadió temporalmente a TX.cpp un sondeo SPI de bajo nivel (ya revertido; ver §7 para
reproducirlo). Resultados **consistentes en todas las ejecuciones**:

```
[CAN - DEBUG] pines: CS=34 SCK=36 MISO=33 MOSI=35
[CAN - DEBUG] MISO con pull-down=1, con pull-up=1 => fijado a ALTO desde fuera
[CAN - DEBUG] bit-bang 10kHz: CANSTAT=0xFF (esp. 0x80) CANCTRL=0xFF (esp. 0x87) => sin respuesta
[CAN - DEBUG] CANSTAT@250k=0xFF | CANCTRL@250k=0xFF | CANSTAT@10M=0xFF
```

Las tres pruebas fueron:
1. **Test de línea MISO**: con pull-down interno (~45 kΩ) del ESP32 activado, MISO lee 1.
   ⇒ **algo externo mantiene MISO en nivel alto permanentemente**, incluso con CS en alto
   (cuando el MCP2515 debería tener su pin SO en alta impedancia y el pull-down leería 0).
2. **SPI bit-bang a ~10 kHz** (digitalWrite, sin usar el periférico SPI): RESET (0xC0) +
   READ (0x03) de CANSTAT (reg 0x0E) y CANCTRL (0x0F). Esperado tras reset: 0x80 y 0x87.
   Leído: **0xFF, 0xFF**. Descarta problemas del driver/pin-mux SPI del ESP32-S3.
3. **SPI hardware a 250 kHz y 10 MHz**: idéntico, todo 0xFF. Descarta que sea un problema
   de velocidad/integridad marginal.

## 5. Matriz de eliminación (todo probado, mismo error idéntico)

| Hipótesis | Cómo se descartó |
|---|---|
| Librería mcp_can corrupta/cambiada | `git log`: sin cambios desde el commit "Funcional 02 julio" (anterior a cuando funcionó). Además se probó con el **master oficial de coryjfowler** descargado de GitHub: mismo error |
| MCP2515 dañado | **Sustituido por otro módulo igual**: mismo error |
| ESP32/Heltec dañada | **Sustituida por otra placa igual**: mismo error |
| Pines mal definidos en el código | Sin cambios en git desde que funcionaba (SCK=36 desde siempre) |
| Velocidad SPI / integridad de señal | Falla igual a 10 kHz bit-bang que a 10 MHz |
| Periférico SPI del ESP32-S3 / conflicto con LoRa | LoRa (otro bus SPI) funciona; bit-bang puro por GPIO también falla |
| Bus CAN / terminación / cristal | Irrelevante: el fallo es anterior (el chip no responde por SPI) |
| Monitor serie a velocidad equivocada | El resto de logs a 921600 se leen perfectamente |

**Lo único NO sustituido/verificado con instrumento: los cables dupont, el patrón de
conexión (qué cable va a qué pin del módulo) y la alimentación del módulo.**

## 6. Hipótesis principales restantes (por orden de probabilidad)

1. **Cable MISO conectado al pin INT del módulo en vez de a SO.**
   Firma exacta observada: INT del MCP2515 es push-pull y reposa en ALTO ⇒ todas las
   lecturas SPI dan 0xFF y la línea queda "fijada a alto" incluso con CS desactivado.
   El orden del header (INT, SCK, SI, SO, CS, GND, VCC) **varía entre fabricantes** de
   módulos MCP2515: verificar contra la serigrafía del módulo actual, no de memoria.
   Correspondencia correcta: GPIO33→SO, GPIO35→SI, GPIO36→SCK, GPIO34→CS.
2. **Cable CS que no llega al chip** (roto o en pin equivocado): el chip quedaría
   seleccionado o desalineado permanentemente y SO activo ⇒ también produce 0xFF constantes.
3. **Alimentación**: módulo conectado a 3V3 o al pin "Ve" de la Heltec en vez de a **5V**.
   Ojo: el rail "Ve"/Vext de la Heltec V3 lo conmuta el GPIO36 (activo a nivel bajo)…
   que es justamente el pin usado como SCK. El módulo debe ir al pin 5V.
4. **Dupont con crimp flojo**: da continuidad al medirlo suelto y falla montado.
   Medir pinchando en la pata del header del módulo, no en el conector del cable.

## 7. Herramientas de diagnóstico disponibles (para re-flashear si hace falta)

En el historial de esta sesión existe un TX.cpp instrumentado con:
- `canDebugProbeGpio()`: test de MISO flotante/fijado + lectura bit-bang 10 kHz de CANSTAT/CANCTRL.
- `canDebugProbe()`: lecturas con SPI hardware a 250 kHz y 10 MHz.
- `canDebugWireTrace()`: **modo traza de cables** — al fallar el init entra en bucle infinito
  poniendo cada señal a 3.3 V durante 3 s por turno (CS → SCK → MOSI), para verificar con
  multímetro en los pines del MÓDULO que cada cable llega a su pin correcto de extremo a
  extremo. Con la traza activa, el pin SO del módulo debe medir ~0 V; si el cable que crees
  que es MISO mide 3.3 V constante, está en INT.

Interpretación rápida de una nueva captura del sondeo:
- `0xFF` en todo ⇒ MISO en alto: hipótesis 1/2/4.
- `0x00` en todo ⇒ MISO en bajo/flotante: módulo sin alimentación o MISO suelto.
- `CANSTAT=0x80` a 250 kHz pero mal a 10 MHz ⇒ integridad de señal (acortar cables,
  mover SCK fuera de GPIO36, o bajar SPISettings de la librería).
- `CANSTAT=0x80` en todo y aun así `begin()` falla ⇒ investigar la secuencia de la librería.

## 8. Recomendaciones adicionales (independientes del fallo)

- Aunque funcionó así, **GPIO36 como SCK es frágil** en la Heltec V3 (es el control de Vext,
  con el gate del PMOS colgado de la línea). Candidatos limpios: GPIO47 o GPIO48.
- `CAN0.setMode(MCP_LISTENONLY)` en TX.cpp no comprueba el valor devuelto.
- Bug en la librería (ambas versiones): si `mcp2515_configRate()` falla, `mcp2515_init()`
  devuelve `res`=0 y `begin()` reporta `CAN_OK` erróneamente ("Setting Baudrate Failure..."
  en serie pero sin error de retorno).
- `src/can_manager.cpp` es código muerto (no entra en ningún `build_src_filter`) y contiene
  un error de sintaxis (`\` como comentario en la línea 14).
- El working tree se revirtió solo una vez durante la sesión (probablemente sincronización
  de OneDrive sobre el repo git): cuidado con ediciones sin commitear en este proyecto.

## 9. Entorno de compilación

- PlatformIO, entorno `coche_tx` (`pio run -e coche_tx -t upload`), board `heltec_wifi_lora_32_V3`.
- Monitor serie: **921600 baudios**, DTR=0, RTS=0 (la basura inicial del boot es el
  bootloader de la ROM a 115200; es normal).
- Puerto en este PC: COM6 (Silicon Labs CP210x). Solo un proceso puede abrir el puerto:
  cerrar el monitor antes de flashear.
- La librería CAN es una copia local en `lib/mcp_can/` (fork coryjfowler parcheado con un
  clamp de DLC>8; NO añadir la dependencia del registro sin leer el comentario de
  `platformio.ini`).
