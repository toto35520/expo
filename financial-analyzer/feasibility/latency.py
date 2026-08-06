"""Q19 phase 0 — borne supérieure de ce qu'un signal pourrait capturer.

Principe : pour la classe d'événements que vise la famille microstructure — déplacements
rapides — on mesure quelle part du mouvement est **déjà survenue** au moment où l'on
aurait pu agir. Le mouvement résiduel borne par le haut ce que **n'importe quel** signal
détectant cet événement peut réaliser : on ne capture pas ce qui a déjà eu lieu.

Ce calcul ne dépend d'aucune définition de signal, d'aucune étiquette et d'aucun modèle.
C'est le seul test capable de rendre un verdict négatif conclusif avant toute
construction (ADR-100, asymétrie des conclusions).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class LatencyVerdict(str, Enum):
    LATENCY_VIABLE = "LATENCY_VIABLE"
    LATENCY_NON_VIABLE = "LATENCY_NON_VIABLE"
    LATENCY_REGIME_DEPENDENT = "LATENCY_REGIME_DEPENDENT"
    LATENCY_INDETERMINATE = "LATENCY_INDETERMINATE"


@dataclass(frozen=True)
class Phase0Result:
    """Borne supérieure du mouvement exploitable après latence."""

    evaluation_horizon_ns: int
    events: int
    independent_clusters: int
    #: Part du déplacement total déjà réalisée à t0 + L, moyennée sur la distribution de latence.
    consumed_fraction_p50: float
    consumed_fraction_p90: float
    #: Déplacement restant après latence, en unité de prix, dans le sens de l'événement.
    residual_p50: float
    residual_p25: float
    #: Résiduel net des coûts. C'est la grandeur qui décide.
    residual_net_p50: float
    residual_net_p25: float
    verdict: LatencyVerdict


def detect_price_events(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    window_ns: int,
    quantile: float = 0.99,
) -> tuple[np.ndarray, np.ndarray]:
    """Événements définis par le **prix seul** : déplacements extrêmes sur une fenêtre courte.

    Aucune référence au carnet, au volume ou à un motif. C'est ce qui rend le test
    indépendant de toute hypothèse de signal — et donc capable de conclure négativement.

    Renvoie les indices de départ et le signe du déplacement.
    """
    ends = np.searchsorted(timestamps_ns, timestamps_ns + window_ns, side="left")
    valid = ends < timestamps_ns.size
    idx = np.nonzero(valid)[0]
    if idx.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0)

    moves = prices[ends[idx]] - prices[idx]
    threshold = np.quantile(np.abs(moves), quantile)
    selected = idx[np.abs(moves) >= threshold]
    if selected.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0)

    # Un même épisode déclenche plusieurs ticks consécutifs : on ne garde que le premier
    # de chaque grappe, sans quoi un seul mouvement serait compté des dizaines de fois.
    keep = np.concatenate(([True], np.diff(timestamps_ns[selected]) > window_ns))
    selected = selected[keep]
    return selected, np.sign(prices[ends[selected]] - prices[selected])


def phase0_residual(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    cluster_ids: np.ndarray,
    event_starts: np.ndarray,
    event_signs: np.ndarray,
    latency_samples_ns: np.ndarray,
    evaluation_horizon_ns: int,
    round_trip_cost: float,
    min_clusters: int = 20,
    rng: np.random.Generator | None = None,
) -> Phase0Result:
    """Part du mouvement consommée par la latence, et résiduel net de coûts.

    `latency_samples_ns` est la distribution **conditionnelle** de latence mesurée dans
    les états où le signal se déclencherait (ADR-102). Utiliser une latence médiane
    globale sous-estimerait systématiquement le délai subi au moment utile.
    """
    rng = rng or np.random.default_rng(0)

    if event_starts.size == 0 or latency_samples_ns.size == 0:
        return Phase0Result(
            evaluation_horizon_ns, 0, 0,
            *(float("nan"),) * 6,
            LatencyVerdict.LATENCY_INDETERMINATE,
        )

    consumed: list[float] = []
    residual: list[float] = []

    drawn = rng.choice(latency_samples_ns, size=event_starts.size, replace=True)
    for start, sign, lat in zip(event_starts, event_signs, drawn):
        t0 = timestamps_ns[start]
        i_lat = int(np.searchsorted(timestamps_ns, t0 + lat, side="left"))
        i_end = int(np.searchsorted(timestamps_ns, t0 + evaluation_horizon_ns, side="left"))
        if i_end >= timestamps_ns.size:
            continue
        if i_lat >= i_end:
            # La latence dépasse la fenêtre d'évaluation : au moment où l'on pourrait
            # agir, il n'y a plus rien à capturer. Écarter ces cas ne garderait que les
            # événements favorables et transformerait un résultat conclusif en
            # indétermination.
            consumed.append(1.0)
            residual.append(0.0)
            continue

        total = sign * (prices[i_end] - prices[start])
        after_latency = sign * (prices[i_end] - prices[i_lat])
        if total <= 0:
            # Le mouvement s'est retourné avant la fin de la fenêtre : l'événement
            # n'offrait rien à capturer dans son propre sens. Conservé, car l'exclure
            # ne garderait que les cas favorables.
            consumed.append(1.0)
            residual.append(after_latency)
            continue

        consumed.append(float(np.clip((total - after_latency) / total, 0.0, 1.0)))
        residual.append(float(after_latency))

    if not residual:
        return Phase0Result(
            evaluation_horizon_ns, 0, 0,
            *(float("nan"),) * 6,
            LatencyVerdict.LATENCY_INDETERMINATE,
        )

    consumed_arr = np.asarray(consumed)
    residual_arr = np.asarray(residual)
    net_arr = residual_arr - round_trip_cost
    clusters = int(np.unique(cluster_ids[event_starts]).size)

    if clusters < min_clusters:
        verdict = LatencyVerdict.LATENCY_INDETERMINATE
    elif float(np.median(net_arr)) <= 0.0:
        # Conclusif : la borne supérieure elle-même ne couvre pas les frais.
        verdict = LatencyVerdict.LATENCY_NON_VIABLE
    else:
        verdict = LatencyVerdict.LATENCY_VIABLE

    return Phase0Result(
        evaluation_horizon_ns=evaluation_horizon_ns,
        events=int(residual_arr.size),
        independent_clusters=clusters,
        consumed_fraction_p50=float(np.median(consumed_arr)),
        consumed_fraction_p90=float(np.quantile(consumed_arr, 0.90)),
        residual_p50=float(np.median(residual_arr)),
        residual_p25=float(np.quantile(residual_arr, 0.25)),
        residual_net_p50=float(np.median(net_arr)),
        residual_net_p25=float(np.quantile(net_arr, 0.25)),
        verdict=verdict,
    )


def evaluation_latency_percentile(
    latency_samples_ns: np.ndarray, percentile: float = 0.95
) -> float:
    """Centile de latence retenu pour le gate.

    À calculer sur les échantillons **conditionnels à la rafale**, pas sur l'ensemble :
    la latence se dégrade précisément quand les signaux se déclenchent.
    """
    if latency_samples_ns.size == 0:
        return float("nan")
    return float(np.quantile(latency_samples_ns, percentile))
