/**
 * TELEMETRÍA MADFT06 - RECEPTOR (BASE) - VERSION F1
 * Hardware: Heltec V3
 * Función: Recibe Binario -> Convierte a CSV para PC + Monitoreo OLED
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
#define Vext        36  // Pin de alimentación de la pantalla

// Crear objeto display
SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);

// --- MÉTRICAS DE SEÑAL ---
uint32_t paquetesRecibidos = 0;
uint32_t paquetesCorruptos = 0;
float rssi = 0;
float snr = 0;
unsigned long ultimaActualizacion = 0;

// Tasa de paquetes por segundo
uint32_t paquetesPorSegundo = 0;
uint32_t contadorTemporal = 0;
unsigned long tiempoSegundo = 0;

// --- ESTRUCTURA DE DATOS (DEBE SER IDÉNTICA AL TX) ---
struct __attribute__((packed)) TelemetryPacket {
  //uint32_t packetId;
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
  display.clear();
  
  // --- LÍNEA 1: Contador de paquetes (0-10px) ---
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 0, "RX:" + String(paquetesRecibidos));
  display.drawString(55, 0, "ERR:" + String(paquetesCorruptos));
  
  // PPS en la esquina derecha
  display.setTextAlignment(TEXT_ALIGN_RIGHT);
  display.drawString(128, 0, String(paquetesPorSegundo) + "/s");
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
  display.drawString(64, 48, calidad);  // Centrado en y=48 para que quepa
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  
  display.display();
  
  // --- CALCULAR PPS (Paquetes Por Segundo) ---
  if(millis() - tiempoSegundo >= 1000) {
    paquetesPorSegundo = contadorTemporal;
    contadorTemporal = 0;
    tiempoSegundo = millis();
  }
}

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
  display.drawString(0, 47, "BW: 125 kHz | SF: 9");  // ← Cambiar esta línea
  display.display();
  delay(2000);

  // VELOCIDAD ALTA (Ajusta tu monitor serie a esto)
  Serial.begin(921600);
  Serial.println("--- BASE STATION LISTA ---");

  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  
  // MISMA CONFIG QUE TX: BW 500.0, SF 7
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);  
  radio.setDio1Action(setFlag);

  if (state == RADIOLIB_ERR_NONE) {
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
    Serial.print("Fallo Radio: ");
    Serial.println(state);
    
    display.clear();
    display.setFont(ArialMT_Plain_16);
    display.drawString(0, 20, "ERROR RADIO");
    display.setFont(ArialMT_Plain_10);
    display.drawString(0, 40, "Codigo: " + String(state));
    display.display();
    
    while(1);
  }
}

void loop() {
  if(rxReceived) {
    rxReceived = false; // Reset flag

    // Leemos el paquete binario
    int state = radio.readData((uint8_t*)&packet, sizeof(packet));

    if (state == RADIOLIB_ERR_NONE) {
      // --- CAPTURAR MÉTRICAS DE SEÑAL ---
      rssi = radio.getRSSI();
      snr = radio.getSNR();
      paquetesRecibidos++;
      contadorTemporal++;
      
      Serial.print("t"); // Inicio de trama estándar

      // ID (Debe ser siempre 3 caracteres hexadecimales)
      // Ejemplo: ID 0x1A -> "01A"
      if (packet.canId < 0x100) Serial.print("0");
      if (packet.canId < 0x10)  Serial.print("0");
      Serial.print(packet.canId, HEX);

      // Longitud (1 caracter)
      Serial.print(packet.len);

      // Datos (2 caracteres hex por cada byte)
      // Ejemplo: dato 10 -> "0A"
      for(int i=0; i<packet.len; i++) {
        if(packet.data[i] < 0x10) Serial.print("0");
        Serial.print(packet.data[i], HEX);
      }

      // Terminador (Retorno de carro, vital para python-can)
      Serial.write('\r'); 
      
    } else {
      // Error de CRC (paquete corrupto)
      paquetesCorruptos++;
    }

    // Volvemos a escuchar inmediatamente
    radio.startReceive();
  }
  
  // --- ACTUALIZAR PANTALLA CADA 250ms ---
  if(millis() - ultimaActualizacion > 250) {
    ultimaActualizacion = millis();
    actualizarOLED();
  }
}