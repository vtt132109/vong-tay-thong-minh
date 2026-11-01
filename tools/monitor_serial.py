#!/usr/bin/env python3
"""Read the board's USB CDC serial output and print it.

Usage: python tools/monitor_serial.py [PORT] [--no-reset] [--seconds N]
  PORT        e.g. COM13 or /dev/ttyACM0; auto-detected (Espressif USB, VID 0x303A) when omitted
  --no-reset  do not toggle DTR/RTS (attach without rebooting the board)
  --seconds N stop after N seconds (default: until Ctrl+C)
"""
import sys
import time

import serial
from serial.tools import list_ports


def find_port() -> str | None:
    for p in list_ports.comports():
        if p.vid == 0x303A:  # Espressif
            return p.device
    ports = list(list_ports.comports())
    return ports[0].device if len(ports) == 1 else None


def main() -> int:
    args = sys.argv[1:]
    reset = "--no-reset" not in args
    seconds = None
    if "--seconds" in args:
        seconds = float(args[args.index("--seconds") + 1])
    positional = [a for i, a in enumerate(args)
                  if not a.startswith("--") and (i == 0 or args[i - 1] != "--seconds")]
    port = positional[0] if positional else find_port()
    if port is None:
        print("No Espressif serial port found. Pass the port explicitly (python tools/monitor_serial.py COM13).",
              file=sys.stderr)
        return 2

    # Wi-Fi names and Vietnamese text in the log are UTF-8; do not crash on a cp1252 console/pipe.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
    except serial.SerialException as exc:
        print(f"Cannot open {port}: {exc}", file=sys.stderr)
        return 2
    with ser:
        if reset:
            ser.setDTR(False)
            ser.setRTS(True)
            time.sleep(0.1)
            ser.setRTS(False)
            print(f"[monitor] reset {port}, reading... (Ctrl+C to quit)", flush=True)
        else:
            print(f"[monitor] {port}, reading... (Ctrl+C to quit)", flush=True)
        end = time.time() + seconds if seconds else None
        try:
            while end is None or time.time() < end:
                line = ser.readline()
                if line:
                    print(line.decode("utf-8", "replace").rstrip(), flush=True)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
