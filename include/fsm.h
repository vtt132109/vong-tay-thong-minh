#pragma once

#include "app_state.h"

const char *stateName(SystemState s);
void setState(SystemState next, const char *reason = nullptr);
void enterAlarm(AlertType type, const char *reason, float impact);
void startImpact(uint32_t now);
void updateFallDetection(uint32_t now, float acc);
void updateHealthGuard(uint32_t now);
void cancelAlert();
