#include "Network/MqttService.h"

MqttService *MqttService::_instance = nullptr;

MqttService::MqttService()
    : _mqttClient(_espClient), _lastWifiRetry(0), _lastMqttRetry(0),
      _onScreenPower(nullptr), _onScreenPage(nullptr), _onScreenMsg(nullptr),
      _onVibrate(nullptr), _onResetSteps(nullptr), _onFallDismiss(nullptr) {
  _instance = this;
}

void MqttService::staticMqttCallback(char *topic, byte *payload,
                                    unsigned int length) {
  if (_instance) {
    _instance->handleMessage(topic, payload, length);
  }
}

void MqttService::begin() {
  connectWiFi();
  _espClient.setTimeout(2); // Timeout TCP socket tối đa 2s chống block lâu
  _mqttClient.setServer(SECRET_MQTT_BROKER, SECRET_MQTT_PORT);
  _mqttClient.setCallback(staticMqttCallback);
  _mqttClient.setBufferSize(768);
}

void MqttService::connectWiFi() {
  Serial.print("[WiFi] Dang ket noi toi: ");
  Serial.println(SECRET_WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);
  WiFi.setTxPower(WIFI_POWER_13dBm);
  WiFi.begin(SECRET_WIFI_SSID, SECRET_WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(300);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Da ket noi thanh cong!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  } else {
    Serial.println("\n[!] Chua ket noi duoc WiFi. Se tu dong thu lai sau.");
  }
}

void MqttService::update() {
  unsigned long now = millis();

  // 1. Giám sát kết nối WiFi
  if (WiFi.status() != WL_CONNECTED) {
    if (now - _lastWifiRetry > WIFI_RETRY_INTERVAL_MS) {
      _lastWifiRetry = now;
      WiFi.reconnect();
    }
    return;
  }

  // 2. Giám sát kết nối MQTT
  if (!_mqttClient.connected()) {
    reconnectMqtt();
  } else {
    _mqttClient.loop();
  }
}

bool MqttService::isConnected() {
  return (WiFi.status() == WL_CONNECTED && _mqttClient.connected());
}

void MqttService::reconnectMqtt() {
  unsigned long now = millis();
  if (now - _lastMqttRetry < MQTT_RETRY_INTERVAL_MS) {
    return;
  }
  _lastMqttRetry = now;

  Serial.print("[MQTT] Dang ket noi toi Broker: ");
  Serial.println(SECRET_MQTT_BROKER);

  bool connected = false;
  if (strlen(SECRET_MQTT_USER) > 0) {
    connected = _mqttClient.connect(SECRET_MQTT_CLIENT_ID, SECRET_MQTT_USER,
                                    SECRET_MQTT_PASSWORD);
  } else {
    connected = _mqttClient.connect(SECRET_MQTT_CLIENT_ID);
  }

  if (connected) {
    Serial.println("[+] MQTT da ket noi thanh cong!");

    _mqttClient.subscribe(TOPIC_SCREEN_POWER_SET);
    _mqttClient.subscribe(TOPIC_SCREEN_PAGE_SET);
    _mqttClient.subscribe(TOPIC_SCREEN_MSG_SET);
    _mqttClient.subscribe(TOPIC_VIBRATE_SET);
    _mqttClient.subscribe(TOPIC_RESET_STEPS_SET);
    _mqttClient.subscribe(TOPIC_FALL_DISMISS);

    Serial.println("[+] Da dang ky xong cac Topic dieu khien tu Web!");
  } else {
    Serial.printf("[-] MQTT ket noi that bai, ma loi rc=%d\n",
                  _mqttClient.state());
  }
}

void MqttService::handleMessage(char *topic, byte *payload,
                                unsigned int length) {
  char message[64];
  unsigned int copyLen = (length < sizeof(message) - 1) ? length : (sizeof(message) - 1);
  memcpy(message, payload, copyLen);
  message[copyLen] = '\0';

  while (copyLen > 0 && (message[copyLen - 1] == ' ' || message[copyLen - 1] == '\r' ||
                         message[copyLen - 1] == '\n')) {
    message[--copyLen] = '\0';
  }

  Serial.printf("[RX MQTT] Topic: %s | Payload: %s\n", topic, message);

  if (strcmp(topic, TOPIC_SCREEN_POWER_SET) == 0) {
    bool on = (strcasecmp(message, "ON") == 0);
    if (_onScreenPower) _onScreenPower(on);
    publishScreenStatus(on ? "ON" : "OFF");
  } else if (strcmp(topic, TOPIC_SCREEN_PAGE_SET) == 0) {
    int targetPage = atoi(message);
    if (targetPage >= 0 && targetPage <= 3) {
      if (_onScreenPage) _onScreenPage(targetPage);
      publishPageStatus(targetPage);
    }
  } else if (strcmp(topic, TOPIC_SCREEN_MSG_SET) == 0) {
    if (_onScreenMsg) _onScreenMsg(message);
  } else if (strcmp(topic, TOPIC_VIBRATE_SET) == 0) {
    if (_onVibrate) _onVibrate(1500);
  } else if (strcmp(topic, TOPIC_RESET_STEPS_SET) == 0) {
    if (strcasecmp(message, "RESET") == 0 && _onResetSteps) {
      _onResetSteps();
    }
  } else if (strcmp(topic, TOPIC_FALL_DISMISS) == 0) {
    if (_onFallDismiss) _onFallDismiss();
  }
}

void MqttService::publishScreenStatus(const char *state) {
  if (_mqttClient.connected()) {
    _mqttClient.publish(TOPIC_SCREEN_POWER_STATUS, state);
  }
}

void MqttService::publishPageStatus(int page) {
  if (_mqttClient.connected()) {
    char pageBuf[4];
    snprintf(pageBuf, sizeof(pageBuf), "%d", page);
    _mqttClient.publish(TOPIC_SCREEN_PAGE_STATUS, pageBuf);
  }
}

void MqttService::publishFallAlert(float peakMs2) {
  if (_mqttClient.connected()) {
    char alertBuf[64];
    snprintf(alertBuf, sizeof(alertBuf),
             "{\"alert\":\"FALL_DETECTED\",\"mag_ms2\":%.2f}", peakMs2);
    _mqttClient.publish(TOPIC_FALL_ALERT, alertBuf);
  }
}

void MqttService::publishFallCleared() {
  if (_mqttClient.connected()) {
    _mqttClient.publish(TOPIC_FALL_ALERT, "{\"alert\":\"CLEARED\"}");
  }
}

void MqttService::sendTelemetry(const TelemetryData &data) {
  if (!_mqttClient.connected()) return;

  uint32_t freeHeap = ESP.getFreeHeap();
  uint32_t totalHeap = ESP.getHeapSize();
  float heapPct = totalHeap > 0 ? (((float)(totalHeap - freeHeap) / totalHeap) * 100.0f) : 0.0f;
  int rssi = WiFi.RSSI();
  float chipTemp = temperatureRead();
  unsigned long uptimeSec = millis() / 1000;
  uint32_t sketchSize = ESP.getSketchSize();
  uint32_t flashSize = ESP.getFlashChipSize();

  char jsonBuffer[640];
  int len = snprintf(
      jsonBuffer, sizeof(jsonBuffer),
      "{\"hr\":%d,\"spo2\":%.1f,\"steps\":%lu,\"sensor_temp\":%.1f,"
      "\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,"
      "\"ax_ms2\":%.2f,\"ay_ms2\":%.2f,\"az_ms2\":%.2f,\"a_mag_ms2\":%.2f,"
      "\"fall\":%s,\"finger\":%s,\"max_ready\":%s,"
      "\"screen_state\":\"%s\",\"oled_page\":%d,"
      "\"free_heap\":%u,\"total_heap\":%u,\"heap_pct\":%.1f,"
      "\"chip_temp\":%.1f,\"rssi\":%d,\"uptime\":%lu,"
      "\"cpu_freq\":%u,\"sketch_size\":%u,\"flash_size\":%u}",
      data.hr, data.spo2, data.steps, data.sensorTemp, data.ax_g, data.ay_g,
      data.az_g, data.ax_ms2, data.ay_ms2, data.az_ms2, data.a_mag_ms2,
      data.fall ? "true" : "false", data.finger ? "true" : "false",
      data.maxReady ? "true" : "false", data.screenState, data.oledPage,
      freeHeap, totalHeap, heapPct, chipTemp, rssi, uptimeSec,
      ESP.getCpuFreqMHz(), sketchSize, flashSize);

  if (len > 0 && len < (int)sizeof(jsonBuffer)) {
    _mqttClient.publish(TOPIC_TELEMETRY, jsonBuffer);
  }
}
