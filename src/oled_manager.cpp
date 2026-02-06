#include "oled_manager.h"

// ============================================================================
// IMPLEMENTACIÓN DEL GESTOR OLED
// ============================================================================

// Objeto global
SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);

bool oledInit() {
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

  return true;
}

void oledShowStartup() {
  display.clear();

  // Logo/Título centrado
  display.setFont(ArialMT_Plain_16);
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 0, "MADFT06 RX");
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  // Información del sistema
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 22, "Iniciando sistema...");
  display.drawString(0, 35, "Freq: 869.5 MHz");
  display.drawString(0, 47, "BW:125kHz SF:7 CR:4/7");

  display.display();
}

void oledUpdate(MetricsData &data) {
  display.clear();

  // --- LÍNEA 1: Contador de paquetes (0-10px) ---
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 0, "RX:" + String(data.paquetesRecibidos));
  display.drawString(55, 0, "ERR:" + String(data.paquetesCorruptos));

  // PPS en la esquina derecha
  display.setTextAlignment(TEXT_ALIGN_RIGHT);
  display.drawString(128, 0, String(data.paquetesPorSegundo) + "/s");
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  // Indicador de conexión (círculo en esquina superior derecha)
  if(data.conectado) {
    display.fillCircle(120, 5, 3);  // Círculo relleno
  } else {
    display.drawCircle(120, 5, 3);  // Círculo vacío
  }

  // --- LÍNEA 2: RSSI (12-26px) ---
  display.setFont(ArialMT_Plain_16);
  display.drawString(0, 12, String((int)data.rssi) + " dBm");

  // SNR a la derecha de RSSI
  display.setFont(ArialMT_Plain_10);
  display.drawString(75, 16, "SNR:" + String(data.snr, 1));

  // --- LÍNEA 3: Barra visual de RSSI (28-38px) ---
  int barraRSSI = map(constrain(data.rssi, -120, -30), -120, -30, 0, 100);
  display.drawProgressBar(0, 28, 120, 8, barraRSSI);

  // --- LÍNEA 4: Estado de calidad CENTRADO (40-63px) ---
  String calidad;
  if(data.rssi > -70) {
    calidad = "EXCELENTE";
  } else if(data.rssi > -85) {
    calidad = "BUENA";
  } else if(data.rssi > -100) {
    calidad = "MEDIA";
  } else if(data.rssi > -115) {
    calidad = "DEBIL";
  } else {
    calidad = "MUY DEBIL";
  }

  // Calidad también depende del SNR
  if(data.snr < 0 && data.rssi > -100) {
    calidad = "RUIDOSA";
  }

  // Estado centrado y grande
  display.setFont(ArialMT_Plain_16);
  display.setTextAlignment(TEXT_ALIGN_CENTER);
  display.drawString(64, 48, calidad);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  display.display();
}
