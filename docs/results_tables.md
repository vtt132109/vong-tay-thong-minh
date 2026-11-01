### Leave-one-subject-out, 21 held-out subjects, firmware signal chain

Operating-curve columns are threshold-free (recall of the 104 falls at the best threshold that keeps pooled false alerts at or below the budget; 1.95 h of daily activities, so 1 alert ≈ 0.51 /h). Seeds averaged where several exist.

| Model | Params | Seeds | Recall @ ≤1 FA/h | @ ≤2 | @ ≤5 | Per-fold threshold: recall (95 % CI) | FA/h |
|---|---|---|---|---|---|---|---|
| Logistic regression (42 feat.) | 43 | 1 | 0.000 | 0.000 | 0.913 | 93/104 (0.82–0.94) | 4.6 |
| Decision tree (depth 6) | depth 6 | 1 | 0.000 | 0.000 | 0.529 | 60/104 (0.48–0.67) | 3.6 |
| Random forest (60 trees) | 60 trees, depth<=8 | 1 | 0.837 | 0.875 | 0.904 | 70/104 (0.58–0.76) | 4.6 |
| MLP-42, trained on HIFD as published | 705 | 1 | 0.827 | 0.865 | 0.923 | 92/104 (0.81–0.93) | 4.1 |
| MLP-42, firmware-chain data | 705 | 1 | 0.846 | 0.913 | 0.962 | 97/104 (0.87–0.97) | 7.2 |
| MLP-42, firmware chain + augmentation | 705 | 3 | 0.942 | 0.942 | 0.971 | 98/104 (0.88–0.97) | 5.1 |
| MLP-30, orientation-invariant features | 513 | 1 | 0.904 | 0.923 | 0.971 | 97/104 (0.87–0.97) | 1.0 |
| 1D-CNN small (4-8-8) | 529 | 1 | 0.000 | 0.000 | 0.923 | 91/104 (0.80–0.93) | 3.6 |
| 1D-CNN (8-16-16), firmware-chain data | 1761 | 3 | 0.885 | 0.933 | 0.990 | 98/104 (0.88–0.97) | 4.1 |
| 1D-CNN (8-16-16), + augmentation | 1761 | 3 | 0.904 | 0.933 | 0.990 | 100/104 (0.91–0.98) | 5.1 |
| 1D-CNN large (16-32-32) | 6337 | 1 | 0.000 | 0.000 | 0.933 | 98/104 (0.88–0.97) | 5.1 |
| **Ensemble = mean(MLP-42 aug, CNN aug)** | 2466 | 3+3 | **0.962** | **0.971** | **0.981** | see below | |

### Deployed operating point (pooled out-of-sample scores)

| Rule | Threshold | Falls detected (95 % CI) | False alerts | FA/h (95 % upper) | Missed |
|---|---|---|---|---|---|
| Ensemble | 0.87 | 99/104 (0.89–0.98) | 0 in 1.95 h | 0.00 (1.9) | s01/fall/fall1, s03/fall/fall1, s14/fall/fall4, s17/fall/fall4, s21/fall/fall3 |
| MLP-42 alone | 0.90 | 98/104 (0.88–0.97) | 3 in 1.95 h | 1.54 (4.5) | s01/fall/fall1, s01/fall/fall4, s03/fall/fall1, s06/fall/fall2, s14/fall/fall4, s21/fall/fall3 |
| CNN alone | 0.90 | 97/104 (0.87–0.97) | 3 in 1.95 h | 1.54 (4.5) | s01/fall/fall1, s02/fall/fall3, s03/fall/fall1, s12/fall/fall6, s14/fall/fall4, s17/fall/fall4, s21/fall/fall3 |

### Rule-based baselines on all 21 subjects (no training involved)

| Rule | Falls detected | False alerts | FA/h | Median latency |
|---|---|---|---|---|
| Threshold ≥ 25 m/s² only | 104/104 | 177 in 1.80 h | 98.3 | 0.08 s |
| Firmware FSM, original constants | 6/104 | 14 in 1.80 h | 7.8 | 6.38 s |
| FSM recalibrated (settle 1.5 s, window 2 s, var < 0.8), subjects 16–21 | 31/31 | 9 in 0.50 h | 18.1 | 3.4 s |

### Ablation (MLP-42, seed 0, per-fold threshold)

| Variant | Falls detected | False alerts (1.95 h) | Recall @ ≤2 / ≤5 FA/h |
|---|---|---|---|
| Final recipe, MLP-42 (firmware chain) | 97/104 | 14 | 0.91 / 0.96 |
| No event-centred labels (recording-level labels) | 18/104 | 4 | 0.15 / 0.20 |
| No hard-negative weighting (bed/chair) | 94/104 | 12 | 0.92 / 0.96 |
| No class weights | 93/104 | 4 | 0.91 / 0.96 |
| Without feature 41 (variance of the last 0.5 s) | 94/104 | 13 | 0.93 / 0.95 |
