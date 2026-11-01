# CLAUDE HANDOFF — Bio-Band ESP32-S3 (2026-11-02)

> Đọc file này trước, rồi `README.md` (kiến trúc, API, build), `BAO_CAO.md` (toàn bộ nội dung AI và kết quả) và `PLAN.md` (tiến độ).
> Repo: https://github.com/vtt132109/vong-tay-thong-minh · Dashboard từ xa: `…/remote.html` (GitHub Pages).

## 0. TL;DR

- **Board đang cắm USB (COM13)** và chạy firmware hiện tại: CPU 160 MHz, WiFi `Tiến Tài 1` (2,4 GHz), MQTT online, MLP + CNN int8 chạy trên chip, `[SELFTEST] PASS`.
- **AI hoàn chỉnh ở mức làm được bằng dữ liệu công khai** (HIFD, 21 người): LOSO, so sánh 11 mô hình, ablation, hardware-in-the-loop. Điểm vận hành đã nạp (ngưỡng 0,87): 99/104 ca ngã, 0 báo nhầm trong 1,95 giờ. Chi tiết và hạn chế: `BAO_CAO.md` mục 6 và 11.
- **Báo động bằng AI là công tắc runtime, mặc định TẮT** (`POST /ai_mode?val=1` hoặc nút trên dashboard LAN; lưu NVS). Đừng bật mặc định cho đến khi có số liệu từ người đeo thật (PLAN.md GĐ E).
- Việc còn lại **cần người/phần cứng**: sửa dây nút GPIO2, hàn pin + ADC, thử ngã trên đệm có giám sát, đo dòng, slide/poster/video, đổi mật khẩu WiFi `vtt` cũ, quyết định xóa NVS (`falls=18`).

## 1. Những điều dễ sai (đã trả giá một lần)

- **SSID phân biệt chữ hoa/thường**: mạng thật là `Tiến Tài 1`, không phải `tiến tài 1`. Quét WiFi trong firmware đã được sửa (ngắt kết nối trước khi quét) và in danh sách mạng khi STA lỗi.
- **Console Windows cp1252** làm `monitor_serial.py` cũ crash khi in SSID có dấu → script đã dùng UTF-8. Khi chạy lệnh qua pipe, đặt `PYTHONIOENCODING=utf-8`.
- **Không chạy hai `pio run` cùng lúc** trong cùng thư mục (lỗi liên kết ngẫu nhiên). `tools/thermal_test.py` và `hil_eval.py` giữ cổng COM13: không nạp/đọc Serial song song.
- **`uv pip install` trên ổ D: đôi khi tạo gói rỗng** (thư mục `*.dist-info` có nhưng không có mã): dùng `--reinstall --link-mode copy`.
- **Công cụ sửa file qua script Python**: ký tự `\n` trong chuỗi C bị diễn giải thành xuống dòng thật khi gửi qua shell; dùng công cụ Edit/Write hoặc `chr(92)`.
- **Replay/HIL** đã được làm để không đổi bộ đếm ngã/bước trong NVS (bản đầu đã làm `falls` 18 → 25; đã khôi phục bằng `#SETCOUNTS,18,187`). Giá trị 18/187 là số gốc của người dùng, chưa rõ nguồn gốc — hỏi trước khi xóa.
- Ổ D: còn ít dung lượng (~8 GB); không cài thêm gói nặng.

## 2. Kiến trúc AI (tóm tắt)

- Vòng 50 Hz → hiệu chỉnh gyro → loại trọng lực (high-pass α 0,98) → bộ đệm 100×6 trượt 25 mẫu → **MLP-42** (`include/tiny_fall_model.h`) và **CNN 1D int8** (`include/cnn_fall_model.h`, kernel `src/ai_cnn.cpp`) → trung bình xác suất, ngưỡng 0,87 → `aiFall`, `aiMax6s`.
- `fsm.cpp`: khi `aiAlarmEnabled`: (A) `aiFall` → COUNTDOWN ngay; (B) luật hiệu chỉnh (1,5 s / 2 s / phương sai < 0,8) cần `aiMax6s ≥ 0,5`. Khi tắt: chỉ luật gốc.
- Các file `include/*_model.h`, `selftest_vectors.h` **sinh tự động** bởi `tools/ai_lab/export_final.py` từ `dataset/ai_results/fusion.json`; đừng sửa tay.
- Self-test khi khởi động và `tools/ai_lab/hil_eval.py` phải khớp numpy; nếu đổi mô hình, chạy lại cả hai.
- Pipeline: `tools/README.md`. Kiểm thử: `python -m pytest tests -q` (8 test). CI: `.github/workflows/ci.yml`.

## 3. Phần cứng thực tế

| Chức năng | Chân | Ghi chú |
|---|---|---|
| I2C | GPIO 8/9, 100 kHz | OLED 0x3C, MPU6050 0x68, MAX30100 0x57 |
| Nút ngoài | GPIO 2 | đọc LOW khi nhả (lỗi dây); BOOT (GPIO 0) là dự phòng |
| Còi | GPIO 3 | HIGH = kêu |
| ADC pin | chưa gán | chờ hàn pin |

MAX30100: LED 11 mA, I2C ép về 100 kHz, tự xả FIFO khi đầy. Đo ở đầu ngón tay.

## 4. Quy tắc an toàn khi làm tiếp

- Không bật báo động bằng AI mặc định; không dùng số liệu HIFD để khẳng định độ chính xác y tế.
- Không thêm lại lệnh điều khiển qua MQTT công khai (hủy báo động, xóa dữ liệu, đổi ngưỡng) — đã loại có chủ đích.
- Không test còi/động cơ mà không báo trước người dùng; không thử ngã thật không có đệm và người giám sát.
- Không đưa `include/secrets.h`, khóa API hoặc dữ liệu HIFD thô (`dataset/`) lên repo.
- Không đổi pinout/ngưỡng 25 m/s²/cờ AI mà không hỏi.

## 5. Lệnh thường dùng

```bash
pio run -e esp32-s3-super-mini -t upload --upload-port COM13
python tools/monitor_serial.py --seconds 30
python tools/mqtt_peek.py                    # telemetry mới nhất qua broker
python tools/ai_lab/hil_eval.py --port COM13 # đưa 1942 cửa sổ HIFD qua chip
python -m pytest tests -q
```

_Handoff cập nhật 2026-11-02 sau khi hoàn tất AI (LOSO, CNN int8, HIL), bảo mật MQTT/HTTP, cấu hình WiFi qua web và hạ xung CPU._
