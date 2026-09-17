import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
df,d=load(); df=df.reset_index(drop=True)
# chronological slot inside the trading day: 0 at 18:00 NY, ascending to the 17:55 close
df['slot']=(df.ny_min-1080)%1440
piv=df.pivot_table(index='tdayd',columns='slot',values='close',aggfunc='first')
atr=df.groupby('tdayd').atrp.first()
slots=sorted(piv.columns)
def lab(s):
    m=(s+1080)%1440; return f"{m//60:02d}:{m%60:02d}"
print("="*96); print("CORRECTED EXHAUSTIVE SWEEP — every forward window, 30-min grid, holds 1h..8h"); print("="*96)
res=[]
grid=[s for s in slots if s%30==0]
for a in grid:
    for b in grid:
        if b<=a or (b-a)>480 or (b-a)<60: continue
        if a not in piv.columns or b not in piv.columns: continue
        r=((piv[b]-piv[a])/atr).dropna()
        if len(r)<900: continue
        m,t,n,sd=ts(r); res.append((t,m,a,b,n))
res.sort(key=lambda z:-abs(z[0]))
K=len(res); bonf=2.81 if K<1000 else 3.2
print(f"  {K} windows tested. Bonferroni 5% threshold ~ |t| > {abs(np.round(np.sqrt(2)*1.0,2))}... use FDR below.")
# Benjamini-Hochberg FDR
from math import erf, sqrt
p=[(2*(1-0.5*(1+erf(abs(t)/sqrt(2)))),t,m,a,b,n) for t,m,a,b,n in res]
p.sort()
crit=[(i+1)/K*0.05 for i in range(K)]
sig=[p[i] for i in range(K) if p[i][0]<=crit[i]]
print(f"  Benjamini-Hochberg FDR 5%: {len(sig)} windows survive out of {K}\n")
print("  TOP 15 by |t|:")
print("     window              meanR      t      n    p-value")
for t,m,a,b,n in res[:15]:
    pv=2*(1-0.5*(1+erf(abs(t)/sqrt(2))))
    flag="  <-- FDR-significant" if any(abs(s[1]-t)<1e-9 for s in sig) else ""
    print(f"     {lab(a)} -> {lab(b)}   {m:+.5f}  {t:+5.2f}  {n}  {pv:.2e}{flag}")
print("\n  Any window with NEGATIVE t beyond -2.5?  ", [f"{lab(a)}->{lab(b)} t={t:+.2f}" for t,m,a,b,n in res if t<-2.5] or "none")
