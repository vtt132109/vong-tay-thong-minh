#include "Dsp/PpgSignalProcessor.h"

PpgSignalProcessor::PpgSignalProcessor() {
  reset();
}

void PpgSignalProcessor::reset() {
  _heartRate = 0;
  _spo2 = 0.0f;
  _fingerDetected = false;
  _rawRed = 0;
  _rawIr = 0;
  _irDc = 0.0f;
  _redDc = 0.0f;
  _irAcSmooth = 0.0f;
  _redAcSmooth = 0.0f;
  _prevIrAcSmooth = 0.0f;
  _cycleIrMax = -99999.0f;
  _cycleIrMin = 99999.0f;
  _cycleRedMax = -99999.0f;
  _cycleRedMin = 99999.0f;
  _lastBeatMillis = 0;
  _isPulseRising = false;
  _beatIntervalIndex = 0;

  for (int k = 0; k < MEDIAN_WINDOW_SIZE; k++) {
    _beatIntervals[k] = 0;
  }

  _waveIndex = 0;
  for (int k = 0; k < PPG_WAVE_BUFFER_SIZE; k++) {
    _waveform[k] = 0;
  }
}

bool PpgSignalProcessor::isPulseBeating() const {
  return (_fingerDetected && (millis() - _lastBeatMillis < 200));
}

void PpgSignalProcessor::simulate(float ax_g, float ay_g) {
  int motionBonus = (abs(ax_g) + abs(ay_g)) > 0.4f ? 12 : 0;
  _heartRate = 72 + motionBonus + (int)(sin(millis() / 3000.0) * 4);
  _spo2 = 98.2f + (sin(millis() / 5000.0) * 0.5f);
  _fingerDetected = false;

  unsigned long now = millis();
  float phase = (now % 800) / 800.0f * 6.28318f;
  float simWave = sin(phase) * 8.0f - sin(phase * 2) * 3.0f;
  _waveform[_waveIndex] = (int8_t)constrain((int)simWave, -12, 12);
  _waveIndex = (_waveIndex + 1) % PPG_WAVE_BUFFER_SIZE;
}

void PpgSignalProcessor::processSample(uint32_t rawRedVal, uint32_t rawIrVal,
                                       float ax_g, float ay_g) {
  _rawRed = rawRedVal;
  _rawIr = rawIrVal;

  // Ngưỡng chạm cổ tay / ngón tay: IR > PPG_TOUCH_MIN_IR
  if (_rawIr > PPG_TOUCH_MIN_IR) {
    _fingerDetected = true;

    // Kiểm tra bão hòa ADC 18-bit
    if (_rawIr >= PPG_ADC_SATURATION_LIMIT || _rawRed >= PPG_ADC_SATURATION_LIMIT) {
      return; // Bão hòa quang hoặc ấn ngón tay quá mạnh
    }

    // 1. Tách thành phần tĩnh DC nền (High-Pass Baseline Tracker)
    if (_irDc == 0.0f) {
      _irDc = (float)_rawIr;
      _redDc = (float)_rawRed;
    }
    _irDc = (_irDc * PPG_DC_TRACK_ALPHA) + ((float)_rawIr * (1.0f - PPG_DC_TRACK_ALPHA));
    _redDc = (_redDc * PPG_DC_TRACK_ALPHA) + ((float)_rawRed * (1.0f - PPG_DC_TRACK_ALPHA));

    float rawIrAc = (float)_rawIr - _irDc;
    float rawRedAc = (float)_rawRed - _redDc;

    // 2. Bộ lọc thông thấp 2 tầng (Low-Pass Filter) triệt tiêu nhiễu cao tần
    _irAcSmooth = (_irAcSmooth * PPG_LPF_ALPHA) + (rawIrAc * (1.0f - PPG_LPF_ALPHA));
    _redAcSmooth = (_redAcSmooth * PPG_LPF_ALPHA) + (rawRedAc * (1.0f - PPG_LPF_ALPHA));

    // Theo dõi min-max trong chu kỳ nhịp đập
    if (_irAcSmooth > _cycleIrMax) _cycleIrMax = _irAcSmooth;
    if (_irAcSmooth < _cycleIrMin) _cycleIrMin = _irAcSmooth;
    if (_redAcSmooth > _cycleRedMax) _cycleRedMax = _redAcSmooth;
    if (_redAcSmooth < _cycleRedMin) _cycleRedMin = _redAcSmooth;

    // 3. Phát hiện đỉnh mạch đập (Adaptive Peak Detection)
    float ptp = _cycleIrMax - _cycleIrMin;

    // Cập nhật bộ đệm sóng đồ thị (Plethysmogram)
    float ptpSafe = (ptp > 15.0f) ? ptp : 40.0f;
    int waveVal = (int)((_irAcSmooth / ptpSafe) * 20.0f);
    _waveform[_waveIndex] = (int8_t)constrain(waveVal, -12, 12);
    _waveIndex = (_waveIndex + 1) % PPG_WAVE_BUFFER_SIZE;

    unsigned long now = millis();
    unsigned long timeSinceLastBeat = now - _lastBeatMillis;

    // Ngưỡng trơ sinh học thích ứng (Adaptive Refractory Window)
    int minRefractory = 520;
    if (_heartRate >= PPG_MIN_BPM && _heartRate <= PPG_MAX_BPM) {
      int currentPeriod = 60000 / _heartRate;
      minRefractory = (int)(currentPeriod * 0.70f);
      if (minRefractory < 500) minRefractory = 500;
      if (minRefractory > 750) minRefractory = 750;
    }

    // Xác nhận đỉnh Systolic Peak
    if (_isPulseRising && _irAcSmooth < _prevIrAcSmooth && ptp >= PPG_MIN_PEAK_PTP &&
        _prevIrAcSmooth > 0.0f && (_prevIrAcSmooth - _cycleIrMin) > (ptp * 0.60f)) {
      if (timeSinceLastBeat >= (unsigned long)minRefractory && timeSinceLastBeat <= 1600) {
        _beatIntervals[_beatIntervalIndex] = (int)timeSinceLastBeat;
        _beatIntervalIndex = (_beatIntervalIndex + 1) % MEDIAN_WINDOW_SIZE;

        // Bộ lọc trung vị (Median Filter) loại bỏ ngoại lai
        int sorted[MEDIAN_WINDOW_SIZE];
        int validCount = 0;
        for (int k = 0; k < MEDIAN_WINDOW_SIZE; k++) {
          if (_beatIntervals[k] >= 480 && _beatIntervals[k] <= 1600) {
            sorted[validCount++] = _beatIntervals[k];
          }
        }

        if (validCount > 0) {
          // Sắp xếp nổi bọt (Bubble Sort) trên mảng nhỏ 7 phần tử
          for (int a = 0; a < validCount - 1; a++) {
            for (int b = a + 1; b < validCount; b++) {
              if (sorted[a] > sorted[b]) {
                int tmp = sorted[a];
                sorted[a] = sorted[b];
                sorted[b] = tmp;
              }
            }
          }
          int medianInterval = sorted[validCount / 2];
          if (medianInterval > 0) {
            int calculatedBpm = 60000 / medianInterval;
            if (calculatedBpm >= PPG_MIN_BPM && calculatedBpm <= PPG_MAX_BPM) {
              if (_heartRate == 0) {
                _heartRate = calculatedBpm;
              } else {
                // Bộ giới hạn độ dốc biến thiên (Slew Rate Limiter)
                int diff = calculatedBpm - _heartRate;
                if (diff > PPG_MAX_SLEW_BPM) diff = PPG_MAX_SLEW_BPM;
                if (diff < -PPG_MAX_SLEW_BPM) diff = -PPG_MAX_SLEW_BPM;
                _heartRate += diff;
              }
            }
          }
        }

        // 4. Tính SpO2 chuẩn y tế theo tỷ lệ đỉnh-đáy (Ratio-of-Ratios)
        float irAmplitude = _cycleIrMax - _cycleIrMin;
        float redAmplitude = _cycleRedMax - _cycleRedMin;
        if (irAmplitude > 12.0f && _irDc > 4000.0f && _redDc > 4000.0f) {
          float acRedNorm = redAmplitude / _redDc;
          float acIrNorm = irAmplitude / _irDc;
          if (acIrNorm > 0.0001f) {
            float R = acRedNorm / acIrNorm;
            float calcSpo2 = 111.5f - (16.0f * R);
            calcSpo2 = constrain(calcSpo2, 94.0f, 99.5f);
            if (_spo2 <= 1.0f) {
              _spo2 = calcSpo2;
            } else {
              _spo2 = (_spo2 * 0.85f) + (calcSpo2 * 0.15f);
            }
          }
        }

        // Đặt lại đỉnh-đáy cho chu kỳ nhịp mới
        _cycleIrMax = _irAcSmooth;
        _cycleIrMin = _irAcSmooth;
        _cycleRedMax = _redAcSmooth;
        _cycleRedMin = _redAcSmooth;
        _lastBeatMillis = now;
      } else if (timeSinceLastBeat > 1600) {
        _lastBeatMillis = now;
      }
      _isPulseRising = false;
    } else if (_irAcSmooth > _prevIrAcSmooth && ptp >= PPG_MIN_RISING_PTP &&
               (_irAcSmooth - _cycleIrMin) > (ptp * 0.25f)) {
      _isPulseRising = true;
    }

    _prevIrAcSmooth = _irAcSmooth;
  } else {
    // Không chạm tay: Reset trạng thái hoàn toàn
    _fingerDetected = false;
    _isPulseRising = false;
    _irDc = 0.0f;
    _redDc = 0.0f;
    _irAcSmooth = 0.0f;
    _redAcSmooth = 0.0f;
    _prevIrAcSmooth = 0.0f;
    _cycleIrMax = -99999.0f;
    _cycleIrMin = 99999.0f;
    _cycleRedMax = -99999.0f;
    _cycleRedMin = 99999.0f;
    for (int k = 0; k < MEDIAN_WINDOW_SIZE; k++) {
      _beatIntervals[k] = 0;
    }
    _beatIntervalIndex = 0;
    _waveform[_waveIndex] = 0;
    _waveIndex = (_waveIndex + 1) % PPG_WAVE_BUFFER_SIZE;
  }
}
