"""Tests de l'enveloppe de faisabilité.

Chaque test vise une décision d'architecture précise, citée en docstring : le but n'est
pas de couvrir des lignes mais de vérifier que les garde-fous se déclenchent réellement.
Une porte qu'on n'a jamais vue bloquer est une hypothèse, pas un mécanisme.
"""

from __future__ import annotations

import numpy as np
import pytest

from feasibility import (
    Cell,
    ConventionError,
    Conventions,
    CostMethod,
    CostVerdict,
    EnvelopeVerdict,
    FrequencyVerdict,
    LatencyVerdict,
    OccurrenceCensus,
    PlausibleEdgeBand,
    ReferencePriceConvention,
    RoundTripDefinition,
    SpreadCountingConvention,
    assess_frequency,
    combine,
    detect_price_events,
    displacement_sample,
    economic_frequency_floor,
    kappa_with_ci,
    modeled_round_trip_cost,
    observed_round_trip_cost,
    phase0_residual,
    realized_scale,
    sqrt_time_diagnostic,
    statistical_frequency_floor,
)
from feasibility.scale import robust_scale
from feasibility.synthetic import NS_PER_SECOND, generate, latency_samples

# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def ticks():
    return generate(days=25, ticks_per_session=40_000, seed=7)


@pytest.fixture
def modeled_conventions():
    return Conventions(
        cost_measurement_method=CostMethod.MODELED,
        reference_price_convention=ReferencePriceConvention.MID_TO_MID,
        round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
        spread_counting_convention=SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
        protocol_version="Q40_PHASE0_1.0",
        cost_model_version="Q40_COST_1.0",
    )


@pytest.fixture
def observed_conventions():
    return Conventions(
        cost_measurement_method=CostMethod.OBSERVED_IS,
        reference_price_convention=ReferencePriceConvention.MID_EXECUTABLE_AT_DECISION,
        round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
        spread_counting_convention=SpreadCountingConvention.ALREADY_IN_PERFORMANCE,
        protocol_version="Q40_PHASE0_1.0",
        cost_model_version="Q40_COST_1.0",
    )


@pytest.fixture
def cell():
    return Cell(
        instrument="XAUUSD",
        detection_market="SYNTHETIC",
        execution_market="SYNTHETIC",
        order_type="MARKET",
        session="ALL",
        size=0.05,
        regime="NORMAL",
    )


@pytest.fixture
def band():
    return PlausibleEdgeBand(
        a_min=0.05,
        a_max=0.30,
        source="bande arbitraire de test — aucune valeur de marché",
        declared_at="2026-08-06",
    )


# ------------------------------------------------------------------- ADR-111 / ADR-112


def test_observed_method_rejects_explicit_spread():
    """ADR-111 : l'implementation shortfall contient déjà le spread ; l'ajouter le
    compterait deux fois, gonflerait le seuil et rejetterait des effets réels."""
    with pytest.raises(ConventionError, match="déjà contenu"):
        Conventions(
            cost_measurement_method=CostMethod.OBSERVED_IS,
            reference_price_convention=ReferencePriceConvention.MID_EXECUTABLE_AT_DECISION,
            round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
            spread_counting_convention=SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
            protocol_version="v1",
            cost_model_version="v1",
        )


def test_modeled_method_requires_explicit_spread():
    """Symétrique : en méthode modélisée, aucune mesure d'exécution ne contient le spread."""
    with pytest.raises(ConventionError, match="compté explicitement"):
        Conventions(
            cost_measurement_method=CostMethod.MODELED,
            reference_price_convention=ReferencePriceConvention.MID_TO_MID,
            round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
            spread_counting_convention=SpreadCountingConvention.ALREADY_IN_PERFORMANCE,
            protocol_version="v1",
            cost_model_version="v1",
        )


def test_cost_functions_refuse_the_other_method(cell, modeled_conventions, observed_conventions):
    """ADR-110 : les deux méthodes ne se mélangent jamais dans une même estimation."""
    clusters = np.zeros(10, dtype=np.int64)
    with pytest.raises(ConventionError):
        modeled_round_trip_cost(
            cell, observed_conventions, np.full(10, 0.2), clusters, commission_round_trip=0.0
        )
    with pytest.raises(ConventionError):
        observed_round_trip_cost(
            cell, modeled_conventions, np.full(10, 0.2), np.full(10, 0.2), clusters, 0.0
        )


def test_conventions_digest_is_stable_and_discriminating(modeled_conventions):
    """Deux expériences de conventions différentes doivent être reconnaissables."""
    other = Conventions(
        cost_measurement_method=CostMethod.MODELED,
        reference_price_convention=ReferencePriceConvention.BID_ASK,
        round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
        spread_counting_convention=SpreadCountingConvention.FULL_SPREAD_ONCE,
        protocol_version="Q40_PHASE0_1.0",
        cost_model_version="Q40_COST_1.0",
    )
    assert modeled_conventions.digest() == modeled_conventions.digest()
    assert modeled_conventions.digest() != other.digest()


# ----------------------------------------------------------------------------- ADR-115


@pytest.mark.parametrize("a_min,a_max", [(0.0, 0.3), (0.4, 0.2), (-0.1, 0.3)])
def test_band_rejects_invalid_bounds(a_min, a_max):
    with pytest.raises(ValueError):
        PlausibleEdgeBand(a_min=a_min, a_max=a_max, source="s", declared_at="d")


def test_band_requires_provenance():
    """ADR-115 : sans source ni date, rien ne distingue une bande préenregistrée d'une
    bande choisie après avoir vu la courbe."""
    with pytest.raises(ValueError, match="source"):
        PlausibleEdgeBand(a_min=0.05, a_max=0.3, source="  ", declared_at="2026-01-01")


# ------------------------------------------------------------------------------ échelle


def test_robust_scale_matches_normal_sigma():
    rng = np.random.default_rng(0)
    x = rng.normal(0.0, 3.0, size=200_000)
    assert robust_scale(x) == pytest.approx(3.0, rel=0.02)


def test_robust_scale_resists_outliers():
    """Motif du choix : les rendements ont des queues épaisses, et l'écart-type y est
    dominé par quelques observations."""
    x = np.concatenate([np.random.default_rng(1).normal(0, 1, 10_000), np.full(50, 500.0)])
    assert robust_scale(x) == pytest.approx(1.0, rel=0.05)
    assert np.std(x) > 10


def test_realized_scale_grows_with_horizon(ticks):
    scales = [
        realized_scale(
            ticks.timestamps_ns, ticks.mid, h, ticks.cluster_ids, step=13
        ).robust_scale
        for h in (NS_PER_SECOND, 10 * NS_PER_SECOND, 60 * NS_PER_SECOND)
    ]
    assert all(np.isfinite(s) and s > 0 for s in scales)
    assert scales[0] < scales[1] < scales[2]


def test_sqrt_diagnostic_is_a_control_not_a_constraint(ticks):
    """ADR-114 : le diagnostic mesure l'écart à la racine du temps sans l'imposer."""
    estimates = [
        realized_scale(ticks.timestamps_ns, ticks.mid, h, ticks.cluster_ids, step=13)
        for h in (NS_PER_SECOND, 4 * NS_PER_SECOND, 16 * NS_PER_SECOND)
    ]
    diag = sqrt_time_diagnostic(estimates)
    assert len(diag) == 3
    assert diag[0]["ratio"] == pytest.approx(1.0)
    # Les ratios existent et sont finis : le diagnostic n'écrase pas les données.
    assert all(np.isfinite(d["ratio"]) for d in diag)


def test_realized_scale_handles_empty_input():
    est = realized_scale(np.array([1]), np.array([1.0]), 10, np.array([0]))
    assert est.observations == 0
    assert np.isnan(est.robust_scale)


# -------------------------------------------------------------------------------- coût


def test_modeled_cost_components_are_additive(cell, modeled_conventions):
    clusters = np.arange(100) // 10
    cost = modeled_round_trip_cost(
        cell,
        modeled_conventions,
        spread_samples=np.full(100, 0.20),
        cluster_ids=clusters,
        commission_round_trip=0.07,
        latency_slippage_samples=np.full(100, 0.03),
        financing=0.01,
    )
    assert cost.quantile(0.5) == pytest.approx(0.20 + 0.03 + 0.07 + 0.01)
    assert cost.independent_clusters == 10
    assert cost.method is CostMethod.MODELED


def test_modeled_cost_rejects_misaligned_slippage(cell, modeled_conventions):
    with pytest.raises(ValueError, match="aligné"):
        modeled_round_trip_cost(
            cell,
            modeled_conventions,
            spread_samples=np.full(10, 0.2),
            cluster_ids=np.zeros(10),
            commission_round_trip=0.0,
            latency_slippage_samples=np.full(4, 0.01),
        )


def test_observed_cost_needs_paired_shortfalls(cell, observed_conventions):
    with pytest.raises(ValueError, match="appariés"):
        observed_round_trip_cost(
            cell, observed_conventions, np.full(5, 0.1), np.full(4, 0.1), np.zeros(5), 0.0
        )


# ------------------------------------------------------------------- kappa et verdicts


def _kappa_for(ticks, cell, conventions, band, horizon_ns, spread_scale=1.0, commission=0.07):
    disp, disp_clusters = displacement_sample(
        ticks.timestamps_ns, ticks.mid, horizon_ns, ticks.cluster_ids, step=17
    )
    cost = modeled_round_trip_cost(
        cell,
        conventions,
        spread_samples=ticks.spread[::17] * spread_scale,
        cluster_ids=ticks.cluster_ids[::17],
        commission_round_trip=commission,
    )
    return kappa_with_ci(
        cost, disp, disp_clusters, horizon_ns, band, n_bootstrap=120, min_clusters=20
    )


def test_kappa_decreases_with_horizon(ticks, cell, modeled_conventions, band):
    """Le coût est presque fixe, l'amplitude croît : kappa doit décroître. C'est le
    mécanisme qui fait exister un horizon minimal."""
    short = _kappa_for(ticks, cell, modeled_conventions, band, NS_PER_SECOND)
    long = _kappa_for(ticks, cell, modeled_conventions, band, 300 * NS_PER_SECOND)
    assert short.kappa_p95 > long.kappa_p95


def test_short_horizon_is_excluded_by_cost(ticks, cell, modeled_conventions, band):
    """À l'échelle de la seconde, les frais dépassent largement l'amplitude."""
    res = _kappa_for(ticks, cell, modeled_conventions, band, NS_PER_SECOND)
    assert res.verdict is CostVerdict.COST_NON_VIABLE
    assert res.confidence_lower > band.a_max


def test_long_horizon_is_not_excluded(ticks, cell, modeled_conventions, band):
    """`COST_NOT_EXCLUDED` ne démontre aucune rentabilité — seulement que l'argument de
    coût ne tranche pas."""
    res = _kappa_for(ticks, cell, modeled_conventions, band, 1800 * NS_PER_SECOND)
    assert res.verdict in (CostVerdict.COST_NOT_EXCLUDED, CostVerdict.COST_HEADROOM)


def test_insufficient_clusters_yields_indeterminate(cell, modeled_conventions, band):
    """ADR-093 : trop peu de blocs indépendants ⇒ on ne conclut pas. `INDETERMINATE`
    n'est pas une exclusion."""
    clusters = np.zeros(50, dtype=np.int64)
    cost = modeled_round_trip_cost(
        cell, modeled_conventions, np.full(50, 0.2), clusters, commission_round_trip=0.07
    )
    res = kappa_with_ci(
        cost, np.random.default_rng(0).normal(0, 1, 50), clusters,
        NS_PER_SECOND, band, n_bootstrap=50, min_clusters=20,
    )
    assert res.verdict is CostVerdict.COST_INDETERMINATE
    assert res.sample.independent_clusters == 1


def test_exclusion_uses_lower_bound_not_point_estimate(ticks, cell, modeled_conventions):
    """ADR-116 : une bande large ne doit pas exclure alors que l'incertitude chevauche
    l'avantage plausible."""
    generous = PlausibleEdgeBand(
        a_min=0.01, a_max=1e6, source="bande volontairement large", declared_at="2026-08-06"
    )
    res = _kappa_for(ticks, cell, modeled_conventions, generous, NS_PER_SECOND)
    assert res.verdict is not CostVerdict.COST_NON_VIABLE


# ---------------------------------------------------------------- Q19 phase 0, latence


def test_event_detection_deduplicates_clusters(ticks):
    """Un même épisode déclenche plusieurs ticks : sans déduplication, un seul mouvement
    serait compté des dizaines de fois."""
    starts, signs = detect_price_events(
        ticks.timestamps_ns, ticks.mid, window_ns=2 * NS_PER_SECOND, quantile=0.999
    )
    assert starts.size > 0
    assert np.all(np.diff(ticks.timestamps_ns[starts]) > 2 * NS_PER_SECOND)
    assert set(np.unique(signs)).issubset({-1.0, 1.0})


def test_phase0_consumed_fraction_grows_with_latency(ticks):
    """Plus la latence est grande, plus la part du mouvement déjà survenue est grande.
    C'est tout le raisonnement du pré-test."""
    starts, signs = detect_price_events(
        ticks.timestamps_ns, ticks.mid, window_ns=2 * NS_PER_SECOND, quantile=0.995
    )
    horizon = 30 * NS_PER_SECOND
    fast = phase0_residual(
        ticks.timestamps_ns, ticks.mid, ticks.cluster_ids, starts, signs,
        np.full(500, 10_000_000), horizon, round_trip_cost=0.0, min_clusters=5,
    )
    slow = phase0_residual(
        ticks.timestamps_ns, ticks.mid, ticks.cluster_ids, starts, signs,
        np.full(500, 20 * NS_PER_SECOND), horizon, round_trip_cost=0.0, min_clusters=5,
    )
    assert slow.consumed_fraction_p50 > fast.consumed_fraction_p50


def test_phase0_is_conclusive_when_costs_exceed_residual(ticks):
    """Verdict négatif conclusif : même la borne supérieure ne couvre pas les frais."""
    starts, signs = detect_price_events(
        ticks.timestamps_ns, ticks.mid, window_ns=2 * NS_PER_SECOND, quantile=0.995
    )
    res = phase0_residual(
        ticks.timestamps_ns, ticks.mid, ticks.cluster_ids, starts, signs,
        np.full(500, 500_000_000), 30 * NS_PER_SECOND,
        round_trip_cost=1_000.0, min_clusters=5,
    )
    assert res.verdict is LatencyVerdict.LATENCY_NON_VIABLE
    assert res.residual_net_p50 < 0


def test_phase0_without_events_is_indeterminate(ticks):
    res = phase0_residual(
        ticks.timestamps_ns, ticks.mid, ticks.cluster_ids,
        np.empty(0, dtype=np.int64), np.empty(0),
        np.full(10, 1_000_000), NS_PER_SECOND, round_trip_cost=0.0,
    )
    assert res.verdict is LatencyVerdict.LATENCY_INDETERMINATE


def test_burst_latency_is_worse_than_quiet():
    """ADR-102 : la latence se dégrade là où les signaux se déclenchent, donc le centile
    marginal sous-estime celui qui compte."""
    quiet, burst = latency_samples(n=20_000)
    assert np.quantile(burst, 0.95) > np.quantile(quiet, 0.95)


# -------------------------------------------------------------------------- fréquence


def test_frequency_floor_is_the_maximum_of_both(ticks):
    """ADR-117 : économique et statistique sont deux conditions distinctes."""
    census = OccurrenceCensus(
        raw_occurrences=40, observation_span_days=40.0,
        independent_clusters=40, regimes_covered=2,
    )
    req = assess_frequency(census, f_min_economic=0.5, f_min_statistical=3.0)
    assert req.f_min == 3.0
    assert req.verdict is FrequencyVerdict.FREQUENCY_NON_VIABLE
    assert "statistique" in req.rationale


def test_frequency_not_excluded_when_abundant():
    census = OccurrenceCensus(
        raw_occurrences=4_000, observation_span_days=40.0,
        independent_clusters=40, regimes_covered=3,
    )
    req = assess_frequency(census, f_min_economic=2.0, f_min_statistical=1.0)
    assert req.verdict is FrequencyVerdict.FREQUENCY_NOT_EXCLUDED


def test_single_regime_coverage_is_indeterminate():
    census = OccurrenceCensus(
        raw_occurrences=4_000, observation_span_days=40.0,
        independent_clusters=40, regimes_covered=1,
    )
    req = assess_frequency(census, f_min_economic=0.1, f_min_statistical=0.1)
    assert req.verdict is FrequencyVerdict.FREQUENCY_INDETERMINATE


def test_economic_floor_is_infinite_without_edge():
    assert economic_frequency_floor(1.0, 0.0, 0.5, 0.0) == float("inf")
    assert statistical_frequency_floor(30, 0.0) == float("inf")


# --------------------------------------------------------------------------- enveloppe


def _envelope(cost_v, lat_v, freq_v, cell, band):
    from feasibility.frequency import FrequencyRequirement
    from feasibility.kappa import KappaResult
    from feasibility.latency import Phase0Result
    from feasibility.model import SampleSize

    kappa = KappaResult(
        horizon_ns=1, cell=cell, kappa_p50=0.1, kappa_p95=0.2,
        confidence_lower=0.1, confidence_upper=0.3, cost_quantile_used=0.95,
        scale=1.0, sample=SampleSize(100, 30), verdict=cost_v,
    )
    phase0 = Phase0Result(1, 100, 30, 0.5, 0.7, 0.5, 0.3, 0.2, 0.1, lat_v)
    freq = FrequencyRequirement(0.1, 0.1, freq_v, "test")
    return combine(cell, 1, kappa, phase0, freq)


def test_envelope_requires_all_three_to_be_eligible(cell, band):
    """ADR-118 : l'éligibilité est une intersection, pas une majorité."""
    env = _envelope(
        CostVerdict.COST_NOT_EXCLUDED,
        LatencyVerdict.LATENCY_VIABLE,
        FrequencyVerdict.FREQUENCY_NOT_EXCLUDED,
        cell, band,
    )
    assert env.verdict is EnvelopeVerdict.ELIGIBLE_FOR_PREDICTIVE_TESTING
    assert env.trigger_authority is True


@pytest.mark.parametrize(
    "cost_v,lat_v,freq_v,expected",
    [
        (CostVerdict.COST_NON_VIABLE, LatencyVerdict.LATENCY_VIABLE,
         FrequencyVerdict.FREQUENCY_NOT_EXCLUDED, EnvelopeVerdict.EXCLUDED_BY_COST),
        (CostVerdict.COST_NOT_EXCLUDED, LatencyVerdict.LATENCY_NON_VIABLE,
         FrequencyVerdict.FREQUENCY_NOT_EXCLUDED, EnvelopeVerdict.EXCLUDED_BY_LATENCY),
        (CostVerdict.COST_NOT_EXCLUDED, LatencyVerdict.LATENCY_VIABLE,
         FrequencyVerdict.FREQUENCY_NON_VIABLE, EnvelopeVerdict.EXCLUDED_BY_FREQUENCY),
        (CostVerdict.COST_NON_VIABLE, LatencyVerdict.LATENCY_NON_VIABLE,
         FrequencyVerdict.FREQUENCY_NOT_EXCLUDED, EnvelopeVerdict.EXCLUDED_BY_MULTIPLE),
    ],
)
def test_envelope_reports_which_dimension_excluded(cost_v, lat_v, freq_v, expected, cell, band):
    env = _envelope(cost_v, lat_v, freq_v, cell, band)
    assert env.verdict is expected
    assert env.trigger_authority is False


def test_indeterminate_never_grants_eligibility(cell, band):
    """Ignorance n'est pas permission : une dimension inconnue empêche l'éligibilité
    sans pour autant valoir exclusion."""
    env = _envelope(
        CostVerdict.COST_INDETERMINATE,
        LatencyVerdict.LATENCY_VIABLE,
        FrequencyVerdict.FREQUENCY_NOT_EXCLUDED,
        cell, band,
    )
    assert env.verdict is EnvelopeVerdict.INDETERMINATE
    assert env.trigger_authority is False


def test_exclusion_takes_precedence_over_indeterminate(cell, band):
    env = _envelope(
        CostVerdict.COST_INDETERMINATE,
        LatencyVerdict.LATENCY_NON_VIABLE,
        FrequencyVerdict.FREQUENCY_INDETERMINATE,
        cell, band,
    )
    assert env.verdict is EnvelopeVerdict.EXCLUDED_BY_LATENCY


def test_missing_inputs_are_indeterminate_not_eligible(cell):
    env = combine(cell, 1, None, None, None)
    assert env.verdict is EnvelopeVerdict.INDETERMINATE
    assert env.trigger_authority is False


# ------------------------------------------------------------------------- déterminisme


def test_kappa_is_reproducible(ticks, cell, modeled_conventions, band):
    """I2 : mêmes entrées, mêmes paramètres, même résultat."""
    disp, clusters = displacement_sample(
        ticks.timestamps_ns, ticks.mid, 60 * NS_PER_SECOND, ticks.cluster_ids, step=17
    )
    cost = modeled_round_trip_cost(
        cell, modeled_conventions, ticks.spread[::17], ticks.cluster_ids[::17], 0.07
    )
    kw = dict(horizon_ns=60 * NS_PER_SECOND, band=band, n_bootstrap=80, min_clusters=20)
    a = kappa_with_ci(cost, disp, clusters, rng=np.random.default_rng(42), **kw)
    b = kappa_with_ci(cost, disp, clusters, rng=np.random.default_rng(42), **kw)
    assert (a.confidence_lower, a.confidence_upper) == (b.confidence_lower, b.confidence_upper)
