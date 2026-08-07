"""Tests de l'inférence séquentielle (Q59-A).

Le point central n'est pas qu'un arrêt opportuniste rende l'intervalle « optimiste » :
c'est que la garantie de couverture disparaît. Les tests le vérifient par simulation,
pas seulement par construction.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from feasibility.sequential import (
    ClusterWeighting,
    InferenceMode,
    InferenceValidity,
    SequentialError,
    ThresholdVerdict,
    cluster_fractions,
    clusters_for_separation,
    fixed_horizon_interval,
    interval_for_mode,
    normal_mixture_radius,
    rho_for_target,
    threshold_confidence_sequence,
    threshold_verdict,
    validity,
)


def clustered(n_clusters: int, per_cluster: int, fraction_below: float,
              low=5.0, high=500.0):
    """Échantillon déterministe : `fraction_below` des valeurs sous le seuil de 100."""
    values, clusters = [], []
    k = round(per_cluster * fraction_below)
    for i in range(n_clusters):
        values += [low] * k + [high] * (per_cluster - k)
        clusters += [f"C{i}"] * per_cluster
    return values, clusters


# ============================================= la frontière


def test_the_sequential_radius_is_wider_than_the_fixed_horizon_one():
    """C'est exactement le prix du droit d'arrêter quand on veut."""
    for n in (30, 100, 400):
        cs = normal_mixture_radius(n, 0.05, rho_for_target(200))
        fh = math.sqrt(math.log(2 / 0.05) / (2 * n))
        assert cs > fh


def test_the_radius_shrinks_as_clusters_accumulate():
    rho = rho_for_target(200)
    radii = [normal_mixture_radius(n, 0.05, rho) for n in (20, 100, 500, 2000)]
    assert radii == sorted(radii, reverse=True)


def test_the_boundary_is_tightest_around_its_declared_target():
    """ρ place la meilleure précision là où la décision se prendra."""
    near = normal_mixture_radius(200, 0.05, rho_for_target(200))
    far = normal_mixture_radius(200, 0.05, rho_for_target(20_000))
    assert near < far


def test_the_boundary_refuses_an_undeclared_or_absurd_tuning():
    with pytest.raises(SequentialError, match="ρ"):
        normal_mixture_radius(100, 0.05, 0.0)
    with pytest.raises(SequentialError, match="α"):
        normal_mixture_radius(100, 1.5, 25.0)
    with pytest.raises(SequentialError):
        rho_for_target(0)


def test_no_clusters_yields_an_uninformative_interval():
    assert normal_mixture_radius(0, 0.05, 25.0) == float("inf")


# ============================================= couverture sous arrêt adverse


def test_the_sequence_keeps_its_coverage_under_adversarial_stopping():
    """Un adversaire qui surveille en continu et s'arrête dès que l'intervalle exclut la
    vraie valeur ne doit pas dépasser α."""
    rng = np.random.default_rng(0)
    p, alpha, n_max, reps = 0.90, 0.05, 800, 800
    rho = rho_for_target(400)
    checks = np.arange(20, n_max + 1, 20)

    x = (rng.random((reps, n_max)) < p).astype(float)
    running = np.cumsum(x, axis=1) / np.arange(1, n_max + 1)
    deviation = np.abs(running[:, checks - 1] - p)
    radii = np.array([normal_mixture_radius(int(n), alpha, rho) for n in checks])

    breach = float((deviation > radii).any(axis=1).mean())
    assert breach <= alpha


def test_an_ordinary_interval_loses_its_guarantee_under_the_same_adversary():
    """La raison pour laquelle un avertissement ne suffisait pas : ce n'est pas un biais,
    c'est une garantie qui n'existe plus."""
    rng = np.random.default_rng(0)
    p, n_max, reps = 0.90, 800, 800
    checks = np.arange(20, n_max + 1, 20)

    x = (rng.random((reps, n_max)) < p).astype(float)
    running = np.cumsum(x, axis=1) / np.arange(1, n_max + 1)
    sub = running[:, checks - 1]
    se = np.sqrt(np.maximum(sub * (1 - sub), 1e-12) / checks)

    breach = float((np.abs(sub - p) > 1.96 * se).any(axis=1).mean())
    assert breach > 0.25          # nominalement 5 %


# ============================================= l'unité d'échantillon est la grappe


def test_the_sample_size_is_the_number_of_clusters_not_observations():
    values, clusters = clustered(40, 50, 0.9)
    fractions, n_obs = cluster_fractions(values, clusters, 100.0)
    assert fractions.size == 40
    assert n_obs == 2_000


def test_a_burst_does_not_narrow_the_interval_by_its_length():
    """Trois cents ticks d'une rafale ne sont pas trois cents tirages indépendants."""
    few = threshold_confidence_sequence(*clustered(20, 300, 0.9), 100.0, 0.05,
                                        rho_for_target(200))
    many_ = threshold_confidence_sequence(*clustered(200, 30, 0.9), 100.0, 0.05,
                                          rho_for_target(200))
    assert few.n_observations == many_.n_observations == 6_000
    assert many_.width < few.width


def test_the_estimand_is_declared_as_cluster_weighted():
    cs = threshold_confidence_sequence(*clustered(30, 20, 0.9), 100.0, 0.05, 25.0)
    assert cs.weighting is ClusterWeighting.EQUAL_PER_CLUSTER


def test_an_empty_sample_claims_nothing():
    cs = threshold_confidence_sequence([], [], 100.0, 0.05, 25.0)
    assert cs.lower == 0.0 and cs.upper == 1.0
    assert threshold_verdict(cs, 0.95) is ThresholdVerdict.UNDETERMINED


# ============================================= le verdict de seuil


def test_a_quantile_clearly_above_the_threshold_is_detected():
    """`F(seuil) < q` équivaut à « le quantile dépasse le seuil »."""
    cs = threshold_confidence_sequence(*clustered(400, 40, 0.50), 100.0, 0.05,
                                       rho_for_target(400))
    assert threshold_verdict(cs, 0.95) is ThresholdVerdict.QUANTILE_ABOVE_THRESHOLD


def test_concluding_below_the_threshold_costs_far_more_than_excluding():
    """L'asymétrie est structurelle et voulue : exclure demande une marge large, donc peu
    de grappes ; conclure « non exclu » demande une marge fine contre `q = 0,95`, donc un
    échantillon bien plus grand. C'est cohérent avec le statut des deux verdicts."""
    rho = rho_for_target(400)
    modest = threshold_confidence_sequence(*clustered(400, 40, 1.0), 100.0, 0.05, rho)
    assert threshold_verdict(modest, 0.95) is ThresholdVerdict.UNDETERMINED

    plenty = threshold_confidence_sequence(*clustered(4_000, 40, 1.0), 100.0, 0.05, rho)
    assert threshold_verdict(plenty, 0.95) is ThresholdVerdict.QUANTILE_BELOW_THRESHOLD


def test_the_cost_of_each_direction_is_computable_before_the_campaign():
    """Déclarer un horizon gelé réaliste suppose de connaître ce coût à l'avance."""
    rho = rho_for_target(400)
    to_exclude = clusters_for_separation(0.45, 0.05, rho)   # F ≈ 0,50 contre q = 0,95
    to_accept = clusters_for_separation(0.05, 0.05, rho)    # F ≈ 1,00 contre q = 0,95
    assert to_exclude is not None and to_accept is not None
    assert to_exclude < 100 < to_accept
    assert clusters_for_separation(0.0, 0.05, rho) is None


def test_a_quantile_sitting_on_the_threshold_stays_undetermined():
    cs = threshold_confidence_sequence(*clustered(100, 20, 0.95), 100.0, 0.05,
                                       rho_for_target(200))
    assert threshold_verdict(cs, 0.95) is ThresholdVerdict.UNDETERMINED


def test_the_verdict_uses_a_single_fixed_threshold_so_no_union_bound_is_owed():
    """Aucune inversion sur une grille de quantiles : la décision porte sur le seuil
    admissible, qui est fixe."""
    values, clusters = clustered(200, 20, 0.80)
    a = threshold_confidence_sequence(values, clusters, 100.0, 0.05, 50.0)
    b = threshold_confidence_sequence(values, clusters, 100.0, 0.05, 50.0)
    assert (a.lower, a.upper) == (b.lower, b.upper)


# ============================================= discipline de mode


def test_a_data_dependent_stop_under_fixed_horizon_is_invalid():
    assert validity(InferenceMode.FIXED_HORIZON, True) is (
        InferenceValidity.SEQUENTIAL_INFERENCE_INVALID
    )


def test_a_fixed_horizon_run_that_did_not_peek_stays_valid():
    assert validity(InferenceMode.FIXED_HORIZON, False) is InferenceValidity.VALID


def test_anytime_valid_survives_a_data_dependent_stop():
    assert validity(InferenceMode.ANYTIME_VALID, True) is InferenceValidity.VALID


def test_the_mode_chooses_the_method_never_the_other_way_round():
    values, clusters = clustered(100, 20, 0.9)
    seq = interval_for_mode(InferenceMode.ANYTIME_VALID, values, clusters, 100.0,
                            0.05, rho_for_target(100))
    fixed = interval_for_mode(InferenceMode.FIXED_HORIZON, values, clusters, 100.0,
                              0.05, None)
    assert seq.width > fixed.width
    assert math.isnan(fixed.rho)


def test_anytime_valid_refuses_a_boundary_chosen_after_the_fact():
    with pytest.raises(SequentialError, match="déclaré à l'avance"):
        interval_for_mode(InferenceMode.ANYTIME_VALID, *clustered(10, 5, 0.9),
                          100.0, 0.05, None)


def test_the_fixed_horizon_interval_is_the_tighter_of_the_two():
    """Il est plus étroit parce qu'il achète cette précision en renonçant à l'arrêt
    optionnel — pas parce qu'il en sait davantage."""
    values, clusters = clustered(150, 20, 0.9)
    assert (fixed_horizon_interval(values, clusters, 100.0, 0.05).width
            < threshold_confidence_sequence(values, clusters, 100.0, 0.05,
                                            rho_for_target(150)).width)
