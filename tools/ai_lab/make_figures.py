"""Figures + summary tables for the report (docs/figures/*.png, dataset/ai_results/summary.json)."""
import json
import pickle
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab import lab, quant
from ai_lab.data import load_recordings, FS
from ai_lab.evalx import event_report, wilson, WIN, rec_slices
from ai_lab.features import FEAT42_NAMES
from ai_lab.models import load_header_mlp, shipped_mlp_scores

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "dataset" / "ai_results"
FIG = ROOT / "docs" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

recs = load_recordings()
V = lab.get_views(recs, ("fw", "hifd"))
W = V["fw"]


def sc(*files):
    arr = []
    for f in files:
        if (RES / f).is_file():
            arr += list(np.load(RES / f)["scores"])
    return np.mean(arr, axis=0) if arr else None


S = {
    "MLP-42 (aug)": sc("loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz"),
    "CNN 1D (aug)": sc("loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz"),
    "MLP + CNN (ensemble)": None,
    "MLP-30 inv. feats": sc("loso_mlpinv_fw_aug.npz"),
    "Logistic regression": sc("loso_lr_fw_aug.npz"),
    "Random forest": sc("loso_rf_fw_aug.npz"),
    "Decision tree": sc("loso_dt_fw_aug.npz"),
    "MLP trained on HIFD-as-published": sc("loso_mlp_hifd.npz"),
}
S["MLP + CNN (ensemble)"] = (S["MLP-42 (aug)"] + S["CNN 1D (aug)"]) / 2
S = {k: v for k, v in S.items() if v is not None}

# ------------------------------------------------------------------ 1. operating curves + rule baselines
b1 = json.load(open(RES / "b1_baselines.json"))
fig, ax = plt.subplots(figsize=(7.5, 5))
summary = {"operating": {}}
for name, s in S.items():
    curve, hours = lab.operating_curve(recs, W, s)
    c = curve[np.argsort(-curve[:, 0])]   # high threshold -> low threshold: FA/h grows
    ax.step(c[:, 2], c[:, 1], where="post", lw=2.2 if "ensemble" in name else 1.3, label=name)
    summary["operating"][name] = {f"recall@FA<={k}/h": lab.recall_at_fa(curve, k) for k in (1, 2, 5, 10)}
for label, key, mk in (("Threshold only (25 m/s²)", "threshold only", "s"), ("Firmware FSM (strict)", "FSM (still after impact)", "^")):
    r = b1[key]
    ax.scatter([r["fa_per_h"]], [r["recall"]], marker=mk, s=70, color="k", zorder=5)
    ax.annotate(label, (r["fa_per_h"], r["recall"]), textcoords="offset points", xytext=(-110 if mk == "s" else 6, -14 if mk == "s" else 6), fontsize=8)
ax.set_xscale("symlog", linthresh=1)
ax.set_xlim(0, 120)
ax.set_ylim(0, 1.02)
ax.set_xlabel("False alerts per hour (21 held-out subjects, 1.95 h of daily activities)")
ax.set_ylabel("Fall detection rate (event level)")
ax.set_title("Leave-one-subject-out operating curves (firmware signal chain)")
ax.grid(alpha=0.3)
ax.legend(fontsize=7, loc="center right", bbox_to_anchor=(1.0, 0.45))
fig.tight_layout()
fig.savefig(FIG / "fig_operating_curves.png", dpi=150)
plt.close(fig)

# ------------------------------------------------------------------ 2. ablation
rows = []
for label, f in (("final recipe (MLP, fw)", "loso_mlp_fw.json"), ("no event-centred labels", "loso_abl_legacy.json"),
                 ("no hard negatives", "loso_abl_nohard.json"), ("no class weights", "loso_abl_noweight.json"),
                 ("without post-impact variance", "loso_abl_nopostvar.json"), ("trained on HIFD as published", "loso_mlp_hifd.json")):
    p = RES / f
    if p.is_file():
        j = json.load(open(p))
        rows.append((label, j["rep"]["detected"], j["rep"]["n_fall"], j["rep"]["false_alerts"], j["recall_at_fa"]))
if rows:
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    names = [r[0] for r in rows]
    ax[0].barh(names, [r[1] / r[2] for r in rows], color="#4c78a8")
    ax[0].set_xlim(0, 1.05); ax[0].set_title("Event recall (per-fold threshold)"); ax[0].invert_yaxis()
    ax[1].barh(names, [r[3] for r in rows], color="#e45756")
    ax[1].set_title("False alerts in 1.95 h"); ax[1].invert_yaxis(); ax[1].set_yticklabels([])
    fig.tight_layout(); fig.savefig(FIG / "fig_ablation.png", dpi=150); plt.close(fig)
    summary["ablation"] = [{"name": r[0], "detected": r[1], "n_fall": r[2], "false_alerts": r[3], "recall_at_fa": r[4]} for r in rows]

# ------------------------------------------------------------------ 3. false alerts by scenario: shipped vs final
cfg = json.load(open(RES / "fusion.json"))
thr = cfg["thr_fused"]
ens = S["MLP + CNN (ensemble)"]
ev_final = event_report(recs, W, ens, thr)
h = load_header_mlp(ROOT / "dataset" / "tiny_fall_model.h.orig")
Wh = V["hifd"]
ev_ship = event_report(recs, Wh, shipped_mlp_scores(Wh.F42, h), h["thr"])  # shipped model on its own domain (train+val+test subjects mixed)
scen = sorted(set(list(ev_final["false_by_scenario"]) + list(ev_ship["false_by_scenario"])))
summary["final_ensemble"] = {k: ev_final[k] for k in ("detected", "n_fall", "recall", "false_alerts", "hours", "fa_per_h", "fa_upper95", "missed", "false_by_scenario")}
summary["final_ensemble"]["recall_ci"] = ev_final["recall_ci"]

# ------------------------------------------------------------------ 4. probability timelines
sl = rec_slices(W)
picks = [("s19/fall/fall1", "fall"), ("s20/fall/fall3", "fall"), ("s19/non-fall/clap", "clap"), ("s20/non-fall/bed", "bed"), ("s21/non-fall/walk", "walk")]
names = {r.name: i for i, r in enumerate(recs)}
fig, axs = plt.subplots(len(picks), 1, figsize=(8, 8), sharey=True)
for ax, (nm, kind) in zip(axs, picks):
    if nm not in names or names[nm] not in sl:
        ax.set_visible(False); continue
    ri = names[nm]; s = sl[ri]
    t = (W.start[s] + WIN) / FS
    ax.plot(t, ens[s], color="#d62728" if kind == "fall" else "#1f77b4", lw=1.6)
    ax.axhline(thr, color="gray", ls="--", lw=0.9)
    if recs[ri].center is not None:
        ax.axvline(recs[ri].center / FS, color="k", ls=":", lw=1)
        ax.text(recs[ri].center / FS + 0.2, 0.55, "impact", fontsize=8)
    ax.set_ylabel("p(fall)"); ax.set_title(nm, fontsize=9, loc="left"); ax.set_ylim(-0.02, 1.02); ax.grid(alpha=0.25)
axs[-1].set_xlabel("time (s) — probability computed from the 2 s window ending at that time")
fig.tight_layout(); fig.savefig(FIG / "fig_probability_timelines.png", dpi=150); plt.close(fig)

# ------------------------------------------------------------------ 5. permutation importance (deployed MLP, subjects 19-21)
fm = pickle.load(open(RES / "final_models.pkl", "rb"))
te = W.sub(W.subj >= 19)
keep = te.keep
from sklearn.metrics import roc_auc_score
base = roc_auc_score(te.y[keep], fm["mlp"].predict(te)[keep])
rng = np.random.default_rng(0)
imp = []
F0 = te.F42.copy()
for j in range(42):
    drops = []
    for _ in range(5):
        te.F42 = F0.copy(); te.F42[:, j] = rng.permutation(F0[:, j])
        drops.append(base - roc_auc_score(te.y[keep], fm["mlp"].predict(te)[keep]))
    imp.append(float(np.mean(drops)))
te.F42 = F0
order = np.argsort(imp)[::-1][:15]
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.barh([FEAT42_NAMES[i] for i in order][::-1], [imp[i] for i in order][::-1], color="#54a24b")
ax.set_xlabel("AUC drop when the feature is shuffled (subjects 19-21)")
ax.set_title(f"Permutation importance, deployed MLP (AUC {base:.4f})")
fig.tight_layout(); fig.savefig(FIG / "fig_feature_importance.png", dpi=150); plt.close(fig)
summary["importance_top"] = [(FEAT42_NAMES[i], imp[i]) for i in order[:10]]
summary["mlp_auc_test"] = float(base)

json.dump(summary, open(RES / "summary.json", "w"), indent=1, default=float)
print("figures written to", FIG)
print(json.dumps(summary["operating"], indent=1))
print(summary["final_ensemble"])
