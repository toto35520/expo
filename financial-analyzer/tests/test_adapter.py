"""Tests de l'adaptateur de données courtier.

L'adaptateur ne produit aucun verdict : il garantit que les données qui entrent dans les
calculs sont interprétables. Chaque test vérifie qu'un cas où le calcul produirait un
nombre crédible et faux est bien intercepté.
"""

from __future__ import annotations

import numpy as np
import pytest

from feasibility.adapter import (
    NS_PER_SECOND,
    AdapterError,
    BurstState,
    ClockSync,
    DensityStatus,
    OrderingStatus,
    QuoteQuality,
    RawQuotes,
    SessionResolver,
    classify_gaps,
    density_diagnostic,
    evaluation_delay,
    infer_timestamp_resolution,
    normalize,
)
from feasibility.calendar import (
    GapClassification,
    MarketState,
    QuoteExpectation,
    local_to_ns,
    synthetic_calendar,
)
from feasibility.contract import (
    ContractSpecification,
    CostPolicy,
    CostScenario,
    ExecutionMode,
    PriceUnit,
    Quantity,
    UnitError,
)
from feasibility.model import (
    Cell,
    Conventions,
    CostMethod,
    PlausibleEdgeBand,
    ReferencePriceConvention,
    RoundTripDefinition,
    SpreadCountingConvention,
)
from feasibility.quality import Measurability, assess, build_calculation_inputs
from feasibility.synthetic import generate


@pytest.fixture
def contract():
    return ContractSpecification(
        broker="BROKER_TEST",
        account_type="RAW",
        symbol="XAUUSD",
        underlying="XAU",
        quote_currency="USD",
        contract_size=100.0,
        tick_size=0.01,
        tick_value=1.0,
        minimum_volume=0.01,
        volume_step=0.01,
        commission_per_side_per_lot=3.5,
        swap_long_per_lot_per_day=-12.0,
        swap_short_per_lot_per_day=4.0,
        triple_swap_weekday=2,
        triple_swap_verified=True,
        execution_mode=ExecutionMode.MARKET,
        source="fiche contractuelle de test",
        retrieved_at="2026-08-06",
        version="TEST_1.0",
    )


@pytest.fixture
def policy():
    return CostPolicy(
        scenario=CostScenario.OPTIMISTIC,
        volume_lots=0.05,
        unmeasured_slippage_bound=0.05,
        unmeasured_impact_bound=0.02,
        unmeasured_adverse_selection_bound=0.03,
        rationale="bornes de test — aucune mesure réelle",
    )


@pytest.fixture
def raw_quotes():
    t = generate(days=25, ticks_per_session=40_000, seed=3)
    half = t.spread / 2.0
    return RawQuotes(
        receive_timestamps_ns=t.timestamps_ns,
        bid=t.mid - half,
        ask=t.mid + half,
        source="SYNTHETIC",
    )


@pytest.fixture
def normalized(raw_quotes, contract):
    return normalize(raw_quotes, contract, SessionResolver())


# --------------------------------------------------------------------------- unités


def test_quantity_refuses_mixed_units():
    """Sur XAU/USD, confondre l'once et le lot est un facteur cent — silencieux."""
    with pytest.raises(UnitError, match="unités différentes"):
        Quantity(1.0, PriceUnit.QUOTE_PER_UNIT) + Quantity(1.0, PriceUnit.ACCOUNT_MONEY)


def test_price_move_to_money_uses_contract_size(contract):
    money = contract.price_move_to_money(move_quote=0.20, volume_lots=0.05)
    assert money.unit is PriceUnit.ACCOUNT_MONEY
    assert money.value == pytest.approx(0.20 * 100.0 * 0.05)


def test_contract_requires_provenance():
    with pytest.raises(UnitError, match="source"):
        ContractSpecification(
            broker="B", account_type="A", symbol="S", underlying="U", quote_currency="USD",
            contract_size=100.0, tick_size=0.01, tick_value=1.0, minimum_volume=0.01,
            volume_step=0.01, commission_per_side_per_lot=0.0,
            swap_long_per_lot_per_day=0.0, swap_short_per_lot_per_day=0.0,
            triple_swap_weekday=None, triple_swap_verified=False,
            execution_mode=ExecutionMode.UNKNOWN, source="", retrieved_at="", version="v",
        )


def test_financing_refuses_unverified_triple_swap_policy(contract):
    """Le jour de portage multiplié se vérifie auprès du courtier, il ne se suppose pas."""
    unverified = ContractSpecification(**{**contract.__dict__, "triple_swap_verified": False})
    assert unverified.financing(0.05, direction=1, rollover_crossings=0).value == 0.0
    with pytest.raises(UnitError, match="non vérifiée"):
        unverified.financing(0.05, direction=1, rollover_crossings=3)


def test_cost_scenarios_are_ordered(policy):
    """Les coûts inconnus ne sont jamais nuls : ils sont traités par scénarios."""
    prudent = CostPolicy(**{**policy.__dict__, "scenario": CostScenario.PRUDENT})
    central = CostPolicy(**{**policy.__dict__, "scenario": CostScenario.CENTRAL})
    assert policy.unmeasured_allowance() == 0.0
    assert 0.0 < central.unmeasured_allowance() < prudent.unmeasured_allowance()


def test_policy_requires_rationale(policy):
    with pytest.raises(UnitError, match="justification"):
        CostPolicy(**{**policy.__dict__, "rationale": "   "})


# --------------------------------------------------------------- alignement, cotations


def test_raw_quotes_reject_misaligned_arrays():
    with pytest.raises(AdapterError, match="aligné"):
        RawQuotes(
            receive_timestamps_ns=np.arange(10, dtype=np.int64),
            bid=np.zeros(10),
            ask=np.zeros(9),
        )


def test_raw_quotes_reject_empty_export():
    with pytest.raises(AdapterError, match="vide"):
        RawQuotes(np.empty(0, dtype=np.int64), np.empty(0), np.empty(0))


def test_crossed_quote_is_flagged_not_repaired(contract):
    """Un spread négatif n'est jamais remplacé silencieusement par zéro : il signale un
    réordonnancement, un flux composite, ou une erreur de source."""
    ts = np.arange(100, dtype=np.int64) * NS_PER_SECOND
    bid = np.full(100, 4000.0)
    ask = np.full(100, 4000.2)
    ask[42] = 3999.9  # ask < bid
    q = normalize(RawQuotes(ts, bid, ask), contract, SessionResolver())
    assert q.quality[42] == QuoteQuality.CROSSED_QUOTE.value
    assert q.spread[42] < 0  # conservé tel quel
    assert not q.usable_mask[42]


def test_zero_spread_is_kept_but_flagged(contract):
    ts = np.arange(100, dtype=np.int64) * NS_PER_SECOND
    bid = np.full(100, 4000.0)
    ask = np.full(100, 4000.2)
    ask[10] = 4000.0
    q = normalize(RawQuotes(ts, bid, ask), contract, SessionResolver())
    assert q.quality[10] == QuoteQuality.ZERO_SPREAD.value
    assert q.usable_mask[10]  # conservé dans le chemin principal, mais audité


def test_suspected_bad_tick_is_not_excluded_from_sensitivity(contract):
    """Une valeur suspecte reste disponible pour les analyses de sensibilité ; seuls les
    mauvais ticks confirmés quittent le chemin principal."""
    ts = np.arange(300, dtype=np.int64) * NS_PER_SECOND
    mid = 4000.0 + np.cumsum(np.random.default_rng(0).normal(0, 0.01, 300))
    mid[150] += 50.0  # pic isolé immédiatement annulé
    q = normalize(RawQuotes(ts, mid - 0.1, mid + 0.1), contract, SessionResolver())
    assert QuoteQuality.SUSPECTED_BAD_TICK.value in set(q.quality)
    suspected = q.quality == QuoteQuality.SUSPECTED_BAD_TICK.value
    assert q.usable_mask[suspected].all()


# --------------------------------------------------------------------- ordre temporel


def test_out_of_order_arrival_is_recorded_not_erased(contract):
    """Une arrivée tardive est une information sur la qualité du flux, pas un désordre à
    effacer par un tri."""
    ts = np.arange(50, dtype=np.int64) * NS_PER_SECOND
    ts[30], ts[31] = ts[31], ts[30]
    q = normalize(RawQuotes(ts, np.full(50, 4000.0), np.full(50, 4000.2)),
                  contract, SessionResolver())
    assert q.out_of_order_fraction > 0
    assert np.all(np.diff(q.arrival_timestamps_ns) >= 0)  # ordre événementiel reconstruit
    assert not np.array_equal(q.raw_arrival_order, np.arange(50))  # ordre d'arrivée conservé


def test_sequence_gap_is_detected(contract):
    ts = np.arange(50, dtype=np.int64) * NS_PER_SECOND
    seq = np.arange(50, dtype=np.int64)
    seq[25:] += 7
    q = normalize(
        RawQuotes(ts, np.full(50, 4000.0), np.full(50, 4000.2), sequence_numbers=seq),
        contract, SessionResolver(),
    )
    assert OrderingStatus.SEQUENCE_GAP.value in set(q.ordering_status)


def test_technical_duplicates_are_removed(contract):
    ts = np.repeat(np.arange(30, dtype=np.int64), 2) * NS_PER_SECOND
    seq = np.repeat(np.arange(30, dtype=np.int64), 2)
    q = normalize(
        RawQuotes(ts, np.full(60, 4000.0), np.full(60, 4000.2), sequence_numbers=seq),
        contract, SessionResolver(),
    )
    assert q.arrival_timestamps_ns.size == 30
    assert q.duplicate_fraction == pytest.approx(0.5)


# ------------------------------------------------------------------------- horloges


def test_timestamp_resolution_is_measured_not_declared():
    """Une résolution à la milliseconde suffit à quinze cotations par seconde et perd
    tout l'ordre interne d'une rafale à cinq cents."""
    ms = 1_000_000
    ts = np.arange(0, 1000, dtype=np.int64) * ms
    res = infer_timestamp_resolution(ts)
    assert res.inferred_granularity_ns == ms
    assert res.zero_diff_fraction == 0.0


def test_coarse_resolution_is_insufficient_for_bursts():
    ms = 1_000_000
    ts = np.sort(np.concatenate([
        np.arange(0, 100, dtype=np.int64) * 50 * ms,     # cadence calme
        np.full(200, 5_000 * ms) + np.arange(200) * ms,  # rafale à la milliseconde
    ]))
    res = infer_timestamp_resolution(ts)
    assert not res.sufficient_for_bursts


def test_clock_sync_gates_absolute_latency():
    """Sans synchronisation fiable, la latence absolue est indisponible — mais l'ordre
    local reste utilisable."""
    assert not ClockSync("aucune", 1_000_000, 5_000_000).absolute_latency_usable
    assert ClockSync("NTP", 20_000_000, 1_000_000).absolute_latency_usable


# --------------------------------------------------------------------------- lacunes


def test_outage_during_an_open_session_is_reported(contract):
    """Le calendrier dit que des cotations étaient attendues ; il n'y en a aucune."""
    import datetime as dt

    cal = synthetic_calendar(
        market_id=contract.instrument_id, timezone="UTC",
        session_start=dt.time(9, 0), session_end=dt.time(13, 0),
    )
    a = local_to_ns(dt.datetime(2026, 8, 4, 10, 0), "UTC")
    b = local_to_ns(dt.datetime(2026, 8, 4, 12, 0), "UTC")
    gaps = classify_gaps(np.array([a, b], dtype=np.int64), cal, 60 * NS_PER_SECOND)
    assert gaps[0].classification is GapClassification.DATA_OUTAGE
    assert gaps[0].censored_ns == b - a


def test_planned_night_censors_nothing(contract):
    """Une fermeture planifiée ne retire rien de l'échantillon."""
    import datetime as dt

    cal = synthetic_calendar(
        market_id=contract.instrument_id, timezone="UTC",
        session_start=dt.time(9, 0), session_end=dt.time(13, 0),
    )
    a = local_to_ns(dt.datetime(2026, 8, 4, 13, 0), "UTC")
    b = local_to_ns(dt.datetime(2026, 8, 5, 9, 0), "UTC")
    gaps = classify_gaps(np.array([a, b], dtype=np.int64), cal, 60 * NS_PER_SECOND)
    assert gaps[0].classification is GapClassification.MARKET_CLOSED
    assert gaps[0].censored_ns == 0


def test_adapter_delegates_closure_logic_to_the_calendar():
    """Sans calendrier, l'adaptateur ne suppose jamais une fermeture : tout est inconnu.

    C'est le mode provisoire — la collecte peut commencer, l'interprétation non."""
    ts = np.array([0, 10_000 * NS_PER_SECOND], dtype=np.int64)
    gaps = classify_gaps(ts, None, 60 * NS_PER_SECOND)
    assert gaps[0].classification is GapClassification.UNKNOWN_GAP
    assert gaps[0].segments == ()
    assert gaps[0].censored_ns == gaps[0].duration_ns


# ----------------------------------------------------------- densité et quantification


def test_quantized_horizon_is_detected(contract):
    """Le défaut observé sur données synthétiques devient un test automatique."""
    ts = np.arange(20_000, dtype=np.int64) * NS_PER_SECOND
    mid = 4000.0 + np.cumsum(
        np.random.default_rng(0).choice([-0.01, 0.0, 0.01], size=20_000)
    )
    diag = density_diagnostic(ts, mid, NS_PER_SECOND, tick_size=0.01, step=1)
    assert diag.status is DensityStatus.DENSITY_QUANTIZED
    assert diag.median_abs_move_in_ticks <= 1.0
    assert not diag.usable


def test_dense_horizon_is_valid(contract):
    rng = np.random.default_rng(1)
    ts = np.arange(50_000, dtype=np.int64) * (NS_PER_SECOND // 10)
    mid = 4000.0 + np.cumsum(rng.normal(0, 0.05, 50_000))
    diag = density_diagnostic(ts, mid, 60 * NS_PER_SECOND, tick_size=0.01, step=7)
    assert diag.status is DensityStatus.DENSITY_VALID
    assert diag.usable


def test_too_few_windows_is_invalid(contract):
    ts = np.arange(50, dtype=np.int64) * NS_PER_SECOND
    mid = np.linspace(4000, 4001, 50)
    diag = density_diagnostic(ts, mid, NS_PER_SECOND, tick_size=0.01)
    assert diag.status is DensityStatus.DENSITY_INVALID


# ----------------------------------------------------------------- cadence, rafales


def test_evaluation_delay_is_measured_not_assumed():
    """`cadence / 2` n'est exact que sous arrivée uniforme indépendante de la cadence.
    Des événements alignés sur la cadence ont un délai nul."""
    cadence = 100_000_000  # 100 ms
    aligned = np.arange(0, 20, dtype=np.int64) * cadence
    assert evaluation_delay(aligned, cadence).max() == 0.0

    rng = np.random.default_rng(0)
    scattered = np.sort(rng.integers(0, 20 * cadence, size=5_000))
    delays = evaluation_delay(scattered, cadence)
    assert 0 <= delays.mean() <= cadence
    assert delays.mean() == pytest.approx(cadence / 2, rel=0.1)


def test_burst_thresholds_are_per_session(normalized):
    """Une cadence normale de Londres ne doit pas être classée en rafale au seul motif
    qu'elle dépasse la cadence asiatique."""
    states = set(normalized.burst_states)
    assert BurstState.NORMAL.value in states
    assert BurstState.BURST_P95.value in states or BurstState.BURST_P99.value in states

    for session in np.unique(normalized.session_ids):
        m = normalized.session_ids == session
        if m.sum() < 100:
            continue
        burst = np.isin(
            normalized.burst_states[m],
            [BurstState.BURST_P95.value, BurstState.BURST_P99.value],
        )
        # Par construction quantile, environ 5 % par session — jamais 0 % ni 100 %.
        assert 0.0 < burst.mean() < 0.20


# ---------------------------------------------------------------- rapport de qualité


def test_quality_report_flags_unmeasurable_horizons(normalized, contract):
    horizons = tuple(h * NS_PER_SECOND for h in (1, 60, 3600))
    report = assess(normalized, contract, horizons, calendar=None)
    assert report.measurability(horizons[0]) is Measurability.NOT_MEASURABLE
    assert report.measurability(horizons[-1]) is not Measurability.NOT_MEASURABLE
    assert report.span_days > 20


def test_build_refuses_when_no_horizon_is_measurable(normalized, contract, policy):
    """Sans horizon mesurable, le calcul produirait un artefact de discrétisation."""
    conventions = Conventions(
        CostMethod.MODELED, ReferencePriceConvention.MID_TO_MID,
        RoundTripDefinition.ENTRY_AND_EXIT, SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
        "v1", "v1",
    )
    band = PlausibleEdgeBand(0.05, 0.30, "test", "2026-08-06")
    cell = Cell("XAUUSD", "S", contract.instrument_id, "MARKET", "ALL", 0.05, "NORMAL")
    with pytest.raises(AdapterError, match="Aucun horizon mesurable"):
        build_calculation_inputs(
            normalized, contract, policy, conventions,
            (NS_PER_SECOND,), band, cell,
        )


def test_build_refuses_mismatched_execution_market(normalized, contract, policy):
    conventions = Conventions(
        CostMethod.MODELED, ReferencePriceConvention.MID_TO_MID,
        RoundTripDefinition.ENTRY_AND_EXIT, SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
        "v1", "v1",
    )
    band = PlausibleEdgeBand(0.05, 0.30, "test", "2026-08-06")
    wrong = Cell("XAUUSD", "S", "AUTRE_COURTIER:XAUUSD:RAW", "MARKET", "ALL", 0.05, "NORMAL")
    with pytest.raises(AdapterError, match="marché d'exécution"):
        build_calculation_inputs(
            normalized, contract, policy, conventions,
            (3_600 * NS_PER_SECOND,), band, wrong,
        )


def test_build_succeeds_on_measurable_horizons(normalized, contract, policy):
    conventions = Conventions(
        CostMethod.MODELED, ReferencePriceConvention.MID_TO_MID,
        RoundTripDefinition.ENTRY_AND_EXIT, SpreadCountingConvention.HALF_SPREAD_EACH_SIDE,
        "v1", "v1",
    )
    band = PlausibleEdgeBand(0.05, 0.30, "test", "2026-08-06")
    cell = Cell("XAUUSD", "S", contract.instrument_id, "MARKET", "ALL", 0.05, "NORMAL")
    built = build_calculation_inputs(
        normalized, contract, policy, conventions,
        tuple(h * NS_PER_SECOND for h in (600, 1800, 3600)), band, cell,
    )
    assert built.spread_cost.size == built.cluster_ids.size == built.mid.size
    assert built.commission_round_trip_quote > 0
    assert built.scenario is CostScenario.OPTIMISTIC


def test_observed_method_cannot_add_spread(normalized, contract, policy):
    """ADR-111 : en méthode observée, le spread est déjà dans l'implementation shortfall."""
    from feasibility.quality import round_trip_spread_cost

    conventions = Conventions(
        CostMethod.OBSERVED_IS, ReferencePriceConvention.MID_EXECUTABLE_AT_DECISION,
        RoundTripDefinition.ENTRY_AND_EXIT, SpreadCountingConvention.ALREADY_IN_PERFORMANCE,
        "v1", "v1",
    )
    with pytest.raises(AdapterError, match="déjà dans l'implementation shortfall"):
        round_trip_spread_cost(normalized, contract, policy, conventions)
