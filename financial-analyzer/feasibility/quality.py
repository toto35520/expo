"""Rapport de qualité et construction des entrées de calcul.

Le jalon n'est pas « obtenir la vraie courbe kappa » mais « prouver que l'export permet
de la mesurer ». Ce module produit cette preuve — ou son absence — et **refuse** de
fabriquer des entrées de calcul quand elle manque.

La carte de faisabilité ne doit jamais être affichée seule : sans le diagnostic qui
précède, rien n'indique si elle est interprétable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .adapter import (
    NS_PER_SECOND,
    AdapterError,
    DensityDiagnostic,
    DensityStatus,
    Gap,
    NormalizedQuotes,
    QuoteQuality,
    classify_gaps,
    density_diagnostic,
)
from .calendar import GapClassification, VersionedMarketCalendar
from .contract import ContractSpecification, CostPolicy, CostScenario
from .model import Cell, Conventions, PlausibleEdgeBand


class Measurability(str, Enum):
    """Verdict portant sur la **mesure**, distinct de tout verdict économique."""

    #: L'export permet de mesurer kappa sur cet horizon.
    MEASURABLE = "MEASURABLE"
    #: Densité insuffisante ou saturation par le pas de cotation : aucun verdict
    #: économique n'est prononçable, quel que soit le résultat du calcul.
    NOT_MEASURABLE = "NOT_MEASURABLE"
    #: Mesurable sous réserve — données censurées, horloges douteuses, échantillon court.
    MEASURABLE_WITH_RESERVATIONS = "MEASURABLE_WITH_RESERVATIONS"


@dataclass
class QualityReport:
    span_days: float
    quotes_total: int
    quotes_usable: int
    sessions: int
    independent_clusters: int
    duplicate_fraction: float
    out_of_order_fraction: float
    crossed_quote_fraction: float
    zero_spread_fraction: float
    suspected_bad_tick_fraction: float
    spread_quantiles: dict[float, float]
    tick_rate_by_session: dict[str, float]
    gaps_by_class: dict[str, int]
    censored_fraction: float
    clock_usable: bool
    resolution_sufficient_for_bursts: bool
    calendar_version: str
    density: dict[int, DensityDiagnostic] = field(default_factory=dict)
    reservations: list[str] = field(default_factory=list)

    def measurability(self, horizon_ns: int) -> Measurability:
        diag = self.density.get(horizon_ns)
        if diag is None or diag.status in (
            DensityStatus.DENSITY_INVALID,
            DensityStatus.DENSITY_QUANTIZED,
        ):
            return Measurability.NOT_MEASURABLE
        if diag.status is DensityStatus.DENSITY_SPARSE or self.reservations:
            return Measurability.MEASURABLE_WITH_RESERVATIONS
        return Measurability.MEASURABLE

    @property
    def measurable_horizons(self) -> list[int]:
        return [h for h in self.density if self.measurability(h) is not Measurability.NOT_MEASURABLE]


def assess(
    quotes: NormalizedQuotes,
    contract: ContractSpecification,
    horizons_ns: tuple[int, ...],
    outage_threshold_ns: int = 60 * NS_PER_SECOND,
    step: int = 41,
    calendar: VersionedMarketCalendar | None = None,
) -> QualityReport:
    """Diagnostic complet, à produire **avant** toute carte de faisabilité."""
    usable = quotes.usable_mask
    ts = quotes.arrival_timestamps_ns
    span_days = float((ts[-1] - ts[0]) / (86_400 * NS_PER_SECOND))

    gaps = classify_gaps(ts, calendar, outage_threshold_ns)
    gaps_by_class = {c.value: 0 for c in GapClassification}
    censored_ns = 0
    for g in gaps:
        gaps_by_class[g.classification.value] += 1
        # Seule la part où des cotations étaient attendues est censurée : une fermeture
        # planifiée ne retire rien de l'échantillon.
        censored_ns += g.censored_ns

    tick_rate_by_session = {
        str(s): float(np.median(quotes.tick_rate_1s[quotes.session_ids == s]))
        for s in np.unique(quotes.session_ids)
    }

    spread_usable = quotes.spread[usable]
    report = QualityReport(
        span_days=span_days,
        quotes_total=int(ts.size),
        quotes_usable=int(usable.sum()),
        sessions=int(np.unique(quotes.session_ids).size),
        independent_clusters=int(np.unique(quotes.cluster_ids).size),
        duplicate_fraction=quotes.duplicate_fraction,
        out_of_order_fraction=quotes.out_of_order_fraction,
        crossed_quote_fraction=float(np.mean(quotes.quality == QuoteQuality.CROSSED_QUOTE.value)),
        zero_spread_fraction=float(np.mean(quotes.quality == QuoteQuality.ZERO_SPREAD.value)),
        suspected_bad_tick_fraction=float(
            np.mean(quotes.quality == QuoteQuality.SUSPECTED_BAD_TICK.value)
        ),
        spread_quantiles={
            q: float(np.quantile(spread_usable, q)) for q in (0.5, 0.9, 0.95, 0.99)
        },
        tick_rate_by_session=tick_rate_by_session,
        gaps_by_class=gaps_by_class,
        censored_fraction=float(censored_ns / max(1, ts[-1] - ts[0])),
        clock_usable=bool(quotes.clock.absolute_latency_usable) if quotes.clock else False,
        resolution_sufficient_for_bursts=quotes.resolution.sufficient_for_bursts,
        calendar_version=calendar.calendar_version if calendar else "PROVISIONAL_CALENDAR",
    )

    for h in horizons_ns:
        report.density[h] = density_diagnostic(
            ts[usable], quotes.mid[usable], h, contract.tick_size, step=step
        )

    if calendar is None:
        report.reservations.append(
            "aucun calendrier versionné : toutes les lacunes restent UNKNOWN_GAP et aucun "
            "verdict portant sur une fenêtre potentiellement fermée n'est autorisé"
        )
    if not report.clock_usable:
        report.reservations.append(
            "synchronisation d'horloge insuffisante : latence absolue indisponible, "
            "l'ordre temporel local reste utilisable pour les coûts"
        )
    if not report.resolution_sufficient_for_bursts:
        report.reservations.append(
            f"résolution d'horodatage ({quotes.resolution.inferred_granularity_ns} ns) trop "
            "grossière devant l'inter-arrivée en rafale : l'ordre interne des rafales est perdu"
        )
    if report.censored_fraction > 0.01:
        report.reservations.append(
            f"{report.censored_fraction:.1%} de la période traversée par des coupures ou "
            "des lacunes inexpliquées"
        )
    if report.independent_clusters < 20:
        report.reservations.append(
            f"seulement {report.independent_clusters} blocs indépendants : "
            "tout intervalle de confiance sera large"
        )
    if report.crossed_quote_fraction > 0.001:
        report.reservations.append(
            f"{report.crossed_quote_fraction:.2%} de cotations croisées — réordonnancement "
            "ou flux composite mal synchronisé"
        )
    return report


def round_trip_spread_cost(
    quotes: NormalizedQuotes,
    contract: ContractSpecification,
    policy: CostPolicy,
    conventions: Conventions,
) -> np.ndarray:
    """Coût de spread aller-retour, en unité de cotation, selon la convention déclarée.

    Le code ne produit **jamais** `spread × 2` par défaut : la référence de performance,
    le spread de sortie, le type d'ordre et la convention d'aller-retour déterminent
    ensemble le facteur, et supposer l'un d'eux est le mode d'échec le plus courant.
    """
    from .model import SpreadCountingConvention

    conv = conventions.spread_counting_convention
    spread = quotes.spread[quotes.usable_mask]

    if conv is SpreadCountingConvention.HALF_SPREAD_EACH_SIDE:
        # Un demi-spread payé à l'entrée, un demi à la sortie, contre une performance
        # mesurée de mi-prix à mi-prix : le total vaut un spread complet.
        base = spread
    elif conv is SpreadCountingConvention.FULL_SPREAD_ONCE:
        base = spread
    else:
        raise AdapterError(
            f"Convention de spread inapplicable au calcul de coût : {conv.value}. "
            "En méthode observée, le spread est déjà dans l'implementation shortfall."
        )
    return base + policy.unmeasured_allowance()


@dataclass(frozen=True)
class BuildResult:
    spread_cost: np.ndarray
    cluster_ids: np.ndarray
    timestamps_ns: np.ndarray
    mid: np.ndarray
    commission_round_trip_quote: float
    report: QualityReport
    scenario: CostScenario


def build_calculation_inputs(
    quotes: NormalizedQuotes,
    contract: ContractSpecification,
    policy: CostPolicy,
    conventions: Conventions,
    horizons_ns: tuple[int, ...],
    band: PlausibleEdgeBand,
    cell: Cell,
    calendar: VersionedMarketCalendar | None = None,
) -> BuildResult:
    """Construit les entrées de calcul, ou échoue en expliquant pourquoi.

    Les conditions d'échec ne sont pas des garde-fous défensifs : chacune correspond à un
    cas où le calcul produirait un nombre crédible et faux.
    """
    if quotes.bid.size != quotes.ask.size:
        raise AdapterError("`bid` et `ask` ne sont pas alignés.")
    if not contract.version.strip():
        raise AdapterError(
            "Spécification de contrat non versionnée : un changement de barème passerait "
            "inaperçu et invaliderait silencieusement les résultats antérieurs."
        )
    if band is None:
        raise AdapterError("Bande d'avantages plausibles absente : elle doit être préenregistrée.")
    if cell.execution_market != contract.instrument_id:
        raise AdapterError(
            f"Le marché d'exécution de la cellule ({cell.execution_market}) ne correspond "
            f"pas au contrat chargé ({contract.instrument_id})."
        )

    report = assess(quotes, contract, horizons_ns, calendar=calendar)

    if not report.measurable_horizons:
        raise AdapterError(
            "Aucun horizon mesurable : densité insuffisante ou amplitude saturée par le pas "
            "de cotation sur toute la grille. Un verdict de coût y serait un artefact de "
            "discrétisation. Il faut une source plus dense, davantage de jours, ou une "
            "grille d'horizons plus longs."
        )

    usable = quotes.usable_mask
    spread_cost = round_trip_spread_cost(quotes, contract, policy, conventions)
    commission_quote = (
        2.0 * contract.commission_per_side_per_lot * policy.volume_lots
    ) / (contract.contract_size * policy.volume_lots)

    return BuildResult(
        spread_cost=spread_cost,
        cluster_ids=quotes.cluster_ids[usable],
        timestamps_ns=quotes.arrival_timestamps_ns[usable],
        mid=quotes.mid[usable],
        commission_round_trip_quote=float(commission_quote),
        report=report,
        scenario=policy.scenario,
    )


def print_quality_report(report: QualityReport, horizons_ns: tuple[int, ...]) -> None:
    print("=" * 96)
    print("RAPPORT DE QUALITÉ — la carte de faisabilité n'est lisible qu'après ce diagnostic")
    print("=" * 96)
    print(f"Période            : {report.span_days:.1f} jours, {report.sessions} sessions, "
          f"{report.independent_clusters} blocs indépendants")
    print(f"Cotations          : {report.quotes_total} reçues, {report.quotes_usable} exploitables "
          f"({report.quotes_usable / max(1, report.quotes_total):.1%})")
    print(f"Duplication        : {report.duplicate_fraction:.2%}"
          f"     Hors ordre : {report.out_of_order_fraction:.2%}")
    print(f"Cotations croisées : {report.crossed_quote_fraction:.3%}"
          f"    Spread nul : {report.zero_spread_fraction:.3%}"
          f"    Ticks suspects : {report.suspected_bad_tick_fraction:.3%}")
    print("Spread (unité de cotation) : "
          + "  ".join(f"p{int(q * 100)}={v:.4f}" for q, v in sorted(report.spread_quantiles.items())))
    print("Cadence médiane /s : "
          + "  ".join(f"{k}={v:.1f}" for k, v in sorted(report.tick_rate_by_session.items())))
    print("Lacunes            : "
          + "  ".join(f"{k}={v}" for k, v in report.gaps_by_class.items())
          + f"   — période censurée {report.censored_fraction:.2%}")
    print(f"Calendrier         : {report.calendar_version}")
    print(f"Horloges           : latence absolue "
          f"{'utilisable' if report.clock_usable else 'INDISPONIBLE'}"
          f"   ·   résolution suffisante en rafale : "
          f"{'oui' if report.resolution_sufficient_for_bursts else 'NON'}")

    print()
    print("DENSITÉ PAR HORIZON — un horizon saturé mesure la discrétisation, pas le marché")
    print(f"{'horizon':>9} {'fenêtres':>9} {'ticks p50':>10} {'|Δ| médian':>11} "
          f"{'Δ=0':>7} {'Δ=1 tick':>9} {'statut':>20}  mesurabilité")
    print("-" * 96)
    for h in horizons_ns:
        d = report.density.get(h)
        if d is None:
            continue
        print(f"{h / NS_PER_SECOND:>8.0f}s {d.window_count:>9} {d.tick_count_p50:>10.1f} "
              f"{d.median_abs_move_in_ticks:>9.1f}tk {d.zero_return_fraction:>7.1%} "
              f"{d.one_tick_move_fraction:>9.1%} {d.status.value:>20}  "
              f"{report.measurability(h).value}")

    if report.reservations:
        print()
        print("RÉSERVES :")
        for r in report.reservations:
            print(f"  · {r}")
    print()
