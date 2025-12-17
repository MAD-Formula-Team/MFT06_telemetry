#include <Arduino.h>
#include <RadioLib.h>
#include <SPI.h>

/*
 * TELEMETRÍA MADFT06 - RECEPTOR (GROUND STATION)
 * Hardware: Heltec WiFi LoRa 32 V3
 * Función: Recibir paquetes CSV y mostrar calidad de enlace.
 */

// --- PINES LORA (Heltec V3) ---
#define LORA_NSS    8
#define LORA_SCK    9
#define LORA_MOSI   10
#define LORA_MISO   11
#define LORA_RST    12
#define LORA_DIO1   14
#define LORA_BUSY   13 

// --- OBJETOS ---
// Usamos un bus SPI dedicado igual que en el emisor para máxima compatibilidad
SPIClass loraSPI(HSPI); 
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n--- INICIANDO ESTACIÓN DE TIERRA (RX) ---");

  // 1. INICIALIZAR SPI
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);

  // 2. INICIALIZAR LORA
  // IMPORTANTE: Estos valores DEBEN ser idénticos al Transmisor
  // Freq: 868.0 MHz, BW: 125.0 kHz, SF: 9, CR: 4/7, SyncWord: 0x12
  Serial.print("[LoRa] Iniciando Radio... ");
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 22);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("EXITO!");
  } else {
    Serial.print("FALLO, código: ");
    Serial.println(state);
    while (true);
  }
}

void loop() {
  // Buffer para el paquete recibido
  String str;
  
  // Escuchamos (bloqueante o con interrupción, usamos simple receive por ahora)
  int state = radio.receive(str);

  if (state == RADIOLIB_ERR_NONE) {
    // --- PAQUETE RECIBIDO ---
    
    // 1. Imprimir los datos crudos (CSV)
    Serial.print("RX >> ");
    Serial.print(str);
    
    // 2. Imprimir Diagnóstico de Señal (CRÍTICO para Telemetría)
    // RSSI: Potencia de señal (dBm). 
    //       > -100 excelente. 
    //       < -120 riesgo de pérdida.
    Serial.print(" | RSSI: ");
    Serial.print(radio.getRSSI());
    Serial.print(" dBm");
    
    // SNR: Relación Señal/Ruido. 
    //      Positivo es perfecto. 
    //      Negativo (ej: -10) es aceptable en LoRa (señal bajo el ruido).
    Serial.print(" | SNR: ");
    Serial.print(radio.getSNR());
    Serial.println(" dB");

  } else if (state == RADIOLIB_ERR_RX_TIMEOUT) {
    // Tiempo de espera agotado (normal si el coche no envía nada)
    // No imprimimos nada para no ensuciar el log
  } else {
    // Algún error de recepción (CRC, Header, etc.)
    Serial.print("[LoRa] Error RX: ");
    Serial.println(state);
  }
}