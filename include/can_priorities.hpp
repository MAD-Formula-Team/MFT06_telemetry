#ifndef CAN_PRIORITIES_H
#define CAN_PRIORITIES_H
#include <Arduino.h>

struct CANFilterEntry {
    uint32_t canId;
    uint32_t minIntervalMs;
    uint8_t priority;
    const char *name;
};

static const CANFilterEntry CAN_FILTER_TABLE[] = {
        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 0
        // ─────────────────────────────────────────────────────────────
        {930, 2000, 0, "engine_press"},
        {929, 2000, 0, "engine_temp"},
        {946, 3000, 0, "currents_cooling"},

        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 1
        // ─────────────────────────────────────────────────────────────
        {931, 4000, 1, "engine_fuel"},
        {933, 5000, 1, "engine_misc"},
        {945, 6000, 1, "curr_engine"},
        {993, 6000, 1, "node_temp_1"},
        {994, 6000, 1, "node_temp_2"},

        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 2
        // ─────────────────────────────────────────────────────────────
        {176, 6000, 2, "steering"},
        {932, 8000, 2, "engine_speed"},
        {947, 8000, 2, "curr_other"},
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
