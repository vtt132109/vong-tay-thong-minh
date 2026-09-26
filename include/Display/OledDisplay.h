#ifndef OLED_DISPLAY_H
#define OLED_DISPLAY_H

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Arduino.h>
#include <Wire.h>
#include "Config.h"

class OledDisplay {
public:
  OledDisplay();

  bool begin();
  bool isReady() const { return _ready; }

  void setPower(bool on);
  bool isPowerOn() const { return _screenOn; }

  void setPage(int page);
  int getPage() const { return _currentPage; }

  void setMessage(const char *msg, unsigned long durationMs = 6000);

  // Vẽ khung hình tổng thể với đồ thị sóng PPG và đồng hồ thời gian thực NTP
  void render(int hr, float spo2, float sensorTemp, bool maxReady,
              bool fingerDetected, unsigned long steps, float ax_ms2,
              float ay_ms2, float az_ms2, float a_mag_ms2, bool fallAlert,
              float peakFallMs2, bool isVibrating, const int8_t *ppgWave,
              bool pulseBeating, const char *timeStr, const char *dateStr,
              bool wifiConnected);

private:
  Adafruit_SSD1306 _display;
  bool _ready;
  bool _screenOn;
  int _currentPage;
  char _customMessage[33];
  unsigned long _messageExpireMillis;

  void drawHeartIcon(int x, int y, bool big);
  void drawWaveform(int x, int y, int w, int h, const int8_t *wave);

  void renderWatchfacePage(const char *timeStr, const char *dateStr,
                           unsigned long steps, int hr, bool wifiConnected);
  void renderHealthPage(int hr, float spo2, float sensorTemp, bool maxReady,
                        bool fingerDetected, bool isVibrating,
                        const int8_t *ppgWave, bool pulseBeating,
                        const char *timeStr);
  void renderStepPage(unsigned long steps);
  void renderMotionPage(float ax_ms2, float ay_ms2, float az_ms2,
                        float a_mag_ms2, bool fallAlert);
  void renderFallAlertScreen(float peakFallMs2);
  void renderMessagePopup();
};

#endif // OLED_DISPLAY_H
