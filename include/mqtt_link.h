#pragma once

#include <Arduino.h>

// One-way telemetry + command bridge to the public EMQX broker.
// Telemetry:  bioband/vtt132109/dev01/telemetry   (retained)
// Presence:   bioband/vtt132109/dev01/status      (online/offline, retained, LWT)
// Alerts:     bioband/vtt132109/dev01/fall/alert  (state transitions only)
// Commands:   bioband/vtt132109/dev01/{cancel,test_hw,clear_nvs,set_thresh,set_time}
void mqttLinkBegin();
void mqttLinkLoop(uint32_t now);
bool mqttLinkConnected();
