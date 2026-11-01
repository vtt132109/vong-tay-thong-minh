import sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings
from ai_lab import lab, quant
from ai_lab.evalx import event_report
recs = load_recordings(); V = lab.get_views(recs); W = V['fw']
tr = W.subj<=15; va=(W.subj>=16)&(W.subj<=18); te=W.subj>=19
fm = lab.fit_cnn(W.sub(tr), W.sub(va), 0)
Wt = W.sub(te); pf = fm.predict(Wt)
q = quant.quantize(fm, W.sub(tr).X[::5])
pq = quant.int8_forward(q, Wt.X)
print('params', sum(p.numel() for p in fm.model.parameters()), 'MACs', quant.macs(q))
print('float vs int8: max|dp| %.4f mean|dp| %.5f corr %.4f' % (np.abs(pf-pq).max(), np.abs(pf-pq).mean(), np.corrcoef(pf,pq)[0,1]))
for thr in (0.5,0.8,0.9):
    print(thr, 'decision flips', int(((pf>=thr)!=(pq>=thr)).sum()), 'of', len(pf))
for name,p in (('float',pf),('int8',pq)):
    ev=event_report(recs,Wt,p,0.9); print(name,'event',ev['detected'],'/',ev['n_fall'],'FA',ev['false_alerts'])
