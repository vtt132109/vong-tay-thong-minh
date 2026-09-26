#ifndef TINYML_CLASSIFIER_H
#define TINYML_CLASSIFIER_H

#include <Arduino.h>
#include "Config.h"

// Cấu trúc mẫu cảm biến gia tốc 3 trục
struct MotionSample {
  float ax;
  float ay;
  float az;
  float mag;
};

class TinyMlClassifier {
public:
  TinyMlClassifier();

  // Nhận mẫu 50Hz (Core 0), cập nhật bộ đệm trượt 100 mẫu (2 giây)
  // Trả về true nếu phát hiện té ngã đã được AI xác nhận
  bool processSample(float ax, float ay, float az);

  // Trạng thái & kết quả suy luận
  bool isCandidateActive() const { return _candidateActive; }
  float getFallProbability() const { return _lastFallProb; }
  float getNormalProbability() const { return _lastNormalProb; }
  unsigned long getInferenceCount() const { return _inferenceCount; }
  void reset();

private:
  MotionSample _buffer[TINYML_WINDOW_SIZE];
  int _head;
  int _count;

  // Máy trạng thái 2 tầng
  bool _candidateActive;
  int _samplesPostImpact;
  float _candidatePeakMag;
  float _candidateMinMag;

  // Thống kê kết quả suy luận
  float _lastFallProb;
  float _lastNormalProb;
  unsigned long _inferenceCount;

  // Tầng 2: Suy luận phân loại đặc trưng động học
  void runInference();
};

#endif // TINYML_CLASSIFIER_H
