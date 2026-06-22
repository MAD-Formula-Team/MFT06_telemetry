#ifndef PACKET_H
#define PACKET_H

#include <stdint.h>

// ============================================================================
// ESTRUCTURA DE DATOS DE TELEMETRÍA (BINARIA COMPACTA)
// ============================================================================
// Total: 15 Bytes (vs ~40 Bytes en formato texto)
// IMPORTANTE: Esta estructura DEBE ser idéntica en TX y RX

struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId; // 4 bytes - Contador secuencial de paquetes
  uint16_t canId;    // 2 bytes - ID del mensaje CAN
  uint8_t  len;      // 1 byte  - Longitud de datos CAN (0-8)
  uint8_t  data[8];  // 8 bytes - Payload CAN
};

#endif // PACKET_H
