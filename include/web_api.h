#pragma once

#include "app_state.h"

void publishTelemetry(uint32_t now);
bool readTelemetry(TelemetrySnapshot &out);
void startNetwork();
void networkTask(void *arg);
