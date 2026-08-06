"""Moteur de calendrier de marché versionné.

Le calendrier n'est pas une liste d'horaires : c'est un moteur temporel capable de dire,
pour tout intervalle sans cotation, **ce qui était censé s'y passer** — et de justifier sa
réponse par une version, une source et un statut de vérification.

Principe fondateur : l'absence de ticks est une **observation** ; la fermeture est une
**information externe versionnée**. Le moteur ne déduit jamais l'une de l'autre.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from zoneinfo import ZoneInfo

NS_PER_SECOND = 1_000_000_000
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------------- états


class MarketState(str, Enum):
    OPEN_CONTINUOUS = "OPEN_CONTINUOUS"
    OPEN_REDUCED = "OPEN_REDUCED"
    PRE_OPEN = "PRE_OPEN"
    POST_CLOSE = "POST_CLOSE"
    SCHEDULED_BREAK = "SCHEDULED_BREAK"
    BROKER_MAINTENANCE = "BROKER_MAINTENANCE"
    PROVIDER_MAINTENANCE = "PROVIDER_MAINTENANCE"
    HOLIDAY_CLOSED = "HOLIDAY_CLOSED"
    EARLY_CLOSE = "EARLY_CLOSE"
    LATE_OPEN = "LATE_OPEN"
    WEEKEND_CLOSED = "WEEKEND_CLOSED"
    EMERGENCY_CLOSED = "EMERGENCY_CLOSED"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


#: Priorité de résolution des états qui se chevauchent. Ne détruit pas les états
#: secondaires : ils sont conservés dans `contributing_states`.
DOMINANCE: tuple[MarketState, ...] = (
    MarketState.EMERGENCY_CLOSED,
    MarketState.HALTED,
    MarketState.BROKER_MAINTENANCE,
    MarketState.PROVIDER_MAINTENANCE,
    MarketState.HOLIDAY_CLOSED,
    MarketState.SCHEDULED_BREAK,
    MarketState.WEEKEND_CLOSED,
    MarketState.EARLY_CLOSE,
    MarketState.LATE_OPEN,
    MarketState.PRE_OPEN,
    MarketState.POST_CLOSE,
    MarketState.OPEN_REDUCED,
    MarketState.OPEN_CONTINUOUS,
    MarketState.UNKNOWN,
)
_RANK = {s: i for i, s in enumerate(DOMINANCE)}


class QuoteExpectation(str, Enum):
    """L'état de négociation ne suffit pas : un marché ouvert ne garantit pas que le
    courtier diffuse ce symbole, et une séance ouverte mais traditionnellement creuse ne
    doit pas être confondue avec une panne."""

    QUOTES_EXPECTED_NORMAL = "QUOTES_EXPECTED_NORMAL"
    QUOTES_EXPECTED_SPARSE = "QUOTES_EXPECTED_SPARSE"
    QUOTES_NOT_EXPECTED = "QUOTES_NOT_EXPECTED"
    QUOTE_POLICY_UNKNOWN = "QUOTE_POLICY_UNKNOWN"


class VerificationStatus(str, Enum):
    VERIFIED_PRIMARY_SOURCE = "VERIFIED_PRIMARY_SOURCE"
    VERIFIED_PROVIDER_SOURCE = "VERIFIED_PROVIDER_SOURCE"
    VERIFIED_BROKER_SOURCE = "VERIFIED_BROKER_SOURCE"
    INFERRED_FROM_REPEATED_OBSERVATION = "INFERRED_FROM_REPEATED_OBSERVATION"
    MANUAL_OVERRIDE_VERIFIED = "MANUAL_OVERRIDE_VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class GapClassification(str, Enum):
    MARKET_CLOSED = "MARKET_CLOSED"
    PARTIAL_SCHEDULED_CLOSURE = "PARTIAL_SCHEDULED_CLOSURE"
    DATA_OUTAGE = "DATA_OUTAGE"
    EXPECTED_SPARSE_ACTIVITY = "EXPECTED_SPARSE_ACTIVITY"
    UNKNOWN_GAP = "UNKNOWN_GAP"


class CalendarError(ValueError):
    """Entrée temporelle inexploitable, ou règle mal formée."""


# --------------------------------------------------------------- temps et fuseaux


def require_aware(value: dt.datetime) -> dt.datetime:
    """Rejette les datetimes naïfs aux frontières du moteur.

    `2026-10-25 01:30:00` sans fuseau est ambigu à Londres — l'heure existe deux fois — et
    inexistant le 29 mars à 01h30. Accepter la valeur reviendrait à choisir silencieusement
    l'une des deux réponses.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise CalendarError(
            f"Datetime naïf refusé : {value.isoformat()}. Fournir un fuseau explicite — "
            "une heure locale sans fuseau est ambiguë ou inexistante deux fois par an."
        )
    return value


def to_ns(value: dt.datetime) -> int:
    return int((require_aware(value) - _EPOCH).total_seconds() * NS_PER_SECOND)


def from_ns(ns: int) -> dt.datetime:
    return _EPOCH + dt.timedelta(microseconds=ns / 1_000)


def is_nonexistent(local: dt.datetime, tz: ZoneInfo) -> bool:
    """Heure locale supprimée par le passage à l'heure d'été."""
    stamped = local.replace(tzinfo=tz)
    return stamped.astimezone(dt.timezone.utc).astimezone(tz).replace(tzinfo=None) != local


def is_ambiguous(local: dt.datetime, tz: ZoneInfo) -> bool:
    """Heure locale répétée au retour à l'heure standard — deux instants UTC distincts."""
    a = local.replace(tzinfo=tz, fold=0)
    b = local.replace(tzinfo=tz, fold=1)
    return a.utcoffset() != b.utcoffset()


def local_to_ns(local_naive: dt.datetime, timezone: str, fold: int = 0) -> int:
    """Convertit une heure locale en instant absolu, en traitant explicitement les
    discontinuités de changement d'heure.

    Une heure inexistante est **refusée** plutôt que déplacée : la déplacer produirait un
    horaire d'ouverture que personne n'a jamais publié.
    """
    tz = ZoneInfo(timezone)
    if is_nonexistent(local_naive, tz):
        raise CalendarError(
            f"Heure locale inexistante dans {timezone} : {local_naive.isoformat()} — "
            "supprimée par le passage à l'heure d'été. La règle doit être reformulée."
        )
    return to_ns(local_naive.replace(tzinfo=tz, fold=fold))


# ------------------------------------------------------------------------- règles


@dataclass(frozen=True)
class Provenance:
    source_id: str
    source_type: str
    retrieved_at: str
    content_hash: str
    verification: VerificationStatus

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.retrieved_at.strip():
            raise CalendarError(
                "Une règle de calendrier doit porter sa source et sa date de relevé : "
                "sans elles, un horaire inféré est indiscernable d'un horaire officiel."
            )


@dataclass(frozen=True)
class Bitemporal:
    """Deux temporalités distinctes (ADR-133).

    `valid_*` répond à « quel était réellement l'état du marché ? ».
    `known_*` répond à « que pouvait savoir le système à cet instant ? ».
    Une fermeture annoncée après coup ne doit pas être visible d'un backtest décisionnel.
    """

    valid_from_ns: int
    valid_to_ns: int | None = None
    known_from_ns: int = 0
    known_to_ns: int | None = None

    def applies_at(self, ts_ns: int, known_as_of_ns: int | None) -> bool:
        if ts_ns < self.valid_from_ns:
            return False
        if self.valid_to_ns is not None and ts_ns >= self.valid_to_ns:
            return False
        if known_as_of_ns is None:
            return True  # audit historique : l'état réel, quelle que soit sa date de connaissance
        if known_as_of_ns < self.known_from_ns:
            return False
        if self.known_to_ns is not None and known_as_of_ns >= self.known_to_ns:
            return False
        return True


@dataclass(frozen=True)
class RecurringRule:
    """Règle habituelle, définie dans le fuseau d'origine du marché.

    Jamais en décalage UTC fixe : un marché appliquant un changement d'heure verrait ses
    ouvertures dériver d'une heure deux fois par an.
    """

    market_id: str
    weekdays: frozenset[int]
    local_start: dt.time
    local_end: dt.time
    timezone: str
    state: MarketState
    quote_expectation: QuoteExpectation
    temporal: Bitemporal
    provenance: Provenance
    label: str = ""


@dataclass(frozen=True)
class CalendarException:
    """Exception datée, **prioritaire sur toute règle récurrente** (ADR-135).

    Couvre jour férié, demi-séance, fermeture exceptionnelle, ouverture retardée,
    maintenance. `local_start`/`local_end` absents ⇒ la journée locale entière.
    """

    market_id: str
    local_date: dt.date
    timezone: str
    state: MarketState
    quote_expectation: QuoteExpectation
    temporal: Bitemporal
    provenance: Provenance
    local_start: dt.time | None = None
    local_end: dt.time | None = None
    reason: str = ""

    def interval_ns(self) -> tuple[int, int]:
        start = dt.datetime.combine(self.local_date, self.local_start or dt.time(0, 0))
        if self.local_end is not None:
            end = dt.datetime.combine(self.local_date, self.local_end)
        else:
            end = dt.datetime.combine(self.local_date + dt.timedelta(days=1), dt.time(0, 0))
        return local_to_ns(start, self.timezone), local_to_ns(end, self.timezone)


@dataclass(frozen=True)
class ManualOverride:
    """Couche auditable, qui ne modifie jamais la source d'origine."""

    override_id: str
    market_id: str
    start_ns: int
    end_ns: int
    previous_state: MarketState
    new_state: MarketState
    quote_expectation: QuoteExpectation
    author: str
    reason: str
    evidence: str
    created_at: str
    temporal: Bitemporal

    def __post_init__(self) -> None:
        if not (self.author.strip() and self.reason.strip() and self.evidence.strip()):
            raise CalendarError(
                "Un override manuel exige auteur, motif et preuve : sans eux, il est "
                "indiscernable d'une correction opportuniste."
            )


# ------------------------------------------------------------------------ résultats


@dataclass(frozen=True)
class MarketStateAt:
    market_id: str
    as_of_ns: int
    primary_state: MarketState
    contributing_states: tuple[MarketState, ...]
    quote_expectation: QuoteExpectation
    calendar_version: str
    verification: VerificationStatus
    resolution_rule: str


@dataclass(frozen=True)
class CalendarSegment:
    start_ns: int
    end_ns: int
    state: MarketState
    quote_expectation: QuoteExpectation
    contributing_states: tuple[MarketState, ...]
    resolution_rule: str

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns


@dataclass(frozen=True)
class IntervalStateSummary:
    market_id: str
    start_ns: int
    end_ns: int
    duration_by_state_ns: dict[str, int]
    duration_by_quote_expectation_ns: dict[str, int]
    segments: tuple[CalendarSegment, ...]
    classification: GapClassification
    calendar_version: str

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns

    def fraction_with(self, expectation: QuoteExpectation) -> float:
        if self.duration_ns <= 0:
            return 0.0
        return self.duration_by_quote_expectation_ns.get(expectation.value, 0) / self.duration_ns

    @property
    def market_time_ns(self) -> int:
        """Temps pendant lequel des cotations étaient attendues (ADR-137).

        Une fenêtre traversant une fermeture ne se compare pas directement à une fenêtre
        entièrement ouverte.
        """
        return (
            self.duration_by_quote_expectation_ns.get(
                QuoteExpectation.QUOTES_EXPECTED_NORMAL.value, 0
            )
            + self.duration_by_quote_expectation_ns.get(
                QuoteExpectation.QUOTES_EXPECTED_SPARSE.value, 0
            )
        )


# ------------------------------------------------------------------------ moteur


@dataclass
class VersionedMarketCalendar:
    """Calendrier d'un marché, versionné et auditable.

    Un calendrier par source et par marché d'exécution : `Calendar(GC)` n'est pas
    `Calendar(broker XAU/USD)`. Ils ne partagent ni horaires, ni maintenances, ni fériés,
    ni fuseau serveur, ni disponibilité de cotation.
    """

    calendar_id: str
    calendar_version: str
    market_id: str
    timezone_database_version: str
    recurring: tuple[RecurringRule, ...] = ()
    exceptions: tuple[CalendarException, ...] = ()
    overrides: tuple[ManualOverride, ...] = ()
    parent_version: str | None = None
    provisional: bool = False

    # ----------------------------------------------------------------- évaluation

    def state_at(self, ts_ns: int, known_as_of_ns: int | None = None) -> MarketStateAt:
        candidates: list[tuple[MarketState, QuoteExpectation, VerificationStatus, str]] = []

        for ov in self.overrides:
            if ov.market_id != self.market_id or not ov.temporal.applies_at(ts_ns, known_as_of_ns):
                continue
            if ov.start_ns <= ts_ns < ov.end_ns:
                candidates.append(
                    (ov.new_state, ov.quote_expectation,
                     VerificationStatus.MANUAL_OVERRIDE_VERIFIED, f"override:{ov.override_id}")
                )

        exception_hit = False
        for exc in self.exceptions:
            if exc.market_id != self.market_id or not exc.temporal.applies_at(ts_ns, known_as_of_ns):
                continue
            start, end = exc.interval_ns()
            if start <= ts_ns < end:
                exception_hit = True
                candidates.append(
                    (exc.state, exc.quote_expectation, exc.provenance.verification,
                     f"exception:{exc.provenance.source_id}")
                )

        # Une exception remplace localement la règle récurrente (ADR-135) : les règles
        # habituelles ne sont consultées que si aucune exception ne couvre l'instant.
        if not exception_hit:
            for rule in self.recurring:
                if rule.market_id != self.market_id or not rule.temporal.applies_at(
                    ts_ns, known_as_of_ns
                ):
                    continue
                if self._recurring_covers(rule, ts_ns):
                    candidates.append(
                        (rule.state, rule.quote_expectation, rule.provenance.verification,
                         f"recurring:{rule.label or rule.provenance.source_id}")
                    )

        if not candidates:
            return MarketStateAt(
                self.market_id, ts_ns, MarketState.UNKNOWN, (),
                QuoteExpectation.QUOTE_POLICY_UNKNOWN, self.calendar_version,
                VerificationStatus.UNVERIFIED, "aucune règle applicable",
            )

        candidates.sort(key=lambda c: _RANK[c[0]])
        state, expectation, verification, rule = candidates[0]
        return MarketStateAt(
            market_id=self.market_id,
            as_of_ns=ts_ns,
            primary_state=state,
            contributing_states=tuple(c[0] for c in candidates),
            quote_expectation=expectation,
            calendar_version=self.calendar_version,
            verification=verification,
            resolution_rule=rule,
        )

    def _recurring_covers(self, rule: RecurringRule, ts_ns: int) -> bool:
        tz = ZoneInfo(rule.timezone)
        local = from_ns(ts_ns).astimezone(tz)
        if local.weekday() not in rule.weekdays:
            return False
        t = local.timetz().replace(tzinfo=None)
        if rule.local_start <= rule.local_end:
            return rule.local_start <= t < rule.local_end
        # Règle traversant minuit : elle appartient au jour de son ouverture.
        return t >= rule.local_start or t < rule.local_end

    # ------------------------------------------------------------- segmentation

    def _boundaries(self, start_ns: int, end_ns: int) -> list[int]:
        """Instants de transition candidats dans l'intervalle.

        Énumérés exactement plutôt qu'échantillonnés : un échantillonnage manquerait une
        maintenance de quelques minutes, qui est précisément le cas qu'on cherche à voir.
        """
        marks = {start_ns, end_ns}

        for ov in self.overrides:
            for b in (ov.start_ns, ov.end_ns):
                if start_ns < b < end_ns:
                    marks.add(b)

        for exc in self.exceptions:
            if exc.market_id != self.market_id:
                continue
            s, e = exc.interval_ns()
            for b in (s, e):
                if start_ns < b < end_ns:
                    marks.add(b)

        for rule in self.recurring:
            if rule.market_id != self.market_id:
                continue
            tz = ZoneInfo(rule.timezone)
            first = from_ns(start_ns).astimezone(tz).date() - dt.timedelta(days=1)
            last = from_ns(end_ns).astimezone(tz).date() + dt.timedelta(days=1)
            day = first
            while day <= last:
                for local_time in (rule.local_start, rule.local_end):
                    naive = dt.datetime.combine(day, local_time)
                    try:
                        b = local_to_ns(naive, rule.timezone)
                    except CalendarError:
                        continue  # heure supprimée par le changement d'heure ce jour-là
                    if start_ns < b < end_ns:
                        marks.add(b)
                day += dt.timedelta(days=1)

        return sorted(marks)

    def split_by_calendar_state(
        self, start_ns: int, end_ns: int, known_as_of_ns: int | None = None
    ) -> tuple[CalendarSegment, ...]:
        if end_ns <= start_ns:
            return ()

        marks = self._boundaries(start_ns, end_ns)
        segments: list[CalendarSegment] = []
        for a, b in zip(marks[:-1], marks[1:]):
            if b <= a:
                continue
            st = self.state_at(a + (b - a) // 2, known_as_of_ns)
            if segments and segments[-1].state is st.primary_state:
                prev = segments[-1]
                segments[-1] = CalendarSegment(
                    prev.start_ns, b, prev.state, prev.quote_expectation,
                    prev.contributing_states, prev.resolution_rule,
                )
            else:
                segments.append(
                    CalendarSegment(a, b, st.primary_state, st.quote_expectation,
                                    st.contributing_states, st.resolution_rule)
                )
        return tuple(segments)

    def summarize_interval(
        self,
        start_ns: int,
        end_ns: int,
        known_as_of_ns: int | None = None,
        closed_fraction_threshold: float = 0.95,
        unknown_fraction_threshold: float = 0.20,
        min_open_duration_ns: int = 60 * NS_PER_SECOND,
    ) -> IntervalStateSummary:
        """Classe un intervalle par l'intégralité de son contenu (ADR-130).

        Ni l'état au début, ni l'état à la fin, ni le premier tick après la coupure ne
        suffisent : une nuit va de la clôture de New York à l'ouverture de Londres, et
        aucune de ses bornes n'est en session fermée.
        """
        segments = self.split_by_calendar_state(start_ns, end_ns, known_as_of_ns)

        by_state: dict[str, int] = {}
        by_expect: dict[str, int] = {}
        for seg in segments:
            by_state[seg.state.value] = by_state.get(seg.state.value, 0) + seg.duration_ns
            by_expect[seg.quote_expectation.value] = (
                by_expect.get(seg.quote_expectation.value, 0) + seg.duration_ns
            )

        total = max(1, end_ns - start_ns)
        f_closed = by_expect.get(QuoteExpectation.QUOTES_NOT_EXPECTED.value, 0) / total
        f_normal = by_expect.get(QuoteExpectation.QUOTES_EXPECTED_NORMAL.value, 0) / total
        f_sparse = by_expect.get(QuoteExpectation.QUOTES_EXPECTED_SPARSE.value, 0) / total
        f_unknown = by_expect.get(QuoteExpectation.QUOTE_POLICY_UNKNOWN.value, 0) / total

        open_ns = (
            by_expect.get(QuoteExpectation.QUOTES_EXPECTED_NORMAL.value, 0)
            + by_expect.get(QuoteExpectation.QUOTES_EXPECTED_SPARSE.value, 0)
        )

        if self.provisional or f_unknown > unknown_fraction_threshold:
            classification = GapClassification.UNKNOWN_GAP
        elif f_closed > 0.0 and open_ns >= min_open_duration_ns:
            # La durée **absolue** de la partie ouverte prime sur sa fraction : une panne
            # d'une demi-heure après réouverture représente 2 % d'une nuit de vingt heures
            # et serait avalée par un seuil en pourcentage. Or c'est précisément le cas
            # qu'une fermeture planifiée ne doit pas masquer.
            classification = GapClassification.PARTIAL_SCHEDULED_CLOSURE
        elif f_closed >= closed_fraction_threshold:
            classification = GapClassification.MARKET_CLOSED
        elif f_closed > 0.0 and open_ns > 0:
            classification = GapClassification.PARTIAL_SCHEDULED_CLOSURE
        elif f_normal >= f_sparse:
            classification = GapClassification.DATA_OUTAGE
        else:
            classification = GapClassification.EXPECTED_SPARSE_ACTIVITY

        return IntervalStateSummary(
            market_id=self.market_id,
            start_ns=start_ns,
            end_ns=end_ns,
            duration_by_state_ns=by_state,
            duration_by_quote_expectation_ns=by_expect,
            segments=segments,
            classification=classification,
            calendar_version=self.calendar_version,
        )

    def market_time_ns(self, start_ns: int, end_ns: int) -> int:
        return self.summarize_interval(start_ns, end_ns).market_time_ns


# ------------------------------------------------- attendu contre observé, révisions


@dataclass(frozen=True)
class ObservationMismatch:
    market_id: str
    start_ns: int
    end_ns: int
    expected: QuoteExpectation
    observed_quotes: int
    kind: str


def compare_expected_to_observed(
    calendar: VersionedMarketCalendar,
    timestamps_ns,
    start_ns: int,
    end_ns: int,
) -> list[ObservationMismatch]:
    """Confronte le calendrier normatif à la disponibilité réellement observée (ADR-132).

    Les deux restent des couches séparées : la divergence produit un événement auditable,
    elle ne corrige jamais le calendrier.
    """
    import numpy as np

    ts = np.asarray(timestamps_ns)
    out: list[ObservationMismatch] = []
    for seg in calendar.split_by_calendar_state(start_ns, end_ns):
        n = int(np.sum((ts >= seg.start_ns) & (ts < seg.end_ns)))
        if seg.quote_expectation is QuoteExpectation.QUOTES_NOT_EXPECTED and n > 0:
            out.append(ObservationMismatch(
                calendar.market_id, seg.start_ns, seg.end_ns,
                seg.quote_expectation, n, "cotations reçues pendant une fermeture attendue",
            ))
        elif seg.quote_expectation is QuoteExpectation.QUOTES_EXPECTED_NORMAL and n == 0:
            out.append(ObservationMismatch(
                calendar.market_id, seg.start_ns, seg.end_ns,
                seg.quote_expectation, 0, "aucune cotation pendant une période ouverte",
            ))
    return out


@dataclass(frozen=True)
class RevisionCandidate:
    """Proposition de révision — **jamais** appliquée automatiquement (ADR-136).

    Sans validation explicite, une panne répétée serait progressivement reclassée en
    fermeture normale, et le calendrier finirait par décrire les défaillances du flux
    plutôt que le marché.
    """

    market_id: str
    interval_start_ns: int
    interval_end_ns: int
    observed_pattern: str
    suggested_state: MarketState
    occurrences: int
    requires_explicit_validation: bool = True


def propose_revisions(mismatches: list[ObservationMismatch], min_occurrences: int = 5):
    grouped: dict[str, list[ObservationMismatch]] = {}
    for m in mismatches:
        grouped.setdefault(m.kind, []).append(m)

    return [
        RevisionCandidate(
            market_id=items[0].market_id,
            interval_start_ns=min(i.start_ns for i in items),
            interval_end_ns=max(i.end_ns for i in items),
            observed_pattern=kind,
            suggested_state=MarketState.UNKNOWN,
            occurrences=len(items),
        )
        for kind, items in grouped.items()
        if len(items) >= min_occurrences
    ]


# --------------------------------------------------------------- intersection


class Executability(str, Enum):
    EXECUTABLE_NORMAL = "EXECUTABLE_NORMAL"
    EXECUTABLE_REDUCED_CONTEXT = "EXECUTABLE_REDUCED_CONTEXT"
    ANALYSIS_ONLY = "ANALYSIS_ONLY"
    EXECUTION_CLOSED = "EXECUTION_CLOSED"
    DETECTION_CLOSED = "DETECTION_CLOSED"
    CALENDAR_UNKNOWN = "CALENDAR_UNKNOWN"


def executability(
    detection: MarketStateAt, execution: MarketStateAt
) -> tuple[Executability, bool]:
    """État composite d'une cellule intermarchés.

    Un signal détecté sur un marché ouvert n'a aucune autorité d'exécution si le marché
    d'exécution est fermé. Inversement, exécuter pendant que le marché de détection est
    fermé reste possible mais avec un contexte dégradé, ce qui doit être déclaré.
    """
    unknown = (
        detection.primary_state is MarketState.UNKNOWN
        or execution.primary_state is MarketState.UNKNOWN
    )
    if unknown:
        return Executability.CALENDAR_UNKNOWN, True

    exec_open = execution.quote_expectation is not QuoteExpectation.QUOTES_NOT_EXPECTED
    det_open = detection.quote_expectation is not QuoteExpectation.QUOTES_NOT_EXPECTED

    if not exec_open:
        return Executability.EXECUTION_CLOSED, not det_open
    if not det_open:
        return Executability.DETECTION_CLOSED, True
    if execution.primary_state is MarketState.OPEN_REDUCED or (
        detection.primary_state is MarketState.OPEN_REDUCED
    ):
        return Executability.EXECUTABLE_REDUCED_CONTEXT, True
    return Executability.EXECUTABLE_NORMAL, False


# ------------------------------------------------ calendrier synthétique de test


def synthetic_calendar(
    market_id: str = "BROKER_DEMO:XAUUSD:RAW",
    timezone: str = "Europe/London",
    session_start: dt.time = dt.time(9, 0),
    session_end: dt.time = dt.time(13, 0),
    version: str = "SYNTHETIC_CALENDAR_1.0",
    holiday: dt.date | None = None,
    half_session: dt.date | None = None,
    maintenance: tuple[dt.date, dt.time, dt.time] | None = None,
) -> VersionedMarketCalendar:
    """Calendrier de démonstration : semaine ouvrée, nuits, week-ends, plus exceptions.

    **Ce n'est pas un calendrier de marché réel.** Il sert à exercer le moteur — nuit
    planifiée, panne après réouverture, changement d'heure, férié, demi-séance,
    maintenance courtier — et non à décrire un quelconque horaire officiel.
    """
    prov = Provenance(
        source_id="synthetic",
        source_type="TEST_FIXTURE",
        retrieved_at="2026-08-06",
        content_hash="n/a",
        verification=VerificationStatus.UNVERIFIED,
    )
    always = Bitemporal(valid_from_ns=0)
    weekdays = frozenset({0, 1, 2, 3, 4})

    recurring = [
        RecurringRule(
            market_id=market_id, weekdays=weekdays,
            local_start=session_start, local_end=session_end, timezone=timezone,
            state=MarketState.OPEN_CONTINUOUS,
            quote_expectation=QuoteExpectation.QUOTES_EXPECTED_NORMAL,
            temporal=always, provenance=prov, label="seance",
        ),
        RecurringRule(
            market_id=market_id, weekdays=weekdays,
            local_start=session_end, local_end=session_start, timezone=timezone,
            state=MarketState.SCHEDULED_BREAK,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            temporal=always, provenance=prov, label="nuit",
        ),
        RecurringRule(
            market_id=market_id, weekdays=frozenset({5, 6}),
            local_start=dt.time(0, 0), local_end=dt.time(23, 59, 59, 999_999),
            timezone=timezone,
            state=MarketState.WEEKEND_CLOSED,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            temporal=always, provenance=prov, label="weekend",
        ),
    ]

    exceptions = []
    if holiday is not None:
        exceptions.append(CalendarException(
            market_id=market_id, local_date=holiday, timezone=timezone,
            state=MarketState.HOLIDAY_CLOSED,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            temporal=always, provenance=prov, reason="jour férié de test",
        ))
    if half_session is not None:
        exceptions.append(CalendarException(
            market_id=market_id, local_date=half_session, timezone=timezone,
            local_start=session_start, local_end=dt.time(11, 0),
            state=MarketState.OPEN_REDUCED,
            quote_expectation=QuoteExpectation.QUOTES_EXPECTED_SPARSE,
            temporal=always, provenance=prov, reason="demi-séance de test",
        ))
        exceptions.append(CalendarException(
            market_id=market_id, local_date=half_session, timezone=timezone,
            local_start=dt.time(11, 0), local_end=session_end,
            state=MarketState.EARLY_CLOSE,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            temporal=always, provenance=prov, reason="clôture anticipée de test",
        ))
    if maintenance is not None:
        day, m_start, m_end = maintenance
        exceptions.append(CalendarException(
            market_id=market_id, local_date=day, timezone=timezone,
            local_start=m_start, local_end=m_end,
            state=MarketState.BROKER_MAINTENANCE,
            quote_expectation=QuoteExpectation.QUOTES_NOT_EXPECTED,
            temporal=always, provenance=prov, reason="maintenance courtier de test",
        ))

    return VersionedMarketCalendar(
        calendar_id=f"{market_id}:synthetic",
        calendar_version=version,
        market_id=market_id,
        timezone_database_version="stdlib-zoneinfo",
        recurring=tuple(recurring),
        exceptions=tuple(exceptions),
    )
