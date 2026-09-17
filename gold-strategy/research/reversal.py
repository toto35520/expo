import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
df,d=load(); df=df.reset_index(drop=True)
piv=df.pivot_table(index='tdayd',columns='ny_min',values='close',aggfunc='first')
pivo=df.pivot_table(index='tdayd',columns='ny_min',values='open',aggfunc='first')
atrp=df.groupby('tdayd').atrp.first()
sm=d.c.shift(1).rolling(200).mean()

A=pd.DataFrame({'ein':piv[1080],'xp':piv[20*60+55],'atr':atrp}).dropna()
A=A[(A.index.dayofweek!=0)&(d.c.shift(1).reindex(A.index)>sm.reindex(A.index))]
A['net']=A.xp-A.ein-0.30; A['R']=A.net/A.atr

# conditioners, ALL observable strictly before the 18:05 entry
day_sess =((piv[16*60+55]-piv[8*60])/atrp)            # 08:00 -> 16:55 NY move of the session that just ended
ny_pm    =((piv[16*60+55]-piv[12*60])/atrp)           # 12:00 -> 16:55 NY
gap      =((pivo[1080]-piv[16*60+55].shift(1))/atrp)  # 16:55 close (prev day) -> 18:00 open
full_prev=((d.c.shift(1)-d.c.shift(2))/d.atr.shift()) # prior close-to-close
# day_sess / ny_pm belong to tday T-1 (they happen before T's 18:00 reopen)
A['day_sess']=day_sess.shift(1).reindex(A.index)
A['ny_pm']   =ny_pm.shift(1).reindex(A.index)
A['gap']     =gap.reindex(A.index)
A['prev']    =full_prev.reindex(A.index)

print("="*100); print("A. DOES THE PRECEDING US SESSION PREDICT THE OVERNIGHT DRIFT? (quintiles + walk-forward)"); print("="*100)
for c,nm in [('day_sess','US session 08:00-16:55 move'),('ny_pm','NY afternoon 12:00-16:55 move'),
             ('gap','reopen gap 16:55->18:00'),('prev','prior close-to-close')]:
    x=A.dropna(subset=[c])
    q=pd.qcut(x[c],5,labels=False,duplicates='drop')
    rc=x[c].rank().corr(x.R.rank()); tr=rc*np.sqrt(len(x)-2)/np.sqrt(1-rc**2)
    print(f"\n  {nm}   Spearman={rc:+.4f} t={tr:+.2f}  n={len(x)}")
    print("    quintile  n    mean_cond   meanR       t     net$/tr")
    for k in range(5):
        s=x[q==k]; m,t,n,sd=ts(s.R)
        print(f"      Q{k+1}    {n:4d}   {s[c].mean():+7.4f}   {m:+.5f} {t:+6.2f}   {s.net.mean():+7.3f}")
    # honest walk-forward on the sign of the conditioner
    ins=x[x.index<'2024-09-01']; oos=x[x.index>='2024-09-01']
    for lbl,sub in [("IS ",ins),("OOS",oos)]:
        neg=sub[sub[c]<0]; pos=sub[sub[c]>=0]
        mn,tn,nn,sn=ts(neg.R); mp,tp_,np_,sp=ts(pos.R)
        print(f"    {lbl} cond<0: n={nn:3d} meanR={mn:+.5f} t={tn:+5.2f} | cond>=0: n={np_:3d} meanR={mp:+.5f} t={tp_:+5.2f}")

print("\n"+"="*100); print("B. IS THE DRIFT A REBOUND? correlation structure"); print("="*100)
x=A.dropna(subset=['day_sess'])
print(f"  corr(US session move, overnight drift)      = {x.day_sess.corr(x.R):+.4f}")
print(f"  corr(reopen gap, overnight drift)           = {A.dropna(subset=['gap']).gap.corr(A.dropna(subset=['gap']).R):+.4f}")
print(f"  corr(prior close-to-close, overnight drift) = {A.dropna(subset=['prev']).prev.corr(A.dropna(subset=['prev']).R):+.4f}")
print("\n  -> a strong NEGATIVE corr would mean 'the Asian session undoes the US session'")

print("\n"+"="*100); print("C. UNCONDITIONAL CHECK — the drift split by US-session sign, full sample"); print("="*100)
for lbl,sel in [("US session DOWN", x[x.day_sess<0]),("US session UP", x[x.day_sess>=0])]:
    m,t,n,sd=ts(sel.R); print(f"   {lbl:16s} n={n:4d} meanR={m:+.5f} t={t:+5.2f} net$/tr={sel.net.mean():+6.3f} Sharpe={m/sd*np.sqrt(252):+5.2f}")
