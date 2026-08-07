"""Tests de la campagne passive Q51-A.

Les critères d'acceptation de §28, plus les cas où une campagne mal conditionnée
produirait une borne crédible et fausse : quantiles globaux au lieu de conditionnels,
grappes gonflées, arrêt opportuniste, ancrage optimiste de la capturabilité.
"""

from __future__ import annotations

import numpy as np
import pytest

from feasibility.latency_journal import BurstState, ConnectionState
from feasibility.observability import (
    ClockDomain,
    CorrectionMode,
    GranularityTest,
    MeasurementGrade,
    Virtualization,
    blank_capability,
    build_matrix,
    qualify_clock,
)
from feasibility.sequential import (
    InferenceMode,
    InferenceValidity,
    rho_for_target,
)
from feasibility.passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    AdmissibleLatency,
    BlockSensitivity,
    BlockingChoice,
    CapturabilityScope,
    ComparisonDesign,
    HorizonEndPolicy,
    AnalyticalImpossibility,
    BoundQuality,
    ConstraintClass,
    CostFloor,
    DataStatus,
    EconomicTarget,
    EconomicThresholds,
    ProtocolFreeze,
    OracleCapture,
    OracleKind,
    OracleVerdict,
    OpportunitySet,
    OrderType,
    OverlapPolicy,
    Phase0State,
    assess_oracle,
    clopper_pearson_upper,
    most_favourable_floor,
    rarity_bound,
    block_sensitivity,
    blocking_is_robust,
    compare_cadence,
    inference_validity,
    observer_overhead,
    oracle_capturable,
    oracle_verdict,
    phase0_state,
    CampaignCell,
    CampaignError,
    CapturabilityAnchor,
    ClusterAssigner,
    EvaluationMode,
    HostLoad,
    MarketContext,
    PassiveBoundaries,
    PassiveObservation,
    PassiveVerdict,
    PipelineMode,
    Q42Priority,
    StopDecision,
    StoppingPolicy,
    assess_stopping,
    capturability_input,
    coverage,
    daily_report,
    hourly_report,
    is_stable,
    latency_budget_ns,
    passive_verdict,
    q42_priority,
    stability_trace,
    summarise_by_cell,
    summarise_cell,
)

MS = NS_PER_MS


def clock(**kw):
    g = GranularityTest(40, 48.0, 160.0, 0.0)
    base = dict(
        host_id="H1", granularity_wall=g, granularity_monotonic=g, monotonic_failures=0,
        wall_discontinuities=0, drift_p95_ppm=1.0, measured_uncertainty_ns=None,
        correction_mode=CorrectionMode.SLEW, virtualization=Virtualization.BARE_METAL,
        suspend_events=0, sync_method="NTP", qualified_at_ns=0,
        wall_mono_samples=50_000, intersystem_uncertainty_declared_unknown=True,
    )
    return qualify_clock(**{**base, **kw})


def cell(**kw) -> CampaignCell:
    base = dict(
        source="courtier", session="LONDON", burst_state=BurstState.NORMAL,
        evaluation_mode=EvaluationMode.EVENT_DRIVEN, pipeline=PipelineMode.TARGET,
        host_id="H1", software_commit="abc123",
    )
    return CampaignCell(**{**base, **kw})


def boundaries(eligibility=1 * MS, wait=2 * MS, compute=5 * MS, decision=1 * MS,
               provider=None, start=0) -> PassiveBoundaries:
    b1 = start
    b2 = b1 + eligibility
    b3 = b2 + wait
    b4 = b3 + compute
    b5 = b4 + decision
    return PassiveBoundaries(provider, b1, b2, b3, b4, b5, local_receive_wall_ns=start)


def observation(**kw) -> PassiveObservation:
    base = dict(
        boundaries=boundaries(),
        market=MarketContext(1.2, 12.0, 60.0, 0.18, 0.5, 0.01, 0.5),
        host=HostLoad(2, 5, 100_000, 0.4, 10**8),
        cell=cell(),
        cluster_id="C1",
        day="2026-08-07",
        clock_grade=MeasurementGrade.EXACT_LOCAL,
        connection_state=ConnectionState.CONNECTED_STABLE,
        calendar_state="OPEN",
    )
    return PassiveObservation(**{**base, **kw})


def many(n: int, *, total_ns: int, burst=BurstState.NORMAL, day="2026-08-07",
         cluster_prefix="C", per_cluster=1, jitter_ns=0, **kw) -> list[PassiveObservation]:
    """Échantillon déterministe. `jitter_ns` sert aux tests qui ont besoin de variance :
    sans lui, tous les quantiles d'un groupe coïncident et ne distinguent plus rien."""
    out = []
    for i in range(n):
        spread = ((i * 37) % 101) * jitter_ns // 100 if jitter_ns else 0
        out.append(observation(
            boundaries=boundaries(compute=total_ns - 4 * MS + spread,
                                  start=i * 10 * MS),
            cell=cell(burst_state=burst),
            cluster_id=f"{cluster_prefix}{i // per_cluster}",
            day=day,
            **kw,
        ))
    return out


# ============================================= §28 — critères d'acceptation


def test_the_campaign_runs_with_an_entirely_unqualified_broker():
    """Q51-A ne suppose aucune latence courtier et fonctionne avec une fiche Q58 vide."""
    m = build_matrix(clock(), blank_capability("COURTIER", "REEL"))
    o = observation()
    assert o.local_lower_bound_ns == 9 * MS
    assert m.status_of("submit_to_ack").value == "NOT_IDENTIFIABLE"


def test_a_local_only_clock_produces_the_bound_without_claiming_the_provider_leg():
    """La borne locale est produite sans prétendre mesurer provider → réception."""
    o = observation(boundaries=boundaries(provider=-40 * MS))
    assert o.local_lower_bound_ns == 9 * MS
    assert o.provider_lower_bound_ns(clock()) is None


def test_the_provider_leg_appears_only_once_qualified():
    qualified = clock(measured_uncertainty_ns=200_000,
                      intersystem_uncertainty_declared_unknown=False)
    o = observation(boundaries=boundaries(provider=-40 * MS), provider_qualified=True)
    assert o.provider_lower_bound_ns(qualified) == 49 * MS


def test_burst_conditional_quantiles_differ_from_the_global_ones():
    """Les signaux apparaissent là où la latence se dégrade : le p95 global sous-estime
    celui qui décide."""
    calm = many(60, total_ns=8 * MS, cluster_prefix="N", per_cluster=2,
                jitter_ns=2 * MS)
    heavy = many(60, total_ns=70 * MS, burst=BurstState.BURST_P95,
                 cluster_prefix="B", per_cluster=2, jitter_ns=30 * MS)
    by_cell = summarise_by_cell(calm + heavy)

    normal = next(s for c, s in by_cell.items() if c.burst_state is BurstState.NORMAL)
    burst = next(s for c, s in by_cell.items() if c.burst_state is BurstState.BURST_P95)
    pooled = np.quantile(
        [o.local_lower_bound_ns for o in calm + heavy], 0.95
    )
    assert burst.bound.p95 > pooled > normal.bound.p95


def test_queue_accumulation_shows_up_in_the_evaluation_wait():
    shallow = observation(boundaries=boundaries(wait=1 * MS),
                          host=HostLoad(1, 1, 50_000, 0.2, 10**8))
    deep = observation(boundaries=boundaries(wait=40 * MS),
                       host=HostLoad(180, 220, 4 * MS, 0.95, 10**9))
    assert deep.evaluation_wait_ns > shallow.evaluation_wait_ns
    assert deep.local_lower_bound_ns > shallow.local_lower_bound_ns


def test_the_wait_is_measured_never_replaced_by_half_a_period():
    """L'approximation cadence/2 suppose des arrivées uniformes ; les cotations arrivent
    en rafale et s'alignent sur des frontières rondes."""
    periodic = cell(evaluation_mode=EvaluationMode.PERIODIC,
                    evaluation_period_ns=100 * MS)
    o = observation(cell=periodic, boundaries=boundaries(wait=3 * MS))
    assert o.evaluation_wait_ns == 3 * MS
    assert o.evaluation_wait_ns != periodic.evaluation_period_ns // 2


def test_a_periodic_cell_must_declare_its_configured_cadence():
    with pytest.raises(CampaignError, match="cadence configurée"):
        cell(evaluation_mode=EvaluationMode.PERIODIC)


def test_event_driven_evaluation_can_have_a_near_zero_wait():
    o = observation(boundaries=boundaries(eligibility=0, wait=0))
    assert o.evaluation_wait_ns == 0
    assert o.local_lower_bound_ns == 6 * MS


def test_a_hundred_ticks_in_one_burst_are_not_a_hundred_clusters():
    a = ClusterAssigner(burst_threshold=100.0, reset_ns=2 * NS_PER_SECOND,
                        quiet_block_ns=NS_PER_SECOND)
    ids = [a.assign(i * 5 * MS, 400.0) for i in range(100)]
    assert len(set(ids)) == 1


def test_a_burst_ends_only_after_a_sustained_return_below_the_threshold():
    """Une oscillation autour du seuil fabriquerait des grappes artificielles."""
    a = ClusterAssigner(burst_threshold=100.0, reset_ns=2 * NS_PER_SECOND,
                        quiet_block_ns=NS_PER_SECOND)
    a.assign(0, 400.0)
    dipped = a.assign(500 * MS, 20.0)
    back = a.assign(700 * MS, 400.0)
    assert dipped == back == "S1:burst:1"

    a.assign(1 * NS_PER_SECOND, 400.0)
    a.assign(2 * NS_PER_SECOND, 10.0)
    after = a.assign(5 * NS_PER_SECOND, 10.0)
    assert after.startswith("S1:quiet:")


def test_quiet_observations_are_clustered_too():
    """Deux cotations calmes séparées de 50 ms ne sont pas indépendantes non plus. Ne
    regrouper que les rafales gonflerait la précision apparente en régime normal."""
    a = ClusterAssigner(burst_threshold=100.0, reset_ns=NS_PER_SECOND,
                        quiet_block_ns=200 * MS)
    ids = [a.assign(i * 50 * MS, 5.0) for i in range(20)]
    assert 1 < len(set(ids)) < 20


def test_a_degraded_clock_observation_never_enters_the_local_distribution():
    mixed = many(40, total_ns=8 * MS, per_cluster=2)
    mixed += [observation(clock_grade=MeasurementGrade.DEGRADED_CLOCK, cluster_id="D1")]
    s = summarise_cell(mixed)
    assert s.observations == 40


def test_a_summary_refuses_to_mix_cells():
    with pytest.raises(CampaignError, match="cellules mélangées"):
        summarise_cell([observation(), observation(cell=cell(session="NEW_YORK"))])


def test_a_summary_refuses_a_sample_with_no_exact_clock():
    with pytest.raises(CampaignError, match="horloge exacte"):
        summarise_cell([observation(clock_grade=MeasurementGrade.UNKNOWN)])


# ============================================= frontières, jamais additions


def test_the_bound_is_a_boundary_difference_equal_to_its_components():
    """Les cinq frontières sont consécutives : la différence B5−B1 et la somme des
    quatre composantes coïncident nécessairement. Si elles divergeaient, ce serait le
    signe d'un recouvrement."""
    o = observation(boundaries=boundaries(eligibility=2 * MS, wait=7 * MS,
                                          compute=11 * MS, decision=3 * MS))
    assert o.local_lower_bound_ns == 23 * MS
    assert o.components_sum_ns == o.local_lower_bound_ns


def test_boundaries_out_of_order_are_refused():
    from feasibility.observability import ObservabilityError

    with pytest.raises(ObservabilityError, match="hors ordre"):
        observation(boundaries=PassiveBoundaries(None, 10 * MS, 5 * MS, 6 * MS,
                                                 7 * MS, 8 * MS))


def test_an_incomplete_local_path_is_refused_not_estimated():
    """Sans ce refus, la borne retomberait silencieusement sur `B4 − B1` : une valeur
    plausible, mais qui mesure un chemin plus court sans le dire."""
    with pytest.raises(CampaignError, match="incomplet"):
        PassiveBoundaries(None, 0, 1 * MS, 2 * MS, 3 * MS, None)  # type: ignore[arg-type]


def test_the_bound_never_silently_falls_back_to_a_shorter_path():
    complete = observation(boundaries=boundaries(decision=6 * MS))
    assert complete.local_lower_bound_ns == 14 * MS
    with pytest.raises(CampaignError):
        boundaries(decision=6 * MS).__class__(None, 0, 1 * MS, 2 * MS, 3 * MS, None)  # type: ignore[arg-type]


# ============================================= §15 — pas d'arrêt opportuniste


def policy(**kw) -> StoppingPolicy:
    base = dict(
        declared_at_ns=0, declared_by="responsable de la campagne",
        min_days=5, min_sessions=2, min_clusters_per_cell=20,
        min_burst_p95_clusters=15, min_burst_p99_clusters=5,
        max_relative_ci_width=0.30,
        required_clock_qualification="CLOCK_QUALIFIED_LOCAL_ONLY",
        inference_mode=InferenceMode.FIXED_HORIZON,
        fixed_horizon_days=10,
    )
    return StoppingPolicy(**{**base, **kw})


def anytime_policy(**kw) -> StoppingPolicy:
    return policy(inference_mode=InferenceMode.ANYTIME_VALID,
                  rho=rho_for_target(200), fixed_horizon_days=None, **kw)


def six_days() -> list[PassiveObservation]:
    obs: list[PassiveObservation] = []
    for d in range(6):
        obs += many(80, total_ns=8 * MS, day=f"2026-08-0{d + 1}",
                    cluster_prefix=f"D{d}C", per_cluster=2, jitter_ns=6 * MS)
        obs += many(60, total_ns=30 * MS, burst=BurstState.BURST_P95,
                    day=f"2026-08-0{d + 1}", cluster_prefix=f"D{d}B", per_cluster=2,
                    jitter_ns=20 * MS)
        obs += many(30, total_ns=50 * MS, burst=BurstState.BURST_P99,
                    day=f"2026-08-0{d + 1}", cluster_prefix=f"D{d}X", per_cluster=2,
                    jitter_ns=30 * MS)
    return obs


def test_a_policy_declared_after_the_first_observation_is_invalid():
    """Une politique écrite après avoir vu le résultat n'est pas une politique : c'est
    le résultat lui-même, reformulé."""
    obs = many(60, total_ns=8 * MS, per_cluster=2)
    a = assess_stopping(policy(declared_at_ns=10**9), coverage(obs),
                        summarise_by_cell(obs), first_observation_ns=0, clock=clock())
    assert a.decision is StopDecision.POLICY_INVALID
    assert "a posteriori" in a.reasons[0]


def test_a_policy_without_an_author_cannot_be_created():
    with pytest.raises(CampaignError, match="auteur"):
        policy(declared_by="  ")


def test_a_policy_supposing_another_clock_qualification_is_invalid():
    obs = many(60, total_ns=8 * MS, per_cluster=2)
    a = assess_stopping(policy(required_clock_qualification="CLOCK_QUALIFIED"),
                        coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.POLICY_INVALID


def test_insufficient_coverage_continues_regardless_of_the_measured_value():
    obs = many(60, total_ns=8 * MS, per_cluster=2)
    a = assess_stopping(policy(), coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.CONTINUE
    assert any("journées" in r for r in a.reasons)


def test_under_fixed_horizon_a_narrow_interval_cannot_trigger_the_stop():
    """La largeur est un diagnostic. Sous horizon gelé, seule la durée déclarée arrête —
    sinon la couverture de l'intervalle final n'est plus garantie du tout."""
    obs = six_days()
    lenient = policy(min_sessions=1, max_relative_ci_width=0.0001, fixed_horizon_days=10)
    a = assess_stopping(lenient, coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.CONTINUE
    assert not a.confidence_interval_is_optimistic


def test_under_fixed_horizon_the_frozen_duration_is_the_only_stopping_criterion():
    obs = six_days()
    reached = policy(min_sessions=1, max_relative_ci_width=10.0, fixed_horizon_days=6)
    a = assess_stopping(reached, coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.MAY_STOP
    assert "horizon gelé atteint" in a.reasons[0]
    assert not a.confidence_interval_is_optimistic


def test_a_wide_interval_never_prolongs_a_fixed_horizon_campaign():
    """Prolonger parce que l'intervalle est large est un arrêt dépendant des données par
    l'autre bout."""
    obs = six_days()
    strict = policy(min_sessions=1, max_relative_ci_width=0.0001, fixed_horizon_days=6)
    a = assess_stopping(strict, coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.MAY_STOP
    assert any("diagnostic seulement" in r for r in a.reasons)


def test_under_anytime_valid_the_sequence_width_may_decide():
    """La garantie étant simultanée dans le temps, arrêter sur la largeur reste valide."""
    obs = six_days()
    a = assess_stopping(anytime_policy(min_days=1, min_sessions=1,
                                       max_relative_ci_width=10.0),
                        coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.MAY_STOP
    assert a.inference_mode is InferenceMode.ANYTIME_VALID


def test_an_anytime_valid_policy_needs_its_boundary_declared_in_advance():
    with pytest.raises(CampaignError, match="ρ déclaré"):
        policy(inference_mode=InferenceMode.ANYTIME_VALID, rho=None)


def test_a_fixed_horizon_policy_needs_its_duration_frozen_in_advance():
    with pytest.raises(CampaignError, match="durée gelée"):
        policy(fixed_horizon_days=None, fixed_horizon_clusters=None)


def test_a_data_dependent_stop_under_ordinary_inference_is_invalid_not_reserved():
    """Pas une réserve à côté du chiffre : il n'y a pas de chiffre à publier."""
    assert inference_validity(policy(), stopped_on_observed_uncertainty=True) is (
        InferenceValidity.SEQUENTIAL_INFERENCE_INVALID
    )
    assert inference_validity(policy(), stopped_on_observed_uncertainty=False) is (
        InferenceValidity.VALID
    )
    assert inference_validity(anytime_policy(), True) is InferenceValidity.VALID


def test_the_policy_fingerprint_changes_with_its_content():
    assert policy().fingerprint != policy(min_days=6).fingerprint
    assert policy().fingerprint == policy().fingerprint


# ============================================= §14 — stabilité séquentielle


def test_the_stability_trace_grows_one_snapshot_per_day():
    obs: list[PassiveObservation] = []
    for d in range(4):
        obs += many(50, total_ns=8 * MS, day=f"2026-08-0{d + 1}",
                    cluster_prefix=f"D{d}C", per_cluster=2)
    trace = stability_trace(obs)
    assert [s.day for s in trace] == ["2026-08-01", "2026-08-02", "2026-08-03",
                                      "2026-08-04"]
    assert trace[-1].cumulative_clusters > trace[0].cumulative_clusters


def test_a_settled_estimate_is_reported_stable():
    obs: list[PassiveObservation] = []
    for d in range(5):
        obs += many(50, total_ns=8 * MS, day=f"2026-08-0{d + 1}",
                    cluster_prefix=f"D{d}C", per_cluster=2)
    assert is_stable(stability_trace(obs))


def test_a_drifting_estimate_is_not_reported_stable():
    obs: list[PassiveObservation] = []
    for d in range(5):
        obs += many(50, total_ns=(8 + 12 * d) * MS, day=f"2026-08-0{d + 1}",
                    cluster_prefix=f"D{d}C", per_cluster=2)
    assert not is_stable(stability_trace(obs))


def test_one_day_is_never_enough_to_call_it_stable():
    assert not is_stable(stability_trace(many(50, total_ns=8 * MS, per_cluster=2)))


# ============================================= verdicts et budget


def admissible(horizon=NS_PER_SECOND, maximum=200 * MS) -> AdmissibleLatency:
    return AdmissibleLatency(horizon, maximum, source="politique de risque v1",
                             declared_at_ns=0, engine_id="moteur-de-test",
                             gates_passed=True)


def test_admissible_latency_must_be_declared_with_a_source():
    with pytest.raises(CampaignError, match="source déclarée"):
        AdmissibleLatency(NS_PER_SECOND, 200 * MS, source="  ", declared_at_ns=0,
                          engine_id="m")


def test_a_signal_specific_budget_must_name_its_engine():
    """Un Lmax sans moteur serait une croyance sur l'alpha réintroduite dans un test
    conçu pour en être indépendant."""
    with pytest.raises(CampaignError, match="moteur nommé"):
        AdmissibleLatency(NS_PER_SECOND, 200 * MS, source="politique", declared_at_ns=0)


def test_admissible_latency_cannot_exceed_its_horizon():
    with pytest.raises(CampaignError, match="fenêtre est déjà close"):
        AdmissibleLatency(100 * MS, 200 * MS, source="x", declared_at_ns=0,
                          engine_id="m")


def test_a_bound_already_too_slow_excludes_conclusively():
    """Même en supposant courtier instantané, aucune file et exécution immédiate."""
    obs = many(80, total_ns=400 * MS, per_cluster=2)
    v, why = passive_verdict(summarise_cell(obs), admissible())
    assert v is PassiveVerdict.PASSIVE_LATENCY_EXCLUDED
    assert "instantané" in why


def test_a_fast_bound_only_means_not_excluded():
    obs = many(80, total_ns=8 * MS, per_cluster=2)
    v, why = passive_verdict(summarise_cell(obs), admissible())
    assert v is PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED
    assert "peut encore exclure" in why


def test_too_few_clusters_stays_indeterminate():
    obs = many(200, total_ns=8 * MS, per_cluster=100)
    v, _ = passive_verdict(summarise_cell(obs), admissible())
    assert v is PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE


def test_the_stress_pipeline_never_renders_the_main_verdict():
    """Sa charge est délibérément excessive et ne décrit aucune architecture envisagée."""
    obs = [
        observation(boundaries=boundaries(compute=400 * MS, start=i * 10 * MS),
                    cell=cell(pipeline=PipelineMode.STRESS), cluster_id=f"C{i // 2}")
        for i in range(80)
    ]
    v, why = passive_verdict(summarise_cell(obs), admissible())
    assert v is PassiveVerdict.PASSIVE_MEASUREMENT_INVALID
    assert "STRESS" in why


def test_an_unqualified_clock_invalidates_the_measurement():
    obs = many(80, total_ns=8 * MS, per_cluster=2)
    v, _ = passive_verdict(summarise_cell(obs), admissible(),
                           clock=clock(monotonic_failures=1))
    assert v is PassiveVerdict.PASSIVE_MEASUREMENT_INVALID


def test_the_remaining_budget_is_what_q42_must_fit_into():
    obs = many(80, total_ns=120 * MS, per_cluster=2)
    budget = latency_budget_ns(summarise_cell(obs), admissible(maximum=200 * MS))
    assert 70 * MS <= budget <= 85 * MS


def test_a_negative_budget_means_the_horizon_is_already_gone():
    obs = many(80, total_ns=400 * MS, per_cluster=2)
    assert latency_budget_ns(summarise_cell(obs), admissible(maximum=200 * MS)) < 0


# ============================================= §25 — embranchement Q42


def test_cost_exclusion_makes_q42_pointless():
    p, why = q42_priority(True, PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED)
    assert p is Q42Priority.NOT_PRIORITARY_COST
    assert "coût" in why


def test_passive_exclusion_makes_q42_pointless():
    """La partie inconnue de la latence ne peut qu'aggraver le constat."""
    p, _ = q42_priority(False, PassiveVerdict.PASSIVE_LATENCY_EXCLUDED)
    assert p is Q42Priority.NOT_PRIORITARY_LATENCY


def test_q42_becomes_rational_only_when_the_horizon_survives_both():
    p, _ = q42_priority(False, PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED)
    assert p is Q42Priority.RATIONAL


def test_an_indeterminate_bound_does_not_justify_funding_q42():
    p, _ = q42_priority(False, PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE)
    assert p is Q42Priority.UNDETERMINED


# ============================================= §21 — ancrage de la capturabilité


def test_a_local_anchor_makes_capturability_an_upper_bound():
    """Le mouvement survenu avant la réception locale est invisible et n'est donc jamais
    compté comme perdu : la fraction capturable en ressort surestimée."""
    ci = capturability_input(many(40, total_ns=8 * MS, per_cluster=2), clock())
    assert ci.anchor is CapturabilityAnchor.LOCAL_RECEIVE_ANCHOR
    assert ci.scope is CapturabilityScope.POST_RECEIVE_ONLY
    assert ci.is_upper_bound_of_capturability
    assert ci.result_name == "POST_RECEIVE_CAPTURABILITY"


def provider_anchored(n=40):
    return [
        observation(boundaries=boundaries(provider=i * 10 * MS - 40 * MS,
                                          start=i * 10 * MS),
                    provider_qualified=True, cluster_id=f"C{i // 2}")
        for i in range(n)
    ]


def test_a_provider_anchor_does_not_reach_the_market_event():
    """L'horodatage fournisseur ignore appariement, agrégation et délai interne
    précédant la publication : il reste une borne optimiste, pas la référence
    économique."""
    qualified = clock(measured_uncertainty_ns=200_000,
                      intersystem_uncertainty_declared_unknown=False)
    ci = capturability_input(provider_anchored(), qualified)
    assert ci.anchor is CapturabilityAnchor.PROVIDER_EVENT_ANCHOR
    assert ci.scope is CapturabilityScope.PROVIDER_TO_ACTION
    assert ci.result_name == "PROVIDER_ANCHORED_CAPTURABILITY"
    assert ci.is_upper_bound_of_capturability
    assert int(ci.latency_samples_ns[0]) == 49 * MS


def test_the_three_scopes_are_never_merged():
    """Trois estimandes distincts ne se fusionnent pas dans une seule distribution."""
    qualified = clock(measured_uncertainty_ns=200_000,
                      intersystem_uncertainty_declared_unknown=False)
    local = capturability_input(many(40, total_ns=8 * MS, per_cluster=2), clock())
    provider = capturability_input(provider_anchored(), qualified)
    assert not local.mergeable_with(provider)
    assert local.mergeable_with(local)


def test_a_sliding_horizon_end_creates_a_different_estimand():
    """Déplacer l'ancre sans fixer la fin de l'horizon prolongerait la fenêtre de
    `t_ancre − t_marché` et fabriquerait du mouvement capturable."""
    fixed = capturability_input(many(40, total_ns=8 * MS, per_cluster=2), clock())
    sliding = capturability_input(many(40, total_ns=8 * MS, per_cluster=2), clock(),
                                  horizon_end_policy=HorizonEndPolicy.ANCHORED_TO_ORIGIN)
    assert not fixed.creates_extended_window
    assert sliding.creates_extended_window
    assert not fixed.mergeable_with(sliding)


def test_post_receive_exclusion_concludes_but_non_exclusion_does_not():
    """Même en offrant gratuitement dissémination, trajet fournisseur et réseau entrant,
    si la latence interne suffit à éliminer l'horizon, l'exclusion est forte."""
    ci = capturability_input(many(40, total_ns=8 * MS, per_cluster=2), clock())
    assert "exclusion concluante" in ci.interpret(excluded=True)
    assert "ne qualifie en rien" in ci.interpret(excluded=False)
    assert "POST_RECEIVE_CAPTURABILITY" in ci.interpret(excluded=False)


def test_the_capturability_sample_is_conditional_on_its_cell():
    with pytest.raises(CampaignError, match="une cellule"):
        capturability_input(
            [observation(), observation(cell=cell(burst_state=BurstState.BURST_P99))],
            clock(),
        )


def test_the_conditional_sample_feeds_phase_zero_directly():
    """La distribution transmise est celle des états où le signal se déclencherait."""
    from feasibility.latency import phase0_residual

    rng = np.random.default_rng(4)
    n = 4_000
    ts = np.arange(n, dtype=np.int64) * 10 * MS
    prices = 2400.0 + np.cumsum(rng.normal(0, 0.02, n))
    clusters = np.arange(n) // 200
    starts = np.arange(50, n - 200, 60)
    signs = np.ones_like(starts)

    ci = capturability_input(
        many(60, total_ns=300 * MS, burst=BurstState.BURST_P95, per_cluster=2), clock()
    )
    res = phase0_residual(ts, prices, clusters, starts, signs,
                          ci.latency_samples_ns, 500 * MS, 0.30, rng=rng)
    assert res.consumed_fraction_p50 > 0.0
    assert res.events == starts.size


# ============================================= couverture et rapports


def test_coverage_counts_independent_clusters_not_observations():
    obs = many(200, total_ns=8 * MS, burst=BurstState.BURST_P95,
               cluster_prefix="B", per_cluster=50)
    c = coverage(obs)
    assert c.observations == 200
    assert c.burst_clusters_p95 == 4


def test_coverage_separates_macro_windows():
    obs = many(20, total_ns=8 * MS, per_cluster=5)
    obs += [observation(cluster_id="M1", macro_window=True)]
    assert coverage(obs).macro_windows == 1


def test_the_hourly_report_is_an_instrumentation_check():
    out = hourly_report(many(40, total_ns=8 * MS, per_cluster=2))
    assert "CONTRÔLE D'INSTRUMENTATION" in out
    assert "borne locale" in out
    assert "retard de boucle" in out


def test_the_hourly_report_survives_an_empty_start():
    assert hourly_report([]) == "aucune observation"


def test_the_daily_report_states_what_was_not_measured():
    """Un rapport qui tairait le segment courtier se lirait comme une latence complète."""
    obs = many(60, total_ns=8 * MS, per_cluster=2)
    obs += many(40, total_ns=60 * MS, burst=BurstState.BURST_P95,
                cluster_prefix="B", per_cluster=2)
    out = daily_report(obs, clock())
    assert "aucun ordre émis" in out
    assert "traitement courtier" in out
    assert "BURST_P95" in out
    assert "COUVERTURE DE RAFALE" in out


def test_the_daily_report_breaks_down_only_the_target_pipeline():
    obs = many(40, total_ns=8 * MS, per_cluster=2)
    obs += [
        observation(boundaries=boundaries(compute=300 * MS, start=i * 10 * MS),
                    cell=cell(pipeline=PipelineMode.STRESS), cluster_id=f"S{i // 2}")
        for i in range(40)
    ]
    out = daily_report(obs, clock())
    decomposition = out.split("DÉCOMPOSITION")[1]
    assert "PIPELINE_TARGET" in decomposition
    assert "PIPELINE_STRESS" not in decomposition


# ============================================= Q61-A — exclusion sans signal


def price_path(n=4_000, seed=3, drift=0.02):
    rng = np.random.default_rng(seed)
    ts = np.arange(n, dtype=np.int64) * 10 * MS
    prices = 2400.0 + np.cumsum(rng.normal(0, drift, n))
    return ts, prices


def floor_(value=0.35, order_type=OrderType.AGGRESSIVE, **kw) -> CostFloor:
    base = dict(order_type=order_type, certain_commission=value, mandatory_fees=0.0,
                source="barème contractuel du courtier, v1")
    return CostFloor(**{**base, **kw})


def opportunities(starts, span_ns, **kw) -> OpportunitySet:
    base = dict(starts_ns=starts, horizon_ns=500 * MS, span_ns=span_ns)
    return OpportunitySet(**{**base, **kw})


def capture_for(latency_ns, n=4_000, seed=3, drift=0.02, horizon=500 * MS):
    ts, prices = price_path(n, seed, drift)
    starts = np.arange(50, n - 200, 40)
    cap = oracle_capturable(
        ts, prices, starts, np.full(60, latency_ns, dtype=np.int64), horizon,
        CapturabilityScope.POST_RECEIVE_ONLY, cluster_ids=np.arange(n) // 100,
    )
    return cap, ts


def test_the_oracle_is_computed_without_any_signal_definition():
    """Direction connue d'avance et sortie parfaite : aucun moteur ne peut faire mieux."""
    cap, _ = capture_for(20 * MS)
    assert cap.gross.size > 0
    assert cap.quantiles.p90 > 0.0
    assert cap.exhausted_fraction == 0.0


def test_a_latency_beyond_the_horizon_captures_nothing_but_stays_in_the_sample():
    cap, _ = capture_for(900 * MS)
    assert cap.exhausted_fraction == 1.0
    assert cap.quantiles.p90 == 0.0
    assert cap.gross.size > 0


def test_the_oracle_captures_less_as_latency_grows():
    fast, _ = capture_for(10 * MS)
    slow, _ = capture_for(400 * MS)
    assert slow.quantiles.p90 < fast.quantiles.p90


# ---- le cœur de la correction : un quantile n'exclut jamais à lui seul


def test_a_low_quantile_never_excludes_when_the_tail_survives():
    """92 % des situations impossibles, 8 % très favorables : `p90 ≤ coût plancher` est
    vrai, et pourtant un moteur qui ne trade que ces 8 % garde de la valeur. C'est
    exactement le type de stratégie sélective que la phase 0 ne doit pas supprimer."""
    gross = np.array([0.20] * 920 + [3.00] * 80)
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, gross, 500 * MS, CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=1_000 * NS_PER_SECOND, clusters=50,
                        exhausted_fraction=0.0)

    assert cap.quantiles.p90 <= 0.35              # le raccourci précédent aurait exclu

    a = assess_oracle(cap, floor_(0.35),
                      opportunities(starts, 1_000 * NS_PER_SECOND,
                                    overlap_policy=OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE),
                      delta_meu=0.05)
    verdict, why = oracle_verdict(a, minimum_frequency_per_second=1 / 86_400,
                                  minimum_contribution_per_second=1e-9)
    assert verdict is OracleVerdict.ORACLE_NOT_EXCLUDED
    assert "ne dit rien de la capacité d'un moteur" in why


def no_survivor_case():
    gross = np.full(600, 0.10)
    starts = np.arange(600, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, gross, 500 * MS, CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=600 * NS_PER_SECOND, clusters=40, exhausted_fraction=0.0)
    return cap, assess_oracle(cap, floor_(0.35),
                              opportunities(starts, 600 * NS_PER_SECOND), delta_meu=0.05)


def test_zero_survivors_observed_is_not_an_impossibility():
    """« Je n'en ai pas vu » ne devient jamais « cela n'existe pas ». Un échantillon
    fini borne une fréquence, il ne démontre pas une absence."""
    _, a = no_survivor_case()
    verdict, why = oracle_verdict(a, 1 / 86_400, 1e-9)
    assert verdict is OracleVerdict.ORACLE_NO_SURVIVOR_OBSERVED
    assert not verdict.excludes
    assert "ne démontre pas l'absence" in why


def test_universal_impossibility_requires_a_demonstrated_argument():
    """Réservée à une borne analytique sur tout le domaine admissible."""
    _, a = no_survivor_case()
    proven = AnalyticalImpossibility(
        holds=True, supremum=0.0,
        argument="horizon inférieur à la latence minimale certaine du chemin",
        declared_by="protocole Q19",
    )
    verdict, why = oracle_verdict(a, 1 / 86_400, 1e-9, analytical=proven)
    assert verdict is OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE
    assert verdict.excludes
    assert "domaine admissible" in why


def test_an_impossibility_without_argument_cannot_be_declared():
    with pytest.raises(CampaignError, match="absence d'observation"):
        AnalyticalImpossibility(holds=True, supremum=0.0, argument="  ",
                                declared_by="quelqu'un")


def test_zero_survivors_becomes_conclusive_only_through_frequency():
    """Le résultat empirique conclut lorsque sa borne supérieure est déjà incompatible
    avec la fréquence minimale."""
    _, a = no_survivor_case()
    verdict, why = oracle_verdict(a, minimum_frequency_per_second=10.0,
                                  minimum_contribution_per_second=1e-9)
    assert verdict is OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE
    assert verdict.excludes
    assert "DEPENDENCE_ROBUST_BOUND" in why


def test_the_rate_upper_bound_is_never_zero():
    """Avec zéro succès observé, le taux réel reste borné, pas nul."""
    _, a = no_survivor_case()
    assert a.profitable == 0
    assert a.profitable_rate_upper > 0.0


# ---- §4-6 : disjoint ≠ indépendant


def test_the_rarity_bound_degrades_when_independence_is_not_proven():
    """Même disjointes, plusieurs opportunités partagent régime, séance, tendance,
    événement macro, volatilité et liquidité."""
    naive = rarity_bound(0, 2_000, 0, 0.05)
    robust = rarity_bound(0, 2_000, 40, 0.05)
    proven = rarity_bound(0, 2_000, 40, 0.05, independence_proven=True)

    assert naive.quality is BoundQuality.RAW_EVENT_BOUND
    assert not naive.quality.usable_for_verdict
    assert robust.quality is BoundQuality.DEPENDENCE_ROBUST_BOUND
    assert proven.quality is BoundQuality.QUALIFIED_INDEPENDENT_BOUND
    # La borne robuste, portée sur 40 épisodes, est bien plus large que celle sur 2 000.
    assert robust.upper > proven.upper


def test_a_raw_bound_alone_cannot_produce_a_frequency_exclusion():
    gross = np.full(600, 0.10)
    starts = np.arange(600, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, gross, 500 * MS, CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=600 * NS_PER_SECOND, clusters=0, exhausted_fraction=0.0)
    a = assess_oracle(cap, floor_(0.35), opportunities(starts, 600 * NS_PER_SECOND),
                      delta_meu=0.05)
    assert a.rarity.quality is BoundQuality.RAW_EVENT_BOUND
    assert oracle_verdict(a, 10.0, 1e-9, min_clusters=0)[0] is not (
        OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE
    )


# ---- §12-13 : deux oracles


def test_a_policy_cooldown_never_enters_the_physical_oracle():
    """Un cooldown arbitraire réduit V_oracle_max et peut fabriquer une exclusion
    imputable à notre architecture, pas au marché."""
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    policy = opportunities(starts, 1_000 * NS_PER_SECOND, cooldown_ns=60 * NS_PER_SECOND,
                           cooldown_class=ConstraintClass.POLICY_CONSTRAINT,
                           overlap_policy=OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE)
    assert policy.kind is OracleKind.POLICY_ORACLE
    assert policy.physical_view().cooldown_ns == 0
    assert policy.physical_view().capacity > policy.capacity


def test_a_hard_cooldown_survives_into_the_physical_oracle():
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    hard = opportunities(starts, 1_000 * NS_PER_SECOND, cooldown_ns=60 * NS_PER_SECOND,
                         cooldown_class=ConstraintClass.HARD_CONSTRAINT,
                         concurrency_class=ConstraintClass.HARD_CONSTRAINT)
    assert hard.physical_view().cooldown_ns == 60 * NS_PER_SECOND


def test_the_assessment_records_which_oracle_it_used():
    _, a = no_survivor_case()
    assert a.kind in (OracleKind.PHYSICAL_ORACLE, OracleKind.POLICY_ORACLE)


# ---- §11 : le plancher le plus favorable parmi les modes autorisés


def test_a_global_exclusion_uses_the_cheapest_allowed_execution():
    """Sinon on éliminerait une famille parce que les ordres au marché coûtent trop
    cher, alors qu'une exécution passive compatible resterait viable."""
    market = floor_(0.30, observed_crossing=0.12)
    limit = floor_(0.05, order_type=OrderType.PASSIVE)
    assert most_favourable_floor([market, limit]) is limit
    assert most_favourable_floor([market, limit]).value < market.value


def test_floors_in_different_units_are_refused():
    a = floor_(0.30)
    b = CostFloor(OrderType.PASSIVE, 3.0, 0.0, unit="USD/lot",
                  source="barème contractuel")
    with pytest.raises(CampaignError, match="unités différentes"):
        most_favourable_floor([a, b])


def test_no_allowed_mode_is_refused():
    with pytest.raises(CampaignError, match="aucun mode d'exécution"):
        most_favourable_floor([])


def test_level_b_excludes_when_opportunities_are_too_rare():
    """Des opportunités existent, mais aucune stratégie réelle n'atteindrait la
    fréquence exigée."""
    gross = np.array([0.10] * 998 + [5.00] * 2)
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, gross, 500 * MS, CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=1_000 * NS_PER_SECOND, clusters=40, exhausted_fraction=0.0)
    a = assess_oracle(cap, floor_(0.35), opportunities(starts, 1_000 * NS_PER_SECOND),
                      delta_meu=0.05)
    verdict, why = oracle_verdict(a, minimum_frequency_per_second=50.0,
                                  minimum_contribution_per_second=1e-9)
    assert verdict is OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE
    assert "trop rarement" in why or "plancher" in why


def test_capacity_cannot_conclude_without_a_single_observed_survivor():
    """Sans survivant, la valeur mesurée vaut zéro par absence d'observation, pas par
    impossibilité : conclure ici referait l'erreur du niveau A."""
    _, a = no_survivor_case()
    assert a.capacity_value_per_second == 0.0
    verdict, _ = oracle_verdict(a, 1 / 86_400, minimum_contribution_per_second=1_000.0)
    assert verdict is OracleVerdict.ORACLE_NO_SURVIVOR_OBSERVED


def test_level_c_excludes_on_economic_capacity():
    gross = np.array([0.10] * 900 + [0.45] * 100)
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, gross, 500 * MS, CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=1_000 * NS_PER_SECOND, clusters=40, exhausted_fraction=0.0)
    a = assess_oracle(cap, floor_(0.35), opportunities(starts, 1_000 * NS_PER_SECOND),
                      delta_meu=0.01)
    verdict, why = oracle_verdict(a, minimum_frequency_per_second=1 / 86_400,
                                  minimum_contribution_per_second=1_000.0)
    assert verdict is OracleVerdict.ORACLE_ECONOMIC_CAPACITY_NON_VIABLE
    assert "capacité économique" in why


def test_too_few_clusters_leaves_the_oracle_indeterminate():
    starts = np.arange(60, dtype=np.int64) * NS_PER_SECOND
    cap = OracleCapture(starts, np.full(60, 1.0), 500 * MS,
                        CapturabilityScope.POST_RECEIVE_ONLY,
                        span_ns=60 * NS_PER_SECOND, clusters=3, exhausted_fraction=0.0)
    a = assess_oracle(cap, floor_(0.35), opportunities(starts, 60 * NS_PER_SECOND),
                      delta_meu=0.05)
    assert oracle_verdict(a, 1 / 86_400, 1e-9)[0] is OracleVerdict.ORACLE_INDETERMINATE


# ---- §7-9 : un mouvement ne compte qu'une fois


def test_five_hundred_ticks_of_one_move_are_not_five_hundred_opportunities():
    """Sans politique de chevauchement, un seul mouvement gonflerait la fréquence et la
    valeur économique de l'oracle."""
    starts = np.arange(500, dtype=np.int64) * MS       # 500 départs en 0,5 s
    surplus = np.full(500, 1.0)
    disjoint = opportunities(starts, 500 * MS)
    assert disjoint.select(surplus).size == 1


def test_the_capacity_bounds_how_many_positions_the_oracle_can_take():
    starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    o = opportunities(starts, 1_000 * NS_PER_SECOND, cooldown_ns=500 * MS,
                      max_concurrent_positions=2,
                      overlap_policy=OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE)
    assert o.capacity == 2 * (1_000 * NS_PER_SECOND) // (500 * MS + 500 * MS)
    # La capacité est un plafond : la sélection ne dépasse ni ce plafond ni le stock.
    assert o.select(np.full(1_000, 1.0)).size == min(o.capacity, 1_000)

    narrow = opportunities(starts, 1_000 * NS_PER_SECOND, horizon_ns=100 * NS_PER_SECOND,
                           max_concurrent_positions=1,
                           overlap_policy=OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE)
    assert narrow.capacity == 10
    assert narrow.select(np.full(1_000, 1.0)).size == 10


def test_disjoint_selection_prefers_the_valuable_windows():
    starts = np.array([0, 100 * MS, 600 * MS], dtype=np.int64)
    surplus = np.array([0.1, 5.0, 0.2])
    kept = opportunities(starts, NS_PER_SECOND).select(surplus)
    assert 1 in kept.tolist()


def test_concurrency_and_span_must_be_declared_sanely():
    starts = np.arange(10, dtype=np.int64) * NS_PER_SECOND
    with pytest.raises(CampaignError, match="position simultanée"):
        opportunities(starts, NS_PER_SECOND, max_concurrent_positions=0)
    with pytest.raises(CampaignError, match="durée d'observation"):
        opportunities(starts, 0)


# ---- §11-15 : Q63, le plancher de coûts


def test_a_cost_floor_needs_a_source():
    with pytest.raises(CampaignError, match="source déclarée"):
        CostFloor(OrderType.AGGRESSIVE, 0.3, 0.0, source="  ")


def test_a_passive_order_cannot_put_the_crossing_in_its_floor():
    """Un ordre passif peut obtenir un prix différent du scénario agressif."""
    with pytest.raises(CampaignError, match="ordre passif"):
        floor_(order_type=OrderType.PASSIVE, observed_crossing=0.2)
    passive = floor_(0.05, order_type=OrderType.PASSIVE)
    assert passive.value == 0.05


def test_a_credit_is_signed_and_lowers_the_floor():
    """Transformer un crédit possible en coût positif pour faciliter une exclusion est
    interdit."""
    plain = floor_(0.30)
    with_credit = floor_(0.30, signed_credits=-0.08)
    assert with_credit.value < plain.value


def test_an_estimated_component_must_enter_by_its_lower_bound():
    with pytest.raises(CampaignError, match="borne inférieure"):
        floor_(0.30, estimated_components_use_lower_bound=False)


def test_the_floor_is_a_lower_bound_not_a_central_estimate():
    aggressive = floor_(0.30, observed_crossing=0.10, mandatory_fees=0.02)
    assert aggressive.value == pytest.approx(0.42)


# ---- bornes exactes


def test_the_rate_upper_bound_matches_the_rule_of_three_at_zero_successes():
    assert clopper_pearson_upper(0, 100, 0.05) == pytest.approx(1 - 0.05 ** 0.01)
    assert clopper_pearson_upper(0, 1_000, 0.05) < clopper_pearson_upper(0, 100, 0.05)


def test_the_rate_upper_bound_always_exceeds_the_point_estimate():
    for k, n in ((1, 100), (10, 200), (37, 900)):
        assert clopper_pearson_upper(k, n, 0.05) > k / n


def test_the_rate_upper_bound_is_one_when_nothing_is_known():
    assert clopper_pearson_upper(0, 0, 0.05) == 1.0
    assert clopper_pearson_upper(5, 5, 0.05) == 1.0


# ============================================= §21 — état consolidé de la phase 0


def test_an_unexcluded_oracle_verdict_never_reports_as_excluding():
    assert not OracleVerdict.ORACLE_NO_SURVIVOR_OBSERVED.excludes
    assert not OracleVerdict.ORACLE_NOT_EXCLUDED.excludes
    assert not OracleVerdict.ORACLE_INDETERMINATE.excludes


@pytest.mark.parametrize("oracle", [
    OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE,
    OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE,
    OracleVerdict.ORACLE_ECONOMIC_CAPACITY_NON_VIABLE,
])
def test_phase0_can_exclude_before_any_signal_exists(oracle):
    state, _ = phase0_state(False, PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED, oracle)
    assert state is Phase0State.PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY


def test_cost_exclusion_dominates_every_latency_argument():
    state, _ = phase0_state(True, PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
                            OracleVerdict.ORACLE_NOT_EXCLUDED)
    assert state is Phase0State.PHASE0_EXCLUDED_BY_COST


def test_an_invalid_measurement_authorises_nothing():
    state, _ = phase0_state(True, PassiveVerdict.PASSIVE_MEASUREMENT_INVALID,
                            OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE)
    assert state is Phase0State.PHASE0_MEASUREMENT_INVALID


def test_ignorance_never_grants_permission():
    state, why = phase0_state(False, PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE,
                              OracleVerdict.ORACLE_NOT_EXCLUDED)
    assert state is Phase0State.PHASE0_INDETERMINATE
    assert "ne vaut pas permission" in why


def test_not_excluded_never_means_a_good_trade_is_possible():
    state, why = phase0_state(False, PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
                              OracleVerdict.ORACLE_NOT_EXCLUDED)
    assert state is Phase0State.PHASE0_NOT_EXCLUDED
    assert "ne dit rien de son existence" in why


# ============================================= §16 — sensibilité au découpage


def blocking(**kw) -> BlockingChoice:
    base = dict(block_ns=NS_PER_SECOND, source="autocorrélation observée, campagne pilote",
                version="v1")
    return BlockingChoice(**{**base, **kw})


def test_a_block_duration_must_declare_its_source():
    with pytest.raises(CampaignError, match="source déclarée"):
        blocking(source="  ")


def test_halving_the_block_produces_more_clusters():
    obs = many(200, total_ns=8 * MS, per_cluster=1, jitter_ns=6 * MS)
    sens = block_sensitivity(obs, blocking(block_ns=200 * MS), 100.0, NS_PER_SECOND)
    counts = [s.clusters for s in sens]
    assert counts == sorted(counts, reverse=True)


def test_a_verdict_that_survives_every_blocking_is_robust():
    obs = many(200, total_ns=8 * MS, per_cluster=1, jitter_ns=4 * MS)
    sens = block_sensitivity(obs, blocking(block_ns=200 * MS), 100.0, NS_PER_SECOND)
    assert blocking_is_robust(sens, threshold_ns=500 * MS)


def test_a_verdict_that_flips_between_blockings_is_not_a_verdict_about_latency():
    obs = many(200, total_ns=8 * MS, per_cluster=1, jitter_ns=4 * MS)
    sens = block_sensitivity(obs, blocking(block_ns=200 * MS), 100.0, NS_PER_SECOND)
    straddling = sens[0].ci_low_ns + (sens[0].ci_high_ns - sens[0].ci_low_ns) / 2
    fabricated = (
        BlockSensitivity(1, 10, 1.0, 0.0, straddling + 1e9),
        BlockSensitivity(2, 20, 1.0, straddling + 1e9, straddling + 2e9),
    )
    assert not blocking_is_robust(fabricated, threshold_ns=straddling + 5e8)


def test_a_single_blocking_is_never_declared_robust():
    assert not blocking_is_robust((BlockSensitivity(1, 10, 1.0, 0.0, 2.0),), 1.0)


# ============================================= §19 — effet observateur mesuré


def test_the_overhead_is_published_as_a_distribution():
    base = [1_000.0 + i for i in range(200)]
    inst = [b + 250 + (i % 40) for i, b in enumerate(base)]
    report = observer_overhead(base, inst)
    assert report.samples == 200
    assert report.p50_ns > 0
    assert report.p99_ns >= report.p95_ns >= report.p50_ns


def test_an_overhead_rounded_to_zero_is_refused_when_the_clock_advanced():
    """Sérialiser hors du chemin critique ne supprime ni lecture d'horloge, ni allocation,
    ni mise en file, ni contention."""
    base = [1_000.0] * 50
    with pytest.raises(CampaignError, match="arrondi à zéro"):
        observer_overhead(base, list(base))


def test_unpaired_series_are_refused():
    with pytest.raises(CampaignError, match="appariées"):
        observer_overhead([1.0, 2.0], [1.0])


def test_an_empty_benchmark_measures_nothing():
    with pytest.raises(CampaignError, match="aucun échantillon"):
        observer_overhead([], [])


# ============================================= §18 — comparaison de cadence


def test_unpaired_days_cannot_attribute_the_difference_to_the_cadence():
    """Les marchés n'étaient pas les mêmes."""
    ed = many(60, total_ns=8 * MS, per_cluster=2, day="2026-08-03")
    pe = [
        observation(boundaries=boundaries(compute=60 * MS, start=i * 10 * MS),
                    cell=cell(evaluation_mode=EvaluationMode.PERIODIC,
                              evaluation_period_ns=100 * MS),
                    cluster_id=f"P{i // 2}", day="2026-08-04")
        for i in range(60)
    ]
    c = compare_cadence(ed, pe, ComparisonDesign.UNPAIRED_DAYS)
    assert not c.attributable
    assert "non attribuable" in c.interpretation
    assert "rejeu apparié" in c.interpretation


def test_a_paired_replay_supports_attribution():
    ed = many(60, total_ns=8 * MS, per_cluster=2)
    pe = [
        observation(boundaries=boundaries(compute=60 * MS, start=i * 10 * MS),
                    cell=cell(evaluation_mode=EvaluationMode.PERIODIC,
                              evaluation_period_ns=100 * MS),
                    cluster_id=f"P{i // 2}")
        for i in range(60)
    ]
    c = compare_cadence(ed, pe, ComparisonDesign.PAIRED_REPLAY)
    assert c.attributable
    assert "même flux" in c.interpretation
    assert c.periodic_p95_ns > c.event_driven_p95_ns


def test_shadow_evaluation_also_supports_attribution():
    assert ComparisonDesign.SHADOW_EVALUATION.supports_attribution
    assert not ComparisonDesign.UNPAIRED_DAYS.supports_attribution


def test_both_modes_must_be_represented():
    with pytest.raises(CampaignError, match="deux modes"):
        compare_cadence(many(10, total_ns=8 * MS), [], ComparisonDesign.PAIRED_REPLAY)


# ============================================= §9 — collecte ≠ échantillon normatif


def freeze(at_ns=1_000, mode=InferenceMode.FIXED_HORIZON) -> ProtocolFreeze:
    return ProtocolFreeze(frozen_at_ns=at_ns, frozen_by="responsable de la campagne",
                          inference_mode=mode, fingerprint="abc123")


def test_data_collected_before_the_freeze_is_exploratory_not_lost():
    """La collecte peut démarrer immédiatement ; c'est le droit d'en tirer un verdict
    qui attend le gel."""
    f = freeze()
    assert f.status_of(500) is DataStatus.EXPLORATORY
    assert f.status_of(1_000) is DataStatus.NORMATIVE
    assert f.status_of(5_000) is DataStatus.NORMATIVE


def stamped(i: int, wall_ns: int) -> PassiveObservation:
    base = i * 10 * MS
    return PassiveObservation(
        boundaries=PassiveBoundaries(None, base, base + 1 * MS, base + 3 * MS,
                                     base + 8 * MS, base + 9 * MS,
                                     local_receive_wall_ns=wall_ns),
        market=MarketContext(1.2, 12.0, 60.0, 0.18, 0.5, 0.01, 0.5),
        host=HostLoad(2, 5, 100_000, 0.4, 10**8), cell=cell(),
        cluster_id=f"K{i}", day="2026-08-08",
        clock_grade=MeasurementGrade.EXACT_LOCAL,
        connection_state=ConnectionState.CONNECTED_STABLE, calendar_state="OPEN",
    )


def test_the_freeze_partitions_a_campaign_without_discarding_anything():
    before = [stamped(i, wall_ns=100 + i) for i in range(5)]
    after = [stamped(10 + i, wall_ns=2_000 + i) for i in range(4)]
    parts = freeze().partition(before + after)
    assert len(parts[DataStatus.EXPLORATORY]) == 5
    assert len(parts[DataStatus.NORMATIVE]) == 4
    assert sum(len(v) for v in parts.values()) == 9


# ============================================= §14-17 — Q64 dérive de Q1


def thresholds(**kw) -> EconomicThresholds:
    base = dict(
        primary=EconomicTarget.PER_UNIT_TIME,
        delta_meu=0.20, j_min_per_second=0.60 / 86_400,
        f_stat_min_per_second=1 / 86_400,
        q1_reference="Q1 v1 — alerte, unité $/oz, capital de référence 50 k$, "
                     "horizon d'évaluation trimestriel",
    )
    return EconomicThresholds(**{**base, **kw})


def test_economic_thresholds_must_reference_the_q1_target():
    """Les choisir parce qu'ils produisent une taille d'échantillon pratique
    inverserait le raisonnement."""
    with pytest.raises(CampaignError, match="cible définie par Q1"):
        thresholds(q1_reference="  ")


def test_the_economic_frequency_is_derived_not_invented():
    t = thresholds(delta_meu=0.20, j_min_per_second=0.60 / 86_400)
    assert t.derived_f_econ_min_per_second == pytest.approx(3 / 86_400)


def test_statistical_and_economic_frequency_floors_are_not_confused():
    """Le plancher effectif est le plus contraignant des deux, jamais leur mélange."""
    stat_binding = thresholds(f_stat_min_per_second=10 / 86_400)
    assert stat_binding.f_min_per_second == pytest.approx(10 / 86_400)

    econ_binding = thresholds(f_stat_min_per_second=1 / 86_400)
    assert econ_binding.f_min_per_second == pytest.approx(3 / 86_400)


def test_three_thresholds_encoding_one_requirement_are_flagged():
    """Si elles coïncident, seule la cible principale contraint réellement."""
    redundant = thresholds(delta_meu=0.20, j_min_per_second=0.60 / 86_400,
                           f_stat_min_per_second=3 / 86_400)
    assert redundant.redundancy_warning is not None
    assert "cible PER_UNIT_TIME" in redundant.redundancy_warning

    independent = thresholds(f_stat_min_per_second=30 / 86_400)
    assert independent.redundancy_warning is None


def test_a_non_positive_surplus_threshold_is_refused():
    with pytest.raises(CampaignError, match="positif"):
        thresholds(delta_meu=0.0)
