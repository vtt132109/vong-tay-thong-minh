"""Windows, event-level metrics with timing, FA/h, confidence intervals, FSM simulation."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import chi2

from .data import FS, WIN, STRIDE, Recording, event_label, window_starts
from .preproc import make_signal, raw_acc, _SOS, ACC_CLIP
from scipy.signal import sosfilt


# ----------------------------------------------------------------------------- windows
@dataclass
class Windows:
    X: np.ndarray            # (n,100,6) float32
    y: np.ndarray            # (n,) event-centered label
    keep: np.ndarray         # (n,) bool, False = ambiguous (excluded from train/window metrics)
    subj: np.ndarray         # (n,)
    rec: np.ndarray          # (n,) index into recs
    start: np.ndarray        # (n,)
    hard: np.ndarray         # (n,) bed/chair hard negative flag
    scen: list = field(default_factory=list)

    def __len__(self):
        return len(self.y)

    def sub(self, mask) -> "Windows":
        return Windows(self.X[mask], self.y[mask], self.keep[mask], self.subj[mask],
                       self.rec[mask], self.start[mask], self.hard[mask],
                       [s for s, m in zip(self.scen, mask) if m])


def build_windows(recs: list[Recording], view: str, *, rng=None, rot=None, bias=0.0,
                  only: set[int] | None = None) -> Windows:
    rng = rng or np.random.default_rng(0)
    Xs, ys, ks, ss, rs, st, hd, sc = [], [], [], [], [], [], [], []
    for ri, r in enumerate(recs):
        if only is not None and r.subject not in only:
            continue
        sig = make_signal(r, view, rng, rot, bias)
        for s in window_starts(r.n):
            lab, keep = event_label(int(s), r.center)
            Xs.append(sig[s:s + WIN]); ys.append(lab); ks.append(keep)
            ss.append(r.subject); rs.append(ri); st.append(s)
            hd.append(r.scenario in ("bed", "chair")); sc.append(r.scenario)
    return Windows(np.stack(Xs), np.array(ys), np.array(ks), np.array(ss), np.array(rs),
                   np.array(st), np.array(hd), sc)


# ----------------------------------------------------------------------------- stats
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def poisson_upper(k: int, hours: float, conf: float = 0.95) -> float:
    if hours <= 0:
        return float("nan")
    return float(chi2.ppf(1 - (1 - conf) / 2, 2 * (k + 1)) / 2 / hours)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


# ----------------------------------------------------------------------------- alerts
TP_ZONE = 2.0 * FS      # fire within +-2 s of the impact (window centre) is a detection
FP_ZONE = 3.0 * FS      # fire farther than 3 s from the impact is a false alert
MERGE_GAP = 3.0         # fires closer than 3 s belong to the same alert


def merge_fires(times_s: list[float]) -> list[float]:
    out, last = [], None
    for t in sorted(times_s):
        if last is None or t - last > MERGE_GAP:
            out.append(t)
        last = t
    return out


def rec_slices(W: Windows) -> dict:
    cache = getattr(W, "_sl", None)
    if cache is None:
        rec = W.rec
        cache = {}
        if len(rec):
            idx = np.flatnonzero(np.r_[True, rec[1:] != rec[:-1], True])
            for a, b in zip(idx[:-1], idx[1:]):
                cache[int(rec[a])] = slice(int(a), int(b))
        W._sl = cache
    return cache


def event_report(recs: list[Recording], W: Windows, scores: np.ndarray, thr: float,
                 rec_ids: set[int] | None = None) -> dict:
    """Operational metrics at threshold `thr` over the recordings present in W."""
    sl = rec_slices(W)
    ids = sorted(sl if rec_ids is None else rec_ids)
    det = nfall = 0
    lat = []
    false_alerts = 0
    false_by_scen: dict[str, int] = {}
    hours = 0.0
    missed = []
    for ri in ids:
        if ri not in sl:
            continue
        m = sl[ri]
        r = recs[ri]
        starts = W.start[m]
        sc = scores[m]
        fire = sc >= thr
        wc = starts + WIN // 2
        end_t = (starts + WIN) / FS
        if r.is_fall:
            nfall += 1
            d = np.abs(wc - r.center)
            tp_hit = fire & (d <= TP_ZONE)
            if tp_hit.any():
                det += 1
                lat.append(float(end_t[tp_hit][0] - r.center / FS))
            else:
                missed.append(r.name)
            fp_fire = fire & (d > FP_ZONE)
            hours += (r.n - 2 * FP_ZONE) / FS / 3600.0
        else:
            fp_fire = fire
            hours += r.n / FS / 3600.0
        al = merge_fires(end_t[fp_fire].tolist())
        false_alerts += len(al)
        if al:
            false_by_scen[r.scenario] = false_by_scen.get(r.scenario, 0) + len(al)
    lo, hi = wilson(det, nfall)
    return {
        "n_fall": nfall, "detected": det, "recall": det / nfall if nfall else float("nan"),
        "recall_ci": (lo, hi), "false_alerts": false_alerts, "hours": hours,
        "fa_per_h": false_alerts / hours if hours else float("nan"),
        "fa_upper95": poisson_upper(false_alerts, hours),
        "latency_median_s": float(np.median(lat)) if lat else float("nan"),
        "latency_max_s": float(np.max(lat)) if lat else float("nan"),
        "false_by_scenario": false_by_scen, "missed": missed,
    }


def window_report(W: Windows, scores: np.ndarray, thr: float) -> dict:
    m = W.keep
    pred = scores[m] >= thr
    y = W.y[m] == 1
    tp = int((pred & y).sum()); fp = int((pred & ~y).sum()); fn = int((~pred & y).sum())
    p, r, f = prf(tp, fp, fn)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": int((~pred & ~y).sum()),
            "precision": p, "recall": r, "f1": f}


def pr_curve(W: Windows, scores: np.ndarray, grid=None):
    grid = np.linspace(0.01, 0.995, 120) if grid is None else grid
    m = W.keep
    y = W.y[m] == 1
    s = scores[m]
    rows = []
    for t in grid:
        pred = s >= t
        tp = (pred & y).sum(); fp = (pred & ~y).sum(); fn = (~pred & y).sum()
        p, r, f = prf(tp, fp, fn)
        rows.append((t, p, r, f))
    return np.array(rows)


# ----------------------------------------------------------------------------- firmware FSM simulation
THRESH = 25.0


def fsm_input(rec: Recording, dlpf: bool = True) -> np.ndarray:
    a = raw_acc(rec)
    if dlpf:
        a = sosfilt(_SOS, a, axis=0)
    a = np.clip(a, -ACC_CLIP, ACC_CLIP)
    return np.linalg.norm(a, axis=1)


def simulate_fsm(acc: np.ndarray, thr: float = THRESH, ai_fire_ms: np.ndarray | None = None,
                 ai_promote: bool = False, ai_window_ms: float = 3000.0,
                 settle_ms: int = 200, window_ms: int = 3000,
                 var_still: float = 0.08, var_motion: float = 0.8):
    """Port of updateFallDetection() (src/fsm.cpp). Returns list of (alert_ms, impact_ms, how)."""
    IDLE, FREE, IMPACT = 0, 1, 2
    st = IDLE
    low = 0
    ff_start = 0
    imp_start = 0
    samples: list[float] = []
    extended = False
    last_direct = 0
    alerts = []
    cooldown_until = -1
    for i, a in enumerate(acc):
        now = i * 20
        if now < cooldown_until:
            continue
        if st == IDLE:
            if a < 5.0:
                low += 1
                if low >= 3:
                    ff_start = now
                    st = FREE
            else:
                low = 0
            if st == IDLE and a >= thr and (last_direct == 0 or now - last_direct > 2000):
                last_direct = now
                st, imp_start, samples, extended = IMPACT, now, [], False
        elif st == FREE:
            if a >= thr:
                last_direct = now
                st, imp_start, samples, extended = IMPACT, now, [], False
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
                ai_hit = False
                if ai_promote and ai_fire_ms is not None and len(ai_fire_ms):
                    ai_hit = bool(np.any((ai_fire_ms >= imp_start - 500) & (ai_fire_ms <= now)))
                if var < var_still:
                    alerts.append((now, imp_start, "still"))
                    cooldown_until = now + 30000
                    st, low = IDLE, 0
                elif var > var_motion:
                    st, low = IDLE, 0
                elif not extended:
                    if ai_hit:
                        alerts.append((now, imp_start, "ai"))
                        cooldown_until = now + 30000
                        st, low = IDLE, 0
                    else:
                        extended, imp_start, samples = True, now, []
                else:
                    if ai_hit:
                        alerts.append((now, imp_start, "ai"))
                        cooldown_until = now + 30000
                    st, low = IDLE, 0
    return alerts


def alerts_report(recs: list[Recording], alerts_by_rec: dict[int, list[float]], ids: list[int]) -> dict:
    """alerts_by_rec: rec index -> alert times (s) at which the device would enter COUNTDOWN."""
    det = nfall = fa = 0
    hours = 0.0
    lat = []
    by_scen: dict[str, int] = {}
    missed = []
    for ri in ids:
        r = recs[ri]
        al = alerts_by_rec.get(ri, [])
        if r.is_fall:
            nfall += 1
            c = r.center / FS
            good = [t for t in al if c - 1.0 <= t <= c + 8.0]  # decision after impact+window
            if good:
                det += 1
                lat.append(good[0] - c)
            else:
                missed.append(r.name)
            fa_al = [t for t in al if not (c - 3.0 <= t <= c + 8.0)]
            hours += max(r.n / FS - 11.0, 0) / 3600.0
        else:
            fa_al = al
            hours += r.n / FS / 3600.0
        fa += len(fa_al)
        if fa_al:
            by_scen[r.scenario] = by_scen.get(r.scenario, 0) + len(fa_al)
    lo, hi = wilson(det, nfall)
    return {"n_fall": nfall, "detected": det, "recall": det / nfall if nfall else float("nan"),
            "recall_ci": (lo, hi), "false_alerts": fa, "hours": hours,
            "fa_per_h": fa / hours if hours else float("nan"), "fa_upper95": poisson_upper(fa, hours),
            "latency_median_s": float(np.median(lat)) if lat else float("nan"),
            "false_by_scenario": by_scen, "missed": missed}
