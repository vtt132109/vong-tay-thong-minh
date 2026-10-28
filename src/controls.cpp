#include "controls.h"
#include "fsm.h"
#include "storage.h"
#include <math.h>

static bool externalArmed = false;
static bool bootArmed = false;
static bool warnedExternal = false;
static int lastGpio1 = -1;
static int lastGpio2 = -1;
static int lastGpio0 = -1;

void updateButton(uint32_t now) {
  int g1 = digitalRead(PIN_BUTTON);
  int g2 = digitalRead(PIN_BUTTON_MIRROR);
  int g0 = digitalRead(PIN_BUTTON_ALT);

  bool externalDown = (g1 == LOW || g2 == LOW);
  bool bootDown = (g0 == LOW);
  if (!externalArmed && !externalDown) externalArmed = true;
  if (!bootArmed && !bootDown) bootArmed = true;
  if (!externalArmed && !warnedExternal && now > 3000) {
    warnedExternal = true;
    Serial.println("[BTN] external GPIO1/2 stuck LOW; check wiring; BOOT works");
  }

  if (g1 != lastGpio1 || g2 != lastGpio2 || g0 != lastGpio0) {
    Serial.printf("[BTN] GPIO1=%d GPIO2=%d BOOT=%d extArmed=%d bootArmed=%d\n",
                  g1, g2, g0, externalArmed ? 1 : 0, bootArmed ? 1 : 0);
    lastGpio1 = g1;
    lastGpio2 = g2;
    lastGpio0 = g0;
  }

  // A stuck-low external line must not block the onboard BOOT fallback.
  bool down = (externalArmed && externalDown) || (bootArmed && bootDown);
  if (down && !buttonDown) {
    buttonDown = true;
    buttonDownMs = now;
    buttonLongHandled = false;
  } else if (down && buttonDown && !buttonLongHandled && (now - buttonDownMs >= BUTTON_LONG_MS)) {
    buttonLongHandled = true;
    Serial.printf("[BTN] long press state=%s\n", stateName(state));
    if (state != SystemState::Alarm && state != SystemState::PanicSos) {
      enterAlarm(AlertType::PanicSos, "SOS khan cap", lastTotalAcc);
    }
  } else if (!down && buttonDown) {
    buttonDown = false;
    uint32_t held = now - buttonDownMs;
    if (!buttonLongHandled && held >= 40) {
      Serial.printf("[BTN] short press held=%lums state=%s\n",
                    (unsigned long)held, stateName(state));
      if (state == SystemState::Idle) buttonTestUntilMs = now + 1200;
      cancelAlert();
    }
  }
}

void updateBuzzer(uint32_t now) {
  bool on = false;
  if (now < testBuzzerUntilMs) {
    on = true;
  } else if (state == SystemState::Countdown) {
    on = ((now - stateEnteredMs) % 1000) < 100;
  } else if (state == SystemState::Alarm || state == SystemState::PanicSos) {
    on = true;
  }
  if (on != buzzerActive) {
    buzzerActive = on;
    digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
  }
}

void handleCommands(uint32_t now) {
  if (commandQueue == nullptr) return;
  WebCommand cmd;
  while (xQueueReceive(commandQueue, &cmd, 0) == pdTRUE) {
    switch (cmd.type) {
      case WebCommandType::CancelAlert:
        cancelAlert();
        break;
      case WebCommandType::TestHardware:
        testBuzzerUntilMs = now + TEST_BUZZER_MS;
        break;
      case WebCommandType::ClearData:
        clearAllData();
        break;
      case WebCommandType::SetThreshold:
        if (!isnan(cmd.value)) {
          fallThreshold = constrain(cmd.value, 10.0f, 60.0f);
          saveThreshold();
          if (!captureActive) {
            Serial.printf("[NVS] threshold=%.1f\n", fallThreshold);
          }
        }
        break;
      case WebCommandType::StartCapture:
        captureActive = true;
        captureEndMs = now + (uint32_t)(cmd.value * 1000.0f);
        if (cmd.value < 5.0f || cmd.value > (float)CAPTURE_MAX_SECONDS || captureEndMs < now) {
          captureEndMs = now + CAPTURE_DEFAULT_SECONDS * 1000UL;
        }
        break;
      case WebCommandType::StopCapture:
        captureActive = false;
        break;
    }
  }
}
