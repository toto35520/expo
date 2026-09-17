import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
df,d=load(); df=df.reset_index(drop=True)
df['slot']=(df.ny_min-1080)%1440
piv=df.pivot_table(index='tdayd',columns='slot',values='close',aggfunc='first')
atr=df.groupby('tdayd').atrp.first()
def W(a,b):
    g=((piv[b]-piv[a])/atr).dropna(); return g
def lab(s): m=(s+1080)%1440; return f"{m//60:02d}:{m%60:02d}"
print("="*94); print("IS THE t=-4.54 WINDOW A REAL SHORT, OR JUST THE FIXED COST DRAGGING A QUIET HOUR?"); print("="*94)
print("  window            gross_mean   gross_t   net_mean(-$0.30)  net_t    sd      mean_ATR$")
for a,b in [(330,390),(0,180),(0,240),(60,120),(300,360),(390,450)]:
    g=W(a,b); net=((piv[b]-piv[a]-0.30)/atr).dropna()
    mg,tg,ng,sg=ts(g); mn,tn,nn,sn=ts(net)
    print(f"  {lab(a)} -> {lab(b)}   {mg:+.5f}  {tg:+6.2f}     {mn:+.5f}   {tn:+6.2f}  {sg:.4f}   {atr.reindex(g.index).mean():6.1f}")
print("\n  -> if gross_t ~ 0 while net_t is strongly negative, the 'signal' is only the fixed spread")
print("     divided by a very small intraday standard deviation. Not tradeable as a short.")
g=W(330,390); mg,tg,ng,sg=ts(g)
print(f"\n  23:30->00:30 gross: mean={mg:+.6f} ATR  t={tg:+.2f}  n={ng}")
print(f"  shorting it would EARN the drift ({-mg:+.6f}) and still PAY the spread -> net {-mg-0.30/atr.reindex(g.index).mean():+.6f} ATR")
print("\n  Conclusion: cost artifact. Every window carries the same -$0.30; the quietest hours")
print("  show the most negative t because their standard deviation is smallest.")
