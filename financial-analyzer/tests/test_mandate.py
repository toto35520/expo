"""Q1-v1 — le mandat économique normatif.

Chaque test vise un cas où le mandat serait mal lu : qualité liée à la taille du compte,
`NO TRADE` récompensé, `δ_MEU` pris pour une espérance, ou contrainte de politique
présentée comme une limite physique.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from feasibility.mandate import (
    MANDATE_VERSION,
    QUALITY_COVERAGE_COLUMNS,
    REQUIRED_BREAKDOWNS,
    REQUIRED_TAIL_METRICS,
    Q1_V1,
    EconomicMandate,
    MandateError,
    SignalExecutionStatus,
    SystemRole,
)
from feasibility.passive_campaign import EconomicFrequencyRequirement


# ============================================= l'unité protège du capital


def test_the_quality_of_a_signal_does_not_depend_on_account_size():
    """C'est le point central : ne jamais calibrer l'analyseur sur un compte à 75 €."""
    assert Q1_V1.performance_unit == "R"
    assert Q1_V1.risk_unit_in_currency(100) == 0.50
    assert Q1_V1.risk_unit_in_currency(1_000) == 5.0
    assert Q1_V1.risk_unit_in_currency(10_000) == 50.0
    # Aucune de ces valeurs n'apparaît dans les seuils.
    assert Q1_V1.j_min_per_session_r == 0.10
    assert Q1_V1.delta_meu_r == 0.20


def test_a_mandate_expressed_in_currency_is_refused():
    with pytest.raises(MandateError, match="unité primaire est R"):
        replace(Q1_V1, performance_unit="EUR")


def test_a_lot_minimum_invalidates_the_execution_not_the_signal():
    """`SIGNAL_VALID + EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL`, jamais `BAD_SIGNAL`."""
    assert Q1_V1.execution_status(planned_risk_r=1.0, smallest_lot_risk_r=0.4) is (
        SignalExecutionStatus.EXECUTABLE)
    assert Q1_V1.execution_status(planned_risk_r=1.0, smallest_lot_risk_r=3.2) is (
        SignalExecutionStatus.EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL)


# ============================================= les valeurs v1


def test_the_horizon_target_follows_from_the_session_target():
    assert Q1_V1.j_min_over_horizon_r == pytest.approx(6.0)
    assert Q1_V1.evaluation_horizon_sessions == 60


def test_the_target_is_reachable_by_a_very_selective_system():
    """Un trade qualifiant toutes les deux séances suffit — c'est ce qui rend la cible
    compatible avec de longues séries de `NO TRADE`."""
    assert Q1_V1.frequency_if_ev_equals_meu() == pytest.approx(0.5)


def test_the_drawdown_budget_is_twice_the_horizon_target():
    """Rapport publié plutôt que subi : il est facile de le découvrir après coup."""
    assert Q1_V1.drawdown_to_target_ratio == pytest.approx(2.0)


def test_the_role_decides_whether_q42_is_required():
    assert Q1_V1.role is SystemRole.RECOMMENDATION
    assert not Q1_V1.role.requires_broker_qualification
    assert SystemRole.AUTO_EXECUTION.requires_broker_qualification


# ============================================= ce que le mandat refuse


def test_simultaneous_risk_cannot_be_below_a_single_trade():
    with pytest.raises(MandateError, match="risque simultané"):
        replace(Q1_V1, max_planned_open_risk_r=0.5)


def test_every_threshold_must_be_positive():
    for field in ("j_min_per_session_r", "delta_meu_r", "max_planned_risk_per_trade_r",
                  "max_validation_drawdown_r"):
        with pytest.raises(MandateError, match=field):
            replace(Q1_V1, **{field: 0.0})


def test_a_mandate_without_an_author_is_refused():
    with pytest.raises(MandateError, match="auteur"):
        replace(Q1_V1, declared_by="  ")


# ============================================= versionnement


def test_any_normative_change_produces_a_different_fingerprint():
    """Changer J_min, δ_MEU, le risque, la limite de perte, l'horizon, le rôle ou
    l'unité crée une version suivante, non rétroactive."""
    base = Q1_V1.fingerprint
    for field, value in (("j_min_per_session_r", 0.15), ("delta_meu_r", 0.30),
                         ("max_planned_risk_per_trade_r", 0.5),
                         ("max_validation_drawdown_r", 20.0),
                         ("evaluation_horizon_sessions", 90),
                         ("role", SystemRole.AUTO_EXECUTION)):
        assert replace(Q1_V1, **{field: value}).fingerprint != base


def test_the_version_name_is_explicit():
    assert Q1_V1.version == MANDATE_VERSION == "Q1-GOLD-RECOMMENDATION-V1"


# ============================================= dérivation de Q64


def test_the_frequency_requirement_derives_from_the_mandate():
    """Q64 ne fixe plus ses seuils : elle les lit dans Q1."""
    req = EconomicFrequencyRequirement.from_mandate(
        Q1_V1, ev_upper_r=2.0, sessions_per_second=1 / 86_400)
    # J_min 0,10 R ÷ EV_U 2,0 R = 0,05 trade/séance.
    assert req.value_per_second * 86_400 == pytest.approx(0.05)
    assert Q1_V1.version in req.q1_reference
    assert Q1_V1.fingerprint in req.q1_reference


def test_a_generous_expectation_bound_lowers_the_required_frequency():
    """C'est ce qui protège un moteur rare : mieux ses trades valent, moins il en faut."""
    rare_but_strong = EconomicFrequencyRequirement.from_mandate(
        Q1_V1, ev_upper_r=4.0, sessions_per_second=1 / 86_400)
    mediocre = EconomicFrequencyRequirement.from_mandate(
        Q1_V1, ev_upper_r=0.25, sessions_per_second=1 / 86_400)
    assert rare_but_strong.value_per_second < mediocre.value_per_second


def test_a_non_positive_expectation_bound_is_refused():
    with pytest.raises(MandateError, match="positive"):
        Q1_V1.necessary_frequency_per_session(0.0)


# ============================================= ce que le rapport doit publier


def test_the_report_requirements_are_named_not_left_to_judgement():
    assert "macro/non-macro" in REQUIRED_BREAKDOWNS
    assert "Expected Shortfall" in REQUIRED_TAIL_METRICS
    assert "pertes de gap et de glissement" in REQUIRED_TAIL_METRICS
    assert "couverture" in QUALITY_COVERAGE_COLUMNS
    assert "calibration (Brier)" in QUALITY_COVERAGE_COLUMNS


def test_the_planned_risk_is_never_presented_as_a_maximum_loss():
    """Gaps et glissement produisent des pertes supérieures à 1R ; l'écart se mesure."""
    assert any("gap" in m for m in REQUIRED_TAIL_METRICS)
    assert Q1_V1.max_planned_risk_per_trade_r == 1.0
