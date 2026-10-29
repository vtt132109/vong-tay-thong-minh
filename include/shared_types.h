#pragma once

#include <Arduino.h>

enum class SystemState : uint8_t {
  Idle,
  FreeFall,
  Impact,
  Inactivity,
  Countdown,
  Alarm,
  Snooze,
  PanicSos,
};

enum class AlertType : uint8_t {
  Fall = 1,
  Health = 2,
  PanicSos = 3,
};

enum class WebCommandType : uint8_t {
  CancelAlert = 1,
  TestHardware = 2,
  ClearData = 3,
  SetThreshold = 4,
  StartCapture = 5,
  StopCapture = 6,
};

struct TelemetrySnapshot {
  SystemState state = SystemState::Idle;
  float total_acc = 0.0f;
  float fall_threshold = 25.0f;
  float battery_voltage = 0.0f;
  uint8_t battery_percent = 0;
  float bpm = 0.0f;
  uint8_t spo2 = 0;
  float raw_bpm = 0.0f;
  uint8_t raw_spo2 = 0;
  bool finger_detected = false;
  bool max_connected = false;
  bool mpu_connected = false;
  bool buzzer_active = false;
  bool wifi_connected = false;
  bool lead_off = true;
  bool ppg_motion = false;
  uint32_t total_fall_events = 0;
  uint32_t countdown_remaining_ms = 0;
  uint32_t snooze_remaining_ms = 0;
  float loop_fps = 0.0f;
  uint32_t steps = 0;
  float distance_km = 0.0f;
  float calories = 0.0f;
  float ram_pct = 0.0f;
  char ai_label[16] = "n/a";
  float ai_confidence = 0.0f;
  float ai_probability = 0.0f;
  float ai_threshold = 0.0f;
  float ai_window_peak = 0.0f;
  uint8_t ai_window_fill = 0;
  uint32_t ai_inference_count = 0;
  uint32_t ai_inference_us = 0;
  bool ai_fall = false;
};

struct WebCommand {
  WebCommandType type = WebCommandType::CancelAlert;
  float value = 0.0f;
};
