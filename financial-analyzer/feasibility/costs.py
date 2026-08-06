"""Modèle de coûts aller-retour.

ADR-110 : deux méthodes autorisées, jamais mélangées.
ADR-111 : dans la méthode observée, latence et glissement sont **déjà** dans
l'implementation shortfall et ne s'ajoutent pas séparément.
ADR-105 : le résultat dépend de la cellule ; il n'existe pas de coût universel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .model import Cell, ConventionError, Conventions, CostMethod, SpreadCountingConvention


@dataclass(frozen=True)
class CostSample:
    """Distribution de coût aller-retour pour une cellule, en unité de prix."""

    cell: Cell
    method: CostMethod
    #: Échantillon de coûts aller-retour, un par occurrence.
    samples: np.ndarray
    #: Identifiant de bloc indépendant de chaque échantillon (typiquement la séance).
    cluster_ids: np.ndarray
    components: dict[str, float] = field(default_factory=dict)

    def quantile(self, q: float) -> float:
        if self.samples.size == 0:
            return float("nan")
        return float(np.quantile(self.samples, q))

    @property
    def independent_clusters(self) -> int:
        return int(np.unique(self.cluster_ids).size)


@dataclass(frozen=True)
class FinancingSpec:
    """Portage overnight — seul terme proportionnel à la durée.

    C'est lui qui rend le coût dépendant de l'horizon, donc qui fait que le choix des
    horizons conditionne toute la surface de coûts. Aucune valeur n'est supposée : le jour
    de portage multiplié en particulier doit être vérifié auprès de la source d'exécution,
    jamais deviné.
    """

    long_per_day: float
    short_per_day: float
    triple_day_index: int | None = None
    verified_with_broker: bool = False

    def cost_for(self, horizon_ns: int, direction: int, crossings: int = 0) -> float:
        """Coût de portage pour une durée et un sens donnés.

        `crossings` est le nombre de franchissements de l'heure de rollover, à fournir par
        l'appelant : il dépend du fuseau serveur du courtier et du calendrier, que ce
        module n'a pas à redécouvrir.
        """
        per_day = self.long_per_day if direction > 0 else self.short_per_day
        return float(per_day * crossings)


def modeled_round_trip_cost(
    cell: Cell,
    conventions: Conventions,
    spread_samples: np.ndarray,
    cluster_ids: np.ndarray,
    commission_round_trip: float,
    latency_slippage_samples: np.ndarray | None = None,
    impact: float = 0.0,
    financing: float = 0.0,
) -> CostSample:
    """Méthode B — décomposition explicite.

    Le glissement de latence est fourni comme un échantillon **modélisé** ; il ne doit
    jamais être un glissement observé de bout en bout, qui contiendrait déjà le spread.
    """
    if conventions.cost_measurement_method is not CostMethod.MODELED:
        raise ConventionError(
            "modeled_round_trip_cost exige la méthode MODELED. Mélanger les deux "
            "méthodes dans une même estimation compte deux fois les mêmes termes."
        )

    spread_samples = np.asarray(spread_samples, dtype=float)
    if spread_samples.size == 0:
        raise ValueError("Aucun échantillon de spread : le coût n'est pas estimable.")

    conv = conventions.spread_counting_convention
    if conv is SpreadCountingConvention.HALF_SPREAD_EACH_SIDE:
        spread_cost = spread_samples  # deux demi-spreads = un spread complet
    elif conv is SpreadCountingConvention.FULL_SPREAD_ONCE:
        spread_cost = spread_samples
    else:  # pragma: no cover - interdit par Conventions.__post_init__
        raise ConventionError(f"Convention de spread inapplicable en MODELED : {conv}")

    slippage = (
        np.asarray(latency_slippage_samples, dtype=float)
        if latency_slippage_samples is not None
        else np.zeros_like(spread_cost)
    )
    if slippage.size not in (spread_cost.size, 1):
        raise ValueError(
            "Le glissement modélisé doit être scalaire ou aligné sur les spreads "
            f"({slippage.size} contre {spread_cost.size})."
        )

    total = spread_cost + slippage + commission_round_trip + impact + financing
    return CostSample(
        cell=cell,
        method=CostMethod.MODELED,
        samples=total,
        cluster_ids=np.asarray(cluster_ids),
        components={
            "spread_p50": float(np.median(spread_cost)),
            "spread_p95": float(np.quantile(spread_cost, 0.95)),
            "commission_round_trip": commission_round_trip,
            "modeled_slippage_p95": float(np.quantile(slippage, 0.95)) if slippage.size else 0.0,
            "impact": impact,
            "financing": financing,
        },
    )


def observed_round_trip_cost(
    cell: Cell,
    conventions: Conventions,
    entry_shortfall: np.ndarray,
    exit_shortfall: np.ndarray,
    cluster_ids: np.ndarray,
    commission_round_trip: float,
    financing: float = 0.0,
) -> CostSample:
    """Méthode A — implementation shortfall observé.

    Chaque shortfall est déjà signé dans le sens défavorable et contient spread,
    mouvement pendant la latence, glissement, impact et effet de file. Aucun de ces
    termes n'est ajouté ensuite.
    """
    if conventions.cost_measurement_method is not CostMethod.OBSERVED_IS:
        raise ConventionError(
            "observed_round_trip_cost exige la méthode OBSERVED_IS."
        )

    entry = np.asarray(entry_shortfall, dtype=float)
    exit_ = np.asarray(exit_shortfall, dtype=float)
    if entry.size != exit_.size:
        raise ValueError("Les shortfalls d'entrée et de sortie doivent être appariés.")
    if entry.size == 0:
        raise ValueError("Aucune exécution observée : le coût n'est pas estimable.")

    total = entry + exit_ + commission_round_trip + financing
    return CostSample(
        cell=cell,
        method=CostMethod.OBSERVED_IS,
        samples=total,
        cluster_ids=np.asarray(cluster_ids),
        components={
            "entry_shortfall_p50": float(np.median(entry)),
            "exit_shortfall_p50": float(np.median(exit_)),
            "commission_round_trip": commission_round_trip,
            "financing": financing,
        },
    )


def adverse_selection_cost(
    post_fill_returns: np.ndarray,
    direction: int,
    control_returns: np.ndarray,
) -> float:
    """Coût de sélection adverse des ordres passifs (ADR-108).

    Un ordre limite est exécuté préférentiellement quand le marché vient vers vous, donc
    quand vous avez tort. On compare le rendement **conditionnel à l'exécution** au
    rendement d'un échantillon témoin apparié. Une valeur positive est un coût.

    Ce terme n'apparaît sur aucun relevé de frais : il ne peut être que mesuré.
    """
    fills = np.asarray(post_fill_returns, dtype=float)
    control = np.asarray(control_returns, dtype=float)
    if fills.size == 0 or control.size == 0:
        return float("nan")
    return float(direction * (np.mean(control) - np.mean(fills)))
