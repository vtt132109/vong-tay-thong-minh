#!/usr/bin/env python3
"""Stdlib-only mock of the Bio-Band HTTP API for realtime.html.

Usage:
    python tools/mock_server.py [--host 127.0.0.1] [--port 8000] [--quiet]
"""
import argparse
import json
import math
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "realtime.html"
PHASES = (("IDLE", 12.0), ("COUNTDOWN", 10.0), ("ALARM", 10.0), ("SNOOZE", 10.0))
DURATION = dict(PHASES)
OK, TEXT = "OK", "text/plain; charset=utf-8"


class Sim:
    """Tiny FSM + telemetry generator, updated on a 5 Hz timer thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.t0 = time.monotonic()
        self.phase = "IDLE"
        self.phase_end = self.t0 + DURATION["IDLE"]
        self.test_until = 0.0
        self.falls, self.steps, self.thresh = 3, 1420, 25.0
        self.data = self._build(self.t0)
        self.thread = threading.Thread(target=self._run, name="sim", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)

    def _advance(self, now):
        names = [name for name, _ in PHASES]
        self.phase = names[(names.index(self.phase) + 1) % len(names)]
        self.phase_end = now + DURATION[self.phase]

    def _run(self):
        while not self.stop.wait(0.2):
            with self.lock:
                now = time.monotonic()
                while now >= self.phase_end:
                    self._advance(now)
                self.data = self._build(now)

    def _build(self, now):
        t, left = now - self.t0, max(0.0, self.phase_end - now)
        bpm = int(min(78, max(72, round(75 + 1.6 * math.sin(t / 2.3) + random.uniform(-0.7, 0.7)))))
        spo2 = int(min(98, max(96, round(97 + 0.7 * math.sin(t / 3.7) + random.uniform(-0.4, 0.4)))))
        acc = round(10.05 + 0.20 * math.sin(t * 3.1) + 0.07 * math.sin(t * 11.3)
                    + random.uniform(-0.04, 0.04), 2)
        fps = round(49.0 + 0.4 * math.sin(t / 1.7) + random.uniform(-0.15, 0.15), 1)
        cd = max(1, int(math.ceil(left))) if self.phase == "COUNTDOWN" else 0
        snooze = 0
        if self.phase == "SNOOZE":
            snooze = max(1, min(20, int(math.ceil(left / DURATION["SNOOZE"] * 20))))
        return {
            "state": self.phase, "bpm": bpm, "spo2": spo2,
            "raw_bpm": round(bpm + random.uniform(-1.5, 1.5), 1),
            "raw_spo2": int(min(99, max(95, round(spo2 + random.uniform(-1, 1))))),
            "acc": acc, "thresh": self.thresh, "max30102": True, "lead_off": False,
            "falls": self.falls, "fps": fps, "steps": self.steps,
            "distance_km": round(self.steps * 0.0007, 3),
            "calories": round(self.steps * 0.03, 1),
            "battery_v": 3.94, "battery_pct": 88,
            "ram_pct": int(min(43, max(41, round(42 + 0.5 * math.sin(t / 5))))),
            "buzzer": self.phase == "ALARM" or now < self.test_until,
            "motor": False, "snooze_sec": snooze, "cd_sec": cd,
            "mpu": True, "finger": True, "ppg_motion": False,
            "ai_label": "n/a", "ai_conf": 0.0, "ai_fall": False,
        }

    def snapshot(self):
        with self.lock:
            return dict(self.data)

    def command(self, name, value=None):
        with self.lock:
            now = time.monotonic()
            if name == "cancel":
                self.phase, self.phase_end = "SNOOZE", now + DURATION["SNOOZE"]
            elif name == "test_hw":
                self.test_until = now + 2.0
            elif name == "clear_nvs":
                self.falls = self.steps = 0
            elif name == "thresh":
                self.thresh = value
            self.data = self._build(now)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_request(self, code="-", size="-"):
        if self.server.quiet and self.path.startswith("/data"):
            if self.server.poll_logged:
                return
            self.server.poll_logged = True
        super().log_request(code, size)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, body, ctype):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def _page(self):
        try:
            body = PAGE.read_bytes()
        except OSError:
            return self._send(404, "realtime.html not found. Create %s to use the dashboard.\n"
                              % PAGE, TEXT)
        self._send(200, body, "text/html; charset=utf-8")

    def _set_thresh(self, query):
        vals = parse_qs(query).get("val")
        if not vals:
            return self._send(400, "missing val", TEXT)
        try:
            val = float(vals[0])
        except ValueError:
            val = float("nan")
        if not math.isfinite(val) or not 10.0 <= val <= 60.0:
            return self._send(400, "val must be 10..60", TEXT)
        self.server.sim.command("thresh", val)
        self._send(200, OK, TEXT)

    def _capture(self, query):
        self._send(200, OK, TEXT)  # capture is a no-op in the mock

    def _route(self, post):
        url = urlsplit(self.path)
        if not post and url.path == "/":
            return self._page()
        if not post and url.path == "/data":
            body = json.dumps(self.server.sim.snapshot(), separators=(",", ":"))
            return self._send(200, body, "application/json")
        if url.path == "/set_time":
            return self._send(200, OK, TEXT)
        if url.path == "/set_thresh":
            return self._set_thresh(url.query)
        if url.path == "/capture":
            return self._capture(url.query)
        if post and url.path in ("/cancel", "/test_hw", "/clear_nvs"):
            self.server.sim.command(url.path[1:])
            return self._send(200, OK, TEXT)
        self._send(404, "not found", TEXT)

    def do_GET(self):
        self._route(post=False)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._route(post=True)

    def do_OPTIONS(self):
        self._send(200, OK, TEXT)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bio-Band HTTP API mock (stdlib only).")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="listen port (default 8000)")
    parser.add_argument("--quiet", action="store_true", help="hide repeated /data poll log lines")
    args = parser.parse_args(argv)

    sim = Sim()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads, server.sim = True, sim
    server.quiet, server.poll_logged = args.quiet, False
    print("Bio-Band mock on http://%s:%d/  (page: %s)"
          % (args.host, server.server_address[1], PAGE), file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        sim.close()


if __name__ == "__main__":
    main()
