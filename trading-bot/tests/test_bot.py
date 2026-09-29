import numpy as np
import pandas as pd

from backtest import run
from config import Settings, StrategyParams
from risk import DailyLossGuard, position_volume
from strategy import BUY, SELL, add_indicators, signal_at


def make_bars(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=len(closes), freq="h"),
        "open": closes, "high": closes + 1, "low": closes - 1, "close": closes,
    })


P = StrategyParams(ema_fast=3, ema_slow=6, ema_trend=10, atr_period=5)


def test_buy_signal_on_upward_cross_above_trend():
    closes = [100] * 30 + [99, 98, 97, 96, 95] + list(range(96, 130))
    df = add_indicators(make_bars(closes), P)
    sides = [signal_at(df, i, P).side for i in range(len(df)) if signal_at(df, i, P)]
    assert sides and sides[0] == BUY


def test_sell_signal_on_downward_cross_below_trend():
    closes = [100] * 30 + [101, 102, 103, 104] + list(range(103, 70, -1))
    df = add_indicators(make_bars(closes), P)
    sides = [signal_at(df, i, P).side for i in range(len(df)) if signal_at(df, i, P)]
    assert SELL in sides


def test_no_signal_before_trend_ema_warmup():
    df = add_indicators(make_bars([100, 90, 110, 80, 120] * 2), P)
    assert all(signal_at(df, i, P) is None for i in range(len(df)))


def test_position_volume_matches_risk():
    # 10 000 € de solde, 1 % de risque, stop à 10 $ sur l'or, 1 USD = 1 unité de compte
    vol = position_volume(10_000, 1.0, 10.0, 1.0, min_volume=100, step_volume=100, max_volume=10**9)
    assert vol == 1000  # 10 onces = 1000 en centièmes d'unité -> perte au stop = 100


def test_position_volume_never_rounds_risk_up():
    assert position_volume(100, 0.5, 10.0, 1.0, min_volume=100, step_volume=100, max_volume=10**9) == 0


def test_daily_guard_blocks_after_limit():
    from datetime import datetime, timezone
    g = DailyLossGuard(2.0)
    day = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert g.allows_trading(1000, day)
    assert g.allows_trading(985, day)
    assert not g.allows_trading(980, day)
    assert g.allows_trading(980, datetime(2025, 1, 2, tzinfo=timezone.utc))  # nouveau jour


def test_backtest_runs_and_losses_are_bounded_by_risk():
    rng = np.random.default_rng(0)
    closes = 2000 + np.cumsum(rng.normal(0, 3, 3000))
    df = make_bars(closes)
    trades, equity = run(df, Settings(), spread=0.3, balance=10_000)
    assert trades
    # Aucune perte ne doit dépasser nettement le risque par trade (0,5 %) + spread
    for t in trades:
        assert t.pnl > -0.006 * equity.max()
