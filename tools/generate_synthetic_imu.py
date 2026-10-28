#!/usr/bin/env python3
"""Generate synthetic 6-axis IMU windows for a wrist-worn fall detector.

This script fabricates physically plausible accelerometer/gyroscope windows for
pipeline and demo testing of an Edge Impulse fall-detection model targeting an
ESP32-S3 wristband (MPU6050, 50 Hz, 2 s windows). It is deliberately
standard-library only: no numpy, pandas, or external data files are needed.

Output layout (relative to --out):
    dataset/training/fall/fall_0000.csv
    dataset/training/adl/adl_0000.csv
    dataset/testing/fall/fall_0000.csv
    dataset/testing/adl/adl_0000.csv

Every CSV contains 100 rows of data for the default 2 s / 50 Hz window and the
header:
    timestamp,ax,ay,az,gx,gy,gz

Acceleration is in m/s^2, angular rate in rad/s, and timestamps start at 0 ms.
Values are rounded to four decimal places and clamped to a plausible MPU6050
range (about +/-8 g and +/-1000 deg/s). Generation is deterministic for a given
--seed.

Fall windows contain a pre-impact baseline, a 0.24-0.40 s free fall below
5 m/s^2, a sharp 27-58 m/s^2 impact spike on a randomly chosen axis that decays
within roughly 200 ms, a bounce/rotation, and a low-motion post-impact tail.
ADL windows mix idle/sitting, walking, sit-stand transitions, and hand movement;
their acceleration axes are held below the 25 m/s^2 fall threshold.

Usage:
    python tools/generate_synthetic_imu.py
    python tools/generate_synthetic_imu.py --out dataset --samples-per-class 80
    python tools/generate_synthetic_imu.py --seed 7 --test-samples-per-class 10

WARNING: this is synthetic, hand-crafted data for wiring up and demonstrating a
pipeline. It is NOT a substitute for measurements from real people. Models
trained on it will not generalize to real falls, body sizes, wrist orientations,
or sensor mounting. Collect and label real wristband data before reporting any
accuracy or deploying a detector.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path
from typing import List, Sequence, Tuple

Vec3 = Tuple[float, float, float]
Row = List[float]  # [ax, ay, az, gx, gy, gz]

GRAVITY_MS2 = 9.80665
FALL_THRESHOLD_MS2 = 25.0
# Keep all ADL accelerometer axes clearly under the fall threshold.
ADL_ACCEL_LIMIT_MS2 = 24.0
# Typical configured MPU6050 ranges: +/-8 g, +/-1000 deg/s.
ACCEL_CLAMP_MS2 = 78.5
GYRO_CLAMP_RAD_S = 17.45
TWO_PI = 2.0 * math.pi


# ---------------------------------------------------------------------------
# Small vector / math helpers
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* to the inclusive interval [low, high]."""
    return low if value < low else high if value > high else value


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: Vec3) -> float:
    return math.sqrt(_dot(v, v))


def _scale(v: Vec3, factor: float) -> Vec3:
    return (v[0] * factor, v[1] * factor, v[2] * factor)


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _unit(v: Vec3, fallback: Vec3 = (0.0, 0.0, 1.0)) -> Vec3:
    length = _norm(v)
    if length < 1e-9:
        return fallback
    return (v[0] / length, v[1] / length, v[2] / length)


def _tilted_up(rng: random.Random, min_deg: float, max_deg: float) -> Vec3:
    """Return a unit 'up' vector with a random tilt from the device +z axis.

    The accelerometer at rest reads +1 g along this vector. Small tilts model a
    mostly upright wrist; large tilts model a limb lying on the ground.
    """
    tilt = math.radians(rng.uniform(min_deg, max_deg))
    azimuth = rng.uniform(0.0, TWO_PI)
    return (
        math.sin(tilt) * math.cos(azimuth),
        math.sin(tilt) * math.sin(azimuth),
        math.cos(tilt),
    )


def _horizontal_dir(up: Vec3) -> Vec3:
    """Return a unit horizontal direction perpendicular to *up*."""
    return _unit((up[0], up[1], 0.0), fallback=(1.0, 0.0, 0.0))


def _slerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Spherical interpolation between two unit vectors (t in [0, 1])."""
    t = _clamp(t, 0.0, 1.0)
    cos_angle = _clamp(_dot(a, b), -1.0, 1.0)
    if cos_angle > 0.9995:  # nearly parallel: plain normalized lerp
        return _unit(
            (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
            ),
            fallback=a,
        )
    angle = math.acos(cos_angle)
    sin_angle = math.sin(angle)
    # Both endpoints are unit vectors, so standard slerp stays on the sphere.
    return (
        a[0] * math.sin((1.0 - t) * angle) / sin_angle
        + b[0] * math.sin(t * angle) / sin_angle,
        a[1] * math.sin((1.0 - t) * angle) / sin_angle
        + b[1] * math.sin(t * angle) / sin_angle,
        a[2] * math.sin((1.0 - t) * angle) / sin_angle
        + b[2] * math.sin(t * angle) / sin_angle,
    )


def _smoothstep(t: float) -> float:
    """Ease-in/ease-out ramp on [0, 1]."""
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _orientation_rate(prev: Vec3, curr: Vec3, dt: float) -> Vec3:
    """Angular velocity (rad/s) that rotates *prev* into *curr* in *dt*."""
    axis = _cross(prev, curr)
    sin_angle = _norm(axis)
    if sin_angle < 1e-9:
        return (0.0, 0.0, 0.0)
    angle = math.acos(_clamp(_dot(prev, curr), -1.0, 1.0))
    rate = angle / dt
    return (
        axis[0] / sin_angle * rate,
        axis[1] / sin_angle * rate,
        axis[2] / sin_angle * rate,
    )


def _gyro_from_orientations(ups: Sequence[Vec3], dt: float) -> List[Vec3]:
    """Differentiate an orientation sequence into body angular rates."""
    rates: List[Vec3] = [(0.0, 0.0, 0.0)]
    for i in range(1, len(ups)):
        rates.append(_orientation_rate(ups[i - 1], ups[i], dt))
    return rates


def _finish(
    rows: Sequence[Row],
    rng: random.Random,
    accel_sigma: float,
    gyro_sigma: float,
    accel_limit: float,
) -> List[Row]:
    """Add sensor noise, clamp to sensor range, and return mutable rows."""
    noisy: List[Row] = []
    for row in rows:
        values = [
            row[0] + rng.gauss(0.0, accel_sigma),
            row[1] + rng.gauss(0.0, accel_sigma),
            row[2] + rng.gauss(0.0, accel_sigma),
            row[3] + rng.gauss(0.0, gyro_sigma),
            row[4] + rng.gauss(0.0, gyro_sigma),
            row[5] + rng.gauss(0.0, gyro_sigma),
        ]
        for k in range(3):
            values[k] = _clamp(values[k], -accel_limit, accel_limit)
        for k in range(3, 6):
            values[k] = _clamp(values[k], -GYRO_CLAMP_RAD_S, GYRO_CLAMP_RAD_S)
        noisy.append(values)
    return noisy


# ---------------------------------------------------------------------------
# ADL synthesis
# ---------------------------------------------------------------------------
def synthesize_idle(
    n: int, dt: float, rng: random.Random, sitting: bool = False
) -> List[Row]:
    """Near-still wrist: gravity mostly on z plus small sway and noise."""
    up = _tilted_up(rng, 1.0, 12.0 if sitting else 7.0)
    horizontal = _horizontal_dir(up)
    sway_amp = rng.uniform(0.02, 0.10)  # m/s^2, breathing / posture sway
    sway_hz = rng.uniform(0.15, 0.35)
    sway_phase = rng.uniform(0.0, TWO_PI)
    gyro_amp = rng.uniform(0.004, 0.018)
    gyro_phase = rng.uniform(0.0, TWO_PI)

    rows: List[Row] = []
    for i in range(n):
        t = i * dt
        sway = sway_amp * math.sin(TWO_PI * sway_hz * t + sway_phase)
        vertical = 0.02 * math.sin(TWO_PI * 0.6 * t + sway_phase)
        accel = _add(
            _scale(up, GRAVITY_MS2 + vertical),
            _scale(horizontal, sway),
        )
        gyro = (
            gyro_amp * math.sin(TWO_PI * 0.2 * t + gyro_phase),
            gyro_amp * math.cos(TWO_PI * 0.17 * t + gyro_phase),
            0.5 * gyro_amp * math.sin(TWO_PI * 0.11 * t),
        )
        rows.append([accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]])

    return _finish(
        rows,
        rng,
        accel_sigma=rng.uniform(0.04, 0.10),
        gyro_sigma=rng.uniform(0.006, 0.015),
        accel_limit=ADL_ACCEL_LIMIT_MS2,
    )


def synthesize_walking(n: int, dt: float, rng: random.Random) -> List[Row]:
    """Steady walking: 1-3 m/s^2 vertical oscillation and mild wrist rotation."""
    up = _tilted_up(rng, 3.0, 12.0)
    forward = _horizontal_dir(up)
    lateral = _unit(_cross(up, forward), fallback=(0.0, 1.0, 0.0))

    stride_hz = rng.uniform(1.5, 2.2)
    vertical_amp = rng.uniform(1.0, 3.0)
    lateral_amp = rng.uniform(0.3, 0.9)
    forward_amp = rng.uniform(0.2, 0.6)
    p1, p2, p3 = (rng.uniform(0.0, TWO_PI) for _ in range(3))
    roll_amp = rng.uniform(0.4, 1.2)
    pitch_amp = rng.uniform(0.3, 0.9)
    yaw_amp = rng.uniform(0.05, 0.20)

    rows: List[Row] = []
    for i in range(n):
        t = i * dt
        vertical = vertical_amp * math.sin(TWO_PI * stride_hz * t + p1)
        lateral_acc = lateral_amp * math.sin(math.pi * stride_hz * t + p2)
        forward_acc = forward_amp * math.sin(TWO_PI * stride_hz * t + p3)
        accel = _add(
            _scale(up, GRAVITY_MS2 + vertical),
            _add(_scale(lateral, lateral_acc), _scale(forward, forward_acc)),
        )
        gyro = _add(
            _scale(lateral, roll_amp * math.sin(TWO_PI * stride_hz * t + p1)),
            _add(
                _scale(forward, pitch_amp * math.sin(TWO_PI * stride_hz * t + p3)),
                _scale(up, yaw_amp * math.sin(math.pi * stride_hz * t + p2)),
            ),
        )
        rows.append([accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]])

    return _finish(
        rows,
        rng,
        accel_sigma=rng.uniform(0.10, 0.20),
        gyro_sigma=rng.uniform(0.02, 0.05),
        accel_limit=ADL_ACCEL_LIMIT_MS2,
    )


def synthesize_sit_stand(n: int, dt: float, rng: random.Random) -> List[Row]:
    """Slow standing <-> seated tilt with a small forward acceleration bump."""
    duration = max((n - 1) * dt, dt)
    up_standing = _tilted_up(rng, 2.0, 10.0)
    up_seated = _tilted_up(rng, 28.0, 48.0)

    start = rng.uniform(0.15, 0.35) * duration
    move_dur = min(rng.uniform(0.55, 1.10), max(0.30, 0.85 * duration - start))
    if move_dur <= 0.0:
        move_dur = max(0.30, 0.40 * duration)
    forward = _unit(
        (
            up_seated[0] - up_standing[0],
            up_seated[1] - up_standing[1],
            0.0,
        ),
        fallback=_horizontal_dir(up_standing),
    )

    ups: List[Vec3] = []
    progress: List[float] = []
    for i in range(n):
        t = i * dt
        s = _smoothstep((t - start) / move_dur)
        ups.append(_slerp(up_standing, up_seated, s))
        progress.append(s)
    rates = _gyro_from_orientations(ups, dt)

    rows: List[Row] = []
    for i in range(n):
        p = progress[i]
        bump = math.sin(math.pi * p) if 0.0 < p < 1.0 else 0.0
        accel = _add(
            _scale(ups[i], GRAVITY_MS2),
            _scale(forward, 0.55 * bump),
        )
        rate = rates[i]
        # Mild wrist rotation on top of the trunk tilt.
        wobble = 0.03 * math.sin(TWO_PI * 0.7 * i * dt)
        rows.append(
            [
                accel[0],
                accel[1],
                accel[2],
                rate[0] + wobble,
                rate[1] + wobble,
                rate[2],
            ]
        )

    return _finish(
        rows,
        rng,
        accel_sigma=rng.uniform(0.06, 0.12),
        gyro_sigma=rng.uniform(0.01, 0.03),
        accel_limit=ADL_ACCEL_LIMIT_MS2,
    )


def synthesize_hand_movement(n: int, dt: float, rng: random.Random) -> List[Row]:
    """Brisk hand/wrist movement: larger gyro bursts, moderate linear accel."""
    up = _tilted_up(rng, 2.0, 12.0)
    amps = (
        rng.uniform(1.5, 4.0),
        rng.uniform(1.5, 4.0),
        rng.uniform(0.3, 1.5),
    )
    freqs = (rng.uniform(1.2, 2.8), rng.uniform(1.2, 2.8), rng.uniform(1.5, 3.0))
    phases = tuple(rng.uniform(0.0, TWO_PI) for _ in range(3))
    gyro_amps = (
        rng.uniform(1.0, 3.5),
        rng.uniform(1.0, 3.5),
        rng.uniform(0.9, 3.0),
    )
    gyro_freqs = (
        rng.uniform(1.0, 2.6),
        rng.uniform(1.0, 2.6),
        rng.uniform(1.2, 2.8),
    )
    gyro_phases = tuple(rng.uniform(0.0, TWO_PI) for _ in range(3))
    burst_freq = rng.uniform(0.6, 1.0)
    burst_phase = rng.uniform(0.0, TWO_PI)

    rows: List[Row] = []
    for i in range(n):
        t = i * dt
        envelope = 0.35 + 0.65 * max(
            0.0, math.sin(TWO_PI * burst_freq * t + burst_phase)
        )
        accel = _add(
            _scale(up, GRAVITY_MS2),
            (
                amps[0] * envelope * math.sin(TWO_PI * freqs[0] * t + phases[0]),
                amps[1] * envelope * math.sin(TWO_PI * freqs[1] * t + phases[1]),
                amps[2] * envelope * math.sin(TWO_PI * freqs[2] * t + phases[2]),
            ),
        )
        gyro = (
            gyro_amps[0] * envelope * math.sin(TWO_PI * gyro_freqs[0] * t + gyro_phases[0]),
            gyro_amps[1] * envelope * math.sin(TWO_PI * gyro_freqs[1] * t + gyro_phases[1]),
            gyro_amps[2] * envelope * math.sin(TWO_PI * gyro_freqs[2] * t + gyro_phases[2]),
        )
        rows.append([accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]])

    return _finish(
        rows,
        rng,
        accel_sigma=rng.uniform(0.10, 0.22),
        gyro_sigma=rng.uniform(0.02, 0.06),
        accel_limit=ADL_ACCEL_LIMIT_MS2,
    )


# ---------------------------------------------------------------------------
# Fall synthesis
# ---------------------------------------------------------------------------
def synthesize_fall(n: int, dt: float, rng: random.Random) -> List[Row]:
    """Synthesize one fall: baseline, free fall, impact, bounce, low motion.

    Timeline fractions are relative to the window length, so the default 2 s
    window contains roughly 0.25-0.40 s of free fall starting 0.24-0.40 s in,
    followed by impact, a short rebound, and a quiet post-impact tail.
    """
    duration = max((n - 1) * dt, dt)

    # Free fall starts after the pre-impact baseline and lasts 0.12-0.20 of the
    # window (0.24-0.40 s at 2 s), then impact and a long low-motion tail.
    i_free = max(1, int(round(rng.uniform(0.12, 0.20) * duration / dt)))
    free_samples = max(1, int(round(rng.uniform(0.12, 0.20) * duration / dt)))
    i_impact = i_free + free_samples
    i_impact = min(i_impact, n - max(4, int(round(0.20 * n))))
    i_impact = max(i_impact, i_free + 1)

    # Orientation: mostly upright before the fall, lying at an arbitrary angle
    # afterwards. The rotation is spread over free fall and the first impact
    # samples so the gyro shows a plausible turn.
    up_before = _tilted_up(rng, 0.0, 18.0)
    up_after = _tilted_up(rng, 70.0, 105.0)
    i_rot_end = min(n - 1, i_impact + max(1, int(round(0.10 / dt))))
    ups: List[Vec3] = []
    for i in range(n):
        if i <= i_free:
            ups.append(up_before)
        elif i >= i_rot_end:
            ups.append(up_after)
        else:
            s = _smoothstep((i - i_free) / float(i_rot_end - i_free))
            ups.append(_slerp(up_before, up_after, s))
    orientation_rates = _gyro_from_orientations(ups, dt)

    freefall_scale = rng.uniform(0.03, 0.22)  # 0.3-2.2 m/s^2 of gravity left
    sway_amp = rng.uniform(0.03, 0.12)
    sway_phase = rng.uniform(0.0, TWO_PI)
    horizontal = _horizontal_dir(up_before)

    # Small tumbling-specific acceleration during free fall (keeps |a| < 5).
    tumble_amp = (rng.uniform(0.10, 0.30),) * 3
    tumble_freq = (rng.uniform(0.8, 2.0),) * 3
    tumble_phase = tuple(rng.uniform(0.0, TWO_PI) for _ in range(3))

    # Impact direction: one dominant axis (25-60 m/s^2 after gravity), with a
    # small lateral component, so different windows hit different axes.
    dominant = rng.randrange(3)
    peak = rng.uniform(27.0, 48.0)
    impact_dir = [rng.uniform(-0.22, 0.22) * peak for _ in range(3)]
    gravity_component = ups[i_impact][dominant] * GRAVITY_MS2
    sign = 1.0 if gravity_component >= 0.0 else -1.0
    if abs(gravity_component) < 0.5 and rng.random() < 0.5:
        sign = -1.0
    impact_dir[dominant] = sign * peak
    impact_tau = rng.uniform(0.050, 0.075)
    bounce_delay = rng.uniform(0.10, 0.16)
    bounce_amp = rng.uniform(0.15, 0.30)
    bounce_tau = rng.uniform(0.030, 0.050)

    # Rotation pulse at impact plus a low-frequency settling oscillation.
    rot_axis = _unit(
        (
            rng.uniform(-1.0, 1.0),
            rng.uniform(-1.0, 1.0),
            rng.uniform(-1.0, 1.0),
        ),
        fallback=(0.0, 1.0, 0.0),
    )
    rot_amp = rng.uniform(5.0, 11.0)
    rot_tau = rng.uniform(0.06, 0.10)
    settle_amp = rng.uniform(0.5, 1.2)
    settle_hz = rng.uniform(1.8, 3.0)
    settle_dir = _horizontal_dir(ups[-1])

    rows: List[Row] = []
    for i in range(n):
        t = i * dt
        up = ups[i]
        in_freefall = i_free <= i < i_impact
        gravity_scale = freefall_scale if in_freefall else 1.0
        accel = _scale(up, GRAVITY_MS2 * gravity_scale)

        if i < i_free:
            # Pre-impact baseline: quiet standing/walking, no fall signature.
            sway = sway_amp * math.sin(TWO_PI * 0.45 * t + sway_phase)
            accel = _add(accel, _scale(horizontal, sway))
        elif in_freefall:
            accel = _add(
                accel,
                (
                    tumble_amp[0] * math.sin(TWO_PI * tumble_freq[0] * t + tumble_phase[0]),
                    tumble_amp[1] * math.sin(TWO_PI * tumble_freq[1] * t + tumble_phase[1]),
                    tumble_amp[2] * math.sin(TWO_PI * tumble_freq[2] * t + tumble_phase[2]),
                ),
            )

        impact_gyro = (0.0, 0.0, 0.0)
        if i >= i_impact:
            tau = (i - i_impact) * dt
            envelope = math.exp(-tau / impact_tau)
            impact = _scale(tuple(impact_dir), envelope)
            rebound_t = tau - bounce_delay
            if rebound_t >= 0.0:
                impact = _add(
                    impact,
                    _scale(
                        tuple(impact_dir),
                        -bounce_amp * math.exp(-rebound_t / bounce_tau),
                    ),
                )
            accel = _add(accel, impact)

            # Small settling sway once the initial impact has decayed.
            if tau >= 0.20:
                settle = (
                    settle_amp
                    * math.exp(-(tau - 0.20) / 0.30)
                    * math.sin(TWO_PI * settle_hz * (tau - 0.20))
                )
                accel = _add(accel, _scale(settle_dir, settle))

            impact_gyro = _scale(rot_axis, rot_amp * math.exp(-tau / rot_tau))

        rate = orientation_rates[i]
        gyro = (
            rate[0] + impact_gyro[0],
            rate[1] + impact_gyro[1],
            rate[2] + impact_gyro[2],
        )
        rows.append([accel[0], accel[1], accel[2], gyro[0], gyro[1], gyro[2]])

    return _finish(
        rows,
        rng,
        accel_sigma=rng.uniform(0.06, 0.12),
        gyro_sigma=rng.uniform(0.01, 0.04),
        accel_limit=ACCEL_CLAMP_MS2,
    )


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------
def _adl_schedule(count: int, rng: random.Random) -> List[str]:
    """Return a balanced, shuffled sequence of ADL activity types."""
    kinds = ["idle", "walking", "sit_stand", "hand"]
    schedule = [kinds[i % len(kinds)] for i in range(count)]
    rng.shuffle(schedule)
    return schedule


def _synthesize_adl(kind: str, n: int, dt: float, rng: random.Random) -> List[Row]:
    if kind == "idle":
        return synthesize_idle(n, dt, rng, sitting=rng.random() < 0.5)
    if kind == "walking":
        return synthesize_walking(n, dt, rng)
    if kind == "sit_stand":
        return synthesize_sit_stand(n, dt, rng)
    if kind == "hand":
        return synthesize_hand_movement(n, dt, rng)
    raise ValueError(f"unknown ADL kind: {kind}")


def _write_window(path: Path, rows: Sequence[Row], hz: float) -> None:
    """Write one window as CSV with the required header and timestamp grid."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp", "ax", "ay", "az", "gx", "gy", "gz"])
        for i, row in enumerate(rows):
            timestamp_ms = int(round(i * 1000.0 / hz))
            values = []
            for value in row:
                rounded = round(value, 4)
                if rounded == 0.0:
                    rounded = 0.0  # avoid "-0.0000" in the CSV
                values.append(f"{rounded:.4f}")
            writer.writerow([timestamp_ms] + values)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate synthetic 6-axis IMU windows for an ESP32-S3 wristband "
            "fall-detection pipeline (MPU6050, 50 Hz, 2 s windows)."
        ),
        epilog=(
            "Synthetic data is for pipeline/demo testing only. It will not "
            "generalize to real people; collect real wristband data before "
            "reporting fall-detection accuracy."
        ),
    )
    parser.add_argument(
        "--out",
        default="dataset",
        help="output root directory (default: dataset)",
    )
    parser.add_argument(
        "--samples-per-class",
        type=int,
        default=60,
        help="training windows per class (default: 60)",
    )
    parser.add_argument(
        "--test-samples-per-class",
        type=int,
        default=20,
        help="testing windows per class (default: 20)",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=50.0,
        help="sampling rate in Hz (default: 50)",
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=2.0,
        help="window length in seconds (default: 2)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="random seed for reproducibility (default: 42)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the dataset, and print a summary."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.hz <= 0.0:
        parser.error("--hz must be greater than 0")
    if args.window_sec <= 0.0:
        parser.error("--window-sec must be greater than 0")
    if args.samples_per_class < 0:
        parser.error("--samples-per-class must be non-negative")
    if args.test_samples_per_class < 0:
        parser.error("--test-samples-per-class must be non-negative")
    if args.hz * args.window_sec < 10.0:
        parser.error("--hz * --window-sec must be at least 10 samples")

    n_samples = max(1, int(round(args.hz * args.window_sec)))
    dt = 1.0 / args.hz
    out_root = Path(args.out)
    rng = random.Random(args.seed)

    splits = (
        ("training", args.samples_per_class),
        ("testing", args.test_samples_per_class),
    )
    counts: List[Tuple[str, str, int]] = []

    for split_name, count in splits:
        for label in ("fall", "adl"):
            folder = out_root / split_name / label
            folder.mkdir(parents=True, exist_ok=True)
            schedule = _adl_schedule(count, rng) if label == "adl" else []

            for index in range(count):
                if label == "fall":
                    rows = synthesize_fall(n_samples, dt, rng)
                else:
                    rows = _synthesize_adl(schedule[index], n_samples, dt, rng)
                _write_window(folder / f"{label}_{index:04d}.csv", rows, args.hz)

            counts.append((split_name, label, count))

    total_windows = sum(count for _, _, count in counts)
    total_samples = total_windows * n_samples
    print("Synthetic IMU dataset written to: " + str(out_root.resolve()))
    print(
        f"  sampling: {args.hz:g} Hz, {args.window_sec:g} s windows "
        f"({n_samples} samples per window)"
    )
    print(f"  seed: {args.seed}  |  fall threshold reference: {FALL_THRESHOLD_MS2:g} m/s^2")
    for split_name, label, count in counts:
        print(
            f"  {split_name + '/' + label:<18} {count:4d} windows "
            f"({count * n_samples:6d} rows)"
        )
    print(f"  total: {total_windows} windows, {total_samples} rows")
    print()
    print("WARNING: SYNTHETIC DATA ONLY.")
    print("WARNING: These hand-crafted signals will NOT generalize to real people,")
    print("         wrist orientations, or sensor mounting. A model trained on them")
    print("         is useful only for pipeline/demo testing.")
    print("         Collect and label real wristband recordings before claiming")
    print("         fall-detection accuracy or deploying the detector.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
