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
    ClusterQualification,
    Estimand,
    InferenceMode,
    InferenceValidity,
    SequentialError,
    SequentialQualification,
    autocorrelation,
    ThresholdVerdict,
    cluster_fractions,
    clusters_for_separation,
    event_weighted_fraction,
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
    fractions, sizes = cluster_fractions(values, clusters, 100.0)
    assert fractions.size == 40
    assert int(sizes.sum()) == 2_000


def test_a_burst_does_not_narrow_the_interval_by_its_length():
    """Trois cents ticks d'une rafale ne sont pas trois cents tirages indépendants."""
    few = threshold_confidence_sequence(*clustered(20, 300, 0.9), 100.0, 0.05,
                                        rho_for_target(200))
    many_ = threshold_confidence_sequence(*clustered(200, 30, 0.9), 100.0, 0.05,
                                          rho_for_target(200))
    assert few.n_observations == many_.n_observations == 6_000
    assert many_.width < few.width


def test_the_two_estimands_answer_different_questions():
    """Deux rafales très inégales : la CDF par grappe et la CDF par événement divergent
    fortement, et les deux sont justes. Le regroupement ne doit pas choisir en silence."""
    values = [5.0] * 10 + [5.0] * 500 + [500.0] * 500
    clusters = ["A"] * 10 + ["B"] * 1_000

    by_cluster = threshold_confidence_sequence(values, clusters, 100.0, 0.05, 25.0)
    assert by_cluster.estimand is Estimand.CLUSTER_WEIGHTED
    assert abs(by_cluster.estimate - 0.75) < 1e-9

    by_event = event_weighted_fraction(values, clusters, 100.0)
    assert abs(by_event - 510 / 1010) < 1e-9
    assert abs(by_cluster.estimate - by_event) > 0.2


def test_the_event_weighted_sequence_needs_a_declared_cluster_cap():
    """Sans plafond, la variable n'est pas bornée et la frontière ne s'applique pas."""
    values, clusters = clustered(30, 20, 0.9)
    with pytest.raises(SequentialError, match="plafond"):
        threshold_confidence_sequence(values, clusters, 100.0, 0.05, 25.0,
                                      estimand=Estimand.EVENT_WEIGHTED)


def test_a_cluster_above_the_declared_cap_is_refused_not_accommodated():
    values, clusters = clustered(30, 50, 0.9)
    with pytest.raises(SequentialError, match="plafond déclaré"):
        threshold_confidence_sequence(values, clusters, 100.0, 0.05, 25.0,
                                      estimand=Estimand.EVENT_WEIGHTED,
                                      max_cluster_size=20)


def test_the_event_weighted_sequence_brackets_its_own_estimand():
    values = [5.0] * 10 + [5.0] * 500 + [500.0] * 500
    clusters = ["A"] * 10 + ["B"] * 1_000
    cs = threshold_confidence_sequence(values, clusters, 100.0, 0.05, rho_for_target(50),
                                       estimand=Estimand.EVENT_WEIGHTED,
                                       max_cluster_size=1_000)
    assert cs.estimand is Estimand.EVENT_WEIGHTED
    assert cs.lower <= event_weighted_fraction(values, clusters, 100.0) <= cs.upper


# ============================================= qualification des hypothèses


def qualification(**kw) -> ClusterQualification:
    base = dict(
        cluster_definition="rafale au-dessus du seuil, bloc de 30 s sinon",
        reset_rule="retour sous seuil maintenu 3 s",
        minimum_gap_ns=3_000_000_000,
        n_clusters=120, size_p50=25.0, size_p95=180.0,
        duration_p50_ns=8_000_000_000,
        acf1_fraction=0.05, acf1_value=0.04, acf1_load=0.06,
        stationarity_checked=True,
    )
    return ClusterQualification(**{**base, **kw})


def test_good_diagnostics_alone_never_earn_the_anytime_valid_label():
    """Une série peut afficher `ACF ≈ 0` et rester dépendante ; un test de stationnarité
    qui ne rejette pas ne démontre pas la stationnarité. Une absence de contre-preuve
    n'est pas une preuve."""
    assert qualification().qualify() is (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    )


def test_only_a_positive_argument_qualifies_the_procedure():
    proven = qualification(
        assumption_proof="borne de Robbins appliquée à une martingale construite par "
                         "sous-échantillonnage à écart supérieur à la longueur de "
                         "corrélation mesurée"
    )
    assert proven.qualify() is SequentialQualification.SEQUENTIAL_VALID


def test_a_proof_does_not_override_failing_diagnostics():
    """La preuve s'ajoute aux diagnostics, elle ne les remplace pas."""
    assert qualification(assumption_proof="argument", acf1_load=0.7).qualify() is (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    )


def test_an_experimental_sequence_is_computed_but_never_normative():
    assert not InferenceMode.ANYTIME_VALID_EXPERIMENTAL.is_normative
    assert InferenceMode.FIXED_HORIZON.is_normative
    assert InferenceMode.ANYTIME_VALID.is_normative


def test_persistent_dependence_withholds_the_label():
    """Découper en blocs ne rend pas les blocs indépendants : deux blocs consécutifs
    peuvent partager charge, file, régime, connexion ou volatilité."""
    q = qualification(acf1_load=0.65)
    assert not q.dependence_within_tolerance
    assert q.qualify() is SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED


def test_unchecked_stationarity_withholds_the_label():
    assert qualification(stationarity_checked=False).qualify() is (
        SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED
    )


def test_too_few_clusters_is_outright_invalid():
    assert qualification(n_clusters=1).qualify() is (
        SequentialQualification.SEQUENTIAL_INVALID
    )


def test_an_unqualified_cell_falls_back_instead_of_being_lost():
    """Elle n'est pas perdue : elle change de protocole. Garder la revendication
    séquentielle serait émettre une garantie sans fondement."""
    values, clusters = clustered(100, 20, 0.9)
    cs = interval_for_mode(
        InferenceMode.ANYTIME_VALID, values, clusters, 100.0, 0.05,
        rho_for_target(100),
        clusters_qualified=SequentialQualification.SEQUENTIAL_ASSUMPTIONS_UNVERIFIED,
    )
    assert not cs.anytime_valid_claimable
    assert math.isnan(cs.rho)          # la borne appliquée est celle de l'horizon fixe

    qualified = interval_for_mode(
        InferenceMode.ANYTIME_VALID, values, clusters, 100.0, 0.05,
        rho_for_target(100),
        clusters_qualified=SequentialQualification.SEQUENTIAL_VALID,
    )
    experimental = interval_for_mode(
        InferenceMode.ANYTIME_VALID_EXPERIMENTAL, values, clusters, 100.0, 0.05,
        rho_for_target(100),
        clusters_qualified=SequentialQualification.SEQUENTIAL_VALID,
    )
    assert experimental.width == qualified.width
    assert qualified.anytime_valid_claimable
    assert qualified.width > cs.width


def test_autocorrelation_detects_a_persistent_series():
    drifting = [float(i) for i in range(60)]
    alternating = [0.0, 1.0] * 30
    assert autocorrelation(drifting) > 0.8
    assert autocorrelation(alternating) < -0.8
    assert math.isnan(autocorrelation([1.0, 2.0]))
    assert autocorrelation([3.0] * 20) == 0.0


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
                            0.05, rho_for_target(100),
                            clusters_qualified=SequentialQualification.SEQUENTIAL_VALID)
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
