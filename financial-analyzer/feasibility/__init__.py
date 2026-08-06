"""Enveloppe de faisabilité — première pièce exécutable du projet.

Ce paquet ne cherche pas un avantage. Il détermine **où un avantage peut encore
exister** après coûts, latence et rareté des occurrences :

    D_feasible = D_cost  ∩  D_latency  ∩  D_frequency

Aucun moteur prédictif n'est impliqué : les trois calculs sont indépendants de tout
motif, de toute étiquette et de tout modèle. C'est ce qui leur permet de conclure
négativement avant qu'un seul signal ne soit défini.

Code de recherche, exécuté hors ligne sur des données historiques. Il ne préjuge pas de
la pile technique du système de production (Q1, ADR-005).
"""

from .costs import (
    CostSample,
    FinancingSpec,
    adverse_selection_cost,
    modeled_round_trip_cost,
    observed_round_trip_cost,
)
from .envelope import CellEnvelope, EnvelopeVerdict, combine, summarise
from .frequency import (
    FrequencyRequirement,
    FrequencyVerdict,
    OccurrenceCensus,
    assess_frequency,
    economic_frequency_floor,
    statistical_frequency_floor,
)
from .kappa import CostVerdict, KappaResult, kappa_with_ci, minimum_cost_horizon
from .latency import (
    LatencyVerdict,
    Phase0Result,
    detect_price_events,
    evaluation_latency_percentile,
    phase0_residual,
)
from .model import (
    Cell,
    ConventionError,
    Conventions,
    CostMethod,
    PlausibleEdgeBand,
    Provenance,
    ReferencePriceConvention,
    RoundTripDefinition,
    SampleSize,
    SpreadCountingConvention,
)
from .scale import ScaleEstimate, displacement_sample, realized_scale, sqrt_time_diagnostic

__all__ = [
    "Cell",
    "CellEnvelope",
    "ConventionError",
    "Conventions",
    "CostMethod",
    "CostSample",
    "CostVerdict",
    "EnvelopeVerdict",
    "FinancingSpec",
    "FrequencyRequirement",
    "FrequencyVerdict",
    "KappaResult",
    "LatencyVerdict",
    "OccurrenceCensus",
    "Phase0Result",
    "PlausibleEdgeBand",
    "Provenance",
    "ReferencePriceConvention",
    "RoundTripDefinition",
    "SampleSize",
    "ScaleEstimate",
    "SpreadCountingConvention",
    "adverse_selection_cost",
    "assess_frequency",
    "combine",
    "detect_price_events",
    "displacement_sample",
    "economic_frequency_floor",
    "evaluation_latency_percentile",
    "kappa_with_ci",
    "minimum_cost_horizon",
    "modeled_round_trip_cost",
    "observed_round_trip_cost",
    "phase0_residual",
    "realized_scale",
    "sqrt_time_diagnostic",
    "statistical_frequency_floor",
    "summarise",
]
