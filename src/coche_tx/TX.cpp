#include <Arduino.h>
#include <RadioLib.h>
#include <SPI.h>
#include <mcp_can.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "can_priorities.hpp"
#include "common_config.hpp"
#include "heartbeat_config.hpp"

static volatile bool lvPending[FILTER_TABLE_SIZE];
static volatile bool lvHasData[FILTER_TABLE_SIZE];

static TelemetryPacket lvBuf[FILTER_TABLE_SIZE];
static volatile uint32_t lastQueuedMs[FILTER_TABLE_SIZE];

static SemaphoreHandle_t txReadySem = nullptr;
static SemaphoreHandle_t pendingMutex = nullptr;

#ifdef HB_CHECK_ENABLED
static volatile uint32_t hbLastSeen[HEARTBEAT_TABLE_SIZE];
static volatile bool hbEverSeen[HEARTBEAT_TABLE_SIZE];
#endif

#ifdef FUEL_CONSUMPTION_CALC
static float fuelAccumCc = 0.0f;
static uint32_t fuelLastMs = 0;
#endif

static volatile uint32_t statSent = 0;
static volatile uint32_t statRateDrop = 0;
static volatile uint32_t statSkipId = 0;
static volatile uint32_t statMutexErr = 0;
static volatile uint32_t seqNum = 0;

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

IRAM_ATTR void setFlag() {
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(txReadySem, &woken);
    if (woken) {
        portYIELD_FROM_ISR();
    }
}

static int selectBest() {
    static int loop_counter = 0;

    static constexpr int schedule[16] = {
            0, 1, 2
    };

    const int best = schedule[loop_counter % 3];
    ++loop_counter;
    return best;
}

void taskLoRa(void *pvParameters) {
    uint32_t lastTxStart = 0, lastLog = 0, lastHbCheck = 0;

    while (true) {
        TelemetryPacket telemetry_packet{};
        bool got_packet = false;

        if (xSemaphoreTake(pendingMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
            const int current_can_id = selectBest();
            if (current_can_id >= 0) {
                if (lvPending[current_can_id]) {
                    telemetry_packet = lvBuf[current_can_id];
                    lvPending[current_can_id] = false;
                    got_packet = true;
                } else if (lvHasData[current_can_id]) {
                    // No hay trama nueva en este slot, enviar la última muestra
                    // conocida para garantizar que las tres trazas roten.
                    telemetry_packet = lvBuf[current_can_id];
                    got_packet = true;
                }
            }
            xSemaphoreGive(pendingMutex);
        }

        if (got_packet) {
#ifndef LORA_UNTHROTTLED_MODE
            { // Check duty cycle
                const uint32_t elapsed = millis() - lastTxStart;
                if (elapsed < lora_timing::TX_INTERVAL_MS) {
                    vTaskDelay(pdMS_TO_TICKS(lora_timing::TX_INTERVAL_MS - elapsed));
                }
            }
#endif

            if (xSemaphoreTake(txReadySem, pdMS_TO_TICKS(lora_timing::TX_INTERVAL_MS + lora_timing::TOA_MS + 50u)) ==
                pdTRUE) {
                lastTxStart = millis();
                statSent++;
                radio.startTransmit(reinterpret_cast<uint8_t *>(&telemetry_packet), sizeof(telemetry_packet));
            } else {
                LOGF("[LORA - WARNING] timeout HW (tx=%u)\n", statSent);
                xSemaphoreGive(txReadySem);
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(10));
        }


#ifdef HB_CHECK_ENABLED
        const uint32_t now_ms = millis();
        if (now_ms - lastHbCheck > 5000u) {
            lastHbCheck = now_ms;
            for (int i = 0; i < (int) HEARTBEAT_TABLE_SIZE; i++) {
                if (hbEverSeen[i] && (now_ms - hbLastSeen[i] > HEARTBEAT_TABLE[i].timeoutMs)) {
                    LOGF("[HB - WARN] sin heartbeat: %s (0x%03X) — %ums sin mensaje\n", HEARTBEAT_TABLE[i].name,
                         HEARTBEAT_TABLE[i].canId, now_ms - hbLastSeen[i]);
                }
            }
        }
#endif

#ifdef SERIAL_LOGGING_ENABLED
        const uint32_t now_ms = millis();
        if (now_ms - lastLog > 10000u) {
            lastLog = now_ms;
            uint32_t secs = now_ms / 1000u;
            uint32_t dc = (secs > 0) ? ((uint32_t) statSent * lora_timing::TOA_MS / secs) : 0u;
            LOGF("[LORA] tx=%u | rate_drop=%u | skip=%u | DC=%u.%u%%\n", statSent, statRateDrop, statSkipId, dc / 10u,
                 dc % 10u);
        }
#endif
    }
}

void setup() {
#ifdef SERIAL_LOGGING_ENABLED
    Serial.begin(921600);
#endif

    txReadySem = xSemaphoreCreateBinary();
    pendingMutex = xSemaphoreCreateMutex();
    if (!txReadySem || !pendingMutex) {
        LOGL("[SYS - ERROR] SEMAPHORE INIT FAIL");
        while (true);
    }

    for (int i = 0; i < static_cast<int>(FILTER_TABLE_SIZE); i++) {
        lvPending[i] = false;
        lvHasData[i] = false;
        lastQueuedMs[i] = 0;
    }

#ifdef HB_CHECK_ENABLED
    for (int i = 0; i < static_cast<int>(HEARTBEAT_TABLE_SIZE); i++) {
        hbLastSeen[i] = 0;
        hbEverSeen[i] = false;
    }
#endif

    // Inicializar LoRa y CAN secuencialmente, en el mismo core y antes de crear
    // ninguna tarea: instalar dos buses SPI en paralelo desde cores distintos
    // (uno ya en transacciones activas) corrompe el driver SPI y provoca un
    // Guru Meditation (LoadProhibited) dentro de beginTransaction().
    loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
    const int lora_state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
    radio.setDio1Action(setFlag);
    if (lora_state != RADIOLIB_ERR_NONE) {
        LOGF("[LORA - ERROR] INIT ERROR: %d\n", lora_state);
        while (true);
    }
    xSemaphoreGive(txReadySem);
    LOGF("[LoRa] OK — ToA=%ums TX_interval=%ums DC=%u%%\n", lora_timing::TOA_MS, lora_timing::TX_INTERVAL_MS,
         lora_timing::DUTY_CYCLE_PERCENT);

    SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
    int err = CAN0.begin(MCP_ANY, CAN_SPEED, MCP_8MHZ);
    if (err == CAN_OK) {
        CAN0.setMode(MCP_LISTENONLY);
        LOGL("[CAN] INIT OK");
    }
    else {
        LOGF("[CAN - ERROR] INIT ERROR - %d", err);
        while (true);
    }

    xTaskCreatePinnedToCore(taskLoRa, "TaskLoRa", 4096, nullptr, 2, nullptr, 0);

    LOGF("[SYS] INIT OK\n\t\tFilters: %d IDs\n", (int) FILTER_TABLE_SIZE);
}

void loop() {
    if (CAN0.checkReceive() != CAN_MSGAVAIL) {
        // Ceder CPU: sin esto, con el bus CAN inactivo loop() gira sin bloquear
        // nunca en el core de Arduino, la tarea IDLE de ese core no llega a
        // ejecutarse y el Task Watchdog acaba reiniciando la placa.
        vTaskDelay(pdMS_TO_TICKS(1));
        return;
    }

    unsigned long rxId;
    uint8_t rxLen;
    uint8_t rxBuf[8];
    CAN0.readMsgBuf(&rxId, &rxLen, rxBuf);

#ifdef HB_CHECK_ENABLED
    const int hb_idx = heartbeatFind(rxId);
    if (hb_idx >= 0) {
        hbLastSeen[hb_idx] = millis();
        hbEverSeen[hb_idx] = true;
    }
#endif

    const int current_can_id = canFilterFind(rxId);
    if (current_can_id < 0) {
        statSkipId++;
        return;
    }

    const auto now = millis();
#ifdef FUEL_CONSUMPTION_CALC
    // Acumula consumo en cada trama (antes del rate-limit) y reemplaza bytes 2-3
    // con el acumulado en cc (escala 1 cc/LSB, max 65535 cc). DBC: (1,0) "cc"
    if (rxId == 931 && rxLen >= 4) {
        uint16_t raw = (uint16_t) rxBuf[2] | ((uint16_t) rxBuf[3] << 8);
        float instant_ccmin = raw * 0.1f;
        if (fuelLastMs > 0) {
            float dt_min = (now - fuelLastMs) / 60000.0f;
            fuelAccumCc += instant_ccmin * dt_min;
        }
        fuelLastMs = now;
        uint16_t accum_raw = fuelAccumCc > 65535.0f ? 65535u : (uint16_t) fuelAccumCc;
        rxBuf[2] = (uint8_t) (accum_raw & 0xFF);
        rxBuf[3] = (uint8_t) (accum_raw >> 8);
    }
#endif

#ifdef LORA_UNTHROTTLED_MODE
    const bool rate_ok = true;
#else
    const bool rate_ok = ((now - lastQueuedMs[current_can_id]) >= (CAN_FILTER_TABLE[current_can_id].minIntervalMs));
#endif
#ifdef SERIAL_LOGGING_ENABLED
    if (!rate_ok) {
        statRateDrop++;
    }
#endif

    if (rate_ok) {
        if (xSemaphoreTake(pendingMutex, pdMS_TO_TICKS(1)) == pdTRUE) {
            // Si el mensaje es engine_misc (933) y la batería viene en voltios
            // como entero (p.ej. 12), convertir a centésimas (1200) para enviar
            // con resolución de 0.01 V/LSB en el enlace.
            if (rxId == 933 && rxLen >= 2) {
                uint16_t raw = (uint16_t) rxBuf[0] | ((uint16_t) rxBuf[1] << 8);
                // Forzar siempre envío en centésimas (0.01 V/LSB)
                uint32_t scaled = (uint32_t) raw * 100u; // centésimas
                if (scaled > 65535u) scaled = 65535u;
                rxBuf[0] = (uint8_t) (scaled & 0xFF);
                rxBuf[1] = (uint8_t) (scaled >> 8);
            }

            lvBuf[current_can_id].canId = static_cast<uint16_t>(rxId); // FIXME: sobra?
            lvBuf[current_can_id].len = rxLen; // FIXME: sobra?
            memcpy(lvBuf[current_can_id].data, rxBuf, 8);
            lvBuf[current_can_id].packetId = seqNum++;
            lvHasData[current_can_id] = true;
            lvPending[current_can_id] = true;
            lastQueuedMs[current_can_id] = now;
            xSemaphoreGive(pendingMutex);
        } else {
            statMutexErr++;
        }
    }
}
