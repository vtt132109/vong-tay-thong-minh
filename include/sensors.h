#pragma once

#include "app_state.h"

uint8_t lipoPercent(float voltage);
float readBatteryVoltage();
void processMaxSamples(uint32_t now, bool motion);
void updatePedometer(uint32_t now, float acc);
