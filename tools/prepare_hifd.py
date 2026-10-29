#!/usr/bin/env python3
"""Convert the public HIFD wrist IMU dataset into 42-feature windows.

This script is download-independent: it expects a local clone of
https://github.com/nhoyh/HR_IMU_falldetection_dataset at --dataset-root.

Pipeline
--------
  1. Read every subject_XX/{fall,non-fall}/*.mat recording (MATLAB v5 or v7.3).
  2. Build a 6-axis signal in SI units:
       ax, ay, az  = raw g values * 9.80665          [m/s^2]
       gx, gy, gz  = droll, dpitch, dyaw * pi / 180  [rad/s]
     HIFD stores angular velocity in deg/s (measured range +-2000, and it
     matches the quaternion derivative within a factor of ~57).  The task and
     the firmware use rad/s, so the conversion is applied here and recorded in
     the metadata.
  3. Slice 100-sample (2 s @ 50 Hz) windows with stride 25 (0.5 s), dropping
     incomplete windows.
  4. Extract 42 features per window (see tools/hifd_features.md).
  5. Label fall/ -> 1 and non-fall/ -> 0 (near-falls stay ADL).
  6. Save an un-standardized .npz (features, labels, subject, source, start).

The train/validation/test subject split lives in train_hifd_model.py so this
converter stays split-agnostic.

Example
-------
  .venv-ds/Scripts/python.exe tools/prepare_hifd.py \
      --dataset-root dataset/hifd \
      --out dataset/hifd_processed/hifd_windows.npz
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset" / "hifd"
DEFAULT_OUT = PROJECT_ROOT / "dataset" / "hifd_processed" / "hifd_windows.npz"

GRAVITY = 9.80665
# HIFD droll/dpitch/dyaw are in deg/s despite the README not stating units.
GYRO_DEG_TO_RAD = np.pi / 180.0

WINDOW_SAMPLES = 100  # 2 s at 50 Hz
STRIDE_SAMPLES = 25  # 0.5 s at 50 Hz
SAMPLE_PERIOD_S = 0.02

AXES = ("ax", "ay", "az", "gx", "gy", "gz")
AXIS_STATS = ("mean", "std", "min", "max", "rms", "mean_abs")
MAG_STATS = ("mean", "std", "min", "max", "peak_abs", "post_window_var_25")

FEATURE_NAMES = tuple(
    f"{axis}_{stat}" for axis in AXES for stat in AXIS_STATS
) + tuple(f"mag_{stat}" for stat in MAG_STATS)
assert len(FEATURE_NAMES) == 42

ALL_SCENARIOS = {
    "fall": [f"fall{i}" for i in range(1, 7)],
    "non-fall": [
        "bed",
        "chair",
        "clap",
        "cloth",
        "eat",
        "hair",
        "shoe",
        "stair",
        "teeth",
        "walk",
        "wash",
        "write",
        "zip",
    ],
}


def _flatten_numeric(value) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim > 1:
        # MATLAB columns: (N, 1); h5py may expose (1, N).  ravel('F') keeps
        # MATLAB memory order, but for a single vector every layout is equal
        # to the 1-D sequence.
        arr = arr.reshape(-1, order="F")
    return arr.ravel()


def _load_hdf5(path: Path) -> dict[str, np.ndarray]:
    try:
        import h5py  # type: ignore
    except ImportError as exc:  # pragma: no cover - all HIFD files are v5
        raise RuntimeError(
            f"{path} is MATLAB v7.3 and requires h5py; "
            "install it with: uv pip install --python .venv-ds/Scripts/python.exe h5py"
        ) from exc
    fields: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as handle:
        for key in ("ax", "ay", "az", "droll", "dpitch", "dyaw"):
            if key not in handle:
                raise KeyError(f"{path}: missing field {key!r}")
            fields[key] = _flatten_numeric(handle[key][()])
    return fields


def load_mat(path: Path) -> dict[str, np.ndarray]:
    """Load the six needed channels from a MATLAB v5 or v7.3 file."""
    try:
        mat = sio.loadmat(str(path))
        if any(key in mat for key in ("ax", "ay", "az")):
            return {
                key: _flatten_numeric(mat[key])
                for key in ("ax", "ay", "az", "droll", "dpitch", "dyaw")
            }
    except (NotImplementedError, ValueError):
        pass  # MATLAB v7.3 / HDF5
    return _load_hdf5(path)


def load_recording(
    path: Path, gyro_scale: float = GYRO_DEG_TO_RAD
) -> np.ndarray:
    """Return one recording as (N, 6) float64 in [ax ay az gx gy gz] SI units."""
    fields = load_mat(path)
    lengths = {key: len(value) for key, value in fields.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{path}: inconsistent channel lengths {lengths}")
    accel = np.column_stack(
        [fields[key] for key in ("ax", "ay", "az")]
    ) * GRAVITY
    gyro = np.column_stack(
        [fields[key] for key in ("droll", "dpitch", "dyaw")]
    ) * gyro_scale
    data = np.column_stack([accel, gyro])
    # Keep the feature contract deterministic even for damaged recordings.
    return np.nan_to_num(data, copy=False, nan=0.0, posinf=0.0, neginf=0.0)


def extract_features(window: np.ndarray) -> np.ndarray:
    """Extract the exact 42-float feature vector from a (100, 6) window."""
    window = np.asarray(window, dtype=np.float64)
    if window.ndim != 2 or window.shape[1] != 6:
        raise ValueError(f"expected (N, 6) window, got {window.shape}")
    if window.shape[0] < 25:
        raise ValueError("window must have at least 25 samples")

    features: list[float] = []
    for axis in range(6):
        x = window[:, axis]
        features.extend(
            (
                float(np.mean(x)),
                float(np.std(x, ddof=0)),  # population std
                float(np.min(x)),
                float(np.max(x)),
                float(np.sqrt(np.mean(np.square(x)))),  # RMS
                float(np.mean(np.abs(x))),
            )
        )

    # Magnitude uses the three LINEAR acceleration axes only.
    accel = window[:, :3]
    mag = np.sqrt(np.sum(np.square(accel), axis=1))
    features.extend(
        (
            float(np.mean(mag)),
            float(np.std(mag, ddof=0)),
            float(np.min(mag)),
            float(np.max(mag)),
            float(np.max(np.abs(mag))),
            float(np.var(mag[-25:], ddof=0)),  # post-window variance
        )
    )

    out = np.asarray(features, dtype=np.float64)
    out[~np.isfinite(out)] = 0.0
    return out


def window_signal(data: np.ndarray, window: int, stride: int):
    """Yield (start, window) pairs; the final partial window is dropped."""
    n_samples = data.shape[0]
    starts = range(0, n_samples - window + 1, stride)
    for start in starts:
        yield start, data[start : start + window]


def _scenario_category(folder: str) -> str:
    normalized = folder.strip().lower().replace("_", "-")
    if normalized in ("fall", "falls"):
        return "fall"
    if normalized in ("non-fall", "nonfall", "nonfalls", "adl"):
        return "non-fall"
    raise ValueError(f"unexpected class folder {folder!r}")


def discover_files(dataset_root: Path) -> list[tuple[int, str, str, Path]]:
    """Return (subject, category, scenario, path) sorted deterministically."""
    records: list[tuple[int, str, str, Path]] = []
    for subject_dir in sorted(dataset_root.glob("subject_*")):
        if not subject_dir.is_dir():
            continue
        try:
            subject = int(subject_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        for class_dir in sorted(subject_dir.iterdir()):
            if not class_dir.is_dir():
                continue
            category = _scenario_category(class_dir.name)
            for mat_path in sorted(class_dir.glob("*.mat")):
                records.append(
                    (subject, category, mat_path.stem, mat_path.resolve())
                )
    return records


def build_metadata(
    dataset_root: Path,
    records: list[tuple[int, str, str, Path]],
    total_samples: int,
    window: int,
    stride: int,
    gyro_scale: float,
    dropped_short_files: list[str],
) -> dict:
    inventory: dict[str, dict[str, object]] = {}
    seen: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    subject_files: dict[int, list[str]] = collections.defaultdict(list)
    for subject, category, scenario, path in records:
        seen[(category, scenario)].add(subject)
        subject_files[subject].append(f"{category}/{scenario}")
        entry = inventory.setdefault(
            f"subject_{subject:02d}", {"fall": [], "non-fall": []}
        )
        entry[category].append(scenario)

    missing = {}
    for category, scenarios in ALL_SCENARIOS.items():
        missing[category] = {}
        for scenario in scenarios:
            present = sorted(seen[(category, scenario)])
            absent = sorted(set(subject_files) - set(present))
            if absent:
                missing[category][scenario] = {
                    "present_subjects": present,
                    "missing_subjects": absent,
                }

    git_commit = None
    head = dataset_root / ".git"
    if head.exists():
        import subprocess

        try:
            git_commit = subprocess.check_output(
                ["git", "-C", str(dataset_root), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:  # noqa: BLE001 - metadata must never break conversion
            git_commit = None

    return {
        "dataset": "HIFD (Heart Rate & IMU sensor data for fall detection)",
        "repository": "https://github.com/nhoyh/HR_IMU_falldetection_dataset",
        "git_commit": git_commit,
        "sampling_hz": 50,
        "sample_period_s": SAMPLE_PERIOD_S,
        "window_samples": window,
        "stride_samples": stride,
        "mat_files": len(records),
        "total_samples": total_samples,
        "channels": [
            "ax (m/s^2)",
            "ay (m/s^2)",
            "az (m/s^2)",
            "gx (rad/s)",
            "gy (rad/s)",
            "gz (rad/s)",
        ],
        "accel_conversion": "raw g * 9.80665",
        "gyro_conversion": f"raw deg/s * {gyro_scale!r}",
        "gyro_scale": gyro_scale,
        "gyro_source_unit": "deg/s (inferred from +-2000 range; README omits units)",
        "labels": {
            "fall": 1,
            "adl": 0,
            "folder_mapping": {"fall": "fall", "non-fall": "adl"},
            "near_falls": "not separately identified; kept in adl",
        },
        "inventory_counts": {
            key: {"fall": len(value["fall"]), "non-fall": len(value["non-fall"])}
            for key, value in inventory.items()
        },
        "missing_scenarios": missing,
        "short_files_dropped": dropped_short_files,
        "feature_names": list(FEATURE_NAMES),
    }


def convert(
    dataset_root: Path,
    out_path: Path,
    window: int = WINDOW_SAMPLES,
    stride: int = STRIDE_SAMPLES,
    gyro_scale: float = GYRO_DEG_TO_RAD,
) -> dict:
    if not dataset_root.is_dir():
        raise FileNotFoundError(
            f"dataset not found at {dataset_root}; clone HIFD first "
            "(git clone --depth 1 https://github.com/nhoyh/"
            "HR_IMU_falldetection_dataset.git dataset/hifd)"
        )
    records = discover_files(dataset_root)
    if not records:
        raise RuntimeError(f"no .mat recordings found under {dataset_root}")

    X: list[np.ndarray] = []
    y: list[int] = []
    subjects: list[int] = []
    scenarios: list[str] = []
    sources: list[str] = []
    starts: list[int] = []
    dropped: list[str] = []
    total_samples = 0

    for subject, category, scenario, path in records:
        data = load_recording(path, gyro_scale=gyro_scale)
        total_samples += data.shape[0]
        if data.shape[0] < window:
            dropped.append(str(path.relative_to(PROJECT_ROOT)))
            continue
        label = 1 if category == "fall" else 0
        for start, win in window_signal(data, window, stride):
            X.append(extract_features(win))
            y.append(label)
            subjects.append(subject)
            scenarios.append(f"{category}/{scenario}")
            sources.append(path.relative_to(PROJECT_ROOT).as_posix())
            starts.append(start)

    if not X:
        raise RuntimeError("no complete windows produced")

    feature_matrix = np.asarray(X, dtype=np.float64)
    labels = np.asarray(y, dtype=np.int8)
    meta = build_metadata(
        dataset_root,
        records,
        total_samples,
        window,
        stride,
        gyro_scale,
        dropped,
    )
    meta["windows"] = {
        "total": int(len(labels)),
        "fall": int(np.sum(labels == 1)),
        "adl": int(np.sum(labels == 0)),
    }
    meta["raw_slice_convention"] = "window = data[start:start+window]"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        X=feature_matrix,
        y=labels,
        subject=np.asarray(subjects, dtype=np.int16),
        scenario=np.asarray(scenarios, dtype="<U24"),
        source=np.asarray(sources, dtype="<U96"),
        start=np.asarray(starts, dtype=np.int32),
        meta=np.asarray(json.dumps(meta, sort_keys=True)),
    )

    print(f"recordings : {len(records)} .mat files, {total_samples} samples")
    print(
        f"windows    : {meta['windows']['total']} "
        f"(fall={meta['windows']['fall']}, adl={meta['windows']['adl']})"
    )
    print(f"short files dropped: {len(dropped)}")
    print(f"saved      : {out_path}")

    per_subject = collections.Counter()
    per_subject_fall = collections.Counter()
    for subject, label in zip(subjects, labels):
        per_subject[int(subject)] += 1
        per_subject_fall[int(subject)] += int(label == 1)
    print("per-subject windows (fall/total):")
    for subject in sorted(per_subject):
        print(
            f"  subject_{subject:02d}: "
            f"{per_subject_fall[subject]:4d}/{per_subject[subject]:4d}"
        )
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--window", type=int, default=WINDOW_SAMPLES)
    parser.add_argument("--stride", type=int, default=STRIDE_SAMPLES)
    parser.add_argument(
        "--gyro-scale",
        type=float,
        default=GYRO_DEG_TO_RAD,
        help="multiplier applied to droll/dpitch/dyaw (default: deg->rad)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.window <= 0 or args.stride <= 0:
        print("error: --window and --stride must be positive", file=sys.stderr)
        return 2
    convert(
        args.dataset_root.resolve(),
        args.out.resolve(),
        window=args.window,
        stride=args.stride,
        gyro_scale=args.gyro_scale,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
