#include "web_api.h"
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <sys/time.h>

// Defined in the FSM module (declared in fsm.h).
const char *stateName(SystemState s);

// Embedded by PlatformIO (board_build.embed_txtfiles).
extern const uint8_t realtime_html_start[] asm("_binary_realtime_html_start");
extern const uint8_t realtime_html_end[] asm("_binary_realtime_html_end");

void publishTelemetry(uint32_t now) {
  TelemetrySnapshot t;
  t.state = state;
  t.total_acc = lastTotalAcc;
  t.fall_threshold = fallThreshold;
  t.battery_voltage = batteryVoltage;
  t.battery_percent = batteryPercent;
  t.bpm = bpm;
  t.spo2 = spo2;
  t.raw_bpm = rawBpm;
  t.raw_spo2 = rawSpo2;
  t.finger_detected = fingerDetected;
  t.max_connected = maxReady;
  t.mpu_connected = mpuReady;
  t.buzzer_active = buzzerActive;
  t.wifi_connected = gWifiConnected;
  t.lead_off = (!maxReady || !fingerDetected);
  t.ppg_motion = ppgMotion;
  t.total_fall_events = fallCount;
  t.countdown_remaining_ms = (state == SystemState::Countdown && countdownEndMs > now) ? (countdownEndMs - now) : 0;
  t.snooze_remaining_ms = (state == SystemState::Snooze && snoozeEndMs > now) ? (snoozeEndMs - now) : 0;
  t.loop_fps = loopFps;
  t.steps = stepCount;
  t.distance_km = stepCount * 0.0007f;
  t.calories = stepCount * 0.03f;
  t.ram_pct = 100.0f - (ESP.getFreeHeap() * 100.0f / 327680.0f);
  strncpy(t.ai_label, aiLabel, sizeof(t.ai_label) - 1);
  t.ai_label[sizeof(t.ai_label) - 1] = '\0';
  t.ai_confidence = aiConfidence;
  t.ai_fall = aiFall;

  if (telemetryMutex != nullptr && xSemaphoreTake(telemetryMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
    gTelemetry = t;
    xSemaphoreGive(telemetryMutex);
  }
}

bool readTelemetry(TelemetrySnapshot &out) {
  if (telemetryMutex == nullptr) return false;
  if (xSemaphoreTake(telemetryMutex, pdMS_TO_TICKS(50)) != pdTRUE) return false;
  out = gTelemetry;
  xSemaphoreGive(telemetryMutex);
  return true;
}

// ---------------------------------------------------------------------------
// HTTP API (matches realtime.html)
// ---------------------------------------------------------------------------
static void sendCors() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.sendHeader("Cache-Control", "no-store");
}

static void handleRoot() {
  sendCors();
  const size_t len = (size_t)(realtime_html_end - realtime_html_start);
  server.send_P(200, "text/html; charset=utf-8",
                (const char *)realtime_html_start, len);
}

static void handleApi() {
  sendCors();
  server.send(200, "text/plain",
              "Bio-Band API\n/data\n/cancel (POST)\n/test_hw (POST)\n/clear_nvs (POST)\n/set_thresh?val=25 (POST/GET)\n/set_time?epoch=... (POST/GET)\n/capture?seconds=60 (POST/GET)\n");
}

static void handleData() {
  TelemetrySnapshot t;
  if (!readTelemetry(t)) {
    sendCors();
    server.send(503, "text/plain", "busy");
    return;
  }

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
  doc["ai_fall"] = t.ai_fall;

  String out;
  serializeJson(doc, out);
  sendCors();
  server.send(200, "application/json", out);
}

static void enqueueCommand(WebCommandType type, float value = 0.0f) {
  WebCommand cmd;
  cmd.type = type;
  cmd.value = value;
  if (commandQueue != nullptr && xQueueSend(commandQueue, &cmd, 0) == pdTRUE) {
    sendCors();
    server.send(200, "text/plain", "OK");
  } else {
    sendCors();
    server.send(503, "text/plain", "BUSY");
  }
}

static void handleCancel() { enqueueCommand(WebCommandType::CancelAlert); }
static void handleTest() { enqueueCommand(WebCommandType::TestHardware); }
static void handleClear() { enqueueCommand(WebCommandType::ClearData); }

static void handleSetTime() {
  if (!server.hasArg("epoch")) {
    sendCors();
    server.send(400, "text/plain", "missing epoch");
    return;
  }
  unsigned long epoch = strtoul(server.arg("epoch").c_str(), nullptr, 10);
  if (epoch < 1600000000UL) {
    sendCors();
    server.send(400, "text/plain", "invalid epoch");
    return;
  }
  struct timeval tv;
  tv.tv_sec = (time_t)epoch;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  setenv("TZ", "ICT-7", 1);
  tzset();
  sendCors();
  server.send(200, "text/plain", "OK");
  Serial.printf("[NET] time set epoch=%lu\n", epoch);
}

static void handleCapture() {
  bool on = true;
  if (server.hasArg("on")) on = server.arg("on").toInt() != 0;
  if (!on) {
    enqueueCommand(WebCommandType::StopCapture);
    return;
  }
  float seconds = server.hasArg("seconds") ? server.arg("seconds").toFloat() : (float)CAPTURE_DEFAULT_SECONDS;
  if (isnan(seconds) || seconds < 5.0f) seconds = 5.0f;
  if (seconds > (float)CAPTURE_MAX_SECONDS) seconds = (float)CAPTURE_MAX_SECONDS;
  enqueueCommand(WebCommandType::StartCapture, seconds);
}

static void handleSetThreshold() {
  if (!server.hasArg("val")) {
    sendCors();
    server.send(400, "text/plain", "missing val");
    return;
  }
  float v = server.arg("val").toFloat();
  if (isnan(v) || v < 10.0f || v > 60.0f) {
    sendCors();
    server.send(400, "text/plain", "val must be 10..60");
    return;
  }
  enqueueCommand(WebCommandType::SetThreshold, v);
}

static void handleNotFound() {
  sendCors();
  server.send(404, "text/plain", "not found");
}

// ---------------------------------------------------------------------------
// Network task (Core 0)
// ---------------------------------------------------------------------------
void startNetwork() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);

  if (strlen(WIFI_SSID) > 0) {
    Serial.printf("[NET] connecting to %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
      vTaskDelay(pdMS_TO_TICKS(250));
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    gWifiConnected = true;
    Serial.printf("[NET] STA IP %s\n", WiFi.localIP().toString().c_str());
    configTime(7 * 3600, 0, "pool.ntp.org", "time.google.com");
  } else {
    Serial.printf("[NET] STA failed status=%d; scanning 2.4 GHz...\n",
                  (int)WiFi.status());
    int found = WiFi.scanNetworks();
    Serial.printf("[NET] scan found %d\n", found);
    for (int i = 0; i < found; ++i) {
      Serial.printf("[NET] %s rssi=%d ch=%d enc=%d\n",
                    WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i),
                    (int)WiFi.encryptionType(i));
    }
    WiFi.scanDelete();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_AP);
    WiFi.softAP("BioBand-Setup", "bioband123");
    gWifiConnected = true;
    Serial.printf("[NET] AP IP %s\n", WiFi.softAPIP().toString().c_str());
  }

  server.on("/", HTTP_GET, handleRoot);
  server.on("/api", HTTP_GET, handleApi);
  server.on("/data", HTTP_GET, handleData);
  server.on("/cancel", HTTP_POST, handleCancel);
  server.on("/test_hw", HTTP_POST, handleTest);
  server.on("/clear_nvs", HTTP_POST, handleClear);
  server.on("/set_time", HTTP_POST, handleSetTime);
  server.on("/set_time", HTTP_GET, handleSetTime);
  server.on("/set_thresh", HTTP_POST, handleSetThreshold);
  server.on("/set_thresh", HTTP_GET, handleSetThreshold);
  server.on("/capture", HTTP_POST, handleCapture);
  server.on("/capture", HTTP_GET, handleCapture);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println("[NET] HTTP server port 80");
}

void networkTask(void *arg) {
  (void)arg;
  startNetwork();
  for (;;) {
    server.handleClient();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
