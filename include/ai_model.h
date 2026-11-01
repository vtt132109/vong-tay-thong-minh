#pragma once

#include <Arduino.h>

// Pushes one 6-axis MPU6050 sample into the active AI backend.
//   ENABLE_EDGE_AI=1: Edge Impulse impulse buffer (raw accel + gravity).
//   ENABLE_TINY_AI=1: HIFD tiny model buffer (100x6 @ 50 Hz, gravity removed
//                     with a low-pass estimate; gyro in rad/s).
//   Both 0: no-op.
void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz);

// Runs fixture windows through the on-chip models at boot (compares with the numpy reference).
bool aiSelfTest();

// Hardware-in-the-loop helper: runs one 100x6 window (gravity-removed accel m/s^2, gyro rad/s,
// row-major [sample][6]) through the on-chip models. pCnn is -1 when the CNN is not compiled in.
bool aiEvalWindow(const float *win, float *pMlp, float *pCnn);

// AI alarm mode is a RUNTIME switch (aiAlarmEnabled, NVS key "aiarm", POST /ai_mode?val=0|1).
//
// OFF (default): the AI only computes and publishes probabilities; the rule-based FSM is the sole
//                alarm source. The models were trained on public HIFD data (different sensor,
//                placement and subjects) and have not been validated on people wearing Bio-Band.
// ON:            the AI may start a COUNTDOWN (src/fsm.cpp). Switch it on only for supervised tests
//                or a demo; every alarm can still be cancelled with the button.
