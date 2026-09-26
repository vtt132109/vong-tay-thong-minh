#ifndef MAX30102_DRIVER_H
#define MAX30102_DRIVER_H

#include <Arduino.h>
#include <Wire.h>
#include "Config.h"

class Max30102Driver {
public:
  Max30102Driver();

  // Khởi tạo cảm biến và khôi phục bus I2C nếu cần
  bool begin();

  // Kiểm tra trạng thái sẵn sàng
  bool isReady() const { return _ready; }

  // Khôi phục bus I2C khi bị kẹt (SDA stuck low)
  static void recoverBus();

  // Đọc ghi thanh ghi I2C
  bool writeReg(uint8_t reg, uint8_t val);
  uint8_t readReg(uint8_t reg);

  // Đọc dữ liệu mẫu từ FIFO
  uint8_t availableSamples();
  bool readFifo(uint32_t &red, uint32_t &ir);

  // Chế độ tiết kiệm năng lượng Eco-Sense
  void setEcoMode(bool eco);
  bool isEcoMode() const { return _ecoMode; }

  // Đọc nhiệt độ cảm biến không khóa CPU (Non-blocking Asynchronous)
  float updateTemperature();
  float getTemperature() const { return _sensorTemp; }

private:
  bool _ready;
  bool _ecoMode;
  float _sensorTemp;
  unsigned long _lastTempTriggerMillis;
  bool _tempConverting;
};

#endif // MAX30102_DRIVER_H
