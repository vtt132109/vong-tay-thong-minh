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
### Kết luận F4

*(Opus, 2026-11-02, sau F1–F3. Chỉ dùng `final_config.json`, `device_trials.json`, `shift_check.json`, `replay.json` + đọc firmware. Mọi số dưới đây đã kiểm lại.)*

#### 0. Sửa lại các câu trong mục này đã sai

1. **"C1 = 99/104, 0 báo nhầm" chỉ là đường A.** Đó là `event_report` trên 1,9455 h, không có FSM. **Hệ thống C1 đầy đủ (A ∪ B) = 102/104 (Wilson 0,933–0,995), 1 báo nhầm trong 1,801 h** (0,56/h, cận trên Poisson 95 % 3,09/h) — đường B cứu thêm 3 ca ngã và tốn đúng 1 báo nhầm (vỗ tay). Hệ quả quan trọng: **C1 đã dùng hết ngân sách FA = 1**, nên quy tắc "FA ≤ 1" tuyệt đối loại mọi ứng viên thêm dù chỉ 1 FA.
2. **"~20 phút sinh hoạt" trên thiết bị là sai:** log thực chỉ có **517,9 s = 8,6 phút** yên tĩnh (6 khoảng, 105 cửa sổ log, max p = 0,003). 0 báo nhầm trên 0,144 h chỉ cho cận trên một phía 95 % ≈ **20,8/h** → **bằng chứng FA từ thiết bị bằng không**, không ràng buộc được ứng viên nào.
3. **Seed:** F1 trung bình **3 seed mỗi mô hình** (`meta.seeds_averaged = {mlp: 3, cnn: 3}`), không phải 2 như mục "Hiện trạng" viết.
4. **Giả định của bước 4 ("cửa sổ không log có max ≤ 0,4") đã vỡ một lần:** live5 #2 có cửa sổ không được log với mean 0,69 (`aiMax6s` firmware ghi 0,69 trong khi ring dựng lại từ log chỉ ra 0,602). Chấm lại là đầy đủ *trừ* lỗ hổng này.
5. **Dự đoán "C1 ≈ 0" ở stress-test đúng, nhưng con số thô 45/104 là lỗi số học:** CNN int8 trả **đúng 1,0** trên ~1 % cửa sổ, nên khi MLP = 0 thì mean = 0,5 vẫn "≥ 0,5" của đường B. Chặn ở 0,999 → **C1/C2/C4/C5 = 0/0**. Chỉ được báo cáo số đã chặn.
6. **"C7 dự kiến nhiều khả năng nhất" là sai** (xem §2).

#### 1. Diễn giải quy tắc chấp nhận: dùng bản **tương đối** (FA ≤ FA(C1) + 1 = 2)

Hai câu trong mục "Tiêu chí quyết định" đã mâu thuẫn ngay khi biết C1 có 1 FA chứ không phải 0: *"X = tối đa 1 báo nhầm trong 1,95 h"* (tuyệt đối ⇒ ngưỡng 1) và *"tức chỉ được thêm tối đa 1 so với C1"* (tương đối ⇒ ngưỡng 2). Con số tuyệt đối "1" được viết **dựa trên tiền đề sai rằng C1 = 0 FA**; tiền đề đó đã đổ, nên mệnh đề còn hiệu lực là mệnh đề tương đối, cũng là mệnh đề diễn đạt đúng ý định ("≈ 0,5/h đo được, đời thực thấp hơn nhiều").

**Áp dụng:** quy tắc **nới** `FA_train ≤ FA(C1, cùng người) + 1`. Ghi rõ căng thẳng: **nếu đọc theo nghĩa tuyệt đối "FA ≤ 1" thì không ứng viên nào vượt C1 ở (1)–(2), và kết luận là giữ C1** — vì vậy thay đổi ở §5 được thiết kế để **lùi lại bằng một hằng số duy nhất**.

#### 2. Bằng chứng từng ứng viên vào vòng cuối

| | HIFD lồng nhau (104 ca, 1,801 h) | nhóm sạch 16–21 | bootstrap vs C1 (1000 lần, theo người) | stress 1 mô hình hỏng (đã chặn 0,999) | cổ tay thật (n = 5) | hằng số đổi |
|---|---|---|---|---|---|---|
| **C1** (giữ) | 102/104 • FA 1 • 0,56/h | 31/31 • FA 1 | – | **0 / 0** | 3/5 (4 ca AI bật: 3/4) | 0 |
| **C6** t_hi = 0,95 | **102/104 • FA 2 • 1,11/h** | **31/31 • FA 1** | Δrecall **0,000** (CI 0,000–0,000; 0/1000 tốt hơn, **0/1000 xấu hơn**) • ΔFA +1,06 (CI 0–+3) • ΔFA/h +0,59 (CI 0–+1,70) | **96 / 97** | **4/5** có cooldown, **5/5** nếu tính rời; 4 ca AI bật: 3/4 | **1** |
| C7 / C7v τ_B = 0,9 | 100/104 • FA 2 | 30/31 • FA 1 | Δrecall −0,019 (CI −0,049–0,000), **89,5 % lần lấy lại xấu hơn** | 97 / 98 | **2/5** (kém cả C1) | 1–2 |
| C3 t = 0,99 / τ = 0,9 | 100/104 • FA 4 (in-sample 3) | 30/31 • FA 1 | Δrecall −0,019 (CI −0,049–0,000) • ΔFA +3,06 (CI 0–+7) | 97 / 98 | 4/5 (5/5 rời) | 2 + đổi bộ kết hợp |
| C8b (chỉ CNN) | 103/104 • FA 5 | 31/31 • FA 1 | Δrecall +0,009 (CI 0,000–+0,029) • ΔFA +4,06 (CI +1–+8) | 103 / **0** | 3/5 | bỏ hẳn MLP |

**Đọc bảng:**

- **C6 là ứng viên duy nhất không mất gì về recall.** Δrecall = 0,000 trong **cả 1000** lần lấy lại — vì trên HIFD hai mô hình gần như luôn đồng ý nên đường A′ không bắt thêm ca nào; toàn bộ giá trị của C6 nằm ở (a) chống hỏng mô hình, (b) các ca bất đồng trên cổ tay thật. Giá phải trả là **đúng 1 báo nhầm**, và **1 FA đó nằm hoàn toàn ở người 1–15** (nhóm sạch 16–21 vẫn FA 1, y như C1 — tức ở nhóm duy nhất mà tham số FSM không được chỉnh, C6 **không tốn thêm gì**).
- **C6 không nhạy ngưỡng:** FA = 2 cho mọi t_hi ∈ {0,95; 0,97; 0,98; 0,99} (t_hi = 0,93 → FA 3; 0,90 → FA 4); stress tốt nhất ở 0,95–0,97 (96/97) và tụt ở 0,98–0,99 (92/96–97). Chọn lồng nhau ra **t_hi = 0,95 ở 21/21 fold**, không fold nào phải dùng phương án dự phòng dưới quy tắc nới.
- **C7/C7v bị loại thẳng, và lý do đáng ghi lại:** thay "mean6s ≥ 0,5" bằng "max6s ≥ 0,9" **không phải nới lỏng mà là thắt lại** khi hai mô hình đều trung bình. Chính live5 #3 (max 0,865 < 0,9 nhưng mean 0,588 ≥ 0,5) bị mất → C7 chỉ bắt **2/5** trên cổ tay, kém C1. Trên HIFD C7 cũng **kém C1 ở 89,5 %** lần lấy lại. Muốn C7 bắt được thì phải τ_B = 0,5 → FA nhảy lên **7–8** (và var_still 2,5 → FA 8). Ứng viên "nhiều khả năng nhất" của kế hoạch là ứng viên **tệ nhất** trong nhóm cuối.
- **C3 bị loại** vì đổi bộ kết hợp toàn cục: mất 2 ca ngã HIFD và FA 4 lồng nhau (ΔFA/h +1,70, CI 0–+3,80) — vượt mọi cách đọc ngân sách, để đổi lấy đúng cái robustness mà C6 có với 1 FA.
- **C8b bị loại** vì bỏ MLP: 0 ca khi CNN hỏng, FA 5, và F3 cho thấy **CNN là mô hình nhạy hướng gắn hơn** (xem §6).
- **C2/C5 không thắng gì:** Δrecall 0,000 nhưng stress vẫn 0/0 (như C1) và vẫn tốn +1 FA — trả giá mà không mua được gì. Loại theo tiêu chí (4).

#### 3. Quyết định

> **Nạp C6 với `AI_SINGLE_P = 0,95`.** Đường A giữ nguyên `mean ≥ 0,87`, đường B giữ nguyên `mean6s ≥ 0,5`, FSM giữ nguyên (settle 1,5 s / cửa sổ 2 s / var_still 0,8 / var_motion 4,0). Thêm **đường A′**: `max(MLP, CNN) ≥ 0,95` **và** FSM đang ở `FREE_FALL`/`IMPACT` → COUNTDOWN, dùng chung cooldown 30 s.

Chiếu từng tiêu chí: **(1)** FA lồng nhau 2 = FA(C1) + 1 ✔ theo cách đọc tương đối (✘ theo cách đọc tuyệt đối — đã nêu); cửa chặn replay vẫn phải chạy ở F5. **(2)** recall 102/104 = C1, không kém ca nào ✔. **(3)** C6 **thắng dứt khoát**: stress 96/97 so với 0/0 của C1, và là ứng viên duy nhất kích hoạt được trên **cả hai** ca C1 bỏ sót trên cổ tay thật (live1 #1: ngã rồi tiếp tục cử động mạnh var 111 — đường B bất động không bao giờ cứu được; live5 #2: MLP 0,17 / CNN 1,00). **(4)** chỉ thêm **1 hằng số**, không chạm ngưỡng cũ, lùi lại được bằng một giá trị.

**Trung thực về chỗ yếu của chứng cứ cổ tay:** 4/5 (hay 5/5 nếu tính rời) so với 3/5 của C1 là **không có ý nghĩa thống kê** — Wilson 3/5 = 0,23–0,88, 5/5 = 0,57–1,00, trùm lên nhau. Hơn nữa trong 4 ca **thực sự chạy với AI bật**, C6 = C1 = **3/4**: ca C6 bắt thêm mà C1 không (live1 #1) là ca chạy với **AI tắt**, chỉ chấm lại trên giấy; còn live5 #2 bị **cooldown 30 s** của live5 #1 (cách 12,5 s) chặn. Vậy **5 lần ngã thật không phải căn cứ chọn C6** — nó chỉ xác nhận rằng hai ca C1 bỏ sót đúng là dạng bất đồng mà C6 nhắm vào, và F3 chứng minh dạng bất đồng này là thật và sẽ còn (3/6 sự kiện lệch > 0,5 so với 1/104 trên HIFD, Fisher **p = 3,6·10⁻⁴**). **Căn cứ chính của quyết định là tiêu chí (3) trên 104 ca ngã: stress 96/97 vs 0/0, với Δrecall = 0 chắc chắn và ΔFA = 1.**

#### 4. Thêm bao nhiêu báo nhầm mỗi giờ, có chấp nhận được không?

- **Đo được:** C1 0,56/h → C6 1,11/h, tức **+0,56 báo nhầm/h** trên 1,801 h sinh hoạt HIFD (cận trên Poisson 95 %: 3,09 → **4,01/h**). Bootstrap: +1,06 FA (CI 0 đến +3), +0,59/h (CI 0 đến +1,70). Trên nhóm sạch 16–21: **+0,00**.
- **Nhưng 1,801 h đó gần như toàn hoạt động "khó"** (vỗ tay, ngồi phịch, giũ áo liên tiếp), không phải một ngày bình thường. Quy ra mỗi ngày **phải giả định** tỉ lệ thời gian có hoạt động khó, và **chúng ta chưa đo nó**: nếu hoạt động như vậy chiếm 5–10 % trong 14 h thức (0,7–1,4 h) thì phần thêm là **≈ +0,4 đến +0,8 báo nhầm/ngày**; nếu 2 % thì ≈ +0,16/ngày. Đây là ngoại suy, không phải số đo.
- **Thiết bị không ràng buộc được gì:** 8,6 phút, 0 FA cho **mọi** ứng viên (cận trên ≈ 20,8/h).
- **Kết luận về khả năng chấp nhận:** mục tiêu đặt ra là ≤ 1/ngày. Điểm ước lượng tốt nhất cho phần **thêm** nằm dưới 1/ngày nhưng **sát mép** và **chưa kiểm chứng cho chế độ đeo 14 h/ngày**. Với còi + **10 s hủy** + cooldown 30 s, một báo nhầm mà người đeo hủy kịp chỉ tốn một tiếng bíp và một lần bấm nút — không tới người chăm sóc. Vì vậy: **chấp nhận được cho bản mẫu và cho thử nghiệm có giám sát**, kèm điều kiện lùi ở §5(e) nếu nhật ký đeo thật cho > 1 báo nhầm/ngày. Người cao tuổi phản xạ chậm là lý do **không** hạ `AI_ENSEMBLE_THRESHOLD` và **không** chọn C3/C8b.

#### 5. F5 phải sửa gì, xác minh thế nào, khi nào lùi

**(a) `src/fsm.cpp` — thay đổi chính:**

- Thêm cạnh `AI_SUPPORT_P` (dòng 83):
  ```cpp
  // C6 path A': one model alone may fire, but only with mechanical evidence of an impact.
  // t_hi = 0.95 chosen by nested leave-one-subject-out selection (21/21 folds),
  // dataset/ai_results/final_config.json -> candidates.C6.  Set to 2.0f to fall back to C1.
  static constexpr float AI_SINGLE_P = 0.95f;
  ```
- Trong `updateFallDetection`, **trước** khối đường A (dòng 100), tính:
  ```cpp
  const bool aiWindowFresh = (aiWindowMs != 0) && (now - aiWindowMs <= 600);
  const bool aiSingleStrong = aiWindowFresh &&
      ((isfinite(aiProbMlp) && aiProbMlp >= AI_SINGLE_P) ||
       (isfinite(aiProbCnn) && aiProbCnn >= AI_SINGLE_P));
  const bool aiSingleGate = aiSingleStrong &&
      (state == SystemState::FreeFall || state == SystemState::Impact);
  ```
  `isfinite` là cần: `aiProbCnn` bằng −1,0 khi CNN không chạy. **`aiWindowFresh` là bắt buộc để khớp với F1:** bộ chấm offline xét cờ A′ **một lần mỗi cửa sổ** (trạng thái FSM tại mẫu cuối cửa sổ), còn `updateFallDetection` chạy mỗi 20 ms — không có chốt tươi, một cửa sổ vỗ tay có CNN cao sẽ còn "treo" 0,5 s và kịp bắn nếu FSM vào `IMPACT` sau đó, tức firmware sẽ **lỏng hơn** số FA đã đo.
- Đổi điều kiện dòng 100 thành `aiAlarmEnabled && (aiFall || aiSingleGate) && (state == Idle || FreeFall || Impact) && (lastAiAlertMs == 0 || now - lastAiAlertMs > AI_ALERT_COOLDOWN_MS)`. **Giữ nguyên** `lastAiAlertMs`, `AI_ALERT_COOLDOWN_MS` (30 s) và `setState(SystemState::Countdown, "Te nga (AI)")` để OLED/dashboard không đổi chữ.
- **Log mới:** khi bắn *chỉ* qua A′ (`!aiFall && aiSingleGate`) in
  `[FSM] AI single-model trigger mlp=%.3f cnn=%.3f thr=%.2f state=%s` (giữ dòng `[FSM] AI trigger ...` cũ cho đường A, để đếm riêng được hai đường khi soát log).
- **Thêm vào dòng `[FSM] impact variance=…`** (dòng 162) hai trường `mlp=%.2f cnn=%.2f` (từ `aiProbMlp`/`aiProbCnn`) — chỉ để chẩn đoán về sau, không thêm biến.
- Cập nhật khối chú thích dòng 68–78 để mô tả A′ và nguồn số.

**(b) `aiWindowMs` — biến mới duy nhất:** `extern uint32_t aiWindowMs;` trong `include/app_state.h` (cạnh `aiMax6s`), định nghĩa `uint32_t aiWindowMs = 0;` trong `src/main.cpp`, gán `aiWindowMs = now;` ở **cuối** `runTinyAi()` trong `src/ai_model.cpp` (sau khi `aiProbability`/`aiFall` đã được đặt, trước khối log).

**(c) KHÔNG được chạm:** `include/cnn_fall_model.h` (`AI_ENSEMBLE_THRESHOLD` giữ `0.870000005f`), `AI_SUPPORT_P` giữ `0.5f`, dòng `p = 0.5f * (pMlp + pCnn)` trong `src/ai_model.cpp`, `AI_STILL_VAR`/`AI_MOTION_VAR`, `fusion.json`, `final_models.pkl`, mọi header mô hình. Không huấn luyện lại, không chạy `export_final.py`. ⇒ `aiSelfTest()` chỉ so xác suất từng mô hình nên **không bị ảnh hưởng**; không cần chạy lại HIL 1942 cửa sổ.
Lưu ý: `src/fsm.cpp`, `src/main.cpp`, `include/board_config.h` đang có thay đổi chưa commit (nút/còi chung net GPIO1-2-3) — sửa **trên nền** các thay đổi đó, commit riêng.

**(d) Xác minh, theo thứ tự:**

1. `pio run` (chạy một mình, không song song pio khác) — không có cảnh báo mới.
2. Nạp COM13 (cần người dùng cho phép) → `[SELFTEST] PASS`. Nếu FAIL thì bản sửa đã làm hỏng thứ không liên quan → dừng.
3. `tools/ai_lab/replay_eval.py --ai both` trên **đúng 9 bản ghi** của `replay.json`. **Kỳ vọng:**
   - 5 ca ngã vẫn 5/5 có COUNTDOWN: `s19/fall/fall1`, `s19/fall/fall4`, `s20/fall/fall2`, `s20/fall/fall5` (lý do `Te nga (AI…`), `s21/fall/fall3` (hiện là `Te nga + bat dong`). `s21/fall3` **được phép** đổi sang bắn qua A′ và countdown ngắn lại (hiện 3,43 s) — ghi lại con số mới.
   - Sinh hoạt: **đúng 1** báo nhầm, `s20/non-fall/clap` (như `replay.json`: countdown 17,0 s → ALARM). `s19/non-fall/clap` (peak mean p 0,3895), `s19/non-fall/bed` (0,0017), `s19/non-fall/walk` (0,0119) **phải không có COUNTDOWN**.
   - **Đây là cửa chặn cứng của tiêu chí (1).** Dấu hiệu tốt: trên điểm LOSO, FA tăng của C6 nằm ở người 1–15, nhóm 16–21 (gồm s19–s21) vẫn FA 1 — nhưng replay dùng **mô hình đã nạp** (người 1–18 là dữ liệu huấn luyện, nên s19/s20 cho xác suất cao hơn LOSO), vì vậy phải chạy thật, không được suy luận.
4. Người dùng làm, có giám sát: 3 lần ngã trên đệm + **≥ 10 phút** sinh hoạt thường bằng `tools/live_ai.py`, **có cố ý vỗ tay và ngồi phịch**. Đếm riêng số lần `[FSM] AI single-model trigger` xuất hiện và trong đó bao nhiêu là báo nhầm. Lưu log vào `dataset/device_logs/`.

**(e) Điều kiện lùi (chỉ cần một điều kiện đúng → đặt `AI_SINGLE_P = 2.0f`, khôi phục C1 chính xác, không sửa gì khác):**

- replay sinh **bất kỳ** báo nhầm sinh hoạt nào ngoài `s20/non-fall/clap`; **hoặc**
- thử nghiệm có giám sát cho ≥ 1 báo nhầm do dòng `[FSM] AI single-model trigger` trong ≤ 10 phút sinh hoạt thường (≈ ≥ 6/h, hơn 10 lần mức tăng đo trên HIFD); **hoặc**
- nhật ký đeo dài hơn về sau cho > 1 báo nhầm/ngày; **hoặc**
- `[SELFTEST] FAIL`.

#### 6. Rủi ro tồn đọng quan trọng nhất (một rủi ro, đã lượng hóa)

**Lệch hướng gắn làm đường A′ của CNN bắn trên sinh hoạt.** F3 đo trên mô hình đã nạp, người 19–21, 1792 cửa sổ sinh hoạt: ở hướng gốc chỉ **0,056 %** cửa sổ có CNN ≥ 0,9 (MLP: 0 %); nhưng khi xoay **z −90°** thì **3,40 %** cửa sổ sinh hoạt có CNN ≥ 0,9 — trong khi `mean ≥ 0,87` vẫn **0,00 %**. Nói cách khác: **C1 miễn nhiễm với kịch bản này, C6 thì không**, và CNN đúng là mô hình nhạy hướng hơn. Dây đeo hiện **không khóa được góc của MPU6050** trên cổ tay (BAO_CAO mục 12, việc tương lai). Cổng `FREE_FALL`/`IMPACT` + cooldown 30 s cắt phần lớn số đó (bằng chứng: ở hướng gốc cổng này giữ giá phải trả ở đúng +1 FA trong 1,8 h), nhưng **mức giảm khi bị xoay thì chưa đo được**. Giảm thiểu: vỏ/dây cố định hướng (đã có trong việc tương lai), bước xác minh (d)(4), và điều kiện lùi (e).

#### 7. Ba câu cho giám khảo (trung thực, gồm cả giới hạn)

> "Hai mô hình AI bổ sung nhau: trên 21 người của bộ dữ liệu công khai chúng gần như luôn đồng ý, nên lấy trung bình hai xác suất với ngưỡng 0,87 đạt 102/104 ca ngã và 1 báo nhầm trong 1,8 giờ sinh hoạt khó. Trên cổ tay thật của chúng tôi hai mô hình lại hay bất đồng — 3/6 sự kiện lệch hơn 0,5, so với 1/104 trên bộ dữ liệu (Fisher p = 3,6·10⁻⁴) — nên chúng tôi thêm luật hai bằng chứng: chỉ cần **một** mô hình chắc chắn (≥ 0,95) **và** FSM đang thấy rơi/va đập là báo; luật này giữ nguyên 102/104, chỉ thêm 1 báo nhầm, và nếu một mô hình hỏng hẳn vẫn bắt 96–97/104 thay vì 0. Giới hạn: ngưỡng chọn bằng kiểm định chéo lồng nhau theo từng người nhưng chỉ có 21 người; bằng chứng trên người thật là 5 lần ngã xuống **đệm** của **một** người (khoảng tin cậy 0,23–0,88) và 8,6 phút sinh hoạt — chưa đủ để công bố tỉ lệ báo nhầm mỗi ngày, nên còi vẫn có 10 giây để hủy."

#### 8. Người dùng cần quyết

1. **Chốt C6 (`AI_SINGLE_P = 0,95`) hay ra lệnh "giữ C1"?** Chọn C1 nếu muốn đọc quy tắc theo nghĩa tuyệt đối "FA ≤ 1" — khi đó F5 không sửa code, chỉ cập nhật tài liệu với số lồng nhau + stress-test.
2. **Cho phép dùng COM13** ở F5 (build + nạp + `replay_eval.py`), và nhận làm **thử nghiệm đeo có giám sát** (3 lần ngã trên đệm + ≥ 10 phút sinh hoạt có vỗ tay/ngồi phịch) — không có bước này thì không đóng được điều kiện lùi.
3. **AI alarm mode để mặc định ON hay vẫn OFF trong NVS** (`#AIARM`)? C6 chỉ có tác dụng khi AI bật; live1 chạy với AI tắt nên 1 trong 5 ca ngã hôm nay không nói được gì.
4. **Hủy đếm ngược có nên xóa cooldown 30 s không?** live5 #2 bị chặn bởi cooldown của live5 #1 *đã bị hủy*. Đây là thay đổi riêng, ngoài phạm vi F4 — quyết định có đưa vào F5 hay hoãn.
5. **Tùy chọn:** nâng chuỗi phiên bản FW (2.1-ai → 2.2-ai), và có bỏ ~5 phút chạy lại `run_final_config.py` để biết bản ghi sinh hoạt nào ở người 1–15 gây ra FA thứ 2 của C6 (hiện `final_config.json` không ghi nhãn kịch bản ở mức hệ thống).

#### 9. Tóm tắt

1. **Nạp C6, `AI_SINGLE_P = 0,95` trong `src/fsm.cpp`.** Giữ nguyên `mean ≥ 0,87`, `mean6s ≥ 0,5`, mọi tham số FSM và mọi mô hình.
2. Quy tắc chấp nhận dùng bản **tương đối** (FA ≤ FA(C1) + 1 = 2), vì con số tuyệt đối "1" được viết khi còn tưởng C1 = 0 FA; theo nghĩa tuyệt đối thì giữ C1 — nên thay đổi được làm sao cho lùi lại bằng một hằng số.
3. C6 **không mất ca ngã nào**: 102/104 y như C1, Δrecall = 0,000 trong cả 1000 lần bootstrap. Giá: **+1 báo nhầm** (0,56 → 1,11/h; nhóm sạch 16–21 **+0**).
4. Lý do chọn là tiêu chí (3): khi **một mô hình hỏng**, C6 giữ **96/97 trên 104**, C1 giữ **0** (số 45 là lỗi số học của CNN int8 = 1,0).
5. C7/C7v **loại**: `max6s ≥ 0,9` thắt hơn `mean6s ≥ 0,5`, nên kém C1 cả trên HIFD (100/104; xấu hơn ở 89,5 % lần bootstrap) lẫn trên cổ tay (2/5).
6. C3 loại (FA 4, mất 2 ca), C8b loại (FA 5, hỏng CNN → 0 ca), C2/C5 loại (trả +1 FA mà stress vẫn 0).
7. 5 lần ngã thật **không phải** căn cứ chọn: 4/5 vs 3/5 không có ý nghĩa (CI 0,23–0,88 trùm nhau), và trong 4 ca AI bật thì C6 = C1 = 3/4. Nó chỉ xác nhận dạng bất đồng là thật (F3: Fisher p = 3,6·10⁻⁴).
8. Rủi ro tồn đọng số một: **lệch hướng gắn** đẩy CNN ≥ 0,9 từ 0,06 % lên **3,4 %** cửa sổ sinh hoạt, trong khi `mean ≥ 0,87` vẫn 0 % — C1 miễn nhiễm, C6 không.
9. **F5 sửa:** `src/fsm.cpp` (hằng `AI_SINGLE_P`, cờ `aiSingleGate` có chốt tươi 600 ms, nối vào điều kiện đường A, log `[FSM] AI single-model trigger`, thêm `mlp=`/`cnn=` vào dòng `impact variance=`, cập nhật chú thích); `aiWindowMs` mới ở `include/app_state.h` + `src/main.cpp` + cuối `runTinyAi()` trong `src/ai_model.cpp`. Không chạm header mô hình, ngưỡng 0,87, `AI_SUPPORT_P`, `fusion.json`.
10. **Xác minh:** `pio run` → `[SELFTEST] PASS` → `replay_eval.py --ai both` trên 9 bản ghi: ngã 5/5, sinh hoạt **đúng 1** báo nhầm (`s20/clap`) — cửa chặn cứng → thử nghiệm đeo có giám sát.
11. **Lùi** (đặt `AI_SINGLE_P = 2.0f`) nếu: replay thêm báo nhầm, hoặc ≥ 1 báo nhầm từ A′ trong 10 phút sinh hoạt, hoặc > 1/ngày khi đeo thật, hoặc self-test FAIL.
12. Không cần chạy lại HIL; `aiSelfTest()` không phụ thuộc luật kết hợp.

## Bài báo PDF (6-8 trang)

*(Viết 2026-11-03. Nội dung ở `docs/paper/paper.html` — HTML thuần, không script, không tài nguyên ngoài;
`docs/paper/paper.css` do người/agent dàn trang viết. Mọi số trong bài đã đối chiếu lại với file nguồn,
danh sách ở dưới.)*

### Dàn ý và ngân sách trang (ước lượng cho 2 cột A4, 10 pt)

| Mục | Nội dung | Ước lượng |
|---|---|---|
| Tiêu đề + tác giả + Tóm tắt + Từ khóa | tóm tắt ~330 từ tiếng Việt | 0,5 trang |
| 1. Giới thiệu | vấn đề, hai thái cực (ngưỡng 98,3 FA/h ↔ FSM 6/104), 6 đóng góp đánh số | 0,7 |
| 2. Bối cảnh | ba nhóm phương pháp, vì sao không so với số liệu công bố nơi khác, vì sao chọn bộ dữ liệu cổ tay | 0,3 |
| 3. Thiết kế hệ thống | 3.1 phần cứng · 3.2 firmware/2 lõi · 3.3 FSM + Bảng 1 · 3.4 bảo mật. Hình 1 (wide) | 1,2 (gồm hình/bảng) |
| 4. Phương pháp AI | 4.1 HIFD · 4.2 mô phỏng chuỗi firmware · 4.3 nhãn theo sự kiện · 4.4 MLP + CNN int8 · 4.5 giao thức LOSO · 4.6 nghiên cứu quyết định | 1,3 |
| 5. Kết quả | 5.1 LOSO (Bảng 2, Hình 2, Hình 3) · 5.2 luật + ablation (Bảng 3, Hình 4) · 5.3 C1 vs C6 (Bảng 4) · 5.4 trên chip (Bảng 5) + nhiệt · 5.5 cổ tay thật · 5.6 HR/SpO2 | 2,6 |
| 6. Thảo luận và hạn chế | lệch miền, mẫu nhỏ, hướng gắn (0,056 % → 3,40 %), ngưỡng lạc quan, chưa lâm sàng/chưa đủ phần cứng | 0,6 |
| 7. Kết luận và hướng phát triển | tóm tắt + 4 việc tiếp theo | 0,3 |
| Tài liệu tham khảo | 3 mục | 0,15 |

Tổng ước lượng **≈ 7 trang**. Thân bài ~26 000 ký tự (~5 750 từ tiếng Việt). Nếu bản dàn trang ra quá 8 trang,
cắt theo thứ tự: 5.6 (HR/SpO2) → đoạn "ứng viên bị loại" ở 5.3 → mục 2 → đoạn nhiệt/xung ở 5.4.
Nếu thiếu trang thì ngược lại: thêm `fig_feature_importance.png` vào 4.4.

### Hình và bảng đã chọn (4 hình + 5 bảng)

| Số | File / nội dung | Vì sao chọn |
|---|---|---|
| Hình 1 | `docs/figures/fig_system.png` (wide) | hình duy nhất cho thấy cả hai nhánh (IMU→AI→FSM và PPG) và ranh giới "mọi thứ chạy trên chip" |
| Hình 2 | `fig_operating_curves.png` (col) | hình "đắt" nhất: 8 mô hình + 2 mốc luật trên một trục FA/h, cho thấy ngay tổ hợp thắng ở ngân sách thấp |
| Hình 3 | `fig_probability_timelines.png` (col) | cho giám khảo thấy *hình dạng* tín hiệu AI, giải thích vì sao vỗ tay là nguồn báo nhầm |
| Hình 4 | `fig_ablation.png` (col) | trực quan hóa cú sụp 97→18 khi bỏ nhãn theo sự kiện; dùng hình thay bảng để đỡ một bảng |
| Bảng 1 | 4 đường vào COUNTDOWN (luật gốc, A, A′, B) | thay cho `fig_states.png` (xem cảnh báo dưới) |
| Bảng 2 | so sánh 12 mô hình LOSO (wide) | lấy nguyên từ `docs/results_tables.md` |
| Bảng 3 | 3 mốc so sánh bằng luật | số liệu then chốt của mục 1 |
| Bảng 4 | C1 vs C6, gồm bootstrap và stress-test (wide) | trình bày quyết định cấu hình cuối |
| Bảng 5 | 6 phép kiểm chứng trên chip | gom self-test / HIL / replay / HTTP / vòng lặp / pytest |

**Không dùng:**

- `fig_states.png` — **đã lỗi thời**: vẫn vẽ trạng thái `SNOOZE` (đã bỏ khỏi `include/shared_types.h`;
  nhấn nút giờ về IDLE ngay) và chưa có đường A′. Dùng Bảng 1 thay thế. Nếu muốn có hình trạng thái,
  phải vẽ lại: bỏ SNOOZE, thêm cạnh A′ (`max(MLP,CNN) ≥ 0,95` từ FREE_FALL/IMPACT), rồi chèn làm Hình 2
  và đánh số lại các hình sau.
- `fig_feature_importance.png` — các giá trị permutation đều < 0,007 (AUC đã 0,9998) nên hình không nói
  được nhiều; để dành nếu thiếu trang.
- `poster_system.png`, `poster_curves.png` — bản cho poster.
- `docs/screenshots/dashboard-*.png` — **không phải thiết bị thật**: chân trang ghi
  `API http://127.0.0.1:8123` (tức `tools/mock_server.py`), hiển thị pin 88 % / 3,94 V trong khi pin chưa hàn,
  và còn trạng thái SNOOZE. Dùng sẽ là trình bày sai sự thật. Xem mục "Người dùng cần làm".

### Mọi con số trong bài và nguồn

| Con số | Nguồn |
|---|---|
| 21 người, 349 bản ghi, 381 394 mẫu, 104 ngã / 245 sinh hoạt, cổ tay trái, 50 Hz | `BAO_CAO.md` §6.1; `final_config.json` → `meta.n_recordings/n_fall` |
| Ngưỡng 25 m/s²: 104/104, 177 FA / 1,801 h, 98,3/h, trễ 0,08 s | `b1_baselines.json` → `threshold only` |
| FSM gốc: 6/104, 14 FA, 7,77/h, trễ 6,38 s | `b1_baselines.json` → `FSM (still after impact)`; `final_config.json` → `verification.C0_vs_b1_baselines` |
| FSM hiệu chỉnh: 31/31, 9 FA / 0,50 h, 18,1/h, 3,4 s | `docs/results_tables.md` §"Rule-based baselines" |
| Bảng 2 (12 dòng mô hình, cột @≤1/≤2/≤5 và ngưỡng theo fold) | `docs/results_tables.md` §"Leave-one-subject-out"; `summary.json` → `operating` |
| Ablation 97 / 18 / 94 / 93 / 94 / 92 trên 104 | `summary.json` → `ablation` |
| Khoảng cách miền 92 → 97 → 98 / 104 | `docs/results_tables.md` (3 dòng MLP-42); `BAO_CAO.md` §6.2 |
| Đường A đơn thuần: 99/104, 0 FA / 1,9455 h, cận trên 1,896/h | `fusion.json`; `final_config.json` → `verification.C1_pathA_event_report` |
| **C1 đầy đủ (A∪B): 102/104 (0,933–0,995), 1 FA / 1,8011 h = 0,56/h (cận trên 3,09), trễ 0,26 s** | `final_config.json` → `candidates.C1.deploy_all21_selection.groups.all_21_optimistic_for_1_15` |
| **C6 lồng nhau: 102/104, 2 FA, 1,11/h (cận trên 4,01), trễ 0,20 s; nhóm 16–21: 31/31, 1 FA** | `final_config.json` → `candidates.C6.nested` và `.relaxed_fa_c1_plus_1` |
| C6 stress: 96 (MLP = 0) / 97 (CNN = 0); C1 stress 0 / 0 | `final_config.json` → `candidates.C6.relaxed_fa_c1_plus_1.nested_stress_*`; `candidates.C1.stress_test.*_capped_0.999_on_falls` |
| Bootstrap C6 vs C1: Δrecall 0,000 (0/1000 xấu hơn), ΔFA +1,06 (CI 0…+3) | `final_config.json` → `bootstrap_vs_C1_nested_relaxed_fa_c1_plus_1.C6` |
| t_hi = 0,95 chọn ở 21/21 fold; FA = 2 cho t_hi 0,95–0,99 | `final_config.json` → `candidates.C6.nested.selected_params_frequency`; mục "Kết luận F4" §2 |
| C7 kém C1 ở 89,5 % lần bootstrap; C3 100/104 + 4 FA; C8b 5 FA, stress 0 | PLAN "Kết luận F4" §2 (từ `final_config.json`) |
| HIL: 1 942 cửa sổ, MLP 1,2·10⁻⁶, CNN 1,6·10⁻⁴, 0 lệch; 14/15 ngã, 1 FA / 0,27 h, trễ 0,16 s | `hil_final_full.json` |
| Replay: AI bật 5/5 ngã + 1/4 sinh hoạt (vỗ tay); AI tắt 0/5 ngã + 2/2 vỗ tay | `replay.json` (18 dòng = 9 bản ghi × 2 chế độ) |
| 0,42 ms / 4,2 ms @160 MHz; 80 MHz 0,76/8,4 ms 40,7 °C; 240 MHz 0,32/2,8 ms 57,7 °C; jit 35 ms, 50 fps | `thermal.json` |
| 705 / 1 761 / 2 466 tham số, 49 200 MAC | `docs/results_tables.md`; `final.json` → `macs`; kiểm lại bằng tay từ kiến trúc |
| Ngưỡng 0,87 (`AI_ENSEMBLE_THRESHOLD`), `AI_SINGLE_P` 0,95, `AI_SUPPORT_P` 0,5, settle 1,5 s, var 0,8/4,0, cooldown 30 s, cửa sổ tươi 600 ms | `include/cnn_fall_model.h`, `src/fsm.cpp` |
| Luật gốc: 25 m/s², rơi tự do 5 m/s², bất động 3 s var < 0,08, đếm ngược 10 s, SOS giữ 3 s | `include/board_config.h` |
| FW 2.2-c6; 983 KB flash (75 %), RAM 16,6 % | `include/board_config.h`; `README.md` §2 |
| HTTP self-test 11/11; 8 test pytest + CI | `BAO_CAO.md` §9; `tests/test_tools.py` |
| Cổ tay thật: 5 ngã / 1 người / nệm, 4 ca chạy với AI bật, C1 bắt 3/5 (Wilson 0,231–0,882) | `device_trials.json` → `trials`, `candidates[id=C1]` |
| Bất đồng 1,00 / 0,97 / 0,84 / 0,58 ở 4/5 ca | `device_trials.json` → `trials[*].max_mlp_cnn_disagreement` |
| 8,6 phút (517,9 s) đeo yên tĩnh, max p 0,003, 0 FA, cận trên 20,8/h | `device_trials.json` → `idle`; PLAN "Kết luận F4" §0.2 |
| Bất đồng thiết bị 3/6 vs HIFD 1/104, Fisher p = 3,6·10⁻⁴ | `shift_check.json` → `numbers.device_vs_hifd_fisher_exact` |
| Không tìm thấy lệch trục/dấu/đơn vị giữa firmware và pipeline | `shift_check.json` → `verdict`, `verdict_explanation` |
| Hướng gắn: CNN ≥ 0,9 trên 0,056 % cửa sổ ADL (gốc) → 3,40 % (xoay z −90°), mean ≥ 0,87 vẫn 0,00 %; n = 1 792 | `shift_check.json` → `numbers.sensitivity_deployed_models_subjects_19_21` |
| Biên độ gia tốc ×0,5 → 9/15 ca ngã (xấp xỉ nệm mềm) | `shift_check.json` → cùng mục, dòng `SOFT impact proxy: accel x0.5` |
| Phương sai sau va đập trung vị 3,7; 1 % ngã < 0,08; 12 % đoạn sinh hoạt < 0,08 | `BAO_CAO.md` §6.7 |
| int8 vs float: sai lệch xác suất trung bình 0,0015 | `BAO_CAO.md` §6.4 (chỉ có trong báo cáo, không có file JSON riêng) |
| HR/SpO2: mô phỏng 200 seed 4,72 → 1,65 bpm, 13,7 % → 2,1 %; đo thật HR 55–76, SpO2 96–97, PI 1,5–3,5 % | `BAO_CAO.md` §7 |
| Quaternion: cosin trung vị −0,50 (world→body) vs 0,03 | `BAO_CAO.md` §6.2 |

### Người dùng cần điền hoặc xác nhận

1. **Tác giả.** `<p class="authors">` đang là một dòng placeholder duy nhất: `[Điền: tên nhóm, họ tên thành viên, đơn vị, giáo viên hướng dẫn]`.
2. **Tài liệu tham khảo [1] (HIFD).** Kho mã chỉ ghi "Heart Rate & IMU sensor data for fall detection, IEEE Access 2020"
   + link GitHub; **không có tên tác giả, tiêu đề đầy đủ, số tập/trang**. Phải tra và điền theo mẫu của cuộc thi.
3. **Tài liệu tham khảo [2]** (Nghị định 13/2023/NĐ-CP): bổ sung ngày ban hành/cơ quan nếu mẫu trích dẫn yêu cầu.
   WEDA-FALL và SisFall được nhắc trong mục 2 **không có trích dẫn** (kho mã không có chi tiết); nếu muốn trích dẫn
   thì phải tự tra, hoặc bỏ tên chúng khỏi câu đó.
4. **Ảnh sản phẩm thật còn thiếu.** Không có ảnh chụp vòng tay trong kho. Một ảnh board đã lắp (và/hoặc ảnh màn hình
   dashboard **chụp từ IP thật của board**, không phải `127.0.0.1:8123`) sẽ là hình giá trị nhất còn thiếu —
   chèn làm Hình 5 ở mục 3.1.
5. **Vẽ lại `fig_states.png`** nếu muốn có hình máy trạng thái (bỏ SNOOZE, thêm A′).
6. **Nhãn trục của Hình 2–4 đang bằng tiếng Anh.** Chạy lại `tools/ai_lab/make_figures.py` với nhãn tiếng Việt thì
   bài sẽ nhất quán hơn; nếu không kịp thì giữ nguyên, chú thích hình đã bằng tiếng Việt.
7. **Xác nhận một phát biểu trong mục 6:** bài nói rõ rằng số liệu replay ở Bảng 5 đo trên cấu hình **C1**
   (`replay.json` ghi lúc 01:54 ngày 2026-11-02, trước khi `src/fsm.cpp` đổi sang C6 lúc 23:26) và rằng việc chạy lại
   `replay_eval.py --ai both` trên 9 bản ghi với FW 2.2-c6 vẫn là cửa chặn bắt buộc (F5 bước d.3). **Nếu đã chạy lại
   rồi mà chưa lưu kết quả, hãy lưu và sửa lại câu đó + Bảng 5.**
8. **Tiêu đề bài** hiện khá dài; rút gọn nếu mẫu của cuộc thi giới hạn.
9. `CLAUDE_HANDOFF.md` §0 và `README.md` §1 vẫn ghi "99/104, 0 báo nhầm" (chỉ đúng cho đường A).
   Bài báo đã dùng số đúng (102/104, 1 FA cho C1; 102/104, 2 FA cho C6) — nên đồng bộ hai file kia để không mâu thuẫn
   khi giám khảo đọc repo.
