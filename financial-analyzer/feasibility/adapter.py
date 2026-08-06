"""Adaptateur strict entre les cotations du courtier et les entrées de calcul.

L'adaptateur **ne produit aucun verdict**. Il garantit seulement que les données qui
entreront dans les calculs sont correctement horodatées, exprimées dans des unités non
ambiguës, réellement exécutables, suffisamment denses, complètes ou explicitement marquées
comme incomplètes, et reproductibles depuis les données brutes.

Son livrable n'est pas la courbe kappa : c'est la **preuve que l'export permet de la
mesurer**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .contract import ContractSpecification

NS_PER_SECOND = 1_000_000_000


# --------------------------------------------------------------------------- statuts


class OrderingStatus(str, Enum):
    ORDERED = "ORDERED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    TIMESTAMP_CONFLICT = "TIMESTAMP_CONFLICT"


class QuoteQuality(str, Enum):
    VALID = "VALID"
    CROSSED_QUOTE = "CROSSED_QUOTE"
    ZERO_SPREAD = "ZERO_SPREAD"
    VALID_EXTREME = "VALID_EXTREME"
    SUSPECTED_BAD_TICK = "SUSPECTED_BAD_TICK"
    CONFIRMED_BAD_TICK = "CONFIRMED_BAD_TICK"


class GapClass(str, Enum):
    MARKET_CLOSED = "MARKET_CLOSED"
    EXPECTED_INACTIVITY = "EXPECTED_INACTIVITY"
    DATA_OUTAGE = "DATA_OUTAGE"
    UNKNOWN_GAP = "UNKNOWN_GAP"


class DensityStatus(str, Enum):
    DENSITY_VALID = "DENSITY_VALID"
    DENSITY_SPARSE = "DENSITY_SPARSE"
    DENSITY_QUANTIZED = "DENSITY_QUANTIZED"
    DENSITY_INVALID = "DENSITY_INVALID"


class BurstState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    BURST_P95 = "BURST_P95"
    BURST_P99 = "BURST_P99"


class AdapterError(ValueError):
    """Entrée inexploitable. L'adaptateur échoue plutôt que de produire du plausible."""


# ------------------------------------------------------------------------- horloges


@dataclass(frozen=True)
class ClockSync:
    """Qualité de synchronisation entre l'horloge du fournisseur et l'horloge locale.

    Sans synchronisation fiable, la latence **absolue** est indisponible — mais l'ordre
    temporel local reste utilisable pour les coûts. Les deux conclusions sont distinctes
    et ne doivent pas être confondues.
    """

    method: str
    offset_estimate_ns: float
    offset_uncertainty_ns: float

    @property
    def absolute_latency_usable(self) -> bool:
        """La latence absolue n'a de sens que si l'incertitude est petite devant elle."""
        return (
            np.isfinite(self.offset_uncertainty_ns)
            and self.offset_uncertainty_ns < abs(self.offset_estimate_ns) * 0.5
        )


@dataclass(frozen=True)
class TimestampResolution:
    """Résolution effective des horodatages, mesurée et non déclarée.

    Point souvent manqué : une résolution à la milliseconde suffit à quinze cotations par
    seconde, et perd tout l'ordre interne d'une rafale à cinq cents. Or la rafale est
    précisément le régime qui compte pour la latence conditionnelle.
    """

    inferred_granularity_ns: int
    zero_diff_fraction: float
    median_inter_arrival_ns: float
    burst_inter_arrival_ns: float

    @property
    def sufficient_for_bursts(self) -> bool:
        return self.inferred_granularity_ns < self.burst_inter_arrival_ns


def infer_timestamp_resolution(timestamps_ns: np.ndarray) -> TimestampResolution:
    diffs = np.diff(np.sort(timestamps_ns))
    positive = diffs[diffs > 0]
    if positive.size == 0:
        return TimestampResolution(0, 1.0, float("nan"), float("nan"))

    # La granularité effective est le plus petit écart non nul réellement observé :
    # une horloge à la milliseconde ne produira jamais d'écart de 1 ns.
    granularity = int(np.min(positive))
    return TimestampResolution(
        inferred_granularity_ns=granularity,
        zero_diff_fraction=float(np.mean(diffs == 0)),
        median_inter_arrival_ns=float(np.median(positive)),
        burst_inter_arrival_ns=float(np.quantile(positive, 0.05)),
    )


# ------------------------------------------------------------------ cotations brutes


@dataclass(frozen=True)
class RawQuotes:
    """Cotations telles qu'exportées, dans leur ordre d'arrivée.

    `provider_timestamps_ns` peut être absent : certains courtiers ne le fournissent pas.
    Dans ce cas la latence de dissémination est indisponible, ce qui est déclaré plutôt
    que comblé.
    """

    receive_timestamps_ns: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    provider_timestamps_ns: np.ndarray | None = None
    sequence_numbers: np.ndarray | None = None
    source: str = "UNKNOWN"

    def __post_init__(self) -> None:
        n = self.receive_timestamps_ns.size
        if n == 0:
            raise AdapterError("Export vide.")
        for name in ("bid", "ask"):
            if getattr(self, name).size != n:
                raise AdapterError(
                    f"`{name}` n'est pas aligné sur les horodatages "
                    f"({getattr(self, name).size} contre {n})."
                )
        for name in ("provider_timestamps_ns", "sequence_numbers"):
            arr = getattr(self, name)
            if arr is not None and arr.size != n:
                raise AdapterError(f"`{name}` n'est pas aligné sur les horodatages.")


@dataclass
class NormalizedQuotes:
    """Cotations normalisées, avec leurs diagnostics attachés."""

    event_timestamps_ns: np.ndarray
    arrival_timestamps_ns: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    mid: np.ndarray
    spread: np.ndarray
    #: Rang d'arrivée d'origine, conservé : une arrivée tardive est une information sur
    #: la qualité du flux, pas un désordre à effacer par un tri.
    raw_arrival_order: np.ndarray
    ordering_status: np.ndarray
    quality: np.ndarray
    session_ids: np.ndarray
    cluster_ids: np.ndarray
    burst_states: np.ndarray
    tick_rate_1s: np.ndarray
    instrument_id: str
    clock: ClockSync | None
    resolution: TimestampResolution
    duplicate_fraction: float
    out_of_order_fraction: float
    normalizer_version: str = "BROKER_ADAPTER_1.0"

    @property
    def usable_mask(self) -> np.ndarray:
        """Cotations admissibles au chemin principal.

        Les cotations suspectes restent dans la structure — elles servent aux analyses de
        sensibilité — mais sortent du chemin de calcul. Seuls les mauvais ticks
        **confirmés** et les cotations croisées sont écartés.
        """
        excluded = {QuoteQuality.CONFIRMED_BAD_TICK.value, QuoteQuality.CROSSED_QUOTE.value}
        return ~np.isin(self.quality, list(excluded))


# ------------------------------------------------------------------ normalisation


def _classify_ordering(
    receive_ns: np.ndarray, sequences: np.ndarray | None
) -> tuple[np.ndarray, float, float]:
    n = receive_ns.size
    status = np.full(n, OrderingStatus.ORDERED.value, dtype=object)

    diffs = np.diff(receive_ns)
    status[1:][diffs < 0] = OrderingStatus.OUT_OF_ORDER.value
    status[1:][diffs == 0] = OrderingStatus.TIMESTAMP_CONFLICT.value

    if sequences is not None:
        seq_diff = np.diff(sequences)
        gap = seq_diff > 1
        dup = seq_diff == 0
        status[1:][gap] = OrderingStatus.SEQUENCE_GAP.value
        status[1:][dup] = OrderingStatus.DUPLICATE.value

    out_of_order = float(np.mean(status == OrderingStatus.OUT_OF_ORDER.value))
    duplicate = float(np.mean(status == OrderingStatus.DUPLICATE.value))
    return status, duplicate, out_of_order


def _deduplicate(quotes: RawQuotes) -> np.ndarray:
    """Indices à conserver, par ordre de priorité décroissante des clés.

    Une répétition **réelle** de cotation — même bid, même ask, publiée à nouveau — n'est
    pas une duplication technique : elle peut porter de l'information sur l'activité. Seule
    la seconde est écartée, et elle se reconnaît à l'identité de sa clé technique.
    """
    n = quotes.receive_timestamps_ns.size

    if quotes.sequence_numbers is not None:
        _, keep = np.unique(quotes.sequence_numbers, return_index=True)
        return np.sort(keep)

    if quotes.provider_timestamps_ns is not None:
        key = np.stack([quotes.provider_timestamps_ns, quotes.bid, quotes.ask], axis=1)
        _, keep = np.unique(key, axis=0, return_index=True)
        return np.sort(keep)

    key = np.stack([quotes.receive_timestamps_ns, quotes.bid, quotes.ask], axis=1)
    _, keep = np.unique(key, axis=0, return_index=True)
    return np.sort(keep)


def _classify_quality(
    bid: np.ndarray, ask: np.ndarray, mid: np.ndarray, contract: ContractSpecification
) -> np.ndarray:
    """Qualité par cotation.

    Un spread négatif n'est **jamais** remplacé silencieusement par zéro : il signale un
    réordonnancement, un flux composite mal synchronisé, une erreur de source, ou une
    situation de marché particulière — quatre causes qu'il faut pouvoir distinguer.
    """
    n = bid.size
    quality = np.full(n, QuoteQuality.VALID.value, dtype=object)
    spread = ask - bid

    quality[spread < 0] = QuoteQuality.CROSSED_QUOTE.value
    quality[spread == 0] = QuoteQuality.ZERO_SPREAD.value

    # Un déplacement extrême isolé, immédiatement annulé, est suspect ; un déplacement
    # extrême qui persiste est une nouvelle. Le critère est la persistance, pas l'ampleur.
    if n >= 3:
        step = np.diff(mid)
        scale = np.median(np.abs(step)) * 1.4826
        if scale > 0:
            big = np.abs(step) > 20.0 * scale
            reverted = np.zeros(n, dtype=bool)
            reverted[1:-1] = big[:-1] & big[1:] & (np.sign(step[:-1]) != np.sign(step[1:]))
            persisted = np.zeros(n, dtype=bool)
            persisted[1:-1] = big[:-1] & ~reverted[1:-1]
            quality[reverted & (quality == QuoteQuality.VALID.value)] = (
                QuoteQuality.SUSPECTED_BAD_TICK.value
            )
            quality[persisted & (quality == QuoteQuality.VALID.value)] = (
                QuoteQuality.VALID_EXTREME.value
            )
    return quality


def _tick_rate(timestamps_ns: np.ndarray, window_ns: int) -> np.ndarray:
    """Cadence dans la fenêtre glissante **précédant** chaque cotation."""
    starts = np.searchsorted(timestamps_ns, timestamps_ns - window_ns, side="left")
    return (np.arange(timestamps_ns.size) - starts).astype(float) / (window_ns / NS_PER_SECOND)


def _forward_tick_rate(timestamps_ns: np.ndarray, window_ns: int) -> np.ndarray:
    """Cadence dans la fenêtre **suivant** chaque cotation.

    Nécessaire pour classer une lacune : la cadence rétrospective du premier tick qui la
    suit vaut zéro par construction — c'est la lacune elle-même — et classerait toute
    coupure en inactivité normale.
    """
    ends = np.searchsorted(timestamps_ns, timestamps_ns + window_ns, side="right")
    return (ends - np.arange(timestamps_ns.size)).astype(float) / (window_ns / NS_PER_SECOND)


def _burst_states(rate: np.ndarray, session_ids: np.ndarray) -> np.ndarray:
    """État de rafale, par quantile **calculé séparément par session**.

    Sans cette séparation, une cadence normale de Londres serait classée en rafale au seul
    motif qu'elle dépasse la cadence asiatique — et la latence conditionnelle mesurerait
    alors l'heure de la journée plutôt que la charge.
    """
    states = np.full(rate.size, BurstState.NORMAL.value, dtype=object)
    for session in np.unique(session_ids):
        m = session_ids == session
        if m.sum() < 20:
            continue
        r = rate[m]
        q75, q95, q99 = np.quantile(r, [0.75, 0.95, 0.99])
        s = np.full(r.size, BurstState.NORMAL.value, dtype=object)
        s[r >= q75] = BurstState.ELEVATED.value
        s[r >= q95] = BurstState.BURST_P95.value
        s[r >= q99] = BurstState.BURST_P99.value
        states[m] = s
    return states


def normalize(
    quotes: RawQuotes,
    contract: ContractSpecification,
    session_of: "SessionResolver",
    clock: ClockSync | None = None,
) -> NormalizedQuotes:
    """Produit les cotations normalisées et leurs diagnostics."""
    keep = _deduplicate(quotes)
    duplicate_fraction = 1.0 - keep.size / quotes.receive_timestamps_ns.size

    receive = quotes.receive_timestamps_ns[keep]
    bid = quotes.bid[keep].astype(float)
    ask = quotes.ask[keep].astype(float)
    sequences = quotes.sequence_numbers[keep] if quotes.sequence_numbers is not None else None
    provider = (
        quotes.provider_timestamps_ns[keep] if quotes.provider_timestamps_ns is not None else None
    )

    ordering, dup_seq, out_of_order = _classify_ordering(receive, sequences)

    # L'ordre événementiel est reconstruit, mais l'ordre d'arrivée est conservé : une
    # cotation arrivée en retard reste identifiable comme telle.
    order = np.argsort(receive, kind="stable")
    raw_arrival_order = np.argsort(order, kind="stable")

    receive, bid, ask = receive[order], bid[order], ask[order]
    ordering = ordering[order]
    event_ts = provider[order] if provider is not None else receive

    mid = (bid + ask) / 2.0
    spread = ask - bid
    quality = _classify_quality(bid, ask, mid, contract)

    session_ids, cluster_ids = session_of(receive)
    rate_1s = _tick_rate(receive, NS_PER_SECOND)

    return NormalizedQuotes(
        event_timestamps_ns=event_ts,
        arrival_timestamps_ns=receive,
        bid=bid,
        ask=ask,
        mid=mid,
        spread=spread,
        raw_arrival_order=raw_arrival_order,
        ordering_status=ordering,
        quality=quality,
        session_ids=session_ids,
        cluster_ids=cluster_ids,
        burst_states=_burst_states(rate_1s, session_ids),
        tick_rate_1s=rate_1s,
        instrument_id=contract.instrument_id,
        clock=clock,
        resolution=infer_timestamp_resolution(receive),
        duplicate_fraction=max(duplicate_fraction, dup_seq),
        out_of_order_fraction=out_of_order,
    )


# ------------------------------------------------------------------------- sessions


class SessionResolver:
    """Attribue session et bloc indépendant à chaque cotation.

    Implémentation minimale fondée sur l'heure UTC. **Ce n'est pas un calendrier de
    marché** : les jours fériés, demi-séances et changements d'heure exigent le calendrier
    versionné, sans lequel les fermetures seront prises pour des interruptions de données.
    """

    def __init__(self, calendar_version: str = "PLACEHOLDER_NOT_A_REAL_CALENDAR"):
        self.calendar_version = calendar_version

    def __call__(self, timestamps_ns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        day = (timestamps_ns // (86_400 * NS_PER_SECOND)).astype(np.int64)
        hour = ((timestamps_ns // (3_600 * NS_PER_SECOND)) % 24).astype(np.int64)

        session = np.full(timestamps_ns.size, "OFF_HOURS", dtype=object)
        session[(hour >= 0) & (hour < 7)] = "ASIA"
        session[(hour >= 7) & (hour < 12)] = "LONDON"
        session[(hour >= 12) & (hour < 16)] = "OVERLAP_LONDON_NEW_YORK"
        session[(hour >= 16) & (hour < 21)] = "NEW_YORK"
        session[(hour >= 21) & (hour < 22)] = "ROLLOVER_WINDOW"
        return session, day


# ------------------------------------------------------------------------- lacunes


@dataclass(frozen=True)
class Gap:
    start_ns: int
    end_ns: int
    duration_ns: int
    preceding_rate: float
    following_rate: float
    classification: GapClass


def classify_gaps(
    timestamps_ns: np.ndarray,
    session_ids: np.ndarray,
    outage_threshold_ns: int,
    closed_sessions: tuple[str, ...] = ("OFF_HOURS",),
    session_of: "SessionResolver | None" = None,
) -> list[Gap]:
    """Un intervalle sans cotation n'est **jamais** une absence de mouvement.

    Il peut être un marché calme, une fermeture, une coupure de connexion, un trou
    d'export ou une interruption du fournisseur — cinq causes aux conséquences opposées.

    Une lacune se classe par ce qui se passe **pendant** elle, pas à ses extrémités : une
    coupure nocturne va de la clôture de New York à l'ouverture de Londres, et aucune de
    ses deux bornes n'est en session fermée. Sans échantillonnage intérieur, toutes les
    nuits seraient comptées comme des interruptions de données.
    """
    if timestamps_ns.size < 2:
        return []

    diffs = np.diff(timestamps_ns)
    idx = np.nonzero(diffs > outage_threshold_ns)[0]
    window = 30 * NS_PER_SECOND
    rate_before = _tick_rate(timestamps_ns, window)
    rate_after = _forward_tick_rate(timestamps_ns, window)

    gaps = []
    for i in idx:
        in_closed = session_ids[i] in closed_sessions or session_ids[i + 1] in closed_sessions
        if not in_closed and session_of is not None:
            interior = np.linspace(
                timestamps_ns[i], timestamps_ns[i + 1], num=12, dtype=np.int64
            )[1:-1]
            inside, _ = session_of(interior)
            in_closed = bool(np.isin(inside, list(closed_sessions)).any())
        before, after = float(rate_before[i]), float(rate_after[i + 1])
        if in_closed:
            cls = GapClass.MARKET_CLOSED
        elif before < 0.2 and after < 0.2:
            cls = GapClass.EXPECTED_INACTIVITY
        elif before > 1.0 and after > 1.0:
            # Le flux était actif avant et après : le silence n'est pas du marché.
            cls = GapClass.DATA_OUTAGE
        else:
            cls = GapClass.UNKNOWN_GAP
        gaps.append(
            Gap(
                start_ns=int(timestamps_ns[i]),
                end_ns=int(timestamps_ns[i + 1]),
                duration_ns=int(diffs[i]),
                preceding_rate=before,
                following_rate=after,
                classification=cls,
            )
        )
    return gaps


# ------------------------------------------------------------- densité et saturation


@dataclass(frozen=True)
class DensityDiagnostic:
    """Diagnostic Q48 pour un horizon."""

    horizon_ns: int
    window_count: int
    windows_with_no_update: float
    windows_with_one_update: float
    tick_count_p10: float
    tick_count_p50: float
    tick_count_p90: float
    unique_displacement_ratio: float
    zero_return_fraction: float
    one_tick_move_fraction: float
    median_abs_move_in_ticks: float
    status: DensityStatus

    @property
    def usable(self) -> bool:
        return self.status is DensityStatus.DENSITY_VALID


def density_diagnostic(
    timestamps_ns: np.ndarray,
    mid: np.ndarray,
    horizon_ns: int,
    tick_size: float,
    step: int = 1,
    min_windows: int = 500,
) -> DensityDiagnostic:
    """Mesure si un horizon est interprétable, avant tout verdict économique.

    Le défaut visé est celui observé sur données synthétiques : quand la médiane du
    déplacement vaut exactement un pas de cotation, l'amplitude mesure la discrétisation
    et non le marché — et la courbe kappa devient plate, ce qui se lit comme un résultat.
    """
    starts = np.arange(0, timestamps_ns.size, max(1, step), dtype=np.int64)
    ends = np.searchsorted(timestamps_ns, timestamps_ns[starts] + horizon_ns, side="left")
    valid = ends < timestamps_ns.size
    starts, ends = starts[valid], ends[valid]

    if starts.size == 0:
        return DensityDiagnostic(
            horizon_ns, 0, *(float("nan"),) * 8, DensityStatus.DENSITY_INVALID
        )

    counts = (ends - starts).astype(float)
    moves = mid[ends] - mid[starts]
    moves_in_ticks = np.round(np.abs(moves) / tick_size)

    unique_ratio = float(np.unique(np.round(moves / tick_size)).size) / float(moves.size)
    zero_fraction = float(np.mean(moves_in_ticks == 0))
    one_tick_fraction = float(np.mean(moves_in_ticks == 1))
    median_ticks = float(np.median(moves_in_ticks))

    if starts.size < min_windows:
        status = DensityStatus.DENSITY_INVALID
    elif median_ticks <= 1.0 or (zero_fraction + one_tick_fraction) > 0.5:
        # Signature de saturation : la moitié des fenêtres tient en un pas de cotation.
        status = DensityStatus.DENSITY_QUANTIZED
    elif float(np.quantile(counts, 0.5)) < 2.0:
        status = DensityStatus.DENSITY_SPARSE
    else:
        status = DensityStatus.DENSITY_VALID

    return DensityDiagnostic(
        horizon_ns=horizon_ns,
        window_count=int(starts.size),
        windows_with_no_update=float(np.mean(counts == 0)),
        windows_with_one_update=float(np.mean(counts == 1)),
        tick_count_p10=float(np.quantile(counts, 0.10)),
        tick_count_p50=float(np.quantile(counts, 0.50)),
        tick_count_p90=float(np.quantile(counts, 0.90)),
        unique_displacement_ratio=unique_ratio,
        zero_return_fraction=zero_fraction,
        one_tick_move_fraction=one_tick_fraction,
        median_abs_move_in_ticks=median_ticks,
        status=status,
    )


# ------------------------------------------------------------- cadence d'évaluation


def evaluation_delay(
    event_timestamps_ns: np.ndarray, cadence_ns: int, phase_ns: int = 0
) -> np.ndarray:
    """Délai entre un événement et le prochain cycle d'évaluation, **mesuré**.

    La valeur `cadence / 2` n'est exacte que sous arrivée uniforme indépendante de la
    cadence. Les cotations arrivent en rafale et s'alignent souvent sur des frontières de
    temps rondes : le délai réel se mesure sur les horodatages, il ne se déduit pas.
    """
    offset = (event_timestamps_ns - phase_ns) % cadence_ns
    return np.where(offset == 0, 0, cadence_ns - offset).astype(float)
