"""Q63 — plancher de coûts XAUUSD / IC Markets MT5 (`Q63-XAUUSD-ICMARKETS-MT5-V1`).

`C_floor` est la borne **inférieure** du coût réellement incontournable. Sa règle de
construction tient en une phrase : on préfère manquer une exclusion plutôt que d'en
fabriquer une. Un composant non prouvé vaut donc `0` — sauf lorsque son absence empêche
une conversion cohérente, auquel cas il vaut `UNRESOLVED` et **bloque** le plancher.

La distinction entre `0` et `UNRESOLVED` n'est pas de la prudence rhétorique. Elle est
arithmétique, et le financement en donne la démonstration :

    swap défavorable  →  C_réel = commission + swap  >  commission
    swap favorable    →  C_réel = commission − crédit  <  commission

Pour une cellule qui traverse le rollover sans que le swap soit connu, poser
`unavoidable_financing = 0` produit `C_floor = commission`. Si le swap est un crédit,
`C_réel < C_floor` : la propriété qui fonde toute exclusion est violée, et l'exclusion
devient fabriquée. Zéro n'est pas conservateur ici — il est faux.

Ce module ne modélise pas le coût réel de l'exécution. C'est le rôle de Q40. Un plancher
d'exclusion utilisé comme coût attendu rendrait toute stratégie plus rentable qu'elle
ne l'est : le garde-fou est explicite (`FloorUse`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum

from .passive_campaign import CampaignError, CostFloor, OrderType

Q63_VERSION = "Q63-XAUUSD-ICMARKETS-MT5-V1"

#: Le symbole visé. Toute autre valeur exige sa propre spécification contractuelle.
SYMBOL = "XAUUSD"
BROKER = "IC Markets"
PLATFORM = "MetaTrader 5"


class Unresolved:
    """Sentinelle : composant dont l'absence empêche une conversion cohérente.

    Volontairement distincte de `None` et de `0.0`. `None` se confond avec « pas de
    valeur », `0.0` avec « valeur nulle prouvée » — et c'est exactement la confusion qui
    transforme une ignorance en plancher.
    """

    _instance: "Unresolved | None" = None

    def __new__(cls) -> "Unresolved":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNRESOLVED"

    def __bool__(self) -> bool:
        raise CampaignError(
            "UNRESOLVED n'a pas de valeur de vérité : le tester comme un booléen le "
            "ferait silencieusement passer pour zéro."
        )


UNRESOLVED = Unresolved()

Component = float | Unresolved


class AccountType(str, Enum):
    """Structure tarifaire du compte. Elle change la nature du plancher, pas son niveau."""

    #: Commission séparée, spread brut. La commission est contractuelle donc plancher.
    RAW_SPREAD = "RAW_SPREAD"
    #: Pas de commission séparée : le coût passe par un mark-up de spread, qui n'est pas
    #: un plancher tant qu'aucune borne inférieure positive n'est démontrée.
    STANDARD = "STANDARD"
    UNKNOWN = "UNKNOWN"


class BaseCurrency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    UNKNOWN = "UNKNOWN"


#: Tarif MetaTrader Raw Spread, par lot standard, **aller-retour**, dans la devise du
#: compte. Source : IC Markets EU — Trading Costs (métaux précieux inclus).
RAW_COMMISSION_ROUND_TURN: dict[BaseCurrency, float] = {
    BaseCurrency.USD: 7.00,
    BaseCurrency.EUR: 6.50,
    BaseCurrency.GBP: 5.50,
}


class RolloverExposure(str, Enum):
    """Ce que la cellule fait du rollover. La seule question qui décide du financement."""

    #: La position est obligatoirement clôturée avant le rollover. Le financement est
    #: alors nul **exactement**, et c'est une preuve, pas une hypothèse prudente.
    CLOSES_BEFORE_ROLLOVER = "CLOSES_BEFORE_ROLLOVER"
    #: La position peut traverser le rollover. Le financement devient `UNRESOLVED`.
    MAY_CROSS_ROLLOVER = "MAY_CROSS_ROLLOVER"


class CommissionBasis(str, Enum):
    """Combien de côtés de la commission sont réellement inévitables pour la mesure."""

    #: L'entrée et la sortie sont toutes deux dans la fenêtre mesurée.
    ROUND_TURN = "ROUND_TURN"
    #: Seule l'entrée est certaine dans la fenêtre. Retenir l'aller-retour compterait un
    #: coût hors périmètre de la capture mesurée, et gonflerait le plancher.
    ENTRY_ONLY = "ENTRY_ONLY"

    @property
    def sides(self) -> float:
        return 1.0 if self is CommissionBasis.ROUND_TURN else 0.5


class FloorUse(str, Enum):
    """À quoi le plancher a le droit de servir."""

    #: Répondre à « cette capture maximale suffit-elle à couvrir le coût minimal ? ».
    ORACLE_EXCLUSION = "ORACLE_EXCLUSION"
    #: Estimer ce qu'un trade coûtera réellement. **Interdit** : c'est Q40.
    EXPECTED_COST_MODEL = "EXPECTED_COST_MODEL"


class Q63Status(str, Enum):
    #: Utilisable pour l'exclusion, pas encore pour une conversion exacte vers R.
    PROVISIONAL = "PROVISIONAL"
    #: Les trois éléments manquants ont été relevés dans le terminal du compte.
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class MT5SymbolSpecification:
    """Spécification contractuelle du symbole, relevée dans le terminal.

    Ces valeurs ne se devinent pas : elles sont propres au compte et au courtier. C'est
    la raison pour laquelle Q63 reste `PROVISIONAL` sans elles — pas une précaution de
    principe, une impossibilité de conversion.
    """

    symbol: str
    contract_size: float
    tick_size: float
    point: float
    volume_min: float
    volume_step: float
    volume_max: float
    currency_profit: str
    currency_margin: str
    digits: int
    #: Relevé le jour de la collecte : les swaps publiés varient et la référence est la
    #: plateforme du compte, pas une page web.
    swap_long: float | None = None
    swap_short: float | None = None
    swap_mode: str = ""
    swap_rollover_3days: int | None = None
    read_at_ns: int = 0
    read_from: str = ""

    def __post_init__(self) -> None:
        if self.contract_size <= 0:
            raise CampaignError("contract_size doit être strictement positif")
        if self.tick_size <= 0:
            raise CampaignError("tick_size doit être strictement positif")
        if self.volume_min <= 0:
            raise CampaignError("volume_min doit être strictement positif")
        if not self.read_from.strip():
            raise CampaignError(
                "une spécification de symbole sans provenance ne se distingue pas de "
                "valeurs saisies à la main"
            )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({
            k: v for k, v in self.__dict__.items() if k != "read_at_ns"
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def swaps_known(self) -> bool:
        return self.swap_long is not None and self.swap_short is not None


@dataclass(frozen=True)
class AccountIdentity:
    """Ce qu'il faut savoir du compte pour convertir une commission en unité de prix."""

    account_type: AccountType = AccountType.UNKNOWN
    base_currency: BaseCurrency = BaseCurrency.UNKNOWN
    read_from: str = ""

    @property
    def known(self) -> bool:
        return (
            self.account_type is not AccountType.UNKNOWN
            and self.base_currency is not BaseCurrency.UNKNOWN
        )


@dataclass(frozen=True)
class MissingElement:
    name: str
    why: str
    where: str


@dataclass(frozen=True)
class FloorResolution:
    """Résultat d'une résolution de plancher : un `CostFloor`, ou l'explication de son absence."""

    status: Q63Status
    order_type: OrderType
    floor: CostFloor | None
    missing: tuple[MissingElement, ...] = ()
    components: dict[str, Component] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.floor is not None

    def value_for(self, use: FloorUse) -> float:
        """Valeur du plancher, pour un usage déclaré.

        Le garde-fou n'est pas décoratif : un plancher d'exclusion vaut délibérément
        moins que le coût réel. L'employer comme coût attendu ferait apparaître un
        avantage là où il n'y en a pas — l'erreur exactement inverse de celle contre
        laquelle le plancher protège.
        """
        if use is not FloorUse.ORACLE_EXCLUSION:
            raise CampaignError(
                "Le plancher Q63 ne sert qu'à l'exclusion oracle. Il sous-estime "
                "délibérément le coût réel ; l'utiliser comme coût attendu surestimerait "
                "la rentabilité. Le modèle de coût réel est Q40."
            )
        if self.floor is None:
            names = ", ".join(m.name for m in self.missing)
            raise CampaignError(
                f"plancher non résolu — éléments manquants : {names}. Un composant "
                "UNRESOLVED ne devient pas zéro : pour une cellule traversant le "
                "rollover, un swap créditeur rendrait le coût réel inférieur au "
                "plancher, ce qui fabriquerait l'exclusion au lieu de la fonder."
            )
        return self.floor.value

    def __str__(self) -> str:
        head = f"Q63 {self.status.value} — {self.order_type.value}"
        if self.floor is not None:
            head += f" — C_floor = {self.floor.value:+.6f} {self.floor.unit}"
        else:
            head += " — NON RÉSOLU"
        lines = [head]
        for name, comp in self.components.items():
            shown = repr(comp) if isinstance(comp, Unresolved) else f"{comp:+.6f}"
            lines.append(f"    {name:<26} {shown}")
        for m in self.missing:
            lines.append(f"  ✗ {m.name} — {m.why}")
            lines.append(f"      à relever dans : {m.where}")
        for n in self.notes:
            lines.append(f"  · {n}")
        return "\n".join(lines)


@dataclass(frozen=True)
class SwapConversion:
    """Comment un swap MT5 devient des USD/oz. Déclarée, jamais devinée.

    Le facteur dépend de `swap_mode`, du contract size et parfois du prix courant. Il
    doit donc être établi une fois, avec sa source, et refusé dès que le mode déclaré
    n'est plus celui du symbole.
    """

    swap_mode: str
    usd_per_oz_per_swap_unit: float
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                "une conversion de swap sans source ne se distingue pas d'un facteur "
                "choisi pour obtenir le plancher voulu"
            )
        if not self.swap_mode.strip():
            raise CampaignError(
                "une conversion de swap doit nommer le mode auquel elle s'applique"
            )

    def to_usd_per_oz(self, swap_units: float) -> float:
        return swap_units * self.usd_per_oz_per_swap_unit


@dataclass(frozen=True)
class Q63Specification:
    """Le plancher Q63 tel que figé, et ce qui lui manque pour devenir `VERIFIED`."""

    account: AccountIdentity
    symbol_spec: MT5SymbolSpecification | None = None
    swap_conversion: SwapConversion | None = None
    version: str = Q63_VERSION
    source: str = "IC Markets EU — Trading Costs"

    # ------------------------------------------------------------------- statut

    @property
    def missing_elements(self) -> tuple[MissingElement, ...]:
        out: list[MissingElement] = []
        if self.account.account_type is AccountType.UNKNOWN:
            out.append(MissingElement(
                "ACCOUNT_TYPE",
                "Raw Spread applique une commission contractuelle — donc un plancher "
                "strictement positif. Standard n'en a pas : son coût passe par un "
                "mark-up de spread, qui n'est pas un plancher.",
                "MT5 → propriétés du compte, ou l'espace client IC Markets",
            ))
        if self.account.base_currency is BaseCurrency.UNKNOWN:
            out.append(MissingElement(
                "ACCOUNT_BASE_CURRENCY",
                "Le tarif diffère selon la devise (7,00 USD / 6,50 EUR / 5,50 GBP par "
                "lot aller-retour) et une commission libellée hors USD exige un taux de "
                "change pour devenir un plancher en USD/oz.",
                "MT5 → propriétés du compte",
            ))
        if self.symbol_spec is None:
            out.append(MissingElement(
                "MT5_SYMBOL_SPECIFICATION",
                "Sans contract size ni tick size contractuels, aucune conversion "
                "lot → oz → R n'est légitime. Convertir « au pip » de tête est "
                "précisément ce que Q63 interdit.",
                "MT5 → clic droit sur XAUUSD → Spécification",
            ))
        return tuple(out)

    @property
    def status(self) -> Q63Status:
        return Q63Status.VERIFIED if not self.missing_elements else Q63Status.PROVISIONAL

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({
            "version": self.version,
            "account_type": self.account.account_type.value,
            "base_currency": self.account.base_currency.value,
            "symbol": self.symbol_spec.fingerprint if self.symbol_spec else None,
            "swap_conversion": (
                None if self.swap_conversion is None
                else [self.swap_conversion.swap_mode,
                      self.swap_conversion.usd_per_oz_per_swap_unit]
            ),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # -------------------------------------------------------------- composants

    def certain_commission_per_oz(self, basis: CommissionBasis) -> Component:
        """Commission contractuelle convertie en USD/oz, ou `UNRESOLVED`.

        Trois choses doivent être vraies simultanément : le type de compte est connu, la
        devise est USD (sinon un taux de change entre dans un plancher contractuel), et
        le contract size est celui du symbole réel.
        """
        if self.account.account_type is AccountType.UNKNOWN:
            return UNRESOLVED
        if self.account.account_type is AccountType.STANDARD:
            # Pas de commission séparée. Le mark-up de spread existe mais n'est pas un
            # plancher : rien ne garantit contractuellement un spread minimal positif.
            return 0.0
        if self.account.base_currency is BaseCurrency.UNKNOWN:
            return UNRESOLVED
        if self.account.base_currency is not BaseCurrency.USD:
            # Un taux de change n'est pas contractuel. Une borne inférieure déclarée et
            # sourcée sur la parité conviendrait ; l'inventer, non.
            return UNRESOLVED
        if self.symbol_spec is None:
            return UNRESOLVED
        per_lot = RAW_COMMISSION_ROUND_TURN[self.account.base_currency]
        return per_lot * basis.sides / self.symbol_spec.contract_size

    def unavoidable_financing(self, exposure: RolloverExposure) -> Component:
        """Financement inévitable, signé. Nul par preuve, ou non résolu.

        Connaître `swap_long` et `swap_short` ne suffit pas : MT5 les exprime selon
        `swap_mode` — en points, en devise du compte par lot, en pourcentage annuel… Les
        additionner à une commission en USD/oz sans conversion déclarée produirait un
        plancher dont l'unité n'existe pas. C'est exactement l'erreur que Q63 interdit
        pour les pips, et elle ne devient pas acceptable parce qu'il s'agit de swaps.
        """
        if exposure is RolloverExposure.CLOSES_BEFORE_ROLLOVER:
            return 0.0
        spec, conv = self.symbol_spec, self.swap_conversion
        if spec is None or not spec.swaps_known or conv is None:
            return UNRESOLVED
        if conv.swap_mode != spec.swap_mode:
            # Une conversion établie pour un autre mode de swap ne s'applique pas ici.
            return UNRESOLVED
        # La direction n'étant pas fixée par la cellule, le swap le plus favorable des
        # deux borne le coût par le bas. Un crédit reste négatif.
        return conv.to_usd_per_oz(min(spec.swap_long, spec.swap_short))

    # -------------------------------------------------------------- résolution

    def resolve(
        self,
        order_type: OrderType,
        exposure: RolloverExposure,
        basis: CommissionBasis = CommissionBasis.ENTRY_ONLY,
    ) -> FloorResolution:
        """Construit le plancher d'une cellule, ou explique pourquoi il n'existe pas."""
        commission = self.certain_commission_per_oz(basis)
        financing = self.unavoidable_financing(exposure)

        components: dict[str, Component] = {
            "certain_commission": commission,
            "mandatory_fees": 0.0,
            "observed_crossing": 0.0,
            "unavoidable_financing": financing,
            "signed_credits": 0.0,
            "slippage_floor": 0.0,
            "adverse_selection_floor": 0.0,
        }
        notes = (
            "spread moyen publié : diagnostic, jamais plancher — rien ne garantit un "
            "franchissement strictement positif",
            "slippage et sélection adverse : une moyenne historique n'est pas une borne "
            "inférieure",
            "swaps à relever le jour de la collecte, pas figés depuis une page web",
        )

        missing = list(self.missing_elements)
        if isinstance(financing, Unresolved):
            missing.append(MissingElement(
                "SWAP_SPECIFICATION",
                "La cellule peut traverser le rollover. Poser un financement nul y "
                "serait faux et non prudent : un swap créditeur rendrait le coût réel "
                "inférieur au plancher. Les swaps relevés ne suffisent pas non plus "
                "seuls — leur conversion vers USD/oz dépend de swap_mode et doit être "
                "déclarée.",
                "MT5 → Spécification du symbole → swap long / swap short / swap mode",
            ))

        if isinstance(commission, Unresolved) or isinstance(financing, Unresolved):
            return FloorResolution(
                status=self.status, order_type=order_type, floor=None,
                missing=tuple(missing), components=components, notes=notes,
            )

        floor = CostFloor(
            order_type=order_type,
            certain_commission=commission,
            mandatory_fees=0.0,
            observed_crossing=0.0,
            unavoidable_financing=financing,
            signed_credits=0.0,
            unit="USD/oz",
            source=f"{self.version} ({self.fingerprint}) — {self.source}",
        )
        return FloorResolution(
            status=self.status, order_type=order_type, floor=floor,
            missing=tuple(missing), components=components, notes=notes,
        )

    def report(self) -> str:
        lines = [
            f"Q63 — {self.version} ({self.fingerprint})",
            f"  symbole  : {SYMBOL} — {BROKER} / {PLATFORM}",
            f"  compte   : {self.account.account_type.value} / "
            f"{self.account.base_currency.value}",
            f"  statut   : {self.status.value}",
        ]
        if self.missing_elements:
            lines.append("  manquants :")
            for m in self.missing_elements:
                lines.append(f"    ✗ {m.name}")
                lines.append(f"        {m.where}")
        return "\n".join(lines)


#: Le plancher tel qu'il peut être figé aujourd'hui, sans rien inventer. `PROVISIONAL`,
#: et suffisant pour ne pas bloquer le démarrage de la collecte : un plancher non résolu
#: interdit une exclusion, il n'interdit pas d'enregistrer.
Q63_PROVISIONAL = Q63Specification(account=AccountIdentity(
    read_from="non relevé — le compte n'a pas encore été inspecté dans MT5",
))
