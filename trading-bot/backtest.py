"""Backtest de la stratégie sur un CSV de bougies (colonnes : time, open, high, low, close).

Obtenir l'historique de ton courtier :  python bot.py --download 365
Puis :                                  python backtest.py data/XAUUSD_H1.csv --spread 0.30

Hypothèses conservatrices : entrée à l'ouverture de la bougie suivant le signal,
spread payé à chaque trade, et si le SL et le TP sont touchés dans la même bougie
on considère que c'est le SL.
"""
import argparse
from dataclasses import dataclass

import pandas as pd

from config import Settings
from strategy import BUY, add_indicators, exit_at, signal_at


@dataclass
class Trade:
    side: int
    entry_time: pd.Timestamp
    entry: float
    sl: float
    tp: float
    units: float
    exit_time: pd.Timestamp = None
    exit: float = None
    pnl: float = 0.0


def run(df: pd.DataFrame, settings: Settings, spread: float, balance: float = 10_000.0):
    p = settings.strategy
    df = add_indicators(df, p)
    equity = [balance]
    trades, pos = [], None
    # Les bougies cTrader sont en prix BID : un achat se fait au ask (bid + spread)
    # et une position vendeuse se ferme au ask.
    def ask(side):  # surcoût pour clôturer
        return spread if side != BUY else 0.0

    def close(t: Trade, price: float, when):
        nonlocal balance
        t.exit, t.exit_time = price, when
        t.pnl = (price - t.entry) * t.side * t.units
        balance += t.pnl
        trades.append(t)

    for i in range(len(df) - 1):
        bar, nxt = df.iloc[i], df.iloc[i + 1]
        if pos is not None:
            # Achat clôturé au bid, vente clôturée au ask
            if pos.side == BUY:
                hit_sl, hit_tp = bar["low"] <= pos.sl, bar["high"] >= pos.tp
            else:
                hit_sl, hit_tp = bar["high"] + spread >= pos.sl, bar["low"] + spread <= pos.tp
            if hit_sl:
                close(pos, pos.sl, bar["time"]); pos = None
            elif hit_tp:
                close(pos, pos.tp, bar["time"]); pos = None
            elif exit_at(df, i, pos.side):
                close(pos, nxt["open"] + ask(pos.side), nxt["time"]); pos = None
        if pos is None:
            sig = signal_at(df, i, p)
            if sig is not None:
                entry = nxt["open"] + (spread if sig.side == BUY else 0.0)
                units = balance * settings.risk_per_trade_pct / 100 / sig.sl_distance
                pos = Trade(sig.side, nxt["time"], entry,
                            entry - sig.side * sig.sl_distance,
                            entry + sig.side * sig.tp_distance, units)
        equity.append(balance)

    if pos is not None:
        close(pos, df.iloc[-1]["close"] + ask(pos.side), df.iloc[-1]["time"])
        equity.append(balance)
    return trades, pd.Series(equity)


def report(trades, equity: pd.Series, start: float):
    if not trades:
        print("Aucun trade sur la période.")
        return
    pnl = pd.Series([t.pnl for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    dd = ((equity - equity.cummax()) / equity.cummax()).min() * 100
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    print(f"Trades           : {len(trades)}")
    print(f"Taux de réussite : {len(wins) / len(trades) * 100:.1f} %")
    print(f"Profit factor    : {pf:.2f}")
    print(f"Rendement total  : {(equity.iloc[-1] / start - 1) * 100:+.2f} %")
    print(f"Drawdown max     : {dd:.2f} %")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--spread", type=float, default=0.30, help="spread moyen en unités de prix")
    ap.add_argument("--balance", type=float, default=10_000.0)
    args = ap.parse_args()
    df = pd.read_csv(args.csv, parse_dates=["time"])
    trades, equity = run(df, Settings(), args.spread, args.balance)
    report(trades, equity, args.balance)


if __name__ == "__main__":
    main()
