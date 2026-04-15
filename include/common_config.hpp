#ifndef COMMON_CONFIG_H
#define COMMON_CONFIG_H

#include <Arduino.h>
#include <cstdint>

// ==================================
// PINES LoRa (Comunes para TX y RX)
// ==================================
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

// =========================================
// CONFIGURACIÓN LoRa (Común para TX y RX)
// =========================================
#define LORA_BAND     869.5   // MHz
#define LORA_SF       7
#define LORA_BW       125.0   // kHz
#define LORA_CR       7       // 4/7
#define LORA_PREAMBLE 8       // símbolos
#define LORA_POWER    22      // dBm

// =============================================
// PINES CAN (MCP2515 Externo) - Específico TX
// =============================================
#define CAN_CS      34
#define CAN_SCK     36
#define CAN_MISO    33
#define CAN_MOSI    35

// ============================
// PINES OLED - Específico RX
// ============================
#define OLED_SDA    17
#define OLED_SCL    18
#define OLED_RST    21
#define OLED_VEXT   36

// ==========================================================
// ESTRUCTURA DE PAQUETE DE TELEMETRÍA (Común para TX y RX)
// ==========================================================
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId;
  uint16_t canId;
  uint8_t  len;
  uint8_t  data[8];
};

#endif // COMMON_CONFIG_H
