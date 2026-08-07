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

from feasibility.passive_campaign import MovingBlockBootstrapBound

ALPHA = 0.05
REPS = 300


def bootstrap(block_length: int, seed: int = 0) -> MovingBlockBootstrapBound:
    return MovingBlockBootstrapBound(
        block_length=block_length,
        dependence_argument="longueur de bloc supérieure à la persistance mesurée",
        reference="calibration",
        draws=300,
        seed=seed,
        coverage_qualification="campagne de calibration en cours",
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


# ============================================= couverture sous i.i.d.


@pytest.mark.parametrize("p", [0.05, 0.20, 0.50])
def test_coverage_holds_on_independent_episodes(p):
    rng = np.random.default_rng(1)
    series = (rng.random((REPS, 120)) < p).astype(float)
    assert coverage(series, p, block_length=3) >= 1 - ALPHA


def test_coverage_holds_on_a_rare_success_tail():
    """Le cas qui compte pour une stratégie sélective : succès très rares."""
    rng = np.random.default_rng(2)
    series = (rng.random((REPS, 200)) < 0.02).astype(float)
    assert coverage(series, 0.02, block_length=3) >= 1 - ALPHA


def test_coverage_holds_when_no_success_ever_appears():
    """Zéro succès : la borne doit rester au-dessus de tout taux plausible."""
    series = np.zeros((REPS, 100))
    est = bootstrap(3)
    bounds = [est.upper_bound(series[r], ALPHA) for r in range(REPS)]
    assert min(bounds) > 0.0
    assert coverage(series, 0.01, block_length=3) == 1.0


# ============================================= couverture sous dépendance


@pytest.mark.parametrize("persistence", [0.5, 0.8])
def test_coverage_survives_moderate_persistence_with_adequate_blocks(persistence):
    series = markov_binary(REPS, 200, p=0.20, persistence=persistence, seed=3)
    truth = float(series.mean())
    assert coverage(series, truth, block_length=8) >= 1 - ALPHA


def test_blocks_shorter_than_the_persistence_lose_coverage():
    """La longueur de bloc doit dépasser la persistance : sinon la méthode casse
    précisément la dépendance qu'elle est censée conserver."""
    series = markov_binary(REPS, 200, p=0.20, persistence=0.95, seed=4)
    truth = float(series.mean())
    too_short = coverage(series, truth, block_length=1)
    long_enough = coverage(series, truth, block_length=40)
    assert long_enough > too_short


@pytest.mark.parametrize("block_length", [2, 5, 10, 20])
def test_the_bound_widens_monotonically_with_block_length(block_length):
    """Sensibilité au paramètre : elle doit être visible, pas cachée."""
    series = markov_binary(1, 300, p=0.20, persistence=0.9, seed=5)[0]
    assert bootstrap(block_length).upper_bound(series, ALPHA) > series.mean()


# ============================================= ce que la calibration ne donne pas


def test_a_qualified_coverage_reference_is_what_grants_the_status():
    """Une couverture empirique bonne ne s'auto-décerne pas le statut : c'est la
    référence de campagne déclarée qui l'accorde."""
    unqualified = MovingBlockBootstrapBound(
        block_length=3, dependence_argument="argument", reference="v1")
    assert not unqualified.coverage_qualified
    assert bootstrap(3).coverage_qualified


def test_under_a_regime_change_the_bound_degenerates_to_uselessness():
    """Résultat contre-intuitif, et c'est le point : la borne ne perd pas sa couverture,
    elle sature à 1,0. Elle couvre alors **tout** et n'exclut plus rien.

    C'est le bon comportement — une borne qui se tairait serait pire qu'une borne qui
    devient vacante. Mais elle ne devient pas pour autant informative : sur une série
    moitié 5 %, moitié 60 %, la moyenne groupée de 32 % ne décrit aucun des deux
    régimes. Une raison de plus de conserver des cellules homogènes et versionnées.
    """
    rng = np.random.default_rng(6)
    calm = (rng.random((REPS, 100)) < 0.05).astype(float)
    agitated = (rng.random((REPS, 100)) < 0.60).astype(float)
    series = np.concatenate([calm, agitated], axis=1)

    est = bootstrap(8)
    bounds = np.array([est.upper_bound(series[r], ALPHA) for r in range(REPS)])
    assert bounds.mean() > 0.95            # vacante : elle ne borne plus rien d'utile
    assert coverage(series, float(series.mean()), block_length=8) >= 1 - ALPHA

    # Sur un régime homogène de même longueur, la même borne reste informative.
    homogeneous = np.array(
        [bootstrap(8).upper_bound(calm[r], ALPHA) for r in range(REPS)]
    )
    assert homogeneous.mean() < bounds.mean()
    assert homogeneous.mean() < 0.75
