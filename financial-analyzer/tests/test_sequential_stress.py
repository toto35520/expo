"""Tests de la séquence de confiance **hors de ses hypothèses** (§26-27).

Ces tests ne démontrent **pas** la validité de la procédure. Ils délimitent son domaine de
sécurité : ils montrent comment elle se dégrade lorsque indépendance, stationnarité ou
calibration sont violées.

La distinction est nécessaire. `0 franchissement / 800 réplications` sous hypothèses i.i.d.
est encourageant, mais la borne supérieure du taux réel reste non nulle, et surtout la
garantie théorique dépend de ses hypothèses — pas de la qualité des simulations qui les
respectent.

    tests sous hypothèses      → conformité de l'implémentation à la théorie
    stress hors hypothèses     → domaine de sécurité, jamais une preuve
"""

from __future__ import annotations

import numpy as np
import pytest

from feasibility.sequential import (
    Estimand,
    SequentialQualification,
    autocorrelation,
    clusters_for_separation,
    normal_mixture_radius,
    rho_for_target,
    threshold_confidence_sequence,
)

ALPHA = 0.05


def breach_rate(series: np.ndarray, truth: float, radii: np.ndarray,
                checks: np.ndarray) -> float:
    """Part des réplications où la séquence exclut la vraie valeur à un temps d'arrêt."""
    running = np.cumsum(series, axis=1) / np.arange(1, series.shape[1] + 1)
    deviation = np.abs(running[:, checks - 1] - truth)
    return float((deviation > radii).any(axis=1).mean())


def radii_for(checks: np.ndarray, rho: float) -> np.ndarray:
    return np.array([normal_mixture_radius(int(n), ALPHA, rho) for n in checks])


# ============================================= grappes très inégales


def test_wildly_unequal_cluster_sizes_do_not_break_the_cluster_estimand():
    """Sous `CLUSTER_WEIGHTED`, chaque grappe pèse un, quelle que soit sa taille : la
    borne ne dépend que de leur nombre."""
    values, clusters = [], []
    for i in range(200):
        size = 10 if i % 2 else 400          # les deux tailles peuvent atteindre 0,9 exactement
        below = int(size * 0.9)
        values += [5.0] * below + [500.0] * (size - below)
        clusters += [f"C{i}"] * size
    cs = threshold_confidence_sequence(values, clusters, 100.0, ALPHA,
                                       rho_for_target(200))
    assert cs.n_clusters == 200
    assert cs.lower <= 0.9 <= cs.upper


def test_unequal_sizes_move_the_event_weighted_estimand_but_not_the_cluster_one():
    """Le déplacement n'est pas un défaut : ce sont deux questions différentes."""
    values, clusters = [], []
    for i in range(100):
        size = 5 if i % 2 else 500
        below = size if i % 2 else size // 2
        values += [5.0] * below + [500.0] * (size - below)
        clusters += [f"C{i}"] * size
    by_cluster = threshold_confidence_sequence(values, clusters, 100.0, ALPHA,
                                               rho_for_target(100))
    by_event = threshold_confidence_sequence(values, clusters, 100.0, ALPHA,
                                             rho_for_target(100),
                                             estimand=Estimand.EVENT_WEIGHTED,
                                             max_cluster_size=500)
    assert abs(by_cluster.estimate - by_event.estimate) > 0.15


# ============================================= masse près du seuil, queues extrêmes


def test_mass_sitting_exactly_on_the_threshold_stays_undetermined_rather_than_flipping():
    values = [100.0] * 4_000
    clusters = [f"C{i // 20}" for i in range(4_000)]
    cs = threshold_confidence_sequence(values, clusters, 100.0, ALPHA,
                                       rho_for_target(200))
    assert cs.estimate == 1.0
    assert cs.lower < 1.0          # la borne ne prétend jamais à la certitude


def test_extreme_tails_do_not_affect_a_threshold_indicator():
    """L'indicateur est borné par construction : une queue extrême ne le déstabilise pas."""
    modest = [5.0] * 900 + [500.0] * 100
    extreme = [5.0] * 900 + [1e12] * 100
    clusters = [f"C{i // 10}" for i in range(1_000)]
    a = threshold_confidence_sequence(modest, clusters, 100.0, ALPHA, rho_for_target(100))
    b = threshold_confidence_sequence(extreme, clusters, 100.0, ALPHA, rho_for_target(100))
    assert (a.lower, a.upper) == (b.lower, b.upper)


# ============================================= violations d'hypothèses


def test_positive_autocorrelation_degrades_coverage_and_the_diagnostic_sees_it():
    """Une dépendance persistante entre grappes fait perdre à la séquence la couverture
    qu'elle annonce. Le diagnostic d'autocorrélation est ce qui l'empêche d'être
    revendiquée."""
    rng = np.random.default_rng(0)
    reps, n = 400, 600
    rho_ar = 0.85
    truth = 0.90

    noise = rng.normal(0, 1, (reps, n))
    latent = np.zeros((reps, n))
    for t in range(1, n):
        latent[:, t] = rho_ar * latent[:, t - 1] + noise[:, t]
    series = (latent < np.quantile(latent, truth)).astype(float)

    checks = np.arange(20, n + 1, 20)
    rate = breach_rate(series, float(series.mean()), radii_for(checks, rho_for_target(300)),
                       checks)
    assert autocorrelation(series[0]) > 0.4
    assert rate > ALPHA            # le domaine de sécurité est bien franchi


def test_slow_drift_means_there_is_no_single_parameter_to_cover():
    """Si `F_t(L*)` dérive entre séances, une moyenne globale unique n'a pas
    nécessairement de sens — d'où des cellules homogènes et versionnées."""
    rng = np.random.default_rng(1)
    n = 800
    p = np.linspace(0.70, 0.99, n)
    series = (rng.random((300, n)) < p).astype(float)
    checks = np.arange(20, n + 1, 20)
    rate = breach_rate(series, 0.845, radii_for(checks, rho_for_target(400)), checks)
    assert rate > ALPHA


def test_a_regime_change_is_not_absorbed_silently():
    rng = np.random.default_rng(2)
    n = 800
    series = np.concatenate(
        [(rng.random((300, n // 2)) < 0.99).astype(float),
         (rng.random((300, n // 2)) < 0.60).astype(float)],
        axis=1,
    )
    checks = np.arange(20, n + 1, 20)
    rate = breach_rate(series, 0.795, radii_for(checks, rho_for_target(400)), checks)
    assert rate > ALPHA


def test_persistent_bursts_inflate_dependence_within_the_cluster_series():
    rng = np.random.default_rng(3)
    burst = np.repeat(rng.random(60) < 0.5, 20).astype(float)
    assert autocorrelation(burst) > 0.8


# ============================================= arrêt agressif sous hypothèses


def test_aggressive_stopping_stays_within_alpha_when_assumptions_hold():
    """Sous hypothèses, la couverture tient même en surveillant à chaque grappe."""
    rng = np.random.default_rng(4)
    reps, n, truth = 600, 500, 0.90
    series = (rng.random((reps, n)) < truth).astype(float)
    checks = np.arange(2, n + 1)              # surveillance à chaque pas
    assert breach_rate(series, truth, radii_for(checks, rho_for_target(250)),
                       checks) <= ALPHA


def test_oversampling_a_single_cluster_does_not_narrow_the_bound():
    """Répéter une grappe n'ajoute pas d'information indépendante."""
    values = [5.0] * 20
    one = threshold_confidence_sequence(values * 30, [f"C{i // 20}" for i in range(600)],
                                        100.0, ALPHA, rho_for_target(30))
    inflated = threshold_confidence_sequence(values * 30, ["C0"] * 600, 100.0, ALPHA,
                                             rho_for_target(30))
    assert inflated.width > one.width


# ============================================= ce que les simulations ne prouvent pas


def test_zero_breaches_never_proves_the_rate_is_zero():
    """Avec zéro violation sur 800 réplications, la borne supérieure du taux réel reste
    non nulle. Une simulation ne remplace pas la garantie théorique."""
    from feasibility.passive_campaign import clopper_pearson_upper

    bound = clopper_pearson_upper(0, 800, ALPHA)
    assert bound > 0.0
    assert bound < 0.005


def test_the_qualification_is_what_grants_the_label_not_the_simulation():
    """Garder la revendication séquentielle au motif que les simulations i.i.d. sont
    bonnes serait émettre une garantie sans fondement."""
    cs = threshold_confidence_sequence(
        [5.0] * 100, [f"C{i}" for i in range(100)], 100.0, ALPHA, rho_for_target(100)
    )
    assert cs.qualification is SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    assert not cs.anytime_valid_claimable


@pytest.mark.parametrize("margin,expected_order", [(0.40, 1), (0.10, 2), (0.03, 3)])
def test_the_separation_cost_grows_sharply_as_the_margin_narrows(margin, expected_order):
    n = clusters_for_separation(margin, ALPHA, rho_for_target(400))
    assert n is not None
    assert len(str(n)) >= expected_order
