#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>
#include <RadioLib.h>

// --- PINES ---
#define LORA_NSS 8
#define LORA_DIO1 14
#define LORA_RST 12
#define LORA_BUSY 13
#define LORA_SCK 9
#define LORA_MISO 11
#define LORA_MOSI 10

#define CAN_CS 34
#define CAN_SCK 36
#define CAN_MISO 33
#define CAN_MOSI 35

// --- ESTRUCTURA DE DATOS BINARIA (14 Bytes) ---
// Enviar esto es 3 veces más rápido que enviar String
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId; // 4 bytes
  uint16_t canId;    // 2 bytes (Suficiente para ID estándar)
  uint8_t  len;      // 1 byte
  uint8_t  data[8];  // 8 bytes
} packet;

// --- OBJETOS ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

// --- VARIABLES ---
volatile bool txDone = true;
uint32_t counter = 0;

// Interrupción
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  txDone = true;
}

void setup() {
  // VELOCIDAD SERIAL MAXIMA para depuración
  Serial.begin(921600);
  
  // 1. CAN
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
  if(CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) == CAN_OK) { // ¡REVISA TU CRISTAL!
    CAN0.setMode(MCP_NORMAL);
  } else {
    while(1); // Fallo hardware
  }

  // 2. LORA - CONFIGURACIÓN "F1" (Max Speed)
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  
  // Freq: 868.0
  // BW: 500.0 (Máximo ancho de banda = Menor tiempo de aire)
  // SF: 7 (Spread Factor mínimo = Mayor velocidad)
  // CR: 5 (4/5 = Mínima redundancia, corrección de errores básica)
  int state = radio.begin(868.0, 500.0, 7, 5, 0x12, 22);
  
  radio.setDio1Action(setFlag);

  if (state != RADIOLIB_ERR_NONE) {
    while(1);
  }
}

void loop() {
  // Leer CAN constantemente
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    long unsigned int rxId;
    unsigned char len;
    unsigned char rxBuf[8];
    
    CAN0.readMsgBuf(&rxId, &len, rxBuf);

    // Si la radio está libre, enviamos el binario
    if(txDone) {
      txDone = false; // Marcamos ocupado

      // Llenamos la estructura (Super rápido)
      packet.packetId = counter++;
      packet.canId = (uint16_t)rxId;
      packet.len = len;
      memcpy(packet.data, rxBuf, 8); // Copia de memoria directa

      // Enviamos raw bytes (tamaño fijo de 15 bytes aprox)
      // Tiempo de aire estimado: ~4ms
      radio.startTransmit((uint8_t*)&packet, sizeof(packet));
      
      // Feedback visual mínimo (un punto) para no frenar el micro
      Serial.write('.'); 
    }
  }
}