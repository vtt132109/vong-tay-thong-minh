# CLAUDE HANDOFF — Bio-Band ESP32-S3 (2026-10-29)

> **Đọc file này trước, sau đó đọc `README.md`.** Đây là bản tổng hợp trạng thái thực tế sau khi viết lại firmware, dashboard, MQTT remote và train model HIFD.
> Repo: https://github.com/vtt132109/vong-tay-thong-minh
> GitHub Pages: https://vtt132109.github.io/vong-tay-thong-minh/
> Remote dashboard: https://vtt132109.github.io/vong-tay-thong-minh/remote.html

## 0. TL;DR — trạng thái hiện tại

- **Board:** ESP32-S3 Super Mini, hiện **đang rút khỏi USB** (`COM13` missing). Firmware **đang chạy trên board trước khi rút** là bản **MQTT-only**, chưa có AI.
- **Source hiện tại:** đã tích hợp **MQTT + HIFD TinyML**, build thành công nhưng **CHƯA NẠP** vì board không kết nối.
  - RAM: `51,948 / 327,680` (15.9%)
  - Flash: `955,169 / 1,310,720` (72.9%)
- **Khi cắm lại board:** nạp firmware source hiện tại, kiểm tra `[TINY-AI]`/`/data` và remote page. Đây là việc còn lại duy nhất của phần firmware.
- **AI:** model TinyML train trên **HIFD thật** (không synthetic). Event-level test: **14/15 ca ngã**, **1/34 ADL báo nhầm**; window test precision 98.3%, recall 91.8%, F1 94.9%, threshold 0.94. AI hiện **chỉ telemetry, không kích alarm** (`AI_PROMOTION_ENABLED=0`).
- **Web remote:** `remote.html` chạy trên GitHub Pages, kết nối MQTT qua `broker.emqx.io`; đã test nhận dữ liệu thật từ máy tính ở mạng khác. Board offline hiện tại chỉ vì đang rút điện.
- **Không còn demo/mock** trong dashboard; không còn nút test còi từ xa.

## 1. URLs, repo, commit

- Repo public: `https://github.com/vtt132109/vong-tay-thong-minh` (branch `main`).
- Pages landing: `https://vtt132109.github.io/vong-tay-thong-minh/`.
- Remote dashboard: `https://vtt132109.github.io/vong-tay-thong-minh/remote.html`.
- LAN dashboard: `http://<STA-IP>/` hoặc `http://192.168.4.1/` khi AP; **không mở được từ mạng khác**.
- Các commit gần nhất:
  - `149cc27` — bỏ demo, dashboard LAN live.
  - `f176c25` — thêm MQTT remote, bỏ test còi remote.
  - `4ce8152` — bundle `mqtt.min.js` local.
  - `f9656e9` — fix khoảng trắng chart remote.
  - Commit AI/HIFD + handoff này được tạo sau các commit trên.
- Git identity dùng `vtt132109 <vtt132109@users.noreply.github.com>` (máy chưa cấu hình git identity).

## 2. Phần cứng thực tế (quan trọng)

| Chức năng | Pin | Ghi chú |
|---|---|---|
| I2C SDA / SCL | **GPIO8 / GPIO9** | 100 kHz; SSD1306 0x3C, MPU6050 0x68, MAX30100 0x57 |
| Nút ngoài | **GPIO2** | Active-low, INPUT_PULLUP; nút BOOT GPIO0 là fallback |
| Buzzer active | **GPIO3** | HIGH = kêu; GPIO3 là strapping pin |
| Battery ADC | **Chưa gán** (`PIN_BATTERY_ADC=-1`) | Pin chưa hàn; OLED/web hiện `--`/0% |
| Motor | Không có | `motor=false` |

- **Nút GPIO2 đang đọc LOW khi không nhấn** (dù pull-up). Đây là lỗi phần cứng/dây: thường do tactile 4 chân đấu nhầm cặp chân thông nhau, hoặc chập GND. Firmware bỏ qua external button đến khi line lên HIGH và dùng **BOOT GPIO0** fallback. Cần sửa dây; kiểm tra GPIO2 phải ~3.3V khi nhả.
- **Battery ADC đã tắt**; khi hàn cầu phân áp 100k/100k, gán `PIN_BATTERY_ADC` (GPIO1 đang trống là ứng viên) rồi hiệu chuẩn.
- MAX30100: part ID `0x11`; LED 11mA/11mA; I2C 100kHz sau init; FIFO-full recovery; xem README mục 3.4.

## 3. Firmware — kiến trúc và hành vi

- File chính: `src/main.cpp` (setup/loop, globals), `src/sensors.cpp` (MAX30100, PPG, pin, pedometer), `src/fsm.cpp`, `src/controls.cpp`, `src/display_ui.cpp` (OLED mới), `src/web_api.cpp` (HTTP + WiFi + network task), `src/mqtt_link.cpp` (MQTT), `src/ai_model.cpp` (Edge Impulse + TinyML), `src/storage.cpp`.
- Loop 20 ms (~50 Hz) trên Core 1; network task Core 0; telemetry mutex; command queue.
- **WiFi:** `include/secrets.h` (gitignored) chứa SSID `vtt`; ESP32-S3 chỉ 2.4GHz. STA fail → `AP_STA` fallback `BioBand-Setup` / `bioband123` tại `192.168.4.1`; retry STA mỗi 60s; MQTT tự kết nối khi STA lên.
- **HTTP API:** `/` dashboard nhúng, `/api`, `/data`, `/cancel`, `/test_hw`, `/clear_nvs`, `/set_thresh`, `/set_time`, `/capture`. Dashboard local tự poll `/data`; không demo.
- **OLED:** màn boot mới, header WiFi pin steps, HR/SpO2 lớn, giờ/ngày/điện áp, alert/countdown/snooze/lead-off/moving/not-found/BUTTON OK. Giờ từ NTP hoặc `/set_time` của dashboard.
- **Nút:** short press khi countdown/alarm → snooze; giữ 3s → PANIC SOS; short press IDLE → OLED BUTTON OK; BOOT fallback.
- **Buzzer:** active GPIO3; local only.

### 3.1 MQTT remote (đã hoạt động)

- Board → `broker.emqx.io:1883`, base `bioband/vtt132109/dev01`.
- Publish `/telemetry` retained 1 Hz đúng schema `/data`; `/status` online/offline LWT retained; `/fall/alert` khi vào COUNTDOWN/ALARM/PANIC.
- Subscribe `/cancel`, `/clear_nvs`, `/set_thresh`, `/set_time`. **`test_hw` KHÔNG subscribe** để không thể làm còi kêu từ xa; local `/test_hw` vẫn có.
- `remote.html` dùng `mqtt.min.js` bundle local, WSS `broker.emqx.io:8084`; không cần cài; đã test từ mạng khác.
- Broker/topic **công khai, không auth**: ai biết topic đọc được dữ liệu sức khỏe và gửi cancel/clear/threshold. Không dùng cho dữ liệu nhạy cảm; nếu triển khai thật, thay bằng broker private/TLS + auth hoặc backend.

## 4. AI/TinyML — HIFD thật, không synthetic

- Dataset: **HIFD** — https://github.com/nhoyh/HR_IMU_falldetection_dataset; 21 subjects, cổ tay trái, 50Hz, 349 file `.mat`, 14,028 window; accel đã bỏ trọng lực, gyro đổi deg/s → rad/s; nhãn `fall`/`adl` (near-fall nằm trong adl).
- Split subject-wise: train 01–15, validation 16–18, test 19–21; không leakage.
- Label strategy đã chọn: event-centered ±1.0s quanh impact (smoothed |linear accel| peak); ngoài ±1.5s là ADL; fall weight 8; bed/chair hard-negative ×2.
- Model: 42 features → 16 tanh → 1 sigmoid; threshold **0.94**; input 100×6 @50Hz, stride 25.
- Metrics:
  - Validation: P 1.0000, R 0.9697, F1 0.9846.
  - Held-out event-centered test: P 0.9825, R 0.9180, F1 0.9492; event-level **14/15 fall recordings detected**, **1/34 ADL recordings alarmed**.
  - Legacy all-window recall 0.1329 (vì label event-centered; model chỉ nhận cửa sổ quanh impact). Không dùng metric legacy để kết luận model hỏng.
- Firmware đã tích hợp:
  - `ENABLE_TINY_AI=1`, `ENABLE_EDGE_AI=0`, `AI_PROMOTION_ENABLED=0`.
  - Gravity removal low-pass α=0.98; MPU **±16G / ±2000 dps**; gyro rad/s.
  - `ai_label`/`ai_conf`/`ai_fall` publish `/data` + MQTT; **AI không kích alarm**; rule-based FSM là lớp an toàn.
  - Artifacts: `include/tiny_fall_model.h`, `tools/hifd_features.md`, `tools/prepare_hifd.py`, `tools/train_hifd_model.py`, `tools/hifd_model_report.json`, `tools/hifd_model_report_baseline.json`, `tools/hifd_feature_test.json`.
  - Venv `.venv-ds` và dataset `dataset/hifd*` gitignored.
- **Edge Impulse path:** project cũ `1116928` chỉ có 3 mẫu 3-axis, không impulse; key role `ingestion_deployment`, không train/export qua API. Muốn Edge Impulse thật: tạo project 6-axis mới/admin key, upload HIFD, train, export `bioband_inferencing`, rồi đổi flags. Không trộn 3-axis cũ.
- **Chưa test model trên board** vì board đang rút; cần đặt tay/ngã trên đệm để xác nhận domain gap. Không claim accuracy y tế.

## 5. Web

- `realtime.html`: dashboard LAN, firmware nhúng tại `/`; không CDN; poll `/data`; layout responsive; đã test.
- `remote.html`: dashboard remote MQTT, `mqtt.min.js` local; chart cap 160px (đã fix khoảng trắng trên layout rộng); không demo; không test còi; cancel/clear/threshold.
- `index.html`: landing Pages; nút Remote trỏ `remote.html`; không link IP LAN làm CTA.
- `tools/mock_server.py`: test UI offline (không phải demo public); `tools/log_telemetry.py`, `capture_labeled.py`.
- HTML cũ `vtt.html`, `simulation.html` vẫn giữ; không dùng cho live.

## 6. Build / flash

```bash
pio run -e esp32-s3-super-mini
pio run -e esp32-s3-super-mini -t upload --upload-port COM13
python tools/monitor_serial.py COM13
```

- Nếu `COM13 missing`: cắm USB/nguồn board, kiểm tra `pio device list`.
- Source hiện tại build **955,169 B / 72.9%**, RAM 51,948 B; board đang chạy bản MQTT-only **948,909 B** (chưa AI). Sau khi nạp bản AI, cập nhật README/handoff.
- `include/secrets.h` phải tồn tại local với WiFi `vtt`; không commit.

## 7. Việc còn lại (theo thứ tự)

1. **Cắm board**, nạp source hiện tại; xác nhận `[I2C] 0x3C/0x57/0x68`, `[MQTT] connected`, `[TINY-AI]` có log, `/data` có `ai_label`/`ai_conf`; remote page hiện AI.
2. Test AI on-device: đứng yên (adl), đi lại/vỗ tay (adl), ngã trên đệm (fall) — so với rule-based; **không bật AI promotion** cho đến khi false alarm đạt mục tiêu.
3. Sửa nút GPIO2 (tactile 4 chân dùng chân chéo; nhả phải HIGH); kiểm tra BOOT fallback.
4. Hàn pin + cầu phân áp; gán `PIN_BATTERY_ADC`, hiệu chuẩn; bật lại hiển thị pin.
5. Thu data thật từ chính vòng tay (`tools/capture_labeled.py`), fine-tune/validate; HIFD chỉ là domain gần, không thay data thật.
6. (Tuỳ chọn) Edge Impulse 6-axis/admin key; hoặc giữ TinyML local.
7. Bảo mật: đổi mật khẩu WiFi (mật khẩu cũ từng nằm trong git history public), thay broker public bằng private/auth nếu dùng thật; `include/secrets.h` gitignored.
8. Cập nhật README/handoff sau khi test board; commit/push; Pages.

## 8. Lưu ý an toàn / không làm lại

- Không reintroduce Telegram, MAX30102/SparkFun cho module MAX30100 hiện tại, pinout cũ (1/7/3 battery, v.v.).
- Không bật `AI_PROMOTION_ENABLED=1` hoặc cho AI hủy alarm rule-based nếu chưa validate on-device.
- Không dùng synthetic/HIFD để claim accuracy y tế; model là research demo, domain gap.
- Không đưa `include/secrets.h`, API key, hoặc raw HIFD dataset lên repo.
- **Không test còi/motor từ xa mà không báo trước** (đã từng làm người dùng giật mình và rút hardware). Local `/test_hw` chỉ khi được yêu cầu.
- Public broker/topic: dữ liệu sức khỏe ai biết topic đều xem; cân nhắc trước khi dùng thật.

## 9. File map nhanh

```
src/main.cpp          globals, setup/loop
src/sensors.cpp       MAX30100 + PPG + pin + pedometer
src/fsm.cpp           fall FSM; AI promotion guarded off
src/controls.cpp      button/buzzer/commands
src/display_ui.cpp    OLED mới
src/web_api.cpp       HTTP, WiFi AP_STA retry, network task
src/mqtt_link.cpp     MQTT telemetry/status/commands
src/ai_model.cpp      EI branch + TinyML HIFD branch
include/tiny_fall_model.h  model weights/threshold
include/mqtt_link.h
include/board_config.h
include/app_state.h / shared_types.h
realtime.html / remote.html / index.html / mqtt.min.js
tools/prepare_hifd.py / train_hifd_model.py / hifd_features.md
tools/hifd_model_report*.json / hifd_feature_test.json
README.md / CLAUDE_HANDOFF.md
```

## 10. Cách Claude tiếp tục

1. Đọc file này + `README.md` + `include/board_config.h`.
2. Kiểm tra `pio device list` / COM13; nếu board chưa cắm, **hỏi người dùng cắm board** trước khi nạp.
3. Build; nạp; đọc Serial; kiểm tra MQTT/remote page; test AI theo mục 7.
4. Không sửa pinout/AI safety/broker public mà không hỏi; không tự ý test còi.
5. Cập nhật file này/README và commit sau khi có kết quả thực tế.

_Handoff generated 2026-10-29; AI integration build verified but not flashed because the board was unplugged._
