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
from .passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    AdmissibleLatency,
    ClusterAssigner,
    EvaluationMode,
    HostLoad,
    MarketContext,
    PipelineMode,
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
    admissible = AdmissibleLatency(
        horizon_ns=NS_PER_SECOND, max_admissible_ns=200 * MS,
        source="valeur de démonstration — à remplacer par la politique de risque réelle",
        declared_at_ns=0,
    )

    print("-" * 78)
    print("VERDICT PAR CELLULE — horizon 1 s, latence admissible déclarée 200 ms")
    print()
    for cell in sorted(summaries, key=lambda c: c.label):
        s = summaries[cell]
        verdict, why = passive_verdict(s, admissible, clock=clock)
        budget = latency_budget_ns(s, admissible)
        priority, _ = q42_priority(cost_excluded=False, passive=verdict)
        print(f"  {cell.burst_state.value:<12} {verdict.value}")
        print(f"    {why}")
        print(f"    budget restant pour tout le trajet courtier : {budget / MS:+.1f} ms")
        print(f"    Q42 : {priority.value}")
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
    )
    assessment = assess_stopping(policy, coverage(observations), summaries, 0, clock)
    print("-" * 78)
    print(f"POLITIQUE D'ARRÊT {policy.fingerprint} — {assessment.decision.value}")
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
        if sample.is_upper_bound_of_capturability:
            print("  ⚠ ancrage local : le mouvement survenu avant la réception n'est pas")
            print("    compté comme perdu. La fraction capturable en ressort **surestimée**,")
            print("    donc une exclusion reste concluante mais une non-exclusion est faible.")
    print()
    print("Non mesuré, et donc jamais compté : émission, réseau, traitement courtier,")
    print("file, activation, exécution, glissement, sélection adverse.")


if __name__ == "__main__":
    main()
