"""GD B1: how much does the shipped model lose when HIFD is passed through the firmware chain?
Also GD C baselines that need no training: bare threshold and the firmware FSM, on all 21 subjects.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings, SPLIT, FS
from ai_lab.evalx import (build_windows, event_report, window_report, simulate_fsm,
                          fsm_input, alerts_report)
from ai_lab.features import feat42
from ai_lab.models import load_header_mlp, shipped_mlp_scores
from ai_lab.preproc import check_gravity_convention

OUT = Path(__file__).resolve().parents[2] / "dataset" / "ai_results"
OUT.mkdir(parents=True, exist_ok=True)

recs = load_recordings()
print("gravity convention check:", check_gravity_convention(recs))
h = load_header_mlp()
res = {}
test_subjects = set(SPLIT["test"])
for view in ("hifd", "fw"):
    t = time.time()
    W = build_windows(recs, view, only=test_subjects)
    s = shipped_mlp_scores(feat42(W.X), h)
    ev = event_report(recs, W, s, h["thr"])
    wd = window_report(W, s, h["thr"])
    res[view] = {"event": ev, "window": wd}
    print(f"\n[shipped MLP | view={view} | test subjects 19-21 | {time.time()-t:.1f}s]")
    print(f"  event recall {ev['detected']}/{ev['n_fall']}  CI {ev['recall_ci'][0]:.2f}-{ev['recall_ci'][1]:.2f}"
          f"  false alerts {ev['false_alerts']} in {ev['hours']:.2f} h  ({ev['fa_per_h']:.1f}/h, 95% upper {ev['fa_upper95']:.1f}/h)")
    print(f"  latency median {ev['latency_median_s']:.2f}s  false by scenario {ev['false_by_scenario']}  missed {ev['missed']}")
    print(f"  window P/R/F1 {wd['precision']:.3f}/{wd['recall']:.3f}/{wd['f1']:.3f}  tp/fp/fn {wd['tp']}/{wd['fp']}/{wd['fn']}")

# FSM / threshold baselines on all 21 subjects (no training involved)
print("\n[firmware rules on all 21 subjects]")
ids = list(range(len(recs)))
fsm_al, thr_al = {}, {}
for ri, r in enumerate(recs):
    a = fsm_input(r)
    fsm_al[ri] = [al[0] / 1000.0 for al in simulate_fsm(a)]
    # bare threshold: first sample >= 25 m/s^2 then 2 s cooldown, alert at impact + 0.2 s
    idx, last = [], -10**9
    for i in np.where(a >= 25.0)[0]:
        if i - last > 2 * FS:
            idx.append(i / FS + 0.2)
        last = i
    thr_al[ri] = idx
for name, al in (("FSM (still after impact)", fsm_al), ("threshold only", thr_al)):
    rep = alerts_report(recs, al, ids)
    res[name] = rep
    print(f"  {name}: recall {rep['detected']}/{rep['n_fall']} CI {rep['recall_ci'][0]:.2f}-{rep['recall_ci'][1]:.2f}; "
          f"false alerts {rep['false_alerts']} in {rep['hours']:.2f} h = {rep['fa_per_h']:.1f}/h (95% upper {rep['fa_upper95']:.1f}); "
          f"latency {rep['latency_median_s']:.2f}s")
    print(f"     false by scenario {rep['false_by_scenario']}")
(OUT / "b1_baselines.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
