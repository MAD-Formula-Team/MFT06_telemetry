#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <Wire.h>
#include <SSD1306Wire.h>
#include "common_config.h"

// --- OBJETO DISPLAY ---
SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);

// --- MÉTRICAS DE SEÑAL ---
volatile uint32_t paquetesRecibidos  = 0;
volatile uint32_t paquetesCorruptos  = 0;
volatile float    rssi               = 0;
volatile float    snr                = 0;
volatile uint32_t paquetesPorSegundo = 0;
volatile uint32_t contadorTemporal   = 0;
volatile unsigned long tiempoSegundo = 0;

SemaphoreHandle_t mutexDisplay;

// TODO QUITAR LOS CAMPOS QUE NO SE USAN PARA AHORRAR ANCHO DE BANDA (ej. packetId)
TelemetryPacket packet;

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);

volatile bool rxReceived = false;

ICACHE_RAM_ATTR void setFlag(void) {
  rxReceived = true;
}

// ================================================================
// OLED: Funciones de pantalla
// ================================================================

void iniciarOLED() {
  pinMode(OLED_VEXT, OUTPUT);
  digitalWrite(OLED_VEXT, LOW);  
  delay(100);

  pinMode(OLED_RST, OUTPUT);
  digitalWrite(OLED_RST, LOW);
  delay(20);
  digitalWrite(OLED_RST, HIGH);

  display.init();
  display.flipScreenVertically();
  display.setFont(ArialMT_Plain_10);
  display.clear();
  display.display();
}

void actualizarOLED() {
  if(millis() - tiempoSegundo >= 1000) {
    paquetesPorSegundo = contadorTemporal;
    contadorTemporal   = 0;
    tiempoSegundo      = millis();
  }

  // Captura local de volátiles para consistencia durante el dibujado
  uint32_t rx  = paquetesRecibidos;
  uint32_t err = paquetesCorruptos;
  float    r   = rssi;
  float    s   = snr;
  uint32_t pps = paquetesPorSegundo;

  display.clear();

  // --- LÍNEA 1: Contadores ---
  display.setFont(ArialMT_Plain_10);
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.drawString(0, 0, "RX:" + String(rx));
  display.drawString(55, 0, "ERR:" + String(err));

  display.setTextAlignment(TEXT_ALIGN_RIGHT);
  display.drawString(128, 0, String(pps) + "/s");
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  // --- LÍNEA 2: RSSI grande ---
  display.setFont(ArialMT_Plain_16);
  display.drawString(0, 12, String((int)r) + " dBm");

  display.setFont(ArialMT_Plain_10);
  display.drawString(75, 16, "SNR:" + String(s, 1));

  // --- LÍNEA 3: Barra RSSI ---
  int barraRSSI = map(constrain((int)r, -120, -30), -120, -30, 0, 100);
  display.drawProgressBar(0, 28, 120, 8, barraRSSI);

  // --- LÍNEA 4: Calidad de señal ---
  String calidad;
  if(r > -70)       calidad = "EXCELENTE";
  else if(r > -85)  calidad = "BUENA";
  else if(r > -100) calidad = "MEDIA";
  else if(r > -115) calidad = "DEBIL";
  else              calidad = "MUY DEBIL";

  if(s < 0 && r > -100) calidad = "RUIDOSA";

  display.setFont(ArialMT_Plain_16);
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 48, calidad);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  display.display();
}

// ================================================================
// OLED
// ================================================================
void taskOLED(void *pvParameters) {
  for(;;) {
    if(xSemaphoreTake(mutexDisplay, pdMS_TO_TICKS(50)) == pdTRUE) {
      actualizarOLED();
      xSemaphoreGive(mutexDisplay);
    }

    // Dormir 250ms
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}

// ================================================================
// SETUP
// ================================================================
void setup() {
  iniciarOLED();

  // Pantalla de inicio
  display.clear();
  display.setFont(ArialMT_Plain_16);
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 0, "MADFT06 RX");
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 22, "Iniciando sistema...");
  display.drawString(0, 35, "Freq: 869.5 MHz");
  display.drawString(0, 47, "BW: 125 kHz | SF: 7");
  display.display();
  delay(2000);

  Serial.begin(921600);
  delay(1000);
  Serial.println("--- BASE STATION LISTA ---");
  Serial.printf("[Sistema] Corriendo en Core: %d\n", xPortGetCoreID());

  // Inicializar LoRa
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  radio.setDio1Action(setFlag);

  if(state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] Receptor listo");

    display.clear();
    display.setFont(ArialMT_Plain_16);
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.drawString(64, 20, "LISTO");
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.setFont(ArialMT_Plain_10);
    display.drawString(0, 50, "Esperando datos...");
    display.display();
    delay(1000);

    radio.startReceive();
    tiempoSegundo = millis();

  } else {
    Serial.print("[LoRa] Fallo Radio: ");
    Serial.println(state);

    display.clear();
    display.setFont(ArialMT_Plain_16);
    display.drawString(0, 20, "ERROR RADIO");
    display.setFont(ArialMT_Plain_10);
    display.drawString(0, 40, "Codigo: " + String(state));
    display.display();

    while(1);
  }

  // Crear mutex para el display
  mutexDisplay = xSemaphoreCreateMutex();
  if(mutexDisplay == NULL) {
    Serial.println("[ERROR] No se pudo crear mutex OLED");
    while(1);
  }

  // Lanzar task OLED 
  xTaskCreatePinnedToCore(
    taskOLED,     // Función
    "TaskOLED",   // Nombre debug
    3072,         // Stack bytes
    NULL,         // Parámetros
    1,            // Prioridad
    NULL,         // Handle
    0             // ← CORE 0
  );

  Serial.println("[OLED] Task lanzado en Core 0");
}

// ================================================================
// LOOP - LoRa
// ================================================================
void loop() {
  if(rxReceived) {
    rxReceived = false;

    int state = radio.readData((uint8_t*)&packet, sizeof(packet));

    if(state == RADIOLIB_ERR_NONE) {
      rssi = radio.getRSSI();
      snr  = radio.getSNR();
      paquetesRecibidos++;
      contadorTemporal++;

      // No quitar, esto se usa para que la UI lea los datos
      Serial.print(packet.canId, HEX);

      for(int i = 0; i < packet.len; i++) {
        Serial.print(",");
        if(packet.data[i] < 0x10) Serial.print("0");
        Serial.print(packet.data[i], HEX);
      }
      Serial.println();
      
      // Todo este bloque no se puede quitar

    } else {
      paquetesCorruptos++;
    }

    radio.startReceive();
  }
}