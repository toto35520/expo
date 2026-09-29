"""Stratégie de suivi de tendance : croisement d'EMA filtré par l'EMA 200, stops basés sur l'ATR.

Règles (évaluées uniquement sur des bougies CLÔTURÉES) :
  - Achat  : EMA rapide croise au-dessus de l'EMA lente ET clôture > EMA tendance
  - Vente  : EMA rapide croise en dessous de l'EMA lente ET clôture < EMA tendance
  - Sortie : stop loss / take profit à SL_ATR / TP_ATR x ATR, ou croisement inverse.
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import StrategyParams

BUY, SELL = 1, -1


@dataclass
class Signal:
    side: int              # BUY ou SELL
    sl_distance: float     # distance du stop en unités de prix
    tp_distance: float


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()  # lissage de Wilder


def add_indicators(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], p.ema_fast)
    df["ema_slow"] = ema(df["close"], p.ema_slow)
    df["ema_trend"] = ema(df["close"], p.ema_trend)
    df["atr"] = atr(df, p.atr_period)
    above = df["ema_fast"] > df["ema_slow"]
    df["cross"] = 0
    df.loc[above & ~above.shift(1, fill_value=False), "cross"] = BUY
    df.loc[~above & above.shift(1, fill_value=True), "cross"] = SELL
    # Pas de signal tant que l'EMA de tendance n'a pas assez d'historique
    df.loc[df.index[: p.ema_trend], "cross"] = 0
    return df


def signal_at(df: pd.DataFrame, i: int, p: StrategyParams) -> Optional[Signal]:
    """Signal d'entrée sur la bougie i (df doit déjà contenir les indicateurs)."""
    row = df.iloc[i]
    if row["cross"] == BUY and row["close"] > row["ema_trend"]:
        side = BUY
    elif row["cross"] == SELL and row["close"] < row["ema_trend"]:
        side = SELL
    else:
        return None
    return Signal(side, p.sl_atr * row["atr"], p.tp_atr * row["atr"])


def exit_at(df: pd.DataFrame, i: int, position_side: int) -> bool:
    """Sortie anticipée : croisement dans le sens inverse de la position."""
    return int(df.iloc[i]["cross"]) == -position_side


def min_bars(p: StrategyParams) -> int:
    return p.ema_trend + 50
