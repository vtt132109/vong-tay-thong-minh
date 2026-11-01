#include "web_api.h"
#include "mqtt_link.h"
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <sys/time.h>
#include "esp_sntp.h"

// Defined in the FSM module (declared in fsm.h).
const char *stateName(SystemState s);

static bool apFallback = false;

// WiFi credentials: NVS (set from the /wifi page) wins over include/secrets.h.
static bool hasSavedWifi() { return prefs.isKey("wssid") && prefs.getString("wssid", "").length() > 0; }
static String staSsid() { return hasSavedWifi() ? prefs.getString("wssid", "") : String(WIFI_SSID); }
static String staPass() { return hasSavedWifi() ? prefs.getString("wpass", "") : String(WIFI_PASS); }

// Setup AP password: include/secrets.h AP_PASS if defined, otherwise derived from the MAC so that the
// public repository does not contain a shared default password.
static String apPassword() {
#ifdef AP_PASS
  return String(AP_PASS);
#else
  uint8_t mac[6] = {0};
  WiFi.macAddress(mac);
  char buf[16];
  snprintf(buf, sizeof(buf), "bb-%02X%02X%02X%02X", mac[2], mac[3], mac[4], mac[5]);
  return String(buf);
#endif
}

static uint32_t rebootAtMs = 0;

static const char kWifiPage[] PROGMEM =
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Bio-Band WiFi</title><body style='font:16px system-ui;max-width:420px;margin:24px auto;padding:0 16px'>"
    "<h2>Bio-Band: c&#7845;u h&#236;nh WiFi</h2>"
    "<p>Ch&#7881; h&#7895; tr&#7907; m&#7841;ng 2.4 GHz. Sau khi l&#432;u, v&#242;ng tay s&#7869; kh&#7903;i &#273;&#7897;ng l&#7841;i.</p>"
    "<label>T&#234;n WiFi (SSID)<br><input id=s style='width:100%;padding:8px' autocomplete=off></label><br><br>"
    "<label>M&#7853;t kh&#7849;u<br><input id=p type=password style='width:100%;padding:8px' autocomplete=off></label><br><br>"
    "<button id=b style='padding:10px 18px'>L&#432;u v&#224; kh&#7903;i &#273;&#7897;ng l&#7841;i</button> <span id=m></span>"
    "<script>b.onclick=async()=>{m.textContent='...';try{const r=await fetch('/wifi_save',{method:'POST',"
    "headers:{'X-Bioband':'1','Content-Type':'application/x-www-form-urlencoded'},"
    "body:'ssid='+encodeURIComponent(s.value)+'&pass='+encodeURIComponent(p.value)});"
    "m.textContent=r.ok?'\u0110\u00e3 l\u01b0u. \u0110ang kh\u1edfi \u0111\u1ed9ng l\u1ea1i...':'L\u1ed7i '+r.status}"
    "catch(e){m.textContent='L\u1ed7i k\u1ebft n\u1ed1i'}};</script>";

static bool ntpSynced() {
  return sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED;
}
static uint32_t lastStaRetryMs = 0;

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
  t.ai_probability = aiProbability;
  t.ai_threshold = aiThreshold;
  t.ai_window_peak = aiWindowPeak;
  t.ai_window_fill = aiWindowFill;
  t.ai_inference_count = aiInferenceCount;
  t.ai_inference_us = aiInferenceUs;
  t.ai_fall = aiFall;
  t.ai_prob_mlp = aiProbMlp;
  t.ai_prob_cnn = aiProbCnn;
  t.ai_cnn_us = aiCnnUs;
  t.ai_selftest = aiSelfTestResult;
  t.loop_max_dt_ms = loopMaxDtMsPublished;
  t.ai_armed = aiAlarmEnabled;
  t.chip_c = temperatureRead();
  t.ai_max_6s = aiMax6s;

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
// No Access-Control-Allow-* headers on purpose: only the dashboard served by this device
// (same origin) may use the API; other web pages cannot read /data or issue commands.
static void sendCors() {
  server.sendHeader("Cache-Control", "no-store");
}

// State-changing requests must carry a custom header. Cross-origin pages cannot add it
// without a CORS preflight, which this server never approves (CSRF guard).
static bool guardWrite() {
  if (server.hasHeader("X-Bioband")) return true;
  sendCors();
  server.send(403, "text/plain", "forbidden");
  return false;
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
              "Bio-Band API\n/data\n/cancel (POST)\n/test_hw (POST)\n/clear_nvs (POST)\n/set_thresh?val=25 (POST)\n/set_time?epoch=... (POST)\n/capture?seconds=60 (POST/GET)\n/ai_mode?val=0|1 (POST)\n/wifi (GET page; saves via POST /wifi_save)\n(POST needs header X-Bioband: 1)\n");
}

void fillTelemetryJson(JsonDocument &doc, const TelemetrySnapshot &t) {
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
  doc["ai_mlp"] = t.ai_prob_mlp;
  doc["ai_cnn"] = t.ai_prob_cnn;
  doc["ai_cnn_us"] = t.ai_cnn_us;
  doc["ai_self"] = t.ai_selftest;
  doc["jit"] = t.loop_max_dt_ms;
  doc["ai_arm"] = t.ai_armed;
  doc["chip_c"] = t.chip_c;
  doc["ai_max6"] = t.ai_max_6s;
  doc["cpu_mhz"] = getCpuFrequencyMhz();
  doc["fw"] = FW_VERSION;
}

static void handleData() {
  TelemetrySnapshot t;
  if (!readTelemetry(t)) {
    sendCors();
    server.send(503, "text/plain", "busy");
    return;
  }
  StaticJsonDocument<1536> doc;
  fillTelemetryJson(doc, t);
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

static void handleCancel() { if (guardWrite()) enqueueCommand(WebCommandType::CancelAlert); }
static void handleTest() { if (guardWrite()) enqueueCommand(WebCommandType::TestHardware); }
static void handleClear() { if (guardWrite()) enqueueCommand(WebCommandType::ClearData); }

static void handleSetTime() {
  if (!guardWrite()) return;
  if (ntpSynced()) {  // real network time wins over the browser clock
    sendCors();
    server.send(200, "text/plain", "OK (ntp)");
    return;
  }
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

// While a capture runs the sensor loop only streams CSV (no fall detection) for up to
// CAPTURE_MAX_SECONDS, so starting/stopping it needs the same CSRF guard as the other writes.
static void handleCapture() {
  if (!guardWrite()) return;
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
  if (!guardWrite()) return;
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

static void handleAiMode() {
  if (!guardWrite()) return;
  if (!server.hasArg("val")) {
    sendCors();
    server.send(400, "text/plain", "missing val");
    return;
  }
  enqueueCommand(WebCommandType::SetAiMode, server.arg("val").toInt() != 0 ? 1.0f : 0.0f);
}

static void handleWifiPage() {
  sendCors();
  server.send_P(200, "text/html; charset=utf-8", kWifiPage);
}

static void handleWifiSave() {
  if (!guardWrite()) return;
  String ssid = server.arg("ssid");
  String pass = server.arg("pass");
  ssid.trim();
  if (ssid.length() == 0 || ssid.length() > 32 || pass.length() > 63) {
    sendCors();
    server.send(400, "text/plain", "invalid ssid/password length");
    return;
  }
  prefs.putString("wssid", ssid);
  prefs.putString("wpass", pass);
  Serial.printf("[NET] WiFi credentials saved for '%s'; restarting\n", ssid.c_str());
  sendCors();
  server.send(200, "text/plain", "OK");
  rebootAtMs = millis() + 1200;
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
  // Modem sleep: radio naps between beacons (large saving; adds <~100 ms HTTP latency).
  WiFi.setSleep(WIFI_PS_MIN_MODEM);
  WiFi.setAutoReconnect(true);

  if (staSsid().length() > 0) {
    Serial.printf("[NET] connecting to %s\n", staSsid().c_str());
    WiFi.begin(staSsid().c_str(), staPass().c_str());
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
    // A pending WiFi.begin() makes scanNetworks() fail with -2; stop it first.
    WiFi.disconnect(true, true);
    vTaskDelay(pdMS_TO_TICKS(300));
    WiFi.mode(WIFI_STA);
    vTaskDelay(pdMS_TO_TICKS(300));
    int found = 0;
    for (int attempt = 1; attempt <= 3 && found <= 0; ++attempt) {
      found = WiFi.scanNetworks(false, true);
      Serial.printf("[NET] scan %d found %d\n", attempt, found);
      if (found <= 0) vTaskDelay(pdMS_TO_TICKS(500));
    }
    for (int i = 0; i < found; ++i) {
      Serial.printf("[NET] %s rssi=%d ch=%d enc=%d\n",
                    WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i),
                    (int)WiFi.encryptionType(i));
    }
    WiFi.scanDelete();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_AP_STA);
    const String apPass = apPassword();
    WiFi.softAP("BioBand-Setup", apPass.c_str());
    Serial.printf("[NET] setup AP BioBand-Setup, password %s, page http://192.168.4.1/wifi\n", apPass.c_str());
    gWifiConnected = true;
    apFallback = true;
    lastStaRetryMs = millis();
    Serial.printf("[NET] AP IP %s\n", WiFi.softAPIP().toString().c_str());
  }

  server.on("/", HTTP_GET, handleRoot);
  server.on("/api", HTTP_GET, handleApi);
  server.on("/data", HTTP_GET, handleData);
  server.on("/cancel", HTTP_POST, handleCancel);
  server.on("/test_hw", HTTP_POST, handleTest);
  server.on("/clear_nvs", HTTP_POST, handleClear);
  server.on("/set_time", HTTP_POST, handleSetTime);
  server.on("/set_thresh", HTTP_POST, handleSetThreshold);
  server.on("/ai_mode", HTTP_POST, handleAiMode);
  server.on("/wifi", HTTP_GET, handleWifiPage);
  server.on("/wifi_save", HTTP_POST, handleWifiSave);
  server.on("/capture", HTTP_POST, handleCapture);
  server.on("/capture", HTTP_GET, handleCapture);
  server.onNotFound(handleNotFound);
  static const char *kHeaders[] = {"X-Bioband"};
  server.collectHeaders(kHeaders, 1);
  server.begin();
  Serial.println("[NET] HTTP server port 80");

  // Cloud link (only starts talking once the STA link is up).
  mqttLinkBegin();
}

void networkTask(void *arg) {
  (void)arg;
  startNetwork();
  for (;;) {
    const uint32_t now = millis();
    if (rebootAtMs != 0 && now >= rebootAtMs) ESP.restart();
    if (apFallback && staSsid().length() > 0 && now - lastStaRetryMs >= 60000) {
      lastStaRetryMs = now;
      Serial.println("[NET] retry STA");
      WiFi.begin(staSsid().c_str(), staPass().c_str());
    }
    if (apFallback && WiFi.status() == WL_CONNECTED) {
      apFallback = false;
      gWifiConnected = true;
      Serial.printf("[NET] STA reconnected %s\n", WiFi.localIP().toString().c_str());
      configTime(7 * 3600, 0, "pool.ntp.org", "time.google.com");
    }
    server.handleClient();
    mqttLinkLoop(now);
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
