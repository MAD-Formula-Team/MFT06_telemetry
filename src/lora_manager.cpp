#include "lora_manager.h"

// ============================================================================
// IMPLEMENTACIÓN DEL GESTOR LORA
// ============================================================================

// Objetos globales
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
volatile bool txReady = true;
volatile bool rxReceived = false;

// Callbacks de interrupción
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void loraSetTxFlag() {
  txReady = true;
}

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void loraSetRxFlag() {
  rxReceived = true;
}

bool loraInit() {
  // Inicializar SPI para LoRa
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);

  // Configurar radio: Freq, BW, SF, CR, SyncWord, Power
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);

  if (state != RADIOLIB_ERR_NONE) {
    return false;
  }

  // Configurar longitud de preámbulo
  radio.setPreambleLength(LORA_PREAMBLE);

  // Asignar callbacks de interrupción
  radio.setDio1Action(loraSetTxFlag);

  return true;
}

bool loraSend(TelemetryPacket &packet) {
  if (!txReady) {
    return false;
  }

  txReady = false;
  int state = radio.startTransmit((uint8_t*)&packet, sizeof(TelemetryPacket));

  return (state == RADIOLIB_ERR_NONE);
}

bool loraReceive(TelemetryPacket &packet) {
  if (!rxReceived) {
    return false;
  }

  rxReceived = false;
  int state = radio.readData((uint8_t*)&packet, sizeof(TelemetryPacket));

  // Reiniciar recepción inmediatamente
  radio.startReceive();

  return (state == RADIOLIB_ERR_NONE);
}

void loraGetMetrics(float &rssi, float &snr) {
  rssi = radio.getRSSI();
  snr = radio.getSNR();
}

bool loraIsTxReady() {
  return txReady;
}
