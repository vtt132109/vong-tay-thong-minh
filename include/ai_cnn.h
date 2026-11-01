#pragma once

#ifndef ENABLE_CNN_AI
#define ENABLE_CNN_AI 0
#endif

// Probability of "fall" from the int8 1D-CNN for one 100x6 window (see src/ai_cnn.cpp).
#if ENABLE_CNN_AI
float cnnInfer(const float *win);
float cnnEnsembleThreshold();  // decision threshold of mean(MLP, CNN)
#endif
