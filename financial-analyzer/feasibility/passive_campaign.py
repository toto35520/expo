"""Campagne passive de qualification réelle (Q51-A + Q57).

Première collecte réelle et irréversible du projet. **Aucun ordre n'est émis**, aucune
capacité courtier n'est supposée : la campagne fonctionne avec une fiche Q58 entièrement
vide et ne prétend rien mesurer au-delà de la frontière du processus.

Elle produit une seule grandeur décisionnelle :

    L^LB_p95 | rafale, cellule

soit le 95ᵉ centile de la borne inférieure de latence, **conditionné à l'état où les
signaux apparaissent réellement**. Un p95 global ne peut jamais le remplacer : les signaux
microstructurels apparaissent quand les ticks accélèrent, quand la file se remplit et
quand la boucle d'événements est la plus sollicitée — exactement là où la latence se
dégrade.

Le résultat n'est pas un nombre. C'est une **surface de latence**, à intersecter avec la
surface de coûts de Q40.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from typing import Protocol
from dataclasses import dataclass, field, replace
from enum import Enum

import numpy as np

from .latency_journal import BurstState, ConnectionState
from .sequential import (
    ConfidenceSequence,
    InferenceMode,
    InferenceValidity,
    ThresholdVerdict,
    interval_for_mode,
    threshold_verdict,
    validity,
)
from .observability import (
    ClockCapability,
    ClockDomain,
    BoundaryQuality,
    LatencyBoundary,
    LatencyPath,
    MeasurementGrade,
    format_ns,
)

NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000
CAMPAIGN_VERSION = "Q51A_PASSIVE_1.0"


class CampaignError(ValueError):
    """Mesure impossible, cellule mal formée, ou politique déclarée trop tard."""


# ------------------------------------------------------------------- la cellule


class PipelineMode(str, Enum):
    """Trois niveaux de charge (§9). Seul TARGET alimente le verdict principal.

    Exécuter tous les moteurs futurs pour mesurer une latence maximale fictive
    produirait un chiffre défavorable qui ne décrit aucune architecture réelle.
    """

    MINIMAL = "PIPELINE_MINIMAL"
    TARGET = "PIPELINE_TARGET"
    STRESS = "PIPELINE_STRESS"


class EvaluationMode(str, Enum):
    EVENT_DRIVEN = "EVENT_DRIVEN"
    PERIODIC = "PERIODIC"


@dataclass(frozen=True)
class CampaignCell:
    """Cellule de fonctionnement. Le conditionnement n'est pas optionnel (ADR-172)."""

    source: str
    session: str
    burst_state: BurstState
    evaluation_mode: EvaluationMode
    pipeline: PipelineMode
    host_id: str
    software_commit: str
    evaluation_period_ns: int | None = None

    def __post_init__(self) -> None:
        if self.evaluation_mode is EvaluationMode.PERIODIC and not self.evaluation_period_ns:
            raise CampaignError(
                "Une cellule périodique doit déclarer sa cadence configurée : sans elle, "
                "la cadence réellement observée n'est comparable à rien."
            )

    @property
    def label(self) -> str:
        return (
            f"{self.source}/{self.session}/{self.burst_state.value}"
            f"/{self.evaluation_mode.value}/{self.pipeline.value}"
        )


# ------------------------------------------------------- frontières et contexte


@dataclass(frozen=True)
class PassiveBoundaries:
    """Les six frontières du chemin passif (§2).

    `B0` appartient au domaine du fournisseur ; les cinq autres à l'horloge monotone
    locale. La borne locale est `B5 − B1` — une **différence de frontières**, jamais une
    somme d'intervalles (ADR-168, ADR-171).
    """

    #: B0 — horodatage fournisseur. Absent ou non qualifiable dans le cas courant.
    provider_event_ns: int | None
    #: B1 — réception locale, horloge monotone.
    local_receive_ns: int
    #: B2 — l'événement devient éligible à l'évaluation.
    eligible_ns: int
    #: B3 — début d'évaluation.
    evaluation_start_ns: int
    #: B4 — fin d'évaluation.
    evaluation_end_ns: int
    #: B5 — décision disponible.
    decision_ready_ns: int
    #: Horodatage mural de la réception, conservé pour l'audit et le rattachement.
    local_receive_wall_ns: int = 0

    #: Les cinq frontières locales, dans l'ordre du chemin.
    LOCAL_FIELDS = (
        "local_receive_ns", "eligible_ns", "evaluation_start_ns",
        "evaluation_end_ns", "decision_ready_ns",
    )

    def __post_init__(self) -> None:
        missing = [f for f in self.LOCAL_FIELDS if getattr(self, f) is None]
        if missing:
            # Sans ce contrôle, une frontière absente ferait silencieusement retomber la
            # borne sur la dernière frontière connue : `B4 − B1` au lieu de `B5 − B1`.
            # La valeur resterait plausible, mais mesurerait une autre grandeur.
            raise CampaignError(
                f"Chemin local incomplet : {', '.join(missing)}. Une frontière absente "
                "n'est jamais remplacée par la précédente — la borne mesurerait alors "
                "un chemin plus court sans le dire."
            )

    def local_path(self, clock: ClockCapability | None = None) -> LatencyPath:
        q = BoundaryQuality.EXACT_LOCAL
        d = ClockDomain.LOCAL_MONOTONIC
        return LatencyPath(
            boundaries=(
                LatencyBoundary("local_receive", self.local_receive_ns, d, q),
                LatencyBoundary("eligible", self.eligible_ns, d, q),
                LatencyBoundary("evaluation_start", self.evaluation_start_ns, d, q),
                LatencyBoundary("evaluation_end", self.evaluation_end_ns, d, q),
                LatencyBoundary("decision_ready", self.decision_ready_ns, d, q),
            ),
            clock=clock,
        )

    def full_path(self, clock: ClockCapability | None = None) -> LatencyPath:
        """Chemin complet depuis l'horodatage fournisseur.

        Le segment `B0 → B1` reste `NOT_RESOLVABLE_INTERSYSTEM` tant que Q57 n'a pas
        qualifié la comparaison — même si les deux valeurs numériques existent.
        """
        known = self.provider_event_ns is not None
        head = LatencyBoundary(
            "provider_event",
            self.provider_event_ns,
            ClockDomain.PROVIDER if known else ClockDomain.NONE,
            BoundaryQuality.QUALIFIED_INTERSYSTEM if known else BoundaryQuality.UNKNOWN,
        )
        return LatencyPath(
            boundaries=(head,) + self.local_path(clock).boundaries, clock=clock
        )


@dataclass(frozen=True)
class MarketContext:
    """Intensité au moment du déclenchement. Continue d'abord, classée ensuite (§10)."""

    tick_rate_100ms: float
    tick_rate_1s: float
    tick_rate_5s: float
    spread: float
    spread_percentile: float
    price_velocity: float
    burst_percentile: float


@dataclass(frozen=True)
class HostLoad:
    """Ce que la campagne mesure d'elle-même — elle fait partie du chemin critique."""

    evaluation_queue_depth: int
    pending_event_count: int
    event_loop_lag_ns: int
    cpu_load: float
    memory_bytes: int


# ------------------------------------------------------------- l'observation


@dataclass(frozen=True)
class PassiveObservation:
    """Une évaluation, de la réception à la décision.

    Rien de ce qui suit la décision n'est représenté : émission, accusé, ordre actif et
    exécution restent **explicitement absents** (ADR-173).
    """

    boundaries: PassiveBoundaries
    market: MarketContext
    host: HostLoad
    cell: CampaignCell
    cluster_id: str
    day: str
    clock_grade: MeasurementGrade
    connection_state: ConnectionState
    calendar_state: str
    macro_window: bool = False
    provider_qualified: bool = False
    _local_bound_ns: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        # La validation d'ordre et le calcul de la borne passent tous deux par le chemin :
        # une seule définition, donc aucune dérive possible entre contrôle et mesure.
        # La complétude des cinq frontières, elle, est déjà garantie par PassiveBoundaries.
        bound = self.boundaries.local_path().critical_path_ns()
        object.__setattr__(self, "_local_bound_ns", bound)

    @property
    def local_lower_bound_ns(self) -> int:
        """`B5 − B1`, la borne locale (§3).

        Elle ignore tout ce qui précède la réception locale et tout ce qui suit la
        décision : la latence réelle ne peut qu'être supérieure.
        """
        return self._local_bound_ns

    def provider_lower_bound_ns(self, clock: ClockCapability) -> int | None:
        """`B5 − B0`, publiée **uniquement** si Q57 qualifie la comparaison."""
        if not self.provider_qualified or self.boundaries.provider_event_ns is None:
            return None
        return self.boundaries.full_path(clock).critical_path_ns()

    @property
    def eligibility_ns(self) -> int:
        return self.boundaries.eligible_ns - self.boundaries.local_receive_ns

    @property
    def evaluation_wait_ns(self) -> int:
        """`B3 − B2` — mesuré événement par événement.

        Jamais remplacé par `cadence / 2` : cette approximation suppose des arrivées
        uniformes, alors que les cotations arrivent en rafale et s'alignent souvent sur
        des frontières rondes.
        """
        return self.boundaries.evaluation_start_ns - self.boundaries.eligible_ns

    @property
    def compute_ns(self) -> int:
        return self.boundaries.evaluation_end_ns - self.boundaries.evaluation_start_ns

    @property
    def decision_ns(self) -> int:
        return self.boundaries.decision_ready_ns - self.boundaries.evaluation_end_ns

    @property
    def components_sum_ns(self) -> int:
        """Les quatre composantes. Égale la borne : les frontières sont consécutives."""
        return (
            self.eligibility_ns + self.evaluation_wait_ns
            + self.compute_ns + self.decision_ns
        )

    @property
    def usable_for_local_distribution(self) -> bool:
        """Les qualités de mesure ne se mélangent pas dans une même distribution (§16)."""
        return self.clock_grade is MeasurementGrade.EXACT_LOCAL


# ---------------------------------------------------------------- les grappes


@dataclass
class ClusterAssigner:
    """Attribue une grappe à **chaque** observation, y compris hors rafale.

    Cent ticks d'une même rafale ne sont pas cent observations indépendantes — mais deux
    cotations calmes séparées de 50 ms ne le sont pas davantage. Ne regrouper que les
    rafales laisserait le régime normal se compter comme indépendant observation par
    observation, et gonflerait la précision apparente exactement là où le rapport est le
    plus lu.
    """

    burst_threshold: float
    reset_ns: int
    quiet_block_ns: int
    session_id: str = "S1"
    _in_burst: bool = field(default=False, init=False)
    _below_since_ns: int | None = field(default=None, init=False)
    _burst_index: int = field(default=0, init=False)

    def assign(self, now_ns: int, intensity: float) -> str:
        if intensity > self.burst_threshold:
            if not self._in_burst:
                self._burst_index += 1
                self._in_burst = True
            self._below_since_ns = None
            return f"{self.session_id}:burst:{self._burst_index}"

        if self._in_burst:
            # Une rafale ne se termine qu'après un retour sous le seuil maintenu : sinon
            # une oscillation autour du seuil fabriquerait des grappes artificielles.
            if self._below_since_ns is None:
                self._below_since_ns = now_ns
            if now_ns - self._below_since_ns < self.reset_ns:
                return f"{self.session_id}:burst:{self._burst_index}"
            self._in_burst = False
            self._below_since_ns = None

        block = now_ns // self.quiet_block_ns
        return f"{self.session_id}:quiet:{block}"


# ------------------------------------------------------------ les distributions


@dataclass(frozen=True)
class Quantiles:
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    maximum: float

    @staticmethod
    def of(values: Sequence[float]) -> "Quantiles":
        if not len(values):
            nan = float("nan")
            return Quantiles(nan, nan, nan, nan, nan, nan)
        a = np.asarray(values, dtype=float)
        return Quantiles(
            *(float(np.quantile(a, q)) for q in (0.50, 0.75, 0.90, 0.95, 0.99)),
            float(a.max()),
        )


def _cluster_bootstrap_ci(
    values: Sequence[float],
    cluster_ids: Sequence[str],
    quantile: float = 0.95,
    draws: int = 400,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Intervalle par rééchantillonnage **de grappes**, jamais d'observations.

    Rééchantillonner les observations traiterait une rafale de 300 ticks comme 300 tirages
    indépendants et produirait un intervalle faussement étroit.
    """
    rng = rng or np.random.default_rng(0)
    by_cluster: dict[str, list[float]] = {}
    for v, c in zip(values, cluster_ids):
        by_cluster.setdefault(c, []).append(float(v))
    keys = list(by_cluster)
    if len(keys) < 2:
        return float("nan"), float("nan")

    estimates = []
    for _ in range(draws):
        drawn = rng.choice(len(keys), size=len(keys), replace=True)
        pooled: list[float] = []
        for i in drawn:
            pooled.extend(by_cluster[keys[i]])
        estimates.append(float(np.quantile(pooled, quantile)))
    return float(np.quantile(estimates, 0.05)), float(np.quantile(estimates, 0.95))


@dataclass(frozen=True)
class BoundSummary:
    """Distribution de la borne locale pour une cellule."""

    cell: CampaignCell
    observations: int
    clusters: int
    bound: Quantiles
    eligibility: Quantiles
    evaluation_wait: Quantiles
    compute: Quantiles
    decision: Quantiles
    p95_ci_low: float
    p95_ci_high: float

    @property
    def relative_ci_width(self) -> float:
        if not np.isfinite(self.p95_ci_low) or self.bound.p95 <= 0:
            return float("inf")
        return (self.p95_ci_high - self.p95_ci_low) / self.bound.p95


def summarise_cell(
    observations: Sequence[PassiveObservation],
    rng: np.random.Generator | None = None,
) -> BoundSummary:
    """Résume une cellule. N'accepte que des mesures de même qualité d'horloge."""
    usable = [o for o in observations if o.usable_for_local_distribution]
    if not usable:
        raise CampaignError(
            "Aucune observation à horloge exacte : une distribution locale ne se calcule "
            "pas sur des mesures de qualités mélangées."
        )
    cells = {o.cell for o in usable}
    if len(cells) != 1:
        raise CampaignError(
            f"{len(cells)} cellules mélangées dans un même résumé. Le conditionnement "
            "perdrait tout son sens."
        )

    bounds = [o.local_lower_bound_ns for o in usable]
    clusters = [o.cluster_id for o in usable]
    lo, hi = _cluster_bootstrap_ci(bounds, clusters, 0.95, rng=rng)
    return BoundSummary(
        cell=usable[0].cell,
        observations=len(usable),
        clusters=len(set(clusters)),
        bound=Quantiles.of(bounds),
        eligibility=Quantiles.of([o.eligibility_ns for o in usable]),
        evaluation_wait=Quantiles.of([o.evaluation_wait_ns for o in usable]),
        compute=Quantiles.of([o.compute_ns for o in usable]),
        decision=Quantiles.of([o.decision_ns for o in usable]),
        p95_ci_low=lo,
        p95_ci_high=hi,
    )


def summarise_by_cell(
    observations: Iterable[PassiveObservation],
    rng: np.random.Generator | None = None,
) -> dict[CampaignCell, BoundSummary]:
    grouped: dict[CampaignCell, list[PassiveObservation]] = {}
    for o in observations:
        if o.usable_for_local_distribution:
            grouped.setdefault(o.cell, []).append(o)
    return {c: summarise_cell(v, rng=rng) for c, v in grouped.items()}


# ---------------------------------------------------------------- la couverture


@dataclass(frozen=True)
class CoverageReport:
    days_observed: int
    sessions_observed: int
    normal_clusters: int
    burst_clusters_p95: int
    burst_clusters_p99: int
    macro_windows: int
    observations: int
    invalid_clock_observations: int


def coverage(observations: Iterable[PassiveObservation]) -> CoverageReport:
    obs = list(observations)
    burst95 = {o.cluster_id for o in obs if o.cell.burst_state is BurstState.BURST_P95}
    burst99 = {o.cluster_id for o in obs if o.cell.burst_state is BurstState.BURST_P99}
    normal = {
        o.cluster_id for o in obs
        if o.cell.burst_state in (BurstState.NORMAL, BurstState.ELEVATED)
    }
    return CoverageReport(
        days_observed=len({o.day for o in obs}),
        sessions_observed=len({o.cell.session for o in obs}),
        normal_clusters=len(normal),
        burst_clusters_p95=len(burst95),
        burst_clusters_p99=len(burst99),
        macro_windows=len({o.cluster_id for o in obs if o.macro_window}),
        observations=len(obs),
        invalid_clock_observations=sum(
            1 for o in obs if o.clock_grade is MeasurementGrade.UNKNOWN
        ),
    )


# ------------------------------------------- statut des données et cible économique


class DataStatus(str, Enum):
    """Sépare la collecte du verdict (ADR-204).

    La collecte peut démarrer immédiatement. Ce qui doit attendre le gel du protocole,
    c'est le droit d'en tirer un verdict — pas l'enregistrement lui-même. Aucune donnée
    n'est perdue, et aucune décision statistique n'est prise après avoir vu son résultat.
    """

    #: Collectée avant le gel du protocole. Sert au réglage, au diagnostic, à
    #: l'estimation des ordres de grandeur — jamais au premier verdict normatif.
    EXPLORATORY = "EXPLORATORY"
    #: Période contiguë postérieure au gel. Seule elle soutient le verdict normatif.
    NORMATIVE = "NORMATIVE"


@dataclass(frozen=True)
class ProtocolFreeze:
    """Instant à partir duquel les données deviennent normatives."""

    frozen_at_ns: int
    frozen_by: str
    inference_mode: InferenceMode
    fingerprint: str

    def status_of(self, observed_at_ns: int) -> DataStatus:
        return (
            DataStatus.NORMATIVE if observed_at_ns >= self.frozen_at_ns
            else DataStatus.EXPLORATORY
        )

    def partition(
        self, observations: Sequence[PassiveObservation]
    ) -> dict[DataStatus, tuple[PassiveObservation, ...]]:
        out: dict[DataStatus, list[PassiveObservation]] = {
            DataStatus.EXPLORATORY: [], DataStatus.NORMATIVE: []
        }
        for o in observations:
            out[self.status_of(o.boundaries.local_receive_wall_ns)].append(o)
        return {k: tuple(v) for k, v in out.items()}


class FrequencyAxis(str, Enum):
    """Deux axes orthogonaux, jamais réduits à un seul plancher."""

    ADEQUATE = "ADEQUATE"
    #: Trop rare pour atteindre la cible économique, l'espérance étant connue.
    ECONOMICALLY_NON_VIABLE = "ECONOMICALLY_NON_VIABLE"
    #: Économiquement possible, mais trop rare pour être validée avec cet historique.
    #: **Ce n'est pas un échec économique.**
    STATISTICALLY_INDETERMINATE = "STATISTICALLY_INDETERMINATE"


class EvBasis(str, Enum):
    """Base de l'espérance nette — typée pour empêcher un double comptage du fill."""

    #: Par déclenchement : la probabilité d'exécution est **déjà incluse**.
    EV_PER_TRIGGER = "EV_PER_TRIGGER"
    #: Par exécution effective : la probabilité d'exécution reste à appliquer.
    EV_PER_FILLED_EXECUTION = "EV_PER_FILLED_EXECUTION"


class EconomicTarget(str, Enum):
    """Grandeur qui **pilote** les seuils de Q64 ; les autres en dérivent.

    Exiger simultanément `δ_MEU`, `f_min` et `J_min` choisis indépendamment code souvent
    trois fois la même exigence — et l'une des trois finit par mordre sans qu'on sache
    laquelle.
    """

    PER_OCCURRENCE = "PER_OCCURRENCE"
    PER_UNIT_TIME = "PER_UNIT_TIME"
    FREQUENCY = "FREQUENCY"


@dataclass(frozen=True)
class EconomicThresholds:
    """Q64 — seuils économiques **dérivés de Q1**, jamais choisis pour leur commodité.

    Ils expriment ce que le projet appelle « un effet suffisamment utile pour justifier
    le système ». Les choisir parce qu'ils produisent une taille d'échantillon pratique
    inverserait le raisonnement.

    Deux planchers de fréquence sont distingués et **ne se confondent pas** :
    `f_econ_min` vient de l'économie, `f_stat_min` de ce qu'il faut pour valider
    statistiquement quoi que ce soit.
    """

    primary: EconomicTarget
    #: Valeur nette minimale par occurrence exploitable.
    delta_meu: float
    #: Contribution économique minimale par unité de temps.
    j_min_per_second: float
    #: Fréquence minimale d'origine **statistique**.
    f_stat_min_per_second: float
    q1_reference: str = ""
    unit: str = "USD/oz"

    def __post_init__(self) -> None:
        if not self.q1_reference.strip():
            raise CampaignError(
                "Les seuils économiques dérivent de la cible définie par Q1 — objectif, "
                "unité de performance, capital de référence, tolérance de risque, "
                "horizon d'évaluation, rôle du système. Sans cette référence, ils ne "
                "sont que des nombres choisis pour leur commodité."
            )
        if self.delta_meu <= 0:
            raise CampaignError("le surplus minimal par occurrence doit être positif")
        if self.ev_basis is None:
            raise CampaignError(
                "La base de l'espérance doit être typée : EV_PER_TRIGGER inclut déjà la "
                "probabilité d'exécution, EV_PER_FILLED_EXECUTION non. Les mélanger "
                "compterait le fill deux fois."
            )

    @property
    def f_econ_min_per_second(self) -> float | None:
        """Fréquence qu'implique la cible temporelle, **exclusivement dérivée** :

            f_econ_min = (J_min + C_fixes + C_capital) / (P(fill) · EV_filled)

        Retourne `None` lorsque l'espérance n'est pas connue. Une fréquence économique
        indéterminée **n'exclut rien** — elle ne peut pas être remplacée par une valeur
        de planification déguisée en contrainte.
        """
        if not self.ev_is_known:
            return None
        per_occurrence = self._value_per_occurrence
        if per_occurrence <= 0:
            return float("inf")
        return (self.j_min_per_second + self._costs_per_second) / per_occurrence

    def planning_frequency_if_ev_equals_meu(self) -> float:
        """Fréquence requise **si** l'espérance valait le plancher de matérialité.

        Valeur de planification, sans aucune autorité d'exclusion. Le nom porte
        l'hypothèse pour qu'elle ne puisse pas être lue comme une contrainte.
        """
        base = self.delta_meu * (
            1.0 if self.ev_basis is EvBasis.EV_PER_TRIGGER else self.fill_probability
        )
        return (self.j_min_per_second + self._costs_per_second) / base

    def necessary_frequency_from_ev_bound(self, ev_upper: float) -> float:
        """Fréquence nécessaire **quelle que soit** la qualité des trades.

            f_nécessaire = (J_min + C) / EV_U

        C'est la seule construction qui autorise une exclusion économique d'un moteur
        rare : elle exige une borne **supérieure** de l'espérance, cohérente avec `S_U`
        du perfect oracle. Sans elle, la rareté ne peut pas être opposée à la qualité.
        """
        if ev_upper <= 0:
            raise CampaignError("une borne supérieure d'espérance doit être positive")
        return (self.j_min_per_second + self._costs_per_second) / ev_upper

    def axes(self) -> "tuple[float | None, float]":
        """Les deux axes, **jamais fusionnés** en un seul plancher.

            viabilité économique   ←  f_econ_min
            validabilité statistique ←  f_stat_min

        Une stratégie peut être économiquement excellente et trop rare pour être validée
        avec l'historique disponible. Le verdict correct est alors
        `STATISTICALLY_INDETERMINATE`, jamais `ECONOMICALLY_NON_VIABLE` — et cette
        distinction protège précisément les stratégies rares mais fortes que le projet
        cherche à conserver.
        """
        return self.f_econ_min_per_second, self.f_stat_min_per_second

    #: Espérance nette par occurrence, avec sa **base** déclarée.
    expected_net_per_occurrence: float | None = None
    ev_basis: "EvBasis" = None  # type: ignore[assignment]
    fill_probability: float = 1.0
    fixed_cost_per_second: float = 0.0
    #: Coût d'opportunité du capital immobilisé — il court même sans position, et son
    #: absence rendait la relation calculée différente de la relation documentée.
    capital_opportunity_cost_per_second: float = 0.0

    @property
    def _costs_per_second(self) -> float:
        return self.fixed_cost_per_second + self.capital_opportunity_cost_per_second

    @property
    def ev_is_known(self) -> bool:
        return self.expected_net_per_occurrence is not None

    @property
    def _value_per_occurrence(self) -> float:
        """Contribution d'une occurrence, la probabilité d'exécution comptée **une fois**.

        Sous `EV_PER_TRIGGER` elle est déjà incluse dans l'espérance ; la remultiplier
        la compterait deux fois. Sous `EV_PER_FILLED_EXECUTION` elle doit être appliquée.
        C'est précisément pour empêcher ce double comptage que la base est typée.
        """
        if not self.ev_is_known:
            raise CampaignError(
                "δ_MEU ne remplace pas une espérance inconnue. C'est un **minimum pour "
                "accepter** un trade, pas un majorant de ce qu'il peut rapporter : un "
                "moteur rare dont les trades valent +2 R serait déclaré trop peu "
                "fréquent parce qu'on lui aurait prêté +0,10 R."
            )
        ev = self.expected_net_per_occurrence
        if self.ev_basis is EvBasis.EV_PER_TRIGGER:
            return ev
        return ev * self.fill_probability

    def implied_contribution_per_second(self, frequency_per_second: float) -> float:
        """`J(f) = f · valeur_par_occurrence − coûts_fixes − coût_du_capital`."""
        return frequency_per_second * self._value_per_occurrence - self._costs_per_second

    def frequency_verdict(self, observed_frequency: float) -> "FrequencyAxis":
        """Classe une fréquence sur les deux axes séparément."""
        econ, stat = self.axes()
        if econ is not None and observed_frequency < econ:
            return FrequencyAxis.ECONOMICALLY_NON_VIABLE
        if observed_frequency < stat:
            return FrequencyAxis.STATISTICALLY_INDETERMINATE
        return FrequencyAxis.ADEQUATE

    def redundancy_report(self) -> str | None:
        """Dit **laquelle** des grandeurs contraint réellement, via le modèle économique.

        La redondance ne se détecte pas à une proximité numérique : les trois quantités
        ont des unités et des rôles différents, et `f_min` en `1/s` ne se compare pas à
        `J_min` en `$/s`. Elle se dérive en demandant si `f_min` et `δ_MEU` ne font que
        reconstruire `J_min` par la relation économique.
        """
        if self.primary is not EconomicTarget.PER_UNIT_TIME:
            return None
        econ = self.f_econ_min_per_second
        if econ is None:
            return None
        # Évaluer à `f_econ_min` reconstruirait `J_min` par construction — c'est sa
        # définition. La question utile porte sur l'**autre** plancher : le plancher
        # statistique impose-t-il quelque chose de plus que la cible économique ?
        implied = self.implied_contribution_per_second(self.f_stat_min_per_second)
        if self.j_min_per_second <= 0:
            return None
        gap = abs(implied - self.j_min_per_second) / self.j_min_per_second
        if gap > 0.25:
            return (
                f"les trois grandeurs sont indépendantes : au plancher de fréquence "
                f"retenu, la relation économique implique "
                f"{implied * 86_400:.3f}/jour contre une cible de "
                f"{self.j_min_per_second * 86_400:.3f}/jour."
            )
        binding = (
            "f_stat_min" if self.f_stat_min_per_second >= econ
            else "la cible temporelle J_min"
        )
        return (
            f"f_min et δ_MEU reconstruisent J_min par la relation économique "
            f"(implique {implied * 86_400:.3f}/jour pour une cible de "
            f"{self.j_min_per_second * 86_400:.3f}/jour) : seule {binding} contraint "
            "réellement le verdict."
        )


# ------------------------------------------------- politique d'arrêt préenregistrée


@dataclass(frozen=True)
class StoppingPolicy:
    """Critères d'arrêt **déclarés avant** la première observation (ADR-176, ADR-182).

    Une politique écrite après avoir vu le résultat n'est pas une politique : c'est le
    résultat lui-même, reformulé. Le module refuse donc d'évaluer une campagne contre une
    politique postérieure à sa première mesure.

    Le mode d'inférence est déclaré au même moment, et il détermine ce qui a le droit de
    déclencher l'arrêt :

    - `FIXED_HORIZON` — la durée est gelée d'avance ; la largeur d'intervalle est un
      **diagnostic**, jamais un critère d'arrêt ;
    - `ANYTIME_VALID` — la séquence de confiance conserve sa couverture à tout instant,
      donc sa largeur peut légitimement décider de l'arrêt.
    """

    declared_at_ns: int
    declared_by: str
    min_days: int
    min_sessions: int
    min_clusters_per_cell: int
    min_burst_p95_clusters: int
    min_burst_p99_clusters: int
    max_relative_ci_width: float
    required_clock_qualification: str
    #: Q59-A — méthode d'inférence, déclarée avant la méthode et avant les valeurs.
    inference_mode: InferenceMode = InferenceMode.FIXED_HORIZON
    alpha: float = 0.05
    #: Réglage de la frontière séquentielle, obligatoire en ANYTIME_VALID.
    rho: float | None = None
    #: Horizon gelé, obligatoire en FIXED_HORIZON. L'unité est libre — journées,
    #: séances, grappes — mais la valeur est fixée avant la première observation.
    fixed_horizon_days: int | None = None
    fixed_horizon_clusters: int | None = None
    campaign_version: str = CAMPAIGN_VERSION

    def __post_init__(self) -> None:
        if not self.declared_by.strip():
            raise CampaignError(
                "Une politique d'arrêt sans auteur ne peut pas être opposée à quiconque."
            )
        if self.inference_mode is InferenceMode.ANYTIME_VALID and self.rho is None:
            raise CampaignError(
                "ANYTIME_VALID exige un ρ déclaré à l'avance : régler la frontière après "
                "coup reviendrait à l'ajuster contre les données qu'elle borne."
            )
        if self.inference_mode is InferenceMode.FIXED_HORIZON and not (
            self.fixed_horizon_days or self.fixed_horizon_clusters
        ):
            raise CampaignError(
                "FIXED_HORIZON exige une durée gelée avant la première observation. "
                "Sans elle, l'arrêt ne peut être que dépendant des données, et "
                "l'inférence conventionnelle perd sa garantie."
            )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                k: v for k, v in self.__dict__.items()
                if not k.startswith("_")
            },
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class StopDecision(str, Enum):
    CONTINUE = "CONTINUE"
    MAY_STOP = "MAY_STOP"
    POLICY_INVALID = "POLICY_INVALID"
    #: Arrêt dépendant des données sous inférence classique. Aucun résultat publiable.
    SEQUENTIAL_INFERENCE_INVALID = "SEQUENTIAL_INFERENCE_INVALID"


@dataclass(frozen=True)
class StopAssessment:
    decision: StopDecision
    reasons: tuple[str, ...]
    #: Vrai si la largeur d'intervalle a participé au déclenchement de l'arrêt.
    width_triggered: bool = False
    inference_mode: InferenceMode = InferenceMode.FIXED_HORIZON

    @property
    def publishable(self) -> bool:
        return self.decision in (StopDecision.CONTINUE, StopDecision.MAY_STOP)

    @property
    def confidence_interval_is_optimistic(self) -> bool:
        """Diagnostic historique, **conservé sans valeur de garde-fou**.

        Il indiquait qu'un arrêt déclenché par la largeur rendait l'intervalle optimiste.
        C'était une description trop faible : sous une règle d'arrêt lisant l'intervalle,
        un intervalle classique ne conserve pas sa couverture nominale — la garantie
        n'est pas optimiste, elle n'existe plus. La protection réelle est le mode
        d'inférence, qui rend `SEQUENTIAL_INFERENCE_INVALID` la combinaison fautive.
        """
        return self.decision is StopDecision.MAY_STOP and self.width_triggered


def assess_stopping(
    policy: StoppingPolicy,
    cover: CoverageReport,
    summaries: dict[CampaignCell, BoundSummary],
    first_observation_ns: int,
    clock: ClockCapability,
) -> StopAssessment:
    """Confronte la campagne à sa politique. Ne regarde **jamais** la valeur mesurée.

    Sous `FIXED_HORIZON`, seule la durée gelée peut autoriser l'arrêt : une largeur
    d'intervalle atteinte est un diagnostic, et prétendre s'en servir invalide
    l'inférence au lieu de la nuancer.
    """
    mode = policy.inference_mode
    if policy.declared_at_ns > first_observation_ns:
        return StopAssessment(
            StopDecision.POLICY_INVALID,
            (
                "politique déclarée après la première observation — elle ne peut plus "
                "être distinguée d'une justification a posteriori",
            ),
            inference_mode=mode,
        )
    if clock.qualification.value != policy.required_clock_qualification:
        return StopAssessment(
            StopDecision.POLICY_INVALID,
            (
                f"qualification d'horloge {clock.qualification.value} au lieu de "
                f"{policy.required_clock_qualification} : la campagne ne mesure pas ce "
                "que la politique suppose",
            ),
            inference_mode=mode,
        )

    missing: list[str] = []
    if cover.days_observed < policy.min_days:
        missing.append(f"{cover.days_observed} journées sur {policy.min_days}")
    if cover.sessions_observed < policy.min_sessions:
        missing.append(f"{cover.sessions_observed} sessions sur {policy.min_sessions}")
    if cover.burst_clusters_p95 < policy.min_burst_p95_clusters:
        missing.append(
            f"{cover.burst_clusters_p95} rafales P95 sur {policy.min_burst_p95_clusters}"
        )
    if cover.burst_clusters_p99 < policy.min_burst_p99_clusters:
        missing.append(
            f"{cover.burst_clusters_p99} rafales P99 sur {policy.min_burst_p99_clusters}"
        )
    thin = [
        c for c, s in summaries.items() if s.clusters < policy.min_clusters_per_cell
    ]
    if thin:
        missing.append(
            f"{len(thin)} cellules sous {policy.min_clusters_per_cell} grappes "
            f"(dont {thin[0].label})"
        )
    coverage_met = not missing

    wide = [
        c for c, s in summaries.items()
        if s.relative_ci_width > policy.max_relative_ci_width
    ]

    if mode is InferenceMode.FIXED_HORIZON:
        # La durée gelée est le **seul** critère d'arrêt. La largeur est publiée comme
        # diagnostic et ne peut ni retenir ni déclencher l'arrêt.
        total_clusters = sum(s.clusters for s in summaries.values())
        horizon_reached = (
            (policy.fixed_horizon_days is not None
             and cover.days_observed >= policy.fixed_horizon_days)
            or (policy.fixed_horizon_clusters is not None
                and total_clusters >= policy.fixed_horizon_clusters)
        )
        diagnostics = tuple(missing) + (
            (f"diagnostic seulement : {len(wide)} cellules à intervalle large",)
            if wide else ()
        )
        if not horizon_reached:
            return StopAssessment(
                StopDecision.CONTINUE,
                diagnostics or ("horizon gelé non atteint",),
                inference_mode=mode,
            )
        if missing:
            # L'horizon gelé est atteint mais la couverture minimale ne l'est pas :
            # prolonger serait un arrêt dépendant des données par l'autre bout.
            return StopAssessment(
                StopDecision.MAY_STOP,
                ("horizon gelé atteint ; couverture incomplète : ",) + tuple(missing),
                inference_mode=mode,
            )
        return StopAssessment(
            StopDecision.MAY_STOP,
            ("horizon gelé atteint",) + diagnostics,
            inference_mode=mode,
        )

    # ANYTIME_VALID — la largeur a le droit de décider, parce que la garantie de
    # couverture est simultanée dans le temps.
    if wide:
        missing.append(f"{len(wide)} cellules à séquence de confiance trop large")
    if missing:
        return StopAssessment(StopDecision.CONTINUE, tuple(missing), inference_mode=mode)
    return StopAssessment(
        StopDecision.MAY_STOP,
        ("couverture atteinte et séquence de confiance suffisamment étroite",),
        width_triggered=coverage_met,
        inference_mode=mode,
    )


def inference_validity(
    policy: StoppingPolicy, stopped_on_observed_uncertainty: bool
) -> InferenceValidity:
    """Verdict de validité d'un run terminé (ADR-181).

    Un run arrêté sur l'incertitude observée alors qu'il déclarait `FIXED_HORIZON` ne
    reçoit pas une réserve : il reçoit `SEQUENTIAL_INFERENCE_INVALID`. Il n'y a pas de
    chiffre à publier, seulement une procédure à refaire.
    """
    return validity(policy.inference_mode, stopped_on_observed_uncertainty)


# ------------------------------------------------------- stabilité séquentielle


@dataclass(frozen=True)
class DailySnapshot:
    day: str
    cumulative_clusters: int
    p95_ns: float
    ci_low_ns: float
    ci_high_ns: float


def stability_trace(
    observations: Sequence[PassiveObservation],
    rng: np.random.Generator | None = None,
) -> tuple[DailySnapshot, ...]:
    """Recalcule le p95 cumulé après chaque journée (§14).

    Le tracé sert à voir **si** l'estimation se stabilise. Il ne sert pas à choisir le
    moment d'arrêt : ce choix appartient à la politique préenregistrée.
    """
    usable = [o for o in observations if o.usable_for_local_distribution]
    days = sorted({o.day for o in usable})
    out: list[DailySnapshot] = []
    for i, day in enumerate(days):
        upto = [o for o in usable if o.day <= day]
        bounds = [o.local_lower_bound_ns for o in upto]
        clusters = [o.cluster_id for o in upto]
        lo, hi = _cluster_bootstrap_ci(bounds, clusters, 0.95, rng=rng)
        out.append(DailySnapshot(
            day=day,
            cumulative_clusters=len(set(clusters)),
            p95_ns=float(np.quantile(bounds, 0.95)),
            ci_low_ns=lo,
            ci_high_ns=hi,
        ))
        del i
    return tuple(out)


def is_stable(trace: Sequence[DailySnapshot], tolerance: float = 0.05, days: int = 3) -> bool:
    """Vrai si le p95 ne bouge plus au-delà de la tolérance sur les dernières journées."""
    if len(trace) < days + 1:
        return False
    recent = [s.p95_ns for s in trace[-(days + 1):]]
    base = recent[0]
    if base <= 0:
        return False
    return all(abs(p - base) / base <= tolerance for p in recent[1:])


# ---------------------------------------------------------------- les verdicts


class PassiveVerdict(str, Enum):
    #: La borne inférieure suffit à exclure l'horizon. Verdict négatif fort.
    PASSIVE_LATENCY_EXCLUDED = "PASSIVE_LATENCY_EXCLUDED"
    #: Compatible avec l'horizon. Ne démontre rien sur messagerie, ordre actif ou fill.
    PASSIVE_LATENCY_NOT_EXCLUDED = "PASSIVE_LATENCY_NOT_EXCLUDED"
    PASSIVE_LATENCY_INDETERMINATE = "PASSIVE_LATENCY_INDETERMINATE"
    #: Instrument ou horloge défaillants. Aucun verdict.
    PASSIVE_MEASUREMENT_INVALID = "PASSIVE_MEASUREMENT_INVALID"


@dataclass(frozen=True)
class AdmissibleLatency:
    """Q61-**B** — latence maximale admissible **propre à un moteur prédictif validé**.

    Elle dérive de `edge_j(L, h, c)`, donc de l'existence d'un signal ayant passé ses
    gates. Elle est spécifique au moteur, à l'horizon, à la cellule, au régime et au type
    d'ordre — et se fige dans le protocole du moteur avant son évaluation finale.

    **Elle ne bloque pas le premier verdict de la phase 0** (ADR-183, ADR-184). La phase 0
    doit précisément pouvoir éliminer des horizons avant qu'un signal existe : lui imposer
    un `Lmax` réintroduirait une croyance sur l'alpha dans un test conçu pour en être
    indépendant. Pour exclure sans signal, voir `oracle_exclusion()`.
    """

    horizon_ns: int
    max_admissible_ns: int
    source: str
    declared_at_ns: int
    #: Moteur auquel ce budget appartient. Un budget sans moteur serait un `Lmax` inventé.
    engine_id: str = ""
    gates_passed: bool = False

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                "Une latence admissible sans source déclarée ne peut pas être distinguée "
                "d'un seuil choisi après lecture du résultat."
            )
        if not self.engine_id.strip():
            raise CampaignError(
                "Un budget de latence admissible appartient à un moteur nommé. Sans lui, "
                "ce serait un Lmax inventé avant l'existence du signal qu'il suppose "
                "(ADR-184) — et une croyance sur l'alpha rentrerait dans un test conçu "
                "pour en être indépendant. Pour exclure sans signal : oracle_exclusion()."
            )
        if self.max_admissible_ns > self.horizon_ns:
            raise CampaignError(
                "Latence admissible supérieure à l'horizon : au moment où l'on pourrait "
                "agir, la fenêtre est déjà close."
            )


def passive_verdict(
    summary: BoundSummary,
    admissible: AdmissibleLatency,
    min_clusters: int,
    clock: ClockCapability | None = None,
    policy: StoppingPolicy | None = None,
    observations: Sequence[PassiveObservation] | None = None,
) -> tuple[PassiveVerdict, str]:
    """Verdict par cellule et par horizon, **contre un budget propre à un moteur** (Q61-B).

    L'asymétrie est celle de tout le projet : une borne **inférieure** déjà trop lente
    conclut, une borne assez rapide n'établit rien.

    Lorsque la politique déclare `ANYTIME_VALID` et que les observations sont fournies,
    l'exclusion s'appuie sur la **séquence de confiance** plutôt que sur l'intervalle par
    rééchantillonnage : c'est la seule construction dont la couverture survive à un arrêt
    décidé en regardant l'incertitude.
    """
    if clock is not None and not clock.local_usable:
        return (
            PassiveVerdict.PASSIVE_MEASUREMENT_INVALID,
            "horloge locale non qualifiée : aucune durée n'est mesurable",
        )
    if summary.cell.pipeline is PipelineMode.STRESS:
        return (
            PassiveVerdict.PASSIVE_MEASUREMENT_INVALID,
            "pile STRESS : sa charge est délibérément excessive et ne décrit aucune "
            "architecture envisagée (ADR-174)",
        )
    if summary.clusters < min_clusters:
        return (
            PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE,
            f"{summary.clusters} grappes indépendantes sur {min_clusters} requises",
        )

    if (
        policy is not None
        and policy.inference_mode is InferenceMode.ANYTIME_VALID
        and observations
    ):
        usable = [o for o in observations if o.usable_for_local_distribution]
        cs = interval_for_mode(
            InferenceMode.ANYTIME_VALID,
            [o.local_lower_bound_ns for o in usable],
            [o.cluster_id for o in usable],
            float(admissible.max_admissible_ns),
            policy.alpha,
            policy.rho,
        )
        verdict = threshold_verdict(cs, 0.95)
        if verdict is ThresholdVerdict.QUANTILE_ABOVE_THRESHOLD:
            return (
                PassiveVerdict.PASSIVE_LATENCY_EXCLUDED,
                f"séquence de confiance : F({format_ns(admissible.max_admissible_ns)}) ≤ "
                f"{cs.upper:.3f} < 0,95 sur {cs.n_clusters} grappes — la borne p95 dépasse "
                "l'admissible, garantie valide sous arrêt optionnel",
            )
        if verdict is ThresholdVerdict.QUANTILE_BELOW_THRESHOLD:
            return (
                PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
                f"séquence de confiance : F({format_ns(admissible.max_admissible_ns)}) ≥ "
                f"{cs.lower:.3f} > 0,95 — la partie courtier, non mesurée, peut encore "
                "exclure cet horizon",
            )
        return (
            PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE,
            f"séquence de confiance non séparée : F ∈ [{cs.lower:.3f} ; {cs.upper:.3f}] "
            f"encadre 0,95 après {cs.n_clusters} grappes",
        )

    # L'exclusion s'appuie sur la borne de confiance **basse** : si même l'estimation la
    # plus favorable de la borne inférieure dépasse l'admissible, la conclusion tient.
    favourable = summary.p95_ci_low if np.isfinite(summary.p95_ci_low) else summary.bound.p95
    if favourable >= admissible.max_admissible_ns:
        return (
            PassiveVerdict.PASSIVE_LATENCY_EXCLUDED,
            f"borne locale p95 ≥ {format_ns(int(favourable))} contre "
            f"{format_ns(admissible.max_admissible_ns)} admissibles à l'horizon "
            f"{format_ns(admissible.horizon_ns)} — courtier supposé instantané, "
            "aucune file, exécution immédiate",
        )
    return (
        PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED,
        f"borne locale p95 = {format_ns(int(summary.bound.p95))} sous "
        f"{format_ns(admissible.max_admissible_ns)} — la partie courtier, non mesurée, "
        "peut encore exclure cet horizon",
    )


def latency_budget_ns(summary: BoundSummary, admissible: AdmissibleLatency) -> int:
    """Budget de latence restant (§26, ADR-179).

    C'est ce que Q42 devra faire tenir dans le segment encore inconnu — émission, réseau,
    traitement courtier, file, activation, exécution. Une valeur négative signifie que
    l'horizon est déjà exclu sans mesurer quoi que ce soit du courtier.
    """
    return int(admissible.max_admissible_ns - summary.bound.p95)


# ------------------------------------ Q61-A — borne oracle, indépendante de tout signal


class ConstraintClass(str, Enum):
    """Origine d'une contrainte imposée à l'oracle.

    La distinction décide de ce qu'une exclusion signifie. Un `cooldown` choisi
    arbitrairement réduit `V_oracle_max` et peut **fabriquer** une exclusion : elle
    porterait alors sur notre architecture, pas sur le marché.
    """

    #: Impossible à contourner : horaires, prix réellement cotés, latence déjà subie,
    #: capital réel, contraintes du courtier, taille de contrat.
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    #: Décision d'architecture : un seul trade simultané, cooldown, type d'ordre
    #: autorisé, risque maximal, séances retenues.
    POLICY_CONSTRAINT = "POLICY_CONSTRAINT"


class OracleKind(str, Enum):
    """Deux oracles, deux questions. Ils ne se confondent jamais."""

    #: Seules les contraintes incontournables. Borne la plus favorable — c'est elle qui
    #: doit servir à prétendre éliminer *tout moteur possible*.
    PHYSICAL_ORACLE = "PHYSICAL_ORACLE"
    #: Ajoute les décisions d'architecture. Répond : « notre système tel que nous avons
    #: décidé de le construire est-il viable ? »
    POLICY_ORACLE = "POLICY_ORACLE"


class OverlapPolicy(str, Enum):
    """Comment les opportunités se disputent le même mouvement.

    Interdit de traiter chaque tick comme une opportunité indépendante puis de sommer
    les profits oracle : un seul mouvement peut produire 500 horodatages, 500 fenêtres
    et 500 « opportunités » alors qu'un système réel n'aurait pris qu'une position.
    """

    #: Aucune nouvelle opportunité tant que la fenêtre précédente est active.
    DISJOINT_WINDOWS = "DISJOINT_WINDOWS"
    #: Toutes les opportunités existent, mais l'oracle doit choisir un sous-ensemble
    #: compatible avec concurrence, capital, cooldown et capacité d'ordres.
    CAPACITY_CONSTRAINED_ORACLE = "CAPACITY_CONSTRAINED_ORACLE"


@dataclass(frozen=True)
class OpportunitySet:
    """Ensemble d'opportunités admissibles, sous contraintes déclarées."""

    starts_ns: np.ndarray
    horizon_ns: int
    span_ns: int
    cooldown_ns: int = 0
    max_concurrent_positions: int = 1
    overlap_policy: OverlapPolicy = OverlapPolicy.DISJOINT_WINDOWS
    session: str = ""
    cell_label: str = ""
    #: Origine du cooldown. Un cooldown de politique ne doit pas entrer dans la borne
    #: physique : il y fabriquerait une exclusion imputable à notre propre architecture.
    cooldown_class: ConstraintClass = ConstraintClass.POLICY_CONSTRAINT
    #: Origine de la limite de concurrence.
    concurrency_class: ConstraintClass = ConstraintClass.POLICY_CONSTRAINT

    @property
    def kind(self) -> OracleKind:
        policy = ConstraintClass.POLICY_CONSTRAINT
        has_policy = (
            (self.cooldown_ns > 0 and self.cooldown_class is policy)
            or (self.max_concurrent_positions < 2**31 and self.concurrency_class is policy)
        )
        return OracleKind.POLICY_ORACLE if has_policy else OracleKind.PHYSICAL_ORACLE

    def physical_view(self) -> "OpportunitySet":
        """Même ensemble, contraintes de politique retirées.

        C'est la borne à employer pour prétendre éliminer *tout moteur possible* :
        conserver un cooldown arbitraire y ferait passer une décision d'architecture pour
        une limite du marché.
        """
        policy = ConstraintClass.POLICY_CONSTRAINT
        return replace(
            self,
            cooldown_ns=0 if self.cooldown_class is policy else self.cooldown_ns,
            max_concurrent_positions=(
                2**31 if self.concurrency_class is policy
                else self.max_concurrent_positions
            ),
        )

    def __post_init__(self) -> None:
        if self.max_concurrent_positions < 1:
            raise CampaignError("au moins une position simultanée est nécessaire")
        if self.span_ns <= 0:
            raise CampaignError("la durée d'observation doit être positive")

    @property
    def occupancy_ns(self) -> int:
        """Temps qu'une position immobilise : sa fenêtre plus son délai de réarmement."""
        return self.horizon_ns + self.cooldown_ns

    @property
    def capacity(self) -> int:
        """Nombre **maximal** de positions que l'oracle peut prendre sur la période.

        Aucune sélection ne peut dépasser ce plafond : c'est ce qui empêche de compter
        plusieurs fois le même mouvement.
        """
        return max(1, self.max_concurrent_positions * int(self.span_ns // self.occupancy_ns))

    def admissible(self) -> np.ndarray:
        """Opportunités **économiquement admissibles** — sans jamais voir le futur.

        Répond à : *quelles décisions auraient physiquement pu être envisagées ?* Le
        dénominateur de toute fréquence vient d'ici. Le faire dépendre du surplus
        rendrait la sélection outcome-dependent : on choisirait les observations d'après
        ce qu'elles rapportent, puis on diviserait par leur nombre.
        """
        if self.overlap_policy is OverlapPolicy.CAPACITY_CONSTRAINED_ORACLE:
            return np.arange(self.starts_ns.size, dtype=int)

        # Sélection d'activités classique : la fenêtre qui se libère le plus tôt, sans
        # aucune référence à sa valeur. Maximise le nombre de créneaux disjoints.
        order = np.argsort(self.starts_ns, kind="stable")
        kept: list[int] = []
        free_at = -(2**62)
        for i in order:
            if self.starts_ns[i] >= free_at:
                kept.append(int(i))
                free_at = self.starts_ns[i] + self.occupancy_ns
        return np.array(sorted(kept), dtype=int)

    def concurrency_respected(self, chosen: np.ndarray) -> bool:
        """Vérifie `∀t : N_ouvertes(t) ≤ K` — à tout instant, pas en moyenne.

        Un plafond global sur le nombre total n'est pas une contrainte de concurrence :
        dix positions simultanées peuvent respecter un total de dix et violer une limite
        de deux.
        """
        if chosen.size == 0:
            return True
        starts = np.sort(self.starts_ns[chosen])
        ends = np.sort(self.starts_ns[chosen] + self.occupancy_ns)
        i = j = open_now = 0
        while i < starts.size:
            if starts[i] < ends[j]:
                open_now += 1
                if open_now > self.max_concurrent_positions:
                    return False
                i += 1
            else:
                open_now -= 1
                j += 1
        return True

    def value_upper_bound(self, surplus: np.ndarray, threshold: float = 0.0) -> float:
        """Majorant de la valeur oracle sous contrainte de capacité.

        C'est une **relaxation**, revendiquée comme telle : l'ensemble des `m` plus gros
        surplus peut violer la concurrence instantanée, mais toute planification faisable
        contient au plus `m` positions, donc sa valeur est au plus la somme des `m` plus
        gros. Un majorant qui relâche une contrainte reste un majorant — au contraire
        d'une planification gloutonne, qui minorerait et ferait sur-exclure.
        """
        eligible = surplus[surplus > threshold]
        if eligible.size == 0:
            return 0.0
        top = np.sort(eligible)[::-1][: self.capacity]
        return float(top.sum())

    def profitable_count_upper_bound(self, surplus: np.ndarray, threshold: float) -> int:
        """Majorant du nombre d'opportunités rentables qu'un oracle pourrait retenir.

        Calculé sur l'**univers complet des candidats**, borné par la capacité :

            N_U = min( N_capacité , N_rentables_brutes )

        Il peut surestimer ce que l'oracle prendrait réellement — c'est exactement ce
        qu'on veut pour une exclusion. Le calculer sur une planification particulière
        sous-estimerait, et ferait sur-exclure.
        """
        return int(min(self.capacity, int((surplus > threshold).sum())))

    def opportunity_rate_upper_bound(self, span_ns: int) -> float:
        """Cadence maximale d'opportunités compatibles, par seconde.

        Ne dépend d'aucune planification retenue : `λ_opp` doit rester favorable à
        l'oracle, sinon `λ·p_U·S_U` sous-estimerait et pourrait fabriquer une exclusion.
        """
        if span_ns <= 0:
            return float("nan")
        return self.capacity / (span_ns / NS_PER_SECOND)


# ------------------------------------------------------------- Q63 — coût plancher


class OrderType(str, Enum):
    AGGRESSIVE = "AGGRESSIVE"
    PASSIVE = "PASSIVE"


def most_favourable_floor(floors: Sequence["CostFloor"]) -> "CostFloor":
    """Plancher le plus bas parmi les modes d'exécution **autorisés** (ADR-205).

        C_floor^any = inf { C_floor(o) : o ∈ O_autorisés }

    Une conclusion prétendant éliminer tout moteur possible doit laisser à l'oracle le
    choix de l'exécution la plus favorable. Sinon on éliminerait une famille parce que
    les ordres au marché coûtent trop cher, alors qu'une exécution passive compatible
    resterait viable.
    """
    if not floors:
        raise CampaignError("aucun mode d'exécution autorisé n'a été déclaré")
    units = {f.unit for f in floors}
    if len(units) != 1:
        raise CampaignError(
            f"planchers exprimés dans {len(units)} unités différentes : les comparer "
            "exigerait une conversion contractuelle explicite."
        )
    return min(floors, key=lambda f: f.value)


@dataclass(frozen=True)
class CostFloor:
    """Q63 — borne **inférieure** du coût réellement inévitable (ADR-192).

    Ce n'est ni le coût central estimé, ni le coût prudent. Pour que l'exclusion tienne,
    `C_réel ≥ C_floor` doit être défendable — donc mieux vaut sous-estimer les coûts que
    les surestimer.

    Les crédits sont **signés** : un swap ou une remise favorable rend un composant
    négatif, et le plancher doit retenir la convention la plus favorable compatible avec
    la cellule. Transformer un crédit possible en coût positif pour faciliter une
    exclusion est interdit.
    """

    order_type: OrderType
    #: Commission certaine, contractuellement connue.
    certain_commission: float
    #: Frais obligatoires incontournables.
    mandatory_fees: float
    #: Franchissement déjà nécessaire et observé. **Interdit pour un ordre passif** :
    #: celui-ci peut obtenir un prix différent du scénario agressif.
    observed_crossing: float = 0.0
    #: Financement inévitable si l'horizon traverse la frontière. Signé.
    unavoidable_financing: float = 0.0
    #: Crédits signés — remises, swaps favorables. Négatifs par convention.
    signed_credits: float = 0.0
    unit: str = "USD/oz"
    source: str = ""
    estimated_components_use_lower_bound: bool = True

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                "Un plancher de coûts sans source déclarée ne peut pas être distingué "
                "d'une valeur choisie pour obtenir l'exclusion souhaitée."
            )
        if self.order_type is OrderType.PASSIVE and self.observed_crossing > 0.0:
            raise CampaignError(
                "Le franchissement ne peut pas entrer dans le plancher d'un ordre "
                "passif : celui-ci peut obtenir un prix différent du scénario agressif. "
                "Son plancher se limite aux frais réellement certains."
            )
        if not self.estimated_components_use_lower_bound:
            raise CampaignError(
                "Un composant estimé entre dans le plancher par sa borne inférieure, "
                "jamais par son estimation centrale : pour une exclusion "
                "signal-agnostique, sous-estimer les coûts est le sens conservateur."
            )

    @property
    def value(self) -> float:
        return (
            self.certain_commission + self.mandatory_fees + self.observed_crossing
            + self.unavoidable_financing + self.signed_credits
        )


# -------------------------------------------------------- capture et surplus oracle


@dataclass(frozen=True)
class OracleCapture:
    """`G_i^oracle` — capture brute maximale après latence, par opportunité.

    Construite en offrant au système la direction parfaite, la meilleure sortie de la
    fenêtre et aucune erreur prédictive. Elle conserve en revanche les contraintes
    qu'aucun oracle ne peut contourner : latence déjà subie, prix réellement disponibles,
    horizon, capacité — sans quoi elle cesserait d'être une borne supérieure **du système
    étudié**.
    """

    starts_ns: np.ndarray
    gross: np.ndarray
    horizon_ns: int
    scope: CapturabilityScope
    span_ns: int
    clusters: int
    exhausted_fraction: float
    #: Épisode d'appartenance de chaque opportunité. Sans lui, aucune statistique ne peut
    #: être calculée dans l'unité « épisode » qu'une borne robuste revendique.
    episode_ids: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))

    @property
    def quantiles(self) -> Quantiles:
        """Diagnostics. Un quantile seul n'exclut jamais rien (ADR-189)."""
        return Quantiles.of(self.gross.tolist())


def oracle_capturable(
    timestamps_ns: np.ndarray,
    prices: np.ndarray,
    event_starts: np.ndarray,
    latency_samples_ns: np.ndarray,
    horizon_ns: int,
    scope: CapturabilityScope,
    cluster_ids: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
) -> OracleCapture:
    """Excursion favorable maximale atteignable **après** avoir attendu la latence.

    Si `L ≥ h`, la capture vaut zéro et l'opportunité **reste dans l'échantillon** : la
    retirer ne conserverait que les cas où l'on avait eu le temps d'agir (ADR-159).
    """
    rng = rng or np.random.default_rng(0)
    if event_starts.size == 0 or latency_samples_ns.size == 0:
        return OracleCapture(np.array([], dtype=np.int64), np.array([]), horizon_ns,
                             scope, 0, 0, float("nan"))

    drawn = rng.choice(latency_samples_ns, size=event_starts.size, replace=True)
    gross: list[float] = []
    exhausted = 0

    for start, lat in zip(event_starts, drawn):
        t0 = timestamps_ns[start]
        if lat >= horizon_ns:
            gross.append(0.0)
            exhausted += 1
            continue
        i_act = int(np.searchsorted(timestamps_ns, t0 + int(lat), side="left"))
        i_end = int(np.searchsorted(timestamps_ns, t0 + horizon_ns, side="right"))
        if i_act >= i_end or i_act >= prices.size:
            gross.append(0.0)
            exhausted += 1
            continue
        window = prices[i_act:i_end]
        entry = prices[i_act]
        gross.append(float(max(window.max() - entry, entry - window.min())))

    episodes = (
        cluster_ids[event_starts] if cluster_ids is not None
        else np.arange(len(gross), dtype=np.int64)
    )
    clusters = int(np.unique(episodes).size)
    span = int(timestamps_ns[-1] - timestamps_ns[0]) if timestamps_ns.size > 1 else 0
    return OracleCapture(
        starts_ns=timestamps_ns[event_starts],
        gross=np.asarray(gross, dtype=float),
        horizon_ns=horizon_ns,
        scope=scope,
        span_ns=span,
        clusters=clusters,
        exhausted_fraction=exhausted / len(gross),
        episode_ids=np.asarray(episodes, dtype=np.int64),
    )


def clopper_pearson_upper(successes: int, trials: int, alpha: float) -> float:
    """Borne supérieure exacte du taux — indispensable pour exclure prudemment.

    Sans elle, « aucune opportunité rentable observée » se lirait comme « le taux est
    nul », alors qu'il n'est que **borné**. Avec zéro succès sur `n` tirages, la borne
    vaut `1 − α^(1/n)` : elle ne descend jamais à zéro.
    """
    if trials <= 0:
        return 1.0
    if successes >= trials:
        return 1.0
    if successes == 0:
        return 1.0 - alpha ** (1.0 / trials)
    if successes > 4_000:
        # Repli conservateur : Hoeffding, valide sans limite de taille.
        return min(1.0, successes / trials + math.sqrt(math.log(1.0 / alpha) / (2 * trials)))

    def cdf(p: float) -> float:
        return sum(
            math.comb(trials, i) * p**i * (1.0 - p) ** (trials - i)
            for i in range(successes + 1)
        )

    lo, hi = successes / trials, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


@dataclass(frozen=True)
class OracleAssessment:
    """Ce que le perfect oracle pourrait extraire, sous contraintes."""

    opportunities: int
    selected: int
    profitable: int
    profitable_rate: float
    profitable_rate_upper: float
    #: Fréquence maximale d'opportunités oracle-rentables, par seconde.
    profitable_frequency: float
    profitable_frequency_upper: float
    max_surplus: float
    #: Capacité **brute** : tout surplus positif. Diagnostic scientifique.
    raw_capacity_value_per_second: float
    #: Capacité **économiquement admissible** : seuls les surplus au-dessus de δ_MEU.
    #: C'est elle, et elle seule, qui se relie à Q1 et Q64 — un système ne doit pas
    #: pouvoir atteindre `J_min` avec des trades que le plancher de matérialité interdit
    #: individuellement.
    capacity_value_per_second: float
    capacity: int
    cost_floor: float
    delta_meu: float
    quantiles: Quantiles
    clusters: int
    rarity: RarityBound
    kind: OracleKind
    opportunity_rate_per_second: float = float("nan")

    def capacity_ceiling_per_second(
        self, surplus_bound: "SurplusUpperBound | None"
    ) -> float | None:
        """`λ_opp · p_U · S_U` — plafond de ce que l'oracle pourrait extraire.

        Ne se calcule qu'avec une borne de gain déclarée et une borne de taux qui
        revendique quelque chose sur la population : sans l'une ou l'autre, la queue non
        observée reste sans majorant.
        """
        if surplus_bound is None or not self.rarity.is_population_claim:
            return None
        if not math.isfinite(self.opportunity_rate_per_second):
            return None
        return (
            self.opportunity_rate_per_second * self.rarity.upper * surplus_bound.value
        )


def assess_oracle(
    capture: OracleCapture,
    cost_floor: CostFloor,
    opportunities: OpportunitySet,
    delta_meu: float,
    alpha: float = 0.05,
    independence_proven: bool = False,
    estimator: DependenceBoundEstimator | None = None,
) -> OracleAssessment:
    """Surplus, fréquence et capacité économique de l'oracle (§3-4).

        S_i = G_i − C_floor        I_i = 1[ S_i > δ_MEU ]

    Toutes les grandeurs passent par la sélection sous contraintes : sans elle, un seul
    mouvement compterait autant de fois qu'il a produit d'horodatages.
    """
    surplus = capture.gross - cost_floor.value
    # L'ensemble admissible ne regarde jamais le surplus : c'est lui qui fournit le
    # dénominateur, et le faire dépendre du futur rendrait la fréquence circulaire.
    selected = opportunities.admissible()
    kept = surplus[selected] if selected.size else np.array([])

    profitable_flags = kept > delta_meu
    # Majorant sur l'**univers des candidats**, pas sur la planification retenue. Une
    # planification outcome-independent peut garder une fenêtre à −1 R et écarter la
    # fenêtre chevauchante à +4 R : compter les rentables sur elle **sous-estimerait**
    # ce qu'un oracle pourrait choisir, et sous-estimer est le mauvais sens pour exclure.
    profitable = opportunities.profitable_count_upper_bound(surplus, delta_meu)
    n = int(selected.size)
    rate = profitable / n if n else 0.0
    bound = rarity_bound(
        profitable_flags.astype(float),
        capture.episode_ids[selected] if capture.episode_ids.size else np.array([]),
        alpha, independence_proven, estimator,
        starts_ns=capture.starts_ns[selected] if capture.starts_ns.size else None,
    )

    span_s = capture.span_ns / NS_PER_SECOND if capture.span_ns else float("nan")
    frequency = profitable / span_s if span_s and span_s > 0 else float("nan")
    # La borne de fréquence se porte sur la cadence d'opportunités : λ_rentable,U =
    # p_U × λ_opp. Sous dépendance, p_U vient des épisodes, pas des opportunités brutes.
    frequency_upper = (
        bound.upper * n / span_s if span_s and span_s > 0 else float("nan")
    )

    raw_value = opportunities.value_upper_bound(surplus, threshold=0.0)
    admissible_value = opportunities.value_upper_bound(surplus, threshold=delta_meu)
    return OracleAssessment(
        opportunities=int(capture.gross.size),
        selected=n,
        profitable=profitable,
        profitable_rate=rate,
        profitable_rate_upper=bound.upper,
        profitable_frequency=frequency,
        profitable_frequency_upper=frequency_upper,
        max_surplus=float(surplus.max()) if surplus.size else float("nan"),
        raw_capacity_value_per_second=(
            raw_value / span_s if span_s and span_s > 0 else float("nan")),
        capacity_value_per_second=(
            admissible_value / span_s if span_s and span_s > 0 else float("nan")),
        capacity=opportunities.capacity,
        cost_floor=cost_floor.value,
        delta_meu=delta_meu,
        quantiles=capture.quantiles,
        clusters=capture.clusters,
        rarity=bound,
        kind=opportunities.kind,
        opportunity_rate_per_second=opportunities.opportunity_rate_upper_bound(
            capture.span_ns
        ),
    )


@dataclass(frozen=True)
class DependenceMethod:
    """**Provenance** d'une méthode de dépendance — métadonnée, pas calcul.

    Elle documente ce qui a été exécuté. Elle ne l'exécute pas, et ne suffit donc jamais
    à obtenir `DEPENDENCE_ROBUST_BOUND` :

        métadonnée de méthode  ≠  méthode exécutée
    """

    name: str
    dependence_argument: str
    parameter: str
    reference: str

    def __post_init__(self) -> None:
        for field_name in ("name", "dependence_argument", "parameter", "reference"):
            if not getattr(self, field_name).strip():
                raise CampaignError(
                    f"Une méthode de dépendance sans {field_name} n'en est pas une : "
                    "elle rendrait à nouveau une hypothèse de Bernoulli implicite."
                )


class DependenceBoundEstimator(Protocol):
    """Estimateur qui **calcule** réellement une borne sous dépendance."""

    version: str

    def describe(self) -> DependenceMethod: ...

    def upper_bound(self, episode_successes: np.ndarray, alpha: float) -> float:
        """Borne supérieure du taux d'épisodes porteurs, sous la dépendance traitée."""
        ...


@dataclass(frozen=True)
class MovingBlockBootstrapBound:
    """Bootstrap par blocs mobiles sur la série **ordonnée** d'indicateurs d'épisode.

    Rééchantillonner des blocs de `block_length` épisodes consécutifs conserve la
    dépendance à l'intérieur du bloc, au lieu de la supposer absente. La borne est le
    quantile `1 − α` des taux rééchantillonnés — plus large qu'un intervalle de Bernoulli
    dès que la dépendance est réelle, ce qui est exactement l'effet recherché.

    La longueur de bloc doit dépasser la persistance mesurée ; elle est déclarée, pas
    ajustée après lecture du résultat.
    """

    block_length: int
    dependence_argument: str
    reference: str
    draws: int = 2_000
    seed: int = 0
    version: str = "MBB_1.0"
    #: Référence de la campagne de calibration ayant **vérifié la couverture** sous les
    #: dépendances revendiquées. Vide tant qu'elle n'a pas été menée : la borne reste
    #: alors modélisée, sans autorité normative.
    coverage_qualification: str = ""

    def __post_init__(self) -> None:
        if self.block_length < 1:
            raise CampaignError("la longueur de bloc doit être au moins 1")
        if not self.dependence_argument.strip() or not self.reference.strip():
            raise CampaignError(
                "Un estimateur sans argument de dépendance ni référence redevient une "
                "hypothèse implicite."
            )

    def describe(self) -> DependenceMethod:
        return DependenceMethod(
            name="bootstrap par blocs mobiles",
            dependence_argument=self.dependence_argument,
            parameter=f"longueur de bloc {self.block_length} épisodes",
            reference=self.reference,
        )

    @property
    def coverage_qualified(self) -> bool:
        return bool(self.coverage_qualification.strip())

    def upper_bound(self, episode_successes: np.ndarray, alpha: float) -> float:
        n = episode_successes.size
        if n < 2:
            return 1.0
        b = min(self.block_length, n)
        rng = np.random.default_rng(self.seed)
        n_blocks = int(np.ceil(n / b))
        starts = rng.integers(0, n - b + 1, size=(self.draws, n_blocks))
        offsets = np.arange(b)
        idx = (starts[:, :, None] + offsets[None, None, :]).reshape(self.draws, -1)[:, :n]
        rates = episode_successes[idx].mean(axis=1)
        # Le quantile bootstrap seul s'effondre à zéro lorsque aucun succès n'apparaît.
        # Le plancher retenu est celui de la règle de trois sur le nombre de blocs — il
        # n'est pas présenté comme exact : `n_blocks` n'est pas un nombre d'essais de
        # Bernoulli indépendants, et c'est précisément pourquoi la borne reste
        # `DEPENDENCE_MODELLED_BOUND` tant que sa couverture n'est pas vérifiée.
        floor = clopper_pearson_upper(int(episode_successes.sum()), n_blocks, alpha)
        return float(max(np.quantile(rates, 1.0 - alpha), floor))


class BoundQuality(str, Enum):
    """Ce qu'une borne de rareté vaut réellement.

    `disjoint ≠ indépendant`, et `regroupé ≠ indépendant` non plus.
    """

    #: Calculée sur le nombre brut d'opportunités. **Diagnostic seulement.**
    RAW_EVENT_BOUND = "RAW_EVENT_BOUND"
    #: Comptage au niveau des épisodes, sans estimateur traitant la dépendance. C'est une
    #: **observation**, pas une borne sur la population future.
    EPISODE_OBSERVATION = "EPISODE_OBSERVATION"
    #: Hypothèses de Bernoulli réellement défendables.
    QUALIFIED_INDEPENDENT_BOUND = "QUALIFIED_INDEPENDENT_BOUND"
    #: Estimateur **exécuté**, mais dont la couverture n'est pas encore qualifiée. Le
    #: fait qu'une borne s'élargisse sous dépendance montre qu'elle y réagit — pas
    #: qu'elle atteint le niveau de confiance annoncé.
    DEPENDENCE_MODELLED_BOUND = "DEPENDENCE_MODELLED_BOUND"
    #: Estimateur exécuté **et** couverture qualifiée sous les hypothèses revendiquées.
    DEPENDENCE_ROBUST_BOUND = "DEPENDENCE_ROBUST_BOUND"

    @property
    def claims_population(self) -> bool:
        """`DEPENDENCE_MODELLED_BOUND` n'y figure pas : réagir à la dépendance ne
        démontre pas `P(p ≤ p_U) ≥ 1 − α`."""
        return self in (
            BoundQuality.QUALIFIED_INDEPENDENT_BOUND,
            BoundQuality.DEPENDENCE_ROBUST_BOUND,
        )

    @property
    def usable_for_verdict(self) -> bool:
        return self.claims_population


@dataclass(frozen=True)
class RarityBound:
    """Taux d'opportunités oracle-rentables : ce qui est observé, et ce qui est borné."""

    upper: float
    quality: BoundQuality
    trials: int
    successes: int
    alpha: float
    rationale: str = ""
    method: DependenceMethod | None = None
    estimator_version: str = ""

    @property
    def is_population_claim(self) -> bool:
        return self.quality.claims_population

    def describe(self) -> str:
        if self.quality is BoundQuality.DEPENDENCE_MODELLED_BOUND:
            return (
                f"taux modélisé ≤ {self.upper:.2%} ({self.trials} épisodes, "
                f"{self.estimator_version}) — couverture non qualifiée, sans autorité "
                "normative"
            )
        if self.is_population_claim:
            return (
                f"taux ≤ {self.upper:.2%} ({self.quality.value}, {self.trials} unités"
                + (f", {self.estimator_version}" if self.estimator_version else "") + ")"
            )
        return (
            f"{self.successes} porteur(s) sur {self.trials} épisodes observés — "
            "observation, sans borne sur la population future"
        )


def episode_successes(
    episode_ids: np.ndarray,
    profitable: np.ndarray,
    starts_ns: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """Indicateur **par épisode**, dans l'ordre **temporel**.

        Y_g = 1[ ∃ i ∈ g : S_i > δ_MEU ]

    Deux exigences, et la seconde est facile à manquer.

    Sept opportunités rentables peuvent appartenir au même épisode : le comptage se fait
    dans l'unité que la borne revendique, jamais par `min(succès, épisodes)`.

    Et un bootstrap par blocs suppose que l'ordre des observations est leur ordre
    **temporel** — or le nom d'un épisode n'est pas son instant. Trier par identifiant
    produirait une chronologie fictive : la série `0 1 2 … 39 0 1 2 …` regrouperait tous
    les « 0 » d'une campagne entière dans un même prétendu épisode.

    Un épisode est donc un **segment contigu** : une séquence `A B A` est refusée.
    """
    if episode_ids.size == 0:
        return np.array([], dtype=float), 0

    if starts_ns is not None:
        order = np.argsort(starts_ns, kind="stable")
    else:
        order = np.arange(episode_ids.size)
    ids, flags = episode_ids[order], profitable[order]

    boundaries = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    segments = ids[boundaries]
    if np.unique(segments).size != segments.size:
        offender = [int(x) for x in segments[:6]]
        raise CampaignError(
            f"Un épisode réapparaît après avoir été clos : {offender}… Un épisode doit "
            "être un segment temporel contigu — sans quoi la série transmise à une "
            "méthode de dépendance n'est pas une chronologie."
        )

    ends = list(boundaries[1:]) + [ids.size]
    carried = np.array(
        [bool(flags[a:b].any()) for a, b in zip(boundaries, ends)], dtype=float
    )
    return carried, segments.size


def rarity_bound(
    profitable: np.ndarray,
    episode_ids: np.ndarray,
    alpha: float,
    independence_proven: bool = False,
    estimator: DependenceBoundEstimator | None = None,
    starts_ns: np.ndarray | None = None,
) -> RarityBound:
    """Borne de rareté, dégradée selon ce qui est **réellement exécuté**.

    Trois marches, et une seule sépare l'observation de la revendication :

    - indépendance démontrée → Clopper-Pearson sur les opportunités ;
    - estimateur de dépendance **exécuté** → sa borne, sur les épisodes ;
    - ni l'une ni l'autre → observation d'épisodes, publiée telle quelle.
    """
    n_opp = int(profitable.size)
    k_opp = int(profitable.sum())

    if independence_proven:
        return RarityBound(
            clopper_pearson_upper(k_opp, n_opp, alpha),
            BoundQuality.QUALIFIED_INDEPENDENT_BOUND, n_opp, k_opp, alpha,
            "indépendance des opportunités démontrée",
        )

    carried, n_episodes = episode_successes(episode_ids, profitable, starts_ns)
    k_episodes = int(carried.sum())

    if estimator is not None and n_episodes >= 2:
        method = estimator.describe()
        qualified = getattr(estimator, "coverage_qualified", False)
        return RarityBound(
            estimator.upper_bound(carried, alpha),
            BoundQuality.DEPENDENCE_ROBUST_BOUND if qualified
            else BoundQuality.DEPENDENCE_MODELLED_BOUND,
            n_episodes, k_episodes, alpha,
            f"dépendance traitée par {method.name} ({method.parameter})"
            + ("" if qualified else " — couverture non encore qualifiée"),
            method, estimator.version,
        )
    if n_episodes >= 2:
        return RarityBound(
            clopper_pearson_upper(k_episodes, n_episodes, alpha),
            BoundQuality.EPISODE_OBSERVATION, n_episodes, k_episodes, alpha,
            "épisodes possiblement liés par journée, régime, macro ou charge — "
            "aucun estimateur de dépendance exécuté",
        )
    return RarityBound(
        clopper_pearson_upper(k_opp, n_opp, alpha),
        BoundQuality.RAW_EVENT_BOUND, n_opp, k_opp, alpha,
        "aucun épisode identifié — diagnostic seulement",
    )


class BoundDerivationType(str, Enum):
    """Comment la borne supérieure du surplus oracle est obtenue."""

    #: L'horizon est inférieur à la latence minimale certaine : rien n'est capturable.
    HORIZON_BELOW_MINIMUM_LATENCY = "HORIZON_BELOW_MINIMUM_LATENCY"
    #: Déplacement maximal possible sur l'horizon résiduel, moins le plancher de coûts.
    MAX_DISPLACEMENT_MINUS_FLOOR = "MAX_DISPLACEMENT_MINUS_FLOOR"
    #: Limite contractuelle rendant l'opération impossible.
    CONTRACTUAL_LIMIT = "CONTRACTUAL_LIMIT"


@dataclass(frozen=True)
class BoundInput:
    """Une entrée nommée de la dérivation, avec sa provenance."""

    name: str
    value: float
    unit: str
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                f"L'entrée « {self.name} » n'a pas de provenance : la dérivation ne "
                "serait pas vérifiable."
            )


@dataclass(frozen=True)
class BoundDerivation:
    """Dérivation **exécutable** de la borne supérieure du surplus oracle.

    Le calcul est refait à partir des entrées déclarées, de sorte qu'un appelant ne peut
    pas se contenter d'affirmer un chiffre favorable accompagné d'une documentation
    convaincante.
    """

    derivation_type: BoundDerivationType
    inputs: tuple[BoundInput, ...]
    calculator_version: str

    def _input(self, name: str) -> BoundInput:
        for i in self.inputs:
            if i.name == name:
                return i
        raise CampaignError(
            f"La dérivation {self.derivation_type.value} exige une entrée « {name} »."
        )

    def _get(self, name: str) -> float:
        return self._input(name).value

    def _same_unit(self, *names: str) -> str:
        """Refuse `0,40 USD/oz − 30 USD/lot`.

        Le résultat numérique existerait et n'aurait aucun sens physique. Une borne
        d'exclusion issue d'une soustraction entre unités incompatibles est un chiffre
        arbitraire habillé en démonstration.
        """
        units = {self._input(n).unit for n in names}
        if len(units) != 1:
            raise CampaignError(
                f"Unités incompatibles dans {self.derivation_type.value} : "
                f"{sorted(units)}. Une conversion contractuelle explicite est requise."
            )
        return units.pop()

    @property
    def unit(self) -> str:
        t = self.derivation_type
        if t is BoundDerivationType.MAX_DISPLACEMENT_MINUS_FLOOR:
            return self._same_unit("max_displacement", "cost_floor")
        return self._input("cost_floor").unit

    def is_applicable(self) -> tuple[bool, str]:
        """Conditions d'applicabilité, vérifiées avant tout calcul."""
        t = self.derivation_type
        if t is BoundDerivationType.HORIZON_BELOW_MINIMUM_LATENCY:
            horizon = self._get("horizon_ns")
            latency = self._get("minimum_certain_latency_ns")
            if latency < horizon:
                return False, (
                    f"latence minimale certaine {latency:.0f} ns **inférieure** à "
                    f"l'horizon {horizon:.0f} ns : il reste {horizon - latency:.0f} ns "
                    "de fenêtre. Cette dérivation ne connaît pas la borne du mouvement "
                    "restant et ne peut rien conclure."
                )
            return True, ""
        if t is BoundDerivationType.CONTRACTUAL_LIMIT:
            required = self._get("minimum_order_size")
            available = self._get("allowed_capital_capacity")
            if required <= available:
                return False, (
                    f"taille minimale d'ordre {required:g} compatible avec la capacité "
                    f"autorisée {available:g} : aucune impossibilité contractuelle. Un "
                    "enum ne constitue pas une preuve."
                )
            return True, ""
        return True, ""

    def recompute(self) -> float:
        """Recalcule la borne. Une dérivation inapplicable **lève**.

        Elle ne retourne jamais une valeur favorable par défaut : c'est exactement ainsi
        qu'une latence de 74 ms sur un horizon de 500 ms pouvait produire un certificat
        d'impossibilité.
        """
        applicable, why = self.is_applicable()
        if not applicable:
            raise CampaignError(f"DERIVATION_NOT_APPLICABLE — {why}")

        t = self.derivation_type
        if t is BoundDerivationType.HORIZON_BELOW_MINIMUM_LATENCY:
            # La fenêtre est close avant qu'on puisse agir : capture brute nulle, donc
            # le surplus maximal se réduit au plancher de coûts, négatif.
            return -self._get("cost_floor")
        if t is BoundDerivationType.MAX_DISPLACEMENT_MINUS_FLOOR:
            self._same_unit("max_displacement", "cost_floor")
            return self._get("max_displacement") - self._get("cost_floor")
        return -self._get("cost_floor")


@dataclass(frozen=True)
class ImpossibilityCertificate:
    """Preuve **vérifiable** qu'aucune opportunité ne survit sur tout le domaine.

    Un champ texte non vide donnerait une fausse sécurité : *« impossible parce que la
    latence est trop élevée »* passerait un simple contrôle de non-vacuité. Le certificat
    porte donc les éléments qui rendent la conclusion **recalculable** — et `holds` est
    dérivé, jamais déclaré :

        U_oracle(Ω) = 0,031 R      δ_MEU = 0,05 R      ⇒   U_oracle(Ω) < δ_MEU

    Le système peut alors expliquer exactement pourquoi l'impossibilité est universelle,
    au lieu d'affirmer qu'elle l'est.
    """

    #: Propriété démontrée, énoncée mathématiquement.
    property_proven: str
    #: Domaine Ω sur lequel elle vaut, et ce qu'il exclut.
    domain: str
    #: Hypothèses sous lesquelles la démonstration tient.
    hypotheses: tuple[str, ...]
    #: Dérivation **exécutable** de la borne. Le certificat ne reçoit jamais la valeur
    #: normative : il la recalcule.
    derivation: "BoundDerivation"
    #: Données et constantes utilisées, avec leur provenance.
    constants_used: tuple[tuple[str, str], ...]
    proof_version: str
    declared_by: str
    unit: str = "USD/oz"

    @property
    def computed_upper_bound(self) -> float:
        """Recalculée à chaque lecture — jamais fournie par l'appelant.

            preuve recalculable  ≠  valeur fournie + documentation
        """
        return self.derivation.recompute()

    def __post_init__(self) -> None:
        missing = [
            name for name, value in (
                ("propriété démontrée", self.property_proven),
                ("domaine", self.domain),
                ("version de la démonstration", self.proof_version),
                ("auteur", self.declared_by),
            ) if not value.strip()
        ]
        if missing:
            raise CampaignError(
                f"Certificat incomplet : {', '.join(missing)}. Une impossibilité "
                "universelle qui ne peut pas être recalculée n'est pas une "
                "démonstration, c'est une affirmation."
            )
        if not self.hypotheses:
            raise CampaignError(
                "Un certificat sans hypothèses déclarées prétend valoir inconditionnellement."
            )
        if not self.constants_used:
            raise CampaignError(
                "Un certificat sans constantes ni provenance ne peut pas être vérifié."
            )

    def holds_against(self, delta_meu: float, delta_unit: str | None = None) -> bool:
        """Condition mathématique, évaluée — pas une case cochée.

        La comparaison exige la même unité des deux côtés : comparer `USD/oz` à
        `USD/lot` produirait un booléen dénué de sens physique.
        """
        if delta_unit is not None and delta_unit != self.derivation.unit:
            raise CampaignError(
                f"Comparaison entre unités différentes : borne en "
                f"{self.derivation.unit}, δ_MEU en {delta_unit}."
            )
        return self.computed_upper_bound < delta_meu

    def explain(self, delta_meu: float) -> str:
        relation = "<" if self.holds_against(delta_meu) else "≥"
        return (
            f"U_oracle(Ω) = {self.computed_upper_bound:.4f} {self.unit} {relation} "
            f"δ_MEU = {delta_meu:.4f} {self.unit} · {self.property_proven} sur {self.domain} "
            f"· hypothèses : {'; '.join(self.hypotheses)} · dérivation "
            f"{self.derivation.derivation_type.value}/{self.derivation.calculator_version} "
            f"· démonstration {self.proof_version} ({self.declared_by})"
        )


@dataclass(frozen=True)
class SurplusUpperBound:
    """Borne physique du gain d'un survivant, permettant de conclure sans en observer.

    Sans elle, aucune capacité économique n'est bornable à partir de zéro survivant : la
    queue non observée pourrait contenir n'importe quel gain. Avec elle, la borne devient

        J_oracle ≤ λ_opp · p_U · S_U

    extrêmement favorable à l'oracle, et donc conclusive si elle passe quand même sous
    `J_min`.
    """

    derivation: BoundDerivation
    argument: str
    domain: str
    proof_version: str

    def __post_init__(self) -> None:
        if not self.argument.strip() or not self.domain.strip():
            raise CampaignError(
                "Une borne de gain sans argument physique ni domaine serait une "
                "supposition présentée comme une limite."
            )
        if not self.proof_version.strip():
            raise CampaignError("une borne de gain doit porter sa version de dérivation")
        if self.value <= 0:
            raise CampaignError("une borne de gain doit être strictement positive")

    @property
    def value(self) -> float:
        """Recalculée, jamais fournie.

        C'est le même défaut que celui retiré du certificat d'impossibilité : un appelant
        pouvait écrire `value = 0.001` avec un argument convaincant et faire tomber
        `λ·p_U·S_U` sous `J_min` jusqu'à déclencher une exclusion.
        """
        return self.derivation.recompute()

    @property
    def unit(self) -> str:
        return self.derivation.unit


class OracleVerdict(str, Enum):
    #: **Réservé à une impossibilité démontrée** sur tout le domaine admissible. Ne
    #: s'obtient jamais d'un échantillon fini.
    ORACLE_UNIVERSALLY_NON_VIABLE = "ORACLE_UNIVERSALLY_NON_VIABLE"
    #: Aucun survivant dans l'échantillon observé, avec une borne sur leur fréquence.
    #: « Je n'en ai pas vu » — jamais « cela n'existe pas ».
    ORACLE_NO_SURVIVOR_OBSERVED = "ORACLE_NO_SURVIVOR_OBSERVED"
    #: Des opportunités existent, mais trop rarement pour le plancher exigé.
    ORACLE_FREQUENCY_NON_VIABLE = "ORACLE_FREQUENCY_NON_VIABLE"
    #: L'oracle ne produit pas assez de valeur par unité de temps sous contraintes.
    ORACLE_ECONOMIC_CAPACITY_NON_VIABLE = "ORACLE_ECONOMIC_CAPACITY_NON_VIABLE"
    #: Des opportunités suffisamment favorables subsistent. **Ne signifie pas** qu'un
    #: signal pourra les identifier.
    ORACLE_NOT_EXCLUDED = "ORACLE_NOT_EXCLUDED"
    ORACLE_INDETERMINATE = "ORACLE_INDETERMINATE"

    @property
    def excludes(self) -> bool:
        """`ORACLE_NO_SURVIVOR_OBSERVED` **n'exclut pas** : il décrit un échantillon."""
        return self in (
            OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE,
            OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE,
            OracleVerdict.ORACLE_ECONOMIC_CAPACITY_NON_VIABLE,
        )


def oracle_verdict(
    assessment: OracleAssessment,
    minimum_frequency_per_second: float,
    minimum_contribution_per_second: float,
    min_clusters: int,
    certificate: ImpossibilityCertificate | None = None,
    surplus_bound: SurplusUpperBound | None = None,
) -> tuple[OracleVerdict, str]:
    """Exclusion oracle (ADR-192, ADR-199).

    Deux erreurs sont interdites par construction. **Un quantile n'exclut jamais seul** :
    que 90 % de la population soit sous le plancher n'établit rien sur les 10 % restants,
    précisément ceux qu'un moteur sélectif retiendrait. Et **« aucun survivant observé »
    n'est pas « aucun survivant possible »** : un échantillon fini ne démontre pas une
    impossibilité, il borne une fréquence.
    """
    if assessment.selected == 0:
        return OracleVerdict.ORACLE_INDETERMINATE, "aucune opportunité admissible"
    if assessment.clusters < min_clusters:
        return (
            OracleVerdict.ORACLE_INDETERMINATE,
            f"{assessment.clusters} grappes indépendantes sur {min_clusters} requises",
        )

    # Impossibilité universelle : seulement si le certificat **se vérifie**.
    if certificate is not None and certificate.holds_against(assessment.delta_meu):
        return (
            OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE,
            certificate.explain(assessment.delta_meu),
        )

    bound = assessment.rarity
    # Exclusion par fréquence : la borne **supérieure** du taux, portée sur la cadence
    # d'opportunités, reste sous le plancher exigé.
    if (
        bound.quality.usable_for_verdict
        and assessment.profitable_frequency_upper < minimum_frequency_per_second
    ):
        return (
            OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE,
            f"fréquence oracle-rentable bornée par "
            f"{assessment.profitable_frequency_upper * 86_400:.2f}/jour, sous le plancher "
            f"de {minimum_frequency_per_second * 86_400:.2f}/jour — borne "
            f"{bound.quality.value} sur {bound.trials} unités",
        )

    # Niveau C — une seule voie normative.
    #
    # La capacité **observée**, même multipliée par un facteur de sécurité, ne démontre
    # rien sur la capacité future : un facteur 2 n'est ni une borne statistique, ni une
    # borne physique, ni une borne de population. C'est la même famille d'erreur que
    # « je n'ai pas observé davantage, donc davantage n'existe pas ». Elle reste publiée
    # comme diagnostic et n'exclut jamais.
    #
    # Seule une borne de population sur le taux, combinée à une borne physique du gain,
    # majore ce que la queue non observée pourrait rapporter :
    #
    #     J_oracle ≤ λ_opp · p_U · S_U
    ceiling = assessment.capacity_ceiling_per_second(surplus_bound)
    if (
        ceiling is not None
        and bound.quality.usable_for_verdict
        and ceiling < minimum_contribution_per_second
    ):
        return (
            OracleVerdict.ORACLE_ECONOMIC_CAPACITY_NON_VIABLE,
            f"plafond économique λ·p_U·S_U = {ceiling * 86_400:.4f}/jour sous la "
            f"contribution requise {minimum_contribution_per_second * 86_400:.2f}/jour — "
            f"avec p_U ≤ {bound.upper:.2%} et un gain majoré par {surplus_bound.value:.3f} "
            f"({surplus_bound.argument}), même la queue non observée ne suffirait pas",
        )

    # Aucun survivant observé, mais la fréquence reste compatible avec le plancher :
    # l'échantillon ne conclut pas.
    if assessment.profitable == 0:
        return (
            OracleVerdict.ORACLE_NO_SURVIVOR_OBSERVED,
            f"aucun survivant sur {assessment.selected} opportunités observées ; "
            f"{bound.describe()} — compatible avec le plancher de fréquence. "
            "L'échantillon ne montre rien, il ne démontre pas l'absence",
        )

    return (
        OracleVerdict.ORACLE_NOT_EXCLUDED,
        f"{assessment.profitable} opportunités oracle-rentables sur "
        f"{assessment.selected} retenues, surplus maximal {assessment.max_surplus:.4f} — "
        "il reste assez d'espace pour justifier la recherche d'un signal, ce qui ne dit "
        "rien de la capacité d'un moteur à les identifier",
    )


class Q42Priority(str, Enum):
    NOT_PRIORITARY_COST = "NOT_PRIORITARY_COST"
    NOT_PRIORITARY_LATENCY = "NOT_PRIORITARY_LATENCY"
    RATIONAL = "RATIONAL"
    UNDETERMINED = "UNDETERMINED"


def q42_priority(
    cost_excluded: bool, passive: PassiveVerdict
) -> tuple[Q42Priority, str]:
    """Embranchement Q42 (§25).

    Q42 coûte cher et comporte un risque financier réel. Elle ne devient rationnelle que
    lorsque les inconnues courtier **déterminent** encore le verdict.
    """
    if cost_excluded:
        return (
            Q42Priority.NOT_PRIORITARY_COST,
            "la famille est déjà exclue par le coût — la latence ne peut pas la sauver",
        )
    if passive is PassiveVerdict.PASSIVE_LATENCY_EXCLUDED:
        return (
            Q42Priority.NOT_PRIORITARY_LATENCY,
            "la borne passive exclut déjà l'horizon ; la partie inconnue de la latence "
            "ne peut qu'aggraver le constat (ADR-177)",
        )
    if passive is PassiveVerdict.PASSIVE_LATENCY_NOT_EXCLUDED:
        return (
            Q42Priority.RATIONAL,
            "l'horizon survit au coût et à la borne passive : les inconnues courtier "
            "déterminent désormais le verdict",
        )
    return (
        Q42Priority.UNDETERMINED,
        "borne passive indéterminée ou invalide — financer Q42 achèterait une précision "
        "sur un segment dont l'amont n'est pas encore mesuré",
    )


# --------------------------------------------------- capturabilité (Q19 phase 0)


class CapturabilityAnchor(str, Enum):
    """Instant à partir duquel la fraction consommée est comptée.

    Les trois ancres n'estiment pas la même quantité et ne se substituent jamais l'une à
    l'autre.
    """

    #: `t0` = instant de l'événement de marché. Référence économique idéale, disponible
    #: seulement si l'événement peut être horodaté de façon crédible.
    MARKET_EVENT_ANCHOR = "MARKET_EVENT_ANCHOR"
    #: `t0` = horodatage fournisseur. Ignore appariement, agrégation et délai interne
    #: précédant la publication, selon la sémantique de la source.
    PROVIDER_EVENT_ANCHOR = "PROVIDER_EVENT_ANCHOR"
    #: `t0` = B1. Répond seulement : une fois l'information arrivée chez nous, quelle
    #: part reste exploitable après notre propre traitement ?
    LOCAL_RECEIVE_ANCHOR = "LOCAL_RECEIVE_ANCHOR"


class CapturabilityScope(str, Enum):
    """Portée du résultat. Les trois ne peuvent **jamais** être fusionnées dans une même
    distribution : ce sont trois estimandes distincts."""

    END_TO_END_MARKET = "END_TO_END_MARKET"
    PROVIDER_TO_ACTION = "PROVIDER_TO_ACTION"
    POST_RECEIVE_ONLY = "POST_RECEIVE_ONLY"


class HorizonEndPolicy(str, Enum):
    """Où se termine la fenêtre d'évaluation.

    Déplacer l'ancre sans fixer cette politique déplacerait **silencieusement** la fin de
    l'horizon, et créerait un second estimande sous le même nom.
    """

    #: Fin = `t_marché + h`. La fenêtre économique d'origine est préservée.
    FIXED_MARKET_END = "FIXED_MARKET_END"
    #: Fin = `t_ancre + h`. La fenêtre glisse avec l'ancre et va donc plus loin dans le
    #: futur de `t_ancre − t_marché` — davantage de mouvement, artificiellement.
    ANCHORED_TO_ORIGIN = "ANCHORED_TO_ORIGIN"


#: Portée impliquée par chaque ancre.
_SCOPE_OF_ANCHOR = {
    CapturabilityAnchor.MARKET_EVENT_ANCHOR: CapturabilityScope.END_TO_END_MARKET,
    CapturabilityAnchor.PROVIDER_EVENT_ANCHOR: CapturabilityScope.PROVIDER_TO_ACTION,
    CapturabilityAnchor.LOCAL_RECEIVE_ANCHOR: CapturabilityScope.POST_RECEIVE_ONLY,
}

#: Nom sous lequel chaque portée doit être publiée. « capturabilité » tout court est
#: interdit : il laisserait croire à une mesure de bout en bout.
_RESULT_NAME = {
    CapturabilityScope.END_TO_END_MARKET: "END_TO_END_CAPTURABILITY",
    CapturabilityScope.PROVIDER_TO_ACTION: "PROVIDER_ANCHORED_CAPTURABILITY",
    CapturabilityScope.POST_RECEIVE_ONLY: "POST_RECEIVE_CAPTURABILITY",
}


@dataclass(frozen=True)
class CapturabilityInput:
    """Ce que la campagne transmet à la phase 0 de Q19 (§19, §21).

    L'ancre, la portée et la politique de fin d'horizon sont des **types**, pas des
    annotations : deux entrées de portées différentes ne peuvent pas être combinées.
    """

    cell: CampaignCell
    latency_samples_ns: np.ndarray
    anchor: CapturabilityAnchor
    clusters: int
    horizon_end_policy: HorizonEndPolicy = HorizonEndPolicy.FIXED_MARKET_END

    @property
    def scope(self) -> CapturabilityScope:
        return _SCOPE_OF_ANCHOR[self.anchor]

    @property
    def result_name(self) -> str:
        return _RESULT_NAME[self.scope]

    @property
    def creates_extended_window(self) -> bool:
        """Vrai lorsque la fenêtre glisse avec une ancre postérieure au marché.

        Elle va alors plus loin dans le futur que la fenêtre économique d'origine et
        peut créer du mouvement capturable qui n'existait pas dans la question posée.
        """
        return (
            self.horizon_end_policy is HorizonEndPolicy.ANCHORED_TO_ORIGIN
            and self.anchor is not CapturabilityAnchor.MARKET_EVENT_ANCHOR
        )

    @property
    def is_upper_bound_of_capturability(self) -> bool:
        """Vrai hors ancrage marché : le résultat borne la capturabilité par le **haut**.

        Tout ce qui précède l'ancre est offert gratuitement au système — dissémination,
        trajet fournisseur, réseau entrant — donc jamais compté comme perdu.
        """
        return self.anchor is not CapturabilityAnchor.MARKET_EVENT_ANCHOR

    def mergeable_with(self, other: "CapturabilityInput") -> bool:
        return (
            self.scope is other.scope
            and self.horizon_end_policy is other.horizon_end_policy
            and self.cell == other.cell
        )

    def interpret(self, excluded: bool) -> str:
        """Ce que le résultat autorise à conclure, selon la portée (§15)."""
        if self.scope is CapturabilityScope.END_TO_END_MARKET:
            return (
                "exclusion de bout en bout" if excluded
                else "non exclu de bout en bout, sous réserve des coûts"
            )
        if excluded:
            return (
                f"exclusion concluante : même en offrant gratuitement tout ce qui précède "
                f"l'ancre {self.anchor.value}, l'horizon ne survit pas"
            )
        return (
            f"non exclu **au sens de {self.result_name}** seulement — ne qualifie en rien "
            "le chemin de bout en bout, dont la partie amont n'a pas été comptée"
        )


def capturability_input(
    observations: Sequence[PassiveObservation],
    clock: ClockCapability,
    horizon_end_policy: HorizonEndPolicy = HorizonEndPolicy.FIXED_MARKET_END,
) -> CapturabilityInput:
    """Extrait la distribution **conditionnelle** de latence d'une cellule.

    Q19 phase 0 doit tirer sa latence dans les états où le signal se déclencherait ; une
    médiane globale sous-estimerait systématiquement le délai subi au moment utile.
    """
    usable = [o for o in observations if o.usable_for_local_distribution]
    if not usable:
        raise CampaignError("aucune observation à horloge exacte dans cette cellule")
    cells = {o.cell for o in usable}
    if len(cells) != 1:
        raise CampaignError("la distribution de latence doit rester dans une cellule")

    provider_ok = all(o.provider_qualified for o in usable) and clock.intersystem_usable
    if provider_ok:
        values = [o.provider_lower_bound_ns(clock) for o in usable]
        if any(v is None for v in values):
            provider_ok = False
    if not provider_ok:
        values = [o.local_lower_bound_ns for o in usable]

    # L'ancre marché n'est jamais atteinte par cette voie : l'horodatage fournisseur
    # ignore appariement, agrégation et délai interne précédant la publication. Le
    # revendiquer comme instant de l'événement supposerait une sémantique de source que
    # Q58 n'a pas établie.
    return CapturabilityInput(
        cell=usable[0].cell,
        latency_samples_ns=np.asarray(values, dtype=np.int64),
        anchor=(
            CapturabilityAnchor.PROVIDER_EVENT_ANCHOR if provider_ok
            else CapturabilityAnchor.LOCAL_RECEIVE_ANCHOR
        ),
        clusters=len({o.cluster_id for o in usable}),
        horizon_end_policy=horizon_end_policy,
    )


# --------------------------------------------------- état consolidé de la phase 0


class Phase0State(str, Enum):
    """Verdict consolidé — `D_cost ∩ D_passive_latency ∩ D_capturability`."""

    PHASE0_EXCLUDED_BY_COST = "PHASE0_EXCLUDED_BY_COST"
    PHASE0_EXCLUDED_BY_PASSIVE_LATENCY = "PHASE0_EXCLUDED_BY_PASSIVE_LATENCY"
    #: Impossibilité universelle, par fréquence, ou par capacité économique — jamais
    #: par un simple quantile (ADR-189).
    PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY = "PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY"
    #: Il reste physiquement et économiquement assez d'espace pour **justifier la
    #: recherche** d'un signal. Ne signifie jamais qu'un bon trade est possible.
    PHASE0_NOT_EXCLUDED = "PHASE0_NOT_EXCLUDED"
    PHASE0_INDETERMINATE = "PHASE0_INDETERMINATE"
    PHASE0_MEASUREMENT_INVALID = "PHASE0_MEASUREMENT_INVALID"


def phase0_state(
    cost_excluded: bool,
    passive: PassiveVerdict,
    oracle: OracleVerdict,
) -> tuple[Phase0State, str]:
    """Consolide les trois arguments d'exclusion, aucun ne dépendant d'un signal.

    L'ordre suit la solidité : une exclusion par le coût ne peut être rattrapée par
    aucune amélioration de latence, et une mesure invalide n'autorise rien.
    """
    if passive is PassiveVerdict.PASSIVE_MEASUREMENT_INVALID:
        return (
            Phase0State.PHASE0_MEASUREMENT_INVALID,
            "instrument ou horloge défaillants — aucun verdict",
        )
    if cost_excluded:
        return (
            Phase0State.PHASE0_EXCLUDED_BY_COST,
            "les coûts excluent l'horizon indépendamment de toute latence",
        )
    if passive is PassiveVerdict.PASSIVE_LATENCY_EXCLUDED:
        return (
            Phase0State.PHASE0_EXCLUDED_BY_PASSIVE_LATENCY,
            "la borne passive exclut, courtier supposé instantané",
        )
    oracle_exclusions = {
        OracleVerdict.ORACLE_UNIVERSALLY_NON_VIABLE:
            "aucune opportunité ne survit même avec connaissance parfaite du futur",
        OracleVerdict.ORACLE_FREQUENCY_NON_VIABLE:
            "des opportunités existent, mais trop rarement pour le plancher de fréquence",
        OracleVerdict.ORACLE_ECONOMIC_CAPACITY_NON_VIABLE:
            "la capacité économique de l'oracle reste sous la contribution requise",
    }
    if oracle in oracle_exclusions:
        return (
            Phase0State.PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY,
            oracle_exclusions[oracle],
        )
    if (
        passive is PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE
        or oracle is OracleVerdict.ORACLE_INDETERMINATE
    ):
        return (
            Phase0State.PHASE0_INDETERMINATE,
            "données insuffisantes ou instables — l'ignorance ne vaut pas permission",
        )
    if oracle is OracleVerdict.ORACLE_NO_SURVIVOR_OBSERVED:
        return (
            Phase0State.PHASE0_NOT_EXCLUDED,
            "aucun survivant observé, mais leur fréquence reste compatible avec le "
            "plancher : l'échantillon ne montre rien et ne démontre pas l'absence",
        )
    return (
        Phase0State.PHASE0_NOT_EXCLUDED,
        "il reste physiquement et économiquement assez d'espace pour justifier la "
        "recherche d'un signal — ce qui ne dit rien de son existence",
    )


# ----------------------------------------- sensibilité au découpage du régime calme


@dataclass(frozen=True)
class BlockingChoice:
    """Découpage temporel du régime calme — **versionné**, jamais une constante oubliée.

    Sa valeur devrait à terme être confrontée à l'autocorrélation des latences et du
    débit de ticks, à la durée des épisodes de file et de connexion : les blocs doivent
    être assez longs pour ne pas présenter comme indépendantes des observations qui ne
    le sont pas.
    """

    block_ns: int
    source: str
    version: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                "Une durée de bloc sans source déclarée redevient une constante "
                "arbitraire oubliée dans le code."
            )


@dataclass(frozen=True)
class BlockSensitivity:
    block_ns: int
    clusters: int
    p95_ns: float
    ci_low_ns: float
    ci_high_ns: float


def reassign_clusters(
    observations: Sequence[PassiveObservation],
    block_ns: int,
    burst_threshold: float,
    reset_ns: int,
    session_id: str = "S",
) -> tuple[str, ...]:
    """Recalcule les grappes avec un autre découpage calme, à observations inchangées."""
    assigner = ClusterAssigner(
        burst_threshold=burst_threshold, reset_ns=reset_ns,
        quiet_block_ns=block_ns, session_id=session_id,
    )
    return tuple(
        assigner.assign(o.boundaries.local_receive_ns, o.market.tick_rate_1s)
        for o in sorted(observations, key=lambda o: o.boundaries.local_receive_ns)
    )


def block_sensitivity(
    observations: Sequence[PassiveObservation],
    choice: BlockingChoice,
    burst_threshold: float,
    reset_ns: int,
    factors: Sequence[float] = (0.5, 1.0, 2.0),
    rng: np.random.Generator | None = None,
) -> tuple[BlockSensitivity, ...]:
    """Refait l'inférence sur plusieurs découpages (§16, ADR-187).

    Le verdict ne doit pas dépendre brutalement d'un unique découpage temporel — sinon
    il décrit le découpage autant que la latence.
    """
    usable = sorted(
        (o for o in observations if o.usable_for_local_distribution),
        key=lambda o: o.boundaries.local_receive_ns,
    )
    if not usable:
        raise CampaignError("aucune observation à horloge exacte")

    bounds = [o.local_lower_bound_ns for o in usable]
    out: list[BlockSensitivity] = []
    for f in factors:
        block = max(1, int(choice.block_ns * f))
        clusters = reassign_clusters(usable, block, burst_threshold, reset_ns)
        lo, hi = _cluster_bootstrap_ci(bounds, clusters, 0.95, rng=rng)
        out.append(BlockSensitivity(
            block_ns=block,
            clusters=len(set(clusters)),
            p95_ns=float(np.quantile(bounds, 0.95)),
            ci_low_ns=lo,
            ci_high_ns=hi,
        ))
    return tuple(out)


def blocking_is_robust(
    sensitivities: Sequence[BlockSensitivity], threshold_ns: float
) -> bool:
    """Vrai si tous les découpages placent le seuil du même côté de l'intervalle.

    Un verdict qui bascule entre `b/2` et `2b` n'est pas un verdict sur la latence.
    """
    if len(sensitivities) < 2:
        return False
    sides = {
        (s.ci_low_ns > threshold_ns, s.ci_high_ns < threshold_ns)
        for s in sensitivities
    }
    return len(sides) == 1


# ----------------------------------------------------- effet observateur mesuré


@dataclass(frozen=True)
class OverheadReport:
    """Perturbation réelle de l'instrumentation : `L_instrumenté − L_baseline`."""

    samples: int
    p50_ns: float
    p95_ns: float
    p99_ns: float
    clock_advanced: bool

    def __post_init__(self) -> None:
        if self.clock_advanced and self.p50_ns == 0.0 and self.p95_ns == 0.0:
            # Sérialiser hors du chemin critique ne supprime ni la lecture d'horloge, ni
            # la création d'objet, ni l'allocation, ni la mise en file, ni la contention.
            raise CampaignError(
                "Surcoût arrondi à zéro alors que l'horloge a avancé : la mesure est "
                "trop grossière pour la perturbation qu'elle prétend écarter."
            )


def observer_overhead(
    baseline_ns: Sequence[float], instrumented_ns: Sequence[float]
) -> OverheadReport:
    """Compare deux séries appariées d'un même travail, avec et sans instrumentation."""
    if len(baseline_ns) != len(instrumented_ns):
        raise CampaignError(
            "Les deux séries doivent être appariées : comparer des tailles différentes "
            "mesurerait aussi la différence d'échantillon."
        )
    if not baseline_ns:
        raise CampaignError("aucun échantillon de référence")
    diff = np.asarray(instrumented_ns, dtype=float) - np.asarray(baseline_ns, dtype=float)
    return OverheadReport(
        samples=diff.size,
        p50_ns=float(np.quantile(diff, 0.50)),
        p95_ns=float(np.quantile(diff, 0.95)),
        p99_ns=float(np.quantile(diff, 0.99)),
        clock_advanced=bool(np.any(np.asarray(baseline_ns) > 0)),
    )


# ------------------------------------------- comparaison de cadence (Q43, §18)


class ComparisonDesign(str, Enum):
    #: Même flux enregistré, rejoué sous les deux politiques.
    PAIRED_REPLAY = "PAIRED_REPLAY"
    #: Les deux politiques calculent leurs horodatages hypothétiques sur le même flux.
    SHADOW_EVALUATION = "SHADOW_EVALUATION"
    #: Deux journées différentes. Les marchés n'étaient pas les mêmes.
    UNPAIRED_DAYS = "UNPAIRED_DAYS"

    @property
    def supports_attribution(self) -> bool:
        return self is not ComparisonDesign.UNPAIRED_DAYS


@dataclass(frozen=True)
class CadenceComparison:
    design: ComparisonDesign
    event_driven_p95_ns: float
    periodic_p95_ns: float
    attributable: bool
    interpretation: str


def compare_cadence(
    event_driven: Sequence[PassiveObservation],
    periodic: Sequence[PassiveObservation],
    design: ComparisonDesign,
) -> CadenceComparison:
    """Compare les deux modes d'évaluation (ADR-188).

    Sous `UNPAIRED_DAYS`, la différence mesurée confond cadence et régime de marché : le
    module refuse l'attribution et n'offre qu'un diagnostic. Les deux politiques doivent
    voir **le même flux**.
    """
    if not event_driven or not periodic:
        raise CampaignError("les deux modes doivent être représentés")

    ed = float(np.quantile([o.local_lower_bound_ns for o in event_driven], 0.95))
    pe = float(np.quantile([o.local_lower_bound_ns for o in periodic], 0.95))
    if design.supports_attribution:
        interpretation = (
            f"écart attribuable à la cadence : {format_ns(int(abs(pe - ed)))} au p95, "
            "les deux politiques ayant vu le même flux"
        )
    else:
        interpretation = (
            "écart non attribuable à la cadence — les deux modes ont vu des marchés "
            "différents. Diagnostic seulement ; utiliser un rejeu apparié ou une "
            "évaluation fantôme sur le même flux."
        )
    return CadenceComparison(
        design=design,
        event_driven_p95_ns=ed,
        periodic_p95_ns=pe,
        attributable=design.supports_attribution,
        interpretation=interpretation,
    )


# ------------------------------------------------------------------ les rapports


def hourly_report(observations: Sequence[PassiveObservation]) -> str:
    """Rapport de démarrage (§17) — sert à détecter les erreurs d'instrumentation.

    Ce n'est pas un rapport de recherche : il ne conditionne rien et ne conclut rien.
    """
    if not observations:
        return "aucune observation"
    q = lambda vals: Quantiles.of(vals)  # noqa: E731
    bounds = [o.local_lower_bound_ns for o in observations]
    qb = q(bounds)
    lines = [
        f"CONTRÔLE D'INSTRUMENTATION — {len(observations)} évaluations",
        f"  cadence de ticks     p50 {q([o.market.tick_rate_1s for o in observations]).p50:.1f}"
        f"   p95 {q([o.market.tick_rate_1s for o in observations]).p95:.1f}/s",
        f"  spread               p50 {q([o.market.spread for o in observations]).p50:.3f}"
        f"   p95 {q([o.market.spread for o in observations]).p95:.3f}",
        f"  attente d'évaluation p50 {format_ns(int(q([o.evaluation_wait_ns for o in observations]).p50))}"
        f"   p95 {format_ns(int(q([o.evaluation_wait_ns for o in observations]).p95))}",
        f"  calcul               p50 {format_ns(int(q([o.compute_ns for o in observations]).p50))}"
        f"   p95 {format_ns(int(q([o.compute_ns for o in observations]).p95))}",
        f"  décision             p50 {format_ns(int(q([o.decision_ns for o in observations]).p50))}"
        f"   p95 {format_ns(int(q([o.decision_ns for o in observations]).p95))}",
        f"  borne locale         p50 {format_ns(int(qb.p50))}   p95 {format_ns(int(qb.p95))}"
        f"   p99 {format_ns(int(qb.p99))}",
        f"  profondeur de file   max {max(o.host.evaluation_queue_depth for o in observations)}",
        f"  retard de boucle     p95 {format_ns(int(q([o.host.event_loop_lag_ns for o in observations]).p95))}",
        f"  horloges dégradées   {sum(1 for o in observations if not o.usable_for_local_distribution)}",
        f"  connexions instables {sum(1 for o in observations if o.connection_state is not ConnectionState.CONNECTED_STABLE)}",
    ]
    return "\n".join(lines)


def daily_report(
    observations: Sequence[PassiveObservation],
    clock: ClockCapability,
    rng: np.random.Generator | None = None,
) -> str:
    """Rapport de recherche (§18) — conditionnel par construction."""
    cover = coverage(observations)
    summaries = summarise_by_cell(observations, rng=rng)
    lines = [
        "CAMPAGNE PASSIVE Q51-A — aucun ordre émis, aucune latence courtier supposée",
        "",
        "QUALITÉ",
        f"  journées {cover.days_observed}   sessions {cover.sessions_observed}"
        f"   évaluations {cover.observations}",
        f"  horloge  {clock.qualification.value}"
        f"   observations écartées {cover.invalid_clock_observations}",
        "",
        "COUVERTURE DE RAFALE (grappes indépendantes)",
        f"  normal {cover.normal_clusters}   P95 {cover.burst_clusters_p95}"
        f"   P99 {cover.burst_clusters_p99}   macro {cover.macro_windows}",
        "",
        "BORNE LOCALE PAR CELLULE",
        f"  {'cellule':<52} {'grappes':>8} {'p50':>10} {'p95':>10} {'p99':>10}",
        "  " + "-" * 94,
    ]
    for cell in sorted(summaries, key=lambda c: c.label):
        s = summaries[cell]
        lines.append(
            f"  {cell.label:<52} {s.clusters:>8} "
            f"{format_ns(int(s.bound.p50)):>10} {format_ns(int(s.bound.p95)):>10} "
            f"{format_ns(int(s.bound.p99)):>10}"
        )
    lines += ["", "DÉCOMPOSITION (p95, pile TARGET seulement)"]
    for cell in sorted(summaries, key=lambda c: c.label):
        if cell.pipeline is not PipelineMode.TARGET:
            continue
        s = summaries[cell]
        lines.append(
            f"  {cell.label:<52} éligibilité {format_ns(int(s.eligibility.p95))}"
            f" · attente {format_ns(int(s.evaluation_wait.p95))}"
            f" · calcul {format_ns(int(s.compute.p95))}"
            f" · décision {format_ns(int(s.decision.p95))}"
        )
    lines += [
        "",
        "Non mesuré, et donc non compté : émission, réseau, traitement courtier, file,",
        "activation, exécution, glissement, sélection adverse.",
    ]
    return "\n".join(lines)
