"""Amplitude réalisée multi-échelle.

ADR-114 : la mesure principale de sigma(h) est **empirique**. La loi en racine carrée du
temps n'est qu'une approximation de contrôle — elle sert à repérer les anomalies, jamais
à imposer une courbe aux données.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Facteur rendant l'écart absolu médian comparable à un écart-type sous loi normale.
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class ScaleEstimate:
    """Amplitude à un horizon, pour une cellule."""

    horizon_ns: int
    robust_scale: float
    quantiles: dict[float, float]
    observations: int
    independent_clusters: int
    #: Écart entre les deux extrémités du chemin et l'amplitude parcourue : proche de 1
    #: pour un déplacement direct, proche de 0 pour un aller-retour.
    directional_efficiency: float


def robust_scale(x: np.ndarray) -> float:
    """Écart absolu médian normalisé.

    Préféré à l'écart-type : les rendements financiers ont des queues épaisses, et
    l'écart-type y est dominé par quelques observations extrêmes.
    """
    if x.size == 0:
        return float("nan")
    med = np.median(x)
    return float(MAD_TO_SIGMA * np.median(np.abs(x - med)))


def _displacements(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    horizon_ns: int,
    step: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Déplacements P(t+h) - P(t) et indices de départ retenus.

    Les fenêtres se chevauchent : le point estimé reste consistant, mais toute mesure
    d'incertitude doit passer par un rééchantillonnage par blocs (cf. bootstrap.py).
    """
    if timestamps_ns.size < 2:
        return np.empty(0), np.empty(0, dtype=np.int64)

    starts = np.arange(0, timestamps_ns.size, max(1, step), dtype=np.int64)
    targets = timestamps_ns[starts] + horizon_ns
    ends = np.searchsorted(timestamps_ns, targets, side="left")

    valid = ends < timestamps_ns.size
    starts, ends = starts[valid], ends[valid]
    if starts.size == 0:
        return np.empty(0), np.empty(0, dtype=np.int64)

    return prices[ends] - prices[starts], starts


def _path_efficiency(
    prices: np.ndarray, starts: np.ndarray, horizon_ns: int, timestamps_ns: np.ndarray
) -> float:
    """Rapport entre déplacement net et chemin parcouru, moyenné sur les fenêtres.

    Diagnostic : une efficacité élevée signale un marché directionnel, une efficacité
    basse un marché qui oscille. Deux marchés de même amplitude et d'efficacité
    différente n'offrent pas les mêmes possibilités.
    """
    if starts.size == 0:
        return float("nan")
    sample = starts[:: max(1, starts.size // 500)]
    ratios = []
    for s in sample:
        e = int(np.searchsorted(timestamps_ns, timestamps_ns[s] + horizon_ns, side="left"))
        if e <= s or e >= prices.size:
            continue
        segment = prices[s : e + 1]
        travelled = float(np.abs(np.diff(segment)).sum())
        if travelled > 0:
            ratios.append(abs(float(segment[-1] - segment[0])) / travelled)
    return float(np.mean(ratios)) if ratios else float("nan")


def realized_scale(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    horizon_ns: int,
    cluster_ids: np.ndarray,
    quantiles: tuple[float, ...] = (0.5, 0.75, 0.9, 0.95),
    step: int = 1,
) -> ScaleEstimate:
    """Amplitude empirique à l'horizon donné.

    `cluster_ids` identifie les blocs indépendants (typiquement la séance). Il n'entre pas
    dans le point estimé mais conditionne toute mesure d'incertitude en aval.
    """
    disp, starts = _displacements(timestamps_ns, prices, horizon_ns, step)
    if disp.size == 0:
        return ScaleEstimate(horizon_ns, float("nan"), {}, 0, 0, float("nan"))

    abs_disp = np.abs(disp)
    return ScaleEstimate(
        horizon_ns=horizon_ns,
        robust_scale=robust_scale(disp),
        quantiles={q: float(np.quantile(abs_disp, q)) for q in quantiles},
        observations=int(disp.size),
        independent_clusters=int(np.unique(cluster_ids[starts]).size),
        directional_efficiency=_path_efficiency(prices, starts, horizon_ns, timestamps_ns),
    )


def displacement_sample(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    horizon_ns: int,
    cluster_ids: np.ndarray,
    step: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Déplacements bruts et leur bloc d'appartenance.

    Exposé pour que le rééchantillonnage par blocs puisse recalculer conjointement
    l'amplitude et le coût sur les mêmes blocs tirés — les deux partagent la séance, et
    les traiter séparément casserait cette dépendance.
    """
    disp, starts = _displacements(timestamps_ns, prices, horizon_ns, step)
    if disp.size == 0:
        return np.empty(0), np.empty(0, dtype=cluster_ids.dtype)
    return disp, cluster_ids[starts]


def sqrt_time_diagnostic(estimates: list[ScaleEstimate]) -> list[dict[str, float]]:
    """Écart à la loi en racine carrée du temps — **contrôle, jamais contrainte**.

    Un rapport nettement supérieur à 1 suggère de la tendance ou des sauts ; nettement
    inférieur, un retour à la moyenne. Dans les deux cas, extrapoler en `sqrt(h)` depuis
    un horizon court fausserait la lecture, et c'est précisément ce que ce diagnostic
    sert à repérer.
    """
    usable = [e for e in estimates if np.isfinite(e.robust_scale) and e.robust_scale > 0]
    if len(usable) < 2:
        return []

    ref = usable[0]
    out = []
    for e in usable:
        expected = ref.robust_scale * np.sqrt(e.horizon_ns / ref.horizon_ns)
        out.append(
            {
                "horizon_ns": float(e.horizon_ns),
                "observed": e.robust_scale,
                "sqrt_time_expected": float(expected),
                "ratio": float(e.robust_scale / expected),
            }
        )
    return out
