#include "ai_model.h"
#include "app_state.h"
#include "board_config.h"
#include <string.h>
#include <strings.h>

#ifndef ENABLE_EDGE_AI
#define ENABLE_EDGE_AI 0
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
