"""End-to-end replay test: play real HIFD recordings into the firmware as if they came from the MPU6050.

The host sends raw samples (accelerometer WITH gravity rebuilt from the HIFD quaternion, band-limited by the
21 Hz DLPF; gyro in rad/s) at 50 Hz over USB. The board runs its normal pipeline (gravity removal, MLP + CNN,
FSM) with the buzzer muted, and reports FSM transitions on the serial log. This tests the complete chain on
the chip, including timing, not only the models.

Usage: replay_eval.py [--port COM13] [--ai on|off] [--falls 6] [--adl clap:2,bed:1,chair:1,walk:1,stair:1]
"""
import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import serial
from scipy.signal import sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings, FS
from ai_lab.preproc import raw_acc, _SOS, ACC_CLIP, GYRO_CLIP

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "dataset" / "ai_results"
PAD_S = 8.0       # static lead-in so the gravity filter and the AI window settle
TAIL_S = 2.0


class Reader(threading.Thread):
    def __init__(self, ser):
        super().__init__(daemon=True)
        self.ser, self.lines, self.stop_flag = ser, [], False

    def run(self):
        while not self.stop_flag:
            try:
                ln = self.ser.readline()
            except serial.SerialException:
                return
            if ln:
                self.lines.append((time.perf_counter(), ln.decode("utf-8", "replace").strip()))


def make_stream(rec):
    raw = raw_acc(rec)
    gyro = rec.gyro
    raw = np.clip(sosfilt(_SOS, raw, axis=0), -ACC_CLIP, ACC_CLIP)
    gyro = np.clip(sosfilt(_SOS, gyro, axis=0), -GYRO_CLIP, GYRO_CLIP)
    s = np.hstack([raw, gyro])
    pad = np.repeat(s[:1], int(PAD_S * FS), axis=0)
    tail = np.repeat(s[-1:], int(TAIL_S * FS), axis=0)
    return np.vstack([pad, s, tail])


def play(ser, reader, rec, ai_on):
    ser.write(b"#REPLAY\n")
    time.sleep(0.3)
    ser.write(f"#AIMODE,{1 if ai_on else 0}\n".encode())
    time.sleep(0.2)
    start_idx = len(reader.lines)
    stream = make_stream(rec)
    t0 = time.perf_counter() + 0.2
    impact_idx = int(PAD_S * FS) + (rec.center or 0)
    t_impact = None
    for i, row in enumerate(stream):
        target = t0 + i / FS
        while True:
            dt = target - time.perf_counter()
            if dt <= 0:
                break
            time.sleep(min(dt, 0.004))
        ser.write(("S," + ",".join(f"{v:.5f}" for v in row) + "\n").encode())
        if i == impact_idx:
            t_impact = time.perf_counter()
    time.sleep(1.0)
    ser.write(b"#REPLAYEND\n")
    time.sleep(0.4)
    new = reader.lines[start_idx:]
    res = {"name": rec.name, "ai": ai_on, "countdown_s": None, "reason": None, "peak_p": 0.0, "transitions": []}
    for t, ln in new:
        m = re.search(r"\[FSM\] (\w+) -> (\w+) \(([^)]*)\)", ln)
        if m:
            res["transitions"].append((round(t - t0, 2), m.group(1), m.group(2)))
            if m.group(2) == "COUNTDOWN" and res["countdown_s"] is None and t_impact is not None:
                res["countdown_s"] = round(t - t_impact, 2)
                res["reason"] = m.group(3)
        m = re.search(r"\[TINY-AI\] p=([0-9.]+)", ln)
        if m:
            res["peak_p"] = max(res["peak_p"], float(m.group(1)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM13")
    ap.add_argument("--ai", default="both", choices=["on", "off", "both"])
    ap.add_argument("--subjects", default="19,20,21")
    ap.add_argument("--falls", type=int, default=6)
    ap.add_argument("--adl", default="clap:2,bed:1,chair:1,walk:1,stair:1")
    ap.add_argument("--out", default=str(RES / "replay.json"))
    a = ap.parse_args()

    recs = load_recordings()
    subj = {int(s) for s in a.subjects.split(",")}
    falls = [r for r in recs if r.is_fall and r.subject in subj][::max(1, 15 // max(a.falls, 1))][:a.falls]
    adl = []
    for item in a.adl.split(","):
        sc, n = item.split(":")
        adl += [r for r in recs if (not r.is_fall) and r.scenario == sc and r.subject in subj][:int(n)]
    modes = [True, False] if a.ai == "both" else [a.ai == "on"]

    ser = serial.Serial(a.port, 115200, timeout=0.5)
    ser.dtr = False
    ser.rts = False
    time.sleep(0.3)
    reader = Reader(ser)
    reader.start()
    results = []
    for ai_on in modes:
        for rec in falls + adl:
            r = play(ser, reader, rec, ai_on)
            results.append(r)
            print(f"AI {'ON ' if ai_on else 'OFF'} {rec.name:22s} countdown after impact: "
                  f"{r['countdown_s'] if r['countdown_s'] is not None else '-':>5}  reason={r['reason']}  peak p={r['peak_p']:.2f}", flush=True)
    reader.stop_flag = True
    ser.close()
    Path(a.out).write_text(json.dumps(results, indent=1))
    for ai_on in modes:
        sel = [r for r in results if r["ai"] == ai_on]
        f = [r for r in sel if "/fall/" in r["name"]]
        n = [r for r in sel if "/non-fall/" in r["name"]]
        print(f"AI {'ON ' if ai_on else 'OFF'}: falls alarmed {sum(r['countdown_s'] is not None for r in f)}/{len(f)}, "
              f"ADL alarmed {sum(r['countdown_s'] is not None for r in n)}/{len(n)}, "
              f"median latency {np.median([r['countdown_s'] for r in f if r['countdown_s'] is not None] or [np.nan]):.2f} s")


if __name__ == "__main__":
    main()
