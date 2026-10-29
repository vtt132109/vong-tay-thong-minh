#include "fsm.h"
#include "ai_model.h"  // AI_PROMOTION_ENABLED guard
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
    case SystemState::Snooze: return "SNOOZE";
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
  } else if (next == SystemState::Snooze) {
    snoozeEndMs = stateEnteredMs + SNOOZE_MS;
    buzzerActive = false;
    digitalWrite(PIN_BUZZER, LOW);
    healthAbnormal = false;
    healthAbnormalSinceMs = 0;
    impactSampleCount = 0;
    freeFallLowCount = 0;
  } else if (next == SystemState::Idle) {
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
  ++fallCount;
  saveFalls();

  setState(type == AlertType::PanicSos ? SystemState::PanicSos : SystemState::Alarm, alarmReason);
  Serial.printf("[ALERT] type=%u reason=%s\n", (unsigned)type, alarmReason);
}

void startImpact(uint32_t now) {
  impactStartMs = now;
  impactSampleCount = 0;
  impactExtended = false;
  setState(SystemState::Impact);
}

void updateFallDetection(uint32_t now, float acc) {
  if (!mpuReady) return;

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
      uint32_t elapsed = now - impactStartMs;
      if (elapsed >= IMPACT_SETTLE_MS &&
          impactSampleCount < (sizeof(impactSamples) / sizeof(impactSamples[0]))) {
        impactSamples[impactSampleCount++] = acc;
      }
      if (elapsed >= INACTIVITY_WINDOW_MS + IMPACT_SETTLE_MS) {
        if (impactSampleCount < 30) {
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
        Serial.printf("[FSM] impact variance=%.3f samples=%u\n", variance, (unsigned)impactSampleCount);

        if (variance < INACTIVITY_VAR_THRESHOLD) {
          pendingAlertType = AlertType::Fall;
          setState(SystemState::Countdown, "Te nga + bat dong");
        } else if (variance > MOTION_VAR_THRESHOLD) {
          setState(SystemState::Idle);
        } else if (!impactExtended) {
          // AI may only promote an ambiguous rule result; it never cancels a
          // rule-confirmed fall. AI promotion is compiled out unless
          // AI_PROMOTION_ENABLED=1 (on-device validated model only), so the
          // rule-based FSM is the sole alarm source in the demo build.
#if AI_PROMOTION_ENABLED
          if (aiFall && aiConfidence >= AI_FALL_CONFIRM_CONFIDENCE) {
            pendingAlertType = AlertType::Fall;
            setState(SystemState::Countdown, "Te nga (AI)");
          } else
#endif
          {
            impactExtended = true;
            impactStartMs = now;
            impactSampleCount = 0;
          }
        } else {
#if AI_PROMOTION_ENABLED
          if (aiFall && aiConfidence >= AI_FALL_CONFIRM_CONFIDENCE) {
            pendingAlertType = AlertType::Fall;
            setState(SystemState::Countdown, "Te nga (AI)");
          } else
#endif
          {
            setState(SystemState::Idle);
          }
        }
      }
      break;
    }

    case SystemState::Countdown:
      if (now >= countdownEndMs) {
        enterAlarm(pendingAlertType, alarmReason, lastTotalAcc);
      }
      break;

    case SystemState::Snooze:
      if (now >= snoozeEndMs) {
        setState(SystemState::Idle);
      }
      break;

    default:
      break;
  }
}

void updateHealthGuard(uint32_t now) {
  if (state != SystemState::Idle || !maxReady || !fingerDetected || bpm <= 0.0f || spo2 == 0) {
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
    setState(SystemState::Snooze);
  }
}
