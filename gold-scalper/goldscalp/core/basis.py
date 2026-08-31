"""Mesure automatique de la base Bybit ↔ or spot.

Le problème
-----------
Le prix Bybit du XAUT n'est pas le prix de l'or. Il en diffère de plusieurs
dollars, et cet écart **dérive** : prime du métal tokenisé, ancrage imparfait
de l'USDT, flux propres à la plateforme. Un ancrage manuel fige cette valeur à
l'instant du relevé ; deux heures plus tard elle est fausse, et tous les
niveaux avec elle.

La solution
-----------
On dispose déjà d'une cotation de l'or SPOT (Yahoo `XAUUSD=X`), le même
sous-jacent que le XAUUSD du broker. Il suffit d'aligner les deux séries sur
leurs horodatages et de mesurer l'écart :

    base(t) = spot(t) − bybit(t)

Cette mesure est refaite à chaque analyse. L'ancrage manuel ne sert alors plus
qu'à capturer le **markup du broker** — quelques dizaines de centimes, stable —
au lieu de la prime XAUT qui, elle, bouge sans arrêt.

Robustesse
----------
La médiane et l'écart absolu médian sont préférés à la moyenne et à
l'écart-type : une seule bougie aberrante (mèche de liquidation sur XAUT,
trou de cotation chez Yahoo) suffirait à décaler une moyenne de plusieurs
dollars, donc à déplacer tous les stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from goldscalp.core.series import Series
from goldscalp.util import LOG, clamp, linreg_slope, median, ms_to_iso, now_ms, theil_sen

MIN_SAMPLES = 12            # en dessous, la médiane n'a pas de sens
MAX_AGE_MS = 3 * 3600_000   # au-delà, l'échantillon ne décrit plus le marché
MAX_PLAUSIBLE = 80.0        # $ — au-delà, ce ne sont pas deux cotations de l'or


@dataclass
class Basis:
    """Écart mesuré entre l'or spot et la cotation Bybit."""

    value: float = 0.0            # $ à ajouter au prix Bybit pour obtenir le spot
    samples: int = 0
    dispersion: float = 0.0       # écart absolu médian, en $
    drift_per_hour: float = 0.0   # dérive de la base, en $/h
    last_ts: int = 0
    spread_observed: float = 0.0  # amplitude de la base sur la fenêtre
    ok: bool = False
    note: str = "non mesurée"

    @property
    def age_ms(self) -> int:
        return max(0, now_ms() - self.last_ts) if self.last_ts else 10 ** 12

    def quality(self) -> float:
        """0-100 : peut-on se fier à cette base ?"""
        if not self.ok:
            return 0.0
        score = 40.0
        score += min(self.samples, 60) / 60.0 * 25.0
        # Une dispersion de 0.20 $ est excellente, 1.50 $ est inexploitable.
        score += clamp(25.0 * (1.0 - self.dispersion / 1.5), 0.0, 25.0)
        age_h = self.age_ms / 3600_000
        score += clamp(10.0 * (1.0 - age_h / 3.0), 0.0, 10.0)
        return round(clamp(score, 0.0, 100.0), 1)

    def to_spot(self, bybit_price: float) -> float:
        return bybit_price + self.value

    def apply(self, series: Series) -> Series:
        """Traduit une série Bybit en série d'or spot."""
        return series.apply_calibration(self.value, 1.0)

    def describe(self) -> str:
        if not self.ok:
            return f"base Bybit→spot non mesurée ({self.note})"
        return (
            f"base Bybit→spot {self.value:+.2f} $ "
            f"(± {self.dispersion:.2f}, {self.samples} bougies, "
            f"dérive {self.drift_per_hour:+.2f} $/h, qualité {self.quality():.0f}/100)"
        )

    def warnings(self) -> list[str]:
        out: list[str] = []
        if not self.ok:
            return out
        if self.dispersion > 0.80:
            out.append(
                f"Base bruitée (± {self.dispersion:.2f} $) : les deux cotations ne "
                "bougent pas en phase, la correction est approximative."
            )
        if abs(self.drift_per_hour) > 1.5:
            out.append(
                f"La base dérive de {self.drift_per_hour:+.2f} $/h — prime XAUT ou "
                "ancrage USDT instable. Recalibre plus souvent."
            )
        if self.age_ms > MAX_AGE_MS:
            out.append(
                f"Base mesurée il y a {self.age_ms / 3600_000:.1f} h : le marché spot "
                "était peut-être fermé depuis."
            )
        return out


def estimate_basis(bybit: Series, spot: Series, lookback: int = 120) -> Basis:
    """Mesure la base sur les bougies communes aux deux séries.

    `lookback` est un nombre de bougies communes, pas de minutes : les deux
    séries peuvent avoir des granularités identiques mais des trous différents.
    """
    if not bybit or not spot:
        return Basis(note="une des deux séries est vide")

    # On ne compare que des bougies CLÔTURÉES : la dernière est en formation
    # de part et d'autre, et rarement au même stade.
    left = {c.ts: c.close for c in bybit.closed_only}
    right = {c.ts: c.close for c in spot.closed_only}
    common = sorted(set(left) & set(right))

    if len(common) < MIN_SAMPLES:
        return Basis(
            samples=len(common),
            note=f"seulement {len(common)} bougies communes (minimum {MIN_SAMPLES})",
        )

    common = common[-lookback:]
    diffs = [right[ts] - left[ts] for ts in common]

    centre = median(diffs)
    if abs(centre) > MAX_PLAUSIBLE:
        LOG.warning("base aberrante de %.2f $ — séries incompatibles ?", centre)
        return Basis(
            value=0.0, samples=len(common),
            note=f"écart de {centre:.0f} $ hors de toute plausibilité pour deux cotations de l'or",
        )

    # Écart absolu médian : insensible aux mèches isolées.
    dispersion = median([abs(d - centre) for d in diffs])

    # Dérive : pente de la base, ramenée à l'heure.
    bars = len(common)
    span_ms = common[-1] - common[0]
    drift = 0.0
    if bars >= 8 and span_ms > 0:
        slope_per_bar = linreg_slope(diffs)
        bar_ms = span_ms / max(bars - 1, 1)
        drift = slope_per_bar * (3600_000 / bar_ms) if bar_ms else 0.0

    # Une base qui dérive doit être estimée MAINTENANT, pas au centre de la
    # fenêtre. Prendre la médiane d'une série en pente introduit un retard égal
    # à la moitié de la dérive sur la fenêtre — soit plusieurs dizaines de
    # centimes d'erreur permanente sur les niveaux.
    #
    # On projette donc une régression de Theil-Sen (pente médiane des paires,
    # insensible aux valeurs aberrantes contrairement aux moindres carrés) sur
    # la dernière bougie observée.
    recent = diffs[-max(MIN_SAMPLES, bars // 4):]
    fallback = median(recent) * 0.65 + centre * 0.35

    value = fallback
    if bars >= 24:
        intercept, slope = theil_sen(list(range(bars)), diffs)
        projected = intercept + slope * (bars - 1)
        # Garde-fou : l'extrapolation ne doit jamais sortir de la plage
        # réellement observée, marge d'une demi-dispersion mise à part. Une
        # pente mal estimée ne peut donc pas produire un prix fantaisiste.
        low = min(diffs) - dispersion - 0.10
        high = max(diffs) + dispersion + 0.10
        value = clamp(projected, low, high)

    return Basis(
        value=round(value, 4),
        samples=bars,
        dispersion=round(dispersion, 4),
        drift_per_hour=round(clamp(drift, -50.0, 50.0), 4),
        last_ts=common[-1],
        spread_observed=round(max(diffs) - min(diffs), 4),
        ok=True,
        note=f"mesurée sur {bars} bougies communes jusqu'à {ms_to_iso(common[-1])}",
    )


def best_common_timeframe(bybit: dict[str, Series], spot: dict[str, Series]) -> Optional[str]:
    """Choisit le timeframe offrant le meilleur recouvrement des deux sources.

    On préfère la granularité la plus fine qui fournisse assez de points : plus
    les bougies sont courtes, plus la base mesurée colle à l'instant présent.
    """
    for timeframe in ("M1", "M5", "M15"):
        left, right = bybit.get(timeframe), spot.get(timeframe)
        if not left or not right:
            continue
        common = set(c.ts for c in left.closed_only) & set(c.ts for c in right.closed_only)
        if len(common) >= MIN_SAMPLES:
            return timeframe
    return None
