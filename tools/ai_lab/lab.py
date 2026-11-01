"""Shared lab: cached datasets, trainers (torch MLP / 1D-CNN, sklearn), LOSO runner, operating curves."""
from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from .data import load_recordings, FS
from .evalx import Windows, build_windows, event_report, window_report, rec_slices
from .features import feat42, featinv

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "dataset" / "ai_cache"
CACHE.mkdir(parents=True, exist_ok=True)
torch.set_num_threads(6)

POS_W, HARD_W = 8.0, 2.0


# ----------------------------------------------------------------------------- datasets
def get_views(recs, names=("hifd", "fw", "fw_aug0", "fw_aug1", "fw_aug2")) -> dict:
    out = {}
    for n in names:
        f = CACHE / f"{n}.pkl"
        if f.is_file():
            out[n] = pickle.load(open(f, "rb"))
            continue
        t = time.time()
        if n in ("hifd", "fw"):
            W = build_windows(recs, n)
        else:
            k = int(n[-1])
            W = build_windows(recs, "fw", rng=np.random.default_rng(100 + k), rot="small", bias=0.15)
        W.F42 = feat42(W.X)
        W.FINV = featinv(W.X)
        pickle.dump(W, open(f, "wb"))
        print(f"built view {n}: {len(W)} windows in {time.time()-t:.0f}s")
        out[n] = W
    return out


def sample_weights(W: Windows, pos_w: float | None = None, hard_w: float | None = None) -> np.ndarray:
    w = np.ones(len(W.y), dtype=np.float32)
    w[W.y == 1] = POS_W if pos_w is None else pos_w
    w[(W.y == 0) & W.hard] = HARD_W if hard_w is None else hard_w
    return w


RECS = None  # set by runners that need recording metadata (legacy-label ablation)


def legacy_view(W: Windows) -> Windows:
    """Ablation: recording-level labels (every window of a fall recording is 'fall'), nothing excluded."""
    y = np.array([1 if RECS[r].is_fall else 0 for r in W.rec])
    out = W.sub(np.ones(len(W), dtype=bool))
    out.y = y
    out.keep = np.ones(len(W), dtype=bool)
    return out


def getf(W, feat):
    return np.concatenate([getattr(W, f) for f in feat.split("+")], axis=1) if "+" in feat else getattr(W, feat)


# ----------------------------------------------------------------------------- models
def _bce(logit, y, w):
    return (nn.functional.binary_cross_entropy_with_logits(logit, y, reduction="none") * w).sum() / w.sum()


class MLP(nn.Module):
    def __init__(self, d, h=16):
        super().__init__()
        self.l1, self.l2 = nn.Linear(d, h), nn.Linear(h, 1)

    def forward(self, x):
        return self.l2(torch.tanh(self.l1(x))).squeeze(-1)


class CNN(nn.Module):
    """1D-CNN on [ax,ay,az,gx,gy,gz,|a|] x 100. cfg=(c1,c2,c3)."""

    def __init__(self, cfg=(8, 16, 16), cin=7):
        super().__init__()
        c1, c2, c3 = cfg
        self.c1 = nn.Conv1d(cin, c1, 5, stride=2, padding=2)
        self.c2 = nn.Conv1d(c1, c2, 5, stride=2, padding=2)
        self.c3 = nn.Conv1d(c2, c3, 3, padding=1)
        self.fc = nn.Linear(2 * c3, 1)

    def forward(self, x):
        x = torch.relu(self.c1(x))
        x = torch.relu(self.c2(x))
        x = torch.relu(self.c3(x))
        f = torch.cat([x.max(-1).values, x.mean(-1)], 1)
        return self.fc(f).squeeze(-1)


def cnn_input(X: np.ndarray) -> np.ndarray:
    """(n,100,6) -> (n,7,100) with the magnitude channel."""
    mag = np.linalg.norm(X[:, :, :3], axis=2, keepdims=True)
    return np.concatenate([X, mag], axis=2).transpose(0, 2, 1).astype(np.float32)


class Fitted:
    """Uniform wrapper: predict(Windows)->probabilities."""

    def __init__(self, kind, model, norm=None, feat="F42", cols=None):
        self.kind, self.model, self.norm, self.feat, self.cols = kind, model, norm, feat, cols

    def predict(self, W: Windows) -> np.ndarray:
        if self.kind == "mlp":
            F = getf(W, self.feat)
            if self.cols is not None:
                F = F[:, self.cols]
            z = (F - self.norm[0]) / self.norm[1]
            with torch.no_grad():
                return torch.sigmoid(self.model(torch.tensor(z, dtype=torch.float32))).numpy()
        if self.kind == "cnn":
            x = (cnn_input(W.X) - self.norm[0]) / self.norm[1]
            out = []
            with torch.no_grad():
                for i in range(0, len(x), 2048):
                    out.append(torch.sigmoid(self.model(torch.tensor(x[i:i + 2048]))).numpy())
            return np.concatenate(out)
        F = getf(W, self.feat)
        return self.model.predict_proba((F - self.norm[0]) / self.norm[1])[:, 1]


def fit_mlp(Wtr, Wva, seed, feat="F42", hidden=16, epochs=1500, patience=150, lr=0.01,
            pos_w=None, hard_w=None, cols=None, legacy=False):
    torch.manual_seed(seed)
    if legacy:
        Wtr = legacy_view(Wtr)
    F = getf(Wtr, feat)
    if cols is not None:
        F = F[:, cols]
    F = F[Wtr.keep]
    mu, sd = F.mean(0), np.maximum(F.std(0), 1e-6)
    x = torch.tensor((F - mu) / sd, dtype=torch.float32)
    y = torch.tensor(Wtr.y[Wtr.keep], dtype=torch.float32)
    w = torch.tensor(sample_weights(Wtr, pos_w, hard_w)[Wtr.keep])
    Fv = getf(Wva, feat)
    if cols is not None:
        Fv = Fv[:, cols]
    Fv = Fv[Wva.keep]
    xv = torch.tensor((Fv - mu) / sd, dtype=torch.float32)
    yv = torch.tensor(Wva.y[Wva.keep], dtype=torch.float32)
    m = MLP(x.shape[1], hidden)
    opt = torch.optim.Adam(m.parameters(), lr=lr)
    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        opt.zero_grad()
        loss = _bce(m(x), y, w)
        loss.backward()
        opt.step()
        with torch.no_grad():
            vl = _bce(m(xv), yv, torch.ones_like(yv)).item()
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.clone() for k, v in m.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    m.load_state_dict(best_state)
    return Fitted("mlp", m.eval(), (mu, sd), feat, cols)


def fit_cnn(Wtr, Wva, seed, cfg=(8, 16, 16), epochs=60, patience=10, lr=3e-3, bs=256, extra=None):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    X = cnn_input(Wtr.X[Wtr.keep])
    y = Wtr.y[Wtr.keep].astype(np.float32)
    w = sample_weights(Wtr)[Wtr.keep]
    mu = X.mean((0, 2), keepdims=True)
    sd = np.maximum(X.std((0, 2), keepdims=True), 1e-3)
    xt = torch.tensor((X - mu) / sd)
    yt, wt = torch.tensor(y), torch.tensor(w)
    xv = torch.tensor((cnn_input(Wva.X[Wva.keep]) - mu) / sd)
    yv = torch.tensor(Wva.y[Wva.keep].astype(np.float32))
    m = CNN(cfg)
    opt = torch.optim.Adam(m.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    best, best_state, bad = 1e9, None, 0
    n = len(xt)
    for ep in range(epochs):
        m.train()
        perm = torch.tensor(rng.permutation(n))
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            xb = xt[idx]
            xb = xb + 0.03 * torch.randn_like(xb)
            opt.zero_grad()
            _bce(m(xb), yt[idx], wt[idx]).backward()
            opt.step()
        sched.step()
        m.eval()
        with torch.no_grad():
            vl = _bce(m(xv), yv, torch.ones_like(yv)).item()
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.clone() for k, v in m.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    m.load_state_dict(best_state)
    return Fitted("cnn", m.eval(), (mu, sd))


def fit_sklearn(kind, Wtr, Wva, seed, feat="F42"):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    F = getattr(Wtr, feat)[Wtr.keep]
    mu, sd = F.mean(0), np.maximum(F.std(0), 1e-6)
    y = Wtr.y[Wtr.keep]
    w = sample_weights(Wtr)[Wtr.keep]
    if kind == "lr":
        m = LogisticRegression(max_iter=2000, C=1.0)
    elif kind == "dt":
        m = DecisionTreeClassifier(max_depth=6, min_samples_leaf=10, random_state=seed)
    else:
        m = RandomForestClassifier(n_estimators=60, max_depth=8, min_samples_leaf=5, random_state=seed, n_jobs=6)
    m.fit((F - mu) / sd, y, sample_weight=w)
    return Fitted(kind, m, (mu, sd), feat)


# ----------------------------------------------------------------------------- thresholds
GRID = np.concatenate([np.linspace(0.2, 0.9, 36), np.linspace(0.91, 0.995, 18)])


def pick_threshold(recs, Wva, sva, margin=0.02, min_recall=0.8):
    """Lowest threshold with zero validation false alerts and recall >= min_recall, + margin."""
    best = None
    for t in GRID:
        ev = event_report(recs, Wva, sva, t)
        if ev["false_alerts"] == 0 and ev["recall"] >= min_recall:
            best = t
            break
    if best is None:
        return 0.99
    return float(min(best + margin, 0.995))


# ----------------------------------------------------------------------------- LOSO
def val_subjects(held: int, all_subj: list[int]) -> list[int]:
    rng = np.random.default_rng(1000 + held)
    others = [s for s in all_subj if s != held]
    return sorted(rng.choice(others, 3, replace=False).tolist())


def loso(recs, name, trainer, train_views: list[Windows], eval_view: Windows,
         seeds=(0,), subjects=None, log=True):
    """Leave-one-subject-out. train_views: windows sets (same ordering) concatenated for training.
    Returns pooled scores (eval_view order), per-fold thresholds."""
    subs = sorted(set(eval_view.subj.tolist())) if subjects is None else subjects
    all_subj = sorted(set(eval_view.subj.tolist()))
    scores = np.zeros((len(seeds), len(eval_view)), dtype=np.float32)
    thr = {}
    for held in subs:
        vs = val_subjects(held, all_subj)
        tr_mask = ~np.isin(eval_view.subj, [held] + vs)
        va_mask = np.isin(eval_view.subj, vs)
        te_mask = eval_view.subj == held
        Wtr = _concat([v.sub(tr_mask) for v in train_views])
        Wva = train_views[0].sub(va_mask)
        Wva_eval = eval_view.sub(va_mask)
        Wte = eval_view.sub(te_mask)
        for si, seed in enumerate(seeds):
            t0 = time.time()
            fm = trainer(Wtr, Wva, seed)
            scores[si, te_mask] = fm.predict(Wte)
            sva = fm.predict(Wva_eval)
            thr[(held, seed)] = pick_threshold(recs, Wva_eval, sva)
            if log:
                print(f"  [{name}] held {held:2d} seed {seed} thr {thr[(held, seed)]:.3f} ({time.time()-t0:.1f}s)", flush=True)
    return scores, thr


def _concat(ws: list[Windows]) -> Windows:
    if len(ws) == 1:
        return ws[0]
    c = Windows(np.concatenate([w.X for w in ws]), np.concatenate([w.y for w in ws]),
                np.concatenate([w.keep for w in ws]), np.concatenate([w.subj for w in ws]),
                np.concatenate([w.rec for w in ws]), np.concatenate([w.start for w in ws]),
                np.concatenate([w.hard for w in ws]), sum([w.scen for w in ws], []))
    for a in ("F42", "FINV"):
        if hasattr(ws[0], a):
            setattr(c, a, np.concatenate([getattr(w, a) for w in ws]))
    return c


# patch Windows.sub so feature caches follow subsetting
_orig_sub = Windows.sub


def _sub(self, mask):
    out = _orig_sub(self, mask)
    for a in ("F42", "FINV"):
        if hasattr(self, a):
            setattr(out, a, getattr(self, a)[mask])
    return out


Windows.sub = _sub


# ----------------------------------------------------------------------------- reporting
def pooled_report(recs, W, scores_1seed, thr_by_subject: dict[int, float]) -> dict:
    """Per-held-out-subject thresholds (chosen on validation), pooled over all subjects."""
    det = nfall = fa = 0
    hours = 0.0
    by_scen, missed, lat = {}, [], []
    for s, t in thr_by_subject.items():
        m = W.subj == s
        ev = event_report(recs, W.sub(m), scores_1seed[m], t)
        det += ev["detected"]; nfall += ev["n_fall"]; fa += ev["false_alerts"]; hours += ev["hours"]
        missed += ev["missed"]
        for k, v in ev["false_by_scenario"].items():
            by_scen[k] = by_scen.get(k, 0) + v
        if ev["latency_median_s"] == ev["latency_median_s"]:
            lat.append(ev["latency_median_s"])
    from .evalx import wilson, poisson_upper
    lo, hi = wilson(det, nfall)
    return {"detected": det, "n_fall": nfall, "recall": det / nfall, "recall_ci": (lo, hi),
            "false_alerts": fa, "hours": hours, "fa_per_h": fa / hours,
            "fa_upper95": poisson_upper(fa, hours), "false_by_scenario": by_scen,
            "missed": missed, "latency_median_s": float(np.median(lat)) if lat else float("nan")}


def operating_curve(recs, W, scores, grid=None):
    """Pooled (all subjects, threshold-free): recall and FA/h versus threshold."""
    grid = GRID if grid is None else grid
    rows = []
    for t in grid:
        ev = event_report(recs, W, scores, t)
        rows.append((t, ev["recall"], ev["fa_per_h"], ev["detected"], ev["false_alerts"]))
    return np.array(rows), ev["hours"]


def recall_at_fa(curve, fa_target):
    ok = curve[curve[:, 2] <= fa_target]
    return float(ok[:, 1].max()) if len(ok) else 0.0
