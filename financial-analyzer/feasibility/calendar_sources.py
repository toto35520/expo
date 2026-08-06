"""Sources normatives et chaîne de preuve du calendrier.

Le moteur de `calendar.py` applique correctement une règle temporelle. Ce module garantit
que la règle **mérite d'être appliquée**.

La chaîne complète, vérifiable de bout en bout :

    source → instantané → assertion → revue → manifest → compilation → calendrier

Le calendrier ne contient jamais une règle nue — « XAU/USD ferme à 22 h ». Il contient une
affirmation documentée : *le symbole XAUUSD du compte RAW sur ce serveur est annoncé
indisponible entre X et Y, selon la spécification récupérée le Z, applicable à partir de W*.
**La règle et sa preuve sont inséparables.**
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum

from .calendar import (
    NS_PER_SECOND,
    Bitemporal,
    CalendarError,
    CalendarException,
    MarketState,
    Provenance,
    QuoteExpectation,
    RecurringRule,
    VerificationStatus,
    VersionedMarketCalendar,
    local_to_ns,
)

COMPILER_VERSION = "CALENDAR_COMPILER_1.0"


# --------------------------------------------------------------------- énumérations


class SourceRank(str, Enum):
    """Autorité d'une source **dans son domaine**.

    Il n'existe pas de hiérarchie globale : la source normative dépend de ce que
    l'assertion décrit. Une place fait autorité sur ses propres horaires, un courtier sur
    la disponibilité du symbole de son compte, un fournisseur sur son flux.
    """

    NORMATIVE_EXCHANGE = "NORMATIVE_EXCHANGE"
    NORMATIVE_PROVIDER = "NORMATIVE_PROVIDER"
    NORMATIVE_DATA_PROVIDER = "NORMATIVE_DATA_PROVIDER"
    NORMATIVE_BROKER_SYMBOL = "NORMATIVE_BROKER_SYMBOL"
    NORMATIVE_BROKER_GENERAL = "NORMATIVE_BROKER_GENERAL"
    SECONDARY_MARKET_SOURCE = "SECONDARY_MARKET_SOURCE"
    OBSERVATIONAL_INFERENCE = "OBSERVATIONAL_INFERENCE"

    @property
    def is_normative(self) -> bool:
        return self.name.startswith("NORMATIVE")


class AssertionType(str, Enum):
    REGULAR_SESSION = "REGULAR_SESSION"
    SCHEDULED_BREAK = "SCHEDULED_BREAK"
    HOLIDAY = "HOLIDAY"
    EARLY_CLOSE = "EARLY_CLOSE"
    LATE_OPEN = "LATE_OPEN"
    MAINTENANCE = "MAINTENANCE"
    TRIPLE_SWAP_DAY = "TRIPLE_SWAP_DAY"
    ROLLOVER_TIME = "ROLLOVER_TIME"
    SERVER_TIMEZONE = "SERVER_TIMEZONE"
    FEED_UNAVAILABLE = "FEED_UNAVAILABLE"
    EXCEPTIONAL_CLOSURE = "EXCEPTIONAL_CLOSURE"


#: Assertions capables de modifier fortement la censure ou les coûts. Elles exigent une
#: source normative, une preuve conservée et une revue humaine.
CRITICAL_TYPES: frozenset[AssertionType] = frozenset({
    AssertionType.SCHEDULED_BREAK,
    AssertionType.HOLIDAY,
    AssertionType.MAINTENANCE,
    AssertionType.TRIPLE_SWAP_DAY,
    AssertionType.ROLLOVER_TIME,
    AssertionType.SERVER_TIMEZONE,
})


class ReviewStatus(str, Enum):
    PARSED_UNREVIEWED = "PARSED_UNREVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TimezoneInterpretation(str, Enum):
    """« GMT+2 » dans un document : décalage fixe, ou heure locale saisonnière ?

    L'ambiguïté n'est pas résolue par défaut — elle décalerait toutes les sessions d'une
    heure la moitié de l'année.
    """

    EXPLICIT_IANA = "EXPLICIT_IANA"
    RESOLVED_FROM_CONTEXT = "RESOLVED_FROM_CONTEXT"
    AMBIGUOUS = "AMBIGUOUS"


class EffectiveDateBasis(str, Enum):
    EXPLICIT_IN_SOURCE = "EXPLICIT_IN_SOURCE"
    INFERRED_FROM_PUBLICATION_DATE = "INFERRED_FROM_PUBLICATION_DATE"
    INFERRED_FROM_OBSERVATION = "INFERRED_FROM_OBSERVATION"
    UNKNOWN = "UNKNOWN"


class Freshness(str, Enum):
    FRESH = "FRESH"
    REVIEW_DUE = "REVIEW_DUE"
    STALE = "STALE"
    UNKNOWN_FRESHNESS = "UNKNOWN_FRESHNESS"


class ChangeKind(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    PRESENTATION_ONLY_CHANGE = "PRESENTATION_ONLY_CHANGE"
    SEMANTIC_CHANGE = "SEMANTIC_CHANGE"
    SOURCE_REMOVED = "SOURCE_REMOVED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class ImpactLevel(str, Enum):
    NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"
    RECOMPUTE_RECOMMENDED = "RECOMPUTE_RECOMMENDED"
    RECOMPUTE_REQUIRED = "RECOMPUTE_REQUIRED"
    VERDICT_INVALIDATED = "VERDICT_INVALIDATED"


class CalendarContentStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"


class SourceError(CalendarError):
    """Preuve manquante, portée incorrecte, conflit ouvert, ou compilation impossible."""


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]


# ---------------------------------------------------------------------- portée


@dataclass(frozen=True)
class Scope:
    """Domaine d'application d'une assertion.

    Les champs non applicables sont **explicitement nuls** plutôt qu'omis : l'absence
    déclarée se distingue de l'oubli, et c'est cette distinction qui empêche d'appliquer
    une règle de compte de démonstration à un compte réel.
    """

    market_id: str
    broker: str | None = None
    server: str | None = None
    account_type: str | None = None
    symbol: str | None = None
    data_source: str | None = None
    jurisdiction: str | None = None

    def covers(self, other: "Scope") -> bool:
        """Vrai si cette portée s'applique au contexte décrit par `other`.

        Un champ nul est un joker — la règle ne dit rien sur cette dimension. Un champ
        renseigné doit correspondre exactement : une règle du serveur A ne décrit pas le
        serveur B, et une règle de compte démo ne décrit pas un compte réel.
        """
        if self.market_id != other.market_id:
            return False
        for f in ("broker", "server", "account_type", "symbol", "data_source", "jurisdiction"):
            mine, theirs = getattr(self, f), getattr(other, f)
            if mine is not None and mine != theirs:
                return False
        return True

    @property
    def specificity(self) -> int:
        """Nombre de dimensions contraintes. Une portée plus spécifique prime."""
        return sum(
            1
            for f in ("broker", "server", "account_type", "symbol", "data_source", "jurisdiction")
            if getattr(self, f) is not None
        )


# ------------------------------------------------------------------ instantané


@dataclass(frozen=True)
class SourceSnapshot:
    """Acquisition immuable d'une source.

    Lorsque le contenu ne peut pas être conservé intégralement, l'empreinte, les
    métadonnées et l'extrait utilisé suffisent à rendre l'assertion auditable — mais leur
    absence, elle, invalide la preuve.
    """

    source_id: str
    source_type: str
    location: str
    retrieved_at_ns: int
    content_hash: str
    market_scope: tuple[str, ...]
    acquisition_method: str
    mime_type: str | None = None
    language: str | None = None
    status_code: str | None = None
    retained_excerpt: str | None = None
    collector_version: str | None = None
    unavailable: bool = False

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.location.strip():
            raise SourceError("Un instantané exige un identifiant et une localisation.")
        if not self.content_hash.strip():
            raise SourceError(
                "Empreinte manquante : sans elle, aucun changement de source n'est "
                "détectable et la chaîne de preuve est rompue."
            )


# ------------------------------------------------------------------ assertion


@dataclass(frozen=True)
class CalendarAssertion:
    """Affirmation atomique sur un marché, documentée par une source.

    Une page indiquant plusieurs horaires produit **plusieurs** assertions : c'est ce qui
    permet de superseder l'une sans toucher aux autres.
    """

    assertion_id: str
    scope: Scope
    assertion_type: AssertionType

    timezone: str
    timezone_interpretation: TimezoneInterpretation
    source_timezone_expression: str

    valid_from_ns: int
    valid_to_ns: int | None
    effective_date_basis: EffectiveDateBasis

    known_from_ns: int
    known_to_ns: int | None

    source_id: str
    source_rank: SourceRank
    review_status: ReviewStatus
    retrieved_at_ns: int
    extract_hash: str
    parser_version: str

    local_start: dt.time | None = None
    local_end: dt.time | None = None
    weekdays: frozenset[int] | None = None
    local_date: dt.date | None = None

    last_verified_at_ns: int | None = None
    next_review_due_ns: int | None = None
    supersedes_assertion_id: str | None = None
    superseded_by_assertion_id: str | None = None
    supersession_reason: str | None = None
    reviewer: str | None = None
    note: str = ""

    @property
    def is_critical(self) -> bool:
        return self.assertion_type in CRITICAL_TYPES

    @property
    def is_normative(self) -> bool:
        return self.source_rank.is_normative and self.review_status is ReviewStatus.APPROVED

    def freshness(self, now_ns: int) -> Freshness:
        if self.last_verified_at_ns is None or self.next_review_due_ns is None:
            return Freshness.UNKNOWN_FRESHNESS
        if now_ns < self.next_review_due_ns:
            return Freshness.FRESH
        overdue = now_ns - self.next_review_due_ns
        return Freshness.STALE if overdue > 180 * 86_400 * NS_PER_SECOND else Freshness.REVIEW_DUE

    def semantic_key(self) -> str:
        """Empreinte du **contenu**, hors métadonnées de présentation.

        Sert à distinguer une refonte de mise en page d'un changement d'horaire : deux
        acquisitions dont la semantic_key est identique ne créent pas de règle nouvelle.
        """
        return _hash(
            {
                "scope": asdict(self.scope),
                "type": self.assertion_type.value,
                "tz": self.timezone,
                "start": str(self.local_start),
                "end": str(self.local_end),
                "weekdays": sorted(self.weekdays) if self.weekdays else None,
                "date": str(self.local_date),
                "valid_from": self.valid_from_ns,
                "valid_to": self.valid_to_ns,
            }
        )


# ------------------------------------------------------------------- conflits


class ConflictType(str, Enum):
    DIFFERENT_CLOSE_TIME = "DIFFERENT_CLOSE_TIME"
    DIFFERENT_OPEN_TIME = "DIFFERENT_OPEN_TIME"
    DIFFERENT_TIMEZONE = "DIFFERENT_TIMEZONE"
    DIFFERENT_WEEKDAYS = "DIFFERENT_WEEKDAYS"
    INCOMPATIBLE_STATE = "INCOMPATIBLE_STATE"


@dataclass(frozen=True)
class CalendarSourceConflict:
    conflict_id: str
    assertion_ids: tuple[str, ...]
    conflict_type: ConflictType
    detected_at_ns: int
    resolution_status: str = "OPEN"
    resolution_note: str = ""
    #: Un conflit entre deux sources **normatives** bloque la compilation ; entre une
    #: normative et une secondaire, la spécificité tranche et le conflit est informatif.
    blocking: bool = True


def detect_conflicts(
    assertions: list[CalendarAssertion], now_ns: int
) -> list[CalendarSourceConflict]:
    """Les contradictions ne sont jamais résolues silencieusement.

    Deux sources récentes peuvent décrire deux périodes, deux produits ou deux serveurs
    différents : la récence n'est qu'un attribut, jamais un arbitre.
    """
    conflicts: list[CalendarSourceConflict] = []
    active = [a for a in assertions if a.superseded_by_assertion_id is None]

    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if a.assertion_type is not b.assertion_type:
                continue
            if not (a.scope.covers(b.scope) or b.scope.covers(a.scope)):
                continue
            if a.valid_to_ns is not None and b.valid_from_ns >= a.valid_to_ns:
                continue
            if b.valid_to_ns is not None and a.valid_from_ns >= b.valid_to_ns:
                continue

            kind = None
            if a.timezone != b.timezone:
                kind = ConflictType.DIFFERENT_TIMEZONE
            elif a.local_end != b.local_end:
                kind = ConflictType.DIFFERENT_CLOSE_TIME
            elif a.local_start != b.local_start:
                kind = ConflictType.DIFFERENT_OPEN_TIME
            elif a.weekdays != b.weekdays:
                kind = ConflictType.DIFFERENT_WEEKDAYS
            if kind is None:
                continue

            both_normative = a.source_rank.is_normative and b.source_rank.is_normative
            same_specificity = a.scope.specificity == b.scope.specificity
            conflicts.append(
                CalendarSourceConflict(
                    conflict_id=f"CAL-CONFLICT-{_hash((a.assertion_id, b.assertion_id))[:8]}",
                    assertion_ids=(a.assertion_id, b.assertion_id),
                    conflict_type=kind,
                    detected_at_ns=now_ns,
                    blocking=both_normative and same_specificity,
                )
            )
    return conflicts


def resolve_by_priority(candidates: list[CalendarAssertion]) -> CalendarAssertion:
    """Priorité : spécificité de portée, puis autorité de source, puis récence.

    La spécificité prime sur l'autorité générale — une fiche de symbole du compte
    l'emporte sur une page générique du courtier. La récence n'intervient qu'en dernier
    recours, et jamais seule.
    """
    rank_order = {r: i for i, r in enumerate(SourceRank)}
    return sorted(
        candidates,
        key=lambda a: (
            -a.scope.specificity,
            rank_order[a.source_rank],
            -a.known_from_ns,
        ),
    )[0]


# -------------------------------------------------------------------- manifest


@dataclass(frozen=True)
class CalendarManifest:
    calendar_version: str
    market_id: str
    created_at_ns: int
    effective_from_ns: int
    assertion_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    unresolved_conflict_ids: tuple[str, ...]
    provisional_assertion_ids: tuple[str, ...]
    manifest_hash: str
    approved_by: str
    software_version: str
    parent_version: str | None = None


def build_manifest(
    calendar_version: str,
    market_id: str,
    assertions: list[CalendarAssertion],
    snapshots: dict[str, SourceSnapshot],
    conflicts: list[CalendarSourceConflict],
    approved_by: str,
    created_at_ns: int,
    effective_from_ns: int,
    parent_version: str | None = None,
) -> CalendarManifest:
    """Manifest immuable et reproductible.

    L'empreinte est calculée sur le **contenu** des assertions et des instantanés, non sur
    leurs identifiants seuls : deux constructions du même manifest doivent produire la
    même empreinte, et un manifest dépendant d'informations non conservées est invalide.
    """
    ordered = sorted(assertions, key=lambda a: a.assertion_id)
    payload = {
        "version": calendar_version,
        "market": market_id,
        "assertions": [(a.assertion_id, a.semantic_key(), a.extract_hash) for a in ordered],
        "sources": sorted((s.source_id, s.content_hash) for s in snapshots.values()),
        "conflicts": sorted(c.conflict_id for c in conflicts),
        "compiler": COMPILER_VERSION,
    }
    return CalendarManifest(
        calendar_version=calendar_version,
        market_id=market_id,
        created_at_ns=created_at_ns,
        effective_from_ns=effective_from_ns,
        assertion_ids=tuple(a.assertion_id for a in ordered),
        source_ids=tuple(sorted(snapshots)),
        unresolved_conflict_ids=tuple(
            c.conflict_id for c in conflicts if c.resolution_status == "OPEN"
        ),
        provisional_assertion_ids=tuple(
            a.assertion_id for a in ordered if not a.is_normative
        ),
        manifest_hash=_hash(payload),
        approved_by=approved_by,
        software_version=COMPILER_VERSION,
        parent_version=parent_version,
    )


# ------------------------------------------------------------------ compilation


@dataclass
class CompilationResult:
    calendar: VersionedMarketCalendar
    manifest: CalendarManifest
    content_status: CalendarContentStatus
    conflicts: tuple[CalendarSourceConflict, ...]
    stale_assertion_ids: tuple[str, ...]
    provisional_assertion_ids: tuple[str, ...]
    warnings: tuple[str, ...]


_STATE_MAP: dict[AssertionType, tuple[MarketState, QuoteExpectation]] = {
    AssertionType.REGULAR_SESSION: (
        MarketState.OPEN_CONTINUOUS, QuoteExpectation.QUOTES_EXPECTED_NORMAL),
    AssertionType.SCHEDULED_BREAK: (
        MarketState.SCHEDULED_BREAK, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.HOLIDAY: (
        MarketState.HOLIDAY_CLOSED, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.EARLY_CLOSE: (
        MarketState.EARLY_CLOSE, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.LATE_OPEN: (
        MarketState.LATE_OPEN, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.MAINTENANCE: (
        MarketState.BROKER_MAINTENANCE, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.FEED_UNAVAILABLE: (
        MarketState.PROVIDER_MAINTENANCE, QuoteExpectation.QUOTES_NOT_EXPECTED),
    AssertionType.EXCEPTIONAL_CLOSURE: (
        MarketState.EMERGENCY_CLOSED, QuoteExpectation.QUOTES_NOT_EXPECTED),
}


def compile_calendar(
    calendar_version: str,
    market_id: str,
    assertions: list[CalendarAssertion],
    snapshots: dict[str, SourceSnapshot],
    now_ns: int,
    approved_by: str,
    effective_from_ns: int = 0,
    parent_version: str | None = None,
    allow_provisional: bool = False,
) -> CompilationResult:
    """Compile un calendrier exécutable depuis ses assertions.

    Trois échecs bloquants, par conception :

    1. **assertion critique sans preuve** — une règle capable de modifier fortement la
       censure ou les coûts ne peut pas reposer sur une source absente, non normative ou
       non revue ;
    2. **conflit normatif ouvert** — deux sources normatives de même spécificité qui se
       contredisent ne se départagent pas toutes seules ;
    3. **fuseau ou période d'effet ambigu** — « GMT+2 » non résolu décalerait toutes les
       sessions d'une heure la moitié de l'année, et une date d'effet inconnue serait
       appliquée rétroactivement sans preuve.
    """
    active = [a for a in assertions if a.superseded_by_assertion_id is None]
    active = [a for a in active if a.review_status is not ReviewStatus.REJECTED]
    warnings: list[str] = []

    # ---- échec 1 : preuve manquante sur une assertion critique
    for a in active:
        if not a.is_critical:
            continue
        if a.source_id not in snapshots:
            raise SourceError(
                f"Assertion critique {a.assertion_id} ({a.assertion_type.value}) sans "
                f"instantané de source : la règle et sa preuve sont inséparables."
            )
        if not a.source_rank.is_normative:
            raise SourceError(
                f"Assertion critique {a.assertion_id} adossée à une source non normative "
                f"({a.source_rank.value}). Une observation ne devient jamais normative "
                "automatiquement."
            )
        if a.review_status is not ReviewStatus.APPROVED:
            raise SourceError(
                f"Assertion critique {a.assertion_id} non revue "
                f"({a.review_status.value}) : une extraction automatique reste non "
                "normative jusqu'à validation humaine."
            )

    # ---- échec 3 : ambiguïtés temporelles
    for a in active:
        if a.timezone_interpretation is TimezoneInterpretation.AMBIGUOUS:
            raise SourceError(
                f"Assertion {a.assertion_id} : interprétation de fuseau ambiguë "
                f"(« {a.source_timezone_expression} »). Décalage fixe ou heure locale "
                "saisonnière ? La confusion décale toutes les sessions d'une heure la "
                "moitié de l'année."
            )
        if a.effective_date_basis is EffectiveDateBasis.UNKNOWN:
            raise SourceError(
                f"Assertion {a.assertion_id} : date d'effet inconnue. L'appliquer "
                "rétroactivement reviendrait à supposer qu'elle a toujours été vraie."
            )
        if a.valid_to_ns is not None and a.valid_to_ns <= a.valid_from_ns:
            raise SourceError(
                f"Assertion {a.assertion_id} : période d'effet incohérente."
            )

    # ---- échec 2 : conflit normatif ouvert
    conflicts = detect_conflicts(active, now_ns)
    blocking = [c for c in conflicts if c.blocking and c.resolution_status == "OPEN"]
    if blocking:
        raise SourceError(
            "Conflit normatif ouvert entre "
            + ", ".join("/".join(c.assertion_ids) for c in blocking)
            + " : deux sources normatives de même spécificité se contredisent. La "
            "résolution est explicite, jamais automatique par récence."
        )

    # ---- assemblage
    recurring: list[RecurringRule] = []
    exceptions: list[CalendarException] = []
    stale: list[str] = []
    provisional: list[str] = []

    for a in active:
        if a.freshness(now_ns) is Freshness.STALE:
            stale.append(a.assertion_id)
        if not a.is_normative:
            provisional.append(a.assertion_id)
            if not allow_provisional:
                warnings.append(
                    f"{a.assertion_id} non normative — intervalle marqué provisoire"
                )

        if a.assertion_type not in _STATE_MAP:
            warnings.append(f"{a.assertion_id} : type {a.assertion_type.value} non temporel")
            continue

        state, expectation = _STATE_MAP[a.assertion_type]
        prov = Provenance(
            source_id=a.source_id,
            source_type=snapshots[a.source_id].source_type if a.source_id in snapshots else "?",
            retrieved_at=str(a.retrieved_at_ns),
            content_hash=a.extract_hash,
            verification=(
                VerificationStatus.VERIFIED_BROKER_SOURCE
                if a.source_rank in (SourceRank.NORMATIVE_BROKER_SYMBOL,
                                     SourceRank.NORMATIVE_BROKER_GENERAL)
                else VerificationStatus.VERIFIED_PRIMARY_SOURCE
                if a.source_rank.is_normative
                else VerificationStatus.INFERRED_FROM_REPEATED_OBSERVATION
                if a.source_rank is SourceRank.OBSERVATIONAL_INFERENCE
                else VerificationStatus.UNVERIFIED
            ),
        )
        temporal = Bitemporal(a.valid_from_ns, a.valid_to_ns, a.known_from_ns, a.known_to_ns)

        if a.local_date is not None:
            exceptions.append(CalendarException(
                market_id=market_id, local_date=a.local_date, timezone=a.timezone,
                state=state, quote_expectation=expectation,
                temporal=temporal, provenance=prov,
                local_start=a.local_start, local_end=a.local_end, reason=a.note,
            ))
        elif a.weekdays is not None and a.local_start is not None and a.local_end is not None:
            recurring.append(RecurringRule(
                market_id=market_id, weekdays=a.weekdays,
                local_start=a.local_start, local_end=a.local_end, timezone=a.timezone,
                state=state, quote_expectation=expectation,
                temporal=temporal, provenance=prov, label=a.assertion_id,
            ))
        else:
            warnings.append(f"{a.assertion_id} : ni règle récurrente ni exception datée")

    manifest = build_manifest(
        calendar_version, market_id, active, snapshots, conflicts,
        approved_by, now_ns, effective_from_ns, parent_version,
    )

    if any(c.resolution_status == "OPEN" for c in conflicts):
        status = CalendarContentStatus.CONFLICTING
    elif provisional:
        status = CalendarContentStatus.PROVISIONAL
    elif stale:
        status = CalendarContentStatus.STALE
    else:
        status = CalendarContentStatus.VERIFIED

    calendar = VersionedMarketCalendar(
        calendar_id=f"{market_id}:{manifest.manifest_hash}",
        calendar_version=calendar_version,
        market_id=market_id,
        timezone_database_version="stdlib-zoneinfo",
        recurring=tuple(recurring),
        exceptions=tuple(exceptions),
        parent_version=parent_version,
        provisional=status is not CalendarContentStatus.VERIFIED,
    )

    return CompilationResult(
        calendar=calendar,
        manifest=manifest,
        content_status=status,
        conflicts=tuple(conflicts),
        stale_assertion_ids=tuple(stale),
        provisional_assertion_ids=tuple(provisional),
        warnings=tuple(warnings),
    )


# ------------------------------------------------- changements et impact historique


def classify_change(
    previous: SourceSnapshot | None,
    current: SourceSnapshot | None,
    previous_assertions: list[CalendarAssertion],
    current_assertions: list[CalendarAssertion],
) -> ChangeKind:
    """Distingue une refonte de mise en page d'un changement d'horaire.

    Comparer les seules empreintes de contenu créerait une règle nouvelle à chaque
    modification cosmétique de la page source.
    """
    if previous is not None and current is None:
        return ChangeKind.SOURCE_REMOVED
    if current is not None and current.unavailable:
        return ChangeKind.SOURCE_UNAVAILABLE
    if previous is None or current is None:
        return ChangeKind.SEMANTIC_CHANGE

    same_content = previous.content_hash == current.content_hash
    before = sorted(a.semantic_key() for a in previous_assertions)
    after = sorted(a.semantic_key() for a in current_assertions)

    if same_content and before == after:
        return ChangeKind.NO_CHANGE
    if before == after:
        return ChangeKind.PRESENTATION_ONLY_CHANGE
    return ChangeKind.SEMANTIC_CHANGE


@dataclass(frozen=True)
class HistoricalImpact:
    level: ImpactLevel
    affected_intervals: tuple[tuple[int, int], ...]
    rationale: str


def assess_historical_impact(
    previous: VersionedMarketCalendar,
    current: VersionedMarketCalendar,
    report_intervals: list[tuple[int, int]],
    sample_points: int = 24,
) -> HistoricalImpact:
    """Identifie les rapports affectés par une correction — **sans les réécrire**.

    Les anciens rapports conservent l'identifiant exact du calendrier utilisé ; une
    nouvelle exécution est liée à la nouvelle version.
    """
    affected: list[tuple[int, int]] = []
    for start, end in report_intervals:
        if end <= start:
            continue
        step = max(1, (end - start) // sample_points)
        for t in range(start, end, step):
            if previous.state_at(t).primary_state is not current.state_at(t).primary_state:
                affected.append((start, end))
                break

    if not affected:
        return HistoricalImpact(
            ImpactLevel.NO_MATERIAL_IMPACT, (), "aucun état modifié sur les intervalles publiés"
        )
    ratio = len(affected) / max(1, len(report_intervals))
    level = (
        ImpactLevel.VERDICT_INVALIDATED
        if ratio > 0.5
        else ImpactLevel.RECOMPUTE_REQUIRED
        if ratio > 0.1
        else ImpactLevel.RECOMPUTE_RECOMMENDED
    )
    return HistoricalImpact(
        level, tuple(affected), f"{len(affected)} intervalle(s) publié(s) sur {len(report_intervals)}"
    )


# ------------------------------------------------------------- rapport de provenance


@dataclass(frozen=True)
class ProvenanceReport:
    calendar_version: str
    manifest_hash: str
    content_status: CalendarContentStatus
    source_count: int
    normative_assertion_count: int
    provisional_assertion_count: int
    stale_assertion_count: int
    unresolved_conflict_count: int
    next_review_due_ns: int | None


def provenance_report(result: CompilationResult, assertions: list[CalendarAssertion]) -> ProvenanceReport:
    due = [a.next_review_due_ns for a in assertions if a.next_review_due_ns is not None]
    return ProvenanceReport(
        calendar_version=result.calendar.calendar_version,
        manifest_hash=result.manifest.manifest_hash,
        content_status=result.content_status,
        source_count=len(result.manifest.source_ids),
        normative_assertion_count=sum(1 for a in assertions if a.is_normative),
        provisional_assertion_count=len(result.provisional_assertion_ids),
        stale_assertion_count=len(result.stale_assertion_ids),
        unresolved_conflict_count=len(result.manifest.unresolved_conflict_ids),
        next_review_due_ns=min(due) if due else None,
    )


def print_provenance(report: ProvenanceReport) -> None:
    print("PROVENANCE DU CALENDRIER")
    print(f"  version            : {report.calendar_version}")
    print(f"  empreinte manifest : {report.manifest_hash}")
    print(f"  statut du contenu  : {report.content_status.value}")
    print(f"  sources            : {report.source_count}")
    print(f"  assertions         : {report.normative_assertion_count} normatives · "
          f"{report.provisional_assertion_count} provisoires · "
          f"{report.stale_assertion_count} périmées")
    print(f"  conflits ouverts   : {report.unresolved_conflict_count}")
