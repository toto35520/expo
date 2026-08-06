"""Tests de la chaîne de preuve du calendrier (Q53).

Q52 garantit que le moteur applique correctement une règle. Q53 garantit que la règle
mérite d'être appliquée. Chaque test vise un cas où le calendrier appliquerait
parfaitement un horaire faux.
"""

from __future__ import annotations

import datetime as dt

import pytest

from feasibility.calendar import MarketState, local_to_ns
from feasibility.calendar_sources import (
    AssertionType,
    CalendarAssertion,
    CalendarContentStatus,
    ChangeKind,
    ConflictType,
    EffectiveDateBasis,
    Freshness,
    ImpactLevel,
    ReviewStatus,
    Scope,
    SourceError,
    SourceRank,
    SourceSnapshot,
    TimezoneInterpretation,
    assess_historical_impact,
    build_manifest,
    classify_change,
    compile_calendar,
    detect_conflicts,
    provenance_report,
    resolve_by_priority,
)

LONDON = "Europe/London"
MARKET = "BROKER_A:XAUUSD:RAW"
DAY_NS = 86_400 * 1_000_000_000
NOW = local_to_ns(dt.datetime(2026, 8, 7, 0, 0), "UTC")


def snapshot(source_id: str = "SRC-1", **kw) -> SourceSnapshot:
    base = dict(
        source_id=source_id,
        source_type="BROKER_SYMBOL_SPEC",
        location="plateforme > spécification du symbole",
        retrieved_at_ns=NOW,
        content_hash="hash-" + source_id,
        market_scope=(MARKET,),
        acquisition_method="MANUAL_CAPTURE",
        retained_excerpt="XAUUSD — pause quotidienne 22:00–23:00 heure serveur",
    )
    base.update(kw)
    return SourceSnapshot(**base)


def assertion(assertion_id: str = "A-1", **kw) -> CalendarAssertion:
    base = dict(
        assertion_id=assertion_id,
        scope=Scope(market_id=MARKET, broker="BROKER_A", account_type="RAW", symbol="XAUUSD"),
        assertion_type=AssertionType.SCHEDULED_BREAK,
        timezone=LONDON,
        timezone_interpretation=TimezoneInterpretation.EXPLICIT_IANA,
        source_timezone_expression="Europe/London",
        valid_from_ns=0,
        valid_to_ns=None,
        effective_date_basis=EffectiveDateBasis.EXPLICIT_IN_SOURCE,
        known_from_ns=0,
        known_to_ns=None,
        source_id="SRC-1",
        source_rank=SourceRank.NORMATIVE_BROKER_SYMBOL,
        review_status=ReviewStatus.APPROVED,
        retrieved_at_ns=NOW,
        extract_hash="extract-" + assertion_id,
        parser_version="P1",
        local_start=dt.time(22, 0),
        local_end=dt.time(23, 0),
        weekdays=frozenset({0, 1, 2, 3, 4}),
        last_verified_at_ns=NOW,
        next_review_due_ns=NOW + 90 * DAY_NS,
        reviewer="opérateur",
    )
    base.update(kw)
    return CalendarAssertion(**base)


def compile_ok(assertions, snapshots=None, **kw):
    return compile_calendar(
        calendar_version="TEST_1.0",
        market_id=MARKET,
        assertions=assertions,
        snapshots=snapshots if snapshots is not None else {"SRC-1": snapshot()},
        now_ns=NOW,
        approved_by="reviewer",
        **kw,
    )


# ------------------------------------------------------------------ échec bloquant 1


def test_critical_assertion_without_evidence_does_not_compile():
    """Une règle capable de modifier fortement la censure ne peut pas reposer sur une
    source absente. La règle et sa preuve sont inséparables."""
    with pytest.raises(SourceError, match="sans instantané"):
        compile_ok([assertion()], snapshots={})


def test_critical_assertion_from_observation_does_not_compile():
    """L'observation ne devient jamais normative automatiquement."""
    with pytest.raises(SourceError, match="non normative"):
        compile_ok([assertion(source_rank=SourceRank.OBSERVATIONAL_INFERENCE)])


def test_critical_assertion_unreviewed_does_not_compile():
    """Une extraction automatique reste non normative jusqu'à validation humaine."""
    with pytest.raises(SourceError, match="non revue"):
        compile_ok([assertion(review_status=ReviewStatus.PARSED_UNREVIEWED)])


def test_non_critical_assertion_tolerates_a_secondary_source():
    """La contrainte porte sur les règles critiques, pas sur toute assertion."""
    result = compile_ok([
        assertion(
            assertion_type=AssertionType.REGULAR_SESSION,
            source_rank=SourceRank.SECONDARY_MARKET_SOURCE,
            local_start=dt.time(9, 0), local_end=dt.time(17, 0),
        )
    ])
    assert result.content_status is CalendarContentStatus.PROVISIONAL


# ------------------------------------------------------------------ échec bloquant 2


def test_two_normative_sources_of_equal_specificity_block_compilation():
    """« GMT+2 » chez l'un, « 22h » chez l'autre : le moteur ne tranche pas seul."""
    a = assertion("A-1", local_end=dt.time(23, 0))
    b = assertion("A-2", local_end=dt.time(22, 30), source_id="SRC-2")
    with pytest.raises(SourceError, match="Conflit normatif ouvert"):
        compile_ok([a, b], snapshots={"SRC-1": snapshot(), "SRC-2": snapshot("SRC-2")})


def test_conflict_is_detected_with_its_type():
    a = assertion("A-1", timezone=LONDON)
    b = assertion("A-2", timezone="Europe/Lisbon")
    conflicts = detect_conflicts([a, b], NOW)
    assert conflicts and conflicts[0].conflict_type is ConflictType.DIFFERENT_TIMEZONE
    assert conflicts[0].resolution_status == "OPEN"


def test_specificity_beats_general_authority():
    """Une fiche de symbole du compte prime sur une page générique du courtier."""
    specific = assertion(
        "A-SPEC",
        scope=Scope(MARKET, broker="BROKER_A", server="EU-3", account_type="RAW", symbol="XAUUSD"),
        source_rank=SourceRank.NORMATIVE_BROKER_SYMBOL,
    )
    general = assertion(
        "A-GEN",
        scope=Scope(MARKET, broker="BROKER_A"),
        source_rank=SourceRank.NORMATIVE_BROKER_GENERAL,
        known_from_ns=NOW,  # plus récente
    )
    assert resolve_by_priority([general, specific]).assertion_id == "A-SPEC"


def test_recency_alone_never_arbitrates():
    """Une page récente peut décrire une autre période ou un autre produit."""
    old_specific = assertion("A-OLD", known_from_ns=0)
    new_general = assertion(
        "A-NEW",
        scope=Scope(MARKET, broker="BROKER_A"),
        source_rank=SourceRank.NORMATIVE_BROKER_GENERAL,
        known_from_ns=NOW + 10 * DAY_NS,
    )
    assert resolve_by_priority([new_general, old_specific]).assertion_id == "A-OLD"


def test_conflict_between_unequal_specificity_is_informative_not_blocking():
    a = assertion("A-1", scope=Scope(MARKET, broker="BROKER_A", server="EU-3",
                                     account_type="RAW", symbol="XAUUSD"))
    b = assertion("A-2", scope=Scope(MARKET, broker="BROKER_A"),
                  local_end=dt.time(22, 30), source_id="SRC-2")
    conflicts = detect_conflicts([a, b], NOW)
    assert conflicts and not conflicts[0].blocking


# ------------------------------------------------------------------ échec bloquant 3


def test_ambiguous_timezone_does_not_compile():
    """Décalage fixe ou heure locale saisonnière ? La confusion décale toutes les
    sessions d'une heure la moitié de l'année."""
    with pytest.raises(SourceError, match="ambiguë"):
        compile_ok([assertion(
            timezone_interpretation=TimezoneInterpretation.AMBIGUOUS,
            source_timezone_expression="GMT+2",
        )])


def test_unknown_effective_date_does_not_compile():
    """Appliquer rétroactivement une règle sans date d'effet reviendrait à supposer
    qu'elle a toujours été vraie."""
    with pytest.raises(SourceError, match="date d'effet inconnue"):
        compile_ok([assertion(effective_date_basis=EffectiveDateBasis.UNKNOWN)])


def test_inconsistent_validity_period_does_not_compile():
    with pytest.raises(SourceError, match="incohérente"):
        compile_ok([assertion(valid_from_ns=NOW, valid_to_ns=NOW - DAY_NS)])


# ---------------------------------------------------------------------- portée


def test_demo_account_rule_does_not_cover_a_live_account():
    """Une règle d'un compte de démonstration ne décrit pas le compte réel."""
    demo = Scope(MARKET, broker="BROKER_A", account_type="DEMO")
    live = Scope(MARKET, broker="BROKER_A", account_type="RAW")
    assert not demo.covers(live)


def test_null_field_is_a_wildcard_not_an_omission():
    """Un champ nul dit que la règle ne se prononce pas sur cette dimension."""
    general = Scope(MARKET, broker="BROKER_A")
    specific = Scope(MARKET, broker="BROKER_A", server="EU-3", account_type="RAW")
    assert general.covers(specific)
    assert not specific.covers(general)


def test_other_market_is_never_covered():
    assert not Scope("COMEX_GC").covers(Scope(MARKET))


def test_specificity_counts_constrained_dimensions():
    assert Scope(MARKET).specificity == 0
    assert Scope(MARKET, broker="B", server="S", symbol="X").specificity == 3


# ------------------------------------------------------- fraîcheur et changements


def test_freshness_states():
    fresh = assertion(last_verified_at_ns=NOW, next_review_due_ns=NOW + 10 * DAY_NS)
    due = assertion(last_verified_at_ns=NOW, next_review_due_ns=NOW - 10 * DAY_NS)
    stale = assertion(last_verified_at_ns=NOW, next_review_due_ns=NOW - 400 * DAY_NS)
    unknown = assertion(last_verified_at_ns=None, next_review_due_ns=None)

    assert fresh.freshness(NOW) is Freshness.FRESH
    assert due.freshness(NOW) is Freshness.REVIEW_DUE
    assert stale.freshness(NOW) is Freshness.STALE
    assert unknown.freshness(NOW) is Freshness.UNKNOWN_FRESHNESS


def test_stale_assertion_marks_the_calendar_but_still_compiles():
    """Une assertion périmée n'est pas nécessairement fausse — mais elle ne peut pas
    soutenir silencieusement un verdict définitif."""
    result = compile_ok([assertion(next_review_due_ns=NOW - 400 * DAY_NS)])
    assert result.content_status is CalendarContentStatus.STALE
    assert result.stale_assertion_ids


def test_presentation_change_does_not_create_a_new_rule():
    """Une refonte de mise en page ne doit pas produire une règle différente."""
    before, after = snapshot("SRC-1"), snapshot("SRC-1", content_hash="hash-nouveau-html")
    a = assertion("A-1")
    assert classify_change(before, after, [a], [a]) is ChangeKind.PRESENTATION_ONLY_CHANGE


def test_semantic_change_is_detected():
    before, after = snapshot("SRC-1"), snapshot("SRC-1", content_hash="hash-2")
    a = assertion("A-1", local_end=dt.time(23, 0))
    b = assertion("A-1", local_end=dt.time(22, 0))
    assert classify_change(before, after, [a], [b]) is ChangeKind.SEMANTIC_CHANGE


def test_identical_snapshot_and_assertions_is_no_change():
    s = snapshot()
    a = assertion()
    assert classify_change(s, s, [a], [a]) is ChangeKind.NO_CHANGE


def test_removed_and_unavailable_sources_are_distinguished():
    s = snapshot()
    assert classify_change(s, None, [], []) is ChangeKind.SOURCE_REMOVED
    assert classify_change(s, snapshot(unavailable=True), [], []) is ChangeKind.SOURCE_UNAVAILABLE


def test_evidence_survives_an_unavailable_source():
    """La preuve conservée permet encore l'audit quand la source disparaît."""
    gone = snapshot(unavailable=True, retained_excerpt="pause 22:00–23:00")
    assert gone.retained_excerpt
    assert gone.content_hash


# ------------------------------------------------------- supersession et manifest


def test_superseded_assertion_is_excluded_but_not_deleted():
    """Le système ne supprime pas l'ancienne assertion : le calendrier bitemporel doit
    pouvoir reconstruire ce qu'il savait avant la correction."""
    old = assertion("A-OLD", superseded_by_assertion_id="A-NEW",
                    supersession_reason="horaire corrigé par le courtier")
    new = assertion("A-NEW", local_end=dt.time(22, 30), source_id="SRC-2")
    result = compile_ok([old, new], snapshots={"SRC-1": snapshot(), "SRC-2": snapshot("SRC-2")})
    assert "A-OLD" not in result.manifest.assertion_ids
    assert old.supersession_reason


def test_manifest_hash_is_reproducible():
    """Deux constructions du même manifest produisent la même empreinte."""
    a, snaps = [assertion()], {"SRC-1": snapshot()}
    kw = dict(calendar_version="V", market_id=MARKET, assertions=a, snapshots=snaps,
              conflicts=[], approved_by="x", created_at_ns=NOW, effective_from_ns=0)
    assert build_manifest(**kw).manifest_hash == build_manifest(**kw).manifest_hash


def test_manifest_hash_changes_with_content():
    snaps = {"SRC-1": snapshot()}
    kw = dict(calendar_version="V", market_id=MARKET, snapshots=snaps, conflicts=[],
              approved_by="x", created_at_ns=NOW, effective_from_ns=0)
    h1 = build_manifest(assertions=[assertion(local_end=dt.time(23, 0))], **kw).manifest_hash
    h2 = build_manifest(assertions=[assertion(local_end=dt.time(22, 0))], **kw).manifest_hash
    assert h1 != h2


def test_two_compilations_of_the_same_manifest_agree():
    a, snaps = [assertion()], {"SRC-1": snapshot()}
    r1 = compile_ok(a, snaps)
    r2 = compile_ok(a, snaps)
    assert r1.manifest.manifest_hash == r2.manifest.manifest_hash
    assert r1.calendar.calendar_id == r2.calendar.calendar_id


# ---------------------------------------------------------------- impact historique


def test_historical_correction_identifies_affected_reports_without_rewriting():
    """Les anciens rapports ne sont jamais réécrits ; une nouvelle exécution est liée à
    la nouvelle version."""
    base = compile_ok([assertion(
        assertion_type=AssertionType.REGULAR_SESSION,
        local_start=dt.time(9, 0), local_end=dt.time(17, 0),
    )])
    corrected = compile_ok([assertion(
        assertion_type=AssertionType.REGULAR_SESSION,
        local_start=dt.time(9, 0), local_end=dt.time(15, 0),
    )])

    interval = (
        local_to_ns(dt.datetime(2026, 8, 4, 16, 0), LONDON),
        local_to_ns(dt.datetime(2026, 8, 4, 16, 30), LONDON),
    )
    impact = assess_historical_impact(base.calendar, corrected.calendar, [interval])
    assert impact.level is not ImpactLevel.NO_MATERIAL_IMPACT
    assert impact.affected_intervals == (interval,)
    # Le calendrier d'origine est intact.
    assert base.calendar.state_at(interval[0]).primary_state is MarketState.OPEN_CONTINUOUS


def test_correction_without_effect_reports_no_material_impact():
    base = compile_ok([assertion()])
    interval = (
        local_to_ns(dt.datetime(2026, 8, 4, 10, 0), LONDON),
        local_to_ns(dt.datetime(2026, 8, 4, 11, 0), LONDON),
    )
    impact = assess_historical_impact(base.calendar, base.calendar, [interval])
    assert impact.level is ImpactLevel.NO_MATERIAL_IMPACT


# ------------------------------------------------------- compilation et provenance


def test_verified_calendar_is_not_provisional():
    result = compile_ok([assertion()])
    assert result.content_status is CalendarContentStatus.VERIFIED
    assert result.calendar.provisional is False


def test_provisional_content_marks_the_engine_provisional():
    """Le moteur de Q52 refuse alors tout verdict définitif sur ces intervalles."""
    result = compile_ok([assertion(
        assertion_type=AssertionType.REGULAR_SESSION,
        source_rank=SourceRank.OBSERVATIONAL_INFERENCE,
        local_start=dt.time(9, 0), local_end=dt.time(17, 0),
    )])
    assert result.content_status is CalendarContentStatus.PROVISIONAL
    assert result.calendar.provisional is True


def test_compiled_calendar_applies_its_assertions():
    result = compile_ok([
        assertion("A-SESSION", assertion_type=AssertionType.REGULAR_SESSION,
                  local_start=dt.time(9, 0), local_end=dt.time(17, 0)),
        assertion("A-HOLIDAY", assertion_type=AssertionType.HOLIDAY,
                  local_date=dt.date(2026, 8, 10), weekdays=None,
                  local_start=None, local_end=None, source_id="SRC-2"),
    ], snapshots={"SRC-1": snapshot(), "SRC-2": snapshot("SRC-2")})

    cal = result.calendar
    assert cal.state_at(local_to_ns(dt.datetime(2026, 8, 4, 11), LONDON)).primary_state is (
        MarketState.OPEN_CONTINUOUS
    )
    assert cal.state_at(local_to_ns(dt.datetime(2026, 8, 10, 11), LONDON)).primary_state is (
        MarketState.HOLIDAY_CLOSED
    )


def test_provenance_report_exposes_the_chain():
    result = compile_ok([assertion()])
    rep = provenance_report(result, [assertion()])
    assert rep.content_status is CalendarContentStatus.VERIFIED
    assert rep.manifest_hash == result.manifest.manifest_hash
    assert rep.normative_assertion_count == 1
    assert rep.unresolved_conflict_count == 0


def test_snapshot_requires_a_content_hash():
    with pytest.raises(SourceError, match="Empreinte"):
        SourceSnapshot(
            source_id="S", source_type="T", location="L", retrieved_at_ns=NOW,
            content_hash="", market_scope=(MARKET,), acquisition_method="MANUAL",
        )


def test_snapshot_requires_identifier_and_location():
    with pytest.raises(SourceError, match="identifiant"):
        SourceSnapshot(
            source_id="", source_type="T", location="", retrieved_at_ns=NOW,
            content_hash="h", market_scope=(MARKET,), acquisition_method="MANUAL",
        )
