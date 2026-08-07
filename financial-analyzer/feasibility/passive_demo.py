"""Démonstration exécutable de la campagne passive Q51-A.

    python3 -m feasibility.passive_demo

**Aucun chiffre produit ici ne décrit un système réel.** Le flux, la charge et les rafales
sont simulés : l'exécution renseigne sur le câblage des cinq points d'instrumentation, pas
sur la latence de quoi que ce soit. C'est un test de branchement, à remplacer par la boucle
réelle dès qu'elle existe.

Ce que la démonstration montre effectivement :

- les cinq points produisent des observations complètes ;
- la latence se dégrade en rafale, donc le p95 conditionnel dépasse le p95 global ;
- le verdict, le budget résiduel et l'embranchement Q42 s'enchaînent sans intervention.
"""

from __future__ import annotations

import random

import numpy as np

from .latency_journal import ConnectionState
from .observability import (
    CorrectionMode,
    GranularityTest,
    MeasurementGrade,
    Virtualization,
    blank_capability,
    build_matrix,
    print_matrix,
    q57_resolved,
    qualify_clock,
)
from .sequential import InferenceMode, rho_for_target
from .passive_campaign import (  # noqa: E402
    NS_PER_MS,
    NS_PER_SECOND,
    BlockingChoice,
    ClusterAssigner,
    EvaluationMode,
    HostLoad,
    MarketContext,
    PipelineMode,
    StoppingPolicy,
    assess_stopping,
    block_sensitivity,
    blocking_is_robust,
    capturability_input,
    coverage,
    daily_report,
    hourly_report,
    is_stable,
    PassiveVerdict,
    oracle_capturable,
    oracle_exclusion,
    phase0_state,
    stability_trace,
    summarise_by_cell,
)
from .passive_recorder import PassiveRecorder, default_cell_of

MS = NS_PER_MS


class _SimClock:
    def __init__(self) -> None:
        self.mono = 0
        self.wall = 1_770_000_000 * NS_PER_SECOND

    def advance(self, ns: int) -> None:
        self.mono += ns
        self.wall += ns

    def monotonic_ns(self) -> int:
        return self.mono

    def wall_ns(self) -> int:
        return self.wall


def _demo_clock():
    g_mono = GranularityTest(41, 55.0, 180.0, 0.0)
    g_wall = GranularityTest(1_000, 1_100.0, 3_000.0, 0.01)
    return qualify_clock(
        host_id="hote-de-demonstration",
        granularity_wall=g_wall, granularity_monotonic=g_mono,
        monotonic_failures=0, wall_discontinuities=0, drift_p95_ppm=3.0,
        measured_uncertainty_ns=None,
        correction_mode=CorrectionMode.SLEW, virtualization=Virtualization.VM,
        suspend_events=0, sync_method="NTP", qualified_at_ns=0,
        wall_mono_samples=120_000,
        intersystem_uncertainty_declared_unknown=True,
    )


def _simulate(days: int = 6, seed: int = 7):
    """Journée simulée : périodes calmes entrecoupées de rafales, avec une file qui se
    remplit — donc une latence qui se dégrade là où les signaux apparaîtraient."""
    rng = random.Random(seed)
    clock = _SimClock()
    observations = []

    for day in range(days):
        rec = PassiveRecorder(
            cell_of=default_cell_of(
                session="LONDON_NY_OVERLAP", host_id="hote-de-demonstration",
                software_commit="demo", evaluation_mode=EvaluationMode.EVENT_DRIVEN,
                pipeline=PipelineMode.TARGET,
            ),
            clusters=ClusterAssigner(
                burst_threshold=120.0, reset_ns=3 * NS_PER_SECOND,
                quiet_block_ns=30 * NS_PER_SECOND, session_id=f"J{day}",
            ),
            monotonic_ns=clock.monotonic_ns,
            wall_ns=clock.wall_ns,
            day_of=lambda _w, d=day: f"2026-08-{d + 1:02d}",
        )

        for episode in range(40):
            in_burst = episode % 5 == 0
            n = 60 if in_burst else 25
            for _ in range(n):
                if in_burst:
                    rate = rng.uniform(150, 600)
                    queue = rng.randint(20, 200)
                    pct = rng.uniform(0.95, 0.999)
                else:
                    rate = rng.uniform(3, 40)
                    queue = rng.randint(0, 4)
                    pct = rng.uniform(0.05, 0.70)

                market = MarketContext(
                    tick_rate_100ms=rate * 0.1, tick_rate_1s=rate, tick_rate_5s=rate * 5,
                    spread=0.14 + (0.5 if in_burst else 0.0) * rng.random(),
                    spread_percentile=pct, price_velocity=rng.random() * 0.4,
                    burst_percentile=pct,
                )
                eid = rec.on_quote_received(market)
                clock.advance(int(rng.uniform(0.1, 0.6) * MS))
                rec.on_event_eligible(eid)
                # L'attente d'évaluation croît avec la file : c'est le mécanisme qui rend
                # la distribution conditionnelle différente de la marginale.
                clock.advance(int((0.2 + queue * 0.35) * MS))
                rec.on_evaluation_start(eid)
                clock.advance(int(rng.uniform(1.5, 4.0) * MS * (2.2 if in_burst else 1.0)))
                rec.on_evaluation_end(eid)
                clock.advance(int(rng.uniform(0.2, 0.8) * MS))
                rec.on_decision_ready(
                    eid,
                    HostLoad(queue, queue * 2, int(queue * 0.2 * MS),
                             0.3 + (0.5 if in_burst else 0.0), 3 * 10**8),
                    connection_state=ConnectionState.CONNECTED_STABLE,
                    calendar_state="OPEN",
                    clock_grade=MeasurementGrade.EXACT_LOCAL,
                )
                clock.advance(int(rng.uniform(2, 40) * MS))
            clock.advance(int(rng.uniform(1, 6) * NS_PER_SECOND))

        rec.flush()
        observations.extend(rec.drain())
        if day == 0:
            first_report = hourly_report(observations[:400])
            first_effect = rec.observer_effect_report()

    return observations, first_report, first_effect


def main() -> None:
    clock = _demo_clock()
    connector = blank_capability("COURTIER", "REEL")

    print("=" * 78)
    print("CAMPAGNE PASSIVE Q51-A — DÉMONSTRATION SUR DONNÉES SIMULÉES")
    print("Aucun chiffre ci-dessous ne décrit un système réel.")
    print("=" * 78)
    print()

    print_matrix(build_matrix(clock, connector))
    ok57, missing57 = q57_resolved(clock)
    print()
    print(f"  Q57 résolue : {ok57}" + ("" if ok57 else f" — {missing57}"))
    print()

    observations, first_hour, effect = _simulate()

    print("-" * 78)
    print(first_hour)
    print()
    print(effect)
    print()
    print("-" * 78)
    print(daily_report(observations, clock))
    print()

    summaries = summarise_by_cell(observations)

    # ---- Q61-A : exclusion signal-agnostique, sans aucun Lmax inventé
    rng = random.Random(11)
    n = 6_000
    ts = np.arange(n, dtype=np.int64) * 10 * MS
    prices = 2400.0 + np.cumsum(
        np.array([rng.gauss(0, 0.02) for _ in range(n)], dtype=float)
    )
    starts = np.arange(100, n - 200, 45)
    cluster_ids = np.arange(n) // 150
    COST_FLOOR = 0.35          # plancher de coûts aller-retour, en dollars l'once

    print("-" * 78)
    print("PHASE 0 PAR CELLULE — exclusion sans qu'aucun signal ne soit défini")
    print(f"horizon 500 ms · plancher de coûts {COST_FLOOR:.2f} $/oz")
    print()
    for cell in sorted(summaries, key=lambda c: c.label):
        sample = capturability_input(
            [o for o in observations if o.cell == cell], clock
        )
        capture = oracle_capturable(
            ts, prices, starts, sample.latency_samples_ns, 500 * MS,
            sample.scope, cluster_ids=cluster_ids,
        )
        oracle, why = oracle_exclusion(capture, COST_FLOOR)
        state, state_why = phase0_state(
            cost_excluded=False,
            passive=PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE
            if summaries[cell].clusters < 20 else
            PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
            oracle=oracle,
        )
        print(f"  {cell.burst_state.value:<12} {state.value}")
        print(f"    borne locale p95 : {summaries[cell].bound.p95 / MS:.1f} ms"
              f"   ({sample.result_name})")
        print(f"    {why}")
        print(f"    → {state_why}")
        print()

    choice = BlockingChoice(
        block_ns=30 * NS_PER_SECOND,
        source="valeur de démonstration — à confronter à l'autocorrélation réelle",
        version="demo-v1",
    )
    sens = block_sensitivity(observations, choice, 120.0, 3 * NS_PER_SECOND)
    print("-" * 78)
    print("SENSIBILITÉ AU DÉCOUPAGE DU RÉGIME CALME")
    for entry in sens:
        print(f"  bloc {entry.block_ns / NS_PER_SECOND:5.1f} s"
              f"   {entry.clusters:>4} grappes"
              f"   p95 {entry.p95_ns / MS:6.2f} ms"
              f"   [{entry.ci_low_ns / MS:6.2f} ; {entry.ci_high_ns / MS:6.2f}]")
    robust = blocking_is_robust(sens, threshold_ns=200 * MS)
    print(f"  verdict robuste au découpage (seuil 200 ms) : {robust}")
    print()

    trace = stability_trace(observations)
    print("-" * 78)
    print("STABILITÉ SÉQUENTIELLE — p95 cumulé, toutes cellules confondues")
    for snap in trace:
        print(f"  {snap.day}   p95 {snap.p95_ns / MS:7.2f} ms"
              f"   [{snap.ci_low_ns / MS:6.2f} ; {snap.ci_high_ns / MS:6.2f}]"
              f"   {snap.cumulative_clusters} grappes")
    print(f"  stabilisé : {is_stable(trace)}")
    print()

    policy = StoppingPolicy(
        declared_at_ns=0, declared_by="démonstration",
        min_days=10, min_sessions=3, min_clusters_per_cell=30,
        min_burst_p95_clusters=40, min_burst_p99_clusters=15,
        max_relative_ci_width=0.20,
        required_clock_qualification=clock.qualification.value,
        inference_mode=InferenceMode.ANYTIME_VALID,
        rho=rho_for_target(400),
    )
    assessment = assess_stopping(policy, coverage(observations), summaries, 0, clock)
    print("-" * 78)
    print(f"POLITIQUE D'ARRÊT {policy.fingerprint} — {assessment.decision.value}"
          f"   ({policy.inference_mode.value})")
    for reason in assessment.reasons:
        print(f"  · {reason}")
    print()

    burst_cells = [c for c in summaries if c.burst_state.value.startswith("BURST")]
    if burst_cells:
        sample = capturability_input(
            [o for o in observations if o.cell == burst_cells[0]], clock
        )
        print("-" * 78)
        print("À TRANSMETTRE À LA PHASE 0 DE Q19")
        print(f"  cellule       : {sample.cell.label}")
        print(f"  échantillon   : {sample.latency_samples_ns.size} latences,"
              f" {sample.clusters} grappes")
        print(f"  ancrage       : {sample.anchor.value}")
        print(f"  portée        : {sample.scope.value}  →  {sample.result_name}")
        print(f"  fin d'horizon : {sample.horizon_end_policy.value}")
        if sample.is_upper_bound_of_capturability:
            print(f"  ⚠ {sample.interpret(excluded=False)}")
    print()
    print("Non mesuré, et donc jamais compté : émission, réseau, traitement courtier,")
    print("file, activation, exécution, glissement, sélection adverse.")


if __name__ == "__main__":
    main()
