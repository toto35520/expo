"""Donnees macro qui pilotent l'or : dollar, taux, risque.

L'or n'est pas un actif isole. Sur une seance, l'essentiel de sa direction
s'explique par trois forces :

  DXY  (dollar)      : correlation NEGATIVE forte
  US10Y (taux reels) : correlation NEGATIVE (cout d'opportunite de detention)
  VIX  (risque)      : correlation POSITIVE (valeur refuge)

Sources gratuites sans cle : Yahoo Finance (intraday) puis Stooq (journalier).
Toute source indisponible est simplement ignoree, avec sa contribution retiree
du score - jamais remplacee par une valeur inventee.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Optional

from goldscalp.util import (
    LOG,
    Http,
    HttpConfig,
    cache_read,
    cache_write,
    linreg_slope,
    mean,
    stdev,
)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
STOOQ_CSV = "https://stooq.com/q/d/l/"

# (cle interne, symbole Yahoo, symbole Stooq, correlation attendue avec l'or)
MACRO_SYMBOLS: list[tuple[str, str, str, float]] = [
    ("dxy", "DX-Y.NYB", "dx.f", -1.0),
    ("us10y", "^TNX", "10usy.b", -1.0),
    ("us02y", "^FVX", "2usy.b", -0.6),
    ("vix", "^VIX", "^vix", 0.5),
    ("spx", "^GSPC", "^spx", -0.3),
    ("silver", "SI=F", "xagusd", 0.7),
    ("oil", "CL=F", "cl.f", 0.2),
]


@dataclass
class MacroSeries:
    key: str
    closes: list[float] = field(default_factory=list)
    correlation: float = 0.0     # sens attendu vs l'or
    source: str = ""

    @property
    def last(self) -> Optional[float]:
        return self.closes[-1] if self.closes else None

    def change_pct(self, bars: int = 12) -> Optional[float]:
        if len(self.closes) < bars + 1:
            return None
        base = self.closes[-bars - 1]
        if not base:
            return None
        return (self.closes[-1] - base) / base * 100.0

    def momentum_z(self, window: int = 40) -> Optional[float]:
        """Z-score de la variation recente : mesure d'impulsion normalisee."""
        if len(self.closes) < window + 2:
            return None
        deltas = [
            (b - a) / a * 100.0
            for a, b in zip(self.closes[-window - 1 : -1], self.closes[-window:])
            if a
        ]
        if len(deltas) < 5:
            return None
        sd = stdev(deltas)
        if sd <= 0:
            return None
        return (deltas[-1] - mean(deltas)) / sd

    def trend_slope(self, window: int = 20) -> Optional[float]:
        if len(self.closes) < window:
            return None
        tail = self.closes[-window:]
        base = mean(tail)
        if not base:
            return None
        return linreg_slope(tail) / base * 100.0  # pente en % par barre


class MacroFeed:
    def __init__(self, http: Optional[Http] = None, cache_seconds: float = 300.0) -> None:
        # Source d'enrichissement, pas source critique : elle ne doit jamais
        # retarder un signal de scalp. Si elle traine, on s'en passe.
        self.http = http or Http(HttpConfig(timeout=6.0, retries=2, backoff=0.4))
        self.cache_seconds = cache_seconds
        # Coupe-circuit par fournisseur : si Yahoo est injoignable pour le
        # premier symbole, il le sera pour les six suivants. Insister
        # multiplierait l'attente par sept sans rien apporter.
        self._down: set[str] = set()

    # -- Yahoo ------------------------------------------------------------- #
    def _yahoo(self, symbol: str, rng: str = "5d", interval: str = "15m") -> list[float]:
        cache_key = f"yahoo_{symbol}_{rng}_{interval}.json"
        cached = cache_read(cache_key, self.cache_seconds)
        if cached is not None:
            return [float(v) for v in cached]
        if "yahoo" in self._down:
            raise ValueError("Yahoo Finance injoignable (coupe-circuit ouvert)")
        payload = self.http.get_json(
            YAHOO_CHART.format(symbol=symbol),
            {"range": rng, "interval": interval, "includePrePost": "false"},
        )
        chart = (payload or {}).get("chart") or {}
        results = chart.get("result") or []
        if not results:
            raise ValueError(f"Yahoo n'a rien renvoye pour {symbol}")
        quotes = (results[0].get("indicators") or {}).get("quote") or [{}]
        closes = [c for c in (quotes[0].get("close") or []) if c is not None]
        if not closes:
            raise ValueError(f"serie vide pour {symbol}")
        cache_write(cache_key, closes)
        return [float(c) for c in closes]

    # -- Stooq ------------------------------------------------------------- #
    def _stooq(self, symbol: str) -> list[float]:
        cache_key = f"stooq_{symbol}.json"
        cached = cache_read(cache_key, max(self.cache_seconds, 3600.0))
        if cached is not None:
            return [float(v) for v in cached]
        if "stooq" in self._down:
            raise ValueError("Stooq injoignable (coupe-circuit ouvert)")
        text = self.http.get_text(STOOQ_CSV, {"s": symbol, "i": "d"})
        rows = list(csv.DictReader(io.StringIO(text)))
        closes = []
        for row in rows:
            try:
                closes.append(float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
        if not closes:
            raise ValueError(f"Stooq vide pour {symbol}")
        closes = closes[-260:]
        cache_write(cache_key, closes)
        return closes

    # -- api --------------------------------------------------------------- #
    def fetch(self, intraday: bool = True) -> dict[str, MacroSeries]:
        out: dict[str, MacroSeries] = {}
        for key, yahoo_sym, stooq_sym, corr in MACRO_SYMBOLS:
            closes: list[float] = []
            source = ""
            if intraday:
                try:
                    closes = self._yahoo(yahoo_sym)
                    source = "yahoo/15m"
                except Exception as exc:
                    LOG.debug("yahoo %s indisponible: %s", yahoo_sym, exc)
                    if _is_transport_error(exc):
                        self._down.add("yahoo")
            if not closes:
                try:
                    closes = self._stooq(stooq_sym)
                    source = "stooq/1d"
                except Exception as exc:
                    LOG.debug("stooq %s indisponible: %s", stooq_sym, exc)
                    if _is_transport_error(exc):
                        self._down.add("stooq")
            if closes:
                out[key] = MacroSeries(key=key, closes=closes, correlation=corr, source=source)
        if not out:
            LOG.warning("aucune donnee macro accessible - analyse fondamentale desactivee")
        return out


def _is_transport_error(exc: BaseException) -> bool:
    """Panne reseau (a generaliser) plutot que symbole inconnu (a ignorer).

    Un 404 sur un symbole ne dit rien du fournisseur ; une connexion refusee,
    si.
    """
    from goldscalp.util import HttpError

    if isinstance(exc, HttpError):
        return exc.status in (403, 407, 429) or exc.status >= 500
    return isinstance(exc, (OSError, TimeoutError))
