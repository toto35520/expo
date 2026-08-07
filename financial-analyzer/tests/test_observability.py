"""Tests du contrat d'observabilité de la latence (Q57 + Q58).

Ce module ne mesure pas la performance : il fixe **ce qui peut être revendiqué**. Chaque
test vise un cas où une revendication non fondée — une horloge crue précise, un rappel cru
probant, deux intervalles additionnés — produirait un chiffre crédible et faux.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feasibility.observability import (
    NS_PER_MS,
    NS_PER_SECOND,
    AckSemantics,
    BoundaryQuality,
    BrokerConnectorCapability,
    ClockCapability,
    ClockDomain,
    ClockQualification,
    ComponentStatus,
    CorrectionMode,
    EvidenceType,
    EventSemantics,
    GranularityTest,
    LatencyBoundary,
    LatencyPath,
    QUALIFIABLE_EVENTS,
    MeasurementGrade,
    MessageKind,
    ObservabilityError,
    ObservabilityVerdict,
    OrderState,
    RejectKind,
    ResolutionClass,
    SegmentStatus,
    SubmitReturnSemantics,
    Virtualization,
    blank_capability,
    build_matrix,
    format_ns,
    group_by_grade,
    load_capability,
    print_matrix,
    q57_resolved,
    q58_resolved,
    qualify_clock,
    resolution_class,
    state_after_reject,
)

MS = NS_PER_MS


def granularity(step_ns: int = 40, duplicates: float = 0.0) -> GranularityTest:
    return GranularityTest(
        minimum_non_zero_step_ns=step_ns,
        median_step_ns=step_ns * 1.2,
        p99_step_ns=step_ns * 4.0,
        duplicate_timestamp_rate=duplicates,
    )


def clock(**kw) -> ClockCapability:
    base = dict(
        host_id="H1",
        granularity_wall=granularity(1_000),
        granularity_monotonic=granularity(40),
        monotonic_failures=0,
        wall_discontinuities=0,
        drift_p95_ppm=1.0,
        measured_uncertainty_ns=200_000,
        correction_mode=CorrectionMode.SLEW,
        virtualization=Virtualization.BARE_METAL,
        suspend_events=0,
        sync_method="NTP",
        qualified_at_ns=0,
    )
    return qualify_clock(**{**base, **kw})


def proven_event(name: str, **kw) -> EventSemantics:
    base = dict(
        event_name=name,
        observable=True,
        meaning="accusé de réception créé par le courtier",
        message_kind=MessageKind.BROKER_EVENT,
        timestamp_available=True,
        clock_domain=ClockDomain.BROKER,
        evidence_type=EvidenceType.CONTROLLED_TEST,
        evidence_id="TEST-2026-001",
        ordering_guaranteed=True,
    )
    return EventSemantics(**{**base, **kw})


def connector(**kw) -> BrokerConnectorCapability:
    base = dict(
        connector_id="broker:demo",
        connector_version="1.4.2",
        broker="COURTIER",
        account_type="DEMO",
        submit_return_semantics=SubmitReturnSemantics.LOCAL_QUEUE_ACCEPTED,
        ack_semantics=AckSemantics.ORDER_RECEIVED,
        rejection_semantics="motif structuré fourni par le courtier",
        cancel_semantics="ORDER_CANCEL_RECEIVED",
        order_active_observable=False,
        broker_receive_timestamp_available=False,
        broker_accept_timestamp_available=False,
        fill_timestamp_available=False,
        timestamp_clock_domain=None,
        events=(proven_event("BROKER_ACK"),),
        reconciliation_available=True,
        qualification_status="QUALIFIED",
    )
    return BrokerConnectorCapability(**{**base, **kw})


# ============================================================ Q57 — horloges


def test_intersystem_qualification_requires_measured_uncertainty():
    """La précision annoncée par une source de synchronisation n'est pas une mesure.
    L'accepter reviendrait à revendiquer une décomposition inter-systèmes sur la foi
    d'une brochure."""
    with pytest.raises(ObservabilityError, match="mesurée"):
        ClockCapability(
            host_id="H1", wall_clock_source="wall", monotonic_clock_source="monotonic",
            sync_method="NTP", sync_server="pool", advertised_accuracy_ns=1_000,
            measured_uncertainty_ns=None, correction_mode=CorrectionMode.SLEW,
            virtualization_state=Virtualization.BARE_METAL,
            monotonic_resolution_ns=40, wall_resolution_ns=1_000,
            qualification=ClockQualification.CLOCK_QUALIFIED,
            qualified_at_ns=0, qualification_version="Q57_CLOCK_1.0",
        )


def test_unmeasured_uncertainty_still_resolves_q57_as_local_only():
    """Déclarer correctement l'inconnu **résout** Q57 : le domaine mesurable se réduit,
    il ne devient pas indéterminé."""
    c = clock(measured_uncertainty_ns=None)
    assert c.qualification is ClockQualification.CLOCK_QUALIFIED_LOCAL_ONLY
    assert c.local_usable
    assert not c.intersystem_usable


def test_monotonic_failure_disqualifies_even_local_durations():
    c = clock(monotonic_failures=2)
    assert c.qualification is ClockQualification.CLOCK_UNQUALIFIED
    assert not c.local_usable


def test_step_correction_degrades_the_clock():
    """Un saut d'heure murale censure les durées inter-systèmes qui le traversent."""
    assert clock(correction_mode=CorrectionMode.STEP).qualification is (
        ClockQualification.CLOCK_DEGRADED
    )


def test_wall_discontinuity_degrades_the_clock():
    assert clock(wall_discontinuities=1).qualification is ClockQualification.CLOCK_DEGRADED


def test_excessive_drift_degrades_the_clock():
    assert clock(drift_p95_ppm=500.0).qualification is ClockQualification.CLOCK_DEGRADED


def test_suspend_event_forces_requalification():
    """Une reprise après veille invalide l'étalonnage : l'horloge reste qualifiée en
    titre mais n'est plus utilisable tant qu'elle n'a pas été réévaluée."""
    c = clock(suspend_events=1)
    assert c.requalification_required
    assert not c.intersystem_usable


def test_effective_granularity_is_measured_not_advertised():
    """Une horloge affichant des nanosecondes peut n'avancer que par pas de 15 µs."""
    coarse = granularity(15_000)
    assert coarse.limits(typical_latency_ns=100_000)
    assert not coarse.limits(typical_latency_ns=50 * MS)


def test_granularity_limits_when_latency_is_degenerate():
    assert granularity(40).limits(typical_latency_ns=0)


def test_nothing_is_published_finer_than_the_measured_uncertainty():
    c = clock(measured_uncertainty_ns=200_000)
    assert not c.can_publish(1_000)
    assert c.can_publish(500_000)


def test_local_only_clock_cannot_publish_intersystem_precision():
    assert not clock(measured_uncertainty_ns=None).can_publish(NS_PER_SECOND)


@pytest.mark.parametrize(
    "uncertainty,duration,expected",
    [
        (1 * MS, 100 * MS, ResolutionClass.HIGH_CONFIDENCE),
        (20 * MS, 100 * MS, ResolutionClass.USABLE),
        (40 * MS, 100 * MS, ResolutionClass.DEGRADED),
        (80 * MS, 100 * MS, ResolutionClass.NOT_RESOLVABLE),
        (1 * MS, 0, ResolutionClass.NOT_RESOLVABLE),
    ],
)
def test_resolution_is_a_ratio_not_an_absolute(uncertainty, duration, expected):
    """Une incertitude de 1 ms est excellente sur 100 ms et inutilisable sur 2 ms."""
    assert resolution_class(uncertainty, duration) is expected


# ============================================================ Q58 — connecteur


def test_an_event_declared_observable_needs_evidence():
    """Le nom d'un rappel n'a aucune valeur probatoire."""
    with pytest.raises(ObservabilityError, match="probatoire"):
        proven_event("BROKER_ACK", evidence_id="  ")


def test_a_timestamp_must_declare_its_clock_domain():
    with pytest.raises(ObservabilityError, match="domaine d'horloge"):
        proven_event("BROKER_ACK", clock_domain=ClockDomain.NONE)


def test_observational_inference_is_not_probative():
    """Observer que l'accusé arrive « vite » n'établit pas ce qu'il signifie."""
    e = proven_event("BROKER_ACK", evidence_type=EvidenceType.OBSERVATIONAL_INFERENCE)
    assert e.observable
    assert not e.is_probative
    assert connector(events=(e,)).unqualified_events == ("BROKER_ACK",)


def test_ack_does_not_imply_an_active_order():
    """`on_order_accepted()` ne démontre pas qu'un ordre est actif sur le marché."""
    assert not connector(ack_semantics=AckSemantics.ORDER_CREATED).ack_implies_active
    assert not connector(
        ack_semantics=AckSemantics.ORDER_ACTIVE, order_active_observable=False
    ).ack_implies_active
    assert connector(
        ack_semantics=AckSemantics.ORDER_ACTIVE, order_active_observable=True
    ).ack_implies_active


def test_a_timeout_is_not_a_rejection():
    """Un délai dépassé laisse l'état réel inconnu : le traiter comme un rejet
    autoriserait un second ordre alors que le premier existe peut-être."""
    assert RejectKind.TIMEOUT_UNKNOWN_STATE not in (
        RejectKind.LOCAL_VALIDATION_REJECT,
        RejectKind.BROKER_REJECT,
        RejectKind.MARKET_REJECT,
    )


def test_rpc_response_and_broker_event_are_distinct_messages():
    """Deux messages arrivant presque simultanément ne portent pas la même information."""
    assert MessageKind.RPC_RESPONSE is not MessageKind.BROKER_EVENT


def test_blank_capability_declares_everything_unknown():
    """Une fiche vide vaut mieux qu'une fausse précision : elle produit des bornes
    honnêtes là où une supposition produirait des verdicts faux."""
    c = blank_capability("COURTIER", "REEL")
    assert c.submit_return_semantics is SubmitReturnSemantics.UNKNOWN
    assert c.ack_semantics is AckSemantics.UNKNOWN
    assert not c.order_active_observable
    assert c.events == ()
    assert c.qualification_status == "UNQUALIFIED"


def test_semantics_lookup_returns_none_for_undeclared_events():
    assert connector().semantics_of("FULL_FILL") is None


# ============================================= frontières : le double comptage


def local(name: str, ts: int | None) -> LatencyBoundary:
    return LatencyBoundary(
        name, ts, ClockDomain.LOCAL_MONOTONIC,
        BoundaryQuality.EXACT_LOCAL if ts is not None else BoundaryQuality.UNKNOWN,
    )


def critical_path() -> LatencyPath:
    return LatencyPath(boundaries=(
        local("quote_received", 0),
        local("evaluation_started", 2 * MS),
        local("decision_ready", 5 * MS),
        local("submit_started", 6 * MS),
        local("ack_received", 20 * MS),
    ))


def test_naive_interval_sum_can_exceed_the_duration_actually_lived():
    """Le défaut que les frontières éliminent : additionner l'aller-retour d'émission et
    le traitement courtier qu'il **contient déjà** produit un total supérieur à la durée
    réellement vécue. Une « borne inférieure » qui dépasse le vécu n'en est plus une."""
    path = critical_path()
    lived = path.critical_path_ns()
    submit_to_ack = 14 * MS
    broker_processing_inside_it = 9 * MS

    assert submit_to_ack + broker_processing_inside_it > lived
    assert path.certain_lower_bound_ns() == lived == 20 * MS


def test_segments_are_disjoint_by_construction():
    """Deux segments consécutifs partagent une frontière : ils ne peuvent pas se
    recouvrir, et leur somme ne peut pas dépasser le chemin."""
    path = critical_path()
    durations = [s.duration_ns for s in path.segments()]
    assert durations == [2 * MS, 3 * MS, 1 * MS, 14 * MS]
    assert sum(durations) == path.critical_path_ns()
    assert path.coverage() == 1.0


def test_boundaries_out_of_order_in_the_same_domain_are_refused():
    with pytest.raises(ObservabilityError, match="hors ordre"):
        LatencyPath(boundaries=(local("submit_started", 10 * MS), local("ack_received", 4 * MS)))


def test_a_missing_boundary_makes_its_segments_unidentifiable_never_estimated():
    """Une frontière absente n'est pas interpolée : les deux segments qu'elle borde
    disparaissent de la borne, qui reste inférieure."""
    path = LatencyPath(boundaries=(
        local("quote_received", 0),
        local("decision_ready", None),
        local("ack_received", 20 * MS),
    ))
    statuses = [s.status for s in path.segments()]
    assert statuses == [SegmentStatus.NOT_IDENTIFIABLE, SegmentStatus.NOT_IDENTIFIABLE]
    assert path.certain_lower_bound_ns() == 0
    assert path.critical_path_ns() == 20 * MS
    assert path.coverage() == 0.0
    assert len(path.unknown_segments()) == 2


def test_cross_domain_segment_needs_a_clock_qualified_for_intersystem():
    """Comparer un horodatage courtier à une horloge locale sans qualification produit
    une durée qui n'est qu'un décalage de synchronisation déguisé."""
    boundaries = (
        local("submit_started", 0),
        LatencyBoundary("broker_received", 5 * MS, ClockDomain.BROKER,
                        BoundaryQuality.QUALIFIED_INTERSYSTEM),
    )
    unqualified = LatencyPath(boundaries=boundaries, clock=clock(measured_uncertainty_ns=None))
    assert unqualified.segments()[0].status is SegmentStatus.NOT_RESOLVABLE_INTERSYSTEM
    assert unqualified.certain_lower_bound_ns() == 0

    qualified = LatencyPath(boundaries=boundaries, clock=clock())
    assert qualified.segments()[0].status is SegmentStatus.QUALIFIED_INTERSYSTEM
    assert qualified.certain_lower_bound_ns() == 5 * MS


def test_cross_domain_segment_shorter_than_its_uncertainty_is_not_resolvable():
    """Une durée de 300 µs mesurée à ±200 µs près n'est pas une mesure."""
    path = LatencyPath(
        boundaries=(
            local("submit_started", 0),
            LatencyBoundary("broker_received", 300_000, ClockDomain.BROKER,
                            BoundaryQuality.QUALIFIED_INTERSYSTEM),
        ),
        clock=clock(measured_uncertainty_ns=200_000),
    )
    assert path.segments()[0].status is SegmentStatus.NOT_RESOLVABLE_INTERSYSTEM
    assert path.certain_lower_bound_ns() == 0


def test_critical_path_across_unqualified_domains_is_none_not_zero():
    """Ne pas savoir n'est pas mesurer zéro."""
    path = LatencyPath(
        boundaries=(
            local("submit_started", 0),
            LatencyBoundary("broker_ack", 5 * MS, ClockDomain.BROKER,
                            BoundaryQuality.DEGRADED_CLOCK),
        ),
        clock=clock(wall_discontinuities=1),
    )
    assert path.critical_path_ns() is None
    assert path.coverage() == 0.0


def test_a_single_known_boundary_yields_no_path():
    path = LatencyPath(boundaries=(local("quote_received", 0), local("ack_received", None)))
    assert path.critical_path_ns() is None


def test_lower_bound_never_exceeds_the_lived_path():
    """Invariant central : la somme d'attribution est toujours ≤ la durée vécue."""
    path = LatencyPath(boundaries=(
        local("quote_received", 0),
        local("gap_start", None),
        local("ack_received", 50 * MS),
    ))
    assert path.certain_lower_bound_ns() <= path.critical_path_ns()


# ============================================= matrice : l'intersection est pessimiste


def test_matrix_requires_both_clock_and_connector_to_declare_a_component_observed():
    """Des horodatages courtier sans horloge qualifiée ne décomposent rien."""
    full = connector(
        broker_receive_timestamp_available=True,
        broker_accept_timestamp_available=True,
        timestamp_clock_domain=ClockDomain.BROKER,
    )
    assert build_matrix(clock(), full).status_of("broker_processing") is (
        ComponentStatus.OBSERVED
    )
    degraded = build_matrix(clock(measured_uncertainty_ns=None), full)
    assert degraded.status_of("broker_processing") is ComponentStatus.NOT_IDENTIFIABLE
    assert degraded.status_of("submit_to_ack") is ComponentStatus.AGGREGATE_ONLY


def test_without_broker_timestamps_the_round_trip_is_an_aggregate():
    """L'aller-retour reste mesurable, mais ses composantes ne sont pas séparables."""
    m = build_matrix(clock(), connector())
    assert m.status_of("submit_to_ack") is ComponentStatus.AGGREGATE_ONLY
    for name in ("outbound_network", "broker_processing", "inbound_network"):
        assert m.status_of(name) is ComponentStatus.NOT_IDENTIFIABLE


def test_matrix_refuses_attribution_to_an_unidentifiable_component():
    m = build_matrix(clock(), connector())
    with pytest.raises(ObservabilityError, match="pas identifiable"):
        m.authorize("broker_processing")
    m.authorize("submit_to_ack")


def test_ack_never_grants_the_activation_component():
    m = build_matrix(clock(), connector(ack_semantics=AckSemantics.ORDER_ACTIVE))
    assert m.status_of("ack_to_active") is ComponentStatus.NOT_IDENTIFIABLE

    observable = build_matrix(clock(), connector(order_active_observable=True))
    assert observable.status_of("ack_to_active") is ComponentStatus.OBSERVED


def test_unqualified_clock_makes_the_matrix_insufficient_for_q19():
    m = build_matrix(clock(monotonic_failures=1), connector())
    assert m.verdict is ObservabilityVerdict.INSUFFICIENT_FOR_Q19
    assert m.status_of("compute") is ComponentStatus.NOT_IDENTIFIABLE


def test_unproven_connector_leaves_only_the_local_process():
    """Sans accusé prouvé, la composante d'aller-retour n'est pas « grossière » : elle
    est absente. Le système ne mesure alors que lui-même."""
    m = build_matrix(clock(measured_uncertainty_ns=None), blank_capability("X", "REEL"))
    assert m.status_of("submit_to_ack") is ComponentStatus.NOT_IDENTIFIABLE
    assert m.status_of("compute") is ComponentStatus.OBSERVED
    assert m.verdict is ObservabilityVerdict.LOCAL_ONLY


def test_local_clock_with_proven_ack_suffices_for_a_lower_bound():
    m = build_matrix(clock(measured_uncertainty_ns=None), connector())
    assert m.verdict is ObservabilityVerdict.SUFFICIENT_FOR_LOWER_BOUND
    assert m.status_of("provider_to_local_receive") is ComponentStatus.NOT_IDENTIFIABLE


def test_fully_qualified_requires_broker_timestamps_and_a_qualified_clock():
    m = build_matrix(
        clock(),
        connector(
            broker_receive_timestamp_available=True,
            broker_accept_timestamp_available=True,
            fill_timestamp_available=True,
            order_active_observable=True,
            timestamp_clock_domain=ClockDomain.BROKER,
        ),
    )
    assert m.verdict is ObservabilityVerdict.FULLY_QUALIFIED


def test_provider_feed_is_never_called_network_latency():
    """Le trajet fournisseur → réception contient appariement, agrégation, distribution,
    transport et tamponnage. Le nommer « latence réseau » serait faux."""
    m = build_matrix(clock(), connector())
    feed = next(c for c in m.components if c.component == "provider_to_local_receive")
    assert feed.status is ComponentStatus.AGGREGATE_ONLY
    assert "transport_network" in feed.contains
    assert len(feed.contains) >= 5


def test_unknown_status_defaults_to_not_identifiable():
    """Une composante jamais déclarée n'est pas implicitement autorisée."""
    m = build_matrix(clock(), connector())
    assert m.status_of("queue_position") is ComponentStatus.NOT_IDENTIFIABLE


def test_the_critical_path_itself_is_a_lower_bound_when_a_component_is_missing():
    """§19 — la durée observée ne couvre qu'une partie certaine du chemin total. Le
    déclarer OBSERVED suggérerait qu'il ne manque rien."""
    partial = build_matrix(clock(), connector())
    assert partial.status_of("critical_path") is ComponentStatus.LOWER_BOUND

    complete = build_matrix(
        clock(),
        connector(
            broker_receive_timestamp_available=True,
            broker_accept_timestamp_available=True,
            fill_timestamp_available=True,
            order_active_observable=True,
            timestamp_clock_domain=ClockDomain.BROKER,
        ),
    )
    assert complete.status_of("critical_path") is ComponentStatus.OBSERVED


def test_the_critical_path_is_not_identifiable_when_nothing_is():
    m = build_matrix(clock(monotonic_failures=1), blank_capability("X", "REEL"))
    assert m.status_of("critical_path") is ComponentStatus.NOT_IDENTIFIABLE


def test_the_critical_path_does_not_inflate_the_verdict():
    """Il agrège les autres composantes : s'y compter lui-même fausserait le décompte."""
    m = build_matrix(clock(measured_uncertainty_ns=None), blank_capability("X", "REEL"))
    assert m.verdict is ObservabilityVerdict.LOCAL_ONLY


# ============================================= états, ordre et versions


def test_a_timeout_never_resolves_into_a_rejection():
    """Le résoudre en rejet autoriserait un second ordre alors que le premier existe
    peut-être déjà : une position double au lieu d'une."""
    assert state_after_reject(RejectKind.TIMEOUT_UNKNOWN_STATE) is (
        OrderState.UNKNOWN_PENDING_RECONCILIATION
    )
    for kind in (RejectKind.LOCAL_VALIDATION_REJECT, RejectKind.BROKER_REJECT,
                 RejectKind.MARKET_REJECT):
        assert state_after_reject(kind) is OrderState.REJECTED


def test_only_declared_orderings_are_guaranteed():
    """Une API peut délivrer un rappel avant le retour de l'appel : le journal n'impose
    que les invariants réellement garantis."""
    c = connector(guaranteed_orderings=(("SUBMIT_STARTED", "BROKER_ACK"),))
    assert c.guarantees_order("SUBMIT_STARTED", "BROKER_ACK")
    assert not c.guarantees_order("SUBMIT_RETURNED", "BROKER_ACK")
    assert not c.guarantees_order("BROKER_ACK", "SUBMIT_STARTED")


def test_a_connector_update_invalidates_the_previous_qualification():
    """Une mise à jour de SDK peut changer rappels, tamponnage, ordre des événements et
    horodatages : les conclusions précédentes ne sont pas supposées valables."""
    old = connector(connector_version="1.4.2")
    assert old.invalidated_by(connector(connector_version="1.5.0"))
    assert old.invalidated_by(connector(qualification_version="Q58_CONNECTOR_2.0"))
    assert not old.invalidated_by(connector(connector_version="1.4.2"))


def test_a_different_connector_does_not_invalidate_this_one():
    old = connector(connector_id="broker:demo")
    assert not old.invalidated_by(connector(connector_id="autre:reel",
                                            connector_version="9.9.9"))


def test_evidence_ids_are_collected_from_the_qualified_events():
    c = connector(events=(proven_event("BROKER_ACK", evidence_id="DOC-1"),
                          proven_event("FULL_FILL", evidence_id="TEST-2")))
    assert c.evidence_ids == ("DOC-1", "TEST-2")


# ============================================= §37 — les qualités ne se mélangent pas


def test_measurement_grades_are_never_pooled_into_one_distribution():
    """Un p95 confondant durées exactes et horloge dégradée décrit la répartition des
    qualités de mesure autant que la latence."""
    grouped = group_by_grade([
        (MeasurementGrade.EXACT_LOCAL, 3 * MS),
        (MeasurementGrade.DEGRADED_CLOCK, 400 * MS),
        (MeasurementGrade.EXACT_LOCAL, 4 * MS),
        (MeasurementGrade.UNKNOWN, 0),
    ])
    assert grouped[MeasurementGrade.EXACT_LOCAL] == (3 * MS, 4 * MS)
    assert grouped[MeasurementGrade.DEGRADED_CLOCK] == (400 * MS,)
    assert MeasurementGrade.QUALIFIED_INTERSYSTEM not in grouped


# ============================================= §38 / §39 — critères de passage


def instrumented(**kw):
    return clock(wall_mono_samples=5_000, **kw)


def test_q57_is_resolved_by_a_mediocre_but_fully_described_clock():
    """Une synchronisation médiocre n'empêche pas de résoudre Q57 : elle réduit le
    domaine mesurable."""
    ok, missing = q57_resolved(
        instrumented(measured_uncertainty_ns=None,
                     intersystem_uncertainty_declared_unknown=True)
    )
    assert ok, missing


def test_q57_is_not_resolved_by_uncharted_ignorance():
    """Ne pas avoir mesuré l'incertitude et l'avoir déclarée introuvable ne se valent
    pas."""
    ok, missing = q57_resolved(instrumented(measured_uncertainty_ns=None))
    assert not ok
    assert any("explicitement déclarée inconnue" in m for m in missing)


def test_q57_requires_the_wall_mono_pair_to_be_instrumented():
    ok, missing = q57_resolved(clock(wall_mono_samples=3))
    assert not ok
    assert any("instrumenté" in m for m in missing)


def test_q57_requires_a_known_synchronisation_method():
    ok, missing = q57_resolved(instrumented(sync_method="UNKNOWN"))
    assert not ok
    assert any("synchronisation" in m for m in missing)


def test_q57_fails_when_the_monotonic_clock_went_backwards():
    ok, missing = q57_resolved(instrumented(monotonic_failures=1))
    assert not ok
    assert any("reculé" in m for m in missing)


def test_q58_accepts_an_event_declared_unobservable():
    """Les événements non identifiables sont acceptables ; l'ambiguïté non documentée
    ne l'est pas."""
    unobservable = EventSemantics(
        event_name="ORDER_ACTIVE", observable=False, meaning="non exposé par l'API",
        message_kind=MessageKind.BROKER_EVENT, timestamp_available=False,
        clock_domain=ClockDomain.NONE, evidence_type=EvidenceType.OFFICIAL_DOCUMENTATION,
        evidence_id="", ordering_guaranteed=False,
    )
    ok, missing = q58_resolved(
        connector(events=(proven_event("BROKER_ACK"), unobservable)),
        ("BROKER_ACK", "ORDER_ACTIVE"),
    )
    assert ok, missing


def test_q58_rejects_an_event_used_without_any_declared_semantics():
    ok, missing = q58_resolved(connector(), ("BROKER_ACK", "FULL_FILL"))
    assert not ok
    assert any("FULL_FILL" in m for m in missing)


def test_q58_rejects_semantics_resting_on_inference_alone():
    ok, missing = q58_resolved(
        connector(events=(proven_event(
            "BROKER_ACK", evidence_type=EvidenceType.OBSERVATIONAL_INFERENCE),)),
        ("BROKER_ACK",),
    )
    assert not ok
    assert any("inférence" in m for m in missing)


def test_q58_requires_a_reconciliation_path():
    """Sans elle, un état inconnu après délai dépassé resterait irrésolu."""
    ok, missing = q58_resolved(connector(reconciliation_available=False), ("BROKER_ACK",))
    assert not ok
    assert any("réconciliation" in m for m in missing)


def test_the_full_event_roster_is_named_not_improvised():
    assert "ORDER_ACTIVE" in QUALIFIABLE_EVENTS
    assert "TIMEOUT" not in QUALIFIABLE_EVENTS
    assert len(QUALIFIABLE_EVENTS) == 9


# ============================================= §42 — la fiche livrée


SHEET = Path(__file__).resolve().parents[1] / "connector-capability"


def test_the_shipped_sheet_claims_nothing():
    """La fiche livrée est vide et doit le rester : c'est elle qui garantit qu'aucune
    borne n'est calculée sur une sémantique supposée."""
    c = load_capability(str(SHEET / "broker-connector-capability.json"))
    assert c.ack_semantics is AckSemantics.UNKNOWN
    assert c.submit_return_semantics is SubmitReturnSemantics.UNKNOWN
    assert not c.order_active_observable
    assert not c.broker_receive_timestamp_available
    assert c.events == ()
    assert c.evidence_ids == ()


def test_the_shipped_sheet_resolves_nothing_and_says_why():
    c = load_capability(str(SHEET / "broker-connector-capability.json"))
    ok, missing = q58_resolved(c, ("BROKER_ACK",))
    assert not ok
    assert any("aucune sémantique déclarée" in m for m in missing)


def test_the_shipped_sheet_yields_the_pessimistic_matrix():
    m = build_matrix(clock(measured_uncertainty_ns=None),
                     load_capability(str(SHEET / "broker-connector-capability.json")))
    assert m.verdict is ObservabilityVerdict.LOCAL_ONLY
    assert m.status_of("submit_to_ack") is ComponentStatus.NOT_IDENTIFIABLE


def test_a_missing_field_is_read_as_unknown_never_as_favourable(tmp_path):
    """Une fiche incomplète produit des bornes prudentes, pas des permissions par
    défaut."""
    p = tmp_path / "partial.json"
    p.write_text('{"broker": "COURTIER"}', encoding="utf-8")
    c = load_capability(str(p))
    assert c.ack_semantics is AckSemantics.UNKNOWN
    assert not c.reconciliation_available
    assert c.qualification_status == "UNQUALIFIED"


def test_an_unrecognised_semantics_value_is_refused_not_ignored(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"ack_semantics": "PROBABLEMENT_ACTIF"}', encoding="utf-8")
    with pytest.raises(ObservabilityError, match="sémantique reconnue"):
        load_capability(str(p))


def test_a_small_uncertainty_is_never_displayed_as_zero():
    """Un arrondi fixe au millième de milliseconde afficherait « ±0.000 ms » pour une
    résolution de 40 ns : une incertitude réelle présentée comme nulle."""
    assert format_ns(40) == "40 ns"
    assert format_ns(200_000) == "200 µs"
    assert format_ns(None) == "—"
    assert "0.000" not in format_ns(40)


def test_the_printed_matrix_names_what_each_aggregate_confuses(capsys):
    """Un agrégat affiché sans sa liste pourrait être lu comme une mesure fine."""
    print_matrix(build_matrix(clock(), connector()))
    out = capsys.readouterr().out
    assert "confond : " in out
    assert "transport_network" in out
    assert "LOWER_BOUND" in out
