import pandas as pd, numpy as np
D=os.environ.get("GOLD_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
def load():
    df=pd.read_pickle(f"{D}/m5.pkl"); d=pd.read_pickle(f"{D}/d1.pkl")
    df['tdayd']=pd.to_datetime(df.tday)
    df['atrp']=df.tdayd.map(d.atr.shift())
    df=df.dropna(subset=['atrp']).reset_index(drop=True)
    return df,d
def ts(x):
    x=np.asarray(x,float); x=x[~np.isnan(x)]
    if len(x)<10: return (np.nan,np.nan,len(x),np.nan)
    sd=x.std(ddof=1)
    return x.mean(), (x.mean()/(sd/np.sqrt(len(x))) if sd>0 else np.nan), len(x), sd
def window(df, a_min, b_min, min_frac=0.7):
    """open->close over [a_min,b_min) in NY-minutes, wrapping past midnight."""
    if b_min>a_min: mask=(df.ny_min>=a_min)&(df.ny_min<b_min); span=b_min-a_min
    else:           mask=(df.ny_min>=a_min)|(df.ny_min<b_min); span=1440-a_min+b_min
    g=df[mask].groupby('tdayd').agg(o=('open','first'),c=('close','last'),h=('high','max'),
                                    l=('low','min'),n=('close','size'),a=('atrp','first'))
    return g[g.n>=span/5*min_frac]
def perf(r_atr, name="", ntr=None, per_year=252):
    m,t,n,sd=ts(r_atr)
    sh=m/sd*np.sqrt(per_year) if sd and sd>0 else np.nan
    return dict(name=name, mean=m, t=t, n=n, sd=sd, sharpe=sh)
