import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_lab.data import load_recordings
from ai_lab import lab
recs = load_recordings()
t=time.time(); V = lab.get_views(recs); print('views', {k:len(v) for k,v in V.items()}, f'{time.time()-t:.0f}s')
import numpy as np
W = V['fw']
tr = W.subj<=15; va=(W.subj>=16)&(W.subj<=18); te=W.subj>=19
for name, fn in (('mlp', lambda a,b: lab.fit_mlp(a,b,0)), ('cnn', lambda a,b: lab.fit_cnn(a,b,0)), ('rf', lambda a,b: lab.fit_sklearn('rf',a,b,0))):
    t=time.time(); fm=fn(W.sub(tr), W.sub(va)); s=fm.predict(W.sub(te)); 
    from ai_lab.evalx import event_report, window_report
    Wt=W.sub(te)
    for thr in (0.5,0.9,0.95):
        ev=event_report(recs,Wt,s,thr); wr=window_report(Wt,s,thr)
        print(f"{name} thr{thr}: event {ev['detected']}/{ev['n_fall']} FA {ev['false_alerts']} win P/R {wr['precision']:.2f}/{wr['recall']:.2f}  ({time.time()-t:.1f}s)")
