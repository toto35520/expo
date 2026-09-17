import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
from math import erf, sqrt
df,d=load(); df=df.reset_index(drop=True)
COST=0.30
ret=d.c.pct_change()
rv=ret.rolling(20).std()*np.sqrt(252)
def run(pos,label,tv=0.10,maxlev=3.0):
    pos=pos.reindex(d.index).fillna(0.0)
    lev=(tv/rv.shift(1)).clip(0,maxlev).fillna(0)
    p=pos*lev
    r=(p.shift(1)*ret - p.diff().abs().fillna(0)*(COST/2)/d.c).dropna()
    if len(r)<200 or r.std()==0: return None
    eq=(1+r).cumprod(); y=(r.index[-1]-r.index[0]).days/365.25
    return dict(name=label,CAGR=(eq.iloc[-1]**(1/y)-1)*100,vol=r.std()*np.sqrt(252)*100,
                sharpe=r.mean()/r.std()*np.sqrt(252),maxDD=(eq/eq.cummax()-1).min()*100,
                timeIn=(pos!=0).mean()*100,flips=int((pos.diff()!=0).sum()))
rows=[]
print("="*104); print("A. TIME-SERIES MOMENTUM (Moskowitz-Ooi-Pedersen): sign of the past N-day return"); print("="*104)
for N,lbl in [(21,'1m'),(63,'3m'),(126,'6m'),(252,'12m')]:
    past=d.c.pct_change(N)
    rows.append(run(np.sign(past).shift(1),f"TSMOM {lbl} long+short"))
    rows.append(run((past>0).astype(float).shift(1),f"TSMOM {lbl} long-only"))
# blended CTA-style
blend=sum(np.sign(d.c.pct_change(N)) for N in [21,63,126,252])/4
rows.append(run(blend.shift(1),"TSMOM blend 1/3/6/12m L+S"))
rows.append(run(blend.clip(0,1).shift(1),"TSMOM blend long-only"))
rows.append(run(pd.Series(1.0,index=d.index),"BUY & HOLD vol-targeted"))
out=pd.DataFrame([r for r in rows if r])
print(out.round(2).to_string(index=False))
bh=out[out.name.str.startswith('BUY')].sharpe.iloc[0]
print(f"\n  benchmark Sharpe = {bh:.2f}.  Nothing above it by a clear margin = no timing skill, only beta.")

print("\n"+"="*104); print("B. THE CURRENT REGIME — what works when gold is BELOW its SMA200?"); print("="*104)
sma=d.c.rolling(200).mean()
below=(d.c.shift(1)<sma.shift(1))
print(f"  days below SMA200: {below.sum()} of {len(d)} ({below.mean()*100:.0f}%)")
r_atr=(d.c.diff()/d.atr.shift())
m,t,n,sd=ts(r_atr[below]); print(f"  buy&hold while below SMA200 : meanR={m:+.5f} t={t:+5.2f} n={n}")
m,t,n,sd=ts(r_atr[~below]); print(f"  buy&hold while above SMA200 : meanR={m:+.5f} t={t:+5.2f} n={n}")
m,t,n,sd=ts(-r_atr[below]); print(f"  SHORT while below SMA200    : meanR={m:+.5f} t={t:+5.2f} n={n}")

print("\n  time-window sweep restricted to BELOW-SMA200 days (FDR controlled):")
df['slot']=(df.ny_min-1080)%1440
piv=df.pivot_table(index='tdayd',columns='slot',values='close',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
blw=below.reindex(piv.index).fillna(False)
grid=[s for s in sorted(piv.columns) if s%30==0]
res=[]
for a in grid:
    for b in grid:
        if b<=a or not (60<=b-a<=480): continue
        r=((piv[b]-piv[a])/atrp)[blw].dropna()
        if len(r)<250: continue
        m,t,nn,sd=ts(r); res.append((t,m,a,b,nn))
K=len(res); ps=sorted([(2*(1-0.5*(1+erf(abs(x[0])/sqrt(2)))),x) for x in res])
sig=[x for i,(p_,x) in enumerate(ps) if p_<=(i+1)/K*0.05]
res.sort(key=lambda z:-abs(z[0]))
def lab(s): mm=(s+1080)%1440; return f"{mm//60:02d}:{mm%60:02d}"
print(f"   {K} windows tested on below-SMA200 days. FDR 5% survivors: {len(sig)}")
print("   top 6 by |t|:")
for t,m,a,b,nn in res[:6]:
    print(f"     {lab(a)} -> {lab(b)}  meanR={m:+.5f} t={t:+5.2f} n={nn}")

print("\n"+"="*104); print("C. SESSION INTERACTION — does the Asian session predict London/NY?"); print("="*104)
def W(a,b): return ((piv[b]-piv[a])/atrp)
asia=W(0,480)                    # 18:00 -> 02:00 NY
asia_rng=((df[( (df.slot>=0)&(df.slot<480) )].groupby('tdayd').high.max()
          -df[((df.slot>=0)&(df.slot<480))].groupby('tdayd').low.min())/atrp)
asia_cl=df[((df.slot>=0)&(df.slot<480))].groupby('tdayd').close.last()
asia_hi=df[((df.slot>=0)&(df.slot<480))].groupby('tdayd').high.max()
asia_lo=df[((df.slot>=0)&(df.slot<480))].groupby('tdayd').low.min()
pos_in_rng=((asia_cl-asia_lo)/(asia_hi-asia_lo)).clip(0,1)
ldn_ny=W(540,1140)               # 03:00 -> 13:00 NY
j=asia.dropna().index.intersection(ldn_ny.dropna().index)
for nm,x in [("Asia return sign",np.sign(asia[j])),("Asia close in top/bottom of its range",np.sign(pos_in_rng[j]-0.5))]:
    sigr=(x*ldn_ny[j]).dropna(); m,t,n,sd=ts(sigr)
    print(f"   follow {nm:38s}: meanR={m:+.5f} t={t:+5.2f} n={n}")
    m,t,n,sd=ts(-sigr); print(f"   fade   {nm:38s}: meanR={m:+.5f} t={t:+5.2f} n={n}")
print(f"\n   corr(Asia move, London/NY move) = {asia[j].corr(ldn_ny[j]):+.4f}")
print(f"   corr(Asia RANGE, London/NY |move|) = {asia_rng[j].corr(ldn_ny[j].abs()):+.4f}  <- range predicts range, not direction")
