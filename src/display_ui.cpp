#include "display_ui.h"
#include "fsm.h"
#include <stdio.h>
#include <string.h>
#include <time.h>

static const int W = OLED_WIDTH;

static uint16_t textWidth(const char *text, uint8_t size) {
  return (uint16_t)strlen(text) * 6 * size;
}

static void centerText(const char *text, int y, uint8_t size,
                       uint16_t color = SSD1306_WHITE) {
  int x = (W - (int)textWidth(text, size)) / 2;
  if (x < 0) x = 0;
  display.setTextSize(size);
  display.setTextColor(color);
  display.setCursor(x, y);
  display.print(text);
}

static void drawBattery(int x, int y, uint8_t pct) {
  display.drawRect(x, y, 13, 7, SSD1306_WHITE);
  display.fillRect(x + 13, y + 2, 2, 3, SSD1306_WHITE);
  int fill = (int)pct * 9 / 100;
  if (fill > 0) display.fillRect(x + 2, y + 2, fill, 3, SSD1306_WHITE);
}

static void drawWifiStatus() {
  if (WiFi.status() == WL_CONNECTED) {
    int rssi = WiFi.RSSI();
    int bars = rssi > -55 ? 4 : rssi > -65 ? 3 : rssi > -75 ? 2 : 1;
    for (int i = 0; i < 4; ++i) {
      int h = 2 + i * 2;
      int x = 58 + i * 4;
      if (i < bars) display.fillRect(x, 8 - h, 3, h, SSD1306_WHITE);
      else display.drawRect(x, 8 - h, 3, h, SSD1306_WHITE);
    }
  } else {
    display.setCursor(58, 1);
    display.print("AP");
  }
}

static void drawTopBar() {
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(2, 1);
  display.print("BIO-BAND");

  drawWifiStatus();

  char buf[12];
  if (batteryVoltage > 0.1f) {
    snprintf(buf, sizeof(buf), "%u", (unsigned)batteryPercent);
  } else {
    strcpy(buf, "--");
  }
  display.setCursor(112 - (int)strlen(buf) * 6, 1);
  display.print(buf);
  drawBattery(113, 1, batteryVoltage > 0.1f ? batteryPercent : 0);
  display.drawFastHLine(0, 9, W, SSD1306_WHITE);
}

static void drawHeart(int x, int y, bool filled) {
  if (filled) {
    display.fillCircle(x + 2, y + 2, 2, SSD1306_WHITE);
    display.fillCircle(x + 7, y + 2, 2, SSD1306_WHITE);
    display.fillTriangle(x, y + 3, x + 9, y + 3, x + 4, y + 9, SSD1306_WHITE);
  } else {
    display.drawCircle(x + 2, y + 2, 2, SSD1306_WHITE);
    display.drawCircle(x + 7, y + 2, 2, SSD1306_WHITE);
    display.drawLine(x, y + 3, x + 4, y + 9, SSD1306_WHITE);
    display.drawLine(x + 9, y + 3, x + 4, y + 9, SSD1306_WHITE);
  }
}

static void drawDrop(int x, int y) {
  display.fillTriangle(x + 4, y, x + 8, y + 6, x, y + 6, SSD1306_WHITE);
  display.fillCircle(x + 4, y + 6, 4, SSD1306_WHITE);
}

static void drawProgress(int y, uint32_t remainingMs, uint32_t totalMs,
                         uint16_t color) {
  if (totalMs == 0) return;
  uint32_t frac = remainingMs > totalMs ? totalMs : remainingMs;
  int w = (int)((uint64_t)(W - 16) * frac / totalMs);
  display.drawRect(8, y, W - 16, 4, color);
  if (w > 0) display.fillRect(8, y + 1, w, 2, color);
}

static void drawMain() {
  drawTopBar();

  display.setTextColor(SSD1306_WHITE);
  drawHeart(4, 10, true);
  display.setTextSize(1);
  display.setCursor(16, 12);
  display.print("HR");

  char buf[12];
  if (bpm > 0.5f) snprintf(buf, sizeof(buf), "%d", (int)(bpm + 0.5f));
  else strcpy(buf, "--");
  display.setTextSize(2);
  display.setCursor(4, 20);
  display.print(buf);
  display.setTextSize(1);
  display.setCursor(44, 26);
  display.print("BPM");

  display.setTextSize(1);
  display.setCursor(70, 12);
  display.print("SpO2");
  drawDrop(116, 11);
  if (spo2 > 0) snprintf(buf, sizeof(buf), "%u", (unsigned)spo2);
  else strcpy(buf, "--");
  display.setTextSize(2);
  display.setCursor(70, 20);
  display.print(buf);
  display.setTextSize(1);
  display.setCursor(70 + (int)strlen(buf) * 12 + 2, 28);
  display.print("%");

  display.drawFastVLine(64, 11, 26, SSD1306_WHITE);
  display.drawFastHLine(0, 37, W, SSD1306_WHITE);

  struct tm tmNow;
  bool haveTime = getLocalTime(&tmNow, 0);
  char timeBuf[8] = "--:--";
  char secBuf[4] = "";
  char dateBuf[8] = "--/--";
  if (haveTime) {
    strftime(timeBuf, sizeof(timeBuf), "%H:%M", &tmNow);
    snprintf(secBuf, sizeof(secBuf), ":%02d", tmNow.tm_sec);
    strftime(dateBuf, sizeof(dateBuf), "%d/%m", &tmNow);
  }

  display.setTextSize(2);
  display.setCursor(4, 40);
  display.print(timeBuf);
  display.setTextSize(1);
  if (haveTime) {
    display.setCursor(68, 42);
    display.print(secBuf);
  }
  display.setCursor(4, 56);
  display.print(dateBuf);

  char info[16];
  snprintf(info, sizeof(info), "S%lu", (unsigned long)stepCount);
  display.setCursor(W - 2 - (int)strlen(info) * 6, 42);
  display.print(info);
  if (batteryVoltage > 0.1f) snprintf(info, sizeof(info), "%.2fV", batteryVoltage);
  else strcpy(info, "--V");
  display.setCursor(W - 2 - (int)strlen(info) * 6, 52);
  display.print(info);

  display.display();
}

static void drawCountdown(uint32_t now) {
  bool invert = ((now / 300) & 1U) == 0;
  uint16_t fg = invert ? SSD1306_BLACK : SSD1306_WHITE;
  if (invert) display.fillRect(0, 0, W, OLED_HEIGHT, SSD1306_WHITE);

  const char *label = pendingAlertType == AlertType::Health ? "HEALTH ALERT"
                                                             : "FALL DETECTED";
  centerText(label, 1, 1, fg);

  int sec = (int)((countdownEndMs > now) ? ((countdownEndMs - now + 999) / 1000) : 0);
  char buf[8];
  snprintf(buf, sizeof(buf), "%02d", sec);
  int tw = (int)strlen(buf) * 24;
  display.setTextSize(4);
  display.setTextColor(fg);
  display.setCursor((W - tw) / 2, 9);
  display.print(buf);

  centerText("PRESS BUTTON", 42, 1, fg);
  centerText("TO CANCEL", 50, 1, fg);
  drawProgress(59, countdownEndMs > now ? countdownEndMs - now : 0,
               COUNTDOWN_MS, fg);
  display.display();
}

static void drawAlarm(uint32_t now) {
  bool invert = ((now / 400) & 1U) == 0;
  uint16_t fg = invert ? SSD1306_BLACK : SSD1306_WHITE;
  if (invert) display.fillRect(0, 0, W, OLED_HEIGHT, SSD1306_WHITE);

  centerText(state == SystemState::PanicSos ? "PANIC" : "ALARM", 2, 2, fg);
  const char *reason = "SOS";
  if (state != SystemState::PanicSos) {
    reason = pendingAlertType == AlertType::Health ? "HEALTH" : "FALL";
  }
  centerText(reason, 20, 3, fg);
  centerText("PRESS BUTTON", 46, 1, fg);
  centerText("TO STOP", 55, 1, fg);
  display.display();
}

static void drawSnooze(uint32_t now) {
  drawTopBar();
  centerText("SNOOZE", 11, 2);
  int sec = (int)((snoozeEndMs > now) ? ((snoozeEndMs - now + 999) / 1000) : 0);
  char buf[8];
  snprintf(buf, sizeof(buf), "%02ds", sec);
  centerText(buf, 27, 3);
  centerText("TAM KHOA", 53, 1);
  display.display();
}

static void drawVerifying(uint32_t now) {
  drawTopBar();
  centerText(stateName(state), 16, 2);
  char buf[24];
  snprintf(buf, sizeof(buf), "a=%.1f m/s2", lastTotalAcc);
  centerText(buf, 36, 1);
  centerText(((now / 300) & 1U) ? "VERIFYING." : "VERIFYING..", 50, 1);
  display.fillCircle(120, 60, 1, ((now / 250) & 1U) ? SSD1306_WHITE : SSD1306_BLACK);
  display.display();
}

static void drawLeadOff() {
  drawTopBar();
  int ix = 58;
  int iy = 13;
  display.drawRoundRect(ix, iy, 12, 20, 5, SSD1306_WHITE);
  display.drawLine(ix - 4, iy + 18, ix + 16, iy + 2, SSD1306_WHITE);
  centerText("LEAD-OFF", 36, 2);
  centerText("PLACE FINGER ON SENSOR", 54, 1);
  display.display();
}

static void drawMotion() {
  drawTopBar();
  centerText("MOVING", 18, 2);
  centerText("HOLD STILL", 38, 1);
  centerText("PPG LOCKED", 50, 1);
  display.display();
}

static void drawNotFound() {
  drawTopBar();
  centerText("MAX30100", 14, 2);
  centerText("NOT FOUND", 32, 2);
  centerText("CHECK I2C 8/9 + 3V3", 54, 1);
  display.display();
}

static void drawButtonTest() {
  drawTopBar();
  centerText("BUTTON OK", 18, 2);
  centerText("GPIO2 / BOOT", 38, 1);
  centerText("NUT DA HOAT DONG", 50, 1);
  display.display();
}

void renderBootScreen() {
  if (!oledReady) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(16, 8);
  display.print("BIO-BAND");
  centerText("ESP32-S3 WEARABLE", 26, 1);

  const int xs[] = {10, 32, 44, 52, 56, 60, 64, 70, 78, 92, 104, 118};
  const int ys[] = {40, 40, 40, 40, 32, 44, 36, 40, 40, 40, 40, 40};
  for (int i = 0; i < 11; ++i) {
    display.drawLine(xs[i], ys[i], xs[i + 1], ys[i + 1], SSD1306_WHITE);
  }

  display.setTextSize(1);
  display.setCursor(31, 48);
  display.print("SENSOR INIT");
  display.setCursor(34, 57);
  display.print("STARTING...");
  display.display();
}

void renderDisplay(uint32_t now) {
  if (!oledReady) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  if (state == SystemState::Idle && buttonTestUntilMs > now) {
    drawButtonTest();
    return;
  }

  if (state == SystemState::Countdown) {
    drawCountdown(now);
    return;
  }
  if (state == SystemState::Alarm || state == SystemState::PanicSos) {
    drawAlarm(now);
    return;
  }
  if (state == SystemState::Snooze) {
    drawSnooze(now);
    return;
  }
  if (state == SystemState::FreeFall || state == SystemState::Impact ||
      state == SystemState::Inactivity) {
    drawVerifying(now);
    return;
  }
  if (!maxReady) {
    drawNotFound();
    return;
  }
  if (!fingerDetected) {
    drawLeadOff();
    return;
  }
  if (ppgMotion) {
    drawMotion();
    return;
  }
  drawMain();
}
