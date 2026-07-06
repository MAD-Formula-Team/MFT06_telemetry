#ifndef CAN_PRIORITIES_H
#define CAN_PRIORITIES_H
#include <Arduino.h>

struct CANFilterEntry {
    uint32_t canId;
    uint32_t minIntervalMs;
    uint8_t priority;
    uint8_t decimation; // conservar 1 de cada N tramas recibidas (1 = todas)
    const char *name;
};

// Solo se transmiten estos 5 IDs (decimal). El resto de tramas CAN se descarta.
// El orden importa: selectBest() en TX.cpp asume engine_temp en el índice 0.
// engine_temp: máximo 1 trama por segundo (minIntervalMs = 1000); los demás
// sin rate-limit y se reparten los slots LoRa equitativamente entre ellos.
static const CANFilterEntry CAN_FILTER_TABLE[] = {
        {929, 1000, 0, 1,  "engine_temp"},   // 0x3A1: 1 vez por segundo
        {931, 0,    1, 1,  "engine_fuel"},   // 0x3A3
        {932, 0,    2, 20, "engine_speed"},  // 0x3A4: solo 1 de cada 20 tramas
        {933, 0,    1, 1,  "engine_misc"},   // 0x3A5
        {176, 0,    2, 1,  "steering"},      // 0x0B0
};

#define FILTER_TABLE_SIZE (sizeof(CAN_FILTER_TABLE) / sizeof(CAN_FILTER_TABLE[0]))

static inline int canFilterFind(const uint32_t id) {
    for (int i = 0; i < static_cast<int>(FILTER_TABLE_SIZE); i++) {
        if (CAN_FILTER_TABLE[i].canId == id)
            return i;
    }
    return -1;
}

#endif
