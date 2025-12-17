/**
 * TELEMETRÍA MADFT06 - TRANSMISOR (COCHE) - VERSION F1 (Low Latency)
 * Hardware: Heltec V3 + MCP2515
 * Protocolo: Binario Raw + Drop Strategy
 */
#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>
#include <RadioLib.h>

// --- CONFIGURACIÓN DE PINES ---
// LoRa (Heltec V3 Interno)
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// CAN (MCP2515 Externo)
#define CAN_CS      34
#define CAN_SCK     36
#define CAN_MISO    33
#define CAN_MOSI    35

// --- ESTRUCTURA DE DATOS (BINARIA COMPACTA) ---
// Total: 15 Bytes (vs ~40 Bytes en texto)
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId; // 4 bytes
  uint16_t canId;    // 2 bytes
  uint8_t  len;      // 1 byte
  uint8_t  data[8];  // 8 bytes
} packet;

// --- OBJETOS ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

// --- VARIABLES DE CONTROL ---
volatile bool txReady = true; // Semáforo para saber si la radio está libre
uint32_t globalCounter = 0;

// Interrupción: Se dispara cuando la radio termina de enviar
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  txReady = true;
}

void setup() {
  // VELOCIDAD ALTA PARA DEBUG
  Serial.begin(921600);
  delay(1000);

  // 1. INICIALIZAR CAN
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
  // ¡IMPORTANTE! Si tu cristal es de 16MHz, cambia MCP_8MHZ por MCP_16MHZ abajo:
  if(CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) == CAN_OK) {
    CAN0.setMode(MCP_NORMAL);
    Serial.println("[CAN] Hardware OK.");
  } else {
    Serial.println("[CAN] FALLO DE HARDWARE.");
    while(1);
  }

  // 2. INICIALIZAR LORA (MODO VELOCIDAD)
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  
  // Parametros: Freq 868.0, BW 500.0, SF 7, CR 5 (4/5), SyncWord 0x12, Pwr 22dBm
  // BW 500 + SF 7 = La configuración más rápida posible en LoRa
  int state = radio.begin(868.0, 500.0, 7, 5, 0x12, 22);
  
  // Asignamos la función de interrupción
  radio.setDio1Action(setFlag);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] Hardware OK (Modo F1).");
  } else {
    Serial.print("[LoRa] Fallo código: ");
    Serial.println(state);
    while(1);
  }
}

void loop() {
  // 1. LEER CAN (SIEMPRE, para vaciar buffer)
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    long unsigned int rxId;
    unsigned char len;
    unsigned char rxBuf[8];
    
    CAN0.readMsgBuf(&rxId, &len, rxBuf);

    // 2. ENVIAR SOLO SI LA RADIO ESTÁ LIBRE (Estrategia "Drop")
    if(txReady) {
      txReady = false; // Marcamos ocupado
      
      // Llenamos la estructura binaria
      packet.packetId = globalCounter++;
      packet.canId = (uint16_t)rxId;
      packet.len = len;
      memcpy(packet.data, rxBuf, 8); // Copia rápida de memoria

      // Enviamos (Non-blocking)
      radio.startTransmit((uint8_t*)&packet, sizeof(packet));
      
      // Feedback mínimo (un punto)
      Serial.print("."); 
    }
    // Si txReady es false, ignoramos el paquete para no crear cola (LAG CERO)
  }
}