"""Couverture du bootstrap par blocs — **calibration**, séparée du stress (§15).

Le test précédent montrait que la borne s'élargit quand les observations sont
regroupées. C'est nécessaire et insuffisant : réagir à la dépendance ne démontre pas

    P( p_vrai ≤ p_U ) ≥ 1 − α

Ces tests mesurent la couverture empirique sur des processus simulés. Ils délimitent le
domaine où la borne mérite le statut `DEPENDENCE_ROBUST_BOUND` — ils ne le démontrent
pas mathématiquement, et le module ne l'accorde d'ailleurs qu'à un estimateur portant
une référence de campagne de calibration.

    CALIBRATION  → la couverture tient-elle là où on la revendique ?
    STRESS       → où se dégrade-t-elle ?  (test_sequential_stress.py)
"""

from __future__ import annotations

import numpy as np
import pytest

from feasibility.passive_campaign import (
    CampaignError,
    clopper_pearson_lower,
    CoverageQualificationCertificate,
    MovingBlockBootstrapBound,
    QualificationStatus,
)


def certificate(est, **kw) -> CoverageQualificationCertificate:
    base = dict(
        status=QualificationStatus.QUALIFIED, campaign_id="CAL-2026-001",
        protocol_hash=est.protocol_hash, estimator_version=est.version,
        block_rule_version="BLOCK-1.0",
        data_generating_domain="Markov binaire, persistance ≤ 0,8",
        alpha=ALPHA, target_coverage=0.95,
        simulation_repetitions=1_000, covering_repetitions=990,
        calibration_confidence=0.95, qualified_at_ns=0, qualified_by="protocole Q66",
    )
    base.update({"covering_repetitions": kw.pop("covering", base["covering_repetitions"]),
                 "simulation_repetitions": kw.pop("reps", base["simulation_repetitions"])})
    return CoverageQualificationCertificate(**{**base, **kw})

ALPHA = 0.05
REPS = 300


def bootstrap(block_length: int, seed: int = 0) -> MovingBlockBootstrapBound:
    return MovingBlockBootstrapBound(
        block_length=block_length,
        dependence_argument="longueur de bloc supérieure à la persistance mesurée",
        reference="calibration",
        draws=300,
        seed=seed,
    )


def coverage(series: np.ndarray, truth: float, block_length: int) -> float:
    """Part des réplications où la borne couvre effectivement le vrai taux."""
    est = bootstrap(block_length)
    covered = [
        est.upper_bound(series[r], ALPHA) >= truth for r in range(series.shape[0])
    ]
    return float(np.mean(covered))


def markov_binary(reps: int, n: int, p: float, persistence: float, seed: int):
    """Chaîne binaire à persistance réglable — succès groupés, comme les épisodes."""
    rng = np.random.default_rng(seed)
    out = np.zeros((reps, n))
    out[:, 0] = rng.random(reps) < p
    for t in range(1, n):
        stay = rng.random(reps) < persistence
        fresh = rng.random(reps) < p
        out[:, t] = np.where(stay, out[:, t - 1], fresh)
    return out


# ============================================= couverture mesurée, pas supposée


@pytest.mark.parametrize("p", [0.05, 0.20, 0.50])
def test_the_measured_coverage_does_not_qualify_the_procedure(p):
    """**Le résultat qui maintient Q66 ouverte.** La couverture mesurée frôle le nominal
    — 0,94 à 0,96 selon `p` — mais sa **borne inférieure** ne l'atteint jamais avec ce
    nombre de réplications.

    C'est précisément l'erreur que le certificat interdit : conclure « couverture vraie
    ≥ 95 % » depuis la seule proportion observée. Aucun certificat ne peut donc être
    émis en l'état, et le statut reste `DEPENDENCE_MODELLED_BOUND`.
    """
    rng = np.random.default_rng(1)
    series = (rng.random((REPS, 120)) < p).astype(float)
    measured = coverage(series, p, block_length=3)   # p connu : paramètre du générateur
    covering = int(round(measured * REPS))
    assert clopper_pearson_lower(covering, REPS, 1 - 0.95) < 0.95


def test_the_calibration_truth_is_the_generator_parameter_not_the_sample_mean():
    """Estimer la vérité sur les réplications qui servent à mesurer la couverture
    reviendrait à se noter soi-même."""
    rng = np.random.default_rng(7)
    p = 0.20
    series = (rng.random((REPS, 120)) < p).astype(float)
    sample_mean = float(series.mean())

    # La moyenne d'échantillon dérive du paramètre — et surtout, elle est calculée sur
    # les réplications mêmes qui servent à mesurer la couverture.
    assert sample_mean != p
    assert abs(sample_mean - p) < 0.02
    assert coverage(series, p, block_length=3) > 0.0


def test_a_markov_chain_is_calibrated_against_its_stationary_marginal():
    """Le générateur démarre sur sa marginale : la vérité est `p`, pas la moyenne des
    séries simulées."""
    p = 0.20
    series = markov_binary(REPS, 200, p=p, persistence=0.8, seed=3)
    measured = coverage(series, p, block_length=8)
    assert 0.0 <= measured <= 1.0
    # Publié comme mesure, sans prétendre atteindre la cible.
    assert measured < 1.0


# ============================================= conservatisme, pas couverture


def test_the_zero_success_floor_is_a_conservatism_check_not_a_coverage_test():
    """Une série identiquement nulle a `p_vrai = 0`. Vérifier que la borne dépasse 0,01
    mesure son conservatisme sous ce générateur — pas sa couverture."""
    series = np.zeros((REPS, 120))
    est = bootstrap(3)
    bounds = [est.upper_bound(series[r], ALPHA) for r in range(REPS)]
    assert min(bounds) > 0.0
    assert min(bounds) < 0.20        # informative, pas saturée


def test_the_zero_success_floor_stays_in_the_procedure_own_unit():
    """Le plancher compare des blocs à des blocs. Comparer un nombre de succès au niveau
    épisode à un nombre d'essais au niveau bloc renvoyait 1,0 et saturait la borne."""
    est = bootstrap(3)
    dense = np.array([1.0, 1.0, 0.0] * 40)       # 80 porteurs, 40 blocs
    assert est.upper_bound(dense, ALPHA) <= 1.0
    sparse = np.r_[np.ones(6), np.zeros(114)]
    assert est.upper_bound(sparse, ALPHA) < 0.5


@pytest.mark.parametrize("block_length", [2, 5, 10, 20])
def test_the_bound_reacts_to_block_length(block_length):
    """Sensibilité au paramètre : elle doit être visible, pas cachée."""
    series = markov_binary(1, 300, p=0.20, persistence=0.9, seed=5)[0]
    assert bootstrap(block_length).upper_bound(series, ALPHA) > series.mean()


def test_blocks_shorter_than_the_persistence_bound_more_tightly():
    """Des blocs trop courts cassent la dépendance qu'ils devraient conserver, et
    produisent une borne plus étroite — donc trop optimiste."""
    series = markov_binary(1, 300, p=0.20, persistence=0.95, seed=4)[0]
    assert bootstrap(1).upper_bound(series, ALPHA) < bootstrap(40).upper_bound(series, ALPHA)


# ============================================= ce que la calibration ne donne pas


def test_a_string_never_grants_normative_authority():
    """« campagne de calibration en cours » accordait le statut normatif à une campagne
    que son propre libellé déclarait inachevée."""
    est = bootstrap(3)
    assert not est.coverage_qualified          # aucun certificat

    in_progress = certificate(est, status=QualificationStatus.IN_PROGRESS)
    assert not in_progress.qualifies(est.version, est.protocol_hash)
    assert "IN_PROGRESS" in in_progress.explain(est.version, est.protocol_hash)


def test_the_lower_bound_on_coverage_decides_not_the_observed_proportion():
    """285/300 donnent exactement 95 %, mais la borne inférieure vaut ≈ 92 % : on ne
    peut pas conclure que la couverture vraie atteint la cible."""
    est = bootstrap(3)
    borderline = certificate(est, covering=285, reps=300)
    assert borderline.empirical_coverage == pytest.approx(0.95)
    assert borderline.coverage_lower_bound < 0.95
    assert not borderline.qualifies(est.version, est.protocol_hash)
    assert "borne inférieure" in borderline.explain(est.version, est.protocol_hash)

    # Il faut beaucoup plus de réplications pour que la borne atteigne la cible.
    ample = certificate(est, covering=9_900, reps=10_000)
    assert ample.coverage_lower_bound >= 0.95
    assert ample.qualifies(est.version, est.protocol_hash)


def test_a_certificate_emitted_for_another_estimator_does_not_transfer():
    est = bootstrap(3)
    other = bootstrap(20)
    cert = certificate(est, covering=9_900, reps=10_000)
    assert cert.qualifies(est.version, est.protocol_hash)
    assert not cert.qualifies(other.version, other.protocol_hash)


def test_a_certificate_needs_all_its_provenance_fields():
    est = bootstrap(3)
    with pytest.raises(CampaignError, match="campaign_id"):
        certificate(est, campaign_id="  ")
    with pytest.raises(CampaignError, match="data_generating_domain"):
        certificate(est, data_generating_domain=" ")


def test_a_regime_change_is_an_estimand_diagnostic_not_a_coverage_test():
    """Sur une série moitié 5 %, moitié 60 %, il n'existe **aucune** probabilité
    stationnaire unique représentant les deux régimes. Dire que la borne « couvre la
    moyenne » ne qualifierait donc pas le bon estimande.

    Ce test reste un diagnostic de non-stationnarité : il montre que la borne s'élargit,
    sans prétendre mesurer une couverture. Une raison de plus de conserver des cellules
    homogènes et versionnées.
    """
    rng = np.random.default_rng(6)
    calm = (rng.random((REPS, 100)) < 0.05).astype(float)
    agitated = (rng.random((REPS, 100)) < 0.60).astype(float)
    series = np.concatenate([calm, agitated], axis=1)

    est = bootstrap(8)
    bounds = np.array([est.upper_bound(series[r], ALPHA) for r in range(REPS)])
    homogeneous = np.array(
        [bootstrap(8).upper_bound(calm[r], ALPHA) for r in range(REPS)]
    )
    assert bounds.mean() > homogeneous.mean()
