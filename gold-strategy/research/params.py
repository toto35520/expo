import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
df,d=load(); df=df.reset_index(drop=True)
piv=df.pivot_table(index='tdayd',columns='ny_min',values='close',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
sm=d.c.shift(1).rolling(200).mean()
A=pd.DataFrame({'ein':piv[1080],'xp':piv[20*60+55],'atr':atrp}).dropna()
A=A[(A.index.dayofweek!=0)&(d.c.shift(1).reindex(A.index)>sm.reindex(A.index))]
A['net']=A.xp-A.ein-0.30; A['R']=A.net/A.atr
m,t,n,sd=ts(A.R)
yrs=(A.index[-1]-A.index[0]).days/365.25
tpy=n/yrs
print("="*88); print("CORRECTION — annualised Sharpe was computed with the wrong trade count"); print("="*88)
print(f"  trades {n} over {yrs:.2f}y  ->  {tpy:.0f} trades/year (NOT 252)")
print(f"  per-trade Sharpe          = {m/sd:.4f}")
print(f"  WRONG (x sqrt(252))       = {m/sd*np.sqrt(252):.2f}   <- what I reported")
print(f"  CORRECT (x sqrt({tpy:.0f}))     = {m/sd*np.sqrt(tpy):.2f}   <- real figure")
# cross-check via the daily series with zeros on non-trade days
rA=A.R.reindex(d.index).fillna(0.0)
print(f"  cross-check, daily series with zeros, x sqrt(252) = {rA.mean()/rA.std()*np.sqrt(252):.2f}")

print("\n"+"="*88); print("SIZING — f = fraction of equity risked per 1 ATR of adverse move"); print("="*88)
print(f"  per trade: mean = {m:.5f} ATR, sd = {sd:.4f} ATR, {tpy:.0f} trades/yr")
print(f"  annual return  ~ {tpy:.0f} * f * {m:.5f} = {tpy*m:.3f} * f")
print(f"  annual vol     ~ f * {sd:.4f} * sqrt({tpy:.0f}) = {sd*np.sqrt(tpy):.3f} * f")
print(f"\n  {'target vol':>11s} {'f':>8s} {'exp. return/yr':>15s} {'plausible maxDD':>17s}")
for tv in [0.05,0.075,0.10,0.15]:
    f=tv/(sd*np.sqrt(tpy)); print(f"  {tv*100:9.1f}% {f*100:7.2f}% {tpy*m*f*100:14.1f}% {tv*1.6*100:16.0f}%")

print("\n"+"="*88); print("POSITION SIZE in ounces, at f = 2.5% (about 5% annual vol)"); print("="*88)
f=0.025
print(f"  units = equity * {f} / ATR_daily")
for eq in [2000,5000,10000,25000,50000]:
    for a_ in [50,105]:
        u=eq*f/a_
        print(f"   equity ${eq:>6,} , ATR ${a_:>3}  ->  {u:6.2f} oz  ({u/100:.3f} lots)  exp. ${u*m*a_:+6.2f}/trade  ${u*m*a_*tpy:+7.0f}/yr")
    print()

print("="*88); print("THE ATR GATE — below this level the spread eats the edge"); print("="*88)
print(f"  gross edge per trade = {A.net.mean()+0.30:.3f} $ at mean ATR {A.atr.mean():.1f} -> {(A.net.mean()+0.30)/A.atr.mean():.5f} ATR")
g=(A.net.mean()+0.30)/A.atr.mean()
for spread in [0.20,0.30,0.50,0.80]:
    print(f"   spread ${spread:.2f}: breakeven ATR = ${spread/g:6.1f} | 'edge >= 2x cost' needs ATR >= ${2*spread/g:6.1f}")
print(f"\n  current ATR(14) daily = ${d.atr.iloc[-1]:.1f}")

print("\n"+"="*88); print("HOW LONG BEFORE A FORWARD TEST CAN CONFIRM ANYTHING?"); print("="*88)
s_pt=m/sd
for tt in [1.5,2.0,2.5]:
    nn=(tt/s_pt)**2; print(f"   to reach t = {tt}: {nn:.0f} trades = {nn/tpy*12:.0f} months")
print("   -> a 3-month forward test CANNOT confirm the edge. It can only catch")
print("      execution problems: real spread, slippage, wrong session times.")
