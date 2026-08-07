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
from feasibility.passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    AdmissibleLatency,
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
    )
    return StoppingPolicy(**{**base, **kw})


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


def test_stopping_on_the_width_criterion_flags_the_interval_as_optimistic():
    """Arrêter dès que l'intervalle est étroit sélectionne les échantillons homogènes :
    l'intervalle final sous-estime alors l'incertitude réelle."""
    obs: list[PassiveObservation] = []
    for d in range(6):
        obs += many(80, total_ns=8 * MS, day=f"2026-08-0{d + 1}",
                    cluster_prefix=f"D{d}C", per_cluster=2)
        obs += many(60, total_ns=30 * MS, burst=BurstState.BURST_P95,
                    day=f"2026-08-0{d + 1}", cluster_prefix=f"D{d}B", per_cluster=2)
        obs += many(30, total_ns=50 * MS, burst=BurstState.BURST_P99,
                    day=f"2026-08-0{d + 1}", cluster_prefix=f"D{d}X", per_cluster=2)
    lenient = policy(min_sessions=1, max_relative_ci_width=10.0)
    a = assess_stopping(lenient, coverage(obs), summarise_by_cell(obs), 0, clock())
    assert a.decision is StopDecision.MAY_STOP
    assert a.confidence_interval_is_optimistic


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
                             declared_at_ns=0)


def test_admissible_latency_must_be_declared_with_a_source():
    with pytest.raises(CampaignError, match="source déclarée"):
        AdmissibleLatency(NS_PER_SECOND, 200 * MS, source="  ", declared_at_ns=0)


def test_admissible_latency_cannot_exceed_its_horizon():
    with pytest.raises(CampaignError, match="fenêtre est déjà close"):
        AdmissibleLatency(100 * MS, 200 * MS, source="x", declared_at_ns=0)


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
    assert ci.anchor is CapturabilityAnchor.LOCAL_RECEIVE
    assert ci.is_upper_bound_of_capturability


def test_a_qualified_provider_anchor_removes_the_optimism():
    qualified = clock(measured_uncertainty_ns=200_000,
                      intersystem_uncertainty_declared_unknown=False)
    obs = [
        observation(boundaries=boundaries(provider=i * 10 * MS - 40 * MS,
                                          start=i * 10 * MS),
                    provider_qualified=True, cluster_id=f"C{i // 2}")
        for i in range(40)
    ]
    ci = capturability_input(obs, qualified)
    assert ci.anchor is CapturabilityAnchor.QUALIFIED_MARKET
    assert not ci.is_upper_bound_of_capturability
    assert int(ci.latency_samples_ns[0]) == 49 * MS


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
