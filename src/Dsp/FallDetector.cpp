#include "Dsp/FallDetector.h"

FallDetector::FallDetector()
    : _state(FALL_IDLE), _freefallStartMillis(0), _impactMillis(0),
      _immobilityStartMillis(0), _alertStartMillis(0), _peakMagnitude(9.81f),
      _immobilityMinMag(999.0f), _immobilityMaxMag(-999.0f) {}

void FallDetector::triggerAlert(float peakMs2) {
  _state = FALL_ALERT_ACTIVE;
  _peakMagnitude = peakMs2;
  _alertStartMillis = millis();
  Serial.printf("\n[CANH BAO TE NGA] Xac nhan nga voi gia toc dinh: %.2f m/s2\n", peakMs2);
}

void FallDetector::dismiss() {
  _state = FALL_IDLE;
  _peakMagnitude = 9.81f;
  Serial.println("[FALL ALERT] Da huy canh bao te nga.");
}

void FallDetector::update(float magnitude) {
  unsigned long now = millis();

  switch (_state) {
  case FALL_IDLE:
    // Pha 1: Nhận diện rơi tự do (Free-fall: mất trọng lực đột ngột < 5.0 m/s^2)
    if (magnitude < FALL_FREEFALL_THRESHOLD) {
      _state = FALL_FREEFALL;
      _freefallStartMillis = now;
    }
    // Hoặc va đập trực tiếp cực mạnh (> 25 m/s^2) chuyển thẳng sang kiểm tra bất động
    else if (magnitude > (FALL_IMPACT_THRESHOLD + 4.0f)) {
      _peakMagnitude = magnitude;
      _state = FALL_CHECK_IMMOBILITY;
      _immobilityStartMillis = now;
      _immobilityMinMag = magnitude;
      _immobilityMaxMag = magnitude;
    }
    break;

  case FALL_FREEFALL:
    // Xác nhận rơi tự do duy trì tối thiểu (60ms)
    if (magnitude < FALL_FREEFALL_THRESHOLD) {
      if (now - _freefallStartMillis >= FALL_FREEFALL_MIN_MS) {
        _state = FALL_WAIT_IMPACT;
      }
    } else {
      // Thoát nếu chỉ là rung động thoáng qua (< 60ms)
      _state = FALL_IDLE;
    }
    break;

  case FALL_WAIT_IMPACT:
    // Pha 2: Chờ xung va chạm tiếp đất (> 21 m/s^2) trong vòng 1.2s
    if (magnitude > FALL_IMPACT_THRESHOLD) {
      _peakMagnitude = magnitude;
      _impactMillis = now;
      _state = FALL_CHECK_IMMOBILITY;
      _immobilityStartMillis = now;
      _immobilityMinMag = magnitude;
      _immobilityMaxMag = magnitude;
    } else if (now - _freefallStartMillis > FALL_IMPACT_WINDOW_MS) {
      // Quá 1.2s không có va đập -> Trở về bình thường
      _state = FALL_IDLE;
    }
    break;

  case FALL_CHECK_IMMOBILITY:
    // Pha 3: Kiểm tra trạng thái bất động sau cú ngã trong 2.5s
    if (magnitude < _immobilityMinMag) _immobilityMinMag = magnitude;
    if (magnitude > _immobilityMaxMag) _immobilityMaxMag = magnitude;

    // Nếu người dùng tiếp tục cử động mạnh (vung tay, đứng dậy > 16 m/s^2) -> Hủy báo động giả
    if (magnitude > 16.0f && (now - _immobilityStartMillis > 500)) {
      _state = FALL_IDLE;
      break;
    }

    // Sau 2.5s nằm bất động (biên độ dao động ổn định gần 1g) -> Kích hoạt báo động khẩn cấp!
    if (now - _immobilityStartMillis >= FALL_IMMOBILITY_WINDOW_MS) {
      triggerAlert(_peakMagnitude);
    }
    break;

  case FALL_ALERT_ACTIVE:
    // Duy trì báo động trong 15s hoặc cho đến khi dismiss (chống tràn số millis)
    if (now - _alertStartMillis >= FALL_ALERT_DURATION_MS) {
      dismiss();
    }
    break;
  }
}
