"""Poster versions of the two figures (large fonts, Vietnamese labels): docs/figures/poster_system.png, poster_curves.png.

Run with the project venv: .venv-ds/Scripts/python.exe tools/make_poster_figs.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / "docs" / "figures"
RES = ROOT / "dataset" / "ai_results"

BLUE, GREEN, ORANGE, GREY, RED, PURPLE = "#dbe8fb", "#dff2dc", "#fde7c8", "#ececec", "#f9d5d3", "#e6dcf5"


def box(ax, x, y, w, h, text, color, fs=12.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.0", fc=color, ec="#333", lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal",
            linespacing=1.15)


def arrow(ax, p, q):
    ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#222"))


def system():
    fig, ax = plt.subplots(figsize=(10, 3.85))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 38.5)
    ax.axis("off")
    # row A: fall path
    box(ax, 1, 23, 12, 11, "MPU6050\n50 Hz", BLUE)
    box(ax, 17, 23, 14, 11, "Bỏ trọng lực\ncửa sổ 2 s", BLUE)
    box(ax, 35, 28, 14, 6.5, "MLP 42→16→1", GREEN, fs=11.5)
    box(ax, 35, 20.5, 14, 6.5, "CNN 1D int8", GREEN, fs=11.5)
    box(ax, 53, 23, 14, 11, "Trung bình\nxác suất\n≥ 0,87", GREEN, bold=True)
    box(ax, 71, 23, 13, 11, "FSM luật\n+ công tắc\nchế độ AI", ORANGE)
    box(ax, 88, 23, 11, 11, "Còi · OLED\nnút hủy", RED, fs=11.5)
    for p, q in (((13, 28.5), (17, 28.5)), ((31, 31), (35, 31)), ((31, 26), (35, 24)), ((49, 31), (53, 30)),
                 ((49, 24), (53, 27)), ((67, 28.5), (71, 28.5)), ((84, 28.5), (88, 28.5))):
        arrow(ax, p, q)
    # row B: PPG path and outputs
    box(ax, 1, 3, 12, 11, "MAX30100\n100 Hz", BLUE)
    box(ax, 17, 3, 14, 11, "Lọc PPG\nHR · SpO2", BLUE)
    box(ax, 35, 3, 14, 11, "Health\nguard", ORANGE)
    box(ax, 51, 3, 21, 11, "Dashboard LAN\n(HTTP + header)", PURPLE, fs=11.5)
    box(ax, 75, 3, 24, 11, "MQTT chỉ publish\n→ remote.html", GREY, fs=11.5)
    for p, q in (((13, 8.5), (17, 8.5)), ((31, 8.5), (35, 8.5))):
        arrow(ax, p, q)
    arrow(ax, (77.5, 23), (77.5, 14.5))
    fig.tight_layout(pad=0.3)
    fig.savefig(OUT / "poster_system.png", dpi=220)
    plt.close(fig)


def curves():
    from ai_lab import lab
    from ai_lab.data import load_recordings

    recs = load_recordings()
    W = lab.get_views(recs, ("fw",))["fw"]

    def sc(*files):
        arr = []
        for f in files:
            if (RES / f).is_file():
                arr += list(np.load(RES / f)["scores"])
        return np.mean(arr, axis=0)

    mlp = sc("loso_mlp_fw_aug.npz", "loso_mlp_fw_aug_s12.npz")
    cnn = sc("loso_cnn_fw_aug.npz", "loso_cnn_fw_aug_s12.npz")
    series = [("MLP + CNN (đã nạp)", (mlp + cnn) / 2, "#1E9FB5", 4.0), ("MLP 42 đặc trưng", mlp, "#4C78A8", 2.0),
              ("CNN 1D int8", cnn, "#F58518", 2.0), ("Hồi quy logistic", sc("loso_lr_fw_aug.npz"), "#999999", 2.0),
              ("Random forest", sc("loso_rf_fw_aug.npz"), "#B279A2", 2.0)]
    b1 = json.load(open(RES / "b1_baselines.json"))
    fig, ax = plt.subplots(figsize=(6.2, 4.3))
    for name, s, color, lw in series:
        curve, _ = lab.operating_curve(recs, W, s)
        c = curve[np.argsort(-curve[:, 0])]
        ax.step(c[:, 2], c[:, 1], where="post", color=color, lw=lw, label=name)
    r = b1["threshold only"]
    ax.scatter([r["fa_per_h"]], [r["recall"]], marker="s", s=90, color="k", zorder=5)
    ax.annotate("ngưỡng 25 m/s²", (r["fa_per_h"], r["recall"]), xytext=(-105, -22), textcoords="offset points", fontsize=11)
    r = b1["FSM (still after impact)"]
    ax.scatter([r["fa_per_h"]], [r["recall"]], marker="^", s=100, color="k", zorder=5)
    ax.annotate("FSM luật gốc", (r["fa_per_h"], r["recall"]), xytext=(8, 4), textcoords="offset points", fontsize=11)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 1.03)
    ax.set_xlabel("Số báo nhầm mỗi giờ", fontsize=13)
    ax.set_ylabel("Tỉ lệ phát hiện ca ngã", fontsize=13)
    ax.tick_params(labelsize=11.5)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=10.5, loc="center right", bbox_to_anchor=(1.0, 0.42), framealpha=0.95)
    fig.tight_layout(pad=0.4)
    fig.savefig(OUT / "poster_curves.png", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    system()
    curves()
    print("poster figures written")
