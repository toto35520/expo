"""Exécution des deux phases 0 et production de la carte de faisabilité.

    python3 -m feasibility.report

Sans argument, le rapport tourne sur des **données synthétiques** : il démontre que la
chaîne s'exécute, il ne dit rien de l'or. Les valeurs réelles exigent le flux du courtier
et une campagne de mesure de latence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import time as dt_time

import numpy as np

from .costs import modeled_round_trip_cost
from .envelope import CellEnvelope, combine, summarise
from .frequency import (
    OccurrenceCensus,
    assess_frequency,
    economic_frequency_floor,
    statistical_frequency_floor,
)
from .kappa import kappa_with_ci, minimum_cost_horizon
from .latency import detect_price_events, evaluation_latency_percentile, phase0_residual
from .model import (
    Cell,
    Conventions,
    CostMethod,
    PlausibleEdgeBand,
    Provenance,
    ReferencePriceConvention,
    RoundTripDefinition,
    SpreadCountingConvention,
)
from .scale import displacement_sample, realized_scale, sqrt_time_diagnostic
from .synthetic import NS_PER_SECOND, generate, latency_samples

HORIZON_GRID_SECONDS = (1, 5, 15, 30, 60, 120, 300, 600, 1_800, 3_600, 7_200)


@dataclass
class ReportInputs:
    timestamps_ns: np.ndarray
    mid: np.ndarray
    spread: np.ndarray
    cluster_ids: np.ndarray
    latency_quiet_ns: np.ndarray
    latency_burst_ns: np.ndarray
    commission_round_trip: float
    band: PlausibleEdgeBand
    cell: Cell
    conventions: Conventions
    step: int = 41


def _fmt(x: float, width: int = 8, digits: int = 3) -> str:
    return "—".rjust(width) if not np.isfinite(x) else f"{x:{width}.{digits}f}"


def run(inp: ReportInputs, horizons_ns: tuple[int, ...] | None = None) -> list[CellEnvelope]:
    grid = horizons_ns or tuple(h * NS_PER_SECOND for h in HORIZON_GRID_SECONDS)

    provenance = Provenance(
        conventions_digest=inp.conventions.digest(),
        protocol_version=inp.conventions.protocol_version,
        cost_model_version=inp.conventions.cost_model_version,
        data_start_ns=int(inp.timestamps_ns[0]),
        data_end_ns=int(inp.timestamps_ns[-1]),
    )

    span_days = (inp.timestamps_ns[-1] - inp.timestamps_ns[0]) / (86_400 * NS_PER_SECOND)
    spread_sample = inp.spread[:: inp.step]
    cost_clusters = inp.cluster_ids[:: inp.step]

    print("=" * 96)
    print("CARTE DE FAISABILITÉ — intersection coût × latence × fréquence")
    print("=" * 96)
    print(f"Cellule            : {inp.cell.cell_id}")
    print(f"Conventions        : {inp.conventions.cost_measurement_method.value} / "
          f"{inp.conventions.spread_counting_convention.value} / digest {provenance.conventions_digest}")
    print(f"Bande plausible    : [{inp.band.a_min:g} ; {inp.band.a_max:g}] σ "
          f"— déclarée le {inp.band.declared_at} ({inp.band.source})")
    print(f"Observations       : {inp.timestamps_ns.size} ticks sur {span_days:.1f} jours, "
          f"{np.unique(inp.cluster_ids).size} blocs indépendants")
    print(f"Spread aller-retour: médiane {np.median(spread_sample):.4f}  p95 {np.quantile(spread_sample, 0.95):.4f}")
    print(f"Commission A/R     : {inp.commission_round_trip:.4f}")

    # ---- latence conditionnelle (ADR-102) --------------------------------------------
    l95_quiet = evaluation_latency_percentile(inp.latency_quiet_ns, 0.95)
    l95_burst = evaluation_latency_percentile(inp.latency_burst_ns, 0.95)
    print()
    print("LATENCE  p95 hors rafale : "
          f"{l95_quiet / 1e6:7.1f} ms      p95 en rafale : {l95_burst / 1e6:7.1f} ms"
          f"      écart ×{l95_burst / l95_quiet:.2f}")
    print("         Le gate utilise le centile EN RAFALE : c'est là que les signaux se déclenchent.")

    # ---- phase 0 de Q19 ---------------------------------------------------------------
    starts, signs = detect_price_events(
        inp.timestamps_ns, inp.mid, window_ns=2 * NS_PER_SECOND, quantile=0.995
    )
    round_trip_cost_p95 = float(np.quantile(spread_sample, 0.95)) + inp.commission_round_trip

    print()
    print(f"ÉVÉNEMENTS DE PRIX  {starts.size} détectés (définition par le prix seul, sans signal)")
    print()
    print("PHASE 0 Q19 — part du mouvement déjà consommée à l'instant où l'on pourrait agir")
    print(f"{'horizon':>9} {'consommé p50':>13} {'résiduel p50':>13} {'net p50':>10}  verdict")
    print("-" * 96)

    phase0_by_horizon = {}
    for h in grid:
        h_s = h / NS_PER_SECOND
        res = phase0_residual(
            inp.timestamps_ns, inp.mid, inp.cluster_ids, starts, signs,
            inp.latency_burst_ns, h, round_trip_cost_p95, min_clusters=20,
        )
        phase0_by_horizon[h] = res
        print(f"{h_s:>8.0f}s {res.consumed_fraction_p50:>12.0%} "
              f"{_fmt(res.residual_p50, 13, 4)} {_fmt(res.residual_net_p50, 10, 4)}  {res.verdict.value}")

    # ---- courbe kappa -----------------------------------------------------------------
    print()
    print("PHASE 0 Q40 — kappa : unités d'amplitude à capturer pour seulement couvrir les frais")
    print(f"{'horizon':>9} {'amplitude':>11} {'kappa p50':>11} {'kappa p95':>11} "
          f"{'IC 90%':>19} {'blocs':>6}  verdict")
    print("-" * 96)

    kappa_results = []
    scale_estimates = []
    for h in grid:
        h_s = h / NS_PER_SECOND
        disp, disp_clusters = displacement_sample(
            inp.timestamps_ns, inp.mid, h, inp.cluster_ids, step=inp.step
        )
        scale_estimates.append(
            realized_scale(inp.timestamps_ns, inp.mid, h, inp.cluster_ids, step=inp.step)
        )
        cost = modeled_round_trip_cost(
            inp.cell, inp.conventions, spread_sample, cost_clusters, inp.commission_round_trip
        )
        r = kappa_with_ci(cost, disp, disp_clusters, h, inp.band, n_bootstrap=200, min_clusters=20)
        kappa_results.append(r)
        ci = f"[{_fmt(r.confidence_lower, 6)},{_fmt(r.confidence_upper, 7)}]"
        print(f"{h_s:>8.0f}s {_fmt(r.scale, 11, 4)} {_fmt(r.kappa_p50, 11)} {_fmt(r.kappa_p95, 11)} "
              f"{ci:>19} {r.sample.independent_clusters:>6}  {r.verdict.value}")

    h_min = minimum_cost_horizon(kappa_results, inp.band)
    print()
    if h_min.horizon_ns is None:
        print(f"HORIZON MINIMAL DE COÛT : aucun — {h_min.reason}")
    else:
        print(f"HORIZON MINIMAL DE COÛT : {h_min.horizon_ns / NS_PER_SECOND:.0f}s ({h_min.reason})")

    diag = sqrt_time_diagnostic(scale_estimates)
    if diag:
        ratios = [d["ratio"] for d in diag]
        print(f"DIAGNOSTIC √h          : ratio observé/attendu de {min(ratios):.2f} à {max(ratios):.2f} "
              "— contrôle d'ordre de grandeur, la mesure empirique fait foi")

    # ---- fréquence ---------------------------------------------------------------------
    census = OccurrenceCensus(
        raw_occurrences=int(starts.size),
        observation_span_days=float(span_days),
        independent_clusters=int(np.unique(inp.cluster_ids[starts]).size),
        regimes_covered=2,
    )
    f_econ = economic_frequency_floor(
        target_contribution_per_day=1.0,
        fixed_costs_per_day=0.5,
        fill_probability=0.9,
        optimistic_ev_per_occurrence=0.5,
    )
    f_stat = statistical_frequency_floor(min_independent_clusters=30, observation_span_days=span_days)
    freq = assess_frequency(census, f_econ, f_stat)
    print()
    print(f"FRÉQUENCE  {census.per_day:.2f} occurrences/jour · plancher économique {f_econ:.2f} · "
          f"plancher statistique {f_stat:.2f} → {freq.verdict.value}")
    print(f"           {freq.rationale}")

    # ---- enveloppe ---------------------------------------------------------------------
    print()
    print("ENVELOPPE — D_cost ∩ D_latency ∩ D_frequency")
    print(f"{'horizon':>9}  {'coût':>18} {'latence':>22} {'fréquence':>24}  verdict")
    print("-" * 96)

    envelopes = []
    for r in kappa_results:
        p0 = phase0_by_horizon.get(r.horizon_ns)
        env = combine(inp.cell, r.horizon_ns, r, p0, freq, provenance)
        envelopes.append(env)
        print(f"{r.horizon_ns / NS_PER_SECOND:>8.0f}s  {env.cost_verdict.value:>18} "
              f"{env.latency_verdict.value:>22} {env.frequency_verdict.value:>24}  {env.verdict.value}")

    print()
    print("RÉSUMÉ :", ", ".join(f"{k} × {v}" for k, v in sorted(summarise(envelopes).items())))
    print()
    print("RAPPEL : `ELIGIBLE_FOR_PREDICTIVE_TESTING` ne signifie pas rentable. Cela signifie")
    print("         qu'aucun des trois arguments d'exclusion ne s'applique à cette cellule.")
    print("=" * 96)
    return envelopes


def synthetic_inputs() -> ReportInputs:
    ticks = generate()
    quiet, burst = latency_samples()
    return ReportInputs(
        timestamps_ns=ticks.timestamps_ns,
        mid=ticks.mid,
        spread=ticks.spread,
        cluster_ids=ticks.cluster_ids,
        latency_quiet_ns=quiet,
        latency_burst_ns=burst,
        commission_round_trip=0.07,
        band=PlausibleEdgeBand(
            a_min=0.05,
            a_max=0.30,
            source="bande de démonstration — à remplacer par une bande préenregistrée (Q46)",
            declared_at="2026-08-06",
        ),
        cell=Cell("XAUUSD", "SYNTHETIC", "SYNTHETIC", "MARKET", "ALL", 0.05, "NORMAL"),
        conventions=Conventions(
            cost_measurement_method=CostMethod.MODELED,
            reference_price_convention=ReferencePriceConvention.MID_TO_MID,
            round_trip_definition=RoundTripDefinition.ENTRY_AND_EXIT,
            spread_counting_convention=SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
            protocol_version="Q40_PHASE0_1.0",
            cost_model_version="Q40_COST_1.0",
        ),
    )


def run_from_export(
    raw,
    contract,
    conventions: Conventions,
    band: PlausibleEdgeBand,
    cell: Cell,
    latency_burst_ns: np.ndarray,
    latency_quiet_ns: np.ndarray,
    horizons_ns: tuple[int, ...],
    volume_lots: float = 0.05,
) -> None:
    """Chemin réel : export courtier → diagnostic de qualité → carte, en trois scénarios.

    L'ordre est imposé. Une carte de faisabilité affichée sans le diagnostic qui la précède
    ne permet pas de savoir si elle est interprétable.
    """
    from .adapter import SessionResolver, normalize
    from .calendar import synthetic_calendar
    from .contract import CostPolicy, CostScenario
    from .quality import build_calculation_inputs, print_quality_report

    quotes = normalize(raw, contract, SessionResolver())
    # Le générateur produit ses ticks de 09h00 à 13h00 UTC : le calendrier de
    # démonstration est aligné dessus. Avec un vrai fuseau, l'écart apparaîtrait
    # immédiatement — le Royaume-Uni était par exemple à UTC+1 toute l'année en 1970,
    # ce qu'un décalage codé en dur n'aurait jamais montré.
    calendar = synthetic_calendar(
        market_id=contract.instrument_id,
        timezone="UTC",
        session_start=dt_time(9, 0),
        session_end=dt_time(13, 0),
    )
    report = None

    for scenario in (CostScenario.OPTIMISTIC, CostScenario.CENTRAL, CostScenario.PRUDENT):
        policy = CostPolicy(
            scenario=scenario,
            volume_lots=volume_lots,
            unmeasured_slippage_bound=0.05,
            unmeasured_impact_bound=0.02,
            unmeasured_adverse_selection_bound=0.03,
            rationale="bornes de démonstration — à remplacer par une campagne d'exécution (Q42)",
        )
        built = build_calculation_inputs(
            quotes, contract, policy, conventions, horizons_ns, band, cell, calendar
        )

        if report is None:
            report = built.report
            print_quality_report(report, horizons_ns)

        measurable = tuple(h for h in horizons_ns if h in report.measurable_horizons)
        print()
        print(f"┌── SCÉNARIO {scenario.value} — {len(measurable)} horizons mesurables sur "
              f"{len(horizons_ns)}")
        print(f"│   Les coûts non mesurés sont traités par scénario, jamais fixés à zéro :")
        print(f"│   provision retenue {policy.unmeasured_allowance():.4f} par aller-retour")
        print("└" + "─" * 90)

        run(
            ReportInputs(
                timestamps_ns=built.timestamps_ns,
                mid=built.mid,
                spread=built.spread_cost,
                cluster_ids=built.cluster_ids,
                latency_quiet_ns=latency_quiet_ns,
                latency_burst_ns=latency_burst_ns,
                commission_round_trip=built.commission_round_trip_quote,
                band=band,
                cell=cell,
                conventions=conventions,
            ),
            horizons_ns=measurable,
        )


def synthetic_export():
    """Reconstruit un export courtier plausible à partir du générateur synthétique."""
    from .adapter import RawQuotes
    from .contract import ContractSpecification, ExecutionMode

    ticks = generate()
    half = ticks.spread / 2.0
    raw = RawQuotes(
        receive_timestamps_ns=ticks.timestamps_ns,
        bid=ticks.mid - half,
        ask=ticks.mid + half,
        source="SYNTHETIC_EXPORT",
    )
    contract = ContractSpecification(
        broker="BROKER_DEMO", account_type="RAW", symbol="XAUUSD",
        underlying="XAU", quote_currency="USD",
        contract_size=100.0, tick_size=0.01, tick_value=1.0,
        minimum_volume=0.01, volume_step=0.01,
        commission_per_side_per_lot=3.5,
        swap_long_per_lot_per_day=-12.0, swap_short_per_lot_per_day=4.0,
        triple_swap_weekday=2, triple_swap_verified=True,
        execution_mode=ExecutionMode.MARKET,
        source="valeurs de démonstration — à remplacer par la fiche du compte réel (Q44)",
        retrieved_at="2026-08-06", version="DEMO_1.0",
    )
    return raw, contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-arrays", action="store_true",
        help="chemin direct sans adaptateur (diagnostic de qualité omis)",
    )
    args = parser.parse_args()

    print()
    print("⚠  DONNÉES SYNTHÈTIQUES — aucune valeur ci-dessous ne décrit un marché réel.")
    print("   Le rapport démontre que la chaîne s'exécute ; les chiffres décrivent le générateur.")
    print()

    if args.raw_arrays:
        run(synthetic_inputs())
        return

    raw, contract = synthetic_export()
    quiet, burst = latency_samples()
    inp = synthetic_inputs()
    run_from_export(
        raw=raw,
        contract=contract,
        conventions=inp.conventions,
        band=inp.band,
        cell=Cell("XAUUSD", "SYNTHETIC", contract.instrument_id, "MARKET", "ALL", 0.05, "NORMAL"),
        latency_burst_ns=burst,
        latency_quiet_ns=quiet,
        horizons_ns=tuple(h * NS_PER_SECOND for h in HORIZON_GRID_SECONDS),
    )


if __name__ == "__main__":
    main()
