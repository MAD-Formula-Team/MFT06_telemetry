#ifndef LORA_MANAGER_H
#define LORA_MANAGER_H

#include <RadioLib.h>
#include <SPI.h>
#include "config.h"
#include "packet.h"

// ============================================================================
// GESTIÓN DE RADIO LORA (SX1262)
// ============================================================================
// Maneja inicialización, transmisión y recepción de paquetes LoRa

// Objetos globales (accesibles externamente si necesario)
extern SPIClass loraSPI;
extern SX1262 radio;
extern volatile bool txReady;
extern volatile bool rxReceived;

// Inicializar radio LoRa con parámetros de config.h
// Retorna: true si éxito, false si fallo
bool loraInit();

// Enviar paquete de telemetría (non-blocking)
// Retorna: true si enviado, false si radio ocupada
bool loraSend(TelemetryPacket &packet);

// Recibir paquete de telemetría si disponible
// Retorna: true si paquete recibido OK, false si no hay o corrupto
bool loraReceive(TelemetryPacket &packet);

// Obtener métricas del último paquete recibido
void loraGetMetrics(float &rssi, float &snr);

// Callbacks de interrupción (llamados por RadioLib)
void loraSetTxFlag();
void loraSetRxFlag();

// Verificar si radio está lista para transmitir
bool loraIsTxReady();

#endif // LORA_MANAGER_H
