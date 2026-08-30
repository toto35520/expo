"""Pont MetaTrader 5 (optionnel).

Si le paquet `MetaTrader5` est installe et qu'un terminal tourne, on peut :
  - lire les bougies XAUUSD directement chez TON broker (verite terrain) ;
  - relever bid/ask pour ancrer automatiquement la calibration ;
  - lire la taille de contrat et le solde pour dimensionner les lots.

Sans MT5, tout continue de fonctionner : on trade les prix Bybit recalibres.
Le paquet n'est officiellement disponible que sous Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from goldscalp.core.series import Candle, Series
from goldscalp.util import LOG

TF_MAP_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M3": "TIMEFRAME_M3",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


@dataclass
class SymbolSpec:
    """Specification du symbole telle que definie par le broker."""

    name: str = "XAUUSD"
    digits: int = 2
    point: float = 0.01
    contract_size: float = 100.0      # 1 lot XAUUSD = 100 onces chez la majorite
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    spread_points: int = 30
    tick_value: float = 1.0
    currency_profit: str = "USD"

    @property
    def spread_price(self) -> float:
        return self.spread_points * self.point

    def value_per_price_unit(self, lots: float) -> float:
        """Combien vaut 1.00 $ de mouvement du prix, pour `lots` lots."""
        return self.contract_size * lots

    def normalize_lots(self, lots: float) -> float:
        if self.volume_step <= 0:
            return round(lots, 2)
        steps = int(lots / self.volume_step)
        value = steps * self.volume_step
        value = max(self.volume_min, min(self.volume_max, value))
        return round(value, 8)


@dataclass
class AccountInfo:
    balance: float = 0.0
    equity: float = 0.0
    currency: str = "USD"
    leverage: int = 100


class Mt5Bridge:
    """Enveloppe tolerante autour du paquet MetaTrader5."""

    def __init__(self, symbol: str = "XAUUSD", path: Optional[str] = None) -> None:
        self.symbol = symbol
        self.path = path
        self._mt5: Any = None
        self._ready = False

    # -- cycle de vie ------------------------------------------------------ #
    @property
    def available(self) -> bool:
        try:
            import MetaTrader5  # noqa: F401
        except ImportError:
            return False
        return True

    def connect(self) -> bool:
        if self._ready:
            return True
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            LOG.debug("paquet MetaTrader5 absent (normal hors Windows)")
            return False
        ok = mt5.initialize(self.path) if self.path else mt5.initialize()
        if not ok:
            LOG.warning("connexion MT5 impossible: %s", mt5.last_error())
            return False
        if not mt5.symbol_select(self.symbol, True):
            LOG.warning("symbole %s indisponible chez ce broker", self.symbol)
            mt5.shutdown()
            return False
        self._mt5 = mt5
        self._ready = True
        LOG.info("MT5 connecte sur %s", self.symbol)
        return True

    def close(self) -> None:
        if self._ready and self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:  # pragma: no cover
                pass
        self._ready = False

    def __enter__(self) -> "Mt5Bridge":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- lectures ---------------------------------------------------------- #
    def tick(self) -> Optional[tuple[float, float]]:
        """(bid, ask) courants, ou None."""
        if not self._ready:
            return None
        info = self._mt5.symbol_info_tick(self.symbol)
        if info is None or not info.bid or not info.ask:
            return None
        return float(info.bid), float(info.ask)

    def spec(self) -> SymbolSpec:
        if not self._ready:
            return SymbolSpec(name=self.symbol)
        info = self._mt5.symbol_info(self.symbol)
        if info is None:
            return SymbolSpec(name=self.symbol)
        return SymbolSpec(
            name=self.symbol,
            digits=int(getattr(info, "digits", 2)),
            point=float(getattr(info, "point", 0.01)),
            contract_size=float(getattr(info, "trade_contract_size", 100.0)),
            volume_min=float(getattr(info, "volume_min", 0.01)),
            volume_max=float(getattr(info, "volume_max", 100.0)),
            volume_step=float(getattr(info, "volume_step", 0.01)),
            spread_points=int(getattr(info, "spread", 30)),
            tick_value=float(getattr(info, "trade_tick_value", 1.0)),
            currency_profit=str(getattr(info, "currency_profit", "USD")),
        )

    def account(self) -> Optional[AccountInfo]:
        if not self._ready:
            return None
        info = self._mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            balance=float(info.balance),
            equity=float(info.equity),
            currency=str(info.currency),
            leverage=int(getattr(info, "leverage", 100)),
        )

    def candles(self, timeframe: str, bars: int = 1000) -> Optional[Series]:
        """Bougies directement issues du broker : reference absolue."""
        if not self._ready:
            return None
        attr = TF_MAP_NAMES.get(timeframe)
        if attr is None or not hasattr(self._mt5, attr):
            return None
        rates = self._mt5.copy_rates_from_pos(self.symbol, getattr(self._mt5, attr), 0, bars)
        if rates is None or len(rates) == 0:
            LOG.debug("aucune bougie MT5 %s", timeframe)
            return None
        out: list[Candle] = []
        for row in rates:
            try:
                volume = float(row["real_volume"]) or float(row["tick_volume"])
            except (KeyError, ValueError, IndexError):
                volume = 0.0
            out.append(
                Candle(
                    ts=int(row["time"]) * 1000,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=volume,
                )
            )
        out.sort(key=lambda c: c.ts)
        if out:
            last = out[-1]
            out[-1] = Candle(last.ts, last.open, last.high, last.low, last.close,
                             last.volume, last.turnover, closed=False)
        return Series(timeframe, out, symbol=self.symbol)
