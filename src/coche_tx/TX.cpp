#include <Arduino.h>
#include <RadioLib.h>
#include <SPI.h>
#include <cstdint>
#include <mcp_can.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "can_priorities.hpp"
#include "common_config.hpp"

static TelemetryPacket lvBuf[FILTER_TABLE_SIZE];
static volatile bool lvPending[FILTER_TABLE_SIZE];
static uint32_t lastQueuedMs[FILTER_TABLE_SIZE];
static bool firstSeen[FILTER_TABLE_SIZE];

SemaphoreHandle_t txReadySem = nullptr;
SemaphoreHandle_t pendingMutex = nullptr;

static volatile uint32_t statSent = 0;
static volatile uint32_t statRateDrop = 0;
static volatile uint32_t statSkipId = 0;
static volatile uint32_t statMutexErr = 0;
static uint32_t seqNum = 0;

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

ICACHE_RAM_ATTR void setFlag(void) {
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(txReadySem, &woken);
    if (woken)
        portYIELD_FROM_ISR();
}

static int selectBest() { // TODO: cambiar por un std::map?
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
        Serial.printf("[LORA - ERROR] INIT ERROR: %d\n", state);
        vTaskDelete(NULL);
        return;
    }
    xSemaphoreGive(txReadySem);
    Serial.printf("[LoRa] OK — ToA=%ums TX_interval=%ums DC=%u%%\n", lora_timing::TOA_MS, lora_timing::TX_INTERVAL_MS,
                  lora_timing::DUTY_CYCLE_PERCENT);
    uint32_t lastTxStart = 0, lastLog = 0;

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

        if (!got_packet) {
            vTaskDelay(pdMS_TO_TICKS(10));
            goto log; // TODO: smelly goto
        }

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
            Serial.printf("[LORA - WARNING] timeout HW (tx=%u)\n", statSent);
            xSemaphoreGive(txReadySem);
        }

    log:
        if (millis() - lastLog > 10000) {
            lastLog = millis();
            float dc = (float) statSent * lora_timing::TOA_MS / (millis() / 1000.0f) / 10.0f;
            Serial.printf("[LORA] tx=%u | rate_drop=%u | skip=%u | DC=%.1f%%\n", statSent, statRateDrop, statSkipId,
                          dc);
        }
    }
}

void setup() {
    Serial.begin(921600);

    txReadySem = xSemaphoreCreateBinary();
    pendingMutex = xSemaphoreCreateMutex();
    if (!txReadySem || !pendingMutex) {
        Serial.println("[SYS - ERROR] SEMAPHORE INIT FAIL");
        while (1);
    }

    for (int i = 0; i < (int) FILTER_TABLE_SIZE; i++) {
        lvPending[i] = false;
        firstSeen[i] = true;
        lastQueuedMs[i] = 0;
    }

    SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
    if (CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
        CAN0.setMode(MCP_NORMAL);
        Serial.println("[CAN] INIT OK");
    } else {
        Serial.println("[CAN - ERROR] INIT ERROR");
        while (1);
    }

    xTaskCreatePinnedToCore(taskLoRa, "TaskLoRa", 4096, NULL, 2, NULL, 0);

    Serial.printf("[SYS] INIT OK\n\t\tFilters: %d IDs\n", (int) FILTER_TABLE_SIZE);
}

void loop() {
    if (CAN0.checkReceive() != CAN_MSGAVAIL)
        return;

    unsigned long rxId;
    uint8_t rxLen;
    uint8_t rxBuf[8];
    CAN0.readMsgBuf(&rxId, &rxLen, rxBuf);

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
