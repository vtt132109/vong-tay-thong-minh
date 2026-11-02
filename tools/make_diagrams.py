"""Draw the two block diagrams of BAO_CAO.md as PNG (docs/figures/fig_system.png, fig_states.png).

Run with the project venv (matplotlib): .venv-ds/Scripts/python.exe tools/make_diagrams.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

BLUE, GREEN, ORANGE, GREY, RED, PURPLE = "#dbe8fb", "#dff2dc", "#fde7c8", "#ececec", "#f9d5d3", "#e6dcf5"


def box(ax, x, y, w, h, text, color, fs=9, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.2",
                                fc=color, ec="#333", lw=1.1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal")


def arrow(ax, p, q, text=None, rad=0.0, fs=8, dx=0, dy=0):
    ax.annotate("", xy=q, xytext=p,
                arrowprops=dict(arrowstyle="-|>", lw=1.3, color="#222", connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((p[0] + q[0]) / 2 + dx, (p[1] + q[1]) / 2 + dy, text, ha="center", va="center", fontsize=fs,
                bbox=dict(fc="white", ec="none", pad=0.6))


def system():
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.set_xlim(0, 122)
    ax.set_ylim(0, 46)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((1, 1), 87, 44, boxstyle="round,pad=0.3,rounding_size=2", fc="#fafafa", ec="#555", lw=1.5, ls="--"))
    ax.text(3, 43, "Vòng tay ESP32-S3 (160 MHz)", fontsize=10, fontweight="bold", va="center")

    box(ax, 3, 29, 12, 8, "MPU6050\n50 Hz", BLUE)
    box(ax, 18, 29, 16, 8, "Hiệu chỉnh gyro\n+ loại trọng lực\n(α = 0,98)", BLUE)
    box(ax, 37, 29, 10, 8, "Cửa sổ\n100 × 6", BLUE)
    box(ax, 50, 34, 12, 6, "MLP 42→16→1", GREEN)
    box(ax, 50, 24.5, 12, 6, "CNN 1D int8", GREEN)
    box(ax, 66, 29, 18, 8, "Trung bình xác suất\nngưỡng 0,87", GREEN, bold=True)
    box(ax, 66, 16, 18, 8, "FSM luật\n(công tắc chế độ AI)", ORANGE)
    box(ax, 66, 4, 18, 8, "Còi + OLED + nút", RED)
    box(ax, 3, 6, 12, 7, "MAX30100\n100 Hz", BLUE)
    box(ax, 18, 6, 16, 7, "Lọc PPG\nHR / SpO2", BLUE)
    box(ax, 37, 6, 14, 7, "Health guard", ORANGE)

    arrow(ax, (15, 33), (18, 33))
    arrow(ax, (34, 33), (37, 33))
    arrow(ax, (47, 34), (50, 37))
    arrow(ax, (47, 32), (50, 28))
    arrow(ax, (62, 37), (66, 34))
    arrow(ax, (62, 27.5), (66, 31))
    arrow(ax, (75, 29), (75, 24))
    arrow(ax, (75, 16), (75, 12))
    ax.plot([9, 9, 66], [29, 20, 20], color="#222", lw=1.3)
    arrow(ax, (60, 20), (66, 20))
    arrow(ax, (15, 9.5), (18, 9.5))
    arrow(ax, (34, 9.5), (37, 9.5))
    arrow(ax, (51, 9.5), (66, 8))

    box(ax, 96, 31, 24, 9, "Dashboard LAN\n(HTTP, header X-Bioband)", PURPLE)
    box(ax, 96, 17, 24, 9, "Broker MQTT công khai\n(chỉ publish)", GREY)
    box(ax, 96, 4, 24, 9, "remote.html\n(chỉ xem)", PURPLE)
    arrow(ax, (88, 35), (96, 35.5))
    arrow(ax, (88, 22), (96, 21.5))
    arrow(ax, (108, 17), (108, 13))
    fig.tight_layout()
    fig.savefig(OUT / "fig_system.png", dpi=170)
    plt.close(fig)


def states():
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 56)
    ax.axis("off")
    pos = {"IDLE": (12, 28), "FREE_FALL": (40, 38), "IMPACT": (68, 38), "COUNTDOWN": (92, 28),
           "ALARM": (92, 8), "SNOOZE": (52, 8), "PANIC_SOS": (12, 8)}
    col = {"IDLE": GREEN, "FREE_FALL": ORANGE, "IMPACT": ORANGE, "COUNTDOWN": RED, "ALARM": RED,
           "SNOOZE": GREY, "PANIC_SOS": RED}
    for k, (x, y) in pos.items():
        box(ax, x - 9, y - 3.5, 18, 7, k, col[k], fs=9.5, bold=True)
    arrow(ax, (14, 31.8), (32, 36), "|a| < 5 m/s²\n(3 mẫu)", dx=-4, dy=5)
    arrow(ax, (49, 38), (59, 38), "|a| ≥ 25", dy=2.4)
    arrow(ax, (8, 31.8), (64, 41.8), None, rad=-0.42)
    ax.text(34, 53, "va đập trực tiếp: |a| ≥ 25 m/s² (cooldown 2 s)", ha="center", fontsize=8,
            bbox=dict(fc="white", ec="none", pad=0.6))
    arrow(ax, (74, 34.5), (86, 31.8), "bất động\n(+ AI hỗ trợ)", dx=8, dy=3.2)
    arrow(ax, (62, 34.5), (21, 29.5), "còn cử động", dy=-3.2)
    arrow(ax, (21, 25.5), (83, 25.5), "AI báo ngã (chế độ AI BẬT)", dy=-2.6)
    arrow(ax, (92, 24.5), (92, 11.5), "hết 10 s", dx=7)
    arrow(ax, (85, 24.5), (58, 11.5), "nhấn nút", dx=-3, dy=3)
    arrow(ax, (83, 8), (61, 8), "nhấn nút", dy=2.4)
    arrow(ax, (44, 11.5), (16, 24.5), "sau 20 s", dx=-5, dy=-3)
    arrow(ax, (12, 24.5), (12, 11.5), "giữ nút 3 s", dx=-8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_states.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    system()
    states()
    print("diagrams written to", OUT)
