# HIFD real-data fall model: feature and label specification

This document is the contract between `tools/prepare_hifd.py`,
`tools/train_hifd_model.py`, `include/tiny_fall_model.h`, and any firmware
feature extractor. The exported model was trained **only on real wrist data
from HIFD**; no synthetic data and no Edge Impulse upload were used.

The feature vector is unchanged from the previous 42-feature baseline. The
precision improvement comes from **event-centered training labels**, a
validation-selected decision threshold, and class weighting, not from new
features.

## Source data

- Dataset: [HIFD](https://github.com/nhoyh/HR_IMU_falldetection_dataset),
  IEEE Access 2020, 21 subjects (13 male / 8 female), left wrist, 50 Hz.
- Local clone: `dataset/hifd` (gitignored, not part of this repository).
- 349 `.mat` recordings (MATLAB v5), 381,394 samples.
- Signals used: `ax, ay, az` (g, gravity removed by the dataset authors) and
  `droll, dpitch, dyaw` (gyroscope angular velocity).
- `heart`, quaternion `w/x/y/z`, and `time` are not used.
- Not used: `dataset/testing`, `dataset/training`, the synthetic data generator,
  and any Edge Impulse upload.

### Unit conversion (important)

- Accelerometer: `ax, ay, az [m/s^2] = raw_g * 9.80665`.
- Gyroscope: the README calls `droll/dpitch/dyaw` "angular velocity" without a
  unit. Their range is about -2000..+2000 and the vector magnitude agrees with
  a quaternion-derived angular rate within a factor of ~56, so HIFD is storing
  **deg/s**. They are converted: `gx, gy, gz [rad/s] = raw_dps * pi/180`.
  This matches the task's rad/s input contract and the Adafruit MPU6050
  `gyro.x/y/z` values used by Bio-Band.
- `time` is not used: every recording is treated as uniformly sampled at 50 Hz
  (20 ms), as specified. The observed timestamp deltas are approximately 20 ms.

### Labels: recording-level folder label plus event-centered refinement

| HIFD folder | Folder label | Integer |
| --- | --- | --- |
| `fall/` | `fall` | 1 |
| `non-fall/` | `adl` | 0 |

Near-falls are not individually identified in HIFD. They remain inside
`non-fall/` and stay `adl`; no fall labels are invented.

The previous baseline labeled **every** window cut from a `fall/*.mat`
recording as fall, including pre-impact and post-impact stillness. Those quiet
windows are physically indistinguishable from bed/chair ADL and were the main
source of false positives. The selected model therefore refines only the
timing inside recordings that HIFD already labels fall:

```text
For each fall recording (one intentional fall per recording):
  mag[i]      = sqrt(ax[i]^2 + ay[i]^2 + az[i]^2)      # m/s^2, gravity removed
  smoothed[i] = 5-sample centred moving average of mag
  p           = argmax(smoothed)                        # impact centre

  fall window:        |window_centre - p| <= 50 samples (1.0 s)
  ADL hard negative:  window_end < p - 75  or  window_start > p + 75 (1.5 s)
  excluded:           everything else in that fall recording (1.0-1.5 s band)
```

- `window_centre = window_start + 50`.
- ADL (`non-fall/*.mat`) recordings are **completely unchanged**.
- No fall is created outside a `fall/` recording. Relabeling far windows as ADL
  is a refinement of an existing fall label, not a synthetic label.
- The 104 fall recordings have one center each, at 7.86-9.36 s; the smoothed
  magnitude peak is 18.6-114.6 m/s^2.

Event-centered window counts:

| Split | Original windows | Fall original | Event fall | Event ADL | Relabeled to ADL | Excluded |
| --- | --- | --- | --- | --- | --- | --- |
| train | 10,103 | 2,262 | 294 | 9,373 | 1,532 | 436 |
| validation | 1,983 | 487 | 66 | 1,823 | 327 | 94 |
| test | 1,942 | 459 | 61 | 1,792 | 309 | 89 |

All 104 fall recordings contribute event positives; ADL windows are unchanged.

### Inventory gaps

349 recordings are present instead of the nominal 21 x 19 = 399. Missing files:

- `fall4`: subjects 5-13.
- `fall5`: subjects 1-8.
- `fall6`: subjects 17-21.
- `bed`: subjects 1, 14.
- `eat`: subjects 2, 6, 7, 10, 12, 14, 17, 20.
- `hair`: subjects 5, 13, 16, 17, 20, 21.
- `stair`: subjects 17, 20.
- `write`: subjects 2, 4, 5, 6, 8, 13, 14, 16, 17, 20.

The authoritative list is in `tools/hifd_model_report.json`
(`dataset.missing_scenarios`) and in the `.npz` metadata.

## Windowing and split

- One window: **100 samples = 2.0 s at 50 Hz**, shape `(100, 6)`.
- Stride: **25 samples = 0.5 s**. Adjacent windows overlap by 75 samples.
- Incomplete trailing windows are dropped:
  `n_windows = floor((n_samples - 100) / 25) + 1`.
- Channel order inside each window:
  `[ax, ay, az, gx, gy, gz]` in m/s^2 and rad/s.
- Total: 14,028 windows (3,208 fall / 10,820 adl) before event refinement.

Subject-wise split, fixed in `tools/train_hifd_model.py`:

| Split | Subjects | Windows | Fall (folder) | ADL (folder) |
| --- | --- | --- | --- | --- |
| train | 01-15 | 10,103 | 2,262 | 7,841 |
| validation | 16-18 | 1,983 | 487 | 1,496 |
| test | 19-21 | 1,942 | 459 | 1,483 |

Every window of a subject belongs to exactly one split, so there is no
subject/window leakage across splits. Overlap between adjacent windows exists
only within a split. Each split contains both classes.

## Evaluation views

Three views are reported; do not mix them:

1. **Event-centered window** (training view): retained windows only, with the
   event labels above. This is the primary 2 s-window metric. Test: 1,853
   windows, 61 fall / 1,792 adl.
2. **Legacy all-window** (old task definition): every window of a fall
   recording is fall; all 1,942 test windows. This is directly comparable to
   the old baseline. Its recall is low by construction because the model no
   longer fires on quiet pre/post-impact windows. That is not a regression in
   fall detection; those windows are label noise.
3. **Event-level** (operational): one decision per recording. A fall recording
   is detected if any of its windows exceeds the threshold; an ADL recording is
   a false alarm if any window exceeds it.

## Feature vector: exactly 42 float32 values (unchanged)

All statistics are computed per window. Population statistics use denominator
`N` (`ddof=0`). Indices are the positions in the exported arrays.

### Per-axis block: indices 0-35

For each axis in the order `ax, ay, az, gx, gy, gz`, six features:

| Offset | Name suffix | Formula |
| --- | --- | --- |
| +0 | `mean` | `(1/N) * sum(x_i)` |
| +1 | `std` | population standard deviation, `ddof=0` |
| +2 | `min` | `min(x_i)` |
| +3 | `max` | `max(x_i)` |
| +4 | `rms` | `sqrt((1/N) * sum(x_i^2))` |
| +5 | `mean_abs` | `(1/N) * sum(abs(x_i))` |

Resulting index map:

| Indices | Axis | Units |
| --- | --- | --- |
| 0-5 | ax: mean, std, min, max, rms, mean_abs | m/s^2 |
| 6-11 | ay: mean, std, min, max, rms, mean_abs | m/s^2 |
| 12-17 | az: mean, std, min, max, rms, mean_abs | m/s^2 |
| 18-23 | gx: mean, std, min, max, rms, mean_abs | rad/s |
| 24-29 | gy: mean, std, min, max, rms, mean_abs | rad/s |
| 30-35 | gz: mean, std, min, max, rms, mean_abs | rad/s |

### Acceleration-magnitude block: indices 36-41

Magnitude is built **only from the three linear acceleration axes**, after
gravity removal and g-to-m/s^2 conversion:

```text
mag[i] = sqrt(ax[i]^2 + ay[i]^2 + az[i]^2),  i = 0..99
```

| Index | Name | Formula |
| --- | --- | --- |
| 36 | `mag_mean` | mean of all 100 magnitude samples |
| 37 | `mag_std` | population std of all 100 magnitude samples |
| 38 | `mag_min` | minimum magnitude |
| 39 | `mag_max` | maximum magnitude |
| 40 | `mag_peak_abs` | `max(abs(mag[i]))` |
| 41 | `mag_post_window_var_25` | population variance of `mag[75..99]` (last 25 samples = 0.5 s) |

Non-finite feature values are replaced with `0.0`, in this exact order.
The same rule is implemented in `prepare_hifd.extract_features()`.
`mag_post_window_var_25` is particularly useful for separating a single
fall impact followed by stillness from repeated clapping.

## Standardization

Standardization is part of inference and uses **training-subject statistics
only**, computed over the retained event-centered training windows:

```text
scale[i] = max(std_train[i], 1e-6)
z[i]     = (x[i] - TINY_AI_MEAN[i]) / TINY_AI_SCALE[i]
```

`TINY_AI_MEAN[42]` and `TINY_AI_SCALE[42]` in `include/tiny_fall_model.h` are
these values. Do not recompute them on device data.

## Model and decision rule

```text
z[42] -> Dense 16, tanh -> Dense 1, sigmoid -> P(fall)
fall if P(fall) >= TINY_AI_THRESHOLD (0.94), otherwise adl
```

- Parameters: `TINY_AI_W1[16][42]`, `TINY_AI_B1[16]`, `TINY_AI_W2[16]`,
  `TINY_AI_B2`, `TINY_AI_THRESHOLD` in `include/tiny_fall_model.h` (float32).
- Training: numpy only, weighted binary cross-entropy (fall:ADL = 8:1),
  bed/chair hard negatives weighted x2, Adam full batch, early stopping on
  **unweighted** validation BCE, fixed seed 20240517.
- Threshold: selected on validation only, 0.30..0.95 in steps of 0.01, as the
  highest precision subject to event-centered window recall >= 0.90; ties
  choose the lower threshold. The F1-optimal validation threshold is also
  0.94.
- Metrics: `tools/hifd_model_report.json`; preserved baseline in
  `tools/hifd_model_report_baseline.json`.
- Test fixture: `tools/hifd_feature_test.json` contains one held-out test
  window (100 rows x 6 channels), its 42 expected features, and the expected
  float32 probability/label. Feature tolerance is `1e-3` absolute and
  probability tolerance is `1e-4` absolute.

### Results at the exported threshold (test subjects 19-21)

| View | Windows | Precision | Recall | F1 | Confusion |
| --- | --- | --- | --- | --- | --- |
| Baseline, legacy all-window | 1,942 | 0.6036 | 0.9455 | 0.7368 | [[434,25],[285,1198]] |
| Improved, event-centered | 1,853 | 0.9825 | 0.9180 | 0.9492 | [[56,5],[1,1791]] |
| Improved, legacy all-window | 1,942 | 0.9839 | 0.1329 | 0.2342 | [[61,398],[1,1482]] |
| Improved, event-level | 15 fall / 34 ADL recordings | 0.9333 | 0.9333 | 0.9333 | 14/15 falls; 1/34 ADL |

Validation (subjects 16-18, event-centered): precision 1.0000, recall 0.9697,
F1 0.9846, confusion [[64,2],[0,1823]]; event-level 16/16 fall recordings,
0/33 ADL false alarms. The test false alarm is one `clap` recording; bed and
chair have zero false positives, down from 34 and 33 windows in the baseline.

## Reproduce

```bash
uv venv --python 3.12 .venv-ds
uv pip install --python .venv-ds/Scripts/python.exe numpy scipy
git clone --depth 1 https://github.com/nhoyh/HR_IMU_falldetection_dataset.git dataset/hifd
.venv-ds/Scripts/python.exe tools/prepare_hifd.py
.venv-ds/Scripts/python.exe tools/train_hifd_model.py
```

The first run preserves the old header/report in
`tools/hifd_model_report_baseline.json` before regenerating the model.

## Caveats and domain gap

- **Legacy recall is low by construction.** Under the old all-window labels,
  fall recall >= 0.90 with substantially better precision was not achievable:
  the quiet pre/post-impact windows are physically the same as bed/chair ADL.
  The event-level and event-centered views are the valid operational metrics.
- **One event per recording** is assumed for HIFD fall files; this was verified
  for all 104 fall recordings. The model has no temporal state on device, so
  firmware should apply a short confirmation/debounce logic to the per-window
  output.
- **Near-falls** are part of `adl`, not a third class.
- **Different hardware:** HIFD used a different wrist sensor and placement than
  Bio-Band. Subjects are young adults. Expect a domain gap; the 0.94 threshold
  is high and may need on-device recalibration.
- **Gravity must be removed on device.** The model expects linear acceleration
  in m/s^2 and gyro in rad/s at 50 Hz. Feeding raw MPU6050 acceleration
  (which includes ~9.8 m/s^2 of gravity) will invalidate the features.
- **Fixed timing:** 100-sample windows at 50 Hz; resample or adjust the window
  length if the device sample rate differs.
- **Probability calibration:** probabilities are not calibrated; the threshold
  is a validation-selected operating point.
- **Not a medical device.** This is a research demo, not a fall-detection
  safety guarantee.
