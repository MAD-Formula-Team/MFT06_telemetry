#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <Wire.h>
#include <SSD1306Wire.h>
#include "common_config.hpp"

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif

// GPIO47 para entrada dedicada del laptimer.
constexpr uint8_t LAPTIMER_TRIGGER_PIN = 47;
constexpr uint8_t LAPTIMER_TRIGGER_ACTIVE_LEVEL = LOW;
// El sensor IR emite DOS pulsos en cada pasada del coche (reflejo del frontal
// y de la cola). Tras aceptar un trigger se ignora todo pulso durante el
// lockout: mucho mayor que la separación entre ambos pulsos (<1 s) y mucho
// menor que la vuelta más corta posible (skidpad ~4.5 s). Así cada pasada
// cuenta una sola vez y la vuelta se mide de primer pulso a primer pulso.
constexpr uint32_t TRIGGER_LOCKOUT_MS = 1000;

QueueHandle_t colaLoRa;
#define COLA_SIZE 32

SPIClass loraSPI(HSPI);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY, loraSPI);
SSD1306Wire display(0x3c, OLED_SDA, OLED_SCL);

volatile bool txReady = true;
volatile bool triggerPendiente = false;
uint32_t ultimoTriggerMs = 0;

uint32_t packetCounter = 0;
uint32_t triggersAceptados = 0;
uint64_t ultimoTimestampUs = 0;

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
  display.drawString(0, 0, "Laptimer TX");
  display.drawString(0, 14, "Init...");
  display.display();
}

void actualizarOLED(bool signalRx) {
  display.clear();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 0, "Laptimer TX GPIO47");
  display.drawString(0, 14, signalRx ? "Signal: RECIBIDA" : "Signal: esperando");
  display.drawString(0, 28, "Count: " + String(triggersAceptados));
  display.drawString(0, 42, "Last us: " + String((unsigned long)(ultimoTimestampUs % 1000000ULL)));
  display.display();
}

ICACHE_RAM_ATTR void setFlag(void) {
  txReady = true;
}

ICACHE_RAM_ATTR void onLapTrigger() {
  triggerPendiente = true;
}

void taskLoRa(void *pvParameters) {
  TelemetryPacket packet;

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
    if(xQueueReceive(colaLoRa, &packet, pdMS_TO_TICKS(100)) == pdTRUE) {
      uint32_t timeout = millis();
      while(!txReady && (millis() - timeout < 500)) {
        vTaskDelay(1);
      }

      if(txReady) {
        txReady = false;
        radio.startTransmit((uint8_t*)&packet, sizeof(packet));
      } else {
        txReady = true;
      }
    }
  }
}

void setup() {
  Serial.begin(921600);
  iniciarOLED();

  colaLoRa = xQueueCreate(COLA_SIZE, sizeof(TelemetryPacket));
  if(colaLoRa == NULL) {
    Serial.println("[ERROR] No se pudo crear la cola LoRa");
    while(1);
  }

  pinMode(LAPTIMER_TRIGGER_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(LAPTIMER_TRIGGER_PIN), onLapTrigger, FALLING);

  xTaskCreatePinnedToCore(taskLoRa, "TaskLoRa", 4096, NULL, 2, NULL, 0);

  Serial.println("[SYSTEM] Laptimer TX listo");
  Serial.printf("[GPIO] Trigger pin=%u level=%s\n", LAPTIMER_TRIGGER_PIN,
                (LAPTIMER_TRIGGER_ACTIVE_LEVEL == LOW) ? "LOW" : "HIGH");
  actualizarOLED(false);
}

void loop() {
  if(!triggerPendiente) {
    return;
  }

  triggerPendiente = false;

  uint32_t now = millis();
  // Lockout anti doble-pulso: solo cuenta desde triggers ACEPTADOS, por lo
  // que el segundo pulso de la misma pasada nunca rearma la ventana.
  if(triggersAceptados > 0 && (now - ultimoTriggerMs) < TRIGGER_LOCKOUT_MS) {
    return;
  }

  if(digitalRead(LAPTIMER_TRIGGER_PIN) != LAPTIMER_TRIGGER_ACTIVE_LEVEL) {
    return;
  }
  ultimoTriggerMs = now;

  uint64_t timestampUs = esp_timer_get_time();
  ultimoTimestampUs = timestampUs;
  triggersAceptados++;

  TelemetryPacket packet = {};
  packet.packetId = packetCounter++;
  packet.canId = 0x777;
  packet.len = 8;
  memcpy(packet.data, &timestampUs, sizeof(timestampUs));

  if(xQueueSend(colaLoRa, &packet, 0) != pdTRUE) {
    Serial.println("[WARN] Cola LoRa llena, timestamp descartado");
    actualizarOLED(false);
    return;
  }

  Serial.printf("[LT] Trigger enviado - ts_us=%llu\n", (unsigned long long)timestampUs);
  actualizarOLED(true);
}
