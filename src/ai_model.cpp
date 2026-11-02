#include "ai_model.h"
#include "ai_cnn.h"
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
    aiProbability = 0.0f;
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
  aiProbability = bestValue;
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
static float tinyProbRing[12] = {0};  // 6 s of ensemble probabilities (one per 0.5 s window)
static uint8_t tinyProbHead = 0;
static uint8_t tinyFireHistory = 0;  // last AI_DEBOUNCE_N window decisions, bit0 = newest

static inline float tinyFinite(float v) { return isfinite(v) ? v : 0.0f; }

// 42 features in the exact order of tools/hifd_features.md:
// per axis (ax,ay,az,gx,gy,gz): mean, population std, min, max, rms, mean_abs,
// then magnitude: mean, population std, min, max, peak_abs, var of last 25.
static void tinyExtractFeatures(const float *win, float *feat) {
  for (size_t axis = 0; axis < TINY_AXES; ++axis) {
    float sum = 0.0f;
    float sumSq = 0.0f;
    float sumAbs = 0.0f;
    float vMin = win[axis];
    float vMax = win[axis];
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
  const uint32_t t0 = micros();
  tinyExtractFeatures(tinyWindow, feat);
  const float pMlp = tinyInfer(feat);
  aiInferenceUs = micros() - t0;
  ++aiInferenceCount;
  aiWindowPeak = feat[TINY_AXES * 6 + 4];
  aiProbMlp = pMlp;

  float p = pMlp;
  float thr = TINY_AI_THRESHOLD;
#if ENABLE_CNN_AI
  const uint32_t t1 = micros();
  const float pCnn = cnnInfer(tinyWindow);
  aiCnnUs = micros() - t1;
  aiProbCnn = pCnn;
  // Ensemble = mean of the two probabilities (tools/ai_lab/run_fusion.py chose it).
  p = isfinite(pCnn) ? 0.5f * (pMlp + pCnn) : pMlp;
  thr = cnnEnsembleThreshold();
#endif
  aiThreshold = thr;
  tinyProbRing[tinyProbHead] = isfinite(p) ? p : 0.0f;
  tinyProbHead = (uint8_t)((tinyProbHead + 1) % 12);
  {
    float m = 0.0f;
    for (uint8_t i = 0; i < 12; ++i) if (tinyProbRing[i] > m) m = tinyProbRing[i];
    aiMax6s = m;
  }

  if (!isfinite(p)) {
    strncpy(aiLabel, "error", sizeof(aiLabel) - 1);
    aiLabel[sizeof(aiLabel) - 1] = '\0';
    aiConfidence = 0.0f;
    aiProbability = 0.0f;
    aiFall = false;
    return;
  }

  // k-of-n debounce over consecutive 0.5 s windows: an isolated spike (clap, door slam)
  // is one window; a real fall keeps the impact inside several overlapping windows.
  const bool fire = (p >= thr);
  tinyFireHistory = (uint8_t)(((tinyFireHistory << 1) | (fire ? 1 : 0)) & ((1u << AI_DEBOUNCE_N) - 1u));
  const bool fall = __builtin_popcount(tinyFireHistory) >= AI_DEBOUNCE_K;
  strncpy(aiLabel, fall ? "fall" : "adl", sizeof(aiLabel) - 1);
  aiLabel[sizeof(aiLabel) - 1] = '\0';
  aiConfidence = (p >= 0.5f) ? p : (1.0f - p);  // max(p, 1-p)
  aiProbability = p;
  aiFall = fall;
  aiWindowMs = now;  // freshness latch for FSM path A' (single-model trigger)

  if (now - tinyLastLogMs >= TINY_LOG_MIN_MS && (fire || p > 0.2f || now - tinyLastLogMs >= 5000)) {
    tinyLastLogMs = now;
    Serial.printf("[TINY-AI] p=%.4f (mlp %.3f cnn %.3f) thr=%.2f label=%s us=%lu/%lu\n", (double)p,
                  (double)aiProbMlp, (double)aiProbCnn, (double)thr, aiLabel,
                  (unsigned long)aiInferenceUs, (unsigned long)aiCnnUs);
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

  static uint32_t tinySamplesSeen = 0;
  ++tinySamplesSeen;
  aiWindowFill = tinySamplesSeen >= TINY_WINDOW_SAMPLES
                     ? 100
                     : (uint8_t)((tinySamplesSeen * 100) / TINY_WINDOW_SAMPLES);

  if (tinyWriteIndex < TINY_WINDOW_SAMPLES) return;

  runTinyAi(millis());

  const size_t shift = TINY_STRIDE_SAMPLES * TINY_AXES;
  memmove(tinyWindow, tinyWindow + shift,
          (TINY_WINDOW_SAMPLES - TINY_STRIDE_SAMPLES) * TINY_AXES * sizeof(float));
  tinyWriteIndex = TINY_WINDOW_SAMPLES - TINY_STRIDE_SAMPLES;
}


// Boot-time self-test: re-computes the fixture windows from tools/ai_lab/export_final.py and
// compares with the numpy reference. Catches feature/quantisation/layout mismatches on the
// actual chip (PLAN.md A8).
#include "selftest_vectors.h"

bool aiEvalWindow(const float *win, float *pMlp, float *pCnn) {
  float feat[TINY_AI_FEATURE_COUNT];
  tinyExtractFeatures(win, feat);
  *pMlp = tinyInfer(feat);
#if ENABLE_CNN_AI
  *pCnn = cnnInfer(win);
#else
  *pCnn = -1.0f;
#endif
  return true;
}

bool aiSelfTest() {
  bool ok = true;
  float worstMlp = 0.0f, worstCnn = 0.0f;
  for (int i = 0; i < SELFTEST_N; ++i) {
    float feat[TINY_AI_FEATURE_COUNT];
    tinyExtractFeatures(SELFTEST_WIN[i], feat);
    const float pm = tinyInfer(feat);
    const float dm = fabsf(pm - SELFTEST_P_MLP[i]);
    if (dm > worstMlp) worstMlp = dm;
    float dc = 0.0f, pc = -1.0f;
#if ENABLE_CNN_AI
    pc = cnnInfer(SELFTEST_WIN[i]);
    dc = fabsf(pc - SELFTEST_P_CNN[i]);
    if (dc > worstCnn) worstCnn = dc;
#endif
    Serial.printf("[SELFTEST] %-12s mlp %.4f (ref %.4f)  cnn %.4f (ref %.4f)\n", SELFTEST_NAME[i],
                  (double)pm, (double)SELFTEST_P_MLP[i], (double)pc, (double)SELFTEST_P_CNN[i]);
  }
  ok = worstMlp < 0.02f && worstCnn < 0.03f;
  Serial.printf("[SELFTEST] %s (max |dp| mlp %.4f cnn %.4f)\n", ok ? "PASS" : "FAIL",
                (double)worstMlp, (double)worstCnn);
  aiSelfTestResult = ok ? 1 : 2;
  return ok;
}

#else

bool aiSelfTest() { return true; }
bool aiEvalWindow(const float *, float *pMlp, float *pCnn) { *pMlp = 0.0f; *pCnn = -1.0f; return false; }

void aiPushSample(float ax, float ay, float az, float gx, float gy, float gz) {
  (void)ax;
  (void)ay;
  (void)az;
  (void)gx;
  (void)gy;
  (void)gz;
}

#endif
