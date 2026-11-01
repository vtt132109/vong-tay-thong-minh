"""Leave-one-subject-out experiments. Usage: run_loso.py NAME [NAME ...] [--seeds 0,1,2]"""
import json, sys, time, pickle
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings
from ai_lab import lab
from ai_lab.evalx import window_report
import torch
torch.set_num_threads(3)

OUT = Path(__file__).resolve().parents[2] / "dataset" / "ai_results"
OUT.mkdir(parents=True, exist_ok=True)

# name -> (trainer(Wtr, Wva, seed), [train views])
CONFIGS = {
    "mlp_hifd":     (lambda a, b, s: lab.fit_mlp(a, b, s), ["hifd"]),
    "mlp_fw":       (lambda a, b, s: lab.fit_mlp(a, b, s), ["fw"]),
    "mlp_fw_aug":   (lambda a, b, s: lab.fit_mlp(a, b, s), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "mlpinv_fw_aug": (lambda a, b, s: lab.fit_mlp(a, b, s, feat="FINV"), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "mlp32_fw_aug": (lambda a, b, s: lab.fit_mlp(a, b, s, hidden=32), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "lr_fw_aug":    (lambda a, b, s: lab.fit_sklearn("lr", a, b, s), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "dt_fw_aug":    (lambda a, b, s: lab.fit_sklearn("dt", a, b, s), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "rf_fw_aug":    (lambda a, b, s: lab.fit_sklearn("rf", a, b, s), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "rfinv_fw_aug": (lambda a, b, s: lab.fit_sklearn("rf", a, b, s, feat="FINV"), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "mlpall_fw_aug": (lambda a, b, s: lab.fit_mlp(a, b, s, feat="F42+FINV"), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "mlpinv_fw":    (lambda a, b, s: lab.fit_mlp(a, b, s, feat="FINV"), ["fw"]),
    "mlpinv32_fw_aug": (lambda a, b, s: lab.fit_mlp(a, b, s, hidden=32, feat="FINV"), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "abl_legacy":   (lambda a, b, s: lab.fit_mlp(a, b, s, legacy=True), ["fw"]),
    "abl_nohard":   (lambda a, b, s: lab.fit_mlp(a, b, s, hard_w=1.0), ["fw"]),
    "abl_noweight": (lambda a, b, s: lab.fit_mlp(a, b, s, hard_w=1.0, pos_w=1.0), ["fw"]),
    "abl_nopostvar": (lambda a, b, s: lab.fit_mlp(a, b, s, cols=[i for i in range(42) if i != 41]), ["fw"]),
    "cnnL_fw":      (lambda a, b, s: lab.fit_cnn(a, b, s, cfg=(16, 32, 32)), ["fw"]),
    "cnnS_fw":      (lambda a, b, s: lab.fit_cnn(a, b, s, cfg=(4, 8, 8)), ["fw"]),
    "cnn_fw":       (lambda a, b, s: lab.fit_cnn(a, b, s), ["fw"]),
    "cnn_fw_aug":   (lambda a, b, s: lab.fit_cnn(a, b, s), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
    "cnnL_fw_aug":  (lambda a, b, s: lab.fit_cnn(a, b, s, cfg=(16, 32, 32)), ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]),
}

def summarize(name, recs, W, scores, thr, seeds):
    s0 = scores[0]
    per_subj = {h: thr[(h, seeds[0])] for h in sorted(set(W.subj.tolist()))}
    rep = lab.pooled_report(recs, W, s0, per_subj)
    curve, hours = lab.operating_curve(recs, W, s0)
    wr = window_report(W, s0, 0.9)
    r = {k: lab.recall_at_fa(curve, k) for k in (2, 5, 10, 20)}
    print(f"\n=== {name} (seed {seeds[0]}) ===")
    print(f"  per-fold thr: recall {rep['detected']}/{rep['n_fall']} CI {rep['recall_ci'][0]:.2f}-{rep['recall_ci'][1]:.2f} | "
          f"false alerts {rep['false_alerts']} in {rep['hours']:.2f} h = {rep['fa_per_h']:.1f}/h (95% up {rep['fa_upper95']:.1f}) | latency {rep['latency_median_s']:.2f}s")
    print(f"  recall @ FA/h<=2/5/10/20: {r[2]:.2f}/{r[5]:.2f}/{r[10]:.2f}/{r[20]:.2f} | window@0.9 P {wr['precision']:.3f} R {wr['recall']:.3f}")
    print(f"  false by scenario {rep['false_by_scenario']} | missed {rep['missed'][:6]}")
    return {"rep": rep, "curve": curve.tolist(), "recall_at_fa": r}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seeds = (0,)
    for i, a in enumerate(sys.argv):
        if a == "--seeds":
            seeds = tuple(int(x) for x in sys.argv[i + 1].split(","))
            args = [x for x in args if x != sys.argv[i + 1]]
    recs = load_recordings()
    lab.RECS = recs
    V = lab.get_views(recs)
    for name in args:
        trainer, vnames = CONFIGS[name]
        t = time.time()
        scores, thr = lab.loso(recs, name, trainer, [V[v] for v in vnames], V["fw"], seeds=seeds, log=False)
        res = summarize(name, recs, V["fw"], scores, thr, seeds)
        res["seconds"] = time.time() - t
        tag = "" if seeds == (0,) else "_s" + "".join(map(str, seeds))
        np.savez(OUT / f"loso_{name}{tag}.npz", scores=scores)
        json.dump({"thr": {f"{k[0]}_{k[1]}": v for k, v in thr.items()}, **res}, open(OUT / f"loso_{name}{tag}.json", "w"), default=str)
        print(f"  ({res['seconds']:.0f}s)", flush=True)
