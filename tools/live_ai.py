#!/usr/bin/env python3
"""Live view of the on-chip AI from the USB serial log (no reset, nothing is sent to the board).

Prints one line per AI inference that is worth seeing (p > 0.2, or a heartbeat every 5 s) and every FSM
transition, with a text bar. Also keeps the peak probability of the session.

Usage: python tools/live_ai.py [PORT] [--seconds 180]
"""
import re
import sys
import time

import serial
from serial.tools import list_ports


def find_port():
    for p in list_ports.comports():
        if p.vid == 0x303A:
            return p.device
    return None


def main():
    args = sys.argv[1:]
    seconds = float(args[args.index("--seconds") + 1]) if "--seconds" in args else 180.0
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--seconds")]
    port = pos[0] if pos else find_port()
    if port is None:
        sys.exit("no Espressif serial port found")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ser = serial.Serial(port, 115200, timeout=0.5)
    ser.dtr = False
    ser.rts = False
    print(f"[live] {port}: theo doi AI {seconds:.0f} s (khong reset board). Ctrl+C de dung.", flush=True)
    end = time.time() + seconds
    peak = 0.0
    t0 = time.time()
    try:
        while time.time() < end:
            ln = ser.readline().decode("utf-8", "replace").strip()
            if not ln:
                continue
            m = re.search(r"\[TINY-AI\] p=([0-9.]+) \(mlp ([0-9.]+) cnn ([0-9.]+)\) thr=([0-9.]+) label=(\w+)", ln)
            if m:
                p, pm, pc, thr, label = float(m[1]), float(m[2]), float(m[3]), float(m[4]), m[5]
                peak = max(peak, p)
                bar = "#" * int(round(p * 30))
                flag = "  <== NGA" if label == "fall" else ""
                print(f"{time.time()-t0:6.1f}s p={p:.3f} [{bar:<30}] mlp {pm:.2f} cnn {pc:.2f} thr {thr:.2f} {label}{flag}", flush=True)
            elif "[FSM]" in ln or "[ALERT]" in ln or "[BTN]" in ln:
                print(f"{time.time()-t0:6.1f}s {ln}", flush=True)
    except KeyboardInterrupt:
        pass
    print(f"[live] xong. Dinh p cao nhat: {peak:.3f}", flush=True)


if __name__ == "__main__":
    main()
