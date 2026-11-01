"""GD D: ensemble + k-of-n debounce + threshold from out-of-sample LOSO scores, and rule/AI fusion strategies.

Writes dataset/ai_results/fusion.json (read by export_final.py).
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings, FS
from ai_lab import lab
from ai_lab.evalx import (event_report, rec_slices, merge_fires, wilson, poisson_upper, simulate_fsm,
                          fsm_input, alerts_report, WIN)

R = Path(__file__).resolve().parents[2] / "dataset" / "ai_results"
recs = load_recordings(); W = lab.get_views(recs, ("fw",))["fw"]


def load(name_files):
    arrs = []
    for f in name_files:
        p = R / f
        if p.is_file():
            arrs += list(np.load(p)["scores"])
    return np.mean(arrs, axis=0), len(arrs)

mlp, nm = load(["loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz"])
cnn, nc = load(["loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz"])
print(f"MLP seeds averaged: {nm}   CNN seeds averaged: {nc}")
ens = (mlp + cnn) / 2


def debounce(scores, thr, k, n):
    """fire[i] = at least k of the last n windows (same recording) were >= thr."""
    fire = scores >= thr
    out = np.zeros_like(fire)
    for sl in rec_slices(W).values():
        f = fire[sl].astype(int)
        c = np.convolve(f, np.ones(n, dtype=int))[:len(f)]
        out[sl] = c >= k
    return out


def report(label, fire, subj_mask=None):
    """Operational metrics from boolean per-window fire flags (reuse event_report via 0/1 scores)."""
    s = fire.astype(float)
    Wm = W if subj_mask is None else W.sub(subj_mask)
    sm = s if subj_mask is None else s[subj_mask]
    ev = event_report(recs, Wm, sm, 0.5)
    print(f"{label:46s} recall {ev['detected']:3d}/{ev['n_fall']:3d} ({ev['recall']:.3f}, CI {ev['recall_ci'][0]:.2f}-{ev['recall_ci'][1]:.2f}) "
          f"FA {ev['false_alerts']:2d}/{ev['hours']:.2f}h = {ev['fa_per_h']:.2f}/h (95% up {ev['fa_upper95']:.1f}) lat {ev['latency_median_s']:.2f}s")
    return ev

print("\n== debounce x threshold on the ensemble (pooled 21 held-out subjects) ==")
best = None
for k, n in ((1, 1), (2, 3), (2, 2), (3, 4)):
    for thr in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        ev = report(f"ens thr {thr:.2f} {k}-of-{n}", debounce(ens, thr, k, n))
        score = ev["recall"] - 0.04 * ev["false_alerts"]
        if best is None or score > best[0]:
            best = (score, thr, k, n, ev)
print("\nbest by recall - 0.04*FA:", best[1:4], f"recall {best[4]['recall']:.3f}, FA {best[4]['false_alerts']}")

# single-model references at their own best threshold with the same debounce
print("\n== single models (2-of-3, thr 0.9) vs ensemble ==")
report("MLP-42  2of3 thr.9", debounce(mlp, 0.9, 2, 3))
report("CNN-int8 2of3 thr.9", debounce(cnn, 0.9, 2, 3))
report("Ensemble 2of3 thr.9", debounce(ens, 0.9, 2, 3))
report("MLP-42  1of1 thr.9", mlp >= 0.9)
report("CNN-int8 1of1 thr.9", cnn >= 0.9)
report("Ensemble 1of1 thr.9", ens >= 0.9)

# ---------------------------------------------------------------- rule + AI fusion
print("\n== rule (FSM) + AI fusion, held-out subjects 16-21 (FSM params fixed on subjects 1-15) ==")
FSM = dict(settle_ms=1500, window_ms=2000, var_still=0.8, var_motion=4.0)
k, n, thr = 1, 1, 0.87   # deployed ensemble threshold (see the threshold rule at the end of this script)
fire = debounce(ens, thr, k, n)
sl = rec_slices(W)
ids = [i for i, r in enumerate(recs) if r.subject >= 16]
ai_al, fsm_al, and_al, or_al, promo_al = {}, {}, {}, {}, {}
for ri in ids:
    r = recs[ri]
    s = sl[ri]
    st = W.start[s]
    ftimes = ((st + WIN) / FS)[fire[s]]
    ai_al[ri] = merge_fires(ftimes.tolist())
    acc = fsm_input(r)
    fa = [a[0] / 1000 for a in simulate_fsm(acc, **FSM)]
    fsm_al[ri] = fa
    and_al[ri] = [t for t in fa if np.any((ftimes >= t - 8) & (ftimes <= t + 1))]
    or_al[ri] = merge_fires(sorted(fa + ai_al[ri]))
    pa = [a[0] / 1000 for a in simulate_fsm(acc, ai_fire_ms=ftimes * 1000, ai_promote=True, **FSM)]
    promo_al[ri] = pa
TAU = (0.1, 0.2, 0.3, 0.5, 0.6, 0.7, 0.8)
combo = {t: {} for t in TAU}
for ri in ids:
    s = sl[ri]
    st = W.start[s]
    endt = (st + WIN) / FS
    for tau in TAU:
        ok = []
        for t in fsm_al[ri]:
            m = (endt >= t - 6) & (endt <= t + 1)
            if m.any() and ens[s][m].max() >= tau:
                ok.append(t)
        combo[tau][ri] = merge_fires(sorted(ok + ai_al[ri]))
for tau in TAU:
    rep = alerts_report(recs, combo[tau], ids)
    print(f"AI strong OR (FSM AND AI>={tau:.1f})        recall {rep['detected']:2d}/{rep['n_fall']} ({rep['recall']:.3f}) FA {rep['false_alerts']:2d}/{rep['hours']:.2f}h = {rep['fa_per_h']:.1f}/h  lat {rep['latency_median_s']:.2f}s")
for label, al in (("AI only (debounced ensemble)", ai_al), ("FSM only (recalibrated)", fsm_al),
                  ("FSM AND AI", and_al), ("FSM OR AI", or_al), ("FSM + AI promotes ambiguous", promo_al)):
    rep = alerts_report(recs, al, ids)
    print(f"{label:34s} recall {rep['detected']:2d}/{rep['n_fall']} ({rep['recall']:.3f}) FA {rep['false_alerts']:2d}/{rep['hours']:.2f}h = {rep['fa_per_h']:.1f}/h  lat {rep['latency_median_s']:.2f}s")

# ---------------------------------------------------------------- thresholds for firmware
# Rule: the HIGHEST threshold that still keeps pooled held-out recall >= 95 % with <= 1 false alert
# (~0.5/h). Higher thresholds are preferred on purpose: the models were trained on public data, so
# the on-device false-alarm rate is probably worse than the HIFD estimate and a margin is needed.
def pick(scores, label):
    for t in np.arange(0.95, 0.30, -0.005):
        ev = event_report(recs, W, (scores >= t).astype(float), 0.5)
        if ev["recall"] >= 0.95 and ev["false_alerts"] <= 1:
            return float(round(t, 3)), ev
    return 0.9, event_report(recs, W, (scores >= 0.9).astype(float), 0.5)

t_ens, ev = pick(ens, "ensemble")
t_mlp, ev_m = pick(mlp, "mlp")
t_cnn, ev_c = pick(cnn, "cnn")
print(f"\nchosen thresholds: ensemble {t_ens}  mlp {t_mlp}  cnn {t_cnn}  (1-of-1, no debounce)")
for name, e in (("ensemble", ev), ("mlp", ev_m), ("cnn", ev_c)):
    print(f"  {name:9s} recall {e['detected']}/{e['n_fall']} CI {e['recall_ci'][0]:.3f}-{e['recall_ci'][1]:.3f}  FA {e['false_alerts']} in {e['hours']:.2f} h = {e['fa_per_h']:.2f}/h (95% up {e['fa_upper95']:.1f})  missed {e['missed']}  fa_by_scen {e['false_by_scenario']}")
cfg = {"thr_fused": t_ens, "thr_mlp": t_mlp, "thr_cnn": t_cnn, "k": 1, "n": 1, "fsm": FSM, "tau_low": AI_SUPPORT_TAU if "AI_SUPPORT_TAU" in globals() else 0.5,
       "recall": ev["recall"], "recall_ci": list(ev["recall_ci"]), "false_alerts": ev["false_alerts"], "hours": ev["hours"],
       "fa_per_h": ev["fa_per_h"], "fa_upper95": ev["fa_upper95"], "missed": ev["missed"],
       "cnn_cfg": [8, 16, 16], "cnn_views": ["fw", "fw_aug0", "fw_aug1", "fw_aug2"]}
(R / "fusion.json").write_text(json.dumps(cfg, indent=1, default=float))
