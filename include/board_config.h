#pragma once

#include <Arduino.h>

// Hardware map from the actual build:
//   I2C SDA=GPIO8, SCL=GPIO9: SSD1306 0x3C + MPU6050 0x68 + MAX30100 0x57
//   Battery divider: not assigned yet (battery not soldered); set PIN_BATTERY_ADC when wired
//   Push button GPIO2 -> GND, active low; BOOT GPIO0 is a fallback input
//   Active buzzer -> GPIO3 (HIGH = sound); GPIO3 is a strapping pin
//   MSK-12D19 is the main power switch, not a GPIO.
static constexpr uint8_t PIN_I2C_SDA = 8;
static constexpr uint8_t PIN_I2C_SCL = 9;
static constexpr int8_t PIN_BATTERY_ADC = -1;
static constexpr uint8_t PIN_BUTTON = 2;
// Onboard BOOT button (GPIO0), active-low. Used as a fallback/diagnostic input.
static constexpr uint8_t PIN_BUTTON_ALT = 0;
static constexpr uint8_t PIN_BUZZER = 3;

static constexpr uint8_t OLED_ADDRESS = 0x3C;
static constexpr uint8_t OLED_WIDTH = 128;
static constexpr uint8_t OLED_HEIGHT = 64;

static constexpr float DEFAULT_FALL_THRESHOLD = 25.0f;
static constexpr float FREEFALL_THRESHOLD = 5.0f;
static constexpr float INACTIVITY_VAR_THRESHOLD = 0.08f;
static constexpr float MOTION_VAR_THRESHOLD = 0.8f;
static constexpr uint32_t FREEFALL_CONFIRM_MS = 60;
static constexpr uint32_t IMPACT_WINDOW_MS = 800;
static constexpr uint32_t INACTIVITY_WINDOW_MS = 3000;
static constexpr uint32_t IMPACT_SETTLE_MS = 200;
static constexpr uint32_t COUNTDOWN_MS = 10000;
static constexpr uint32_t SNOOZE_MS = 20000;
static constexpr uint32_t HEALTH_CONFIRM_MS = 10000;
static constexpr uint32_t BUTTON_LONG_MS = 3000;
static constexpr uint32_t TEST_BUZZER_MS = 2000;
static constexpr uint32_t DISPLAY_PERIOD_MS = 200;
static constexpr uint32_t TELEMETRY_PERIOD_MS = 200;
static constexpr uint32_t BATTERY_PERIOD_MS = 1000;
static constexpr uint32_t STEP_SAVE_PERIOD_MS = 60000;

// MAX30100 / PPG configuration.
static constexpr uint16_t MAX30100_LEAD_OFF_IR = 5000;
static constexpr int PPG_BUFFER_SIZE = 100;

// PPG noise handling: reject motion, reject weak/abnormal perfusion, median-filter results.
static constexpr float PPG_MOTION_ACCEL_GATE = 1.5f;   // m/s^2 deviation from 1g
static constexpr float PPG_MOTION_GYRO_GATE = 1.5f;    // rad/s
static constexpr uint32_t PPG_MOTION_HOLD_MS = 800;
static constexpr float PPG_MIN_PI = 0.10f;             // percent
static constexpr float PPG_MAX_PI = 15.0f;             // percent
static constexpr int32_t PPG_HR_MIN = 30;
static constexpr int32_t PPG_HR_MAX = 220;
static constexpr int32_t PPG_SPO2_MIN = 70;
static constexpr int32_t PPG_SPO2_MAX = 100;

// Edge AI (Edge Impulse) and data capture.
static constexpr float AI_FALL_CONFIRM_CONFIDENCE = 0.80f;
static constexpr uint32_t CAPTURE_DEFAULT_SECONDS = 60;
static constexpr uint32_t CAPTURE_MAX_SECONDS = 300;

static constexpr int WAVE_POINTS = 116;
static constexpr size_t IMPACT_SAMPLE_CAPACITY = 300;
