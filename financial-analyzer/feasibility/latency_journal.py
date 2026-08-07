"""Journalisation de latence de production (Q51).

Q51 mesure **exactement ce qui est observable**, publie ce qui reste inconnu, et utilise
cette information comme borne. Il ne cherche pas encore à démontrer qu'un signal est
rentable.

Le principe central est une contrainte de type, pas une consigne : un accusé de réception
local ne permet **pas** de distinguer file locale, réseau aller, traitement courtier,
réseau retour et rappel local si le courtier ne fournit pas ses propres horodatages. Un
intervalle mesuré déclare donc ce qu'il contient et ce qu'il ne peut pas séparer.

Stratégie scientifique asymétrique :

    borne inférieure déjà trop lente  → exclusion concluante
    borne inférieure assez rapide     → seulement « non exclu à la couche messagerie »
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum

NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000
JOURNAL_VERSION = "Q51_JOURNAL_1.0"


# ----------------------------------------------------------------- observabilité


class Observability(str, Enum):
    """Ce qu'un intervalle mesuré permet réellement d'affirmer."""

    #: Mesuré entre deux horodatages fiables du même référentiel. Décomposable.
    OBSERVED = "OBSERVED"
    #: Mesuré, mais somme de composantes que l'infrastructure ne sépare pas.
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    #: Non mesurable avec cette API. Reste inconnu — jamais estimé.
    NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"


class ClockBasis(str, Enum):
    MONOTONIC = "MONOTONIC"
    WALL = "WALL"
    CROSS_SYSTEM = "CROSS_SYSTEM"


class JournalError(ValueError):
    """Mesure impossible, invariant de journal violé, ou décomposition non fondée."""


@dataclass(frozen=True)
class LatencyInterval:
    """Durée mesurée, avec ce qu'elle contient et ce qu'elle ne sépare pas.

    `contains` n'est pas décoratif : c'est ce qui empêche de rebaptiser un agrégat en
    « latence réseau » ou « latence courtier ». Un intervalle `AGGREGATE_ONLY` ne peut pas
    être présenté sous le nom de l'une de ses composantes.
    """

    name: str
    duration_ns: int | None
    observability: Observability
    clock: ClockBasis
    contains: tuple[str, ...] = ()
    uncertainty_ns: int = 0

    def __post_init__(self) -> None:
        if self.observability is Observability.NOT_IDENTIFIABLE and self.duration_ns is not None:
            raise JournalError(
                f"{self.name} : une composante non identifiable ne porte pas de durée. "
                "Une valeur absente reste absente, elle n'est pas estimée."
            )
        if self.observability is Observability.AGGREGATE_ONLY and len(self.contains) < 2:
            raise JournalError(
                f"{self.name} : un agrégat doit déclarer les composantes qu'il ne sépare pas. "
                "Sans cette liste, rien n'empêche de le renommer d'après l'une d'elles."
            )
        if self.duration_ns is not None and self.duration_ns < 0:
            raise JournalError(
                f"{self.name} : durée négative ({self.duration_ns} ns). Une horloge murale "
                "a probablement été utilisée là où l'horloge monotone était requise."
            )

    @property
    def reportable_precision_ns(self) -> int:
        """Aucun résultat ne s'affiche avec une précision supérieure à celle de l'horloge."""
        return max(1, self.uncertainty_ns)

    def decomposable_into(self, component: str) -> bool:
        return self.observability is Observability.OBSERVED and component == self.name


#: Composantes de l'aller-retour d'émission qu'un accusé local ne sépare pas.
SUBMIT_ACK_COMPONENTS = (
    "local_outbound_queue",
    "outbound_network",
    "broker_processing",
    "inbound_network",
    "local_callback_dispatch",
)

#: Composantes du trajet fournisseur → réception locale.
FEED_COMPONENTS = (
    "matching_publication",
    "provider_aggregation",
    "provider_distribution",
    "transport_network",
    "local_buffering",
)


# ---------------------------------------------------------------------- horloges


class ClockSyncState(str, Enum):
    SYNC_VERIFIED = "SYNC_VERIFIED"
    SYNC_DEGRADED = "SYNC_DEGRADED"
    SYNC_UNKNOWN = "SYNC_UNKNOWN"
    CLOCK_UNSTABLE = "CLOCK_UNSTABLE"


@dataclass(frozen=True)
class ClockReading:
    """Les deux horloges, toujours prises ensemble.

    L'horloge murale peut sauter — correction de synchronisation, changement manuel,
    virtualisation, reprise après veille. L'horloge monotone ne recule pas.
    """

    wall_ns: int
    monotonic_ns: int


@dataclass(frozen=True)
class ClockSyncStatus:
    method: str
    source: str
    estimated_offset_ns: int
    estimated_uncertainty_ns: int
    last_sync_wall_ns: int
    drift_ppm: float
    state: ClockSyncState

    def can_claim_precision(self, claimed_ns: int) -> bool:
        """Une latence inter-systèmes ne se revendique pas plus finement que l'incertitude
        de synchronisation."""
        return claimed_ns >= self.estimated_uncertainty_ns


@dataclass
class ClockMonitor:
    """Surveille la cohérence entre horloge murale et horloge monotone."""

    tolerance_ns: int = 50 * NS_PER_MS
    discontinuities: list[tuple[ClockReading, ClockReading, int]] = field(default_factory=list)

    def measure(self, start: ClockReading, end: ClockReading) -> tuple[int, bool]:
        """Durée locale et présence d'une discontinuité.

        La durée retenue est **toujours** celle de l'horloge monotone ; l'écart mural est
        conservé pour l'audit, jamais pour la mesure.
        """
        mono = end.monotonic_ns - start.monotonic_ns
        wall = end.wall_ns - start.wall_ns
        drift = abs(wall - mono)

        # Un recul de l'horloge murale pendant que l'horloge monotone avance est une
        # discontinuité **quelle que soit son amplitude** : c'est un signe, pas une
        # magnitude. Un seuil de tolérance laisserait passer les petites corrections, qui
        # sont précisément les plus fréquentes.
        went_backwards = wall < 0 <= mono
        if went_backwards or drift > self.tolerance_ns:
            self.discontinuities.append((start, end, drift))
            return mono, True
        return mono, False


# ------------------------------------------------------------------- contexte


class BurstState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    BURST_P95 = "BURST_P95"
    BURST_P99 = "BURST_P99"


class ConnectionState(str, Enum):
    CONNECTED_STABLE = "CONNECTED_STABLE"
    CONNECTED_RECOVERED = "CONNECTED_RECOVERED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"


@dataclass(frozen=True)
class BurstContext:
    """Intensité au moment considéré.

    Les classes discrètes sont conservées pour l'interface, mais les variables continues
    permettent de tracer la latence en fonction de l'intensité plutôt que de dépendre de
    seuils arbitraires.
    """

    state: BurstState
    tick_rate_100ms: float
    tick_rate_1s: float
    tick_rate_5s: float
    spread: float
    spread_percentile: float
    price_velocity: float = 0.0
    is_macro_window: bool = False


@dataclass(frozen=True)
class ConnectionEpisode:
    episode_id: str
    state: ConnectionState
    started_wall_ns: int
    ended_wall_ns: int | None = None


# --------------------------------------------------------------------- journal


class EventType(str, Enum):
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    SUBMIT_STARTED = "SUBMIT_STARTED"
    SUBMIT_RETURNED = "SUBMIT_RETURNED"
    BROKER_ACK = "BROKER_ACK"
    BROKER_REJECT = "BROKER_REJECT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_ACK = "CANCEL_ACK"
    PARTIAL_FILL = "PARTIAL_FILL"
    FULL_FILL = "FULL_FILL"
    EXPIRED = "EXPIRED"
    CONNECTION_LOST = "CONNECTION_LOST"
    CLOCK_DISCONTINUITY = "CLOCK_DISCONTINUITY"
    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    EVALUATION_STARTED = "EVALUATION_STARTED"
    EVALUATION_COMPLETED = "EVALUATION_COMPLETED"
    DECISION_CREATED = "DECISION_CREATED"


#: Événements capables de créer un état réel chez le courtier. Ils sont persistés avant ou
#: au moment de l'action : sans cela, un incident peut laisser un ordre réel sans trace
#: locale de son origine.
WRITE_AHEAD_TYPES = frozenset({
    EventType.ORDER_INTENT_CREATED,
    EventType.SUBMIT_STARTED,
    EventType.CANCEL_REQUESTED,
})


@dataclass(frozen=True)
class JournalEvent:
    journal_event_id: str
    event_type: EventType
    clock: ClockReading
    correlation_id: str | None = None
    logical_order_id: str | None = None
    submission_attempt_id: str | None = None
    decision_id: str | None = None
    #: Horodatages fournis par des systèmes tiers — conservés séparément, jamais fusionnés
    #: avec les horloges locales.
    broker_timestamp_ns: int | None = None
    broker_timestamp_semantics: str | None = None
    provider_timestamp_ns: int | None = None
    market_id: str | None = None
    order_type: str | None = None
    side: str | None = None
    quantity: float | None = None
    price: float | None = None
    burst: BurstContext | None = None
    connection_state: ConnectionState = ConnectionState.CONNECTED_STABLE
    evaluation_queue_depth: int | None = None
    event_loop_lag_ns: int | None = None
    probe_sampling_probability: float | None = None
    sampling_policy_version: str | None = None
    host_id: str = "unknown"
    connector_version: str = "unknown"
    journal_version: str = JOURNAL_VERSION
    previous_event_hash: str | None = None
    event_hash: str | None = None

    def compute_hash(self, previous: str | None) -> str:
        payload = {
            k: v for k, v in asdict(self).items()
            if k not in ("event_hash", "previous_event_hash")
        }
        payload["previous"] = previous
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]


@dataclass
class LatencyJournal:
    """Journal append-only, chaîné par empreintes.

    Aucun événement n'est réécrit : les états courants sont reconstruits depuis les
    événements. La chaîne rend toute modification historique détectable.
    """

    session_id: str
    host_boot_id: str
    process_start_wall_ns: int
    software_commit: str
    connector_version: str
    clock_sync: ClockSyncStatus
    account_fingerprint: str
    events: list[JournalEvent] = field(default_factory=list)
    _durable: set[str] = field(default_factory=set)

    def append(self, event: JournalEvent, durable: bool = False) -> JournalEvent:
        if event.event_type in WRITE_AHEAD_TYPES and not durable:
            raise JournalError(
                f"{event.event_type.value} doit être persisté de façon durable avant ou au "
                "moment de l'action : un incident laisserait sinon un ordre réel sans trace "
                "locale de son origine."
            )
        previous = self.events[-1].event_hash if self.events else None
        stamped = JournalEvent(
            **{**asdict_shallow(event), "previous_event_hash": previous,
               "event_hash": event.compute_hash(previous)}
        )
        self.events.append(stamped)
        if durable:
            self._durable.add(stamped.journal_event_id)
        return stamped

    def verify_chain(self) -> bool:
        previous = None
        for e in self.events:
            if e.previous_event_hash != previous:
                return False
            if e.event_hash != e.compute_hash(previous):
                return False
            previous = e.event_hash
        return True

    def by_logical_order(self, logical_order_id: str) -> list[JournalEvent]:
        return [e for e in self.events if e.logical_order_id == logical_order_id]

    def attempts_of(self, logical_order_id: str) -> list[str]:
        """Tentatives distinctes d'un même ordre logique.

        Un retry ne crée pas un nouvel ordre logique : sans cette séparation, un délai
        d'attente suivi d'un accusé compterait comme deux ordres, et l'idempotence
        deviendrait invérifiable.
        """
        seen: list[str] = []
        for e in self.by_logical_order(logical_order_id):
            if e.submission_attempt_id and e.submission_attempt_id not in seen:
                seen.append(e.submission_attempt_id)
        return seen


def asdict_shallow(event: JournalEvent) -> dict:
    """Copie de champs sans reconstruire les objets imbriqués."""
    return {f: getattr(event, f) for f in event.__dataclass_fields__}


# ------------------------------------------------------------------- mesures


@dataclass(frozen=True)
class EvaluationProbe:
    """Attente de cadence et temps de calcul, mesurés événement par événement.

    L'approximation `cadence / 2` n'est qu'un diagnostic théorique sous arrivée uniforme.
    Les cotations arrivent en rafale et s'alignent souvent sur des frontières rondes : le
    retard réel se mesure.
    """

    eligible: ClockReading
    evaluated: ClockReading
    completed: ClockReading
    decision: ClockReading | None
    burst: BurstContext
    engine_version: str
    events_processed: int

    def wait(self, monitor: ClockMonitor) -> LatencyInterval:
        d, _ = monitor.measure(self.eligible, self.evaluated)
        return LatencyInterval(
            "evaluation_wait", d, Observability.OBSERVED, ClockBasis.MONOTONIC
        )

    def compute(self, monitor: ClockMonitor) -> LatencyInterval:
        d, _ = monitor.measure(self.evaluated, self.completed)
        return LatencyInterval(
            "compute", d, Observability.OBSERVED, ClockBasis.MONOTONIC
        )

    def decide(self, monitor: ClockMonitor) -> LatencyInterval:
        if self.decision is None:
            return LatencyInterval(
                "decision", None, Observability.NOT_IDENTIFIABLE, ClockBasis.MONOTONIC
            )
        d, _ = monitor.measure(self.completed, self.decision)
        return LatencyInterval("decision", d, Observability.OBSERVED, ClockBasis.MONOTONIC)


def feed_latency(
    provider_ns: int | None, receive_wall_ns: int, sync: ClockSyncStatus
) -> LatencyInterval:
    """Trajet fournisseur → réception locale.

    Cet intervalle contient appariement, agrégation, distribution, transport et
    tamponnage. **Il ne doit jamais être nommé « latence réseau »** : ce serait attribuer à
    une composante ce qui appartient à cinq.
    """
    if provider_ns is None or sync.state is ClockSyncState.SYNC_UNKNOWN:
        return LatencyInterval(
            "provider_to_local_receive_latency", None,
            Observability.NOT_IDENTIFIABLE, ClockBasis.CROSS_SYSTEM,
        )
    raw = receive_wall_ns - provider_ns - sync.estimated_offset_ns
    return LatencyInterval(
        name="provider_to_local_receive_latency",
        duration_ns=max(0, raw),
        observability=Observability.AGGREGATE_ONLY,
        clock=ClockBasis.CROSS_SYSTEM,
        contains=FEED_COMPONENTS,
        uncertainty_ns=sync.estimated_uncertainty_ns,
    )


def submit_to_ack(
    submit_start: ClockReading,
    ack_receive: ClockReading,
    monitor: ClockMonitor,
    broker_timestamps_available: bool = False,
) -> LatencyInterval:
    """Aller-retour d'émission mesuré localement.

    Sans horodatages du courtier, cet intervalle est un **agrégat non décomposable** :
    file locale, réseau aller, traitement courtier, réseau retour et rappel local n'y sont
    pas séparables. Il porte donc son nom d'agrégat, jamais celui d'une composante.
    """
    d, _ = monitor.measure(submit_start, ack_receive)
    return LatencyInterval(
        name="submit_to_ack_latency",
        duration_ns=d,
        observability=(
            Observability.OBSERVED if broker_timestamps_available
            else Observability.AGGREGATE_ONLY
        ),
        clock=ClockBasis.MONOTONIC,
        contains=() if broker_timestamps_available else SUBMIT_ACK_COMPONENTS,
    )


def broker_side_split(
    submit_start: ClockReading,
    broker_received_ns: int | None,
    broker_ack_ns: int | None,
    ack_receive: ClockReading,
    sync: ClockSyncStatus,
) -> tuple[LatencyInterval, LatencyInterval, LatencyInterval]:
    """Décomposition de l'aller-retour — **seulement** si le courtier horodate.

    Sans ses horodatages, les trois composantes restent non identifiables. Le module ne
    les estime pas : il les déclare inconnues.
    """
    if broker_received_ns is None or broker_ack_ns is None:
        unknown = lambda n: LatencyInterval(  # noqa: E731
            n, None, Observability.NOT_IDENTIFIABLE, ClockBasis.CROSS_SYSTEM
        )
        return unknown("outbound_leg"), unknown("broker_processing"), unknown("inbound_leg")

    u = sync.estimated_uncertainty_ns
    return (
        LatencyInterval("outbound_leg", max(0, broker_received_ns - submit_start.wall_ns),
                        Observability.AGGREGATE_ONLY, ClockBasis.CROSS_SYSTEM,
                        ("local_outbound_queue", "outbound_network"), u),
        LatencyInterval("broker_processing", max(0, broker_ack_ns - broker_received_ns),
                        Observability.OBSERVED, ClockBasis.CROSS_SYSTEM, (), u),
        LatencyInterval("inbound_leg", max(0, ack_receive.wall_ns - broker_ack_ns),
                        Observability.AGGREGATE_ONLY, ClockBasis.CROSS_SYSTEM,
                        ("inbound_network", "local_callback_dispatch"), u),
    )


# ------------------------------------------------------------------- sortie Q19


class MeasurementQuality(str, Enum):
    MEASUREMENT_VALID = "MEASUREMENT_VALID"
    MEASUREMENT_DEGRADED = "MEASUREMENT_DEGRADED"
    MEASUREMENT_INVALID = "MEASUREMENT_INVALID"


@dataclass(frozen=True)
class LatencyObservation:
    """Ce que Q51 livre à Q19.

    Les champs absents restent `None`. **Q19 ne reconstruit jamais un horodatage manquant
    à partir de moyennes** : une composante inconnue reste inconnue et n'entre pas dans la
    borne.
    """

    trigger_wall_ns: int
    session_id: str
    burst: BurstContext
    connection_state: ConnectionState
    intervals: tuple[LatencyInterval, ...]
    clock_uncertainty_ns: int
    quality: MeasurementQuality
    cluster_id: str
    probe_sampling_probability: float | None = None

    @property
    def observable_lower_bound_ns(self) -> int:
        """Somme des seules composantes réellement mesurées.

        C'est une **borne inférieure** de la latence totale : ce qui n'est pas observable
        n'est pas compté, donc la vraie latence ne peut qu'être supérieure. Cette asymétrie
        est ce qui rend un verdict négatif concluant sans campagne complète.
        """
        return sum(i.duration_ns or 0 for i in self.intervals)

    @property
    def unknown_components(self) -> tuple[str, ...]:
        return tuple(
            i.name for i in self.intervals
            if i.observability is Observability.NOT_IDENTIFIABLE
        )

    def consumed_fraction_at(self, horizon_ns: int) -> float:
        """Part de l'horizon consommée par la latence.

        Une latence supérieure à l'horizon compte pour la totalité — l'observation n'est
        **jamais** supprimée. C'est la règle qui a corrigé le biais de sélection détecté
        dans la phase 0 de Q19.
        """
        if horizon_ns <= 0:
            return 1.0
        return min(1.0, self.observable_lower_bound_ns / horizon_ns)


class LatencyVerdictQ51(str, Enum):
    #: La borne inférieure observable dépasse déjà l'horizon : concluant sans campagne
    #: d'exécution.
    LATENCY_NON_VIABLE = "LATENCY_NON_VIABLE"
    #: La couche messagerie ne suffit pas à exclure. Ne démontre **pas** que l'exécution
    #: réelle sera assez rapide.
    LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER = "LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER"
    LATENCY_INDETERMINATE = "LATENCY_INDETERMINATE"


def messaging_layer_verdict(
    observations: list[LatencyObservation],
    horizon_ns: int,
    percentile: float = 0.95,
    min_clusters: int = 20,
) -> tuple[LatencyVerdictQ51, str]:
    """Verdict asymétrique fondé sur la borne inférieure observable.

    Une bonne latence d'aller-retour ne démontre rien sur l'exécution réelle ; une mauvaise
    borne inférieure, elle, suffit à conclure.
    """
    usable = [o for o in observations if o.quality is not MeasurementQuality.MEASUREMENT_INVALID]
    if not usable:
        return LatencyVerdictQ51.LATENCY_INDETERMINATE, "aucune observation exploitable"

    clusters = {o.cluster_id for o in usable}
    if len(clusters) < min_clusters:
        return (
            LatencyVerdictQ51.LATENCY_INDETERMINATE,
            f"{len(clusters)} grappes indépendantes sur {min_clusters} requises",
        )

    bounds = sorted(o.observable_lower_bound_ns for o in usable)
    idx = min(len(bounds) - 1, int(percentile * len(bounds)))
    p = bounds[idx]

    if p >= horizon_ns:
        return (
            LatencyVerdictQ51.LATENCY_NON_VIABLE,
            f"borne inférieure observable p{int(percentile * 100)} = {p / NS_PER_MS:.0f} ms "
            f"≥ horizon {horizon_ns / NS_PER_MS:.0f} ms — concluant sans campagne d'exécution",
        )
    return (
        LatencyVerdictQ51.LATENCY_NOT_EXCLUDED_AT_MESSAGING_LAYER,
        f"borne inférieure observable p{int(percentile * 100)} = {p / NS_PER_MS:.0f} ms ; "
        "les composantes non mesurées peuvent encore l'exclure",
    )


# ------------------------------------------------------ distributions conditionnelles


@dataclass(frozen=True)
class LatencyDistribution:
    name: str
    burst_state: BurstState | None
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    maximum: float
    sample_count: int
    independent_cluster_count: int
    observability: Observability
    contains: tuple[str, ...]

    @property
    def is_decomposable(self) -> bool:
        return self.observability is Observability.OBSERVED


def summarize(
    observations: list[LatencyObservation],
    interval_name: str,
    burst_state: BurstState | None = None,
) -> LatencyDistribution | None:
    """Distribution conditionnelle d'un intervalle nommé.

    Le conditionnement par état de rafale n'est pas un raffinement : la latence se dégrade
    précisément quand les signaux apparaissent, de sorte que la distribution marginale
    sous-estime celle qui compte.
    """
    import numpy as np

    selected = [
        (o, i)
        for o in observations
        for i in o.intervals
        if i.name == interval_name and i.duration_ns is not None
        and (burst_state is None or o.burst.state is burst_state)
    ]
    if not selected:
        return None

    values = np.array([i.duration_ns for _, i in selected], dtype=float)
    q = np.quantile(values, [0.5, 0.75, 0.90, 0.95, 0.99])
    first = selected[0][1]
    return LatencyDistribution(
        name=interval_name,
        burst_state=burst_state,
        p50=float(q[0]), p75=float(q[1]), p90=float(q[2]),
        p95=float(q[3]), p99=float(q[4]),
        maximum=float(values.max()),
        sample_count=len(values),
        independent_cluster_count=len({o.cluster_id for o, _ in selected}),
        observability=first.observability,
        contains=first.contains,
    )


# ------------------------------------------------------------- effet observateur


@dataclass(frozen=True)
class PerturbationCheck:
    """La campagne de mesure peut elle-même allonger la latence qu'elle mesure."""

    with_logging_p95_ns: float
    reduced_logging_p95_ns: float
    sample_count: int

    @property
    def overhead_ns(self) -> float:
        return self.with_logging_p95_ns - self.reduced_logging_p95_ns

    def is_material(self, threshold_ratio: float = 0.05) -> bool:
        if self.reduced_logging_p95_ns <= 0:
            return True
        return self.overhead_ns / self.reduced_logging_p95_ns > threshold_ratio


def measurement_quality(
    sync: ClockSyncStatus,
    connection: ConnectionState,
    clock_discontinuities: int,
    perturbation: PerturbationCheck | None = None,
) -> MeasurementQuality:
    if sync.state is ClockSyncState.CLOCK_UNSTABLE or clock_discontinuities > 0:
        return MeasurementQuality.MEASUREMENT_INVALID
    if connection in (ConnectionState.RECONNECTING, ConnectionState.DISCONNECTED):
        return MeasurementQuality.MEASUREMENT_INVALID
    degraded = (
        sync.state in (ClockSyncState.SYNC_DEGRADED, ClockSyncState.SYNC_UNKNOWN)
        or connection in (ConnectionState.DEGRADED, ConnectionState.CONNECTED_RECOVERED)
        or (perturbation is not None and perturbation.is_material())
    )
    return (
        MeasurementQuality.MEASUREMENT_DEGRADED if degraded
        else MeasurementQuality.MEASUREMENT_VALID
    )


# ------------------------------------------------------------------ campagne


class ProbePhase(str, Enum):
    #: Journalisation passive. Aucun ordre. Démarre immédiatement.
    A_PASSIVE = "A_PASSIVE"
    #: Probes de messagerie. Exige Q42 si un ordre réel peut être créé.
    B_MESSAGING = "B_MESSAGING"
    #: Micro-exécutions. Bloquée tant que Q42 n'est pas résolue.
    C_MICRO_EXECUTION = "C_MICRO_EXECUTION"


@dataclass(frozen=True)
class CampaignPolicy:
    """Politique d'une campagne, avec sa probabilité d'échantillonnage.

    Les probes ne doivent pas se concentrer sur les périodes calmes : Q19 sous-estimerait
    alors la latence conditionnelle. La probabilité de sélection est conservée pour que la
    distribution puisse être repondérée.
    """

    phase: ProbePhase
    sampling_policy_version: str
    probability_by_burst: dict[str, float]
    max_active_orders: int
    budget_approved: bool
    kill_switch_armed: bool

    def authorize(self, creates_real_order: bool) -> None:
        if creates_real_order and not (self.budget_approved and self.kill_switch_armed):
            raise JournalError(
                "Tout probe capable de créer un ordre réel reste bloqué tant que le budget "
                "et le coupe-circuit ne sont pas définis (Q42). La journalisation passive, "
                "elle, démarre sans condition."
            )
        if self.phase is ProbePhase.C_MICRO_EXECUTION and not self.budget_approved:
            raise JournalError("La phase de micro-exécutions exige la résolution de Q42.")

    def weight_for(self, state: BurstState) -> float:
        """Poids de repondération : l'inverse de la probabilité de sélection."""
        p = self.probability_by_burst.get(state.value, 0.0)
        if p <= 0:
            return 0.0
        return 1.0 / p
