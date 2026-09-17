import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
np.random.seed(23)
df,d=load(); df=df.reset_index(drop=True)
df['slot']=(df.ny_min-1080)%1440
piv=df.pivot_table(index='tdayd',columns='slot',values='close',aggfunc='first')
atr=df.groupby('tdayd').atrp.first()
grid=[s for s in sorted(piv.columns) if s%30==0]
sm200=d.c.shift(1).rolling(200).mean()
above=(d.c.shift(1)>sm200)
notmon=pd.Series(piv.index.dayofweek!=0,index=piv.index)
FILTERS={'none':pd.Series(True,index=piv.index),
         'skipSun':notmon,
         'skipSun+SMA200':(notmon & above.reindex(piv.index).fillna(False))}
def lab(s): m=(s+1080)%1440; return f"{m//60:02d}:{m%60:02d}"

cols=[];names=[]
for fn,fm in FILTERS.items():
    for a in grid:
        for b in grid:
            if b<=a or not (60<=b-a<=480): continue
            r=((piv[b]-piv[a]-0.30)/atr).where(fm)      # net of cost, filter applied
            if r.notna().sum()<300: continue
            cols.append(r); names.append((fn,a,b))
M=pd.concat(cols,axis=1); M.columns=range(len(cols))
X=M.values; n,K=X.shape
print("="*100); print("REALITY CHECK OVER THE FULL SEARCH SPACE (windows x filters), net of costs"); print("="*100)
print(f"  {K} hypotheses x {n} days (NaN-aware)")
def tcol(A):
    with np.errstate(invalid='ignore',divide='ignore'):
        cnt=np.sum(~np.isnan(A),0)
        m=np.nanmean(A,0); s=np.nanstd(A,0,ddof=1)
        return np.where(cnt>=200, m/(s/np.sqrt(np.maximum(cnt,1))), np.nan)
t_obs=tcol(X)
i=int(np.nanargmax(np.abs(t_obs))); fn,a,b=names[i]
print(f"  best observed: [{fn}]  {lab(a)} -> {lab(b)}   t = {t_obs[i]:+.3f}")
# our actual traded rule inside this family
try:
    j=names.index(('skipSun+SMA200',0,(20*60+55-1080)%1440))
except ValueError:
    j=min(range(K),key=lambda k: 9e9 if names[k][0]!='skipSun+SMA200' else abs(names[k][1]-0)+abs(names[k][2]-175))
print(f"  traded rule  : [{names[j][0]}]  {lab(names[j][1])} -> {lab(names[j][2])}   t = {t_obs[j]:+.3f}")
Xc=X-np.nanmean(X,0)                 # impose the null
IT=2000; BL=10; nb=int(np.ceil(n/BL)); maxt=np.empty(IT)
for it in range(IT):
    st=np.random.randint(0,n-BL,size=nb)
    idx=(st[:,None]+np.arange(BL)[None,:]).ravel()[:n]
    tt=tcol(Xc[idx]); maxt[it]=np.nanmax(np.abs(tt))
print(f"\n  null max|t|: median {np.median(maxt):.2f} | 95th {np.percentile(maxt,95):.2f} | 99th {np.percentile(maxt,99):.2f}")
for lbl,k in [("best-of-search",i),("traded rule",j)]:
    o=abs(t_obs[k]); p=(maxt>=o).mean()
    print(f"  {lbl:16s} t={o:.3f}  adjusted p = {p:.4f}  -> {'SURVIVES' if p<0.05 else 'does not survive'} the full search")

print("\n"+"="*100); print("IS THE EDGE BROAD OR A LUCKY PICK? share of positive windows by start hour"); print("="*100)
byh={}
for k,(fn,a,b) in enumerate(names):
    if fn!='skipSun+SMA200' or np.isnan(t_obs[k]): continue
    h=((a+1080)%1440)//60
    byh.setdefault(h,[]).append(t_obs[k])
print("  startNY   n_windows   %t>0    mean_t   max_t")
for h in sorted(byh):
    v=np.array(byh[h]); print(f"    {h:02d}:00      {len(v):3d}      {(v>0).mean()*100:5.1f}   {v.mean():+6.2f}  {v.max():+6.2f}")
