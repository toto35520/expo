"""Tests du moteur de calendrier de marché versionné.

Reprend les cas d'acceptation de Q52. Chacun correspond à une situation où une
classification naïve se trompe — et où l'erreur est invisible dans les données.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
from zoneinfo import ZoneInfo

from feasibility.calendar import (
    NS_PER_SECOND,
    Bitemporal,
    CalendarError,
    CalendarException,
    Executability,
    GapClassification,
    ManualOverride,
    MarketState,
    Provenance,
    QuoteExpectation,
    RecurringRule,
    VerificationStatus,
    VersionedMarketCalendar,
    compare_expected_to_observed,
    executability,
    from_ns,
    is_ambiguous,
    is_nonexistent,
    local_to_ns,
    propose_revisions,
    require_aware,
    synthetic_calendar,
    to_ns,
)

LONDON = "Europe/London"
MARKET = "BROKER_DEMO:XAUUSD:RAW"


@pytest.fixture
def calendar():
    return synthetic_calendar(
        market_id=MARKET,
        timezone=LONDON,
        holiday=dt.date(2026, 8, 10),          # lundi férié
        half_session=dt.date(2026, 8, 12),     # mercredi en demi-séance
        maintenance=(dt.date(2026, 8, 13), dt.time(10, 0), dt.time(10, 30)),
    )


def ns(y, m, d, h, mi=0, tz=LONDON) -> int:
    return local_to_ns(dt.datetime(y, m, d, h, mi), tz)


def prov() -> Provenance:
    return Provenance("src", "TEST", "2026-08-06", "hash", VerificationStatus.UNVERIFIED)


# ---------------------------------------------------------------- fuseaux et heures


def test_naive_datetime_is_rejected():
    """Une heure locale sans fuseau est ambiguë ou inexistante deux fois par an ;
    l'accepter reviendrait à choisir silencieusement l'une des réponses."""
    with pytest.raises(CalendarError, match="naïf"):
        require_aware(dt.datetime(2026, 10, 25, 1, 30))
    with pytest.raises(CalendarError, match="naïf"):
        to_ns(dt.datetime(2026, 8, 6, 12, 0))


def test_spring_forward_creates_a_nonexistent_local_hour():
    """Le passage à l'heure d'été supprime une heure locale. La déplacer produirait un
    horaire d'ouverture que personne n'a jamais publié."""
    tz = ZoneInfo(LONDON)
    missing = dt.datetime(2026, 3, 29, 1, 30)
    assert is_nonexistent(missing, tz)
    with pytest.raises(CalendarError, match="inexistante"):
        local_to_ns(missing, LONDON)


def test_fall_back_hour_is_ambiguous_and_fold_distinguishes_it():
    """Le retour à l'heure standard répète une heure locale : deux instants UTC réellement
    distincts, que seul `fold` sépare."""
    tz = ZoneInfo(LONDON)
    repeated = dt.datetime(2026, 10, 25, 1, 30)
    assert is_ambiguous(repeated, tz)

    first = local_to_ns(repeated, LONDON, fold=0)
    second = local_to_ns(repeated, LONDON, fold=1)
    assert second - first == 3_600 * NS_PER_SECOND


def test_day_lengths_differ_across_dst_transitions():
    """Journées de 23 et 25 heures : un décalage entier codé en dur les manquerait."""
    spring = ns(2026, 3, 30, 0) - ns(2026, 3, 28, 0)
    autumn = ns(2026, 10, 26, 0) - ns(2026, 10, 24, 0)
    assert spring == 47 * 3_600 * NS_PER_SECOND
    assert autumn == 49 * 3_600 * NS_PER_SECOND


# ------------------------------------------------------------------- états ponctuels


def test_session_and_night_states(calendar):
    assert calendar.state_at(ns(2026, 8, 4, 11)).primary_state is MarketState.OPEN_CONTINUOUS
    assert calendar.state_at(ns(2026, 8, 4, 20)).primary_state is MarketState.SCHEDULED_BREAK


def test_weekend_is_closed(calendar):
    st = calendar.state_at(ns(2026, 8, 8, 11))  # samedi
    assert st.primary_state is MarketState.WEEKEND_CLOSED
    assert st.quote_expectation is QuoteExpectation.QUOTES_NOT_EXPECTED


def test_holiday_exception_overrides_the_recurring_rule(calendar):
    """Une exception remplace localement la règle habituelle : le lundi férié n'est pas
    une séance ouverte."""
    st = calendar.state_at(ns(2026, 8, 10, 11))
    assert st.primary_state is MarketState.HOLIDAY_CLOSED
    assert st.resolution_rule.startswith("exception:")


def test_half_session_is_not_a_full_closure(calendar):
    """Une demi-séance est ouverte puis fermée plus tôt. La classer en fermeture
    quotidienne mélangerait sa densité et son spread avec ceux d'une séance normale."""
    open_part = calendar.state_at(ns(2026, 8, 12, 10))
    closed_part = calendar.state_at(ns(2026, 8, 12, 12))
    assert open_part.primary_state is MarketState.OPEN_REDUCED
    assert open_part.quote_expectation is QuoteExpectation.QUOTES_EXPECTED_SPARSE
    assert closed_part.primary_state is MarketState.EARLY_CLOSE


def test_broker_maintenance_dominates_an_open_session(calendar):
    """Le marché de référence peut rester ouvert pendant que le symbole du courtier est
    indisponible."""
    st = calendar.state_at(ns(2026, 8, 13, 10, 15))
    assert st.primary_state is MarketState.BROKER_MAINTENANCE
    assert st.quote_expectation is QuoteExpectation.QUOTES_NOT_EXPECTED
    assert calendar.state_at(ns(2026, 8, 13, 11)).primary_state is MarketState.OPEN_CONTINUOUS


def test_unknown_when_no_rule_applies():
    empty = VersionedMarketCalendar(
        calendar_id="vide", calendar_version="v0", market_id=MARKET,
        timezone_database_version="stdlib",
    )
    st = empty.state_at(ns(2026, 8, 4, 11))
    assert st.primary_state is MarketState.UNKNOWN
    assert st.quote_expectation is QuoteExpectation.QUOTE_POLICY_UNKNOWN


# ------------------------------------------------------------------ intervalles


def test_planned_night_is_market_closed(calendar):
    """Les deux bornes sont en session ouverte ; seul l'intérieur est fermé. C'est le cas
    qui invalidait l'ancienne classification par extrémités."""
    summary = calendar.summarize_interval(ns(2026, 8, 4, 13), ns(2026, 8, 5, 9))
    assert summary.classification is GapClassification.MARKET_CLOSED
    assert summary.market_time_ns == 0


def test_outage_during_open_session_is_never_market_closed(calendar):
    summary = calendar.summarize_interval(ns(2026, 8, 4, 10), ns(2026, 8, 4, 12))
    assert summary.classification is GapClassification.DATA_OUTAGE
    assert summary.market_time_ns == 2 * 3_600 * NS_PER_SECOND


def test_mixed_gap_is_segmented_and_the_open_part_survives(calendar):
    """Une fermeture planifiée ne doit pas masquer une panne survenue après la
    réouverture — même si elle ne représente que quelques pour cent de l'intervalle."""
    summary = calendar.summarize_interval(ns(2026, 8, 4, 13), ns(2026, 8, 5, 10))
    assert summary.classification is GapClassification.PARTIAL_SCHEDULED_CLOSURE

    states = [s.state for s in summary.segments]
    assert MarketState.SCHEDULED_BREAK in states
    assert MarketState.OPEN_CONTINUOUS in states
    # Seule l'heure ouverte compte comme temps de marché.
    assert summary.market_time_ns == 3_600 * NS_PER_SECOND


def test_fraction_alone_would_swallow_the_outage(calendar):
    """Vérifie explicitement le piège : l'heure ouverte pèse 5 % d'un intervalle de 21 h.
    Un seuil en pourcentage seul l'aurait classé en fermeture."""
    summary = calendar.summarize_interval(ns(2026, 8, 4, 13), ns(2026, 8, 5, 10))
    closed_fraction = summary.fraction_with(QuoteExpectation.QUOTES_NOT_EXPECTED)
    assert closed_fraction > 0.94
    assert summary.classification is not GapClassification.MARKET_CLOSED


def test_sparse_expectation_is_not_an_outage(calendar):
    """Une période ouverte mais traditionnellement peu active ne se confond pas avec une
    panne."""
    summary = calendar.summarize_interval(ns(2026, 8, 12, 9, 30), ns(2026, 8, 12, 10, 30))
    assert summary.classification is GapClassification.EXPECTED_SPARSE_ACTIVITY


def test_segments_cover_the_interval_exactly(calendar):
    start, end = ns(2026, 8, 4, 13), ns(2026, 8, 5, 10)
    segments = calendar.split_by_calendar_state(start, end)
    assert segments[0].start_ns == start
    assert segments[-1].end_ns == end
    assert sum(s.duration_ns for s in segments) == end - start
    for a, b in zip(segments[:-1], segments[1:]):
        assert a.end_ns == b.start_ns


def test_provisional_calendar_yields_unknown_only(calendar):
    """Mode dégradé : la collecte peut commencer, l'interprétation non."""
    provisional = VersionedMarketCalendar(
        **{**calendar.__dict__, "provisional": True, "calendar_version": "PROVISIONAL"}
    )
    summary = provisional.summarize_interval(ns(2026, 8, 4, 13), ns(2026, 8, 5, 9))
    assert summary.classification is GapClassification.UNKNOWN_GAP


# --------------------------------------------------------------------- bitemporalité


def test_closure_announced_after_the_fact_is_invisible_to_a_backtest():
    """Une fermeture connue seulement après coup ne doit pas apparaître dans une
    simulation décisionnelle, mais reste disponible pour l'audit historique."""
    event_ns = ns(2026, 8, 4, 11)
    announced_ns = ns(2026, 8, 4, 15)

    late = CalendarException(
        market_id=MARKET, local_date=dt.date(2026, 8, 4), timezone=LONDON,
        state=MarketState.EMERGENCY_CLOSED,
        quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
        temporal=Bitemporal(valid_from_ns=0, known_from_ns=announced_ns),
        provenance=prov(), reason="fermeture annoncée en cours de séance",
    )
    cal = synthetic_calendar(market_id=MARKET, timezone=LONDON)
    cal = VersionedMarketCalendar(**{**cal.__dict__, "exceptions": (late,)})

    # Décision prise à 11h : l'annonce n'existait pas encore.
    assert cal.state_at(event_ns, known_as_of_ns=event_ns).primary_state is (
        MarketState.OPEN_CONTINUOUS
    )
    # Audit historique : l'état réel.
    assert cal.state_at(event_ns, known_as_of_ns=None).primary_state is (
        MarketState.EMERGENCY_CLOSED
    )


# ------------------------------------------------------------ dominance et overrides


def test_dominance_keeps_secondary_states():
    """La priorité ne détruit pas les états secondaires : elle les ordonne."""
    cal = synthetic_calendar(market_id=MARKET, timezone=LONDON)
    override = ManualOverride(
        override_id="ov-1", market_id=MARKET,
        start_ns=ns(2026, 8, 4, 10), end_ns=ns(2026, 8, 4, 11),
        previous_state=MarketState.OPEN_CONTINUOUS, new_state=MarketState.HALTED,
        quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
        author="opérateur", reason="suspension observée", evidence="capture du flux",
        created_at="2026-08-04", temporal=Bitemporal(valid_from_ns=0),
    )
    cal = VersionedMarketCalendar(**{**cal.__dict__, "overrides": (override,)})
    st = cal.state_at(ns(2026, 8, 4, 10, 30))
    assert st.primary_state is MarketState.HALTED
    assert MarketState.OPEN_CONTINUOUS in st.contributing_states
    assert st.verification is VerificationStatus.MANUAL_OVERRIDE_VERIFIED


def test_override_requires_author_reason_and_evidence():
    with pytest.raises(CalendarError, match="preuve"):
        ManualOverride(
            override_id="ov", market_id=MARKET, start_ns=0, end_ns=1,
            previous_state=MarketState.OPEN_CONTINUOUS, new_state=MarketState.HALTED,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            author="", reason="", evidence="", created_at="",
            temporal=Bitemporal(valid_from_ns=0),
        )


def test_rule_requires_provenance():
    with pytest.raises(CalendarError, match="source"):
        Provenance("", "TEST", "", "h", VerificationStatus.UNVERIFIED)


# ------------------------------------------------------------- calendriers distincts


def test_two_markets_do_not_share_their_closures():
    """Une fermeture du marché de détection ne s'applique pas au marché d'exécution."""
    detection = synthetic_calendar(
        market_id="COMEX_GC", timezone=LONDON, holiday=dt.date(2026, 8, 10)
    )
    execution = synthetic_calendar(market_id="BROKER_A:XAUUSD:RAW", timezone=LONDON)

    t = ns(2026, 8, 10, 11)
    assert detection.state_at(t).primary_state is MarketState.HOLIDAY_CLOSED
    assert execution.state_at(t).primary_state is MarketState.OPEN_CONTINUOUS

    verdict, degraded = executability(detection.state_at(t), execution.state_at(t))
    assert verdict is Executability.DETECTION_CLOSED
    assert degraded is True


def test_execution_closed_removes_all_authority():
    detection = synthetic_calendar(market_id="COMEX_GC", timezone=LONDON)
    execution = synthetic_calendar(
        market_id="BROKER_A:XAUUSD:RAW", timezone=LONDON, holiday=dt.date(2026, 8, 10)
    )
    t = ns(2026, 8, 10, 11)
    verdict, _ = executability(detection.state_at(t), execution.state_at(t))
    assert verdict is Executability.EXECUTION_CLOSED


def test_unknown_calendar_never_grants_execution():
    empty = VersionedMarketCalendar(
        calendar_id="vide", calendar_version="v0", market_id=MARKET,
        timezone_database_version="stdlib",
    )
    open_cal = synthetic_calendar(market_id=MARKET, timezone=LONDON)
    t = ns(2026, 8, 4, 11)
    verdict, degraded = executability(empty.state_at(t), open_cal.state_at(t))
    assert verdict is Executability.CALENDAR_UNKNOWN
    assert degraded is True


# ------------------------------------------------- attendu contre observé, révisions


def test_mismatch_detects_quotes_during_a_closure(calendar):
    start, end = ns(2026, 8, 4, 13), ns(2026, 8, 4, 20)
    ticks = np.array([ns(2026, 8, 4, 15), ns(2026, 8, 4, 16)], dtype=np.int64)
    mismatches = compare_expected_to_observed(calendar, ticks, start, end)
    assert any("fermeture attendue" in m.kind for m in mismatches)


def test_mismatch_detects_silence_during_an_open_session(calendar):
    start, end = ns(2026, 8, 4, 10), ns(2026, 8, 4, 12)
    mismatches = compare_expected_to_observed(calendar, np.empty(0, dtype=np.int64), start, end)
    assert any("période ouverte" in m.kind for m in mismatches)


def test_revisions_are_proposals_and_never_applied(calendar):
    """Sans validation explicite, une panne répétée serait progressivement reclassée en
    fermeture normale, et le calendrier décrirait le flux plutôt que le marché."""
    start, end = ns(2026, 8, 4, 10), ns(2026, 8, 4, 12)
    mismatches = compare_expected_to_observed(calendar, np.empty(0, dtype=np.int64), start, end)
    proposals = propose_revisions(mismatches * 6, min_occurrences=5)

    assert proposals and all(p.requires_explicit_validation for p in proposals)
    # Le calendrier est inchangé.
    assert calendar.state_at(ns(2026, 8, 4, 11)).primary_state is MarketState.OPEN_CONTINUOUS


# ------------------------------------------------------------------- versionnement


def test_a_correction_creates_a_new_version_without_touching_the_old(calendar):
    """Les rapports déjà produits conservent l'identifiant exact du calendrier utilisé."""
    corrected = VersionedMarketCalendar(
        **{
            **calendar.__dict__,
            "calendar_version": "SYNTHETIC_CALENDAR_1.1",
            "parent_version": calendar.calendar_version,
            "exceptions": calendar.exceptions + (
                CalendarException(
                    market_id=MARKET, local_date=dt.date(2026, 8, 11), timezone=LONDON,
                    state=MarketState.HOLIDAY_CLOSED,
                    quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
                    temporal=Bitemporal(valid_from_ns=0), provenance=prov(),
                    reason="férié découvert après coup",
                ),
            ),
        }
    )
    t = ns(2026, 8, 11, 11)
    assert calendar.state_at(t).primary_state is MarketState.OPEN_CONTINUOUS
    assert corrected.state_at(t).primary_state is MarketState.HOLIDAY_CLOSED
    assert corrected.parent_version == calendar.calendar_version
    assert calendar.calendar_version == "SYNTHETIC_CALENDAR_1.0"


def test_summary_carries_the_calendar_version(calendar):
    summary = calendar.summarize_interval(ns(2026, 8, 4, 13), ns(2026, 8, 5, 9))
    assert summary.calendar_version == calendar.calendar_version


# --------------------------------------------------------- temps de marché / horloge


def test_market_time_differs_from_wall_clock(calendar):
    """Deux définitions d'horizon légitimes, jamais mélangées : quinze minutes réelles ne
    valent pas quinze minutes de cotations attendues."""
    start, end = ns(2026, 8, 4, 12), ns(2026, 8, 5, 10)
    wall = end - start
    market = calendar.market_time_ns(start, end)
    assert market < wall
    assert market == 2 * 3_600 * NS_PER_SECOND  # 12h→13h puis 9h→10h
