#include "app_state.h"
#include "ai_model.h"
#include "controls.h"
#include "display_ui.h"
#include "fsm.h"
#include "sensors.h"
#include "storage.h"
#include "web_api.h"
#include <stdlib.h>
#include <string.h>
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
float aiProbMlp = 0.0f;
float aiProbCnn = -1.0f;
uint32_t aiCnnUs = 0;
uint8_t aiSelfTestResult = 0;
volatile bool replayActive = false;
bool aiAlarmEnabled = false;
float aiMax6s = 0.0f;
bool ppgMotion = false;

SystemState state = SystemState::Idle;
uint32_t stateEnteredMs = 0;
uint32_t countdownEndMs = 0;
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
uint32_t loopMaxDtMs = 0;
uint32_t loopMaxDtMsPublished = 0;

static float gyroBias[3] = {0.0f, 0.0f, 0.0f};

// MPU6050 zero-rate offset is up to ~0.35 rad/s and would shift the gyro features of the AI.
// Average one second of gyro at boot (only if the wrist is clearly still) and subtract it.
static void calibrateGyro() {
  float sum[3] = {0.0f, 0.0f, 0.0f};
  int n = 0;
  for (; n < 50; ++n) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    const float mag = sqrtf(g.gyro.x * g.gyro.x + g.gyro.y * g.gyro.y + g.gyro.z * g.gyro.z);
    if (mag > 0.35f) break;  // moving: a bias estimate would be wrong
    sum[0] += g.gyro.x;
    sum[1] += g.gyro.y;
    sum[2] += g.gyro.z;
    delay(20);
  }
  if (n < 50) {
    Serial.println("[MPU6050] gyro bias skipped (wrist moving at boot)");
    return;
  }
  for (int i = 0; i < 3; ++i) gyroBias[i] = sum[i] / 50.0f;
  Serial.printf("[MPU6050] gyro bias %.4f %.4f %.4f rad/s\n", (double)gyroBias[0],
                (double)gyroBias[1], (double)gyroBias[2]);
}

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

// ---------------------------------------------------------------------------------------------
// Hardware-in-the-loop over USB serial (tools/ai_lab/hil_eval.py):
//   host -> "#HIL"                 board -> "HIL READY"
//   host -> "W,<600 floats>"       board -> "P,<mlp>,<cnn>"   (one window per line)
//   host -> "#END"                 board -> "HIL END"
// Lets the host push thousands of real HIFD windows through the models running on the chip.
// ---------------------------------------------------------------------------------------------
static bool hilActive = false;

// Replay mode (tools/ai_lab/replay_eval.py): the host streams raw MPU-like samples at 50 Hz
//   "#REPLAY"                     start (virtual MPU, buzzer muted, FSM reset)   -> "REPLAY READY"
//   "S,ax,ay,az,gx,gy,gz"         one raw sample (accel incl. gravity, m/s^2; gyro rad/s)
//   "#AIMODE,0|1"                 set the AI alarm mode for this run only (not saved to NVS)
//   "#REPLAYEND"                  stop, restore the saved AI mode                -> "REPLAY END"
struct ReplaySample { float v[6]; };
static ReplaySample replayQ[64];
static uint8_t replayHead = 0, replayTail = 0;
static ReplaySample replayLast = {{0.0f, 0.0f, 9.80665f, 0.0f, 0.0f, 0.0f}};
static bool savedAiMode = false;

static bool replayPop(ReplaySample &out) {
  if (replayHead == replayTail) return false;
  out = replayQ[replayTail];
  replayTail = (uint8_t)((replayTail + 1) % 64);
  return true;
}


// ---------------------------------------------------------------------------------------------
// "#HTTPSELF": the board calls its own HTTP API over loopback and checks the CSRF guard and the
// missing-CORS behaviour (the host cannot reach the LAN address, so this runs on the chip).
// Never touches /test_hw, /clear_nvs or /wifi_save.
// ---------------------------------------------------------------------------------------------
static int httpProbe(const char *method, const String &path, bool withHeader, bool *hasCors) {
  WiFiClient c;
  c.setTimeout(2);
  if (!c.connect(WiFi.localIP(), 80)) return -1;
  c.printf("%s %s HTTP/1.1\r\nHost: bioband\r\nConnection: close\r\n", method, path.c_str());
  if (withHeader) c.print("X-Bioband: 1\r\n");
  c.print("Content-Length: 0\r\n\r\n");
  String status = c.readStringUntil('\n');
  int code = status.length() > 12 ? status.substring(9, 12).toInt() : -2;
  if (hasCors) *hasCors = false;
  uint32_t t0 = millis();
  while (c.connected() && millis() - t0 < 2000) {
    String line = c.readStringUntil('\n');
    if (line.length() <= 1) break;  // blank line: end of headers
    line.toLowerCase();
    if (hasCors && line.startsWith("access-control-allow")) *hasCors = true;
  }
  c.stop();
  return code;
}

static void httpSelfTest() {
  if (WiFi.status() != WL_CONNECTED && !WiFi.softAPgetStationNum()) {
    Serial.println("[HTTPSELF] skipped: no network");
    return;
  }
  struct Case { const char *name; const char *method; String path; bool header; int expect; };
  const String thr = "/set_thresh?val=" + String(fallThreshold, 1);
  const String ai = "/ai_mode?val=" + String(aiAlarmEnabled ? 1 : 0);
  const Case cases[] = {
      {"GET /data", "GET", "/data", false, 200},
      {"GET /wifi", "GET", "/wifi", false, 200},
      {"POST /cancel no header", "POST", "/cancel", false, 403},
      {"POST /cancel header", "POST", "/cancel", true, 200},
      {"POST /set_thresh no header", "POST", thr, false, 403},
      {"POST /set_thresh header", "POST", thr, true, 200},
      {"POST /set_time no header", "POST", "/set_time?epoch=1900000000", false, 403},
      {"POST /ai_mode no header", "POST", ai, false, 403},
      {"POST /ai_mode header", "POST", ai, true, 200},
      {"GET /capture?on=0 no header", "GET", "/capture?on=0", false, 403},
      {"POST /capture?on=0 header", "POST", "/capture?on=0", true, 200},
  };
  int bad = 0;
  bool cors = false;
  for (const Case &k : cases) {
    const int code = httpProbe(k.method, k.path, k.header, &cors);
    const bool ok = (code == k.expect) && !cors;
    if (!ok) ++bad;
    Serial.printf("[HTTPSELF] %-30s -> %d (want %d) cors=%d %s\n", k.name, code, k.expect, cors ? 1 : 0,
                  ok ? "OK" : "FAIL");
  }
  Serial.printf("[HTTPSELF] %s (%d failures)\n", bad == 0 ? "PASS" : "FAIL", bad);
}

static void serialCommands() {
  static char line[12288];
  static size_t len = 0;
  while (Serial.available() > 0) {
    const int c = Serial.read();
    if (c < 0) break;
    if (c == '\r') continue;
    if (c != '\n') {
      if (len < sizeof(line) - 1) line[len++] = (char)c;
      else len = 0;  // overlong line: drop it
      continue;
    }
    line[len] = '\0';
    len = 0;
    if (strcmp(line, "#HIL") == 0) {
      hilActive = true;
      Serial.println("HIL READY");
    } else if (strcmp(line, "#END") == 0) {
      hilActive = false;
      Serial.println("HIL END");
    } else if (strncmp(line, "#SETCOUNTS,", 11) == 0) {
      // Maintenance over USB: "#SETCOUNTS,<falls>,<steps>" (e.g. to undo a test run).
      unsigned long f = 0, s = 0;
      if (sscanf(line + 11, "%lu,%lu", &f, &s) == 2) {
        fallCount = f;
        stepCount = s;
        saveFalls();
        saveSteps();
        Serial.printf("COUNTS falls=%lu steps=%lu\n", f, s);
      }
    } else if (!replayActive && strncmp(line, "#AIARM,", 7) == 0) {
      // Maintenance over USB: "#AIARM,0|1" sets and saves the AI alarm mode (same as the dashboard toggle).
      aiAlarmEnabled = line[7] == '1';
      saveAiMode();
      fsmReset();
      Serial.printf("AIARM %d\n", aiAlarmEnabled ? 1 : 0);
    } else if (!replayActive && strcmp(line, "#NETTEST") == 0) {
      // Diagnostic for the shared GPIO1/2/3 net: millivolts on GPIO2 under different pin configurations.
      buzzerNetSet(false);
      pinMode(PIN_BUTTON, INPUT_PULLUP);
      delay(20);
      const uint32_t mvUp = analogReadMilliVolts(PIN_BUTTON);
      pinMode(PIN_BUTTON, INPUT);
      delay(50);
      const uint32_t mvFloat = analogReadMilliVolts(PIN_BUTTON);
      pinMode(PIN_BUTTON, INPUT_PULLDOWN);
      delay(50);
      const uint32_t mvDown = analogReadMilliVolts(PIN_BUTTON);
      pinMode(PIN_BUTTON, INPUT);
      pinMode(PIN_BUZZER, OUTPUT);
      digitalWrite(PIN_BUZZER, HIGH);
      delay(2);
      const uint32_t mvDriven = analogReadMilliVolts(PIN_BUTTON);
      digitalWrite(PIN_BUZZER, LOW);
      pinMode(PIN_BUZZER, INPUT);
      Serial.printf("NETTEST pullup=%lumV none=%lumV pulldown=%lumV gpio3high=%lumV\n",
                    (unsigned long)mvUp, (unsigned long)mvFloat, (unsigned long)mvDown, (unsigned long)mvDriven);
    } else if (strcmp(line, "#HTTPSELF") == 0) {
      httpSelfTest();
    } else if (strcmp(line, "#REPLAY") == 0) {
      replayHead = replayTail = 0;
      savedAiMode = aiAlarmEnabled;
      replayActive = true;
      fsmReset();
      Serial.println("REPLAY READY");
    } else if (strcmp(line, "#REPLAYEND") == 0) {
      replayActive = false;
      aiAlarmEnabled = savedAiMode;
      fsmReset();
      Serial.println("REPLAY END");
    } else if (replayActive && strncmp(line, "#AIMODE,", 8) == 0) {
      aiAlarmEnabled = line[8] == '1';
      Serial.printf("REPLAY AIMODE %d\n", aiAlarmEnabled ? 1 : 0);
    } else if (replayActive && line[0] == 'S' && line[1] == ',') {
      ReplaySample s;
      char *p = line + 2;
      int n = 0;
      while (n < 6 && *p) {
        char *end = nullptr;
        s.v[n++] = strtof(p, &end);
        if (end == p) break;
        p = (*end == ',') ? end + 1 : end;
      }
      const uint8_t next = (uint8_t)((replayHead + 1) % 64);
      if (n == 6 && next != replayTail) {
        replayQ[replayHead] = s;
        replayHead = next;
      }
    } else if (hilActive && line[0] == 'W' && line[1] == ',') {
      static float win[600];
      char *p = line + 2;
      int n = 0;
      while (n < 600 && *p) {
        char *end = nullptr;
        win[n++] = strtof(p, &end);
        if (end == p) break;
        p = (*end == ',') ? end + 1 : end;
      }
      if (n != 600) {
        Serial.printf("E,%d\n", n);
      } else {
        float pm = 0.0f, pc = -1.0f;
        aiEvalWindow(win, &pm, &pc);
        Serial.printf("P,%.6f,%.6f\n", (double)pm, (double)pc);
      }
    }
  }
}

void setup() {
  // 160 MHz (not 240): about 30% less current and noticeably cooler, still fast enough for the AI;
  // the loop/AI budget is re-measured in the [DATA] line (jit=, ai us in telemetry).
  setCpuFrequencyMhz(CPU_FREQ_MHZ);
  Serial.setRxBufferSize(16384);  // HIL windows arrive as ~5 KB lines
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[BIO-BAND] ESP32-S3 Super Mini");
  Serial.printf("[BIO-BAND] cpu=%u MHz apb=%u MHz\n", (unsigned)getCpuFrequencyMhz(),
                (unsigned)(getApbFrequency() / 1000000));
  i2cBusRecover();

  pinMode(PIN_NET_AUX, INPUT);
  buzzerNetSet(false);
  pinMode(PIN_BUTTON, INPUT);  // read with the ADC (see controls.cpp)
  analogSetPinAttenuation(PIN_BUTTON, ADC_2_5db);
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
    calibrateGyro();
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

  aiSelfTest();
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
  serialCommands();
  if (hilActive) {  // host is streaming windows: keep the chip busy only with that
    delay(1);
    return;
  }
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

  {
    static uint32_t prevLoopMs = 0;
    if (prevLoopMs != 0) {
      const uint32_t dt = now - prevLoopMs;
      if (dt > loopMaxDtMs) loopMaxDtMs = dt;
    }
    prevLoopMs = now;
  }

  handleCommands(now);
  updateButton(now);

  float acc = 0.0f;
  bool motion = false;
  if (mpuReady) {
    sensors_event_t a, g, temp;
    if (replayActive) {
      ReplaySample s;
      if (replayPop(s)) replayLast = s;
      a.acceleration.x = replayLast.v[0];
      a.acceleration.y = replayLast.v[1];
      a.acceleration.z = replayLast.v[2];
      g.gyro.x = replayLast.v[3] + gyroBias[0];  // undo the bias subtraction below: replay data is already clean
      g.gyro.y = replayLast.v[4] + gyroBias[1];
      g.gyro.z = replayLast.v[5] + gyroBias[2];
    } else {
      mpu.getEvent(&a, &g, &temp);
    }
    acc = sqrtf(a.acceleration.x * a.acceleration.x +
                a.acceleration.y * a.acceleration.y +
                a.acceleration.z * a.acceleration.z);
    lastTotalAcc = acc;
    g.gyro.x -= gyroBias[0];
    g.gyro.y -= gyroBias[1];
    g.gyro.z -= gyroBias[2];
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

  const bool fastDisplay = state != SystemState::Idle;
  const uint32_t displayPeriod = (fastDisplay || buttonTestUntilMs > now) ? DISPLAY_PERIOD_MS
                                                                          : DISPLAY_IDLE_PERIOD_MS;
  if (now - lastDisplayMs >= displayPeriod) {
    renderDisplay(now);
    lastDisplayMs = now;
  }
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    publishTelemetry(now);
    lastTelemetryMs = now;
  }
  if (now - lastDebugMs >= 2000) {
    Serial.printf("[DATA] HR=%.0f/raw%.0f SpO2=%u/raw%u acc=%.2f batt=%.2fV %u%% motion=%d steps=%lu falls=%lu state=%s jit=%lums T=%.1fC\n",
                  bpm, rawBpm, (unsigned)spo2, (unsigned)rawSpo2, lastTotalAcc, batteryVoltage,
                  (unsigned)batteryPercent, motion ? 1 : 0, (unsigned long)stepCount,
                  (unsigned long)fallCount, stateName(state), (unsigned long)loopMaxDtMs,
                  (double)temperatureRead());
    loopMaxDtMsPublished = loopMaxDtMs;
    loopMaxDtMs = 0;
    lastDebugMs = now;
  }
  if (stepCount != lastSavedSteps && now - lastStepSaveMs >= STEP_SAVE_PERIOD_MS) {
    saveSteps();
  }
}
