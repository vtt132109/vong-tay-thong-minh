#include "sensors.h"
#include <math.h>

uint8_t lipoPercent(float v) {
  static const struct { float v; uint8_t p; } lut[] = {
      {4.20f, 100}, {4.10f, 90}, {4.00f, 80}, {3.90f, 70},
      {3.82f, 60},  {3.78f, 50}, {3.75f, 40}, {3.72f, 30},
      {3.68f, 20},  {3.60f, 10}, {3.40f, 5},  {3.00f, 0},
  };
  const int n = sizeof(lut) / sizeof(lut[0]);
  if (v >= lut[0].v) return 100;
  if (v <= lut[n - 1].v) return 0;
  for (int i = 0; i < n - 1; ++i) {
    if (v <= lut[i].v && v >= lut[i + 1].v) {
      float ratio = (v - lut[i + 1].v) / (lut[i].v - lut[i + 1].v);
      return (uint8_t)(lut[i + 1].p + ratio * (lut[i].p - lut[i + 1].p));
    }
  }
  return 0;
}

float readBatteryVoltage() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; ++i) {
    mv += analogReadMilliVolts(PIN_BATTERY_ADC);
  }
  return (mv / 8.0f) * 2.0f / 1000.0f;
}

static void pushWave(float irAC, float redAC) {
  for (int i = 1; i < WAVE_POINTS; ++i) {
    irWave[i - 1] = irWave[i];
    redWave[i - 1] = redWave[i];
  }
  irWave[WAVE_POINTS - 1] = irAC;
  redWave[WAVE_POINTS - 1] = redAC;

  float a = fabsf(irAC);
  float b = fabsf(redAC);
  irPeak = (a > irPeak) ? a : irPeak * 0.998f;
  redPeak = (b > redPeak) ? b : redPeak * 0.998f;
  if (irPeak < 1.0f) irPeak = 1.0f;
  if (redPeak < 1.0f) redPeak = 1.0f;
}

static uint32_t irPpgRing[PPG_BUFFER_SIZE];
static uint8_t ppgRingHead = 0;
static uint8_t ppgRingCount = 0;
static uint32_t lastMotionMs = 0;
static uint32_t lastOutputMs = 0;
static uint32_t lastPpgLogMs = 0;
static uint32_t lastIr = 0;
static float lastDc = 0.0f;
static uint16_t samplesThisSecond = 0;
static uint32_t lastRed = 0;
static uint16_t noFingerSamples = 200;
static uint8_t hrCount = 0;
static uint8_t spo2Count = 0;
static float hrHistory[3] = {0};
static float spo2History[3] = {0};

static float median3(const float *values, uint8_t count) {
  if (count == 0) return 0.0f;
  if (count == 1) return values[0];
  if (count == 2) return (values[0] + values[1]) * 0.5f;
  float a = values[0];
  float b = values[1];
  float c = values[2];
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

static void pushHistory(float *history, uint8_t &count, float value) {
  if (count < 3) {
    history[count++] = value;
  } else {
    history[0] = history[1];
    history[1] = history[2];
    history[2] = value;
  }
}

static void resetPpgAlgorithm() {  irDCRemover = DCRemover(0.95f);
  redDCRemover = DCRemover(0.95f);
  pulseFilter = FilterBuLp1();
  beatDetector = BeatDetector();
  spo2Calculator = SpO2Calculator();
  ppgRingHead = 0;
  ppgRingCount = 0;
  hrCount = 0;
  spo2Count = 0;
  rawBpm = 0.0f;
  rawSpo2 = 0;
  bpm = 0.0f;
  spo2 = 0;
  lastOutputMs = millis();
}

static float computePerfusionIndex() {
  if (ppgRingCount < PPG_BUFFER_SIZE) return 0.0f;
  uint32_t minIr = 0xFFFFFFFFu;
  uint32_t maxIr = 0;
  uint64_t sum = 0;
  for (int i = 0; i < PPG_BUFFER_SIZE; ++i) {
    uint32_t value = irPpgRing[i];
    if (value < minIr) minIr = value;
    if (value > maxIr) maxIr = value;
    sum += value;
  }
  float dc = (float)sum / (float)PPG_BUFFER_SIZE;
  if (dc < 1.0f) return 0.0f;
  return ((float)(maxIr - minIr) * 100.0f) / dc;
}

static uint8_t readMaxReg(uint8_t reg) {
  Wire.beginTransmission(0x57);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom((uint8_t)0x57, (uint8_t)1) != 1) return 0xFF;
  return Wire.read();
}

static void handleRawSample(uint16_t ir, uint16_t red) {
  float irAC = irDCRemover.step(ir);
  float redAC = redDCRemover.step(red);
  float dc = irDCRemover.getDCW();
  lastIr = ir;
  lastRed = red;
  lastDc = dc;

  if (ir < MAX30100_LEAD_OFF_IR) {
    if (noFingerSamples < 200) ++noFingerSamples;
  } else {
    noFingerSamples = 0;
  }
  bool finger = (noFingerSamples < 100);  // 100 samples at 100 Hz = 1 s

  if (!finger) {
    fingerDetected = false;
    pushWave(0.0f, 0.0f);
    bpm = 0.0f;
    spo2 = 0;
    rawBpm = 0.0f;
    rawSpo2 = 0;
    return;
  }

  if (!fingerDetected) {
    resetPpgAlgorithm();
    fingerDetected = true;
    return;
  }

  irPpgRing[ppgRingHead] = ir;
  ppgRingHead = (uint8_t)((ppgRingHead + 1) % PPG_BUFFER_SIZE);
  if (ppgRingCount < PPG_BUFFER_SIZE) ++ppgRingCount;

  float filtered = pulseFilter.step(-irAC);
  bool beat = beatDetector.addSample(filtered);
  if (beatDetector.getRate() > 0.0f) {
    spo2Calculator.update(irAC, redAC, beat);
  } else {
    spo2Calculator.reset();
  }
  pushWave(irAC, redAC);
}

void processMaxSamples(uint32_t now, bool motion) {
  if (!maxReady) {
    bpm = 0.0f;
    spo2 = 0;
    rawBpm = 0.0f;
    rawSpo2 = 0;
    fingerDetected = false;
    ppgMotion = false;
    return;
  }

  if (motion) lastMotionMs = now;
  bool motionBlocked = (lastMotionMs != 0 && (now - lastMotionMs) < PPG_MOTION_HOLD_MS);
  ppgMotion = motionBlocked;

  if (motionBlocked) {
    hrm.update();
    uint16_t ir = 0;
    uint16_t red = 0;
    while (hrm.getRawValues(&ir, &red)) {
      ++samplesThisSecond;
    }
    resetPpgAlgorithm();
    return;
  }

  hrm.update();
  uint16_t ir = 0;
  uint16_t red = 0;
  uint16_t readThisRound = 0;
  while (hrm.getRawValues(&ir, &red)) {
    ++samplesThisSecond;
    ++readThisRound;
    handleRawSample(ir, red);
  }

  uint8_t wr = readMaxReg(0x02);
  uint8_t rd = readMaxReg(0x04);
  uint8_t ovf = readMaxReg(0x03);
  if (readThisRound == 0 && wr == rd && ovf > 0) {
    // FIFO full: MAX30100lib treats wr==rd as empty and never drains it.
    Wire.beginTransmission(0x57);
    Wire.write(0x05);
    Wire.endTransmission(false);
    if (Wire.requestFrom((uint8_t)0x57, (uint8_t)64) == 64) {
      for (uint8_t i = 0; i < 16; ++i) {
        uint16_t sampleIr = (uint16_t)Wire.read() << 8;
        sampleIr |= Wire.read();
        uint16_t sampleRed = (uint16_t)Wire.read() << 8;
        sampleRed |= Wire.read();
        ++samplesThisSecond;
        handleRawSample(sampleIr, sampleRed);
      }
    }
    hrm.resetFifo();
  } else if (ovf > 0) {
    Wire.beginTransmission(0x57);
    Wire.write(0x03);
    Wire.write(0x00);
    Wire.endTransmission();
  }

  if (now - lastPpgLogMs >= 1000) {
    lastPpgLogMs = now;
    Serial.printf("[PPG] ir=%lu red=%lu dc=%.0f finger=%d pi=%.2f rate=%.1f spo2=%u n=%u\n",
                  (unsigned long)lastIr, (unsigned long)lastRed, lastDc * 0.05f,
                  fingerDetected ? 1 : 0, computePerfusionIndex(),
                  beatDetector.getRate(), (unsigned)spo2Calculator.getSpO2(),
                  (unsigned)samplesThisSecond);
    samplesThisSecond = 0;
  }

  if (!fingerDetected) {
    bpm = 0.0f;
    spo2 = 0;
    rawBpm = 0.0f;
    rawSpo2 = 0;
    return;
  }

  if (now - lastOutputMs >= 1000) {
    lastOutputMs = now;
    float pi = computePerfusionIndex();
    if (pi < PPG_MIN_PI || pi > PPG_MAX_PI) {
      bpm = 0.0f;
      spo2 = 0;
      rawBpm = 0.0f;
      rawSpo2 = 0;
      return;
    }

    float rate = beatDetector.getRate();
    uint8_t value = spo2Calculator.getSpO2();
    rawBpm = rate;
    rawSpo2 = value;

    if (rate >= PPG_HR_MIN && rate <= PPG_HR_MAX) {
      pushHistory(hrHistory, hrCount, rate);
      bpm = median3(hrHistory, hrCount);
    } else {
      bpm = 0.0f;
    }
    if (value >= PPG_SPO2_MIN && value <= PPG_SPO2_MAX) {
      pushHistory(spo2History, spo2Count, (float)value);
      spo2 = (uint8_t)(median3(spo2History, spo2Count) + 0.5f);
    } else {
      spo2 = 0;
    }
  }
}

void updatePedometer(uint32_t now, float acc) {
  if (acc > 13.0f && !stepHigh) {
    stepHigh = true;
    if (now - lastStepMs > 300) {
      ++stepCount;
      lastStepMs = now;
    }
  } else if (acc < 10.5f) {
    stepHigh = false;
  }
}
