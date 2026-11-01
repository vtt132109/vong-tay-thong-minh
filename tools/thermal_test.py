#!/usr/bin/env python3
"""Compare chip temperature / loop jitter / AI latency at several CPU clocks (build-time -DBIO_CPU_MHZ).

For each clock: build + flash, let the band run normally (WiFi, MQTT, AI, OLED) for --minutes while the
telemetry (retained MQTT topic) is sampled every 20 s. The internal temperature sensor is crude
(~1 degC steps, +-several degC absolute) so only differences between runs are meaningful. Leave the
board in the same place, same power source, same ambient for the whole test.

Usage: python tools/thermal_test.py [--clocks 160,80,240] [--minutes 6] [--port COM13]
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mqtt_peek import peek

ROOT = Path(__file__).resolve().parents[1]


def run(clock: int, port: str, minutes: float) -> dict:
    env = dict(os.environ, PLATFORMIO_BUILD_FLAGS=f"-DBIO_CPU_MHZ={clock}")
    print(f"[{clock} MHz] build + flash", flush=True)
    r = subprocess.run(["pio", "run", "-e", "esp32-s3-super-mini", "-t", "upload", "--upload-port", port],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stdout[-2000:] + r.stderr[-2000:])
    samples = []
    t_end = time.time() + minutes * 60
    time.sleep(25)  # boot + WiFi + MQTT
    while time.time() < t_end:
        try:
            tel = peek(seconds=4)["telemetry"] or {}
        except OSError:
            tel = {}
        if tel.get("cpu_mhz") == clock:
            samples.append({"t": time.time(), "chip_c": tel.get("chip_c"), "jit": tel.get("jit"),
                            "ai_us": tel.get("ai_us"), "ai_cnn_us": tel.get("ai_cnn_us"), "fps": tel.get("fps")})
            print(f"  {len(samples):2d}: {tel.get('chip_c'):.1f} C  jit {tel.get('jit')} ms  mlp {tel.get('ai_us')} us  cnn {tel.get('ai_cnn_us')} us", flush=True)
        time.sleep(16)
    tail = [s for s in samples if s["t"] > t_end - 120]
    return {"clock": clock, "samples": len(samples),
            "chip_c_last2min": statistics.mean(s["chip_c"] for s in tail) if tail else None,
            "chip_c_first": samples[0]["chip_c"] if samples else None,
            "ai_us": statistics.median(s["ai_us"] for s in samples) if samples else None,
            "ai_cnn_us": statistics.median(s["ai_cnn_us"] for s in samples) if samples else None,
            "jit_max_ms": max(s["jit"] for s in samples) if samples else None,
            "fps_min": min(s["fps"] for s in samples) if samples else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clocks", default="160,80,240")
    ap.add_argument("--minutes", type=float, default=6)
    ap.add_argument("--port", default="COM13")
    ap.add_argument("--out", default=str(ROOT / "dataset" / "ai_results" / "thermal.json"))
    a = ap.parse_args()
    res = [run(int(c), a.port, a.minutes) for c in a.clocks.split(",")]
    # restore the default build
    subprocess.run(["pio", "run", "-e", "esp32-s3-super-mini", "-t", "upload", "--upload-port", a.port],
                   cwd=ROOT, capture_output=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
