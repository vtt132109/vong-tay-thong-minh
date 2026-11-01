"""HIFD recordings -> raw per-recording arrays (cached), windows, event labels.

Everything downstream (augmentation, firmware-preprocessing simulation, models,
leave-one-subject-out evaluation) starts from `load_recordings()`.

Units: accel m/s^2 (gravity already removed by the HIFD authors), gyro rad/s,
quaternion (w, x, y, z) as stored in the .mat files, 50 Hz.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import scipy.io as sio

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset" / "hifd"
CACHE = ROOT / "dataset" / "hifd_cache" / "recordings.pkl"

G = 9.80665
FS = 50
WIN = 100
STRIDE = 25
EVENT_SMOOTH = 5


@dataclass
class Recording:
    subject: int
    category: str          # "fall" | "non-fall"
    scenario: str          # e.g. "fall2", "clap"
    path: str
    lin: np.ndarray        # (N,3) m/s^2, gravity removed
    gyro: np.ndarray       # (N,3) rad/s
    quat: np.ndarray       # (N,4) w,x,y,z
    center: int | None     # impact sample for fall recordings

    @property
    def n(self) -> int:
        return self.lin.shape[0]

    @property
    def is_fall(self) -> bool:
        return self.category == "fall"

    @property
    def name(self) -> str:
        return f"s{self.subject:02d}/{self.category}/{self.scenario}"


def _col(m, k):
    return np.asarray(m[k], dtype=np.float64).reshape(-1, order="F")


def _load_one(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = sio.loadmat(str(path))
    lin = np.column_stack([_col(m, k) for k in ("ax", "ay", "az")]) * G
    gyro = np.column_stack([_col(m, k) for k in ("droll", "dpitch", "dyaw")]) * (np.pi / 180.0)
    quat = np.column_stack([_col(m, k) for k in ("w", "x", "y", "z")])
    return (np.nan_to_num(lin), np.nan_to_num(gyro), np.nan_to_num(quat))


def load_recordings(refresh: bool = False) -> list[Recording]:
    if CACHE.is_file() and not refresh:
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    recs: list[Recording] = []
    for sdir in sorted(DATASET.glob("subject_*")):
        subject = int(sdir.name.split("_")[1])
        for cdir in sorted(p for p in sdir.iterdir() if p.is_dir()):
            category = "fall" if cdir.name.lower().startswith("fall") else "non-fall"
            for f in sorted(cdir.glob("*.mat")):
                lin, gyro, quat = _load_one(f)
                center = None
                if category == "fall":
                    mag = np.linalg.norm(lin, axis=1)
                    sm = np.convolve(mag, np.ones(EVENT_SMOOTH) / EVENT_SMOOTH, mode="same")
                    center = int(np.argmax(sm))
                recs.append(Recording(subject, category, f.stem, str(f.relative_to(ROOT)),
                                      lin, gyro, quat, center))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump(recs, fh)
    return recs


def window_starts(n: int) -> np.ndarray:
    return np.arange(0, n - WIN + 1, STRIDE)


def event_label(start: int, center: int | None, radius: int = 50, exclude: int = 75):
    """Return (label, keep) for one window under the event-centered rule."""
    if center is None:
        return 0, True
    wc = start + WIN // 2
    if abs(wc - center) <= radius:
        return 1, True
    if start + WIN - 1 < center - exclude or start > center + exclude:
        return 0, True
    return 0, False


SPLIT = {"train": range(1, 16), "val": range(16, 19), "test": range(19, 22)}


def split_of(subject: int) -> str:
    for k, r in SPLIT.items():
        if subject in r:
            return k
    raise ValueError(subject)


if __name__ == "__main__":
    recs = load_recordings(refresh=True)
    falls = [r for r in recs if r.is_fall]
    print(len(recs), "recordings;", len(falls), "falls;",
          sum(r.n for r in recs), "samples")
    print("example", recs[0].name, recs[0].n, recs[0].center)
