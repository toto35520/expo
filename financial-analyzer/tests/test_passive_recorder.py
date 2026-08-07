"""Tests des cinq points d'instrumentation (Q51-A §30).

Le collecteur doit produire exactement ce qu'il a mesuré : une frontière manquante, une
évaluation qui ne conclut pas ou une horloge qui recule ne doivent jamais devenir une
observation plausible.
"""

from __future__ import annotations

import json

import pytest

from feasibility.latency_journal import BurstState, ConnectionState
from feasibility.observability import MeasurementGrade
from feasibility.passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    ClusterAssigner,
    EvaluationMode,
    HostLoad,
    MarketContext,
    PipelineMode,
    summarise_cell,
)
from feasibility.passive_recorder import (
    DropReason,
    PassiveRecorder,
    default_cell_of,
)

MS = NS_PER_MS


class FakeClock:
    """Horloge déterministe : la monotone avance seule, la murale suit ou saute."""

    def __init__(self) -> None:
        self.mono = 0
        self.wall = 1_700_000_000 * NS_PER_SECOND

    def advance(self, ns: int, wall_ns: int | None = None) -> None:
        self.mono += ns
        self.wall += ns if wall_ns is None else wall_ns

    def monotonic_ns(self) -> int:
        return self.mono

    def wall_ns(self) -> int:
        return self.wall


def market(burst_percentile=0.5, tick_rate=12.0, spread=0.18) -> MarketContext:
    return MarketContext(
        tick_rate_100ms=tick_rate * 0.1, tick_rate_1s=tick_rate,
        tick_rate_5s=tick_rate * 5, spread=spread, spread_percentile=0.5,
        price_velocity=0.01, burst_percentile=burst_percentile,
    )


def host(queue=2, lag=100_000) -> HostLoad:
    return HostLoad(queue, queue * 2, lag, 0.4, 10**8)


def recorder(clock: FakeClock, **kw) -> PassiveRecorder:
    base = dict(
        cell_of=default_cell_of(
            session="LONDON", host_id="H1", software_commit="abc123",
            evaluation_mode=EvaluationMode.EVENT_DRIVEN, pipeline=PipelineMode.TARGET,
        ),
        clusters=ClusterAssigner(burst_threshold=100.0, reset_ns=2 * NS_PER_SECOND,
                                 quiet_block_ns=NS_PER_SECOND),
        monotonic_ns=clock.monotonic_ns,
        wall_ns=clock.wall_ns,
    )
    return PassiveRecorder(**{**base, **kw})


def one_evaluation(rec: PassiveRecorder, clock: FakeClock, *, eligibility=1 * MS,
                   wait=2 * MS, compute=5 * MS, decision=1 * MS, m=None, **kw):
    eid = rec.on_quote_received(m or market())
    clock.advance(eligibility)
    rec.on_event_eligible(eid)
    clock.advance(wait)
    rec.on_evaluation_start(eid)
    clock.advance(compute)
    rec.on_evaluation_end(eid)
    clock.advance(decision)
    return rec.on_decision_ready(eid, host(), **kw)


# ============================================= le chemin complet


def test_the_five_points_produce_one_observation():
    clock = FakeClock()
    rec = recorder(clock)
    o = one_evaluation(rec, clock)
    assert o is not None
    assert o.local_lower_bound_ns == 9 * MS
    assert o.eligibility_ns == 1 * MS
    assert o.evaluation_wait_ns == 2 * MS
    assert o.compute_ns == 5 * MS
    assert o.decision_ns == 1 * MS
    assert rec.stats.completed == 1


def test_durations_are_measured_on_the_monotonic_clock():
    """La murale peut sauter ; la durée mesurée ne bouge pas."""
    clock = FakeClock()
    rec = recorder(clock)
    eid = rec.on_quote_received(market())
    clock.advance(1 * MS)
    rec.on_event_eligible(eid)
    clock.advance(2 * MS, wall_ns=-500 * MS)   # correction de synchronisation
    rec.on_evaluation_start(eid)
    clock.advance(5 * MS)
    rec.on_evaluation_end(eid)
    clock.advance(1 * MS)
    o = rec.on_decision_ready(eid, host())
    assert o.local_lower_bound_ns == 9 * MS


def test_an_observed_wall_regression_is_counted_however_small():
    """Le signe est absolu : un seuil de magnitude laisserait passer les petites
    corrections de synchronisation, précisément les plus fréquentes."""
    clock = FakeClock()
    rec = recorder(clock, drift_tolerance_ns=10 * NS_PER_SECOND)
    one_evaluation(rec, clock)                       # la murale avance de 9 ms
    clock.advance(1 * MS, wall_ns=-(9 * MS + 1))     # net : 1 ns en arrière
    one_evaluation(rec, clock)
    assert rec.stats.clock_discontinuities == 1


def test_a_sub_sample_correction_is_caught_by_the_drift_rule_not_by_the_sign():
    """Un recul survenu entre deux échantillons se solde par un ΔW positif : seul
    l'écart ΔW − ΔM le révèle, et lui seul relève d'un seuil."""
    clock = FakeClock()
    rec = recorder(clock, drift_tolerance_ns=5 * MS)
    one_evaluation(rec, clock)
    clock.advance(1 * MS, wall_ns=-6 * MS)           # ΔW = 3 ms, positif, ΔM = 10 ms
    one_evaluation(rec, clock)
    assert rec.stats.clock_discontinuities == 1


def test_ordinary_slew_is_not_reported_as_a_discontinuity():
    """Une correction en douceur produit légitimement un écart non nul."""
    clock = FakeClock()
    rec = recorder(clock, drift_tolerance_ns=5 * MS)
    for _ in range(5):
        one_evaluation(rec, clock)
        clock.advance(1 * MS, wall_ns=1 * MS - 200)  # 200 ns de dérive par tour
    assert rec.stats.clock_discontinuities == 0


def test_a_forward_wall_jump_beyond_tolerance_is_a_discontinuity():
    clock = FakeClock()
    rec = recorder(clock, drift_tolerance_ns=50 * MS)
    one_evaluation(rec, clock)
    clock.advance(1 * MS, wall_ns=500 * MS)
    one_evaluation(rec, clock)
    assert rec.stats.clock_discontinuities == 1


# ============================================= ce que le collecteur refuse


def test_an_evaluation_without_a_decision_produces_nothing():
    clock = FakeClock()
    rec = recorder(clock)
    eid = rec.on_quote_received(market())
    clock.advance(1 * MS)
    rec.on_event_eligible(eid)
    clock.advance(30 * MS)
    o = rec.on_decision_ready(eid, host())     # B3 et B4 manquent
    assert o is None
    assert rec.stats.dropped[DropReason.NO_DECISION.value] == 1
    assert rec.stats.completed == 0


def test_an_unknown_event_id_is_ignored_not_invented():
    clock = FakeClock()
    rec = recorder(clock)
    assert rec.on_decision_ready(9_999, host()) is None
    rec.on_event_eligible(9_999)               # ne doit pas lever
    assert rec.stats.completed == 0


def test_stale_evaluations_are_abandoned_not_left_pending():
    """Une évaluation qui ne conclut jamais n'est pas une évaluation rapide : la laisser
    en attente la ferait sortir du dénominateur, et la latence moyenne s'améliorerait à
    mesure que le système échoue."""
    clock = FakeClock()
    rec = recorder(clock)
    rec.on_quote_received(market())
    rec.on_quote_received(market())
    clock.advance(5 * NS_PER_SECOND)
    assert rec.abandon_stale(NS_PER_SECOND) == 2
    assert rec.in_flight == 0
    assert rec.stats.dropped[DropReason.NO_DECISION.value] == 2


def test_overflow_drops_the_oldest_and_counts_it():
    clock = FakeClock()
    rec = recorder(clock, max_in_flight=3)
    for _ in range(5):
        rec.on_quote_received(market())
        clock.advance(1 * MS)
    assert rec.in_flight == 3
    assert rec.stats.dropped[DropReason.OVERFLOW.value] == 2


def test_the_recorder_never_estimates_a_missing_boundary():
    clock = FakeClock()
    rec = recorder(clock)
    eid = rec.on_quote_received(market())
    clock.advance(1 * MS)
    rec.on_event_eligible(eid)
    clock.advance(2 * MS)
    rec.on_evaluation_start(eid)
    clock.advance(5 * MS)
    # B4 jamais posée
    assert rec.on_decision_ready(eid, host()) is None
    assert rec.drain() == []


# ============================================= cellules et grappes


def test_the_cell_follows_the_continuous_burst_percentile():
    """Les catégories ne servent qu'à présenter ; l'intensité continue décide."""
    clock = FakeClock()
    rec = recorder(clock)
    calm = one_evaluation(rec, clock, m=market(burst_percentile=0.10))
    clock.advance(1 * MS)
    high = one_evaluation(rec, clock, m=market(burst_percentile=0.96))
    clock.advance(1 * MS)
    extreme = one_evaluation(rec, clock, m=market(burst_percentile=0.995))
    assert calm.cell.burst_state is BurstState.NORMAL
    assert high.cell.burst_state is BurstState.BURST_P95
    assert extreme.cell.burst_state is BurstState.BURST_P99


def test_the_continuous_intensity_survives_the_classification():
    """Sans elle, impossible de tracer L_p95(λ) autrement que par catégories."""
    clock = FakeClock()
    rec = recorder(clock)
    o = one_evaluation(rec, clock, m=market(burst_percentile=0.97, tick_rate=340.0))
    assert o.market.burst_percentile == 0.97
    assert o.market.tick_rate_1s == 340.0


def test_a_burst_of_evaluations_shares_one_cluster():
    clock = FakeClock()
    rec = recorder(clock)
    for _ in range(30):
        one_evaluation(rec, clock, m=market(tick_rate=400.0))
        clock.advance(1 * MS)
    assert len({o.cluster_id for o in rec.drain()}) == 1


# ============================================= persistance et effet observateur


def test_the_journal_is_written_append_only(tmp_path):
    path = tmp_path / "q51a.jsonl"
    clock = FakeClock()
    rec = recorder(clock, sink_path=str(path), flush_every=2)
    for _ in range(5):
        one_evaluation(rec, clock)
        clock.advance(1 * MS)
    rec.flush()

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5
    first = json.loads(lines[0])
    assert first["bound_ns"] == 9 * MS
    assert first["b5"] - first["b1"] == first["bound_ns"]
    assert first["cell"].endswith("PIPELINE_TARGET")


def test_a_second_run_appends_rather_than_overwrites(tmp_path):
    """Les données ne se reconstruisent pas après coup : rien n'est jamais réécrit."""
    path = tmp_path / "q51a.jsonl"
    for _ in range(2):
        clock = FakeClock()
        rec = recorder(clock, sink_path=str(path))
        one_evaluation(rec, clock)
        rec.flush()
    assert len(path.read_text(encoding="utf-8").strip().split("\n")) == 2


def test_flushing_without_a_sink_still_clears_the_buffer():
    clock = FakeClock()
    rec = recorder(clock)
    one_evaluation(rec, clock)
    assert rec.flush() == 1
    assert rec.flush() == 0


def test_the_recorder_measures_its_own_cost():
    """Le surcoût est mesuré, pas supposé négligeable — la campagne fait partie du chemin
    critique qu'elle mesure."""
    clock = FakeClock()
    rec = recorder(clock)
    for _ in range(10):
        one_evaluation(rec, clock)
        clock.advance(1 * MS)
    report = rec.observer_effect_report()
    assert "EFFET OBSERVATEUR" in report
    assert "10 réceptions" in report
    assert "coût moyen d'instrumentation" in report


def test_a_zero_instrumentation_cost_is_flagged_not_celebrated():
    """Une horloge monotone réelle ne peut pas ne pas avancer entre l'entrée et la sortie
    d'un appel : zéro révèle une horloge injectée, pas une instrumentation gratuite."""
    clock = FakeClock()
    rec = recorder(clock)
    one_evaluation(rec, clock)
    report = rec.observer_effect_report()
    assert "non mesurable" in report
    assert "horloge\n    injectée" in report


def test_a_real_instrumentation_cost_is_reported_without_the_caveat():
    clock = FakeClock()
    rec = recorder(clock, monotonic_ns=lambda: _ticking(clock))
    one_evaluation(rec, clock)
    report = rec.observer_effect_report()
    assert "par événement" in report
    assert "non mesurable" not in report


def _ticking(clock: FakeClock) -> int:
    """Horloge qui avance de 200 ns à chaque lecture — comme une vraie."""
    clock.mono += 200
    return clock.mono


def test_drops_are_reported_by_cause():
    clock = FakeClock()
    rec = recorder(clock)
    rec.on_quote_received(market())
    clock.advance(5 * NS_PER_SECOND)
    rec.abandon_stale(NS_PER_SECOND)
    assert "NO_DECISION" in rec.observer_effect_report()


# ============================================= bout en bout


def test_a_collected_sample_summarises_without_further_wiring():
    """De la boucle réelle au résumé par cellule, sans étape intermédiaire manuelle."""
    clock = FakeClock()
    rec = recorder(clock)
    for i in range(60):
        one_evaluation(rec, clock, compute=(5 + i % 7) * MS, m=market(tick_rate=400.0))
        clock.advance(1 * MS)
    observations = rec.drain()

    summary = summarise_cell(observations)
    assert summary.observations == 60
    assert summary.clusters == 1
    assert summary.bound.p95 > summary.bound.p50
    assert summary.compute.p95 >= 11 * MS


def test_degraded_clock_observations_are_tagged_at_collection_time():
    clock = FakeClock()
    rec = recorder(clock)
    o = one_evaluation(rec, clock, clock_grade=MeasurementGrade.DEGRADED_CLOCK)
    assert not o.usable_for_local_distribution
    with pytest.raises(Exception, match="horloge exacte"):
        summarise_cell([o])


def test_connection_and_calendar_state_travel_with_the_observation():
    clock = FakeClock()
    rec = recorder(clock)
    o = one_evaluation(rec, clock, connection_state=ConnectionState.CONNECTED_RECOVERED,
                       calendar_state="HALF_SESSION", macro_window=True)
    assert o.connection_state is ConnectionState.CONNECTED_RECOVERED
    assert o.calendar_state == "HALF_SESSION"
    assert o.macro_window
