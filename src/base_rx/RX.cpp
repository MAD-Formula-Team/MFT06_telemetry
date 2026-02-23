/**
 * TELEMETRÍA MADFT06 - RECEPTOR (BASE) - VERSION F2 (Dual-Core)
 * Hardware: Heltec V3
 * Función: Recibe Binario -> Convierte a CSV para PC + Monitoreo OLED
 * 
 * Core 1: Recepción LoRa + Serial (loop principal)
 * Core 0: Refresco OLED cada 250ms
 */
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <Wire.h>
#include <SSD1306Wire.h>

// --- PINES LORA ---
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// valores lora
#define LORA_BAND    869.5   // MHz
#define LORA_SF      7
#define LORA_BW      125.0   // kHz
#define LORA_CR      7       // 4/7
#define LORA_PREAMBLE 8      // símbolos
#define LORA_POWER   22      // dBm


// Pines OLED
#define OLED_SDA    17
#define OLED_SCL    18
#define OLED_RST    21
#define Vext        36

// --- OBJETO DISPLAY ---
SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);

// --- MÉTRICAS DE SEÑAL ---
// Usamos volatile para las variables compartidas entre cores
volatile uint32_t paquetesRecibidos  = 0;
volatile uint32_t paquetesCorruptos  = 0;
volatile float    rssi               = 0;
volatile float    snr                = 0;

// Tasa de paquetes por segundo
volatile uint32_t paquetesPorSegundo = 0;
volatile uint32_t contadorTemporal   = 0;
volatile unsigned long tiempoSegundo = 0;

// --- MUTEX para proteger acceso al display desde Core 0 ---
SemaphoreHandle_t mutexDisplay;

// --- ESTRUCTURA DE DATOS (DEBE SER IDÉNTICA AL TX) ---
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId;
  uint16_t canId;
  uint8_t  len;
  uint8_t  data[8];
} packet;

// --- OBJETOS RADIO ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);

// --- BANDERA DE INTERRUPCIÓN ---
volatile bool rxReceived = false;

ICACHE_RAM_ATTR void setFlag(void) {
  rxReceived = true;
}

// ================================================================
// OLED: Funciones de pantalla
// ================================================================

void iniciarOLED() {
    // 1. Encender alimentación de la pantalla (IMPORTANTE en V3)
    pinMode(Vext, OUTPUT);
    digitalWrite(Vext, LOW);  // LOW = encendido
    delay(100);

    // 2. Reset de la pantalla
    pinMode(OLED_RST, OUTPUT);
    digitalWrite(OLED_RST, LOW);
    delay(20);
    digitalWrite(OLED_RST, HIGH);

    // 3. Inicializar display
    display.init();

    // 4. Voltear pantalla (para que se vea bien)
    display.flipScreenVertically();

    // 5. Configurar fuente por defecto
    display.setFont(ArialMT_Plain_10);

    // 6. Limpiar pantalla
    display.clear();
    display.display();
}

void actualizarOLED() {
  // Calcular PPS aquí (se llama cada 250ms desde Core 0)
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

  // --- LÍNEA 1: Contador de paquetes (0-10px) ---
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 0, "RX:" + String(paquetesRecibidos));
  display.drawString(55, 0, "ERR:" + String(paquetesCorruptos));

  // PPS en la esquina derecha
  display.setTextAlignment(TEXT_ALIGN_RIGHT);
  display.drawString(128, 0, String(pps) + "/s");
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  // --- LÍNEA 2: RSSI (12-26px) ---
  display.setFont(ArialMT_Plain_16);
  display.drawString(0, 12, String((int)rssi) + " dBm");

  // SNR a la derecha de RSSI
  display.setFont(ArialMT_Plain_10);
  display.drawString(75, 16, "SNR:" + String(snr, 1));

  // --- LÍNEA 3: Barra visual de RSSI (28-38px) ---
  int barraRSSI = map(constrain(rssi, -120, -30), -120, -30, 0, 100);
  display.drawProgressBar(0, 28, 120, 8, barraRSSI);

  // --- LÍNEA 4: Estado de calidad CENTRADO (40-63px) ---
  String calidad;
  if(rssi > -70) {
    calidad = "EXCELENTE";
  } else if(rssi > -85) {
    calidad = "BUENA";
  } else if(rssi > -100) {
    calidad = "MEDIA";
  } else if(rssi > -115) {
    calidad = "DEBIL";
  } else {
    calidad = "MUY DEBIL";
  }

  // Calidad también depende del SNR
  if(snr < 0 && rssi > -100) {
    calidad = "RUIDOSA";
  }

  // Estado centrado y grande
  display.setFont(ArialMT_Plain_16);
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 48, calidad);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  display.display();

  // --- CALCULAR PPS (Paquetes Por Segundo) ---
  if(millis() - tiempoSegundo >= 1000) {
    paquetesPorSegundo = contadorTemporal;
    contadorTemporal = 0;
    tiempoSegundo = millis();
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

  // MISMA CONFIG QUE TX: BW 500.0, SF 7
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  radio.setDio1Action(setFlag);

  if(state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] Receptor listo");

    // Pantalla de confirmación
    display.clear();
    display.setFont(ArialMT_Plain_16);
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.drawString(64, 20, "LISTO");
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.setFont(ArialMT_Plain_10);
    display.drawString(0, 50, "Esperando datos...");
    display.display();
    delay(1000);

    // Empezamos a escuchar
    radio.startReceive();

    // Inicializar timer para PPS
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

  // Lanzar task OLED en Core 0
  // Prioridad 1 (igual que loop), stack 3KB suficiente para el display
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
// LOOP - CORE 1: 100% dedicado a recepción LoRa + Serial
// ================================================================
void loop() {
  if(rxReceived) {
    rxReceived = false;

    int state = radio.readData((uint8_t*)&packet, sizeof(packet));

    if(state == RADIOLIB_ERR_NONE) {
      // Actualizar métricas (volatile, acceso atómico en ESP32 para 32bit)
      rssi = radio.getRSSI();
      snr  = radio.getSNR();
      paquetesRecibidos++;
      contadorTemporal++;

      Serial.print("t"); // Inicio de trama estándar

      // ID (Debe ser siempre 3 caracteres hexadecimales)
      // Ejemplo: ID 0x1A -> "01A"
      if (packet.canId < 0x100) Serial.print("0");
      if (packet.canId < 0x10)  Serial.print("0");
      Serial.print(packet.canId, HEX);

      for(int i = 0; i < packet.len; i++) {
        Serial.print(",");
        if(packet.data[i] < 0x10) Serial.print("0");
        Serial.print(packet.data[i], HEX);
      }

      // Terminador (Retorno de carro, vital para python-can)
      Serial.write('\r');

    } else {
      paquetesCorruptos++;
    }

    // Volver a escuchar inmediatamente
    radio.startReceive();
  }

  // --- ACTUALIZAR PANTALLA CADA 250ms ---
  if(millis() - ultimaActualizacion > 250) {
    ultimaActualizacion = millis();
    actualizarOLED();
  }
}
