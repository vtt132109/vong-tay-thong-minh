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
static char topicCancel[80];
static char topicTestHw[80];
static char topicClearNvs[80];
static char topicSetThresh[80];
static char topicSetTime[80];

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

static void enqueueCommand(WebCommandType type, float value = 0.0f) {
  if (commandQueue == nullptr) return;
  WebCommand cmd;
  cmd.type = type;
  cmd.value = value;
  if (xQueueSend(commandQueue, &cmd, 0) != pdTRUE) {
    Serial.println("[MQTT] cmd queue full");
  }
}

static void handleSetTime(const char *payload) {
  unsigned long epoch = strtoul(payload, nullptr, 10);
  if (epoch < 1600000000UL) {
    Serial.printf("[MQTT] set_time invalid '%s'\n", payload);
    return;
  }
  struct timeval tv;
  tv.tv_sec = (time_t)epoch;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  setenv("TZ", "ICT-7", 1);
  tzset();
  Serial.printf("[MQTT] time set epoch=%lu\n", epoch);
}

static void onMqttMessage(char *topic, byte *payload, unsigned int length) {
  char buf[64];
  unsigned int n = length < (sizeof(buf) - 1) ? length : (sizeof(buf) - 1);
  memcpy(buf, payload, n);
  buf[n] = '\0';

  if (strcmp(topic, topicCancel) == 0) {
    enqueueCommand(WebCommandType::CancelAlert);
    Serial.println("[MQTT] cmd cancel");
  } else if (strcmp(topic, topicClearNvs) == 0) {
    enqueueCommand(WebCommandType::ClearData);
    Serial.println("[MQTT] cmd clear_nvs");
  } else if (strcmp(topic, topicSetThresh) == 0) {
    float v = atof(buf);
    if (isnan(v) || v < 10.0f || v > 60.0f) {
      Serial.printf("[MQTT] set_thresh rejected '%s' (10..60)\n", buf);
      return;
    }
    enqueueCommand(WebCommandType::SetThreshold, v);
    Serial.printf("[MQTT] cmd set_thresh %.1f\n", v);
  } else if (strcmp(topic, topicSetTime) == 0) {
    handleSetTime(buf);
  }
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
    mqttClient.subscribe(topicCancel);
    mqttClient.subscribe(topicClearNvs);
    mqttClient.subscribe(topicSetThresh);
    mqttClient.subscribe(topicSetTime);
    publishHistoryJson();
    lastHistoryPublishMs = millis();
    Serial.println("[MQTT] connected");
    Serial.printf("[MQTT] base=%s (public broker - telemetry is NOT private)\n", MQTT_BASE);
  } else {
    Serial.printf("[MQTT] rc=%d\n", mqttClient.state());
  }
}

static void publishTelemetryJson(const TelemetrySnapshot &t) {
  StaticJsonDocument<1024> doc;
  doc["state"] = stateName(t.state);
  doc["bpm"] = t.bpm;
  doc["spo2"] = t.spo2;
  doc["raw_bpm"] = t.raw_bpm;
  doc["raw_spo2"] = t.raw_spo2;
  doc["acc"] = t.total_acc;
  doc["thresh"] = t.fall_threshold;
  doc["max30102"] = t.max_connected;
  doc["lead_off"] = t.lead_off;
  doc["falls"] = t.total_fall_events;
  doc["fps"] = t.loop_fps;
  doc["steps"] = t.steps;
  doc["distance_km"] = t.distance_km;
  doc["calories"] = t.calories;
  doc["battery_v"] = t.battery_voltage;
  doc["battery_pct"] = t.battery_percent;
  doc["ram_pct"] = t.ram_pct;
  doc["buzzer"] = t.buzzer_active;
  doc["motor"] = false;
  doc["snooze_sec"] = t.snooze_remaining_ms / 1000;
  doc["cd_sec"] = t.countdown_remaining_ms / 1000;
  doc["mpu"] = t.mpu_connected;
  doc["finger"] = t.finger_detected;
  doc["ppg_motion"] = t.ppg_motion;
  doc["ai_label"] = t.ai_label;
  doc["ai_conf"] = t.ai_confidence;
  doc["ai_p"] = t.ai_probability;
  doc["ai_thr"] = t.ai_threshold;
  doc["ai_peak"] = t.ai_window_peak;
  doc["ai_fill"] = t.ai_window_fill;
  doc["ai_n"] = t.ai_inference_count;
  doc["ai_us"] = t.ai_inference_us;
  doc["ai_fall"] = t.ai_fall;

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
  buildTopic(topicCancel, sizeof(topicCancel), "cancel");
  buildTopic(topicTestHw, sizeof(topicTestHw), "test_hw");
  buildTopic(topicClearNvs, sizeof(topicClearNvs), "clear_nvs");
  buildTopic(topicSetThresh, sizeof(topicSetThresh), "set_thresh");
  buildTopic(topicSetTime, sizeof(topicSetTime), "set_time");

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
  mqttClient.setCallback(onMqttMessage);

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
      if (now - lastHistoryPublishMs >= MQTT_HISTORY_MS) {
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
