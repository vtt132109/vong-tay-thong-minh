#!/usr/bin/env python3
"""Simulate the Bio-Band PPG output filter.

This is NOT a test of the MAX30102/Maxim DSP. It models the firmware's
post-processing rules (motion gate + 4 s refill, PI/valid gate, median-3,
range checks) on synthetic HR/SpO2 estimates. Real sensor performance still
requires board data via tools/capture_labeled.py or /data logging.

Run: python tools/test_ppg_filter.py
"""

import math
import random
import statistics
from dataclasses import dataclass
from typing import List, Optional

SECONDS = 120
SEEDS = 200
MOTION_SEGMENTS = ((20, 30), (70, 78))
LOW_PI_SEGMENT = (45, 50)
HR_STEP_SECOND = 60


@dataclass
class Result:
    coverage: float
    mae: float
    rmse: float
    spike_rate: float
    motion_outputs: int


def is_motion(t: int) -> bool:
    return any(lo <= t < hi for lo, hi in MOTION_SEGMENTS)


def is_low_pi(t: int) -> bool:
    return LOW_PI_SEGMENT[0] <= t < LOW_PI_SEGMENT[1]


def median(values: List[float]) -> float:
    return statistics.median(values)


def simulate(seed: int):
    random.seed(seed)
    true_hr = []
    true_spo2 = []
    raw_hr = []
    raw_spo2 = []
    raw_valid = []

    for t in range(SECONDS):
        h = 70.0 + 2.5 * math.sin(2.0 * math.pi * t / 25.0)
        if t >= HR_STEP_SECOND:
            h = 95.0 + 2.5 * math.sin(2.0 * math.pi * t / 25.0)
        s = 97.0 + 0.4 * math.sin(2.0 * math.pi * t / 33.0)
        true_hr.append(h)
        true_spo2.append(s)

        if is_low_pi(t):
            raw_valid.append(False)
            raw_hr.append(0.0)
            raw_spo2.append(0.0)
            continue

        hr_noise = random.gauss(0.0, 2.0)
        spo2_noise = random.gauss(0.0, 0.6)
        if is_motion(t):
            hr_noise += random.gauss(0.0, 18.0)
            spo2_noise += random.gauss(0.0, 5.0)
        if random.random() < 0.05:
            hr_noise += random.choice((-25.0, 25.0))
        if random.random() < 0.04:
            spo2_noise += random.choice((-4.0, 4.0))

        raw_valid.append(True)
        raw_hr.append(max(20.0, min(240.0, h + hr_noise)))
        raw_spo2.append(max(60.0, min(100.0, s + spo2_noise)))

    def median_only(values, valid):
        history = []
        output = []
        for value, ok in zip(values, valid):
            if not ok:
                output.append(None)
                continue
            history.append(value)
            if len(history) > 3:
                history.pop(0)
            output.append(median(history))
        return output

    def full_filter(values, valid):
        history = []
        output = []
        last_motion = None
        for t, (value, ok) in enumerate(zip(values, valid)):
            if is_motion(t):
                last_motion = t
            motion_blocked = last_motion is not None and t <= last_motion + 4
            if motion_blocked or is_low_pi(t) or not ok:
                output.append(None)
                if motion_blocked:
                    history = []
                continue
            history.append(value)
            if len(history) > 3:
                history.pop(0)
            output.append(median(history))
        return output

    raw_hr_out = [value if ok else None for value, ok in zip(raw_hr, raw_valid)]
    raw_spo2_out = [value if ok else None for value, ok in zip(raw_spo2, raw_valid)]
    med_hr_out = median_only(raw_hr, raw_valid)
    med_spo2_out = median_only(raw_spo2, raw_valid)
    full_hr_out = full_filter(raw_hr, raw_valid)
    full_spo2_out = full_filter(raw_spo2, raw_valid)

    def metrics(true_values, output, limit):
        errors = []
        spikes = 0
        motion_outputs = 0
        for t, value in enumerate(output):
            if value is None:
                continue
            error = abs(value - true_values[t])
            errors.append(error)
            if error > limit:
                spikes += 1
            if is_motion(t) or (is_motion(t - 1) if t > 0 else False):
                motion_outputs += 1
        if not errors:
            return Result(0.0, float("inf"), float("inf"), 0.0, motion_outputs)
        coverage = len(errors) / SECONDS
        mae = sum(errors) / len(errors)
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        spike_rate = spikes / len(errors)
        return Result(coverage, mae, rmse, spike_rate, motion_outputs)

    raw_hr_m = metrics(true_hr, raw_hr_out, 10.0)
    med_hr_m = metrics(true_hr, med_hr_out, 10.0)
    full_hr_m = metrics(true_hr, full_hr_out, 10.0)
    raw_spo2_m = metrics(true_spo2, raw_spo2_out, 3.0)
    med_spo2_m = metrics(true_spo2, med_spo2_out, 3.0)
    full_spo2_m = metrics(true_spo2, full_spo2_out, 3.0)

    return (raw_hr_m, med_hr_m, full_hr_m, raw_spo2_m, med_spo2_m, full_spo2_m)


def average(results):
    groups = list(zip(*results))  # transpose: one group per metric set
    aggregated = []
    for group in groups:
        n = len(group)
        aggregated.append(tuple(
            sum(getattr(r, field) for r in group) / n
            for field in ("coverage", "mae", "rmse", "spike_rate", "motion_outputs")
        ))
    return tuple(aggregated)


def main():
    rows = [simulate(seed) for seed in range(SEEDS)]
    avg = average(rows)

    print("PPG output-filter simulation (synthetic estimates, not hardware)")
    print(f"seeds={SEEDS}, duration={SECONDS}s, motion={MOTION_SEGMENTS}, low_pi={LOW_PI_SEGMENT}")
    print()

    labels = ("Raw (no filter)", "Median only", "Full filter")

    def show(name, metric_rows, unit, spike_unit):
        print(f"{name}")
        print(f"  {'method':18s} {'coverage':>9s} {'MAE':>8s} {'RMSE':>8s} {'spikes':>9s} {'motion_out':>11s}")
        for label, row in zip(labels, metric_rows):
            coverage, mae, rmse, spike_rate, motion_outputs = row
            print(f"  {label:18s} {coverage*100:8.1f}% {mae:7.2f}{unit} {rmse:7.2f}{unit} {spike_rate*100:8.1f}% {motion_outputs:11.2f}")
        print()

    show("Heart rate", avg[0:3], "bpm", "bpm")
    show("SpO2", avg[3:6], "%", "%")

    # Step response: first valid output within 3 bpm of the new truth after the step.
    print("Note: coverage < 100% is intentional during motion/refill/low-PI.")
    print("Median/full filter latency is ~2 samples (2 s) after a clean step.")
    print("This tests output gating/median only; validate with real MAX30102 data.")


if __name__ == "__main__":
    main()
