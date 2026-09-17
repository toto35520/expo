import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
from math import erf, sqrt
df,d=load(); df=df.reset_index(drop=True)
vol=df.groupby('tdayd').volume.sum(); d['v']=vol.reindex(d.index)

F=pd.DataFrame(index=d.index)
a=d.atr.shift()
F['ret1']   =(d.c.shift(1)-d.c.shift(2))/a
F['mom5']   =(d.c.shift(1)-d.c.shift(6))/a
F['mom10']  =(d.c.shift(1)-d.c.shift(11))/a
F['mom20']  =(d.c.shift(1)-d.c.shift(21))/a
F['clo_pos']=((d.c.shift(1)-d.l.shift(1))/(d.h.shift(1)-d.l.shift(1))).clip(0,1)
F['rng_atr']=(d.h.shift(1)-d.l.shift(1))/a
F['nr7']    =((d.h-d.l).shift(1)<=(d.h-d.l).shift(1).rolling(7).min()).astype(float)
F['inside'] =((d.h.shift(1)<d.h.shift(2))&(d.l.shift(1)>d.l.shift(2))).astype(float)
F['vol_rel']=(d.v.shift(1)/d.v.shift(1).rolling(20).mean())
F['vol_z']  =((d.v.shift(1)-d.v.shift(1).rolling(20).mean())/d.v.shift(1).rolling(20).std())
atr5=d.tr.ewm(alpha=1/5,adjust=False).mean(); atr20=d.tr.ewm(alpha=1/20,adjust=False).mean()
F['squeeze']=(atr5.shift(1)/atr20.shift(1))
bw=(d.c.rolling(20).std()/d.c.rolling(20).mean())
F['bw_pct'] =bw.shift(1).rolling(120).rank(pct=True)
F['d200']   =(d.c.shift(1)-d.c.shift(1).rolling(200).mean())/a
up=(d.c.diff()>0).astype(int)
F['streak'] =up.shift(1).groupby((up.shift(1)!=up.shift(2)).cumsum()).cumcount()+1
F['streak'] =F['streak']*np.where(up.shift(1)==1,1,-1)
F['dom']    =d.index.day
F=F.replace([np.inf,-np.inf],np.nan)

Y=(d.c-d.c.shift())/a                       # next-day return, ATR units
print("="*98); print("A. FEATURE -> NEXT-DAY RETURN (Spearman rank corr + tercile spread), FDR-controlled"); print("="*98)
print(f"  {'feature':10s} {'rank_corr':>10s} {'t':>7s} {'  T1':>8s} {'T2':>8s} {'T3':>8s}  {'T3-T1':>8s} {'t(T3-T1)':>9s}")
rows=[]
for c in F.columns:
    x=F[c]; j=x.dropna().index.intersection(Y.dropna().index)
    if len(j)<400: continue
    xx=x[j]; yy=Y[j]
    rc=xx.rank().corr(yy.rank()); tt=rc*np.sqrt(len(j)-2)/np.sqrt(1-rc**2)
    if xx.nunique()<=2:                      # binary feature -> two-group test
        g1=yy[xx>xx.median()]; g0=yy[xx<=xx.median()]
        if len(g1)<30 or len(g0)<30: continue
        ms=[g0.mean(), np.nan, g1.mean()]; d31=g1; d11=g0
    else:
        try: q=pd.qcut(xx,3,labels=False,duplicates='drop')
        except Exception: continue
        if pd.Series(q).nunique()<3: continue
        ms=[yy[q==k].mean() for k in range(3)]
        d31=yy[q==2]; d11=yy[q==0]
    if len(d31)<30 or len(d11)<30: continue
    sp=d31.mean()-d11.mean()
    se=np.sqrt(d31.var(ddof=1)/len(d31)+d11.var(ddof=1)/len(d11))
    tsp=sp/se
    rows.append((c,rc,tt,ms,sp,tsp))
    mid="     n/a" if np.isnan(ms[1]) else f"{ms[1]:+8.4f}"
    print(f"  {c:10s} {rc:+10.4f} {tt:+7.2f} {ms[0]:+8.4f} {mid} {ms[2]:+8.4f}  {sp:+8.4f} {tsp:+9.2f}")
K=len(rows); ps=sorted([(2*(1-0.5*(1+erf(abs(r[5])/sqrt(2)))),r[0]) for r in rows])
sig=[ps[i][1] for i in range(K) if ps[i][0]<=(i+1)/K*0.05]
print(f"\n  Benjamini-Hochberg FDR 5% on the tercile spread: {sig if sig else 'NOTHING SURVIVES'}  ({K} features)")

print("\n"+"="*98); print("B. VOLATILITY COMPRESSION -> EXPANSION (the classic squeeze setup), as a strategy"); print("="*98)
print("  next-day |move| and directional return conditional on compression state:")
absY=Y.abs()
for c,lo,hi,nm in [('squeeze',0,0.8,'ATR5/ATR20 < 0.8 (compressed)'),('squeeze',1.2,9,'ATR5/ATR20 > 1.2 (expanded)'),
                   ('bw_pct',0,0.2,'BB width in bottom 20%'),('bw_pct',0.8,1.0,'BB width in top 20%'),
                   ('nr7',0.5,1.5,'NR7 day'),('inside',0.5,1.5,'inside day')]:
    m_=(F[c]>=lo)&(F[c]<hi); j=m_[m_].index
    ja=j.intersection(absY.dropna().index)
    if len(ja)<60: continue
    base=absY.dropna().mean()
    mm,tt,nn,sd=ts(absY[ja]); md,td,nd,_=ts(Y[ja])
    print(f"   {nm:32s} n={nn:4d}  |move|={mm:.4f} vs base {base:.4f} ({(mm/base-1)*100:+5.1f}%)  dir_t={td:+5.2f}")
print("\n  -> does compression predict a bigger move the NEXT day? if |move| ratio ~1.0, the setup is empty")

print("\n"+"="*98); print("C. VOLUME as a filter on STRATEGY A (18:05->20:55, skip Sunday, >SMA200)"); print("="*98)
piv=df.pivot_table(index='tdayd',columns='ny_min',values='close',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
sm=d.c.shift(1).rolling(200).mean()
b=pd.DataFrame({'ein':piv[1080],'xp':piv[20*60+55],'atr':atrp}).dropna()
b=b[(b.index.dayofweek!=0)&(d.c.shift(1).reindex(b.index)>sm.reindex(b.index))]
b['net']=b.xp-b.ein-0.30; b['R']=b.net/b.atr
# volume of the ENTRY bar and of the 18:00 hour (known at/just after entry)
v18=df[df.ny_min==1080].groupby('tdayd').volume.first()
v18h=df[(df.slot if 'slot' in df else ((df.ny_min-1080)%1440))<60].groupby('tdayd').volume.sum() if False else None
b['v18']=v18.reindex(b.index)
b['v18_rel']=b.v18/b.v18.rolling(20).mean()
b['vprev']=F['vol_rel'].reindex(b.index)
for c,nm in [('v18_rel','reopen-bar volume vs 20d avg'),('vprev','prior-day volume vs 20d avg')]:
    x=b[c].dropna(); j=x.index
    q=pd.qcut(x,3,labels=False,duplicates='drop')
    print(f"   {nm}:")
    for k in range(3):
        sel=b.loc[j][q==k]; m,t,n,sd=ts(sel.R)
        print(f"     tercile {k+1}: n={n:4d} meanR={m:+.5f} t={t:+5.2f} net$/tr={sel.net.mean():+6.3f} Sharpe={m/sd*np.sqrt(252):+5.2f}")
