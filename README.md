# Bio-Band ESP32-S3 Super Mini — Project Handoff

> Repo công khai: https://github.com/vtt132109/vong-tay-thong-minh
> GitHub Pages: https://vtt132109.github.io/vong-tay-thong-minh/
> File này là nguồn thông tin chính cho session tiếp theo. Đọc hết trước khi sửa code.
> Cập nhật lần cuối: 2026-10-29.

## 1. Trạng thái hiện tại

- Firmware đã được viết lại từ đầu theo sơ đồ EasyEDA `Sheet_1`.
- Build PlatformIO **thành công**:
  - RAM: `48,700 / 327,680 bytes` (14.9%)
  - Flash: `939,889 / 1,310,720 bytes` (71.7% của app partition 1.25 MB, đã gồm dashboard nhúng)
- **Đã flash COM13 và chạy thật.** I2C 100 kHz ổn định; MAX30100 part `0x11` nhận đúng; HR/SpO2 đã đo bằng đầu ngón tay (HR ~68–78 bpm, SpO2 ~97%, IR ~18k–20k, PI ~2.5%).
- WiFi: `include/secrets.h` đã đặt SSID `vtt`. Khi hotspot 2.4 GHz bật, board vào STA và in `[NET] STA IP ...` (IP DHCP có thể đổi). Máy tính đang ở mạng 5 GHz khác nên có thể không truy cập được subnet của hotspot; dùng điện thoại cùng `vtt` hoặc chuyển PC sang `vtt`. Nếu STA fail, board fallback AP `BioBand-Setup` / `bioband123` tại `192.168.4.1` và in scan 2.4 GHz ra Serial. ESP32-S3 chỉ hỗ trợ 2.4 GHz.
- Dashboard `realtime.html` mới: tự chứa/không CDN, đã test desktop + mobile bằng `tools/mock_server.py`; các lệnh Test còi, Lưu ngưỡng, HỦY gửi đúng. Firmware nhúng dashboard và phục vụ tại `GET /`.
- OLED đã thiết kế lại: bỏ dải IR/RED và footer MPU/MAX/F; thêm giờ:phút, giây, ngày/tháng, cột WiFi, số bước, điện áp pin. Giờ lấy từ NTP khi STA có Internet, hoặc được dashboard đồng bộ qua `/set_time` khi mở web; nếu chưa có cả hai thì hiện `--:--`.
- Pin chưa hàn nên firmware tắt ADC pin (`PIN_BATTERY_ADC=-1`), dashboard/OLED hiện 0%/`--`; khi hàn cầu phân áp, gán lại pin.
- Nút ngoài **GPIO2** (active-low) đang đọc `0` khi không nhấn → kiểm tra chập GND/đấu chân tactile; nút **BOOT GPIO0** vẫn dùng được. Buzzer active **GPIO3**. `falls=7` lưu NVS (xóa bằng `/clear_nvs`); buzzer/FSM chưa test đầy đủ.
- Edge AI scaffold + capture mode đã có; mặc định `ENABLE_EDGE_AI=0` để build không cần model.
- Có script tạo synthetic data/upload tại `tools/generate_synthetic_imu.py` và `tools/upload_dataset.py` (fake data chỉ để test pipeline).
- HTML được giữ lại: `realtime.html`, `vtt.html`, `simulation.html`.

## 2. Mục tiêu

Vòng đeo tay sức khỏe dùng ESP32-S3 Super Mini:

- Phát hiện té ngã bằng MPU6050, ngưỡng va đập 25 m/s².
- Đo nhịp tim/SpO2 bằng module GY-MAX30100.
- Cảnh báo tại chỗ bằng buzzer active và nút hủy; không dùng Telegram.
- Hiển thị OLED SSD1306 128x64.
- Lưu ngưỡng/số lần cảnh báo/số bước vào NVS.
- Web dashboard qua WiFi (AP fallback hoặc STA).
- Không có motor rung và không có GPS trên phần cứng hiện tại.

## 3. Phần cứng và pinout

### 3.1 Bảng chân

| Chức năng | GPIO / net | Ghi chú |
|---|---|---|
| I2C SDA | **GPIO8** | Dùng chung cho OLED, MPU6050, GY-MAX30100 |
| I2C SCL | **GPIO9** | 100 kHz (MAX30100lib tự đổi 400 kHz trong `begin()`, firmware ép lại 100 kHz) |
| OLED SSD1306 | 0x3C | Có fallback 0x3D |
| MPU6050 | 0x68 | AD0 để mặc định |
| MAX30100 (GY-MAX30100) | 0x57 | Part ID mong đợi: `0x11` |
| ADC pin | **Chưa gán** | Pin chưa hàn; firmware đặt `PIN_BATTERY_ADC=-1`; gán lại khi hàn cầu phân áp |
| Nút nhấn | **GPIO2** | INPUT_PULLUP; nhấn = LOW; nút **BOOT GPIO0** là fallback |
| Buzzer active | **GPIO3** | HIGH = kêu, LOW = tắt; GPIO3 là strapping pin |
| Công tắc MSK-12D19 | — | Công tắc nguồn, **không phải GPIO** |
| Motor rung | — | Không có trên board |

### 3.2 Sơ đồ nguồn / linh kiện

- U1: KENSINH ESP32-S3-SUPERMINI TH.
- U2: GY-MAX30100 (VCC/GND/SCL/SDA; INT không dùng).
- U3: OLED 0.96 (GND/VCC/SCL/SDA).
- U4: MPU6050 (VCC/GND/SCL/SDA; XDA/XCL/AD0/INT không dùng).
- U5: pin LiPo (GND, 4.2+).
- U6: TP4057 Mini-HT (sạc LiPo).
- U7: active buzzer.
- U8: push button.
- NO1: MSK-12D19 — công tắc nguồn giữa battery+ và rail 5V.
- R1 = R2 = 100k (cầu phân áp pin, **chưa gán GPIO**), C1 = 100nF (lọc ADC khi hàn).
- OLED/MPU/MAX đều dùng 3.3V, chung GND, chung bus I2C 8/9.

### 3.3 Cảnh báo phần cứng

- **GPIO3 là strapping pin** và đang dùng cho **buzzer**. Nếu board boot không ổn định, kiểm tra mức GPIO3 lúc boot. ADC pin hiện **chưa gán** (`PIN_BATTERY_ADC=-1`) vì pin chưa hàn.
- **Đường nguồn TP4057 + USB + pin**: cần kiểm tra backfeed khi vừa cắm USB vừa có pin. Nếu chưa có diode/load-sharing, không nên cắm cả hai lâu dài.
- Khi hàn cầu phân áp pin, dùng nguồn có trở kháng thấp và C1 100nF; sau đó gán `PIN_BATTERY_ADC` rồi hiệu chuẩn.
- Buzzer active giả định kích mức HIGH; nếu module kích LOW, đảo logic trong `src/controls.cpp`.
- **Nút ngoài GPIO2 phải là loại thường mở, nối xuống GND.** Firmware bật pull-up nội; nếu Serial in `[BTN] GPIO2=0` khi **không nhấn**, đường nút đang bị chập GND/button kẹt/hàn sai (đặc biệt tactile 4 chân đấu nhầm cặp) — cần sửa dây. Khi đó firmware tự dùng nút **BOOT onboard (GPIO0)** làm fallback. Nút chỉ hủy/snooze khi đang countdown/alarm; nhấn ngắn ở IDLE hiện `BUTTON OK` trên OLED 1,2 giây; giữ 3 giây → `PANIC SOS`.
- Không có motor; mọi hiển thị motor trong HTML chỉ là mô phỏng.

### 3.4 Xử lý MAX30100

- Driver: **MAX30100lib** (`oxullo/Arduino-MAX30100`); part ID `0x11`. Sampling 100 Hz; `BeatDetector`, `DCRemover`, `FilterBuLp1`, `SpO2Calculator` của thư viện; HR/SpO2 cập nhật mỗi 1 s.
- **I2C 100 kHz**: `MAX30100::begin()` gọi `Wire.begin()` và tự đặt bus về **400 kHz** (`I2C_BUS_SPEED`); firmware gọi lại `Wire.setClock(100000)` ngay sau khi cấu hình, nếu không FIFO read sẽ lỗi/trả rác.
- **Soft reset + FIFO**: trước `hrm.begin()`, ghi bit RESET (reg `0x06`, bit 6); sau đó `shutdown()`, `resetFifo()`, cấu hình mode/LED, xả FIFO thủ công, `resetFifo()` lần nữa.
- **FIFO full recovery**: nếu FIFO đầy, `wr == rd` và `ovf > 0`; thư viện coi `wr==rd` là rỗng nên không bao giờ xả. `processMaxSamples()` phát hiện trường hợp này, đọc trực tiếp 16 mẫu từ reg `0x05`, xử lý rồi `resetFifo()`. Log `[PPG] ... n=99..100` xác nhận FIFO chạy đúng.
- **LED current 11 mA / 11 mA** (`MAX30100_LED_CURR_11MA`, reg `0x33`). Trên module hiện tại, 50 mA/27 mA làm ADC bão hòa `65535`; 11 mA cho tín hiệu tốt (IR ~18k–20k, red ~14.5k, PI ~2.5%).
- **Lead-off dùng IR thô**: `ir < MAX30100_LEAD_OFF_IR` (5000) liên tục ~1 s → `fingerDetected=false`, HR/SpO2 reset. Không dùng `DCRemover::getDCW()` vì giá trị này ~20× trung bình thực (alpha 0.95).
- Thư viện `MAX30100::begin()` gọi `Wire.begin()` không tham số; variant ESP32-S3 mặc định SDA 8 / SCL 9.

### 3.5 Lọc nhiễu HR/SpO2

- **Motion gate**: mỗi mẫu MPU, firmware tính độ lệch gia tốc khỏi 1g và độ lớn gyro. Nếu lệch > 1.5 m/s² hoặc gyro > 1.5 rad/s, PPG bị khóa 800 ms; FIFO được xả, buffer/thuật toán/median reset; `ppgMotion=true`.
- Khi bị khóa, OLED hiện `DANG CHUYEN DONG / GIU YEN TAY`, dashboard PPG hiện `MOVING`, HR/SpO2 về `--`.
- **Perfusion index (PI)**: sau khi đủ buffer 100 mẫu, tính `PI = (IR_max - IR_min) / IR_DC × 100`. Chỉ chạy thuật toán khi PI trong khoảng `0.10–15%`; ngoài khoảng thì HR/SpO2 = 0.
- **Valid flags + median**: chỉ nhận HR 30–220 và SpO2 70–100 khi Maxim báo valid; lấy median của 3 kết quả hợp lệ gần nhất để giảm nhảy giá trị.
- Lead-off vẫn ưu tiên: IR DC < 5000 trong ~1 s → reset toàn bộ kết quả PPG.
- Có thể chỉnh `PPG_MOTION_ACCEL_GATE`, `PPG_MOTION_GYRO_GATE`, `PPG_MOTION_HOLD_MS`, `PPG_MIN_PI` trong `board_config.h`; đeo sát tay, giữ yên khi đo.
- Đây là lọc nhiễu thực dụng, không phải thiết bị y tế; motion artifact/ánh sáng môi trường vẫn có thể làm sai; cần validate với dữ liệu thật.
- Mô phỏng output filter (`python tools/test_ppg_filter.py`, 200 seed, 120 s): HR MAE **4.72 → 2.75 → 1.65 bpm** (raw → median → full), spike >10 bpm **13.7% → 7.3% → 2.1%**, motion outputs **20 → 0**; SpO2 MAE **0.99 → 0.62 → 0.35%**. Full filter coverage 74.2% vì chủ động để trống khi motion/refill/low-PI. Đây là mô phỏng output filter, không phải DSP/hardware.
- Trên board thật, `/data` có thêm `raw_bpm`/`raw_spo2` (kết quả Maxim trước lọc) và `bpm`/`spo2` (sau lọc); dashboard có item **Raw HR/SpO2**; Serial in `[DATA] HR=filtered/raw ...`.
- Log thực tế: `python tools/log_telemetry.py --host 192.168.4.1 --duration 120 --out ppg_log.csv`. Giữ yên 30 s → lắc tay 10 s → giữ yên 30 s; xem jitter/spike raw vs filtered. Không có ground truth trong log; so với máy đo tham chiếu để đánh giá accuracy.

## 4. Kiến trúc firmware

```
src/
  main.cpp         - định nghĩa global, setup(), loop()
  controls.cpp     - nút nhấn, buzzer, xử lý command queue
  sensors.cpp      - LUT pin, đọc ADC pin, xử lý MAX30100 + lọc nhiễu PPG, pedometer
  fsm.cpp          - FSM té ngã, health guard, alarm, snooze
  display_ui.cpp   - toàn bộ render OLED
  storage.cpp      - NVS: threshold, falls, steps
  web_api.cpp      - telemetry, WiFi, HTTP server, network task
  ai_model.cpp     - wrapper Edge Impulse (mặc định tắt)

include/
  board_config.h     - pin, ngưỡng, timing
  app_state.h        - extern toàn bộ state dùng chung
  shared_types.h     - enum + struct telemetry/command
  sensors.h / fsm.h / display_ui.h / storage.h /
  web_api.h / ai_model.h / controls.h
  secrets_config.h   - include secrets.h nếu có, fallback rỗng
  secrets.example.h  - mẫu WiFi
```

### 4.1 Luồng chạy

- Arduino `loop()` chạy trên **Core 1**, chu kỳ 20 ms (~50 Hz):
  - xử lý command từ web, nút nhấn
  - đọc MPU6050, cập nhật pedometer
  - xử lý FIFO MAX30100
  - đọc pin mỗi 1 s
  - cập nhật FSM/health guard/buzzer
  - render OLED mỗi 200 ms
  - publish telemetry mỗi 200 ms
- `networkTask` chạy trên **Core 0**, stack 20 KB:
  - WiFi STA hoặc AP fallback
  - HTTP server port 80
  - nhận command từ web và publish telemetry
- Đồng bộ:
  - `telemetryMutex` bảo vệ `TelemetrySnapshot`
  - `commandQueue` (web → sensor loop)
- Không dùng `Wire1`; tất cả thiết bị I2C nằm trên một `Wire` 8/9.

## 5. FSM và các ngưỡng

| Thông số | Giá trị | Nơi đặt |
|---|---|---|
| Ngưỡng va đập | 25.0 m/s² | NVS + `DEFAULT_FALL_THRESHOLD` |
| Free-fall | < 5.0 m/s², 3 mẫu liên tiếp (~60 ms) | `fsm.cpp` |
| Cửa sổ impact | 800 ms | `IMPACT_WINDOW_MS` |
| Bất động sau impact | 3 s + 200 ms settle | `INACTIVITY_WINDOW_MS` |
| Phương sai xác nhận | < 0.08 | `INACTIVITY_VAR_THRESHOLD` |
| Phương sai hủy do cử động | > 0.8 | `MOTION_VAR_THRESHOLD` |
| Countdown | 10 s | `COUNTDOWN_MS` |
| Snooze | 20 s | `SNOOZE_MS` |
| Giữ nút SOS | 3 s | `BUTTON_LONG_MS` |
| Health guard | HR < 50 hoặc > 120, SpO2 < 90, liên tục 10 s | `HEALTH_CONFIRM_MS` |
| Lead-off | IR DC < 5000 (16-bit) trong ~1 s | `MAX30100_LEAD_OFF_IR` |
| Pedometer | acc > 13 rồi < 10.5, cách nhau ≥ 300 ms | `sensors.cpp` |
| Test buzzer | 2 s | `TEST_BUZZER_MS` |

### 5.1 Trạng thái

`IDLE → FREE_FALL → IMPACT → (INACTIVITY) → COUNTDOWN → ALARM → SNOOZE → IDLE`

- `FREE_FALL` không thấy impact trong 800 ms → về IDLE.
- `IMPACT` lấy mẫu 3 s sau 200 ms; variance thấp → COUNTDOWN; variance cao → IDLE; trung gian → gia hạn thêm 3 s một lần.
- Va đập trực tiếp > 25 m/s² từ IDLE cũng vào IMPACT (có cooldown 2 s).
- COUNTDOWN hết 10 s → ALARM; nút nhấn ngắn → SNOOZE.
- ALARM/PANIC: buzzer kêu liên tục, tăng `fallCount`, lưu NVS, đẩy alert queue; nút nhấn ngắn → SNOOZE.
- Giữ nút 3 s ở trạng thái khác Alarm/Panic → PANIC_SOS (SOS khẩn cấp).
- Health guard chỉ chạy ở IDLE, cần finger + HR/SpO2 hợp lệ.

## 6. OLED

- SSD1306 128x64, I2C 0x3C (fallback 0x3D), render 5 Hz. Giao diện mới theo phong cách "clinical instrument": hairline, số lớn, icon tim/giọt oxy, hai dải sóng.
- Boot: wordmark `BIO-BAND`, `ESP32-S3 WEARABLE`, đường ECG cách điệu, `MAX30100`, `STARTING...`.
- Màn chính:
  - header: `BIO-BAND`, số bước `S...`, phần trăm pin + icon pin
  - trái: icon tim + `HR`, số HR cỡ lớn, đơn vị `BPM`
  - phải: `SpO2`, số SpO2 cỡ lớn, `%`, icon giọt oxy
  - giữa: hairline dọc/ngang tách vitals
  - dưới: hai dải sóng `IR` và `RED` (116 điểm, có baseline chấm)
  - footer: `MPU:OK/NO`, `MAX:OK/NO`, `F:<falls>`
- Màn đặc biệt:
  - COUNTDOWN: nền đảo nhấp nháy, lý do FALL/HEALTH, số giây cỡ 4, hướng dẫn `PRESS BUTTON / TO CANCEL`, progress bar
  - ALARM/PANIC: nền đảo, `ALARM`/`PANIC`, lý do `FALL`/`HEALTH`/`SOS`, hướng dẫn tắt
  - SNOOZE: `SNOOZE`, đếm ngược `nn s`, `TAM KHOA`
  - FREE_FALL/IMPACT/INACTIVITY: tên trạng thái, `a=... m/s2`, `VERIFYING...`, chấm nhấp nháy
  - LEAD-OFF: icon ngón tay + slash, `LEAD-OFF`, `PLACE FINGER ON SENSOR`
  - MOVING: `MOVING`, `HOLD STILL`, `PPG LOCKED`
  - BUTTON OK: hiện 1,2 giây sau khi nhấn nút ngắn ở IDLE; xác nhận GPIO2/BOOT đã đọc được
  - MAX30100 NOT FOUND: `MAX30100`, `NOT FOUND`, `CHECK I2C 8/9 + 3V3`
- Giờ trên OLED: NTP khi STA có Internet, hoặc dashboard tự gửi `/set_time?epoch=...` khi mở web (kể cả AP); nếu chưa có nguồn giờ thì `--:--`.
- Nếu OLED không tìm thấy, firmware vẫn chạy (không treo).

## 7. WiFi và HTTP API

### 7.1 WiFi

- Nếu `include/secrets.h` không tồn tại hoặc không có SSID:
  - phát AP `BioBand-Setup`, mật khẩu `bioband123`
  - IP `192.168.4.1`
- Nếu có SSID:
  - thử STA 15 s; thất bại → AP fallback
  - IP in ra Serial: `[NET] STA IP ...`
- **ESP32-S3 chỉ hỗ trợ WiFi 2.4 GHz.** Mạng `vtt` phải phát ở 2.4 GHz (hotspot điện thoại/router); mạng 5 GHz sẽ không kết nối được.
- `include/secrets.h` hiện đặt `WIFI_SSID "vtt"` / `WIFI_PASS` (file đã gitignore). Khi đổi WiFi, sửa file này rồi build/nạp lại.
- Nếu STA thất bại, board phát AP `BioBand-Setup` / `bioband123`; dashboard vẫn dùng được tại `192.168.4.1`. Firmware in scan 2.4 GHz (`[NET] <ssid> rssi=... ch=... enc=...`) để kiểm tra vì sao không thấy `vtt`.
- NTP UTC+7 khi STA (`pool.ntp.org`, `time.google.com`).
- Không còn Telegram; cảnh báo chỉ tại chỗ qua buzzer/OLED.

Tạo file bí mật:

```bash
copy include\secrets.example.h include\secrets.h
```

Điền:

```cpp
#define WIFI_SSID "..."
#define WIFI_PASS "..."
```

`include/secrets.h` đã nằm trong `.gitignore`.

### 7.2 HTTP API

Server port 80, CORS `*` để mở dashboard từ file local.

| Method | Path | Chức năng |
|---|---|---|
| GET | `/` | dashboard HTML (nhúng trong firmware, tự kết nối cùng origin) |
| GET | `/api` | text danh sách API |
| GET | `/data` | JSON telemetry |
| POST | `/cancel` | hủy countdown/alarm → snooze |
| POST | `/test_hw` | buzzer test 2 s |
| POST | `/clear_nvs` | reset threshold=25, falls=0, steps=0 |
| POST/GET | `/set_thresh?val=25` | đổi ngưỡng 10..60, lưu NVS |
| POST/GET | `/set_time?epoch=...` | đồng bộ giờ hệ thống từ dashboard (Unix epoch), dùng khi không có NTP |
| POST/GET | `/capture?seconds=60` | stream CSV IMU 50 Hz ra USB Serial cho Edge Impulse; `on=0` để dừng |

JSON `/data` (key khớp `realtime.html`):

```json
{
  "state": "IDLE",
  "bpm": 75.0,
  "spo2": 98,
  "raw_bpm": 75.0,
  "raw_spo2": 98,
  "acc": 9.81,
  "thresh": 25.0,
  "max30102": true,
  "lead_off": false,
  "falls": 0,
  "fps": 49.5,
  "steps": 1420,
  "distance_km": 0.994,
  "calories": 42.6,
  "battery_v": 3.94,
  "battery_pct": 88,
  "ram_pct": 42.0,
  "buzzer": false,
  "motor": false,
  "snooze_sec": 0,
  "cd_sec": 0,
  "mpu": true,
  "finger": true,
  "ppg_motion": false,
  "ai_label": "n/a",
  "ai_conf": 0.0,
  "ai_fall": false
}
```

Ghi chú: key `max30102` được giữ để tương thích HTML, dù phần cứng là **MAX30100**.
`ai_label`/`ai_conf`/`ai_fall` là kết quả Edge Impulse (mặc định `n/a` khi `ENABLE_EDGE_AI=0`).

### 7.3 Ghi chú an toàn

- Telegram đã bị bỏ; không có token/chat ID trong firmware hay HTML.
- Cảnh báo chỉ tại chỗ (buzzer active + OLED). Không có GPS.
- Dashboard/API vẫn mở trong LAN; chỉ dùng trong mạng tin cậy.

## 8. HTML

- `realtime.html`: dashboard live mới, **tự chứa** (inline CSS/JS, không CDN, không cần Internet), polling `/data` mỗi 200–250 ms; có HR/SpO2, raw vs filtered, trạng thái FSM, countdown/alarm, pin, bước chân, accelerometer, threshold, cancel/test/clear.
- Firmware **nhúng `realtime.html`** qua `board_build.embed_txtfiles` và phục vụ tại `GET /`. Mở trực tiếp `http://192.168.4.1/` (AP) hoặc IP STA.
- Mở file local vẫn được: dashboard hiện ô nhập host; nhập `192.168.4.1` hoặc IP STA.
- `vtt.html`: testbench mô phỏng OLED/FSM/countdown/lead-off/battery; vẫn dùng Tailwind CDN nên cần Internet để hiển thị đầy đủ.
- `simulation.html`: bản mô phỏng cũ, trùng chức năng với `vtt.html`; hiện vẫn giữ, có thể xóa nếu không cần.
- Dashboard tự gửi `/set_time?epoch=...` khi mở (và mỗi 10 phút) để đồng bộ giờ cho OLED, kể cả khi board ở AP không có Internet.
- `index.html`: trang chủ GitHub Pages (giới thiệu dự án, ảnh minh họa dashboard PC/điện thoại, pinout, trạng thái). **Không còn chế độ demo** trong `realtime.html`.
- Dashboard live chạy trên board: mở `http://<STA-IP>/` (IP in ở Serial `[NET] STA IP`; cần cùng WiFi `vtt`) hoặc `http://192.168.4.1/` khi AP fallback. GitHub Pages chỉ là trang giới thiệu tĩnh; trình duyệt HTTPS không thể gọi thẳng board HTTP trong mạng riêng.
- Test UI không cần board: `python tools/mock_server.py --port 8000` rồi mở `http://127.0.0.1:8000/`; mock tự chạy FSM IDLE → COUNTDOWN → ALARM → SNOOZE.

Cách dùng dashboard:

1. Nạp firmware.
2. Kết nối WiFi máy tính vào `BioBand-Setup` (mật khẩu `bioband123`) hoặc cùng LAN với STA.
3. Mở `http://192.168.4.1/` (hoặc mở `realtime.html` và nhập IP).
4. Dashboard tự poll; bấm **Kết nối** nếu mở từ file local.

## 9. Build

```bash
pio run -e esp32-s3-super-mini
pio run -e esp32-s3-super-mini -t upload
pio device monitor
```

Cấu hình trong `platformio.ini`:

- Env: `esp32-s3-super-mini`
- Board: `esp32-s3-devkitc-1` (PlatformIO chưa có board id Super Mini)
- Flash: 4 MB (`board_upload.flash_size = 4MB`)
- Partition: `default.csv` (app 1.25 MB x2, spiffs 1.4 MB)
- USB CDC on boot: bật
- Web dashboard: `board_build.embed_txtfiles = realtime.html`; sửa HTML xong phải build lại thì firmware mới phục vụ bản mới.
- Libraries:
  - Adafruit SSD1306, Adafruit GFX, Adafruit MPU6050
  - ArduinoJson 6.x
  - https://github.com/oxullo/Arduino-MAX30100.git (MAX30100lib)
  - (tuỳ chọn) Edge Impulse Arduino library export, đặt trong `lib/bioband_inferencing`, bật `-DENABLE_EDGE_AI=1`

Lưu ý: log build vẫn in `8MB Flash` ở dòng HARDWARE do tên board DevKitC-1; partition thực tế là 4 MB (app max 1,310,720 bytes).
Build hiện tại: RAM **48,700 / 327,680** (14.9%), flash **939,889 / 1,310,720** (71.7%, đã gồm dashboard).

## 10. Quyết định quan trọng (không làm lại từ đầu)

- Pinout theo dây thực tế: nút **GPIO2**, buzzer **GPIO3**, I2C 8/9; **không** dùng các pinout cũ 5/4, 17/18, 35/36, 40/41.
- I2C dùng chung 8/9; thư viện MAX30100lib `MAX30100::begin()` gọi `Wire.begin()` mặc định của variant S3 = 8/9. Nếu đổi pin I2C, phải chỉnh wrapper/patch thư viện.
- Module thực tế là **MAX30100** (part ID **0x11**); firmware dùng MAX30100lib, sampling 100 Hz, BeatDetector/SpO2Calculator. Nếu thay module MAX30102/30105 (0x15) thì phải đổi driver SparkFun.
- MAX30100lib `begin()` đặt I2C **400 kHz**; luôn gọi lại `Wire.setClock(100000)` sau khi cấu hình. Không bỏ đoạn này.
- FIFO MAX30100 có thể kẹt đầy với `wr==rd`; giữ nguyên cơ chế phát hiện + xả 16 mẫu + `resetFifo()` trong `src/sensors.cpp`.
- LED current chốt **11 mA / 11 mA**; 50 mA/27 mA bão hòa trên module hiện tại.
- Buzzer là **active**, GPIO3, điều khiển bằng `digitalWrite(HIGH/LOW)`, không dùng `tone()`.
- Nút nhấn active-low **GPIO2**; nút **BOOT GPIO0** là fallback; GPIO1 hiện để trống.
- Công tắc MSK-12D19 là công tắc nguồn; không có GPIO.
- Không có motor; `motor` trong JSON luôn `false`.
- Ngưỡng cảnh báo chốt 25 m/s².
- Edge AI dùng **Edge Impulse**, mặc định tắt (`ENABLE_EDGE_AI=0`). AI chỉ được phép **promote** một kết quả rule-based mơ hồ (variance trung gian) khi label `fall` đạt confidence ≥ 0.8; AI **không được hủy** một ca đã được rule xác nhận. Rule-based vẫn là lớp an toàn.
- Capture mode in CSV 50 Hz qua `/capture`; synthetic data chỉ dùng test pipeline, không dùng để đánh giá độ chính xác thật.
- HTML là nguồn yêu cầu UI; firmware đã khớp các key JSON của `realtime.html`.
- Dashboard `realtime.html` được nhúng vào firmware bằng `board_build.embed_txtfiles` và phục vụ tại `/`; HTML tự chứa, không CDN. Sửa HTML phải build lại.
- OLED bỏ dải IR/RED và footer MPU/MAX/F; giữ HR/SpO2 + icon; thêm giờ/ngày/WiFi/steps/voltage. Giờ lấy từ NTP khi STA có Internet, hoặc dashboard gửi `/set_time` khi mở web; chưa có nguồn giờ thì `--:--`.
- `/set_time?epoch=...` là endpoint đồng bộ giờ từ dashboard; không cần Internet/NTP. Dashboard gửi lúc mở và mỗi 10 phút.
- WiFi chỉ 2.4 GHz; `include/secrets.h` (gitignore) giữ SSID/password. Nếu STA fail, fallback AP `BioBand-Setup`.
- Code cũ/test/Wokwi/agent prompts đã bị xóa; không khôi phục lại trừ khi có yêu cầu.

## 11. Checklist test trên board thật

1. Nạp firmware, mở Serial 115200.
2. Xác nhận I2C: `[I2C] 0x3C OK`, `0x68 OK`, `0x57 OK`; `[MPU6050] ready` và `[MAX30100] ready`. Nếu thiếu `0x57`, power-cycle board/module rồi thử lại.
3. WiFi: nếu `vtt` phát 2.4 GHz và có Internet, log có `[NET] STA IP ...`; nếu không, log `[NET] AP IP 192.168.4.1`. OLED hiện cột WiFi (bars) hoặc `AP`.
4. OLED: boot screen → `LEAD-OFF` khi chưa đặt tay → màn chính HR/SpO2 + giờ/ngày + steps/voltage khi đặt tay. Không có MAX → `MAX30100 NOT FOUND`.
5. Nút: nhấn ngắn trong countdown/alarm → snooze; giữ 3 giây → panic SOS. Ở IDLE, nhấn ngắn → OLED `BUTTON OK`. Nếu `[BTN] GPIO2=0` khi không nhấn, kiểm tra chập GND/đấu chân tactile; dùng nút BOOT onboard (GPIO0) để test.
6. Buzzer: test 2 s qua web hoặc `/test_hw`; kiểm tra mức kích.
7. Pin: so `battery_v` với đồng hồ VOM; hiệu chuẩn LUT nếu lệch.
8. Web: mở `http://<IP>/` (AP `192.168.4.1` hoặc STA IP) thấy dashboard mới; kiểm tra `/api`, `/data`, `/cancel`, `/test_hw`, `/clear_nvs`, `/set_thresh`.
9. HR/SpO2 với tay thật: áp đầu ngón tay lên ô chip MAX30100, giữ yên; `finger=1`, IR ~18k–20k, PI ~2–3%, HR/SpO2 hiện trên OLED và dashboard. Bỏ tay → `LEAD-OFF`.
10. FSM: lắc/thả rơi để test free-fall/impact; kiểm tra countdown và hủy.
11. PPG noise: lắc tay/đi lại → OLED hiện `MOVING / HOLD STILL / PPG LOCKED`, dashboard PPG = `MOVING`, HR/SpO2 về `--`; giữ yên ~4–5 s → có lại kết quả.
12. Telegram đã bỏ; kiểm tra không còn log/token Telegram trong firmware/HTML.
13. Kiểm tra boot khi pin yếu và khi cắm USB + pin (nguồn/backfeed).
14. Capture: gọi `/capture?seconds=10`, kiểm tra Serial ra đúng 6 cột CSV ở 50 Hz; dừng bằng `/capture?on=0`.
15. Edge AI: sau khi có model, kiểm tra `/data` có `ai_label`/`ai_conf`; thử với dữ liệu thật và synthetic; xem AI chỉ promote ca mơ hồ, không hủy alarm rule-based.
16. Raw vs filtered: chạy `tools/log_telemetry.py`, giữ yên → lắc tay → giữ yên; kiểm tra raw spike/jitter và filtered `--`/ổn định; so với máy đo tham chiếu.

## 12. Edge AI (Edge Impulse)

### 12.1 Trạng thái tích hợp

- `src/ai_model.cpp` đã có wrapper Edge Impulse nhưng nằm sau `#if ENABLE_EDGE_AI`; mặc định `0` trong `platformio.ini`.
- `aiPushSample()` được gọi mỗi mẫu MPU 50 Hz trong `src/main.cpp`; khi bật, nó đầy buffer cửa sổ, chạy `run_classifier()`, cập nhật `ai_label`, `ai_conf`, `ai_fall`.
- Kết quả AI đi vào telemetry/`/data` và item **Edge AI** của `realtime.html`.
- `src/fsm.cpp` chỉ dùng AI để promote ca variance trung gian khi `fall` ≥ 0.8; không dùng AI để hủy alarm đã được rule xác nhận.
- Chưa có model thật trong repo; cần export từ Edge Impulse.

### 12.2 Thiết kế Edge Impulse đề xuất

- Tên project: **`bioband`** để header export là `bioband_inferencing.h` (nếu tên khác, sửa include trong `src/ai_model.cpp`).
- Input: 6 axis `ax,ay,az,gx,gy,gz`, **50 Hz**, cửa sổ **2 s = 100 mẫu**; stride 0.5 s.
- Labels ban đầu: `fall` và `adl` (có thể mở rộng `idle`, `walk`, `sit`, `lie`).
- Impulse: Raw/Spectral Analysis + 1D-CNN hoặc MLP nhỏ; quantized **int8**, EON compiler; mục tiêu model <100 KB, inference <100 ms.
- Dữ liệu thật: 10–20 phút/nhãn, nhiều người, té trên đệm; ADL gồm đi, đứng lên, ngồi xuống, cúi nhặt, nằm, lắc tay.

### 12.3 Thu dữ liệu thật từ thiết bị (hướng ưu tiên)

Đây là hướng tốt nhất cho accuracy: dùng chính vòng tay, đúng vị trí đeo, đúng cảm biến và đúng tần số 50 Hz. Public dataset (WEDA/HIFD) chỉ nên dùng để pretrain/augmentation nếu chưa có đủ người tham gia.

Công cụ có nhãn: `tools/capture_labeled.py` (cần `pip install pyserial`).

```bash
pip install pyserial
python tools/capture_labeled.py --list-ports
python tools/capture_labeled.py --host 192.168.4.1 --port COM5 --label fall --subject S01 --trials 10 --seconds 10
python tools/capture_labeled.py --host 192.168.4.1 --port COM5 --label adl  --subject S01 --trials 15 --seconds 10
```

- Kết nối PC với AP `BioBand-Setup` (IP `192.168.4.1`) hoặc STA; truyền IP qua `--host`.
- Tool mở serial trước, gọi `/capture?seconds=10`, đọc CSV 50 Hz, thêm timestamp và lưu:
  `dataset/training/<label>/<label>_<subject>_<trial>.csv`.
- Sau mỗi trial tool gọi `/capture?on=0`, đóng/mở cổng an toàn và in số mẫu đã lưu.
- Không mở serial monitor/Data Forwarder khác trong lúc tool đang đọc cổng.

Protocol thu data tối thiểu:

- 3–5 người, mỗi người 10–20 cú té mô phỏng (trước/sau/sang trái/sang phải, có/không vấp) trên **đệm**, có giám sát; không thử té thật gây chấn thương.
- 10–15 phút ADL/người: đi bộ, đứng lên, ngồi xuống, cúi nhặt, nằm xuống, lăn, vung tay, đóng cửa, ngồi xuống ghế.
- Mỗi trial 10 s; sự kiện té/ADL nằm trong 2–4 s đầu sau khi bắt đầu capture; 10 s giúp có pre/post context.
- Chia train/test theo **người** (leave-one-subject-out), không chia ngẫu nhiên theo cửa sổ.
- Ghi nhãn nhất quán `fall` / `adl`; nếu mở rộng thì `idle`, `walk`, `sit`, `lie`.

Sau khi thu:

```bash
python tools/upload_dataset.py --dry-run
set EI_API_KEY=ei_xxxxxxxx
python tools/upload_dataset.py --split training --label all
```

(Trong repo hiện có `tools/upload_dataset.py`; dùng `--dry-run` trước khi upload thật.)

Nếu chưa có người để thu: có thể tham khảo [WEDA-FALL](https://github.com/joaojtmarques/WEDA-FALL) (cổ tay, 50 Hz) và [HIFD](https://github.com/nhoyh/HR_IMU_falldetection_dataset) (cổ tay, HR + IMU, 50 Hz), hoặc [SisFall](https://www.mdpi.com/1424-8220/17/1/198) (thắt lưng, ~200 Hz). Phải kiểm tra license, format, đơn vị và domain shift; không có model pretrained nào khớp hoàn toàn với Bio-Band.

Cách thay thế không cần tool: dùng Edge Impulse **Data Forwarder** đọc trực tiếp CSV 50 Hz, chọn 6 axes và gắn nhãn trong Studio. Cách này cũng cần dừng capture bằng `/capture?on=0` và không mở serial monitor khác.

Đơn vị: accel m/s², gyro rad/s. Capture mode chiếm Serial nên chỉ dùng một công cụ đọc cổng tại một thời điểm.

### 12.4 Synthetic data (fake) để test pipeline

- `python tools/generate_synthetic_imu.py` tạo `dataset/training|testing/fall|adl/*.csv` (mặc định 160 cửa sổ, 16.000 dòng; seed cố định). Mỗi file có header `timestamp,ax,ay,az,gx,gy,gz` và timestamp tính bằng ms.
- `python tools/upload_dataset.py --dry-run` để xem lệnh; sau đó đặt `EI_API_KEY` và bỏ `--dry-run`.
- Cần Edge Impulse CLI: `npm install -g edge-impulse-cli`. Bản CLI cục bộ hiện có thể bị lỗi module; cài lại trước khi upload.
- **Cảnh báo:** dữ liệu synthetic chỉ để test pipeline (capture → upload → train → export → inference). Model train bằng fake data sẽ không tổng quát hóa cho người thật; không dùng để đánh giá hay triển khai phát hiện té ngã thật.

### 12.5 Train và deploy

1. Upload data (thật hoặc synthetic) vào project Edge Impulse `bioband`.
2. Tạo impulse 50 Hz / 6 axes / 2 s; train; xem confusion matrix, latency, model size.
3. Deployment → **Arduino library** (int8/EON) → tải zip.
4. Giải nén vào `lib/bioband_inferencing/` (giữ `library.properties` và thư mục `src`).
5. Trong `platformio.ini`, đổi `-DENABLE_EDGE_AI=0` thành `1`; build/nạp.
6. Nếu vượt app partition 1.25 MB, đổi `board_build.partitions = huge_app.csv` (3 MB app, mất OTA) hoặc giảm model.

### 12.6 Hành vi AI và an toàn

- Inference chạy trên ESP32-S3, không dùng cloud/MCP lúc runtime.
- Khi `ENABLE_EDGE_AI=0`: `aiPushSample` là no-op, `ai_label` = `n/a`.
- Khi bật: buffer đầy sau 2 s; inference lặp mỗi 25 mẫu (0,5 s); model chạy trong loop nên có thể làm chậm sampling trong lúc suy luận.
- AI chỉ promote ca mơ hồ; alarm rule-based và nút hủy vẫn là lớp an toàn. Không dùng AI làm thiết bị y tế.
- MCP chỉ hữu ích để tự động hóa capture/upload/train/đo; inference vẫn nằm trên ESP32.

## 13. Nếu tiếp tục ở session khác

1. Đọc file này.
2. Đọc `include/board_config.h`, `include/app_state.h`, `src/main.cpp`.
3. Build lại bằng `pio run -e esp32-s3-super-mini`.
4. Không tự ý đổi pinout; nếu đổi, cập nhật cả `board_config.h`, `README.md`, HTML labels và ghi chú phần cứng.
5. Nếu thêm module mới, giữ pattern: extern state trong `app_state.h`, prototype trong header riêng, implementation trong `src/`.
6. Nếu MAX30100 không nhận, kiểm tra part ID `0x11`, địa chỉ I2C `0x57`, nguồn 3.3V; nếu chip thực tế là MAX30102/30105 (0x15) thì cần driver SparkFun.
