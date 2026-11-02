# Bio-Band — Kế hoạch và tiến độ (tập trung AI)

> Cập nhật 2026-11-02. Tài liệu tổng hợp để đọc/báo cáo: [`BAO_CAO.md`](BAO_CAO.md). Cột **Ai**: `C` = Claude làm được, `B` = bạn làm (phần cứng, thử nghiệm có người, quyết định).
> `[x]` = đã xong và đã kiểm tra · `[ ]` = còn lại. Quyết định đã chốt: không làm kênh thông báo, không có người tham gia thu dữ liệu (nên các việc dữ liệu riêng của Bio-Band để lại), làm 1D-CNN, hạ xung CPU.

## Tóm tắt trạng thái

AI đã hoàn chỉnh ở mức có thể làm được **chỉ bằng dữ liệu công khai**: pipeline tái lập, đánh giá leave-one-subject-out 21 người, so sánh 11 mô hình, ablation, CNN int8 chạy trên chip, kiểm chứng hardware-in-the-loop. Điều **chưa thể làm nếu không có người đeo thật**: đo báo nhầm/giờ ngoài đời và recall trên dữ liệu Bio-Band (GĐ E). Vì vậy báo động bằng AI vẫn là công tắc mặc định TẮT.

## GĐ A — Nền tảng đánh giá ✔

- [x] A1 Sửa lỗi khởi tạo min/max trong `ai_model.cpp`; sửa quét WiFi.
- [x] A2 `tools/requirements.txt`, `tools/README.md`; bỏ phụ thuộc cổng COM cứng trong `monitor_serial.py`.
- [x] A3 Metric theo sự kiện: phát hiện trong ±2 s quanh va đập, mọi cảnh báo khác là báo nhầm (`evalx.event_report`).
- [x] A4 Báo nhầm mỗi giờ + khoảng tin cậy Wilson/Poisson.
- [x] A5 LOSO 21 người, nhiều seed (MLP 3, CNN 3).
- [x] A6 Ngưỡng có biên: ngưỡng cao nhất còn giữ recall ≥ 95 % với ≤ 1 báo nhầm (0,87).
- [x] A7 Đặc trưng: đã có bộ đặc trưng bất biến theo hướng (so sánh, không dùng cho bản nạp). *Còn:* bỏ đặc trưng trùng `mag_peak_abs` (giữ nguyên để không đổi hợp đồng đặc trưng; ghi chú trong báo cáo).
- [x] A8 Self-test trên chip (6 cửa sổ) + hardware-in-the-loop qua USB (1942 cửa sổ).
- [x] Kiểm thử tự động: `tests/` (8 test), CI GitHub Actions (build + pytest).

## GĐ B — Thu hẹp khác biệt HIFD và Bio-Band ✔ (phần làm được bằng mô phỏng)

- [x] B1 Dựng gia tốc thô từ quaternion, qua đúng chuỗi firmware, đo khoảng cách miền (92 → 98/104 sau khi sửa).
- [x] B2 DLPF 21 Hz, giới hạn ±16 g, độ lệch gyro, vào mô phỏng.
- [x] B3 Tăng cường xoay hệ trục ±30° + độ lệch gyro; đặc trưng bất biến theo hướng.
- [x] B4 Huấn luyện lại trên tín hiệu giống firmware.
- [x] B5 Hiệu chỉnh bias gyro khi khởi động. *Không nâng DLPF*: mô phỏng không cho thấy cần thiết.

## GĐ C — So sánh mô hình và ablation ✔

- [x] C1 Mốc so sánh: ngưỡng đơn, FSM luật (mô phỏng nguyên văn firmware), hồi quy logistic, cây, random forest, MLP, CNN 3 kích cỡ.
- [x] C2 Đo trên ESP32-S3: MLP 0,42 ms, CNN 4,2 ms (160 MHz).
- [x] C3 Ablation: nhãn theo sự kiện (quyết định), hard-negative, trọng số lớp, đặc trưng phương sai cuối.
- [x] C4 Chọn mô hình theo đánh đổi (độ chính xác – kích thước – thời gian): tổ hợp MLP + CNN 8-16-16.
- [ ] C5 *(tùy chọn)* Độ dài cửa sổ 1,5 / 3 s (cần xây lại cửa sổ + firmware; chưa có lý do để đổi).

## GĐ D — Kết hợp luật + AI trên thiết bị ✔

- [x] D1 Mô phỏng 5 cách hợp nhất trên HIFD (người 16–21); chọn "AI HOẶC (FSM hiệu chỉnh VÀ AI ≥ 0,5)": 31/31 ca ngã, 1 báo nhầm/0,5 giờ.
- [x] D2 Debounce k-of-n: đã thử (2/3, 2/2, 3/4); không có lợi (+0,5 s trễ cho cùng đánh đổi) → mặc định 1/1 (cấu hình được).
- [x] D3 Cài vào `fsm.cpp` dưới dạng công tắc runtime (NVS, mặc định TẮT), có cooldown 30 s.
- [x] D4 Xác suất MLP/CNN, thời gian suy luận, trạng thái công tắc, tự kiểm tra: có trong `/data` và MQTT.

## GĐ E — Dữ liệu từ chính Bio-Band (cần người) ⏸

Không có người tham gia nên chưa làm. Công cụ đã sẵn sàng.

- [x] E1 `capture_labeled.py`: không ghi đè, `--start-index`, không reset board khi mở cổng.
- [ ] E2 (C) Chế độ ghi liên tục khi đeo thật kèm xác suất AI để đo báo nhầm/giờ.
- [ ] E3 (B) Mẫu đồng ý + quy trình an toàn (đệm dày, người giám sát).
- [ ] E4 (B) Thu 3–5 người: ngã 4 hướng, hoạt động khó (ngồi phịch, vỗ tay, đập bàn), 1–2 giờ đeo thật.
- [ ] E5 (C) Đánh giá chéo bộ dữ liệu, fine-tune, LOSO trên dữ liệu Bio-Band.
- [ ] E6 (C+B) Mở cổng báo động bằng AI mặc định nếu đạt chỉ tiêu: recall ≥ 85 % và ≤ 1 báo nhầm/giờ đeo thật.

## GĐ F — Giải thích và trực quan hóa ✔

- [x] F1 Đường cong vận hành, ablation (`docs/figures/`).
- [x] F2 Xác suất AI theo thời gian quanh va đập (ngã, vỗ tay, giường, đi bộ).
- [x] F3 Độ quan trọng đặc trưng (permutation).
- [x] F4 Phân tích ca lỗi: bỏ sót chủ yếu là các ca ngã nhẹ của người 1, 3, 14, 17, 21; báo nhầm chủ yếu là vỗ tay.
- [x] F5 Dashboard: xác suất MLP/CNN, ngưỡng, thời gian, biểu đồ 60 giây, công tắc báo động bằng AI.

## GĐ G — Đóng gói ⏳

- [x] G1 `BAO_CAO.md`, `README.md`, `tools/README.md`, `docs/results_tables.md` cập nhật theo số liệu thật.
- [ ] G2 (B) Slide, poster, video demo — nội dung đã có trong `BAO_CAO.md`; cần làm theo mẫu của cuộc thi.
- [ ] G3 (C+B) Kịch bản demo trực tiếp: (1) dashboard LAN, nút bật AI; (2) đặt tay lắc/vỗ vào cổ tay để thấy xác suất AI trên dashboard; (3) ngã trên đệm có người giám sát khi đã bật AI.
- [ ] G4 (C) Bộ câu hỏi giám khảo: khác biệt miền dữ liệu, mẫu nhỏ, vì sao không chỉ dùng ngưỡng, vì sao AI mặc định tắt, bảo mật MQTT. (Trả lời nằm ở mục 6 và 11 của báo cáo.)

## Vận hành, bảo mật và phần cứng

- [x] Xung CPU 160 MHz (mặc định), modem sleep, OLED 2 Hz khi bình thường; có thể đặt `-DBIO_CPU_MHZ=80|160|240`.
- [x] Cấu hình WiFi không cần nạp lại (`/wifi` trên AP `BioBand-Setup`); mật khẩu AP dẫn xuất từ MAC.
- [x] MQTT chỉ publish; HTTP có header `X-Bioband` và không CORS; `/set_time` bỏ qua khi đã có NTP.
- [x] Health guard chờ 20 giây; NVS ghi ngưỡng mặc định; `lead_off`/dashboard remote sửa lỗi (retained, mất liên lạc khi ALARM, `localStorage`).
- [x] Di chuyển `vtt.html`, `simulation.html` sang `legacy/`; sửa chữ lỗi thời ở `index.html`.
- [ ] (B) Sửa dây nút GPIO2 (khi nhả phải đo ~3,3 V).
- [ ] (B) Hàn pin + cầu phân áp 100k/100k + 100 nF vào GPIO1; (C) gán `PIN_BATTERY_ADC`, hiệu chuẩn; kiểm tra backfeed TP4057.
- [ ] (B+C) Đo dòng tiêu thụ thật với pin; ước tính thời gian dùng.
- [ ] (B) Đổi mật khẩu WiFi `vtt` cũ (từng nằm trong lịch sử git công khai).
- [ ] (B) Quyết định: có xóa NVS (`falls=18`, `steps=187`) không; broker MQTT riêng hay giữ công khai.
- [ ] (C) OLED cập nhật một phần để bỏ độ trễ vòng lặp ~35 ms mỗi 0,5 giây; QAT cho CNN.
- [ ] (B) Vỏ và dây đeo cố định hướng MPU6050; thử đo PPG ở cổ tay.

## Chỉ tiêu và thứ tự đề xuất tiếp theo

| Chỉ tiêu | Mục tiêu | Hiện tại |
|---|---|---|
| Recall theo sự kiện (HIFD, LOSO) | ≥ 90 % | **95,2 %** (CI 0,89–0,98) |
| Báo nhầm (HIFD, LOSO) | ≤ 1/giờ | **0 trong 1,95 giờ** (giới hạn trên 1,9/giờ) |
| Suy luận / bộ nhớ | < 5 ms / < 20 KB | 0,42 + 4,2 ms / ~5 KB trọng số |
| Recall trên dữ liệu Bio-Band | ≥ 85 % | chưa đo (GĐ E) |
| Báo nhầm khi đeo thật | ≤ 1/giờ | chưa đo (GĐ E) |

1. (B) Sửa nút GPIO2, quyết định NVS và đổi mật khẩu WiFi — 10 phút.
2. (B) Chuẩn bị slide/poster/video theo mẫu cuộc thi từ `BAO_CAO.md`.
3. (B+C) Thử ngã trên đệm có giám sát khi đã bật báo động bằng AI; ghi `[TINY-AI]` và `/data` để có số liệu thật đầu tiên.
4. (B+C) Hàn pin, đo dòng, thử PPG ở cổ tay.
5. (B) Nếu có người: GĐ E.

## Giai đoạn tiếp theo (kế hoạch chi tiết)

> Lập 2026-11-02. Chỉ gồm việc Claude (C) làm được **không cần người đeo và không cần phần cứng mới**. Code/tài liệu giao Sonnet, việc đồng bộ tài liệu cơ học giao Haiku (theo `CLAUDE.md`).
> **Điều kiện trước:** working tree đang có thay đổi chưa commit của việc khác (OTA pull: `src/main.cpp`, `src/web_api.cpp`, `src/display_ui.cpp`, `include/board_config.h`, `platformio.ini`, …). Hỏi người dùng commit/chốt phần đó **trước** khi bắt đầu N4, N5 để diff mỗi việc sạch. N1–N3 không chạm các file đó nên làm ngay được.
> Quy tắc chung: không chạy hai `pio run` cùng lúc; COM13 chỉ một công cụ dùng tại một thời điểm; không bật báo động AI, không còi, không replay ngã nếu chưa báo người dùng; không commit nếu chưa được yêu cầu.

### Thứ tự và song song

| Việc | File chạm | Song song? |
|---|---|---|
| N1 E2 ghi liên tục + tóm tắt báo nhầm/giờ | `tools/wear_log.py` (mới), `tests/test_wear_log.py` (mới) | Song song với N2, N3 |
| N2 G4 bộ câu hỏi giám khảo | `docs/HOI_DAP_GIAM_KHAO.md` (mới) | Song song với N1, N3 |
| N3 G3 kịch bản demo + kiểm tra trước demo | `docs/DEMO.md` (mới), `tools/demo_check.py` (mới), `tests/test_demo_check.py` (mới) | Song song với N1, N2 |
| N4 OLED cập nhật một phần | `src/display_ui.cpp`, `include/display_ui.h`, `src/main.cpp` | Sau điều kiện trước; viết code song song N5 được, **build/nạp tuần tự** |
| N5 Chuẩn bị mã `PIN_BATTERY_ADC` | `include/board_config.h`, `src/sensors.cpp`, `platformio.ini` (chỉ chú thích) | Như N4 |
| N6 Đồng bộ tài liệu | `tools/README.md`, `README.md`, `BAO_CAO.md`, `CLAUDE_HANDOFF.md`, `PLAN.md` | Cuối cùng, tuần tự |

Không có hai việc nào chung file, trừ N6 (gom mọi chỉnh sửa tài liệu chung vào một chỗ để tránh xung đột). N1/N3 dùng file test riêng, không sửa `tests/test_tools.py`.

### N1 — E2: ghi liên tục khi đeo kèm xác suất AI (Sonnet, ~3 giờ)

Mục đích: khi có người đeo (kể cả chính người làm), có ngay số **báo nhầm/giờ thật** — chỉ tiêu còn thiếu quan trọng nhất. Không cần sửa firmware: `/data` đã có `ai_n`, `ai_p`, `ai_mlp`, `ai_cnn`, `ai_thr`, `ai_max6`, `ai_arm`, `state`, `acc`, `steps`, `jit`; log Serial `[TINY-AI]` in mọi cửa sổ có p > 0,2 (`TINY_LOG_MIN_MS` 400 < chu kỳ 500 ms) nên đủ để đếm báo nhầm ở mọi ngưỡng ≥ 0,2. MQTT chỉ 1 Hz (mất một nửa cửa sổ) → không dùng làm nguồn chính.

- [ ] `tools/wear_log.py record --host <IP|bioband.local> --out <csv> [--hours H]`: GET `/data` mỗi 0,2 s, mỗi giá trị `ai_n` mới ghi một dòng (`t_iso, t_rel_s, ai_n, p, mlp, cnn, thr, max6, ai_arm, state, acc, steps, jit`); đếm cửa sổ hụt khi `ai_n` nhảy > 1; tự nối lại khi lỗi HTTP (ghi khoảng hở); `flush` mỗi dòng; Ctrl+C an toàn; dòng đầu ghi chú `fw`, `ai_self`, `cpu_mhz`, ngưỡng. Chỉ dùng GET, không gửi lệnh nào.
- [ ] Nguồn thay thế `--port COMx`: đọc Serial không reset (`dtr=rts=False`, như `live_ai.py`), phân tích `[TINY-AI]` và dòng chuyển trạng thái FSM; ghi rõ trong tệp là "chỉ cửa sổ p > 0,2".
- [ ] Đánh dấu hoạt động: người vận hành gõ nhãn + Enter (`ngoi`, `vo tay`, `di bo`, `ngu`…) → tệp `<out>_marks.csv` (thời điểm, nhãn).
- [ ] `tools/wear_log.py summarize <csv> [--thr 0.87] [--merge 3] [--json out.json]`: số giờ có dữ liệu (bỏ khoảng hở > 5 s), % cửa sổ hụt, số sự kiện báo (gộp < 3 s như `evalx.merge_fires`), báo nhầm/giờ + giới hạn trên Poisson 95 % (giống `evalx.poisson_upper`; import nếu nhẹ, nếu không thì viết lại và test khớp), bảng quét ngưỡng 0,5/0,6/0,7/0,8/0,87/0,9/0,95, số lần FSM vào `COUNTDOWN`, 10 sự kiện p cao nhất kèm nhãn đánh dấu gần nhất (phục vụ phân tích ca lỗi như F4).
- [ ] `tests/test_wear_log.py`: CSV tổng hợp biết trước đáp án (số sự kiện, gộp 3 s, giờ, hụt cửa sổ), parser dòng `[TINY-AI]`, quét ngưỡng đơn điệu giảm, Poisson khớp `evalx`.
- **Kiểm tra:** `python -m pytest tests -q` (8 test cũ + test mới đều qua). Thử thật 2 phút, board nằm yên trên bàn, AI tắt: `record --host <IP> --minutes 2` → ~240 dòng, hụt < 2 %, 0 sự kiện ở 0,87; `summarize` chạy ra bảng. Thử `--port COM13` 1 phút khi không có công cụ nào khác giữ cổng.
- **Hoàn thành khi:** test qua; chạy thử thật đạt các số trên; `--help` có ví dụ tiếng Việt/Anh ngắn.
- **Rủi ro hồi quy:** gần như không (công cụ mới, chỉ đọc). Chú ý poll 5 Hz không làm `jit` tăng (so `jit` trước/sau trong lúc chạy; nếu tăng thì hạ xuống 2,5 Hz — vẫn ≥ 1 lần mỗi cửa sổ 0,5 s).
- Ngoài phạm vi: ghi IMU thô trong lúc đeo mà vẫn giữ phát hiện ngã (chế độ `capture` hiện tắt phát hiện) → để GĐ E4 khi có người.

### N2 — G4: bộ câu hỏi giám khảo (Sonnet, ~2 giờ)

- [ ] `docs/HOI_DAP_GIAM_KHAO.md`: 20–25 câu, mỗi câu trả lời 2–4 câu + số liệu + trỏ mục `BAO_CAO.md`. Nhóm: (a) AI/dữ liệu — khác biệt miền HIFD ↔ MPU6050, mẫu nhỏ và khoảng tin cậy, vì sao không chỉ dùng ngưỡng (FSM gốc 6/104), vì sao MLP + CNN, int8 có làm sai không (sai lệch 0,0015, HIL 1942 cửa sổ), vì sao LOSO và đánh giá theo sự kiện, ngưỡng 0,87 chọn thế nào và vì sao hơi lạc quan, vì sao AI mặc định TẮT, nguồn báo nhầm (vỗ tay), ngã chậm/bất tỉnh; (b) hệ thống — bảo mật MQTT (chỉ publish, không lệnh điều khiển), HTTP `X-Bioband`, mật khẩu AP theo MAC, OTA có sha256, quyền riêng tư dữ liệu sức khỏe, pin chưa đo, MAX30100 ở ngón tay; (c) đóng góp, chi phí, hướng phát triển.
- [ ] Mục "Câu hỏi bẫy và điều không được nói" (không khẳng định độ chính xác y tế; không nói "đã thử trên người cao tuổi").
- **Kiểm tra:** mọi con số trong tệp phải tìm thấy trong `BAO_CAO.md` hoặc `docs/results_tables.md` (người làm grep từng số, liệt kê ở cuối tệp nguồn của từng số); không mâu thuẫn mục 6 và 11.
- **Hoàn thành khi:** đủ các chủ đề trong G4 của PLAN, mỗi số có nguồn. **Rủi ro:** chỉ là sai số liệu → chặn bằng bước grep.

### N3 — G3: kịch bản demo trực tiếp + kiểm tra trước demo (Sonnet, ~2,5 giờ)

- [ ] `docs/DEMO.md`: (1) chuẩn bị mang theo (board, cáp, laptop, hotspot 2,4 GHz, đệm dày, người giám sát); (2) checklist T-30 phút; (3) kịch bản 3–5 phút có lời thoại: OLED + HR/SpO2 đặt ngón tay → dashboard LAN (xác suất MLP/CNN, thời gian suy luận) → lắc/vỗ cổ tay khi AI TẮT để thấy p tăng mà không báo → bật AI trên dashboard → ngã trên đệm có giám sát (báo trước khán giả có còi) → đếm ngược 10 s → bấm nút BOOT hủy → dashboard từ xa qua MQTT → **tắt AI lại**; (4) phương án dự phòng: không có WiFi → AP `BioBand-Setup` 192.168.4.1 + `/wifi`; broker MQTT lỗi → chỉ dashboard LAN; ngã không kích hoạt → giải thích ngưỡng + `tools/live_ai.py`, hoặc video dự phòng (G2); (5) sau demo: tắt AI, hỏi người dùng có khôi phục bộ đếm `falls` không.
- [ ] `tools/demo_check.py --host <IP> [--mqtt]`: **chỉ đọc** (GET `/data` hai lần cách 2 s, tùy chọn `mqtt_peek.peek()`), in PASS/WARN/FAIL: `/data` trả lời và độ trễ, `fw`, `ai_self` đạt, `mpu`/`max30102` có, `ai_n` tăng, `jit` < 40 ms, `chip_c` < 60 °C, `ai_arm` (WARN nếu đang BẬT trước giờ demo), telemetry MQTT mới < 5 s. Mã thoát 0/1. Tách hàm thuần `evaluate(snap1, snap2, mqtt) -> list` để test. Kiểm tra kiểu dữ liệu thật của `ai_self` trong `web_api.cpp` trước khi viết.
- [ ] `tests/test_demo_check.py`: snapshot giả cho các ca PASS/FAIL/WARN.
- **Kiểm tra:** pytest qua; chạy `demo_check.py --host <IP>` với board thật → PASS hết (AI đang tắt). Không POST, không bật AI, không còi.
- **Hoàn thành khi:** người không biết dự án đọc `DEMO.md` làm theo được; `demo_check` chạy thật PASS. **Rủi ro:** không (file mới, chỉ đọc).

### N4 — OLED cập nhật một phần, bỏ độ trễ ~35 ms (Sonnet, ~3 giờ, cần nạp COM13)

Nguyên nhân: `display.display()` gửi cả 1024 byte qua I2C (Adafruit nâng 400 kHz trong lúc gửi) → chặn vòng 50 Hz ~35 ms mỗi lần làm mới (`jit` = 35 ms trong BAO_CAO mục 9). Cách sửa: vẽ vào bộ đệm như cũ (chỉ tốn CPU), nhưng gửi **theo trang (8 trang × 128 byte), chỉ trang thay đổi, tối đa 2 trang mỗi vòng 20 ms**.

- [ ] `display_ui.cpp`: bỏ `display.display()` trong các hàm `draw*` (trừ `renderBootScreen` và màn hình setup chạy trước `loop`); thêm bản sao bộ đệm đã gửi (1 KB) và hàm `displayFlushStep()`: so trang với bản đã gửi, gửi trang khác bằng lệnh địa chỉ cột/trang (0x21, 0x22) + dữ liệu chia khúc ≤ 32 byte qua `Wire`, `Wire.setClock(400000)` trong lúc gửi rồi trả về 100 kHz (MAX30100 cần 100 kHz). Chỉ cho `renderDisplay` vẽ khung mới khi khung trước đã gửi xong (tránh xé hình).
- [ ] `display_ui.h`: khai báo `displayFlushStep()`. `main.cpp`: gọi `displayFlushStep()` mỗi vòng sau `renderDisplay`; không đổi chu kỳ 200/500 ms.
- [ ] Cờ build `-DOLED_PARTIAL=0` để quay về `display.display()` cũ nếu có sự cố (mặc định 1).
- **Kiểm tra:** `pio run` (một mình) → nạp COM13 → `python tools/monitor_serial.py --seconds 60`: `[SELFTEST] PASS`, dòng `[DATA] … jit=` ≤ 26 ms (trước: 35), `fps` ≈ 50; so `jit` với `-DOLED_PARTIAL=0` cùng phiên. (B) nhìn OLED 1 phút: đồng hồ chạy giây, không xé/không sót chữ; màn hình LEAD-OFF ↔ chính khi đặt/nhấc ngón tay. Màn hình COUNTDOWN/ALARM (đảo màu toàn bộ, 8 trang/khung → 4 vòng = 80 ms < 200 ms) chỉ kiểm bằng `#REPLAY` có tắt còi **sau khi hỏi người dùng**, nếu không thì kiểm bằng đọc code.
- **Hoàn thành khi:** `jit` ≤ 26 ms ổn định 60 s, không lỗi hiển thị, CI build qua; cập nhật số đo vào N6.
- **Rủi ro hồi quy:** màn hình cảnh báo nhấp nháy chậm/xé hình (đã giảm bằng giới hạn "vẽ khi gửi xong" + cờ quay lui); tranh chấp I2C với MPU/MAX: không có vì cùng một task `loop`, nhưng phải trả clock về 100 kHz sau mỗi trang (nếu quên, MAX30100 đọc lỗi → kiểm `HR`/`SpO2` vẫn ra khi đặt ngón tay).

### N5 — Chuẩn bị mã cho `PIN_BATTERY_ADC` (Sonnet, ~1 giờ, chỉ build)

Hiện trạng: `readBatteryVoltage()` đã có (8 mẫu, ×2), `lipoPercent()` có bảng LUT, OLED hiện `--` khi chưa có pin. Còn thiếu: chọn chân không cần sửa code, hiệu chuẩn, lọc nhiễu, phát hiện "chưa hàn pin".

- [ ] `board_config.h`: `#ifndef BIO_BATTERY_PIN #define BIO_BATTERY_PIN -1`, `PIN_BATTERY_ADC = BIO_BATTERY_PIN`; `BIO_BATTERY_DIVIDER` (mặc định 2,0), `BIO_BATTERY_CAL` (mặc định 1,0); `static_assert` chân là -1 hoặc ADC1 GPIO 1–10 và không trùng 0/2/3/8/9.
- [ ] `sensors.cpp`: đặt suy hao 11 dB một lần (`analogSetPinAttenuation`), lấy 16 mẫu bỏ min/max, nhân hệ số chia và `CAL`, lọc EMA (α ≈ 0,2 ở 1 Hz) để % không nhảy; điện áp < 2,5 V → trả 0 (coi như chưa có pin, OLED vẫn `--`).
- [ ] `platformio.ini`: chỉ thêm dòng chú thích hướng dẫn `-DBIO_BATTERY_PIN=1 -DBIO_BATTERY_CAL=…` và cách tính `CAL = V_đồng_hồ / V_báo` (không đổi cờ build đang dùng).
- **Kiểm tra:** `pio run` mặc định (hành vi không đổi: `batt=0.00V` trên `[DATA]`), rồi `pio run` với `PLATFORMIO_BUILD_FLAGS="-DBIO_BATTERY_PIN=1"` — **chỉ build, không nạp**; build sai chân (vd. 8) phải báo lỗi `static_assert`. Có thể nạp bản mặc định cùng lúc nạp N4 (một lần nạp).
- **Hoàn thành khi:** hai bản build qua, bản mặc định chạy y như cũ; hướng dẫn hiệu chuẩn có trong chú thích. **Rủi ro:** thấp (mặc định -1 giữ nguyên đường code cũ). Việc (B) còn lại không đổi: hàn pin, cầu chia, kiểm backfeed TP4057.

### N6 — Đồng bộ tài liệu (Haiku, ~30 phút, sau N1–N5)

- [ ] `tools/README.md`: mục `wear_log.py` và `demo_check.py`. `README.md`: link `docs/DEMO.md`, `docs/HOI_DAP_GIAM_KHAO.md`. `CLAUDE_HANDOFF.md` mục 5: lệnh mới.
- [ ] `BAO_CAO.md` mục 9/11/12: thay câu "OLED chặn ~35 ms" bằng số `jit` đo được sau N4; mục 12 bỏ ý "OLED cập nhật một phần" nếu N4 xong; nêu công cụ đo báo nhầm/giờ sẵn sàng (E2). Tạo lại `BAO_CAO.docx` bằng `tools/md_to_docx.py` chỉ khi người dùng muốn.
- [ ] `PLAN.md`: tích E2, G4, phần (C) của G3 và dòng OLED; ghi QAT/C5 là "đã cân nhắc, không làm" (lý do bên dưới).
- **Kiểm tra:** link trong Markdown trỏ đúng file; số liệu khớp kết quả đo.

### Loại hoặc hoãn

- **QAT cho CNN — loại.** Lượng tử hóa sau huấn luyện đã gần như không mất gì (sai lệch xác suất trung bình float↔int8 0,0015; HIL khớp numpy). QAT phải huấn luyện lại, sinh lại header, chạy lại self-test + HIL 1942 cửa sổ: tốn công, có rủi ro, không có độ chính xác để lấy lại. Tối ưu SIMD cho CNN cũng không cần (4,2 ms/500 ms < 1 % CPU).
- **C5 cửa sổ 1,5/3 s — hoãn.** Đổi hợp đồng cửa sổ kéo theo bộ đệm firmware, đặc trưng, header tự sinh, self-test, HIL; chưa có bằng chứng cửa sổ 2 s là điểm yếu. Chỉ xem lại sau GĐ E nếu dữ liệu thật cho thấy bỏ sót/trễ do độ dài cửa sổ (khi đó làm trước dạng nghiên cứu ngoại tuyến LOSO, không đụng firmware).
- **Hoãn tới khi có pin/người:** cảnh báo pin yếu trên dashboard (cần pin thật để chọn ngưỡng); ghi IMU thô khi đeo (E4).

## Quyết định cấu hình phát hiện ngã cuối cùng

**Ràng buộc:** huấn luyện đã xong — **không thu thêm dữ liệu, không huấn luyện lại** (kể cả `export_final.py`, vì script này huấn luyện lại mô hình). Chỉ được đổi **cách kết hợp** hai xác suất đã có (MLP float, CNN int8) với đường luật FSM, và các hằng số ngưỡng. Bằng chứng: điểm LOSO đã lưu, công cụ mô phỏng FSM, replay trên chip, 5 lần ngã thật hôm nay.

### Hiện trạng đã kiểm tra lại (2026-11-02)

- Firmware: `p = (MLP + CNN)/2`, `AI_ENSEMBLE_THRESHOLD 0.87` (`include/cnn_fall_model.h`, file sinh tự động), debounce 1-of-1. `src/fsm.cpp`: **đường A** `aiFall` (p ≥ 0,87) ở trạng thái IDLE/FREE_FALL/IMPACT → COUNTDOWN ngay; **đường B** FSM hiệu chỉnh lại (settle 1,5 s, cửa sổ 2 s, var < 0,8, var > 4,0 = cử động) + `aiMax6s` (max của **trung bình** trong 6 s) ≥ `AI_SUPPORT_P 0,5`; AI bật mà `aiMax6s` < 0,5 → IDLE. `aiSelfTest()` chỉ so xác suất từng mô hình, **không phụ thuộc ngưỡng**, nên đổi luật kết hợp không làm hỏng self-test.
- LOSO gộp 21 người (2 bộ seed mỗi mô hình, 104 ca ngã, 1,95 h sinh hoạt; số liệu tính lại bằng `evalx.event_report`, chỉ đường A, không FSM):

| Luật (chỉ đường A) | ngưỡng | phát hiện | báo nhầm / 1,95 h | ghi chú |
|---|---|---|---|---|
| mean (đang nạp) | 0,87 | 99/104 | 0 (cận trên 1,9/h) | `fusion.json` khớp |
| mean | 0,70 | 100/104 | 1 (vỗ tay) | |
| max(MLP, CNN) | 0,95 / 0,98 | 100/104 | 3 / 2 | vỗ tay, giũ áo |
| min (AND) | 0,80 | 98/104 | 0 | |
| MLP đơn / CNN đơn | 0,90 | 98 / 97 | 3 / 3 | |
| luật gốc FSM | – | 6/104 | 14 (7,8/h) | `b1_baselines.json` |

- Replay trên chip (`replay.json`): AI bật 5/5 ca ngã, 1/4 sinh hoạt báo nhầm (vỗ tay, qua đường B); AI tắt 0/5. HIL người 19–21 (`hil_final_full.json`): 1942 cửa sổ, 0 quyết định lệch so với numpy, 14/15 ngã, 1 báo nhầm (vỗ tay).
- **Phát hiện quan trọng:** trên HIFD hai mô hình gần như luôn đồng ý (tương quan điểm 0,94; **0/104** ca ngã có một mô hình ≥ 0,9 mà mô hình kia < 0,5). Trên cổ tay thật hôm nay: **4/5** lần ngã bất đồng mạnh (MLP 0,00/CNN 1,00; 0,98/0,05; 0,17/1,00; 0,86/0,28), chỉ 1/5 đồng ý (1,00/1,00). Đây là dấu hiệu **lệch miền** (người đeo, hướng gắn, đệm), và HIFD **không thể** đo được lợi ích của luật xử lý bất đồng — HIFD chỉ đo được **cái giá** (báo nhầm thêm) của luật đó.

### Cấu hình ứng viên (đều làm được không cần huấn luyện lại)

| ID | Đường A (ngay khi va đập) | Đường B (FSM bất động + AI hỗ trợ 6 s) |
|---|---|---|
| C0 | – (AI tắt) | luật gốc |
| C1 | mean ≥ 0,87 (**hiện tại**) | mean ≥ 0,5 |
| C2 | mean ≥ t, t ∈ {0,6 … 0,95} | mean ≥ τ, τ ∈ {0,3 … 0,7} |
| C3 | max ≥ t, t ∈ {0,9 … 0,99} | max ≥ τ |
| C4 | w·MLP + (1−w)·CNN ≥ t, w ∈ {0,3; 0,4; 0,6; 0,7} | như A |
| C5 | min ≥ t (AND) | mean ≥ τ |
| C6 | mean ≥ 0,87 **hoặc** (max ≥ t_hi **và** đang FREE_FALL/IMPACT) | mean ≥ 0,5 |
| C7 | mean ≥ 0,87 (giữ nguyên) | **max** ≥ τ_B, τ_B ∈ {0,5; 0,7; 0,9}; tùy chọn var_still ∈ {0,8; 1,5; 2,5} |
| C8 | MLP đơn ≥ t / CNN đơn ≥ t (tham chiếu) | đơn ≥ τ |

C6 và C7 nhắm thẳng vào hiện tượng bất đồng mà vẫn đòi **hai bằng chứng** (AI mạnh + va đập, hoặc AI hỗ trợ + bất động). Hiệu chuẩn sau huấn luyện (Platt/isotonic) **loại**: là khớp tham số trên dữ liệu, trái tinh thần "không huấn luyện lại", và không sửa được lệch miền.

### Tiêu chí quyết định

- **Ngân sách báo nhầm X.** Người cao tuổi, còi kêu và có 10 s để hủy; báo nhầm không hủy kịp → người chăm sóc nhận tin sai → mệt mỏi cảnh báo. Mục tiêu đời thực ≤ 1 lần/ngày (≈ 0,07/h khi thức 14 h). Dữ liệu chỉ phân giải được ~0,5/h (1 lần/1,95 h), và 1,95 h HIFD toàn hoạt động "khó" (vỗ tay, ngồi phịch, giũ áo), nên tần suất đời thực thấp hơn nhiều. Vì vậy **X = tối đa 1 báo nhầm trong 1,95 h LOSO** (≈ 0,51/h, cận trên Poisson 95 % ≤ 2,9/h), tức chỉ được thêm tối đa 1 so với C1.
- **Quy tắc chấp nhận** (theo thứ tự): (1) FA LOSO lồng nhau ≤ 1 và replay chip không thêm báo nhầm so với `replay.json`; (2) recall HIFD **không kém** C1 quá 1 ca (≥ 98/104); (3) **tối đa hóa** recall khi stress-test "một mô hình hỏng" (bên dưới) và số lần ngã thật bắt được khi chấm lại offline (5 lần); (4) hòa → chọn cấu hình ít hằng số thay đổi, dễ giải thích hơn. Nếu không ứng viên nào hơn C1 ở (3) mà vẫn đạt (1)–(2) → **giữ C1**.
- Độ trễ/tính toán: mọi ứng viên dùng cùng hai lần suy luận (MLP 0,42 ms, CNN 4,2 ms mỗi 0,5 s) — không phải tiêu chí phân biệt, chỉ cần kiểm tra không tăng.

### Thí nghiệm (chỉ trên dữ liệu/điểm đã có)

1. **Lưới ứng viên trên LOSO** (`run_final_config.py`, mới): dùng điểm `loso_{mlp,cnn}_fw_aug{,_s12}.npz` như `run_fusion.py`; đường B mô phỏng bằng `evalx.simulate_fsm` + `fsm_input` với tham số FSM cố định. Báo cáo recall (Wilson CI), FA/h (Poisson), độ trễ trung vị cho cả **người 16–21** (FSM chỉnh trên 1–15, sạch) và **21 người** (ghi rõ hơi lạc quan cho 1–15).
2. **Chọn ngưỡng lồng nhau:** với mỗi người giữ lại, chọn (t, τ) trên 20 người còn lại theo đúng quy tắc chấp nhận, áp lên người giữ lại, gộp kết quả. Đây là con số được phép báo cáo; điểm "chọn trên toàn bộ" chỉ dùng để nạp. Thêm bootstrap theo người (1000 lần, cặp đôi) cho hiệu recall/FA giữa ứng viên và C1.
3. **Stress-test "một mô hình hỏng"** (mô phỏng chế độ bất đồng thấy trên cổ tay): trên các bản ghi ngã thay điểm MLP bằng 0 (rồi lần lượt CNN bằng 0), giữ nguyên bản ghi sinh hoạt; đo recall còn lại. Dự kiến C1 ≈ 0 (mean không thể ≥ 0,87, cũng khó ≥ 0,5), C3/C6/C7 giữ được phần lớn — con số này cho phép so sánh định lượng mà không cần dữ liệu mới.
4. **Chấm lại offline 5 lần ngã thật + ~20 phút sinh hoạt** (`device_log_rescore.py`, mới): phân tích `[TINY-AI]`/`live_ai` (mlp, cnn mỗi 0,5 s) và dòng `[FSM] impact variance=…` rồi áp từng luật. Lưu ý: firmware chỉ log khi p > 0,2 hoặc mỗi 5 s, nên cửa sổ không được log có max ≤ 0,4 → chấm lại **đầy đủ** cho mọi ngưỡng ≥ 0,4. C1 hiện bắt 3/5 (live5 #1 đường A; live3 và live5 #3 đường B); live1 chạy với AI tắt (`ai=0`) và cử động mạnh sau va đập (var 111).
5. **Kiểm tra lệch miền (chỉ đọc):** so hướng trục/đơn vị/dấu trọng lực của chuỗi firmware (`src/ai_model.cpp`, `src/sensors.cpp`) với `tools/ai_lab/preproc.py`; tính mức bất đồng MLP/CNN của **mô hình đã nạp** (`final_models.pkl`) trên người 19–21. Nếu phát hiện lệch trục thật thì **dừng và hỏi người dùng** (sửa ánh xạ trục là thay đổi riêng, phải kiểm lại trên cổ tay).

### Cách dùng 5 lần ngã thật hôm nay một cách trung thực

- **Cho thấy được:** chuỗi cảm biến → AI → FSM → đếm ngược → hủy chạy trên người thật; hai mô hình **bất đồng** trên người đeo này (điều HIFD không lộ ra); đường B cứu được ca nằm yên; ~20 phút sinh hoạt p ≈ 0,001, không báo nhầm.
- **Không cho thấy được:** recall hay FA/h (n = 5, cùng một người, CI Wilson của 3/5 là 0,23–0,88; 20 phút không báo nhầm chỉ cho cận trên ≈ 9/h); ngã xuống đệm có va đập yếu và nảy, khác ngã trên sàn cứng.
- **Vai trò:** kiểm tra hợp lý + phân xử hòa. Không chọn ngưỡng theo 5 lần này; không chỉnh var_still chỉ để cứu live5 #2 trừ khi lưới LOSO (bước 1) cho thấy FA không tăng.

### Rủi ro

- **Quá khớp ngưỡng trên chính điểm LOSO** → bước 2 (lồng nhau) + chỉ báo cáo con số lồng nhau; ưu tiên ngưỡng tròn và ít tham số tự do (C7 chỉ thêm 1 hằng số).
- **Đệm ≠ sàn thật:** nói rõ trong báo cáo; giữ cooldown 30 s và cửa sổ hủy 10 s.
- **Lệch thang đo float MLP vs int8 CNN:** HIL cho sai lệch tối đa 1,6·10⁻⁴ so với numpy → lượng tử hóa không phải nguyên nhân; bất đồng là do lệch miền. Luật dựa trên max có thể bị một mô hình "quá tự tin" kéo lên → đó là lý do C6/C7 luôn kèm điều kiện va đập/bất động.
- **Code đang sửa dở:** `src/fsm.cpp`, `src/main.cpp`, `include/board_config.h` có thay đổi chưa commit (nút/còi chung net GPIO1-2-3). Bước sửa firmware phải dựa trên các thay đổi đó, commit riêng.

### Bảng bước

| ID | Việc | Model | Thời gian | File chạm | Song song? |
|---|---|---|---|---|---|
| F0 | Chép `live1/3/5.log` từ scratchpad tạm vào `dataset/device_logs/2026-11-02/` + README 5 dòng (người, đệm, AI bật/tắt) | Haiku | 10 ph | `dataset/device_logs/` | đầu tiên |
| F1 | Bước 1–3: lưới ứng viên, chọn ngưỡng lồng nhau, bootstrap, stress-test → `dataset/ai_results/final_config.json` | Sonnet | ~2 h | `tools/ai_lab/run_final_config.py` (mới), `final_config.json` | ∥ F2, F3 |
| F2 | Bước 4: chấm lại log thiết bị → `dataset/ai_results/device_trials.json` | Sonnet | ~45 ph | `tools/ai_lab/device_log_rescore.py` (mới) | ∥ F1, F3 (sau F0) |
| F3 | Bước 5: kiểm tra lệch miền chỉ đọc → `dataset/ai_results/shift_check.json` | Sonnet | ~45 ph | script mới trong scratchpad, `shift_check.json` | ∥ F1, F2 |
| F4 | Áp quy tắc chấp nhận, chọn cấu hình, ghi kết luận vào mục này | Opus | ~30 ph | `PLAN.md` | sau F1–F3 |
| F5 | Sửa firmware theo kết quả, build, nạp, xác minh (cần người dùng cho phép dùng COM13) | Sonnet | ~1,5 h | xem dưới | sau F4, một mình |
| F6 | Đồng bộ tài liệu + câu cho slide | Haiku | ~30 ph | `BAO_CAO.md`, `docs/results_tables.md`, `README.md`, `PLAN.md` | sau F5 |

### Thay đổi firmware theo từng kết quả (F5)

- **Giữ C1:** không đổi code. Chỉ ghi vào báo cáo con số lồng nhau + stress-test + giới hạn đã biết (bất đồng trên cổ tay thật).
- **C2 (chỉ đổi ngưỡng):** sửa tay `AI_ENSEMBLE_THRESHOLD` trong `include/cnn_fall_model.h` (ghi chú "chỉnh tay theo final_config.json") và `thr_fused` trong `fusion.json` cho nhất quán; `AI_SUPPORT_P` trong `src/fsm.cpp`.
- **C7 (dự kiến nhiều khả năng nhất):** `src/ai_model.cpp` thêm hai vòng 12 phần tử cho MLP và CNN → `aiMaxMlp6s`, `aiMaxCnn6s` (khai báo `include/app_state.h`, định nghĩa ở `src/main.cpp`); `src/fsm.cpp` đổi điều kiện đường B thành `max(aiMaxMlp6s, aiMaxCnn6s) < AI_SUPPORT_P` với giá trị τ_B mới; thêm cả hai giá trị vào dòng log `[FSM] impact variance=…`.
- **C6:** thêm `AI_SINGLE_P` (t_hi) trong `src/fsm.cpp`; đường A' chỉ xét khi `state` là FREE_FALL/IMPACT, dùng chung cooldown 30 s; log `[FSM] AI single-model trigger`.
- **C3/C4 (đổi bộ kết hợp):** dòng `p = 0.5f * (pMlp + pCnn)` trong `src/ai_model.cpp` + ngưỡng; dashboard vẫn hiện p, MLP, CNN như cũ.
- **Xác minh:** `pio run` (một mình) → nạp COM13 → `[SELFTEST] PASS` → `replay_eval.py --ai both` trên đúng 9 bản ghi cũ: ngã ≥ 5/5, sinh hoạt không thêm báo nhầm so với `replay.json` → (người dùng làm, có giám sát) 3 lần ngã trên đệm + 10 phút sinh hoạt bằng `tools/live_ai.py`. Không cần chạy lại HIL vì xác suất từng mô hình không đổi.
- **Câu cho slide** (bản cho C6/C7; nếu giữ C1 thì thay câu thứ ba bằng "đường luật bất động + AI hỗ trợ cứu các ca hai mô hình bất đồng"): "Hai mô hình AI bổ sung nhau. Trên dữ liệu 21 người chúng gần như luôn đồng ý, nên lấy trung bình với ngưỡng 0,87 cho 95 % phát hiện mà không báo nhầm. Trên cổ tay thật chúng hay bất đồng, nên chúng tôi thêm luật hai bằng chứng: chỉ cần **một** mô hình chắc chắn **và** có va đập/bất động là báo. Ngưỡng chọn bằng kiểm định chéo lồng nhau theo người, không chạm dữ liệu kiểm tra."
