#ifndef PEDOMETER_H
#define PEDOMETER_H

#include <Arduino.h>
#include <Preferences.h>
#include "Config.h"

class Pedometer {
public:
  Pedometer();

  // Khởi tạo và nạp số bước đã lưu từ bộ nhớ Flash NVS
  void begin();

  // Cập nhật bộ đếm bước theo độ lớn vector gia tốc
  void update(float magnitude);

  // Tự động kiểm tra và lưu vào NVS nếu thỏa mãn điều kiện thời gian/chênh lệch
  void checkAutoSave();

  // Lưu tức thì vào Flash NVS
  void saveToNvs();

  unsigned long getStepCount() const { return _stepCount; }
  void reset();

  int getCalories() const { return (int)(_stepCount * 0.04f); }
  float getDistanceKm() const { return (_stepCount * 0.75f) / 1000.0f; }

private:
  unsigned long _stepCount;
  bool _stepArmed;
  unsigned long _lastStepMillis;

  Preferences _prefs;
  unsigned long _lastSavedStepCount;
  unsigned long _lastSaveMillis;
};

#endif // PEDOMETER_H
