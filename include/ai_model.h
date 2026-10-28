#pragma once

#include <Arduino.h>

// Feeds one 6-axis MPU6050 sample into the Edge Impulse ring buffer.
// No-op when ENABLE_EDGE_AI=0.
void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz);
