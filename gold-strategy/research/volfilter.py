import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
df,d=load(); df=df.reset_index(drop=True)
piv=df.pivot_table(index='tdayd',columns='ny_min',values='close',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
sm=d.c.shift(1).rolling(200).mean()
# reopen-bar volume, normalised on the FULL daily series (no survivorship in the rolling window)
v18=df[df.ny_min==1080].groupby('tdayd').volume.first()
v18_rel=(v18/v18.rolling(20).mean().shift(0))          # rolling uses past 20 incl. today's bar (known at 18:05)
base=pd.DataFrame({'ein':piv[1080],'xp':piv[20*60+55],'atr':atrp}).dropna()
base=base[(base.index.dayofweek!=0)&(d.c.shift(1).reindex(base.index)>sm.reindex(base.index))]
base['net']=base.xp-base.ein-0.30; base['R']=base.net/base.atr
base['vrel']=v18_rel.reindex(base.index)
b=base.dropna(subset=['vrel'])
print("="*96); print("A. REOPEN-BAR VOLUME — finer bins, is it monotonic?"); print("="*96)
q=pd.qcut(b.vrel,5,labels=False,duplicates='drop')
print("  quintile   n   mean_vrel   meanR      t     net$/tr")
for k in range(5):
    s=b[q==k]; m,t,n,sd=ts(s.R)
    print(f"    Q{k+1}     {n:4d}   {s.vrel.mean():6.2f}   {m:+.5f} {t:+6.2f}   {s.net.mean():+7.3f}")
rc=b.vrel.rank().corr(b.R.rank()); print(f"\n  Spearman(vrel, R) = {rc:+.4f}   t = {rc*np.sqrt(len(b)-2)/np.sqrt(1-rc**2):+.2f}")

print("\n"+"="*96); print("B. WALK-FORWARD on the volume filter (threshold frozen on IS)"); print("="*96)
ins=b[b.index<'2024-09-01']; oos=b[b.index>='2024-09-01']
thr=ins.vrel.quantile(2/3)
print(f"  IS top-tercile threshold vrel > {thr:.3f}")
for nm,x in [("IS ",ins),("OOS",oos)]:
    hi=x[x.vrel>thr]; lo=x[x.vrel<=thr]
    mh,th,nh,sh=ts(hi.R); ml,tl,nl,sl=ts(lo.R)
    print(f"  {nm}  high-vol: n={nh:3d} meanR={mh:+.5f} t={th:+5.2f} net$={hi.net.mean():+6.3f} Sh={mh/sh*np.sqrt(252):+5.2f}")
    print(f"       low-vol : n={nl:3d} meanR={ml:+.5f} t={tl:+5.2f} net$={lo.net.mean():+6.3f} Sh={ml/sl*np.sqrt(252):+5.2f}")
print("\n  -> if the OOS gap collapses, the volume filter is noise")

print("\n"+"="*96); print("C. EXIT OPTIMISATION for Strategy A (entry 18:05, skip Sunday, >SMA200)"); print("="*96)
# rebuild intraday path for trailing / target exits
g=df.groupby('tdayd')
idx={k:v for k,v in g.indices.items()}
O=df.open.values;H=df.high.values;L=df.low.values;C=df.close.values;NM=df.ny_min.values
days=[x for x in base.index]
def run(exit_min=20*60+55, tp_atr=None, sl_atr=None, trail_atr=None, cost=0.30):
    out=[]
    for dd_ in days:
        ix=idx.get(dd_)
        if ix is None: continue
        m=NM[ix]
        slot=(m-1080)%1440
        sel=ix[(slot>=0)&(slot<=(exit_min-1080)%1440)]
        if len(sel)<10: continue
        e=sel[0]
        ep=C[e]                                   # enter at close of the 18:00 bar
        A=base.atr.get(dd_)
        if A is None or np.isnan(A): continue
        path=sel[1:]
        if len(path)==0: continue
        peak=ep; xp=None
        for j in path:
            if sl_atr is not None and L[j]<=ep-sl_atr*A: xp=ep-sl_atr*A; break
            if tp_atr is not None and H[j]>=ep+tp_atr*A: xp=ep+tp_atr*A; break
            if trail_atr is not None:
                peak=max(peak,H[j])
                if L[j]<=peak-trail_atr*A: xp=peak-trail_atr*A; break
        if xp is None: xp=C[path[-1]]
        out.append(dict(day=dd_,net=(xp-ep)-cost,atr=A))
    o=pd.DataFrame(out).set_index('day'); o['R']=o.net/o.atr
    return o
cfgs=[("time exit 20:55 (current)",dict()),
      ("+ stop 0.5 ATR",dict(sl_atr=0.5)),("+ stop 0.3 ATR",dict(sl_atr=0.3)),
      ("+ target 0.3 ATR",dict(tp_atr=0.3)),("+ target 0.5 ATR",dict(tp_atr=0.5)),
      ("+ tgt0.3/stop0.3",dict(tp_atr=0.3,sl_atr=0.3)),
      ("+ trail 0.25 ATR",dict(trail_atr=0.25)),("+ trail 0.4 ATR",dict(trail_atr=0.4)),
      ("exit 21:30, no stop",dict(exit_min=21*60+30)),
      ("exit 01:30, no stop",dict(exit_min=1*60+30)),
      ("exit 01:30 + stop 0.5",dict(exit_min=1*60+30,sl_atr=0.5))]
print("  variant                     n    meanR      t    net$/tr  Sharpe   win%   maxDD_R")
for nm,kw in cfgs:
    o=run(**kw); m,t,n,sd=ts(o.R)
    eq=(1+0.01*o.R).cumprod(); dd_=(eq/eq.cummax()-1).min()*100
    print(f"  {nm:26s} {n:4d}  {m:+.5f} {t:+6.2f}  {o.net.mean():+7.3f}  {m/sd*np.sqrt(252):+6.2f}  {(o.net>0).mean()*100:5.1f}  {dd_:+6.2f}%")
