# Research scripts

Exploratory scripts kept for reproducibility. They read the prepared pickles
(`m5.pkl`, `d1.pkl`) produced from the raw CSV; set `GOLD_DATA_DIR` to the folder
holding them, or run `strategy.py` which does everything from the CSV directly.

| Script | What it answers |
|---|---|
| `sweep2.py` | exhaustive forward-window sweep (555 windows) with Benjamini-Hochberg FDR |
| `features.py` | 15 daily features vs next-day return; volatility compression; volume |
| `retail2.py` | pivots, VWAP, Ichimoku, Parabolic SAR, ADX, Heikin-Ashi, candlestick patterns |
| `volfilter.py` | volume filter walk-forward + exit optimisation (10 variants) |
| `reversal.py` | does the preceding US session predict the overnight drift? |
| `reality2.py` | White's Reality Check over the full windows x filters search space |
| `tsmom.py` | time-series momentum, the below-SMA200 regime, session interaction |
| `sizing.py` | volatility estimators for position sizing; within-window momentum |
| `checkneg.py` | shows why a fixed cost manufactures fake negative t-stats in quiet hours |

`lib.py` holds `load()` and `ts()` shared by all of them.

Two method notes worth carrying elsewhere:

1. **A trading day is not a calendar day.** Gold runs 18:00 -> 17:00 NY. Windows that
   cross the session boundary must be ordered chronologically inside the trading day,
   not by clock minute, or they are measured backwards.
2. **Never read a net-of-cost t-statistic without its gross counterpart.** Subtracting a
   fixed spread from every candidate makes the lowest-variance windows look like
   significant short signals when their gross drift is zero.
