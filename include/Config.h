#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// =========================================================================
// 1. CẤU HÌNH PHẦN CỨNG & CHÂN GPIO ESP32-S3
// =========================================================================
#ifndef I2C_SDA_PIN
#define I2C_SDA_PIN SDA // Mặc định GPIO 8 trên ESP32-S3
#endif

#ifndef I2C_SCL_PIN
#define I2C_SCL_PIN SCL // Mặc định GPIO 9 trên ESP32-S3
#endif

#define I2C_BUS_SPEED 400000 // 400kHz Fast Mode
#define I2C_TIMEOUT_MS 50    // Timeout 50ms chống treo bus

// Địa chỉ I2C phần cứng
#define OLED_I2C_ADDR 0x3C
#define MPU6050_I2C_ADDR 0x68
#define MAX30102_I2C_ADDR 0x57

// Chân điều khiển cơ cấu chấp hành
#define PIN_VIBRATE 2 // Chân điều khiển motor rung (GPIO 2)

// =========================================================================
// 2. CHU KỲ & ĐỊNH THÌ (TIMING INTERVALS - ms)
// =========================================================================
#define TELEMETRY_INTERVAL_MS 1500  // Gửi telemetry mỗi 1.5 giây
#define OLED_REFRESH_INTERVAL_MS 150 // Cập nhật màn hình ~6.6 FPS
#define MPU_SAMPLE_INTERVAL_MS 20   // Lấy mẫu MPU6050 ở 50Hz (mỗi 20ms)
#define MAX_SAMPLE_INTERVAL_MS 25   // Lấy mẫu MAX30102 ở 40Hz (mỗi 25ms)
#define PPG_PRINT_INTERVAL_MS 150   // In log PPG định kỳ lên Serial
#define WIFI_RETRY_INTERVAL_MS 10000 // Thử kết nối lại WiFi mỗi 10 giây
#define MQTT_RETRY_INTERVAL_MS 5000  // Thử kết nối lại MQTT mỗi 5 giây
#define SENSOR_RETRY_INTERVAL_MS 5000 // Thử kết nối lại cảm biến mỗi 5 giây

// =========================================================================
// 3. CẤU HÌNH MQTT TOPICS
// =========================================================================
#define TOPIC_BASE "smartband_s3/dev01"
#define TOPIC_TELEMETRY "smartband_s3/dev01/telemetry"
#define TOPIC_SCREEN_POWER_SET "smartband_s3/dev01/screen_power/set"
#define TOPIC_SCREEN_POWER_STATUS "smartband_s3/dev01/screen_power/status"
#define TOPIC_SCREEN_PAGE_SET "smartband_s3/dev01/screen_page/set"
#define TOPIC_SCREEN_PAGE_STATUS "smartband_s3/dev01/screen_page/status"
#define TOPIC_SCREEN_MSG_SET "smartband_s3/dev01/screen_msg/set"
#define TOPIC_VIBRATE_SET "smartband_s3/dev01/vibrate/set"
#define TOPIC_RESET_STEPS_SET "smartband_s3/dev01/reset_steps/set"
#define TOPIC_FALL_ALERT "smartband_s3/dev01/fall/alert"
#define TOPIC_FALL_DISMISS "smartband_s3/dev01/fall/dismiss"

// =========================================================================
// 4. HẰNG SỐ DSP & BỘ LỌC SINH HIỆU PPG (MAX30102)
// =========================================================================
#define PPG_TOUCH_MIN_IR 8000           // Ngưỡng phát hiện tiếp xúc da/ngón tay
#define PPG_ADC_SATURATION_LIMIT 260000 // Trần bão hòa ADC 18-bit (262143)
#define PPG_DC_TRACK_ALPHA 0.96f        // Hệ số lọc thông cao tách thành phần tĩnh DC
#define PPG_LPF_ALPHA 0.60f             // Hệ số lọc thông thấp chống rung cơ học
#define PPG_MIN_PEAK_PTP 18.0f          // Biên độ đỉnh-đáy tối thiểu hợp lệ
#define PPG_MIN_RISING_PTP 15.0f        // Biên độ tối thiểu xác nhận sườn dốc tăng
#define PPG_MIN_BPM 48                  // Giới hạn nhịp tim dưới
#define PPG_MAX_BPM 130                 // Giới hạn nhịp tim trên
#define PPG_MAX_SLEW_BPM 8              // Giới hạn độ dốc biến thiên nhịp (Slew Rate Limit)
#define MEDIAN_WINDOW_SIZE 7            // Kích thước cửa sổ lọc trung vị

// =========================================================================
// 5. HẰNG SỐ ĐẾM BƯỚC CHÂN (PEDOMETER)
// =========================================================================
#define STEP_THRESHOLD_HIGH 11.8f // m/s^2 (~1.2g)
#define STEP_THRESHOLD_LOW 9.2f   // m/s^2 (~0.94g)
#define STEP_DEBOUNCE_MS 260      // Khoảng thời gian tối thiểu giữa 2 bước

// =========================================================================
// 6. MÁY TRẠNG THÁI PHÁT HIỆN TÉ NGÃ 3 PHA (3-PHASE FALL DETECTION)
// =========================================================================
#define FALL_FREEFALL_THRESHOLD 5.0f     // |A| < 5.0 m/s^2 (~0.51g)
#define FALL_FREEFALL_MIN_MS 60          // Thời gian rơi tự do tối thiểu (60ms)
#define FALL_IMPACT_THRESHOLD 21.0f      // |A| > 21.0 m/s^2 (~2.14g)
#define FALL_IMPACT_WINDOW_MS 1200       // Va đập phải xảy ra trong vòng 1.2s sau khi rơi
#define FALL_IMMOBILITY_WINDOW_MS 2500   // Khoảng kiểm tra bất động sau va đập (2.5s)
#define FALL_IMMOBILITY_MIN 8.0f         // Biên độ gia tốc tĩnh tối thiểu (m/s^2)
#define FALL_IMMOBILITY_MAX 12.0f        // Biên độ gia tốc tĩnh tối đa (m/s^2)
#define FALL_ALERT_DURATION_MS 15000     // Thời gian duy trì cảnh báo té ngã (15s)

// =========================================================================
// 7. CẤU HÌNH ĐỒNG BỘ THỜI GIAN NTP (VIETNAM GMT+7)
// =========================================================================
#define NTP_SERVER_1 "pool.ntp.org"
#define NTP_SERVER_2 "time.google.com"
#define NTP_GMT_OFFSET_SEC (7 * 3600) // Múi giờ Việt Nam GMT+7
#define NTP_DAYLIGHT_OFFSET_SEC 0     // Không có giờ mùa hè

// =========================================================================
// 8. CẤU HÌNH BỘ NHỚ NVS FLASH (PREFERENCES)
// =========================================================================
#define NVS_NAMESPACE "smartband"
#define NVS_KEY_STEPS "steps"
#define NVS_SAVE_INTERVAL_MS 60000 // Lưu Flash tối đa 1 lần/phút chống chai Flash
#define NVS_MIN_STEP_DIFF 15      // Hoặc lưu khi bước chân lệch >= 15 bước

// =========================================================================
// 9. CẤU HÌNH NẠP CODE TỪ XA QUA WIFI (ARDUINO OTA)
// =========================================================================
#define OTA_HOSTNAME "smartband-s3"
#define OTA_PORT 3232

// =========================================================================
// 10. CẤU HÌNH ĐỒ THỊ SÓNG MẠCH TIM PPG PLETHYSMOGRAM
// =========================================================================
#define PPG_WAVE_BUFFER_SIZE 64 // 64 điểm dữ liệu hiển thị nửa dưới màn hình OLED

// =========================================================================
// 11. CHẾ ĐỘ THU THẬP DỮ LIỆU EDGE IMPULSE (50Hz CSV SERIAL STREAM)
// =========================================================================
// true: Xuất liên tục "ax,ay,az\n" ở 50Hz qua Serial cho Edge Impulse Studio
// false: Chế độ vòng tay bình thường (xuất log nhịp tim & Telemetry)
#define EDGE_IMPULSE_DATA_FORWARDER true

#endif // CONFIG_H
