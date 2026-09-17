import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import load, ts
from math import erf, sqrt
df,d=load(); df=df.reset_index(drop=True)
df['slot']=(df.ny_min-1080)%1440
COST=0.30
grp=df.groupby('tdayd').indices; days=sorted(grp.keys())
O=df.open.values;H=df.high.values;L=df.low.values;C=df.close.values;S=df.slot.values;V=df.volume.values
atrp=df.groupby('tdayd').atrp.first()
results=[]
def add(nm,r,extra=""):
    m,t,n,sd=ts(r)
    if n<50: return
    results.append(dict(name=nm,n=n,meanR=m,t=t,sharpe=m/sd*np.sqrt(252) if sd>0 else np.nan,note=extra))

print("="*104); print("A. FLOOR-TRADER PIVOT POINTS (P, R1/R2, S1/S2 from the prior trading day)"); print("="*104)
P=((d.h+d.l+d.c)/3).shift(1); R1=(2*P-d.l.shift(1)); S1=(2*P-d.h.shift(1))
R2=P+(d.h.shift(1)-d.l.shift(1)); S2=P-(d.h.shift(1)-d.l.shift(1))
lv={'P':P,'R1':R1,'S1':S1,'R2':R2,'S2':S2}
# for each day: first touch of a level during 03:00-16:00 NY, then measure the next 2h
for name,lev in lv.items():
    for mode in ['revert','break']:
        rs=[]
        for dd_ in days:
            if dd_ not in lev.index or np.isnan(lev.get(dd_,np.nan)): continue
            ix=grp[dd_]; s=S[ix]
            tw=ix[(s>=540)&(s<1320)]        # 03:00 -> 16:00 NY
            if len(tw)<40: continue
            lv_=lev[dd_]; a=atrp.get(dd_)
            if a is None or np.isnan(a): continue
            hit=None
            for k,j in enumerate(tw):
                if L[j]<=lv_<=H[j]: hit=k; break
            if hit is None or hit+24>=len(tw): continue
            e=tw[hit+1]; x=tw[min(hit+24,len(tw)-1)]    # enter next bar, hold 2h
            up_from_below = C[tw[0]]<lv_
            if mode=='break':  dirn = 1 if up_from_below else -1     # trade through the level
            else:              dirn = -1 if up_from_below else 1     # fade the touch
            rs.append((dirn*(C[x]-C[e])-COST)/a)
        add(f"Pivot {name} {mode}", rs)

print("="*104); print("B. SESSION VWAP (anchored at the 18:00 reopen)"); print("="*104)
for band,mode in [(0,'revert_to_vwap'),(1.0,'fade_1sd'),(2.0,'fade_2sd'),(1.0,'break_1sd'),(2.0,'break_2sd')]:
    rs=[]
    for dd_ in days:
        ix=grp[dd_]; a=atrp.get(dd_)
        if a is None or np.isnan(a) or len(ix)<200: continue
        px=(H[ix]+L[ix]+C[ix])/3; vv=V[ix].astype(float)
        cum=np.cumsum(px*vv); cv=np.cumsum(vv)
        vwap=cum/np.maximum(cv,1)
        dev=px-vwap
        sd_=pd.Series(dev).expanding(20).std().values
        s=S[ix]
        tw=np.where((s>=540)&(s<1260))[0]     # 03:00 -> 15:00 NY
        if len(tw)<40: continue
        done=False
        for k in tw:
            if k+24>=len(ix) or np.isnan(sd_[k]) or sd_[k]<=0: continue
            z=dev[k]/sd_[k]
            if mode=='revert_to_vwap':
                if abs(z)<1.5: continue
                dirn=-np.sign(z)
            elif mode.startswith('fade'):
                if abs(z)<band: continue
                dirn=-np.sign(z)
            else:
                if abs(z)<band: continue
                dirn=np.sign(z)
            rs.append((dirn*(C[ix[min(k+24,len(ix)-1)]]-C[ix[k]])-COST)/a); done=True; break
    add(f"VWAP {mode}"+(f" {band}sd" if band else ""), rs)

print("="*104); print("C. ICHIMOKU / SAR / ADX / HEIKIN-ASHI on H4 and D1"); print("="*104)
def rs_tf(rule):
    x=df.set_index('ts').resample(rule).agg(o=('open','first'),h=('high','max'),l=('low','min'),c=('close','last')).dropna()
    tr=np.maximum(x.h-x.l,np.maximum((x.h-x.c.shift()).abs(),(x.l-x.c.shift()).abs()))
    x['atr']=tr.ewm(alpha=1/14,adjust=False).mean()
    return x
for rule,tag,bpy in [('4h','H4',6*252),('1D','D1',252)]:
    x=rs_tf(rule); c=x.c
    # Ichimoku
    conv=(x.h.rolling(9).max()+x.l.rolling(9).min())/2
    base=(x.h.rolling(26).max()+x.l.rolling(26).min())/2
    spanA=((conv+base)/2).shift(26); spanB=((x.h.rolling(52).max()+x.l.rolling(52).min())/2).shift(26)
    pos=np.where((c>spanA)&(c>spanB),1,np.where((c<spanA)&(c<spanB),-1,0))
    pos=pd.Series(pos,index=x.index)
    pnl=(pos.shift(1)*c.diff()-pos.diff().abs().fillna(0)*COST/2)/x.atr.shift(1)
    add(f"{tag} Ichimoku cloud L+S", pnl.dropna())
    add(f"{tag} Ichimoku cloud long-only", ((pos>0).astype(float).shift(1)*c.diff()-(pos>0).astype(float).diff().abs().fillna(0)*COST/2).div(x.atr.shift(1)).dropna())
    # Parabolic SAR (simplified)
    af0,afmax=0.02,0.2; sar=[c.iloc[0]]; trend=1; af=af0; ep=x.h.iloc[0]
    for i in range(1,len(x)):
        s=sar[-1]+af*(ep-sar[-1])
        if trend>0:
            if x.l.iloc[i]<s: trend=-1; s=ep; ep=x.l.iloc[i]; af=af0
            elif x.h.iloc[i]>ep: ep=x.h.iloc[i]; af=min(af+af0,afmax)
        else:
            if x.h.iloc[i]>s: trend=1; s=ep; ep=x.h.iloc[i]; af=af0
            elif x.l.iloc[i]<ep: ep=x.l.iloc[i]; af=min(af+af0,afmax)
        sar.append(s)
    sarS=pd.Series(sar,index=x.index); psar=np.sign(c-sarS)
    add(f"{tag} Parabolic SAR", ((psar.shift(1)*c.diff()-psar.diff().abs().fillna(0)*COST/2)/x.atr.shift(1)).dropna())
    # ADX-filtered EMA trend
    up=x.h.diff(); dn=-x.l.diff()
    pdm=np.where((up>dn)&(up>0),up,0); ndm=np.where((dn>up)&(dn>0),dn,0)
    tr_=np.maximum(x.h-x.l,np.maximum((x.h-c.shift()).abs(),(x.l-c.shift()).abs()))
    atr_=pd.Series(tr_).ewm(alpha=1/14,adjust=False).mean().values
    pdi=100*pd.Series(pdm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr_
    ndi=100*pd.Series(ndm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr_
    dx=100*(pdi-ndi).abs()/(pdi+ndi); adx=dx.ewm(alpha=1/14,adjust=False).mean()
    trend_pos=np.sign(c.ewm(span=21,adjust=False).mean()-c.ewm(span=55,adjust=False).mean())
    for thr in [20,25]:
        p=trend_pos.where(adx>thr,0)
        add(f"{tag} EMA21/55 + ADX>{thr}", ((p.shift(1)*c.diff()-p.diff().abs().fillna(0)*COST/2)/x.atr.shift(1)).dropna())
    # Heikin Ashi
    hac=(x.o+x.h+x.l+x.c)/4; hao=[(x.o.iloc[0]+x.c.iloc[0])/2]
    for i in range(1,len(x)): hao.append((hao[-1]+hac.iloc[i-1])/2)
    haoS=pd.Series(hao,index=x.index); hp=np.sign(hac-haoS)
    add(f"{tag} Heikin-Ashi trend", ((hp.shift(1)*c.diff()-hp.diff().abs().fillna(0)*COST/2)/x.atr.shift(1)).dropna())
    # candlestick patterns -> next bar
    body=(c-x.o); rng=(x.h-x.l).replace(0,np.nan)
    eng_bull=(body>0)&(body.shift(1)<0)&(c>x.o.shift(1))&(x.o<c.shift(1))
    eng_bear=(body<0)&(body.shift(1)>0)&(c<x.o.shift(1))&(x.o>c.shift(1))
    hammer=(body.abs()/rng<0.35)&((x.o.combine(c,min)-x.l)/rng>0.5)
    doji=(body.abs()/rng<0.1)
    tws=(body>0)&(body.shift(1)>0)&(body.shift(2)>0)
    nxt=c.shift(-1)-c
    for nm,mask,dirn in [("engulfing bull",eng_bull,1),("engulfing bear",eng_bear,-1),
                         ("hammer",hammer,1),("doji",doji,1),("3 white soldiers",tws,1)]:
        add(f"{tag} {nm}", ((dirn*nxt-COST)/x.atr)[mask].dropna())

out=pd.DataFrame(results)
K=len(out); ps=sorted([(2*(1-0.5*(1+erf(abs(t)/sqrt(2)))),i) for i,t in enumerate(out.t)])
sigi={ps[i][1] for i in range(K) if ps[i][0]<=(i+1)/K*0.05}
out['FDR']=['YES' if i in sigi else '' for i in range(K)]
out=out.sort_values('t',ascending=False)
print(out[['name','n','meanR','t','sharpe','FDR']].round(4).to_string(index=False))
print(f"\n  {K} strategies tested. Benjamini-Hochberg FDR 5%: {len(sigi)} survive.")
