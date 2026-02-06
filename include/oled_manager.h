#ifndef OLED_MANAGER_H
#define OLED_MANAGER_H

#include <SSD1306Wire.h>
#include <Wire.h>
#include "config.h"

// ============================================================================
// GESTIÓN DE PANTALLA OLED (SSD1306 128x64)
// ============================================================================
// Maneja inicialización y actualización de la pantalla OLED

// Estructura de métricas para mostrar en pantalla
struct MetricsData {
  uint32_t paquetesRecibidos;
  uint32_t paquetesCorruptos;
  float rssi;
  float snr;
  uint32_t paquetesPorSegundo;
  bool conectado;
};

// Objeto global del display
extern SSD1306Wire display;

// Inicializar pantalla OLED
// Incluye: encendido Vext, reset, init, flip
// Retorna: true si éxito, false si fallo
bool oledInit();

// Mostrar pantalla de inicio/bienvenida
// Muestra: Logo, frecuencia, parámetros LoRa
void oledShowStartup();

// Actualizar pantalla con métricas en tiempo real
// Layout: Contadores, RSSI/SNR, barra progreso, estado calidad, indicador conexión
void oledUpdate(MetricsData &data);

#endif // OLED_MANAGER_H
