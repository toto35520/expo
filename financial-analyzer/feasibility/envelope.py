"""Enveloppe de faisabilité : intersection des trois domaines non exclus.

ADR-118 : l'autorité de déclenchement n'est envisageable que dans

    D_feasible = D_cost  ∩  D_latency  ∩  D_frequency

Une cellule hors de cette intersection ne peut pas recevoir de budget de construction
important. Y être ne démontre **aucune** rentabilité : cela signifie seulement qu'aucun
des trois arguments d'exclusion ne s'applique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .frequency import FrequencyRequirement, FrequencyVerdict
from .kappa import CostVerdict, KappaResult
from .latency import LatencyVerdict, Phase0Result
from .model import Cell, Provenance


class EnvelopeVerdict(str, Enum):
    #: Aucun des trois arguments n'exclut la cellule. Elle peut entrer dans les tests
    #: prédictifs. Ce n'est pas un résultat positif.
    ELIGIBLE_FOR_PREDICTIVE_TESTING = "ELIGIBLE_FOR_PREDICTIVE_TESTING"
    EXCLUDED_BY_COST = "EXCLUDED_BY_COST"
    EXCLUDED_BY_LATENCY = "EXCLUDED_BY_LATENCY"
    EXCLUDED_BY_FREQUENCY = "EXCLUDED_BY_FREQUENCY"
    EXCLUDED_BY_MULTIPLE = "EXCLUDED_BY_MULTIPLE"
    #: Au moins une dimension est indéterminée et aucune n'exclut : on ne sait pas.
    #: Distinct d'une exclusion, conformément à la doctrine des quatre situations.
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class CellEnvelope:
    cell: Cell
    horizon_ns: int
    cost_verdict: CostVerdict
    latency_verdict: LatencyVerdict
    frequency_verdict: FrequencyVerdict
    verdict: EnvelopeVerdict
    #: Ce que la cellule est autorisée à faire. Jamais élargi par l'enveloppe seule.
    trigger_authority: bool
    reasons: list[str] = field(default_factory=list)
    provenance: Provenance | None = None


def combine(
    cell: Cell,
    horizon_ns: int,
    kappa: KappaResult | None,
    phase0: Phase0Result | None,
    frequency: FrequencyRequirement | None,
    provenance: Provenance | None = None,
) -> CellEnvelope:
    """Intersection des trois domaines.

    Règle de préséance : une **exclusion** l'emporte sur une indétermination, laquelle
    l'emporte sur une non-exclusion. Autrement dit, on ne déclare jamais une cellule
    éligible tant qu'une dimension reste inconnue — l'ignorance ne vaut pas permission.
    """
    cost_v = kappa.verdict if kappa else CostVerdict.COST_INDETERMINATE
    lat_v = phase0.verdict if phase0 else LatencyVerdict.LATENCY_INDETERMINATE
    freq_v = frequency.verdict if frequency else FrequencyVerdict.FREQUENCY_INDETERMINATE

    exclusions: list[str] = []
    if cost_v is CostVerdict.COST_NON_VIABLE:
        exclusions.append("coût")
    if lat_v is LatencyVerdict.LATENCY_NON_VIABLE:
        exclusions.append("latence")
    if freq_v is FrequencyVerdict.FREQUENCY_NON_VIABLE:
        exclusions.append("fréquence")

    reasons: list[str] = []
    if kappa and kappa.verdict is not CostVerdict.COST_INDETERMINATE:
        reasons.append(
            f"kappa ∈ [{kappa.confidence_lower:.3g}, {kappa.confidence_upper:.3g}] "
            f"sur {kappa.sample.independent_clusters} blocs"
        )
    if phase0:
        reasons.append(
            f"résiduel net médian après latence : {phase0.residual_net_p50:.4g} "
            f"({phase0.consumed_fraction_p50:.0%} du mouvement déjà consommé)"
        )
    if frequency:
        reasons.append(frequency.rationale)

    if len(exclusions) > 1:
        verdict = EnvelopeVerdict.EXCLUDED_BY_MULTIPLE
    elif exclusions == ["coût"]:
        verdict = EnvelopeVerdict.EXCLUDED_BY_COST
    elif exclusions == ["latence"]:
        verdict = EnvelopeVerdict.EXCLUDED_BY_LATENCY
    elif exclusions == ["fréquence"]:
        verdict = EnvelopeVerdict.EXCLUDED_BY_FREQUENCY
    elif (
        cost_v is CostVerdict.COST_INDETERMINATE
        or lat_v is LatencyVerdict.LATENCY_INDETERMINATE
        or freq_v is FrequencyVerdict.FREQUENCY_INDETERMINATE
    ):
        verdict = EnvelopeVerdict.INDETERMINATE
    else:
        verdict = EnvelopeVerdict.ELIGIBLE_FOR_PREDICTIVE_TESTING

    if exclusions:
        reasons.insert(0, "exclue par : " + ", ".join(exclusions))

    return CellEnvelope(
        cell=cell,
        horizon_ns=horizon_ns,
        cost_verdict=cost_v,
        latency_verdict=lat_v,
        frequency_verdict=freq_v,
        verdict=verdict,
        trigger_authority=verdict is EnvelopeVerdict.ELIGIBLE_FOR_PREDICTIVE_TESTING,
        reasons=reasons,
        provenance=provenance,
    )


def summarise(envelopes: list[CellEnvelope]) -> dict[str, int]:
    """Carte des horizons, par verdict."""
    counts: dict[str, int] = {}
    for e in envelopes:
        counts[e.verdict.value] = counts.get(e.verdict.value, 0) + 1
    return counts
