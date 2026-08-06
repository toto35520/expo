"""Rapport coût / amplitude, son incertitude, et le verdict de coût.

kappa(h, c) est le nombre d'unités d'amplitude qu'une opération doit capturer rien que
pour couvrir ses frais. Les frais étant approximativement fixes par aller-retour et
l'amplitude croissant avec l'horizon, kappa décroît avec l'horizon — ce qui borne par
le bas les horizons où un avantage peut exister.

ADR-116 : un horizon n'est exclu que si la **borne inférieure** de kappa dépasse
l'avantage maximal plausible. Exclure sur une estimation ponctuelle reviendrait à
éliminer des cellules par manque de données.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from .costs import CostSample
from .model import Cell, PlausibleEdgeBand, SampleSize
from .scale import robust_scale


class CostVerdict(str, Enum):
    """Quatre issues distinctes, aux conséquences différentes (famille ADR-095)."""

    #: Même sous une lecture optimiste des coûts, la cellule exige plus d'avantage que
    #: la bande jugée plausible. Aucune autorité de déclenchement.
    COST_NON_VIABLE = "COST_NON_VIABLE"
    #: Les coûts ne suffisent pas à éliminer la cellule. Ne démontre **aucune**
    #: rentabilité — dit seulement que l'argument de coût ne tranche pas.
    COST_NOT_EXCLUDED = "COST_NOT_EXCLUDED"
    #: Marge de coût confortable. Reste soumis aux gates de latence, de fréquence et
    #: aux tests prédictifs.
    COST_HEADROOM = "COST_HEADROOM"
    #: Données insuffisantes ou trop incertaines pour trancher dans un sens ou l'autre.
    COST_INDETERMINATE = "COST_INDETERMINATE"


@dataclass(frozen=True)
class KappaResult:
    horizon_ns: int
    cell: Cell
    kappa_p50: float
    kappa_p95: float
    #: Bornes de confiance sur kappa évalué au quantile de coût retenu.
    confidence_lower: float
    confidence_upper: float
    cost_quantile_used: float
    scale: float
    sample: SampleSize
    verdict: CostVerdict


def _kappa_from(cost_samples: np.ndarray, disp: np.ndarray, cost_q: float) -> float:
    if cost_samples.size == 0 or disp.size == 0:
        return float("nan")
    s = robust_scale(disp)
    if not np.isfinite(s) or s <= 0:
        return float("nan")
    return float(np.quantile(cost_samples, cost_q) / s)


def kappa_with_ci(
    cost: CostSample,
    displacements: np.ndarray,
    displacement_clusters: np.ndarray,
    horizon_ns: int,
    band: PlausibleEdgeBand,
    cost_quantile: float = 0.95,
    n_bootstrap: int = 400,
    min_clusters: int = 20,
    confidence: float = 0.90,
    rng: np.random.Generator | None = None,
) -> KappaResult:
    """kappa et son intervalle, par rééchantillonnage **par blocs**.

    Coût et amplitude sont recalculés sur les mêmes blocs tirés : ils partagent la
    séance, et les rééchantillonner séparément supprimerait cette dépendance et
    resserrerait artificiellement l'intervalle.
    """
    rng = rng or np.random.default_rng(0)

    shared = np.intersect1d(np.unique(cost.cluster_ids), np.unique(displacement_clusters))
    sample = SampleSize(
        observations=int(min(cost.samples.size, displacements.size)),
        independent_clusters=int(shared.size),
    )

    point = _kappa_from(cost.samples, displacements, cost_quantile)
    scale_value = robust_scale(displacements)

    if not sample.is_sufficient(min_clusters) or not np.isfinite(point):
        return KappaResult(
            horizon_ns=horizon_ns,
            cell=cost.cell,
            kappa_p50=_kappa_from(cost.samples, displacements, 0.5),
            kappa_p95=point,
            confidence_lower=float("nan"),
            confidence_upper=float("nan"),
            cost_quantile_used=cost_quantile,
            scale=scale_value,
            sample=sample,
            verdict=CostVerdict.COST_INDETERMINATE,
        )

    cost_by_cluster = {c: cost.samples[cost.cluster_ids == c] for c in shared}
    disp_by_cluster = {c: displacements[displacement_clusters == c] for c in shared}

    draws = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        picked = rng.choice(shared, size=shared.size, replace=True)
        c_boot = np.concatenate([cost_by_cluster[c] for c in picked])
        d_boot = np.concatenate([disp_by_cluster[c] for c in picked])
        draws[i] = _kappa_from(c_boot, d_boot, cost_quantile)

    draws = draws[np.isfinite(draws)]
    if draws.size < n_bootstrap // 2:
        verdict = CostVerdict.COST_INDETERMINATE
        lo = hi = float("nan")
    else:
        alpha = (1.0 - confidence) / 2.0
        lo = float(np.quantile(draws, alpha))
        hi = float(np.quantile(draws, 1.0 - alpha))
        verdict = _verdict(lo, hi, band)

    return KappaResult(
        horizon_ns=horizon_ns,
        cell=cost.cell,
        kappa_p50=_kappa_from(cost.samples, displacements, 0.5),
        kappa_p95=point,
        confidence_lower=lo,
        confidence_upper=hi,
        cost_quantile_used=cost_quantile,
        scale=scale_value,
        sample=sample,
        verdict=verdict,
    )


def _verdict(lower: float, upper: float, band: PlausibleEdgeBand) -> CostVerdict:
    """ADR-116. L'exclusion s'appuie sur la borne **inférieure**, la marge sur la borne
    supérieure : dans les deux cas, l'incertitude joue contre la conclusion tranchée."""
    if lower > band.a_max:
        return CostVerdict.COST_NON_VIABLE
    if upper < band.a_min:
        return CostVerdict.COST_HEADROOM
    return CostVerdict.COST_NOT_EXCLUDED


@dataclass(frozen=True)
class MinimumHorizon:
    """Horizon minimal de coût, avec la règle de persistance qui l'a produit."""

    horizon_ns: int | None
    reason: str
    consecutive_required: int
    block_fraction_required: float


def minimum_cost_horizon(
    results: list[KappaResult],
    band: PlausibleEdgeBand,
    consecutive_required: int = 3,
) -> MinimumHorizon:
    """Plus petit horizon où kappa passe durablement sous l'avantage plausible.

    Un point isolé ne suffit pas : la courbe empirique est irrégulière, et un unique
    franchissement est plus souvent un artefact d'échantillonnage qu'un seuil réel. On
    exige un franchissement sur plusieurs horizons consécutifs.
    """
    ordered = sorted(results, key=lambda r: r.horizon_ns)
    run = 0
    for r in ordered:
        crossed = np.isfinite(r.confidence_upper) and r.confidence_upper < band.a_max
        run = run + 1 if crossed else 0
        if run >= consecutive_required:
            first = ordered[ordered.index(r) - consecutive_required + 1]
            return MinimumHorizon(
                horizon_ns=first.horizon_ns,
                reason=f"kappa sous a_max sur {consecutive_required} horizons consécutifs",
                consecutive_required=consecutive_required,
                block_fraction_required=0.0,
            )
    return MinimumHorizon(
        horizon_ns=None,
        reason="aucun franchissement persistant sur la grille étudiée",
        consecutive_required=consecutive_required,
        block_fraction_required=0.0,
    )
