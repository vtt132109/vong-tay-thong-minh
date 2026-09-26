#ifndef OTA_SERVICE_H
#define OTA_SERVICE_H

#include <Arduino.h>
#include <ArduinoOTA.h>
#include "Config.h"

class OtaService {
public:
  OtaService();

  // Khởi tạo dịch vụ nạp code từ xa qua WiFi
  void begin();

  // Xử lý gói tin nạp trong vòng lặp mạng
  void update();

  bool isUpdating() const { return _isUpdating; }

private:
  bool _isUpdating;
};

#endif // OTA_SERVICE_H
