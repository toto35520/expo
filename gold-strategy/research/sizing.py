import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
from math import erf, sqrt
df,d=load(); df=df.reset_index(drop=True)
df['slot']=(df.ny_min-1080)%1440
piv=df.pivot_table(index='tdayd',columns='ny_min',values='close',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
sm=d.c.shift(1).rolling(200).mean()
A=pd.DataFrame({'ein':piv[1080],'xp':piv[20*60+55]}).dropna()
A=A[(A.index.dayofweek!=0)&(d.c.shift(1).reindex(A.index)>sm.reindex(A.index))]
A['gross']=A.xp-A.ein; A['net']=A.gross-0.30

print("="*100); print("A. CAN A BETTER VOLATILITY ESTIMATOR LIFT THE SHARPE? (same trades, different sizing)"); print("="*100)
# candidate risk estimators, all known before 18:05
est={}
est['ATR14 (current)']   = d.atr.shift(1)
est['ATR5']              = d.tr.ewm(alpha=1/5,adjust=False).mean().shift(1)
est['ATR30']             = d.tr.ewm(alpha=1/30,adjust=False).mean().shift(1)
est['ATR14 blend ATR5']  = 0.5*d.atr.shift(1)+0.5*d.tr.ewm(alpha=1/5,adjust=False).mean().shift(1)
# realised vol of the 18:05->20:55 window itself, trailing 20 obs (the risk actually taken)
win=(piv[20*60+55]-piv[1080])
est['window realised sd20'] = win.rolling(20).std().shift(1)*4     # x4 to land on an ATR-like scale
est['window realised sd60'] = win.rolling(60).std().shift(1)*4
# EWMA of squared daily returns
est['EWMA vol (lam .94)'] = (d.c.diff()**2).ewm(alpha=0.06,adjust=False).mean().pow(0.5).shift(1)*1.4
print(f"  {'estimator':26s} {'n':>5s} {'meanR':>9s} {'sd':>8s} {'t':>7s} {'Sharpe_ann':>11s}")
best=None
for nm,e in est.items():
    ee=e.reindex(A.index)
    R=(A.net/ee).replace([np.inf,-np.inf],np.nan).dropna()
    m,t,n,sd=ts(R)
    tpy=n/((A.index[-1]-A.index[0]).days/365.25)
    sh=m/sd*np.sqrt(tpy)
    print(f"  {nm:26s} {n:5d} {m:+9.5f} {sd:8.4f} {t:+7.2f} {sh:+11.2f}")
    if best is None or sh>best[1]: best=(nm,sh)
print(f"\n  best: {best[0]} (Sharpe {best[1]:.2f}) vs ATR14 baseline")
print("  -> a gain under ~0.15 Sharpe is noise; sizing choice is second-order here")

print("\n"+"="*100); print("B. WITHIN-WINDOW MOMENTUM — does 18:05->19:55 predict 19:55->21:55?"); print("="*100)
leg1=(piv[19*60+55]-piv[1080])/atrp
leg2=(piv[21*60+55]-piv[19*60+55])/atrp
j=leg1.dropna().index.intersection(leg2.dropna().index)
j=j.intersection(A.index)
print(f"  corr(leg1, leg2) = {leg1[j].corr(leg2[j]):+.4f}  n={len(j)}")
for nm,s_ in [("follow leg1",np.sign(leg1[j])*leg2[j]),("fade leg1",-np.sign(leg1[j])*leg2[j])]:
    m,t,n,sd=ts(s_); print(f"   {nm:14s}: meanR={m:+.5f} t={t:+5.2f}")
m,t,n,sd=ts(leg2[j]); print(f"   always long leg2 : meanR={m:+.5f} t={t:+5.2f}  (this is just the tail of the drift)")

print("\n"+"="*100); print("C. BELOW-SMA200 WINDOW SWEEP, low threshold (power warning)"); print("="*100)
below=(d.c.shift(1)<sm)
blw=below.reindex(piv.index).fillna(False)
pivS=df.pivot_table(index='tdayd',columns='slot',values='close',aggfunc='first')
grid=[s for s in sorted(pivS.columns) if s%60==0]
res=[]
for a in grid:
    for b in grid:
        if b<=a or not (60<=b-a<=480): continue
        r=((pivS[b]-pivS[a])/atrp)[blw].dropna()
        if len(r)<150: continue
        m,t,nn,sd=ts(r); res.append((t,m,a,b,nn))
def lab(s): mm=(s+1080)%1440; return f"{mm//60:02d}:{mm%60:02d}"
res.sort(key=lambda z:-abs(z[0]))
K=len(res)
print(f"  {K} windows, max n = {max(x[4] for x in res) if res else 0} days below SMA200")
print("  top 5 by |t|:")
for t,m,a,b,nn in res[:5]:
    print(f"    {lab(a)} -> {lab(b)}  meanR={m:+.5f} t={t:+5.2f} n={nn}")
if res:
    mx=max(abs(x[0]) for x in res)
    print(f"\n  max |t| = {mx:.2f}. With {K} windows tested, the expected max |t| under pure noise")
    print(f"  is roughly {sqrt(2*np.log(K)):.2f} -> {'nothing here' if mx < sqrt(2*np.log(K))+0.5 else 'worth a look'}")
print("\n  NOTE: only 218 days in the sample sit below the SMA200, and gold still drifted")
print("  UP over them (meanR +0.031). There is no downtrend sample to build a short on.")
