#include "can_manager.h"

// ============================================================================
// IMPLEMENTACIÓN DEL GESTOR CAN
// ============================================================================

// Objeto global
MCP_CAN CAN0(CAN_CS);

bool canInit() {
  // Inicializar SPI para CAN
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

  // Inicializar MCP2515: Modo ANY, 1000 kbps, cristal 8MHz
  if(CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) != CAN_OK) {
    return false;
  }

  // Cambiar a modo NORMAL para operación
  CAN0.setMode(MCP_NORMAL);

  return true;
}

bool canCheckReceive() {
  return (CAN0.checkReceive() == CAN_MSGAVAIL);
}

bool canReadMessage(uint16_t &id, uint8_t &len, uint8_t data[8]) {
  long unsigned int rxId;
  unsigned char rxLen;
  unsigned char rxBuf[8];

  // Leer mensaje del buffer
  if(CAN0.readMsgBuf(&rxId, &rxLen, rxBuf) != CAN_OK) {
    return false;
  }

  // Convertir tipos
  id = (uint16_t)rxId;
  len = rxLen;
  memcpy(data, rxBuf, 8);

  return true;
}
