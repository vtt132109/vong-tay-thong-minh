"""Calibrate the rule-based FSM (stillness check) on HIFD train subjects, report on held-out subjects."""
import itertools, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings
from ai_lab.evalx import fsm_input, simulate_fsm, alerts_report

recs = load_recordings()
acc = [fsm_input(r) for r in recs]
tr = [i for i, r in enumerate(recs) if r.subject <= 15]
te = [i for i, r in enumerate(recs) if r.subject >= 16]
rows = []
for settle, window, vs in itertools.product((200, 600, 1000, 1500), (1500, 2000, 3000), (0.08, 0.3, 0.8, 1.5, 3.0)):
    vm = max(0.8, 5 * vs)
    al = {i: [a[0] / 1000 for a in simulate_fsm(acc[i], settle_ms=settle, window_ms=window, var_still=vs, var_motion=vm)]
          for i in range(len(recs))}
    a = alerts_report(recs, al, tr); b = alerts_report(recs, al, te)
    rows.append((settle, window, vs, a['recall'], a['fa_per_h'], b['recall'], b['fa_per_h'], b['detected'], b['n_fall'], b['false_alerts']))
rows.sort(key=lambda r: (-(r[3] - 0.02 * r[4])))
print("settle window var_still | TRAIN recall FA/h | HELD-OUT recall FA/h (det/n, FA)")
for r in rows[:15]:
    print(f"{r[0]:5d} {r[1]:5d} {r[2]:5.2f} | {r[3]:.2f} {r[4]:5.1f} | {r[5]:.2f} {r[6]:5.1f} ({r[7]}/{r[8]}, {r[9]})")
print("current firmware config (200,3000,0.08):", [r for r in rows if r[:3] == (200, 3000, 0.08)][0][3:])
json.dump(rows, open(Path(__file__).resolve().parents[2] / "dataset" / "ai_results" / "fsm_sweep.json", "w"))
