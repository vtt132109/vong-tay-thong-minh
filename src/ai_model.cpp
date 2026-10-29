#include "ai_model.h"
#include "app_state.h"
#include <math.h>
#include <string.h>
#include <strings.h>

#ifndef ENABLE_EDGE_AI
#define ENABLE_EDGE_AI 0
#endif
#ifndef ENABLE_TINY_AI
#define ENABLE_TINY_AI 0
#endif

#if ENABLE_EDGE_AI && ENABLE_TINY_AI
#error "Enable only one AI backend: ENABLE_EDGE_AI or ENABLE_TINY_AI"
#endif

#if ENABLE_EDGE_AI

// The Edge Impulse project must be named "bioband" so the exported Arduino
// library provides this header. If you use another name, change this include.
#include <bioband_inferencing.h>

static_assert(EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME == 6,
              "Edge Impulse impulse must use 6 axes: ax, ay, az, gx, gy, gz");
static_assert(EI_CLASSIFIER_RAW_SAMPLE_COUNT > 25,
              "Edge Impulse window must be longer than the 25-sample stride");

static float aiBuffer[EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE];
static size_t aiWriteIndex = 0;
static constexpr size_t AI_STRIDE_SAMPLES = 25;  // 0.5 s at 50 Hz

static int raw_feature_get_data(size_t offset, size_t length, float *out_ptr) {
  memcpy(out_ptr, aiBuffer + offset, length * sizeof(float));
  return 0;
}

static void runAiClassifier() {
  signal_t signal;
  signal.total_length = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE;
  signal.get_data = &raw_feature_get_data;

  ei_impulse_result_t result = {0};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    strncpy(aiLabel, "error", sizeof(aiLabel) - 1);
    aiLabel[sizeof(aiLabel) - 1] = '\0';
    aiConfidence = 0.0f;
    aiFall = false;
    return;
  }

  const char *bestLabel = "n/a";
  float bestValue = 0.0f;
  for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; ++i) {
    if (result.classification[i].value > bestValue) {
      bestValue = result.classification[i].value;
      bestLabel = result.classification[i].label;
    }
  }

  strncpy(aiLabel, bestLabel, sizeof(aiLabel) - 1);
  aiLabel[sizeof(aiLabel) - 1] = '\0';
  aiConfidence = bestValue;
  aiFall = (strcasecmp(bestLabel, "fall") == 0);
}

void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz) {
  aiBuffer[aiWriteIndex++] = ax;
  aiBuffer[aiWriteIndex++] = ay;
  aiBuffer[aiWriteIndex++] = az;
  aiBuffer[aiWriteIndex++] = gx;
  aiBuffer[aiWriteIndex++] = gy;
  aiBuffer[aiWriteIndex++] = gz;

  if (aiWriteIndex < EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE) return;

  runAiClassifier();

  const size_t shift = AI_STRIDE_SAMPLES * 6;
  if (shift < EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE) {
    memmove(aiBuffer, aiBuffer + shift,
            (EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE - shift) * sizeof(float));
    aiWriteIndex = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE - shift;
  } else {
    aiWriteIndex = 0;
  }
}

#elif ENABLE_TINY_AI

// HIFD TinyML backend. Model contract (tools/hifd_features.md):
//   100 samples x 6 channels [ax, ay, az, gx, gy, gz] at 50 Hz, 0.5 s stride.
//   ax/ay/az are gravity-removed LINEAR acceleration in m/s^2; gx/gy/gz in rad/s.
// The MPU6050 reports raw acceleration that still contains gravity, so gravity is
// estimated with a low-pass filter and subtracted before buffering.
#include "tiny_fall_model.h"

static constexpr size_t TINY_WINDOW_SAMPLES = 100;
static constexpr size_t TINY_AXES = 6;
static constexpr size_t TINY_STRIDE_SAMPLES = 25;      // 0.5 s at 50 Hz
static constexpr size_t TINY_MAG_TAIL = 25;            // last 0.5 s of magnitude
static constexpr float TINY_GRAVITY_ALPHA = 0.98f;     // ~1 s time constant at 50 Hz
static constexpr uint32_t TINY_LOG_MIN_MS = 400;       // <= 1 log per inference

// Only [ax, ay, az, gx, gy, gz] per sample is stored; features are recomputed
// from this single buffer, so steady-state RAM is fixed (~2.4 kB).
static float tinyWindow[TINY_WINDOW_SAMPLES * TINY_AXES];
static size_t tinyWriteIndex = 0;  // samples written so far (0..100)
static bool tinyGravityInit = false;
static float tinyGravity[3] = {0.0f, 0.0f, 0.0f};
static uint32_t tinyLastLogMs = 0;

static inline float tinyFinite(float v) { return isfinite(v) ? v : 0.0f; }

// 42 features in the exact order of tools/hifd_features.md:
// per axis (ax,ay,az,gx,gy,gz): mean, population std, min, max, rms, mean_abs,
// then magnitude: mean, population std, min, max, peak_abs, var of last 25.
static void tinyExtractFeatures(const float *win, float *feat) {
  for (size_t axis = 0; axis < TINY_AXES; ++axis) {
    const size_t base = axis * TINY_AXES;
    float sum = 0.0f;
    float sumSq = 0.0f;
    float sumAbs = 0.0f;
    float vMin = win[base];
    float vMax = win[base];
    for (size_t i = 0; i < TINY_WINDOW_SAMPLES; ++i) {
      const float v = win[i * TINY_AXES + axis];
      sum += v;
      sumSq += v * v;
      sumAbs += fabsf(v);
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
    const float mean = sum / (float)TINY_WINDOW_SAMPLES;
    // Two-pass population variance (ddof=0) for numerical parity with numpy.
    float devSq = 0.0f;
    for (size_t i = 0; i < TINY_WINDOW_SAMPLES; ++i) {
      const float d = win[i * TINY_AXES + axis] - mean;
      devSq += d * d;
    }
    const float var = devSq / (float)TINY_WINDOW_SAMPLES;

    feat[axis * 6 + 0] = mean;
    feat[axis * 6 + 1] = sqrtf(var > 0.0f ? var : 0.0f);
    feat[axis * 6 + 2] = vMin;
    feat[axis * 6 + 3] = vMax;
    feat[axis * 6 + 4] = sqrtf(sumSq / (float)TINY_WINDOW_SAMPLES);
    feat[axis * 6 + 5] = sumAbs / (float)TINY_WINDOW_SAMPLES;
  }

  // Magnitude uses the three LINEAR acceleration axes only.
  float mag[TINY_WINDOW_SAMPLES];
  float magSum = 0.0f;
  float magMin = 0.0f;
  float magMax = 0.0f;
  float magPeakAbs = 0.0f;
  for (size_t i = 0; i < TINY_WINDOW_SAMPLES; ++i) {
    const float *s = win + i * TINY_AXES;
    const float m = sqrtf(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]);
    mag[i] = m;
    magSum += m;
    if (i == 0 || m < magMin) magMin = m;
    if (i == 0 || m > magMax) magMax = m;
    const float a = fabsf(m);
    if (a > magPeakAbs) magPeakAbs = a;
  }
  const float magMean = magSum / (float)TINY_WINDOW_SAMPLES;
  float magDevSq = 0.0f;
  for (size_t i = 0; i < TINY_WINDOW_SAMPLES; ++i) {
    const float d = mag[i] - magMean;
    magDevSq += d * d;
  }
  const float magVar = magDevSq / (float)TINY_WINDOW_SAMPLES;

  float tailSum = 0.0f;
  for (size_t i = TINY_WINDOW_SAMPLES - TINY_MAG_TAIL; i < TINY_WINDOW_SAMPLES; ++i) {
    tailSum += mag[i];
  }
  const float tailMean = tailSum / (float)TINY_MAG_TAIL;
  float tailDevSq = 0.0f;
  for (size_t i = TINY_WINDOW_SAMPLES - TINY_MAG_TAIL; i < TINY_WINDOW_SAMPLES; ++i) {
    const float d = mag[i] - tailMean;
    tailDevSq += d * d;
  }
  const float tailVar = tailDevSq / (float)TINY_MAG_TAIL;

  const size_t mbase = TINY_AXES * 6;
  feat[mbase + 0] = magMean;
  feat[mbase + 1] = sqrtf(magVar > 0.0f ? magVar : 0.0f);
  feat[mbase + 2] = magMin;
  feat[mbase + 3] = magMax;
  feat[mbase + 4] = magPeakAbs;
  feat[mbase + 5] = tailVar > 0.0f ? tailVar : 0.0f;

  for (size_t i = 0; i < TINY_AI_FEATURE_COUNT; ++i) {
    feat[i] = tinyFinite(feat[i]);
  }
}

static float tinySigmoid(float x) {
  if (x >= 0.0f) {
    const float e = expf(-x);
    return 1.0f / (1.0f + e);
  }
  const float e = expf(x);
  return e / (1.0f + e);
}

// z -> tanh(W1 z + b1) -> W2 hidden + b2 -> sigmoid
static float tinyInfer(const float *feat) {
  float z[TINY_AI_FEATURE_COUNT];
  for (size_t i = 0; i < TINY_AI_FEATURE_COUNT; ++i) {
    z[i] = (feat[i] - TINY_AI_MEAN[i]) / TINY_AI_SCALE[i];
  }
  float hidden[TINY_AI_HIDDEN];
  for (size_t j = 0; j < TINY_AI_HIDDEN; ++j) {
    float acc = TINY_AI_B1[j];
    for (size_t i = 0; i < TINY_AI_FEATURE_COUNT; ++i) {
      acc += TINY_AI_W1[j][i] * z[i];
    }
    hidden[j] = tanhf(acc);
  }
  float out = TINY_AI_B2;
  for (size_t j = 0; j < TINY_AI_HIDDEN; ++j) {
    out += TINY_AI_W2[j] * hidden[j];
  }
  return tinySigmoid(out);
}

static void runTinyAi(uint32_t now) {
  float feat[TINY_AI_FEATURE_COUNT];
  tinyExtractFeatures(tinyWindow, feat);
  const float p = tinyInfer(feat);

  if (!isfinite(p)) {
    strncpy(aiLabel, "error", sizeof(aiLabel) - 1);
    aiLabel[sizeof(aiLabel) - 1] = '\0';
    aiConfidence = 0.0f;
    aiFall = false;
    return;
  }

  const bool fall = (p >= TINY_AI_THRESHOLD);
  strncpy(aiLabel, fall ? "fall" : "adl", sizeof(aiLabel) - 1);
  aiLabel[sizeof(aiLabel) - 1] = '\0';
  aiConfidence = (p >= 0.5f) ? p : (1.0f - p);  // max(p, 1-p)
  aiFall = fall;

  if (now - tinyLastLogMs >= TINY_LOG_MIN_MS) {
    tinyLastLogMs = now;
    Serial.printf("[TINY-AI] p=%.4f label=%s thr=%.2f\n", (double)p, aiLabel,
                  (double)TINY_AI_THRESHOLD);
  }
}

void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz) {
  // Low-pass gravity estimate in the sensor frame (complementary filter).
  if (!tinyGravityInit) {
    tinyGravity[0] = ax;
    tinyGravity[1] = ay;
    tinyGravity[2] = az;
    tinyGravityInit = true;
  } else {
    const float beta = 1.0f - TINY_GRAVITY_ALPHA;
    tinyGravity[0] += beta * (ax - tinyGravity[0]);
    tinyGravity[1] += beta * (ay - tinyGravity[1]);
    tinyGravity[2] += beta * (az - tinyGravity[2]);
  }

  float *dst = tinyWindow + tinyWriteIndex * TINY_AXES;
  dst[0] = ax - tinyGravity[0];
  dst[1] = ay - tinyGravity[1];
  dst[2] = az - tinyGravity[2];
  dst[3] = gx;  // Adafruit MPU6050 already reports rad/s
  dst[4] = gy;
  dst[5] = gz;
  ++tinyWriteIndex;

  if (tinyWriteIndex < TINY_WINDOW_SAMPLES) return;

  runTinyAi(millis());

  const size_t shift = TINY_STRIDE_SAMPLES * TINY_AXES;
  memmove(tinyWindow, tinyWindow + shift,
          (TINY_WINDOW_SAMPLES - TINY_STRIDE_SAMPLES) * TINY_AXES * sizeof(float));
  tinyWriteIndex = TINY_WINDOW_SAMPLES - TINY_STRIDE_SAMPLES;
}

#else

void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz) {
  (void)ax;
  (void)ay;
  (void)az;
  (void)gx;
  (void)gy;
  (void)gz;
}

#endif
