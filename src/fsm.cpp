#include "fsm.h"
#include "controls.h"
#include "storage.h"
#include <stdio.h>
#include <string.h>

const char *stateName(SystemState s) {
  switch (s) {
    case SystemState::Idle: return "IDLE";
    case SystemState::FreeFall: return "FREE_FALL";
    case SystemState::Impact: return "IMPACT";
    case SystemState::Inactivity: return "INACTIVITY";
    case SystemState::Countdown: return "COUNTDOWN";
    case SystemState::Alarm: return "ALARM";
    case SystemState::PanicSos: return "PANIC_SOS";
  }
  return "IDLE";
}

void setState(SystemState next, const char *reason) {
  if (state == next) return;
  SystemState previous = state;
  state = next;
  stateEnteredMs = millis();
  if (reason != nullptr) {
    strncpy(alarmReason, reason, sizeof(alarmReason) - 1);
    alarmReason[sizeof(alarmReason) - 1] = '\0';
  }
  Serial.printf("[FSM] %s -> %s (%s)\n", stateName(previous), stateName(next), alarmReason);

  if (next == SystemState::Countdown) {
    countdownEndMs = stateEnteredMs + COUNTDOWN_MS;
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
  } else if (next == SystemState::Idle) {
    buzzerActive = false;
    buzzerNetSet(false);
    freeFallLowCount = 0;
    impactSampleCount = 0;
    impactExtended = false;
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
  }
}

void enterAlarm(AlertType type, const char *reason, float impact) {
  if (state == SystemState::Alarm || state == SystemState::PanicSos) return;
  pendingAlertType = type;
  strncpy(alarmReason, reason, sizeof(alarmReason) - 1);
  alarmReason[sizeof(alarmReason) - 1] = '\0';
  if (type == AlertType::Fall && !replayActive) {  // replay tests must not change the stored counter
    ++fallCount;
    saveFalls();
  }

  setState(type == AlertType::PanicSos ? SystemState::PanicSos : SystemState::Alarm, alarmReason);
  Serial.printf("[ALERT] type=%u reason=%s\n", (unsigned)type, alarmReason);
}

void startImpact(uint32_t now) {
  impactStartMs = now;
  impactSampleCount = 0;
  impactExtended = false;
  setState(SystemState::Impact);
}

// ---------------------------------------------------------------------------------------------
// Fall detection.
//
// Rule path (always on): free-fall -> impact -> stillness check.
// AI mode (aiAlarmEnabled, runtime toggle stored in NVS, default OFF until validated on people):
//   A) the CNN+MLP ensemble fires (aiFall) -> COUNTDOWN straight away (~0.2 s after the impact);
//   B) the rule path uses a recalibrated stillness check (settle 1.5 s, window 2 s, variance < 0.8)
//      but must be backed by the AI having seen p >= 0.5 during the last 6 s.
// Constants come from tools/ai_lab/run_fusion.py (held-out HIFD subjects 16-21, FSM tuned on 1-15):
// strict legacy rule alone catches 6/104 HIFD falls because people keep moving for >1 s after the
// impact; recalibrated rule alone gives ~18 false alarms/h (claps); AI-gated gives 31/31, 1 FA.
// ---------------------------------------------------------------------------------------------
static constexpr uint32_t AI_SETTLE_MS = 1500;
static constexpr uint32_t AI_WINDOW_MS = 2000;
static constexpr float AI_STILL_VAR = 0.8f;
static constexpr float AI_MOTION_VAR = 4.0f;
static constexpr float AI_SUPPORT_P = 0.5f;
static constexpr uint32_t AI_ALERT_COOLDOWN_MS = 30000;
static uint32_t lastAiAlertMs = 0;

// Test helper (serial replay mode): forget cooldowns and return to IDLE.
void fsmReset() {
  lastAiAlertMs = 0;
  lastDirectImpactMs = 0;
  freeFallLowCount = 0;
  impactSampleCount = 0;
  impactExtended = false;
  setState(SystemState::Idle);
}

void updateFallDetection(uint32_t now, float acc) {
  if (!mpuReady) return;

  if (aiAlarmEnabled && aiFall &&
      (state == SystemState::Idle || state == SystemState::FreeFall || state == SystemState::Impact) &&
      (lastAiAlertMs == 0 || now - lastAiAlertMs > AI_ALERT_COOLDOWN_MS)) {
    lastAiAlertMs = now;
    pendingAlertType = AlertType::Fall;
    Serial.printf("[FSM] AI trigger p=%.3f (mlp %.3f cnn %.3f)\n", (double)aiProbability,
                  (double)aiProbMlp, (double)aiProbCnn);
    setState(SystemState::Countdown, "Te nga (AI)");
    return;
  }

  switch (state) {
    case SystemState::Idle:
      if (acc < FREEFALL_THRESHOLD) {
        if (++freeFallLowCount >= 3) {
          freeFallStartMs = now;
          setState(SystemState::FreeFall);
        }
      } else {
        freeFallLowCount = 0;
      }
      if (state == SystemState::Idle && acc >= fallThreshold &&
          (lastDirectImpactMs == 0 || now - lastDirectImpactMs > 2000)) {
        lastDirectImpactMs = now;
        startImpact(now);
      }
      break;

    case SystemState::FreeFall:
      if (acc >= fallThreshold) {
        lastDirectImpactMs = now;
        startImpact(now);
      } else if (now - freeFallStartMs > IMPACT_WINDOW_MS) {
        setState(SystemState::Idle);
      }
      break;

    case SystemState::Impact: {
      const bool ai = aiAlarmEnabled;
      const uint32_t settle = ai ? AI_SETTLE_MS : IMPACT_SETTLE_MS;
      const uint32_t window = ai ? AI_WINDOW_MS : INACTIVITY_WINDOW_MS;
      const float stillVar = ai ? AI_STILL_VAR : INACTIVITY_VAR_THRESHOLD;
      const float motionVar = ai ? AI_MOTION_VAR : MOTION_VAR_THRESHOLD;
      uint32_t elapsed = now - impactStartMs;
      if (elapsed >= settle &&
          impactSampleCount < (sizeof(impactSamples) / sizeof(impactSamples[0]))) {
        impactSamples[impactSampleCount++] = acc;
      }
      if (elapsed >= window + settle) {
        if (impactSampleCount < window / 100) {
          setState(SystemState::Idle);
          break;
        }
        float sum = 0.0f;
        float sumSq = 0.0f;
        for (size_t i = 0; i < impactSampleCount; ++i) {
          sum += impactSamples[i];
          sumSq += impactSamples[i] * impactSamples[i];
        }
        float mean = sum / impactSampleCount;
        float variance = sumSq / impactSampleCount - mean * mean;
        if (variance < 0.0f) variance = 0.0f;
        Serial.printf("[FSM] impact variance=%.3f samples=%u aiMax6s=%.2f ai=%d\n", variance,
                      (unsigned)impactSampleCount, (double)aiMax6s, ai ? 1 : 0);

        if (variance < stillVar) {
          if (ai && aiMax6s < AI_SUPPORT_P) {
            // Impact followed by (almost) no motion, but the AI saw nothing fall-like: a knock or clap.
            setState(SystemState::Idle);
          } else {
            pendingAlertType = AlertType::Fall;
            setState(SystemState::Countdown, "Te nga + bat dong");
          }
        } else if (variance > motionVar) {
          setState(SystemState::Idle);
        } else if (!impactExtended) {
          impactExtended = true;
          impactStartMs = now;
          impactSampleCount = 0;
        } else {
          setState(SystemState::Idle);
        }
      }
      break;
    }

    case SystemState::Countdown:
      if (now >= countdownEndMs) {
        enterAlarm(pendingAlertType, alarmReason, lastTotalAcc);
      }
      break;

    default:
      break;
  }
}

void updateHealthGuard(uint32_t now) {
  // The first readings after placing a finger are warm-up values (HR median of 1-3 samples); judge
  // only after the finger has been on the sensor for HEALTH_WARMUP_MS.
  static uint32_t fingerSinceMs = 0;
  if (!fingerDetected) {
    fingerSinceMs = 0;
  } else if (fingerSinceMs == 0) {
    fingerSinceMs = now;
  }
  if (state != SystemState::Idle || !maxReady || !fingerDetected || bpm <= 0.0f || spo2 == 0 ||
      now - fingerSinceMs < HEALTH_WARMUP_MS) {
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
    return;
  }

  bool abnormal = (bpm < 50.0f) || (bpm > 120.0f) || (spo2 < 90);
  if (!abnormal) {
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
    return;
  }

  if (!healthAbnormal) {
    healthAbnormal = true;
    healthAbnormalSinceMs = now;
    Serial.printf("[HEALTH] abnormal start: HR=%.0f SpO2=%u\n", bpm, (unsigned)spo2);
  }
  if (now - healthAbnormalSinceMs >= HEALTH_CONFIRM_MS) {
    char reason[48];
    snprintf(reason, sizeof(reason), "Sinh trac bat thuong HR=%.0f SpO2=%u", bpm, (unsigned)spo2);
    pendingAlertType = AlertType::Health;
    setState(SystemState::Countdown, reason);
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
  }
}

void cancelAlert() {
  if (state == SystemState::Countdown || state == SystemState::Inactivity ||
      state == SystemState::Alarm || state == SystemState::PanicSos) {
    setState(SystemState::Idle, "Huy bo");
  }
}
