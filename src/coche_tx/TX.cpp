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

// void taskCAN(void *pvParameters){
//   Serial.begin(921600);

//   // 1. INICIALIZAR CAN
//   SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
//   if(CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
//     CAN0.setMode(MCP_NORMAL);
//     Serial.println("[CAN] OK");
//   } else {
//     Serial.println("[CAN] FALLO");
//     while(1);
//   }
//   for(;;) {
//     if(CAN0.checkReceive() == CAN_MSGAVAIL) {
//       long unsigned int rxId;
//       unsigned char     len;
//       unsigned char     rxBuf[8];

//       CAN0.readMsgBuf(&rxId, &len, rxBuf);
//       
//       // Filtrar ID 0x3A4: solo enviar cada 10 mensajes
//       if(rxId == 0x3A4) {
//         contador3A4++;
//         if(contador3A4 < 20) {
//           continue; // Ignorar este mensaje
//         }
//         contador3A4 = 0; // Resetear contador
//       }
//       
//       if(txReady) {
//         txReady = false; 

//         packet.canId = rxId;
//         packet.len = len;
//         memcpy(packet.data, rxBuf, 8); 

//         if(xQueueSend(colaLoRa, &packet, 0) != pdTRUE) {
//           Serial.println("[ERROR] No se pudo enviar a la cola LoRa");
//         }

//       } else {
//         txReady = true; 
//       }
//     }
//   }
// }

void setup() {
  // Crear la cola ANTES de lanzar las tareas
  colaLoRa = xQueueCreate(COLA_SIZE, sizeof(TelemetryPacket));
  if(colaLoRa == NULL) {
    Serial.println("[ERROR] No se pudo crear la cola LoRa");
    while(1);
  }
  
  Serial.begin(921600);

  // Inicializar CAN en el setup
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
  if(CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
    CAN0.setMode(MCP_NORMAL);
    Serial.println("[CAN] OK");
  } else {
    Serial.println("[CAN] FALLO");
    while(1);
  }

  // Solo lanzar tarea LoRa, CAN ahora corre en loop()
  xTaskCreatePinnedToCore(taskLoRa,"TaskLoRa",4096,NULL,2,NULL,0);
  //xTaskCreatePinnedToCore(taskCAN,"TaskCAN",4096,NULL,1,NULL,1);
  Serial.println("[SYSTEM] Task LoRa lanzada");
}

void loop() {
  // Ahora el CAN se maneja en el loop() en lugar de taskCAN
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    long unsigned int rxId;
    unsigned char     len;
    unsigned char     rxBuf[8];

    CAN0.readMsgBuf(&rxId, &len, rxBuf);
    
    // Filtrar ID 0x3A4: solo enviar cada 20 mensajes
    if(rxId == 0x3A4) {
      contador3A4++;
      if(contador3A4 < 20) {
        return; // Salir del loop, no enviar este mensaje
      }
      contador3A4 = 0; // Resetear contador
    }
    
    // Enviar a la cola LoRa
    packet.canId = rxId;
    packet.len = len;
    memcpy(packet.data, rxBuf, 8); 

    if(xQueueSend(colaLoRa, &packet, 0) != pdTRUE) {
      // Cola llena, descartamos el paquete silenciosamente
    }
  }
}
