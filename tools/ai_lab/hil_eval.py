"""Hardware-in-the-loop evaluation: stream real HIFD windows over USB into the ESP32-S3 and compare the
probabilities computed ON THE CHIP with the numpy reference of the deployed models.

Needs the board on USB (no other program holding the port) and dataset/ai_results/final_models.pkl
(written by export_final.py; the flashed headers must come from the same export).

Usage: hil_eval.py [--port COM13] [--subjects 19,20,21] [--step 1] [--out dataset/ai_results/hil.json]
"""
import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab import lab, quant
from ai_lab.data import load_recordings
from ai_lab.evalx import event_report, wilson

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "dataset" / "ai_results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM13")
    ap.add_argument("--subjects", default="19,20,21")
    ap.add_argument("--step", type=int, default=1, help="use every N-th window")
    ap.add_argument("--thr", type=float, default=None)
    ap.add_argument("--out", default=str(RES / "hil.json"))
    a = ap.parse_args()

    recs = load_recordings()
    W = lab.get_views(recs, ("fw",))["fw"]
    subj = [int(s) for s in a.subjects.split(",")]
    m = np.isin(W.subj, subj)
    idx = np.where(m)[0][::a.step]
    Wt = W.sub(np.isin(np.arange(len(W)), idx))
    fm = pickle.load(open(RES / "final_models.pkl", "rb"))
    ref_mlp = fm["mlp"].predict(Wt)
    ref_cnn = quant.int8_forward(fm["q"], Wt.X)
    cfg = json.loads((RES / "fusion.json").read_text()) if (RES / "fusion.json").is_file() else {}
    thr = a.thr if a.thr is not None else float(cfg.get("thr_fused", 0.9))

    ser = serial.Serial(a.port, 115200, timeout=2)
    ser.dtr = False
    ser.rts = False
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"#HIL\n")
    t0 = time.time()
    while time.time() - t0 < 5:
        if b"HIL READY" in ser.readline():
            break
    else:
        sys.exit("board did not answer #HIL (is the CNN/HIL firmware flashed? is another program using the port?)")

    dev_mlp = np.zeros(len(Wt))
    dev_cnn = np.zeros(len(Wt))
    t_start = time.time()
    for i in range(len(Wt)):
        row = ",".join(f"{v:.5f}" for v in Wt.X[i].reshape(-1))
        ser.write(("W," + row + "\n").encode())
        for _ in range(50):
            ln = ser.readline().decode("utf-8", "replace").strip()
            if ln.startswith("P,"):
                _, pm, pc = ln.split(",")
                dev_mlp[i], dev_cnn[i] = float(pm), float(pc)
                break
        else:
            sys.exit(f"no answer for window {i}")
        if i % 200 == 0:
            print(f"  {i}/{len(Wt)} windows ({time.time()-t_start:.0f}s)", flush=True)
    ser.write(b"#END\n")
    ser.close()

    d_mlp = np.abs(dev_mlp - ref_mlp)
    d_cnn = np.abs(dev_cnn - ref_cnn)
    dev_ens = (dev_mlp + dev_cnn) / 2
    ref_ens = (ref_mlp + ref_cnn) / 2
    flips = int(((dev_ens >= thr) != (ref_ens >= thr)).sum())
    ev_dev = event_report(recs, Wt, dev_ens, thr)
    ev_ref = event_report(recs, Wt, ref_ens, thr)
    out = {
        "windows": len(Wt), "subjects": subj, "threshold": thr,
        "mlp_max_abs_diff": float(d_mlp.max()), "mlp_mean_abs_diff": float(d_mlp.mean()),
        "cnn_max_abs_diff": float(d_cnn.max()), "cnn_mean_abs_diff": float(d_cnn.mean()),
        "decision_flips": flips,
        "event_device": {k: ev_dev[k] for k in ("detected", "n_fall", "false_alerts", "hours", "fa_per_h", "latency_median_s", "missed", "false_by_scenario")},
        "event_reference": {k: ev_ref[k] for k in ("detected", "n_fall", "false_alerts", "hours", "fa_per_h")},
    }
    print(json.dumps(out, indent=1, default=str))
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
