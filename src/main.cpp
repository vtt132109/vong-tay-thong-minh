#include "app_state.h"
#include "ai_model.h"
#include "controls.h"
#include "display_ui.h"
#include "fsm.h"
#include "sensors.h"
#include "storage.h"
#include "web_api.h"
#include <stdlib.h>
#include <time.h>

Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
Adafruit_MPU6050 mpu;
MAX30100 hrm;
BeatDetector beatDetector;
DCRemover irDCRemover(0.95f);
DCRemover redDCRemover(0.95f);
FilterBuLp1 pulseFilter;
SpO2Calculator spo2Calculator;
Preferences prefs;
WebServer server(80);

SemaphoreHandle_t telemetryMutex = nullptr;
QueueHandle_t commandQueue = nullptr;
TelemetrySnapshot gTelemetry;

volatile bool gWifiConnected = false;

bool oledReady = false;
bool mpuReady = false;
bool maxReady = false;

volatile bool captureActive = false;
uint32_t captureEndMs = 0;
char aiLabel[16] = "n/a";
float aiConfidence = 0.0f;
float aiProbability = 0.0f;
float aiThreshold = 0.94f;
uint8_t aiWindowFill = 0;
uint32_t aiInferenceCount = 0;
uint32_t aiInferenceUs = 0;
float aiWindowPeak = 0.0f;
bool aiFall = false;
bool ppgMotion = false;

SystemState state = SystemState::Idle;
uint32_t stateEnteredMs = 0;
uint32_t countdownEndMs = 0;
uint32_t snoozeEndMs = 0;
AlertType pendingAlertType = AlertType::Fall;
char alarmReason[48] = "Te nga";
float fallThreshold = DEFAULT_FALL_THRESHOLD;
uint32_t fallCount = 0;
uint32_t stepCount = 0;

float lastTotalAcc = 0.0f;
float bpm = 0.0f;
uint8_t spo2 = 0;
float rawBpm = 0.0f;
uint8_t rawSpo2 = 0;
bool fingerDetected = false;
float batteryVoltage = 0.0f;
uint8_t batteryPercent = 0;
bool buzzerActive = false;
uint32_t testBuzzerUntilMs = 0;

uint32_t freeFallStartMs = 0;
uint8_t freeFallLowCount = 0;
uint32_t impactStartMs = 0;
float impactSamples[IMPACT_SAMPLE_CAPACITY];
size_t impactSampleCount = 0;
bool impactExtended = false;
uint32_t lastDirectImpactMs = 0;

bool healthAbnormal = false;
uint32_t healthAbnormalSinceMs = 0;

bool buttonDown = false;
bool buttonLongHandled = false;
uint32_t buttonDownMs = 0;
uint32_t buttonTestUntilMs = 0;

uint32_t lastStepMs = 0;
bool stepHigh = false;

float irWave[WAVE_POINTS] = {0};
float redWave[WAVE_POINTS] = {0};
float irPeak = 1.0f;
float redPeak = 1.0f;

uint32_t loopCounter = 0;
uint32_t loopSecondMs = 0;
float loopFps = 0.0f;
uint32_t lastBatteryMs = 0;
uint32_t lastDisplayMs = 0;
uint32_t lastTelemetryMs = 0;
uint32_t lastStepSaveMs = 0;
uint32_t lastDebugMs = 0;
uint32_t lastSavedSteps = 0;

static void i2cBusRecover() {
  bool stuck = digitalRead(PIN_I2C_SDA) == LOW;
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, OUTPUT_OPEN_DRAIN);
  digitalWrite(PIN_I2C_SCL, HIGH);
  for (int i = 0; i < 9 && digitalRead(PIN_I2C_SDA) == LOW; ++i) {
    digitalWrite(PIN_I2C_SCL, LOW);
    delayMicroseconds(5);
    digitalWrite(PIN_I2C_SCL, HIGH);
    delayMicroseconds(5);
  }
  pinMode(PIN_I2C_SDA, OUTPUT_OPEN_DRAIN);
  digitalWrite(PIN_I2C_SDA, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_I2C_SCL, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_I2C_SDA, HIGH);
  delayMicroseconds(5);
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  if (stuck) {
    Serial.printf("[I2C] bus recovery SDA=%d SCL=%d\n",
                  digitalRead(PIN_I2C_SDA), digitalRead(PIN_I2C_SCL));
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[BIO-BAND] ESP32-S3 Super Mini");
  i2cBusRecover();

  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_BUTTON_ALT, INPUT_PULLUP);
  Serial.printf("[BTN] GPIO2=%d BOOT=%d\n",
                digitalRead(PIN_BUTTON), digitalRead(PIN_BUTTON_ALT));
  if (PIN_BATTERY_ADC >= 0) {
    analogSetPinAttenuation((uint8_t)PIN_BATTERY_ADC, ADC_11db);
  }

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);
  Wire.setTimeOut(20);
  Serial.printf("[I2C] SDA=%u SCL=%u @100kHz\n", (unsigned)PIN_I2C_SDA, (unsigned)PIN_I2C_SCL);
  const uint8_t known[] = {0x3C, 0x3D, 0x57, 0x68};
  for (uint8_t i = 0; i < sizeof(known); ++i) {
    Wire.beginTransmission(known[i]);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[I2C] 0x%02X OK\n", known[i]);
    }
  }

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    oledReady = display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
  } else {
    oledReady = true;
  }
  if (oledReady) {
    renderBootScreen();
  } else {
    Serial.println("[OLED] not found at 0x3C/0x3D");
  }

  if (!mpu.begin(0x68, &Wire)) {
    mpuReady = false;
    Serial.println("[MPU6050] not found");
  } else {
    mpuReady = true;
    // Ranges match the HIFD training domain (impacts up to ~12 g, gyro up to
    // ~2000 deg/s in the dataset).
    mpu.setAccelerometerRange(MPU6050_RANGE_16_G);
    mpu.setGyroRange(MPU6050_RANGE_2000_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("[MPU6050] ready, +/-16G, +/-2000dps, DLPF 21Hz");
  }

  Wire.beginTransmission(0x57);
  Wire.write(0x06);
  Wire.write(0x40);  // MODE_CONFIG RESET bit
  Wire.endTransmission();
  delay(10);
  maxReady = hrm.begin();
  if (maxReady) {
    hrm.shutdown();
    hrm.resetFifo();
    hrm.setMode(MAX30100_MODE_SPO2_HR);
    hrm.setLedsCurrent(MAX30100_LED_CURR_11MA, MAX30100_LED_CURR_11MA);
    delay(20);
    Wire.beginTransmission(0x57);
    Wire.write(0x05);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)0x57, (uint8_t)64);
    while (Wire.available()) Wire.read();
    hrm.resetFifo();
    Wire.setClock(100000);  // MAX30100lib::begin() forces 400 kHz
    Serial.println("[MAX30100] ready");
  } else {
    uint8_t partId = 0;
    Wire.beginTransmission(0x57);
    Wire.write(0xFF);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(0x57, 1) == 1) {
      partId = Wire.read();
    }
    Serial.printf("[MAX] not found; partID=0x%02X (expected 0x11 for MAX30100)\n", partId);
  }

  loadPrefs();
  batteryVoltage = readBatteryVoltage();
  batteryPercent = lipoPercent(batteryVoltage);

  telemetryMutex = xSemaphoreCreateMutex();
  commandQueue = xQueueCreate(8, sizeof(WebCommand));
  publishTelemetry(millis());

  setenv("TZ", "ICT-7", 1);
  tzset();

  xTaskCreatePinnedToCore(networkTask, "network", 20480, nullptr, 1, nullptr, 0);

  if (oledReady) {
    display.clearDisplay();
    display.setCursor(8, 24);
    display.println("READY");
    display.display();
    delay(400);
  }
  Serial.println("[BIO-BAND] ready");
}

void loop() {
  static TickType_t lastWake = xTaskGetTickCount();
  vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(20));
  uint32_t now = millis();

  if (captureActive) {
    handleCommands(now);
    if (!captureActive) {
      // Stop requested from the web API; continue with normal processing.
    } else if (!mpuReady || now >= captureEndMs) {
      captureActive = false;
      Serial.println("# CAPTURE_END");
    } else {
      sensors_event_t a, g, temp;
      mpu.getEvent(&a, &g, &temp);
      Serial.printf("%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n",
                    a.acceleration.x, a.acceleration.y, a.acceleration.z,
                    g.gyro.x, g.gyro.y, g.gyro.z);
      return;
    }
  }

  ++loopCounter;
  if (now - loopSecondMs >= 1000) {
    loopFps = loopCounter * 1000.0f / (now - loopSecondMs);
    loopCounter = 0;
    loopSecondMs = now;
  }

  handleCommands(now);
  updateButton(now);

  float acc = 0.0f;
  bool motion = false;
  if (mpuReady) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    acc = sqrtf(a.acceleration.x * a.acceleration.x +
                a.acceleration.y * a.acceleration.y +
                a.acceleration.z * a.acceleration.z);
    lastTotalAcc = acc;
    float gyroMag = sqrtf(g.gyro.x * g.gyro.x + g.gyro.y * g.gyro.y + g.gyro.z * g.gyro.z);
    motion = (fabsf(acc - 9.80665f) > PPG_MOTION_ACCEL_GATE) ||
             (gyroMag > PPG_MOTION_GYRO_GATE);
    aiPushSample(a.acceleration.x, a.acceleration.y, a.acceleration.z,
                 g.gyro.x, g.gyro.y, g.gyro.z);
    updatePedometer(now, acc);
  }

  processMaxSamples(now, motion);

  if (now - lastBatteryMs >= BATTERY_PERIOD_MS) {
    batteryVoltage = readBatteryVoltage();
    batteryPercent = lipoPercent(batteryVoltage);
    lastBatteryMs = now;
  }

  updateFallDetection(now, acc);
  updateHealthGuard(now);
  updateBuzzer(now);

  if (now - lastDisplayMs >= DISPLAY_PERIOD_MS) {
    renderDisplay(now);
    lastDisplayMs = now;
  }
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    publishTelemetry(now);
    lastTelemetryMs = now;
  }
  if (now - lastDebugMs >= 2000) {
    Serial.printf("[DATA] HR=%.0f/raw%.0f SpO2=%u/raw%u acc=%.2f batt=%.2fV %u%% motion=%d steps=%lu falls=%lu state=%s\n",
                  bpm, rawBpm, (unsigned)spo2, (unsigned)rawSpo2, lastTotalAcc, batteryVoltage,
                  (unsigned)batteryPercent, motion ? 1 : 0, (unsigned long)stepCount,
                  (unsigned long)fallCount, stateName(state));
    lastDebugMs = now;
  }
  if (stepCount != lastSavedSteps && now - lastStepSaveMs >= STEP_SAVE_PERIOD_MS) {
    saveSteps();
  }
}
