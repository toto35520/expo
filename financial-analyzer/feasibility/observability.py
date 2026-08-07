"""Contrat d'observabilité de la latence (Q57 + Q58).

Ce module ne mesure pas la performance : il établit **ce qui peut être revendiqué**. Q57
qualifie les horloges, Q58 qualifie la sémantique du connecteur, et leur intersection
produit la seule décomposition que Q19 est autorisé à utiliser.

Deux principes structurants, encodés plutôt qu'énoncés :

1. **Une durée se calcule entre deux frontières**, jamais par addition d'intervalles. Deux
   intervalles peuvent se chevaucher — l'aller-retour d'émission contient déjà des
   mécanismes représentables ailleurs — et les sommer double-compte silencieusement.
2. **Le nom d'un rappel n'a aucune valeur probatoire.** `on_order_accepted()` ne démontre
   pas qu'un ordre est actif sur le marché.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000

#: Nombre minimal de lectures appariées murale/monotone pour considérer le comportement
#: des deux horloges comme instrumenté (§38, critère 3).
MIN_WALL_MONO_SAMPLES = 1_000


class ObservabilityError(ValueError):
    """Revendication non fondée par le contrat d'observabilité."""


# ============================================================ Q57 — horloges


class ClockQualification(str, Enum):
    #: Durées locales et comparaisons inter-systèmes dans l'incertitude déclarée.
    CLOCK_QUALIFIED = "CLOCK_QUALIFIED"
    #: Durées locales monotones seulement. Décomposition inter-systèmes interdite.
    CLOCK_QUALIFIED_LOCAL_ONLY = "CLOCK_QUALIFIED_LOCAL_ONLY"
    #: Mesures possibles, incertitude importante à publier.
    CLOCK_DEGRADED = "CLOCK_DEGRADED"
    #: Seul l'ordre des événements locaux est éventuellement exploitable.
    CLOCK_UNQUALIFIED = "CLOCK_UNQUALIFIED"


class CorrectionMode(str, Enum):
    #: L'heure murale saute — les durées inter-systèmes traversant l'événement sont censurées.
    STEP = "STEP"
    #: L'horloge est progressivement accélérée ou ralentie — la monotone reste utilisable.
    SLEW = "SLEW"
    UNKNOWN = "UNKNOWN"


class Virtualization(str, Enum):
    BARE_METAL = "BARE_METAL"
    VM = "VM"
    CONTAINER = "CONTAINER"
    UNKNOWN = "UNKNOWN"


class ResolutionClass(str, Enum):
    """Rapport entre incertitude et durée mesurée. Seuils versionnés, mesure inchangée."""

    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    USABLE = "USABLE"
    DEGRADED = "DEGRADED"
    NOT_RESOLVABLE = "NOT_RESOLVABLE"


def resolution_class(uncertainty_ns: float, estimated_ns: float) -> ResolutionClass:
    if estimated_ns <= 0:
        return ResolutionClass.NOT_RESOLVABLE
    r = uncertainty_ns / estimated_ns
    if r <= 0.10:
        return ResolutionClass.HIGH_CONFIDENCE
    if r <= 0.25:
        return ResolutionClass.USABLE
    if r <= 0.50:
        return ResolutionClass.DEGRADED
    return ResolutionClass.NOT_RESOLVABLE


@dataclass(frozen=True)
class GranularityTest:
    """Résolution **effective**, mesurée sur une série d'appels.

    Une horloge affichant des nanosecondes ne fournit pas nécessairement une précision
    nanoseconde : c'est le plus petit écart non nul réellement observé qui compte.
    """

    minimum_non_zero_step_ns: int
    median_step_ns: float
    p99_step_ns: float
    duplicate_timestamp_rate: float

    def limits(self, typical_latency_ns: float, fraction: float = 0.10) -> bool:
        """Vrai si la granularité représente une part importante de la latence mesurée."""
        if typical_latency_ns <= 0:
            return True
        return self.minimum_non_zero_step_ns / typical_latency_ns > fraction


@dataclass(frozen=True)
class ClockCapability:
    """Ce que l'horloge d'un hôte permet réellement d'affirmer."""

    host_id: str
    wall_clock_source: str
    monotonic_clock_source: str
    sync_method: str
    sync_server: str | None
    advertised_accuracy_ns: int | None
    measured_uncertainty_ns: int | None
    correction_mode: CorrectionMode
    virtualization_state: Virtualization
    monotonic_resolution_ns: int
    wall_resolution_ns: int
    qualification: ClockQualification
    qualified_at_ns: int
    qualification_version: str
    monotonic_failures: int = 0
    wall_discontinuities: int = 0
    drift_p95_ppm: float = 0.0
    suspend_events: int = 0
    requalification_required: bool = False
    #: Lectures appariées murale/monotone ayant servi à instrumenter le couple.
    wall_mono_samples: int = 0
    #: Vrai lorsque l'incertitude inter-systèmes a été **cherchée** et déclarée
    #: introuvable, plutôt que simplement jamais mesurée. La distinction est le cœur du
    #: critère 5 de §38 : ignorer et avoir constaté l'ignorance ne se valent pas.
    intersystem_uncertainty_declared_unknown: bool = False

    def __post_init__(self) -> None:
        if self.qualification is ClockQualification.CLOCK_QUALIFIED and (
            self.measured_uncertainty_ns is None
        ):
            raise ObservabilityError(
                "Une horloge ne peut être qualifiée pour l'inter-systèmes sans incertitude "
                "**mesurée**. La précision annoncée par la source ne suffit pas."
            )

    @property
    def intersystem_usable(self) -> bool:
        return (
            self.qualification is ClockQualification.CLOCK_QUALIFIED
            and not self.requalification_required
            and self.monotonic_failures == 0
        )

    @property
    def local_usable(self) -> bool:
        return (
            self.qualification is not ClockQualification.CLOCK_UNQUALIFIED
            and self.monotonic_failures == 0
        )

    def can_publish(self, claimed_precision_ns: int) -> bool:
        """Aucun résultat ne s'affiche plus finement que l'incertitude qualifiée."""
        u = self.measured_uncertainty_ns
        if u is None:
            return False
        return claimed_precision_ns >= u


def qualify_clock(
    host_id: str,
    granularity_wall: GranularityTest,
    granularity_monotonic: GranularityTest,
    monotonic_failures: int,
    wall_discontinuities: int,
    drift_p95_ppm: float,
    measured_uncertainty_ns: int | None,
    correction_mode: CorrectionMode,
    virtualization: Virtualization,
    suspend_events: int,
    sync_method: str,
    qualified_at_ns: int,
    version: str = "Q57_CLOCK_1.0",
    sync_server: str | None = None,
    advertised_accuracy_ns: int | None = None,
    wall_mono_samples: int = 0,
    intersystem_uncertainty_declared_unknown: bool = False,
) -> ClockCapability:
    """Détermine le statut d'une horloge à partir de ses mesures.

    Une synchronisation médiocre n'empêche pas de **résoudre** Q57 : elle réduit
    seulement le domaine mesurable. Déclarer correctement l'inconnu est une résolution
    valide.
    """
    requalification = suspend_events > 0

    if monotonic_failures > 0:
        qualification = ClockQualification.CLOCK_UNQUALIFIED
    elif measured_uncertainty_ns is None:
        # Incertitude inter-systèmes non mesurée : le local reste utilisable, pas le reste.
        qualification = ClockQualification.CLOCK_QUALIFIED_LOCAL_ONLY
    elif correction_mode is CorrectionMode.STEP or wall_discontinuities > 0:
        qualification = ClockQualification.CLOCK_DEGRADED
    elif drift_p95_ppm > 100.0:
        qualification = ClockQualification.CLOCK_DEGRADED
    else:
        qualification = ClockQualification.CLOCK_QUALIFIED

    return ClockCapability(
        host_id=host_id,
        wall_clock_source="wall",
        monotonic_clock_source="monotonic",
        sync_method=sync_method,
        sync_server=sync_server,
        advertised_accuracy_ns=advertised_accuracy_ns,
        measured_uncertainty_ns=measured_uncertainty_ns,
        correction_mode=correction_mode,
        virtualization_state=virtualization,
        monotonic_resolution_ns=granularity_monotonic.minimum_non_zero_step_ns,
        wall_resolution_ns=granularity_wall.minimum_non_zero_step_ns,
        qualification=qualification,
        qualified_at_ns=qualified_at_ns,
        qualification_version=version,
        monotonic_failures=monotonic_failures,
        wall_discontinuities=wall_discontinuities,
        drift_p95_ppm=drift_p95_ppm,
        suspend_events=suspend_events,
        requalification_required=requalification,
        wall_mono_samples=wall_mono_samples,
        intersystem_uncertainty_declared_unknown=intersystem_uncertainty_declared_unknown,
    )


def q57_resolved(clock: ClockCapability) -> tuple[bool, tuple[str, ...]]:
    """Critère de passage Q57 (§38) — cinq conditions, aucune n'exigeant la perfection.

    Une synchronisation médiocre n'empêche pas de résoudre Q57 : elle réduit le domaine
    mesurable. Ce qui bloque la résolution, c'est l'ignorance non constatée.
    """
    missing: list[str] = []
    if clock.monotonic_failures > 0:
        missing.append("l'horloge monotone a reculé : la session est invalidée")
    if clock.monotonic_resolution_ns <= 0:
        missing.append("résolution monotone effective non mesurée")
    if clock.wall_mono_samples < MIN_WALL_MONO_SAMPLES:
        missing.append(
            f"couple murale/monotone insuffisamment instrumenté "
            f"({clock.wall_mono_samples} lectures sur {MIN_WALL_MONO_SAMPLES})"
        )
    if not clock.sync_method or clock.sync_method.upper() == "UNKNOWN":
        missing.append("méthode de synchronisation inconnue")
    if clock.measured_uncertainty_ns is None and not (
        clock.intersystem_uncertainty_declared_unknown
    ):
        missing.append(
            "incertitude inter-systèmes ni estimée ni explicitement déclarée inconnue"
        )
    return not missing, tuple(missing)


# ============================================================ Q58 — connecteur


class EvidenceType(str, Enum):
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    API_SCHEMA = "API_SCHEMA"
    BROKER_SUPPORT_CONFIRMATION = "BROKER_SUPPORT_CONFIRMATION"
    CONTROLLED_TEST = "CONTROLLED_TEST"
    PACKET_TRACE = "PACKET_TRACE"
    CONNECTOR_SOURCE_CODE = "CONNECTOR_SOURCE_CODE"
    OBSERVATIONAL_INFERENCE = "OBSERVATIONAL_INFERENCE"

    @property
    def is_probative(self) -> bool:
        """L'inférence seule ne transforme jamais un événement ambigu en observé."""
        return self is not EvidenceType.OBSERVATIONAL_INFERENCE


class SubmitReturnSemantics(str, Enum):
    LOCAL_QUEUE_ACCEPTED = "LOCAL_QUEUE_ACCEPTED"
    SOCKET_WRITTEN = "SOCKET_WRITTEN"
    SERVER_RECEIVED = "SERVER_RECEIVED"
    SERVER_VALIDATED = "SERVER_VALIDATED"
    ORDER_CREATED = "ORDER_CREATED"
    UNKNOWN = "UNKNOWN"


class AckSemantics(str, Enum):
    RPC_RESPONSE_ONLY = "RPC_RESPONSE_ONLY"
    ORDER_RECEIVED = "ORDER_RECEIVED"
    ORDER_VALIDATED = "ORDER_VALIDATED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_ACTIVE = "ORDER_ACTIVE"
    UNKNOWN = "UNKNOWN"


class RejectKind(str, Enum):
    LOCAL_VALIDATION_REJECT = "LOCAL_VALIDATION_REJECT"
    BROKER_REJECT = "BROKER_REJECT"
    MARKET_REJECT = "MARKET_REJECT"
    #: Un délai d'attente **n'est pas** un rejet : l'état reste inconnu jusqu'à
    #: réconciliation.
    TIMEOUT_UNKNOWN_STATE = "TIMEOUT_UNKNOWN_STATE"


class ClockDomain(str, Enum):
    LOCAL_MONOTONIC = "LOCAL_MONOTONIC"
    LOCAL_WALL = "LOCAL_WALL"
    BROKER = "BROKER"
    PROVIDER = "PROVIDER"
    EXCHANGE = "EXCHANGE"
    NONE = "NONE"


class MessageKind(str, Enum):
    """Un retour d'appel distant et un événement courtier portent deux informations
    différentes, même s'ils arrivent presque simultanément."""

    RPC_RESPONSE = "RPC_RESPONSE"
    BROKER_EVENT = "BROKER_EVENT"
    MARKET_EVENT = "MARKET_EVENT"
    LOCAL_EVENT = "LOCAL_EVENT"


@dataclass(frozen=True)
class EventSemantics:
    """Sémantique **prouvée** d'un événement du connecteur."""

    event_name: str
    observable: bool
    meaning: str
    message_kind: MessageKind
    timestamp_available: bool
    clock_domain: ClockDomain
    evidence_type: EvidenceType
    evidence_id: str
    ordering_guaranteed: bool

    def __post_init__(self) -> None:
        if self.observable and not self.evidence_id.strip():
            raise ObservabilityError(
                f"{self.event_name} déclaré observable sans preuve. Le nom d'un rappel n'a "
                "aucune valeur probatoire."
            )
        if self.timestamp_available and self.clock_domain is ClockDomain.NONE:
            raise ObservabilityError(
                f"{self.event_name} : un horodatage doit déclarer son domaine d'horloge. "
                "Sans lui, aucune comparaison inter-systèmes n'est fondée."
            )

    @property
    def is_probative(self) -> bool:
        return self.observable and self.evidence_type.is_probative


class OrderState(str, Enum):
    """État d'un ordre après une réponse — ou après son absence."""

    REJECTED = "REJECTED"
    #: Ni accepté ni rejeté. Aucune action ne peut supposer l'un ou l'autre.
    UNKNOWN_PENDING_RECONCILIATION = "UNKNOWN_PENDING_RECONCILIATION"


def state_after_reject(kind: RejectKind) -> OrderState:
    """Un délai dépassé n'est pas un rejet (§23, §27).

    Le résoudre en rejet autoriserait l'émission d'un second ordre alors que le premier
    existe peut-être déjà chez le courtier — une position double au lieu d'une.
    """
    if kind is RejectKind.TIMEOUT_UNKNOWN_STATE:
        return OrderState.UNKNOWN_PENDING_RECONCILIATION
    return OrderState.REJECTED


#: Événements dont la sémantique doit être qualifiée avant usage dans Q19 (§17).
QUALIFIABLE_EVENTS = (
    "SUBMIT_STARTED",
    "SUBMIT_RETURNED",
    "BROKER_ACK",
    "BROKER_REJECT",
    "ORDER_ACTIVE",
    "CANCEL_STARTED",
    "CANCEL_ACK",
    "PARTIAL_FILL",
    "FULL_FILL",
)


@dataclass(frozen=True)
class BrokerConnectorCapability:
    connector_id: str
    connector_version: str
    broker: str
    account_type: str
    submit_return_semantics: SubmitReturnSemantics
    ack_semantics: AckSemantics
    rejection_semantics: str
    cancel_semantics: str
    order_active_observable: bool
    broker_receive_timestamp_available: bool
    broker_accept_timestamp_available: bool
    fill_timestamp_available: bool
    timestamp_clock_domain: ClockDomain | None
    events: tuple[EventSemantics, ...]
    reconciliation_available: bool
    qualification_status: str
    #: Couples (avant, après) réellement garantis par le connecteur. Le journal
    #: n'impose que ceux-là : une API peut délivrer un rappel avant le retour de l'appel.
    guaranteed_orderings: tuple[tuple[str, str], ...] = ()
    qualification_version: str = "Q58_CONNECTOR_1.0"

    @property
    def ack_implies_active(self) -> bool:
        """`BROKER_ACK` et `ORDER_ACTIVE` sont structurellement distincts tant que
        l'activation n'est pas observable."""
        return self.ack_semantics is AckSemantics.ORDER_ACTIVE and self.order_active_observable

    def semantics_of(self, event_name: str) -> EventSemantics | None:
        return next((e for e in self.events if e.event_name == event_name), None)

    @property
    def unqualified_events(self) -> tuple[str, ...]:
        return tuple(e.event_name for e in self.events if not e.is_probative)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({e.evidence_id for e in self.events if e.evidence_id.strip()}))

    def guarantees_order(self, before: str, after: str) -> bool:
        return (before, after) in self.guaranteed_orderings

    def invalidated_by(self, newer: "BrokerConnectorCapability") -> bool:
        """Une mise à jour du connecteur périme la qualification (§32).

        Un changement de SDK peut modifier rappels, tamponnage, ordre des événements,
        horodatages et reprises. Les conclusions précédentes ne sont **pas** supposées
        valables.
        """
        return (
            newer.connector_id == self.connector_id
            and (
                newer.connector_version != self.connector_version
                or newer.qualification_version != self.qualification_version
            )
        )


def q58_resolved(
    capability: BrokerConnectorCapability, used_in_q19: Iterable[str]
) -> tuple[bool, tuple[str, ...]]:
    """Critère de passage Q58 (§39).

    Chaque événement utilisé dans Q19 doit porter sémantique, preuve, domaine d'horloge,
    garantie d'ordre déclarée et statut d'identifiabilité. **Un événement non identifiable
    est acceptable ; l'ambiguïté non documentée ne l'est pas.**
    """
    missing: list[str] = []
    for name in used_in_q19:
        e = capability.semantics_of(name)
        if e is None:
            missing.append(f"{name} : aucune sémantique déclarée")
            continue
        if not e.observable:
            # Déclarer l'inobservabilité **est** une qualification valide.
            continue
        if not e.is_probative:
            missing.append(f"{name} : sémantique fondée sur une inférence seule")
        if not e.meaning.strip():
            missing.append(f"{name} : signification non documentée")
        if e.timestamp_available and e.clock_domain is ClockDomain.NONE:
            missing.append(f"{name} : horodatage sans domaine d'horloge")
    if not capability.reconciliation_available:
        missing.append(
            "aucune réconciliation disponible : un état inconnu resterait irrésolu"
        )
    return not missing, tuple(missing)


def load_capability(path: str) -> BrokerConnectorCapability:
    """Lit une fiche `broker-connector-capability.json`.

    Toute valeur absente est lue comme inconnue, jamais comme favorable : une fiche
    incomplète produit des bornes prudentes, pas des permissions par défaut.
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    def enum_or_unknown(cls, key):
        try:
            return cls(raw.get(key, "UNKNOWN"))
        except ValueError:
            raise ObservabilityError(
                f"{key} = {raw.get(key)!r} n'est pas une sémantique reconnue. "
                "Une valeur non prévue ne peut pas être interprétée favorablement."
            ) from None

    events = tuple(
        EventSemantics(
            event_name=e["event_name"],
            observable=bool(e.get("observable", False)),
            meaning=e.get("meaning", ""),
            message_kind=MessageKind(e.get("message_kind", "BROKER_EVENT")),
            timestamp_available=bool(e.get("timestamp_available", False)),
            clock_domain=ClockDomain(e.get("clock_domain", "NONE")),
            evidence_type=EvidenceType(e.get("evidence_type", "OBSERVATIONAL_INFERENCE")),
            evidence_id=e.get("evidence_id", ""),
            ordering_guaranteed=bool(e.get("ordering_guaranteed", False)),
        )
        for e in raw.get("events", ())
    )
    domain = raw.get("timestamp_clock_domain")
    return BrokerConnectorCapability(
        connector_id=raw.get("connector_id", "UNKNOWN"),
        connector_version=raw.get("connector_version", "UNKNOWN"),
        broker=raw.get("broker", "UNKNOWN"),
        account_type=raw.get("account_type", "UNKNOWN"),
        submit_return_semantics=enum_or_unknown(
            SubmitReturnSemantics, "submit_return_semantics"),
        ack_semantics=enum_or_unknown(AckSemantics, "ack_semantics"),
        rejection_semantics=raw.get("rejection_semantics", "UNKNOWN"),
        cancel_semantics=raw.get("cancel_semantics", "UNKNOWN"),
        order_active_observable=bool(raw.get("order_active_observable", False)),
        broker_receive_timestamp_available=bool(
            raw.get("broker_receive_timestamp_available", False)),
        broker_accept_timestamp_available=bool(
            raw.get("broker_accept_timestamp_available", False)),
        fill_timestamp_available=bool(raw.get("fill_timestamp_available", False)),
        timestamp_clock_domain=ClockDomain(domain) if domain else None,
        events=events,
        reconciliation_available=bool(raw.get("reconciliation_available", False)),
        qualification_status=raw.get("qualification_status", "UNQUALIFIED"),
        guaranteed_orderings=tuple(
            (a, b) for a, b in raw.get("guaranteed_orderings", ())
        ),
        qualification_version=raw.get("qualification_version", "Q58_CONNECTOR_1.0"),
    )


def blank_capability(broker: str, account_type: str) -> BrokerConnectorCapability:
    """Fiche vide — à remplir **uniquement** avec ce qui est démontré.

    Une fiche déclarant tout inconnu vaut mieux qu'une fausse précision : elle produit
    des bornes honnêtes là où une supposition produirait des verdicts faux.
    """
    return BrokerConnectorCapability(
        connector_id=f"{broker}:{account_type}",
        connector_version="UNKNOWN",
        broker=broker,
        account_type=account_type,
        submit_return_semantics=SubmitReturnSemantics.UNKNOWN,
        ack_semantics=AckSemantics.UNKNOWN,
        rejection_semantics="UNKNOWN",
        cancel_semantics="UNKNOWN",
        order_active_observable=False,
        broker_receive_timestamp_available=False,
        broker_accept_timestamp_available=False,
        fill_timestamp_available=False,
        timestamp_clock_domain=None,
        events=(),
        reconciliation_available=False,
        qualification_status="UNQUALIFIED",
    )


# ================================================= frontières et chemin de latence


class BoundaryQuality(str, Enum):
    EXACT_LOCAL = "EXACT_LOCAL"
    QUALIFIED_INTERSYSTEM = "QUALIFIED_INTERSYSTEM"
    DEGRADED_CLOCK = "DEGRADED_CLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LatencyBoundary:
    """Instant nommé sur le chemin critique.

    Une frontière absente porte `timestamp_ns = None` : le segment qui la borde devient
    non identifiable, il n'est jamais estimé.
    """

    name: str
    timestamp_ns: int | None
    clock_domain: ClockDomain
    quality: BoundaryQuality

    @property
    def known(self) -> bool:
        return self.timestamp_ns is not None and self.quality is not BoundaryQuality.UNKNOWN


class SegmentStatus(str, Enum):
    OBSERVED = "OBSERVED"
    QUALIFIED_INTERSYSTEM = "QUALIFIED_INTERSYSTEM"
    NOT_RESOLVABLE_INTERSYSTEM = "NOT_RESOLVABLE_INTERSYSTEM"
    NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"


@dataclass(frozen=True)
class PathSegment:
    from_boundary: str
    to_boundary: str
    duration_ns: int | None
    status: SegmentStatus
    uncertainty_ns: int = 0

    @property
    def counts_toward_bound(self) -> bool:
        return self.duration_ns is not None and self.status in (
            SegmentStatus.OBSERVED,
            SegmentStatus.QUALIFIED_INTERSYSTEM,
        )


@dataclass(frozen=True)
class LatencyPath:
    """Chemin critique décrit par ses **frontières**, jamais par ses durées.

    C'est ce qui rend le double comptage structurellement impossible : deux segments
    consécutifs sont disjoints par construction, alors que deux intervalles nommés
    peuvent se recouvrir — l'aller-retour d'émission contient déjà des mécanismes
    représentables ailleurs.
    """

    boundaries: tuple[LatencyBoundary, ...]
    clock: ClockCapability | None = None

    def __post_init__(self) -> None:
        known = [b for b in self.boundaries if b.known]
        for a, b in zip(known[:-1], known[1:]):
            if a.clock_domain is b.clock_domain and b.timestamp_ns < a.timestamp_ns:
                raise ObservabilityError(
                    f"Frontières hors ordre dans le même domaine : {a.name} → {b.name}."
                )

    def _segment(self, a: LatencyBoundary, b: LatencyBoundary) -> PathSegment:
        if not (a.known and b.known):
            return PathSegment(a.name, b.name, None, SegmentStatus.NOT_IDENTIFIABLE)

        same_domain = a.clock_domain is b.clock_domain
        if same_domain:
            return PathSegment(
                a.name, b.name, b.timestamp_ns - a.timestamp_ns, SegmentStatus.OBSERVED
            )

        # Domaines différents : la comparaison n'a de sens que si l'horloge est qualifiée
        # pour l'inter-systèmes, et l'incertitude doit rester petite devant la durée.
        if self.clock is None or not self.clock.intersystem_usable:
            return PathSegment(
                a.name, b.name, None, SegmentStatus.NOT_RESOLVABLE_INTERSYSTEM
            )
        duration = b.timestamp_ns - a.timestamp_ns
        u = self.clock.measured_uncertainty_ns or 0
        if resolution_class(u, duration) is ResolutionClass.NOT_RESOLVABLE:
            return PathSegment(
                a.name, b.name, None, SegmentStatus.NOT_RESOLVABLE_INTERSYSTEM, u
            )
        return PathSegment(
            a.name, b.name, duration, SegmentStatus.QUALIFIED_INTERSYSTEM, u
        )

    def segments(self) -> tuple[PathSegment, ...]:
        return tuple(
            self._segment(a, b) for a, b in zip(self.boundaries[:-1], self.boundaries[1:])
        )

    def certain_lower_bound_ns(self) -> int:
        """Somme des segments **consécutifs et disjoints** réellement mesurés.

        Aucun risque de double comptage : les segments partagent leurs frontières et ne
        se recouvrent donc jamais. Ce qui n'est pas mesuré n'est pas compté, ce qui fait
        de cette valeur une borne inférieure au sens strict.
        """
        return sum(s.duration_ns or 0 for s in self.segments() if s.counts_toward_bound)

    def critical_path_ns(self) -> int | None:
        """Durée réellement vécue, de la première à la dernière frontière connue.

        C'est la vue qui sert au verdict de faisabilité — la décomposition par composante
        sert au diagnostic d'optimisation.
        """
        known = [b for b in self.boundaries if b.known]
        if len(known) < 2:
            return None
        first, last = known[0], known[-1]
        if first.clock_domain is not last.clock_domain:
            if self.clock is None or not self.clock.intersystem_usable:
                return None
        return last.timestamp_ns - first.timestamp_ns

    def unknown_segments(self) -> tuple[PathSegment, ...]:
        return tuple(s for s in self.segments() if not s.counts_toward_bound)

    def coverage(self) -> float:
        """Part du chemin critique couverte par des segments mesurés."""
        total = self.critical_path_ns()
        if not total:
            return 0.0
        return min(1.0, self.certain_lower_bound_ns() / total)


# ================================================= matrice et verdict global


class ComponentStatus(str, Enum):
    OBSERVED = "OBSERVED"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    #: La durée observée ne couvre qu'une partie certaine du chemin total.
    LOWER_BOUND = "LOWER_BOUND"
    NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"


class MeasurementGrade(str, Enum):
    """Qualité d'une mesure individuelle (§37)."""

    EXACT_LOCAL = "EXACT_LOCAL"
    QUALIFIED_INTERSYSTEM = "QUALIFIED_INTERSYSTEM"
    AGGREGATE = "AGGREGATE"
    LOWER_BOUND = "LOWER_BOUND"
    DEGRADED_CLOCK = "DEGRADED_CLOCK"
    UNKNOWN = "UNKNOWN"


def group_by_grade(
    measurements: Iterable[tuple[MeasurementGrade, int]],
) -> dict[MeasurementGrade, tuple[int, ...]]:
    """Sépare les mesures par qualité — le rapport ne les mélange jamais d'office.

    Un p95 calculé en confondant des durées exactes et des durées à horloge dégradée
    décrit la répartition des qualités de mesure autant que la latence elle-même.
    """
    grouped: dict[MeasurementGrade, list[int]] = {}
    for grade, value in measurements:
        grouped.setdefault(grade, []).append(value)
    return {g: tuple(v) for g, v in grouped.items()}


@dataclass(frozen=True)
class ComponentContract:
    component: str
    status: ComponentStatus
    uncertainty_ns: int | None
    contains: tuple[str, ...] = ()
    rationale: str = ""


class ObservabilityVerdict(str, Enum):
    #: Chemin critique et principales frontières inter-systèmes observables. Rare.
    FULLY_QUALIFIED = "FULLY_QUALIFIED"
    #: Les composantes locales et certains agrégats suffisent à une borne inférieure fiable.
    SUFFICIENT_FOR_LOWER_BOUND = "SUFFICIENT_FOR_LOWER_BOUND"
    #: Seule la partie interne du système est qualifiée.
    LOCAL_ONLY = "LOCAL_ONLY"
    #: Ni les horloges ni les sémantiques ne permettent une borne exploitable.
    INSUFFICIENT_FOR_Q19 = "INSUFFICIENT_FOR_Q19"


@dataclass(frozen=True)
class ObservabilityMatrix:
    """Seule décomposition que Q19 est autorisé à utiliser.

    Aucune métrique de Q19 ne peut être plus fine que ce contrat.
    """

    clock: ClockCapability
    connector: BrokerConnectorCapability
    components: tuple[ComponentContract, ...]
    verdict: ObservabilityVerdict

    def status_of(self, component: str) -> ComponentStatus:
        c = next((x for x in self.components if x.component == component), None)
        return c.status if c else ComponentStatus.NOT_IDENTIFIABLE

    def authorize(self, component: str) -> None:
        """Refuse toute attribution plus fine que le contrat."""
        if self.status_of(component) is ComponentStatus.NOT_IDENTIFIABLE:
            raise ObservabilityError(
                f"« {component} » n'est pas identifiable sur cette infrastructure. "
                "Q19 ne peut pas lui attribuer de durée."
            )


def build_matrix(
    clock: ClockCapability, connector: BrokerConnectorCapability
) -> ObservabilityMatrix:
    """Croise qualification d'horloge et sémantique du connecteur.

    Le résultat est volontairement pessimiste : une composante n'est déclarée observable
    que si **les deux** la rendent observable.
    """
    u = clock.measured_uncertainty_ns
    inter = clock.intersystem_usable
    local = clock.local_usable

    def local_component(name: str) -> ComponentContract:
        return ComponentContract(
            name,
            ComponentStatus.OBSERVED if local else ComponentStatus.NOT_IDENTIFIABLE,
            clock.monotonic_resolution_ns if local else None,
            rationale="horloge monotone locale" if local else "horloge non qualifiée",
        )

    components: list[ComponentContract] = [
        local_component("evaluation_wait"),
        local_component("compute"),
        local_component("decision"),
    ]

    components.append(ComponentContract(
        "provider_to_local_receive",
        ComponentStatus.AGGREGATE_ONLY if inter else ComponentStatus.NOT_IDENTIFIABLE,
        u if inter else None,
        contains=("matching_publication", "provider_aggregation", "provider_distribution",
                  "transport_network", "local_buffering"),
        rationale="horodatage fournisseur comparé au local"
        if inter else "domaines d'horloge non qualifiés pour l'inter-systèmes",
    ))

    # Mesurer l'aller-retour suppose qu'un accusé **prouvé** existe. Sans lui, la
    # composante n'est pas « agrégée » : elle est absente. Un connecteur dont l'accusé
    # n'est pas démontré ne fournit pas un agrégat grossier, il ne fournit rien.
    ack_event = connector.semantics_of("BROKER_ACK")
    ack_observable = ack_event is not None and ack_event.is_probative

    submit_ack_observed = (
        ack_observable
        and connector.broker_receive_timestamp_available
        and connector.broker_accept_timestamp_available
        and inter
    )
    if submit_ack_observed:
        submit_status = ComponentStatus.OBSERVED
        submit_why = "horodatages courtier disponibles et horloge qualifiée"
    elif ack_observable and local:
        submit_status = ComponentStatus.AGGREGATE_ONLY
        submit_why = "aller-retour mesuré localement, composantes confondues"
    else:
        submit_status = ComponentStatus.NOT_IDENTIFIABLE
        submit_why = (
            "aucun événement d'accusé prouvé" if not ack_observable
            else "horloge locale non qualifiée"
        )
    components.append(ComponentContract(
        "submit_to_ack",
        submit_status,
        clock.monotonic_resolution_ns
        if submit_status is not ComponentStatus.NOT_IDENTIFIABLE else None,
        contains=() if submit_status is not ComponentStatus.AGGREGATE_ONLY else
        ("local_outbound_queue", "outbound_network", "broker_processing",
         "inbound_network", "local_callback_dispatch"),
        rationale=submit_why,
    ))

    for name in ("outbound_network", "broker_processing", "inbound_network"):
        components.append(ComponentContract(
            name,
            ComponentStatus.OBSERVED if submit_ack_observed
            else ComponentStatus.NOT_IDENTIFIABLE,
            u if submit_ack_observed else None,
            rationale="" if submit_ack_observed
            else "aucun horodatage courtier : composante confondue dans l'aller-retour",
        ))

    components.append(ComponentContract(
        "ack_to_active",
        ComponentStatus.OBSERVED if connector.order_active_observable
        else ComponentStatus.NOT_IDENTIFIABLE,
        None,
        rationale="" if connector.order_active_observable
        else "activation de l'ordre non observable — l'accusé ne la démontre pas",
    ))

    fill_observed = connector.fill_timestamp_available and inter
    components.append(ComponentContract(
        "active_to_fill",
        ComponentStatus.OBSERVED if fill_observed else ComponentStatus.NOT_IDENTIFIABLE,
        u if fill_observed else None,
        rationale="" if fill_observed
        else "horodatage d'exécution absent ou domaines d'horloge non qualifiés",
    ))

    observed = sum(1 for c in components if c.status is ComponentStatus.OBSERVED)
    aggregates = sum(1 for c in components if c.status is ComponentStatus.AGGREGATE_ONLY)

    if not local:
        verdict = ObservabilityVerdict.INSUFFICIENT_FOR_Q19
    elif observed >= 6 and inter:
        verdict = ObservabilityVerdict.FULLY_QUALIFIED
    elif observed >= 3 and (aggregates >= 1 or inter):
        verdict = ObservabilityVerdict.SUFFICIENT_FOR_LOWER_BOUND
    else:
        verdict = ObservabilityVerdict.LOCAL_ONLY

    # Le chemin complet lui-même (§19). Un agrégat **contribue sa durée entière** au
    # total : ce qui rend le chemin une borne inférieure, ce sont les segments manquants,
    # pas les segments non décomposables. Ajouté après le décompte, car il recouvre les
    # autres composantes et fausserait le verdict en s'y comptant lui-même.
    statuses = [c.status for c in components]
    measured = [s for s in statuses if s is not ComponentStatus.NOT_IDENTIFIABLE]
    if not measured:
        path_status = ComponentStatus.NOT_IDENTIFIABLE
    elif len(measured) == len(statuses):
        path_status = ComponentStatus.OBSERVED
    else:
        path_status = ComponentStatus.LOWER_BOUND
    components.append(ComponentContract(
        "critical_path",
        path_status,
        None,
        contains=tuple(c.component for c in components),
        rationale="marché → fournisseur → hôte → évaluation → décision → connecteur "
                  "→ courtier → ordre actif → exécution",
    ))

    return ObservabilityMatrix(clock, connector, tuple(components), verdict)


def format_ns(value: int | None) -> str:
    """Affiche une durée dans l'unité qui la rend lisible.

    Un arrondi fixe au millième de milliseconde afficherait « ±0.000 ms » pour une
    résolution de 40 ns — une incertitude réelle présentée comme nulle. L'unité s'adapte
    donc à l'ordre de grandeur plutôt que l'inverse.
    """
    if value is None:
        return "—"
    if value == 0:
        return "0"
    if abs(value) < 1_000:
        return f"{value} ns"
    if abs(value) < NS_PER_MS:
        return f"{value / 1_000:.3g} µs"
    if abs(value) < NS_PER_SECOND:
        return f"{value / NS_PER_MS:.3g} ms"
    return f"{value / NS_PER_SECOND:.3g} s"


def print_matrix(matrix: ObservabilityMatrix) -> None:
    u_inter = matrix.clock.measured_uncertainty_ns
    print("CONTRAT D'OBSERVABILITÉ — seule décomposition autorisée dans Q19")
    print(f"  horloge   : {matrix.clock.qualification.value}"
          f"   (résolution monotone {format_ns(matrix.clock.monotonic_resolution_ns)},"
          f" incertitude inter-systèmes "
          f"{format_ns(u_inter) if u_inter is not None else 'non mesurée'})")
    print(f"  connecteur: {matrix.connector.qualification_status}"
          f"   émission → {matrix.connector.submit_return_semantics.value}"
          f"   accusé → {matrix.connector.ack_semantics.value}")
    print(f"  verdict   : {matrix.verdict.value}")
    print()
    print(f"  {'composante':<28} {'statut':<20} incertitude")
    print("  " + "-" * 70)
    for c in matrix.components:
        u = "—" if c.uncertainty_ns is None else f"±{format_ns(c.uncertainty_ns)}"
        print(f"  {c.component:<28} {c.status.value:<20} {u}")
        if c.status is ComponentStatus.AGGREGATE_ONLY and c.contains:
            print(f"  {'':<28} └─ confond : {', '.join(c.contains)}")
