"""Spécifications de compte et conversion d'unités.

Le point le plus dangereux de tout l'adaptateur : sur XAU/USD, confondre « par once » et
« par lot » est un facteur cent. L'erreur est silencieuse — les deux nombres restent
plausibles — et elle traverse ensuite tout le calcul de coût.

Aucune conversion n'est donc implicite : l'unité est portée par la valeur, et un mélange
lève une erreur au lieu de produire un résultat crédible et faux.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PriceUnit(str, Enum):
    #: Unité de cotation de l'instrument — pour XAU/USD, dollars par once troy.
    QUOTE_PER_UNIT = "QUOTE_PER_UNIT"
    #: Monnaie du compte, pour une taille de position donnée.
    ACCOUNT_MONEY = "ACCOUNT_MONEY"


class UnitError(ValueError):
    """Unité absente, inconnue, ou incompatible avec l'opération demandée."""


@dataclass(frozen=True)
class Quantity:
    """Valeur portant son unité. Empêche d'additionner des onces et des dollars."""

    value: float
    unit: PriceUnit

    def __post_init__(self) -> None:
        if not isinstance(self.unit, PriceUnit):
            raise UnitError(f"Unité non déclarée ou inconnue : {self.unit!r}")

    def __add__(self, other: "Quantity") -> "Quantity":
        if self.unit is not other.unit:
            raise UnitError(
                f"Addition d'unités différentes : {self.unit.value} + {other.unit.value}"
            )
        return Quantity(self.value + other.value, self.unit)


class ExecutionMode(str, Enum):
    MARKET = "MARKET"
    INSTANT = "INSTANT"
    EXCHANGE = "EXCHANGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ContractSpecification:
    """Spécifications réelles du compte, versionnées.

    Aucune valeur par défaut sur les champs économiques : une convention « générique »
    supposée est précisément ce qui produit une erreur d'un facteur cent. `source` et
    `retrieved_at` documentent d'où viennent ces chiffres — ils doivent provenir du
    courtier, pas d'une mémoire.
    """

    broker: str
    account_type: str
    symbol: str
    underlying: str
    quote_currency: str
    contract_size: float
    tick_size: float
    tick_value: float
    minimum_volume: float
    volume_step: float
    commission_per_side_per_lot: float
    swap_long_per_lot_per_day: float
    swap_short_per_lot_per_day: float
    triple_swap_weekday: int | None
    triple_swap_verified: bool
    execution_mode: ExecutionMode
    source: str
    retrieved_at: str
    version: str

    def __post_init__(self) -> None:
        for name in ("contract_size", "tick_size", "minimum_volume", "volume_step"):
            if getattr(self, name) <= 0:
                raise UnitError(f"{name} doit être strictement positif.")
        if not self.source.strip() or not self.retrieved_at.strip():
            raise UnitError(
                "Les spécifications doivent porter leur source et leur date : sans elles, "
                "rien ne distingue une valeur relevée d'une valeur supposée."
            )

    @property
    def instrument_id(self) -> str:
        return f"{self.broker}:{self.symbol}:{self.account_type}"

    def exposure_units(self, volume_lots: float) -> float:
        """Exposition en unités du sous-jacent — onces pour l'or."""
        return volume_lots * self.contract_size

    def price_move_to_money(self, move_quote: float, volume_lots: float) -> Quantity:
        """Convertit un déplacement de prix en monnaie du compte.

        C'est le seul chemin autorisé entre les deux unités.
        """
        return Quantity(move_quote * self.contract_size * volume_lots, PriceUnit.ACCOUNT_MONEY)

    def commission_round_trip(self, volume_lots: float) -> Quantity:
        return Quantity(
            2.0 * self.commission_per_side_per_lot * volume_lots, PriceUnit.ACCOUNT_MONEY
        )

    def financing(self, volume_lots: float, direction: int, rollover_crossings: int) -> Quantity:
        """Portage overnight.

        `rollover_crossings` est fourni par l'appelant : il dépend du fuseau serveur du
        courtier et du calendrier, que ce module n'a pas à redécouvrir. Si la politique de
        portage triple n'a pas été vérifiée auprès du courtier, le calcul refuse de
        s'exécuter plutôt que de supposer un jour.
        """
        if rollover_crossings > 0 and not self.triple_swap_verified:
            raise UnitError(
                "Politique de portage triple non vérifiée auprès du courtier. Supposer un "
                "jour de portage multiplié fausserait tous les horizons multi-journaliers."
            )
        per_day = self.swap_long_per_lot_per_day if direction > 0 else self.swap_short_per_lot_per_day
        return Quantity(per_day * volume_lots * rollover_crossings, PriceUnit.ACCOUNT_MONEY)


class CostScenario(str, Enum):
    """Trois lectures des coûts non encore mesurés.

    Les coûts inconnus ne sont jamais fixés à zéro : ils sont traités par scénarios, et
    l'écart entre les cartes optimiste et prudente mesure directement ce que l'absence de
    campagne d'exécution coûte en certitude.
    """

    OPTIMISTIC = "OPTIMISTIC"
    CENTRAL = "CENTRAL"
    PRUDENT = "PRUDENT"


@dataclass(frozen=True)
class CostPolicy:
    """Politique de coûts, incluant le traitement des termes non mesurés."""

    scenario: CostScenario
    volume_lots: float
    #: Bornes supérieures raisonnables sur les termes que seule une campagne réelle
    #: mesure : glissement agressif, impact, sélection adverse. Exprimées en unité de
    #: cotation, par aller-retour.
    unmeasured_slippage_bound: float
    unmeasured_impact_bound: float
    unmeasured_adverse_selection_bound: float
    rationale: str

    def unmeasured_allowance(self) -> float:
        """Part des coûts inconnus retenue selon le scénario."""
        total = (
            self.unmeasured_slippage_bound
            + self.unmeasured_impact_bound
            + self.unmeasured_adverse_selection_bound
        )
        if self.scenario is CostScenario.OPTIMISTIC:
            return 0.0  # seuls les coûts certains
        if self.scenario is CostScenario.CENTRAL:
            return 0.5 * total
        return total

    def __post_init__(self) -> None:
        if self.volume_lots <= 0:
            raise UnitError("La taille de position doit être strictement positive.")
        for name in (
            "unmeasured_slippage_bound",
            "unmeasured_impact_bound",
            "unmeasured_adverse_selection_bound",
        ):
            if getattr(self, name) < 0:
                raise UnitError(f"{name} ne peut pas être négatif.")
        if not self.rationale.strip():
            raise UnitError(
                "La politique doit expliciter d'où viennent ses bornes : une borne sans "
                "justification est un chiffre inventé."
            )
