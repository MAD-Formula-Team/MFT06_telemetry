#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

// --- PINES (Mismos que TX) ---
#define LORA_NSS 8
#define LORA_DIO1 14
#define LORA_RST 12
#define LORA_BUSY 13
#define LORA_SCK 9
#define LORA_MISO 11
#define LORA_MOSI 10

// --- ESTRUCTURA BINARIA (Idéntica al TX) ---
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId;
  uint16_t canId;
  uint8_t  len;
  uint8_t  data[8];
} packet;

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);

volatile bool rxFlag = false;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  rxFlag = true;
}

void setup() {
  Serial.begin(921600); // IMPORTANTE: Ajusta tu Monitor Serie a esta velocidad
  
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  
  // MISMA CONFIGURACIÓN QUE TX
  int state = radio.begin(868.0, 500.0, 7, 5, 0x12, 22);
  
  radio.setDio1Action(setFlag);
  
  // Empezar a escuchar
  radio.startReceive();
}

void loop() {
  if(rxFlag) {
    rxFlag = false;
    
    // Leemos los datos binarios en la estructura
    int state = radio.readData((uint8_t*)&packet, sizeof(packet));

    if (state == RADIOLIB_ERR_NONE) {
      // --- CONVERSIÓN A CSV PARA TU SOFTWARE DE PC ---
      // Reconstruimos el formato: ID, CAN_ID, BYTES...
      
      Serial.print(packet.packetId);
      Serial.print(",");
      Serial.print(packet.canId, HEX);
      
      for(int i=0; i<packet.len; i++) {
        Serial.print(",");
        // Formato hex limpio (ej. 0A en vez de A)
        if(packet.data[i] < 0x10) Serial.print("0");
        Serial.print(packet.data[i], HEX);
      }
      
      // Diagnóstico (Opcional, quítalo si molesta a tu Python)
      Serial.print(" | RSSI:");
      Serial.print(radio.getRSSI());
      Serial.println();
      
    }
    
    // Volver a escuchar inmediatamente
    radio.startReceive();
  }
}