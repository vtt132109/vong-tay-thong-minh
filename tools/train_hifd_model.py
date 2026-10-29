#!/usr/bin/env python3
"""Train and evaluate a tiny 42 -> 16 -> 1 fall classifier on real HIFD data.

The model is implemented with numpy only (no sklearn).  It consumes the
un-standardized windows produced by tools/prepare_hifd.py, standardizes with
training-subject statistics, trains with weighted binary cross-entropy and
Adam, stops early on unweighted validation BCE, selects every decision
threshold on validation subjects 16-18, and only then evaluates the selected
model once on held-out subjects 19-21.

Two label views are reported because the original HIFD folder label is
recording-level:

  * legacy: every window of a fall recording is fall (the previous baseline);
  * event-centered: only windows near the detected impact of a fall recording
    are fall; far windows become hard-negative ADL; ambiguous windows are
    excluded.  ADL recordings are unchanged.

The event-centered view is used for threshold selection and for the exported
model.  The legacy view is still computed for an apples-to-apples comparison
with the previous baseline, but its fall recall is expected to be low: the
pre/post-impact stillness windows it calls "fall" are physically
indistinguishable from bed/chair ADL, which is the main source of the old
model's false positives.

Artifacts written:
  include/tiny_fall_model.h              C header with the exact firmware symbols
  tools/hifd_model_report.json           full metrics, sweep, scenario breakdown
  tools/hifd_model_report_baseline.json  preserved previous baseline + evaluation
  tools/hifd_feature_test.json           one raw test window + expected features

Subject-wise split (fixed, no subject appears in more than one split):
  train = subjects 01-15, validation = 16-18, test = 19-21.

Example
-------
  .venv-ds/Scripts/python.exe tools/prepare_hifd.py
  .venv-ds/Scripts/python.exe tools/train_hifd_model.py
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_hifd import (  # noqa: E402
    FEATURE_NAMES,
    GYRO_DEG_TO_RAD,
    PROJECT_ROOT,
    extract_features,
    load_recording,
)

DEFAULT_NPZ = PROJECT_ROOT / "dataset" / "hifd_processed" / "hifd_windows.npz"
DEFAULT_HEADER = PROJECT_ROOT / "include" / "tiny_fall_model.h"
DEFAULT_REPORT = PROJECT_ROOT / "tools" / "hifd_model_report.json"
DEFAULT_BASELINE_REPORT = PROJECT_ROOT / "tools" / "hifd_model_report_baseline.json"
DEFAULT_TEST_VECTOR = PROJECT_ROOT / "tools" / "hifd_feature_test.json"

TRAIN_SUBJECTS = tuple(range(1, 16))  # 15 subjects
VAL_SUBJECTS = (16, 17, 18)  # 3 subjects
TEST_SUBJECTS = (19, 20, 21)  # 3 subjects

FEATURE_COUNT = 42
HIDDEN = 16
WINDOW_SAMPLES = 100
HALF_WINDOW = WINDOW_SAMPLES // 2
SAMPLING_HZ = 50.0

# Event-centered label rule (samples at 50 Hz; 25 samples = 0.5 s).
EVENT_SMOOTH = 5  # centered moving average on the linear-acceleration magnitude
EVENT_RADIUS = 50  # +-1.0 s around the impact: fall
EXCLUDE_RADIUS = 75  # +-1.5 s around the impact: ambiguous and excluded

SEED = 20240517
MAX_EPOCHS = 2500
PATIENCE = 250
LEARNING_RATE = 0.01
MIN_EVENT_WINDOW_RECALL = 0.90
MIN_EVENT_LEVEL_RECALL = 0.90

# Mandated validation sweep range.  Every candidate threshold is chosen from it.
THRESHOLD_GRID = tuple(round(0.30 + 0.01 * i, 2) for i in range(66))  # 0.30..0.95

CANDIDATES = (
    {
        "id": "event_r25_balanced",
        "description": "event labels +-0.5 s, balanced class weights",
        "radius": 25,
        "exclude": 75,
        "class_weights": "balanced",
        "hard_negative_weight": 1.0,
    },
    {
        "id": "event_r37_balanced",
        "description": "event labels +-0.75 s, balanced class weights",
        "radius": 37,
        "exclude": 75,
        "class_weights": "balanced",
        "hard_negative_weight": 1.0,
    },
    {
        "id": "event_r50_balanced",
        "description": "event labels +-1.0 s, balanced class weights",
        "radius": 50,
        "exclude": 75,
        "class_weights": "balanced",
        "hard_negative_weight": 1.0,
    },
    {
        "id": "event_r50_fall8",
        "description": "event labels +-1.0 s, fall weight 8 (class-weight tuning)",
        "radius": 50,
        "exclude": 75,
        "class_weights": "fixed",
        "adl_weight": 1.0,
        "fall_weight": 8.0,
        "hard_negative_weight": 1.0,
    },
    {
        "id": "event_r50_fall8_hardneg",
        "description": (
            "event labels +-1.0 s, fall weight 8, bed/chair hard negatives x2"
        ),
        "radius": 50,
        "exclude": 75,
        "class_weights": "fixed",
        "adl_weight": 1.0,
        "fall_weight": 8.0,
        "hard_negative_weight": 2.0,
    },
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    out = np.empty_like(x, dtype=np.float64)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def init_params(rng: np.random.Generator) -> dict[str, np.ndarray]:
    limit1 = np.sqrt(6.0 / (FEATURE_COUNT + HIDDEN))
    limit2 = np.sqrt(6.0 / (HIDDEN + 1))
    return {
        "W1": rng.uniform(-limit1, limit1, (HIDDEN, FEATURE_COUNT)),
        "b1": np.zeros(HIDDEN, dtype=np.float64),
        "W2": rng.uniform(-limit2, limit2, HIDDEN).astype(np.float64),
        "b2": np.zeros(1, dtype=np.float64),
    }


def forward(params: dict[str, np.ndarray], z: np.ndarray):
    hidden_pre = z @ params["W1"].T + params["b1"]
    hidden = np.tanh(hidden_pre)
    logits = hidden @ params["W2"] + params["b2"][0]
    return sigmoid(logits), hidden


def predict(params: dict[str, np.ndarray], z: np.ndarray) -> np.ndarray:
    probabilities, _ = forward(params, z)
    return probabilities


def loss_and_grads(
    params: dict[str, np.ndarray],
    z: np.ndarray,
    y: np.ndarray,
    sample_weights: np.ndarray,
) -> tuple[float, dict[str, np.ndarray]]:
    probabilities, hidden = forward(params, z)
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    bce = -(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))
    loss = float(np.mean(sample_weights * bce))

    n = y.shape[0]
    d_logits = sample_weights * (probabilities - y) / n
    grads = {
        "W2": hidden.T @ d_logits,
        "b2": np.array([np.sum(d_logits)]),
    }
    d_hidden = np.outer(d_logits, params["W2"]) * (1.0 - hidden * hidden)
    grads["W1"] = d_hidden.T @ z
    grads["b1"] = np.sum(d_hidden, axis=0)
    return loss, grads


def unweighted_bce(
    params: dict[str, np.ndarray], z: np.ndarray, y: np.ndarray
) -> float:
    probabilities = np.clip(predict(params, z), 1e-12, 1.0 - 1e-12)
    bce = -(y * np.log(probabilities) + (1.0 - y) * np.log(1.0 - probabilities))
    return float(np.mean(bce))


def train_mlp(
    z_train: np.ndarray,
    y_train: np.ndarray,
    z_val: np.ndarray,
    y_val: np.ndarray,
    *,
    sample_weights: np.ndarray,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float,
):
    rng = np.random.default_rng(seed)
    params = init_params(rng)
    moments = {key: np.zeros_like(value) for key, value in params.items()}
    velocities = {key: np.zeros_like(value) for key, value in params.items()}

    beta1, beta2, epsilon = 0.9, 0.999, 1e-8
    best_val_loss = float("inf")
    best_params = {key: value.copy() for key, value in params.items()}
    best_epoch = 0
    epochs_run = 0
    history = []

    for epoch in range(1, max_epochs + 1):
        train_loss, grads = loss_and_grads(
            params, z_train, y_train, sample_weights
        )
        # Early stopping uses unweighted BCE so probabilities stay calibrated
        # rather than being pushed by the class-weight vector.
        val_loss = unweighted_bce(params, z_val, y_val)
        epochs_run = epoch

        if val_loss < best_val_loss - 1e-12:
            best_val_loss = val_loss
            best_epoch = epoch
            best_params = {key: value.copy() for key, value in params.items()}
        elif epoch - best_epoch >= patience:
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": float(train_loss),
                    "val_loss": float(val_loss),
                    "early_stop": True,
                }
            )
            break

        if epoch == 1 or epoch % 100 == 0:
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": float(train_loss),
                    "val_loss": float(val_loss),
                }
            )

        for key in params:
            moments[key] = beta1 * moments[key] + (1.0 - beta1) * grads[key]
            velocities[key] = (
                beta2 * velocities[key] + (1.0 - beta2) * np.square(grads[key])
            )
            m_hat = moments[key] / (1.0 - beta1**epoch)
            v_hat = velocities[key] / (1.0 - beta2**epoch)
            params[key] -= learning_rate * m_hat / (np.sqrt(v_hat) + epsilon)

    return best_params, {
        "best_epoch": best_epoch,
        "best_val_loss": float(best_val_loss),
        "epochs_run": epochs_run,
        "history": history,
    }


def cast_params(params: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Round parameters to float32, as they will be stored in the C header."""
    return {
        key: np.asarray(value, dtype=np.float32).astype(np.float64)
        for key, value in params.items()
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def binary_metrics(
    y_true: np.ndarray, probabilities: np.ndarray, threshold: float = 0.5
) -> dict:
    y_true = np.asarray(y_true).astype(np.int64)
    predicted = (probabilities >= threshold).astype(np.int64)
    tp = int(np.sum((predicted == 1) & (y_true == 1)))
    tn = int(np.sum((predicted == 0) & (y_true == 0)))
    fp = int(np.sum((predicted == 1) & (y_true == 0)))
    fn = int(np.sum((predicted == 0) & (y_true == 1)))
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2.0 * precision * recall, precision + recall)
    total = tp + tn + fp + fn
    return {
        "threshold": float(threshold),
        "n_windows": int(total),
        "n_fall": int(tp + fn),
        "n_adl": int(tn + fp),
        "accuracy": _safe_div(tp + tn, total),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": {
            "labels": ["fall", "adl"],
            "rows": "actual",
            "columns": "predicted",
            "matrix": [[int(tp), int(fn)], [int(fp), int(tn)]],
        },
        "mean_probability_fall_windows": float(
            np.mean(probabilities[y_true == 1]) if np.any(y_true == 1) else 0.0
        ),
        "mean_probability_adl_windows": float(
            np.mean(probabilities[y_true == 0]) if np.any(y_true == 0) else 0.0
        ),
    }


def threshold_sweep(
    labels: np.ndarray, probabilities: np.ndarray
) -> list[dict]:
    return [
        binary_metrics(labels, probabilities, threshold)
        for threshold in THRESHOLD_GRID
    ]


def compact_sweep(rows: list[dict], extras: tuple[float, ...] = ()) -> list[dict]:
    """Keep 0.05 steps plus explicitly requested thresholds."""
    wanted = {round(0.30 + 0.05 * i, 2) for i in range(14)}
    wanted.update(round(float(value), 2) for value in extras)
    kept = {}
    for row in rows:
        threshold = round(float(row["threshold"]), 2)
        if threshold in wanted:
            kept[threshold] = row
    return [kept[key] for key in sorted(kept)]


def select_threshold(
    labels: np.ndarray, probabilities: np.ndarray, min_recall: float
) -> tuple[dict | None, dict]:
    """Max precision subject to recall >= min_recall; ties -> lower threshold.

    The lower-threshold tie-break keeps the largest recall margin while still
    attaining the best precision on the mandated validation grid.
    """
    rows = threshold_sweep(labels, probabilities)
    qualifying = [row for row in rows if row["recall"] >= min_recall]
    f1_optimal = max(rows, key=lambda row: (row["f1"], row["precision"]))
    if not qualifying:
        return None, f1_optimal
    best_precision = max(row["precision"] for row in qualifying)
    tied = [
        row
        for row in qualifying
        if abs(row["precision"] - best_precision) < 1e-12
    ]
    return min(tied, key=lambda row: row["threshold"]), f1_optimal


def event_level_metrics(
    probabilities: np.ndarray,
    mask: np.ndarray,
    threshold: float,
    *,
    labels: np.ndarray,
    sources: np.ndarray,
    scenarios: np.ndarray,
) -> dict:
    """One decision per recording: any alert window marks the recording.

    Fall recordings are positives, ADL recordings are negatives.  This differs
    from window metrics: a fall still counts once no matter how many of its
    windows fire, and an ADL recording is a false alarm if any window fires.
    """
    fall_recordings = sorted(set(sources[mask & (labels == 1)].tolist()))
    adl_recordings = sorted(set(sources[mask & (labels == 0)].tolist()))

    def _alerts(recording: str) -> bool:
        recording_mask = sources == recording
        return bool(np.any(probabilities[recording_mask] >= threshold))

    detected = [rec for rec in fall_recordings if _alerts(rec)]
    false_alarms = [rec for rec in adl_recordings if _alerts(rec)]
    false_alarm_by_scenario: dict[str, int] = collections.Counter()
    for rec in false_alarms:
        scenario = str(scenarios[sources == rec][0])
        false_alarm_by_scenario[scenario] += 1

    return {
        "definition": (
            "one detection per recording: fall recording is detected if any of "
            "its windows has P(fall) >= threshold; ADL recording is a false "
            "alarm if any of its windows has P(fall) >= threshold"
        ),
        "threshold": float(threshold),
        "fall_recordings": int(len(fall_recordings)),
        "detected_fall_recordings": int(len(detected)),
        "missed_fall_recordings": int(len(fall_recordings) - len(detected)),
        "event_recall": _safe_div(len(detected), len(fall_recordings)),
        "adl_recordings": int(len(adl_recordings)),
        "adl_recordings_with_false_alarm": int(len(false_alarms)),
        "adl_false_alarm_recording_rate": _safe_div(
            len(false_alarms), len(adl_recordings)
        ),
        "event_precision": _safe_div(
            len(detected), len(detected) + len(false_alarms)
        ),
        "false_alarm_recordings_by_scenario": dict(
            sorted(false_alarm_by_scenario.items())
        ),
    }


def per_scenario_metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    mask: np.ndarray,
    threshold: float,
    *,
    scenarios: np.ndarray,
    sources: np.ndarray,
) -> dict:
    rows = {}
    for scenario in sorted(set(scenarios[mask].tolist())):
        scenario_mask = mask & (scenarios == scenario)
        scenario_labels = labels[scenario_mask]
        predicted = probabilities[scenario_mask] >= threshold
        tp = int(np.sum(predicted & (scenario_labels == 1)))
        tn = int(np.sum(~predicted & (scenario_labels == 0)))
        fp = int(np.sum(predicted & (scenario_labels == 0)))
        fn = int(np.sum(~predicted & (scenario_labels == 1)))
        recordings = sorted(set(sources[scenario_mask].tolist()))
        alert_recordings = 0
        for recording in recordings:
            recording_mask = scenario_mask & (sources == recording)
            if np.any(probabilities[recording_mask] >= threshold):
                alert_recordings += 1
        rows[scenario] = {
            "n_windows": int(scenario_mask.sum()),
            "n_fall_labels": int(np.sum(scenario_labels == 1)),
            "n_adl_labels": int(np.sum(scenario_labels == 0)),
            "predicted_positive": int(tp + fp),
            "tp": int(tp),
            "fn": int(fn),
            "fp": int(fp),
            "tn": int(tn),
            "false_positive_rate": _safe_div(fp, fp + tn),
            "recordings": int(len(recordings)),
            "recordings_with_alert": int(alert_recordings),
        }
    return rows


def false_positive_summary(per_scenario: dict) -> dict:
    """Compact non-fall scenario view for reports and the model header."""
    out = {}
    for scenario, row in per_scenario.items():
        if scenario.startswith("non-fall/"):
            out[scenario] = {
                "n_windows": row["n_windows"],
                "false_positives": row["fp"],
                "false_positive_rate": row["false_positive_rate"],
                "recordings": row["recordings"],
                "recordings_with_alert": row["recordings_with_alert"],
            }
    return out


# ---------------------------------------------------------------------------
# HIFD event detection and event-centered labels
# ---------------------------------------------------------------------------


def detect_event_centers(sources_array: np.ndarray, labels: np.ndarray) -> dict:
    """Find one impact sample per fall recording.

    Rule: linear-acceleration magnitude ||a|| (gravity already removed by the
    dataset authors), 5-sample centered moving average, argmax.  HIFD fall
    recordings contain a single intentional fall, and every recording's peak
    lies near the middle of the recording; no labels are invented.  ADL
    recordings are not touched.

    The peak is only used to refine the timing of an already-labeled fall
    recording, never to create a fall from a non-fall recording.
    """
    centers = {}
    details = {}
    for recording in sorted(set(sources_array[labels == 1].tolist())):
        raw_path = PROJECT_ROOT / recording
        if not raw_path.is_file():
            raise FileNotFoundError(f"fall recording is missing: {raw_path}")
        data = load_recording(raw_path, gyro_scale=GYRO_DEG_TO_RAD)
        magnitude = np.sqrt(np.sum(np.square(data[:, :3]), axis=1))
        kernel = np.ones(EVENT_SMOOTH, dtype=np.float64) / EVENT_SMOOTH
        smoothed = np.convolve(magnitude, kernel, mode="same")
        center = int(np.argmax(smoothed))
        centers[recording] = center
        details[recording] = {
            "samples": int(data.shape[0]),
            "event_center_sample": int(center),
            "event_center_seconds": float(center / SAMPLING_HZ),
            "peak_smoothed_magnitude_m_s2": float(smoothed[center]),
            "peak_raw_magnitude_m_s2": float(np.max(magnitude)),
            "median_magnitude_m_s2": float(np.median(magnitude)),
        }
    return {"centers": centers, "details": details}


def event_centered_labels(
    labels: np.ndarray,
    starts: np.ndarray,
    sources_array: np.ndarray,
    centers: dict,
    radius: int,
    exclude: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (refined_labels, keep_mask) for one event radius.

    Positive: |(start + 50) - event_center| <= radius, i.e. the window centre
    is within +-radius samples of the impact.
    Hard negative: the window lies entirely outside event_center +- exclude;
    it is relabeled ADL.
    Ambiguous: remaining windows are excluded from training and window metrics.
    """
    refined = labels.copy()
    keep = np.ones(len(labels), dtype=bool)
    for recording, center in centers.items():
        recording_mask = sources_array == recording
        window_centers = starts[recording_mask] + HALF_WINDOW
        positive = np.abs(window_centers - center) <= radius
        negative = (
            (starts[recording_mask] + WINDOW_SAMPLES - 1 < center - exclude)
            | (starts[recording_mask] > center + exclude)
        )
        keep[recording_mask] = positive | negative
        refined[recording_mask] = np.where(positive, 1, 0)
    return refined, keep


def label_counts(
    refined: np.ndarray,
    keep: np.ndarray,
    mask: np.ndarray,
    original: np.ndarray,
) -> dict:
    fall_original = mask & (original == 1)
    return {
        "windows_total_original": int(mask.sum()),
        "fall_original": int(np.sum(fall_original)),
        "adl_original": int(np.sum(mask & (original == 0))),
        "windows_kept": int(np.sum(mask & keep)),
        "fall_event_centered": int(np.sum(mask & keep & (refined == 1))),
        "adl_event_centered": int(np.sum(mask & keep & (refined == 0))),
        "fall_windows_relabeled_adl": int(
            np.sum(fall_original & keep & (refined == 0))
        ),
        "ambiguous_windows_excluded": int(np.sum(mask & ~keep)),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _float_literal(value) -> str:
    value32 = np.float32(value)
    if not np.isfinite(value32):
        raise ValueError(f"refusing to export non-finite value {value}")
    if value32 == 0:
        value32 = np.float32(0.0)
    text = format(float(value32), ".9g")
    if "e" not in text and "." not in text:
        text += ".0"
    text += "f"
    if np.float32(float(text[:-1])) != value32:
        raise AssertionError(f"float32 round-trip failed for {value32}")
    return text


def _format_array(name: str, shape: str, values: np.ndarray, per_line: int) -> str:
    flat = np.asarray(values, dtype=np.float32).ravel()
    lines = []
    for index in range(0, flat.size, per_line):
        chunk = ", ".join(_float_literal(v) for v in flat[index : index + per_line])
        lines.append("    " + chunk + ",")
    body = "\n".join(lines)
    return f"static const float {name}{shape} = {{\n{body}\n}};\n"


def _metrics_line(metrics: dict) -> str:
    matrix = metrics["confusion_matrix"]["matrix"]
    return (
        f"accuracy {metrics['accuracy']:.4f}, precision {metrics['precision']:.4f}, "
        f"recall {metrics['recall']:.4f}, F1 {metrics['f1']:.4f} "
        f"(confusion [[{matrix[0][0]}, {matrix[0][1]}], "
        f"[{matrix[1][0]}, {matrix[1][1]}]])"
    )


def export_header(
    path: Path,
    mean: np.ndarray,
    scale: np.ndarray,
    params: dict[str, np.ndarray],
    *,
    threshold: float,
    baseline_test: dict,
    selected_test_event: dict,
    selected_test_legacy: dict,
    selected_test_event_level: dict,
    selected_val_event: dict,
    selected_val_event_level: dict,
) -> None:
    w1_rows = []
    for row in np.asarray(params["W1"], dtype=np.float32):
        cells = ", ".join(_float_literal(v) for v in row)
        w1_rows.append("    {" + cells + "},")
    w1_body = "\n".join(w1_rows)

    event_line = (
        f"//   improved, event-centered labels: {_metrics_line(selected_test_event)} "
        f"on {selected_test_event['n_windows']} retained windows "
        f"({selected_test_event['n_fall']} fall / {selected_test_event['n_adl']} adl)."
    )
    legacy_line = (
        f"//   improved, legacy all-window labels: {_metrics_line(selected_test_legacy)} "
        f"on {selected_test_legacy['n_windows']} windows."
    )
    baseline_line = (
        f"//   baseline, legacy all-window labels: {_metrics_line(baseline_test)} "
        f"on {baseline_test['n_windows']} windows."
    )
    event_level_line = (
        f"// Event-level test (one decision per recording): event recall "
        f"{selected_test_event_level['event_recall']:.4f} "
        f"({selected_test_event_level['detected_fall_recordings']}/"
        f"{selected_test_event_level['fall_recordings']} fall recordings), "
        f"event precision {selected_test_event_level['event_precision']:.4f}, "
        f"ADL recordings with >=1 alarm "
        f"{selected_test_event_level['adl_recordings_with_false_alarm']}/"
        f"{selected_test_event_level['adl_recordings']}."
    )
    validation_line = (
        f"// Validation (subjects 16-18, event-centered): "
        f"{_metrics_line(selected_val_event)}; event-level recall "
        f"{selected_val_event_level['event_recall']:.4f}, event precision "
        f"{selected_val_event_level['event_precision']:.4f}."
    )

    header = f"""#pragma once

// tiny_fall_model.h -- real-data TinyML fall classifier for Bio-Band.
//
// Auto-generated by tools/train_hifd_model.py. Do not hand-edit.
//
// Data provenance: trained on REAL wrist data from the public HIFD dataset
// (Heart Rate & IMU sensor data for fall detection, 21 subjects, left wrist,
// 50 Hz). No synthetic or Edge Impulse data was used.
// Input: 6 axes x 100 samples @ 50 Hz (2 s window, 0.5 s stride). Accelerometer
// channels are gravity-removed linear acceleration in m/s^2; gyro channels are
// angular velocity in rad/s (HIFD's deg/s values were converted).
// Features: exactly 42 floats in the order documented in tools/hifd_features.md.
// Standardize before inference: z[i] = (x[i] - TINY_AI_MEAN[i]) / TINY_AI_SCALE[i].
// Network: 42 -> 16 (tanh) -> 1 (sigmoid).
//
// Training label rule (event-centered; only HIFD fall recordings are refined):
// impact centre p = argmax of a 5-sample moving average of ||linear accel||.
// A window is fall if its centre is within +-1.0 s of p, ADL if it lies fully
// more than 1.5 s from p, and excluded otherwise.  ADL recordings are unchanged.
// See tools/hifd_model_report.json ("label_rule") for exact counts and code.
//
// Decision: fall when P(fall) >= TINY_AI_THRESHOLD ({threshold:.2f}).
// The threshold was selected on validation only (max precision subject to
// event-centered window recall >= 0.90, ties -> lower threshold).
//
// Held-out test (subjects 19-21, subject-wise, never used for tuning):
{baseline_line}
{event_line}
{legacy_line}
{event_level_line}
//
// IMPORTANT: the legacy all-window recall is low by construction.  The old
// baseline labeled pre/post-impact stillness as fall; event-centered training
// deliberately does not fire on those windows because they are physically
// indistinguishable from bed/chair ADL.  Event-level detection is the
// operationally meaningful recall and remains high.
{validation_line}
//
// RESEARCH DEMO ONLY -- NOT A MEDICAL DEVICE. HIFD was captured with a
// different wrist sensor and placement than Bio-Band, and its subjects are
// young adults, so a domain gap remains. Re-validate on-device with local
// subjects before drawing any safety conclusion.

#define TINY_AI_FEATURE_COUNT 42
#define TINY_AI_HIDDEN 16
#define TINY_AI_THRESHOLD {threshold:.2f}f

{_format_array("TINY_AI_MEAN", "[42]", mean, 6)}
{_format_array("TINY_AI_SCALE", "[42]", scale, 6)}
static const float TINY_AI_W1[16][42] = {{
{w1_body}
}};

{_format_array("TINY_AI_B1", "[16]", params["b1"], 8)}
{_format_array("TINY_AI_W2", "[16]", params["W2"], 8)}
static const float TINY_AI_B2 = {_float_literal(params["b2"][0])};
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header, encoding="utf-8")


def build_test_vector(
    npz: dict,
    meta: dict,
    chosen_index: int,
    *,
    mean: np.ndarray,
    scale: np.ndarray,
    params: dict[str, np.ndarray],
    threshold: float,
    event_center: int,
) -> dict:
    source = str(npz["source"][chosen_index])
    raw_path = PROJECT_ROOT / source
    if not raw_path.is_file():
        raise FileNotFoundError(
            f"raw recording for the test vector is missing: {raw_path}"
        )
    gyro_scale = float(meta.get("gyro_scale", GYRO_DEG_TO_RAD))
    raw = load_recording(raw_path, gyro_scale=gyro_scale)
    window_samples = int(meta.get("window_samples", WINDOW_SAMPLES))
    start = int(npz["start"][chosen_index])
    window = raw[start : start + window_samples]
    if window.shape != (window_samples, 6):
        raise ValueError(f"bad test window shape {window.shape}")

    expected_features = extract_features(window)
    stored_features = np.asarray(npz["X"][chosen_index], dtype=np.float64)
    if not np.allclose(expected_features, stored_features, rtol=0.0, atol=1e-9):
        raise AssertionError(
            "recomputed test-window features differ from the training matrix"
        )

    z = (expected_features - mean) / scale
    probability = float(predict(params, z[None, :])[0])
    label = "fall" if probability >= threshold else "adl"
    if label != "fall":
        raise AssertionError("selected fixture is not classified as fall")

    return {
        "description": (
            "Firmware verification fixture: one complete 100x6 window from the "
            "held-out HIFD test subjects, the 42 features extracted from it, and "
            "the expected tiny model output."
        ),
        "metadata": {
            "source_recording": source,
            "subject": int(npz["subject"][chosen_index]),
            "scenario": str(npz["scenario"][chosen_index]),
            "folder_label": "fall",
            "event_centered_label": "fall",
            "window_start_sample": start,
            "window_center_sample": start + window_samples // 2,
            "event_center_sample": int(event_center),
            "offset_from_event_s": float(
                (start + window_samples // 2 - event_center) / SAMPLING_HZ
            ),
            "window_samples": window_samples,
            "sampling_hz": 50,
            "window_duration_s": window_samples / 50.0,
            "selection": (
                "correctly classified event-centered held-out test fall window "
                "with the largest acceleration peak (deterministic)"
            ),
            "channels": ["ax", "ay", "az", "gx", "gy", "gz"],
            "units": {
                "ax,ay,az": "m/s^2 (gravity removed, raw g * 9.80665)",
                "gx,gy,gz": "rad/s (raw HIFD deg/s * pi/180)",
            },
            "model_header": "include/tiny_fall_model.h",
            "decision_threshold": float(threshold),
            "label_rule": (
                "event-centered: window centre within +-1.0 s of the detected "
                "impact; see tools/hifd_features.md"
            ),
        },
        "feature_order": list(FEATURE_NAMES),
        "window": window.tolist(),
        "expected_features": expected_features.tolist(),
        "expected": {
            "probability_fall": probability,
            "label": label,
            "ground_truth": "fall",
            "feature_tolerance_abs": 1e-3,
            "probability_tolerance_abs": 1e-4,
            "note": (
                "Compare unstandardized features; standardize with TINY_AI_MEAN/"
                "TINY_AI_SCALE, then float32 tanh/sigmoid inference. Tolerances "
                "allow for float32 accumulation and libm differences."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Baseline header parsing and evaluation
# ---------------------------------------------------------------------------


def _parse_header_array(text: str, name: str) -> np.ndarray:
    pattern = re.compile(
        r"static\s+const\s+float\s+"
        + re.escape(name)
        + r"\s*(?:\[\d+\])+\s*=\s*\{(.*?)\}\s*;",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"could not parse {name} from header")
    numbers = re.findall(
        r"[-+]?[0-9]+(?:\.[0-9]*)?(?:[eE][-+]?[0-9]+)?", match.group(1)
    )
    return np.asarray([float(value) for value in numbers], dtype=np.float64)


def load_header_model(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    mean = _parse_header_array(text, "TINY_AI_MEAN")
    scale = _parse_header_array(text, "TINY_AI_SCALE")
    w1 = _parse_header_array(text, "TINY_AI_W1")
    b1 = _parse_header_array(text, "TINY_AI_B1")
    w2 = _parse_header_array(text, "TINY_AI_W2")
    b2_match = re.search(
        r"static\s+const\s+float\s+TINY_AI_B2\s*=\s*([^;]+);", text
    )
    if not b2_match:
        raise ValueError("could not parse TINY_AI_B2 from header")
    b2 = float(b2_match.group(1).strip().rstrip("f"))
    threshold_match = re.search(
        r"#define\s+TINY_AI_THRESHOLD\s+([0-9.]+)f?", text
    )
    threshold = float(threshold_match.group(1)) if threshold_match else 0.5

    if mean.size != FEATURE_COUNT or scale.size != FEATURE_COUNT:
        raise ValueError("bad mean/scale size in header")
    if w1.size != HIDDEN * FEATURE_COUNT or b1.size != HIDDEN or w2.size != HIDDEN:
        raise ValueError("bad weight sizes in header")
    return {
        "mean": mean,
        "scale": scale,
        "params": {
            "W1": w1.reshape(HIDDEN, FEATURE_COUNT),
            "b1": b1,
            "W2": w2,
            "b2": np.asarray([b2], dtype=np.float64),
        },
        "threshold": float(threshold),
    }


def _split_masks(subject: np.ndarray) -> dict:
    masks = {
        "train": np.isin(subject, np.asarray(TRAIN_SUBJECTS, dtype=np.int16)),
        "validation": np.isin(subject, np.asarray(VAL_SUBJECTS, dtype=np.int16)),
        "test": np.isin(subject, np.asarray(TEST_SUBJECTS, dtype=np.int16)),
    }
    if sum(int(mask.sum()) for mask in masks.values()) != len(subject):
        raise AssertionError("split does not cover every window exactly once")
    return masks


def evaluate_baseline(
    model: dict,
    X: np.ndarray,
    y: np.ndarray,
    scen: np.ndarray,
    src: np.ndarray,
    masks: dict,
) -> dict:
    z = (X - model["mean"]) / model["scale"]
    probabilities = predict(model["params"], z)
    threshold = float(model["threshold"])
    val, test = masks["validation"], masks["test"]

    val_metrics = binary_metrics(y[val], probabilities[val], threshold)
    test_metrics = binary_metrics(y[test], probabilities[test], threshold)
    sweep_rows = threshold_sweep(y[val], probabilities[val])
    per_scenario_test = per_scenario_metrics(
        y,
        probabilities,
        test,
        threshold,
        scenarios=scen,
        sources=src,
    )
    per_scenario_val = per_scenario_metrics(
        y,
        probabilities,
        val,
        threshold,
        scenarios=scen,
        sources=src,
    )
    return {
        "model": "42 -> 16 (tanh) -> 1 (sigmoid), recording-level labels",
        "threshold": threshold,
        "standardization": {
            "mean_from": "training subjects 01-15",
            "operation": "z = (x - mean) / max(std, 1e-6)",
        },
        "validation_window_original_labels": val_metrics,
        "test_window_original_labels": test_metrics,
        "validation_event_level": event_level_metrics(
            probabilities,
            val,
            threshold,
            labels=y,
            sources=src,
            scenarios=scen,
        ),
        "test_event_level": event_level_metrics(
            probabilities,
            test,
            threshold,
            labels=y,
            sources=src,
            scenarios=scen,
        ),
        "validation_threshold_sweep": sweep_rows,
        "validation_threshold_sweep_compact": compact_sweep(
            sweep_rows, (val_metrics["threshold"],)
        ),
        "per_scenario_test": per_scenario_test,
        "per_scenario_test_false_positives": false_positive_summary(
            per_scenario_test
        ),
        "per_scenario_validation_false_positives": false_positive_summary(
            per_scenario_val
        ),
    }


# ---------------------------------------------------------------------------
# Candidate training (validation only)
# ---------------------------------------------------------------------------


def _class_weights(
    candidate: dict, y_train: np.ndarray
) -> tuple[float, float]:
    n = len(y_train)
    n_fall = int(np.sum(y_train == 1))
    n_adl = n - n_fall
    if candidate["class_weights"] == "balanced":
        return n / (2.0 * n_adl), n / (2.0 * n_fall)
    return float(candidate["adl_weight"]), float(candidate["fall_weight"])


def train_candidate(
    candidate: dict,
    X: np.ndarray,
    y: np.ndarray,
    y_refined: np.ndarray,
    keep: np.ndarray,
    scen: np.ndarray,
    src: np.ndarray,
    masks: dict,
) -> dict:
    train = masks["train"] & keep
    validation = masks["validation"] & keep
    y_train = y_refined[train]

    mean = np.asarray(X[train].mean(axis=0), dtype=np.float32).astype(np.float64)
    std = np.asarray(X[train].std(axis=0), dtype=np.float32).astype(np.float64)
    scale = np.maximum(std, 1e-6)
    z = (X - mean) / scale

    adl_weight, fall_weight = _class_weights(candidate, y_train)
    class_weights = np.asarray([adl_weight, fall_weight], dtype=np.float64)
    sample_weights = class_weights[y_train].copy()
    hard_negative = np.isin(
        scen[train], np.asarray(["non-fall/bed", "non-fall/chair"])
    ) & (y_train == 0)
    sample_weights[hard_negative] *= float(candidate["hard_negative_weight"])

    params, training_info = train_mlp(
        z[train],
        y_train,
        z[validation],
        y_refined[validation],
        sample_weights=sample_weights,
        seed=SEED,
        max_epochs=MAX_EPOCHS,
        patience=PATIENCE,
        learning_rate=LEARNING_RATE,
    )
    params = cast_params(params)

    probabilities = np.full(len(y), np.nan, dtype=np.float64)
    probabilities[masks["validation"]] = predict(params, z[masks["validation"]])

    selected, f1_optimal = select_threshold(
        y_refined[validation],
        probabilities[validation],
        MIN_EVENT_WINDOW_RECALL,
    )
    if selected is None:
        raise RuntimeError(
            f"candidate {candidate['id']} cannot reach the event recall target"
        )
    threshold = float(selected["threshold"])
    sweep_rows = threshold_sweep(
        y_refined[validation], probabilities[validation]
    )

    per_scenario = per_scenario_metrics(
        y_refined,
        probabilities,
        validation,
        threshold,
        scenarios=scen,
        sources=src,
    )
    legacy = binary_metrics(
        y[masks["validation"]],
        probabilities[masks["validation"]],
        threshold,
    )
    event_centered = binary_metrics(
        y_refined[validation],
        probabilities[validation],
        threshold,
    )

    return {
        "candidate": candidate,
        "params": params,
        "mean": mean,
        "scale": scale,
        "keep": keep,
        "labels_refined": y_refined,
        "probabilities": probabilities,
        "training_info": training_info,
        "class_weights": {"adl": adl_weight, "fall": fall_weight},
        "hard_negative_multiplier": float(candidate["hard_negative_weight"]),
        "threshold": threshold,
        "selected": selected,
        "f1_optimal": f1_optimal,
        "validation_threshold_sweep_compact": compact_sweep(
            sweep_rows, (threshold, f1_optimal["threshold"])
        ),
        "validation_event_centered": event_centered,
        "validation_legacy": legacy,
        "validation_event_level": None,  # filled by the caller with real sources
        "validation_per_scenario_false_positives": false_positive_summary(
            per_scenario
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", type=Path, default=DEFAULT_NPZ)
    parser.add_argument("--header", type=Path, default=DEFAULT_HEADER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT
    )
    parser.add_argument("--test-vector", type=Path, default=DEFAULT_TEST_VECTOR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.npz.is_file():
        print(
            f"error: {args.npz} not found; run tools/prepare_hifd.py first",
            file=sys.stderr,
        )
        return 2

    with np.load(args.npz, allow_pickle=False) as npz_file:
        npz = {key: npz_file[key] for key in npz_file.files}
    meta = json.loads(str(npz["meta"]))

    X = np.asarray(npz["X"], dtype=np.float64)
    y = np.asarray(npz["y"], dtype=np.int64)
    subject = np.asarray(npz["subject"], dtype=np.int64)
    scen = np.asarray(npz["scenario"]).astype(str)
    src = np.asarray(npz["source"]).astype(str)
    start = np.asarray(npz["start"], dtype=np.int64)
    if X.shape != (len(y), FEATURE_COUNT):
        raise ValueError(f"unexpected feature matrix shape {X.shape}")
    if not np.isfinite(X).all():
        raise ValueError("feature matrix contains non-finite values")

    masks = _split_masks(subject)
    for name, mask in masks.items():
        if len(np.unique(y[mask])) != 2:
            raise AssertionError(f"{name} split does not contain both classes")

    # Keep the previous report before it is overwritten, and preserve the old
    # header model as an independent baseline.  On reruns the baseline JSON is
    # authoritative so the improved header is never treated as the baseline.
    previous_report = None
    if args.report.is_file():
        with args.report.open("r", encoding="utf-8") as handle:
            previous_report = json.load(handle)

    if args.baseline_report.is_file():
        with args.baseline_report.open("r", encoding="utf-8") as handle:
            baseline_doc = json.load(handle)
        if "evaluation" not in baseline_doc:
            raise RuntimeError(
                f"{args.baseline_report} exists but has no 'evaluation' section"
            )
    else:
        if not args.header.is_file():
            raise FileNotFoundError(
                f"baseline header not found: {args.header}; cannot preserve baseline"
            )
        baseline_model = load_header_model(args.header)
        baseline_evaluation = evaluate_baseline(
            baseline_model, X, y, scen, src, masks
        )
        if previous_report is not None:
            recorded = previous_report.get("test", {})
            computed = baseline_evaluation["test_window_original_labels"]
            if "precision" in recorded and not np.isclose(
                recorded["precision"], computed["precision"], atol=1e-9
            ):
                print(
                    "warning: existing report test precision does not match the "
                    "header model; preserving both verbatim and recomputed",
                    file=sys.stderr,
                )
        baseline_doc = {
            "title": "HIFD baseline (recording-level labels) preserved metrics",
            "purpose": (
                "Frozen copy of the previous baseline artifacts and an independent "
                "re-evaluation of its exported 42->16->1 header."
            ),
            "preserved_from": {
                "header": args.header.relative_to(PROJECT_ROOT).as_posix(),
                "report": args.report.relative_to(PROJECT_ROOT).as_posix()
                if args.report.is_file()
                else None,
                "threshold": baseline_model["threshold"],
            },
            "original_report": previous_report,
            "evaluation": baseline_evaluation,
        }
        args.baseline_report.parent.mkdir(parents=True, exist_ok=True)
        with args.baseline_report.open("w", encoding="utf-8") as handle:
            json.dump(baseline_doc, handle, indent=2)
            handle.write("\n")

    baseline_evaluation = baseline_doc["evaluation"]

    # Detect the impact once per fall recording.  This is timing information
    # inside already-labeled fall recordings, not a new label source.
    event_data = detect_event_centers(src, y)
    centers = event_data["centers"]

    # Train every candidate on train subjects and score validation only.
    # No candidate probability is computed on test subjects here.
    candidate_results = []
    for candidate in CANDIDATES:
        refined, keep = event_centered_labels(
            y,
            start,
            src,
            centers,
            int(candidate["radius"]),
            int(candidate["exclude"]),
        )
        result = train_candidate(
            candidate, X, y, refined, keep, scen, src, masks
        )
        result["validation_event_level"] = event_level_metrics(
            result["probabilities"],
            masks["validation"],
            result["threshold"],
            labels=y,
            sources=src,
            scenarios=scen,
        )
        result["label_counts"] = {
            split: label_counts(refined, keep, mask, y)
            for split, mask in masks.items()
        }
        candidate_results.append(result)
        event_centered = result["validation_event_centered"]
        event_level = result["validation_event_level"]
        print(
            f"{candidate['id']:28s} val event-centered: "
            f"P={event_centered['precision']:.4f} "
            f"R={event_centered['recall']:.4f} "
            f"F1={event_centered['f1']:.4f} "
            f"t={result['threshold']:.2f} "
            f"FP={event_centered['confusion_matrix']['matrix'][1][0]} "
            f"eventR={event_level['event_recall']:.3f} "
            f"eventFP={event_level['adl_recordings_with_false_alarm']}"
        )

    # Selection rule (validation only): highest event-centered precision with
    # both window and event-level recall at/above target; ties by F1 then recall.
    eligible = [
        result
        for result in candidate_results
        if result["validation_event_centered"]["recall"]
        >= MIN_EVENT_WINDOW_RECALL
        and result["validation_event_level"]["event_recall"]
        >= MIN_EVENT_LEVEL_RECALL
    ]
    if not eligible:
        raise RuntimeError("no candidate satisfies the validation recall target")
    selected = max(
        eligible,
        key=lambda result: (
            result["validation_event_centered"]["precision"],
            result["validation_event_centered"]["f1"],
            result["validation_event_centered"]["recall"],
        ),
    )
    selected_id = selected["candidate"]["id"]
    eligible_ids = {result["candidate"]["id"] for result in eligible}
    print(f"selected (validation only): {selected_id}")

    # Test evaluation happens exactly once, for the selected candidate only.
    test = masks["test"]
    z_test = (X[test] - selected["mean"]) / selected["scale"]
    test_probabilities = predict(selected["params"], z_test)
    all_probabilities = np.full(len(y), np.nan, dtype=np.float64)
    all_probabilities[test] = test_probabilities
    threshold = float(selected["threshold"])
    refined = selected["labels_refined"]
    keep = selected["keep"]

    test_event = binary_metrics(
        refined[test & keep], all_probabilities[test & keep], threshold
    )
    test_legacy = binary_metrics(y[test], all_probabilities[test], threshold)
    test_event_level = event_level_metrics(
        all_probabilities,
        test,
        threshold,
        labels=y,
        sources=src,
        scenarios=scen,
    )
    test_per_scenario = per_scenario_metrics(
        refined,
        all_probabilities,
        test & keep,
        threshold,
        scenarios=scen,
        sources=src,
    )
    test_per_scenario_all = per_scenario_metrics(
        y,
        all_probabilities,
        test,
        threshold,
        scenarios=scen,
        sources=src,
    )

    val_event = selected["validation_event_centered"]
    val_legacy = selected["validation_legacy"]
    val_event_level = selected["validation_event_level"]
    val_per_scenario = per_scenario_metrics(
        refined,
        selected["probabilities"],
        masks["validation"] & keep,
        threshold,
        scenarios=scen,
        sources=src,
    )

    # Merge baseline vs improved per-scenario test results.  For non-fall
    # scenarios both views are identical (all windows ADL), so the comparison
    # is exact; for fall scenarios the event-centered row is used.
    baseline_scenarios = baseline_evaluation["per_scenario_test"]
    per_scenario_test_comparison = {}
    for scenario in sorted(set(test_per_scenario) | set(baseline_scenarios)):
        improved_row = test_per_scenario.get(scenario, {})
        baseline_row = baseline_scenarios.get(scenario, {})
        per_scenario_test_comparison[scenario] = {
            "n_windows": int(improved_row.get("n_windows", 0)),
            "folder_label_fall_windows": int(
                np.sum(test & (scen == scenario) & (y == 1))
            ),
            "event_centered_fall_windows": int(
                np.sum(test & (scen == scenario) & keep & (refined == 1))
            ),
            "baseline_false_positives_at_0_50": int(
                baseline_row.get("fp", 0)
            ),
            "improved_false_positives": int(improved_row.get("fp", 0)),
            "improved_false_positive_rate": float(
                improved_row.get("false_positive_rate", 0.0)
            ),
            "recordings": int(improved_row.get("recordings", 0)),
            "recordings_with_alert": int(
                improved_row.get("recordings_with_alert", 0)
            ),
        }

    # Export the header first so the fixture's expected output uses exactly the
    # parameters firmware will compile.
    export_header(
        args.header,
        selected["mean"],
        selected["scale"],
        selected["params"],
        threshold=threshold,
        baseline_test=baseline_evaluation["test_window_original_labels"],
        selected_test_event=test_event,
        selected_test_legacy=test_legacy,
        selected_test_event_level=test_event_level,
        selected_val_event=val_event,
        selected_val_event_level=val_event_level,
    )

    # Fixture: an event-centered test fall window classified correctly at the
    # exported threshold, preferring the strongest acceleration peak.
    test_indices = np.flatnonzero(test)
    candidate_positions = np.flatnonzero(
        (refined[test_indices] == 1) & (test_probabilities >= threshold)
    )
    if len(candidate_positions):
        peaks = X[test_indices, 40]  # mag_peak_abs
        chosen_position = int(
            candidate_positions[np.argmax(peaks[candidate_positions])]
        )
        selection_note = (
            "correctly classified event-centered held-out test fall window "
            "with the largest acceleration peak"
        )
    else:  # pragma: no cover - defensive fallback
        candidate_positions = np.flatnonzero(refined[test_indices] == 1)
        if not len(candidate_positions):
            raise RuntimeError("no event-centered fall window in the test split")
        chosen_position = int(
            candidate_positions[
                np.argmax(test_probabilities[candidate_positions])
            ]
        )
        selection_note = (
            "event-centered held-out test fall window with highest P(fall)"
        )
    chosen = int(test_indices[chosen_position])
    test_vector = build_test_vector(
        npz,
        meta,
        chosen,
        mean=selected["mean"],
        scale=selected["scale"],
        params=selected["params"],
        threshold=threshold,
        event_center=centers[str(src[chosen])],
    )
    test_vector["metadata"]["selection"] = selection_note + " (deterministic)"
    args.test_vector.parent.mkdir(parents=True, exist_ok=True)
    with args.test_vector.open("w", encoding="utf-8") as handle:
        json.dump(test_vector, handle, indent=2)
        handle.write("\n")

    # Split summaries.
    split_summary = {}
    for name, mask in masks.items():
        subjects = {
            "train": TRAIN_SUBJECTS,
            "validation": VAL_SUBJECTS,
            "test": TEST_SUBJECTS,
        }[name]
        split_summary[name] = {
            "subjects": list(subjects),
            "recordings": int(len(set(src[mask].tolist()))),
            "n_windows_original": int(mask.sum()),
            "n_fall_original": int(np.sum(y[mask] == 1)),
            "n_adl_original": int(np.sum(y[mask] == 0)),
            "event_centered": selected["label_counts"][name],
        }

    candidate_report = []
    for result in candidate_results:
        candidate = result["candidate"]
        candidate_report.append(
            {
                "id": candidate["id"],
                "description": candidate["description"],
                "label_rule": {
                    "positive_half_width_s": candidate["radius"] / SAMPLING_HZ,
                    "ambiguous_exclusion_half_width_s": candidate["exclude"]
                    / SAMPLING_HZ,
                    "adl_recordings_unchanged": True,
                },
                "class_weights": result["class_weights"],
                "hard_negative_multiplier": result["hard_negative_multiplier"],
                "training": {
                    "seed": SEED,
                    "max_epochs": MAX_EPOCHS,
                    "patience": PATIENCE,
                    "learning_rate": LEARNING_RATE,
                    "best_epoch": result["training_info"]["best_epoch"],
                    "epochs_run": result["training_info"]["epochs_run"],
                    "best_unweighted_validation_bce": result["training_info"][
                        "best_val_loss"
                    ],
                },
                "threshold_selection": {
                    "objective": (
                        "maximum event-centered validation precision subject to "
                        "window recall >= 0.90 on grid 0.30..0.95; ties -> lower "
                        "threshold (larger recall margin)"
                    ),
                    "selected_threshold": result["threshold"],
                    "selected_metrics": result["selected"],
                    "f1_optimal_threshold": result["f1_optimal"]["threshold"],
                    "f1_optimal_metrics": result["f1_optimal"],
                },
                "validation_event_centered": result[
                    "validation_event_centered"
                ],
                "validation_legacy_all_windows": result["validation_legacy"],
                "validation_threshold_sweep_compact": result[
                    "validation_threshold_sweep_compact"
                ],
                "validation_event_level": result["validation_event_level"],
                "validation_per_scenario_false_positives": result[
                    "validation_per_scenario_false_positives"
                ],
                "label_counts": result["label_counts"],
                "eligible": candidate["id"] in eligible_ids,
            }
        )

    report = {
        "title": (
            "HIFD real-data tiny fall classifier "
            "(event-centered, precision-first)"
        ),
        "generated_by": "tools/train_hifd_model.py",
        "selection_policy": {
            "test_used_for_selection": False,
            "threshold_grid": [float(value) for value in THRESHOLD_GRID],
            "threshold_grid_min": float(THRESHOLD_GRID[0]),
            "threshold_grid_max": float(THRESHOLD_GRID[-1]),
            "window_recall_target": MIN_EVENT_WINDOW_RECALL,
            "event_level_recall_target": MIN_EVENT_LEVEL_RECALL,
            "primary_metric": "event-centered window precision",
            "tie_break": (
                "event-centered F1, then recall; threshold ties -> lower threshold"
            ),
            "test_evaluated_once_for_selected_model": True,
            "selected_candidate": selected_id,
        },
        "dataset": {
            "name": meta["dataset"],
            "repository": meta["repository"],
            "git_commit": meta["git_commit"],
            "mat_files": meta["mat_files"],
            "total_samples": meta["total_samples"],
            "sampling_hz": meta["sampling_hz"],
            "window_samples": meta["window_samples"],
            "stride_samples": meta["stride_samples"],
            "window_seconds": meta["window_samples"] / meta["sampling_hz"],
            "accel_units": "m/s^2, gravity removed (raw g * 9.80665)",
            "gyro_units": "rad/s (HIFD raw values are deg/s; converted * pi/180)",
            "labels": meta["labels"],
            "inventory_counts": meta["inventory_counts"],
            "missing_scenarios": meta["missing_scenarios"],
            "total_windows": meta["windows"],
            "scenario_source": (
                "npz 'scenario' field, derived from subject_XX/{fall,non-fall}/"
                "<scenario>.mat paths"
            ),
        },
        "label_rule": {
            "summary": (
                "Only fall recordings are refined. Impact centre p = argmax of a "
                "5-sample centred moving average of the gravity-removed linear "
                "acceleration magnitude. Window centre within +-1.0 s of p -> "
                "fall; window fully outside p +-1.5 s -> ADL hard negative; "
                "remaining 1.0-1.5 s windows excluded. ADL recordings unchanged."
            ),
            "applies_to": "HIFD fall/ recordings only",
            "event_detection": {
                "signal": "sqrt(ax^2 + ay^2 + az^2), m/s^2, gravity removed",
                "smoothing": f"{EVENT_SMOOTH}-sample centred moving average",
                "peak": "argmax within each fall recording, ties -> first sample",
                "one_event_per_recording": True,
                "fall_recordings": int(len(centers)),
                "event_center_seconds_range": [
                    float(
                        min(
                            item["event_center_seconds"]
                            for item in event_data["details"].values()
                        )
                    ),
                    float(
                        max(
                            item["event_center_seconds"]
                            for item in event_data["details"].values()
                        )
                    ),
                ],
                "peak_smoothed_magnitude_range_m_s2": [
                    float(
                        min(
                            item["peak_smoothed_magnitude_m_s2"]
                            for item in event_data["details"].values()
                        )
                    ),
                    float(
                        max(
                            item["peak_smoothed_magnitude_m_s2"]
                            for item in event_data["details"].values()
                        )
                    ),
                ],
                "details": "computed at train time; not stored per window",
            },
            "window_rule": {
                "positive": (
                    f"|window_center - p| <= {EVENT_RADIUS} samples "
                    f"(<= {EVENT_RADIUS / SAMPLING_HZ:.1f} s)"
                ),
                "hard_negative": (
                    f"window_end < p - {EXCLUDE_RADIUS} or window_start > "
                    f"p + {EXCLUDE_RADIUS} (beyond "
                    f"{EXCLUDE_RADIUS / SAMPLING_HZ:.1f} s), relabeled adl"
                ),
                "ambiguous_excluded": (
                    "any other window in a fall recording; excluded from training "
                    "and from event-centered window metrics"
                ),
                "window_samples": WINDOW_SAMPLES,
                "stride_samples": int(meta["stride_samples"]),
            },
            "counts_by_split": {
                name: selected["label_counts"][name]
                for name in ("train", "validation", "test")
            },
            "no_synthetic_labels": (
                "No fall label is created outside fall/ recordings. Relabeling "
                "far windows as ADL uses only the existing recording label plus "
                "the impact timing inside that recording."
            ),
        },
        "splits": split_summary,
        "leakage_check": {
            "subject_wise": True,
            "overlap": False,
            "note": (
                "All windows of a subject belong to exactly one split. Adjacent "
                "windows overlap by design (stride 25 of 100), only within a split."
            ),
        },
        "features": {
            "count": FEATURE_COUNT,
            "order": list(FEATURE_NAMES),
            "changed_from_baseline": False,
            "standardization": {
                "operation": "z = (x - mean) / max(std, 1e-6)",
                "mean_from": "retained training-subject windows only",
                "std_ddof": 0,
            },
            "specification": "tools/hifd_features.md",
        },
        "baseline": {
            "source": "tools/hifd_model_report_baseline.json",
            "model": baseline_evaluation["model"],
            "threshold": baseline_evaluation["threshold"],
            "validation_window_original_labels": baseline_evaluation[
                "validation_window_original_labels"
            ],
            "test_window_original_labels": baseline_evaluation[
                "test_window_original_labels"
            ],
            "validation_event_level": baseline_evaluation[
                "validation_event_level"
            ],
            "test_event_level": baseline_evaluation["test_event_level"],
            "validation_threshold_sweep_compact": baseline_evaluation[
                "validation_threshold_sweep_compact"
            ],
            "per_scenario_validation_false_positives": baseline_evaluation[
                "per_scenario_validation_false_positives"
            ],
            "per_scenario_test_false_positives": baseline_evaluation[
                "per_scenario_test_false_positives"
            ],
        },
        "candidate_selection": {
            "objective": (
                "Reduce ADL false positives while keeping event-centered window "
                "recall >= 0.90 and event-level recall >= 0.90 on validation."
            ),
            "decision": (
                f"{selected_id}: highest validation event-centered precision "
                "among eligible candidates; ties by F1 then recall."
            ),
            "candidates": candidate_report,
        },
        "selected": {
            "id": selected_id,
            "description": selected["candidate"]["description"],
            "architecture": "42 -> 16 (tanh) -> 1 (sigmoid)",
            "loss": "weighted binary cross-entropy",
            "optimizer": "Adam (beta1=0.9, beta2=0.999, eps=1e-8), full batch",
            "early_stopping": "unweighted validation BCE",
            "class_weights": selected["class_weights"],
            "hard_negative_multiplier": selected["hard_negative_multiplier"],
            "threshold": threshold,
            "threshold_objective": (
                "max event-centered validation precision subject to window recall "
                ">= 0.90 on 0.30..0.95; ties -> lower threshold"
            ),
            "training": {
                "seed": SEED,
                "max_epochs": MAX_EPOCHS,
                "patience": PATIENCE,
                "learning_rate": LEARNING_RATE,
                "best_epoch": selected["training_info"]["best_epoch"],
                "epochs_run": selected["training_info"]["epochs_run"],
                "best_unweighted_validation_bce": selected["training_info"][
                    "best_val_loss"
                ],
                "history_samples": selected["training_info"]["history"],
            },
            "validation": {
                "event_centered_windows": val_event,
                "legacy_all_windows": val_legacy,
                "threshold_sweep_compact": selected[
                    "validation_threshold_sweep_compact"
                ],
                "event_level": val_event_level,
                "per_scenario_false_positives": false_positive_summary(
                    val_per_scenario
                ),
                "per_scenario": val_per_scenario,
            },
            "test": {
                "event_centered_windows": test_event,
                "legacy_all_windows": test_legacy,
                "event_level": test_event_level,
                "per_scenario_event_centered": test_per_scenario,
                "per_scenario_all_windows": test_per_scenario_all,
                "per_scenario_false_positives": false_positive_summary(
                    test_per_scenario_all
                ),
            },
        },
        "per_scenario_test_comparison": per_scenario_test_comparison,
        "artifacts": {
            "header": args.header.relative_to(PROJECT_ROOT).as_posix(),
            "test_vector": args.test_vector.relative_to(PROJECT_ROOT).as_posix(),
            "report": args.report.relative_to(PROJECT_ROOT).as_posix(),
            "baseline_report": args.baseline_report.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "processed_windows": args.npz.relative_to(PROJECT_ROOT).as_posix(),
        },
        "caveats": [
            (
                "Trained on real HIFD wrist data only; no synthetic data and no "
                "Edge Impulse upload."
            ),
            (
                "The legacy all-window recall is low by construction: "
                "pre/post-impact stillness windows are relabeled ADL because they "
                "are physically indistinguishable from bed/chair ADL. Legacy "
                "recall >= 0.90 with substantially better precision was not "
                "achievable under those labels."
            ),
            (
                "Event-level recall (one decision per recording) is the "
                "operationally meaningful recall and is reported alongside window "
                "metrics."
            ),
            (
                "Event centers come from the largest smoothed acceleration peak "
                "inside each fall recording; each HIFD fall recording contains one "
                "intentional fall."
            ),
            (
                "HIFD's droll/dpitch/dyaw are deg/s; they were converted to rad/s. "
                "The README does not state the unit."
            ),
            "Near-falls are not individually identified in HIFD and remain ADL.",
            (
                "HIFD uses a different wrist sensor and placement than Bio-Band; "
                "domain gap remains."
            ),
            (
                "Probabilities are not calibrated; the threshold is a "
                "validation-selected operating point."
            ),
            "Research demo only, not a medical device or a safety guarantee.",
            (
                "Some HIFD subject/scenario recordings are missing; see "
                "dataset.missing_scenarios."
            ),
            (
                "Metrics come from a single fixed training seed; validation seed "
                "sensitivity was observed but not used for selection."
            ),
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")

    print("subject-wise split:")
    for name in ("train", "validation", "test"):
        summary = split_summary[name]
        event = summary["event_centered"]
        print(
            f"  {name:10s} subjects={summary['subjects']} "
            f"recordings={summary['recordings']} "
            f"windows={summary['n_windows_original']} "
            f"(original fall={summary['n_fall_original']}, "
            f"adl={summary['n_adl_original']}; "
            f"event fall={event['fall_event_centered']}, "
            f"event adl={event['adl_event_centered']}, "
            f"excluded={event['ambiguous_windows_excluded']})"
        )
    print(
        f"selected   : {selected_id}, threshold={threshold:.2f}, "
        f"class_weights=({selected['class_weights']['adl']:.2f},"
        f"{selected['class_weights']['fall']:.2f}), "
        f"hardneg_x{selected['hard_negative_multiplier']:.1f}"
    )
    print(
        f"validation : event-centered acc={val_event['accuracy']:.4f} "
        f"prec={val_event['precision']:.4f} rec={val_event['recall']:.4f} "
        f"f1={val_event['f1']:.4f} cm={val_event['confusion_matrix']['matrix']}"
    )
    print(
        f"test       : event-centered acc={test_event['accuracy']:.4f} "
        f"prec={test_event['precision']:.4f} rec={test_event['recall']:.4f} "
        f"f1={test_event['f1']:.4f} cm={test_event['confusion_matrix']['matrix']}"
    )
    print(
        f"test legacy: prec={test_legacy['precision']:.4f} "
        f"rec={test_legacy['recall']:.4f} f1={test_legacy['f1']:.4f}"
    )
    print(
        f"event-level: test recall={test_event_level['event_recall']:.4f} "
        f"precision={test_event_level['event_precision']:.4f} "
        f"ADL false-alarm recordings="
        f"{test_event_level['adl_recordings_with_false_alarm']}/"
        f"{test_event_level['adl_recordings']}"
    )
    print(f"header      : {args.header}")
    print(f"report      : {args.report}")
    print(f"baseline    : {args.baseline_report}")
    print(f"test vector : {args.test_vector} (index {chosen})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
