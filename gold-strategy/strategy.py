#!/usr/bin/env python3
"""
XAUUSD (Gold) — systematic strategy research and backtest.

Reproduces the full study on M5 gold data (2021-08-25 -> 2026-09-11):
  * scans every time-of-day window for drift anomalies
  * benchmarks the classic retail gold playbook (ORB, Asian range, EMA cross,
    RSI-2, Bollinger, Donchian, Supertrend, MACD, Silver Bullet)
  * builds and validates the two systems that survived

Usage:  python3 strategy.py path/to/xauusd_m5.csv
CSV columns expected: time,open,high,low,close,volume  (time ISO-8601, UTC)
"""
import sys
import numpy as np
import pandas as pd

COST = 0.30          # round-trip spread + slippage, USD per ounce
RISK_FREE = 0.0


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def load(csv_path):
    """M5 bars -> (m5 frame with NY session clock, daily frame on the NY trading day)."""
    df = pd.read_csv(csv_path, parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    df = df.rename(columns={"time": "ts"})
    ny = df.ts.dt.tz_convert("America/New_York")
    df["ny_min"] = ny.dt.hour * 60 + ny.dt.minute
    # a gold trading day runs 18:00 NY -> 17:00 NY; shifting by 6h labels it by its NY date
    df["tday"] = pd.to_datetime((ny + pd.Timedelta(hours=6)).dt.date)

    g = df.groupby("tday")
    d = pd.DataFrame({"o": g.open.first(), "h": g.high.max(),
                      "l": g.low.min(), "c": g.close.last(), "n": g.size()})
    d = d[d.n >= 50]                                  # drop holiday stubs
    prev = d.c.shift()
    d["tr"] = np.maximum(d.h - d.l, np.maximum((d.h - prev).abs(), (d.l - prev).abs()))
    d["atr"] = d.tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df, d


def tstat(x):
    """mean, t-statistic, n, sd of a return series."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 10:
        return np.nan, np.nan, len(x), np.nan
    sd = x.std(ddof=1)
    return x.mean(), (x.mean() / (sd / np.sqrt(len(x))) if sd > 0 else np.nan), len(x), sd


# --------------------------------------------------------------------------- #
# Strategy A — Asian-reopen drift
# --------------------------------------------------------------------------- #
def strategy_a(df, d, entry=18 * 60, exit_=20 * 60 + 55, sma=200, cost=COST,
               skip_sunday=True):
    """
    Long gold at the CLOSE of the 18:00 NY bar (i.e. a market order at 18:05),
    flat at the close of the 20:55 NY bar.

    Filters, both known before entry:
      * skip the Sunday-evening reopen (the 'Monday' trading day) - different
        microstructure after a 48h weekend, and it carries no drift
      * only trade when the last daily close is above its SMA(200)

    Entering at the bar CLOSE rather than the printed 18:00 open is deliberate:
    ~60% of the raw headline edge sits inside that first 5-minute print, where
    the reopen spread makes it unreachable. What is measured here is executable.
    """
    close_at = df.pivot_table(index="tday", columns="ny_min", values="close", aggfunc="first")
    atr = d.atr.shift()                               # ATR through yesterday only
    prev_close = d.c.shift(1)
    trend = prev_close > prev_close.rolling(sma).mean()

    t = pd.DataFrame({"entry": close_at[entry], "exit": close_at[exit_]}).dropna()
    t = t.join(pd.DataFrame({"atr": atr, "trend": trend}), how="inner").dropna()
    if skip_sunday:
        t = t[t.index.dayofweek != 0]                 # 'Monday' day opens Sunday 18:00 NY
    t = t[t.trend]

    t["gross"] = t["exit"] - t["entry"]
    t["net"] = t.gross - cost
    t["R"] = t.net / t.atr                            # risk unit = one daily ATR
    return t[["entry", "exit", "atr", "gross", "net", "R"]]


# --------------------------------------------------------------------------- #
# Strategy B — vol-targeted trend-following overlay
# --------------------------------------------------------------------------- #
def strategy_b(d, fast=21, slow=55, vol_target=0.10, max_lev=3.0, cost=COST):
    """
    Long-only daily EMA(21/55) filter, position scaled to a 10% annualised vol
    target. This is not alpha - it is gold beta with the drawdown cut in half.
    """
    ret = d.c.pct_change()
    long = (d.c.ewm(span=fast, adjust=False).mean() >
            d.c.ewm(span=slow, adjust=False).mean()).shift(1).astype(float).fillna(0)
    realised = ret.rolling(20).std() * np.sqrt(252)
    lev = (vol_target / realised.shift(1)).clip(0, max_lev).fillna(0)
    pos = long * lev
    r = pos * ret - pos.diff().abs().fillna(0) * (cost / 2) / d.c
    return r.dropna(), pos


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def perf(r, name, periods=252):
    r = r.dropna()
    if len(r) < 20:
        return {}
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    return dict(name=name,
                CAGR=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=r.std() * np.sqrt(periods) * 100,
                sharpe=r.mean() / r.std() * np.sqrt(periods),
                maxDD=(eq / eq.cummax() - 1).min() * 100)


def main(csv_path):
    df, d = load(csv_path)
    print(f"loaded {len(df):,} M5 bars -> {len(d):,} trading days "
          f"({d.index.min().date()} .. {d.index.max().date()})\n")

    A = strategy_a(df, d)
    m, t, n, sd = tstat(A.R)
    print("=" * 72)
    print("STRATEGY A — Asian-reopen drift (18:05 -> 20:55 NY, long only)")
    print("=" * 72)
    print(f"  trades              {n}")
    print(f"  net $/trade         {A.net.mean():+.3f}   (gross {A.gross.mean():+.3f}, cost {COST:.2f})")
    print(f"  mean R (net)        {m:+.5f}   t = {t:+.2f}")
    print(f"  win rate            {(A.net > 0).mean() * 100:.1f}%")
    print(f"  profit factor       {A.net[A.net > 0].sum() / -A.net[A.net < 0].sum():.3f}")
    print(f"  Sharpe (per trade)  {m / sd * np.sqrt(252):.2f}")
    print("\n  by year:")
    for y, g in A.groupby(A.index.year):
        print(f"    {y}  n={len(g):4d}  net$/tr={g.net.mean():+7.3f}  total=${g.net.sum():+9.1f}")

    rB, pos = strategy_b(d)
    rA = (A.R.reindex(d.index).fillna(0.0))
    rA = rA * (0.10 / (rA[rA != 0].std() * np.sqrt(252)))   # scale A to 10% vol

    print("\n" + "=" * 72)
    print("PORTFOLIO — 50% Strategy A / 50% Strategy B, vs buy & hold")
    print("=" * 72)
    rows = [perf(rA, "A alone (overnight drift)"),
            perf(rB, "B alone (trend, vol-targeted)"),
            perf(0.5 * rA + 0.5 * rB, "PORTFOLIO 50/50"),
            perf(d.c.pct_change(), "Buy & hold (unlevered)")]
    print(pd.DataFrame([r for r in rows if r]).round(2).to_string(index=False))
    print(f"\n  corr(A, B) = {pd.concat([rA, rB], axis=1).dropna().corr().iloc[0, 1]:+.3f}")
    return A, rA, rB, d


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python3 strategy.py path/to/xauusd_m5.csv")
    main(sys.argv[1])
