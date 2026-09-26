#ifndef FALL_DETECTOR_H
#define FALL_DETECTOR_H

#include <Arduino.h>
#include "Config.h"

enum FallState {
  FALL_IDLE,
  FALL_FREEFALL,
  FALL_WAIT_IMPACT,
  FALL_CHECK_IMMOBILITY,
  FALL_ALERT_ACTIVE
};

class FallDetector {
public:
  FallDetector();

  // Cập nhật máy trạng thái 3 pha với độ lớn gia tốc
  void update(float magnitude);

  bool isAlert() const { return _state == FALL_ALERT_ACTIVE; }
  void dismiss();
  void triggerAlert(float peakMs2);

  float getPeakMagnitude() const { return _peakMagnitude; }
  FallState getState() const { return _state; }

private:
  FallState _state;
  unsigned long _freefallStartMillis;
  unsigned long _impactMillis;
  unsigned long _immobilityStartMillis;
  unsigned long _alertExpireMillis;
  float _peakMagnitude;
  float _immobilityMinMag, _immobilityMaxMag;
};

#endif // FALL_DETECTOR_H
