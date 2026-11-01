"""Offline ensembles from saved LOSO scores (all out-of-sample). Compares operating points."""
import sys, itertools
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings
from ai_lab import lab
recs = load_recordings(); V = lab.get_views(recs); W = V['fw']
R = Path(__file__).resolve().parents[2] / "dataset" / "ai_results"
names = [n for n in ("mlp_fw_aug", "mlpinv_fw_aug", "mlpinv32_fw_aug", "mlpall_fw_aug", "cnn_fw", "cnn_fw_aug", "rf_fw_aug", "lr_fw_aug") if (R / f"loso_{n}.npz").is_file()]
S = {n: np.load(R / f"loso_{n}.npz")["scores"][0] for n in names}
def row(label, s):
    c, hours = lab.operating_curve(recs, W, s)
    r = [lab.recall_at_fa(c, k) for k in (1, 2, 3, 5, 10)]
    # AUC-like: mean recall over FA budgets 0.5..10
    print(f"{label:34s} recall@FA/h<=1/2/3/5/10: " + " ".join(f"{x:.3f}" for x in r))
    return r
print(f"hours of evaluation data: {lab.operating_curve(recs, W, S[names[0]], grid=[0.5])[1]:.2f}")
for n in names: row(n, S[n])
print("--- ensembles (mean probability)")
for a, b in itertools.combinations([n for n in names if n not in ("lr_fw_aug", "rf_fw_aug")], 2):
    row(f"{a}+{b}", (S[a] + S[b]) / 2)
if "cnn_fw_aug" in S and "mlpinv_fw_aug" in S and "mlp_fw_aug" in S:
    row("cnn_aug+mlpinv+mlp42", (S["cnn_fw_aug"] + S["mlpinv_fw_aug"] + S["mlp_fw_aug"]) / 3)
    row("geo-mean cnn_aug*mlpinv", np.sqrt(S["cnn_fw_aug"] * S["mlpinv_fw_aug"]))
    row("min(cnn_aug, mlpinv) = AND", np.minimum(S["cnn_fw_aug"], S["mlpinv_fw_aug"]))
