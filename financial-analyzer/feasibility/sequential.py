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


class Estimand(str, Enum):
    """**Quelle question** la séquence de confiance répond — indépendamment de la méthode
    employée pour traiter la dépendance.

    C'est une séparation fondamentale : le regroupement en grappes sert à gérer la
    variance, il ne doit **jamais** changer silencieusement la population cible.

        estimand  ≠  méthode de variance

    L'écart n'est pas cosmétique. Deux rafales — l'une de 10 événements tous sous le
    seuil, l'autre de 1 000 événements à moitié sous le seuil — donnent :

        CDF par grappe      (1 + 0,5) / 2      = 0,75
        CDF par événement   510 / 1 010        ≈ 0,505

    Les deux sont justes. Elles ne répondent pas à la même question.
    """

    #: « Quelle latence subit un événement déclencheur tiré dans la population
    #: opérationnelle ? » — grandeur naturelle d'une décision par événement.
    EVENT_WEIGHTED = "EVENT_WEIGHTED"
    #: « Quelle est la performance d'un épisode de rafale typique ? » — pertinent si un
    #: moteur produit au plus une décision par rafale.
    CLUSTER_WEIGHTED = "CLUSTER_WEIGHTED"
    #: « Quelle est la performance d'une séance typique ? »
    SESSION_WEIGHTED = "SESSION_WEIGHTED"


class SequentialQualification(str, Enum):
    """Statut des **hypothèses** de la procédure séquentielle.

    Orthogonal à la qualité de la mesure : une excellente mesure peut porter une
    inférence séquentielle non qualifiée.
    """

    SEQUENTIAL_VALID = "SEQUENTIAL_VALID"
    #: Dépendance ou non-stationnarité non écartées. La garantie anytime-valid ne peut
    #: pas être revendiquée ; le protocole retombe sur l'horizon fixe.
    SEQUENTIAL_ASSUMPTIONS_UNVERIFIED = "SEQUENTIAL_ASSUMPTIONS_UNVERIFIED"
    SEQUENTIAL_INVALID = "SEQUENTIAL_INVALID"


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
    """Intervalle valide **à tout instant**, pour un estimande explicitement nommé."""

    n_clusters: int
    n_observations: int
    estimate: float
    lower: float
    upper: float
    alpha: float
    rho: float
    estimand: Estimand = Estimand.CLUSTER_WEIGHTED
    qualification: SequentialQualification = (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    )

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def excludes(self, value: float) -> bool:
        return value < self.lower or value > self.upper

    @property
    def anytime_valid_claimable(self) -> bool:
        """Le label ne s'accorde qu'aux cellules dont les hypothèses tiennent."""
        return self.qualification is SequentialQualification.SEQUENTIAL_VALID


def cluster_fractions(
    values: Sequence[float], clusters: Sequence[str], threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    """Fraction sous le seuil et effectif, **par grappe**.

    La grappe est l'unité d'indépendance, donc l'unité d'échantillon de l'inférence.
    Elle n'est pas pour autant l'unité de **pondération** : celle-ci relève de
    l'estimande, choisi séparément.
    """
    by_cluster: dict[str, list[float]] = {}
    for v, c in zip(values, clusters):
        by_cluster.setdefault(c, []).append(float(v))
    fractions = np.array(
        [float(np.mean(np.asarray(vs) <= threshold)) for vs in by_cluster.values()]
    )
    sizes = np.array([len(vs) for vs in by_cluster.values()], dtype=float)
    return fractions, sizes


def event_weighted_fraction(
    values: Sequence[float], clusters: Sequence[str], threshold: float
) -> float:
    """CDF par événement — estimation ponctuelle descriptive, sans garantie séquentielle."""
    fractions, sizes = cluster_fractions(values, clusters, threshold)
    total = sizes.sum()
    return float((fractions * sizes).sum() / total) if total else float("nan")


def threshold_confidence_sequence(
    values: Sequence[float],
    clusters: Sequence[str],
    threshold: float,
    alpha: float,
    rho: float,
    estimand: Estimand = Estimand.CLUSTER_WEIGHTED,
    max_cluster_size: int | None = None,
    qualification: SequentialQualification = (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    ),
) -> ConfidenceSequence:
    """Séquence de confiance pour `F(seuil)` — la proportion sous un seuil **fixe**.

    Le seuil fixe est ce qui rend la construction simple et valide : aucune inversion
    sur une grille de quantiles, donc aucune correction d'union à payer. La décision
    d'exclusion porte précisément sur un seuil fixe.

    Sous `CLUSTER_WEIGHTED`, chaque grappe pèse également. Sous `EVENT_WEIGHTED`, la
    grappe reste l'unité d'indépendance mais pèse proportionnellement à son effectif :
    l'estimande devient un rapport de moyennes, et la borne exige un plafond de taille
    de grappe **déclaré à l'avance** pour que la variable reste bornée.
    """
    fractions, sizes = cluster_fractions(values, clusters, threshold)
    n = fractions.size
    n_obs = int(sizes.sum())
    if n == 0:
        return ConfidenceSequence(0, 0, float("nan"), 0.0, 1.0, alpha, rho,
                                  estimand, qualification)

    radius = normal_mixture_radius(n, alpha, rho)

    if estimand is Estimand.EVENT_WEIGHTED:
        if max_cluster_size is None:
            raise SequentialError(
                "L'estimande par événement exige un plafond de taille de grappe déclaré "
                "à l'avance : sans lui la variable n'est pas bornée, et la frontière "
                "sous-gaussienne ne s'applique pas."
            )
        if sizes.max() > max_cluster_size:
            raise SequentialError(
                f"Grappe de {int(sizes.max())} observations au-dessus du plafond déclaré "
                f"({max_cluster_size}). L'adapter après coup reviendrait à régler la "
                "borne contre les données qu'elle borne."
            )
        y = fractions * sizes / max_cluster_size
        m = sizes / max_cluster_size
        mean_m = float(m.mean())
        if mean_m <= 0.0:
            return ConfidenceSequence(n, n_obs, float("nan"), 0.0, 1.0, alpha, rho,
                                      estimand, qualification)
        mean_y = float(y.mean())
        estimate = mean_y / mean_m
        lower = (mean_y - radius) / mean_m
        upper = (mean_y + radius) / mean_m
    else:
        estimate = float(fractions.mean())
        lower = estimate - radius
        upper = estimate + radius

    return ConfidenceSequence(
        n_clusters=n,
        n_observations=n_obs,
        estimate=estimate,
        lower=max(0.0, lower),
        upper=min(1.0, upper),
        alpha=alpha,
        rho=rho,
        estimand=estimand,
        qualification=qualification,
    )


# ------------------------------------------- qualification des hypothèses de grappe


def autocorrelation(x: Sequence[float], lag: int = 1) -> float:
    """Autocorrélation d'ordre `lag`, calculée au niveau des grappes."""
    a = np.asarray(x, dtype=float)
    if a.size <= lag + 1:
        return float("nan")
    a = a - a.mean()
    denominator = float((a * a).sum())
    if denominator == 0.0:
        return 0.0
    return float((a[:-lag] * a[lag:]).sum() / denominator)


@dataclass(frozen=True)
class ClusterQualification:
    """Ce qui doit être publié **avant** qu'une grappe entre dans l'inférence.

    Découper une série temporelle en blocs ne rend pas les blocs indépendants : deux
    blocs consécutifs peuvent partager charge processeur, file persistante, régime de
    marché, connexion, événement macro ou volatilité. Une séquence valide sous hypothèse
    de martingale perd sa garantie si cette hypothèse est fausse — et de bonnes
    simulations i.i.d. ne la rétablissent pas.
    """

    cluster_definition: str
    reset_rule: str
    minimum_gap_ns: int
    n_clusters: int
    size_p50: float
    size_p95: float
    duration_p50_ns: float
    acf1_fraction: float
    acf1_value: float
    acf1_load: float
    stationarity_checked: bool
    max_abs_acf_tolerated: float = 0.20

    @property
    def dependence_within_tolerance(self) -> bool:
        acfs = (self.acf1_fraction, self.acf1_value, self.acf1_load)
        return all(
            not math.isnan(a) and abs(a) <= self.max_abs_acf_tolerated for a in acfs
        )

    def qualify(self) -> SequentialQualification:
        """Accorde — ou non — le droit de revendiquer `ANYTIME_VALID`.

        Le refus ne perd pas la cellule : elle repasse au protocole à horizon fixe.
        Conserver la revendication séquentielle serait, lui, émettre une garantie sans
        fondement.
        """
        if self.n_clusters < 2:
            return SequentialQualification.SEQUENTIAL_INVALID
        if not self.stationarity_checked or not self.dependence_within_tolerance:
            return SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
        return SequentialQualification.SEQUENTIAL_VALID


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
    fractions, sizes = cluster_fractions(values, clusters, threshold)
    n = fractions.size
    n_obs = int(sizes.sum())
    if n == 0:
        return ConfidenceSequence(0, 0, float("nan"), 0.0, 1.0, alpha, float("nan"))
    estimate = float(fractions.mean())
    radius = math.sqrt(math.log(2.0 / alpha) / (2.0 * n))
    return ConfidenceSequence(
        n_clusters=n, n_observations=n_obs, estimate=estimate,
        lower=max(0.0, estimate - radius), upper=min(1.0, estimate + radius),
        alpha=alpha, rho=float("nan"),
        qualification=SequentialQualification.SEQUENTIAL_VALID,
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
    estimand: Estimand = Estimand.CLUSTER_WEIGHTED,
    max_cluster_size: int | None = None,
    clusters_qualified: SequentialQualification = (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    ),
) -> ConfidenceSequence:
    """Choisit la méthode imposée par le mode déclaré — jamais l'inverse.

    `ANYTIME_VALID` n'est honoré que sur une cellule dont la dépendance et la stabilité
    sont défendables. Sinon la cellule **retombe sur l'horizon fixe** plutôt que
    d'émettre une garantie invalide : elle n'est pas perdue, elle change de protocole.
    """
    if mode is InferenceMode.ANYTIME_VALID:
        if rho is None:
            raise SequentialError(
                "ANYTIME_VALID exige un ρ déclaré à l'avance : le choisir après coup "
                "reviendrait à ajuster la frontière contre les données qu'elle borne."
            )
        if clusters_qualified is SequentialQualification.SEQUENTIAL_VALID:
            return threshold_confidence_sequence(
                values, clusters, threshold, alpha, rho,
                estimand=estimand, max_cluster_size=max_cluster_size,
                qualification=clusters_qualified,
            )
        fallback = fixed_horizon_interval(values, clusters, threshold, alpha)
        return ConfidenceSequence(
            **{**fallback.__dict__, "estimand": estimand,
               "qualification": clusters_qualified}
        )
    return fixed_horizon_interval(values, clusters, threshold, alpha)
