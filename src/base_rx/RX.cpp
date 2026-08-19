#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <Wire.h>
#include <SSD1306Wire.h>
#include "common_config.hpp"

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

// --- DATOS PARA LA PANTALLA PRINCIPAL ---
volatile int      ectC                 = -1000; // -1000 = sin dato aún
volatile int      oilTempC             = -1000;
volatile float    battVolt             = -1000.0;
volatile uint32_t lastPacketMs         = 0;      // millis() del último paquete válido; 0 = ninguno aún

// Sin paquete en este margen desde el último recibido: se considera que ya
// no llegan (indicador a 0 puntos), aunque se conserve el último RSSI.
static const uint32_t SIGNAL_TIMEOUT_MS = 3000;

// 4 = conexión buena, 1 = pobre, 0 = sin paquetes (nunca llegó ninguno o hace
// más de SIGNAL_TIMEOUT_MS que no llega nada).
static int signalDots(float rssiDbm, bool hasSignal) {
  if (!hasSignal)        return 0;
  if (rssiDbm > -70.0f)  return 4;
  if (rssiDbm > -85.0f)  return 3;
  if (rssiDbm > -100.0f) return 2;
  return 1;
}

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
  float    r    = rssi;
  uint32_t pps  = paquetesPorSegundo;
  int      ect  = ectC;
  int      oil  = oilTempC;
  float    batt = battVolt;
  uint32_t lastPkt = lastPacketMs;

  bool hasSignal = (lastPkt != 0) && (millis() - lastPkt < SIGNAL_TIMEOUT_MS);
  int  dots      = signalDots(r, hasSignal);

  display.clear();
  display.setFont(ArialMT_Plain_10);

  // --- LÍNEA 1 (y=0): dBm + indicador de puntos (izquierda) | p/s (derecha) ---
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  String dbmText = hasSignal ? (String((int)r) + "dBm") : "--dBm";
  display.drawString(0, 0, dbmText);

  // Puntos pegados justo detrás del texto (ancho variable según el número)
  int dotX0 = display.getStringWidth(dbmText) + 5;
  const int dotRadius = 2;
  const int dotStep   = 7;
  const int dotY       = 5;
  for (int i = 0; i < 4; i++) {
    int cx = dotX0 + i * dotStep + dotRadius;
    if (i < dots) display.fillCircle(cx, dotY, dotRadius);
    else          display.drawCircle(cx, dotY, dotRadius);
  }

  display.setTextAlignment(TEXT_ALIGN_RIGHT);
  display.drawString(128, 0, String(pps) + " p/s");
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  // --- LÍNEA 2 (y=13): etiquetas ECT / OIL ---
  display.drawString(0, 13, "ECT");
  display.drawString(68, 13, "OIL");

  // --- LÍNEA 3 (y=23): valores ECT / OIL ---
  display.setFont(ArialMT_Plain_16);
  display.drawString(0, 23, (ect > -1000) ? String(ect) + "C" : "---");
  display.drawString(68, 23, (oil > -1000) ? String(oil) + "C" : "---");

  // --- LÍNEA 4 (y=44): batería, debajo de ECT/OIL, centrada ---
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 44, (batt > -1000.0) ? String(batt, 1) + "V" : "---");
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
  display.drawString(0, 35, "Freq: " + String(LORA_BAND, 1) + " MHz");
  display.drawString(0, 47, "BW: " + String((int)LORA_BW) + " kHz | SF: " + String(LORA_SF));
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
      lastPacketMs = millis();
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

      // --- RSSI/SNR hacia la app (pruebas de antena) ---
      // Pseudo-ID reservado (no es una trama CAN real, ver LORA_METRICS_ID en
      // common_config.hpp); robowin2/core/frames.py lo reconoce y lo enruta a
      // "lora_rssi"/"lora_snr" en vez de intentar decodificarlo con el DBC.
      // Throttled: no aporta nada mandarlo a más frecuencia que el refresco
      // de pantalla y satura la lectura de línea de la app sin necesidad.
      static uint32_t lastMetricsMs = 0;
      if(millis() - lastMetricsMs >= 300) {
        lastMetricsMs = millis();
        int16_t rssi_x10 = (int16_t)(rssi * 10.0f);
        int16_t snr_x10  = (int16_t)(snr * 10.0f);
        uint16_t rssi_u = (uint16_t)rssi_x10;
        uint16_t snr_u  = (uint16_t)snr_x10;
        uint8_t metricsBuf[4] = {
          (uint8_t)(rssi_u & 0xFF), (uint8_t)(rssi_u >> 8),
          (uint8_t)(snr_u & 0xFF),  (uint8_t)(snr_u >> 8)
        };
        Serial.print(LORA_METRICS_ID, HEX);
        for(int i = 0; i < 4; i++) {
          Serial.print(",");
          if(metricsBuf[i] < 0x10) Serial.print("0");
          Serial.print(metricsBuf[i], HEX);
        }
        Serial.println();
      }

      // Todo este bloque no se puede quitar

      // --- Decodificar datos para la pantalla principal ---
      // El laptimer (0x777) ya no se decodifica aquí: el OLED de la base no
      // muestra tiempos de vuelta (ver ROBOWIN2 para eso). El frame sigue
      // reenviándose por serie sin tocar, arriba, para que la app lo procese.
      if(packet.canId == 929 && packet.len >= 6) {
        // DBC engine_temp (0x3A1): ect en bytes 2-3, oil_temp en bytes 4-5
        // (little-endian, 1 C/LSB, sin offset)
        ectC     = (int)((uint16_t)packet.data[2] | ((uint16_t)packet.data[3] << 8));
        oilTempC = (int)((uint16_t)packet.data[4] | ((uint16_t)packet.data[5] << 8));
      }
      else if(packet.canId == 933 && packet.len >= 2) {
        // DBC engine_misc (0x3A5 / 933): batt_volt en bytes 0-1 (little-endian)
        // Ahora el emisor manda centésimas (0.01 V/LSB), convertir a V.
        uint16_t raw = (uint16_t)packet.data[0] | ((uint16_t)packet.data[1] << 8);
        battVolt = ((float)raw) * 0.01f;
        // Debug: mostrar raw y voltaje calculado por Serial
        Serial.printf("[RX] CAN 0x%03X batt raw=%u -> %.2fV\n", packet.canId, (unsigned)raw, battVolt);
      }

    } else {
      paquetesCorruptos++;
    }

    radio.startReceive();
  }
}
