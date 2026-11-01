"""Simulate what the Bio-Band firmware feeds to the model, starting from HIFD.

HIFD gives gravity-REMOVED acceleration + a quaternion. The firmware sees raw
MPU6050 acceleration (gravity included), band-limited by the DLPF, and removes
gravity itself with a first-order low-pass (alpha 0.98). This module rebuilds
that signal chain so models can be trained/evaluated on what the board really
produces (GD B of PLAN.md).

ASSUMPTION (documented in BAO_CAO.md): the HIFD quaternion rotates body->world;
gravity in the sensor frame is R^T [0,0,g]. The cross-check against the gyro
(see check_gravity_convention) favours this convention (|cos| 0.50 vs 0.03).
Random-rotation augmentation covers the remaining uncertainty.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from .data import G, FS, Recording

ACC_CLIP = 16 * G          # MPU6050 +-16 g
GYRO_CLIP = 2000 * np.pi / 180
FW_ALPHA = 0.98            # src/ai_model.cpp TINY_GRAVITY_ALPHA


def quat_to_R(q: np.ndarray) -> np.ndarray:
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
    w, x, y, z = q.T
    R = np.empty((len(q), 3, 3))
    R[:, 0, 0] = 1 - 2 * (y * y + z * z); R[:, 0, 1] = 2 * (x * y - z * w); R[:, 0, 2] = 2 * (x * z + y * w)
    R[:, 1, 0] = 2 * (x * y + z * w); R[:, 1, 1] = 1 - 2 * (x * x + z * z); R[:, 1, 2] = 2 * (y * z - x * w)
    R[:, 2, 0] = 2 * (x * z - y * w); R[:, 2, 1] = 2 * (y * z + x * w); R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def gravity_in_sensor(rec: Recording) -> np.ndarray:
    R = quat_to_R(rec.quat)
    return np.einsum("nji,j->ni", R, np.array([0.0, 0.0, G]))


def raw_acc(rec: Recording) -> np.ndarray:
    """Accelerometer reading the MPU6050 would report (gravity included)."""
    return rec.lin + gravity_in_sensor(rec)


def random_rotation(rng: np.random.Generator, max_angle: float | None = None) -> np.ndarray:
    """Uniform SO(3) rotation, or axis-random rotation limited to max_angle (rad)."""
    if max_angle is None:
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        w, x, y, z = q
    else:
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        ang = rng.uniform(-max_angle, max_angle)
        w, x, y, z = np.cos(ang / 2), *(axis * np.sin(ang / 2))
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


_SOS = butter(2, 21.0 / (FS / 2), btype="low", output="sos")


def firmware_chain(raw: np.ndarray, gyro: np.ndarray, *, dlpf: bool = True,
                   clip: bool = True, alpha: float = FW_ALPHA,
                   gyro_bias: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """raw acc (gravity incl.) + gyro -> (linear acc, gyro) as src/ai_model.cpp sees them."""
    a = raw.copy()
    g = gyro.copy()
    if gyro_bias is not None:
        g = g + gyro_bias
    if dlpf:
        a = sosfilt(_SOS, a, axis=0)
        g = sosfilt(_SOS, g, axis=0)
    if clip:
        a = np.clip(a, -ACC_CLIP, ACC_CLIP)
        g = np.clip(g, -GYRO_CLIP, GYRO_CLIP)
    grav = np.empty_like(a)
    grav[0] = a[0]
    beta = 1.0 - alpha
    for i in range(1, len(a)):
        grav[i] = grav[i - 1] + beta * (a[i] - grav[i - 1])
    return a - grav, g


def make_signal(rec: Recording, view: str, rng: np.random.Generator | None = None,
                rot: str | None = None, bias: float = 0.0) -> np.ndarray:
    """(N,6) signal [lin(3), gyro(3)] for a given training/evaluation view.

    view: 'hifd'  -> as published (what the shipped model was trained on)
          'fw'    -> full firmware chain (gravity re-added, DLPF, clip, HP gravity removal)
    rot:  None | 'so3' | 'small' (+-30 deg) random sensor rotation (augmentation)
    bias: gyro zero-rate offset amplitude (rad/s), uniform per axis
    """
    rng = rng or np.random.default_rng(0)
    if view == "hifd":
        lin, gyro = rec.lin.copy(), rec.gyro.copy()
        raw = None
    elif view == "fw":
        raw = raw_acc(rec)
        gyro = rec.gyro
    else:
        raise ValueError(view)
    Rm = None
    if rot == "so3":
        Rm = random_rotation(rng)
    elif rot == "small":
        Rm = random_rotation(rng, np.deg2rad(30))
    if view == "fw":
        if Rm is not None:
            raw = raw @ Rm.T
            gyro = gyro @ Rm.T
        b = rng.uniform(-bias, bias, 3) if bias > 0 else None
        lin, gyro = firmware_chain(raw, gyro, gyro_bias=b)
    else:
        if Rm is not None:
            lin = lin @ Rm.T
            gyro = gyro @ Rm.T
        if bias > 0:
            gyro = gyro + rng.uniform(-bias, bias, 3)
    return np.column_stack([lin, gyro]).astype(np.float32)


def check_gravity_convention(recs, n: int = 150) -> dict:
    out = {"world->body": [], "body->world": []}
    up = np.array([0.0, 0.0, G])
    for r in recs[:n]:
        R = quat_to_R(r.quat)
        gs = {"world->body": np.einsum("nji,j->ni", R, up),
              "body->world": np.einsum("nij,j->ni", R, up)}
        for k, g in gs.items():
            dg = np.gradient(g, 1 / FS, axis=0)
            pred = -np.cross(r.gyro, g)
            m = np.linalg.norm(pred, axis=1) > 2.0
            if m.sum() < 20:
                continue
            c = np.sum(dg[m] * pred[m], axis=1) / (
                np.linalg.norm(dg[m], axis=1) * np.linalg.norm(pred[m], axis=1) + 1e-9)
            out[k].append(float(np.median(c)))
    return {k: float(np.median(v)) for k, v in out.items()}
