#ifndef CONFIG_H
#define CONFIG_H

// ============================================================================
// CONFIGURACIÓN GLOBAL DEL SISTEMA DE TELEMETRÍA MADFT06
// ============================================================================

// --- DEBUG MODE ---
// 0 = Producción (TX silencioso, RX solo CSV limpio)
// 1 = Debug verbose (TX muestra stats, RX muestra CSV + debug)
#define DEBUG_MODE 1

// --- PINES LORA (Heltec WiFi LoRa 32 V3) ---
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// --- PARÁMETROS LORA ---
#define LORA_BAND      869.5   // MHz
#define LORA_SF        7       // Spreading Factor (7 = más rápido)
#define LORA_BW        125.0   // Bandwidth en kHz
#define LORA_CR        7       // Coding Rate 4/7
#define LORA_PREAMBLE  8       // Símbolos de preámbulo
#define LORA_POWER     22      // Potencia en dBm

// --- PINES CAN (MCP2515 Externo) ---
#define CAN_CS      34
#define CAN_SCK     36
#define CAN_MISO    33
#define CAN_MOSI    35

// --- PINES OLED (SSD1306 128x64) ---
#define OLED_SDA    17
#define OLED_SCL    18
#define OLED_RST    21
#define Vext        36  // Pin de alimentación de la pantalla

// --- CONSTANTES DE TIEMPO ---
#define VENTANA_TIEMPO      2000  // Ventana temporal para filtro de IDs duplicadas (ms)
#define TIMEOUT_CONEXION    3000  // Timeout para considerar desconectado (ms)

// --- CONSTANTES DE ARRAYS ---
#define MAX_IDS 50  // Máximo de IDs CAN diferentes a trackear

// --- COMUNICACIÓN SERIAL ---
#define SERIAL_BAUD 921600  // Velocidad del puerto serie

#endif // CONFIG_H
