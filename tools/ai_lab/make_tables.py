"""Markdown result tables for BAO_CAO.md -> docs/results_tables.md (numbers come straight from saved runs)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab import lab
from ai_lab.data import load_recordings
from ai_lab.evalx import event_report, wilson

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "dataset" / "ai_results"
recs = load_recordings()
W = lab.get_views(recs, ("fw",))["fw"]


def scores(files):
    arr = []
    for f in files:
        p = RES / f
        if p.is_file():
            arr += list(np.load(p)["scores"])
    return (np.mean(arr, axis=0), len(arr)) if arr else (None, 0)


def jrep(f):
    p = RES / f
    return json.load(open(p))["rep"] if p.is_file() else None


MODELS = [  # label, params, npz files, json (per-fold threshold run)
    ("Logistic regression (42 feat.)", "43", ["loso_lr_fw_aug.npz"], "loso_lr_fw_aug.json"),
    ("Decision tree (depth 6)", "depth 6", ["loso_dt_fw_aug.npz"], "loso_dt_fw_aug.json"),
    ("Random forest (60 trees)", "60 trees, depth<=8", ["loso_rf_fw_aug.npz"], "loso_rf_fw_aug.json"),
    ("MLP-42, trained on HIFD as published", "705", ["loso_mlp_hifd.npz"], "loso_mlp_hifd.json"),
    ("MLP-42, firmware-chain data", "705", ["loso_mlp_fw.npz"], "loso_mlp_fw.json"),
    ("MLP-42, firmware chain + augmentation", "705", ["loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz"], "loso_mlp_fw_aug.json"),
    ("MLP-30, orientation-invariant features", "513", ["loso_mlpinv_fw_aug.npz"], "loso_mlpinv_fw_aug.json"),
    ("1D-CNN small (4-8-8)", "529", ["loso_cnnS_fw.npz"], "loso_cnnS_fw.json"),
    ("1D-CNN (8-16-16), firmware-chain data", "1761", ["loso_cnn_fw.npz", "loso_cnn_fw_s12.npz"], "loso_cnn_fw.json"),
    ("1D-CNN (8-16-16), + augmentation", "1761", ["loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz"], "loso_cnn_fw_aug.json"),
    ("1D-CNN large (16-32-32)", "6337", ["loso_cnnL_fw.npz"], "loso_cnnL_fw.json"),
]
lines = []
lines.append("### Leave-one-subject-out, 21 held-out subjects, firmware signal chain\n")
lines.append("Operating-curve columns are threshold-free (recall of the 104 falls at the best threshold that keeps pooled false alerts "
             "at or below the budget; 1.95 h of daily activities, so 1 alert ≈ 0.51 /h). Seeds averaged where several exist.\n")
lines.append("| Model | Params | Seeds | Recall @ ≤1 FA/h | @ ≤2 | @ ≤5 | Per-fold threshold: recall (95 % CI) | FA/h |")
lines.append("|---|---|---|---|---|---|---|---|")
for label, params, files, js in MODELS:
    s, ns = scores(files)
    if s is None:
        continue
    curve, hours = lab.operating_curve(recs, W, s)
    r = [lab.recall_at_fa(curve, k) for k in (1, 2, 5)]
    rep = jrep(js)
    pf = f"{rep['detected']}/{rep['n_fall']} ({rep['recall_ci'][0]:.2f}–{rep['recall_ci'][1]:.2f})" if rep else "–"
    fa = f"{rep['fa_per_h']:.1f}" if rep else "–"
    lines.append(f"| {label} | {params} | {ns} | {r[0]:.3f} | {r[1]:.3f} | {r[2]:.3f} | {pf} | {fa} |")
# ensemble
mlp, n1 = scores(["loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz"])
cnn, n2 = scores(["loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz"])
ens = (mlp + cnn) / 2
curve, hours = lab.operating_curve(recs, W, ens)
r = [lab.recall_at_fa(curve, k) for k in (1, 2, 5)]
lines.append(f"| **Ensemble = mean(MLP-42 aug, CNN aug)** | 2466 | {n1}+{n2} | **{r[0]:.3f}** | **{r[1]:.3f}** | **{r[2]:.3f}** | see below | |")

cfg = json.load(open(RES / "fusion.json"))
lines.append("\n### Deployed operating point (pooled out-of-sample scores)\n")
lines.append("| Rule | Threshold | Falls detected (95 % CI) | False alerts | FA/h (95 % upper) | Missed |")
lines.append("|---|---|---|---|---|---|")
for name, s, t in (("Ensemble", ens, cfg["thr_fused"]), ("MLP-42 alone", mlp, cfg["thr_mlp"]), ("CNN alone", cnn, cfg["thr_cnn"])):
    ev = event_report(recs, W, s, t)
    lo, hi = ev["recall_ci"]
    lines.append(f"| {name} | {t:.2f} | {ev['detected']}/{ev['n_fall']} ({lo:.2f}–{hi:.2f}) | {ev['false_alerts']} in {ev['hours']:.2f} h | "
                 f"{ev['fa_per_h']:.2f} ({ev['fa_upper95']:.1f}) | {', '.join(ev['missed']) or '–'} |")

b1 = json.load(open(RES / "b1_baselines.json"))
lines.append("\n### Rule-based baselines on all 21 subjects (no training involved)\n")
lines.append("| Rule | Falls detected | False alerts | FA/h | Median latency |")
lines.append("|---|---|---|---|---|")
for k in ("threshold only", "FSM (still after impact)"):
    r_ = b1[k]
    lines.append(f"| {'Threshold ≥ 25 m/s² only' if k == 'threshold only' else 'Firmware FSM, original constants'} | {r_['detected']}/{r_['n_fall']} | {r_['false_alerts']} in {r_['hours']:.2f} h | {r_['fa_per_h']:.1f} | {r_['latency_median_s']:.2f} s |")
sweep = json.load(open(RES / "fsm_sweep.json"))
row = [x for x in sweep if x[:3] == [1500, 2000, 0.8]]
if row:
    x = row[0]
    lines.append(f"| FSM recalibrated (settle 1.5 s, window 2 s, var < 0.8), subjects 16–21 | {x[7]}/{x[8]} | {x[9]} in 0.50 h | {x[6]:.1f} | 3.4 s |")

ab = []
for label, f in (("Final recipe, MLP-42 (firmware chain)", "loso_mlp_fw.json"), ("No event-centred labels (recording-level labels)", "loso_abl_legacy.json"),
                 ("No hard-negative weighting (bed/chair)", "loso_abl_nohard.json"), ("No class weights", "loso_abl_noweight.json"),
                 ("Without feature 41 (variance of the last 0.5 s)", "loso_abl_nopostvar.json")):
    p = RES / f
    if p.is_file():
        j = json.load(open(p))
        ab.append(f"| {label} | {j['rep']['detected']}/{j['rep']['n_fall']} | {j['rep']['false_alerts']} | {j['recall_at_fa']['2']:.2f} / {j['recall_at_fa']['5']:.2f} |")
if ab:
    lines.append("\n### Ablation (MLP-42, seed 0, per-fold threshold)\n")
    lines.append("| Variant | Falls detected | False alerts (1.95 h) | Recall @ ≤2 / ≤5 FA/h |")
    lines.append("|---|---|---|---|")
    lines += ab

out = ROOT / "docs" / "results_tables.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
