#pragma once

#include <Arduino.h>

// Pushes one 6-axis MPU6050 sample into the active AI backend.
//   ENABLE_EDGE_AI=1: Edge Impulse impulse buffer (raw accel + gravity).
//   ENABLE_TINY_AI=1: HIFD tiny model buffer (100x6 @ 50 Hz, gravity removed
//                     with a low-pass estimate; gyro in rad/s).
//   Both 0: no-op.
void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz);

// AI promotion guard (compile-time).
//
// The tiny HIFD model is a research/demo backend: it was trained on a public
// dataset captured with different hardware, placement and subjects, and a
// synthetic/HIFD demo probability must NOT be able to raise a fall alarm.
// Keep this at 0 until the model is validated on-device (local subjects,
// Bio-Band hardware). The rule-based FSM stays the only alarm source while
// this is 0. The AI fields (aiLabel/aiConfidence/aiFall) are still computed
// and published to /data and MQTT telemetry; only the FSM promotion in
// src/fsm.cpp is compiled out.
#ifndef AI_PROMOTION_ENABLED
#define AI_PROMOTION_ENABLED 0
#endif
