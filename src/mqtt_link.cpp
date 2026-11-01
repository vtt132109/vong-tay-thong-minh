#include "mqtt_link.h"

#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#include "app_state.h"
#include "fsm.h"
#include "web_api.h"

// ---------------------------------------------------------------------------
// Public broker link (mirrors the old project's approach).
// NOT private: anyone who knows the topic can read the health telemetry.
// The link is PUBLISH-ONLY: no command topic is subscribed, so nobody can cancel an alarm,
// clear data or change thresholds through the public broker.
// ---------------------------------------------------------------------------
static const char *MQTT_BROKER = "broker.emqx.io";
static const uint16_t MQTT_PORT = 1883;
static const char *MQTT_BASE = "bioband/vtt132109/dev01";

static const uint32_t MQTT_RECONNECT_MS = 5000;   // retry cadence, non-blocking
static const uint32_t MQTT_TELEMETRY_MS = 1000;   // at most one publish per second
static const uint32_t MQTT_HISTORY_MS = 5000;     // retained 60 s snapshot cadence
static const uint32_t MQTT_LOG_MS = 10000;        // heartbeat log
static const uint16_t MQTT_BUFFER_SIZE = 2048;
static const uint8_t MQTT_HISTORY_SAMPLES = 60;

static WiFiClient mqttNet;
static PubSubClient mqttClient(mqttNet);

static char topicStatus[80];
static char topicTelemetry[80];
static char topicHistory[80];
static char topicAlert[80];

static char mqttClientId[32];

static uint32_t lastReconnectMs = 0;
static uint32_t lastPublishMs = 0;
static uint32_t lastLogMs = 0;
static uint32_t publishCount = 0;
static bool wasConnected = false;
static SystemState lastAlertState = SystemState::Idle;

struct HistorySample {
  uint16_t bpm;
  uint8_t spo2;
  float p;
};
static HistorySample historyBuf[MQTT_HISTORY_SAMPLES];
static uint8_t historyHead = 0;
static uint8_t historyCount = 0;
static uint32_t lastHistoryPublishMs = 0;

static void buildTopic(char *dst, size_t len, const char *suffix) {
  snprintf(dst, len, "%s/%s", MQTT_BASE, suffix);
}

static void historyPush(const TelemetrySnapshot &t) {
  HistorySample &s = historyBuf[historyHead];
  s.bpm = (uint16_t)lroundf(t.bpm > 0.0f ? t.bpm : 0.0f);
  s.spo2 = t.spo2;
  s.p = t.ai_probability;
  historyHead = (uint8_t)((historyHead + 1) % MQTT_HISTORY_SAMPLES);
  if (historyCount < MQTT_HISTORY_SAMPLES) ++historyCount;
}

// Retained snapshot (newest last, 1 s apart) so a freshly opened dashboard
// can draw the last minute instead of starting from an empty chart.
static void publishHistoryJson() {
  if (!mqttClient.connected() || historyCount == 0) return;
  DynamicJsonDocument doc(2048);
  doc["n"] = historyCount;
  JsonArray bpm = doc.createNestedArray("bpm");
  JsonArray spo2 = doc.createNestedArray("spo2");
  JsonArray p = doc.createNestedArray("p");
  uint8_t start = (uint8_t)((historyHead + MQTT_HISTORY_SAMPLES - historyCount) % MQTT_HISTORY_SAMPLES);
  for (uint8_t i = 0; i < historyCount; ++i) {
    const HistorySample &s = historyBuf[(start + i) % MQTT_HISTORY_SAMPLES];
    bpm.add(s.bpm);
    spo2.add(s.spo2);
    p.add((float)(roundf(s.p * 10000.0f) / 10000.0f));
  }
  String out;
  out.reserve(1400);
  serializeJson(doc, out);
  if (!mqttClient.publish(topicHistory, out.c_str(), true)) {
    Serial.printf("[MQTT] history publish failed (len=%u)\n", (unsigned)out.length());
  }
}

static void mqttConnect() {
  Serial.printf("[MQTT] connect %s:%u id=%s\n", MQTT_BROKER, (unsigned)MQTT_PORT, mqttClientId);
  // LWT: broker publishes "offline" (retained) if the link drops.
  if (mqttClient.connect(mqttClientId, nullptr, nullptr,
                         topicStatus, 1, true, "offline")) {
    mqttClient.publish(topicStatus, "online", true);
    publishHistoryJson();
    lastHistoryPublishMs = millis();
    Serial.println("[MQTT] connected");
    Serial.printf("[MQTT] base=%s (public broker - telemetry is NOT private)\n", MQTT_BASE);
  } else {
    Serial.printf("[MQTT] rc=%d\n", mqttClient.state());
  }
}

static void publishTelemetryJson(const TelemetrySnapshot &t) {
  StaticJsonDocument<1536> doc;
  fillTelemetryJson(doc, t);

  String out;
  out.reserve(512);
  serializeJson(doc, out);
  if (mqttClient.publish(topicTelemetry, out.c_str(), true)) {
    ++publishCount;
  } else {
    Serial.printf("[MQTT] telemetry publish failed (len=%u)\n", (unsigned)out.length());
  }
}

// Publish only when the state actually changes into an alert-ish state.
static void publishAlertIfNeeded(const TelemetrySnapshot &t) {
  if (t.state == lastAlertState) return;
  lastAlertState = t.state;
  if (t.state != SystemState::Countdown &&
      t.state != SystemState::Alarm &&
      t.state != SystemState::PanicSos) {
    return;
  }
  StaticJsonDocument<256> doc;
  doc["state"] = stateName(t.state);
  doc["reason"] = alarmReason;
  String out;
  out.reserve(128);
  serializeJson(doc, out);
  if (mqttClient.publish(topicAlert, out.c_str(), false)) {
    Serial.printf("[MQTT] alert %s\n", out.c_str());
  }
}

void mqttLinkBegin() {
  buildTopic(topicStatus, sizeof(topicStatus), "status");
  buildTopic(topicTelemetry, sizeof(topicTelemetry), "telemetry");
  buildTopic(topicHistory, sizeof(topicHistory), "history");
  buildTopic(topicAlert, sizeof(topicAlert), "fall/alert");

  uint8_t mac[6] = {0};
  WiFi.macAddress(mac);
  snprintf(mqttClientId, sizeof(mqttClientId), "bioband-dev01-%02X%02X%02X",
           mac[3], mac[4], mac[5]);

  TelemetrySnapshot t;
  if (readTelemetry(t)) lastAlertState = t.state;

  // Arduino-ESP32 3.x: WiFiClient::setTimeout(seconds) also bounds connect(),
  // so a dead broker cannot stall the web API for long.
  mqttNet.setTimeout(2);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setBufferSize(MQTT_BUFFER_SIZE);
  mqttClient.setKeepAlive(30);
  mqttClient.setSocketTimeout(2);

  lastReconnectMs = millis() - MQTT_RECONNECT_MS;  // try immediately
  lastLogMs = millis();
  Serial.printf("[MQTT] begin %s:%u base=%s id=%s\n",
                MQTT_BROKER, (unsigned)MQTT_PORT, MQTT_BASE, mqttClientId);
}

bool mqttLinkConnected() { return mqttClient.connected(); }

void mqttLinkLoop(uint32_t now) {
  // Only use the STA link (AP fallback has no internet).
  if (WiFi.status() != WL_CONNECTED) {
    wasConnected = false;
    return;
  }

  if (!mqttClient.connected()) {
    if (wasConnected) {
      Serial.printf("[MQTT] disconnected rc=%d\n", mqttClient.state());
      wasConnected = false;
    }
    if (now - lastReconnectMs >= MQTT_RECONNECT_MS) {
      lastReconnectMs = now;
      mqttConnect();
      wasConnected = mqttClient.connected();
      lastPublishMs = now - MQTT_TELEMETRY_MS;  // publish as soon as we are up
      lastLogMs = now;
    }
    return;
  }
  wasConnected = true;

  mqttClient.loop();

  if (now - lastPublishMs >= MQTT_TELEMETRY_MS) {
    lastPublishMs = now;
    TelemetrySnapshot t;
    if (readTelemetry(t)) {
      publishTelemetryJson(t);
      historyPush(t);
      const uint32_t historyCadence = historyCount < 20 ? 2000 : MQTT_HISTORY_MS;
      if (now - lastHistoryPublishMs >= historyCadence) {
        lastHistoryPublishMs = now;
        publishHistoryJson();
      }
      publishAlertIfNeeded(t);
    }
  }

  if (now - lastLogMs >= MQTT_LOG_MS) {
    lastLogMs = now;
    Serial.printf("[MQTT] up rssi=%d pubs=%lu heap=%u\n",
                  WiFi.RSSI(), (unsigned long)publishCount,
                  (unsigned)ESP.getFreeHeap());
  }
}
