#ifndef PPG_SIGNAL_PROCESSOR_H
#define PPG_SIGNAL_PROCESSOR_H

#include <Arduino.h>
#include "Config.h"

class PpgSignalProcessor {
public:
  PpgSignalProcessor();

  // Xử lý mẫu quang phổ thô từ MAX30102
  void processSample(uint32_t rawRedVal, uint32_t rawIrVal, float ax_g, float ay_g);

  // Reset toàn bộ bộ lọc về trạng thái ban đầu
  void reset();

  // Lấy kết quả sau lọc (trả về 0 khi không chạm da)
  int getHeartRate() const { return _fingerDetected ? _heartRate : 0; }
  float getSpO2() const { return _fingerDetected ? _spo2 : 0.0f; }
  bool isFingerDetected() const { return _fingerDetected; }
  uint32_t getRawRed() const { return _rawRed; }
  uint32_t getRawIr() const { return _rawIr; }
  float getIrAcSmooth() const { return _irAcSmooth; }
  bool isPulseBeating() const;
  const int8_t *getWaveform() const { return _waveform; }

  // Mô phỏng khi không có phần cứng
  void simulate(float ax_g, float ay_g);

private:
  int _heartRate;
  float _spo2;
  bool _fingerDetected;

  uint32_t _rawRed, _rawIr;
  float _irDc, _redDc;
  float _irAcSmooth, _redAcSmooth;
  float _prevIrAcSmooth;
  float _cycleIrMax, _cycleIrMin;
  float _cycleRedMax, _cycleRedMin;
  unsigned long _lastBeatMillis;
  bool _isPulseRising;

  int _beatIntervals[MEDIAN_WINDOW_SIZE];
  int _beatIntervalIndex;

  // Đồ thị dạng sóng PPG Plethysmogram
  int8_t _waveform[PPG_WAVE_BUFFER_SIZE];
  int _waveIndex;
};

#endif // PPG_SIGNAL_PROCESSOR_H
