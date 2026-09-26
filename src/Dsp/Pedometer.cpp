#include "Dsp/Pedometer.h"

Pedometer::Pedometer()
    : _stepCount(0), _stepArmed(false), _lastStepMillis(0),
      _lastSavedStepCount(0), _lastSaveMillis(0) {}

void Pedometer::begin() {
  _prefs.begin(NVS_NAMESPACE, false);
  _stepCount = _prefs.getULong(NVS_KEY_STEPS, 0);
  _lastSavedStepCount = _stepCount;
  _lastSaveMillis = millis();
  Serial.printf("[PEDOMETER NVS] Da nap so buoc chan da luu tu Flash: %lu buoc\n", _stepCount);
}

void Pedometer::saveToNvs() {
  _prefs.putULong(NVS_KEY_STEPS, _stepCount);
  _lastSavedStepCount = _stepCount;
  _lastSaveMillis = millis();
}

void Pedometer::checkAutoSave() {
  if (_stepCount == _lastSavedStepCount) return;

  unsigned long now = millis();
  // Lưu nếu đã qua NVS_SAVE_INTERVAL_MS (60s) hoặc chênh lệch >= NVS_MIN_STEP_DIFF (15 bước)
  if ((now - _lastSaveMillis >= NVS_SAVE_INTERVAL_MS) ||
      (_stepCount - _lastSavedStepCount >= NVS_MIN_STEP_DIFF)) {
    saveToNvs();
  }
}

void Pedometer::reset() {
  _stepCount = 0;
  saveToNvs();
  Serial.println("[PEDOMETER] Da reset so buoc chan ve 0.");
}

void Pedometer::update(float magnitude) {
  unsigned long now = millis();

  if (magnitude < STEP_THRESHOLD_LOW) {
    _stepArmed = true;
  } else if (_stepArmed && magnitude > STEP_THRESHOLD_HIGH) {
    if (now - _lastStepMillis > STEP_DEBOUNCE_MS) {
      _stepCount++;
      _lastStepMillis = now;
      _stepArmed = false;
      checkAutoSave();
    }
  }
}
