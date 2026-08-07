"""Les cinq points d'instrumentation de Q51-A (§30).

À brancher dans la boucle réelle. **Aucun ordre, aucun risque financier, aucun moteur
prédictif nécessaire.**

    on_quote_received()  →  on_event_eligible()  →  on_evaluation_start()
                         →  on_evaluation_end()  →  on_decision_ready()

Trois contraintes gouvernent la conception, et aucune n'est cosmétique :

1. **Les données ne se reconstruisent pas après coup.** Une latence non journalisée au
   moment où elle s'est produite est perdue définitivement. Le journal est donc
   append-only et vidé sur disque régulièrement, pas seulement à l'arrêt du processus.
2. **La campagne fait partie du chemin critique qu'elle mesure.** La sérialisation est
   différée hors du chemin ; le surcoût résiduel est mesuré et publié plutôt que supposé
   négligeable.
3. **Une évaluation sans décision n'est pas une évaluation rapide.** Elle est comptée
   comme abandonnée, jamais complétée par une valeur plausible.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .latency_journal import BurstState, ConnectionState
from .observability import MeasurementGrade, format_ns
from .passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    CampaignCell,
    CampaignError,
    ClusterAssigner,
    HostLoad,
    MarketContext,
    PassiveBoundaries,
    PassiveObservation,
)

RECORDER_VERSION = "Q51A_RECORDER_1.0"


class DropReason(str, Enum):
    """Pourquoi une évaluation n'a pas produit d'observation."""

    NO_DECISION = "NO_DECISION"
    CLOCK_DISCONTINUITY = "CLOCK_DISCONTINUITY"
    OVERFLOW = "OVERFLOW"
    OUT_OF_ORDER = "OUT_OF_ORDER"


@dataclass
class _InFlight:
    event_id: int
    provider_event_ns: int | None
    receive_ns: int
    receive_wall_ns: int
    market: MarketContext
    eligible_ns: int | None = None
    evaluation_start_ns: int | None = None
    evaluation_end_ns: int | None = None


@dataclass
class RecorderStats:
    received: int = 0
    completed: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    clock_discontinuities: int = 0
    max_in_flight: int = 0
    #: Coût de l'instrumentation elle-même, mesuré sur le chemin critique.
    instrumentation_ns_total: int = 0

    def drop(self, reason: DropReason) -> None:
        self.dropped[reason.value] = self.dropped.get(reason.value, 0) + 1

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())

    @property
    def mean_instrumentation_ns(self) -> float:
        n = self.received or 1
        return self.instrumentation_ns_total / n


class PassiveRecorder:
    """Collecteur des cinq frontières. Un seul par processus d'évaluation.

    Les horloges sont injectables : la boucle réelle passe `time.monotonic_ns` et
    `time.time_ns`, les tests passent une horloge déterministe. C'est la même règle que
    partout ailleurs — l'horloge murale sert à relier des systèmes, la monotone à mesurer
    des durées.
    """

    def __init__(
        self,
        cell_of: Callable[[MarketContext], CampaignCell],
        clusters: ClusterAssigner,
        sink_path: str | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_ns: Callable[[], int] = time.time_ns,
        max_in_flight: int = 4_096,
        flush_every: int = 256,
        day_of: Callable[[int], str] | None = None,
        drift_tolerance_ns: int = 50 * NS_PER_MS,
    ) -> None:
        self._cell_of = cell_of
        self._clusters = clusters
        self._mono = monotonic_ns
        self._wall = wall_ns
        self._max_in_flight = max_in_flight
        self._flush_every = flush_every
        self._day_of = day_of or _utc_day
        self._sink_path = sink_path
        self._drift_tolerance_ns = drift_tolerance_ns

        self._in_flight: dict[int, _InFlight] = {}
        self._next_id = 0
        self._pending: list[PassiveObservation] = []
        self._buffer: list[str] = []
        self._last_wall = 0
        self._last_mono = 0
        # Drapeau explicite : une horloge monotone peut légitimement valoir 0 au premier
        # appel, et tester sa vérité sauterait silencieusement le premier contrôle.
        self._have_previous = False
        self.stats = RecorderStats()

    # ------------------------------------------------------------ les cinq points

    def on_quote_received(
        self,
        market: MarketContext,
        provider_event_ns: int | None = None,
    ) -> int:
        """B1 — première frontière. Retourne l'identifiant à passer aux suivantes."""
        t0 = self._mono()
        wall = self._wall()

        # Deux règles, et une seule est absolue.
        #
        # Le **signe** de ΔW s'applique sans seuil (ADR-162) : une murale qui recule
        # pendant que la monotone avance est une discontinuité quelle que soit son
        # amplitude.
        #
        # Mais ce contrôle ne voit que ce qui se passe **entre deux échantillons**. Un
        # recul d'une nanoseconde survenu au milieu d'un intervalle de 9 ms se solde par
        # un ΔW positif et reste invisible — il est d'ailleurs indiscernable d'une
        # dérive ordinaire. C'est l'écart D = ΔW − ΔM qui le révèle, et lui seul relève
        # d'un seuil, versionné, puisqu'une correction en douceur produit légitimement
        # un D non nul.
        if self._have_previous:
            d_wall = wall - self._last_wall
            d_mono = t0 - self._last_mono
            if d_wall < 0 <= d_mono:
                self.stats.clock_discontinuities += 1
            elif abs(d_wall - d_mono) > self._drift_tolerance_ns:
                self.stats.clock_discontinuities += 1
        self._last_wall, self._last_mono = wall, t0
        self._have_previous = True

        if len(self._in_flight) >= self._max_in_flight:
            # Saturation : on abandonne la plus ancienne plutôt que de laisser la mémoire
            # croître. L'abandon est compté — il ne disparaît pas silencieusement.
            oldest = min(self._in_flight)
            del self._in_flight[oldest]
            self.stats.drop(DropReason.OVERFLOW)

        self._next_id += 1
        eid = self._next_id
        self._in_flight[eid] = _InFlight(
            event_id=eid,
            provider_event_ns=provider_event_ns,
            receive_ns=t0,
            receive_wall_ns=wall,
            market=market,
        )
        self.stats.received += 1
        self.stats.max_in_flight = max(self.stats.max_in_flight, len(self._in_flight))
        self.stats.instrumentation_ns_total += self._mono() - t0
        return eid

    def on_event_eligible(self, event_id: int) -> None:
        """B2 — l'événement devient éligible à l'évaluation."""
        self._stamp(event_id, "eligible_ns")

    def on_evaluation_start(self, event_id: int) -> None:
        """B3 — début d'évaluation. L'attente `B3 − B2` est mesurée, jamais supposée."""
        self._stamp(event_id, "evaluation_start_ns")

    def on_evaluation_end(self, event_id: int) -> None:
        """B4 — fin d'évaluation."""
        self._stamp(event_id, "evaluation_end_ns")

    def on_decision_ready(
        self,
        event_id: int,
        host: HostLoad,
        connection_state: ConnectionState = ConnectionState.CONNECTED_STABLE,
        calendar_state: str = "OPEN",
        clock_grade: MeasurementGrade = MeasurementGrade.EXACT_LOCAL,
        macro_window: bool = False,
        provider_qualified: bool = False,
    ) -> PassiveObservation | None:
        """B5 — dernière frontière. Produit l'observation, ou rien si le chemin est
        incomplet : une frontière manquante n'est jamais remplacée par une estimation."""
        t0 = self._mono()
        pending = self._in_flight.pop(event_id, None)
        if pending is None:
            return None
        if None in (pending.eligible_ns, pending.evaluation_start_ns,
                    pending.evaluation_end_ns):
            self.stats.drop(DropReason.NO_DECISION)
            self.stats.instrumentation_ns_total += self._mono() - t0
            return None

        try:
            boundaries = PassiveBoundaries(
                provider_event_ns=pending.provider_event_ns,
                local_receive_ns=pending.receive_ns,
                eligible_ns=pending.eligible_ns,
                evaluation_start_ns=pending.evaluation_start_ns,
                evaluation_end_ns=pending.evaluation_end_ns,
                decision_ready_ns=t0,
                local_receive_wall_ns=pending.receive_wall_ns,
            )
            observation = PassiveObservation(
                boundaries=boundaries,
                market=pending.market,
                host=host,
                cell=self._cell_of(pending.market),
                cluster_id=self._clusters.assign(
                    pending.receive_ns, pending.market.tick_rate_1s
                ),
                day=self._day_of(pending.receive_wall_ns),
                clock_grade=clock_grade,
                connection_state=connection_state,
                calendar_state=calendar_state,
                macro_window=macro_window,
                provider_qualified=provider_qualified,
            )
        except (CampaignError, ValueError):
            # Frontières hors ordre : la mesure est fausse, pas approximative.
            self.stats.drop(DropReason.OUT_OF_ORDER)
            self.stats.instrumentation_ns_total += self._mono() - t0
            return None

        self._pending.append(observation)
        self.stats.completed += 1
        # La sérialisation reste hors du chemin critique : seule la mise en file y entre.
        self._buffer.append(_encode(observation))
        if len(self._buffer) >= self._flush_every:
            self.flush()
        self.stats.instrumentation_ns_total += self._mono() - t0
        return observation

    # ----------------------------------------------------------------- persistance

    def flush(self) -> int:
        """Écrit le tampon sur disque. Append-only, jamais de réécriture.

        Appelée automatiquement tous les `flush_every` événements, et à appeler à
        l'arrêt. Ce qui n'est pas vidé au moment d'un incident est perdu — d'où un
        tampon volontairement petit.
        """
        if not self._sink_path or not self._buffer:
            n = len(self._buffer)
            self._buffer.clear()
            return n
        with open(self._sink_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(self._buffer) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        n = len(self._buffer)
        self._buffer.clear()
        return n

    def drain(self) -> list[PassiveObservation]:
        """Récupère et vide les observations accumulées en mémoire."""
        out, self._pending = self._pending, []
        return out

    @property
    def in_flight(self) -> int:
        return len(self._in_flight)

    def abandon_stale(self, older_than_ns: int) -> int:
        """Abandonne les évaluations sans décision au-delà d'un délai.

        Une évaluation qui ne conclut jamais n'est pas une évaluation rapide : la
        conserver en attente la ferait disparaître du dénominateur, et la latence
        moyenne s'améliorerait à mesure que le système échoue.
        """
        now = self._mono()
        stale = [
            eid for eid, p in self._in_flight.items()
            if now - p.receive_ns > older_than_ns
        ]
        for eid in stale:
            del self._in_flight[eid]
            self.stats.drop(DropReason.NO_DECISION)
        return len(stale)

    # --------------------------------------------------------------- effet observateur

    def observer_effect_report(self) -> str:
        """Surcoût de l'instrumentation, mesuré plutôt que supposé négligeable."""
        s = self.stats
        cost = (
            f"{format_ns(int(s.mean_instrumentation_ns))} par événement"
            if s.instrumentation_ns_total > 0
            else "non mesurable — l'horloge n'a pas avancé pendant les appels"
        )
        lines = [
            f"EFFET OBSERVATEUR — {s.received} réceptions, {s.completed} complétées, "
            f"{s.dropped_total} abandonnées",
            f"  coût moyen d'instrumentation : {cost}",
            f"  total sur le chemin critique : {format_ns(s.instrumentation_ns_total)}",
            f"  file d'évaluations maximale  : {s.max_in_flight}",
            f"  discontinuités d'horloge     : {s.clock_discontinuities}",
            f"  abandons par cause           : {s.dropped or '—'}",
        ]
        if s.received and s.instrumentation_ns_total == 0:
            # Un coût nul serait une fausse réassurance : une horloge monotone réelle ne
            # peut pas ne pas avancer entre l'entrée et la sortie d'un appel. Zéro
            # signale donc une horloge injectée ou une résolution trop grossière — pas
            # une instrumentation gratuite.
            lines.append(
                "  ⚠ un coût nul ne signifie pas une instrumentation gratuite : il "
                "révèle une horloge\n    injectée ou une résolution insuffisante pour "
                "la mesurer."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------------ interne

    def _stamp(self, event_id: int, field_name: str) -> None:
        t0 = self._mono()
        pending = self._in_flight.get(event_id)
        if pending is not None:
            setattr(pending, field_name, t0)
        self.stats.instrumentation_ns_total += self._mono() - t0


def _utc_day(wall_ns: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(wall_ns / NS_PER_SECOND))


def _encode(o: PassiveObservation) -> str:
    b = o.boundaries
    return json.dumps({
        "v": RECORDER_VERSION,
        "day": o.day,
        "cell": o.cell.label,
        "cluster": o.cluster_id,
        "b0": b.provider_event_ns,
        "b1": b.local_receive_ns,
        "b2": b.eligible_ns,
        "b3": b.evaluation_start_ns,
        "b4": b.evaluation_end_ns,
        "b5": b.decision_ready_ns,
        "wall": b.local_receive_wall_ns,
        "bound_ns": o.local_lower_bound_ns,
        "tick_rate_1s": o.market.tick_rate_1s,
        "spread": o.market.spread,
        "spread_pct": o.market.spread_percentile,
        "burst_pct": o.market.burst_percentile,
        "queue": o.host.evaluation_queue_depth,
        "loop_lag": o.host.event_loop_lag_ns,
        "cpu": o.host.cpu_load,
        "clock": o.clock_grade.value,
        "conn": o.connection_state.value,
        "calendar": o.calendar_state,
        "macro": o.macro_window,
    }, separators=(",", ":"))


def default_cell_of(
    session: str, host_id: str, software_commit: str,
    evaluation_mode, pipeline, source: str = "courtier",
    elevated: float = 0.75, p95: float = 0.95, p99: float = 0.99,
) -> Callable[[MarketContext], CampaignCell]:
    """Classe l'état de rafale à partir du **centile continu**, pas d'un seuil absolu.

    Les catégories ne servent qu'à présenter les résultats ; l'intensité continue reste
    conservée dans chaque observation pour tracer `L_p95(λ)` sans passer par elles.
    """
    def of(market: MarketContext) -> CampaignCell:
        p = market.burst_percentile
        state = (
            BurstState.BURST_P99 if p >= p99
            else BurstState.BURST_P95 if p >= p95
            else BurstState.ELEVATED if p >= elevated
            else BurstState.NORMAL
        )
        return CampaignCell(
            source=source, session=session, burst_state=state,
            evaluation_mode=evaluation_mode, pipeline=pipeline,
            host_id=host_id, software_commit=software_commit,
        )
    return of
