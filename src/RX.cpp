/**
 * TELEMETRÍA MADFT06 - RECEPTOR (BASE) - VERSION F1
 * Hardware: Heltec V3
 * Función: Recibe Binario -> Convierte a CSV para PC
 */
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

// --- PINES LORA ---
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// --- ESTRUCTURA DE DATOS (DEBE SER IDÉNTICA AL TX) ---
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId;
  uint16_t canId;
  uint8_t  len;
  uint8_t  data[8];
} packet;

// --- OBJETOS ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);

// Bandera de interrupción
volatile bool rxReceived = false;

// Interrupción al recibir
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  rxReceived = true;
}

void setup() {
  // VELOCIDAD ALTA (Ajusta tu monitor serie a esto)
  Serial.begin(921600);
  delay(1000);
  Serial.println("--- BASE ESTATION LISTA ---");

  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  
  // MISMA CONFIG QUE TX: BW 500.0, SF 7
  int state = radio.begin(868.0, 500.0, 7, 5, 0x12, 22);
  
  radio.setDio1Action(setFlag);

  if (state == RADIOLIB_ERR_NONE) {
    // Empezamos a escuchar
    radio.startReceive();
  } else {
    Serial.print("Fallo Radio: ");
    Serial.println(state);
    while(1);
  }
}

void loop() {
  if(rxReceived) {
    rxReceived = false; // Reset flag

    // Leemos el paquete binario
    int state = radio.readData((uint8_t*)&packet, sizeof(packet));

    if (state == RADIOLIB_ERR_NONE) {
      // --- CONVERSIÓN A CSV (Para que RoboWin.py lo entienda) ---
      // Formato: packetID, CAN_ID, Byte0, Byte1, ...
      
      Serial.print(packet.packetId);
      Serial.print(",");
      Serial.print(packet.canId, HEX);
      
      for(int i=0; i<packet.len; i++) {
        Serial.print(",");
        // Formateo bonito (0A en vez de A)
        if(packet.data[i] < 0x10) Serial.print("0");
        Serial.print(packet.data[i], HEX);
      }
      // Salto de línea para terminar el paquete
      Serial.println(); 
      
    } else {
        // Error de CRC (paquete corrupto), lo ignoramos silenciosamente
    }

    // Volvemos a escuchar inmediatamente
    radio.startReceive();
  }
}