#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>
#include <RadioLib.h>
#include "common_config.h"


#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif

int contador3A4 = 0;
volatile bool txReady = true;

QueueHandle_t colaLoRa;
#define COLA_SIZE 32

// --- OBJETOS RADIO Y CAN ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

// --- ISR LoRa ---
ICACHE_RAM_ATTR void setFlag(void) {
  txReady = true;
}

TelemetryPacket packet;

void taskLoRa(void *pvParameters) {
  TelemetryPacket packet;
  
  // Inicializar LoRa 
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  radio.setDio1Action(setFlag);
  
  if(state != RADIOLIB_ERR_NONE) {
    Serial.printf("[LoRa] Error init: %d\n", state);
    vTaskDelete(NULL);
    return;
  }
  Serial.println("[LoRa] Task OK en Core 0");

  for(;;) {
    // Espera bloqueante: duerme hasta que llegue algo a la cola
    // Timeout 100ms para no quedarse colgado para siempre
    if(xQueueReceive(colaLoRa, &packet, pdMS_TO_TICKS(100)) == pdTRUE) {
      
      // Esperar a que la radio esté libre (con timeout de seguridad)
      uint32_t timeout = millis();
      while(!txReady && (millis() - timeout < 500)) {
        vTaskDelay(1); // Ceder CPU mientras espera, no busy-wait
      }
      
      if(txReady) {
        txReady = false;
        radio.startTransmit((uint8_t*)&packet, sizeof(packet));
      } else {
        txReady = true; // Reset forzado
      }
    }
  }
}


void setup() {
  Serial.begin(921600);

  // 1. INICIALIZAR CAN
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
  if(CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
    CAN0.setMode(MCP_NORMAL);
    Serial.println("[CAN] OK");
  } else {
    Serial.println("[CAN] FALLO");
    while(1);
  }

  // 2. INICIALIZAR LORA 
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  radio.setDio1Action(setFlag);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] OK .");
    Serial.println("[CAN] Esperando mensajes CAN...\n");
  } else {
    Serial.print("[LoRa] Fallo código: ");
    Serial.println(state);
    while(1);
  }
}

void loop() {
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    long unsigned int rxId;
    unsigned char len;
    unsigned char rxBuf[8];

    CAN0.readMsgBuf(&rxId, &len, rxBuf);

    uint16_t canId = (uint16_t)rxId;


    // if((canId == 0x3A4) && ( contador3A4 >= 20)) {
    //   contador3A4 = 0; // Reiniciar contador
    // } else if (canId == 0x3A4) {
    //   contador3A4++;
    //   return; }

    if (canId != 0x3A3) {
        return; // Ignorar este mensaje
    }
    if(txReady) {
      txReady = false; // Marcamos ocupado

      packet.canId = canId;
      packet.len = len;
      memcpy(packet.data, rxBuf, 8); 

      radio.startTransmit((uint8_t*)&packet, sizeof(packet));

    } else {
      txReady = true; // Reset forzado
    }
  }
}
