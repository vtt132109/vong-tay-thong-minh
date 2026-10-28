#!/usr/bin/env python3
"""Log Bio-Band /data telemetry to CSV and summarize raw vs filtered PPG.

The ESP32 must be reachable (AP 192.168.4.1 or STA IP), and the dashboard/API
must be running. Raw values are the Maxim algorithm outputs before the firmware
motion/PI/median filter; filtered values are what the UI shows. This tool does
not provide a ground-truth reference; compare with a pulse oximeter manually.

Usage:
  python tools/log_telemetry.py --host 192.168.4.1 --duration 120 --out ppg_log.csv
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

FIELDS = [
    "pc_time", "state", "bpm", "spo2", "raw_bpm", "raw_spo2",
    "ppg_motion", "lead_off", "acc", "battery_v", "battery_pct",
]


def get_data(base):
    with urllib.request.urlopen(base + "/data", timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def jitter(values):
    diffs = [abs(b - a) for a, b in zip(values, values[1:])]
    return sum(diffs) / len(diffs) if diffs else 0.0


def spikes(values, threshold):
    return sum(1 for a, b in zip(values, values[1:]) if abs(b - a) > threshold)


def summarize(rows):
    raw_hr = [float(r["raw_bpm"]) for r in rows if float(r["raw_bpm"]) > 0]
    flt_hr = [float(r["bpm"]) for r in rows if float(r["bpm"]) > 0]
    raw_spo2 = [float(r["raw_spo2"]) for r in rows if float(r["raw_spo2"]) > 0]
    flt_spo2 = [float(r["spo2"]) for r in rows if float(r["spo2"]) > 0]
    motion = sum(1 for r in rows if str(r["ppg_motion"]).lower() == "true")

    print()
    print("Summary")
    print(f"  samples: {len(rows)}  motion samples: {motion}")
    print(f"  raw HR valid: {len(raw_hr)}  filtered HR valid: {len(flt_hr)}")
    print(f"  raw SpO2 valid: {len(raw_spo2)}  filtered SpO2 valid: {len(flt_spo2)}")
    if raw_hr and flt_hr:
        print(f"  HR jitter (mean |delta|): raw {jitter(raw_hr):.2f} bpm, filtered {jitter(flt_hr):.2f} bpm")
        print(f"  HR jumps >10 bpm: raw {spikes(raw_hr, 10)}, filtered {spikes(flt_hr, 10)}")
    if raw_spo2 and flt_spo2:
        print(f"  SpO2 jitter (mean |delta|): raw {jitter(raw_spo2):.2f}%, filtered {jitter(flt_spo2):.2f}%")
        print(f"  SpO2 jumps >3%: raw {spikes(raw_spo2, 3)}, filtered {spikes(flt_spo2, 3)}")
    print("  Note: no ground truth; use a reference oximeter for accuracy, not only jitter.")


def main():
    parser = argparse.ArgumentParser(description="Log Bio-Band /data and compare raw vs filtered PPG.")
    parser.add_argument("--host", required=True, help="ESP32 IP, e.g. 192.168.4.1")
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to log (default 60)")
    parser.add_argument("--interval", type=float, default=0.2, help="poll interval seconds (default 0.2)")
    parser.add_argument("--out", default="ppg_log.csv", help="CSV output path")
    args = parser.parse_args()

    if args.duration <= 0 or args.interval <= 0:
        parser.error("duration and interval must be positive")

    base = args.host.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base

    rows = []
    deadline = time.monotonic() + args.duration
    last_error = None
    try:
        with open(args.out, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
            writer.writeheader()
            while time.monotonic() < deadline:
                try:
                    data = get_data(base)
                    row = {
                        "pc_time": datetime.now().isoformat(timespec="milliseconds"),
                        "state": data.get("state", "?"),
                        "bpm": data.get("bpm", 0),
                        "spo2": data.get("spo2", 0),
                        "raw_bpm": data.get("raw_bpm", 0),
                        "raw_spo2": data.get("raw_spo2", 0),
                        "ppg_motion": data.get("ppg_motion", False),
                        "lead_off": data.get("lead_off", True),
                        "acc": data.get("acc", 0),
                        "battery_v": data.get("battery_v", 0),
                        "battery_pct": data.get("battery_pct", 0),
                    }
                    writer.writerow(row)
                    rows.append(row)
                    print(f"\r{len(rows):5d} samples  bpm={row['bpm']}  raw={row['raw_bpm']}  "
                          f"spo2={row['spo2']}  raw={row['raw_spo2']}  motion={row['ppg_motion']}",
                          end="", flush=True)
                    time.sleep(args.interval)
                except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                    if str(exc) != str(last_error):
                        print(f"\n[WARN] {exc}")
                        last_error = exc
                    time.sleep(min(1.0, args.interval))
    except KeyboardInterrupt:
        print("\n[INFO] interrupted")
    finally:
        print(f"\nSaved {len(rows)} samples to {args.out}")
        if rows:
            summarize(rows)
        else:
            print("No samples; check host/AP connection.")


if __name__ == "__main__":
    main()
