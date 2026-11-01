"""Post-training int8 quantisation of the 1D-CNN and a bit-exact numpy mirror of the C kernel.

Layout used by the firmware (channels-last): in[T][C]. Conv weights stored [cout][k][cin].
Requantisation is float: out = clamp(roundf(acc * M[c])) with M = s_in*s_w[c]/s_out (ReLU => 0..127).
"""
from __future__ import annotations

import numpy as np
import torch

from .lab import Fitted, cnn_input


def rnd(x):
    """C roundf(): half away from zero."""
    return np.where(x >= 0, np.floor(x + 0.5), -np.floor(-x + 0.5))


def _layers(model):
    return [(model.c1, 2, 2), (model.c2, 2, 2), (model.c3, 1, 1)]  # (conv, stride, pad)


def quantize(fm: Fitted, calib: np.ndarray, pct: float = 99.9) -> dict:
    """calib: (n,100,6) windows (training distribution)."""
    mu, sd = fm.norm
    m = fm.model
    xn = (cnn_input(calib) - mu) / sd                        # (n,7,100)
    s_in = float(np.percentile(np.abs(xn), pct) / 127.0)
    # float activations for calibration
    acts = []
    with torch.no_grad():
        h = torch.tensor(xn, dtype=torch.float32)
        for conv, _, _ in _layers(m):
            h = torch.relu(conv(h))
            acts.append(h.numpy())
    s_act = [float(np.percentile(a, pct) / 127.0) for a in acts]
    q = {"s_in": s_in, "mu": mu.reshape(-1), "sd": sd.reshape(-1), "layers": []}
    s_prev = s_in
    for (conv, stride, pad), s_out in zip(_layers(m), s_act):
        W = conv.weight.detach().numpy()                     # (cout,cin,k)
        b = conv.bias.detach().numpy()
        sw = np.maximum(np.abs(W).reshape(W.shape[0], -1).max(1), 1e-8) / 127.0
        Wq = np.clip(rnd(W / sw[:, None, None]), -127, 127).astype(np.int8)
        bq = rnd(b / (s_prev * sw)).astype(np.int32)
        M = (s_prev * sw / s_out).astype(np.float32)
        q["layers"].append({"W": np.ascontiguousarray(Wq.transpose(0, 2, 1)),  # [cout][k][cin]
                            "b": bq, "M": M, "stride": stride, "pad": pad, "s_out": s_out})
        s_prev = s_out
    q["fcw"] = m.fc.weight.detach().numpy().reshape(-1).astype(np.float32)
    q["fcb"] = float(m.fc.bias.detach().numpy().reshape(-1)[0])
    q["s_last"] = s_prev
    return q


def int8_forward(q: dict, X: np.ndarray) -> np.ndarray:
    """X: (n,100,6) -> probabilities, mirroring the C integer kernel."""
    x = cnn_input(X).transpose(0, 2, 1)                     # (n,100,7) channels-last
    xn = (x - q["mu"]) / q["sd"]
    h = np.clip(rnd(xn / q["s_in"]), -127, 127).astype(np.int32)   # int8 values
    for L in q["layers"]:
        n, T, cin = h.shape
        cout, k, _ = L["W"].shape
        pad, stride = L["pad"], L["stride"]
        Tout = (T + 2 * pad - k) // stride + 1
        hp = np.zeros((n, T + 2 * pad, cin), dtype=np.int32)
        hp[:, pad:pad + T] = h
        acc = np.zeros((n, Tout, cout), dtype=np.int64) + L["b"][None, None, :]
        for kk in range(k):
            seg = hp[:, kk:kk + stride * Tout:stride][:, :Tout]          # (n,Tout,cin)
            acc += np.einsum("ntc,oc->nto", seg, L["W"][:, kk, :].astype(np.int32))
        y = rnd(acc.astype(np.float32) * L["M"][None, None, :])
        h = np.clip(y, 0, 127).astype(np.int32)
    fmax = h.max(1).astype(np.float32) * q["s_last"]
    fmean = h.sum(1).astype(np.float32) / h.shape[1] * q["s_last"]
    f = np.concatenate([fmax, fmean], axis=1)
    z = f @ q["fcw"] + q["fcb"]
    return 1.0 / (1.0 + np.exp(-z))


def macs(q: dict, T: int = 100) -> int:
    total = 0
    cin = 7
    for L in q["layers"]:
        cout, k, _ = L["W"].shape
        Tout = (T + 2 * L["pad"] - k) // L["stride"] + 1
        total += Tout * cout * k * cin
        T, cin = Tout, cout
    return total
