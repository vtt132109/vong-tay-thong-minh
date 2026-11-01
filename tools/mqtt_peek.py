#!/usr/bin/env python3
"""Read the latest retained status/telemetry of the band from the public MQTT broker (stdlib only).

Usage: python tools/mqtt_peek.py [--base bioband/vtt132109/dev01] [--seconds 6] [--json]
Reading is passive; nothing is published. Library use: peek(base) -> dict(status=..., telemetry=dict|None).
"""
import argparse
import json
import socket
import struct
import time

BROKER, PORT = "broker.emqx.io", 1883


def _s(x: str) -> bytes:
    b = x.encode()
    return struct.pack(">H", len(b)) + b


def _rl(n: int) -> bytes:
    out = b""
    while True:
        d, n = n % 128, n // 128
        out += bytes([d | (128 if n else 0)])
        if not n:
            return out


def _pkt(t: int, body: bytes) -> bytes:
    return bytes([t]) + _rl(len(body)) + body


def peek(base: str = "bioband/vtt132109/dev01", seconds: float = 6.0) -> dict:
    sock = socket.create_connection((BROKER, PORT), timeout=8)
    sock.sendall(_pkt(0x10, _s("MQTT") + bytes([4, 2]) + struct.pack(">H", 30) + _s("peek-%d" % int(time.time()))))
    sock.recv(4)
    sock.sendall(_pkt(0x82, struct.pack(">H", 1) + _s(base + "/status") + b"\0" + _s(base + "/telemetry") + b"\0"))
    seen, buf, end = {}, b"", time.time() + seconds
    sock.settimeout(1.0)
    while time.time() < end:
        try:
            buf += sock.recv(4096)
        except socket.timeout:
            continue
        while len(buf) >= 2:
            n, m, i = 0, 1, 1
            while i < len(buf):
                c = buf[i]
                n += (c & 127) * m
                m *= 128
                i += 1
                if not c & 128:
                    break
            if i + n > len(buf):
                break
            body, t, buf = buf[i:i + n], buf[0] >> 4, buf[i + n:]
            if t == 3:
                tl = struct.unpack(">H", body[:2])[0]
                seen[body[2:2 + tl].decode().split("/")[-1]] = body[2 + tl:].decode()
    sock.close()
    tel = None
    if seen.get("telemetry"):
        try:
            tel = json.loads(seen["telemetry"])
        except ValueError:
            pass
    return {"status": seen.get("status"), "telemetry": tel}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="bioband/vtt132109/dev01")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = peek(a.base, a.seconds)
    if a.json:
        print(json.dumps(r))
    else:
        print("status   :", r["status"])
        t = r["telemetry"] or {}
        keys = ["state", "bpm", "spo2", "finger", "acc", "falls", "steps", "ai_label", "ai_p", "ai_thr", "ai_mlp", "ai_cnn",
                "ai_us", "ai_cnn_us", "ai_arm", "ai_self", "cpu_mhz", "chip_c", "jit", "fps", "fw"]
        print("telemetry:", {k: t.get(k) for k in keys if k in t})
