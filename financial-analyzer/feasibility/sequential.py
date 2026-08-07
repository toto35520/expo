"""Inférence séquentielle valide sous arrêt optionnel (Q59-A).

Un intervalle de confiance classique suppose que la taille d'échantillon a été fixée
indépendamment des données. Si la décision d'arrêter dépend de l'intervalle observé, la
couverture nominale n'est **plus garantie** — ce n'est pas un biais à signaler, c'est une
garantie qui n'existe plus.

Deux modes seulement sont autorisés :

    FIXED_HORIZON   la durée est gelée avant la première observation ; l'inférence
                    conventionnelle s'applique à la fin, et la largeur d'intervalle
                    ne peut **jamais** déclencher l'arrêt ;

    ANYTIME_VALID   l'arrêt peut dépendre de l'incertitude, parce que la garantie est
                    simultanée dans le temps :

                        P( ∀n, θ ∈ CS_n ) ≥ 1 − α

Toute autre combinaison — arrêt dépendant des données avec intervalle classique —
produit `SEQUENTIAL_INFERENCE_INVALID`, jamais un résultat assorti d'une réserve.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np


class SequentialError(ValueError):
    """Paramètre d'inférence absent, incohérent, ou déclaré trop tard."""


class InferenceMode(str, Enum):
    #: Durée gelée avant la première observation. Inférence conventionnelle à la fin.
    FIXED_HORIZON = "FIXED_HORIZON"
    #: Arrêt autorisé à un temps aléatoire ; garantie simultanée dans le temps.
    ANYTIME_VALID = "ANYTIME_VALID"


class InferenceValidity(str, Enum):
    VALID = "VALID"
    #: Arrêt dépendant des données sous inférence classique. Aucun résultat publiable.
    SEQUENTIAL_INFERENCE_INVALID = "SEQUENTIAL_INFERENCE_INVALID"


class ClusterWeighting(str, Enum):
    """Ce que la séquence de confiance estime réellement.

    La distinction n'est pas cosmétique : une rafale de 300 cotations et un bloc calme
    de 12 cotations ne pèsent pas pareil selon la convention, et les deux quantités
    répondent à des questions différentes.
    """

    #: Chaque grappe pèse également. C'est l'estimande de la séquence de confiance :
    #: l'unité d'indépendance est la grappe, donc l'unité de poids aussi.
    EQUAL_PER_CLUSTER = "EQUAL_PER_CLUSTER"
    #: Chaque observation pèse également. C'est le quantile empirique usuel — descriptif,
    #: sans garantie séquentielle.
    EQUAL_PER_OBSERVATION = "EQUAL_PER_OBSERVATION"


# ------------------------------------------------- séquence de confiance sous-gaussienne


def normal_mixture_radius(
    n: int, alpha: float, rho: float, sigma_squared: float = 0.25
) -> float:
    """Rayon du mélange normal de Robbins — borne **uniforme dans le temps**.

    Pour des incréments centrés σ-sous-gaussiens et `V_n = n σ²` :

        P( ∃n ≥ 1 : |S_n| ≥ √( 2 (V_n + ρ) · log( √((V_n + ρ)/ρ) / α ) ) ) ≤ α

    `ρ` fixe l'instant où la frontière est la plus serrée — de l'ordre de `V ≈ ρ`. Il est
    **déclaré à l'avance** : le choisir après coup reviendrait à optimiser la frontière
    contre les données qu'elle est censée borner.

    `σ² = 1/4` est la borne de Hoeffding pour des variables dans [0, 1]. Elle est
    volontairement conservatrice — les fractions intra-grappe ont une variance bien
    moindre — mais elle est valide sans hypothèse supplémentaire.
    """
    if n <= 0:
        return float("inf")
    if not 0.0 < alpha < 1.0:
        raise SequentialError(f"α = {alpha} hors de ]0, 1[.")
    if rho <= 0.0:
        raise SequentialError("ρ doit être strictement positif et déclaré à l'avance.")

    v = n * sigma_squared
    boundary = math.sqrt(2.0 * (v + rho) * math.log(math.sqrt((v + rho) / rho) / alpha))
    return boundary / n


def rho_for_target(target_clusters: int, sigma_squared: float = 0.25) -> float:
    """`ρ` recommandé pour une taille de campagne visée, à déclarer avec la politique.

    La frontière est la plus serrée autour de `V ≈ ρ` ; viser la taille attendue de la
    campagne place la meilleure précision là où la décision se prendra.
    """
    if target_clusters <= 0:
        raise SequentialError("la taille visée doit être strictement positive")
    return target_clusters * sigma_squared


@dataclass(frozen=True)
class ConfidenceSequence:
    """Intervalle valide **à tout instant** pour une proportion au niveau des grappes."""

    n_clusters: int
    n_observations: int
    estimate: float
    lower: float
    upper: float
    alpha: float
    rho: float
    weighting: ClusterWeighting = ClusterWeighting.EQUAL_PER_CLUSTER

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def excludes(self, value: float) -> bool:
        return value < self.lower or value > self.upper


def cluster_fractions(
    values: Sequence[float], clusters: Sequence[str], threshold: float
) -> tuple[np.ndarray, int]:
    """Fraction d'observations sous le seuil, **par grappe**.

    Réduire chaque grappe à une valeur unique est ce qui rend le nombre de grappes — et
    non le nombre d'observations — la taille d'échantillon de l'inférence.
    """
    by_cluster: dict[str, list[float]] = {}
    for v, c in zip(values, clusters):
        by_cluster.setdefault(c, []).append(float(v))
    fractions = np.array(
        [float(np.mean(np.asarray(vs) <= threshold)) for vs in by_cluster.values()]
    )
    return fractions, sum(len(v) for v in by_cluster.values())


def threshold_confidence_sequence(
    values: Sequence[float],
    clusters: Sequence[str],
    threshold: float,
    alpha: float,
    rho: float,
) -> ConfidenceSequence:
    """Séquence de confiance pour `F(seuil)` — la proportion sous un seuil **fixe**.

    Le choix du seuil fixe est ce qui rend la construction simple et valide : aucune
    inversion sur une grille de quantiles, donc aucune correction d'union à payer. Or la
    décision d'exclusion porte précisément sur un seuil fixe — la latence admissible.
    """
    fractions, n_obs = cluster_fractions(values, clusters, threshold)
    n = fractions.size
    if n == 0:
        return ConfidenceSequence(0, 0, float("nan"), 0.0, 1.0, alpha, rho)

    estimate = float(fractions.mean())
    radius = normal_mixture_radius(n, alpha, rho)
    return ConfidenceSequence(
        n_clusters=n,
        n_observations=n_obs,
        estimate=estimate,
        lower=max(0.0, estimate - radius),
        upper=min(1.0, estimate + radius),
        alpha=alpha,
        rho=rho,
    )


class ThresholdVerdict(str, Enum):
    """Position du quantile par rapport au seuil, établie de façon séquentiellement
    valide."""

    #: `F(seuil) < q` — le quantile dépasse le seuil.
    QUANTILE_ABOVE_THRESHOLD = "QUANTILE_ABOVE_THRESHOLD"
    #: `F(seuil) > q` — le quantile est sous le seuil.
    QUANTILE_BELOW_THRESHOLD = "QUANTILE_BELOW_THRESHOLD"
    #: La séquence n'a pas encore séparé. Continuer.
    UNDETERMINED = "UNDETERMINED"


def clusters_for_separation(
    margin: float, alpha: float, rho: float, max_clusters: int = 10_000_000
) -> int | None:
    """Nombre de grappes nécessaires pour qu'une séquence de largeur `margin` sépare.

    À déclarer **avant** la campagne : c'est ce qui rend un horizon gelé réaliste plutôt
    qu'espéré. La frontière sous-gaussienne est volontairement conservatrice, et le coût
    est très asymétrique :

    - **exclure** demande peu de grappes, parce que la marge à franchir est grande dès
      que le quantile dépasse nettement le seuil ;
    - **conclure « non exclu »** demande une marge fine, donc un échantillon bien plus
      grand — ce qui est cohérent avec le statut des deux verdicts : l'exclusion conclut,
      la non-exclusion ne fait qu'autoriser à continuer de chercher.
    """
    if margin <= 0.0:
        return None
    n = 1
    while n <= max_clusters:
        if normal_mixture_radius(n, alpha, rho) <= margin:
            return n
        n = int(n * 1.2) + 1
    return None


def threshold_verdict(cs: ConfidenceSequence, quantile: float) -> ThresholdVerdict:
    """Compare la séquence de confiance au niveau de quantile visé.

    `Q_q > seuil` équivaut à `F(seuil) < q`. Décider sur la séquence plutôt que sur le
    quantile empirique est ce qui autorise l'arrêt au moment où elle sépare.
    """
    if cs.n_clusters == 0:
        return ThresholdVerdict.UNDETERMINED
    if cs.upper < quantile:
        return ThresholdVerdict.QUANTILE_ABOVE_THRESHOLD
    if cs.lower > quantile:
        return ThresholdVerdict.QUANTILE_BELOW_THRESHOLD
    return ThresholdVerdict.UNDETERMINED


# ------------------------------------------------------- inférence à horizon fixe


def fixed_horizon_interval(
    values: Sequence[float],
    clusters: Sequence[str],
    threshold: float,
    alpha: float,
) -> ConfidenceSequence:
    """Intervalle de Hoeffding classique, valide **uniquement** à taille fixée d'avance.

    Il est plus étroit que la séquence de confiance : c'est exactement le gain qu'on
    échange contre le droit d'arrêter quand on veut. L'utiliser après un arrêt dépendant
    des données rend la garantie fausse, pas seulement optimiste.
    """
    fractions, n_obs = cluster_fractions(values, clusters, threshold)
    n = fractions.size
    if n == 0:
        return ConfidenceSequence(0, 0, float("nan"), 0.0, 1.0, alpha, float("nan"))
    estimate = float(fractions.mean())
    radius = math.sqrt(math.log(2.0 / alpha) / (2.0 * n))
    return ConfidenceSequence(
        n_clusters=n, n_observations=n_obs, estimate=estimate,
        lower=max(0.0, estimate - radius), upper=min(1.0, estimate + radius),
        alpha=alpha, rho=float("nan"),
    )


def validity(
    mode: InferenceMode, stop_was_data_dependent: bool
) -> InferenceValidity:
    """Un arrêt dépendant des données sous inférence classique invalide le résultat.

    Ce n'est pas une réserve à publier à côté du chiffre : la procédure ne fournit plus
    la garantie qu'elle annonce, donc il n'y a pas de chiffre à publier.
    """
    if mode is InferenceMode.FIXED_HORIZON and stop_was_data_dependent:
        return InferenceValidity.SEQUENTIAL_INFERENCE_INVALID
    return InferenceValidity.VALID


def interval_for_mode(
    mode: InferenceMode,
    values: Sequence[float],
    clusters: Sequence[str],
    threshold: float,
    alpha: float,
    rho: float | None,
) -> ConfidenceSequence:
    """Choisit la méthode imposée par le mode déclaré — jamais l'inverse."""
    if mode is InferenceMode.ANYTIME_VALID:
        if rho is None:
            raise SequentialError(
                "ANYTIME_VALID exige un ρ déclaré à l'avance : le choisir après coup "
                "reviendrait à ajuster la frontière contre les données qu'elle borne."
            )
        return threshold_confidence_sequence(values, clusters, threshold, alpha, rho)
    return fixed_horizon_interval(values, clusters, threshold, alpha)
