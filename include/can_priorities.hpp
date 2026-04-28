#pragma once
#include <Arduino.h>
#include <cstdint>

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
        {931, 4000, 1, "engine_fuel"}, // fuel_consump?, lambda, throttle_pos
        {933, 5000, 1, "engine_misc"},
        {945, 6000, 1, "curr_engine"},
        {993, 6000, 1, "node_temp_1"},
        {994, 6000, 1, "node_temp_2"},

        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 2
        // ─────────────────────────────────────────────────────────────
        {176, 6000, 2, "steering"}, // brake_pressure, steering_wheel_angle, FL/FR wheel speeds
        {932, 8000, 2, "engine_speed"}, // gear, rear_l/r_speed, engine_rpm
        {947, 8000, 2, "curr_other"},

        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 3
        // ─────────────────────────────────────────────────────────────
        // {966, 10000, 3, "auto_values"}, // angle_slip / angle_track, curvature_radius ¿bulo de la ultraderecha?
        // {177, 10000, 3, "dampers"}, // realmente esto va en el carro?

        // IMU
        // {965, 12000, 3, "accel_cart"},
        // {962, 12000, 3, "pos_eul"},
        // {963, 15000, 3, "vel_cart"},
        // {964, 15000, 3, "vel_eul"},

        // ─────────────────────────────────────────────────────────────
        // PRIORIDAD 4
        // ─────────────────────────────────────────────────────────────

        {961, 20000, 4, "pos_cart"},
};

#define FILTER_TABLE_SIZE (sizeof(CAN_FILTER_TABLE) / sizeof(CAN_FILTER_TABLE[0]))

static inline int canFilterFind(uint32_t id) {
    for (int i = 0; i < (int) FILTER_TABLE_SIZE; i++) {
        if (CAN_FILTER_TABLE[i].canId == id)
            return i;
    }
    return -1;
}
