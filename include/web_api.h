#pragma once

#include <ArduinoJson.h>
#include "app_state.h"

void publishTelemetry(uint32_t now);
bool readTelemetry(TelemetrySnapshot &out);
// Single JSON schema for /data and the MQTT telemetry topic.
void fillTelemetryJson(JsonDocument &doc, const TelemetrySnapshot &t);
void startNetwork();
void networkTask(void *arg);
