"""F1 (PLAN.md, "Quyet dinh cau hinh phat hien nga cuoi cung"): candidate fusion configs C0..C8 on the saved LOSO scores.

NO model is trained here: it only recombines the saved out-of-sample LOSO probabilities (MLP float, CNN int8,
seeds averaged exactly like run_fusion.py) with the simulated FSM (evalx.simulate_fsm).

  1. grid of candidates C0..C8 -> recall / false alerts / latency, subjects 16-21 (clean) and all 21
  2. nested leave-one-subject-out selection of the thresholds + paired bootstrap over subjects vs C1
  3. "one model fails" stress test (MLP scores -> 0, then CNN scores -> 0 on the fall recordings)

Writes dataset/ai_results/final_config.json and log_final_config.txt.  Reads only; nothing else is touched.
"""
import json, math, sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings, FS
from ai_lab import lab
from ai_lab.evalx import (event_report, rec_slices, merge_fires, wilson, poisson_upper, simulate_fsm,
                          fsm_input, alerts_report, WIN, THRESH)

T0 = time.time()
R = Path(__file__).resolve().parents[2] / "dataset" / "ai_results"
LOG = []
NOTES = []


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def conv(o):
    if isinstance(o, dict):
        return {str(k): conv(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [conv(v) for v in o]
    if isinstance(o, np.ndarray):
        return conv(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ------------------------------------------------------------------ data and scores (same loading as run_fusion.py)
recs = load_recordings()
W = lab.get_views(recs, ("fw",))["fw"]
N = len(recs)
SL = rec_slices(W)


def load(files):
    arrs = []
    for f in files:
        p = R / f
        if p.is_file():
            arrs += list(np.load(p)["scores"])
    return np.mean(arrs, axis=0), len(arrs)


mlp0, nm = load(["loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz"])
cnn0, nc = load(["loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz"])
out(f"MLP seeds averaged: {nm}   CNN seeds averaged: {nc}   recordings {N}  windows {len(W)}")

WEIGHTS = (0.3, 0.4, 0.6, 0.7)


def derive(m, c):
    S = {"mlp": m, "cnn": c, "mean": (m + c) / 2, "max": np.maximum(m, c), "min": np.minimum(m, c)}
    for w in WEIGHTS:
        S[f"w{w}"] = w * m + (1 - w) * c
    return S


S_BASE = derive(mlp0, cnn0)
REC_SUBJ = np.array([r.subject for r in recs])
SUBJS = sorted(set(REC_SUBJ.tolist()))
assert SUBJS == list(range(1, 22)), SUBJS
NS = len(SUBJS)
ISFALL = np.array([r.is_fall for r in recs])
CENTER = np.array([(r.center / FS if r.is_fall else np.nan) for r in recs])
HOURS = np.array([(max(r.n / FS - 11.0, 0.0) if r.is_fall else r.n / FS) / 3600.0 for r in recs])  # alerts_report convention
ENDT = {ri: (W.start[SL[ri]] + WIN) / FS for ri in range(N)}
ONEHOT = np.zeros((N, NS))
ONEHOT[np.arange(N), REC_SUBJ - 1] = 1.0
G_ALL = np.ones(N, bool)
G_1621 = REC_SUBJ >= 16
G_115 = REC_SUBJ <= 15
SUBJ_FALLMASK = np.zeros(len(W), bool)         # windows belonging to fall recordings (for the stress test)
for ri in range(N):
    if ISFALL[ri]:
        SUBJ_FALLMASK[SL[ri]] = True

# ------------------------------------------------------------------ FSM (params fixed as in run_fusion.py)
FSM_B = dict(settle_ms=1500, window_ms=2000, var_still=0.8, var_motion=4.0)   # recalibrated, tuned on subjects 1-15
FSM_ORIG = dict(settle_ms=200, window_ms=3000, var_still=0.08, var_motion=0.8)  # original firmware rule (C0)
VS_LIST = (0.8, 1.5, 2.5)
out("computing FSM alerts (this is the slow part)...")
ACC = [fsm_input(r) for r in recs]
FSMA = {vs: [np.array([a[0] / 1000 for a in simulate_fsm(ACC[ri], **{**FSM_B, "var_still": vs})]) for ri in range(N)]
        for vs in VS_LIST}
FSM_ORIG_AL = [[a[0] / 1000 for a in simulate_fsm(ACC[ri], **FSM_ORIG)] for ri in range(N)]


def fsm_trace(acc, thr=THRESH, settle_ms=200, window_ms=3000, var_still=0.08, var_motion=0.8):
    """Verbatim copy of evalx.simulate_fsm (no AI) that additionally records the state per sample
    (0 IDLE, 1 FREE_FALL, 2 IMPACT). Needed only for C6 ('AI single-model trigger only while FREE_FALL/IMPACT')."""
    IDLE, FREE, IMPACT = 0, 1, 2
    st = IDLE; low = 0; ff_start = 0; imp_start = 0; samples = []; extended = False; last_direct = 0
    alerts = []; cooldown_until = -1
    states = np.zeros(len(acc), np.int8)
    for i, a in enumerate(acc):
        if i:
            states[i - 1] = st
        now = i * 20
        if now < cooldown_until:
            continue
        if st == IDLE:
            if a < 5.0:
                low += 1
                if low >= 3:
                    ff_start = now; st = FREE
            else:
                low = 0
            if st == IDLE and a >= thr and (last_direct == 0 or now - last_direct > 2000):
                last_direct = now; st, imp_start, samples, extended = IMPACT, now, [], False
        elif st == FREE:
            if a >= thr:
                last_direct = now; st, imp_start, samples, extended = IMPACT, now, [], False
            elif now - ff_start > 800:
                st, low = IDLE, 0
        elif st == IMPACT:
            el = now - imp_start
            if el >= settle_ms and len(samples) < 300:
                samples.append(float(a))
            if el >= window_ms + settle_ms:
                if len(samples) < 0.2 * window_ms / 20:
                    st, low = IDLE, 0
                    continue
                s = np.asarray(samples)
                var = max(float(np.mean(s * s) - np.mean(s) ** 2), 0.0)
                if var < var_still:
                    alerts.append(now / 1000); cooldown_until = now + 30000; st, low = IDLE, 0
                elif var > var_motion:
                    st, low = IDLE, 0
                elif not extended:
                    extended, imp_start, samples = True, now, []
                else:
                    st, low = IDLE, 0
    states[len(acc) - 1] = st
    return states, alerts


INCAND = {}
trace_ok = True
for ri in range(N):
    states, al = fsm_trace(ACC[ri], **FSM_B)
    if not np.allclose(al, FSMA[0.8][ri]):
        trace_ok = False
    sidx = W.start[SL[ri]] + WIN - 1               # state at the last sample of each scored window
    INCAND[ri] = np.isin(states[sidx], (1, 2))
out(f"FSM state trace reproduces simulate_fsm alerts on all recordings: {trace_ok}   ({time.time()-T0:.0f}s)")
if not trace_ok:
    NOTES.append("fsm_trace (copy of simulate_fsm used for the C6 state flag) did NOT reproduce simulate_fsm alerts on every recording.")


# ------------------------------------------------------------------ system evaluator
class Ev:
    """Evaluates a config dict on every recording for one set of window scores."""

    def __init__(self, S):
        self.S = S
        self._supp = {}

    def supp(self, vs, nm):
        key = (vs, nm)
        if key not in self._supp:
            d = {}
            for ri in range(N):
                ts = FSMA[vs][ri]
                sc = self.S[nm][SL[ri]]
                e = ENDT[ri]
                v = np.full(len(ts), -1.0)
                for k, t in enumerate(ts):
                    m = (e >= t - 6) & (e <= t + 1)
                    if m.any():
                        v[k] = sc[m].max()
                d[ri] = v
            self._supp[key] = d
        return self._supp[key]

    def alerts(self, cfg, ri, cooldown=None):
        if cfg.get("fsm_only"):
            return list(FSM_ORIG_AL[ri])
        times = []
        if cfg.get("a"):
            nm, t = cfg["a"]
            f = self.S[nm][SL[ri]] >= t
            if f.any():
                times += ENDT[ri][f].tolist()
        if cfg.get("hi"):
            nm, t = cfg["hi"]
            f = (self.S[nm][SL[ri]] >= t) & INCAND[ri]
            if f.any():
                times += ENDT[ri][f].tolist()
        if cfg.get("b"):
            nm, tau, vs = cfg["b"]
            ts = FSMA[vs][ri]
            if len(ts):
                times += ts[self.supp(vs, nm)[ri] >= tau].tolist()
        al = merge_fires(sorted(times)) if times else []
        if cooldown and al:
            kept = [al[0]]
            for t in al[1:]:
                if t - kept[-1] > cooldown:
                    kept.append(t)
            al = kept
        return al

    def eval_all(self, cfg, cooldown=None):
        det = np.zeros(N, np.int8); nfa = np.zeros(N, np.int16); lat = np.full(N, np.nan)
        for ri in range(N):
            al = self.alerts(cfg, ri, cooldown)
            if not al:
                continue
            if ISFALL[ri]:
                c = CENTER[ri]
                good = [t for t in al if c - 1.0 <= t <= c + 8.0]
                if good:
                    det[ri] = 1; lat[ri] = good[0] - c
                nfa[ri] = len([t for t in al if not (c - 3.0 <= t <= c + 8.0)])
            else:
                nfa[ri] = len(al)
        return det, nfa, lat


def metrics(det, nfa, lat, mask):
    nf = int(ISFALL[mask].sum()); d = int(det[mask].sum()); fa = int(nfa[mask].sum()); h = float(HOURS[mask].sum())
    l = lat[mask & (det > 0)]
    return {"n_fall": nf, "detected": d, "recall": d / nf if nf else None, "recall_ci": list(wilson(d, nf)),
            "false_alerts": fa, "hours": h, "fa_per_h": fa / h if h else None, "fa_upper95": poisson_upper(fa, h),
            "latency_median_s": float(np.median(l)) if len(l) else None}


def fmt(m):
    return (f"{m['detected']:3d}/{m['n_fall']:3d} ({m['recall_ci'][0]:.2f}-{m['recall_ci'][1]:.2f}) "
            f"FA {m['false_alerts']:2d} {m['fa_per_h']:5.2f}/h up{m['fa_upper95']:4.1f} lat {m['latency_median_s'] if m['latency_median_s'] is not None else float('nan'):4.2f}")


def alerts_dict(ev, cfg):
    return {ri: ev.alerts(cfg, ri) for ri in range(N)}


# ------------------------------------------------------------------ verification against the existing evidence
out("\n== VERIFICATION ==")
ver = {}
fus = json.loads((R / "fusion.json").read_text())
ens = S_BASE["mean"]
evA = event_report(recs, W, (ens >= 0.87).astype(float), 0.5)
ver["C1_pathA_event_report"] = {k: evA[k] for k in ("n_fall", "detected", "recall", "false_alerts", "hours", "fa_per_h", "fa_upper95", "missed")}
ok = (evA["detected"] == 99 and evA["n_fall"] == 104 and evA["false_alerts"] == 0 and abs(evA["hours"] - fus["hours"]) < 1e-6
      and evA["missed"] == fus["missed"] and abs(fus["thr_fused"] - 0.87) < 1e-9)
out(f"C1 path A (mean>=0.87, evalx.event_report): {evA['detected']}/{evA['n_fall']} detected, {evA['false_alerts']} false alerts in {evA['hours']:.4f} h; "
    f"fusion.json says {fus['recall']*104:.0f}/104, {fus['false_alerts']} FA in {fus['hours']:.4f} h, thr {fus['thr_fused']}, missed list equal: {evA['missed'] == fus['missed']}")
ver["C1_reproduces_fusion_json"] = bool(ok)
if not ok:
    out("DISCREPANCY: C1 does not reproduce fusion.json -> stopping as instructed.")
    out("  mine  :", evA["detected"], evA["false_alerts"], evA["hours"], evA["missed"])
    out("  stored:", fus["recall"] * 104, fus["false_alerts"], fus["hours"], fus["missed"])
    (R / "log_final_config.txt").write_text("\n".join(LOG), encoding="utf-8")
    sys.exit(2)
out("  -> OK: C1 reproduces fusion.json exactly (99/104, 0 false alerts, thr 0.87, same 5 missed recordings).")

# plan-table path-A rows (informational)
plan_rows = {}
for label, nm_, thr_ in (("mean 0.70", "mean", 0.70), ("max 0.95", "max", 0.95), ("max 0.98", "max", 0.98),
                         ("min 0.80", "min", 0.80), ("MLP 0.90", "mlp", 0.90), ("CNN 0.90", "cnn", 0.90)):
    e = event_report(recs, W, (S_BASE[nm_] >= thr_).astype(float), 0.5)
    plan_rows[label] = {"detected": e["detected"], "false_alerts": e["false_alerts"], "scen": e["false_by_scenario"]}
    out(f"  plan table row {label:10s}: {e['detected']}/104, FA {e['false_alerts']} {e['false_by_scenario']}")
ver["plan_table_pathA_rows"] = plan_rows

# run_fusion-style system for C1 on subjects 16-21 (copied logic) vs my evaluator
ids16 = [i for i in range(N) if recs[i].subject >= 16]
ens_fire = ens >= 0.87
combo = {}
for ri in ids16:
    s = SL[ri]
    st_ = W.start[s]
    ftimes = ((st_ + WIN) / FS)[ens_fire[s]]
    ai_al = merge_fires(ftimes.tolist())
    fa_ = FSMA[0.8][ri].tolist()
    endt = (st_ + WIN) / FS
    ok_ = []
    for t in fa_:
        m = (endt >= t - 6) & (endt <= t + 1)
        if m.any() and ens[s][m].max() >= 0.5:
            ok_.append(t)
    combo[ri] = merge_fires(sorted(ok_ + ai_al))
rep_fusion = alerts_report(recs, combo, ids16)
CFG_C1 = {"a": ("mean", 0.87), "b": ("mean", 0.5, 0.8)}
EV0 = Ev(S_BASE)
det1, fa1, lat1 = EV0.eval_all(CFG_C1)
mine = metrics(det1, fa1, lat1, G_1621)
same = (rep_fusion["detected"] == mine["detected"] and rep_fusion["false_alerts"] == mine["false_alerts"]
        and abs(rep_fusion["hours"] - mine["hours"]) < 1e-9)
out(f"C1 system (16-21) run_fusion-style alerts_report: {rep_fusion['detected']}/{rep_fusion['n_fall']} FA {rep_fusion['false_alerts']} in {rep_fusion['hours']:.3f} h"
    f"   my evaluator: {mine['detected']}/{mine['n_fall']} FA {mine['false_alerts']} in {mine['hours']:.3f} h   identical: {same}")
ver["C1_system_16_21_vs_run_fusion_logic"] = {"alerts_report": {k: rep_fusion[k] for k in ("detected", "n_fall", "false_alerts", "hours")}, "mine": {k: mine[k] for k in ("detected", "n_fall", "false_alerts", "hours")}, "identical": bool(same)}
if not same:
    NOTES.append("my per-recording evaluator differs from alerts_report for C1 on subjects 16-21 (see verification).")
# full-set consistency with alerts_report for two configs
for nm_, cfg in (("C1", CFG_C1), ("C7-like", {"a": ("mean", 0.87), "b": ("max", 0.7, 1.5)})):
    d_, f_, l_ = EV0.eval_all(cfg)
    rr = alerts_report(recs, alerts_dict(EV0, cfg), list(range(N)))
    mm = metrics(d_, f_, l_, G_ALL)
    sm = rr["detected"] == mm["detected"] and rr["false_alerts"] == mm["false_alerts"] and abs(rr["hours"] - mm["hours"]) < 1e-9
    out(f"  evaluator vs alerts_report on all 21 subjects ({nm_}): {mm['detected']}/{mm['n_fall']} FA {mm['false_alerts']} vs {rr['detected']}/{rr['n_fall']} FA {rr['false_alerts']}  identical {sm}")
    ver[f"evaluator_vs_alerts_report_{nm_}"] = bool(sm)
    if not sm:
        NOTES.append(f"evaluator differs from alerts_report on all 21 for {nm_}")
# C0
d0, f0, l0 = EV0.eval_all({"fsm_only": True})
m0 = metrics(d0, f0, l0, G_ALL)
b1 = json.loads((R / "b1_baselines.json").read_text()).get("FSM (still after impact)", {})
out(f"C0 original FSM rule (AI off): {m0['detected']}/{m0['n_fall']} FA {m0['false_alerts']} in {m0['hours']:.3f} h;  b1_baselines.json: {b1.get('detected')}/{b1.get('n_fall')} FA {b1.get('false_alerts')} in {b1.get('hours', float('nan')):.3f} h")
ver["C0_vs_b1_baselines"] = {"mine": [m0["detected"], m0["false_alerts"], m0["hours"]], "stored": [b1.get("detected"), b1.get("false_alerts"), b1.get("hours")]}

# ------------------------------------------------------------------ candidate grid
T_MEAN = sorted(set([round(x, 2) for x in np.arange(0.60, 0.951, 0.05)] + [0.87]))
TAU5 = (0.3, 0.4, 0.5, 0.6, 0.7)
T_MAX = (0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99)
TAU_MAX = (0.5, 0.7, 0.9)
T_MIN = (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9)
T_HI = (0.90, 0.93, 0.95, 0.97, 0.98, 0.99)
T_SINGLE = (0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99)
DEFAULTS = {"t": 0.87, "tau": 0.5, "vs": 0.8}


def rcost(x):
    if abs(x * 10 - round(x * 10)) < 1e-6:
        return 0
    if abs(x * 20 - round(x * 20)) < 1e-6:
        return 1
    return 2


CONFIGS = []     # each: dict(cand, params, a, hi, b, cost, nchg)


def add(cand, params, **kw):
    cost = sum(rcost(v) for v in params.values())
    nchg = sum(1 for k, v in params.items() if k in DEFAULTS and abs(v - DEFAULTS[k]) > 1e-9)
    CONFIGS.append(dict(cand=cand, params=params, cost=cost, nchg=nchg, **kw))


add("C0", {}, fsm_only=True)
add("C1", {"t": 0.87, "tau": 0.5}, a=("mean", 0.87), b=("mean", 0.5, 0.8))
for t in T_MEAN:
    for tau in TAU5:
        add("C2", {"t": t, "tau": tau}, a=("mean", t), b=("mean", tau, 0.8))
for t in T_MAX:
    for tau in TAU_MAX:
        add("C3", {"t": t, "tau": tau}, a=("max", t), b=("max", tau, 0.8))
for w in WEIGHTS:
    for t in T_MEAN:
        for tau in TAU5:
            add("C4", {"w": w, "t": t, "tau": tau}, a=(f"w{w}", t), b=(f"w{w}", tau, 0.8))
for t in T_MIN:
    for tau in TAU5:
        add("C5", {"t": t, "tau": tau}, a=("min", t), b=("mean", tau, 0.8))
for th in T_HI:
    add("C6", {"t_hi": th}, a=("mean", 0.87), hi=("max", th), b=("mean", 0.5, 0.8))
for tb in TAU_MAX:
    add("C7", {"tau_B": tb}, a=("mean", 0.87), b=("max", tb, 0.8))
for tb in TAU_MAX:
    for vs in VS_LIST:
        add("C7v", {"tau_B": tb, "vs": vs}, a=("mean", 0.87), b=("max", tb, vs))
for nm_, cid in (("mlp", "C8a"), ("cnn", "C8b")):
    for t in T_SINGLE:
        for tau in TAU5:
            add(cid, {"t": t, "tau": tau}, a=(nm_, t), b=(nm_, tau, 0.8))
NC = len(CONFIGS)
CAND_IDS = ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C7v", "C8a", "C8b"]
IDX = {c: np.array([i for i, g in enumerate(CONFIGS) if g["cand"] == c]) for c in CAND_IDS}
LABEL = {
    "C0": "AI off, original FSM rule",
    "C1": "A: mean>=0.87 | B: FSM still + mean6s>=0.5 (current)",
    "C2": "A: mean>=t | B: still + mean6s>=tau",
    "C3": "A: max(MLP,CNN)>=t | B: still + max6s>=tau",
    "C4": "A: w*MLP+(1-w)*CNN>=t | B: same score>=tau",
    "C5": "A: min(MLP,CNN)>=t | B: still + mean6s>=tau",
    "C6": "A: mean>=0.87 OR (max>=t_hi AND FSM in FREE_FALL/IMPACT) | B: still + mean6s>=0.5",
    "C7": "A: mean>=0.87 | B: still(var<0.8) + max(MLP,CNN)6s>=tau_B",
    "C7v": "C7 plus var_still in {0.8,1.5,2.5}",
    "C8a": "MLP alone: A: >=t | B: still + MLP6s>=tau",
    "C8b": "CNN alone: A: >=t | B: still + CNN6s>=tau",
}
out(f"\n{NC} configurations over {len(CAND_IDS)} candidate ids.  FSM B params {FSM_B}; support window = [alert-6 s, alert+1 s] of window end times (as run_fusion.py)")


def eval_grid(ev, only=None):
    DET = np.zeros((NC, N), np.int8); NFA = np.zeros((NC, N), np.int16); LAT = np.full((NC, N), np.nan)
    for i, g in enumerate(CONFIGS):
        if only is not None and i not in only:
            continue
        DET[i], NFA[i], LAT[i] = ev.eval_all(g)
    return DET, NFA, LAT


out("evaluating the grid on the saved scores...")
DET, NFA, LAT = eval_grid(EV0)
DS = DET.astype(float) @ ONEHOT            # (NC, NS) detections per subject
FS_ = NFA.astype(float) @ ONEHOT
NFALL_S = ISFALL.astype(float) @ ONEHOT
H_S = HOURS @ ONEHOT
out(f"  done ({time.time()-T0:.0f}s)")

# stress-test scores
out("stress test grids (MLP->0 on fall recordings, CNN->0 on fall recordings)...")
mlp_z = mlp0.copy(); mlp_z[SUBJ_FALLMASK] = 0.0
cnn_z = cnn0.copy(); cnn_z[SUBJ_FALLMASK] = 0.0
EVM = Ev(derive(mlp_z, cnn0)); EVC = Ev(derive(mlp0, cnn_z))
# sensitivity: the int8 CNN saturates at exactly 1.0 (~1 % of windows), so with MLP=0 'mean >= 0.5' passes on a float tie
CAP = 0.999
cnn_cap = cnn0.copy(); cnn_cap[SUBJ_FALLMASK] = np.minimum(cnn_cap[SUBJ_FALLMASK], CAP)
mlp_cap = mlp0.copy(); mlp_cap[SUBJ_FALLMASK] = np.minimum(mlp_cap[SUBJ_FALLMASK], CAP)
EVMK = Ev(derive(mlp_z, cnn_cap)); EVCK = Ev(derive(mlp_cap, cnn_z))
DETm, NFAm, LATm = eval_grid(EVM)
DETc, NFAc, LATc = eval_grid(EVC)
DSm = DETm.astype(float) @ ONEHOT
DSc = DETc.astype(float) @ ONEHOT
out(f"  done ({time.time()-T0:.0f}s)")

I_C1 = int(IDX["C1"][0]); I_C0 = int(IDX["C0"][0])
ACCEPT_FA = 1           # at most 1 false alert per 1.95 h-equivalent; training sets are never larger than the full data
SEL_NOTE = ("acceptance: FA_train <= 1 and det_train >= det(C1,train) - 1; objective max detections; ties -> lowest roundness cost "
            "(0: multiple of 0.1, 1: multiple of 0.05, 2: other), then fewest constants changed vs the current firmware, then fewest FA")


def select(cand, train_mask, objective="recall", fa_mode="abs1"):
    """fa_mode 'abs1': FA_train <= 1 (the rule as requested). 'c1plus1': FA_train <= FA(C1 on the same subjects) + 1
    (the PLAN's wording 'at most one more than C1'; extra variant because C1's full system already has 1 FA)."""
    idx = IDX[cand]
    if len(idx) == 1:
        return int(idx[0]), False
    det_tr = DS[idx][:, train_mask].sum(1)
    fa_tr = FS_[idx][:, train_mask].sum(1)
    ref = DS[I_C1][train_mask].sum()
    fa_lim = ACCEPT_FA if fa_mode == "abs1" else FS_[I_C1][train_mask].sum() + 1
    ok = (fa_tr <= fa_lim) & (det_tr >= ref - 1)
    cost = np.array([CONFIGS[i]["cost"] for i in idx]); nchg = np.array([CONFIGS[i]["nchg"] for i in idx])
    if objective == "recall":
        key = lambda j: (-det_tr[j], cost[j], nchg[j], fa_tr[j], j)
    else:   # stress-aware: maximise detections surviving a single-model failure, then recall
        sd = (DSm[idx][:, train_mask].sum(1) + DSc[idx][:, train_mask].sum(1))
        key = lambda j: (-sd[j], -det_tr[j], cost[j], nchg[j], fa_tr[j], j)
    if ok.any():
        j = min(np.flatnonzero(ok), key=key)
        return int(idx[j]), False
    j = min(range(len(idx)), key=lambda j: (fa_tr[j], -det_tr[j], cost[j], j))
    return int(idx[j]), True


def pstr(i):
    g = CONFIGS[i]
    return ",".join(f"{k}={v:g}" for k, v in g["params"].items()) or "-"


# ------------------------------------------------------------------ 1. grid / deploy configs
res = {c: {"label": LABEL[c], "n_configs": len(IDX[c])} for c in CAND_IDS}
ALLM = np.ones(NS, bool)
for c in CAND_IDS:
    i, fb = select(c, ALLM)
    g = CONFIGS[i]
    r = res[c]
    r["deploy_all21_selection"] = {"params": g["params"], "config": {k: g[k] for k in ("a", "hi", "b") if k in g}, "fallback_no_config_accepted": fb}
    r["deploy_all21_selection"]["groups"] = {"subjects_16_21": metrics(DET[i], NFA[i], LAT[i], G_1621),
                                             "all_21_optimistic_for_1_15": metrics(DET[i], NFA[i], LAT[i], G_ALL)}
    # path A only, event_report convention (comparable with the plan table)
    if g.get("a") and not g.get("hi"):
        e = event_report(recs, W, (EV0.S[g["a"][0]] >= g["a"][1]).astype(float), 0.5)
        r["deploy_all21_selection"]["path_A_only_event_report"] = {k: e[k] for k in ("detected", "n_fall", "false_alerts", "hours", "fa_per_h", "fa_upper95", "latency_median_s", "false_by_scenario")}
    # 30 s cooldown sensitivity (firmware has a 30 s cooldown; the base evaluation only merges alerts < 3 s apart)
    dd, ff, ll = EV0.eval_all(g, cooldown=30.0)
    r["deploy_all21_selection"]["with_30s_cooldown_all21"] = metrics(dd, ff, ll, G_ALL)
    r["_deploy_idx"] = i
    # stress on the deploy config
    r["stress_test"] = {"params": g["params"],
                        "baseline": {"subjects_16_21": metrics(DET[i], NFA[i], LAT[i], G_1621), "all_21": metrics(DET[i], NFA[i], LAT[i], G_ALL)},
                        "mlp_zeroed_on_falls": {"subjects_16_21": metrics(DETm[i], NFAm[i], LATm[i], G_1621), "all_21": metrics(DETm[i], NFAm[i], LATm[i], G_ALL)},
                        "cnn_zeroed_on_falls": {"subjects_16_21": metrics(DETc[i], NFAc[i], LATc[i], G_1621), "all_21": metrics(DETc[i], NFAc[i], LATc[i], G_ALL)}}
    dk1 = EVMK.eval_all(g); dk2 = EVCK.eval_all(g)
    r["stress_test"]["mlp_zeroed_other_capped_0.999_on_falls"] = {"all_21": metrics(*dk1, G_ALL), "subjects_16_21": metrics(*dk1, G_1621)}
    r["stress_test"]["cnn_zeroed_other_capped_0.999_on_falls"] = {"all_21": metrics(*dk2, G_ALL), "subjects_16_21": metrics(*dk2, G_1621)}
    r["deploy_all21_selection"]["acceptance_rule_met"] = (not fb)
    # frontier: best detections for each FA budget (in-sample, all 21)
    fr = {}
    for bud in (0, 1, 2, 3):
        okb = [k for k in IDX[c] if FS_[k].sum() <= bud]
        if okb:
            kb = min(okb, key=lambda k: (-DS[k].sum(), CONFIGS[k]["cost"], CONFIGS[k]["nchg"], k))
            fr[f"FA<={bud}"] = {"params": CONFIGS[kb]["params"], "detected": int(DS[kb].sum()), "false_alerts": int(FS_[kb].sum()),
                                "stress_mlp0_detected": int(DSm[kb].sum()), "stress_cnn0_detected": int(DSc[kb].sum())}
        else:
            fr[f"FA<={bud}"] = None
    r["frontier_all21_in_sample"] = fr
    # clean split: select on subjects 1-15, evaluate on 16-21
    tm = np.array([s <= 15 for s in SUBJS])
    j, fb2 = select(c, tm)
    r["select_on_1_15_test_on_16_21"] = {"params": CONFIGS[j]["params"], "fallback": fb2, "metrics_16_21": metrics(DET[j], NFA[j], LAT[j], G_1621),
                                         "metrics_16_21_stress_mlp0": metrics(DETm[j], NFAm[j], LATm[j], G_1621),
                                         "metrics_16_21_stress_cnn0": metrics(DETc[j], NFAc[j], LATc[j], G_1621)}
    # best stress recall among configs that satisfy the acceptance rule on ALL data (in-sample, for information)
    j2, fb3 = select(c, ALLM, "stress")
    r["stress_aware_selection_all21_in_sample"] = {"params": CONFIGS[j2]["params"], "fallback": fb3, "all_21": metrics(DET[j2], NFA[j2], LAT[j2], G_ALL),
                                                   "stress_mlp0_all21": metrics(DETm[j2], NFAm[j2], LATm[j2], G_ALL),
                                                   "stress_cnn0_all21": metrics(DETc[j2], NFAc[j2], LATc[j2], G_ALL)}

out("\n== 1. CANDIDATES (parameters selected on all 21 subjects by the acceptance rule; in-sample for the thresholds) ==")
out(f"   hours: subjects 16-21 = {HOURS[G_1621].sum():.3f} h, all 21 = {HOURS[G_ALL].sum():.3f} h  (alerts_report convention: fall recordings minus 11 s; event_report 'path A only' uses 1.9455 h)")
out(f"{'id':4s} {'params':26s} | {'subjects 16-21 (clean)':58s} | all 21 (optimistic for 1-15)")
for c in CAND_IDS:
    r = res[c]; d = r["deploy_all21_selection"]
    out(f"{c:4s} {pstr(r['_deploy_idx']):26s} | {fmt(d['groups']['subjects_16_21']):58s} | {fmt(d['groups']['all_21_optimistic_for_1_15'])}"
        + ("" if d["acceptance_rule_met"] else "   [no config meets the acceptance rule -> fewest-FA fallback]"))

# ------------------------------------------------------------------ 2. nested LOSO selection
out("\n== 2. NESTED leave-one-subject-out threshold selection (pooled over held-out subjects) ==")
out("   " + SEL_NOTE)
NEST = {}
for c in CAND_IDS:
    chosen = []; fbs = 0
    nd = np.zeros(N, np.int8); nf = np.zeros(N, np.int16); nl = np.full(N, np.nan)
    for h in SUBJS:
        tm = np.array([s != h for s in SUBJS])
        i, fb = select(c, tm)
        chosen.append(i); fbs += int(fb)
        m = REC_SUBJ == h
        nd[m] = DET[i][m]; nf[m] = NFA[i][m]; nl[m] = LAT[i][m]
    NEST[c] = (nd, nf, nl, chosen)
    freq = {}
    for i in chosen:
        freq[pstr(i)] = freq.get(pstr(i), 0) + 1
    res[c]["nested"] = {"groups": {"subjects_16_21": metrics(nd, nf, nl, G_1621), "all_21": metrics(nd, nf, nl, G_ALL)},
                        "selected_params_per_heldout_subject": {int(h): CONFIGS[i]["params"] for h, i in zip(SUBJS, chosen)},
                        "selected_params_frequency": dict(sorted(freq.items(), key=lambda kv: -kv[1])),
                        "folds_with_no_config_accepted": fbs, "selection_note": SEL_NOTE}
    # stress-aware nested (extra, not requested): objective = detections surviving single-model failure
    sd_ = np.zeros(N, np.int8); sm_ = np.zeros(N, np.int8); sc_ = np.zeros(N, np.int8); sf_ = np.zeros(N, np.int16); sl_ = np.full(N, np.nan)
    ch2 = []
    for h in SUBJS:
        tm = np.array([s != h for s in SUBJS])
        i, fb = select(c, tm, "stress"); ch2.append(i)
        m = REC_SUBJ == h
        sd_[m] = DET[i][m]; sf_[m] = NFA[i][m]; sl_[m] = LAT[i][m]; sm_[m] = DETm[i][m]; sc_[m] = DETc[i][m]
    freq2 = {}
    for i in ch2:
        freq2[pstr(i)] = freq2.get(pstr(i), 0) + 1
    res[c]["nested_stress_aware_extra"] = {
        "groups": {"subjects_16_21": metrics(sd_, sf_, sl_, G_1621), "all_21": metrics(sd_, sf_, sl_, G_ALL)},
        "stress_mlp0_all21": metrics(sm_, sf_, sl_, G_ALL), "stress_cnn0_all21": metrics(sc_, sf_, sl_, G_ALL),
        "stress_mlp0_16_21": metrics(sm_, sf_, sl_, G_1621), "stress_cnn0_16_21": metrics(sc_, sf_, sl_, G_1621),
        "selected_params_frequency": dict(sorted(freq2.items(), key=lambda kv: -kv[1])),
        "objective": "acceptance rule, then maximise (detections with MLP zeroed + detections with CNN zeroed) on the 20 training subjects, then recall"}
    # nested per-subject arrays for the bootstrap
    NEST[c] = NEST[c] + ((nd.astype(float) @ ONEHOT, nf.astype(float) @ ONEHOT),)

out(f"{'id':4s} {'nested, subjects 16-21':58s} | {'nested, all 21':58s} | most frequent selected params")
for c in CAND_IDS:
    n = res[c]["nested"]
    top = list(n["selected_params_frequency"].items())[:2]
    out(f"{c:4s} {fmt(n['groups']['subjects_16_21']):58s} | {fmt(n['groups']['all_21']):58s} | {top}")

# ---- extra: relaxed false-alert limit "at most 1 more than C1" (C1's full system already has 1 FA, so FA<=1 leaves no room for C6/C7)
out("\n== 2b. (extra) NESTED with relaxed FA limit: FA_train <= FA(C1, same subjects) + 1  ==")
NEST2 = {}
for c in CAND_IDS:
    chosen = []; fbs = 0
    nd = np.zeros(N, np.int8); nf = np.zeros(N, np.int16); nl = np.full(N, np.nan); nm_ = np.zeros(N, np.int8); nc_ = np.zeros(N, np.int8)
    for h in SUBJS:
        tm = np.array([s != h for s in SUBJS])
        i, fb = select(c, tm, "recall", "c1plus1")
        chosen.append(i); fbs += int(fb)
        m = REC_SUBJ == h
        nd[m] = DET[i][m]; nf[m] = NFA[i][m]; nl[m] = LAT[i][m]; nm_[m] = DETm[i][m]; nc_[m] = DETc[i][m]
    freq = {}
    for i in chosen:
        freq[pstr(i)] = freq.get(pstr(i), 0) + 1
    iA, fbA = select(c, ALLM, "recall", "c1plus1")
    res[c]["relaxed_fa_c1_plus_1"] = {
        "nested_groups": {"subjects_16_21": metrics(nd, nf, nl, G_1621), "all_21": metrics(nd, nf, nl, G_ALL)},
        "nested_stress_mlp0_all21_detected": int(nm_.sum()), "nested_stress_cnn0_all21_detected": int(nc_.sum()),
        "selected_params_frequency": dict(sorted(freq.items(), key=lambda kv: -kv[1])), "folds_with_no_config_accepted": fbs,
        "deploy_all21_params": CONFIGS[iA]["params"], "deploy_all21_fallback": fbA,
        "deploy_all21": metrics(DET[iA], NFA[iA], LAT[iA], G_ALL), "deploy_16_21": metrics(DET[iA], NFA[iA], LAT[iA], G_1621),
        "deploy_stress_mlp0_all21": metrics(DETm[iA], NFAm[iA], LATm[iA], G_ALL), "deploy_stress_cnn0_all21": metrics(DETc[iA], NFAc[iA], LATc[iA], G_ALL)}
    NEST2[c] = (nd, nf, nl, chosen, (nd.astype(float) @ ONEHOT, nf.astype(float) @ ONEHOT))
    r2 = res[c]["relaxed_fa_c1_plus_1"]
    out(f"{c:4s} nested all21 {fmt(r2['nested_groups']['all_21'])} | stress MLP=0 {r2['nested_stress_mlp0_all21_detected']:3d} CNN=0 {r2['nested_stress_cnn0_all21_detected']:3d} "
        f"| fallback folds {fbs:2d} | {list(r2['selected_params_frequency'].items())[:2]}")

# ------------------------------------------------------------------ paired bootstrap over subjects
out("\n== paired bootstrap over the 21 subjects (1000 resamples, seed 20261102) vs C1; nested held-out outcomes ==")
rng = np.random.default_rng(20261102)
BOOT = rng.integers(0, NS, size=(1000, NS))
d1, f1 = NEST["C1"][4]
boot = {}
boot2 = {}
for c in CAND_IDS:
    if c == "C1":
        continue
    for label, src, store in (("", NEST, boot), ("(relaxed FA<=C1+1) ", NEST2, boot2)):
        dcx, fcx = src[c][4]
        nfs_ = NFALL_S
        drx = np.array([(dcx[b].sum() - d1[b].sum()) / nfs_[b].sum() for b in BOOT])
        dfx = np.array([fcx[b].sum() - f1[b].sum() for b in BOOT])
        dfhx = np.array([(fcx[b].sum() - f1[b].sum()) / H_S[b].sum() for b in BOOT])
        store[c] = {"recall_diff_mean": float(drx.mean()), "recall_diff_ci95": [float(np.percentile(drx, 2.5)), float(np.percentile(drx, 97.5))],
                    "fa_count_diff_mean": float(dfx.mean()), "fa_count_diff_ci95": [float(np.percentile(dfx, 2.5)), float(np.percentile(dfx, 97.5))],
                    "fa_per_h_diff_mean": float(dfhx.mean()), "fa_per_h_diff_ci95": [float(np.percentile(dfhx, 2.5)), float(np.percentile(dfhx, 97.5))],
                    "frac_resamples_recall_better": float((drx > 0).mean()), "frac_resamples_recall_worse": float((drx < 0).mean()),
                    "point_recall_diff": float((dcx.sum() - d1.sum()) / nfs_.sum()), "point_fa_diff": int(fcx.sum() - f1.sum())}
        if True:
            b_ = store[c]
            out(f"  {c:4s} {label}d-recall {b_['point_recall_diff']:+.3f} (95% {b_['recall_diff_ci95'][0]:+.3f}..{b_['recall_diff_ci95'][1]:+.3f})   d-FA {b_['point_fa_diff']:+d} (95% {b_['fa_count_diff_ci95'][0]:+.1f}..{b_['fa_count_diff_ci95'][1]:+.1f})")

# ------------------------------------------------------------------ 3. stress test
out("\n== 3. STRESS TEST: 'one model fails' (fall recordings only; ADL scores unchanged), deploy params from section 1 ==")
out(f"{'id':4s} {'params':26s} | {'baseline':>9s} | {'MLP=0':>9s} | {'CNN=0':>9s}   (detections of 104; subjects 16-21 of 31 in brackets)")
for c in CAND_IDS:
    s = res[c]["stress_test"]
    out(f"{c:4s} {pstr(res[c]['_deploy_idx']):26s} | {s['baseline']['all_21']['detected']:3d} [{s['baseline']['subjects_16_21']['detected']:2d}] | "
        f"{s['mlp_zeroed_on_falls']['all_21']['detected']:3d} [{s['mlp_zeroed_on_falls']['subjects_16_21']['detected']:2d}] | "
        f"{s['cnn_zeroed_on_falls']['all_21']['detected']:3d} [{s['cnn_zeroed_on_falls']['subjects_16_21']['detected']:2d}]")
out("\n   sensitivity: same, but the surviving model is capped at 0.999 on the fall windows (removes the CNN==1.0 float tie)")
for c in CAND_IDS:
    s = res[c]["stress_test"]
    out(f"{c:4s} MLP=0: {s['mlp_zeroed_other_capped_0.999_on_falls']['all_21']['detected']:3d}   CNN=0: {s['cnn_zeroed_other_capped_0.999_on_falls']['all_21']['detected']:3d}")
out("\n   frontier (in-sample, all 21): best detections for a false-alert budget  [det/FA, stress MLP=0 / CNN=0 detections]")
for c in CAND_IDS:
    fr = res[c]["frontier_all21_in_sample"]
    cells = []
    for b in (0, 1, 2, 3):
        e = fr[f"FA<={b}"]
        cells.append("-" if e is None else f"{e['detected']}/{e['false_alerts']} [{e['stress_mlp0_detected']}/{e['stress_cnn0_detected']}]")
    out(f"{c:4s} FA<=0 {cells[0]:16s} FA<=1 {cells[1]:16s} FA<=2 {cells[2]:16s} FA<=3 {cells[3]:16s}")
out("\n   stress-aware variants (extra): nested selection maximising the stress detections  [all 21 held-out]")
out(f"{'id':4s} {'nested recall':>13s} {'FA':>3s} | {'MLP=0':>6s} | {'CNN=0':>6s} | most frequent params")
for c in CAND_IDS:
    e = res[c]["nested_stress_aware_extra"]
    out(f"{c:4s} {e['groups']['all_21']['detected']:8d}/104 {e['groups']['all_21']['false_alerts']:3d} | {e['stress_mlp0_all21']['detected']:6d} | {e['stress_cnn0_all21']['detected']:6d} | {list(e['selected_params_frequency'].items())[:2]}")
out("\n   clean split: thresholds selected on subjects 1-15 only, evaluated on subjects 16-21 (31 falls)")
for c in CAND_IDS:
    e = res[c]["select_on_1_15_test_on_16_21"]
    out(f"{c:4s} {','.join(f'{k}={v:g}' for k, v in e['params'].items()) or '-':26s} {fmt(e['metrics_16_21'])} | MLP=0 {e['metrics_16_21_stress_mlp0']['detected']:2d}  CNN=0 {e['metrics_16_21_stress_cnn0']['detected']:2d}")

# ------------------------------------------------------------------ headline table
out("\n== HEADLINE (recall of 104 / false alerts / nested / stress) ==")
out(f"{'id':4s} {'params(all-21 selection)':26s} {'rec 21':>7s} {'FA':>3s} {'rec 16-21':>9s} {'FA':>3s} | {'nested rec':>10s} {'FA':>3s} | {'MLP=0':>5s} {'CNN=0':>5s}")
for c in CAND_IDS:
    d = res[c]["deploy_all21_selection"]["groups"]; n = res[c]["nested"]["groups"]["all_21"]; s = res[c]["stress_test"]
    out(f"{c:4s} {pstr(res[c]['_deploy_idx']):26s} {d['all_21_optimistic_for_1_15']['detected']:4d}/104 {d['all_21_optimistic_for_1_15']['false_alerts']:3d} "
        f"{d['subjects_16_21']['detected']:6d}/31 {d['subjects_16_21']['false_alerts']:3d} | {n['detected']:7d}/104 {n['false_alerts']:3d} | "
        f"{s['mlp_zeroed_on_falls']['all_21']['detected']:5d} {s['cnn_zeroed_on_falls']['all_21']['detected']:5d}")

# ------------------------------------------------------------------ notes + save
NOTES += [
    "No training, no export_final.py, no firmware/serial access: only saved LOSO scores (MLP & CNN, the 3 seeds averaged exactly as run_fusion.py) and evalx.simulate_fsm.",
    "System metrics (path A union path B) use the alerts_report convention (the one run_fusion.py used for the fusion rows): a fall is detected if an alert falls in [centre-1 s, centre+8 s]; alerts outside [centre-3 s, centre+8 s] on fall recordings and all alerts on ADL recordings are false; alerts < 3 s apart merge (evalx.merge_fires). Exposure hours therefore are about 1.80 h (fall recordings minus 11 s each), not the 1.9455 h of event_report; the 'path_A_only_event_report' entries use event_report (1.9455 h) and are the numbers comparable to the PLAN table and fusion.json.",
    "Path A alert time = end of the scored window; path B alert time = FSM 'still' alert time (impact + settle 1.5 s + window 2 s); B is kept only if the max AI support score over window end times in [alert-6 s, alert+1 s] >= tau (same as run_fusion.py). Only FSM 'still' alerts are used (no ai_promote path), as in run_fusion.py.",
    "FSM params for path B are fixed (settle 1500, window 2000, var_still 0.8, var_motion 4.0), tuned on subjects 1-15; subjects 16-21 are therefore the clean group, 'all 21' is slightly optimistic for path B on subjects 1-15. For C7v var_still is 0.8/1.5/2.5 with var_motion kept at 4.0.",
    "C0 = original firmware FSM (settle 200, window 3000, var_still 0.08, var_motion 0.8), no AI. C7 = tau_B only (var_still fixed 0.8); C7v = tau_B and var_still. C8a/C8b = MLP alone / CNN alone.",
    "C6 'FSM in FREE_FALL/IMPACT' flag: evalx.simulate_fsm does not expose its state, so run_final_config.py contains a verbatim copy of its loop (fsm_trace) that records the state; its alerts were checked equal to simulate_fsm. The flag for a window is the FSM state at the window's last sample. The A' trigger is not subject to the FSM cooldown in this evaluation (only the 3 s merge).",
    "Acceptance rule used in the nested/deploy selection: FA on the training subjects <= 1 (1 per 1.95 h-equivalent; training sets are never larger than the full data) and detections >= detections of C1 (fixed 0.87/0.5) on the same subjects minus 1 event; maximise detections; ties -> roundest thresholds (cost 0 multiple of 0.1, 1 multiple of 0.05, 2 other), then fewest constants changed vs the current firmware (t 0.87, tau 0.5, var_still 0.8), then fewest FA. If no config is accepted in a fold the config with the fewest FA is used (counted in folds_with_no_config_accepted). C4 also selects the weight w. Single-config candidates (C0, C1) are fixed.",
    "Grids were not subsampled: C2/C4 t in {0.60..0.95 step 0.05, plus 0.87}, tau in {0.3..0.7}; C3 t in {0.90,0.92,0.94,0.95,0.96,0.97,0.98,0.99}, tau in {0.5,0.7,0.9}; C5 min t in {0.5..0.9}; C6 t_hi in {0.90..0.99}; C7 tau_B in {0.5,0.7,0.9}; C8 t in {0.80..0.99}, tau in {0.3..0.7}.",
    "Stress test: windows of fall recordings get MLP (then CNN) score 0 before forming mean/max/min/weighted scores; ADL recordings unchanged; parameters are the 'deploy_all21_selection' ones (selected without stress). The stress-aware nested selection is an extra (not requested) to show what choosing tau_B/t_hi with the stress objective would give.",
    "Bootstrap: resamples the 21 subjects (1000, seed 20261102, same resample indices for every candidate) and recomputes pooled nested recall and FA for candidate minus C1; with only 21 subjects (and 104 falls) the intervals are wide. A subject-level bootstrap does not capture seed or domain-shift uncertainty.",
    "HIFD scores are out-of-sample LOSO, but the model hyper-parameters were chosen on the same data in earlier phases; the real-wrist disagreement between MLP and CNN seen on 2026-11-02 cannot be measured here (HIFD models almost always agree), only the cost (extra false alerts) of rules that handle disagreement.",
    "C1 (mean>=0.87, tau 0.5) is not 'nested': its 0.87 was chosen on the pooled LOSO scores in run_fusion.py, so its nested row is just the fixed config (the other candidates pay the selection cost, C1 does not).",
    "Stress-test artefact: the int8 CNN output is exactly 1.0 on ~1 % of windows, so with MLP=0 the path-B rule 'mean >= 0.5' still passes on the float tie 0.5*1.0 >= 0.5 (C1 keeps 45/104 instead of ~0). The 'capped 0.999' sensitivity removes it; treat the uncapped C1/C2/C4/C5 MLP=0 number as knife-edge, not robustness.",
    "With the requested absolute rule (FA<=1) C1's full system (path A + B) already uses the whole budget: its single FA is a clap (path B). Candidates C3, C6, C7, C7v, C8a, C8b cannot meet 'FA<=1 and detections >= C1-1' (see 'acceptance_rule_met' / 'folds_with_no_config_accepted'); they then use the fewest-FA fallback and are flagged. The PLAN's wording ('at most one more than C1') is therefore also provided as an extra variant 'relaxed_fa_c1_plus_1' (FA_train <= FA(C1 on the same subjects) + 1) with its own nested result and bootstrap; 'frontier_all21_in_sample' lists the best detections per FA budget 0..3.",
    "The plan's table quotes C1 as 99/104 with 0 FA: that is path A only (event_report, 1.9455 h). The full C1 system (A + B) is 102/104 with 1 FA in 1.801 h on the same scores - path B rescues 3 falls and costs 1 false alert (clap).",
    "30 s cooldown sensitivity: base evaluation counts A then B alerts > 3 s apart as two alerts (conservative for FA); the firmware's 30 s cooldown would merge them. 'with_30s_cooldown_all21' reports the effect.",
]
for c in CAND_IDS:
    res[c].pop("_deploy_idx", None)
final = {"meta": {"script": "tools/ai_lab/run_final_config.py", "seeds_averaged": {"mlp": nm, "cnn": nc}, "n_recordings": N, "n_fall": int(ISFALL.sum()),
                  "windows": len(W), "fsm_path_B": FSM_B, "fsm_original_C0": FSM_ORIG, "var_still_values": list(VS_LIST),
                  "hours_system_all21": float(HOURS.sum()), "hours_system_16_21": float(HOURS[G_1621].sum()),
                  "bootstrap": {"resamples": 1000, "seed": 20261102, "unit": "subject"}, "acceptance_fa": ACCEPT_FA,
                  "runtime_s": round(time.time() - T0, 1)},
         "verification": ver, "candidates": res, "bootstrap_vs_C1_nested": boot,
         "bootstrap_vs_C1_nested_relaxed_fa_c1_plus_1": boot2,
         "grid_all_configs_in_sample": [
             {"cand": g["cand"], "params": g["params"], "all21": {"detected": int(DS[i].sum()), "false_alerts": int(FS_[i].sum())},
              "s16_21": {"detected": int(DET[i][G_1621].sum()), "false_alerts": int(NFA[i][G_1621].sum())},
              "stress_mlp0_all21_detected": int(DSm[i].sum()), "stress_cnn0_all21_detected": int(DSc[i].sum())}
             for i, g in enumerate(CONFIGS)],
         "notes": NOTES}
(R / "final_config.json").write_text(json.dumps(conv(final), indent=1), encoding="utf-8")
out(f"\nwrote {R / 'final_config.json'}  ({time.time()-T0:.0f}s)")
(R / "log_final_config.txt").write_text("\n".join(LOG), encoding="utf-8")
