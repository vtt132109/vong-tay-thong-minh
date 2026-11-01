"""Vectorised feature sets.

feat42  : exact firmware feature contract (tools/hifd_features.md), batched.
featinv : orientation-invariant features (do not depend on sensor axis convention).
"""
from __future__ import annotations

import numpy as np

FEAT42_NAMES = [f"{a}_{s}" for a in ("ax", "ay", "az", "gx", "gy", "gz")
                for s in ("mean", "std", "min", "max", "rms", "mean_abs")] + \
               [f"mag_{s}" for s in ("mean", "std", "min", "max", "peak_abs", "post_var_25")]


def feat42(W: np.ndarray) -> np.ndarray:
    """W: (n,100,6) -> (n,42) float64, identical definitions to prepare_hifd.extract_features."""
    W = W.astype(np.float64)
    n = len(W)
    out = np.empty((n, 42))
    for a in range(6):
        x = W[:, :, a]
        out[:, a * 6 + 0] = x.mean(1)
        out[:, a * 6 + 1] = x.std(1)
        out[:, a * 6 + 2] = x.min(1)
        out[:, a * 6 + 3] = x.max(1)
        out[:, a * 6 + 4] = np.sqrt((x * x).mean(1))
        out[:, a * 6 + 5] = np.abs(x).mean(1)
    mag = np.linalg.norm(W[:, :, :3], axis=2)
    out[:, 36] = mag.mean(1)
    out[:, 37] = mag.std(1)
    out[:, 38] = mag.min(1)
    out[:, 39] = mag.max(1)
    out[:, 40] = np.abs(mag).max(1)
    out[:, 41] = mag[:, -25:].var(1)
    out[~np.isfinite(out)] = 0.0
    return out


FEATINV_NAMES = (
    [f"am_{s}" for s in ("mean", "std", "min", "max", "rms", "var_first25", "var_last25", "argmax", "n_gt15", "n_gt30")] +
    [f"gm_{s}" for s in ("mean", "std", "min", "max", "rms", "var_first25", "var_last25", "argmax")] +
    [f"jerk_{s}" for s in ("mean", "max", "std")] +
    ["acc_eig1", "acc_eig2", "acc_eig3", "gyro_eig1", "gyro_eig2", "gyro_eig3",
     "peak_to_tail", "gyro_peak_dt", "acc_gyro_corr"]
)


def featinv(W: np.ndarray) -> np.ndarray:
    W = W.astype(np.float64)
    A, Gy = W[:, :, :3], W[:, :, 3:]
    am = np.linalg.norm(A, axis=2)
    gm = np.linalg.norm(Gy, axis=2)
    cols = [
        am.mean(1), am.std(1), am.min(1), am.max(1), np.sqrt((am ** 2).mean(1)),
        am[:, :25].var(1), am[:, -25:].var(1), am.argmax(1) / 100.0,
        (am > 15).sum(1), (am > 30).sum(1),
        gm.mean(1), gm.std(1), gm.min(1), gm.max(1), np.sqrt((gm ** 2).mean(1)),
        gm[:, :25].var(1), gm[:, -25:].var(1), gm.argmax(1) / 100.0,
    ]
    jerk = np.abs(np.diff(am, axis=1)) * 50.0
    cols += [jerk.mean(1), jerk.max(1), jerk.std(1)]

    def eigs(X):
        Xc = X - X.mean(1, keepdims=True)
        C = np.einsum("nti,ntj->nij", Xc, Xc) / X.shape[1]
        ev = np.linalg.eigvalsh(C)  # ascending
        return np.sqrt(np.maximum(ev[:, ::-1], 0.0))

    ea, eg = eigs(A), eigs(Gy)
    cols += [ea[:, 0], ea[:, 1], ea[:, 2], eg[:, 0], eg[:, 1], eg[:, 2]]
    tail = am[:, -25:].mean(1)
    cols.append(am.max(1) / (tail + 1.0))
    cols.append((gm.argmax(1) - am.argmax(1)) / 100.0)
    ac = am - am.mean(1, keepdims=True)
    gc = gm - gm.mean(1, keepdims=True)
    cols.append((ac * gc).mean(1) / (ac.std(1) * gc.std(1) + 1e-6))
    out = np.column_stack(cols)
    out[~np.isfinite(out)] = 0.0
    return out
