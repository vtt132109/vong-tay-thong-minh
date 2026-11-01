# tools/

Python tooling for Bio-Band. Install once (Python 3.12):

```bash
uv venv --python 3.12 .venv-ds
uv pip install --python .venv-ds/Scripts/python.exe -r tools/requirements.txt
git clone --depth 1 https://github.com/nhoyh/HR_IMU_falldetection_dataset.git dataset/hifd   # public HIFD data
```

Tests (no dataset needed): `.venv-ds/Scripts/python.exe -m pytest tests -q`

## AI lab (`tools/ai_lab/`) — the pipeline behind the on-chip models

| Step | Script | What it does |
|---|---|---|
| 1 | `data.py` | Loads the 349 HIFD recordings (accel, gyro, **quaternion**), finds the impact of each fall, caches them. |
| 2 | `preproc.py` | Rebuilds what the firmware really sees: raw acceleration with gravity (from the quaternion) → 21 Hz DLPF → ±16 g clip → first-order gravity removal α=0.98. Optional random sensor rotation and gyro-bias augmentation. |
| 3 | `features.py` | The 42-feature contract of `hifd_features.md` (identical to `src/ai_model.cpp`), plus orientation-invariant features. |
| 4 | `evalx.py` | Event-level metrics (detection within ±2 s of the impact; every other alert is a false alert), alerts/hour, Wilson and Poisson confidence intervals, a Python port of the firmware FSM. |
| 5 | `lab.py`, `run_loso.py` | Torch MLP / 1D-CNN and sklearn baselines, **leave-one-subject-out** over 21 subjects (3 validation subjects per fold for early stopping and threshold). `run_loso.py NAME [--seeds 0,1,2]`. |
| 6 | `run_b1.py`, `run_fsm_sweep.py` | Domain-gap check of the shipped model and calibration of the rule-based FSM. |
| 7 | `run_fusion.py` | Ensemble, debounce, threshold selection and rule+AI fusion strategies → `dataset/ai_results/fusion.json`. |
| 8 | `export_final.py` | Trains the deployed models, quantises the CNN to int8, writes `include/tiny_fall_model.h`, `include/cnn_fall_model.h`, `include/selftest_vectors.h`. |
| 9 | `hil_eval.py` | **Hardware-in-the-loop**: streams real HIFD windows over USB into the ESP32-S3 and compares the probabilities computed on the chip with numpy. |
| 9b | `replay_eval.py` | **Replay end-to-end**: phát bản ghi HIFD thật vào firmware ở 50 Hz như dữ liệu MPU6050 (còi tắt) và đo FSM/AI phản ứng thế nào, có và không có chế độ báo động bằng AI. |
| 10 | `make_figures.py` | Figures for the report (`docs/figures/`) and `dataset/ai_results/summary.json`. |

Typical full run (about 40 min on a laptop CPU):

```bash
PY=.venv-ds/Scripts/python.exe
$PY tools/ai_lab/run_loso.py mlp_fw_aug cnn_fw_aug --seeds 0     # repeat with --seeds 1,2
$PY tools/ai_lab/run_fusion.py
$PY tools/ai_lab/export_final.py
pio run -e esp32-s3-super-mini -t upload --upload-port COM13
$PY tools/ai_lab/hil_eval.py --port COM13
$PY tools/ai_lab/make_figures.py
```

## Older HIFD scripts

`prepare_hifd.py` / `train_hifd_model.py` are the original numpy-only pipeline (42 features → 16 → 1,
trained on the HIFD signal as published). They are kept for reproducibility of the first model;
`hifd_features.md` is still the feature contract.

## Device tools

| Script | Use |
|---|---|
| `monitor_serial.py [PORT] [--no-reset] [--seconds N]` | Print the board's serial log (port auto-detected, UTF-8 safe). |
| `capture_labeled.py` | Record labelled 6-axis IMU trials from the real band (`--start-index`, refuses to overwrite unless `--overwrite`). Always on a mattress, with a spotter and consent. |
| `mqtt_peek.py` | Đọc telemetry/status mới nhất của vòng tay từ broker MQTT (chỉ đọc, không publish). |
| `thermal_test.py` | So sánh nhiệt độ chip, độ trễ AI và vòng lặp ở các xung 80/160/240 MHz (build + nạp từng mức). |
| `log_telemetry.py` | Log `/data` to CSV (LAN) to compare raw and filtered HR/SpO2. |
| `mock_server.py` | Fake device for the LAN dashboard (`python tools/mock_server.py --port 8000`). |
| `test_ppg_filter.py` | Simulation of the PPG output filter (also asserted in `tests/`). |
| `generate_synthetic_imu.py`, `upload_dataset.py` | Legacy Edge Impulse pipeline test with **synthetic** data; never use it to claim accuracy. |
