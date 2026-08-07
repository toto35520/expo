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
    CapturabilityScope,
    ClusterAssigner,
    ContributionRequirement,
    CostFloor,
    EconomicFrequencyRequirement,
    MovingBlockBootstrapBound,
    OpportunitySet,
    OracleCapture,
    most_favourable_floor,
    OrderType,
    OverlapPolicy,
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
    assess_oracle,
    oracle_capturable,
    oracle_verdict,
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
    n = 90_000
    ts = np.arange(n, dtype=np.int64) * 20 * MS          # 30 minutes de cotations
    prices = 2400.0 + np.cumsum(
        np.array([rng.gauss(0, 0.02) for _ in range(n)], dtype=float)
    )
    starts = np.arange(100, n - 200, 45)
    cluster_ids = np.arange(n) // 1_500
    HORIZON = 500 * MS
    # Le plancher le plus favorable parmi les modes autorisés : une exclusion globale
    # ne peut pas reposer sur le seul coût des ordres au marché.
    cost_floor = most_favourable_floor([
        CostFloor(order_type=OrderType.AGGRESSIVE, certain_commission=0.30,
                  mandatory_fees=0.05, observed_crossing=0.10,
                  source="démonstration — barème contractuel à substituer (Q63)"),
        CostFloor(order_type=OrderType.PASSIVE, certain_commission=0.30,
                  mandatory_fees=0.05,
                  source="démonstration — barème contractuel à substituer (Q63)"),
    ])
    # Typées : une exigence statistique ne peut pas être passée ici, et l'unité de la
    # contribution est vérifiée contre celle de la capacité.
    FREQ_REQ = EconomicFrequencyRequirement(
        value_per_second=4 / 86_400.0, q1_reference="démonstration — Q1 à figer",
        derived_from="(J_min + coûts) / EV_U, valeurs de démonstration")
    CONTRIB = ContributionRequirement(
        value_per_second=20.0 / 86_400.0, unit="USD/oz",
        q1_reference="démonstration — Q1 à figer")
    DELTA_MEU = 0.05
    MIN_CLUSTERS = 20      # à dériver du protocole de puissance (Q64), pas d'un défaut

    print("-" * 78)
    print("PHASE 0 PAR CELLULE — exclusion sans qu'aucun signal ne soit défini")
    print(f"horizon 500 ms · plancher de coûts {cost_floor.value:.2f} $/oz"
          f" · δ_MEU {DELTA_MEU:.2f}"
          f" · f_econ {FREQ_REQ.value_per_second * 86_400:.0f}/jour")
    print(f"période observée : {(ts[-1] - ts[0]) / NS_PER_SECOND / 60:.0f} min"
          f" — toute fréquence par jour en est une extrapolation")
    print()
    for cell in sorted(summaries, key=lambda c: c.label):
        sample = capturability_input(
            [o for o in observations if o.cell == cell], clock
        )
        capture = oracle_capturable(
            ts, prices, starts, sample.latency_samples_ns, HORIZON,
            sample.scope, cluster_ids=cluster_ids,
        )
        opportunities = OpportunitySet(
            starts_ns=capture.starts_ns, horizon_ns=HORIZON, span_ns=capture.span_ns,
            cooldown_ns=0, max_concurrent_positions=1,
            overlap_policy=OverlapPolicy.DISJOINT_WINDOWS,
            session=cell.session, cell_label=cell.label,
        )
        assessment = assess_oracle(capture, cost_floor, opportunities, DELTA_MEU,
                                   estimator=MovingBlockBootstrapBound(
                                       block_length=3,
                                       dependence_argument="démonstration — longueur de "
                                                           "bloc à calibrer sur la "
                                                           "persistance réelle",
                                       reference="protocole Q59, à figer",
                                       draws=400))   # sans qualification de couverture
        oracle, why = oracle_verdict(assessment, FREQ_REQ, CONTRIB,
                                     min_clusters=MIN_CLUSTERS)
        state, state_why = phase0_state(
            cost_excluded=False,
            passive=PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE
            if summaries[cell].clusters < 20 else
            PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
            oracle=oracle,
        )
        q = assessment.quantiles
        print(f"  {cell.burst_state.value:<12} {state.value}")
        print(f"    borne locale p95 : {summaries[cell].bound.p95 / MS:.1f} ms"
              f"   ({sample.result_name})")
        print(f"    capture oracle   : p50 {q.p50:.3f} · p90 {q.p90:.3f} · p99 {q.p99:.3f}"
              f" · max {q.maximum:.3f}   ← diagnostics, aucun n'exclut à lui seul")
        print(f"    opportunités     : {assessment.selected} retenues sur "
              f"{assessment.opportunities} départs (chevauchement écarté)")
        print(f"    oracle-rentables : {assessment.rarity.describe()}")
        print(f"    oracle            : {assessment.kind.value}")
        print(f"    verdict oracle   : {oracle.value}")
        print(f"      {why}")
        print(f"    → {state_why}")
        print()

    # ---- contre-exemple : pourquoi un quantile seul n'exclut jamais
    tail_gross = np.array([0.20] * 920 + [3.00] * 80)
    tail_starts = np.arange(1_000, dtype=np.int64) * NS_PER_SECOND
    tail = OracleCapture(tail_starts, tail_gross, HORIZON,
                         CapturabilityScope.POST_RECEIVE_ONLY,
                         span_ns=1_000 * NS_PER_SECOND, clusters=50,
                         exhausted_fraction=0.0,
                         episode_ids=np.arange(tail_gross.size) // 20)
    tail_set = OpportunitySet(starts_ns=tail_starts, horizon_ns=HORIZON,
                              span_ns=1_000 * NS_PER_SECOND,
                              overlap_policy=OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE)
    tail_assessment = assess_oracle(tail, cost_floor, tail_set, DELTA_MEU)
    tail_verdict, tail_why = oracle_verdict(tail_assessment, FREQ_REQ, CONTRIB,
                                            min_clusters=MIN_CLUSTERS)

    print("-" * 78)
    print("CONTRE-EXEMPLE — 92 % de situations impossibles, 8 % très favorables")
    print(f"  capture oracle p90 : {tail.quantiles.p90:.3f}"
          f"  ≤  plancher de coûts {cost_floor.value:.2f}")
    print("  le raccourci « p90 ≤ plancher ⇒ exclusion » aurait supprimé cette cellule.")
    print(f"  or {tail_assessment.profitable} opportunités sur "
          f"{tail_assessment.selected} dégagent un surplus, la plus favorable de "
          f"{tail_assessment.max_surplus:.2f}.")
    print(f"  verdict correct : {tail_verdict.value}")
    print(f"    {tail_why}")
    print()
    print("  C'est précisément le profil d'une stratégie sélective : rare, mais réelle.")
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
