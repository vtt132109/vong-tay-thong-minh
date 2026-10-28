#!/usr/bin/env python3
"""Doc Serial USB CDC cua board va in ra terminal.

Dung: python tools/monitor_serial.py [COM13] [--no-reset]
Nhan Ctrl+C de thoat.
"""
import sys
import time

import serial


def main() -> int:
    port = "COM13"
    reset = True
    for arg in sys.argv[1:]:
        if arg == "--no-reset":
            reset = False
        else:
            port = arg

    with serial.Serial(port, 115200, timeout=0.5) as ser:
        if reset:
            ser.setDTR(False)
            ser.setRTS(True)
            time.sleep(0.15)
            ser.setRTS(False)
            time.sleep(0.15)
            print(f"[monitor] reset {port}, dang doc... (Ctrl+C de thoat)")
        else:
            print(f"[monitor] doc {port}... (Ctrl+C de thoat)")

        try:
            while True:
                line = ser.readline()
                if line:
                    print(line.decode("utf-8", "replace").rstrip(), flush=True)
        except KeyboardInterrupt:
            print("\n[monitor] thoat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
