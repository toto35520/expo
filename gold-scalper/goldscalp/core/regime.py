"""Regime de marche et sessions.

Le meme signal technique n'a pas la meme valeur selon le contexte : un
croisement d'EMA vaut de l'or en expansion de volatilite et coute cher en
range compresse. Le regime module donc les poids du moteur de score et le
choix du style (suivi de tendance vs retour a la moyenne).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from goldscalp.core.indicators import IndicatorSet, last_valid, valid_tail
from goldscalp.util import clamp, percentile, rank_pct

# Sessions en heures UTC. L'or vit surtout sur Londres et New York.
SESSIONS = [
    ("Asie", 0, 7, 0.55, "range, faible amplitude - privilegier le fade des extremes"),
    ("Londres", 7, 12, 1.15, "expansion, premieres vraies impulsions"),
    ("Londres+NY", 12, 16, 1.55, "meilleure fenetre de scalp - volume et suivi maximaux"),
    ("New York", 16, 20, 1.00, "tendances qui s'essoufflent, attention aux retournements"),
    ("Cloture", 20, 24, 0.60, "liquidite faible, spreads larges - eviter"),
]


@dataclass
class SessionInfo:
    name: str
    volatility_factor: float
    advice: str
    hour_utc: int
    minutes_to_next: int

    @property
    def is_prime(self) -> bool:
        return self.volatility_factor >= 1.10

    @property
    def is_poor(self) -> bool:
        return self.volatility_factor < 0.65


def current_session(ts_ms: int) -> SessionInfo:
    hour = int((ts_ms // 3_600_000) % 24)
    minute = int((ts_ms // 60_000) % 60)
    for name, start, end, factor, advice in SESSIONS:
        if start <= hour < end:
            return SessionInfo(name, factor, advice, hour, (end - hour) * 60 - minute)
    name, start, end, factor, advice = SESSIONS[-1]
    return SessionInfo(name, factor, advice, hour, (24 - hour) * 60 - minute)


@dataclass
class Regime:
    label: str            # tendance_forte | tendance | range | compression | expansion | chaos
    direction: int        # +1 haussier, -1 baissier, 0 neutre
    strength: float       # 0..1
    adx: Optional[float]
    efficiency: Optional[float]
    atr_percentile: float
    bb_percentile: float
    squeeze: bool
    volatility_state: str  # basse | normale | haute | extreme
    description: str = ""

    @property
    def favors_trend(self) -> bool:
        return self.label in ("tendance_forte", "tendance", "expansion")

    @property
    def favors_fade(self) -> bool:
        return self.label in ("range", "compression")

    @property
    def is_tradable(self) -> bool:
        """Le chaos et la compression extreme ne sont pas scalpables."""
        return self.label != "chaos" and self.volatility_state != "basse"

    @property
    def stop_multiplier(self) -> float:
        """Elargit le stop quand le marche est nerveux, le resserre en range."""
        base = {"basse": 0.85, "normale": 1.0, "haute": 1.25, "extreme": 1.55}[self.volatility_state]
        if self.label == "chaos":
            base *= 1.2
        elif self.label == "compression":
            base *= 0.9
        return round(base, 3)

    @property
    def target_multiplier(self) -> float:
        """En tendance on laisse courir, en range on prend vite."""
        if self.label == "tendance_forte":
            return 1.35
        if self.label in ("tendance", "expansion"):
            return 1.15
        if self.label == "range":
            return 0.80
        if self.label == "compression":
            return 0.70
        return 1.0


def detect_regime(indicators: IndicatorSet, history: int = 200) -> Regime:
    adx_value = last_valid(indicators.adx14)
    er_value = last_valid(indicators.er)
    plus_di = last_valid(indicators.plus_di)
    minus_di = last_valid(indicators.minus_di)

    atr_history = valid_tail(indicators.atr14, history)
    atr_now = last_valid(indicators.atr14) or 0.0
    atr_pct = rank_pct(atr_history, atr_now) if len(atr_history) > 20 else 50.0

    bb_history = valid_tail(indicators.bb_width, history)
    bb_now = last_valid(indicators.bb_width) or 0.0
    bb_pct = rank_pct(bb_history, bb_now) if len(bb_history) > 20 else 50.0

    squeeze_on = bool(indicators.squeeze_on and indicators.squeeze_on[-1])

    if atr_pct < 20:
        vol_state = "basse"
    elif atr_pct < 70:
        vol_state = "normale"
    elif atr_pct < 90:
        vol_state = "haute"
    else:
        vol_state = "extreme"

    direction = 0
    if plus_di is not None and minus_di is not None:
        if plus_di > minus_di * 1.05:
            direction = 1
        elif minus_di > plus_di * 1.05:
            direction = -1
    if direction == 0:
        st_dir = indicators.st_dir[-1] if indicators.st_dir else 0
        direction = st_dir

    adx_v = adx_value or 0.0
    er_v = er_value or 0.0

    # Classement du regime, du plus structurant au plus degrade.
    if squeeze_on and bb_pct < 30:
        label = "compression"
        strength = clamp(1.0 - bb_pct / 30.0, 0.2, 1.0)
        desc = "volatilite comprimee - une expansion se prepare, ne pas anticiper le sens"
    elif adx_v >= 32 and er_v >= 0.35:
        label = "tendance_forte"
        strength = clamp(adx_v / 55.0 * 0.6 + er_v * 0.4, 0.3, 1.0)
        desc = "tendance directionnelle nette - suivre, ne jamais contrer"
    elif adx_v >= 22 and er_v >= 0.20:
        label = "tendance"
        strength = clamp(adx_v / 45.0 * 0.6 + er_v * 0.4, 0.2, 1.0)
        desc = "tendance exploitable - entrer sur repli, pas en cassure"
    elif bb_pct > 80 and adx_v < 22:
        label = "expansion"
        strength = clamp(bb_pct / 100.0, 0.3, 1.0)
        desc = "expansion de volatilite sans direction - mouvements larges et brutaux"
    elif adx_v < 18 and er_v < 0.18:
        if atr_pct > 75:
            label = "chaos"
            strength = clamp(atr_pct / 100.0, 0.3, 1.0)
            desc = "beaucoup de mouvement, aucune direction - le pire contexte pour scalper"
        else:
            label = "range"
            strength = clamp(1.0 - er_v * 3, 0.2, 1.0)
            desc = "range - jouer les extremes vers la moyenne, cibles courtes"
    else:
        label = "range"
        strength = 0.4
        desc = "contexte indecis - exiger davantage de confluence"

    return Regime(
        label=label,
        direction=direction,
        strength=round(strength, 3),
        adx=adx_value,
        efficiency=er_value,
        atr_percentile=round(atr_pct, 1),
        bb_percentile=round(bb_pct, 1),
        squeeze=squeeze_on,
        volatility_state=vol_state,
        description=desc,
    )
