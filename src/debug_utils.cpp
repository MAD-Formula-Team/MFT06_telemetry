#include "debug_utils.h"

// ============================================================================
// IMPLEMENTACIÓN DEL SISTEMA DE DEBUG
// ============================================================================

void debugInit() {
  Serial.begin(SERIAL_BAUD);
  delay(1000);
}

void debugPrint(const char* msg) {
  #if DEBUG_MODE == 1
    Serial.print(msg);
  #endif
}

void debugPrintln(const char* msg) {
  #if DEBUG_MODE == 1
    Serial.println(msg);
  #endif
}

void debugPrintPacket(TelemetryPacket &pkt, bool isTX) {
  #if DEBUG_MODE == 1
    Serial.print(isTX ? "[TX] " : "[RX] ");
    Serial.print("ID:0x");
    if(pkt.canId < 0x100) Serial.print("0");
    if(pkt.canId < 0x10) Serial.print("0");
    Serial.print(pkt.canId, HEX);
    Serial.print(" Len:");
    Serial.print(pkt.len);
    Serial.print(" Data:[");

    for(uint8_t i = 0; i < pkt.len; i++) {
      if(i > 0) Serial.print(" ");
      if(pkt.data[i] < 0x10) Serial.print("0");
      Serial.print(pkt.data[i], HEX);
    }

    Serial.println("]");
  #endif
}

void debugPrintCanMessage(uint16_t id, uint8_t len, uint8_t data[8]) {
  #if DEBUG_MODE == 1
    Serial.print("[CAN] 0x");
    if(id < 0x100) Serial.print("0");
    if(id < 0x10) Serial.print("0");
    Serial.print(id, HEX);

    // Decodificación de IDs conocidas
    if(id == 0x3A4) {
      // Engine Speed - RPM en bytes [5:4] (little endian)
      uint16_t rpm = (data[5] << 8) | data[4];
      Serial.print(" [RPM:");
      Serial.print(rpm);
      Serial.print("]");
    }
    else if(id == 0x3A1) {
      // Engine Temperature - ECT en bytes [3:2] (little endian)
      uint16_t ect = (data[3] << 8) | data[2];
      Serial.print(" [ECT:");
      Serial.print(ect);
      Serial.print("]");
    }

    Serial.print(" Len:");
    Serial.print(len);
    Serial.print(" [");
    for(uint8_t i = 0; i < len && i < 4; i++) {
      if(i > 0) Serial.print(" ");
      if(data[i] < 0x10) Serial.print("0");
      Serial.print(data[i], HEX);
    }
    Serial.println("]");
  #endif
}
