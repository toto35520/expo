"""Collecteur XAUUSD — la première collecte réelle du projet.

    python -m feasibility.collect_xauusd --source replay --file ticks.jsonl
    python -m feasibility.collect_xauusd --source mt5 --symbol XAUUSD --minutes 60

Aucun ordre n'est émis. Aucun moteur prédictif n'est appelé. Le collecteur branche les
cinq points d'instrumentation de Q51-A sur un vrai flux et écrit un journal append-only.

Une seule chose justifie de le lancer avant que le protocole soit gelé : **les données
d'aujourd'hui ne se recréent pas demain**. Elles seront classées `EXPLORATORY` — ce qui
attend le gel, c'est le droit d'en tirer un verdict, pas l'enregistrement lui-même
(ADR-204).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from .constraints import Q65_V1
from .cost_floor_xauusd import (
    CommissionBasis,
    Q63Specification,
    Q63Status,
    RolloverExposure,
)
from .latency_journal import ConnectionState
from .mandate import Q1_V1
from .mt5_source import (
    MarketStateEstimator,
    MT5Source,
    QuoteSource,
    ReplaySource,
    acquisition_report,
)
from .observability import format_ns
from .passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    ClusterAssigner,
    DataStatus,
    EvaluationMode,
    HostLoad,
    OrderType,
    PipelineMode,
    summarise_by_cell,
)
from .passive_recorder import PassiveRecorder, default_cell_of

COLLECTOR_VERSION = "XAUUSD_COLLECTOR_1.0"


@dataclass(frozen=True)
class EvaluationWorkload:
    """Ce que le collecteur fait entre B3 et B4.

    Rien de prédictif — et c'est la limite à déclarer. Une latence mesurée avec une
    évaluation vide est une **borne inférieure** de celle du système final : le jour où
    de vrais moteurs s'exécuteront là, B4 − B3 grandira. Publier ce chiffre comme la
    réactivité du système reviendrait à mesurer une voiture sans son moteur.
    """

    name: str = "NO_OP"
    represents_final_engine: bool = False
    description: str = (
        "aucun calcul décisionnel — seule la traversée du chemin est mesurée"
    )

    def run(self, market) -> None:
        return None


@dataclass
class CollectorConfig:
    symbol: str = "XAUUSD"
    session: str = "S1"
    out_dir: str = "collecte"
    max_events: int = 0
    max_seconds: float = 0.0
    flush_every: int = 128
    burst_threshold_per_s: float = 20.0
    quiet_block_ms: int = 250
    burst_reset_ms: int = 500
    stale_after_ms: int = 2_000
    pipeline: PipelineMode = PipelineMode.MINIMAL
    workload: EvaluationWorkload = field(default_factory=EvaluationWorkload)


@dataclass
class RunManifest:
    """Tout ce qu'il faudra savoir plus tard pour interpréter ce journal.

    Écrit **avant** la collecte : un manifeste rédigé après coup décrirait ce qu'on a
    trouvé plutôt que ce qu'on cherchait.
    """

    collector_version: str
    started_at_ns: int
    symbol: str
    session: str
    host_id: str
    software_commit: str
    acquisition_mode: str
    b1_quantisation_bias_ns: int
    provider_clock_qualified: bool
    evaluation_workload: str
    evaluation_is_final_engine: bool
    q1_version: str
    q1_fingerprint: str
    q63_version: str
    q63_status: str
    q63_fingerprint: str
    q65_version: str
    q65_fingerprint: str
    data_status: str

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.__dict__, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")


# ------------------------------------------------------------------------ préflight


@dataclass(frozen=True)
class Preflight:
    q63: Q63Specification
    floor_before_rollover: object
    floor_crossing_rollover: object

    @property
    def ready_to_record(self) -> bool:
        """Enregistrer ne dépend d'aucune résolution : seul un verdict en dépendrait."""
        return True

    def report(self) -> str:
        lines = [self.q63.report(), ""]
        lines.append("  cellule clôturée avant rollover :")
        lines.append(_indent(str(self.floor_before_rollover), 4))
        lines.append("  cellule pouvant traverser le rollover :")
        lines.append(_indent(str(self.floor_crossing_rollover), 4))
        return "\n".join(lines)


def preflight(source: QuoteSource) -> Preflight:
    """Interroge la source pour résoudre ce qui peut l'être de Q63 — sans rien inventer."""
    account = source.account_identity()
    spec = source.symbol_specification()
    q63 = Q63Specification(account=account, symbol_spec=spec)
    return Preflight(
        q63=q63,
        floor_before_rollover=q63.resolve(
            OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER,
            CommissionBasis.ENTRY_ONLY,
        ),
        floor_crossing_rollover=q63.resolve(
            OrderType.AGGRESSIVE, RolloverExposure.MAY_CROSS_ROLLOVER,
            CommissionBasis.ENTRY_ONLY,
        ),
    )


# ----------------------------------------------------------------------- collecte


class Collector:
    """Boucle de collecte. Un tick entre, une observation sort — ou un abandon compté."""

    def __init__(self, source: QuoteSource, config: CollectorConfig) -> None:
        self.source = source
        self.config = config
        self.market = MarketStateEstimator()
        self._stop = False
        self._started_ns = 0
        os.makedirs(config.out_dir, exist_ok=True)

        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base = f"{config.symbol}-{stamp}"
        self.journal_path = os.path.join(config.out_dir, f"{base}.jsonl")
        self.manifest_path = os.path.join(config.out_dir, f"{base}.manifest.json")

        self.recorder = PassiveRecorder(
            cell_of=default_cell_of(
                session=config.session,
                host_id=_host_id(),
                software_commit=_software_commit(),
                evaluation_mode=EvaluationMode.EVENT_DRIVEN,
                pipeline=config.pipeline,
                source=f"{config.symbol}@MT5",
            ),
            clusters=ClusterAssigner(
                burst_threshold=config.burst_threshold_per_s,
                reset_ns=config.burst_reset_ms * NS_PER_MS,
                quiet_block_ns=config.quiet_block_ms * NS_PER_MS,
                session_id=config.session,
            ),
            sink_path=self.journal_path,
            flush_every=config.flush_every,
        )

    # ------------------------------------------------------------------ manifeste

    def manifest(self, pre: Preflight) -> RunManifest:
        c = self.source.contract
        return RunManifest(
            collector_version=COLLECTOR_VERSION,
            started_at_ns=time.time_ns(),
            symbol=self.config.symbol,
            session=self.config.session,
            host_id=_host_id(),
            software_commit=_software_commit(),
            acquisition_mode=c.mode.value,
            b1_quantisation_bias_ns=c.b1_quantisation_bias_ns,
            provider_clock_qualified=c.provider_clock_qualified,
            evaluation_workload=self.config.workload.name,
            evaluation_is_final_engine=self.config.workload.represents_final_engine,
            q1_version=Q1_V1.version,
            q1_fingerprint=Q1_V1.fingerprint,
            q63_version=pre.q63.version,
            q63_status=pre.q63.status.value,
            q63_fingerprint=pre.q63.fingerprint,
            q65_version=Q65_V1.version,
            q65_fingerprint=Q65_V1.fingerprint,
            # Aucun gel de protocole n'est encore posé : tout ce qui sort d'ici est
            # exploratoire, et le restera même si les chiffres sont beaux.
            data_status=DataStatus.EXPLORATORY.value,
        )

    # -------------------------------------------------------------------- boucle

    def request_stop(self, *_: object) -> None:
        self._stop = True

    def run(self) -> int:
        """Consomme le flux jusqu'à la limite demandée ou l'interruption. Rend le compte."""
        cfg = self.config
        grade = self.source.contract.clock_grade
        self._started_ns = time.monotonic_ns()
        n = 0
        for tick in self.source.ticks():
            if self._stop:
                break
            now = time.monotonic_ns()
            context = self.market.update(tick, now)

            event_id = self.recorder.on_quote_received(
                context, provider_event_ns=tick.provider_ns
            )
            self.recorder.on_event_eligible(event_id)
            self.recorder.on_evaluation_start(event_id)
            cfg.workload.run(context)
            self.recorder.on_evaluation_end(event_id)
            self.recorder.on_decision_ready(
                event_id,
                host=self._host_load(),
                connection_state=ConnectionState.CONNECTED_STABLE,
                calendar_state="OPEN",
                clock_grade=grade,
                macro_window=False,
                # L'horloge du courtier n'a pas été qualifiée : B0 est conservé, mais
                # aucune borne ne s'en sert.
                provider_qualified=self.source.contract.provider_clock_qualified,
            )

            n += 1
            if n % 512 == 0:
                self.recorder.abandon_stale(cfg.stale_after_ms * NS_PER_MS)
            if cfg.max_events and n >= cfg.max_events:
                break
            if cfg.max_seconds and (now - self._started_ns) / NS_PER_SECOND >= cfg.max_seconds:
                break
        self.recorder.flush()
        return n

    def _host_load(self) -> HostLoad:
        return HostLoad(
            evaluation_queue_depth=self.recorder.in_flight,
            pending_event_count=self.recorder.in_flight,
            event_loop_lag_ns=0,
            cpu_load=_cpu_load(),
            memory_bytes=0,
        )

    # -------------------------------------------------------------------- rapport

    def report(self) -> str:
        observations = self.recorder.drain()
        lines = [
            "",
            "=" * 78,
            f"COLLECTE TERMINÉE — {len(observations)} observations",
            "=" * 78,
            "",
            self.recorder.observer_effect_report(),
            "",
        ]
        if not observations:
            lines.append("Aucune observation complète : rien à résumer.")
            return "\n".join(lines)

        if not self.market.warm:
            lines.append(
                "⚠ fenêtre de centiles non remplie : les classes de rafale de cette "
                "collecte\n  reposent sur trop peu de points pour être comparées entre "
                "séances."
            )
            lines.append("")

        by_cell = summarise_by_cell(observations)
        for cell, summary in sorted(by_cell.items(), key=lambda kv: kv[0].label):
            lines.append(f"CELLULE {cell.label}")
            lines.append(
                f"  n = {summary.observations}, grappes = {summary.clusters}"
            )
            lines.append(f"  p50 = {format_ns(int(summary.bound.p50))}")
            lines.append(f"  p95 = {format_ns(int(summary.bound.p95))} {_ci(summary)}")
            lines.append(f"  p99 = {format_ns(int(summary.bound.p99))}")
            lines.append("")

        if not self.source.contract.measures_market_latency:
            lines.append(
                "⚠ SOURCE DE REJEU : les durées ci-dessus sont celles de cette machine, "
                "pas celles du\n  marché. Elles prouvent que la chaîne fonctionne — rien "
                "de plus."
            )
        bias = self.source.contract.b1_quantisation_bias_ns
        if bias:
            lines.append(
                f"⚠ ces durées partent de B1, qui est un instant de sondage : jusqu'à "
                f"{bias / NS_PER_MS:g} ms\n  d'arrivée non observée les précèdent."
            )
        if not self.config.workload.represents_final_engine:
            lines.append(
                "⚠ l'évaluation était vide : ces durées bornent par le bas celles du "
                "système final."
            )
        lines.append(
            f"⚠ statut des données : {DataStatus.EXPLORATORY.value} — aucun gel de "
            "protocole n'a encore\n  été posé, donc aucun verdict normatif ne peut en "
            "sortir."
        )
        lines.append("")
        lines.append(f"journal   : {self.journal_path}")
        lines.append(f"manifeste : {self.manifest_path}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- outils


def _ci(summary) -> str:
    """Intervalle de confiance du p95, ou la raison de son absence.

    L'intervalle est bootstrappé **par grappe**. Avec une seule grappe il n'existe pas :
    afficher un intervalle nul y ferait passer une absence d'information pour une
    précision parfaite — l'inverse exact de ce que la mesure dit.
    """
    lo, hi = summary.p95_ci_low, summary.p95_ci_high
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return f"[IC non calculable — {summary.clusters} grappe(s)]"
    return f"[{format_ns(int(lo))} ; {format_ns(int(hi))}]"


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


def _host_id() -> str:
    try:
        return os.uname().nodename
    except AttributeError:  # pragma: no cover - Windows
        return os.environ.get("COMPUTERNAME", "inconnu")


def _software_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        commit = out.stdout.strip()
        if commit and out.returncode == 0:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )
            # Un dépôt modifié ne produit pas le même logiciel que son commit : le taire
            # ferait passer deux binaires différents pour un seul dans le gel de
            # protocole.
            return f"{commit}-dirty" if dirty.stdout.strip() else commit
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pass
    return "inconnu"


def _cpu_load() -> float:
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):  # pragma: no cover - Windows
        return 0.0


def build_source(args: argparse.Namespace) -> QuoteSource:
    if args.source == "mt5":
        return MT5Source(
            symbol=args.symbol,
            poll_interval_ns=int(args.poll_ms * NS_PER_MS),
        )
    if not args.file:
        raise SystemExit("--source replay exige --file")
    return ReplaySource(path=args.file, symbol=args.symbol)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="collect_xauusd",
        description="Collecte passive XAUUSD — aucun ordre, aucun moteur prédictif.",
    )
    p.add_argument("--source", choices=("mt5", "replay"), default="replay")
    p.add_argument("--file", help="journal de ticks pour --source replay")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--session", default="S1")
    p.add_argument("--out-dir", default="collecte")
    p.add_argument("--poll-ms", type=float, default=1.0)
    p.add_argument("--max-events", type=int, default=0)
    p.add_argument("--minutes", type=float, default=0.0)
    p.add_argument("--preflight-only", action="store_true")
    args = p.parse_args(argv)

    source = build_source(args)
    config = CollectorConfig(
        symbol=args.symbol,
        session=args.session,
        out_dir=args.out_dir,
        max_events=args.max_events,
        max_seconds=args.minutes * 60.0,
    )

    source.open()
    try:
        print(acquisition_report(source.contract))
        print()
        pre = preflight(source)
        print(pre.report())
        print()
        print(Q65_V1.report())
        print()
        print(f"Q1 — {Q1_V1.version} ({Q1_V1.fingerprint})")
        print()

        if pre.q63.status is Q63Status.PROVISIONAL:
            print(
                "Q63 est PROVISIONAL : aucune exclusion oracle ne peut être prononcée.\n"
                "La collecte, elle, n'attend rien — un tick non enregistré aujourd'hui "
                "est perdu.\n"
            )
        if args.preflight_only:
            return 0

        collector = Collector(source, config)
        collector.manifest(pre).write(collector.manifest_path)
        signal.signal(signal.SIGINT, collector.request_stop)
        try:
            signal.signal(signal.SIGTERM, collector.request_stop)
        except (AttributeError, ValueError):  # pragma: no cover - plateforme
            pass

        print(f"journal : {collector.journal_path}")
        print("collecte en cours — Ctrl-C pour arrêter proprement\n")
        collector.run()
        print(collector.report())
        return 0
    finally:
        source.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
