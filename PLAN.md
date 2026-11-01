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
