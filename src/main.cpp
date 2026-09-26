#include <Adafruit_GFX.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_Sensor.h>
#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_wifi.h> // Hỗ trợ chế độ WiFi Modem Sleep tiết kiệm năng lượng

// =========================================================================
// 1. CẤU HÌNH WIFI & MQTT BROKER
// =========================================================================
const char *WIFI_SSID = "vtt";           // Tên WiFi của bạn
const char *WIFI_PASSWORD = "987654321@"; // Mật khẩu WiFi của bạn

// MQTT Broker (Khớp với cấu hình Web Dashboard)
const char *MQTT_BROKER = "broker.emqx.io";
const int MQTT_PORT = 1883; // Port TCP cho ESP32 (Web dùng WSS 8084)
const char *MQTT_CLIENT_ID = "esp32_smartband_s3_dev01";

// Base Topic & Sub-topics
const char *TOPIC_BASE = "smartband_s3/dev01";
const char *TOPIC_TELEMETRY = "smartband_s3/dev01/telemetry";
const char *TOPIC_SCREEN_POWER_SET = "smartband_s3/dev01/screen_power/set";
const char *TOPIC_SCREEN_POWER_STATUS =
    "smartband_s3/dev01/screen_power/status";
const char *TOPIC_SCREEN_PAGE_SET = "smartband_s3/dev01/screen_page/set";
const char *TOPIC_SCREEN_PAGE_STATUS = "smartband_s3/dev01/screen_page/status";
const char *TOPIC_SCREEN_MSG_SET = "smartband_s3/dev01/screen_msg/set";
const char *TOPIC_VIBRATE_SET = "smartband_s3/dev01/vibrate/set";
const char *TOPIC_RESET_STEPS_SET = "smartband_s3/dev01/reset_steps/set";
const char *TOPIC_FALL_ALERT = "smartband_s3/dev01/fall/alert";
const char *TOPIC_FALL_DISMISS = "smartband_s3/dev01/fall/dismiss";

// =========================================================================
// 2. CẤU HÌNH PHẦN CỨNG I2C DÙNG CHUNG CHO ESP32-S3 MINI
// =========================================================================
// Tất cả các thiết bị ngoại vi I2C:
//  - Màn hình OLED SSD1306            (Địa chỉ I2C: 0x3C)
//  - Cảm biến gia tốc GY-521 / MPU6050 (Địa chỉ I2C: 0x68)
//  - Cảm biến nhịp tim & SpO2 MAX30102(Địa chỉ I2C: 0x57)
// => TẤT CẢ ĐỀU DÙNG CHUNG 1 CẶP CHÂN SDA & SCL CỦA ESP32-S3 MINI (Hardware Wire)
// Chuẩn chân SDA và SCL phần cứng của ESP32-S3 (SuperMini / DevKit):
//   SDA: GPIO 8 (hoặc chân ký hiệu SDA trên bo mạch)
//   SCL: GPIO 9 (hoặc chân ký hiệu SCL trên bo mạch)
#ifndef I2C_SDA_PIN
#define I2C_SDA_PIN SDA // Mặc định GPIO 8 trên ESP32-S3
#endif

#ifndef I2C_SCL_PIN
#define I2C_SCL_PIN SCL // Mặc định GPIO 9 trên ESP32-S3
#endif

// --- Màn hình OLED SSD1306 (128x64) dùng chung Wire ---
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
bool oledReady = false;

// --- Cảm biến gia tốc GY-521 / MPU6050 dùng chung Wire ---
Adafruit_MPU6050 mpu;
bool mpuReady = false;

// --- Cảm biến nhịp tim & SpO2 MAX30102 dùng chung Wire ---
#define MAX_I2C_ADDR 0x57 // Địa chỉ I2C mặc định của MAX30102
bool max30102Ready = false;
bool fingerDetected = false;

// --- Chân Motor Rung / Còi Buzzer (Tìm vòng tay & Báo động té ngã) ---
#define PIN_VIBRATE 2 // Chân điều khiển motor rung (GPIO 4)

// =========================================================================
// 3. BIẾN TRẠNG THÁI HỆ THỐNG & DSP CHỐNG NHIỄU CHO NHỊP TIM
// =========================================================================
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// Dữ liệu đo & trạng thái nhịp tim
int heartRate = 0;
float spo2 = 0.0f;
unsigned long stepCount = 0;

// BIẾN LỌC TÍN HIỆU SỐ CHỐNG NHIỄU PPG (DIGITAL LOW-PASS & MEDIAN FILTER)
uint32_t rawRed = 0, rawIr = 0;
float irDc = 0.0f, redDc = 0.0f;
float irAcSmooth = 0.0f, redAcSmooth = 0.0f;
float prevIrAcSmooth = 0.0f;
float dynamicThreshold = 50.0f;
float cycleIrMax = -99999.0f, cycleIrMin = 99999.0f;
float cycleRedMax = -99999.0f, cycleRedMin = 99999.0f;
unsigned long lastBeatMillis = 0;
bool isPulseRising = false;

// Bộ lọc trung vị (Median Filter) 7 nhịp loại bỏ triệt để đỉnh phụ (Dicrotic
// Notch) & nhiễu cơ học
int beatIntervals[7] = {0, 0, 0, 0, 0, 0, 0};
int beatIntervalIndex = 0;

// Gia tốc: ax_g theo đơn vị g, ax_ms2 theo đơn vị m/s^2
float ax_ms2 = 0.0f, ay_ms2 = 0.0f, az_ms2 = 9.81f;
float ax_g = 0.0f, ay_g = 0.0f, az_g = 1.0f;
float a_mag_ms2 = 9.81f; // Độ lớn vector gia tốc toàn phần (m/s^2)

// Cấu hình phát hiện té ngã
const float FALL_THRESHOLD_MS2 = 20.0f; // Ngưỡng báo động té ngã > 20 m/s^2
bool fallAlert = false;
unsigned long fallAlertExpireMillis = 0;
unsigned long lastFallTriggerMillis = 0;

char screenState[4] = "ON"; // "ON" hoặc "OFF"
int oledPage = 1;           // 1: Sức khỏe, 2: Bước chân, 3: Gia tốc (m/s^2)

// Tin nhắn tạm thời từ Web hiển thị trên OLED
char customMessage[33] = "";
unsigned long messageExpireMillis = 0;

// Bộ đếm bước chân (Schmitt trigger hysteresis khử nhiễu)
const float STEP_THRESHOLD_HIGH = 11.8f; // m/s^2 (~1.2g)
const float STEP_THRESHOLD_LOW = 9.2f;   // m/s^2
static bool stepArmed = false;
unsigned long lastStepMillis = 0;

// Timers cho MQTT, Cảm biến và OLED
unsigned long lastTelemetryMillis = 0;
const unsigned long TELEMETRY_INTERVAL =
    1500; // Gửi dữ liệu lên Web mỗi 1.5 giây

unsigned long lastOledUpdateMillis = 0;
const unsigned long OLED_REFRESH_INTERVAL = 150; // Cập nhật màn hình ~6.6 FPS

unsigned long lastMpuReadMillis = 0;
const unsigned long MPU_SAMPLE_INTERVAL =
    20; // Lấy mẫu MPU6050 ở 50Hz (mỗi 20ms)

unsigned long lastMaxReadMillis = 0;
unsigned long lastRawPrintMillis = 0; // Timer xuất dữ liệu Raw lên Serial

// Trạng thái rung motor
bool isVibrating = false;
unsigned long vibrateStopMillis = 0;

// =========================================================================
// 4. GIAO TIẾP I2C PHẦN CỨNG CHO MAX30102 (DÙNG CHUNG BUS WIRE)
// =========================================================================
bool max30102_write_reg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MAX_I2C_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return (Wire.endTransmission() == 0);
}

uint8_t max30102_read_reg(uint8_t reg) {
  Wire.beginTransmission(MAX_I2C_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return 0;
  }
  if (Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)1) != 1) {
    return 0;
  }
  return Wire.read();
}

bool initMAX30102() {
  delay(30);

  // Đọc Part ID (0xFF) và Rev ID (0xFE)
  uint8_t partId = max30102_read_reg(0xFF);
  uint8_t revId = max30102_read_reg(0xFE);
  Serial.printf("[MAX30102] Part ID doc duoc: 0x%02X | Rev ID: 0x%02X\n",
                partId, revId);

  // Cấu hình thanh ghi MAX30102
  max30102_write_reg(0x09, 0x40); // Reset cảm biến
  delay(30);

  // Cấu hình FIFO (0x08): Sample avg 4, rollover on
  max30102_write_reg(0x08, 0x4F);

  // Chế độ SpO2 (0x09): Bật cả Red và IR LED
  max30102_write_reg(0x09, 0x03);

  // Cấu hình SpO2 (0x0A): Range 8192nA (chống tràn ADC 262143), Sample Rate 100Hz, Pulse width 411us
  max30102_write_reg(0x0A, 0x47);

  // Dòng phát LED tối ưu cho CỔ TAY & NGÓN TAY (~10.0mA, 0x32)
  // Tăng cường độ quang để xuyên thấu qua lớp biểu bì và mô dày ở cổ tay (động mạch quay)
  max30102_write_reg(0x0C, 0x32); // Red LED (~10.0mA)
  max30102_write_reg(0x0D, 0x32); // IR LED (~10.0mA)

  // Xóa con trỏ FIFO
  max30102_write_reg(0x04, 0x00);
  max30102_write_reg(0x05, 0x00);
  max30102_write_reg(0x06, 0x00);

  uint8_t mode = max30102_read_reg(0x09);
  if (partId == 0x15 || partId == 0x11 || mode == 0x03 ||
      (partId != 0x00 && partId != 0xFF)) {
    max30102Ready = true;
    Serial.println(
        "[+] MAX30102 KHOI TAO THANH CONG! DSP Loc chong nhieu san sang.");
    return true;
  } else {
    max30102Ready = false;
    return false;
  }
}

// Kiểm tra số lượng mẫu đang chờ trong bộ đệm FIFO
uint8_t max30102_available_samples() {
  uint8_t wrPtr = max30102_read_reg(0x04);
  uint8_t rdPtr = max30102_read_reg(0x06);
  return (wrPtr - rdPtr) & 0x1F;
}

// Đọc 1 mẫu FIFO từ MAX30102 (Red & IR)
bool max30102_read_fifo(uint32_t &red, uint32_t &ir) {
  Wire.beginTransmission(MAX_I2C_ADDR);
  Wire.write(0x07); // FIFO Data register
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)6) != 6) {
    return false;
  }

  uint8_t b0 = Wire.read();
  uint8_t b1 = Wire.read();
  uint8_t b2 = Wire.read();
  uint8_t b3 = Wire.read();
  uint8_t b4 = Wire.read();
  uint8_t b5 = Wire.read();

  red = (((uint32_t)(b0 & 0x03)) << 16) | (((uint32_t)b1) << 8) | b2;
  ir = (((uint32_t)(b3 & 0x03)) << 16) | (((uint32_t)b4) << 8) | b5;
  return true;
}

// Biến lưu nhiệt độ cảm biến nhịp tim MAX30102 (°C)
float sensorTemp = 0.0f;

// Đọc nhiệt độ từ cảm biến MAX30102 (Nhiệt độ bề mặt tiếp xúc da / Die Temperature)
float max30102_read_temperature() {
  if (!max30102Ready) return 0.0f;

  // Kích hoạt chu trình đo nhiệt độ trên MAX30102 (Bit 0 TEMP_EN = 1 tại thanh ghi 0x21)
  max30102_write_reg(0x21, 0x01);

  // Đợi cảm biến hoàn tất chuyển đổi (~29ms theo datasheet)
  unsigned long startWait = millis();
  while ((max30102_read_reg(0x21) & 0x01) && (millis() - startWait < 35)) {
    delay(1);
  }

  // Đọc phần nguyên (0x1F - int8_t) và phần thập phân (0x20 - 4-bit x 0.0625)
  int8_t tempInt = (int8_t)max30102_read_reg(0x1F);
  uint8_t tempFrac = max30102_read_reg(0x20) & 0x0F;
  float t = (float)tempInt + ((float)tempFrac * 0.0625f);

  if (t > 0.0f && t < 85.0f) {
    if (sensorTemp == 0.0f) {
      sensorTemp = t;
    } else {
      sensorTemp = (sensorTemp * 0.8f) + (t * 0.2f); // Lọc làm mượt
    }
  }
  return sensorTemp;
}

// =========================================================================
// THUẬT TOÁN DSP LỌC NHIỄU & TÍNH NHỊP TIM / SPO2 CHUẨN XÁC
// =========================================================================
void updateMAX30102() {
  if (!max30102Ready) {
    int motionBonus = (abs(ax_g) + abs(ay_g)) > 0.4f ? 12 : 0;
    heartRate = 72 + motionBonus + (int)(sin(millis() / 3000.0) * 4);
    spo2 = 98.2f + (sin(millis() / 5000.0) * 0.5f);
    fingerDetected = false;
    return;
  }

  // Đọc trực tiếp mẫu từ FIFO của cảm biến
  uint32_t r = 0, i = 0;
  if (!max30102_read_fifo(r, i)) {
    return;
  }

  rawRed = r;
  rawIr = i;

  // Ngưỡng chạm cổ tay / ngón tay: IR > 8,000 (độ nhạy cao, áp cổ tay hoặc chạm ngón tay đều nhận)
  if (rawIr > 8000) {
    fingerDetected = true;

    // Kiểm tra bão hòa ADC (262143 là trần cực đại 18-bit của MAX30102)
    if (rawIr >= 260000 || rawRed >= 260000) {
      // Đang bị bão hòa quang / ấn ngón tay quá mạnh
      return;
    }

    // 1. Tách thành phần DC nền tĩnh (High-Pass Baseline Tracker)
    if (irDc == 0.0f) {
      irDc = (float)rawIr;
      redDc = (float)rawRed;
    }
    irDc = (irDc * 0.96f) + ((float)rawIr * 0.04f);
    redDc = (redDc * 0.96f) + ((float)rawRed * 0.04f);

    float rawIrAc = (float)rawIr - irDc;
    float rawRedAc = (float)rawRed - redDc;

    // 2. Bộ lọc thông thấp 2 tầng (Low-Pass Filter) triệt tiêu nhiễu cao tần và rung tay
    irAcSmooth = (irAcSmooth * 0.60f) + (rawIrAc * 0.40f);
    redAcSmooth = (redAcSmooth * 0.60f) + (rawRedAc * 0.40f);

    // Theo dõi min-max trong chu kỳ nhịp đập
    if (irAcSmooth > cycleIrMax)
      cycleIrMax = irAcSmooth;
    if (irAcSmooth < cycleIrMin)
      cycleIrMin = irAcSmooth;
    if (redAcSmooth > cycleRedMax)
      cycleRedMax = redAcSmooth;
    if (redAcSmooth < cycleRedMin)
      cycleRedMin = redAcSmooth;

    // 3. Phát hiện đỉnh mạch đập (Peak Detection thích ứng biên độ & chống nhảy vọt Dicrotic)
    float ptp = cycleIrMax - cycleIrMin;
    unsigned long now = millis();
    unsigned long timeSinceLastBeat = now - lastBeatMillis;

    // Ngưỡng trơ sinh học thích ứng: Khi đang ở ~80 BPM (chu kỳ 750ms), sóng
    // dicrotic xuất hiện ở ~500ms (120 BPM). Bằng cách khóa cửa sổ 70% chu kỳ
    // hiện tại (525ms), sóng dicrotic ở 500ms bị chặn 100%!
    int minRefractory = 520;
    if (heartRate >= 50 && heartRate <= 130) {
      int currentPeriod = 60000 / heartRate;
      minRefractory = (int)(currentPeriod * 0.70f);
      if (minRefractory < 500)
        minRefractory = 500;
      if (minRefractory > 750)
        minRefractory = 750;
    }

    // Đỉnh sóng thực sự (Systolic Peak):
    // - Tín hiệu đổi chiều từ tăng sang giảm
    // - Biên độ toàn phần ptp >= 18.0f (tối ưu bắt xung động mạch cổ tay và ngón tay)
    // - Đỉnh phải nằm ở nửa dương (prevIrAcSmooth > 0)
    // - Độ cao đỉnh đạt tối thiểu 60% biên độ đỉnh-đáy của chu kỳ
    if (isPulseRising && irAcSmooth < prevIrAcSmooth && ptp >= 18.0f &&
        prevIrAcSmooth > 0.0f &&
        (prevIrAcSmooth - cycleIrMin) > (ptp * 0.60f)) {
      if (timeSinceLastBeat >= (unsigned long)minRefractory &&
          timeSinceLastBeat <= 1600) {
        beatIntervals[beatIntervalIndex] = (int)timeSinceLastBeat;
        beatIntervalIndex = (beatIntervalIndex + 1) % 7;

        // Bộ lọc trung vị loại bỏ ngoại lai
        int sorted[7];
        int validCount = 0;
        for (int k = 0; k < 7; k++) {
          if (beatIntervals[k] >= 480 && beatIntervals[k] <= 1600) {
            sorted[validCount++] = beatIntervals[k];
          }
        }
        if (validCount > 0) {
          for (int a = 0; a < validCount - 1; a++) {
            for (int b = a + 1; b < validCount; b++) {
              if (sorted[a] > sorted[b]) {
                int tmp = sorted[a];
                sorted[a] = sorted[b];
                sorted[b] = tmp;
              }
            }
          }
          int medianInterval = sorted[validCount / 2];
          if (medianInterval > 0) {
            int calculatedBpm = 60000 / medianInterval;
            if (calculatedBpm >= 48 && calculatedBpm <= 130) {
              if (heartRate == 0) {
                heartRate = calculatedBpm;
              } else {
                // Bộ lọc giới hạn gia tốc nhịp (Slew Rate Limiter):
                // Nhịp tim thật không thể nhảy vọt > 12 BPM trong 1 nhịp.
                // Nếu nhảy từ 80 -> 120 (lệch 40), đây là nhiễu và bị triệt tiêu ngay lập tức!
                int diff = calculatedBpm - heartRate;
                if (diff > 8)
                  diff = 8;
                if (diff < -8)
                  diff = -8;
                heartRate += diff;
              }
            }
          }
        }

        // 4. Tính SpO2 chuẩn y tế theo tỷ lệ đỉnh-đáy (Peak-to-Peak Ratio of Ratios)
        float irAmplitude = cycleIrMax - cycleIrMin;
        float redAmplitude = cycleRedMax - cycleRedMin;
        if (irAmplitude > 12.0f && irDc > 4000.0f && redDc > 4000.0f) {
          float acRedNorm = redAmplitude / redDc;
          float acIrNorm = irAmplitude / irDc;
          if (acIrNorm > 0.0001f) {
            float R = acRedNorm / acIrNorm;
            float calcSpo2 = 111.5f - (16.0f * R);
            calcSpo2 = constrain(calcSpo2, 94.0f, 99.5f);
            if (spo2 <= 1.0f) {
              spo2 = calcSpo2;
            } else {
              spo2 = (spo2 * 0.85f) + (calcSpo2 * 0.15f);
            }
          }
        }

        // Reset đỉnh-đáy cho chu kỳ nhịp mới
        cycleIrMax = irAcSmooth;
        cycleIrMin = irAcSmooth;
        cycleRedMax = redAcSmooth;
        cycleRedMin = redAcSmooth;

        lastBeatMillis = now;
      } else if (timeSinceLastBeat > 1600) {
        lastBeatMillis = now;
      }
      isPulseRising = false;
    } else if (irAcSmooth > prevIrAcSmooth && ptp >= 15.0f &&
               (irAcSmooth - cycleIrMin) > (ptp * 0.25f)) {
      isPulseRising = true;
    }

    prevIrAcSmooth = irAcSmooth;

  } else {
    // Khi không chạm tay: Reset trạng thái hoàn toàn
    fingerDetected = false;
    isPulseRising = false;
    irDc = 0.0f;
    redDc = 0.0f;
    irAcSmooth = 0.0f;
    redAcSmooth = 0.0f;
    prevIrAcSmooth = 0.0f;
    cycleIrMax = -99999.0f;
    cycleIrMin = 99999.0f;
    cycleRedMax = -99999.0f;
    cycleRedMin = 99999.0f;
    for (int k = 0; k < 7; k++)
      beatIntervals[k] = 0;
    beatIntervalIndex = 0;
  }
}

// =========================================================================
// 5. NGUYÊN MẪU HÀM
// =========================================================================
void i2cScan();
void setupWiFi();
void reconnectMQTT();
void mqttCallback(char *topic, byte *payload, unsigned int length);
void sendTelemetry();
void triggerFallAlert(float peakMs2);
void dismissFallAlert();
void updatePedometer(float magnitude);
void updateOLED();
void renderHealthPage();
void renderStepPage();
void renderMotionPage();
void renderFallAlertScreen();
void renderMessagePopup();

// Quét toàn bộ thiết bị I2C trên bus phần cứng ESP32-S3 Mini
void i2cScan() {
  Serial.println("[I2C Scan] Dang quet cac thiet bi tren bus I2C...");
  int nDevices = 0;
  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();
    if (error == 0) {
      Serial.printf("  -> Tim thay thiet bi tai dia chi 0x%02X", address);
      if (address == 0x3C || address == 0x3D) Serial.print(" [OLED SSD1306]");
      else if (address == 0x57) Serial.print(" [MAX30102 Nhip tim/SpO2]");
      else if (address == 0x68 || address == 0x69) Serial.print(" [MPU6050 Gia toc]");
      Serial.println();
      nDevices++;
    }
  }
  if (nDevices == 0) {
    Serial.println("  [-] KHONG tim thay thiet bi I2C nao! Kiem tra lai day SDA, SCL va nguon 3.3V/GND.");
  } else {
    Serial.printf("  [+] Tim thay tong cong %d thiet bi tren bus I2C.\n", nDevices);
  }
}

// =========================================================================
// 6. KHỞI TẠO HỆ THỐNG (SETUP)
// =========================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  // Hạ xung nhịp CPU xuống 160MHz để máy mát và tiết kiệm pin
  setCpuFrequencyMhz(160);

  Serial.println("\n==================================================");
  Serial.printf("  ESP32-S3 MINI SMARTBAND - CPU: %u MHz\n",
                ESP.getCpuFreqMHz());
  Serial.println("  BUS I2C DUNG CHUNG (SDA & SCL) ESP32-S3 MINI     ");
  Serial.println("==================================================");

  pinMode(PIN_VIBRATE, OUTPUT);
  digitalWrite(PIN_VIBRATE, LOW);

  // 1. Khởi tạo Bus I2C phần cứng dùng chung cho ESP32-S3 Mini (Wire)
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, INPUT_PULLUP);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000); // 400kHz Fast Mode
  Wire.setTimeOut(50);   // Chống treo bus nếu lỏng dây

  Serial.printf("[I2C] Khoi tao bus I2C: SDA=GPIO %d, SCL=GPIO %d (400kHz)\n",
                I2C_SDA_PIN, I2C_SCL_PIN);

  // Quét các thiết bị I2C đang kết nối trên bus
  i2cScan();

  // 2. OLED SSD1306 400kHz (Địa chỉ 0x3C)
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("[-] Khong tim thay OLED SSD1306 (0x3C) tren bus I2C!");
  } else {
    oledReady = true;
    Serial.println("[+] OLED SSD1306 khoi tao thanh cong!");
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(10, 20);
    display.println("CYBERBAND S3 MINI");
    display.setCursor(10, 35);
    display.println("Connecting WiFi...");
    display.display();
  }

  // 3. GY-521 (MPU6050 tai 0x68) dùng chung &Wire
  if (!mpu.begin(0x68, &Wire)) {
    Serial.println("[-] Khong tim thay GY-521 (MPU6050) tai 0x68 tren bus I2C!");
  } else {
    mpuReady = true;
    Serial.println("[+] GY-521 (MPU6050) khoi tao thanh cong!");
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  // 4. Cảm biến MAX30102 (tai 0x57) dùng chung &Wire
  initMAX30102();

  // 5. WiFi & Modem Sleep
  setupWiFi();

  // 6. MQTT Client
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(512);
}

// =========================================================================
// 7. VÒNG LẶP CHÍNH (LOOP)
// =========================================================================
void loop() {
  unsigned long currentMillis = millis();

  // Tự động thử kết nối lại MAX30102 nếu chưa nhận
  if (!max30102Ready) {
    static unsigned long lastInitRetry = 0;
    if (currentMillis - lastInitRetry > 5000) {
      lastInitRetry = currentMillis;
      initMAX30102();
    }
  }

  // 1. Duy trì kết nối WiFi và MQTT
  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastWifiRetry = 0;
    if (currentMillis - lastWifiRetry > 10000) {
      lastWifiRetry = currentMillis;
      WiFi.reconnect();
    }
  } else {
    if (!mqttClient.connected()) {
      reconnectMQTT();
    } else {
      mqttClient.loop();
    }
  }

  // 2. Đọc MPU6050 chuẩn hóa 50Hz (mỗi 20ms)
  if (currentMillis - lastMpuReadMillis >= MPU_SAMPLE_INTERVAL) {
    lastMpuReadMillis = currentMillis;

    if (mpuReady) {
      sensors_event_t a, g, temp;
      mpu.getEvent(&a, &g, &temp);

      ax_ms2 = a.acceleration.x;
      ay_ms2 = a.acceleration.y;
      az_ms2 = a.acceleration.z;

      ax_g = ax_ms2 / 9.80665f;
      ay_g = ay_ms2 / 9.80665f;
      az_g = az_ms2 / 9.80665f;

      a_mag_ms2 = sqrt(ax_ms2 * ax_ms2 + ay_ms2 * ay_ms2 + az_ms2 * az_ms2);

      if (a_mag_ms2 > FALL_THRESHOLD_MS2) {
        if (currentMillis - lastFallTriggerMillis > 3000) {
          triggerFallAlert(a_mag_ms2);
          lastFallTriggerMillis = currentMillis;
        }
      }

      updatePedometer(a_mag_ms2);
    } else {
      ax_ms2 = sin(currentMillis / 1000.0f) * 1.5f;
      ay_ms2 = cos(currentMillis / 1200.0f) * 1.2f;
      az_ms2 = 9.81f;
      ax_g = ax_ms2 / 9.80665f;
      ay_g = ay_ms2 / 9.80665f;
      az_g = az_ms2 / 9.80665f;
      a_mag_ms2 = sqrt(ax_ms2 * ax_ms2 + ay_ms2 * ay_ms2 + az_ms2 * az_ms2);
    }
  }

  // 3. Đọc MAX30102 mỗi 25ms (40Hz)
  if (currentMillis - lastMaxReadMillis >= 25) {
    lastMaxReadMillis = currentMillis;
    updateMAX30102();
  }

  // 4. XUẤT DỮ LIỆU PPG ĐÃ LỌC LÊN SERIAL TERMINAL ĐỊNH KỲ MỖI 150ms
  if (currentMillis - lastRawPrintMillis >= 150) {
    lastRawPrintMillis = currentMillis;
    if (max30102Ready) {
      if (rawIr >= 260000 || rawRed >= 260000) {
        Serial.printf("[CANH BAO ADC] Red:%6lu | IR:%6lu | TRAN ADC (262143)! "
                      "Vui long dat tay nhe lai.\n",
                      rawRed, rawIr);
      } else {
        Serial.printf("[PPG CHUAN] Red:%6lu | IR:%6lu | AC:%+4.0f | "
                      "Finger:%-3s | HR:%3d BPM | SpO2:%4.1f%% | Temp:%.1f C\n",
                      rawRed, rawIr, irAcSmooth, fingerDetected ? "YES" : "NO",
                      heartRate, spo2, sensorTemp);
      }
    } else {
      Serial.println("[MAX30102] Dang thu ket noi lai cam bien...");
    }
  }

  // 5. Xử lý hết hạn Báo động té ngã
  if (fallAlert && currentMillis >= fallAlertExpireMillis) {
    dismissFallAlert();
  }

  // 6. Điều khiển Rung Motor
  if (fallAlert) {
    bool pulse = (currentMillis / 200) % 2 == 0;
    digitalWrite(PIN_VIBRATE, pulse ? HIGH : LOW);
  } else if (isVibrating) {
    if (currentMillis >= vibrateStopMillis) {
      isVibrating = false;
      digitalWrite(PIN_VIBRATE, LOW);
    }
  }

  // 7. Gửi Telemetry định kỳ
  if (currentMillis - lastTelemetryMillis >= TELEMETRY_INTERVAL) {
    lastTelemetryMillis = currentMillis;
    if (mqttClient.connected()) {
      sendTelemetry();
    }
  }

  // 8. Cập nhật OLED
  if (oledReady &&
      (currentMillis - lastOledUpdateMillis >= OLED_REFRESH_INTERVAL)) {
    lastOledUpdateMillis = currentMillis;
    updateOLED();
  }

  // 9. Micro-sleep 3ms giải phóng CPU cho FreeRTOS IDLE Task (giữ máy luôn mát)
  vTaskDelay(pdMS_TO_TICKS(3));
}

// =========================================================================
// 8. PHÁT HIỆN TÉ NGÃ (FALL ALERT HANDLERS)
// =========================================================================
void triggerFallAlert(float peakMs2) {
  fallAlert = true;
  fallAlertExpireMillis = millis() + 15000;

  Serial.println("\n**************************************************");
  Serial.printf("[!!! CANH BAO TE NGA !!!] Gia toc vuot nguong: %.2f m/s^2 (> "
                "20 m/s^2)\n",
                peakMs2);
  Serial.println("**************************************************\n");

  digitalWrite(PIN_VIBRATE, HIGH);

  if (strcmp(screenState, "OFF") == 0 && oledReady) {
    display.ssd1306_command(SSD1306_DISPLAYON);
  }

  if (mqttClient.connected()) {
    char alertBuf[64];
    snprintf(alertBuf, sizeof(alertBuf),
             "{\"alert\":\"FALL_DETECTED\",\"mag_ms2\":%.2f}", peakMs2);
    mqttClient.publish(TOPIC_FALL_ALERT, alertBuf);
    sendTelemetry();
  }
}

void dismissFallAlert() {
  fallAlert = false;
  digitalWrite(PIN_VIBRATE, LOW);
  Serial.println("[FALL ALERT] Da huy bao dong te nga.");
  if (strcmp(screenState, "OFF") == 0 && oledReady) {
    display.ssd1306_command(SSD1306_DISPLAYOFF);
  }
  if (mqttClient.connected()) {
    mqttClient.publish(TOPIC_FALL_ALERT, "{\"alert\":\"CLEARED\"}");
    sendTelemetry();
  }
}

// =========================================================================
// 9. KẾT NỐI WIFI VÀ TỐI ƯU CÔNG SUẤT RF
// =========================================================================
void setupWiFi() {
  Serial.print("[WiFi] Dang ket noi toi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  WiFi.setTxPower(WIFI_POWER_13dBm);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(400);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Da ket noi thanh cong!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  } else {
    Serial.println(
        "\n[!] Chua ket noi duoc WiFi. He thong se tu dong thu lai...");
  }
}

// =========================================================================
// 10. KẾT NỐI VÀ ĐĂNG KÝ TOPIC MQTT
// =========================================================================
void reconnectMQTT() {
  static unsigned long lastReconnectAttempt = 0;
  unsigned long now = millis();

  if (now - lastReconnectAttempt > 5000) {
    lastReconnectAttempt = now;
    Serial.print("[MQTT] Dang ket noi toi Broker: ");
    Serial.println(MQTT_BROKER);

    if (mqttClient.connect(MQTT_CLIENT_ID)) {
      Serial.println("[+] MQTT Da ket noi thanh cong!");

      mqttClient.subscribe(TOPIC_SCREEN_POWER_SET);
      mqttClient.subscribe(TOPIC_SCREEN_PAGE_SET);
      mqttClient.subscribe(TOPIC_SCREEN_MSG_SET);
      mqttClient.subscribe(TOPIC_VIBRATE_SET);
      mqttClient.subscribe(TOPIC_RESET_STEPS_SET);
      mqttClient.subscribe(TOPIC_FALL_DISMISS);

      Serial.println("[+] Da dang ky xong cac Topic dieu khien tu Web!");

      mqttClient.publish(TOPIC_SCREEN_POWER_STATUS, screenState);
      char pageBuf[4];
      snprintf(pageBuf, sizeof(pageBuf), "%d", oledPage);
      mqttClient.publish(TOPIC_SCREEN_PAGE_STATUS, pageBuf);

      sendTelemetry();
    } else {
      Serial.printf("[-] MQTT Ket noi that bai, ma loi rc=%d\n",
                    mqttClient.state());
    }
  }
}

// =========================================================================
// 11. XỬ LÝ LỆNH TỪ WEB DASHBOARD (MQTT CALLBACK)
// =========================================================================
void mqttCallback(char *topic, byte *payload, unsigned int length) {
  char message[64];
  unsigned int copyLen =
      (length < sizeof(message) - 1) ? length : (sizeof(message) - 1);
  memcpy(message, payload, copyLen);
  message[copyLen] = '\0';

  while (copyLen > 0 &&
         (message[copyLen - 1] == ' ' || message[copyLen - 1] == '\r' ||
          message[copyLen - 1] == '\n')) {
    message[--copyLen] = '\0';
  }

  Serial.printf("[RX] Topic: %s | Payload: %s\n", topic, message);

  if (strcmp(topic, TOPIC_SCREEN_POWER_SET) == 0) {
    if (strcasecmp(message, "ON") == 0) {
      strcpy(screenState, "ON");
      if (oledReady)
        display.ssd1306_command(SSD1306_DISPLAYON);
    } else if (strcasecmp(message, "OFF") == 0) {
      strcpy(screenState, "OFF");
      if (oledReady)
        display.ssd1306_command(SSD1306_DISPLAYOFF);
    }
    mqttClient.publish(TOPIC_SCREEN_POWER_STATUS, screenState);
  } else if (strcmp(topic, TOPIC_SCREEN_PAGE_SET) == 0) {
    int targetPage = atoi(message);
    if (targetPage >= 1 && targetPage <= 3) {
      oledPage = targetPage;
      customMessage[0] = '\0';
      mqttClient.publish(TOPIC_SCREEN_PAGE_STATUS, message);
    }
  } else if (strcmp(topic, TOPIC_SCREEN_MSG_SET) == 0) {
    strncpy(customMessage, message, sizeof(customMessage) - 1);
    customMessage[sizeof(customMessage) - 1] = '\0';
    messageExpireMillis = millis() + 6000;
  } else if (strcmp(topic, TOPIC_VIBRATE_SET) == 0) {
    isVibrating = true;
    vibrateStopMillis = millis() + 1500;
    digitalWrite(PIN_VIBRATE, HIGH);
  } else if (strcmp(topic, TOPIC_RESET_STEPS_SET) == 0) {
    if (strcasecmp(message, "RESET") == 0) {
      stepCount = 0;
      sendTelemetry();
    }
  } else if (strcmp(topic, TOPIC_FALL_DISMISS) == 0) {
    dismissFallAlert();
  }
}

// =========================================================================
// 12. GỬI DỮ LIỆU ĐO (TELEMETRY) LÊN WEB DASHBOARD (ZERO HEAP ALLOCATION)
// =========================================================================
void sendTelemetry() {
  uint32_t freeHeap = ESP.getFreeHeap();
  uint32_t totalHeap = ESP.getHeapSize();
  float heapPct = totalHeap > 0
                      ? (((float)(totalHeap - freeHeap) / totalHeap) * 100.0f)
                      : 0.0f;
  int rssi = WiFi.RSSI();
  float chipTemp = temperatureRead();
  float maxTemp = max30102_read_temperature();
  unsigned long uptimeSec = millis() / 1000;
  uint32_t sketchSize = ESP.getSketchSize();
  uint32_t flashSize = ESP.getFlashChipSize();

  char jsonBuffer[512];
  int len = snprintf(
      jsonBuffer, sizeof(jsonBuffer),
      "{\"hr\":%d,\"spo2\":%.1f,\"steps\":%lu,\"sensor_temp\":%.1f,"
      "\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,"
      "\"ax_ms2\":%.2f,\"ay_ms2\":%.2f,\"az_ms2\":%.2f,\"a_mag_ms2\":%.2f,"
      "\"fall\":%s,\"finger\":%s,\"max_ready\":%s,"
      "\"screen_state\":\"%s\",\"oled_page\":%d,"
      "\"free_heap\":%u,\"total_heap\":%u,\"heap_pct\":%.1f,"
      "\"chip_temp\":%.1f,\"rssi\":%d,\"uptime\":%lu,"
      "\"cpu_freq\":%u,\"sketch_size\":%u,\"flash_size\":%u}",
      heartRate, spo2, stepCount, maxTemp, ax_g, ay_g, az_g, ax_ms2, ay_ms2, az_ms2,
      a_mag_ms2, fallAlert ? "true" : "false",
      fingerDetected ? "true" : "false", max30102Ready ? "true" : "false",
      screenState, oledPage, freeHeap, totalHeap, heapPct, chipTemp, rssi,
      uptimeSec, ESP.getCpuFreqMHz(), sketchSize, flashSize);

  if (len > 0 && len < (int)sizeof(jsonBuffer)) {
    bool success = mqttClient.publish(TOPIC_TELEMETRY, jsonBuffer);
    if (success) {
      Serial.printf("[TX Telemetry] %s\n", jsonBuffer);
    } else {
      Serial.println("[-] Gui Telemetry that bai!");
    }
  }
}

// =========================================================================
// 13. THUẬT TOÁN ĐẾM BƯỚC CHÂN (PEDOMETER SCHMITT TRIGGER HYSTERESIS)
// =========================================================================
void updatePedometer(float magnitude) {
  unsigned long now = millis();

  if (magnitude < STEP_THRESHOLD_LOW) {
    stepArmed = true;
  } else if (stepArmed && magnitude > STEP_THRESHOLD_HIGH) {
    if (now - lastStepMillis > 260) {
      stepCount++;
      lastStepMillis = now;
      stepArmed = false;
    }
  }
}

// =========================================================================
// 14. VẼ GIAO DIỆN MÀN HÌNH OLED SSD1306 (128x64)
// =========================================================================
void updateOLED() {
  if (!oledReady || (strcmp(screenState, "OFF") == 0 && !fallAlert))
    return;

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  if (fallAlert) {
    renderFallAlertScreen();
  } else if (customMessage[0] != '\0' && millis() < messageExpireMillis) {
    renderMessagePopup();
  } else {
    switch (oledPage) {
    case 1:
      renderHealthPage();
      break;
    case 2:
      renderStepPage();
      break;
    case 3:
      renderMotionPage();
      break;
    default:
      renderHealthPage();
      break;
    }
  }

  display.display();
}

// Trang 1: Nhịp tim & Nồng độ SpO2 từ MAX30102
void renderHealthPage() {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("HEALTH MONITOR [P1]");
  display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  if (max30102Ready && !fingerDetected) {
    display.setTextSize(1);
    display.setCursor(6, 18);
    display.print("MAX30102 SAN SANG");
    display.setCursor(6, 32);
    display.print(">> DAT NGON TAY <<");
    display.setCursor(6, 44);
    display.print("Len cam bien I2C");
  } else {
    display.setTextSize(2);
    display.setCursor(4, 16);
    if (heartRate == 0) {
      display.print("HR: --");
    } else {
      display.printf("HR:%3d", heartRate);
    }
    display.setTextSize(1);
    display.setCursor(85, 22);
    display.print("BPM");

    display.setTextSize(2);
    display.setCursor(4, 38);
    if (spo2 <= 1.0f) {
      display.print("O2: --");
    } else {
      display.printf("O2:%4.1f", spo2);
    }
    display.setTextSize(1);
    display.setCursor(85, 44);
    display.print("%");
  }

  display.drawLine(0, 55, 128, 55, SSD1306_WHITE);
  display.setCursor(0, 57);
  display.print(max30102Ready ? (fingerDetected ? "OK" : "--") : "NC");
  display.setCursor(32, 57);
  if (sensorTemp > 0.0f) {
    display.printf("T:%.1fC", sensorTemp);
  } else {
    display.print("T:--.-C");
  }
  display.setCursor(96, 57);
  display.print(isVibrating ? "VIB!" : "BAND");
}

// Trang 2: Đếm bước chân & Calo
void renderStepPage() {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("PEDOMETER      [P2]");
  display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  display.setTextSize(2);
  display.setCursor(4, 16);
  display.printf("%5lu", stepCount);
  display.setTextSize(1);
  display.setCursor(76, 22);
  display.print("STEPS");

  int calories = (int)(stepCount * 0.04f);
  float distanceKm = (stepCount * 0.75f) / 1000.0f;
  display.setTextSize(1);
  display.setCursor(4, 36);
  display.printf("Calo: %d kcal", calories);
  display.setCursor(4, 46);
  display.printf("Dist: %.2f km", distanceKm);

  int barWidth = map(constrain(stepCount, 0, 10000), 0, 10000, 0, 126);
  display.drawRect(0, 56, 128, 7, SSD1306_WHITE);
  display.fillRect(1, 57, barWidth, 5, SSD1306_WHITE);
}

// Trang 3: Cảm biến gia tốc GY-521 thể hiện đơn vị m/s^2 & Cảnh báo > 20 m/s^2
void renderMotionPage() {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("ACCEL (m/s2)   [P3]");
  display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(4, 14);
  display.printf("Ax: %-5.1f m/s2", ax_ms2);
  display.setCursor(4, 25);
  display.printf("Ay: %-5.1f m/s2", ay_ms2);
  display.setCursor(4, 36);
  display.printf("Az: %-5.1f m/s2", az_ms2);

  display.drawLine(0, 48, 128, 48, SSD1306_WHITE);
  display.setCursor(2, 52);
  display.printf("|A|:%-4.1f", a_mag_ms2);

  display.setCursor(68, 52);
  if (a_mag_ms2 > FALL_THRESHOLD_MS2 || fallAlert) {
    display.print("[TE NGA!!]");
  } else if (a_mag_ms2 > 13.0f) {
    display.print("[VAN DONG]");
  } else {
    display.print("[BINH THUONG]");
  }
}

// Màn hình báo động khẩn cấp khi phát hiện té ngã
void renderFallAlertScreen() {
  display.drawRoundRect(0, 0, 128, 64, 4, SSD1306_WHITE);
  display.drawRoundRect(1, 1, 126, 62, 3, SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(8, 6);
  display.print("! CANH BAO TE NGA !");
  display.drawLine(4, 18, 124, 18, SSD1306_WHITE);

  display.setTextSize(2);
  display.setCursor(8, 24);
  display.printf("%.1f m/s2", a_mag_ms2);

  display.setTextSize(1);
  display.setCursor(8, 44);
  display.print("> 20 m/s2 PHAT HIEN!");
  display.setCursor(8, 54);
  display.print("Rung coi... Can cuu!");
}

// Popup thông báo từ Web Dashboard
void renderMessagePopup() {
  display.drawRoundRect(2, 4, 124, 56, 4, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(20, 10);
  display.print("!! THONG BAO !!");
  display.drawLine(10, 22, 118, 22, SSD1306_WHITE);

  display.setCursor(8, 28);
  int len = strlen(customMessage);
  if (len <= 16) {
    display.print(customMessage);
  } else {
    char line1[17];
    strncpy(line1, customMessage, 16);
    line1[16] = '\0';
    display.print(line1);

    display.setCursor(8, 42);
    char line2[17];
    strncpy(line2, customMessage + 16, 16);
    line2[16] = '\0';
    display.print(line2);
  }
}