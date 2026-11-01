# Bio-Band — vòng đeo tay phát hiện té ngã và theo dõi sinh hiệu (ESP32-S3)

> Repo: https://github.com/vtt132109/vong-tay-thong-minh · Trang giới thiệu: https://vtt132109.github.io/vong-tay-thong-minh/
> **Báo cáo đầy đủ (để đọc, thuyết trình, nộp thi): [`BAO_CAO.md`](BAO_CAO.md).** Kế hoạch và tiến độ: [`PLAN.md`](PLAN.md).
> Cập nhật: 2026-11-02. Sản phẩm nghiên cứu, **không phải thiết bị y tế**.

## 1. Bio-Band làm được gì

- **Phát hiện té ngã bằng hai lớp**: máy trạng thái luật (rơi tự do → va đập → bất động) và **AI chạy ngay trên chip** (MLP 42 đặc trưng + CNN 1D int8, trung bình xác suất). Đo: MPU6050, 50 Hz, cửa sổ 2 giây.
- **Nhịp tim và SpO2** bằng MAX30100 (đặt ngón tay lên cảm biến), lọc nhiễu chuyển động, chỉ số tưới máu, median 3.
- **Cảnh báo tại chỗ**: còi, OLED, nút hủy (đếm ngược 10 giây). Giữ nút 3 giây = SOS.
- **Dashboard**: LAN (`http://<IP>/`, nhúng trong firmware) và từ xa chỉ-xem qua MQTT (`remote.html`).
- Không cần cloud để phát hiện và báo động; MQTT chỉ để xem từ xa.

Kết quả AI (leave-one-subject-out, 21 người, dữ liệu cổ tay thật HIFD qua đúng chuỗi xử lý của firmware): xem bảng ở [`docs/results_tables.md`](docs/results_tables.md) và `BAO_CAO.md` mục 6. Điểm vận hành đã nạp: phát hiện 99/104 ca ngã (95,2 %; CI 95 % 0,89–0,98), 0 báo nhầm trong 1,95 giờ sinh hoạt (giới hạn trên 95 % ≈ 1,9 lần/giờ). Số này đo trên dữ liệu công khai, **chưa phải trên người đeo Bio-Band**.

## 2. Trạng thái

| Hạng mục | Trạng thái |
|---|---|
| Firmware | MQTT publish-only + TinyML (MLP + CNN int8) + self-test khi khởi động. 983 KB flash (75 %), RAM 16,6 %. CPU 160 MHz. |
| AI | Chạy trên chip: MLP 423 µs, CNN 4,2 ms mỗi 0,5 giây. Self-test khớp numpy; hardware-in-the-loop 1942 cửa sổ: 0 quyết định lệch. |
| **Báo động bằng AI** | **Công tắc runtime, mặc định TẮT** (`POST /ai_mode?val=1` hoặc nút trên dashboard LAN). Khi tắt, chỉ luật FSM kích báo động; AI vẫn đo và gửi xác suất. Chỉ bật khi thử có giám sát hoặc demo. |
| Cần phần cứng/người | Nút GPIO2 (đọc LOW khi nhả → dùng nút BOOT GPIO0), chưa hàn pin/ADC pin, chưa thử ngã thật trên người đeo, chưa đo dòng tiêu thụ. |

## 3. Phần cứng

| Chức năng | Chân | Ghi chú |
|---|---|---|
| I2C SDA / SCL | GPIO 8 / 9, 100 kHz | OLED SSD1306 0x3C, MPU6050 0x68, MAX30100 0x57 (part ID 0x11) |
| Nút ngoài | GPIO 2 | Active-low, pull-up nội. Nút BOOT (GPIO 0) là dự phòng |
| Còi active | GPIO 3 | HIGH = kêu (GPIO3 là chân strapping) |
| ADC pin | chưa gán | `PIN_BATTERY_ADC=-1`; hàn cầu phân áp 100k/100k + 100 nF vào GPIO1 rồi gán và hiệu chuẩn |
| Motor, GPS | không có | `motor` trong JSON luôn `false` |

Linh kiện: ESP32-S3 Super Mini, GY-MAX30100, OLED 0,96", MPU6050, pin LiPo + TP4057, còi active, nút nhấn, công tắc MSK-12D19 (công tắc nguồn, không phải GPIO).

Lưu ý phần cứng:
- GPIO2 đọc LOW khi không nhấn: thường do tactile 4 chân đấu nhầm cặp chân thông nhau hoặc chập GND. Khi nhả phải đo ~3,3 V.
- Kiểm tra backfeed TP4057/USB/pin trước khi cắm USB lúc có pin.
- MAX30100: LED 11 mA/11 mA (50/27 mA làm ADC bão hòa), I2C ép về 100 kHz sau `begin()`, tự xả FIFO khi đầy (`wr==rd` và overflow), lead-off khi IR thô < 5000 trong ~1 giây. MAX30100 đo ở đầu ngón tay; đo ở cổ tay chưa được kiểm chứng.

## 4. Build và nạp

```bash
pio run -e esp32-s3-super-mini
pio run -e esp32-s3-super-mini -t upload --upload-port COM13
python tools/monitor_serial.py            # tự tìm cổng; --seconds N, --no-reset
```

- Cờ trong `platformio.ini`: `ENABLE_TINY_AI=1` (MLP), `ENABLE_CNN_AI=1` (CNN int8). Xung CPU: `-DBIO_CPU_MHZ=80|160|240` (mặc định 160).
- `board_build.embed_txtfiles = realtime.html`: sửa dashboard LAN thì phải build lại.
- Partition `default.csv` (app 1,25 MB). Thư viện: Adafruit SSD1306/GFX/MPU6050, ArduinoJson 6, PubSubClient, MAX30100lib.
- Kiểm thử Python: `python -m pytest tests -q` (xem `tools/README.md` để cài môi trường).

### WiFi

- `include/secrets.h` (gitignore; mẫu `secrets.example.h`): `WIFI_SSID`, `WIFI_PASS`, tùy chọn `AP_PASS`.
- **Đổi WiFi không cần nạp lại**: khi không vào được mạng, board phát AP `BioBand-Setup` (mật khẩu in ở Serial, dẫn xuất từ MAC hoặc `AP_PASS`), mở `http://192.168.4.1/wifi`, nhập SSID/mật khẩu, board lưu vào NVS và khởi động lại. Thông tin lưu trong NVS được ưu tiên hơn `secrets.h`.
- ESP32-S3 chỉ hỗ trợ 2,4 GHz. SSID phân biệt chữ hoa/thường (đã từng gây lỗi "không thấy mạng"). Khi STA lỗi, board thử lại mỗi 60 giây.
- Tiết kiệm điện: modem sleep (độ trễ HTTP tăng ≤ ~100 ms). Giờ lấy từ NTP, hoặc từ dashboard khi chưa có NTP.

## 5. API và MQTT

### HTTP (LAN, cổng 80)

| Phương thức | Đường dẫn | Chức năng |
|---|---|---|
| GET | `/` | dashboard nhúng trong firmware (cùng origin) |
| GET | `/data` | JSON telemetry |
| POST | `/cancel`, `/test_hw`, `/clear_nvs` | hủy cảnh báo, test còi 2 giây, xóa số lần ngã/bước |
| POST | `/set_thresh?val=25`, `/set_time?epoch=…` | ngưỡng va đập (10–60), đồng bộ giờ (bỏ qua nếu đã có NTP) |
| POST | `/ai_mode?val=0|1` | bật/tắt báo động bằng AI (lưu NVS) |
| GET/POST | `/capture?seconds=60` | stream IMU CSV 50 Hz ra USB để thu dữ liệu (`on=0` để dừng) |
| GET / POST | `/wifi`, `/wifi_save` | trang cấu hình WiFi |

- **Mọi lệnh POST cần header `X-Bioband: 1`**, và server không gửi header CORS: trang web ở origin khác không đọc được `/data` và không gửi được lệnh (chống CSRF). Dashboard nhúng đã gửi header này.
- `/data` dùng cùng một hàm dựng JSON với MQTT (`fillTelemetryJson`). Khóa: `state, bpm, spo2, raw_bpm, raw_spo2, acc, thresh, max30102*, lead_off, falls, fps, steps, distance_km, calories, battery_v, battery_pct, ram_pct, buzzer, motor, snooze_sec, cd_sec, mpu, finger, ppg_motion, ai_label, ai_conf, ai_p, ai_thr, ai_peak, ai_fill, ai_n, ai_us, ai_fall, ai_mlp, ai_cnn, ai_cnn_us, ai_self, ai_arm, ai_max6, jit, chip_c, cpu_mhz, fw`. (*tên `max30102` giữ để tương thích; phần cứng là MAX30100.)

### MQTT (chỉ xem từ xa)

- Broker công khai `broker.emqx.io` (board: 1883, trình duyệt: `wss://…:8084`), topic gốc `bioband/vtt132109/dev01`: `telemetry` (retained, 1 Hz), `history` (60 giây gần nhất, retained), `status` (online/offline, LWT), `fall/alert`.
- **Chỉ publish, không subscribe lệnh nào.** Broker không có xác thực nên không thể cho phép hủy báo động, xóa dữ liệu hay đổi ngưỡng từ xa. Ai biết topic đều đọc được dữ liệu: không dùng cho dữ liệu nhạy cảm; triển khai thật cần broker riêng có TLS và xác thực.
- `remote.html` phân biệt bản tin retained (dữ liệu cũ) với bản tin trực tiếp và hiển thị "mất liên lạc" nếu đang ALARM mà ngừng nhận dữ liệu.

## 6. Hành vi firmware

- Vòng lặp 20 ms (50 Hz) trên Core 1; mạng, HTTP và MQTT trên Core 0. Telemetry bảo vệ bằng mutex; lệnh đi qua hàng đợi.
- **FSM**: `IDLE → FREE_FALL → IMPACT → COUNTDOWN (10 s) → ALARM → SNOOZE (20 s)`. Ngưỡng va đập 25 m/s² (chỉnh được). Hằng số gốc đòi bất động 3 giây ngay sau va đập; trên HIFD chỉ 6/104 ca ngã thỏa vì người ngã còn cử động hơn 1 giây (xem `BAO_CAO.md`).
- **Chế độ báo động bằng AI** (tắt mặc định): (A) tổ hợp AI ≥ 0,87 → đếm ngược ngay (~0,2 s sau va đập); (B) đường luật hiệu chỉnh lại (ổn định 1,5 s, cửa sổ 2 s, phương sai < 0,8) nhưng phải được AI hỗ trợ (p ≥ 0,5 trong 6 giây gần nhất). Có cooldown 30 giây sau mỗi lần AI báo.
- **Health guard**: HR < 50 hoặc > 120 hoặc SpO2 < 90 liên tục 10 giây, sau 20 giây làm nóng kể từ lúc đặt ngón tay.
- **Hiệu chỉnh gyro** khi khởi động nếu cổ tay đang yên (1 giây, lưu trong RAM).
- **Self-test AI** khi khởi động: 6 cửa sổ cố định chạy qua MLP và CNN, so với tham chiếu numpy (`[SELFTEST] PASS`).
- **Hardware-in-the-loop**: gửi `#HIL` qua USB rồi các dòng `W,<600 số>`; board trả `P,<mlp>,<cnn>` (`tools/ai_lab/hil_eval.py`).
- **Bảo trì qua USB**: `#SETCOUNTS,<ngã>,<bước>` đặt lại bộ đếm lưu trong NVS (replay không bao giờ thay đổi bộ đếm).
- **Tự kiểm tra HTTP**: gửi `#HTTPSELF` qua USB, board gọi API của chính nó và in `[HTTPSELF] PASS/FAIL` (guard CSRF, không CORS).
- **Replay đầu-cuối**: `#REPLAY` rồi các dòng `S,ax,ay,az,gx,gy,gz` ở 50 Hz thay cho MPU6050 (còi bị tắt); xem FSM/AI phản ứng với bản ghi HIFD thật (`tools/ai_lab/replay_eval.py`).
- **OLED**: HR/SpO2, giờ/ngày, bước, WiFi, tag `AI` khi bật báo động bằng AI. Làm mới 2 Hz ở màn thường, 5 Hz khi cảnh báo.
- Lưu NVS: ngưỡng, số lần ngã, số bước, chế độ AI, WiFi.

## 7. Cấu trúc thư mục

```
src/ include/        firmware (main, sensors, fsm, ai_model, ai_cnn, controls, display_ui, web_api, mqtt_link, storage)
include/*_model.h    trọng số sinh tự động (tiny_fall_model.h, cnn_fall_model.h, selftest_vectors.h)
realtime.html        dashboard LAN (nhúng firmware)       remote.html   dashboard từ xa (MQTT)
index.html           trang giới thiệu (GitHub Pages)      legacy/       mô phỏng cũ (vtt, simulation)
tools/ai_lab/        pipeline AI: dữ liệu, tiền xử lý, LOSO, lượng tử hóa, HIL, hình, bảng
tools/               thu dữ liệu, log, mock server, công cụ HIFD gốc (xem tools/README.md)
tests/               pytest        .github/workflows/ci.yml   CI (build + test)
docs/                hình và bảng kết quả
BAO_CAO.md PLAN.md CLAUDE_HANDOFF.md
```

## 8. An toàn và hạn chế

- Không phải thiết bị y tế; không dùng để đánh giá sức khỏe hay thay thế giám sát người.
- Mô hình học từ dữ liệu công khai (người trẻ, cảm biến khác, hướng trục chưa rõ); chưa thử trên người đeo Bio-Band. Báo động bằng AI vì vậy mặc định tắt.
- Thử ngã chỉ trên đệm dày, có người giám sát và có đồng ý của người tham gia (xem `tools/capture_labeled.py`).
- Không đưa `include/secrets.h`, khóa API hay dữ liệu HIFD thô lên repo. Mật khẩu WiFi `vtt` cũ từng nằm trong lịch sử git công khai: hãy đổi.
- Không test còi từ xa mà không báo trước người dùng.
