"""Bougies OHLCV et series temporelles.

Convention : une `Series` est triee du plus ancien au plus recent, et la
derniere bougie peut etre en cours de formation (`closed=False`). Tous les
indicateurs travaillent sur les bougies CLOTUREES pour eviter le repaint,
sauf mention explicite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Sequence

from goldscalp.util import ms_to_iso

TF_MINUTES: dict[str, int] = {
    "M1": 1,
    "M3": 3,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# Correspondance avec le parametre `interval` de l'API Bybit v5.
TF_BYBIT: dict[str, str] = {
    "M1": "1",
    "M3": "3",
    "M5": "5",
    "M15": "15",
    "M30": "30",
    "H1": "60",
    "H4": "240",
    "D1": "D",
}


def tf_ms(timeframe: str) -> int:
    return TF_MINUTES[timeframe] * 60_000


@dataclass(frozen=True)
class Candle:
    ts: int          # timestamp d'OUVERTURE, en ms UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover: float = 0.0
    closed: bool = True

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def bullish(self) -> bool:
        return self.close >= self.open

    @property
    def hlc3(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def ohlc4(self) -> float:
        return (self.open + self.high + self.low + self.close) / 4.0

    def shifted(self, intercept: float, slope: float) -> "Candle":
        """Applique la transformation affine de calibration Bybit -> MT5."""
        return Candle(
            ts=self.ts,
            open=intercept + slope * self.open,
            high=intercept + slope * self.high,
            low=intercept + slope * self.low,
            close=intercept + slope * self.close,
            volume=self.volume,
            turnover=self.turnover,
            closed=self.closed,
        )

    def __repr__(self) -> str:  # pragma: no cover - confort de debug
        return (
            f"Candle({ms_to_iso(self.ts)} O{self.open:.2f} H{self.high:.2f} "
            f"L{self.low:.2f} C{self.close:.2f} V{self.volume:.0f})"
        )


@dataclass
class Series:
    """Suite de bougies pour un timeframe donne."""

    timeframe: str
    candles: list[Candle] = field(default_factory=list)
    symbol: str = "XAUUSD"

    # -- protocole sequence ------------------------------------------------ #
    def __len__(self) -> int:
        return len(self.candles)

    def __iter__(self) -> Iterator[Candle]:
        return iter(self.candles)

    def __getitem__(self, item):  # type: ignore[no-untyped-def]
        return self.candles[item]

    def __bool__(self) -> bool:
        return bool(self.candles)

    # -- accesseurs -------------------------------------------------------- #
    @property
    def last(self) -> Candle:
        return self.candles[-1]

    @property
    def closed_only(self) -> "Series":
        """Vue sans la bougie en cours (anti-repaint)."""
        if self.candles and not self.candles[-1].closed:
            return Series(self.timeframe, self.candles[:-1], self.symbol)
        return self

    def field(self, name: str) -> list[float]:
        return [getattr(c, name) for c in self.candles]

    @property
    def closes(self) -> list[float]:
        return [c.close for c in self.candles]

    @property
    def highs(self) -> list[float]:
        return [c.high for c in self.candles]

    @property
    def lows(self) -> list[float]:
        return [c.low for c in self.candles]

    @property
    def opens(self) -> list[float]:
        return [c.open for c in self.candles]

    @property
    def volumes(self) -> list[float]:
        return [c.volume for c in self.candles]

    def tail(self, n: int) -> "Series":
        return Series(self.timeframe, self.candles[-n:] if n > 0 else [], self.symbol)

    def slice_since(self, ts: int) -> "Series":
        return Series(self.timeframe, [c for c in self.candles if c.ts >= ts], self.symbol)

    # -- construction ------------------------------------------------------ #
    def merge(self, others: Sequence[Candle]) -> "Series":
        """Fusionne en dedupliquant sur le timestamp (les nouvelles gagnent)."""
        table = {c.ts: c for c in self.candles}
        for candle in others:
            table[candle.ts] = candle
        self.candles = [table[ts] for ts in sorted(table)]
        return self

    def apply_calibration(self, intercept: float, slope: float) -> "Series":
        return Series(
            self.timeframe,
            [c.shifted(intercept, slope) for c in self.candles],
            self.symbol,
        )

    def is_fresh(self, now_ms_value: int, tolerance_bars: float = 2.0) -> bool:
        """Vrai si la derniere bougie n'a pas plus de `tolerance_bars` de retard."""
        if not self.candles:
            return False
        age = now_ms_value - self.candles[-1].ts
        return age <= tf_ms(self.timeframe) * (tolerance_bars + 1)

    def gaps(self) -> list[tuple[int, int]]:
        """Trous detectes dans la serie -> liste de (ts_avant, ts_apres)."""
        step = tf_ms(self.timeframe)
        out: list[tuple[int, int]] = []
        for prev, cur in zip(self.candles, self.candles[1:]):
            if cur.ts - prev.ts > step * 1.5:
                out.append((prev.ts, cur.ts))
        return out

    def __repr__(self) -> str:  # pragma: no cover
        if not self.candles:
            return f"Series({self.timeframe}, vide)"
        return (
            f"Series({self.timeframe}, {len(self.candles)} bougies, "
            f"{ms_to_iso(self.candles[0].ts)} -> {ms_to_iso(self.candles[-1].ts)})"
        )


def resample(series: Series, target_tf: str) -> Series:
    """Aggrege une serie vers un timeframe superieur (ex: M1 -> M5).

    Les buckets sont alignes sur l'epoch UTC, comme le font Bybit et MT5.
    """
    src_ms = tf_ms(series.timeframe)
    dst_ms = tf_ms(target_tf)
    if dst_ms < src_ms:
        raise ValueError(f"impossible de descendre de {series.timeframe} vers {target_tf}")
    if dst_ms == src_ms:
        return Series(target_tf, list(series.candles), series.symbol)

    buckets: dict[int, list[Candle]] = {}
    for candle in series.candles:
        key = candle.ts - (candle.ts % dst_ms)
        buckets.setdefault(key, []).append(candle)

    out: list[Candle] = []
    for key in sorted(buckets):
        group = buckets[key]
        expected = dst_ms // src_ms
        out.append(
            Candle(
                ts=key,
                open=group[0].open,
                high=max(c.high for c in group),
                low=min(c.low for c in group),
                close=group[-1].close,
                volume=sum(c.volume for c in group),
                turnover=sum(c.turnover for c in group),
                closed=len(group) >= expected and group[-1].closed,
            )
        )
    return Series(target_tf, out, series.symbol)
