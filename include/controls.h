#pragma once

#include "app_state.h"

void updateButton(uint32_t now);
void updateBuzzer(uint32_t now);
// Drive (true) or release (false, high-Z) the shared buzzer/button net.
void buzzerNetSet(bool on);
void handleCommands(uint32_t now);
