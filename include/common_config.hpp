#ifndef COMMON_CONFIG_H
#define COMMON_CONFIG_H

#include <Arduino.h>

// ================================================================
// LOGGING — comentar para deshabilitar en producción (sin USB)
// ================================================================
#define SERIAL_LOGGING_ENABLED // comentar linea para quitar logging

#ifdef SERIAL_LOGGING_ENABLED
  #define LOG(...)  Serial.print(__VA_ARGS__)
  #define LOGF(...) Serial.printf(__VA_ARGS__)
  #define LOGL(...) Serial.println(__VA_ARGS__)
#else
  #define LOG(...)  do {} while(0)
  #define LOGF(...) do {} while(0)
  #define LOGL(...) do {} while(0)
#endif

// ================================================================
// PINES LoRa
// ================================================================
#define LORA_NSS 8
#define LORA_DIO1 14
#define LORA_RST 12
#define LORA_BUSY 13
#define LORA_SCK 9
#define LORA_MISO 11
#define LORA_MOSI 10

// ================================================================
// CONFIGURACIÓN LoRa
// ================================================================
#define LORA_BAND 869.5f // MHz  — sub-banda h1.7 (869.4–869.65)
#define LORA_SF 7 // Spreading Factor 7–12
#define LORA_BW 125.0f // kHz  — float para RadioLib
#define LORA_BW_KHZ 125u // kHz  — entero para aritmética constexpr
#define LORA_CR 7 // Denominador: 5=4/5, 6=4/6, 7=4/7, 8=4/8
#define LORA_PREAMBLE 8 // Símbolos de preámbulo
#define LORA_POWER 22 // dBm conducido

// ================================================================
// PINES CAN (MCP2515 Externo)
// ================================================================
#define CAN_CS 34
#define CAN_SCK 36
#define CAN_MISO 33
#define CAN_MOSI 35

// ================================================================
// PINES OLED
// ================================================================
#define OLED_SDA 17
#define OLED_SCL 18
#define OLED_RST 21
#define OLED_VEXT 36

// ================================================================
// ESTRUCTURA DE PAQUETE DE TELEMETRÍA
// ================================================================
struct __attribute__((packed)) TelemetryPacket {
    uint32_t packetId; // 4 B
    uint16_t canId; // 2 B
    uint8_t len; // 1 B
    uint8_t data[8]; // 8 B  → total 15 B
};

// ================================================================
// CÁLCULO DE TIME ON AIR EN TIEMPO DE COMPILACIÓN
//
// Referencia: Semtech AN1200.13 "LoRa Modem Designer's Guide", §4
//
// Fórmulas:
//   T_sym [µs] = (2^SF / BW_kHz) × 1000
//   T_pre [µs] = (n_pre + 4.25) × T_sym
//   n_pay      = 8 + max(⌈(8·PL − 4·SF + 28 + 16·CRC − 20·IH)
//                         / (4·(SF − 2·DE))⌉ × (4 + CR_code), 0)
//   T_pay [µs] = n_pay × T_sym
//   ToA   [µs] = T_pre + T_pay
//
//   DE       = 1 si SF≥11 y BW≤125 kHz, sino 0 (Low DR Optimize)
//   CR_code  = LORA_CR − 4     (convierte denominador 5–8 en 1–4)
//   IH       = 0               (cabecera explícita siempre)
//   CRC      = 1               (CRC habilitado siempre)
//   PL       = sizeof(TelemetryPacket)
//
// El intervalo mínimo entre transmisiones depende del duty cycle
// de la sub-banda RF, no del hardware:
//   T_interval = ToA / DC_fraction = ToA_ms × (100 / DC_percent)
//
// Sub-banda h1.7 (869.4–869.65 MHz) → DC = 10 %
//   Si se mueve LORA_BAND a otra sub-banda, cambiar DUTY_CYCLE_PERCENT:
//   h1.3 / h1.4 / h1.5 / h1.8  →  1 %   →  100
//   h1.6                         →  0.1 % →  1000
//   h1.7  (configuración actual) →  10 %  →  10
// ================================================================
namespace lora_timing {

    // ── Constantes derivadas de los #define ───────────────────────
    constexpr uint32_t DE = (LORA_SF >= 11 && LORA_BW_KHZ <= 125u) ? 1u : 0u;

    constexpr uint32_t CR_CODE = (uint32_t) LORA_CR - 4u; // 7→3

    // ── Período de símbolo ─────────────────────────────────────────
    // T_sym_µs = (2^SF × 1000) / BW_kHz
    // SF=7, BW=125 → (128 × 1000) / 125 = 1024 µs  (exacto)
    constexpr uint32_t T_SYM_US = ((1u << LORA_SF) * 1000u) / LORA_BW_KHZ;

    // ── Tiempo de preámbulo ────────────────────────────────────────
    // T_pre = (n_pre + 4.25) × T_sym
    // Se multiplica ×4 para eliminar el 0.25 fraccionario:
    //   (4·n_pre + 17) × T_sym / 4
    constexpr uint32_t T_PRE_US = ((4u * (uint32_t) LORA_PREAMBLE + 17u) * T_SYM_US) / 4u;

    // ── Símbolos de payload ────────────────────────────────────────
    constexpr int PL = (int) sizeof(TelemetryPacket); // 15
    constexpr int _NUM = 8 * PL - 4 * LORA_SF + 28 + 16 - 0; // CRC=1, IH=0
    constexpr int _DEN = 4 * (LORA_SF - 2 * (int) DE);
    constexpr int _CEIL = (_NUM > 0) ? ((_NUM + _DEN - 1) / _DEN) : 0;

    // n_pay = 8 + ⌈…⌉ × (4 + CR_code)
    constexpr uint32_t N_PAY_SYM = 8u + (uint32_t) (_CEIL * (4 + (int) CR_CODE));

    // ── Tiempos finales ────────────────────────────────────────────
    constexpr uint32_t T_PAY_US = N_PAY_SYM * T_SYM_US;
    constexpr uint32_t TOA_US = T_PRE_US + T_PAY_US;
    constexpr uint32_t TOA_MS = (TOA_US + 999u) / 1000u; // techo

    constexpr uint32_t DUTY_CYCLE_PERCENT = 10u;
    constexpr uint32_t TX_INTERVAL_MS = TOA_MS * (100u / DUTY_CYCLE_PERCENT);

    // ── Verificaciones en tiempo de compilación ───────────────────
    static_assert(LORA_SF >= 7 && LORA_SF <= 12, "LORA_SF debe estar entre 7 y 12");
    static_assert(LORA_CR >= 5 && LORA_CR <= 8, "LORA_CR debe ser el denominador: 5, 6, 7 u 8");
    static_assert(LORA_BW_KHZ == 125u || LORA_BW_KHZ == 250u || LORA_BW_KHZ == 500u,
                  "LORA_BW_KHZ debe ser 125, 250 o 500");
    static_assert(TOA_MS > 0u, "ToA calculado es 0: revisa los parametros LoRa");
    static_assert(TX_INTERVAL_MS >= TOA_MS, "TX_INTERVAL_MS < ToA: imposible cumplir el duty cycle");

} // namespace lora_timing

#endif // COMMON_CONFIG_H
