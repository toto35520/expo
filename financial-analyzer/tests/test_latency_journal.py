"""Tests de la journalisation de latence (Q51).

Le module mesure ce qui est observable et déclare ce qui ne l'est pas. Chaque test vise
un cas où une décomposition non fondée, une horloge mal choisie ou un échantillon biaisé
produirait un chiffre crédible et faux.
"""

from __future__ import annotations

import pytest

from feasibility.latency_journal import (
    FEED_COMPONENTS,
    JOURNAL_VERSION,
    NS_PER_MS,
    NS_PER_SECOND,
    SUBMIT_ACK_COMPONENTS,
    BurstContext,
    BurstState,
    CampaignPolicy,
    ClockBasis,
    ClockMonitor,
    ClockReading,
    ClockSyncState,
    ClockSyncStatus,
    ConnectionState,
    EvaluationProbe,
    EventType,
    JournalError,
    JournalEvent,
    LatencyInterval,
    LatencyJournal,
    LatencyObservation,
    LatencyVerdictQ51,
    MeasurementQuality,
    Observability,
    PerturbationCheck,
    ProbePhase,
    broker_side_split,
    detect_interval_overlaps,
    enforce_contract,
    feed_latency,
    measurement_quality,
    messaging_layer_verdict,
    submit_to_ack,
)
from feasibility.observability import (
    AckSemantics,
    BoundaryQuality,
    BrokerConnectorCapability,
    ClockDomain,
    CorrectionMode,
    EvidenceType,
    EventSemantics,
    GranularityTest,
    LatencyBoundary,
    LatencyPath,
    MessageKind,
    SubmitReturnSemantics,
    Virtualization,
    build_matrix,
    qualify_clock,
)


def boundary(name: str, ts: int | None) -> LatencyBoundary:
    return LatencyBoundary(
        name, ts, ClockDomain.LOCAL_MONOTONIC,
        BoundaryQuality.EXACT_LOCAL if ts is not None else BoundaryQuality.UNKNOWN,
    )


def qualified_clock():
    g = GranularityTest(40, 48.0, 160.0, 0.0)
    return qualify_clock(
        host_id="H1", granularity_wall=g, granularity_monotonic=g, monotonic_failures=0,
        wall_discontinuities=0, drift_p95_ppm=1.0, measured_uncertainty_ns=200_000,
        correction_mode=CorrectionMode.SLEW, virtualization=Virtualization.BARE_METAL,
        suspend_events=0, sync_method="NTP", qualified_at_ns=0,
    )


def proven_connector() -> BrokerConnectorCapability:
    """Connecteur réaliste : l'accusé existe et est prouvé, mais le courtier
    n'horodate rien."""
    return BrokerConnectorCapability(
        connector_id="broker:demo", connector_version="1.4.2", broker="COURTIER",
        account_type="DEMO",
        submit_return_semantics=SubmitReturnSemantics.LOCAL_QUEUE_ACCEPTED,
        ack_semantics=AckSemantics.ORDER_RECEIVED,
        rejection_semantics="motif structuré fourni par le courtier",
        cancel_semantics="CANCEL_RECEIVED",
        order_active_observable=False, broker_receive_timestamp_available=False,
        broker_accept_timestamp_available=False, fill_timestamp_available=False,
        timestamp_clock_domain=None,
        events=(EventSemantics(
            event_name="BROKER_ACK", observable=True, meaning="accusé courtier",
            message_kind=MessageKind.BROKER_EVENT, timestamp_available=True,
            clock_domain=ClockDomain.BROKER, evidence_type=EvidenceType.CONTROLLED_TEST,
            evidence_id="TEST-2026-001", ordering_guaranteed=True,
        ),),
        reconciliation_available=True, qualification_status="QUALIFIED",
    )


def sync(state=ClockSyncState.SYNC_VERIFIED, uncertainty_ns=200_000) -> ClockSyncStatus:
    return ClockSyncStatus(
        method="NTP", source="pool", estimated_offset_ns=1_000_000,
        estimated_uncertainty_ns=uncertainty_ns, last_sync_wall_ns=0,
        drift_ppm=0.5, state=state,
    )


def burst(state=BurstState.NORMAL, rate=12.0) -> BurstContext:
    return BurstContext(
        state=state, tick_rate_100ms=rate * 0.1, tick_rate_1s=rate,
        tick_rate_5s=rate * 5, spread=0.18, spread_percentile=0.5,
    )


def reading(wall: int, mono: int) -> ClockReading:
    return ClockReading(wall_ns=wall, monotonic_ns=mono)


def journal() -> LatencyJournal:
    return LatencyJournal(
        session_id="S1", host_boot_id="B1", process_start_wall_ns=0,
        software_commit="abc123", connector_version="C1", clock_sync=sync(),
        account_fingerprint="pseudonymisé",
    )


def event(event_type=EventType.BROKER_ACK, **kw) -> JournalEvent:
    base = dict(
        journal_event_id=f"JRN-{event_type.value}",
        event_type=event_type,
        clock=reading(1_000, 1_000),
        logical_order_id="ORD-1",
        submission_attempt_id="ATT-1",
    )
    base.update(kw)
    return JournalEvent(**base)


def observation(bound_ns: int, cluster: str = "C1", **kw) -> LatencyObservation:
    base = dict(
        trigger_wall_ns=0,
        session_id="S1",
        burst=burst(),
        connection_state=ConnectionState.CONNECTED_STABLE,
        intervals=(
            LatencyInterval("submit_to_ack_latency", bound_ns, Observability.AGGREGATE_ONLY,
                            ClockBasis.MONOTONIC, SUBMIT_ACK_COMPONENTS),
        ),
        clock_uncertainty_ns=200_000,
        quality=MeasurementQuality.MEASUREMENT_VALID,
        cluster_id=cluster,
    )
    base.update(kw)
    return LatencyObservation(**base)


# ------------------------------------------------------------------ observabilité


def test_aggregate_must_declare_what_it_cannot_separate():
    """Sans cette liste, rien n'empêche de rebaptiser un agrégat d'après l'une de ses
    composantes — « latence réseau », « latence courtier »."""
    with pytest.raises(JournalError, match="composantes qu'il ne sépare pas"):
        LatencyInterval("submit_to_ack_latency", 5_000_000,
                        Observability.AGGREGATE_ONLY, ClockBasis.MONOTONIC, contains=())


def test_unidentifiable_component_carries_no_duration():
    """Une valeur absente reste absente : elle n'est pas estimée."""
    with pytest.raises(JournalError, match="ne porte pas de durée"):
        LatencyInterval("broker_processing", 3_000_000,
                        Observability.NOT_IDENTIFIABLE, ClockBasis.CROSS_SYSTEM)


def test_negative_duration_points_at_the_wrong_clock():
    with pytest.raises(JournalError, match="horloge monotone"):
        LatencyInterval("compute", -5, Observability.OBSERVED, ClockBasis.MONOTONIC)


def test_aggregate_is_not_decomposable_into_its_parts():
    interval = LatencyInterval(
        "submit_to_ack_latency", 8 * NS_PER_MS, Observability.AGGREGATE_ONLY,
        ClockBasis.MONOTONIC, SUBMIT_ACK_COMPONENTS,
    )
    assert not interval.decomposable_into("broker_processing")
    assert not interval.decomposable_into("outbound_network")


# ------------------------------------------------------------- ACK sans horodatage


def test_submit_to_ack_without_broker_timestamps_is_an_aggregate():
    """Un accusé local ne sépare pas file locale, réseau aller, traitement courtier,
    réseau retour et rappel local."""
    m = ClockMonitor()
    interval = submit_to_ack(reading(0, 0), reading(9 * NS_PER_MS, 9 * NS_PER_MS), m)
    assert interval.observability is Observability.AGGREGATE_ONLY
    assert interval.contains == SUBMIT_ACK_COMPONENTS
    assert interval.name == "submit_to_ack_latency"
    assert interval.duration_ns == 9 * NS_PER_MS


def test_submit_to_ack_with_broker_timestamps_becomes_observed():
    m = ClockMonitor()
    interval = submit_to_ack(
        reading(0, 0), reading(9 * NS_PER_MS, 9 * NS_PER_MS), m,
        broker_timestamps_available=True,
    )
    assert interval.observability is Observability.OBSERVED
    assert interval.contains == ()


def test_broker_split_stays_unknown_without_broker_timestamps():
    """Le module ne comble pas : il déclare inconnu."""
    out, proc, back = broker_side_split(reading(0, 0), None, None, reading(9, 9), sync())
    for part in (out, proc, back):
        assert part.observability is Observability.NOT_IDENTIFIABLE
        assert part.duration_ns is None


def test_broker_split_only_when_broker_timestamps_exist():
    out, proc, back = broker_side_split(
        reading(0, 0), broker_received_ns=3 * NS_PER_MS, broker_ack_ns=5 * NS_PER_MS,
        ack_receive=reading(9 * NS_PER_MS, 9 * NS_PER_MS), sync=sync(),
    )
    assert proc.observability is Observability.OBSERVED
    assert proc.duration_ns == 2 * NS_PER_MS
    # Les trajets restent des agrégats : la file locale et le réseau ne se séparent pas.
    assert out.observability is Observability.AGGREGATE_ONLY
    assert back.observability is Observability.AGGREGATE_ONLY


def test_feed_latency_is_never_called_network_latency():
    interval = feed_latency(provider_ns=1_000_000, receive_wall_ns=6_000_000, sync=sync())
    assert interval.name == "provider_to_local_receive_latency"
    assert interval.observability is Observability.AGGREGATE_ONLY
    assert interval.contains == FEED_COMPONENTS


def test_feed_latency_unknown_without_provider_timestamp():
    assert feed_latency(None, 5_000_000, sync()).observability is (
        Observability.NOT_IDENTIFIABLE
    )


def test_feed_latency_unknown_without_clock_sync():
    unknown = feed_latency(1_000_000, 6_000_000, sync(ClockSyncState.SYNC_UNKNOWN))
    assert unknown.observability is Observability.NOT_IDENTIFIABLE


# ---------------------------------------------------------------------- horloges


def test_local_duration_uses_the_monotonic_clock():
    """Une correction de synchronisation ne doit pas produire de latence négative."""
    m = ClockMonitor()
    start = reading(wall=1_000_000_000, mono=0)
    end = reading(wall=999_000_000, mono=5 * NS_PER_MS)  # l'horloge murale a reculé
    duration, discontinuity = m.measure(start, end)
    assert duration == 5 * NS_PER_MS
    assert discontinuity


def test_wall_monotonic_divergence_is_recorded():
    m = ClockMonitor(tolerance_ns=10 * NS_PER_MS)
    m.measure(reading(0, 0), reading(500 * NS_PER_MS, 5 * NS_PER_MS))
    assert len(m.discontinuities) == 1


def test_small_divergence_is_tolerated():
    m = ClockMonitor(tolerance_ns=10 * NS_PER_MS)
    d, disc = m.measure(reading(0, 0), reading(5_100_000, 5_000_000))
    assert not disc and d == 5 * NS_PER_MS


def test_precision_claim_is_capped_by_sync_uncertainty():
    """Aucun résultat n'affiche une précision supérieure à celle de l'horloge."""
    s = sync(uncertainty_ns=2 * NS_PER_MS)
    assert not s.can_claim_precision(100_000)
    assert s.can_claim_precision(5 * NS_PER_MS)


def test_cross_system_interval_carries_the_uncertainty():
    interval = feed_latency(1_000_000, 6_000_000, sync(uncertainty_ns=3 * NS_PER_MS))
    assert interval.uncertainty_ns == 3 * NS_PER_MS
    assert interval.reportable_precision_ns == 3 * NS_PER_MS


# --------------------------------------------------------------- cadence, calcul


def test_evaluation_wait_is_measured_not_approximated():
    """`cadence / 2` n'est qu'un diagnostic théorique sous arrivée uniforme."""
    m = ClockMonitor()
    probe = EvaluationProbe(
        eligible=reading(0, 0),
        evaluated=reading(37 * NS_PER_MS, 37 * NS_PER_MS),
        completed=reading(41 * NS_PER_MS, 41 * NS_PER_MS),
        decision=reading(43 * NS_PER_MS, 43 * NS_PER_MS),
        burst=burst(), engine_version="E1", events_processed=120,
    )
    assert probe.wait(m).duration_ns == 37 * NS_PER_MS
    assert probe.compute(m).duration_ns == 4 * NS_PER_MS
    assert probe.decide(m).duration_ns == 2 * NS_PER_MS
    assert probe.wait(m).observability is Observability.OBSERVED


def test_missing_decision_timestamp_stays_unknown():
    m = ClockMonitor()
    probe = EvaluationProbe(
        eligible=reading(0, 0), evaluated=reading(1, 1), completed=reading(2, 2),
        decision=None, burst=burst(), engine_version="E1", events_processed=1,
    )
    assert probe.decide(m).observability is Observability.NOT_IDENTIFIABLE


# ----------------------------------------------------------------------- journal


def test_journal_is_hash_chained_and_verifiable():
    j = journal()
    j.append(event(EventType.ORDER_INTENT_CREATED), durable=True)
    j.append(event(EventType.SUBMIT_STARTED), durable=True)
    j.append(event(EventType.BROKER_ACK))
    assert j.verify_chain()
    assert j.events[0].previous_event_hash is None
    assert j.events[1].previous_event_hash == j.events[0].event_hash


def test_tampering_breaks_the_chain():
    j = journal()
    j.append(event(EventType.ORDER_INTENT_CREATED), durable=True)
    j.append(event(EventType.BROKER_ACK))
    j.events[0] = JournalEvent(
        **{**{f: getattr(j.events[0], f) for f in j.events[0].__dataclass_fields__},
           "price": 9999.0}
    )
    assert not j.verify_chain()


def test_order_creating_events_require_durable_persistence():
    """Un incident ne doit pas laisser un ordre réel sans trace locale de son origine."""
    j = journal()
    with pytest.raises(JournalError, match="durable"):
        j.append(event(EventType.SUBMIT_STARTED), durable=False)
    with pytest.raises(JournalError, match="durable"):
        j.append(event(EventType.CANCEL_REQUESTED), durable=False)


def test_non_critical_events_do_not_require_durability():
    j = journal()
    j.append(event(EventType.QUOTE_RECEIVED, logical_order_id=None))
    assert len(j.events) == 1


def test_retries_keep_one_logical_order_with_several_attempts():
    """Un délai d'attente suivi d'un accusé ne compte pas comme deux ordres."""
    j = journal()
    j.append(event(EventType.ORDER_INTENT_CREATED, submission_attempt_id="ATT-1"), durable=True)
    j.append(event(EventType.SUBMIT_STARTED, submission_attempt_id="ATT-1"), durable=True)
    j.append(event(EventType.SUBMIT_STARTED, submission_attempt_id="ATT-2",
                   journal_event_id="JRN-RETRY"), durable=True)
    j.append(event(EventType.BROKER_ACK, submission_attempt_id="ATT-2"))

    assert len(j.by_logical_order("ORD-1")) == 4
    assert j.attempts_of("ORD-1") == ["ATT-1", "ATT-2"]


def test_async_ack_before_submit_return_is_accepted():
    """Une API peut délivrer le rappel avant que l'appel d'émission ne retourne : le
    moteur n'impose pas d'ordre que la sémantique du connecteur ne garantit pas."""
    j = journal()
    j.append(event(EventType.SUBMIT_STARTED), durable=True)
    j.append(event(EventType.BROKER_ACK, clock=reading(5, 5)))
    j.append(event(EventType.SUBMIT_RETURNED, clock=reading(7, 7)))
    assert j.verify_chain()


def test_broker_timestamp_semantics_are_recorded():
    e = event(broker_timestamp_ns=42, broker_timestamp_semantics="heure de création de l'ACK")
    assert e.broker_timestamp_semantics
    assert e.journal_version == JOURNAL_VERSION


# --------------------------------------------------------- borne et verdict Q19


def test_observable_lower_bound_ignores_unknown_components():
    """Ce qui n'est pas observable n'est pas compté : la vraie latence ne peut donc
    qu'être supérieure. C'est cette asymétrie qui rend un verdict négatif concluant."""
    o = observation(
        8 * NS_PER_MS,
        intervals=(
            LatencyInterval("compute", 3 * NS_PER_MS, Observability.OBSERVED,
                            ClockBasis.MONOTONIC),
            LatencyInterval("submit_to_ack_latency", 8 * NS_PER_MS,
                            Observability.AGGREGATE_ONLY, ClockBasis.MONOTONIC,
                            SUBMIT_ACK_COMPONENTS),
            LatencyInterval("fill", None, Observability.NOT_IDENTIFIABLE,
                            ClockBasis.CROSS_SYSTEM),
        ),
    )
    assert o.observable_lower_bound_ns == 11 * NS_PER_MS
    assert o.unknown_components == ("fill",)


def test_observation_refuses_intervals_that_overlap():
    """Le défaut central corrigé : `submit_to_ack_latency` **contient déjà**
    `broker_processing`. Les additionner produirait une « borne inférieure » supérieure à
    la durée réellement vécue — donc plus une borne du tout."""
    with pytest.raises(JournalError, match="frontières"):
        observation(
            8 * NS_PER_MS,
            intervals=(
                LatencyInterval("submit_to_ack_latency", 8 * NS_PER_MS,
                                Observability.AGGREGATE_ONLY, ClockBasis.MONOTONIC,
                                SUBMIT_ACK_COMPONENTS),
                LatencyInterval("broker_processing", 5 * NS_PER_MS, Observability.OBSERVED,
                                ClockBasis.CROSS_SYSTEM),
            ),
        )


def test_overlap_is_detected_transitively_through_declared_components():
    """`outbound_leg` ne porte pas le même nom que `submit_to_ack_latency`, mais tous deux
    comptent la file locale et le réseau aller."""
    round_trip = LatencyInterval("submit_to_ack_latency", 8 * NS_PER_MS,
                                 Observability.AGGREGATE_ONLY, ClockBasis.MONOTONIC,
                                 SUBMIT_ACK_COMPONENTS)
    leg = LatencyInterval("outbound_leg", 2 * NS_PER_MS, Observability.AGGREGATE_ONLY,
                          ClockBasis.CROSS_SYSTEM,
                          ("local_outbound_queue", "outbound_network"))
    overlaps = detect_interval_overlaps((round_trip, leg))
    assert overlaps
    _, _, shared = overlaps[0]
    assert set(shared) == {"local_outbound_queue", "outbound_network"}


def test_disjoint_intervals_are_accepted_and_summed():
    """La séquence légitime — calcul puis aller-retour — ne se recouvre pas."""
    o = observation(
        8 * NS_PER_MS,
        intervals=(
            LatencyInterval("compute", 3 * NS_PER_MS, Observability.OBSERVED,
                            ClockBasis.MONOTONIC),
            LatencyInterval("submit_to_ack_latency", 8 * NS_PER_MS,
                            Observability.AGGREGATE_ONLY, ClockBasis.MONOTONIC,
                            SUBMIT_ACK_COMPONENTS),
            LatencyInterval("fill", None, Observability.NOT_IDENTIFIABLE,
                            ClockBasis.CROSS_SYSTEM),
        ),
    )
    assert detect_interval_overlaps(o.intervals) == ()
    assert o.attribution_lower_bound_ns == 11 * NS_PER_MS


def test_critical_path_takes_precedence_over_attribution():
    """§36 — le gate utilise la durée vécue ; l'attribution sert au diagnostic. Le chemin
    inclut les trous non mesurés entre composantes, il est donc toujours supérieur."""
    path = LatencyPath(boundaries=(
        boundary("quote_received", 0),
        boundary("compute_started", 4 * NS_PER_MS),
        boundary("ack_received", 30 * NS_PER_MS),
    ))
    o = observation(
        8 * NS_PER_MS,
        intervals=(
            LatencyInterval("compute", 3 * NS_PER_MS, Observability.OBSERVED,
                            ClockBasis.MONOTONIC),
        ),
        path=path,
    )
    assert o.attribution_lower_bound_ns == 3 * NS_PER_MS
    assert o.critical_path_ns == 30 * NS_PER_MS
    assert o.observable_lower_bound_ns == 30 * NS_PER_MS
    assert o.consumed_fraction_at(60 * NS_PER_MS) == 0.5


def test_low_path_coverage_does_not_weaken_the_verdict():
    """Une couverture faible signale un manque de prise pour l'optimisation, pas un
    défaut de fondement : la durée vécue reste mesurée."""
    path = LatencyPath(boundaries=(
        boundary("quote_received", 0),
        boundary("unmeasured", None),
        boundary("ack_received", 40 * NS_PER_MS),
    ))
    o = observation(0, intervals=(), path=path)
    assert o.path_coverage == 0.0
    assert o.observable_lower_bound_ns == 40 * NS_PER_MS
    assert "quote_received→unmeasured" in o.unknown_components


def test_without_a_path_the_bound_falls_back_to_attribution():
    o = observation(8 * NS_PER_MS)
    assert o.critical_path_ns is None
    assert o.path_coverage is None
    assert o.observable_lower_bound_ns == 8 * NS_PER_MS


# ------------------------------------------------- contrat d'observabilité (Q57/Q58)


def test_no_q19_metric_is_finer_than_the_observability_contract():
    """Une infrastructure sans horodatage courtier ne permet pas de nommer
    `broker_processing` : le chiffre serait crédible et faux."""
    matrix = build_matrix(qualified_clock(), proven_connector())
    with pytest.raises(JournalError, match="non identifiable"):
        enforce_contract(
            (LatencyInterval("broker_processing", 5 * NS_PER_MS, Observability.OBSERVED,
                             ClockBasis.CROSS_SYSTEM),),
            matrix,
        )


def test_contract_refuses_to_promote_an_aggregate_to_observed():
    matrix = build_matrix(qualified_clock(), proven_connector())
    with pytest.raises(JournalError, match="agrégat"):
        enforce_contract(
            (LatencyInterval("submit_to_ack", 8 * NS_PER_MS, Observability.OBSERVED,
                             ClockBasis.MONOTONIC),),
            matrix,
        )


def test_contract_accepts_what_the_infrastructure_actually_supports():
    matrix = build_matrix(qualified_clock(), proven_connector())
    enforce_contract(
        (
            LatencyInterval("compute", 3 * NS_PER_MS, Observability.OBSERVED,
                            ClockBasis.MONOTONIC),
            LatencyInterval("submit_to_ack", 8 * NS_PER_MS, Observability.AGGREGATE_ONLY,
                            ClockBasis.MONOTONIC, SUBMIT_ACK_COMPONENTS),
            LatencyInterval("broker_processing", None, Observability.NOT_IDENTIFIABLE,
                            ClockBasis.CROSS_SYSTEM),
        ),
        matrix,
    )


def test_latency_above_horizon_counts_as_full_consumption():
    """L'observation n'est jamais supprimée — c'est la règle qui a corrigé le biais de
    sélection de la phase 0."""
    o = observation(2 * NS_PER_SECOND)
    assert o.consumed_fraction_at(NS_PER_SECOND) == 1.0
    assert o.consumed_fraction_at(4 * NS_PER_SECOND) == 0.5


def test_lower_bound_above_horizon_is_conclusive():
    obs = [observation(500 * NS_PER_MS, cluster=f"C{i}") for i in range(40)]
    verdict, why = messaging_layer_verdict(obs, horizon_ns=200 * NS_PER_MS)
    assert verdict is LatencyVerdictQ51.LATENCY_NON_VIABLE
    assert "concluant" in why


def test_fast_messaging_only_means_not_excluded():
    """Une bonne latence d'aller-retour ne démontre rien sur l'exécution réelle."""
    obs = [observation(5 * NS_PER_MS, cluster=f"C{i}") for i in range(40)]
    verdict, why = messaging_layer_verdict(obs, horizon_ns=NS_PER_SECOND)
    assert verdict is LatencyVerdictQ51.LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER
    assert "non mesurées" in why


def test_too_few_clusters_is_indeterminate():
    obs = [observation(5 * NS_PER_MS, cluster="C1") for _ in range(200)]
    verdict, _ = messaging_layer_verdict(obs, horizon_ns=NS_PER_SECOND)
    assert verdict is LatencyVerdictQ51.LATENCY_INDETERMINATE


def test_invalid_measurements_are_excluded_from_the_verdict():
    obs = [
        observation(5 * NS_PER_MS, cluster=f"C{i}",
                    quality=MeasurementQuality.MEASUREMENT_INVALID)
        for i in range(40)
    ]
    verdict, _ = messaging_layer_verdict(obs, horizon_ns=NS_PER_SECOND)
    assert verdict is LatencyVerdictQ51.LATENCY_INDETERMINATE


# ------------------------------------------------------- distributions et qualité


def test_burst_conditional_distribution_differs_from_marginal():
    """La latence se dégrade là où les signaux apparaissent : la distribution marginale
    sous-estime celle qui compte."""
    from feasibility.latency_journal import summarize

    calm = [observation(5 * NS_PER_MS, cluster=f"N{i}") for i in range(50)]
    heavy = [
        observation(60 * NS_PER_MS, cluster=f"B{i}", burst=burst(BurstState.BURST_P99, 400))
        for i in range(50)
    ]
    marginal = summarize(calm + heavy, "submit_to_ack_latency")
    conditional = summarize(calm + heavy, "submit_to_ack_latency", BurstState.BURST_P99)

    assert conditional.p95 > marginal.p50
    assert conditional.sample_count == 50
    assert conditional.independent_cluster_count == 50


def test_distribution_carries_its_observability():
    from feasibility.latency_journal import summarize

    d = summarize([observation(5 * NS_PER_MS, cluster=f"C{i}") for i in range(10)],
                  "submit_to_ack_latency")
    assert not d.is_decomposable
    assert d.contains == SUBMIT_ACK_COMPONENTS


def test_summarize_returns_nothing_when_the_interval_is_absent():
    from feasibility.latency_journal import summarize

    assert summarize([observation(1)], "fill") is None


def test_reconnection_measurements_are_invalid():
    """Un accusé reçu juste après une reconnexion ne se mélange pas aux mesures
    nominales."""
    q = measurement_quality(sync(), ConnectionState.RECONNECTING, 0)
    assert q is MeasurementQuality.MEASUREMENT_INVALID


def test_clock_discontinuity_invalidates_the_measurement():
    assert measurement_quality(sync(), ConnectionState.CONNECTED_STABLE, 1) is (
        MeasurementQuality.MEASUREMENT_INVALID
    )


def test_degraded_sync_degrades_but_does_not_invalidate():
    q = measurement_quality(sync(ClockSyncState.SYNC_DEGRADED),
                            ConnectionState.CONNECTED_STABLE, 0)
    assert q is MeasurementQuality.MEASUREMENT_DEGRADED


def test_material_measurement_overhead_degrades_quality():
    """La campagne peut allonger la latence qu'elle mesure."""
    perturbation = PerturbationCheck(
        with_logging_p95_ns=12 * NS_PER_MS,
        reduced_logging_p95_ns=10 * NS_PER_MS,
        sample_count=500,
    )
    assert perturbation.is_material()
    assert measurement_quality(sync(), ConnectionState.CONNECTED_STABLE, 0, perturbation) is (
        MeasurementQuality.MEASUREMENT_DEGRADED
    )


def test_small_overhead_is_not_material():
    perturbation = PerturbationCheck(10.1 * NS_PER_MS, 10 * NS_PER_MS, 500)
    assert not perturbation.is_material()


# ----------------------------------------------------------------- campagne


def policy(**kw) -> CampaignPolicy:
    base = dict(
        phase=ProbePhase.A_PASSIVE,
        sampling_policy_version="SP-1",
        probability_by_burst={"NORMAL": 0.1, "BURST_P95": 0.8, "BURST_P99": 1.0},
        max_active_orders=1,
        budget_approved=False,
        kill_switch_armed=False,
    )
    base.update(kw)
    return CampaignPolicy(**base)


def test_passive_phase_starts_without_budget():
    """Q51-A démarre indépendamment de Q42."""
    policy().authorize(creates_real_order=False)


def test_real_order_probe_is_blocked_without_budget_and_kill_switch():
    with pytest.raises(JournalError, match="Q42"):
        policy(phase=ProbePhase.B_MESSAGING).authorize(creates_real_order=True)


def test_micro_execution_phase_requires_budget():
    with pytest.raises(JournalError, match="micro-exécutions"):
        policy(phase=ProbePhase.C_MICRO_EXECUTION,
               kill_switch_armed=True).authorize(creates_real_order=False)


def test_authorized_campaign_passes():
    policy(phase=ProbePhase.B_MESSAGING, budget_approved=True,
           kill_switch_armed=True).authorize(creates_real_order=True)


def test_sampling_weights_allow_reweighting():
    """Une surreprésentation volontaire des rafales doit pouvoir être corrigée."""
    p = policy()
    assert p.weight_for(BurstState.NORMAL) == 10.0
    assert p.weight_for(BurstState.BURST_P99) == 1.0
    assert p.weight_for(BurstState.ELEVATED) == 0.0  # non échantillonné
