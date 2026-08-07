"""Q1-v1 — mandat économique normatif du Gold Analyzer.

Ce module ne calcule presque rien. Il **déclare**, sous une forme versionnée et
vérifiable, ce que le système doit atteindre pour justifier son existence — et c'est de
lui que Q64 dérive ses seuils au lieu de les inventer.

Le choix structurant est l'unité :

    PRIMARY_PERFORMANCE_UNIT = R        1R = risque planifié jusqu'à l'invalidation

L'analyseur n'est ainsi jamais calibré sur un compte à 75 €, 500 € ou 10 000 €. La qualité
du signal s'exprime en R ; l'exécution décide ensuite si le capital réel permet de prendre
le trade. Un lot minimum incompatible produit `EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL`,
jamais `BAD_SIGNAL`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

MANDATE_VERSION = "Q1-GOLD-RECOMMENDATION-V1"


class MandateError(ValueError):
    """Mandat incohérent, ou grandeur exprimée dans la mauvaise unité."""


class SystemRole(str, Enum):
    """Ce que le système fait de sa décision — et donc ce que Q42 doit qualifier."""

    #: Produit BUY / SELL / NO TRADE, construit entrée, invalidation, objectifs, estime
    #: EV et qualité, peut alerter. **N'envoie aucun ordre.**
    RECOMMENDATION = "RECOMMENDATION"
    #: Émet des ordres réels. Rôle différent, exigeant une nouvelle version de Q1 et la
    #: qualification Q42 correspondante.
    AUTO_EXECUTION = "AUTO_EXECUTION"

    @property
    def requires_broker_qualification(self) -> bool:
        return self is SystemRole.AUTO_EXECUTION


class SignalExecutionStatus(str, Enum):
    """Sépare la qualité d'un signal de la capacité du compte à le prendre."""

    EXECUTABLE = "EXECUTABLE"
    #: Le signal est valide ; c'est le capital qui ne suit pas. **Pas** un mauvais signal.
    EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL = "EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL"


@dataclass(frozen=True)
class EconomicMandate:
    """Le mandat déclaré. Toute modification crée une nouvelle version.

    `J_min`, `δ_MEU`, le risque par trade, la limite de perte, l'horizon d'évaluation, le
    rôle et l'unité de performance sont **normatifs** : les changer produit une version
    suivante, non applicable rétroactivement au holdout précédent.
    """

    version: str
    role: SystemRole
    performance_unit: str
    #: Fraction de l'equity de déploiement que vaut 1R.
    risk_unit_fraction_of_equity: float
    #: Cible économique primaire, en R par séance.
    j_min_per_session_r: float
    #: Plancher de matérialité par trade accepté, en R.
    delta_meu_r: float
    #: Horizon d'évaluation économique, en séances.
    evaluation_horizon_sessions: int
    #: Risque planifié maximal par trade, en R.
    max_planned_risk_per_trade_r: float
    #: Risque simultané maximal, en R. **Contrainte de politique** — jamais physique.
    max_planned_open_risk_r: float
    #: Perte maximale acceptable sur l'horizon de validation, en R.
    max_validation_drawdown_r: float
    declared_by: str
    declared_at_ns: int

    def __post_init__(self) -> None:
        if self.performance_unit != "R":
            raise MandateError(
                "L'unité primaire est R. Exprimer la cible en euros lierait la qualité "
                "du signal à la taille du compte."
            )
        for name in ("j_min_per_session_r", "delta_meu_r", "max_planned_risk_per_trade_r",
                     "max_validation_drawdown_r"):
            if getattr(self, name) <= 0:
                raise MandateError(f"{name} doit être strictement positif")
        if self.max_planned_open_risk_r < self.max_planned_risk_per_trade_r:
            raise MandateError(
                "le risque simultané ne peut pas être inférieur au risque d'un seul trade"
            )
        if not self.declared_by.strip():
            raise MandateError("un mandat sans auteur ne peut être opposé à personne")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {k: (v.value if isinstance(v, Enum) else v) for k, v in self.__dict__.items()},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def j_min_over_horizon_r(self) -> float:
        """`+6R` sur 60 séances avec les valeurs v1."""
        return self.j_min_per_session_r * self.evaluation_horizon_sessions

    @property
    def drawdown_to_target_ratio(self) -> float:
        """Rapport entre budget de perte et cible sur le même horizon.

        Publié parce qu'il est facile de le subir sans l'avoir choisi : en v1, le budget
        de perte vaut le double de la cible atteignable sur l'horizon.
        """
        return self.max_validation_drawdown_r / self.j_min_over_horizon_r

    def risk_unit_in_currency(self, equity: float) -> float:
        """Ce que vaut 1R pour un capital donné. **N'entre dans aucun verdict.**"""
        return equity * self.risk_unit_fraction_of_equity

    def execution_status(
        self, planned_risk_r: float, smallest_lot_risk_r: float
    ) -> SignalExecutionStatus:
        """Un lot minimum trop gros n'invalide pas le signal, il invalide l'exécution."""
        if smallest_lot_risk_r > planned_risk_r:
            return SignalExecutionStatus.EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL
        return SignalExecutionStatus.EXECUTABLE

    def frequency_if_ev_equals_meu(self) -> float:
        """Trades par séance requis **si** chaque trade valait exactement `δ_MEU`.

        Lecture de planification, sans autorité d'exclusion : en v1, `0,10 / 0,20 = 0,5`,
        soit un trade qualifiant toutes les deux séances. C'est ce qui rend la cible
        atteignable par un système très sélectif.
        """
        return self.j_min_per_session_r / self.delta_meu_r

    def necessary_frequency_per_session(self, ev_upper_r: float) -> float:
        """Fréquence nécessaire **quelle que soit** la qualité, depuis une borne
        supérieure d'espérance. Seule construction autorisant une exclusion économique."""
        if ev_upper_r <= 0:
            raise MandateError("une borne supérieure d'espérance doit être positive")
        return self.j_min_per_session_r / ev_upper_r


#: Le mandat normatif. Toute modification passe en V2 et n'est pas rétroactive.
Q1_V1 = EconomicMandate(
    version=MANDATE_VERSION,
    role=SystemRole.RECOMMENDATION,
    performance_unit="R",
    risk_unit_fraction_of_equity=0.005,      # 1R = 0,50 % de l'equity
    j_min_per_session_r=0.10,
    delta_meu_r=0.20,
    evaluation_horizon_sessions=60,
    max_planned_risk_per_trade_r=1.0,
    max_planned_open_risk_r=2.0,             # POLICY_CONSTRAINT — jamais physique
    max_validation_drawdown_r=12.0,
    declared_by="mandat de projet",
    declared_at_ns=0,
)


#: Ventilations exigées du rapport — une valeur agrégée seule n'est jamais suffisante.
REQUIRED_BREAKDOWNS = (
    "jour", "semaine", "mois", "session", "régime", "volatilité", "macro/non-macro",
)

#: Grandeurs de queue à publier. `1R` est le risque **planifié**, jamais la perte
#: maximale certaine : gaps et glissement produisent des pertes supérieures, et l'écart
#: doit être mesuré plutôt que supposé nul.
REQUIRED_TAIL_METRICS = (
    "distribution des pertes", "Expected Shortfall", "pire trade", "pire journée",
    "perte maximale", "série de pertes", "pertes de gap et de glissement",
)

#: Colonnes de la courbe Qualité(Couverture).
QUALITY_COVERAGE_COLUMNS = (
    "couverture", "nombre de trades", "EV nette par trade", "EV nette par séance",
    "taux de réussite", "gain moyen", "perte moyenne", "R:R réalisé",
    "calibration (Brier)", "perte maximale", "Expected Shortfall",
)
