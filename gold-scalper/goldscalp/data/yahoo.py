"""Source de prix de repli : Yahoo Finance (public, sans clé).

Pourquoi cette source existe
----------------------------
Bybit filtre par pays au niveau de son CDN : depuis une fonction hébergée aux
États-Unis, l'API renvoie un HTTP 403 « CloudFront is configured to block
access from your country ». Dépendre d'une seule source dont l'accès est
conditionné par l'adresse IP du serveur est une fragilité, pas un détail de
configuration.

Yahoo n'applique pas ce filtrage et sert des bougies intraday jusqu'à la
minute. Mieux : `XAUUSD=X` cote l'or SPOT, c'est-à-dire exactement ce que
cote ton MT5. L'écart à calibrer se réduit alors au markup du broker (moins
d'un dollar), au lieu de la prime du XAUT qui dérive en permanence.

Ce qu'on y perd
---------------
  - Le volume : les paires de change Yahoo ne le publient pas. Les
    indicateurs de participation se dégradent proprement (voir `has_volume`).
  - Le 24/7 : l'or spot suit les horaires du forex, fermé le week-end.
  - La microstructure : ni carnet, ni flux, ni funding. Ces signaux sont
    simplement absents du score plutôt que remplacés par une valeur inventée.

Bybit reste donc la source préférée quand elle est joignable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from goldscalp.core.series import Candle, Series
from goldscalp.util import LOG, Http, HttpConfig, HttpError, now_ms

HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]

# (symbole, description, publie du volume)
CANDIDATES: list[tuple[str, str, bool]] = [
    ("XAUUSD=X", "or spot (identique au sous-jacent de XAUUSD chez ton broker)", False),
    ("GC=F", "future or COMEX (publie du volume)", True),
    ("XAUT-USD", "Tether Gold", True),
]

# Yahoo impose une profondeur maximale par granularité.
#   1m  -> 7 jours     5m/15m -> 60 jours     1d -> plusieurs années
TF_QUERY: dict[str, tuple[str, str]] = {
    "M1": ("1m", "5d"),
    "M5": ("5m", "1mo"),
    "M15": ("15m", "1mo"),
    "M30": ("30m", "2mo"),
    "H1": ("60m", "3mo"),
    "D1": ("1d", "1y"),
}

# Yahoo refuse les clients sans en-tête de navigateur sur certains chemins.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class YahooError(RuntimeError):
    pass


@dataclass
class YahooInstrument:
    symbol: str
    description: str
    has_volume: bool


class YahooGoldClient:
    """Client minimal de l'API chart v8, avec coupe-circuit."""

    def __init__(self, http: Optional[Http] = None, hosts: Optional[Sequence[str]] = None) -> None:
        self.http = http or Http(HttpConfig(timeout=10.0, retries=2, backoff=0.5,
                                            user_agent=BROWSER_UA))
        self.hosts = list(hosts or HOSTS)
        self._active_host: Optional[str] = None
        self._offline_reason: Optional[str] = None

    @property
    def offline(self) -> bool:
        return self._offline_reason is not None

    # -- transport --------------------------------------------------------- #
    def _chart(self, symbol: str, interval: str, rng: str) -> dict:
        if self._offline_reason is not None:
            raise YahooError(self._offline_reason)

        hosts = ([self._active_host] if self._active_host else []) + [
            h for h in self.hosts if h != self._active_host
        ]
        last: Optional[Exception] = None
        for host in hosts:
            try:
                payload = self.http.get_json(
                    f"{host}/v8/finance/chart/{symbol}",
                    {"range": rng, "interval": interval, "includePrePost": "false"},
                    headers={"Accept": "application/json"},
                )
            except (HttpError, OSError) as exc:
                last = exc
                LOG.debug("yahoo %s injoignable : %s", host, exc)
                continue

            chart = (payload or {}).get("chart") or {}
            if chart.get("error"):
                raise YahooError(f"Yahoo a refusé {symbol} : {chart['error']}")
            results = chart.get("result") or []
            if not results:
                raise YahooError(f"Yahoo n'a renvoyé aucune série pour {symbol}")
            self._active_host = host
            return results[0]

        self._offline_reason = (
            f"Aucun hôte Yahoo joignable ({', '.join(self.hosts)}). Dernière erreur : {last}"
        )
        raise YahooError(self._offline_reason)

    # -- instruments ------------------------------------------------------- #
    def resolve_instrument(self, symbol: Optional[str] = None) -> YahooInstrument:
        candidates = (
            [(symbol, "symbole imposé par l'appelant", True)] if symbol else CANDIDATES
        )
        errors: list[str] = []
        for candidate, description, has_volume in candidates:
            if self.offline:
                break
            try:
                result = self._chart(candidate, "15m", "5d")
            except YahooError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            timestamps = result.get("timestamp") or []
            if len(timestamps) < 20:
                errors.append(f"{candidate}: série trop courte ({len(timestamps)} points)")
                continue
            return YahooInstrument(candidate, description, has_volume)

        if self._offline_reason:
            raise YahooError(self._offline_reason)
        raise YahooError("Aucun symbole or exploitable chez Yahoo. " + " | ".join(errors))

    # -- bougies ----------------------------------------------------------- #
    def klines(self, instrument: YahooInstrument, timeframe: str, bars: int = 1000) -> Series:
        if timeframe not in TF_QUERY:
            raise YahooError(f"timeframe {timeframe} non servi par Yahoo")
        interval, rng = TF_QUERY[timeframe]
        result = self._chart(instrument.symbol, interval, rng)

        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quotes.get("open") or []
        highs = quotes.get("high") or []
        lows = quotes.get("low") or []
        closes = quotes.get("close") or []
        volumes = quotes.get("volume") or []

        candles: list[Candle] = []
        for i, stamp in enumerate(timestamps):
            try:
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            except IndexError:
                break
            # Yahoo laisse des trous (nuls) sur les créneaux sans transaction.
            if None in (stamp, o, h, l, c):
                continue
            volume = 0.0
            if i < len(volumes) and volumes[i] is not None:
                volume = float(volumes[i])
            candles.append(
                Candle(
                    ts=int(stamp) * 1000,
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=volume,
                )
            )

        candles.sort(key=lambda candle: candle.ts)
        candles = candles[-bars:]
        if candles:
            live = candles[-1]
            candles[-1] = Candle(live.ts, live.open, live.high, live.low, live.close,
                                 live.volume, live.turnover, closed=False)
        LOG.debug("yahoo %s %s : %d bougies", instrument.symbol, timeframe, len(candles))
        return Series(timeframe, candles, symbol=instrument.symbol)

    def last_price(self, instrument: YahooInstrument) -> Optional[float]:
        try:
            result = self._chart(instrument.symbol, "5m", "1d")
        except YahooError:
            return None
        price = (result.get("meta") or {}).get("regularMarketPrice")
        return float(price) if price else None


def has_usable_volume(series: Series) -> bool:
    """Vrai si la série porte un volume exploitable.

    Sans volume, VWAP, OBV, z-score et profil se rabattent sur une pondération
    temporelle : utilisable, mais il faut le dire plutôt que de laisser croire
    à une analyse de participation réelle.
    """
    if not series:
        return False
    recent = series.candles[-200:]
    return sum(1 for candle in recent if candle.volume > 0) > len(recent) * 0.5
