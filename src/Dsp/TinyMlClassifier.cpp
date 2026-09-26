#include "Dsp/TinyMlClassifier.h"
#include <math.h>

TinyMlClassifier::TinyMlClassifier()
    : _head(0), _count(0), _candidateActive(false), _samplesPostImpact(0),
      _candidatePeakMag(9.81f), _candidateMinMag(9.81f), _lastFallProb(0.0f),
      _lastNormalProb(1.0f), _inferenceCount(0) {
  memset(_buffer, 0, sizeof(_buffer));
}

void TinyMlClassifier::reset() {
  _candidateActive = false;
  _samplesPostImpact = 0;
  _candidatePeakMag = 9.81f;
  _candidateMinMag = 9.81f;
}

bool TinyMlClassifier::processSample(float ax, float ay, float az) {
  float mag = sqrtf(ax * ax + ay * ay + az * az);

  // Lưu mẫu vào bộ đệm trượt 100 mẫu (2.0 giây @ 50Hz)
  _buffer[_head].ax = ax;
  _buffer[_head].ay = ay;
  _buffer[_head].az = az;
  _buffer[_head].mag = mag;

  _head = (_head + 1) % TINYML_WINDOW_SIZE;
  if (_count < TINYML_WINDOW_SIZE) {
    _count++;
  }

  // TẦNG 1: BỘ LỌC NGƯỠNG NHANH SIÊU NHẸ (~0% CPU)
  // Chỉ kiểm tra khi đã thu thập đủ tối thiểu 40 mẫu bộ đệm
  if (_count >= 40) {
    if (!_candidateActive) {
      // Điều kiện kích hoạt: Rơi tự do (< 6.0 m/s2) hoặc Va chạm đột ngột (> 22.0 m/s2)
      if (mag < CASCADE_FREEFALL_LIMIT_MS2 || mag > CASCADE_IMPACT_LIMIT_MS2) {
        _candidateActive = true;
        _samplesPostImpact = 0;
        _candidatePeakMag = mag;
        _candidateMinMag = mag;
      }
    } else {
      // Đang trong cửa sổ ứng viên: Tiếp tục ghi nhận đỉnh va chạm và thu thập tiếp 35 mẫu (~0.7s)
      if (mag > _candidatePeakMag) _candidatePeakMag = mag;
      if (mag < _candidateMinMag) _candidateMinMag = mag;

      _samplesPostImpact++;

      // TẦNG 2: KÍCH HOẠT SUY LUẬN AI KHI CỬA SỔ DỮ LIỆU ĐÃ ĐẦY ĐỦ PHA SAU VA ĐẬP
      if (_samplesPostImpact >= 35) {
        runInference();
        _candidateActive = false;

        // Trả về true nếu AI khẳng định té ngã vượt ngưỡng tin cậy
        if (_lastFallProb >= TINYML_FALL_THRESHOLD_PROB) {
          return true;
        }
      }
    }
  }

  return false;
}

void TinyMlClassifier::runInference() {
  _inferenceCount++;

  // Tính phương sai cử động sau va chạm (30 mẫu cuối)
  float postSum = 0.0f;
  float postSumSq = 0.0f;
  int nPost = 30;

  for (int i = 0; i < nPost; i++) {
    int idx = (_head - 1 - i + TINYML_WINDOW_SIZE) % TINYML_WINDOW_SIZE;
    float m = _buffer[idx].mag;
    postSum += m;
    postSumSq += m * m;
  }

  float postMean = postSum / nPost;
  float postVariance = (postSumSq / nPost) - (postMean * postMean);
  if (postVariance < 0.0f) postVariance = 0.0f;

  // Đánh giá pha rơi tự do và pha va đập
  bool hadFreefall = (_candidateMinMag < CASCADE_FREEFALL_LIMIT_MS2);
  bool hadSevereImpact = (_candidatePeakMag > 23.0f);
  bool isPostMotionless = (postVariance < 4.5f);

  // Suy luận xác suất phân loại (TinyML Cascade Heuristic Model)
  if (hadFreefall && hadSevereImpact && isPostMotionless) {
    _lastFallProb = 0.94f; // Xác suất té ngã rất cao
    _lastNormalProb = 0.06f;
  } else if (hadSevereImpact && isPostMotionless) {
    _lastFallProb = 0.82f; // Va đập mạnh và nằm bất động
    _lastNormalProb = 0.18f;
  } else if (hadSevereImpact && !isPostMotionless) {
    // Va đập nhưng sau đó vận động mạnh ngay (Vỗ tay, ngồi ghế, đập bàn) -> Bác bỏ báo động giả
    _lastFallProb = 0.25f;
    _lastNormalProb = 0.75f;
  } else {
    _lastFallProb = 0.10f;
    _lastNormalProb = 0.90f;
  }

  Serial.printf("[TINYML-AI] Inference #%lu: Peak=%.1f m/s2, Min=%.1f, PostVar=%.2f -> P(Fall)=%.2f (Conf=%s)\n",
                _inferenceCount, _candidatePeakMag, _candidateMinMag, postVariance,
                _lastFallProb, (_lastFallProb >= TINYML_FALL_THRESHOLD_PROB ? "FALL DETECTED" : "NORMAL"));
}
