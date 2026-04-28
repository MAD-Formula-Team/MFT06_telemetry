#pragma once
#include <cstdint>

struct HeartbeatEntry {
    uint32_t canId;
    uint32_t timeoutMs; // ms sin mensaje antes de avisar
    const char *name;
};

// ─── EDITAR AQUÍ ──────────────────────────────────────────────────────────────
static const HeartbeatEntry HEARTBEAT_TABLE[] = {
    {0x370, 2000, "dash_HB"},
    {0x380, 2000, "gear_HB"},
    {0x390, 2000, "steering_HB"},
    {0x3b0, 2000, "PDM_HB"},
    {0x3e0, 2000, "nodo_HB"},
};
// ─────────────────────────────────────────────────────────────────────────────

#define HEARTBEAT_TABLE_SIZE (sizeof(HEARTBEAT_TABLE) / sizeof(HEARTBEAT_TABLE[0]))

static inline int heartbeatFind(uint32_t id) {
    for (int i = 0; i < (int) HEARTBEAT_TABLE_SIZE; i++) {
        if (HEARTBEAT_TABLE[i].canId == id)
            return i;
    }
    return -1;
}
