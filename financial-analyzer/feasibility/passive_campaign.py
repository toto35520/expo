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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
    min_clusters: int = 20,
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


@dataclass(frozen=True)
class OracleCapture:
    """`U_capture(L, h, c)` — borne **optimiste** du mouvement encore capturable.

    Construite en offrant gratuitement au système ce qu'aucun signal réel ne possède :
    la direction connue à l'avance et l'instant de sortie parfait à l'intérieur de la
    fenêtre restante. Aucun moteur prédictif ne peut faire mieux, ce qui est exactement
    ce qui rend une exclusion concluante sans avoir défini le moindre signal.
    """

    events: int
    clusters: int
    horizon_ns: int
    scope: CapturabilityScope
    #: Excursion favorable maximale après latence, en unité de prix.
    capture: Quantiles
    #: Part des événements où la latence dépasse l'horizon — capture nulle, jamais exclue
    #: de l'échantillon.
    exhausted_fraction: float

    @property
    def optimistic_capture(self) -> float:
        """Lecture favorable de la borne : c'est elle qui doit échouer pour exclure."""
        return self.capture.p90


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

    Pour chaque événement : on se place à `t0 + L`, puis on prend la plus grande
    excursion favorable dans la fenêtre restante, dans **la meilleure des deux
    directions**. C'est un oracle, pas une prédiction.

    Si `L ≥ h`, la capture vaut zéro et l'événement **reste dans l'échantillon** : le
    retirer ne conserverait que les cas où l'on avait eu le temps d'agir (ADR-159).
    """
    rng = rng or np.random.default_rng(0)
    if event_starts.size == 0 or latency_samples_ns.size == 0:
        return OracleCapture(0, 0, horizon_ns, scope, Quantiles.of([]), float("nan"))

    drawn = rng.choice(latency_samples_ns, size=event_starts.size, replace=True)
    captures: list[float] = []
    exhausted = 0

    for start, lat in zip(event_starts, drawn):
        t0 = timestamps_ns[start]
        if lat >= horizon_ns:
            captures.append(0.0)
            exhausted += 1
            continue
        i_act = int(np.searchsorted(timestamps_ns, t0 + int(lat), side="left"))
        i_end = int(np.searchsorted(timestamps_ns, t0 + horizon_ns, side="right"))
        if i_act >= i_end or i_act >= prices.size:
            captures.append(0.0)
            exhausted += 1
            continue
        window = prices[i_act:i_end]
        entry = prices[i_act]
        captures.append(float(max(window.max() - entry, entry - window.min())))

    clusters = (
        int(np.unique(cluster_ids[event_starts]).size) if cluster_ids is not None
        else len(captures)
    )
    return OracleCapture(
        events=len(captures),
        clusters=clusters,
        horizon_ns=horizon_ns,
        scope=scope,
        capture=Quantiles.of(captures),
        exhausted_fraction=exhausted / len(captures),
    )


class OracleVerdict(str, Enum):
    #: Même l'oracle ne couvre pas le plancher de coûts. Exclusion sans moteur prédictif.
    LATENCY_COST_ORACLE_EXCLUDED = "LATENCY_COST_ORACLE_EXCLUDED"
    ORACLE_NOT_EXCLUDED = "ORACLE_NOT_EXCLUDED"
    ORACLE_INDETERMINATE = "ORACLE_INDETERMINATE"


def oracle_exclusion(
    capture: OracleCapture,
    cost_floor: float,
    min_clusters: int = 20,
) -> tuple[OracleVerdict, str]:
    """Exclusion signal-agnostique (§6, ADR-183).

        U_capture ≤ C_floor  ⇒  LATENCY_COST_ORACLE_EXCLUDED

    L'argument est plus fort qu'un `Lmax` arbitraire : même un détecteur extrêmement
    favorable ne dispose plus d'un mouvement suffisant après la latence observée. Aucune
    croyance sur l'alpha n'y entre.

    `cost_floor` est le coût aller-retour **le plus bas plausible** : utiliser une
    estimation centrale rendrait l'exclusion moins conservatrice qu'annoncé.
    """
    if capture.events == 0:
        return OracleVerdict.ORACLE_INDETERMINATE, "aucun événement exploitable"
    if capture.clusters < min_clusters:
        return (
            OracleVerdict.ORACLE_INDETERMINATE,
            f"{capture.clusters} grappes indépendantes sur {min_clusters} requises",
        )

    optimistic = capture.optimistic_capture
    if optimistic <= cost_floor:
        return (
            OracleVerdict.LATENCY_COST_ORACLE_EXCLUDED,
            f"capture oracle p90 = {optimistic:.4f} ≤ plancher de coûts {cost_floor:.4f} "
            f"à l'horizon {format_ns(capture.horizon_ns)} — direction connue d'avance et "
            f"sortie parfaite comprises ; {capture.exhausted_fraction:.0%} des événements "
            "sont déjà épuisés au moment où l'on pourrait agir",
        )
    return (
        OracleVerdict.ORACLE_NOT_EXCLUDED,
        f"capture oracle p90 = {optimistic:.4f} au-dessus du plancher {cost_floor:.4f} — "
        "il reste physiquement assez d'espace pour justifier la recherche d'un signal, "
        "ce qui ne dit rien de son existence",
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
    if oracle is OracleVerdict.LATENCY_COST_ORACLE_EXCLUDED:
        return (
            Phase0State.PHASE0_EXCLUDED_BY_ORACLE_CAPTURABILITY,
            "même un détecteur oracle ne couvre plus les coûts après la latence observée",
        )
    if (
        passive is PassiveVerdict.PASSIVE_LATENCY_INDETERMINATE
        or oracle is OracleVerdict.ORACLE_INDETERMINATE
    ):
        return (
            Phase0State.PHASE0_INDETERMINATE,
            "données insuffisantes ou instables — l'ignorance ne vaut pas permission",
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
