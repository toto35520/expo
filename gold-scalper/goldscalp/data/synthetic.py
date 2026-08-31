"""Simulateur de marché or, pour le mode `--demo` et les tests.

Ne sert JAMAIS a produire un signal réel : le CLI marque toute sortie issue
d'ici comme simulée, en evidence. Le générateur reproduit les propriétés qui
comptent pour valider le moteur :

  - marché aléatoire avec derive changeante (régimes de tendance/range),
  - clustering de volatilité façon GARCH,
  - profil de volatilité par session (Asie calme, Londres/NY actives),
  - volume corrélé a la volatilité,
  - meches asymetriques et chasses aux stops occasionnelles.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from goldscalp.core.microstructure import BookLevel, DerivativesStats, OrderBook, Trade
from goldscalp.core.series import Candle, Series, tf_ms
from goldscalp.util import now_ms


def _session_factor(ts: int) -> float:
    """Multiplicateur de volatilité selon l'heure UTC."""
    hour = (ts // 3_600_000) % 24
    if 0 <= hour < 6:        # Asie
        return 0.55
    if 6 <= hour < 12:       # Londres
        return 1.15
    if 12 <= hour < 17:      # chevauchement Londres/NY
        return 1.55
    if 17 <= hour < 21:      # NY
        return 1.00
    return 0.65              # fin de seance


def generate_series(timeframe: str, bars: int, start_price: float = 2400.0,
                    seed: Optional[int] = None, end_ms: Optional[int] = None,
                    trend_bias: float = 0.0) -> Series:
    rng = random.Random(seed)
    step = tf_ms(timeframe)
    end = end_ms or now_ms()
    start_ts = end - step * bars
    start_ts -= start_ts % step

    # Volatilité de base calibrée sur l'or réel : ATR(M1) autour de 0.5-0.8 $
    # en session calme, 1.0-1.5 $ sur le chevauchement Londres/NY.
    base_vol = start_price * 0.00018 * math.sqrt(step / 60000.0)
    vol = base_vol
    drift = trend_bias * base_vol * 0.12
    price = start_price
    anchor = start_price          # ancre lente : empeche la derive de diverger
    candles: list[Candle] = []

    for i in range(bars):
        ts = start_ts + i * step

        # Changement de régime occasionnel : nouvelle derive.
        # L'écart-type reste petit devant la volatilité, sinon le prix derive
        # de plusieurs pourcents en une seance - ce que l'or ne fait pas.
        if rng.random() < 0.012:
            drift = rng.gauss(trend_bias * 0.15, 0.14) * base_vol

        # Clustering de volatilité (GARCH(1,1) simplifie).
        shock = rng.gauss(0.0, 1.0)
        vol = math.sqrt(max(1e-9, 0.10 * base_vol ** 2 + 0.82 * vol ** 2 + 0.08 * (shock * vol) ** 2))
        vol = min(vol, base_vol * 6.0)
        effective = vol * _session_factor(ts)

        # Rappel elastique vers l'ancre (l'or oscille, il ne diverge pas).
        anchor += (price - anchor) * 0.002
        pull = (anchor - price) * 0.004

        open_price = price
        close_price = open_price + drift + pull + shock * effective

        wick_up = abs(rng.gauss(0, effective * 0.75))
        wick_down = abs(rng.gauss(0, effective * 0.75))
        # 3 % de chasses aux stops : une longue meche d'un cote.
        if rng.random() < 0.03:
            if rng.random() < 0.5:
                wick_down *= rng.uniform(2.5, 4.5)
            else:
                wick_up *= rng.uniform(2.5, 4.5)

        high = max(open_price, close_price) + wick_up
        low = min(open_price, close_price) - wick_down
        move = abs(close_price - open_price)
        volume = max(1.0, rng.gauss(500, 120) * _session_factor(ts) * (1 + move / max(effective, 1e-9) * 0.35))

        candles.append(
            Candle(ts, open_price, high, low, close_price, round(volume, 3),
                   round(volume * close_price, 2))
        )
        price = close_price

    if candles:
        live = candles[-1]
        candles[-1] = Candle(live.ts, live.open, live.high, live.low, live.close,
                             live.volume, live.turnover, closed=False)
    return Series(timeframe, candles, symbol="XAUTUSDT[SIMULE]")


def generate_orderbook(mid: float, seed: Optional[int] = None, levels: int = 50,
                       bias: float = 0.0) -> OrderBook:
    rng = random.Random(seed)
    tick = 0.05
    bids = [
        BookLevel(round(mid - tick * (i + 1), 2), max(0.01, rng.gauss(3.0 * (1 + bias), 1.0)))
        for i in range(levels)
    ]
    asks = [
        BookLevel(round(mid + tick * (i + 1), 2), max(0.01, rng.gauss(3.0 * (1 - bias), 1.0)))
        for i in range(levels)
    ]
    return OrderBook(now_ms(), bids, asks)


def generate_trades(mid: float, count: int = 600, seed: Optional[int] = None,
                    buy_ratio: float = 0.5) -> list[Trade]:
    rng = random.Random(seed)
    start = now_ms() - count * 500
    out: list[Trade] = []
    for i in range(count):
        side = "Buy" if rng.random() < buy_ratio else "Sell"
        out.append(
            Trade(
                ts=start + i * 500,
                price=round(mid + rng.gauss(0, 0.3), 2),
                size=round(abs(rng.gauss(0.8, 0.6)) + 0.01, 4),
                side=side,
            )
        )
    return out


def generate_derivatives(seed: Optional[int] = None, bias: float = 0.0) -> DerivativesStats:
    rng = random.Random(seed)
    funding = [rng.gauss(0.0001, 0.00008) for _ in range(40)]
    funding[-1] += bias * 0.0003
    oi = [100000.0]
    for _ in range(30):
        oi.append(oi[-1] * (1 + rng.gauss(bias * 0.002, 0.004)))
    prices = [2400.0]
    for _ in range(30):
        prices.append(prices[-1] * (1 + rng.gauss(bias * 0.0004, 0.001)))
    from goldscalp.core.microstructure import analyse_derivatives

    return analyse_derivatives(funding, oi, prices)


def generate_macro(seed: Optional[int] = None, gold_bias: float = 0.0) -> dict:
    """Séries macro simulées, coherentes avec un biais or donne."""
    from goldscalp.data.macro import MacroSeries, MACRO_SYMBOLS

    rng = random.Random(seed)
    out: dict[str, MacroSeries] = {}
    for key, _, _, corr in MACRO_SYMBOLS:
        base = {"dxy": 104.0, "us10y": 42.0, "us02y": 44.0, "vix": 15.0,
                "spx": 5600.0, "silver": 29.0, "oil": 78.0}.get(key, 100.0)
        closes = [base]
        # corrélation attendue : si l'or monte, le DXY doit baisser
        # corr = corrélation attendue AVEC l'or : un biais or haussier doit
        # faire BAISSER le DXY (corr -1) et monter l'argent (corr +0.7).
        drift = corr * gold_bias * 0.0004
        for _ in range(120):
            closes.append(closes[-1] * (1 + rng.gauss(drift, 0.0015)))
        out[key] = MacroSeries(key=key, closes=closes, correlation=corr, source="simule")
    return out
