"""Objets de base : conventions déclarées et cellules de décision.

Références : ADR-105 (le coût est une surface), ADR-110/111 (méthodes de coût
non mélangeables), ADR-112 (conventions déclarées et versionnées).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class CostMethod(str, Enum):
    """ADR-110 : deux méthodes autorisées, jamais mélangées dans une estimation."""

    #: Implementation shortfall mesuré depuis la référence de décision jusqu'au fill.
    #: Contient déjà spread, mouvement pendant la latence, glissement, impact, file.
    OBSERVED_IS = "OBSERVED_IS"
    #: Décomposition explicite. Le glissement est une fonction déclarée de (L, sigma, ...).
    MODELED = "MODELED"


class ReferencePriceConvention(str, Enum):
    MID_EXECUTABLE_AT_DECISION = "MID_EXECUTABLE_AT_DECISION"
    MID_TO_MID = "MID_TO_MID"
    BID_ASK = "BID_ASK"


class RoundTripDefinition(str, Enum):
    ENTRY_AND_EXIT = "ENTRY_AND_EXIT"
    ENTRY_ONLY = "ENTRY_ONLY"


class SpreadCountingConvention(str, Enum):
    #: Un demi-spread à l'entrée et un demi-spread à la sortie.
    HALF_SPREAD_EACH_SIDE = "HALF_SPREAD_EACH_SIDE"
    #: Spread complet compté une fois pour l'aller-retour.
    FULL_SPREAD_ONCE = "FULL_SPREAD_ONCE"
    #: Aucun spread ajouté : il est déjà contenu dans la mesure de performance.
    ALREADY_IN_PERFORMANCE = "ALREADY_IN_PERFORMANCE"


class ConventionError(ValueError):
    """Convention absente, incohérente, ou méthodes de coût mélangées."""


@dataclass(frozen=True)
class Conventions:
    """Conventions d'une expérience. Aucune valeur par défaut sur les champs critiques.

    ADR-112 : la convention de référence du prix, du spread et de l'aller-retour est
    déclarée et versionnée pour toute expérience. Les laisser implicites rendrait deux
    résultats incomparables sans que rien ne le signale.
    """

    cost_measurement_method: CostMethod
    reference_price_convention: ReferencePriceConvention
    round_trip_definition: RoundTripDefinition
    spread_counting_convention: SpreadCountingConvention
    protocol_version: str
    cost_model_version: str

    def __post_init__(self) -> None:
        self._check_no_double_counting()

    def _check_no_double_counting(self) -> None:
        """ADR-111 : l'implementation shortfall contient déjà le spread.

        Y ajouter un spread modélisé compterait deux fois la même chose, gonflerait le
        seuil et rejetterait donc des effets réels.
        """
        if (
            self.cost_measurement_method is CostMethod.OBSERVED_IS
            and self.spread_counting_convention is not SpreadCountingConvention.ALREADY_IN_PERFORMANCE
        ):
            raise ConventionError(
                "Méthode OBSERVED_IS : le spread est déjà contenu dans l'implementation "
                "shortfall. La convention de spread doit être ALREADY_IN_PERFORMANCE "
                f"(reçu : {self.spread_counting_convention.value})."
            )
        if (
            self.cost_measurement_method is CostMethod.MODELED
            and self.spread_counting_convention is SpreadCountingConvention.ALREADY_IN_PERFORMANCE
        ):
            raise ConventionError(
                "Méthode MODELED : le spread doit être compté explicitement, il n'est "
                "contenu dans aucune mesure d'exécution."
            )

    def digest(self) -> str:
        """Empreinte stable, à joindre à tout résultat pour le rendre comparable."""
        payload = json.dumps(
            {k: (v.value if isinstance(v, Enum) else v) for k, v in asdict(self).items()},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Cell:
    """Cellule de décision (ADR-105).

    Un verdict n'est valable que pour la cellule étudiée. Un moteur peut être non exclu
    en séance liquide et non viable en creux de liquidité sans aucune contradiction.
    """

    instrument: str
    detection_market: str
    execution_market: str
    order_type: str
    session: str
    size: float
    regime: str

    @property
    def cell_id(self) -> str:
        return "-".join(
            [
                self.instrument,
                self.order_type,
                self.session,
                f"{self.size:g}",
                self.regime,
            ]
        ).upper()


@dataclass(frozen=True)
class PlausibleEdgeBand:
    """Bande d'avantages plausibles, en unités de volatilité par occurrence.

    ADR-115 : préenregistrée **avant** tout calcul de kappa. La déclarer après avoir vu
    la courbe reviendrait à choisir la conclusion. `source` documente d'où elle vient et
    `declared_at` quand — les deux sont exigés pour que la préinscription soit vérifiable.
    """

    a_min: float
    a_max: float
    source: str
    declared_at: str

    def __post_init__(self) -> None:
        if not (0.0 < self.a_min <= self.a_max):
            raise ValueError(
                f"Bande invalide : 0 < a_min <= a_max requis (reçu {self.a_min}, {self.a_max})."
            )
        if not self.source.strip() or not self.declared_at.strip():
            raise ValueError(
                "La bande doit porter sa source et sa date de déclaration : sans elles, "
                "rien ne distingue une bande préenregistrée d'une bande choisie après coup."
            )


@dataclass(frozen=True)
class SampleSize:
    """Effectifs bruts et effectifs indépendants.

    ADR-093 : le nombre de lignes n'est pas la taille d'échantillon. Les observations
    d'une même séance sont dépendantes ; c'est le nombre de clusters qui gouverne
    l'incertitude.
    """

    observations: int
    independent_clusters: int

    def is_sufficient(self, min_clusters: int) -> bool:
        return self.independent_clusters >= min_clusters


@dataclass
class Provenance:
    """Traçabilité minimale attachée à tout résultat (I2)."""

    conventions_digest: str
    protocol_version: str
    cost_model_version: str
    data_start_ns: int
    data_end_ns: int
    notes: list[str] = field(default_factory=list)
