"""Gestion du risque : taille de position et coupe-circuit journalier."""
import math
from datetime import date, datetime, timezone
from typing import Optional


def position_volume(balance: float, risk_pct: float, sl_distance: float,
                    quote_to_account: float, min_volume: int, step_volume: int,
                    max_volume: int) -> int:
    """Volume au format de l'API cTrader (centièmes d'unité) pour risquer `risk_pct` % du solde.

    Perte au stop = unités x sl_distance x quote_to_account.
    Le volume est arrondi vers le BAS au pas du courtier. Si le minimum du courtier
    ferait dépasser le risque voulu, on renvoie 0 (pas de trade) plutôt que de sur-risquer.
    """
    if balance <= 0 or sl_distance <= 0 or quote_to_account <= 0:
        return 0
    risk_amount = balance * risk_pct / 100
    units = risk_amount / (sl_distance * quote_to_account)
    volume = math.floor(units * 100 / step_volume) * step_volume
    if volume < min_volume:
        return 0
    return min(volume, max_volume)


class DailyLossGuard:
    """Bloque les nouvelles entrées quand la perte du jour dépasse `max_loss_pct` % du solde d'ouverture."""

    def __init__(self, max_loss_pct: float):
        self.max_loss_pct = max_loss_pct
        self._day: Optional[date] = None
        self._start_balance = 0.0

    def allows_trading(self, balance: float, now: Optional[datetime] = None) -> bool:
        today = (now or datetime.now(timezone.utc)).date()
        if self._day != today:
            self._day, self._start_balance = today, balance
        loss_pct = (self._start_balance - balance) / self._start_balance * 100
        return loss_pct < self.max_loss_pct
