#!/usr/bin/env python3
"""
Live go/no-go analyser for the XAUUSD Asian-reopen drift.

Call check() once a day, a few seconds before 18:05 America/New_York.
It returns a Verdict: go True/False, every individual condition, and the
position size in ounces.

The only hard dependency is pandas (numpy comes with it). Timezone handling
uses the stdlib zoneinfo, so DST is correct without extra packages.

    from live_signal import OvernightGoldSignal, build_trading_days

    sig = OvernightGoldSignal()
    sig.update_daily(build_trading_days(m5_bars))      # M5 OHLC, tz-aware UTC
    v = sig.check(now_utc=datetime.now(timezone.utc), equity=10_000, spread=0.28)
    print(v.explain())
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")

# --------------------------------------------------------------------------- #
# data preparation
# --------------------------------------------------------------------------- #
def build_trading_days(m5: pd.DataFrame, min_bars: int = 50) -> pd.DataFrame:
    """
    M5 bars -> daily OHLC on the GOLD trading day (18:00 NY -> 17:00 NY).

    This is the single easiest thing to get wrong. A calendar-day resample
    produces a different SMA and a different ATR, and the strategy is then
    filtered on numbers that never existed.

    m5 must have a tz-aware UTC 'ts' column (or index) plus open/high/low/close.
    """
    df = m5.copy()
    if "ts" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    ny = df["ts"].dt.tz_convert(NY)
    # +6h maps the 18:00 NY reopen onto the next NY date, which then labels the day
    df["tday"] = pd.to_datetime((ny + timedelta(hours=6)).dt.date)

    g = df.groupby("tday")
    d = pd.DataFrame({"o": g.open.first(), "h": g.high.max(),
                      "l": g.low.min(), "c": g.close.last(), "bars": g.size()})
    d = d[d.bars >= min_bars]                      # drop holiday half-sessions
    prev = d.c.shift()
    d["tr"] = np.maximum(d.h - d.l,
                         np.maximum((d.h - prev).abs(), (d.l - prev).abs()))
    return d


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    go: bool
    checks: dict = field(default_factory=dict)
    blockers: list = field(default_factory=list)
    units: float = 0.0
    lots: float = 0.0
    atr: float = float("nan")
    exit_at_ny: datetime = None
    notes: list = field(default_factory=list)

    def explain(self) -> str:
        head = "GO  — open long" if self.go else "NO-GO"
        out = [f"{head}", "-" * 46]
        for k, (ok, msg) in self.checks.items():
            out.append(f"  [{'x' if ok else ' '}] {k:<22s} {msg}")
        if self.go:
            out.append("-" * 46)
            out.append(f"  size  {self.units:.2f} oz  ({self.lots:.3f} lots)")
            out.append(f"  ATR   {self.atr:.2f}")
            out.append(f"  exit  {self.exit_at_ny:%Y-%m-%d %H:%M} NY  (market order, no stop)")
        for n in self.notes:
            out.append(f"  note: {n}")
        return "\n".join(out)


# --------------------------------------------------------------------------- #
# the analyser
# --------------------------------------------------------------------------- #
class OvernightGoldSignal:
    ENTRY_NY = dtime(18, 5)
    EXIT_NY = dtime(20, 55)

    def __init__(self,
                 sma_len: int = 200,
                 atr_len: int = 14,
                 risk_f: float = 0.025,
                 max_spread: float = 0.80,
                 min_edge_multiple: float = 2.0,
                 gross_edge_atr: float = 0.03922,
                 entry_window_min: int = 10,
                 max_stale_hours: float = 3.0,
                 contract_size: float = 100.0):
        self.sma_len = sma_len
        self.atr_len = atr_len
        self.risk_f = risk_f
        self.max_spread = max_spread
        self.min_edge_multiple = min_edge_multiple
        self.gross_edge_atr = gross_edge_atr      # measured edge, in ATR units
        self.entry_window_min = entry_window_min
        self.max_stale_hours = max_stale_hours
        self.contract_size = contract_size
        self.daily = None

    def update_daily(self, daily: pd.DataFrame):
        """daily: output of build_trading_days(), indexed by trading day."""
        d = daily.copy()
        d["atr"] = d.tr.ewm(alpha=1 / self.atr_len, adjust=False).mean()
        d["sma"] = d.c.rolling(self.sma_len).mean()
        self.daily = d
        return self

    def min_atr(self, spread: float) -> float:
        """ATR below which the spread eats more than 1/min_edge_multiple of the edge."""
        return self.min_edge_multiple * spread / self.gross_edge_atr

    def check(self, now_utc: datetime, equity: float, spread: float) -> Verdict:
        v = Verdict(go=False)
        c = v.checks
        now_ny = now_utc.astimezone(NY)

        # 1. entry window -------------------------------------------------- #
        entry_ny = now_ny.replace(hour=self.ENTRY_NY.hour, minute=self.ENTRY_NY.minute,
                                  second=0, microsecond=0)
        delta = (now_ny - entry_ny).total_seconds() / 60.0
        in_window = -1.0 <= delta <= self.entry_window_min
        c["entry window"] = (in_window,
                             f"{now_ny:%H:%M:%S} NY, target 18:05 "
                             f"({delta:+.1f} min)")

        # 2. not the Sunday-evening reopen --------------------------------- #
        not_sunday = now_ny.weekday() != 6
        c["not Sunday reopen"] = (not_sunday,
                                  f"{now_ny:%A} evening in NY")

        # 3. data present and fresh ---------------------------------------- #
        if self.daily is None or len(self.daily) < self.sma_len + self.atr_len:
            have = 0 if self.daily is None else len(self.daily)
            c["history"] = (False, f"{have} trading days, need "
                                   f"{self.sma_len + self.atr_len}")
            v.blockers.append("history")
            return v
        last = self.daily.iloc[-1]
        last_day = self.daily.index[-1]
        # the session that just ended closed at 17:00 NY today
        expected_close = now_ny.replace(hour=17, minute=0, second=0, microsecond=0)
        stale_h = (now_ny - expected_close).total_seconds() / 3600.0
        fresh = (last_day.date() == now_ny.date()) and (0 <= stale_h <= self.max_stale_hours)
        c["data fresh"] = (fresh,
                           f"last completed day {last_day:%Y-%m-%d} "
                           f"(closed {stale_h:.1f}h ago)")
        c["history"] = (True, f"{len(self.daily)} trading days")

        # 4. trend filter --------------------------------------------------- #
        above = bool(last.c > last.sma)
        c["close > SMA200"] = (above,
                               f"close {last.c:.2f} vs SMA{self.sma_len} {last.sma:.2f} "
                               f"({last.c - last.sma:+.2f})")

        # 5. cost gates ----------------------------------------------------- #
        atr = float(last.atr)
        v.atr = atr
        spread_ok = spread <= self.max_spread
        c["spread"] = (spread_ok, f"{spread:.2f} $ (max {self.max_spread:.2f})")
        need = self.min_atr(spread)
        atr_ok = atr >= need
        c["ATR gate"] = (atr_ok,
                         f"ATR {atr:.1f} vs {need:.1f} required at this spread "
                         f"(edge {self.gross_edge_atr * atr:.2f} $ vs cost {spread:.2f} $)")

        for name, (ok, _) in c.items():
            if not ok:
                v.blockers.append(name)

        v.go = not v.blockers
        if v.go:
            v.units = equity * self.risk_f / atr
            v.lots = v.units / self.contract_size
            v.exit_at_ny = now_ny.replace(hour=self.EXIT_NY.hour,
                                          minute=self.EXIT_NY.minute,
                                          second=0, microsecond=0)
            if v.lots < 0.01:
                v.notes.append(f"size {v.lots:.4f} lots is below a 0.01 minimum - "
                               f"either skip or accept the rounding risk")
        return v


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        m5 = pd.read_csv(sys.argv[1], parse_dates=["time"]).rename(columns={"time": "ts"})
        sig = OvernightGoldSignal().update_daily(build_trading_days(m5))
        last = sig.daily.index[-1]
        fake_now = pd.Timestamp(last).tz_localize(NY).replace(hour=18, minute=5) \
                     .astimezone(timezone.utc)
        print(sig.check(fake_now, equity=10_000, spread=0.28).explain())
