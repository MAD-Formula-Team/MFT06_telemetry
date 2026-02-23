#include <Arduino.h>
#include <SPI.h>
#include <mcp_can.h>
#include <RadioLib.h>

// --- PINES (igual que antes) ---
#define LORA_NSS    8
#define LORA_DIO1   14
#define LORA_RST    12
#define LORA_BUSY   13
#define LORA_SCK    9
#define LORA_MISO   11
#define LORA_MOSI   10

#define LORA_BAND    869.5   // MHz
#define LORA_SF      7
#define LORA_BW      125.0   // kHz
#define LORA_CR      7       // 4/7
#define LORA_PREAMBLE 8      // símbolos
#define LORA_POWER   22      // dBm
// CAN (MCP2515 Externo)
#define CAN_CS      34
#define CAN_SCK     36
#define CAN_MISO    33
#define CAN_MOSI    35

int contador3A4 = 0;

// --- ESTRUCTURA DE PAQUETE ---
struct __attribute__((packed)) TelemetryPacket {
  uint32_t packetId;
  uint16_t canId;
  uint8_t  len;
  uint8_t  data[8];
};

// --- COLA ENTRE NÚCLEOS ---
// Capacidad: 32 paquetes en buffer, si se llena se dropea (no bloquea el CAN)
QueueHandle_t colaLoRa;
#define COLA_SIZE 32

// --- OBJETOS RADIO Y CAN ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);

// --- CONTROL DE IDs (corregido con int8_t) ---
const uint16_t MAX_IDS = 50;
uint16_t idsRecientes[MAX_IDS];
unsigned long tiemposIds[MAX_IDS];
int8_t numIdsTrackeadas = 0;  // ← SIGNED para evitar underflow
const unsigned long VENTANA_TIEMPO = 2000;

// --- STATS ---
uint32_t globalCounter = 0;
uint32_t paquetesDroppeados = 0;

// --- ISR LoRa ---
volatile bool txReady = true;
ICACHE_RAM_ATTR void setFlag(void) {
  txReady = true;
}

// ================================================================
// TASK CORE 0: Empaquetar y enviar por LoRa
// ================================================================
void taskLoRa(void *pvParameters) {
  TelemetryPacket packet;
  
  // Inicializar LoRa en este task (mismo core que lo va a usar)
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  radio.setDio1Action(setFlag);
  
  if(state != RADIOLIB_ERR_NONE) {
    Serial.printf("[LoRa] Error init: %d\n", state);
    vTaskDelete(NULL);
    return;
  }
  Serial.println("[LoRa] Task OK en Core 0");

  for(;;) {
    // Espera bloqueante: duerme hasta que llegue algo a la cola
    // Timeout 100ms para no quedarse colgado para siempre
    if(xQueueReceive(colaLoRa, &packet, pdMS_TO_TICKS(100)) == pdTRUE) {
      
      // Esperar a que la radio esté libre (con timeout de seguridad)
      uint32_t timeout = millis();
      while(!txReady && (millis() - timeout < 500)) {
        vTaskDelay(1); // Ceder CPU mientras espera, no busy-wait
      }
      
      if(txReady) {
        txReady = false;
        radio.startTransmit((uint8_t*)&packet, sizeof(packet));
      } else {
        // Timeout de radio → algo fue mal, reintentar en siguiente paquete
        paquetesDroppeados++;
        txReady = true; // Reset forzado
      }
    }
  }
}

// ================================================================
// TASK CORE 1: Leer CAN (o simplemente el loop() de Arduino)
// ================================================================

bool idYaVista(uint16_t canId) {
  unsigned long ahora = millis();

  // Buscar si la ID ya existe
  for(uint8_t i = 0; i < numIdsTrackeadas; i++) {
    // Limpiar IDs antiguas (más de 2 segundos)
    if(ahora - tiemposIds[i] > VENTANA_TIEMPO) {
      for(int8_t j = i; j < numIdsTrackeadas - 1; j++) {
        idsRecientes[j] = idsRecientes[j + 1];
        tiemposIds[j] = tiemposIds[j + 1];
      }
      if(numIdsTrackeadas > 0) numIdsTrackeadas--; // guarda extra
      i--;
      continue;
    }

    // Si encontramos la ID y es reciente
    if(idsRecientes[i] == canId) {
      return true; // Ya vista recientemente
    }
  }

  // No está en la lista, agregarla
  if(numIdsTrackeadas < MAX_IDS) {
    idsRecientes[numIdsTrackeadas] = canId;
    tiemposIds[numIdsTrackeadas] = ahora;
    numIdsTrackeadas++;
  }

  return false; // No vista, es nueva
}

// --- ESTRUCTURA DE DATOS (BINARIA COMPACTA) ---
// Total: 15 Bytes (vs ~40 Bytes en texto)
struct __attribute__((packed)) TelemetryPacket {
  //uint32_t packetId; // 4 bytes
  uint16_t canId;    // 2 bytes
  uint8_t  len;      // 1 byte
  uint8_t  data[8];  // 8 bytes
} packet;

// --- OBJETOS ---
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
MCP_CAN CAN0(CAN_CS);  // ← COMENTADO

// --- VARIABLES DE CONTROL ---
volatile bool txReady = true; // Semáforo para saber si la radio está libre
uint32_t globalCounter = 0;
uint32_t paquetesDroppeados = 0;

uint8_t contador3A4 = 0; // Contador para la ID 0x3A4 (ejemplo de filtro)


// Interrupción: Se dispara cuando la radio termina de enviar
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  txReady = true;
}

void setup() {
  Serial.begin(921600);
  delay(1000);

  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   MADFT06 TRANSMISOR - MODO CAN    ║");
  Serial.println("║   Leyendo datos del bus CAN...     ║");
  Serial.println("╚════════════════════════════════════╝\n");

  // 1. INICIALIZAR CAN
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);
  if(CAN0.begin(MCP_ANY, CAN_1000KBPS, MCP_8MHZ) == CAN_OK) {
    CAN0.setMode(MCP_NORMAL);
    Serial.println("[CAN] OK");
  } else {
    Serial.println("[CAN] FALLO");
    while(1);
  }

  // 2. INICIALIZAR LORA (MODO VELOCIDAD)
  loraSPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);

  // Parametros: Freq 869.5, BW 125.0, SF 7, CR 5 (4/5), SyncWord 0x12, Pwr 22dBm
  // BW 125 + SF 7 = La configuración más rápida posible en LoRa
  int state = radio.begin(LORA_BAND, LORA_BW, LORA_SF, LORA_CR, 0x12, LORA_POWER);
  // Asignamos la función de interrupción
  radio.setDio1Action(setFlag);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[LoRa] Hardware OK (Modo F1).");
    Serial.println("[CAN] Esperando mensajes CAN...\n");
  } else {
    Serial.print("[LoRa] Fallo código: ");
    Serial.println(state);
    while(1);
  }
}

void loop() {
  // Core 1: solo leer CAN y meter en cola, rapidísimo
  if(CAN0.checkReceive() == CAN_MSGAVAIL) {
    long unsigned int rxId;
    unsigned char len;
    unsigned char rxBuf[8];

    CAN0.readMsgBuf(&rxId, &len, rxBuf);

    uint16_t canId = (uint16_t)rxId;

    // --- FILTRO: Ignorar algo de engine ---

    // if((canId == 0x3A4) && ( contador3A4 >= 20)) {
    //   contador3A4 = 0; // Reiniciar contador
    // } else if (canId == 0x3A4) {
    //   contador3A4++;
    //   return; }

    if (canId != 0x3A3) {

        return; // Ignorar este mensaje

    }

    // 2. ENVIAR SOLO SI LA RADIO ESTÁ LIBRE (Estrategia "Drop")
    if(txReady) {
      txReady = false; // Marcamos ocupado

      // Llenamos la estructura binaria
      //packet.packetId = globalCounter++;
      packet.canId = canId;
      packet.len = len;
      memcpy(packet.data, rxBuf, 8); // Copia rápida de memoria

      // Enviamos (Non-blocking)
      radio.startTransmit((uint8_t*)&packet, sizeof(packet));

      // Feedback mínimo (un punto)
      Serial.print(".");
    } else {
      // Si txReady es false, ignoramos el paquete (DROP)
      paquetesDroppeados++;
    }
  }

  // --- DEBUG ESTADÍSTICAS CADA 5 SEGUNDOS ---
  static unsigned long lastDebug = 0;
  if(millis() - lastDebug > 5000) {
    lastDebug = millis();
    Serial.println("\n");
    Serial.println("╔═══════════════ STATS TX ═══════════════╗");
    Serial.print("║ Paquetes enviados:    ");
    Serial.print(globalCounter);
    Serial.println("              ║");

    Serial.print("║ Paquetes dropped:     ");
    Serial.print(paquetesDroppeados);
    Serial.println("              ║");

    Serial.print("║ IDs únicas trackeadas: ");
    Serial.print(numIdsTrackeadas);
    Serial.println("             ║");

    // Calcular porcentaje de pérdida
    uint32_t total = globalCounter + paquetesDroppeados;
    if(total > 0) {
      float perdida = (paquetesDroppeados * 100.0) / total;
      Serial.print("║ % Pérdida:            ");
      Serial.print(perdida, 2);
      Serial.println(" %            ║");
    }

    Serial.println("╟────────────────────────────────────────╢");
    Serial.println("║ IDs activas (últimos 2s):              ║");
    for(uint8_t i = 0; i < numIdsTrackeadas && i < 10; i++) {
      Serial.print("║   0x");
      if(idsRecientes[i] < 0x100) Serial.print("0");
      if(idsRecientes[i] < 0x10) Serial.print("0");
      Serial.print(idsRecientes[i], HEX);
      Serial.print("  (hace ");
      Serial.print((millis() - tiemposIds[i]) / 1000);
      Serial.println("s)                      ║");
    }
    if(numIdsTrackeadas > 10) {
      Serial.print("║   ... y ");
      Serial.print(numIdsTrackeadas - 10);
      Serial.println(" más                        ║");
    }

    Serial.println("╚════════════════════════════════════════╝\n");
  }
}
