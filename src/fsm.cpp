#include "fsm.h"
#include "controls.h"
#include "storage.h"
#include <math.h>
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
  // Idle (e.g. "Huy bo") must not overwrite alarmReason: it would leak into later logs/MQTT.
  if (reason != nullptr && next != SystemState::Idle) {
    strncpy(alarmReason, reason, sizeof(alarmReason) - 1);
    alarmReason[sizeof(alarmReason) - 1] = '\0';
  }
  Serial.printf("[FSM] %s -> %s (%s)\n", stateName(previous), stateName(next),
                reason != nullptr ? reason : alarmReason);

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
//   A') (C6) ONE model alone (max(MLP, CNN) >= AI_SINGLE_P) may fire, but only while the FSM is in
//      FREE_FALL/IMPACT (mechanical evidence of an impact) and the AI window is fresh (<= 600 ms);
//   B) the rule path uses a recalibrated stillness check (settle 1.5 s, window 2 s, variance < 0.8)
//      but must be backed by the AI having seen p >= 0.5 during the last 6 s.
// Constants come from tools/ai_lab/run_fusion.py (held-out HIFD subjects 16-21, FSM tuned on 1-15):
// strict legacy rule alone catches 6/104 HIFD falls because people keep moving for >1 s after the
// impact; recalibrated rule alone gives ~18 false alarms/h (claps); AI-gated gives 31/31, 1 FA.
// Path A' numbers (PLAN.md "Ket luan F4"): nested leave-one-subject-out on HIFD, 102/104 falls,
// FA 2 in 1.801 h (C1 without A': FA 1); with one model broken it keeps 96/97 where C1 keeps 0.
// ---------------------------------------------------------------------------------------------
static constexpr uint32_t AI_SETTLE_MS = 1500;
static constexpr uint32_t AI_WINDOW_MS = 2000;
static constexpr float AI_STILL_VAR = 0.8f;
static constexpr float AI_MOTION_VAR = 4.0f;
static constexpr float AI_SUPPORT_P = 0.5f;
// C6 path A': one model alone may fire, but only with mechanical evidence of an impact.
// t_hi = 0.95 chosen by nested leave-one-subject-out selection (21/21 folds),
// dataset/ai_results/final_config.json -> candidates.C6.  Set to 2.0f to fall back to C1.
static constexpr float AI_SINGLE_P = 0.95f;
static constexpr uint32_t AI_WINDOW_FRESH_MS = 600;
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

  // Path A': the window must be fresh so a stale clap window cannot "hang" and fire later; the
  // offline scorer evaluates A' once per window.  aiProbCnn is -1 when the CNN did not run.
  const bool aiWindowFresh = (aiWindowMs != 0) &&
      // signed difference: aiWindowMs is taken from millis() inside the same loop pass, a few ms
      // after the caller's `now`, so an unsigned subtraction would wrap and drop that very tick.
      ((int32_t)(now - aiWindowMs) <= (int32_t)AI_WINDOW_FRESH_MS);
  const bool aiSingleStrong = aiWindowFresh &&
      ((isfinite(aiProbMlp) && aiProbMlp >= AI_SINGLE_P) ||
       (isfinite(aiProbCnn) && aiProbCnn >= AI_SINGLE_P));
  const bool aiSingleGate = aiSingleStrong &&
      (state == SystemState::FreeFall || state == SystemState::Impact);

  if (aiAlarmEnabled && (aiFall || aiSingleGate) &&
      (state == SystemState::Idle || state == SystemState::FreeFall || state == SystemState::Impact) &&
      (lastAiAlertMs == 0 || now - lastAiAlertMs > AI_ALERT_COOLDOWN_MS)) {
    lastAiAlertMs = now;
    pendingAlertType = AlertType::Fall;
    if (aiFall) {
      Serial.printf("[FSM] AI trigger p=%.3f (mlp %.3f cnn %.3f)\n", (double)aiProbability,
                    (double)aiProbMlp, (double)aiProbCnn);
    } else {
      Serial.printf("[FSM] AI single-model trigger mlp=%.3f cnn=%.3f thr=%.2f state=%s\n",
                    (double)aiProbMlp, (double)aiProbCnn, (double)AI_SINGLE_P, stateName(state));
    }
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
        Serial.printf("[FSM] impact variance=%.3f samples=%u aiMax6s=%.2f ai=%d mlp=%.2f cnn=%.2f\n",
                      variance, (unsigned)impactSampleCount, (double)aiMax6s, ai ? 1 : 0,
                      (double)aiProbMlp, (double)aiProbCnn);

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
