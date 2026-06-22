#ifndef CAN_MANAGER_H
#define CAN_MANAGER_H

#include <mcp_can.h>
#include <SPI.h>
#include "config.h"

// ============================================================================
// GESTIÓN DE BUS CAN (MCP2515)
// ============================================================================
// Maneja inicialización y lectura de mensajes CAN

// Objeto global del controlador CAN
extern MCP_CAN CAN0;

// Inicializar controlador CAN MCP2515
// Configura: 1000 kbps, cristal 8MHz, modo NORMAL
// Retorna: true si éxito, false si fallo
bool canInit();

// Verificar si hay mensaje CAN disponible
// Retorna: true si hay mensaje esperando
bool canCheckReceive();

// Leer mensaje CAN del buffer
// Parámetros: referencias a id, len y array data[8]
// Retorna: true si lectura OK, false si error
bool canReadMessage(uint16_t &id, uint8_t &len, uint8_t data[8]);

#endif // CAN_MANAGER_H
