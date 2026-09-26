#include "Network/OtaService.h"

OtaService::OtaService() : _isUpdating(false) {}

void OtaService::begin() {
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPort(OTA_PORT);

  ArduinoOTA.onStart([this]() {
    _isUpdating = true;
    String type = (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
    Serial.println("\n[OTA] Bat dau nap firmware qua WiFi: " + type);
  });

  ArduinoOTA.onEnd([this]() {
    _isUpdating = false;
    Serial.println("\n[OTA] Nap hoan tat! ESP32-S3 dang khoi dong lai...");
  });

  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[OTA] Tien do: %u%%\r", (progress / (total / 100)));
  });

  ArduinoOTA.onError([this](ota_error_t error) {
    _isUpdating = false;
    Serial.printf("\n[OTA LỖI] Ma loi [%u]: ", error);
    if (error == OTA_AUTH_ERROR) Serial.println("Loi xac thuc");
    else if (error == OTA_BEGIN_ERROR) Serial.println("Loi khoi tao");
    else if (error == OTA_CONNECT_ERROR) Serial.println("Loi ket noi");
    else if (error == OTA_RECEIVE_ERROR) Serial.println("Loi nhan du lieu");
    else if (error == OTA_END_ERROR) Serial.println("Loi ket thuc");
  });

  ArduinoOTA.begin();
  Serial.printf("[+] ArduinoOTA san sang! Hostname: %s (Port %d)\n", OTA_HOSTNAME, OTA_PORT);
}

void OtaService::update() {
  ArduinoOTA.handle();
}
