"""Source XAUUSD réelle — MetaTrader 5, et rejeu hors ligne.

Ce module est la frontière entre le laboratoire et le marché. Tout ce qui le précède
raisonne sur des observations ; lui seul en produit.

Trois propriétés de la source réelle sont déclarées ici plutôt que découvertes plus tard,
parce qu'elles changent ce que les mesures veulent dire :

1. **L'API MT5 se sonde, elle ne pousse pas.** `symbol_info_tick` rend le dernier tick
   connu ; il n'existe aucun rappel d'arrivée. B1 n'est donc pas l'instant d'arrivée mais
   l'instant où nous avons regardé. La quantification qui en résulte est bornée par
   l'intervalle de sondage, portée par `B1Anchor.POLL_OBSERVATION`, et **déclarée comme
   biais connu** au lieu d'être passée sous silence.

2. **`time_msc` est l'horloge du serveur du courtier.** Elle n'est pas comparable à notre
   horloge locale sans qualification : leur différence contient un décalage inconnu, pas
   seulement un temps de transport. Elle est enregistrée — la donnée ne se reconstruit
   pas — mais `provider_qualified` reste faux, et aucune borne locale ne s'en sert.

3. **Un tick identique n'est pas un nouvel événement.** MT5 rend le même tick tant qu'il
   n'y en a pas d'autre ; les compter tous transformerait la fréquence de sondage en
   activité de marché.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np

from .cost_floor_xauusd import AccountIdentity, AccountType, BaseCurrency, MT5SymbolSpecification
from .observability import MeasurementGrade
from .passive_campaign import NS_PER_MS, NS_PER_SECOND, CampaignError, MarketContext

SOURCE_VERSION = "XAUUSD_SOURCE_1.0"


class AcquisitionMode(str, Enum):
    """Comment les ticks nous parviennent."""

    #: Sondage périodique : B1 est quantifié par l'intervalle. Le seul mode offert par
    #: l'API Python de MT5.
    POLLED = "POLLED"
    #: Le transport nous réveille à l'arrivée. B1 est l'instant de réception.
    PUSHED = "PUSHED"
    #: Rejeu d'un journal : les instants sont ceux du fichier, aucune latence réseau.
    REPLAY = "REPLAY"


class B1Anchor(str, Enum):
    """Ce que B1 date réellement. À ne pas confondre avec la qualité de l'horloge.

    Les deux notions ont été mélangées une première fois, et le mélange était coûteux :
    classer une source sondée en `LOWER_BOUND` écartait chacune de ses observations de
    la distribution locale, et une collecte réelle d'une journée entière n'aurait produit
    aucun résumé — silencieusement.

    L'horloge, elle, est exacte dans les trois modes : les cinq frontières viennent du
    même `monotonic_ns`. Ce qui change d'un mode à l'autre, c'est l'**ancrage** de B1, et
    il se traite comme un biais déclaré, pas comme une horloge dégradée.
    """

    #: B1 date l'arrivée du tick. Aucun temps non observé avant lui.
    ARRIVAL = "ARRIVAL"
    #: B1 date l'instant où nous avons regardé. Jusqu'à un intervalle de sondage s'est
    #: écoulé avant, sans être observé.
    POLL_OBSERVATION = "POLL_OBSERVATION"
    #: Rejeu : il n'y a pas eu de transport du tout. Les durées mesurées sont celles de
    #: la machine, jamais celles du marché.
    REPLAY_NO_TRANSPORT = "REPLAY_NO_TRANSPORT"


@dataclass(frozen=True)
class AcquisitionContract:
    """Ce que la source promet, et ce qu'elle ne promet pas.

    `poll_interval_ns` n'est pas un réglage de confort : c'est la borne supérieure du
    temps écoulé avant B1 sans être observé. Publier la latence sans lui reviendrait à
    s'attribuer une réactivité que l'acquisition ne permet pas.
    """

    mode: AcquisitionMode
    poll_interval_ns: int = 0
    provider_clock_qualified: bool = False
    description: str = ""
    #: Vrai quand les durées mesurées décrivent le chemin réel du marché. Faux en rejeu :
    #: elles y décrivent la vitesse de lecture d'un fichier.
    measures_market_latency: bool = True

    def __post_init__(self) -> None:
        if self.mode is AcquisitionMode.POLLED and self.poll_interval_ns <= 0:
            raise CampaignError(
                "un mode sondé sans intervalle déclaré cacherait la quantification "
                "qu'il ajoute à B1"
            )

    @property
    def b1_anchor(self) -> B1Anchor:
        if self.mode is AcquisitionMode.PUSHED:
            return B1Anchor.ARRIVAL
        if self.mode is AcquisitionMode.POLLED:
            return B1Anchor.POLL_OBSERVATION
        return B1Anchor.REPLAY_NO_TRANSPORT

    @property
    def b1_quantisation_bias_ns(self) -> int:
        """Temps maximal écoulé avant B1 sans avoir été observé."""
        return self.poll_interval_ns if self.mode is AcquisitionMode.POLLED else 0

    @property
    def clock_grade(self) -> MeasurementGrade:
        """Qualité de l'**horloge**, et rien d'autre.

        Les cinq frontières sortent du même compteur monotone local : la mesure est
        exacte. Ce qui manque avant B1 est un biais connu et borné, déclaré à part — il
        élargit la borne inférieure, il ne rend pas la mesure d'une autre nature.
        """
        return MeasurementGrade.EXACT_LOCAL


@dataclass(frozen=True)
class Tick:
    """Un tick normalisé. Rien de dérivé, rien de reconstruit."""

    bid: float
    ask: float
    #: Horodatage du serveur du courtier, en nanosecondes. Non qualifié par défaut.
    provider_ns: int | None
    volume: float = 0.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def identity(self) -> tuple[int | None, float, float]:
        """Ce qui distingue deux ticks. Sert à ne pas compter deux fois le même."""
        return (self.provider_ns, self.bid, self.ask)


class QuoteSource(Protocol):
    """Ce dont le collecteur a besoin, et rien de plus."""

    contract: AcquisitionContract

    def open(self) -> None: ...
    def close(self) -> None: ...
    def account_identity(self) -> AccountIdentity: ...
    def symbol_specification(self) -> MT5SymbolSpecification | None: ...
    def ticks(self) -> Iterator[Tick]: ...


# ------------------------------------------------------------------ état de marché


class MarketStateEstimator:
    """Produit un `MarketContext` en ligne, sur le chemin critique.

    Les centiles sont calculés sur une fenêtre glissante bornée, jamais sur l'historique
    complet : un centile calculé après coup sur toute la séance ne serait pas celui que
    le système a connu au moment de décider — et c'est celui-là qui explique la latence.
    """

    def __init__(self, history: int = 2_048, warmup: int = 64) -> None:
        if history < 2:
            raise CampaignError("la fenêtre de centiles doit contenir au moins 2 points")
        self._history = history
        self._warmup = warmup
        self._times: deque[int] = deque()
        self._spreads: deque[float] = deque(maxlen=history)
        self._rates: deque[float] = deque(maxlen=history)
        self._last_mid: float | None = None
        self._last_ns: int | None = None

    def update(self, tick: Tick, now_ns: int) -> MarketContext:
        self._times.append(now_ns)
        cutoff = now_ns - 5 * NS_PER_SECOND
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

        r100 = self._rate(now_ns, 100 * NS_PER_MS)
        r1 = self._rate(now_ns, NS_PER_SECOND)
        r5 = self._rate(now_ns, 5 * NS_PER_SECOND)

        velocity = 0.0
        if self._last_mid is not None and self._last_ns is not None:
            dt = now_ns - self._last_ns
            if dt > 0:
                velocity = abs(tick.mid - self._last_mid) / (dt / NS_PER_SECOND)
        self._last_mid, self._last_ns = tick.mid, now_ns

        spread_pct = self._percentile_of(self._spreads, tick.spread)
        burst_pct = self._percentile_of(self._rates, r1)
        self._spreads.append(tick.spread)
        self._rates.append(r1)

        return MarketContext(
            tick_rate_100ms=r100,
            tick_rate_1s=r1,
            tick_rate_5s=r5,
            spread=tick.spread,
            spread_percentile=spread_pct,
            price_velocity=velocity,
            burst_percentile=burst_pct,
        )

    @property
    def warm(self) -> bool:
        """Vrai quand les centiles reposent sur assez de points pour signifier quelque chose."""
        return len(self._spreads) >= self._warmup

    def _rate(self, now_ns: int, window_ns: int) -> float:
        start = now_ns - window_ns
        n = sum(1 for t in self._times if t >= start)
        return n / (window_ns / NS_PER_SECOND)

    def _percentile_of(self, values: deque[float], current: float) -> float:
        """Rang du point courant dans la fenêtre — 0.0 tant que la fenêtre est vide.

        Un rang par défaut à 0 est le choix sûr : il classe l'événement en régime normal
        et n'invente pas une rafale au démarrage.
        """
        if not values:
            return 0.0
        below = sum(1 for v in values if v < current)
        return below / len(values)


# ------------------------------------------------------------------- source MT5


class MT5Source:
    """Source réelle : terminal MetaTrader 5 connecté au compte IC Markets.

    Le paquet `MetaTrader5` n'est importé qu'à l'ouverture. Le module reste donc
    importable — et testable — sur une machine sans terminal, ce qui est le cas de tout
    environnement d'intégration.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        poll_interval_ns: int = 1 * NS_PER_MS,
        monotonic_ns=time.monotonic_ns,
        mt5_module=None,
    ) -> None:
        self.symbol = symbol
        self.contract = AcquisitionContract(
            mode=AcquisitionMode.POLLED,
            poll_interval_ns=poll_interval_ns,
            provider_clock_qualified=False,
            description=(
                f"MetaTrader 5 — symbol_info_tick({symbol}) sondé toutes les "
                f"{poll_interval_ns / NS_PER_MS:g} ms"
            ),
        )
        self._mono = monotonic_ns
        self._mt5 = mt5_module
        self._last_identity: tuple[int | None, float, float] | None = None

    # ------------------------------------------------------------------ cycle de vie

    def open(self) -> None:
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - dépend de la machine
                raise CampaignError(
                    "le paquet MetaTrader5 est absent. Il n'existe que sur Windows et "
                    "exige un terminal MT5 ouvert et connecté au compte. Sur une autre "
                    "machine, utiliser --source replay pour valider la chaîne."
                ) from exc
            self._mt5 = mt5
        if not self._mt5.initialize():  # pragma: no cover - dépend du terminal
            raise CampaignError(
                f"initialisation MT5 refusée : {self._mt5.last_error()}. Le terminal "
                "doit être ouvert, connecté, et « Algo Trading » autorisé."
            )
        if not self._mt5.symbol_select(self._symbol_arg(), True):  # pragma: no cover
            raise CampaignError(
                f"symbole {self.symbol} indisponible sur ce compte. Le nom exact peut "
                "différer (XAUUSD, XAUUSD.a, GOLD…) : le relever dans l'Observation du "
                "marché."
            )

    def close(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()

    def _symbol_arg(self) -> str:
        return self.symbol

    # -------------------------------------------------------------------- préflight

    def account_identity(self) -> AccountIdentity:
        """Lit le type de compte et la devise de base — deux des trois éléments de Q63."""
        info = self._mt5.account_info()
        if info is None:  # pragma: no cover - dépend du terminal
            raise CampaignError("account_info() n'a rien rendu : compte non connecté")
        currency = str(getattr(info, "currency", "")).upper()
        try:
            base = BaseCurrency(currency)
        except ValueError:
            base = BaseCurrency.UNKNOWN

        # MT5 ne publie pas « Raw Spread » comme champ. Le nom commercial du compte le
        # porte, et une déduction incertaine ne doit pas devenir une commission
        # contractuelle : sans marqueur reconnu, le type reste UNKNOWN.
        label = f"{getattr(info, 'server', '')} {getattr(info, 'name', '')}".lower()
        if "raw" in label:
            account_type = AccountType.RAW_SPREAD
        elif "standard" in label:
            account_type = AccountType.STANDARD
        else:
            account_type = AccountType.UNKNOWN

        return AccountIdentity(
            account_type=account_type,
            base_currency=base,
            read_from=f"MT5 account_info() — serveur {getattr(info, 'server', '?')}",
        )

    def symbol_specification(self) -> MT5SymbolSpecification | None:
        """Relève la spécification contractuelle du symbole — le troisième élément de Q63."""
        info = self._mt5.symbol_info(self._symbol_arg())
        if info is None:  # pragma: no cover - dépend du terminal
            return None
        return MT5SymbolSpecification(
            symbol=self.symbol,
            contract_size=float(info.trade_contract_size),
            tick_size=float(info.trade_tick_size),
            point=float(info.point),
            volume_min=float(info.volume_min),
            volume_step=float(info.volume_step),
            volume_max=float(info.volume_max),
            currency_profit=str(info.currency_profit),
            currency_margin=str(info.currency_margin),
            digits=int(info.digits),
            swap_long=float(info.swap_long),
            swap_short=float(info.swap_short),
            swap_mode=str(getattr(info, "swap_mode", "")),
            swap_rollover_3days=int(getattr(info, "swap_rollover3days", 0)),
            read_at_ns=time.time_ns(),
            read_from=f"MT5 symbol_info({self.symbol})",
        )

    # ------------------------------------------------------------------------ flux

    def ticks(self) -> Iterator[Tick]:
        """Sonde le terminal et ne rend que les ticks réellement nouveaux."""
        interval = self.contract.poll_interval_ns / NS_PER_SECOND
        while True:
            raw = self._mt5.symbol_info_tick(self._symbol_arg())
            if raw is not None:
                tick = Tick(
                    bid=float(raw.bid),
                    ask=float(raw.ask),
                    provider_ns=int(raw.time_msc) * NS_PER_MS,
                    volume=float(getattr(raw, "volume_real", 0.0) or 0.0),
                )
                if tick.identity != self._last_identity:
                    self._last_identity = tick.identity
                    yield tick
            time.sleep(interval)


# ------------------------------------------------------------------ source rejeu


@dataclass
class ReplaySource:
    """Rejeu d'un journal de ticks. Sert à valider la chaîne avant de la brancher.

    Elle ne remplace jamais une collecte : les latences observées en rejeu sont celles de
    la machine, pas celles du marché. Son contrat le dit explicitement.
    """

    path: str
    symbol: str = "XAUUSD"
    account: AccountIdentity = field(default_factory=AccountIdentity)
    spec: MT5SymbolSpecification | None = None
    contract: AcquisitionContract = field(default_factory=lambda: AcquisitionContract(
        mode=AcquisitionMode.REPLAY,
        provider_clock_qualified=False,
        description="rejeu d'un journal — aucune latence réseau réelle",
        measures_market_latency=False,
    ))

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def account_identity(self) -> AccountIdentity:
        return self.account

    def symbol_specification(self) -> MT5SymbolSpecification | None:
        return self.spec

    def ticks(self) -> Iterator[Tick]:
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                yield Tick(
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    provider_ns=row.get("provider_ns"),
                    volume=float(row.get("volume", 0.0)),
                )


def synthetic_ticks(
    count: int, seed: int = 7, start_mid: float = 2_400.0, symbol: str = "XAUUSD"
) -> list[Tick]:
    """Ticks fabriqués — pour éprouver la chaîne, jamais pour en tirer une conclusion.

    Aucune propriété statistique de l'or n'est reproduite ici, et c'est volontaire : un
    faux marché crédible finirait par être pris pour un vrai.
    """
    rng = np.random.default_rng(seed)
    mid = start_mid
    out: list[Tick] = []
    for _ in range(count):
        mid += float(rng.normal(0.0, 0.05))
        half = abs(float(rng.normal(0.10, 0.03))) / 2.0
        out.append(Tick(bid=mid - half, ask=mid + half, provider_ns=None))
    return out


def acquisition_report(contract: AcquisitionContract) -> str:
    bias = contract.b1_quantisation_bias_ns
    lines = [
        f"ACQUISITION — {contract.mode.value}",
        f"  {contract.description}",
        f"  horloge des frontières   : {contract.clock_grade.value}",
        f"  ancrage de B1            : {contract.b1_anchor.value}",
        f"  horloge fournisseur      : "
        f"{'qualifiée' if contract.provider_clock_qualified else 'NON qualifiée'}",
    ]
    if bias:
        lines.append(
            f"  biais ajouté à B1        : jusqu'à {bias / NS_PER_MS:g} ms — à retrancher "
            "de toute réactivité annoncée"
        )
    if not contract.measures_market_latency:
        lines.append(
            "  ⚠ ces durées ne décrivent pas le marché : elles mesurent la traversée de "
            "cette machine.\n    Elles valident la chaîne, elles ne fondent aucun "
            "verdict de latence."
        )
    if not contract.provider_clock_qualified:
        lines.append(
            "  ⚠ B0 est enregistré mais n'entre dans aucune borne : l'écart entre "
            "l'horloge du\n    courtier et la nôtre contient un décalage inconnu, pas "
            "seulement un transport."
        )
    return "\n".join(lines)


def spec_from_mapping(row: dict, read_from: str) -> MT5SymbolSpecification:
    """Construit une spécification depuis un relevé manuel du terminal.

    Utile quand le terminal tourne sur une autre machine que le collecteur : les valeurs
    sont recopiées une fois, avec leur provenance, plutôt que devinées à chaque usage.
    """
    required = (
        "symbol", "contract_size", "tick_size", "point",
        "volume_min", "volume_step", "volume_max",
        "currency_profit", "currency_margin", "digits",
    )
    missing = [k for k in required if k not in row]
    if missing:
        raise CampaignError(
            f"relevé de spécification incomplet — champs manquants : {', '.join(missing)}"
        )
    return MT5SymbolSpecification(
        symbol=str(row["symbol"]),
        contract_size=float(row["contract_size"]),
        tick_size=float(row["tick_size"]),
        point=float(row["point"]),
        volume_min=float(row["volume_min"]),
        volume_step=float(row["volume_step"]),
        volume_max=float(row["volume_max"]),
        currency_profit=str(row["currency_profit"]),
        currency_margin=str(row["currency_margin"]),
        digits=int(row["digits"]),
        swap_long=_opt_float(row.get("swap_long")),
        swap_short=_opt_float(row.get("swap_short")),
        swap_mode=str(row.get("swap_mode", "")),
        swap_rollover_3days=_opt_int(row.get("swap_rollover_3days")),
        read_at_ns=int(row.get("read_at_ns", 0)),
        read_from=read_from,
    )


def _opt_float(v) -> float | None:
    return None if v is None else float(v)


def _opt_int(v) -> int | None:
    return None if v is None else int(v)


def write_ticks(path: str, ticks: Sequence[Tick]) -> int:
    with open(path, "a", encoding="utf-8") as fh:
        for t in ticks:
            fh.write(json.dumps({
                "bid": t.bid, "ask": t.ask,
                "provider_ns": t.provider_ns, "volume": t.volume,
            }, separators=(",", ":")) + "\n")
    return len(ticks)
