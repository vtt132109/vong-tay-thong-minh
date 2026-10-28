#include <Arduino.h>
#include <Wire.h>
#include <MAX30100.h>
#include <MAX30100_BeatDetector.h>
#include <MAX30100_Filters.h>

// Minimal heart-rate-only diagnostic: no OLED, MPU, WiFi, FSM, buzzer.
// MAX30100 on shared I2C SDA=GPIO8, SCL=GPIO9 at 100 kHz.

MAX30100 hrm;
BeatDetector beatDetector;
DCRemover irDCRemover(0.95f);
FilterBuLp1 pulseFilter;

static uint32_t lastPrintMs = 0;
static uint32_t beats = 0;
static uint16_t lastIr = 0;
static uint16_t lastRed = 0;
static float lastDc = 0.0f;

static void i2cScan() {
  Serial.println("[I2C] scan 100 kHz");
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[I2C] found 0x%02X\n", address);
    }
  }
}

static uint8_t readPartId() {
  Wire.beginTransmission(0x57);
  Wire.write(0xFF);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom(0x57, 1) != 1) return 0;
  return Wire.read();
}

static uint8_t readReg(uint8_t reg) {
  Wire.beginTransmission(0x57);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom(0x57, 1) != 1) return 0;
  return Wire.read();
}

static void dumpRegs() {
  Serial.printf("[MAX] PART=0x%02X REV=0x%02X MODE=0x%02X SPO2=0x%02X LED=0x%02X\n",
                readReg(0xFF), readReg(0xFE), readReg(0x06), readReg(0x07),
                readReg(0x09));
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("[HR-ONLY] MAX30100 diagnostic");

  Wire.begin(8, 9);
  Wire.setClock(100000);
  i2cScan();
  Serial.printf("[MAX] partID before begin = 0x%02X\n", readPartId());

  if (!hrm.begin()) {
    Serial.printf("[MAX] begin failed, partID=0x%02X\n", readPartId());
    while (1) {
      delay(1000);
    }
  }

  hrm.setMode(MAX30100_MODE_SPO2_HR);
  hrm.setLedsCurrent(MAX30100_LED_CURR_50MA, MAX30100_LED_CURR_27_1MA);
  Wire.setClock(100000);
  dumpRegs();
  Serial.println("[MAX] ready; place finger on the sensor window and hold still");
}

void loop() {
  hrm.update();

  uint16_t ir = 0;
  uint16_t red = 0;
  while (hrm.getRawValues(&ir, &red)) {
    float irAC = irDCRemover.step(ir);
    float filtered = pulseFilter.step(-irAC);
    bool beat = beatDetector.addSample(filtered);
    lastIr = ir;
    lastRed = red;
    lastDc = irDCRemover.getDCW();
    if (beat) {
      ++beats;
      Serial.printf("[BEAT] #%lu  ir=%u  dc=%.0f\n", (unsigned long)beats, ir, lastDc);
    }
  }

  if (millis() - lastPrintMs >= 1000) {
    lastPrintMs = millis();
    Serial.printf("[HR] ir=%u red=%u dc=%.0f finger=%d bpm=%.1f beats=%lu\n",
                  lastIr, lastRed, lastDc,
                  (lastDc >= 5000.0f) ? 1 : 0,
                  beatDetector.getRate(), (unsigned long)beats);
  }

  delay(5);
}
