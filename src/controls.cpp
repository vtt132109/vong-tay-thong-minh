#include "controls.h"
#include "fsm.h"
#include "storage.h"
#include <math.h>

static bool externalArmed = false;
static bool bootArmed = false;
static bool warnedExternal = false;
static int lastButton = -1;
static int lastBoot = -1;
static bool rawDown = false;
static bool stableDown = false;
static uint32_t rawChangedMs = 0;
// Shared net (buzzer GPIO3 + button GPIO2 + GPIO1): the button is readable only while the net is released.
static bool netDriven = true;  // forces the first release to configure the pin
static uint32_t netReleasedMs = 0;
static int lastValidG2 = HIGH;

void buzzerNetSet(bool on) {
  if (on == netDriven) return;
  netDriven = on;
  if (on) {
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, HIGH);
  } else {
    pinMode(PIN_BUZZER, INPUT);
    netReleasedMs = millis();
  }
}

void updateButton(uint32_t now) {
  const bool netReadable = !netDriven && (now - netReleasedMs) >= 10;
  // Released, the shared net idles at ~0.55 V (below the digital LOW threshold); pressed it is ~0 V. Only the ADC
  // tells the two apart (measured with #NETTEST), so a press is < BUTTON_ADC_PRESSED_MV.
  if (netReadable) lastValidG2 = (analogReadMilliVolts(PIN_BUTTON) < BUTTON_ADC_PRESSED_MV) ? LOW : HIGH;
  int g2 = lastValidG2;
  int g0 = digitalRead(PIN_BUTTON_ALT);

  bool externalDown = (g2 == LOW);
  bool bootDown = (g0 == LOW);
  // The external line is trusted only after it has idled HIGH for EXT_ARM_MS; a loose wire that only blips
  // HIGH for a moment must not arm it (it would read as a permanent press and fire a false SOS).
  static uint32_t externalHighSinceMs = 0;
  if (externalDown) {
    externalHighSinceMs = 0;
  } else if (externalHighSinceMs == 0) {
    externalHighSinceMs = now;
  }
  if (!externalArmed && externalHighSinceMs != 0 && now - externalHighSinceMs >= 2000) externalArmed = true;
  if (!bootArmed && !bootDown) bootArmed = true;
  if (!externalArmed && !warnedExternal && now > 3000) {
    warnedExternal = true;
    Serial.println("[BTN] external GPIO2 stuck LOW; check wiring; BOOT works");
  }

  if (g2 != lastButton || g0 != lastBoot) {
    Serial.printf("[BTN] GPIO2=%d BOOT=%d extArmed=%d bootArmed=%d\n",
                  g2, g0, externalArmed ? 1 : 0, bootArmed ? 1 : 0);
    lastButton = g2;
    lastBoot = g0;
  }

  // A stuck-low external line must not block the onboard BOOT fallback.
  bool rawPressed = (externalArmed && externalDown) || (bootArmed && bootDown);
  if (rawPressed != rawDown) {
    rawDown = rawPressed;
    rawChangedMs = now;
  }
  if (rawDown != stableDown && now - rawChangedMs >= BUTTON_DEBOUNCE_MS) {
    stableDown = rawDown;
  }
  bool down = stableDown;
  if (down && !buttonDown) {
    buttonDown = true;
    buttonDownMs = now;
    buttonLongHandled = false;
  } else if (down && buttonDown && !buttonLongHandled && (now - buttonDownMs >= BUTTON_LONG_MS)) {
    buttonLongHandled = true;
    Serial.printf("[BTN] long press state=%s\n", stateName(state));
    if (state == SystemState::Idle) {
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
  if (replayActive) {  // serial replay test: never sound the buzzer
    if (buzzerActive) {
      buzzerActive = false;
      buzzerNetSet(false);
    }
    return;
  }
  if (now < testBuzzerUntilMs) {
    on = true;
  } else if (state == SystemState::Countdown) {
    on = ((now - stateEnteredMs) % 1000) < 100;
  } else if (state == SystemState::Alarm || state == SystemState::PanicSos) {
    // 180 ms on / 60 ms released: the gap lets the shared net be read so the button can still cancel.
    on = ((now - stateEnteredMs) % 240) < 180;
  }
  if (on != buzzerActive) {
    buzzerActive = on;
    buzzerNetSet(on);
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
      case WebCommandType::SetAiMode:
        aiAlarmEnabled = cmd.value >= 0.5f;
        saveAiMode();
        Serial.printf("[AI] alarm mode %s\n", aiAlarmEnabled ? "ON" : "OFF");
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
