#include "storage.h"
#include <math.h>

void loadPrefs() {
  prefs.begin("bioband", false);
  if (!prefs.isKey("thresh")) prefs.putFloat("thresh", DEFAULT_FALL_THRESHOLD);
  fallThreshold = prefs.getFloat("thresh", DEFAULT_FALL_THRESHOLD);
  fallCount = prefs.getUInt("falls", 0);
  stepCount = prefs.getUInt("steps", 0);
  aiAlarmEnabled = prefs.getBool("aiarm", false);
  lastSavedSteps = stepCount;
  if (isnan(fallThreshold) || fallThreshold < 10.0f || fallThreshold > 60.0f) {
    fallThreshold = DEFAULT_FALL_THRESHOLD;
  }
}

void saveThreshold() { prefs.putFloat("thresh", fallThreshold); }
void saveFalls() { prefs.putUInt("falls", fallCount); }
void saveAiMode() { prefs.putBool("aiarm", aiAlarmEnabled); }
void saveSteps() {
  prefs.putUInt("steps", stepCount);
  lastSavedSteps = stepCount;
  lastStepSaveMs = millis();
}

void clearAllData() {
  prefs.clear();
  fallThreshold = DEFAULT_FALL_THRESHOLD;
  fallCount = 0;
  stepCount = 0;
  lastSavedSteps = 0;
  saveThreshold();
  saveFalls();
  saveSteps();
}
