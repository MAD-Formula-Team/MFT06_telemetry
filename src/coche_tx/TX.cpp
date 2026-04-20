#include <Arduino.h>
#include <RadioLib.h>
#include <SPI.h>
#include <Wire.h>
#include <SSD1306Wire.h>
#include <cstdint>
#include <mcp_can.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "can_priorities.hpp"
#include "common_config.hpp"
#include "heartbeat_config.hpp"

static SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);
static SemaphoreHandle_t mutexDisplay = nullptr;

static TelemetryPacket lvBuf[FILTER_TABLE_SIZE];
static volatile bool lvPending[FILTER_TABLE_SIZE];
static volatile uint32_t lastQueuedMs[FILTER_TABLE_SIZE];
static volatile bool firstSeen[FILTER_TABLE_SIZE];

static SemaphoreHandle_t txReadySem = nullptr;
static SemaphoreHandle_t pendingMutex = nullptr;

static volatile uint32_t hbLastSeen[HEARTBEAT_TABLE_SIZE];
static volatile bool hbEverSeen[HEARTBEAT_TABLE_SIZE];

static volatile uint32_t statSent = 0;
static volatile uint32_t statRateDrop = 0;
static volatile uint32_t statSkipId = 0;
static volatile uint32_t statMutexErr = 0;
static volatile uint32_t seqNum = 0;

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

IRAM_ATTR void setFlag(void) {
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(txReadySem, &woken);
    if (woken)
        portYIELD_FROM_ISR();
}

static void iniciarOLED() {
    pinMode(OLED_VEXT, OUTPUT);
    digitalWrite(OLED_VEXT, LOW);
    delay(100);
    pinMode(OLED_RST, OUTPUT);
    digitalWrite(OLED_RST, LOW);
    delay(20);
    digitalWrite(OLED_RST, HIGH);
    display.init();
    display.flipScreenVertically();
    display.setFont(ArialMT_Plain_10);
    display.clear();
    display.display();
}

// Abreviaturas de los nodos HB en el mismo orden que HEARTBEAT_TABLE
static const char *HB_LABELS[] = {"DSH", "GER", "STR", "PDM", "NOD"};

static void actualizarOLED() {
    uint32_t now_ms = millis();
    uint32_t tx     = statSent;
    uint32_t drop   = statRateDrop;
    uint32_t err    = statMutexErr;
    uint32_t dc     = (now_ms > 0) ? (tx * lora_timing::TOA_MS / (now_ms / 1000u)) : 0u;

    display.clear();
    display.setFont(ArialMT_Plain_10);

    // Línea 1: título + estado
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.drawString(0, 0, "MADFT06 TX");
    display.setTextAlignment(TEXT_ALIGN_RIGHT);
    display.drawString(128, 0, tx > 0 ? "OK" : "INIT");
    display.setTextAlignment(TEXT_ALIGN_LEFT);

    // Línea 2: paquetes enviados + duty cycle
    display.drawString(0, 14, "TX:" + String(tx) + "  DC:" + String(dc / 10u) + "." + String(dc % 10u) + "%");

    // Línea 3: drops + errores mutex
    display.drawString(0, 28, "DRP:" + String(drop) + "  ERR:" + String(err));

    // Línea 4: heartbeats
    for (int i = 0; i < (int) HEARTBEAT_TABLE_SIZE; i++) {
        int x = i * 25;
        bool alive = hbEverSeen[i] && (now_ms - hbLastSeen[i] <= HEARTBEAT_TABLE[i].timeoutMs);
        display.drawString(x, 42, HB_LABELS[i]);
        if (alive)
            display.fillRect(x + 1, 54, 8, 8);
        else
            display.drawRect(x + 1, 54, 8, 8);
    }

    display.display();
}

static void taskOLED(void *pvParameters) {
    for (;;) {
        if (xSemaphoreTake(mutexDisplay, pdMS_TO_TICKS(50)) == pdTRUE) {
            actualizarOLED();
            xSemaphoreGive(mutexDisplay);
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}

static int selectBest() {
    int best = -1;
    uint8_t pri = 255;
    for (int i = 0; i < (int) FILTER_TABLE_SIZE; i++) {
        if (lvPending[i] && CAN_FILTER_TABLE[i].priority < pri) {
            pri = CAN_FILTER_TABLE[i].priority;
            best = i;
        }
    }
    return best;
}

void taskLoRa(void *pvParameters) {
    loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
    int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
    radio.setDio1Action(setFlag);
    if (state != RADIOLIB_ERR_NONE) {
        LOGF("[LORA - ERROR] INIT ERROR: %d\n", state);
        vTaskDelete(NULL);
        return;
    }
    xSemaphoreGive(txReadySem);
    LOGF("[LoRa] OK — ToA=%ums TX_interval=%ums DC=%u%%\n", lora_timing::TOA_MS, lora_timing::TX_INTERVAL_MS,
         lora_timing::DUTY_CYCLE_PERCENT);
    uint32_t lastTxStart = 0, lastLog = 0, lastHbCheck = 0;

    while (1) {
        TelemetryPacket telemetry_packet;
        bool got_packet = false;

        if (xSemaphoreTake(pendingMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
            int current_can_id = selectBest();
            if (current_can_id >= 0) {
                telemetry_packet = lvBuf[current_can_id];
                lvPending[current_can_id] = false;
                got_packet = true;
            }
            xSemaphoreGive(pendingMutex);
        }

        if (got_packet) {
            { // Check duty cycle
                uint32_t elapsed = millis() - lastTxStart;
                if (elapsed < lora_timing::TX_INTERVAL_MS)
                    vTaskDelay(pdMS_TO_TICKS(lora_timing::TX_INTERVAL_MS - elapsed));
            }

            if (xSemaphoreTake(txReadySem, pdMS_TO_TICKS(lora_timing::TX_INTERVAL_MS + lora_timing::TOA_MS + 50u)) ==
                pdTRUE) {
                lastTxStart = millis();
                statSent++;
                radio.startTransmit((uint8_t *) &telemetry_packet, sizeof(telemetry_packet));
            } else {
                LOGF("[LORA - WARNING] timeout HW (tx=%u)\n", statSent);
                xSemaphoreGive(txReadySem);
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(10));
        }

        uint32_t now_ms = millis();

        if (now_ms - lastHbCheck > 5000u) {
            lastHbCheck = now_ms;
            for (int i = 0; i < (int) HEARTBEAT_TABLE_SIZE; i++) {
                if (hbEverSeen[i] && (now_ms - hbLastSeen[i] > HEARTBEAT_TABLE[i].timeoutMs))
                    LOGF("[HB - WARN] sin heartbeat: %s (0x%03X) — %ums sin mensaje\n",
                         HEARTBEAT_TABLE[i].name, HEARTBEAT_TABLE[i].canId, now_ms - hbLastSeen[i]);
            }
        }

        if (now_ms - lastLog > 10000u) {
            lastLog = now_ms;
            uint32_t dc = (uint32_t) statSent * lora_timing::TOA_MS / (now_ms / 1000u);
            LOGF("[LORA] tx=%u | rate_drop=%u | skip=%u | DC=%u.%u%%\n", statSent, statRateDrop, statSkipId,
                 dc / 10u, dc % 10u);
        }
    }
}

void setup() {
#ifdef SERIAL_LOGGING_ENABLED
    Serial.begin(921600);
#endif

    iniciarOLED();
    display.clear();
    display.setFont(ArialMT_Plain_16);
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.drawString(64, 8, "MADFT06 TX");
    display.setFont(ArialMT_Plain_10);
    display.drawString(64, 30, "Iniciando...");
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.display();

    txReadySem = xSemaphoreCreateBinary();
    pendingMutex = xSemaphoreCreateMutex();
    mutexDisplay = xSemaphoreCreateMutex();
    if (!txReadySem || !pendingMutex || !mutexDisplay) {
        LOGL("[SYS - ERROR] SEMAPHORE INIT FAIL");
        while (1);
    }

    for (int i = 0; i < (int) FILTER_TABLE_SIZE; i++) {
        lvPending[i] = false;
        firstSeen[i] = true;
        lastQueuedMs[i] = 0;
    }

    for (int i = 0; i < (int) HEARTBEAT_TABLE_SIZE; i++) {
        hbLastSeen[i] = 0;
        hbEverSeen[i] = false;
    }

    SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
    if (CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
        CAN0.setMode(MCP_NORMAL);
        LOGL("[CAN] INIT OK");
    } else {
        LOGL("[CAN - ERROR] INIT ERROR");
        while (1);
    }

    xTaskCreatePinnedToCore(taskLoRa, "TaskLoRa", 4096, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(taskOLED, "TaskOLED", 3072, NULL, 1, NULL, 0);

    LOGF("[SYS] INIT OK\n\t\tFilters: %d IDs\n", (int) FILTER_TABLE_SIZE);
}

void loop() {
    if (CAN0.checkReceive() != CAN_MSGAVAIL)
        return;

    unsigned long rxId;
    uint8_t rxLen;
    uint8_t rxBuf[8];
    CAN0.readMsgBuf(&rxId, &rxLen, rxBuf);

    int hb_idx = heartbeatFind(rxId);
    if (hb_idx >= 0) {
        hbLastSeen[hb_idx] = millis();
        hbEverSeen[hb_idx] = true;
    }

    int current_can_id = canFilterFind(rxId);
    if (current_can_id < 0) {
        statSkipId++;
        return;
    }

    // Solo encolar traza si ha pasado suficiente del polling rate
    uint32_t now = millis();
    if (!firstSeen[current_can_id] &&
        (now - lastQueuedMs[current_can_id] < CAN_FILTER_TABLE[current_can_id].minIntervalMs)) {
        statRateDrop++;
        return;
    }

    if (xSemaphoreTake(pendingMutex, pdMS_TO_TICKS(1)) == pdTRUE) {
        lvBuf[current_can_id].packetId = seqNum++;
        lvBuf[current_can_id].canId = (uint16_t) rxId;
        lvBuf[current_can_id].len = rxLen;
        memcpy(lvBuf[current_can_id].data, rxBuf, 8);
        lvPending[current_can_id] = true;
        firstSeen[current_can_id] = false;
        lastQueuedMs[current_can_id] = now;
        xSemaphoreGive(pendingMutex);
    } else {
        statMutexErr++;
    }
}
