"""Analyse d'exécution propre au scalp, et au mode turbo en particulier.

Ce que le moteur de confluence mesure, c'est une DIRECTION : où va le marché.
Ce module mesure autre chose, que le scalp exige et que le swing ignore :
l'INSTANT et le COÛT. Un signal directionnellement juste peut être un mauvais
scalp pour des raisons qui n'apparaissent nulle part dans un score de tendance :

  - le spread mange un tiers de la cible ;
  - le prix est collé sous une résistance, il n'a nulle part où aller ;
  - le mouvement a déjà couru, on entrerait en retard sur trois bougies ;
  - la bougie déclencheuse est une mèche, pas une impulsion ;
  - le marché ne bouge pas assez vite pour atteindre la cible avant expiration.

Chaque contrôle est explicite, chiffré et justifié. Certains sont BLOQUANTS :
ils interdisent le mode turbo quelle que soit la confiance directionnelle,
parce qu'aucune conviction ne compense une cible inaccessible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from goldscalp.core.indicators import IndicatorSet, ema, last, last_valid, slope_of
from goldscalp.core.regime import SessionInfo
from goldscalp.core.structure import StructureView
from goldscalp.util import clamp, median, safe_div

# Fenêtres d'ouverture : les 30 premières minutes de Londres et de New York
# concentrent les expansions de volatilité les plus exploitables.
OPENING_WINDOWS = [(7, 0, 30, "ouverture de Londres"), (12, 30, 30, "ouverture de New York")]

# Part maximale de la cible que le spread peut absorber. Au-delà, le scalp est
# structurellement perdant même avec un taux de réussite correct.
MAX_SPREAD_SHARE = 0.15

# En dessous de cette force, un niveau ne freine pas durablement le prix : le
# compter comme obstacle rendrait tout scalp impossible.
MIN_OBSTACLE_STRENGTH = 0.55


@dataclass
class ScalpCheck:
    name: str
    passed: bool
    value: float
    detail: str
    weight: float = 1.0
    blocking: bool = False

    @property
    def symbol(self) -> str:
        return "ok" if self.passed else ("BLOQUE" if self.blocking else "faible")


@dataclass
class ScalpView:
    """Qualité d'exécution d'un scalp, indépendamment de sa direction."""

    direction: int = 0
    checks: list[ScalpCheck] = field(default_factory=list)
    score: float = 0.0            # 0..1
    burst: bool = False           # impulsion en cours
    chase_bars: int = 0           # bougies déjà parcourues depuis le déclencheur
    spread_share: float = 0.0     # part de la cible mangée par le spread
    room: float = 0.0             # $ disponibles avant le premier obstacle
    velocity: float = 0.0         # $/minute sur les 5 dernières M1
    window: str = ""              # fenêtre horaire remarquable, si applicable
    estimated_target: float = 0.0

    @property
    def blockers(self) -> list[ScalpCheck]:
        return [c for c in self.checks if c.blocking and not c.passed]

    # Un turbo entre AU MARCHÉ, sans attendre de repli. Ça ne se justifie que
    # si la bougie déclencheuse porte réellement le mouvement : sans impulsion,
    # entrer au marché revient à payer le spread pour rien.
    TURBO_REQUIRED = ("impulsion du déclencheur",)
    TURBO_MIN_SCORE = 0.70

    @property
    def turbo_ready(self) -> bool:
        if self.direction == 0 or self.blockers or self.score < self.TURBO_MIN_SCORE:
            return False
        required = {c.name: c.passed for c in self.checks}
        return all(required.get(name, False) for name in self.TURBO_REQUIRED)

    @property
    def turbo_refusal(self) -> str:
        """Pourquoi l'exécution refuse le turbo, en une phrase."""
        if self.direction == 0:
            return "aucune direction"
        if self.blockers:
            return " ; ".join(c.detail for c in self.blockers)
        if self.score < self.TURBO_MIN_SCORE:
            return f"qualité d'exécution {self.score:.0%} sous le seuil de {self.TURBO_MIN_SCORE:.0%}"
        missing = [n for n in self.TURBO_REQUIRED
                   if not next((c.passed for c in self.checks if c.name == n), False)]
        if missing:
            return "contrôle indispensable en échec : " + ", ".join(missing)
        return ""

    @property
    def verdict(self) -> str:
        if self.direction == 0:
            return "aucune direction à exécuter"
        if self.blockers:
            return "exécution refusée : " + " ; ".join(c.detail for c in self.blockers)
        if self.score >= 0.80:
            return "conditions d'exécution excellentes"
        if self.score >= 0.65:
            return "conditions d'exécution correctes"
        if self.score >= 0.45:
            return "exécution médiocre - réduire la taille ou attendre"
        return "conditions d'exécution mauvaises"

    def summary(self) -> list[str]:
        return [f"[{c.symbol}] {c.detail}" for c in self.checks]


def _nearest_obstacle(structure: StructureView, price: float, direction: int,
                      min_distance: float, min_strength: float):
    """Premier niveau SOLIDE devant le prix, dans le sens du trade."""
    if direction > 0:
        candidates = [l for l in structure.levels
                      if l.price > price + min_distance and l.strength >= min_strength]
        return min(candidates, key=lambda l: l.price) if candidates else None
    candidates = [l for l in structure.levels
                  if l.price < price - min_distance and l.strength >= min_strength]
    return max(candidates, key=lambda l: l.price) if candidates else None


def _opening_window(ts_ms: int) -> str:
    hour = int((ts_ms // 3_600_000) % 24)
    minute = int((ts_ms // 60_000) % 60)
    for start_hour, start_minute, span, label in OPENING_WINDOWS:
        start = start_hour * 60 + start_minute
        current = hour * 60 + minute
        if start <= current < start + span:
            return label
    return ""


def analyse_scalp(direction: int, m1: IndicatorSet, m5: IndicatorSet,
                  structure: StructureView, session: SessionInfo, spread: float,
                  target_multiplier: float = 1.0) -> ScalpView:
    """Évalue si le trade est exécutable MAINTENANT, au prix du scalp."""
    view = ScalpView(direction=direction)
    if direction == 0 or len(m1.series) < 25:
        return view

    candles = m1.series.candles
    trigger = candles[-1]
    atr1 = m1.atr_value
    atr5 = m5.atr_value
    price = trigger.close
    checks: list[ScalpCheck] = []

    # Cible estimée pour juger des coûts. Le plan la recalculera précisément ;
    # ici on a seulement besoin d'un ordre de grandeur réaliste.
    target = max(atr5 * target_multiplier, atr1 * 1.5)
    view.estimated_target = round(target, 2)

    # -- 1. coût du spread (bloquant) --------------------------------------- #
    share = safe_div(spread, target, 1.0)
    view.spread_share = round(share, 4)
    checks.append(ScalpCheck(
        "coût du spread", share <= MAX_SPREAD_SHARE, round(share, 4),
        f"le spread de {spread:.2f} $ représente {share:.0%} de la cible estimée "
        f"({target:.2f} $)" + ("" if share <= MAX_SPREAD_SHARE
                               else f" — au-delà de {MAX_SPREAD_SHARE:.0%}, le scalp est perdant par construction"),
        weight=1.6, blocking=True,
    ))

    # -- 2. espace libre devant le prix ------------------------------------- #
    # Seuls les niveaux réellement DÉFENDUS comptent comme obstacles. Prendre
    # en compte chaque chiffre rond ou chaque swing touché une seule fois
    # reviendrait à déclarer le marché infranchissable en permanence : le prix
    # traverse ces niveaux sans ralentir.
    # Marge minuscule : un mur solide collé au prix EST l'obstacle ultime.
    # Un seuil large le ferait disparaître du calcul au pire moment.
    obstacle = _nearest_obstacle(structure, price, direction, atr1 * 0.02, MIN_OBSTACLE_STRENGTH)
    room = abs(obstacle.price - price) if obstacle else target * 3
    view.room = round(room, 2)
    enough_room = room >= target * 0.60
    # Bloquant seulement quand il n'y a vraiment nulle part où aller : entre
    # 35 % et 60 % de la cible, le trade reste possible en réduisant TP1.
    severe = room < target * 0.35
    checks.append(ScalpCheck(
        "espace disponible", enough_room, round(room, 2),
        (f"{room:.2f} $ avant {obstacle.label or obstacle.kind} à {obstacle.price:.2f} "
         f"(force {obstacle.strength:.2f})" if obstacle else "aucun obstacle sérieux à portée")
        + ("" if enough_room else
           f" — {'trop peu' if severe else 'juste'} pour une cible de {target:.2f} $"),
        weight=1.5, blocking=severe,
    ))

    # -- 3. impulsion de la bougie déclencheuse ----------------------------- #
    body_ratio = safe_div(trigger.body, trigger.range, 0.0)
    close_position = safe_div(
        (trigger.close - trigger.low) if direction > 0 else (trigger.high - trigger.close),
        trigger.range, 0.5,
    )
    range_ratio = safe_div(trigger.range, atr1, 0.0)
    aligned = (trigger.close > trigger.open) == (direction > 0)
    impulse = aligned and body_ratio >= 0.45 and close_position >= 0.6 and range_ratio >= 0.8
    view.burst = impulse
    checks.append(ScalpCheck(
        "impulsion du déclencheur", impulse,
        round(body_ratio, 3),
        f"corps {body_ratio:.0%} du range, clôture à {close_position:.0%} dans le sens, "
        f"amplitude {range_ratio:.1f}x ATR M1"
        + ("" if impulse else " — la bougie ne porte pas le mouvement"),
        weight=1.2,
    ))

    # -- 4. mèche de rejet contre le sens ----------------------------------- #
    against = trigger.upper_wick if direction > 0 else trigger.lower_wick
    wick_ratio = safe_div(against, trigger.range, 0.0)
    clean = wick_ratio <= 0.40
    checks.append(ScalpCheck(
        "absence de rejet", clean, round(wick_ratio, 3),
        f"mèche contre le sens : {wick_ratio:.0%} du range"
        + ("" if clean else " — le marché a repoussé le prix sur cette bougie"),
        weight=1.0,
    ))

    # -- 5. micro-tendance M1 (EMA 3 / 8) ----------------------------------- #
    closes = [c.close for c in candles]
    fast, slow = ema(closes, 3), ema(closes, 8)
    f, s = last_valid(fast), last_valid(slow)
    micro_ok = False
    separation = 0.0
    if f is not None and s is not None and atr1 > 0:
        separation = (f - s) / atr1
        micro_ok = (separation > 0.05) if direction > 0 else (separation < -0.05)
    checks.append(ScalpCheck(
        "micro-tendance M1", micro_ok, round(separation, 3),
        f"écart EMA3/EMA8 de {separation:+.2f} ATR"
        + ("" if micro_ok else " — les moyennes courtes ne confirment pas le sens"),
        weight=1.1,
    ))

    # -- 6. vitesse du marché ----------------------------------------------- #
    window = candles[-5:]
    travelled = abs(window[-1].close - window[0].open)
    minutes = max(len(window), 1)
    velocity = travelled / minutes
    typical = atr1 * 0.45
    fast_enough = velocity >= typical
    view.velocity = round(velocity, 3)
    checks.append(ScalpCheck(
        "vitesse", fast_enough, round(velocity, 3),
        f"{velocity:.2f} $/min sur 5 bougies (usuel {typical:.2f})"
        + ("" if fast_enough else " — trop lent pour atteindre la cible avant expiration"),
        weight=1.0,
    ))

    # -- 7. expansion de volatilité ----------------------------------------- #
    ranges = [c.range for c in candles[-20:-1]]
    typical_range = median(ranges) if ranges else atr1
    expansion = safe_div(trigger.range, typical_range, 1.0)
    expanding = expansion >= 1.1
    checks.append(ScalpCheck(
        "expansion", expanding, round(expansion, 2),
        f"amplitude {expansion:.2f}x la médiane des 20 dernières"
        + ("" if expanding else " — le marché se contracte, pas d'énergie"),
        weight=0.9,
    ))

    # -- 8. retard à l'entrée ----------------------------------------------- #
    chase = 0
    for candle in reversed(candles[-8:]):
        if (candle.close > candle.open) == (direction > 0) and candle.body > atr1 * 0.25:
            chase += 1
        else:
            break
    view.chase_bars = chase
    not_late = chase <= 3
    checks.append(ScalpCheck(
        "entrée non tardive", not_late, float(chase),
        f"{chase} bougies d'impulsion consécutives déjà parcourues"
        + ("" if not_late else " — entrer ici, c'est courir après le mouvement"),
        weight=1.2,
    ))

    # -- 9. cohérence M1 / M5 ------------------------------------------------ #
    m5_slope = slope_of(m5.ema21, 4)
    coherent = m5_slope is not None and ((m5_slope > 0) == (direction > 0))
    checks.append(ScalpCheck(
        "cohérence M5", coherent, round(m5_slope or 0.0, 4),
        "l'EMA21 M5 penche dans le sens du trade" if coherent
        else "l'EMA21 M5 penche contre le trade — scalp à contre-courant du support",
        weight=1.1,
    ))

    # -- 10. fenêtre horaire -------------------------------------------------- #
    opening = _opening_window(trigger.ts)
    view.window = opening
    good_window = session.is_prime or bool(opening)
    checks.append(ScalpCheck(
        "fenêtre horaire", good_window, session.volatility_factor,
        (f"{opening} — expansion attendue" if opening
         else f"session {session.name} (x{session.volatility_factor:.2f} de volatilité)")
        + ("" if good_window else " — liquidité insuffisante pour un scalp serré"),
        weight=0.8,
    ))

    # -- 11. changement de session imminent ---------------------------------- #
    settled = session.minutes_to_next >= 8
    checks.append(ScalpCheck(
        "stabilité de session", settled, float(session.minutes_to_next),
        f"changement de session dans {session.minutes_to_next} min"
        + ("" if settled else " — le régime de volatilité va basculer pendant le trade"),
        weight=0.6,
    ))

    view.checks = checks
    total = sum(c.weight for c in checks) or 1.0
    view.score = round(sum(c.weight for c in checks if c.passed) / total, 3)
    return view
