"""Models: shipped MLP (from header), torch MLP, torch 1D-CNN, sklearn baselines."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "include" / "tiny_fall_model.h"


# ----------------------------------------------------------------------------- shipped MLP
def load_header_mlp(path: Path = HEADER) -> dict:
    txt = path.read_text(encoding="utf-8")

    def arr(name):
        m = re.search(r"%s(?:\[[0-9]+\])+\s*=\s*\{(.*?)\};" % name, txt, re.S)
        vals = re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?f?", m.group(1))
        return np.array([float(v.rstrip("f")) for v in vals], dtype=np.float64)

    return {"mean": arr("TINY_AI_MEAN"), "scale": arr("TINY_AI_SCALE"),
            "w1": arr("TINY_AI_W1").reshape(16, 42), "b1": arr("TINY_AI_B1"),
            "w2": arr("TINY_AI_W2"),
            "b2": float(re.search(r"TINY_AI_B2\s*=\s*([-0-9.eE+]+)f", txt).group(1)),
            "thr": float(re.search(r"TINY_AI_THRESHOLD\s+([0-9.]+)f", txt).group(1))}


def shipped_mlp_scores(F42: np.ndarray, h: dict | None = None) -> np.ndarray:
    h = h or load_header_mlp()
    z = (F42 - h["mean"]) / h["scale"]
    out = np.tanh(z @ h["w1"].T + h["b1"]) @ h["w2"] + h["b2"]
    return 1.0 / (1.0 + np.exp(-out))
