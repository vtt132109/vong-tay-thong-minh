#pragma once

#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
// Optional: define AP_PASS in secrets.h to choose the setup-AP password (default: derived from the MAC).
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
