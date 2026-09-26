#ifndef MQTT_SERVICE_H
#define MQTT_SERVICE_H

#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include "Config.h"
#include "Secrets.h"

// Cấu trúc gói dữ liệu Telemetry tổng thể
struct TelemetryData {
  int hr;
  float spo2;
  unsigned long steps;
  float sensorTemp;
  float ax_g, ay_g, az_g;
  float ax_ms2, ay_ms2, az_ms2;
  float a_mag_ms2;
  bool fall;
  bool finger;
  bool maxReady;
  const char *screenState;
  int oledPage;
};

// Kiểu hàm callback điều khiển
typedef void (*ScreenPowerCallback)(bool on);
typedef void (*ScreenPageCallback)(int page);
typedef void (*ScreenMsgCallback)(const char *msg);
typedef void (*VibrateCallback)(unsigned long durationMs);
typedef void (*ResetStepsCallback)();
typedef void (*FallDismissCallback)();

class MqttService {
public:
  MqttService();

  void begin();
  void update(); // Duy trì kết nối WiFi & MQTT

  bool isConnected();
  void sendTelemetry(const TelemetryData &data);
  void publishFallAlert(float peakMs2);
  void publishFallCleared();
  void publishScreenStatus(const char *state);
  void publishPageStatus(int page);

  // Đăng ký callbacks
  void onScreenPower(ScreenPowerCallback cb) { _onScreenPower = cb; }
  void onScreenPage(ScreenPageCallback cb) { _onScreenPage = cb; }
  void onScreenMsg(ScreenMsgCallback cb) { _onScreenMsg = cb; }
  void onVibrate(VibrateCallback cb) { _onVibrate = cb; }
  void onResetSteps(ResetStepsCallback cb) { _onResetSteps = cb; }
  void onFallDismiss(FallDismissCallback cb) { _onFallDismiss = cb; }

private:
  WiFiClient _espClient;
  PubSubClient _mqttClient;
  unsigned long _lastWifiRetry;
  unsigned long _lastMqttRetry;

  ScreenPowerCallback _onScreenPower;
  ScreenPageCallback _onScreenPage;
  ScreenMsgCallback _onScreenMsg;
  VibrateCallback _onVibrate;
  ResetStepsCallback _onResetSteps;
  FallDismissCallback _onFallDismiss;

  void connectWiFi();
  void reconnectMqtt();
  void handleMessage(char *topic, byte *payload, unsigned int length);

  static MqttService *_instance;
  static void staticMqttCallback(char *topic, byte *payload, unsigned int length);
};

#endif // MQTT_SERVICE_H
