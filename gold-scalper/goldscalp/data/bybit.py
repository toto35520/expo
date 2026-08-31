"""Client Bybit v5 (endpoints publics uniquement, aucune cle API requise).

L'or est disponible sur Bybit sous forme tokenisee : XAUT (Tether Gold) et
PAXG (Paxos Gold). Interet décisif pour le scalp : ces marchés cotent 24/7,
y compris quand le forex est ferme. Le prix est ensuite recale sur MT5.

Doc : https://bybit-exchange.github.io/docs/v5/market/kline
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from goldscalp.core.microstructure import BookLevel, OrderBook, Trade
from goldscalp.core.series import Candle, Series, TF_BYBIT, tf_ms
from goldscalp.util import LOG, Http, HttpConfig, HttpError, now_ms

BASE_URLS = [
    "https://api.bybit.com",
    "https://api.bytick.com",  # miroir officiel, utile si le premier est filtre
]

KLINE_MAX = 1000
CANDIDATE_SYMBOLS = ["XAUTUSDT", "PAXGUSDT"]


class BybitError(RuntimeError):
    pass


@dataclass
class Instrument:
    symbol: str
    category: str          # "spot" | "linear"
    tick_size: float = 0.01
    base: str = "XAUT"
    quote: str = "USDT"

    @property
    def has_derivatives(self) -> bool:
        return self.category == "linear"


class BybitClient:
    """Client Bybit avec coupe-circuit.

    Sans coupe-circuit, une coupure réseau coûte plusieurs minutes : chaque
    appel reessaie sur deux domaines, avec un delai exponentiel, et le moteur
    enchaine une dizaine d'appels. Un outil de scalp doit annoncer une panne
    en quelques secondes, pas après le mouvement.
    """

    def __init__(self, http: Optional[Http] = None, base_urls: Optional[Sequence[str]] = None) -> None:
        # Retries courts : en scalp, une donnee qui arrive en retard ne vaut
        # déjà plus rien. Mieux vaut echouer vite et le dire.
        self.http = http or Http(HttpConfig(timeout=8.0, retries=2, backoff=0.5))
        self.base_urls = list(base_urls or BASE_URLS)
        self._active_base: Optional[str] = None
        self._offline_reason: Optional[str] = None

    @property
    def offline(self) -> bool:
        return self._offline_reason is not None

    # -- transport --------------------------------------------------------- #
    def _call(self, path: str, params: dict[str, Any]) -> Any:
        if self._offline_reason is not None:
            raise BybitError(self._offline_reason)

        bases = ([self._active_base] if self._active_base else []) + [
            b for b in self.base_urls if b != self._active_base
        ]
        last_error: Optional[Exception] = None
        for base in bases:
            try:
                payload = self.http.get_json(f"{base}{path}", params)
            except (HttpError, OSError) as exc:
                last_error = exc
                LOG.debug("bybit %s injoignable: %s", base, exc)
                continue
            if not isinstance(payload, dict):
                last_error = BybitError(f"réponse inattendue de {base}")
                continue
            code = payload.get("retCode")
            if code not in (0, "0"):
                raise BybitError(f"Bybit retCode={code}: {payload.get('retMsg')} ({path})")
            self._active_base = base
            return payload.get("result") or {}
        # Tous les domaines sont tombes sur une erreur de transport : le
        # réseau est coupe ou filtre. On ouvre le coupe-circuit pour que les
        # appels suivants echouent instantanément.
        self._offline_reason = (
            f"Aucun endpoint Bybit joignable ({', '.join(self.base_urls)}). "
            f"Derniere erreur : {last_error}. "
            "Verifie ta connexion, ou utilise --demo pour essayer l'outil hors ligne."
        )
        raise BybitError(self._offline_reason)

    # -- instruments ------------------------------------------------------- #
    def resolve_instrument(self, symbol: Optional[str] = None,
                           category: Optional[str] = None) -> Instrument:
        """Trouve un marché or exploitable, en privilegiant le perpetuel.

        Le perpetuel (`linear`) apporte funding + open interest, deux signaux
        que le spot n'a pas. On retombe sur le spot s'il n'existe pas.
        """
        symbols = [symbol] if symbol else CANDIDATE_SYMBOLS
        categories = [category] if category else ["linear", "spot"]

        for candidate in symbols:
            for cat in categories:
                if self.offline:
                    break
                try:
                    result = self._call(
                        "/v5/market/instruments-info", {"category": cat, "symbol": candidate}
                    )
                except BybitError as exc:
                    LOG.debug("instruments-info %s/%s: %s", cat, candidate, exc)
                    continue
                items = result.get("list") or []
                if not items:
                    continue
                item = items[0]
                if str(item.get("status", "Trading")).lower() not in ("trading", "1"):
                    continue
                tick = item.get("priceFilter", {}).get("tickSize")
                return Instrument(
                    symbol=item.get("symbol", candidate),
                    category=cat,
                    tick_size=float(tick) if tick else 0.01,
                    base=item.get("baseCoin") or item.get("baseCoinName") or "XAUT",
                    quote=item.get("quoteCoin") or "USDT",
                )
        if self._offline_reason is not None:
            raise BybitError(self._offline_reason)
        raise BybitError(
            "Aucun marché or trouve sur Bybit parmi "
            f"{symbols} / {categories}. Precise --bybit-symbol et --bybit-category."
        )

    # -- klines ------------------------------------------------------------ #
    def klines(self, instrument: Instrument, timeframe: str, bars: int = 1000) -> Series:
        """Recupere `bars` bougies en paginant vers le passe (max 1000 par appel)."""
        interval = TF_BYBIT[timeframe]
        step = tf_ms(timeframe)
        collected: dict[int, Candle] = {}
        end = now_ms()
        guard = 0

        while len(collected) < bars and guard < 40:
            guard += 1
            want = min(KLINE_MAX, bars - len(collected) + 5)
            result = self._call(
                "/v5/market/kline",
                {
                    "category": instrument.category,
                    "symbol": instrument.symbol,
                    "interval": interval,
                    "limit": want,
                    "end": end,
                },
            )
            rows = result.get("list") or []
            if not rows:
                break
            oldest = end
            for row in rows:
                try:
                    ts = int(row[0])
                    candle = Candle(
                        ts=ts,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        turnover=float(row[6]) if len(row) > 6 else 0.0,
                    )
                except (ValueError, IndexError, TypeError):
                    continue
                collected[ts] = candle
                oldest = min(oldest, ts)
            if oldest >= end:      # plus rien de plus ancien : on arrêté
                break
            end = oldest - 1
            if len(rows) < want // 2:
                break

        ordered = [collected[ts] for ts in sorted(collected)][-bars:]
        # La bougie la plus recente est encore en formation.
        if ordered:
            live = ordered[-1]
            if live.ts + step > now_ms():
                ordered[-1] = Candle(
                    live.ts, live.open, live.high, live.low, live.close,
                    live.volume, live.turnover, closed=False,
                )
        LOG.debug("bybit %s %s: %d bougies", instrument.symbol, timeframe, len(ordered))
        return Series(timeframe, ordered, symbol=instrument.symbol)

    # -- carnet, trades, ticker -------------------------------------------- #
    def orderbook(self, instrument: Instrument, limit: int = 200) -> Optional[OrderBook]:
        capped = min(limit, 200 if instrument.category == "spot" else 500)
        try:
            result = self._call(
                "/v5/market/orderbook",
                {"category": instrument.category, "symbol": instrument.symbol, "limit": capped},
            )
        except BybitError as exc:
            LOG.debug("carnet indisponible: %s", exc)
            return None
        bids = [BookLevel(float(p), float(s)) for p, s in (result.get("b") or [])]
        asks = [BookLevel(float(p), float(s)) for p, s in (result.get("a") or [])]
        if not bids or not asks:
            return None
        bids.sort(key=lambda l: l.price, reverse=True)
        asks.sort(key=lambda l: l.price)
        return OrderBook(ts=int(result.get("ts") or now_ms()), bids=bids, asks=asks)

    def recent_trades(self, instrument: Instrument, limit: int = 1000) -> list[Trade]:
        try:
            result = self._call(
                "/v5/market/recent-trade",
                {"category": instrument.category, "symbol": instrument.symbol, "limit": min(limit, 1000)},
            )
        except BybitError as exc:
            LOG.debug("trades indisponibles: %s", exc)
            return []
        out: list[Trade] = []
        for row in result.get("list") or []:
            try:
                out.append(
                    Trade(
                        ts=int(row.get("time") or 0),
                        price=float(row.get("price")),
                        size=float(row.get("size")),
                        side=str(row.get("side") or "Buy"),
                    )
                )
            except (TypeError, ValueError):
                continue
        out.sort(key=lambda t: t.ts)
        return out

    def ticker(self, instrument: Instrument) -> dict[str, Any]:
        try:
            result = self._call(
                "/v5/market/tickers",
                {"category": instrument.category, "symbol": instrument.symbol},
            )
        except BybitError as exc:
            LOG.debug("ticker indisponible: %s", exc)
            return {}
        items = result.get("list") or []
        return items[0] if items else {}

    # -- dérivés ----------------------------------------------------------- #
    def funding_history(self, instrument: Instrument, limit: int = 60) -> list[float]:
        if not instrument.has_derivatives:
            return []
        try:
            result = self._call(
                "/v5/market/funding/history",
                {"category": "linear", "symbol": instrument.symbol, "limit": min(limit, 200)},
            )
        except BybitError as exc:
            LOG.debug("funding indisponible: %s", exc)
            return []
        rows = result.get("list") or []
        values: list[tuple[int, float]] = []
        for row in rows:
            try:
                values.append((int(row["fundingRateTimestamp"]), float(row["fundingRate"])))
            except (KeyError, TypeError, ValueError):
                continue
        values.sort()
        return [v for _, v in values]

    def open_interest(self, instrument: Instrument, interval: str = "5min", limit: int = 60) -> list[float]:
        if not instrument.has_derivatives:
            return []
        try:
            result = self._call(
                "/v5/market/open-interest",
                {
                    "category": "linear",
                    "symbol": instrument.symbol,
                    "intervalTime": interval,
                    "limit": min(limit, 200),
                },
            )
        except BybitError as exc:
            LOG.debug("open interest indisponible: %s", exc)
            return []
        rows = result.get("list") or []
        values: list[tuple[int, float]] = []
        for row in rows:
            try:
                values.append((int(row["timestamp"]), float(row["openInterest"])))
            except (KeyError, TypeError, ValueError):
                continue
        values.sort()
        return [v for _, v in values]

    def server_time_ms(self) -> int:
        try:
            result = self._call("/v5/market/time", {})
            return int(float(result.get("timeSecond", 0)) * 1000) or now_ms()
        except BybitError:
            return now_ms()
