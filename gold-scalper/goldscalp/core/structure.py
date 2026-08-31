"""Structure de marché : swings, BOS/CHoCH, S/R, pivots, fibs, liquidité.

C'est ce qui donne les niveaux REELS pour poser SL / TP1 / TP2 : un TP
place sur un ATR arbitraire se fait manger, un TP place sous une poche de
liquidité se fait toucher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from goldscalp.core.series import Candle, Series
from goldscalp.util import clamp, mean


@dataclass
class Swing:
    index: int
    ts: int
    price: float
    kind: str  # "high" | "low"


@dataclass
class Level:
    """Niveau horizontal significatif."""

    price: float
    kind: str        # support | résistance | pivot | poc | vah | val | fib | round | pdh | pdl
    strength: float  # 0..1
    touches: int = 1
    label: str = ""

    def distance_pct(self, price: float) -> float:
        return abs(self.price - price) / price * 100.0 if price else 0.0


@dataclass
class StructureView:
    swings: list[Swing]
    trend: str                    # haussier | baissier | range
    last_event: str               # BOS_haussier | BOS_baissier | CHoCH_haussier | CHoCH_baissier | aucun
    event_bars_ago: int
    levels: list[Level] = field(default_factory=list)
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    leg_high: Optional[float] = None
    leg_low: Optional[float] = None
    leg_up: bool = True
    fib: dict[str, float] = field(default_factory=dict)
    liquidity_above: list[float] = field(default_factory=list)
    liquidity_below: list[float] = field(default_factory=list)

    def levels_above(self, price: float, limit: int = 4) -> list[Level]:
        above = [l for l in self.levels if l.price > price]
        above.sort(key=lambda l: l.price)
        return above[:limit]

    def levels_below(self, price: float, limit: int = 4) -> list[Level]:
        below = [l for l in self.levels if l.price < price]
        below.sort(key=lambda l: l.price, reverse=True)
        return below[:limit]

    def nearest_above(self, price: float, min_distance: float = 0.0) -> Optional[Level]:
        candidates = [l for l in self.levels if l.price > price + min_distance]
        return min(candidates, key=lambda l: l.price - price) if candidates else None

    def nearest_below(self, price: float, min_distance: float = 0.0) -> Optional[Level]:
        candidates = [l for l in self.levels if l.price < price - min_distance]
        return min(candidates, key=lambda l: price - l.price) if candidates else None


def find_swings(candles: Sequence[Candle], span: int = 3) -> list[Swing]:
    """Pivots fractals : un plus haut entoure de `span` bougies plus basses."""
    out: list[Swing] = []
    for i in range(span, len(candles) - span):
        window = candles[i - span : i + span + 1]
        centre = candles[i]
        if centre.high >= max(c.high for c in window):
            out.append(Swing(i, centre.ts, centre.high, "high"))
        if centre.low <= min(c.low for c in window):
            out.append(Swing(i, centre.ts, centre.low, "low"))
    out.sort(key=lambda s: s.index)
    return out


def _dedupe_swings(swings: list[Swing], min_gap: int = 2) -> list[Swing]:
    """Retire les swings colles de même nature (garde le plus extrême)."""
    out: list[Swing] = []
    for swing in swings:
        if out and out[-1].kind == swing.kind and swing.index - out[-1].index <= min_gap:
            better = swing.price > out[-1].price if swing.kind == "high" else swing.price < out[-1].price
            if better:
                out[-1] = swing
            continue
        out.append(swing)
    return out


def classify_trend(swings: list[Swing], candles: Sequence[Candle]) -> tuple[str, str, int]:
    """Determine (tendance, dernier événement, index de l'événement).

    - BOS   : cassure dans le sens de la tendance (continuation)
    - CHoCH : cassure contre la tendance (retournement potentiel)

    On regarde à la fois la sequence de swings ET la cassure par le prix
    courant du dernier swing oppose : sans ca on rate le BOS tant que le
    pivot de confirmation n'est pas forme (soit `span` bougies de retard,
    inacceptable en scalp M1).
    """
    if not candles:
        return "range", "aucun", 0

    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        # Un mouvement directionnel SANS repli ne forme aucun pivot fractal :
        # chaque bougie dépasse la précédente, donc aucune n'est un sommet
        # local. Classer ce cas en "range" serait exactement l'inverse de la
        # réalité. On lit alors la pente brute : si le deplacement net couvre
        # l'essentiel de l'amplitude parcourue, le marché est directionnel.
        closes = [c.close for c in candles]
        span = max(closes) - min(closes)
        if span > 0:
            drift = (closes[-1] - closes[0]) / span
            if drift > 0.6:
                return "haussier", "aucun", len(candles) - 1
            if drift < -0.6:
                return "baissier", "aucun", len(candles) - 1
        return "range", "aucun", len(candles) - 1

    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price

    if hh and hl:
        trend = "haussier"
    elif lh and ll:
        trend = "baissier"
    else:
        trend = "range"

    # Cassure par le prix depuis la formation du dernier swing oppose.
    event = "aucun"
    event_index = max(swings, key=lambda s: s.index).index

    ref_high = highs[-1]
    ref_low = lows[-1]
    broke_high_at = next(
        (i for i in range(ref_high.index + 1, len(candles)) if candles[i].close > ref_high.price),
        None,
    )
    broke_low_at = next(
        (i for i in range(ref_low.index + 1, len(candles)) if candles[i].close < ref_low.price),
        None,
    )

    if broke_high_at is not None and (broke_low_at is None or broke_high_at > broke_low_at):
        event = "BOS_haussier" if trend == "haussier" else "CHoCH_haussier"
        event_index = broke_high_at
    elif broke_low_at is not None:
        event = "BOS_baissier" if trend == "baissier" else "CHoCH_baissier"
        event_index = broke_low_at

    return trend, event, event_index


def impulse_leg(swings: list[Swing], candles: Sequence[Candle],
                lookback_swings: int = 12) -> tuple[Optional[float], Optional[float], bool]:
    """Jambe d'impulsion courante -> (haut, bas, haussiere).

    On prend les extrêmes des `lookback_swings` derniers pivots : c'est cette
    amplitude-la qui porte les retracements exploitables en scalp, pas
    l'écart entre deux pivots consecutifs qui peut etre minuscule.
    """
    recent = swings[-lookback_swings:] if swings else []
    highs = [s for s in recent if s.kind == "high"]
    lows = [s for s in recent if s.kind == "low"]
    if not highs or not lows:
        return None, None, True
    top = max(highs, key=lambda s: s.price)
    bottom = min(lows, key=lambda s: s.price)
    if top.price <= bottom.price:
        return None, None, True
    # Si le sommet est plus recent que le creux, l'impulsion est haussiere.
    return top.price, bottom.price, top.index > bottom.index


def cluster_levels(points: Sequence[tuple[float, str, float]], tolerance: float) -> list[Level]:
    """Regroupe des prix proches en niveaux S/R.

    `points` = (prix, nature, recence) ou recence est dans [0, 1], 1 = touche
    la plus recente. La force est ABSOLUE (nombre de touches + recence), pas
    relative au plus gros amas : sinon un niveau touche une seule fois tombe
    à 0.1 et se fait systematiquement doubler par un chiffre rond arbitraire,
    ce qui deplace tous les TP sur des niveaux sans substance.
    """
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p[0])
    clusters: list[list[tuple[float, str, float]]] = [[ordered[0]]]
    for item in ordered[1:]:
        if abs(item[0] - clusters[-1][-1][0]) <= tolerance:
            clusters[-1].append(item)
        else:
            clusters.append([item])

    levels: list[Level] = []
    for cluster in clusters:
        price = mean([c[0] for c in cluster])
        kinds = [c[1] for c in cluster]
        kind = max(set(kinds), key=kinds.count)
        touches = len(cluster)
        touch_score = min(touches, 5) / 5.0
        recency = max(c[2] for c in cluster)
        strength = clamp(0.25 + 0.55 * touch_score + 0.20 * recency, 0.15, 1.0)
        levels.append(
            Level(
                price=price,
                kind=kind,
                strength=round(strength, 3),
                touches=touches,
                label=f"{kind} x{touches}",
            )
        )
    return levels


def daily_pivots(daily: Series) -> list[Level]:
    """Pivots classiques calcules sur la dernière journee CLOTUREE."""
    closed = daily.closed_only
    if len(closed) < 2:
        return []
    prev = closed[-1] if closed[-1].closed else closed[-2]
    pivot = (prev.high + prev.low + prev.close) / 3.0
    width = prev.high - prev.low
    values = {
        "PP": pivot,
        "R1": 2 * pivot - prev.low,
        "S1": 2 * pivot - prev.high,
        "R2": pivot + width,
        "S2": pivot - width,
        "R3": prev.high + 2 * (pivot - prev.low),
        "S3": prev.low - 2 * (prev.high - pivot),
    }
    out = [
        Level(price=value, kind="pivot", strength=0.75 if name == "PP" else 0.55, label=name)
        for name, value in values.items()
    ]
    out.append(Level(price=prev.high, kind="pdh", strength=0.9, label="PDH"))
    out.append(Level(price=prev.low, kind="pdl", strength=0.9, label="PDL"))
    return out


def round_numbers(price: float, step: float = 5.0, count: int = 6) -> list[Level]:
    """Niveaux psychologiques : l'or respecte fortement les x0 et x00."""
    base = round(price / step) * step
    out: list[Level] = []
    for k in range(-count, count + 1):
        value = base + k * step
        if value <= 0:
            continue
        if abs(value % 100) < 1e-6:
            strength = 0.85
        elif abs(value % 50) < 1e-6:
            strength = 0.65
        elif abs(value % 10) < 1e-6:
            strength = 0.45
        else:
            strength = 0.25
        out.append(Level(price=value, kind="round", strength=strength, label=f"{value:.0f}"))
    return out


def fib_levels(high: float, low: float, uptrend: bool) -> dict[str, float]:
    """Retracements + extensions de l'impulsion en cours."""
    span = high - low
    if span <= 0:
        return {}
    ratios = {
        "0.236": 0.236, "0.382": 0.382, "0.5": 0.5, "0.618": 0.618,
        "0.786": 0.786, "1.272": -0.272, "1.618": -0.618,
    }
    out: dict[str, float] = {}
    for name, ratio in ratios.items():
        out[name] = high - span * ratio if uptrend else low + span * ratio
    return out


def liquidity_pools(candles: Sequence[Candle], swings: list[Swing], price: float,
                    tolerance: float) -> tuple[list[float], list[float]]:
    """Poches de liquidité = amas d'egal-highs / equal-lows non balayes.

    Ce sont les cibles naturelles du prix : c'est la que sont les stops.
    """
    highs = [s.price for s in swings if s.kind == "high" and s.price > price]
    lows = [s.price for s in swings if s.kind == "low" and s.price < price]

    def cluster(values: list[float]) -> list[float]:
        if not values:
            return []
        ordered = sorted(values)
        groups: list[list[float]] = [[ordered[0]]]
        for value in ordered[1:]:
            if abs(value - groups[-1][-1]) <= tolerance:
                groups[-1].append(value)
            else:
                groups.append([value])
        return [mean(g) for g in groups if len(g) >= 2]

    above = sorted(cluster(highs))[:3]
    below = sorted(cluster(lows), reverse=True)[:3]
    return above, below


def build_structure(series: Series, daily: Optional[Series] = None, atr_value: float = 1.0,
                    swing_span: int = 3, level_lookback: int = 300) -> StructureView:
    """Assemble la vue structurelle complète d'un timeframe."""
    candles = series.candles[-level_lookback:]
    if len(candles) < swing_span * 2 + 4:
        return StructureView([], "range", "aucun", 0)

    swings = _dedupe_swings(find_swings(candles, swing_span))
    trend, event, event_index = classify_trend(swings, candles)
    event_bars_ago = max(0, len(candles) - 1 - event_index)

    price = candles[-1].close
    # Tolérance resserrée : à 0.45 ATR, des dizaines de swings distincts
    # fusionnent en un seul pseudo-niveau qui ne veut plus rien dire.
    tolerance = max(atr_value * 0.22, price * 0.00025)

    newest = max((s.index for s in swings), default=1) or 1
    oldest = min((s.index for s in swings), default=0)
    span = max(newest - oldest, 1)
    raw: list[tuple[float, str, float]] = [
        (
            swing.price,
            "resistance" if swing.kind == "high" else "support",
            clamp((swing.index - oldest) / span, 0.0, 1.0),
        )
        for swing in swings
    ]
    levels = cluster_levels(raw, tolerance)

    if daily is not None:
        levels.extend(daily_pivots(daily))
    levels.extend(round_numbers(price, step=5.0, count=5))

    # Deduplication finale : deux niveaux a moins d'une tolérance fusionnent.
    levels.sort(key=lambda l: l.price)
    merged: list[Level] = []
    for level in levels:
        if merged and abs(level.price - merged[-1].price) <= tolerance * 0.6:
            previous = merged[-1]
            keep = previous if previous.strength >= level.strength else level
            # Une confluence de natures différentes (swing + pivot + rond)
            # renforce le niveau, sans jamais dépasser 1.0.
            keep.strength = round(min(1.0, max(previous.strength, level.strength) + 0.10), 3)
            keep.touches = min(previous.touches + level.touches, 9)
            keep.label = f"{previous.label}+{level.label}".strip("+")[:26]
            merged[-1] = keep
        else:
            merged.append(level)

    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    swing_high = highs[-1].price if highs else None
    swing_low = lows[-1].price if lows else None
    range_high = max(c.high for c in candles[-60:])
    range_low = min(c.low for c in candles[-60:])

    leg_high, leg_low, leg_up = impulse_leg(swings, candles)
    fib: dict[str, float] = fib_levels(leg_high, leg_low, leg_up) if (leg_high and leg_low) else {}

    above, below = liquidity_pools(candles, swings, price, tolerance)

    return StructureView(
        swings=swings,
        trend=trend,
        last_event=event,
        event_bars_ago=event_bars_ago,
        levels=merged,
        swing_high=swing_high,
        swing_low=swing_low,
        range_high=range_high,
        range_low=range_low,
        leg_high=leg_high,
        leg_low=leg_low,
        leg_up=leg_up,
        fib=fib,
        liquidity_above=above,
        liquidity_below=below,
    )
