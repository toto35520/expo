"""Plancher de fréquence : économique et statistique.

ADR-117 : ce sont deux conditions distinctes, et la fréquence requise est leur maximum.
Un motif peut être assez fréquent pour être rentable mais trop rare pour être validé —
ou l'inverse. Les confondre laisse passer l'un des deux échecs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class FrequencyVerdict(str, Enum):
    FREQUENCY_NON_VIABLE = "FREQUENCY_NON_VIABLE"
    FREQUENCY_NOT_EXCLUDED = "FREQUENCY_NOT_EXCLUDED"
    FREQUENCY_INDETERMINATE = "FREQUENCY_INDETERMINATE"


@dataclass(frozen=True)
class OccurrenceCensus:
    """Comptage brut, avant toute étiquette de résultat.

    Calculable dès qu'une définition d'occurrence existe — donc bien avant de savoir si
    le motif prédit quoi que ce soit. C'est le test le moins coûteux du protocole.
    """

    raw_occurrences: int
    observation_span_days: float
    independent_clusters: int
    regimes_covered: int

    @property
    def per_day(self) -> float:
        if self.observation_span_days <= 0:
            return float("nan")
        return self.raw_occurrences / self.observation_span_days


@dataclass(frozen=True)
class FrequencyRequirement:
    f_min_economic: float
    f_min_statistical: float
    verdict: FrequencyVerdict
    rationale: str

    @property
    def f_min(self) -> float:
        return max(self.f_min_economic, self.f_min_statistical)


def economic_frequency_floor(
    target_contribution_per_day: float,
    fixed_costs_per_day: float,
    fill_probability: float,
    optimistic_ev_per_occurrence: float,
) -> float:
    """Occurrences par jour requises pour atteindre une contribution cible.

    `optimistic_ev_per_occurrence` est une **borne haute plausible**, pas une espérance
    mesurée : le but est de tester la viabilité avant de connaître le signal. Si même
    cette borne exige plus d'occurrences qu'il n'en survient, le motif est écarté sans
    aucun test prédictif.
    """
    denom = fill_probability * optimistic_ev_per_occurrence
    if denom <= 0:
        return float("inf")
    return float((target_contribution_per_day + fixed_costs_per_day) / denom)


def statistical_frequency_floor(
    min_independent_clusters: int,
    observation_span_days: float,
    occurrences_per_cluster: float = 1.0,
) -> float:
    """Occurrences par jour requises pour que le motif soit **validable**.

    Un effet réel dont l'intervalle de confiance dépasse sa propre taille ne peut être
    ni confirmé ni réfuté : le gate rendrait `INDETERMINATE` quelle que soit la réalité.
    """
    if observation_span_days <= 0 or occurrences_per_cluster <= 0:
        return float("inf")
    return float(min_independent_clusters * occurrences_per_cluster / observation_span_days)


def assess_frequency(
    census: OccurrenceCensus,
    f_min_economic: float,
    f_min_statistical: float,
    min_regimes: int = 2,
) -> FrequencyRequirement:
    observed = census.per_day
    required = max(f_min_economic, f_min_statistical)

    if not np.isfinite(observed):
        return FrequencyRequirement(
            f_min_economic, f_min_statistical,
            FrequencyVerdict.FREQUENCY_INDETERMINATE,
            "durée d'observation nulle ou inconnue",
        )
    if census.regimes_covered < min_regimes:
        return FrequencyRequirement(
            f_min_economic, f_min_statistical,
            FrequencyVerdict.FREQUENCY_INDETERMINATE,
            f"couverture de régimes insuffisante ({census.regimes_covered} < {min_regimes})",
        )
    if observed < required:
        binding = "économique" if f_min_economic >= f_min_statistical else "statistique"
        return FrequencyRequirement(
            f_min_economic, f_min_statistical,
            FrequencyVerdict.FREQUENCY_NON_VIABLE,
            f"{observed:.4g}/jour observées contre {required:.4g} requises "
            f"(plancher {binding} contraignant)",
        )
    return FrequencyRequirement(
        f_min_economic, f_min_statistical,
        FrequencyVerdict.FREQUENCY_NOT_EXCLUDED,
        f"{observed:.4g}/jour observées, {required:.4g} requises",
    )
