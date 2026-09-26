#include "Display/OledDisplay.h"

OledDisplay::OledDisplay()
    : _display(128, 64, &Wire, -1), _ready(false), _screenOn(true),
      _currentPage(1), _messageExpireMillis(0) {
  _customMessage[0] = '\0';
}

bool OledDisplay::begin() {
  if (!_display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR)) {
    Serial.println("[-] Khong tim thay OLED SSD1306 tren bus I2C!");
    _ready = false;
    return false;
  }

  _ready = true;
  _display.clearDisplay();
  _display.ssd1306_command(SSD1306_SETCONTRAST);
  _display.ssd1306_command(OLED_CONTRAST_DEFAULT); // Giảm tương phản xuống 40% tiết kiệm 12mA
  _display.setTextSize(1);
  _display.setTextColor(SSD1306_WHITE);
  _display.setCursor(10, 15);
  _display.println("CYBERBAND S3 PRO");
  _display.setCursor(10, 30);
  _display.println("Dual-Core FreeRTOS");
  _display.setCursor(10, 45);
  _display.println("OTA & Waveform Active");
  _display.display();
  Serial.println("[+] OLED SSD1306 khoi tao thanh cong! (Eco Contrast 40%)");
  return true;
}

void OledDisplay::setPower(bool on) {
  _screenOn = on;
  if (_ready) {
    _display.ssd1306_command(on ? SSD1306_DISPLAYON : SSD1306_DISPLAYOFF);
  }
}

void OledDisplay::setPage(int page) {
  if (page >= 0 && page <= 3) {
    _currentPage = page;
    _customMessage[0] = '\0';
  }
}

void OledDisplay::setMessage(const char *msg, unsigned long durationMs) {
  strncpy(_customMessage, msg, sizeof(_customMessage) - 1);
  _customMessage[sizeof(_customMessage) - 1] = '\0';
  _messageExpireMillis = millis() + durationMs;
}

void OledDisplay::drawHeartIcon(int x, int y, bool big) {
  if (big) {
    // Trái tim đập lớn (8x7 pixel)
    _display.fillRect(x + 1, y, 2, 2, SSD1306_WHITE);
    _display.fillRect(x + 5, y, 2, 2, SSD1306_WHITE);
    _display.fillRect(x, y + 1, 8, 3, SSD1306_WHITE);
    _display.fillRect(x + 1, y + 4, 6, 1, SSD1306_WHITE);
    _display.fillRect(x + 2, y + 5, 4, 1, SSD1306_WHITE);
    _display.drawPixel(x + 3, y + 6, SSD1306_WHITE);
    _display.drawPixel(x + 4, y + 6, SSD1306_WHITE);
  } else {
    // Trái tim bình thường (6x5 pixel)
    _display.drawPixel(x + 1, y, SSD1306_WHITE);
    _display.drawPixel(x + 3, y, SSD1306_WHITE);
    _display.drawLine(x, y + 1, x + 4, y + 1, SSD1306_WHITE);
    _display.drawLine(x + 1, y + 2, x + 3, y + 2, SSD1306_WHITE);
    _display.drawPixel(x + 2, y + 3, SSD1306_WHITE);
  }
}

void OledDisplay::drawWaveform(int x, int y, int w, int h, const int8_t *wave) {
  if (!wave) return;

  // Khung chứa đồ thị
  _display.drawRect(x, y, w, h, SSD1306_WHITE);

  // Đường baseline tâm
  int centerY = y + (h / 2);
  for (int i = x + 2; i < x + w - 2; i += 4) {
    _display.drawPixel(i, centerY, SSD1306_WHITE);
  }

  // Vẽ các đoạn thẳng nối liên tiếp 64 điểm sóng
  int numPoints = min(w - 4, (int)PPG_WAVE_BUFFER_SIZE);
  int prevPlotY = centerY;

  for (int i = 0; i < numPoints; i++) {
    int curX = x + 2 + i;
    int curY = centerY - wave[i];
    curY = constrain(curY, y + 1, y + h - 2);

    if (i > 0) {
      _display.drawLine(curX - 1, prevPlotY, curX, curY, SSD1306_WHITE);
    }
    prevPlotY = curY;
  }
}

void OledDisplay::render(int hr, float spo2, float sensorTemp, bool maxReady,
                         bool fingerDetected, unsigned long steps, float ax_ms2,
                         float ay_ms2, float az_ms2, float a_mag_ms2,
                         bool fallAlert, float peakFallMs2, bool isVibrating,
                         const int8_t *ppgWave, bool pulseBeating,
                         const char *timeStr, const char *dateStr,
                         bool wifiConnected) {
  if (!_ready || (!_screenOn && !fallAlert)) return;

  _display.clearDisplay();
  _display.setTextColor(SSD1306_WHITE);

  if (fallAlert) {
    renderFallAlertScreen(peakFallMs2);
  } else if (_customMessage[0] != '\0' && millis() < _messageExpireMillis) {
    renderMessagePopup();
  } else {
    switch (_currentPage) {
    case 0:
      renderWatchfacePage(timeStr, dateStr, steps, hr, wifiConnected);
      break;
    case 1:
      renderHealthPage(hr, spo2, sensorTemp, maxReady, fingerDetected,
                       isVibrating, ppgWave, pulseBeating, timeStr);
      break;
    case 2:
      renderStepPage(steps);
      break;
    case 3:
      renderMotionPage(ax_ms2, ay_ms2, az_ms2, a_mag_ms2, fallAlert);
      break;
    default:
      renderHealthPage(hr, spo2, sensorTemp, maxReady, fingerDetected,
                       isVibrating, ppgWave, pulseBeating, timeStr);
      break;
    }
  }

  _display.display();
}

// Trang 0: Mặt đồng hồ thông minh (Watchface)
void OledDisplay::renderWatchfacePage(const char *timeStr, const char *dateStr,
                                     unsigned long steps, int hr,
                                     bool wifiConnected) {
  // Thanh trạng thái trên cùng
  _display.setTextSize(1);
  _display.setCursor(0, 0);
  _display.print(wifiConnected ? "[WF] OK" : "[WF] --");
  _display.setCursor(84, 0);
  _display.print("100% #");
  _display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  // Giờ số lớn
  _display.setTextSize(2);
  _display.setCursor(16, 16);
  if (timeStr && strlen(timeStr) >= 5) {
    _display.print(timeStr);
  } else {
    _display.print("--:--:--");
  }

  // Ngày tháng
  _display.setTextSize(1);
  _display.setCursor(20, 36);
  if (dateStr && strlen(dateStr) >= 5) {
    _display.print(dateStr);
  } else {
    _display.print("CYBERBAND S3");
  }

  // Thanh chân trang: Bước chân & Nhịp tim
  _display.drawLine(0, 48, 128, 48, SSD1306_WHITE);
  _display.setCursor(2, 53);
  _display.printf("Stp:%lu", steps);
  _display.setCursor(80, 53);
  if (hr > 0) {
    _display.printf("HR:%d", hr);
  } else {
    _display.print("HR:--");
  }
}

// Trang 1: Sức khỏe với đồ thị sóng PPG Plethysmogram & Trái tim đập
void OledDisplay::renderHealthPage(int hr, float spo2, float sensorTemp,
                                  bool maxReady, bool fingerDetected,
                                  bool isVibrating, const int8_t *ppgWave,
                                  bool pulseBeating, const char *timeStr) {
  // Tiêu đề & Trái tim nhấp nháy
  _display.setTextSize(1);
  _display.setCursor(0, 0);
  _display.print("P1:HEALTH");

  drawHeartIcon(64, 0, pulseBeating);

  _display.setCursor(80, 0);
  if (timeStr && strlen(timeStr) >= 5) {
    char shortTime[6];
    strncpy(shortTime, timeStr, 5);
    shortTime[5] = '\0';
    _display.print(shortTime);
  } else {
    _display.print("LIVE");
  }
  _display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  // Chỉ số đo lường
  _display.setTextSize(1);
  _display.setCursor(2, 13);
  if (hr > 0) {
    _display.printf("HR:%3d BPM", hr);
  } else {
    _display.print("HR: -- BPM");
  }

  _display.setCursor(72, 13);
  if (spo2 > 1.0f) {
    _display.printf("SpO2:%4.1f%%", spo2);
  } else {
    _display.print("SpO2: --%");
  }

  _display.setCursor(2, 23);
  if (sensorTemp > 0.0f) {
    _display.printf("T:%4.1fC", sensorTemp);
  } else {
    _display.print("T: --.-C");
  }

  _display.setCursor(72, 23);
  if (!maxReady) {
    _display.print("ERR I2C");
  } else if (!fingerDetected) {
    _display.print("CHỜ TAY..");
  } else {
    _display.print("ĐÃ NHẬN TAY");
  }

  // Đồ thị dạng sóng quang phổ mao mạch PPG thời gian thực (Plethysmogram Waveform)
  drawWaveform(0, 33, 128, 30, ppgWave);
}

void OledDisplay::renderStepPage(unsigned long steps) {
  _display.setTextSize(1);
  _display.setCursor(0, 0);
  _display.print("PEDOMETER      [P2]");
  _display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  _display.setTextSize(2);
  _display.setCursor(4, 16);
  _display.printf("%5lu", steps);
  _display.setTextSize(1);
  _display.setCursor(76, 22);
  _display.print("STEPS");

  int calories = (int)(steps * 0.04f);
  float distanceKm = (steps * 0.75f) / 1000.0f;
  _display.setTextSize(1);
  _display.setCursor(4, 36);
  _display.printf("Calo: %d kcal", calories);
  _display.setCursor(4, 46);
  _display.printf("Dist: %.2f km", distanceKm);

  int barWidth = map(constrain((long)steps, 0L, 10000L), 0L, 10000L, 0, 126);
  _display.drawRect(0, 56, 128, 7, SSD1306_WHITE);
  _display.fillRect(1, 57, barWidth, 5, SSD1306_WHITE);
}

void OledDisplay::renderMotionPage(float ax_ms2, float ay_ms2, float az_ms2,
                                  float a_mag_ms2, bool fallAlert) {
  _display.setTextSize(1);
  _display.setCursor(0, 0);
  _display.print("ACCEL (m/s2)   [P3]");
  _display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  _display.setTextSize(1);
  _display.setCursor(4, 14);
  _display.printf("Ax: %-5.1f m/s2", ax_ms2);
  _display.setCursor(4, 25);
  _display.printf("Ay: %-5.1f m/s2", ay_ms2);
  _display.setCursor(4, 36);
  _display.printf("Az: %-5.1f m/s2", az_ms2);

  _display.drawLine(0, 48, 128, 48, SSD1306_WHITE);
  _display.setCursor(2, 52);
  _display.printf("|A|:%-4.1f", a_mag_ms2);

  _display.setCursor(68, 52);
  if (fallAlert) {
    _display.print("[TE NGA!!]");
  } else if (a_mag_ms2 > 13.0f) {
    _display.print("[VAN DONG]");
  } else {
    _display.print("[BINH THUONG]");
  }
}

void OledDisplay::renderFallAlertScreen(float peakFallMs2) {
  _display.drawRoundRect(0, 0, 128, 64, 4, SSD1306_WHITE);
  _display.drawRoundRect(1, 1, 126, 62, 3, SSD1306_WHITE);

  _display.setTextSize(1);
  _display.setCursor(8, 6);
  _display.print("! CANH BAO TE NGA !");
  _display.drawLine(4, 18, 124, 18, SSD1306_WHITE);

  _display.setTextSize(2);
  _display.setCursor(8, 24);
  _display.printf("%.1f m/s2", peakFallMs2);

  _display.setTextSize(1);
  _display.setCursor(8, 44);
  _display.print("XAC NHAN TE NGA!");
  _display.setCursor(8, 54);
  _display.print("Rung coi... Can cuu!");
}

void OledDisplay::renderMessagePopup() {
  _display.drawRoundRect(2, 4, 124, 56, 4, SSD1306_WHITE);
  _display.setTextSize(1);
  _display.setCursor(20, 10);
  _display.print("!! THONG BAO !!");
  _display.drawLine(10, 22, 118, 22, SSD1306_WHITE);

  _display.setCursor(8, 28);
  int len = strlen(_customMessage);
  if (len <= 16) {
    _display.print(_customMessage);
  } else {
    char line1[17];
    strncpy(line1, _customMessage, 16);
    line1[16] = '\0';
    _display.print(line1);

    _display.setCursor(8, 42);
    char line2[17];
    strncpy(line2, _customMessage + 16, 16);
    line2[16] = '\0';
    _display.print(line2);
  }
}
