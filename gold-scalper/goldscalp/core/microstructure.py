"""Microstructure : carnet d'ordres, flux agressif (CVD), funding, open interest.

Ces signaux ne viennent PAS des bougies. En scalp M1 ils font la différence
entre une cassure qui tient et une meche qui pieges les retardataires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from goldscalp.util import clamp, mean, safe_div, stdev


@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    ts: int
    bids: list[BookLevel] = field(default_factory=list)   # tries prix decroissant
    asks: list[BookLevel] = field(default_factory=list)   # tries prix croissant

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def depth(self, side: str, within_pct: float = 0.05) -> float:
        """Volume cumule d'un cote, dans une bande de `within_pct` % autour du mid."""
        mid = self.mid
        if mid is None:
            return 0.0
        band = mid * within_pct / 100.0
        levels = self.bids if side == "bid" else self.asks
        return sum(l.size for l in levels if abs(l.price - mid) <= band)

    def imbalance(self, within_pct: float = 0.05) -> float:
        """Déséquilibre acheteur/vendeur dans [-1, +1]. Positif = acheteurs devant."""
        bid = self.depth("bid", within_pct)
        ask = self.depth("ask", within_pct)
        total = bid + ask
        return safe_div(bid - ask, total, 0.0)

    def wall(self, side: str, factor: float = 3.0) -> Optional[float]:
        """Prix d'un mur de liquidité (niveau >= `factor` x la taille mediane)."""
        levels = self.bids if side == "bid" else self.asks
        if len(levels) < 5:
            return None
        sizes = [l.size for l in levels]
        typical = mean(sizes)
        if typical <= 0:
            return None
        for level in levels:
            if level.size >= typical * factor:
                return level.price
        return None


@dataclass
class Trade:
    ts: int
    price: float
    size: float
    side: str  # "Buy" (agresseur acheteur) | "Sell"


@dataclass
class FlowStats:
    """Statistiques du flux agressif recent."""

    cvd: float = 0.0              # delta cumule (achats - ventes)
    cvd_slope: float = 0.0        # pente du CVD sur la fenêtre
    buy_ratio: float = 0.5        # part des volumes à l'achat
    trade_count: int = 0
    volume: float = 0.0
    avg_trade_size: float = 0.0
    large_trade_bias: float = 0.0  # biais des gros trades (>p80), dans [-1, +1]
    absorption: float = 0.0        # flux fort mais prix immobile -> absorption

    @property
    def score(self) -> float:
        """Score directionnel du flux dans [-1, +1]."""
        raw = (self.buy_ratio - 0.5) * 2.0
        return round(clamp(raw * 0.55 + clamp(self.cvd_slope, -1, 1) * 0.25 + self.large_trade_bias * 0.20, -1, 1), 3)


def analyse_flow(trades: Sequence[Trade], price_now: Optional[float] = None,
                 price_then: Optional[float] = None) -> FlowStats:
    if not trades:
        return FlowStats()

    ordered = sorted(trades, key=lambda t: t.ts)
    buy_volume = sum(t.size for t in ordered if t.side == "Buy")
    sell_volume = sum(t.size for t in ordered if t.side == "Sell")
    total = buy_volume + sell_volume

    running = 0.0
    curve: list[float] = []
    for trade in ordered:
        running += trade.size if trade.side == "Buy" else -trade.size
        curve.append(running)

    # Pente normalisée par le volume total : comparable d'une session a l'autre.
    slope = 0.0
    if len(curve) >= 4 and total > 0:
        slope = (curve[-1] - curve[len(curve) // 2]) / (total / 2.0)

    sizes = sorted(t.size for t in ordered)
    p80 = sizes[int(len(sizes) * 0.8)] if sizes else 0.0
    big = [t for t in ordered if t.size >= p80 and p80 > 0]
    big_buy = sum(t.size for t in big if t.side == "Buy")
    big_sell = sum(t.size for t in big if t.side == "Sell")
    large_bias = safe_div(big_buy - big_sell, big_buy + big_sell, 0.0)

    # Absorption : beaucoup de volume, peu de deplacement de prix.
    absorption = 0.0
    if price_now is not None and price_then is not None and price_then:
        move_pct = abs(price_now - price_then) / price_then * 100.0
        if total > 0 and move_pct < 0.02:
            absorption = clamp(1.0 - move_pct / 0.02, 0.0, 1.0)

    return FlowStats(
        cvd=round(buy_volume - sell_volume, 4),
        cvd_slope=round(clamp(slope, -1.5, 1.5), 4),
        buy_ratio=round(safe_div(buy_volume, total, 0.5), 4),
        trade_count=len(ordered),
        volume=round(total, 4),
        avg_trade_size=round(safe_div(total, len(ordered), 0.0), 6),
        large_trade_bias=round(large_bias, 4),
        absorption=round(absorption, 3),
    )


@dataclass
class DerivativesStats:
    """Signaux issus des perpetuels : funding et open interest."""

    funding_rate: Optional[float] = None       # taux courant (fraction, ex 0.0001)
    funding_avg: Optional[float] = None        # moyenne recente
    funding_zscore: Optional[float] = None
    open_interest: Optional[float] = None
    oi_change_pct: Optional[float] = None      # variation sur la fenêtre
    price_change_pct: Optional[float] = None

    @property
    def positioning(self) -> str:
        """Lecture croisee OI / prix -> qui pousse le marché."""
        if self.oi_change_pct is None or self.price_change_pct is None:
            return "inconnu"
        oi_up = self.oi_change_pct > 0.4
        oi_down = self.oi_change_pct < -0.4
        px_up = self.price_change_pct > 0.05
        px_down = self.price_change_pct < -0.05
        if oi_up and px_up:
            return "nouveaux_longs"      # tendance haussiere saine
        if oi_up and px_down:
            return "nouveaux_shorts"     # tendance baissiere saine
        if oi_down and px_up:
            return "short_squeeze"       # rally de couverture, fragile
        if oi_down and px_down:
            return "long_liquidation"    # baisse de capitulation, fragile
        return "neutre"

    @property
    def score(self) -> float:
        """Biais contrarien du funding + confirmation OI, dans [-1, +1]."""
        total = 0.0
        weight = 0.0
        if self.funding_zscore is not None:
            # Funding extrême = foule d'un cote = carburant pour le sens inverse.
            total += clamp(-self.funding_zscore / 2.5, -1.0, 1.0) * 0.5
            weight += 0.5
        mapping = {
            "nouveaux_longs": 0.6,
            "nouveaux_shorts": -0.6,
            "short_squeeze": -0.25,
            "long_liquidation": 0.25,
            "neutre": 0.0,
            "inconnu": 0.0,
        }
        if self.positioning != "inconnu":
            total += mapping[self.positioning] * 0.5
            weight += 0.5
        return round(clamp(safe_div(total, weight, 0.0), -1.0, 1.0), 3)


def analyse_derivatives(funding_history: Sequence[float], open_interest: Sequence[float],
                        prices: Sequence[float]) -> DerivativesStats:
    stats = DerivativesStats()
    if funding_history:
        stats.funding_rate = funding_history[-1]
        stats.funding_avg = mean(list(funding_history))
        sd = stdev(list(funding_history))
        if sd > 0:
            stats.funding_zscore = round((funding_history[-1] - stats.funding_avg) / sd, 3)
    if len(open_interest) >= 2 and open_interest[0]:
        stats.open_interest = open_interest[-1]
        stats.oi_change_pct = round((open_interest[-1] - open_interest[0]) / open_interest[0] * 100.0, 4)
    if len(prices) >= 2 and prices[0]:
        stats.price_change_pct = round((prices[-1] - prices[0]) / prices[0] * 100.0, 4)
    return stats


@dataclass
class MicroView:
    """Vue microstructure consolidee, prete pour le moteur de score."""

    book: Optional[OrderBook] = None
    flow: FlowStats = field(default_factory=FlowStats)
    derivatives: DerivativesStats = field(default_factory=DerivativesStats)
    imbalance: float = 0.0
    spread_bybit: Optional[float] = None
    bid_wall: Optional[float] = None
    ask_wall: Optional[float] = None

    @property
    def score(self) -> float:
        """Score microstructure dans [-1, +1] : 60 % flux, 25 % carnet, 15 % dérivés."""
        return round(
            clamp(
                self.flow.score * 0.60 + clamp(self.imbalance, -1, 1) * 0.25 + self.derivatives.score * 0.15,
                -1.0,
                1.0,
            ),
            3,
        )

    def summary(self) -> list[str]:
        out: list[str] = []
        if self.book is not None:
            out.append(f"carnet {self.imbalance:+.2f} ({'acheteurs' if self.imbalance > 0 else 'vendeurs'} devant)")
        if self.flow.trade_count:
            out.append(f"flux {self.flow.score:+.2f} (achats {self.flow.buy_ratio * 100:.0f}%)")
        if self.flow.absorption > 0.4:
            out.append(f"absorption {self.flow.absorption:.2f} - gros volume sans mouvement")
        if self.derivatives.positioning != "inconnu":
            out.append(f"positionnement {self.derivatives.positioning}")
        if self.derivatives.funding_zscore is not None and abs(self.derivatives.funding_zscore) > 1.5:
            out.append(f"funding extrême (z {self.derivatives.funding_zscore:+.1f})")
        return out


def build_micro(book: Optional[OrderBook], trades: Sequence[Trade],
                derivatives: DerivativesStats,
                price_now: Optional[float] = None,
                price_then: Optional[float] = None) -> MicroView:
    flow = analyse_flow(trades, price_now, price_then)
    view = MicroView(book=book, flow=flow, derivatives=derivatives)
    if book is not None:
        view.imbalance = round(book.imbalance(), 4)
        view.spread_bybit = book.spread
        view.bid_wall = book.wall("bid")
        view.ask_wall = book.wall("ask")
    return view
