"""Vietnamese, print-sized versions of paper figures 2-4 (docs/figures/*_vi.png).

Same data as tools/ai_lab/make_figures.py (same loaders, same arrays; only labels, fonts and sizes
differ). The English figures are not touched.  Sizes are real print sizes (page 178 mm text width,
column 85 mm) so that a 8 pt font in the figure is 8 pt on paper.

    .venv-ds/Scripts/python.exe tools/ai_lab/make_figures_vi.py [--dump data.json]
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab import lab
from ai_lab.data import load_recordings, FS
from ai_lab.evalx import WIN, rec_slices

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "dataset" / "ai_results"
FIG = ROOT / "docs" / "figures"
MM = 1 / 25.4

# ---- font with Vietnamese diacritics (Arial is sans, legible at 7-8 pt)
for p in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
    f = Path("C:/Windows/Fonts") / p
    if f.is_file():
        fm.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": ["Arial", "DejaVu Sans"],
    "font.size": 8,
    "axes.titlesize": 8.5,
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "axes.unicode_minus": False,
    "savefig.dpi": 300,
})


def vn(x, nd=2):
    """Vietnamese decimal comma."""
    return f"{x:.{nd}f}".replace(".", ",")


# ---------------------------------------------------------------- data (identical to make_figures.py)
def sc(*files):
    arr = []
    for f in files:
        if (RES / f).is_file():
            arr += list(np.load(RES / f)["scores"])
    return np.mean(arr, axis=0) if arr else None


# key = English key used by make_figures.py (keeps the order/colour cycle), value = Vietnamese legend label
LABEL_VI = {
    "MLP-42 (aug)": "MLP-42 (tăng cường)",
    "CNN 1D (aug)": "CNN 1D (tăng cường)",
    "MLP + CNN (ensemble)": "MLP + CNN (tổ hợp)",
    "MLP-30 inv. feats": "MLP-30 (đặc trưng bất biến)",
    "Logistic regression": "Hồi quy logistic",
    "Random forest": "Rừng ngẫu nhiên",
    "Decision tree": "Cây quyết định",
    "MLP trained on HIFD-as-published": "MLP huấn luyện trên HIFD nguyên bản",
}


def load_all():
    recs = load_recordings()
    V = lab.get_views(recs, ("fw", "hifd"))
    W = V["fw"]
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
    return recs, W, S


def data_curves(recs, W, S):
    b1 = json.load(open(RES / "b1_baselines.json"))
    curves = {}
    for name, s in S.items():
        curve, hours = lab.operating_curve(recs, W, s)
        c = curve[np.argsort(-curve[:, 0])]
        curves[name] = (c[:, 2], c[:, 1])          # (fa_per_h, recall) as plotted by ax.step
    base = {k: (b1[k]["fa_per_h"], b1[k]["recall"]) for k in ("threshold only", "FSM (still after impact)")}
    return curves, base


def data_ablation():
    rows = []
    for label, f in (("final", "loso_mlp_fw.json"), ("legacy", "loso_abl_legacy.json"), ("nohard", "loso_abl_nohard.json"),
                     ("noweight", "loso_abl_noweight.json"), ("nopostvar", "loso_abl_nopostvar.json"), ("hifd", "loso_mlp_hifd.json")):
        p = RES / f
        if p.is_file():
            j = json.load(open(p))
            rows.append((label, j["rep"]["detected"], j["rep"]["n_fall"], j["rep"]["false_alerts"]))
    return rows


PICKS = [("s19/fall/fall1", "fall", "ngã"), ("s20/fall/fall3", "fall", "ngã"), ("s19/non-fall/clap", "clap", "vỗ tay"),
         ("s20/non-fall/bed", "bed", "nằm giường"), ("s21/non-fall/walk", "walk", "đi bộ")]


def data_timelines(recs, W, ens):
    thr = json.load(open(RES / "fusion.json"))["thr_fused"]
    sl = rec_slices(W)
    names = {r.name: i for i, r in enumerate(recs)}
    out = []
    for nm, kind, vi in PICKS:
        if nm not in names or names[nm] not in sl:
            continue
        ri = names[nm]; s = sl[ri]
        t = (W.start[s] + WIN) / FS
        out.append(dict(name=nm, kind=kind, vi=vi, t=t, p=ens[s],
                        center=None if recs[ri].center is None else recs[ri].center / FS))
    return thr, out


# ---------------------------------------------------------------- figures
def fig_curves(curves, base):
    fig, ax = plt.subplots(figsize=(178 * MM, 120 * MM))
    for name, (x, y) in curves.items():
        ens = "ensemble" in name
        ax.step(x, y, where="post", lw=2.2 if ens else 1.2, label=LABEL_VI[name], zorder=3 if ens else 2)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(0, 120)
    ax.set_ylim(0, 1.02)
    # reference points, labelled away from the curves with an arrow
    spec = (("Chỉ ngưỡng 25 m/s²", "threshold only", "s", (0.985, 0.86), "right"),
            ("FSM luật gốc (nghiêm ngặt)", "FSM (still after impact)", "^", (0.27, 0.06), "left"))
    for lab_vi, key, mk, (tx, ty), ha in spec:
        x, y = base[key]
        ax.scatter([x], [y], marker=mk, s=45, color="k", zorder=6)
        ax.annotate(lab_vi, xy=(x, y), xytext=(tx, ty), textcoords="axes fraction", fontsize=8, ha=ha, va="center",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.4", lw=0.5), zorder=7,
                    arrowprops=dict(arrowstyle="-|>", color="k", lw=0.8, shrinkA=0, shrinkB=3, mutation_scale=8))
    ax.set_xlabel("Số báo nhầm mỗi giờ (21 người giữ lại, 1,95 giờ sinh hoạt; thang log)")
    ax.set_ylabel("Tỉ lệ phát hiện ca ngã (theo sự kiện)")
    ax.set_title("Đường cong vận hành, huấn luyện bỏ-một-người (chuỗi tín hiệu của firmware)")
    ax.grid(alpha=0.3, lw=0.5)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.0), framealpha=0.95, edgecolor="0.7", fontsize=7.2, borderaxespad=0.3)
    fig.tight_layout(pad=0.4)
    fig.savefig(FIG / "fig_operating_curves_vi.png")
    plt.close(fig)


def fig_timelines(thr, tl):
    n = len(tl)
    fig, axs = plt.subplots(n, 1, figsize=(85 * MM, 100 * MM), sharex=True, sharey=True)
    for ax, d in zip(np.atleast_1d(axs), tl):
        col = "#d62728" if d["kind"] == "fall" else "#1f77b4"
        ax.plot(d["t"], d["p"], color=col, lw=1.2)
        ax.axhline(thr, color="gray", ls="--", lw=0.8)
        if d["center"] is not None:
            ax.axvline(d["center"], color="k", ls=":", lw=0.9)
        ax.set_ylim(-0.05, 1.15)
        ax.set_yticks([0, 0.5, 1]); ax.set_yticklabels(["0", "0,5", "1"])
        ax.grid(alpha=0.25, lw=0.5)
        ax.text(0.99, 0.70, f"{d['name']}  ({d['vi']})", transform=ax.transAxes, fontsize=7.5, va="top", ha="right",
                zorder=6)
        ax.tick_params(labelsize=7)
    a0 = np.atleast_1d(axs)[0]
    d0 = tl[0]
    if d0["center"] is not None:
        a0.text(d0["center"] - 0.3, 0.45, "va đập", fontsize=7.5, va="center", ha="right")
    a0.text(a0.get_xlim()[0] + 0.5, thr + 0.02, f"ngưỡng {vn(thr)}", fontsize=7, color="0.35", ha="left", va="bottom")
    np.atleast_1d(axs)[-1].set_xlabel("thời gian (s)", fontsize=7.5)
    fig.supylabel("xác suất p(ngã)", fontsize=8)
    fig.tight_layout(pad=0.3, h_pad=0.3)
    fig.savefig(FIG / "fig_probability_timelines_vi.png")
    plt.close(fig)


ABL_VI = {
    "final": "công thức cuối",
    "legacy": "không gán nhãn theo sự kiện",
    "nohard": "không hard-negative",
    "noweight": "không trọng số lớp",
    "nopostvar": "không phương sai sau va đập",
    "hifd": "huấn luyện trên HIFD nguyên bản",
}


def fig_ablation(rows):
    names = [ABL_VI[r[0]] + " (MLP)" if r[0] == "final" else ABL_VI[r[0]] for r in rows]
    fig, ax = plt.subplots(1, 2, figsize=(178 * MM, 56 * MM), gridspec_kw=dict(width_ratios=[1.45, 1]))
    rec = [r[1] / r[2] for r in rows]
    ax[0].barh(names, rec, color="#4c78a8", height=0.7)
    for i, r in enumerate(rows):
        ax[0].text(rec[i] + 0.01, i, f"{r[1]}/{r[2]}", va="center", fontsize=7.5)
    ax[0].set_xlim(0, 1.15); ax[0].set_xticks([0, 0.25, 0.5, 0.75, 1]); ax[0].set_xticklabels(["0", "0,25", "0,5", "0,75", "1"])
    ax[0].set_title("Tỉ lệ phát hiện ca ngã (ngưỡng theo fold)"); ax[0].invert_yaxis()
    fa = [r[3] for r in rows]
    ax[1].barh(names, fa, color="#e45756", height=0.7)
    for i, v in enumerate(fa):
        ax[1].text(v + 0.3, i, str(v), va="center", fontsize=7.5)
    ax[1].set_xlim(0, max(fa) * 1.15 + 1)
    ax[1].set_title("Số báo nhầm trong 1,95 giờ"); ax[1].invert_yaxis(); ax[1].set_yticklabels([])
    for a in ax:
        a.grid(axis="x", alpha=0.3, lw=0.5); a.set_axisbelow(True)
    fig.tight_layout(pad=0.4, w_pad=0.8)
    fig.savefig(FIG / "fig_ablation_vi.png")
    plt.close(fig)


def main():
    recs, W, S = load_all()
    curves, base = data_curves(recs, W, S)
    rows = data_ablation()
    thr, tl = data_timelines(recs, W, S["MLP + CNN (ensemble)"])
    fig_curves(curves, base)
    fig_ablation(rows)
    fig_timelines(thr, tl)
    if "--dump" in sys.argv:
        out = {"curves": {k: [list(map(float, v[0])), list(map(float, v[1]))] for k, v in curves.items()},
               "base": {k: list(map(float, v)) for k, v in base.items()},
               "ablation": [list(r) for r in rows], "thr": float(thr),
               "timelines": [dict(name=d["name"], t=list(map(float, d["t"])), p=list(map(float, d["p"])), center=d["center"]) for d in tl]}
        json.dump(out, open(sys.argv[sys.argv.index("--dump") + 1], "w"))
    print("wrote", [p.name for p in sorted(FIG.glob("*_vi.png"))])


if __name__ == "__main__":
    main()
