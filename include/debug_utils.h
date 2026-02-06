#ifndef DEBUG_UTILS_H
#define DEBUG_UTILS_H

#include <Arduino.h>
#include "config.h"
#include "packet.h"

// ============================================================================
// SISTEMA DE DEBUG/LOGGING CONDICIONAL
// ============================================================================
// Basado en DEBUG_MODE definido en config.h
// DEBUG_MODE = 0: Silencioso (solo errores fatales)
// DEBUG_MODE = 1: Verbose (debug completo)

// Inicializar puerto serial según configuración
void debugInit();

// Print condicional (solo si DEBUG_MODE == 1)
void debugPrint(const char* msg);

// Print con newline condicional (solo si DEBUG_MODE == 1)
void debugPrintln(const char* msg);

// Formatear y mostrar paquete de telemetría
// isTX: true para TX, false para RX
void debugPrintPacket(TelemetryPacket &pkt, bool isTX);

// Decodificar y mostrar mensaje CAN
// Incluye decodificación de IDs conocidas (0x3A4, 0x3A1)
void debugPrintCanMessage(uint16_t id, uint8_t len, uint8_t data[8]);

#endif // DEBUG_UTILS_H
