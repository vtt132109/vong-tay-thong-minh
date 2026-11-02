#!/usr/bin/env python3
"""Offline re-scoring of the on-device live logs (step F2 of the final-config plan).

Input : dataset/device_logs/2026-11-02/live{1,3,5}.log, written by tools/live_ai.py from the USB serial log.
Output: dataset/ai_results/device_trials.json + a compact table on stdout.

What the logs contain
  * one line per AI window (every 0.5 s on the chip) -- but the firmware only logs a window when p > 0.2, or as a
    5 s heartbeat.  Each logged line gives p = (MLP + CNN)/2 (3 decimals) and MLP / CNN (2 decimals).
  * [FSM] transitions and, at the end of every IMPACT observation, `impact variance=.. aiMax6s=.. ai=0|1`.
    aiMax6s is the firmware's own max of the *mean* p over the last 12 windows (6 s) -- exact ground truth
    for any rule that is built on the mean.

Hard facts used for the "unlogged windows" bound
  * an unlogged window has p <= 0.2  =>  MLP + CNN <= 0.4  =>  max(MLP, CNN) <= 0.4, min <= 0.2, mean <= 0.2,
    w*MLP + (1-w)*CNN <= 0.4*max(w, 1-w).  Any rule/threshold above these bounds is *conclusive* on the unlogged
    windows; at or below them the verdict is reported as inconclusive ('?') and never counted as a catch.
  * CAVEAT, measured, not assumed: the assumption "unlogged => p <= 0.2" is NOT airtight.  In live5 (fall #2) the
    firmware reports aiMax6s = 0.69 while the logged windows in the same 6 s have mean <= 0.60: a window with mean
    0.69 was never logged (dropped serial line / log rate-limit).  Such a window is detected here by comparing
    aiMax6s with the rebuilt ring maximum and added as a 'hidden' window with mean = aiMax6s and an unknown
    MLP/CNN split.  A dropped window that is NOT the ring maximum cannot be detected, so every "conclusive"
    statement below is conditional on that.

How the firmware decides (src/fsm.cpp, src/ai_model.cpp) and what is replayed here
  * path A: AI window fires (aiFall) while state is IDLE/FREE_FALL/IMPACT, 30 s cooldown after an A trigger
    -> COUNTDOWN straight away.  The cooldown is replayed per candidate in chronological order, so an early A
    trigger can suppress A on the next fall (this happens in live5: fall #1 triggers at 25.0 s, falls #2/#3
    are within 30 s).  Results are shown with the cooldown (what the firmware would do in this session) and
    'isolated' (each fall as if it were alone).
  * path B: at the end of the IMPACT observation (settle 1.5 s + 2 s window in AI mode): variance < var_still
    (0.8) -> alarm iff the AI support over the last 6 s holds, else IDLE; variance > 4.0 -> IDLE; in between ->
    extend once (second observation) and decide again.  The logged variances are reused for every candidate,
    so only the support test changes.  var_still in {1.5, 2.5} only reuses those measured variances.
  * live1 was recorded with the AI alarm mode OFF (ai=0): the FSM then ran the legacy rule (window 3 s from
    0.2 s, variance thresholds 0.08/0.8), so its variance (111) is not what AI mode would have measured.  The
    model outputs in live1 are real, so path A is replayed as a counterfactual (path A does not depend on the FSM
    mode), but live1 is flagged non-informative for the current firmware and for path B.

Everything is a replay of logged numbers: no serial port, no firmware, no training.
Run: .venv-ds/Scripts/python.exe tools/ai_lab/device_log_rescore.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

from scipy.stats import chi2

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "dataset" / "device_logs" / "2026-11-02"
OUT = ROOT / "dataset" / "ai_results" / "device_trials.json"
LOGS = ["live1", "live3", "live5"]

# ----------------------------------------------------------------------------------------------- constants
P_TOL = 0.0005        # printed p has 3 decimals
MC_TOL = 0.005        # printed MLP / CNN / aiMax6s have 2 decimals
UNLOGGED_P = 0.2      # firmware logs a window when p > 0.2 (or heartbeat)
UNLOGGED_SUM = 2 * UNLOGGED_P   # MLP + CNN of an unlogged window
RING_S = 6.0          # aiMax6s ring: 12 windows
GAP_S = 0.75          # gap between logged windows that could hide an unlogged one (cadence 0.5 s, host jitter)
COOLDOWN_S = 30.0     # AI_ALERT_COOLDOWN_MS
MOTION_VAR = 4.0      # AI_MOTION_VAR
STILL_VAR = 0.8       # AI_STILL_VAR
A_ALLOWED = {"IDLE", "FREE_FALL", "IMPACT"}
IMPACT_STATES = {"FREE_FALL", "IMPACT"}
TRIAL_PAD_BEFORE = 1.5
IDLE_PAD_BEFORE = 2.0
IDLE_PAD_AFTER = 3.0

# What each detected event is.  Order = chronological order inside the log.  Labels come from the README of the
# log folder (the operator's notes); everything else is derived from the logs.
TRIAL_META = {
    "live1#1": dict(label="fall", counts=True, informative=False,
                    note="AI alarm mode OFF (ai=0); strong continued motion, var 111 (legacy 3 s window)"),
    "live1#2": dict(label="post-fall motion (not labelled as a fall)", counts=False, informative=False,
                    note="shortly after live1#1, ai=0; reported as a possible-false-alarm probe only"),
    "live3#1": dict(label="fall", counts=True, informative=True,
                    note="fall, lying still; MLP 0.97 / CNN 0.15 (README)"),
    "live5#1": dict(label="fall", counts=True, informative=True, note="MLP 1.00 / CNN 1.00 (README)"),
    "live5#2": dict(label="fall", counts=True, informative=True, note="MLP 0.17 / CNN 1.00, still moving (README)"),
    "live5#3": dict(label="fall", counts=True, informative=True, note="MLP 0.86 / CNN 0.28, lying still (README)"),
}

RE_WIN = re.compile(r"^\s*(\d+(?:\.\d+)?)s p=([0-9.]+) \[[# ]*\] mlp ([0-9.]+) cnn ([0-9.]+) thr ([0-9.]+) (\w+)")
RE_TR = re.compile(r"^\s*(\d+(?:\.\d+)?)s \[FSM\] (\w+) -> (\w+) \((.*)\)\s*$")
RE_VAR = re.compile(r"^\s*(\d+(?:\.\d+)?)s \[FSM\] impact variance=([0-9.]+) samples=(\d+) aiMax6s=([0-9.]+) ai=(\d)")
RE_TRIG = re.compile(r"^\s*(\d+(?:\.\d+)?)s \[FSM\] AI trigger p=([0-9.]+) \(mlp ([0-9.]+) cnn ([0-9.]+)\)")
RE_ALERT = re.compile(r"^\s*(\d+(?:\.\d+)?)s \[ALERT\] type=(\d+) reason=(.*)$")
RE_BTN = re.compile(r"^\s*(\d+(?:\.\d+)?)s \[BTN\] (short press|long press)(.*)$")


# ----------------------------------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96):
    """Same formula as tools/ai_lab/evalx.wilson."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def poisson_upper(k: int, hours: float, conf: float = 0.95, one_sided: bool = False) -> float:
    """k=0 -> 3.69/h two-sided (evalx.poisson_upper convention) or 3.00/h one-sided."""
    if hours <= 0:
        return float("nan")
    tail = (1 - conf) if one_sided else (1 - conf) / 2
    return float(chi2.ppf(1 - tail, 2 * (k + 1)) / 2 / hours)


def _evalx_crosscheck():
    try:
        sys.path.insert(0, str(ROOT))
        from tools.ai_lab import evalx  # noqa: WPS433
    except Exception as exc:  # evalx pulls the whole data stack; fine to skip
        return f"skipped ({type(exc).__name__})"
    ok = all(abs(a - b) < 1e-9 for (k, n) in [(3, 5), (4, 5), (0, 4), (5, 5)] for a, b in zip(wilson(k, n), evalx.wilson(k, n)))
    ok = ok and abs(poisson_upper(1, 1.95) - evalx.poisson_upper(1, 1.95)) < 1e-9
    return "match" if ok else "MISMATCH"


# ----------------------------------------------------------------------------------------------- parsing
def parse_log(name: str):
    events = []
    state = "IDLE"
    for idx, raw in enumerate((LOG_DIR / f"{name}.log").read_text(encoding="utf-8", errors="replace").splitlines()):
        m = RE_WIN.match(raw)
        if m:
            events.append(dict(type="win", idx=idx, t=float(m[1]), p=float(m[2]), mlp=float(m[3]), cnn=float(m[4]),
                               thr=float(m[5]), label=m[6], state=state, kind="logged"))
            continue
        m = RE_TR.match(raw)
        if m:
            events.append(dict(type="tr", idx=idx, t=float(m[1]), frm=m[2], to=m[3], reason=m[4]))
            state = m[3]
            continue
        m = RE_VAR.match(raw)
        if m:
            events.append(dict(type="var", idx=idx, t=float(m[1]), var=float(m[2]), samples=int(m[3]),
                               aimax6s=float(m[4]), ai=int(m[5])))
            continue
        m = RE_TRIG.match(raw)
        if m:
            events.append(dict(type="trig", idx=idx, t=float(m[1]), p=float(m[2]), mlp=float(m[3]), cnn=float(m[4])))
            continue
        m = RE_ALERT.match(raw)
        if m:
            events.append(dict(type="alert", idx=idx, t=float(m[1]), alert=int(m[2]), reason=m[3]))
            continue
        m = RE_BTN.match(raw)
        if m:
            events.append(dict(type="btn", idx=idx, t=float(m[1]), what=m[2].strip() + m[3]))
    # States occupied while a window's aiFall stays valid (until the next inference, 0.5 s).
    for i, ev in enumerate(events):
        if ev["type"] != "win":
            continue
        st = {ev["state"]}
        for nxt in events[i + 1:]:
            if nxt["t"] > ev["t"] + 0.5:
                break
            if nxt["type"] == "tr":
                st.add(nxt["to"])
        ev["states"] = st
    return events


def build_trials(name: str, events):
    trials = []
    cur = None
    last_closed = None
    for ev in events:
        if ev["type"] == "tr":
            if cur is None and ev["frm"] == "IDLE" and ev["to"] in ("FREE_FALL", "IMPACT"):
                if last_closed is not None and last_closed["close_kind"] == "FF_TIMEOUT" and ev["t"] - last_closed["t_close"] < 1.0:
                    cur = last_closed          # free-fall that timed out and an impact right after = one event
                    trials.pop()
                    cur["t_close"] = None
                else:
                    cur = dict(log=name, t_open=ev["t"], idx_open=ev["idx"], evals=[], trig=None)
            elif cur is not None and ev["frm"] in IMPACT_STATES and ev["to"] not in IMPACT_STATES:
                cur.update(t_close=ev["t"], idx_close=ev["idx"], close_to=ev["to"], close_reason=ev["reason"],
                           close_kind="FF_TIMEOUT" if ev["frm"] == "FREE_FALL" else "IMPACT_END")
                trials.append(cur)
                last_closed = cur
                cur = None
        elif ev["type"] == "var" and cur is not None:
            cur["evals"].append(dict(t=ev["t"], idx=ev["idx"], var=ev["var"], samples=ev["samples"],
                                     aimax6s=ev["aimax6s"], ai=ev["ai"]))
        elif ev["type"] == "trig" and cur is not None:
            cur["trig"] = ev
    if cur is not None:   # log ended inside an event
        cur.update(t_close=events[-1]["t"], idx_close=events[-1]["idx"], close_to="(log end)", close_reason="",
                   close_kind="IMPACT_END")
        trials.append(cur)
    prev_close = -1e9
    for k, tr in enumerate(trials, 1):
        tr["id"] = f"{name}#{k}"
        tr["span_start"] = max(prev_close, tr["t_open"] - TRIAL_PAD_BEFORE)
        tr["span_end"] = tr["t_close"]
        prev_close = tr["t_close"]
    return trials


# ----------------------------------------------------------------------------------------------- window intervals
def _clip(lo, hi):
    return (max(0.0, lo), min(1.0, hi))


def win_interval(w, rule, param=None):
    """(lo, hi) of the rule statistic for one window.  logged: exact up to print rounding;
    hidden: only the mean is known (= aiMax6s); unlogged: only mean <= 0.2 is known."""
    kind = w["kind"]
    a = max(param, 1 - param) if rule == "wmean" else None
    b = (1 - a) if a is not None else None
    if kind == "logged":
        m, c, p = w["mlp"], w["cnn"], w["p"]
        mlo, mhi, clo, chi = m - MC_TOL, m + MC_TOL, c - MC_TOL, c + MC_TOL
        plo, phi = p - P_TOL, p + P_TOL
        # MLP + CNN = 2p gives extra constraints on both
        mlo2, mhi2 = max(mlo, 2 * plo - chi), min(mhi, 2 * phi - clo)
        clo2, chi2_ = max(clo, 2 * plo - mhi), min(chi, 2 * phi - mlo)
        if mlo2 <= mhi2:
            mlo, mhi = mlo2, mhi2
        if clo2 <= chi2_:
            clo, chi = clo2, chi2_
        mlo, mhi = _clip(mlo, mhi)
        clo, chi = _clip(clo, chi)
        if rule == "mean":
            return _clip(plo, phi)
        if rule == "max":
            return _clip(max(mlo, clo), max(mhi, chi))
        if rule == "min":
            return _clip(min(mlo, clo), min(mhi, chi))
        if rule == "wmean":     # param = weight of the MLP
            return _clip(param * mlo + (1 - param) * clo, param * mhi + (1 - param) * chi)
        if rule == "mlp":
            return (mlo, mhi)
        if rule == "cnn":
            return (clo, chi)
    elif kind == "hidden":      # only mean h known, split unknown
        h = w["h"]
        s_lo, s_hi = 2 * (h - MC_TOL), 2 * (h + MC_TOL)
        if rule == "mean":
            return _clip(h - MC_TOL, h + MC_TOL)
        if rule == "max":
            return _clip(h - MC_TOL, s_hi)
        if rule == "min":
            return _clip(s_lo - 1, h + MC_TOL)
        if rule == "wmean":
            x_hi, x_lo = min(1.0, s_hi), min(1.0, s_lo)
            return _clip(b * x_lo + a * (s_lo - x_lo), a * x_hi + b * (s_hi - x_hi))
        if rule in ("mlp", "cnn"):
            return _clip(s_lo - 1, s_hi)
    elif kind == "unlogged":    # MLP + CNN <= S
        s = w.get("S", UNLOGGED_SUM)
        if rule in ("mean", "min"):
            return (0.0, s / 2)
        if rule in ("max", "mlp", "cnn"):
            return (0.0, s)
        if rule == "wmean":
            return (0.0, s * a)
    raise ValueError((kind, rule))


def eligible(w, req):
    """True / False / 'unknown' for path A (state in IDLE/FREE_FALL/IMPACT, and `req` if the term needs it)."""
    st = w.get("states")
    if st is None:
        return True if req is None else "unknown"
    if not (st & A_ALLOWED):
        return False
    if req is not None and not (st & req):
        return False
    return True


def any_ge(windows, terms, tmin=-1e9):
    """Path A over a window list: OR of terms [(rule, param, thr, state_req)].  Returns (verdict, t_first, via)."""
    best, t_first, via = "no", None, None
    for term in terms:
        rule, param, thr, req = term
        for w in sorted(windows, key=lambda x: x["t"]):
            if w["t"] <= tmin:
                continue
            el = eligible(w, req)
            if el is False:
                continue
            lo, hi = win_interval(w, rule, param)
            if lo >= thr and el is True:
                if best != "yes" or w["t"] < t_first:
                    best, t_first, via = "yes", w["t"], f"{rule}>={thr}"
                break
            if hi >= thr and best == "no":
                best, t_first, via = "unk", w["t"], f"{rule}>={thr}"
    return best, t_first, via


def pseudo_unlogged(times, lo_edge, hi_edge, S=UNLOGGED_SUM):
    """One pseudo 'unlogged' window if any gap between logged windows could hide a window."""
    ts = sorted([lo_edge] + [t for t in times if lo_edge < t <= hi_edge] + [hi_edge])
    for a, b in zip(ts, ts[1:]):
        if b - a > GAP_S:
            return [dict(kind="unlogged", t=a + 0.5, S=S, states=None)]
    return []


# ----------------------------------------------------------------------------------------------- ring / evals
def build_ring(ev, wins):
    T = ev["t"]
    ring = [w for w in wins if w["idx"] < ev["idx"] and w["t"] > T - RING_S + 1e-9 and w["t"] <= T + 1e-9]
    rebuilt = max([w["p"] + P_TOL for w in ring], default=0.0)
    hidden = None
    if ev["aimax6s"] - MC_TOL > max(rebuilt, UNLOGGED_P) + P_TOL:
        hidden = dict(kind="hidden", h=ev["aimax6s"], t=T - 2.0, states=None)
    S = min(UNLOGGED_SUM, 2 * (ev["aimax6s"] + MC_TOL))
    pseudo = pseudo_unlogged([w["t"] for w in ring], T - RING_S, T, S)
    allw = ring + ([hidden] if hidden else []) + pseudo
    return allw, ring, hidden, rebuilt


def support(ev, rule, param, tau):
    """Path-B AI support at one FSM evaluation -> 'yes'|'no'|'unk'."""
    if rule == "mean":      # firmware's aiMax6s is exactly max(mean) over the ring
        a = ev["aimax6s"]
        if a - MC_TOL >= tau:
            return "yes"
        return "no" if a + MC_TOL < tau else "unk"
    best = "no"
    for w in ev["ring_all"]:
        lo, hi = win_interval(w, rule, param)
        if lo >= tau:
            return "yes"
        if hi >= tau:
            best = "unk"
    return best


def decide_B(evals, var_still, rule, param, tau):
    """Replay the end-of-IMPACT decision with the logged variances.  -> (verdict, eval_index)"""
    for i, ev in enumerate(evals):
        v = ev["var"]
        if v < var_still:
            return support(ev, rule, param, tau), i
        if v > MOTION_VAR:
            return "no", i
        if i == 0:
            continue            # mid variance: firmware extends the observation once
        return "no", i
    return "no", None


def comb(a, b):
    if "yes" in (a, b):
        return "yes"
    if "unk" in (a, b):
        return "unk"
    return "no"


# ----------------------------------------------------------------------------------------------- candidates
def build_candidates():
    C = []

    def add(cid, fam, A, B, var_still=STILL_VAR, desc=""):
        C.append(dict(id=cid, family=fam, A=A, B=B, var_still=var_still, desc=desc))

    add("C1", "C1", [("mean", None, 0.87, None)], ("mean", None, 0.5), desc="A: mean>=0.87; B: mean>=0.5 (current firmware)")
    for t in (0.6, 0.7, 0.8, 0.87, 0.95):
        for tau in (0.3, 0.4, 0.5, 0.6, 0.7):
            add(f"C2 A>={t:g} B>={tau:g}", "C2", [("mean", None, t, None)], ("mean", None, tau),
                desc=f"A: mean>={t}; B: mean>={tau}")
    for t in (0.9, 0.95, 0.98, 0.99):
        for tau in (0.5, 0.7, 0.9):
            add(f"C3 A>={t:g} B>={tau:g}", "C3", [("max", None, t, None)], ("max", None, tau),
                desc=f"A: max(MLP,CNN)>={t}; B: max>={tau}")
    for w in (0.3, 0.4, 0.6, 0.7):
        for t in (0.7, 0.8, 0.87):
            add(f"C4 w={w:g} A>={t:g}", "C4", [("wmean", w, t, None)], ("wmean", w, 0.5),
                desc=f"A: {w}*MLP+{1 - w:.1f}*CNN>={t}; B: same score>=0.5")
    for t in (0.5, 0.6, 0.7, 0.8):
        add(f"C5 A>={t:g}", "C5", [("min", None, t, None)], ("mean", None, 0.5), desc=f"A: min(MLP,CNN)>={t}; B: mean>=0.5")
    for thi in (0.8, 0.9, 0.95, 0.98):
        add(f"C6 thi={thi:g}", "C6", [("mean", None, 0.87, None), ("max", None, thi, IMPACT_STATES)], ("mean", None, 0.5),
            desc=f"A: mean>=0.87 OR (max>={thi} AND state FREE_FALL/IMPACT); B: mean>=0.5")
    for tau in (0.5, 0.7, 0.9):
        for vs in (0.8, 1.5, 2.5):
            add(f"C7 tauB={tau:g} vs={vs:g}", "C7", [("mean", None, 0.87, None)], ("max", None, tau), var_still=vs,
                desc=f"A: mean>=0.87; B: max(MLP,CNN) over 6 s >= {tau}; var_still={vs}")
    for rule in ("mlp", "cnn"):
        add(f"C8 {rule}-only", "C8", [(rule, None, 0.9, None)], (rule, None, 0.5), desc=f"{rule} alone: A>=0.9, B>=0.5 (reference)")
    return C


# ----------------------------------------------------------------------------------------------- per-log analysis
def prepare_trial(tr, events):
    wins = [e for e in events if e["type"] == "win"]
    tr["windows"] = [w for w in wins if tr["span_start"] <= w["t"] <= tr["span_end"] + 1e-9]
    ring_hidden = []
    for ev in tr["evals"]:
        allw, ring, hidden, rebuilt = build_ring(ev, wins)
        ev["ring_all"] = allw
        ev["ring_logged"] = ring
        ev["hidden"] = hidden
        ev["rebuilt_max_mean"] = rebuilt
        if hidden:
            ring_hidden.append(hidden)
    # path-A window set: logged windows + hidden windows (state unknown) + one pseudo window if gaps exist
    extra = []
    seen = set()
    for h in ring_hidden:
        key = round(h["h"], 3)
        if key not in seen:
            seen.add(key)
            extra.append(dict(h))
    tr["a_windows"] = tr["windows"] + extra + pseudo_unlogged([w["t"] for w in tr["windows"]], tr["span_start"], tr["span_end"])
    # what the firmware did
    nxt = None
    for e in events:
        if e["type"] == "tr" and e["idx"] > tr["idx_close"] and e["frm"] in ("COUNTDOWN", "ALARM", "PANIC_SOS"):
            nxt = e
            break
    if tr["trig"] is not None:
        out = f"A: AI trigger p={tr['trig']['p']:.3f} -> COUNTDOWN"
    elif tr["close_to"] == "COUNTDOWN":
        out = "B: still + AI support -> COUNTDOWN"
    elif tr["close_to"] == "IDLE":
        last = tr["evals"][-1] if tr["evals"] else None
        if tr["close_kind"] == "FF_TIMEOUT":
            out = "no alarm (free-fall timed out)"
        else:
            out = (f"no alarm: IDLE (var {last['var']:.3g}, ai={last['ai']})" if last else "no alarm: IDLE")
    else:
        out = f"{tr['close_to']}"
    if tr["close_to"] == "COUNTDOWN" and nxt is not None:
        out += f" -> {nxt['to']} (+{nxt['t'] - tr['t_close']:.1f} s)"
    tr["firmware_outcome"] = out
    # stats
    lw = tr["windows"]
    tr["mlp_peak"] = max((w["mlp"] for w in lw), default=None)
    tr["cnn_peak"] = max((w["cnn"] for w in lw), default=None)
    tr["mean_peak"] = max((w["p"] for w in lw), default=None)
    tr["max_disagreement"] = max((abs(w["mlp"] - w["cnn"]) for w in lw), default=None)


def eval_candidate_on_log(cand, trials):
    res = {}
    last_a = None
    for tr in trials:
        A_iso, t_iso, via_iso = any_ge(tr["a_windows"], cand["A"])
        tmin = -1e9 if last_a is None else last_a + COOLDOWN_S
        A_cd, t_cd, via_cd = any_ge(tr["a_windows"], cand["A"], tmin)
        blocked = (A_iso == "yes" and A_cd != "yes")
        rule, param, tau = cand["B"]
        B, bi = decide_B(tr["evals"], cand["var_still"], rule, param, tau)
        res[tr["id"]] = dict(
            A_cooldown=A_cd, A_isolated=A_iso, A_blocked_by_cooldown=blocked, A_t=t_cd, A_via=via_cd or via_iso,
            B=B, B_eval=bi, alarm_cooldown=comb(A_cd, B), alarm_isolated=comb(A_iso, B),
        )
        if A_cd == "yes":
            last_a = t_cd
    return res


def code_of(r, tr_id=None, ai_off=False):
    a, b = r["A_cooldown"], r["B"]
    if ai_off:
        b = "no"
    s = ""
    if a == "yes":
        s += "a" if ai_off else "A"
    if b == "yes":
        s += "B"
    if not s:
        s = "?" if "unk" in (a, b) else "-"
    if r["A_blocked_by_cooldown"]:
        s += "c"
    return s


# ----------------------------------------------------------------------------------------------- idle stretches
def idle_analysis(name, events, trials):
    wins = [e for e in events if e["type"] == "win"]
    t0 = wins[0]["t"]
    t_end = max(e["t"] for e in events)
    # non-IDLE intervals from the state timeline
    tl = [(0.0, "IDLE")] + [(e["t"], e["to"]) for e in events if e["type"] == "tr"]
    bad = []
    for (ta, sa), (tb, _) in zip(tl, tl[1:] + [(t_end, None)]):
        if sa != "IDLE":
            bad.append([ta - IDLE_PAD_BEFORE, tb + IDLE_PAD_AFTER])
    bad.sort()
    merged = []
    for iv in bad:
        if merged and iv[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], iv[1])
        else:
            merged.append(iv)
    intervals, cursor = [], t0
    for a, b in merged:
        if a > cursor:
            intervals.append((cursor, min(a, t_end)))
        cursor = max(cursor, b)
    if cursor < t_end:
        intervals.append((cursor, t_end))
    intervals = [(a, b) for a, b in intervals if b - a > 0.4]
    out = []
    for a, b in intervals:
        lw = [w for w in wins if a <= w["t"] <= b]
        out.append(dict(log=name, t0=a, t1=b, duration_s=b - a, n_logged_windows=len(lw),
                        max_p=max((w["p"] for w in lw), default=0.0),
                        max_mlp=max((w["mlp"] for w in lw), default=0.0),
                        max_cnn=max((w["cnn"] for w in lw), default=0.0),
                        n_windows_above_0_2=sum(1 for w in lw if w["p"] > 0.2),
                        _windows=lw))
    return out


def idle_verdict(cand, idle_intervals):
    """Path A over all idle windows + the bound for unlogged ones.  Path B needs an IMPACT, none happened in idle."""
    verdict = "no"
    for iv in idle_intervals:
        wl = [dict(w, states={"IDLE"}) for w in iv["_windows"]]
        wl += [dict(kind="unlogged", t=iv["t0"] + 0.5, S=UNLOGGED_SUM, states={"IDLE"})]
        v, _, _ = any_ge(wl, cand["A"])
        verdict = comb(verdict, v)
    return verdict


# ----------------------------------------------------------------------------------------------- main
def main():
    xcheck = _evalx_crosscheck()
    all_trials, idle_all, log_info = [], [], {}
    for name in LOGS:
        ev = parse_log(name)
        trs = build_trials(name, ev)
        for tr in trs:
            prepare_trial(tr, ev)
        ai_vals = {e["ai"] for e in ev if e["type"] == "var"}
        log_info[name] = dict(last_line_s=max(e["t"] for e in ev), n_logged_windows=sum(1 for e in ev if e["type"] == "win"),
                              ai_alarm_mode=("OFF" if ai_vals == {0} else "ON" if ai_vals == {1} else "unknown"))
        idle_all += idle_analysis(name, ev, trs)
        all_trials.append((name, trs))

    cands = build_candidates()
    fall_ids = [tid for tid, m in TRIAL_META.items() if m["counts"]]
    info_ids = [tid for tid in fall_ids if TRIAL_META[tid]["informative"]]
    probe_ids = [tid for tid, m in TRIAL_META.items() if not m["counts"]]

    # evaluate
    results = {c["id"]: {} for c in cands}
    for name, trs in all_trials:
        for c in cands:
            results[c["id"]].update(eval_candidate_on_log(c, trs))

    idle_hours = sum(iv["duration_s"] for iv in idle_all) / 3600.0
    idle_n_logged = sum(iv["n_logged_windows"] for iv in idle_all)

    cand_rows = []
    for c in cands:
        r = results[c["id"]]

        def count(ids, key):
            lo = sum(1 for i in ids if r[i][key] == "yes")
            hi = sum(1 for i in ids if r[i][key] in ("yes", "unk"))
            return lo, hi

        row = dict(id=c["id"], family=c["family"], desc=c["desc"], var_still=c["var_still"])
        for tag, ids in (("all5", fall_ids), ("informative4", info_ids)):
            for key, kname in (("alarm_cooldown", "with_cooldown"), ("alarm_isolated", "isolated")):
                lo, hi = count(ids, key)
                n = len(ids)
                row[f"{tag}_{kname}"] = dict(caught_min=lo, caught_max=hi, n=n, wilson95_min=list(map(lambda v: round(v, 3), wilson(lo, n))),
                                             wilson95_max=list(map(lambda v: round(v, 3), wilson(hi, n))))
        iv = idle_verdict(c, idle_all)
        row["idle_false_alarm"] = dict(
            verdict=iv, conclusive=(iv == "no"),
            rate_upper_per_h_two_sided=(round(poisson_upper(0, idle_hours), 2) if iv == "no" else None),
            rate_upper_per_h_one_sided=(round(poisson_upper(0, idle_hours, one_sided=True), 2) if iv == "no" else None))
        row["probe_events"] = {i: dict(alarm_cooldown=r[i]["alarm_cooldown"]) for i in probe_ids}
        cand_rows.append(row)

    # ------------------------------------------------------------------------------------ JSON
    trial_json = []
    for name, trs in all_trials:
        for tr in trs:
            meta = TRIAL_META.get(tr["id"], dict(label="unlabelled", counts=False, informative=False, note=""))
            evals = []
            for e in tr["evals"]:
                mx = (max((win_interval(w, "max")[0] for w in e["ring_all"]), default=0.0),
                      max((win_interval(w, "max")[1] for w in e["ring_all"]), default=0.0))
                evals.append(dict(t=e["t"], variance=e["var"], samples=e["samples"], ai_mode=e["ai"],
                                  aiMax6s_logged_by_firmware=e["aimax6s"],
                                  ring_max_mean_rebuilt_from_log=round(e["rebuilt_max_mean"], 3),
                                  hidden_unlogged_window_detected=bool(e["hidden"]),
                                  ring_max_of_max_mlp_cnn_interval=[round(mx[0], 3), round(mx[1], 3)]))
            trial_json.append(dict(
                id=tr["id"], log=tr["log"], label=meta["label"], counted_among_5_falls=meta["counts"],
                informative_for_ai_mode=meta["informative"], note=meta["note"],
                t_open_s=tr["t_open"], t_close_s=tr["t_close"], span_s=[round(tr["span_start"], 2), tr["span_end"]],
                firmware_outcome=tr["firmware_outcome"], mlp_peak=tr["mlp_peak"], cnn_peak=tr["cnn_peak"],
                mean_peak=tr["mean_peak"], max_mlp_cnn_disagreement=tr["max_disagreement"],
                n_logged_windows=len(tr["windows"]), evals=evals,
                logged_windows=[dict(t=w["t"], p=w["p"], mlp=w["mlp"], cnn=w["cnn"], state=w["state"]) for w in tr["windows"]],
                candidates={cid: {k: v for k, v in results[cid][tr["id"]].items()} for cid in results}))

    idle_json = [{k: v for k, v in iv.items() if not k.startswith("_")} for iv in idle_all]
    payload = dict(
        generated=datetime.now().isoformat(timespec="seconds"),
        script="tools/ai_lab/device_log_rescore.py",
        evalx_crosscheck=xcheck,
        method=dict(
            unlogged_window_bound=dict(
                rule="firmware logs a window only if p>0.2 or as 5 s heartbeat; so an unlogged window has mean<=0.2, "
                     "max(MLP,CNN)<=0.4, min<=0.2, w*MLP+(1-w)*CNN<=0.4*max(w,1-w)",
                conclusive_if="threshold is strictly above the bound for the rule used (mean/min thresholds >0.2, max/weighted-mean >0.4*max(w,1-w))",
                caveat="not airtight: live5#2 shows a window with mean 0.69 (aiMax6s) that was never logged; such windows are detected via aiMax6s but a dropped non-maximal window cannot be"),
            print_rounding=dict(p=P_TOL, mlp_cnn_aimax6s=MC_TOL),
            host_timestamp_jitter="live_ai.py stamps lines on arrival; ring membership (6 s) can be off by ~0.5 s",
            cooldown_s=COOLDOWN_S, still_var=STILL_VAR, motion_var=MOTION_VAR,
            live1="AI alarm mode OFF: FSM ran the legacy rule (var thresholds 0.08/0.8, 3 s window); non-informative for current firmware and path B; path A replayed as counterfactual",
            codes="A/B = alarm via path A/B, '-' none, '?' inconclusive, lowercase 'a' = counterfactual path A on the ai=0 log, trailing 'c' = path A would have fired but the 30 s cooldown blocked it",
        ),
        logs=log_info,
        idle=dict(total_s=sum(iv["duration_s"] for iv in idle_all), total_hours=idle_hours, n_logged_windows=idle_n_logged,
                  max_p=max((iv["max_p"] for iv in idle_all), default=0), max_mlp=max((iv["max_mlp"] for iv in idle_all), default=0),
                  max_cnn=max((iv["max_cnn"] for iv in idle_all), default=0),
                  note="quiet wear, activity not annotated (p~0.001): says nothing about claps, sitting down, walking",
                  intervals=idle_json),
        trials=trial_json,
        candidates=cand_rows,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    print_report(all_trials, results, cands, cand_rows, idle_all, idle_hours, fall_ids, info_ids, probe_ids, xcheck, log_info)
    print(f"\nwrote {OUT}")


# ----------------------------------------------------------------------------------------------- report
def fmt_ci(lo, hi, n):
    k = wilson(lo, n)
    s = f"{lo}/{n}" if lo == hi else f"{lo}-{hi}/{n}"
    return f"{s} [{k[0]:.2f}-{k[1]:.2f}]" if lo == hi else f"{s} [{wilson(lo, n)[0]:.2f}-{wilson(hi, n)[1]:.2f}]"


def print_report(all_trials, results, cands, cand_rows, idle_all, idle_hours, fall_ids, info_ids, probe_ids, xcheck, log_info):
    print(f"evalx cross-check of Wilson/Poisson: {xcheck}")
    print("logs:", {k: (v['ai_alarm_mode'], v['last_line_s'], v['n_logged_windows']) for k, v in log_info.items()})
    trs = [tr for _, t in all_trials for tr in t]
    print("\n== per-trial (current firmware, from the log) ==")
    print(f"{'trial':8} {'fall':5} {'MLPpk':>5} {'CNNpk':>5} {'meanpk':>6} {'|M-C|':>5}  variance(s) / aiMax6s            firmware did")
    for tr in trs:
        meta = TRIAL_META.get(tr["id"], {})
        ev = " ".join(f"{e['var']:.3g}/{e['aimax6s']:.2f}{'*' if e['hidden'] else ''}" for e in tr["evals"])
        tag = "yes" if meta.get("counts") else "(no)"
        if meta.get("counts") and not meta.get("informative"):
            tag = "yes!"
        print(f"{tr['id']:8} {tag:5} {tr['mlp_peak']:5.2f} {tr['cnn_peak']:5.2f} {tr['mean_peak']:6.3f} {tr['max_disagreement']:5.2f}  {ev:30} {tr['firmware_outcome']}")
    print("  (* = firmware aiMax6s higher than any logged window: a window with p>0.2 was not logged;  yes! = ai=0 log, non-informative)")

    ids = [tr["id"] for tr in trs]
    hdr = "".join(f"{i:>9}" for i in ids)
    print("\n== candidates x trials (code: A/B path, - none, ? inconclusive, a = ai=0 counterfactual A, c = blocked by 30 s cooldown) ==")
    print(f"{'candidate':22}{hdr}  {'caught/5 (cd)':>18} {'caught/5 iso':>16} {'caught/4 (cd)':>16}  idle FA")
    show = []
    for c, row in zip(cands, cand_rows):
        fam = c["family"]
        cid = c["id"]
        if fam == "C2":      # print the diagonals only; full grid is in the JSON
            m = re.match(r"C2 A>=([\d.]+) B>=([\d.]+)", cid)
            if not (m[1] == "0.87" or m[2] == "0.5"):
                continue
        if fam == "C4" and "A>=0.87" not in cid and "A>=0.8" not in cid:
            continue
        show.append((c, row))
    for c, row in show:
        r = results[c["id"]]
        cells = ""
        for tid in ids:
            ai_off = tid == "live1#1" or tid == "live1#2"
            cells += f"{code_of(r[tid], ai_off=ai_off):>9}"
        a5 = row["all5_with_cooldown"]
        i5 = row["all5_isolated"]
        a4 = row["informative4_with_cooldown"]
        fa = row["idle_false_alarm"]
        fa_s = "0 (concl.)" if fa["conclusive"] else ("INCONCLUSIVE" if fa["verdict"] == "unk" else "ALARM")
        print(f"{c['id']:22}{cells}  {fmt_ci(a5['caught_min'], a5['caught_max'], a5['n']):>18} {fmt_ci(i5['caught_min'], i5['caught_max'], i5['n']):>16} {fmt_ci(a4['caught_min'], a4['caught_max'], a4['n']):>16}  {fa_s}")
    print("  (live1#2 = unlabelled post-fall motion, NOT counted; full grid incl. all C2 pairs in the JSON)")

    print("\n== idle / quiet stretches ==")
    tot = sum(iv["duration_s"] for iv in idle_all)
    for iv in idle_all:
        print(f"  {iv['log']} {iv['t0']:6.1f}-{iv['t1']:6.1f}s  {iv['duration_s']:6.1f} s  logged windows {iv['n_logged_windows']:3d}  max p {iv['max_p']:.3f} mlp {iv['max_mlp']:.2f} cnn {iv['max_cnn']:.2f}")
    print(f"  TOTAL {tot:.0f} s = {tot / 60:.1f} min = {idle_hours:.3f} h; max logged p {max(i['max_p'] for i in idle_all):.3f}")
    print(f"  unlogged-window bound: mean<=0.2, max(MLP,CNN)<=0.4 (worst case), so any max-rule threshold >0.4 and mean/min threshold >0.2 is conclusive")
    print(f"  false-alarm upper bound when 0 alarms (Poisson 95%): {poisson_upper(0, idle_hours):.1f}/h two-sided, {poisson_upper(0, idle_hours, one_sided=True):.1f}/h one-sided (only for quiet wear)")
    unk = [c["id"] for c, row in zip(cands, cand_rows) if not row["idle_false_alarm"]["conclusive"]]
    print(f"  candidates NOT conclusive on idle: {unk if unk else 'none'}")

    print("\n== headline: falls caught of 5 real falls (live1 counted only via counterfactual path A) ==")
    for fam in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        rows = [r for r in cand_rows if r["family"] == fam]
        best = max(rows, key=lambda r: r["all5_with_cooldown"]["caught_min"])
        worst = min(rows, key=lambda r: r["all5_with_cooldown"]["caught_min"])
        print(f"  {fam}: {worst['all5_with_cooldown']['caught_min']}..{best['all5_with_cooldown']['caught_min']}/5 over {len(rows)} settings "
              f"(best: {best['id']}; isolated-fall best {max(r['all5_isolated']['caught_min'] for r in rows)}/5)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
