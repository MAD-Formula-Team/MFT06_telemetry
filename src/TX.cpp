#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>
#include <RadioLib.h>

/* * TELEMETRÍA MADFT06 - LECTOR Y TRANSMISOR
 * Objetivo: Leer CAN Bus, mostrar datos en pantalla y enviarlos por LoRa.
 */

// --- PINES ---
#define LORA_NSS    8
#define LORA_SCK    9
#define LORA_MOSI   10
#define LORA_MISO   11
#define LORA_RST    12
#define LORA_DIO1   14
#define LORA_BUSY   13 

#define CAN_CS      34
#define CAN_MOSI    35
#define CAN_MISO    33
#define CAN_SCK     36
// Nota: En modo polling no usamos el pin INT, leemos directamente del chip.

// --- OBJETOS ---
SPIClass loraSPI(HSPI); 
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS); 

// --- VARIABLES ---
bool hardwareReady = false;
long unsigned int rxId;
unsigned char len = 0;
unsigned char rxBuf[8];
uint32_t packetCounter = 0;
unsigned long lastHeartbeat = 0;

void setup() {
  Serial.begin(115200);
  delay(2000); // Esperamos 2s para que te dé tiempo a abrir el monitor
  Serial.println("\n\n--- INICIANDO SISTEMA DE LECTURA CAN ---");

  // 1. INICIALIZAR SPI GLOBAL (CAN)
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

  // 2. INICIALIZAR MCP2515
  // IMPORTANTE: Ajusta MCP_8MHZ o MCP_16MHZ según lo que ponga en tu cristal plateado
  if(CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) == CAN_OK) {
    Serial.println("[CAN]  Hardware OK -> Escuchando a 500kbps...");
    CAN0.setMode(MCP_NORMAL);
    hardwareReady = true;
  } else {
    Serial.println("[CAN]  FALLO: No se detecta el módulo MCP2515.");
    Serial.println("       -> Revisa: 5V, Cables SPI, Jumper de Terminación.");
    hardwareReady = false;
  }

  // 3. INICIALIZAR LORA
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 22);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] Hardware OK -> Radio lista.");
  } else {
    Serial.print("[LoRa] FALLO código: "); Serial.println(state);
  }
  
  Serial.println("------------------------------------------------");
  Serial.println("ID (HEX)\tDLC\tDATOS (HEX)\t\tESTADO TX");
  Serial.println("------------------------------------------------");
}

void loop() {
  if (!hardwareReady) return;

  // --- LECTURA CAN (POLLING) ---
  // Preguntamos al chip: "¿Tienes mensajes nuevos?"
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    
    // Leemos el mensaje
    byte readStatus = CAN0.readMsgBuf(&rxId, &len, rxBuf);
    
    if(readStatus == CAN_OK) {
        // 1. VISUALIZAR EN PANTALLA (Lo que pediste)
        Serial.print("0x");
        Serial.print(rxId, HEX);
        Serial.print("\t\t");
        Serial.print(len);
        Serial.print("\t");
        
        // Construimos el paquete para LoRa
        String packet = String(packetCounter++) + "," + String(rxId, HEX);
        
        for(int i = 0; i<len; i++){
          if(rxBuf[i] < 0x10) { Serial.print("0"); packet += ",0"; } // Cero a la izquierda estético
          else { packet += ","; }
          
          Serial.print(rxBuf[i], HEX);
          Serial.print(" ");
          
          packet += String(rxBuf[i], HEX);
        }

        // 2. ENVIAR POR LORA
        int state = radio.startTransmit(packet); // Usamos startTransmit (No bloqueante)
        
        if (state == RADIOLIB_ERR_NONE) {
           Serial.println("\t-> Enviando..."); 
        } else {
           Serial.print("\t-> Error LoRa: "); Serial.println(state);
        }
    }
  }
  
  // Heartbeat: Imprime un punto cada segundo si no hay tráfico CAN
  // Para que sepas que el ESP32 no se ha colgado.
  if (millis() - lastHeartbeat > 1000) {
    if(CAN0.checkReceive() != CAN_MSGAVAIL) Serial.print("."); 
    lastHeartbeat = millis();
  }
}