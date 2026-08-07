"""Q65 — classification `HARD` contre `POLICY` (`Q65-GOLD-RECOMMENDATION-V1`).

    PHYSICAL_ORACLE = HARD uniquement
    POLICY_ORACLE   = HARD + POLICY

Toute la valeur de cette question tient dans une seule conséquence : une contrainte mal
classée change le **sens** d'une exclusion. Un cooldown que nous avons choisi, s'il entre
dans le `PHYSICAL_ORACLE`, réduit la capture maximale atteignable et peut produire un
énoncé de la forme « aucun moteur XAUUSD possible ne peut être viable » alors que la
phrase vraie était « aucun moteur *tel que nous avons décidé de le construire* ».

Le registre ci-dessous est donc **fermé** : une contrainte inconnue n'est pas devinée.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from .mandate import SignalExecutionStatus
from .passive_campaign import CampaignError, ConstraintClass, OracleKind

Q65_VERSION = "Q65-GOLD-RECOMMENDATION-V1"


class ConstraintOrigin(str, Enum):
    """Ce qui décide de la classe d'une contrainte — sa nature, pas son effet."""

    #: Le marché, le courtier ou la physique l'imposent. Aucune décision de notre part.
    BROKER_OR_MARKET = "BROKER_OR_MARKET"
    #: Nous l'avons choisie. Elle peut être excellente et rester une décision.
    OUR_ARCHITECTURE = "OUR_ARCHITECTURE"
    #: Imposée par le courtier, mais seulement dans certains états. Elle n'entre dans la
    #: borne physique qu'accompagnée de la preuve que l'état est réalisé.
    BROKER_CONDITIONAL = "BROKER_CONDITIONAL"


@dataclass(frozen=True)
class ConstraintDeclaration:
    """Une contrainte nommée, classée, et justifiée.

    `rationale` n'est pas décoratif : c'est ce qui permet de contester une classification
    sans relire le code qui l'utilise.
    """

    name: str
    label: str
    origin: ConstraintOrigin
    rationale: str

    @property
    def klass(self) -> ConstraintClass:
        if self.origin is ConstraintOrigin.OUR_ARCHITECTURE:
            return ConstraintClass.POLICY_CONSTRAINT
        return ConstraintClass.HARD_CONSTRAINT

    @property
    def requires_proof(self) -> bool:
        """Vrai pour les contraintes conditionnelles : `HARD` seulement sur preuve."""
        return self.origin is ConstraintOrigin.BROKER_CONDITIONAL


_BROKER = ConstraintOrigin.BROKER_OR_MARKET
_OURS = ConstraintOrigin.OUR_ARCHITECTURE
_COND = ConstraintOrigin.BROKER_CONDITIONAL

_DECLARATIONS: tuple[ConstraintDeclaration, ...] = (
    # ------------------------------------------------------------------ HARD
    ConstraintDeclaration(
        "quoted_instrument", "instrument réellement coté", _BROKER,
        "Un instrument que le courtier ne cote pas n'est pas tradable, quel que soit le "
        "moteur.",
    ),
    ConstraintDeclaration(
        "quoting_hours", "horaires réels de cotation", _BROKER,
        "Les heures d'ouverture ne sont pas négociables. À distinguer des séances que "
        "nous choisissons de trader, qui sont une politique.",
    ),
    ConstraintDeclaration(
        "available_prices", "prix réellement disponibles", _BROKER,
        "Un oracle peut choisir parfaitement parmi les prix cotés ; il ne peut pas en "
        "inventer un qui n'a jamais existé.",
    ),
    ConstraintDeclaration(
        "observed_bid_ask", "bid / ask réellement observés", _BROKER,
        "Le côté du carnet réellement disponible au moment de la décision.",
    ),
    ConstraintDeclaration(
        "tick_size", "tick size / point size", _BROKER,
        "Granularité contractuelle du symbole : aucun gain inférieur au tick n'est "
        "réalisable.",
    ),
    ConstraintDeclaration(
        "contract_size", "contract size", _BROKER,
        "Spécification MT5 du symbole. Elle conditionne toute conversion vers l'unité "
        "économique.",
    ),
    ConstraintDeclaration(
        "minimum_lot", "minimum lot", _BROKER,
        "Plus petite taille exécutable. Sa conséquence sur le capital est traitée "
        "séparément (`available_capital`).",
    ),
    ConstraintDeclaration(
        "lot_step", "lot step", _BROKER,
        "Discrétisation des tailles : le dimensionnement continu n'existe pas.",
    ),
    ConstraintDeclaration(
        "broker_maximum_lot", "maximum lot courtier", _BROKER,
        "Plafond contractuel de taille — une limite de capacité qui n'est pas la nôtre.",
    ),
    ConstraintDeclaration(
        "margin_and_leverage", "margin / leverage imposés au compte", _BROKER,
        "Fixés par le courtier et la réglementation applicable au compte.",
    ),
    ConstraintDeclaration(
        "suffered_latency", "latence déjà effectivement subie", _BROKER,
        "Mesurée, jamais supposée. Un oracle parfait subit la même latence que nous : "
        "c'est ce qui en fait une borne supérieure du système étudié.",
    ),
    ConstraintDeclaration(
        "market_closure", "market closure / trading halt", _BROKER,
        "Fermeture ou suspension : aucune exécution n'existe pendant l'interruption.",
    ),
    ConstraintDeclaration(
        "broker_contractual_rules", "règles contractuelles du courtier", _BROKER,
        "Ce que le contrat interdit n'est pas contournable par un meilleur moteur.",
    ),
    ConstraintDeclaration(
        "contractually_inevitable_fees", "frais contractuellement inévitables", _BROKER,
        "Commission et frais obligatoires. Entrent dans Q63 par leur borne inférieure.",
    ),
    ConstraintDeclaration(
        "inevitable_financing", "financement inévitable si le trade traverse le rollover",
        _BROKER,
        "Inévitable seulement pour une cellule qui traverse réellement le rollover. "
        "Signé : un swap favorable est un crédit, pas un coût.",
    ),
    ConstraintDeclaration(
        "broker_offered_order_types", "types d'ordre réellement proposés par le courtier",
        _BROKER,
        "Le `PHYSICAL_ORACLE` reçoit **tous** les modes réellement disponibles ; ne lui "
        "en laisser qu'un rendrait l'exécution artificiellement coûteuse.",
    ),
    # ----------------------------------------------------------- HARD conditionnelle
    ConstraintDeclaration(
        "available_capital", "capital réellement disponible", _COND,
        "`HARD` uniquement lorsque le lot minimum et la distance au stop rendent "
        "l'exécution réellement impossible. Sans cette preuve, le capital est une "
        "propriété du compte et non du marché : l'y admettre transformerait « pas "
        "finançable avec ce compte » en « impossible sur XAUUSD ».",
    ),
    # ---------------------------------------------------------------- POLICY
    ConstraintDeclaration(
        "planned_risk_per_trade", "risque planifié = 0,50 % equity par trade", _OURS,
        "Q1-v1. Excellente discipline, décision entièrement nôtre.",
    ),
    ConstraintDeclaration(
        "max_open_risk", "risque ouvert maximal = 2R", _OURS,
        "Q1-v1, déjà déclaré `POLICY_CONSTRAINT` dans le mandat.",
    ),
    ConstraintDeclaration(
        "max_validation_drawdown", "drawdown maximal de validation = 12R", _OURS,
        "Critère d'arrêt que nous nous imposons pendant la validation.",
    ),
    ConstraintDeclaration(
        "max_concurrent_trades", "nombre maximal de trades simultanés", _OURS,
        "Choisi par le système. Le courtier, lui, en autorise davantage.",
    ),
    ConstraintDeclaration(
        "cooldown", "cooldown entre trades", _OURS,
        "Le cas d'école : un cooldown arbitraire dans la borne physique fabrique une "
        "exclusion imputable à notre architecture.",
    ),
    ConstraintDeclaration(
        "selected_sessions", "séances que nous choisissons de trader", _OURS,
        "À ne pas confondre avec les horaires de cotation, qui sont `HARD`.",
    ),
    ConstraintDeclaration(
        "self_restricted_order_types", "interdiction volontaire de certains types d'ordre",
        _OURS,
        "« Nous n'utiliserons que des ordres au marché » est une décision, pas une "
        "limite du courtier.",
    ),
    ConstraintDeclaration(
        "macro_filters", "filtres macro", _OURS,
        "Fenêtres d'annonces écartées par choix.",
    ),
    ConstraintDeclaration(
        "confidence_threshold", "seuil de confiance", _OURS,
        "Réglage de notre politique de décision.",
    ),
    ConstraintDeclaration(
        "quality_threshold", "seuil de qualité", _OURS,
        "Réglage de notre politique de décision.",
    ),
    ConstraintDeclaration(
        "no_trade_policy", "politique NO_TRADE", _OURS,
        "L'abstention est une sortie de première classe du système — et une décision.",
    ),
    ConstraintDeclaration(
        "architecture_exposure_limits", "limites d'exposition décidées par l'architecture",
        _OURS,
        "Toute limite d'exposition que le courtier n'impose pas.",
    ),
)


class UniversalClaimVerdict(str, Enum):
    """Une exclusion peut-elle prétendre porter sur *tout moteur possible* ?"""

    ADMISSIBLE = "ADMISSIBLE"
    #: Une contrainte que nous avons choisie est entrée dans la borne.
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    #: Une contrainte conditionnelle est entrée sans sa preuve.
    BLOCKED_BY_UNPROVEN_CONDITIONAL = "BLOCKED_BY_UNPROVEN_CONDITIONAL"
    #: Une contrainte hors registre : nous ne savons pas de quel côté elle tombe.
    BLOCKED_BY_UNCLASSIFIED = "BLOCKED_BY_UNCLASSIFIED"


@dataclass(frozen=True)
class UniversalClaimAssessment:
    verdict: UniversalClaimVerdict
    offending: tuple[str, ...]
    scope: str

    @property
    def admissible(self) -> bool:
        return self.verdict is UniversalClaimVerdict.ADMISSIBLE

    def __str__(self) -> str:
        if self.admissible:
            return f"ADMISSIBLE — portée : {self.scope}"
        return (
            f"{self.verdict.value} — portée réelle : {self.scope}\n"
            f"  contraintes en cause : {', '.join(self.offending)}"
        )


@dataclass(frozen=True)
class ConditionalHardProof:
    """Preuve qu'une contrainte conditionnelle est réellement `HARD` ici.

    Le seul cas déclaré en v1 est le capital. La preuve n'est pas une affirmation :
    c'est le calcul montrant que le plus petit lot exécutable dépasse le risque planifié.
    """

    constraint: str
    smallest_lot_risk_r: float
    planned_risk_r: float
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise CampaignError(
                "Une preuve de contrainte conditionnelle sans source déclarée ne se "
                "distingue pas d'une affirmation choisie pour obtenir le résultat voulu."
            )
        if self.smallest_lot_risk_r <= 0 or self.planned_risk_r <= 0:
            raise CampaignError("les risques comparés doivent être strictement positifs")

    @property
    def holds(self) -> bool:
        """La contrainte est réellement bloquante : le plus petit lot dépasse le plan."""
        return self.smallest_lot_risk_r > self.planned_risk_r

    @property
    def execution_status(self) -> SignalExecutionStatus:
        return (
            SignalExecutionStatus.EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL if self.holds
            else SignalExecutionStatus.EXECUTABLE
        )


class ConstraintRegistry:
    """Le registre Q65 gelé. Fermé : ce qui n'y figure pas n'est pas classé."""

    def __init__(
        self, declarations: Sequence[ConstraintDeclaration], version: str
    ) -> None:
        by_name: dict[str, ConstraintDeclaration] = {}
        for d in declarations:
            if d.name in by_name:
                raise CampaignError(f"contrainte déclarée deux fois : {d.name}")
            by_name[d.name] = d
        self._by_name = by_name
        self.version = version

    # ------------------------------------------------------------------ lecture

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)

    def get(self, name: str) -> ConstraintDeclaration:
        try:
            return self._by_name[name]
        except KeyError:
            raise CampaignError(
                f"contrainte « {name} » absente du registre {self.version}. Le registre "
                "est fermé : une contrainte non classée n'est ni supposée dure ni "
                "supposée politique, elle doit être déclarée."
            ) from None

    def names(self, klass: ConstraintClass | None = None) -> tuple[str, ...]:
        return tuple(sorted(
            n for n, d in self._by_name.items() if klass is None or d.klass is klass
        ))

    @property
    def hard(self) -> tuple[str, ...]:
        return self.names(ConstraintClass.HARD_CONSTRAINT)

    @property
    def policy(self) -> tuple[str, ...]:
        return self.names(ConstraintClass.POLICY_CONSTRAINT)

    @property
    def conditional(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, d in self._by_name.items() if d.requires_proof))

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {n: d.origin.value for n, d in sorted(self._by_name.items())},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # ------------------------------------------------------------- règle normative

    def admissible_for(
        self,
        kind: OracleKind,
        names: Iterable[str],
        proofs: Sequence[ConditionalHardProof] = (),
    ) -> tuple[str, ...]:
        """Contraintes retenues pour l'oracle demandé.

            PHYSICAL_ORACLE = HARD uniquement
            POLICY_ORACLE   = HARD + POLICY

        Une conditionnelle n'entre dans la borne physique qu'accompagnée d'une preuve
        qui tient. Sans preuve, elle est simplement écartée — l'écarter rend la borne
        physique **plus** favorable, donc ne fabrique aucune exclusion.
        """
        proven = {p.constraint for p in proofs if p.holds}
        kept: list[str] = []
        for name in names:
            d = self.get(name)
            if kind is OracleKind.POLICY_ORACLE:
                kept.append(name)
                continue
            if d.klass is not ConstraintClass.HARD_CONSTRAINT:
                continue
            if d.requires_proof and name not in proven:
                continue
            kept.append(name)
        return tuple(kept)

    def universal_claim(
        self,
        applied: Iterable[str],
        proofs: Sequence[ConditionalHardProof] = (),
    ) -> UniversalClaimAssessment:
        """Une exclusion construite sous ces contraintes porte-t-elle sur *tout moteur* ?

        C'est le verrou de Q65. Aucune `POLICY_CONSTRAINT` ne peut produire l'énoncé
        « aucun moteur XAUUSD possible ne peut être viable » ; la portée réelle d'une
        borne contenant nos propres décisions est notre système, pas le marché.
        """
        applied = tuple(applied)
        unknown = tuple(n for n in applied if n not in self._by_name)
        if unknown:
            return UniversalClaimAssessment(
                UniversalClaimVerdict.BLOCKED_BY_UNCLASSIFIED, unknown,
                "indéterminée — une contrainte hors registre peut être de l'une ou "
                "l'autre origine",
            )
        policy = tuple(
            n for n in applied
            if self._by_name[n].klass is ConstraintClass.POLICY_CONSTRAINT
        )
        if policy:
            return UniversalClaimAssessment(
                UniversalClaimVerdict.BLOCKED_BY_POLICY, policy,
                "notre système tel que nous avons décidé de le construire",
            )
        proven = {p.constraint for p in proofs if p.holds}
        unproven = tuple(
            n for n in applied if self._by_name[n].requires_proof and n not in proven
        )
        if unproven:
            return UniversalClaimAssessment(
                UniversalClaimVerdict.BLOCKED_BY_UNPROVEN_CONDITIONAL, unproven,
                "indéterminée — contrainte conditionnelle admise sans preuve",
            )
        scope = "tout moteur XAUUSD possible sous les contraintes réelles du courtier"
        if any(self._by_name[n].requires_proof for n in applied):
            scope = (
                "tout moteur XAUUSD possible **sur ce compte** — une contrainte de "
                "capital prouvée limite la portée au compte, jamais au marché"
            )
        return UniversalClaimAssessment(UniversalClaimVerdict.ADMISSIBLE, (), scope)

    # ------------------------------------------------------------- cas particuliers

    def physical_order_types(
        self, broker_offered: Sequence[str], self_allowed: Sequence[str]
    ) -> tuple[str, ...]:
        """Le `PHYSICAL_ORACLE` reçoit tous les modes réellement disponibles.

        Notre restriction volontaire ne le concerne pas : la lui appliquer rendrait
        l'exécution artificiellement coûteuse et pourrait exclure une famille de
        stratégies au motif que *nous* refusons l'ordre qui la rendait viable.
        """
        unknown = tuple(o for o in self_allowed if o not in broker_offered)
        if unknown:
            raise CampaignError(
                f"types d'ordre autorisés par nous mais non proposés par le courtier : "
                f"{', '.join(unknown)}"
            )
        return tuple(broker_offered)

    def capital_constraint(
        self, smallest_lot_risk_r: float, planned_risk_r: float, source: str
    ) -> ConditionalHardProof:
        """Le capital devient `HARD` seulement s'il rend l'exécution réellement impossible.

        Quand il l'est, la conséquence est `EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL` — et
        rien d'autre. Le signal reste ce qu'il était : la qualité se mesure en R,
        l'exécution décide séparément si ce compte peut la financer.
        """
        return ConditionalHardProof(
            constraint="available_capital",
            smallest_lot_risk_r=smallest_lot_risk_r,
            planned_risk_r=planned_risk_r,
            source=source,
        )

    def report(self) -> str:
        lines = [
            f"Q65 — {self.version} ({self.fingerprint})",
            f"  HARD          : {len(self.hard)} contraintes",
            f"  POLICY        : {len(self.policy)} contraintes",
            f"  conditionnelles : {', '.join(self.conditional) or '—'}",
            "",
            "  PHYSICAL_ORACLE = HARD uniquement",
            "  POLICY_ORACLE   = HARD + POLICY",
        ]
        return "\n".join(lines)


Q65_V1 = ConstraintRegistry(_DECLARATIONS, Q65_VERSION)
