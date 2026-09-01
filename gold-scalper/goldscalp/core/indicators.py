"""Indicateurs techniques en Python pur.

Convention : chaque fonction renvoie une `Line` (liste alignee sur l'entrée)
ou les valeurs non définies valent `None`. Pas de NaN : les comparaisons
silencieusement fausses sur NaN sont une source classique de bugs de trading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from goldscalp.core.series import Candle, Series
from goldscalp.util import clamp, mean, safe_div, stdev

Line = list[Optional[float]]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def last(line: Line, offset: int = 0) -> Optional[float]:
    """Derniere valeur définie a `offset` barres du bord droit."""
    idx = len(line) - 1 - offset
    if idx < 0 or idx >= len(line):
        return None
    return line[idx]


def last_valid(line: Line) -> Optional[float]:
    for value in reversed(line):
        if value is not None:
            return value
    return None


def valid_tail(line: Line, n: int) -> list[float]:
    """Les `n` dernières valeurs définies (ordre chronologique)."""
    out: list[float] = []
    for value in reversed(line):
        if value is None:
            continue
        out.append(value)
        if len(out) >= n:
            break
    return list(reversed(out))


def slope_of(line: Line, lookback: int = 5) -> Optional[float]:
    """Variation moyenne par barre sur les `lookback` dernières valeurs."""
    tail = valid_tail(line, lookback + 1)
    if len(tail) < 2:
        return None
    return (tail[-1] - tail[0]) / (len(tail) - 1)


# --------------------------------------------------------------------------- #
# Moyennes
# --------------------------------------------------------------------------- #

def sma(values: Sequence[float], period: int) -> Line:
    out: Line = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


def ema(values: Sequence[float], period: int) -> Line:
    out: Line = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rma(values: Sequence[float], period: int) -> Line:
    """Moyenne lissee de Wilder (utilisée par RSI / ATR / ADX)."""
    out: Line = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def wma(values: Sequence[float], period: int) -> Line:
    out: Line = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    denom = period * (period + 1) / 2
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        out[i] = sum(v * (k + 1) for k, v in enumerate(window)) / denom
    return out


def hma(values: Sequence[float], period: int) -> Line:
    """Hull MA : très reactive, utile pour le déclencheur M1."""
    if period < 2 or len(values) < period:
        return [None] * len(values)
    half = wma(values, max(1, period // 2))
    full = wma(values, period)
    raw = [
        (2 * h - f) if (h is not None and f is not None) else None
        for h, f in zip(half, full)
    ]
    dense = [v for v in raw if v is not None]
    smoothed = wma(dense, max(1, int(math.sqrt(period))))
    out: Line = [None] * len(values)
    cursor = 0
    for i, value in enumerate(raw):
        if value is None:
            continue
        out[i] = smoothed[cursor]
        cursor += 1
    return out


# --------------------------------------------------------------------------- #
# Volatilité
# --------------------------------------------------------------------------- #

def true_range(candles: Sequence[Candle]) -> list[float]:
    out: list[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            out.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            out.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> Line:
    return rma(true_range(candles), period)


def bollinger(values: Sequence[float], period: int = 20, mult: float = 2.0) -> tuple[Line, Line, Line]:
    basis = sma(values, period)
    upper: Line = [None] * len(values)
    lower: Line = [None] * len(values)
    for i in range(period - 1, len(values)):
        if basis[i] is None:
            continue
        sd = stdev(values[i - period + 1 : i + 1])
        upper[i] = basis[i] + mult * sd
        lower[i] = basis[i] - mult * sd
    return upper, basis, lower


def bb_width(upper: Line, basis: Line, lower: Line) -> Line:
    out: Line = [None] * len(basis)
    for i, (u, b, l) in enumerate(zip(upper, basis, lower)):
        if u is None or b is None or l is None or b == 0:
            continue
        out[i] = (u - l) / b * 100.0
    return out


def percent_b(values: Sequence[float], upper: Line, lower: Line) -> Line:
    out: Line = [None] * len(values)
    for i, value in enumerate(values):
        u, l = upper[i], lower[i]
        if u is None or l is None or u == l:
            continue
        out[i] = (value - l) / (u - l)
    return out


def keltner(candles: Sequence[Candle], period: int = 20, mult: float = 1.5) -> tuple[Line, Line, Line]:
    typical = [c.close for c in candles]
    basis = ema(typical, period)
    atr_line = atr(candles, period)
    upper: Line = [None] * len(candles)
    lower: Line = [None] * len(candles)
    for i, (b, a) in enumerate(zip(basis, atr_line)):
        if b is None or a is None:
            continue
        upper[i] = b + mult * a
        lower[i] = b - mult * a
    return upper, basis, lower


def squeeze(candles: Sequence[Candle], period: int = 20) -> list[bool]:
    """TTM squeeze : bandes de Bollinger a l'intérieur des canaux de Keltner."""
    closes = [c.close for c in candles]
    bu, _, bl = bollinger(closes, period, 2.0)
    ku, _, kl = keltner(candles, period, 1.5)
    out: list[bool] = []
    for i in range(len(candles)):
        if None in (bu[i], bl[i], ku[i], kl[i]):
            out.append(False)
        else:
            out.append(bu[i] < ku[i] and bl[i] > kl[i])  # type: ignore[operator]
    return out


# --------------------------------------------------------------------------- #
# Momentum
# --------------------------------------------------------------------------- #

def rsi(values: Sequence[float], period: int = 14) -> Line:
    if len(values) < period + 1:
        return [None] * len(values)
    gains = [0.0]
    losses = [0.0]
    for prev, cur in zip(values, values[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = rma(gains[1:], period)
    avg_loss = rma(losses[1:], period)
    out: Line = [None] * len(values)
    for i in range(len(avg_gain)):
        g, l = avg_gain[i], avg_loss[i]
        if g is None or l is None:
            continue
        if l == 0:
            out[i + 1] = 100.0
        else:
            rs = g / l
            out[i + 1] = 100.0 - 100.0 / (1 + rs)
    return out


def stochastic(candles: Sequence[Candle], k_period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> tuple[Line, Line]:
    raw: Line = [None] * len(candles)
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1 : i + 1]
        hh = max(c.high for c in window)
        ll = min(c.low for c in window)
        raw[i] = 100.0 * safe_div(candles[i].close - ll, hh - ll, 0.5)
    dense = [v for v in raw if v is not None]
    k_dense = sma(dense, k_smooth)
    d_dense = sma([v for v in k_dense if v is not None], d_smooth)

    k_line: Line = [None] * len(candles)
    cursor = 0
    for i, value in enumerate(raw):
        if value is None:
            continue
        k_line[i] = k_dense[cursor]
        cursor += 1

    d_line: Line = [None] * len(candles)
    dense_k_indices = [i for i, v in enumerate(k_line) if v is not None]
    for pos, idx in enumerate(dense_k_indices):
        d_line[idx] = d_dense[pos]
    return k_line, d_line


def stoch_rsi(values: Sequence[float], rsi_period: int = 14, stoch_period: int = 14,
              k_smooth: int = 3, d_smooth: int = 3) -> tuple[Line, Line]:
    rsi_line = rsi(values, rsi_period)
    raw: Line = [None] * len(values)
    for i in range(len(values)):
        window = [v for v in rsi_line[max(0, i - stoch_period + 1) : i + 1] if v is not None]
        if len(window) < stoch_period:
            continue
        hh, ll = max(window), min(window)
        raw[i] = 100.0 * safe_div(window[-1] - ll, hh - ll, 0.5)
    dense = [v for v in raw if v is not None]
    k_dense = sma(dense, k_smooth)
    k_line: Line = [None] * len(values)
    cursor = 0
    for i, value in enumerate(raw):
        if value is None:
            continue
        k_line[i] = k_dense[cursor]
        cursor += 1
    valid_k = [v for v in k_line if v is not None]
    d_dense = sma(valid_k, d_smooth)
    d_line: Line = [None] * len(values)
    for pos, idx in enumerate([i for i, v in enumerate(k_line) if v is not None]):
        d_line[idx] = d_dense[pos]
    return k_line, d_line


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Line, Line, Line]:
    fast_line = ema(values, fast)
    slow_line = ema(values, slow)
    macd_line: Line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_line, slow_line)
    ]
    dense = [v for v in macd_line if v is not None]
    sig_dense = ema(dense, signal)
    signal_line: Line = [None] * len(values)
    for pos, idx in enumerate([i for i, v in enumerate(macd_line) if v is not None]):
        signal_line[idx] = sig_dense[pos]
    hist: Line = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist


def roc(values: Sequence[float], period: int = 10) -> Line:
    out: Line = [None] * len(values)
    for i in range(period, len(values)):
        base = values[i - period]
        if base == 0:
            continue
        out[i] = (values[i] - base) / base * 100.0
    return out


def cci(candles: Sequence[Candle], period: int = 20) -> Line:
    typical = [c.hlc3 for c in candles]
    ma = sma(typical, period)
    out: Line = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        if ma[i] is None:
            continue
        window = typical[i - period + 1 : i + 1]
        mad = mean([abs(v - ma[i]) for v in window])  # type: ignore[operator]
        if mad == 0:
            continue
        out[i] = (typical[i] - ma[i]) / (0.015 * mad)  # type: ignore[operator]
    return out


def williams_r(candles: Sequence[Candle], period: int = 14) -> Line:
    out: Line = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        hh = max(c.high for c in window)
        ll = min(c.low for c in window)
        out[i] = -100.0 * safe_div(hh - candles[i].close, hh - ll, 0.5)
    return out


# --------------------------------------------------------------------------- #
# Tendance
# --------------------------------------------------------------------------- #

def adx(candles: Sequence[Candle], period: int = 14) -> tuple[Line, Line, Line]:
    """Renvoie (adx, +DI, -DI)."""
    n = len(candles)
    if n < period * 2:
        return [None] * n, [None] * n, [None] * n

    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    for prev, cur in zip(candles, candles[1:]):
        up = cur.high - prev.high
        down = prev.low - cur.low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    tr = true_range(candles)
    tr_s = rma(tr[1:], period)
    plus_s = rma(plus_dm[1:], period)
    minus_s = rma(minus_dm[1:], period)

    plus_di: Line = [None] * n
    minus_di: Line = [None] * n
    dx: Line = [None] * n
    for i in range(len(tr_s)):
        t, p, m = tr_s[i], plus_s[i], minus_s[i]
        if t is None or p is None or m is None or t == 0:
            continue
        pdi = 100.0 * p / t
        mdi = 100.0 * m / t
        plus_di[i + 1] = pdi
        minus_di[i + 1] = mdi
        total = pdi + mdi
        dx[i + 1] = 100.0 * safe_div(abs(pdi - mdi), total, 0.0)

    dense_dx = [v for v in dx if v is not None]
    adx_dense = rma(dense_dx, period)
    adx_line: Line = [None] * n
    for pos, idx in enumerate([i for i, v in enumerate(dx) if v is not None]):
        adx_line[idx] = adx_dense[pos]
    return adx_line, plus_di, minus_di


def supertrend(candles: Sequence[Candle], period: int = 10, mult: float = 3.0) -> tuple[Line, list[int]]:
    """Renvoie (ligne supertrend, direction) ou direction vaut +1 (haussier) / -1."""
    n = len(candles)
    atr_line = atr(candles, period)
    st: Line = [None] * n
    direction: list[int] = [0] * n

    final_upper: Optional[float] = None
    final_lower: Optional[float] = None
    prev_dir = 1
    for i, candle in enumerate(candles):
        a = atr_line[i]
        if a is None:
            continue
        mid = (candle.high + candle.low) / 2.0
        basic_upper = mid + mult * a
        basic_lower = mid - mult * a
        prev_close = candles[i - 1].close if i > 0 else candle.close

        if final_upper is None or basic_upper < final_upper or prev_close > final_upper:
            final_upper = basic_upper
        if final_lower is None or basic_lower > final_lower or prev_close < final_lower:
            final_lower = basic_lower

        if candle.close > final_upper:
            prev_dir = 1
        elif candle.close < final_lower:
            prev_dir = -1
        direction[i] = prev_dir
        st[i] = final_lower if prev_dir == 1 else final_upper
    return st, direction


def efficiency_ratio(values: Sequence[float], period: int = 20) -> Line:
    """Kaufman ER : 1 = tendance parfaite, 0 = bruit pur. Cle pour le régime."""
    out: Line = [None] * len(values)
    for i in range(period, len(values)):
        direction = abs(values[i] - values[i - period])
        volatility = sum(abs(values[j] - values[j - 1]) for j in range(i - period + 1, i + 1))
        out[i] = safe_div(direction, volatility, 0.0)
    return out


def donchian(candles: Sequence[Candle], period: int = 20) -> tuple[Line, Line, Line]:
    upper: Line = [None] * len(candles)
    lower: Line = [None] * len(candles)
    mid: Line = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        hh = max(c.high for c in window)
        ll = min(c.low for c in window)
        upper[i], lower[i], mid[i] = hh, ll, (hh + ll) / 2.0
    return upper, mid, lower


# --------------------------------------------------------------------------- #
# Volume / flux
# --------------------------------------------------------------------------- #

def obv(candles: Sequence[Candle]) -> Line:
    out: Line = [None] * len(candles)
    if not candles:
        return out
    running = 0.0
    out[0] = 0.0
    for i in range(1, len(candles)):
        if candles[i].close > candles[i - 1].close:
            running += candles[i].volume
        elif candles[i].close < candles[i - 1].close:
            running -= candles[i].volume
        out[i] = running
    return out


def vwap_session(candles: Sequence[Candle], session_ms: int = 86_400_000) -> tuple[Line, Line, Line]:
    """VWAP ancre par session (journee UTC par défaut) + bandes à 1 écart-type."""
    n = len(candles)
    vwap: Line = [None] * n
    upper: Line = [None] * n
    lower: Line = [None] * n

    cum_pv = 0.0
    cum_v = 0.0
    cum_pv2 = 0.0
    current_session = None
    for i, candle in enumerate(candles):
        session = candle.ts // session_ms
        if session != current_session:
            current_session = session
            cum_pv = cum_v = cum_pv2 = 0.0
        price = candle.hlc3
        volume = candle.volume if candle.volume > 0 else 1.0
        cum_pv += price * volume
        cum_v += volume
        cum_pv2 += price * price * volume
        mean_price = cum_pv / cum_v
        vwap[i] = mean_price
        variance = max(cum_pv2 / cum_v - mean_price * mean_price, 0.0)
        sd = math.sqrt(variance)
        upper[i] = mean_price + sd
        lower[i] = mean_price - sd
    return upper, vwap, lower


def volume_zscore(candles: Sequence[Candle], period: int = 50) -> Line:
    volumes = [c.volume for c in candles]
    out: Line = [None] * len(candles)
    for i in range(period, len(candles)):
        window = volumes[i - period : i]
        sd = stdev(window)
        if sd <= 0:
            continue
        out[i] = (volumes[i] - mean(window)) / sd
    return out


@dataclass
class VolumeProfile:
    poc: float          # Point of Control : prix au volume max
    vah: float          # Value Area High (70%)
    val: float          # Value Area Low
    bins: list[tuple[float, float]]  # (prix milieu, volume)

    def nearest_hvn(self, price: float) -> float:
        """Noeud de volume élevé le plus proche : aimant a prix."""
        if not self.bins:
            return price
        ranked = sorted(self.bins, key=lambda b: b[1], reverse=True)
        top = ranked[: max(3, len(ranked) // 5)]
        return min((b[0] for b in top), key=lambda p: abs(p - price))


def volume_profile(candles: Sequence[Candle], bins: int = 48) -> Optional[VolumeProfile]:
    """Profil de volume approximé : le volume d'une bougie est réparti
    uniformement sur son range. Suffisamment precis pour trouver POC/VA."""
    if len(candles) < 10:
        return None
    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    buckets = [0.0] * bins

    for candle in candles:
        volume = candle.volume if candle.volume > 0 else 1.0
        start = int(clamp((candle.low - lo) / width, 0, bins - 1))
        end = int(clamp((candle.high - lo) / width, 0, bins - 1))
        span = end - start + 1
        share = volume / span
        for b in range(start, end + 1):
            buckets[b] += share

    poc_idx = max(range(bins), key=lambda i: buckets[i])
    total = sum(buckets)
    target = total * 0.70
    covered = buckets[poc_idx]
    low_idx = high_idx = poc_idx
    while covered < target and (low_idx > 0 or high_idx < bins - 1):
        take_low = buckets[low_idx - 1] if low_idx > 0 else -1.0
        take_high = buckets[high_idx + 1] if high_idx < bins - 1 else -1.0
        if take_high >= take_low:
            high_idx += 1
            covered += max(take_high, 0.0)
        else:
            low_idx -= 1
            covered += max(take_low, 0.0)

    center = lambda i: lo + width * (i + 0.5)  # noqa: E731
    return VolumeProfile(
        poc=center(poc_idx),
        vah=center(high_idx),
        val=center(low_idx),
        bins=[(center(i), buckets[i]) for i in range(bins)],
    )


# --------------------------------------------------------------------------- #
# Divergences
# --------------------------------------------------------------------------- #

@dataclass
class Divergence:
    kind: str        # "bullish" | "bearish" | "hidden_bullish" | "hidden_bearish"
    strength: float  # 0..1
    bars_ago: int


def find_divergence(candles: Sequence[Candle], oscillator: Line, lookback: int = 60,
                    pivot_span: int = 3) -> Optional[Divergence]:
    """Divergence regulière/cachée entre le prix et un oscillateur.

    On compare les deux derniers pivots de même sens dans la fenêtre.
    """
    n = len(candles)
    if n < lookback + pivot_span * 2 + 2:
        return None
    start = n - lookback

    def pivots(low_side: bool) -> list[int]:
        found: list[int] = []
        for i in range(max(start, pivot_span), n - pivot_span):
            window = candles[i - pivot_span : i + pivot_span + 1]
            if low_side:
                if candles[i].low == min(c.low for c in window):
                    found.append(i)
            else:
                if candles[i].high == max(c.high for c in window):
                    found.append(i)
        return found

    def compare(indices: list[int], low_side: bool) -> Optional[Divergence]:
        usable = [i for i in indices if oscillator[i] is not None]
        if len(usable) < 2:
            return None
        prev_i, cur_i = usable[-2], usable[-1]
        price_prev = candles[prev_i].low if low_side else candles[prev_i].high
        price_cur = candles[cur_i].low if low_side else candles[cur_i].high
        osc_prev = oscillator[prev_i]
        osc_cur = oscillator[cur_i]
        assert osc_prev is not None and osc_cur is not None
        price_delta = price_cur - price_prev
        osc_delta = osc_cur - osc_prev
        if abs(price_delta) < 1e-9:
            return None
        bars_ago = n - 1 - cur_i

        if low_side:
            if price_delta < 0 < osc_delta:      # plus bas plus bas, oscillateur plus haut
                kind = "bullish"
            elif price_delta > 0 > osc_delta:    # plus bas plus haut, oscillateur plus bas
                kind = "hidden_bullish"
            else:
                return None
        else:
            if price_delta > 0 > osc_delta:
                kind = "bearish"
            elif price_delta < 0 < osc_delta:
                kind = "hidden_bearish"
            else:
                return None

        magnitude = min(abs(osc_delta) / 20.0, 1.0)
        recency = clamp(1.0 - bars_ago / max(lookback / 2.0, 1.0), 0.0, 1.0)
        return Divergence(kind, round(magnitude * 0.6 + recency * 0.4, 3), bars_ago)

    bull = compare(pivots(True), True)
    bear = compare(pivots(False), False)
    if bull and bear:
        return bull if bull.bars_ago <= bear.bars_ago else bear
    return bull or bear


# --------------------------------------------------------------------------- #
# Patterns de bougies
# --------------------------------------------------------------------------- #

def candle_patterns(candles: Sequence[Candle], atr_value: Optional[float]) -> list[str]:
    """Patterns détectés sur les 3 dernières bougies clôturées."""
    if len(candles) < 3:
        return []
    c0, c1, c2 = candles[-1], candles[-2], candles[-3]
    found: list[str] = []
    scale = atr_value if atr_value and atr_value > 0 else max(c0.range, 1e-6)

    if c0.body > 0 and c1.body > 0:
        if c0.bullish and not c1.bullish and c0.close >= c1.open and c0.open <= c1.close:
            found.append("engulfing_haussier")
        if not c0.bullish and c1.bullish and c0.close <= c1.open and c0.open >= c1.close:
            found.append("engulfing_baissier")

    if c0.range > 0:
        if c0.lower_wick > c0.body * 2 and c0.upper_wick < c0.body and c0.range > scale * 0.6:
            found.append("marteau")
        if c0.upper_wick > c0.body * 2 and c0.lower_wick < c0.body and c0.range > scale * 0.6:
            found.append("etoile_filante")
        if c0.body < c0.range * 0.12:
            found.append("doji")
        if c0.body > c0.range * 0.85 and c0.range > scale * 0.9:
            found.append("marubozu_haussier" if c0.bullish else "marubozu_baissier")

    if c0.high <= c1.high and c0.low >= c1.low:
        found.append("inside_bar")
    if c0.high > c1.high and c0.low < c1.low:
        found.append("outside_bar")

    # Trois soldats / trois corbeaux
    trio = [c2, c1, c0]
    if all(c.bullish and c.body > c.range * 0.5 for c in trio) and c2.close < c1.close < c0.close:
        found.append("trois_soldats_blancs")
    if all(not c.bullish and c.body > c.range * 0.5 for c in trio) and c2.close > c1.close > c0.close:
        found.append("trois_corbeaux_noirs")

    return found


# --------------------------------------------------------------------------- #
# Bundle : tout calculer une fois par timeframe
# --------------------------------------------------------------------------- #

@dataclass
class IndicatorSet:
    """Tous les indicateurs d'un timeframe, calcules une seule fois."""

    series: Series
    ema9: Line
    ema21: Line
    ema50: Line
    ema200: Line
    hma20: Line
    rsi14: Line
    stoch_k: Line
    stoch_d: Line
    srsi_k: Line
    srsi_d: Line
    macd_line: Line
    macd_signal: Line
    macd_hist: Line
    atr14: Line
    adx14: Line
    plus_di: Line
    minus_di: Line
    bb_upper: Line
    bb_basis: Line
    bb_lower: Line
    bb_width: Line
    pct_b: Line
    kc_upper: Line
    kc_lower: Line
    squeeze_on: list[bool]
    st_line: Line
    st_dir: list[int]
    vwap: Line
    vwap_upper: Line
    vwap_lower: Line
    obv: Line
    vol_z: Line
    er: Line
    cci: Line
    willr: Line
    roc5: Line
    dc_upper: Line
    dc_mid: Line
    dc_lower: Line
    profile: Optional[VolumeProfile]
    divergence: Optional[Divergence]
    patterns: list[str]

    @property
    def price(self) -> float:
        return self.series.last.close

    @property
    def atr_value(self) -> float:
        value = last_valid(self.atr14)
        return value if value and value > 0 else max(self.series.last.range, 0.01)


def compute_indicators(series: Series, profile_bars: int = 240) -> IndicatorSet:
    """Calcule le jeu complet d'indicateurs sur une série CLOTUREE."""
    candles = series.candles
    closes = [c.close for c in candles]

    bb_u, bb_b, bb_l = bollinger(closes, 20, 2.0)
    kc_u, _, kc_l = keltner(candles, 20, 1.5)
    macd_l, macd_s, macd_h = macd(closes)
    stoch_k, stoch_d = stochastic(candles)
    srsi_k, srsi_d = stoch_rsi(closes)
    adx_l, pdi, mdi = adx(candles)
    st_l, st_d = supertrend(candles)
    vw_u, vw, vw_l = vwap_session(candles)
    dc_u, dc_m, dc_l = donchian(candles, 20)
    rsi_line = rsi(closes, 14)
    atr_line = atr(candles, 14)

    return IndicatorSet(
        series=series,
        ema9=ema(closes, 9),
        ema21=ema(closes, 21),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        hma20=hma(closes, 20),
        rsi14=rsi_line,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        srsi_k=srsi_k,
        srsi_d=srsi_d,
        macd_line=macd_l,
        macd_signal=macd_s,
        macd_hist=macd_h,
        atr14=atr_line,
        adx14=adx_l,
        plus_di=pdi,
        minus_di=mdi,
        bb_upper=bb_u,
        bb_basis=bb_b,
        bb_lower=bb_l,
        bb_width=bb_width(bb_u, bb_b, bb_l),
        pct_b=percent_b(closes, bb_u, bb_l),
        kc_upper=kc_u,
        kc_lower=kc_l,
        squeeze_on=squeeze(candles),
        st_line=st_l,
        st_dir=st_d,
        vwap=vw,
        vwap_upper=vw_u,
        vwap_lower=vw_l,
        obv=obv(candles),
        vol_z=volume_zscore(candles),
        er=efficiency_ratio(closes, 20),
        cci=cci(candles),
        willr=williams_r(candles),
        roc5=roc(closes, 5),
        dc_upper=dc_u,
        dc_mid=dc_m,
        dc_lower=dc_l,
        profile=volume_profile(candles[-profile_bars:]),
        divergence=find_divergence(candles, rsi_line),
        patterns=candle_patterns(candles, last_valid(atr_line)),
    )
