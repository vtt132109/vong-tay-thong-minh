#include <Arduino.h>
#include <Wire.h>
#include <time.h>
#include <esp_task_wdt.h>

#include "Config.h"
#include "Secrets.h"
#include "Display/OledDisplay.h"
#include "Dsp/FallDetector.h"
#include "Dsp/Pedometer.h"
#include "Dsp/PpgSignalProcessor.h"
#include "Dsp/TinyMlClassifier.h"
#include "Network/MqttService.h"
#include "Network/OtaService.h"
#include "Sensors/Max30102Driver.h"
#include "Sensors/Mpu6050Driver.h"

// =========================================================================
// CẤU TRÚC DỮ LIỆU ĐỒNG BỘ TRẠNG THÁI GIỮA 2 NHÂN (THREAD-SAFE SNAPSHOT)
// =========================================================================
struct SystemState {
  int hr;
  float spo2;
  float sensorTemp;
  bool maxReady;
  bool fingerDetected;
  unsigned long steps;
  float ax_ms2, ay_ms2, az_ms2;
  float ax_g, ay_g, az_g;
  float a_mag_ms2;
  bool fallAlert;
  float peakFallMs2;
  bool isVibrating;
  bool pulseBeating;
  float aiFallProb;
  bool aiCandidate;
  int8_t ppgWave[PPG_WAVE_BUFFER_SIZE];
};

static SystemState sharedState;
static SemaphoreHandle_t stateMutex = nullptr;

// =========================================================================
// KHỞI TẠO CÁC MÔ-ĐUN HỆ THỐNG
// =========================================================================
static Max30102Driver max30102;
static Mpu6050Driver mpu;
static PpgSignalProcessor ppg;
static FallDetector fallDetector;
static TinyMlClassifier tinyMl;
static Pedometer pedometer;
static OledDisplay display;
static MqttService mqtt;
static OtaService ota;

// Biến điều khiển rung & timers
static bool isManualVibrating = false;
static unsigned long vibrateStopMillis = 0;
static unsigned long lastScreenActiveTime = 0;

// Nguyên mẫu hàm
void i2cScan();
void setupCallbacks();
void taskSensorsDsp(void *pvParameters);
void taskNetworkUi(void *pvParameters);

// =========================================================================
// KHỞI TẠO HỆ THỐNG (SETUP)
// =========================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  // Hạ xung nhịp CPU xuống 80MHz: WiFi & FreeRTOS hoạt động hoàn hảo, tiết kiệm 50% dòng Core
  setCpuFrequencyMhz(80);

  Serial.println("\n==================================================");
  Serial.printf("  ESP32-S3 MINI SMARTBAND - CPU: %u MHz\n", ESP.getCpuFreqMHz());
  Serial.println("  KIẾN TRÚC DUAL-CORE FREERTOS & HARD REAL-TIME");
  Serial.println("==================================================");

  // Cấu hình chân motor rung
  pinMode(PIN_VIBRATE, OUTPUT);
  digitalWrite(PIN_VIBRATE, LOW);

  // Khôi phục bus I2C nếu có thiết bị đang kéo SDA LOW từ phiên trước
  Max30102Driver::recoverBus();

  // Khởi tạo Bus I2C phần cứng dùng chung (SDA & SCL)
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, INPUT_PULLUP);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(I2C_BUS_SPEED);
  Wire.setTimeOut(I2C_TIMEOUT_MS);

  // Quét thiết bị I2C phục vụ chẩn đoán
  i2cScan();

  // Khởi tạo các ngoại vi
  display.begin();
  mpu.begin();
  max30102.begin();
  pedometer.begin(); // Nạp số bước đã lưu từ Flash NVS

  // Khởi tạo Semaphore khóa trạng thái đồng bộ giữa 2 Core
  stateMutex = xSemaphoreCreateMutex();

  // Thiết lập callbacks điều khiển từ xa
  setupCallbacks();

  // Khởi tạo WiFi & MQTT
  mqtt.begin();

  // Cấu hình đồng bộ thời gian thực qua NTP (Múi giờ Việt Nam GMT+7)
  configTime(NTP_GMT_OFFSET_SEC, NTP_DAYLIGHT_OFFSET_SEC, NTP_SERVER_1, NTP_SERVER_2);

  // Khởi tạo dịch vụ nạp code từ xa OTA qua WiFi
  ota.begin();

  // Khởi tạo Hardware Task Watchdog Timer (TWDT) 5 giây chống treo chip/I2C
  esp_task_wdt_init(WDT_TIMEOUT_SEC, true);

  // TẠO 2 TASK ĐA NHIỆM TRÊN 2 NHÂN VẬT LÝ ESP32-S3
  // Core 0: Task chuyên lấy mẫu cảm biến & DSP (Ưu tiên cao, chu kỳ 20ms)
  xTaskCreatePinnedToCore(
      taskSensorsDsp, "TaskSensorsDSP", 4096, NULL, 3, NULL, 0);

  // Core 1: Task chuyên vẽ màn hình OLED, mạng WiFi/MQTT/OTA (Ưu tiên bình thường)
  xTaskCreatePinnedToCore(
      taskNetworkUi, "TaskNetworkUI", 6144, NULL, 1, NULL, 1);
}

void loop() {
  // Loop chính để trống hoặc chuyển sang chế độ ngủ, toàn bộ xử lý diễn ra trong FreeRTOS Tasks
  vTaskDelay(pdMS_TO_TICKS(1000));
}

// =========================================================================
// TASK 1: THU THẬP CẢM BIẾN & XỬ LÝ TÍN HIỆU SỐ (CORE 0 - HARD REAL-TIME)
// =========================================================================
void taskSensorsDsp(void *pvParameters) {
  esp_task_wdt_add(NULL); // Đăng ký Task Core 0 vào Watchdog

  unsigned long lastMpuTime = 0;
  unsigned long lastMaxTime = 0;
  unsigned long lastLogTime = 0;
  unsigned long lastSensorRetryTime = 0;
  int i2cConsecutiveFails = 0;
  bool prevFall = false;

  for (;;) {
    esp_task_wdt_reset(); // Reset Watchdog mỗi chu kỳ
    unsigned long now = millis();

    // 1. Thử kết nối lại MAX30102 nếu chưa nhận & tự động phục hồi bus I2C nếu kẹt
    if (!max30102.isReady()) {
      if (now - lastSensorRetryTime > SENSOR_RETRY_INTERVAL_MS) {
        lastSensorRetryTime = now;
        i2cConsecutiveFails++;
        if (i2cConsecutiveFails >= I2C_MAX_RETRY_ERRORS) {
          Serial.println("[I2C-RECOVERY] Phat hien bus I2C bi treo -> Reset phan cung bus...");
          Wire.end();
          vTaskDelay(pdMS_TO_TICKS(10));
          Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_BUS_SPEED);
          Wire.setTimeOut(I2C_TIMEOUT_MS);
          i2cConsecutiveFails = 0;
        }
        max30102.begin();
      }
    } else {
      i2cConsecutiveFails = 0;
    }

    // 2. Thu thập dữ liệu MPU6050 ở tần số 50Hz (mỗi 20ms)
    if (now - lastMpuTime >= MPU_SAMPLE_INTERVAL_MS) {
      lastMpuTime = now;
      mpu.update();

      float ax = mpu.getAxMs2();
      float ay = mpu.getAyMs2();
      float az = mpu.getAzMs2();
      float mag = mpu.getMagnitude();

      fallDetector.update(mag);
      pedometer.update(mag);

      // KIẾN TRÚC TINYML 2 TẦNG (2-STAGE CASCADE TRIGGER)
      // Tầng 1: Lọc ngưỡng nhanh. Tầng 2: Suy luận mạng nơ-ron xác nhận té ngã
      bool aiFallDetected = tinyMl.processSample(ax, ay, az);
      if (aiFallDetected && !fallDetector.isAlert()) {
        fallDetector.triggerAlert(mag);
      }

      // Xử lý sườn kích hoạt / hủy cảnh báo té ngã
      bool currentFall = fallDetector.isAlert();
      if (currentFall && !prevFall) {
        mqtt.publishFallAlert(fallDetector.getPeakMagnitude());
      } else if (!currentFall && prevFall) {
        mqtt.publishFallCleared();
        digitalWrite(PIN_VIBRATE, LOW);
      }
      prevFall = currentFall;

#if EDGE_IMPULSE_DATA_FORWARDER
      // Luồng CSV 50Hz thuần túy cho Edge Impulse Studio (accX, accY, accZ)
      Serial.printf("%.2f,%.2f,%.2f\n", ax, ay, az);
#endif
    }

    // 3. Thu thập dữ liệu MAX30102 ở tần số 40Hz (mỗi 25ms)
    if (now - lastMaxTime >= MAX_SAMPLE_INTERVAL_MS) {
      lastMaxTime = now;

      if (max30102.isReady()) {
        uint32_t red = 0, ir = 0;
        if (max30102.readFifo(red, ir)) {
          ppg.processSample(red, ir, mpu.getAxG(), mpu.getAyG());
        }
        max30102.updateTemperature();
      } else {
        ppg.simulate(mpu.getAxG(), mpu.getAyG());
      }
    }

    // 4. Điều khiển motor rung phản hồi
    if (fallDetector.isAlert()) {
      bool pulse = (now / 200) % 2 == 0;
      digitalWrite(PIN_VIBRATE, pulse ? HIGH : LOW);
    } else if (isManualVibrating) {
      if (now >= vibrateStopMillis) {
        isManualVibrating = false;
        digitalWrite(PIN_VIBRATE, LOW);
      }
    }

    // 5. Cập nhật trạng thái dùng chung an toàn sang Core 1
    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
      sharedState.hr = ppg.getHeartRate();
      sharedState.spo2 = ppg.getSpO2();
      sharedState.sensorTemp = max30102.getTemperature();
      sharedState.maxReady = max30102.isReady();
      sharedState.fingerDetected = ppg.isFingerDetected();
      sharedState.steps = pedometer.getStepCount();
      sharedState.ax_ms2 = mpu.getAxMs2();
      sharedState.ay_ms2 = mpu.getAyMs2();
      sharedState.az_ms2 = mpu.getAzMs2();
      sharedState.ax_g = mpu.getAxG();
      sharedState.ay_g = mpu.getAyG();
      sharedState.az_g = mpu.getAzG();
      sharedState.a_mag_ms2 = mpu.getMagnitude();
      sharedState.fallAlert = fallDetector.isAlert();
      sharedState.peakFallMs2 = fallDetector.getPeakMagnitude();
      sharedState.isVibrating = (fallDetector.isAlert() || isManualVibrating);
      sharedState.pulseBeating = ppg.isPulseBeating();
      sharedState.aiFallProb = tinyMl.getFallProbability();
      sharedState.aiCandidate = tinyMl.isCandidateActive();

      const int8_t *waveSrc = ppg.getWaveform();
      memcpy(sharedState.ppgWave, waveSrc, sizeof(sharedState.ppgWave));

      xSemaphoreGive(stateMutex);
    }

#if !EDGE_IMPULSE_DATA_FORWARDER
    // 6. In log PPG định kỳ lên Serial (150ms)
    if (now - lastLogTime >= PPG_PRINT_INTERVAL_MS) {
      lastLogTime = now;
      if (max30102.isReady() && ppg.isFingerDetected()) {
        Serial.printf("[PPG Core0] HR:%3d BPM | SpO2:%4.1f%% | T:%.1f C | Stp:%lu\n",
                      ppg.getHeartRate(), ppg.getSpO2(), max30102.getTemperature(),
                      pedometer.getStepCount());
      }
    }
#endif

    // Nghỉ 4ms nhường CPU nội bộ Core 0
    vTaskDelay(pdMS_TO_TICKS(4));
  }
}

// =========================================================================
// TASK 2: GIAO DIỆN OLED, MẠNG WIFI / MQTT & OTA (CORE 1)
// =========================================================================
void taskNetworkUi(void *pvParameters) {
  esp_task_wdt_add(NULL); // Đăng ký Task Core 1 vào Watchdog

  unsigned long lastOledTime = 0;
  unsigned long lastTelemetryTime = 0;
  lastScreenActiveTime = millis();
  float prevWristAz = 0.0f;
  float prevWristAy = 0.0f;
  char timeStr[12] = "";
  char dateStr[16] = "";

  for (;;) {
    esp_task_wdt_reset(); // Reset Watchdog mỗi chu kỳ
    unsigned long now = millis();

    // 1. Duy trì kết nối WiFi, MQTT và lắng nghe OTA
    mqtt.update();
    ota.update();

    // 2. Đọc thời gian NTP từ đồng hồ phần cứng RTC nội bộ
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 10)) {
      strftime(timeStr, sizeof(timeStr), "%H:%M:%S", &timeinfo);
      strftime(dateStr, sizeof(dateStr), "%d/%m/%Y", &timeinfo);

      // Tự động reset bước chân lúc nửa đêm 00:00:00
      if (timeinfo.tm_hour == 0 && timeinfo.tm_min == 0 && timeinfo.tm_sec == 0) {
        static bool midnightResetDone = false;
        if (!midnightResetDone) {
          pedometer.reset();
          midnightResetDone = true;
        }
      }
    }

    // 3. Tự động lưu số bước chân vào Flash NVS
    pedometer.checkAutoSave();

    // 4. Lấy bản sao trạng thái an toàn từ Core 0
    SystemState localState;
    bool stateValid = false;
    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
      memcpy(&localState, &sharedState, sizeof(SystemState));
      stateValid = true;
      xSemaphoreGive(stateMutex);
    }

    if (stateValid) {
      // 5. Quản lý Auto Screen Timeout & Lắc/Nâng Cổ Tay Bật Màn Hình (Wrist Wake-Up)
      float dAz = fabsf(localState.az_ms2 - prevWristAz);
      float dAy = fabsf(localState.ay_ms2 - prevWristAy);
      prevWristAz = localState.az_ms2;
      prevWristAy = localState.ay_ms2;

      bool wristMotion = (dAz + dAy > WRIST_WAKE_JERK_THRESHOLD);
      bool lookingAtWatch = (localState.az_ms2 > WRIST_WAKE_MIN_AZ && fabsf(localState.ay_ms2) < WRIST_WAKE_MAX_AY);

      // Nếu đang tắt màn hình và người dùng nâng tay nhìn đồng hồ -> Tự động bật màn hình
      if (!display.isPowerOn() && lookingAtWatch && wristMotion) {
        display.setPower(true);
        lastScreenActiveTime = now;
        Serial.println("[WRIST-WAKE] Nang co tay huong vao mat -> Bat man hinh OLED!");
      }

      // Nếu có sự kiện khẩn cấp té ngã hoặc đang rung báo động -> Luôn bật màn hình
      if (localState.fallAlert || localState.isVibrating) {
        if (!display.isPowerOn()) display.setPower(true);
        lastScreenActiveTime = now;
      }

      // Tự động tắt màn hình sau OLED_AUTO_TIMEOUT_MS không cử động để tiết kiệm pin
      if (display.isPowerOn() && !localState.fallAlert) {
        if (wristMotion || (localState.hr > 0 && localState.fingerDetected)) {
          lastScreenActiveTime = now; // Còn tương tác thì gia hạn thời gian sáng
        } else if (now - lastScreenActiveTime > OLED_AUTO_TIMEOUT_MS) {
          display.setPower(false);
          Serial.println("[POWER-SAVE] Man hinh OLED tu dong tat sau 30s tiet kiem pin.");
        }
      }

      // 6. Cập nhật màn hình OLED (150ms / ~6.6 FPS)
      if (now - lastOledTime >= OLED_REFRESH_INTERVAL_MS) {
        lastOledTime = now;
        display.render(localState.hr, localState.spo2, localState.sensorTemp,
                       localState.maxReady, localState.fingerDetected,
                       localState.steps, localState.ax_ms2, localState.ay_ms2,
                       localState.az_ms2, localState.a_mag_ms2,
                       localState.fallAlert, localState.peakFallMs2,
                       localState.isVibrating, localState.ppgWave,
                       localState.pulseBeating, timeStr, dateStr,
                       mqtt.isConnected());
      }

      // 7. Gửi bản tin Telemetry Thích Ứng (Adaptive Telemetry) lên MQTT
      // Khi nghỉ ngơi: gửi mỗi 5s để tiết kiệm 68% công suất phát WiFi
      // Khi vận động hoặc có cảnh báo té ngã / nhịp tim: gửi mỗi 1.5s
      bool isEmergencyOrActive = (localState.fallAlert || localState.isVibrating ||
                                  localState.fingerDetected || (localState.a_mag_ms2 > 12.5f));
      unsigned long telemetryTargetInterval = isEmergencyOrActive ? TELEMETRY_ACTIVE_INTERVAL_MS : TELEMETRY_IDLE_INTERVAL_MS;

      if (now - lastTelemetryTime >= telemetryTargetInterval) {
        lastTelemetryTime = now;

        TelemetryData data;
        data.hr = localState.hr;
        data.spo2 = localState.spo2;
        data.steps = localState.steps;
        data.sensorTemp = localState.sensorTemp;
        data.ax_g = localState.ax_g;
        data.ay_g = localState.ay_g;
        data.az_g = localState.az_g;
        data.ax_ms2 = localState.ax_ms2;
        data.ay_ms2 = localState.ay_ms2;
        data.az_ms2 = localState.az_ms2;
        data.a_mag_ms2 = localState.a_mag_ms2;
        data.fall = localState.fallAlert;
        data.finger = localState.fingerDetected;
        data.maxReady = localState.maxReady;
        data.screenState = display.isPowerOn() ? "ON" : "OFF";
        data.oledPage = display.getPage();

        mqtt.sendTelemetry(data);
      }
    }

    // Nhường CPU cho WiFi stack Core 1 (25ms chu kỳ thức)
    vTaskDelay(pdMS_TO_TICKS(25));
  }
}

// =========================================================================
// THIẾT LẬP CÁC LỆNH ĐIỀU KHIỂN TỪ WEB QUA MQTT CALLBACKS
// =========================================================================
void setupCallbacks() {
  mqtt.onScreenPower([](bool on) {
    display.setPower(on);
    if (on) lastScreenActiveTime = millis();
  });

  mqtt.onScreenPage([](int page) {
    display.setPage(page);
    display.setPower(true);
    lastScreenActiveTime = millis();
  });

  mqtt.onScreenMsg([](const char *msg) {
    display.setPower(true);
    lastScreenActiveTime = millis();
    display.setMessage(msg);
  });

  mqtt.onVibrate([](unsigned long durationMs) {
    isManualVibrating = true;
    vibrateStopMillis = millis() + durationMs;
    digitalWrite(PIN_VIBRATE, HIGH);
  });

  mqtt.onResetSteps([]() {
    pedometer.reset();
  });

  mqtt.onFallDismiss([]() {
    fallDetector.dismiss();
    digitalWrite(PIN_VIBRATE, LOW);
  });
}

// =========================================================================
// QUÉT CÁC THIẾT BỊ I2C TRÊN BUS PHẦN CỨNG
// =========================================================================
void i2cScan() {
  Serial.println("[I2C Scan] Dang quet cac thiet bi tren bus I2C...");
  int nDevices = 0;
  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();
    if (error == 0) {
      Serial.printf("  -> Tim thay thiet bi tai dia chi 0x%02X", address);
      if (address == OLED_I2C_ADDR) Serial.print(" [OLED SSD1306]");
      else if (address == MAX30102_I2C_ADDR) Serial.print(" [MAX30102 Nhip tim/SpO2]");
      else if (address == MPU6050_I2C_ADDR) Serial.print(" [MPU6050 Gia toc]");
      Serial.println();
      nDevices++;
    }
  }
  if (nDevices == 0) {
    Serial.println("  [-] KHONG tim thay thiet bi I2C nao!");
  } else {
    Serial.printf("  [+] Tim thay tong cong %d thiet bi tren bus I2C.\n", nDevices);
  }
}