"""Q65 — ce que la classification autorise à affirmer, et ce qu'elle refuse."""

import pytest

from feasibility.constraints import (
    Q65_V1,
    ConditionalHardProof,
    ConstraintDeclaration,
    ConstraintOrigin,
    ConstraintRegistry,
    UniversalClaimVerdict,
)
from feasibility.mandate import SignalExecutionStatus
from feasibility.passive_campaign import CampaignError, ConstraintClass, OracleKind


# --------------------------------------------------------------- le registre gelé


def test_les_deux_familles_sont_declarees():
    assert "cooldown" in Q65_V1.policy
    assert "quoting_hours" in Q65_V1.hard
    assert Q65_V1.version == "Q65-GOLD-RECOMMENDATION-V1"


def test_horaires_de_cotation_et_seances_choisies_ne_sont_pas_la_meme_chose():
    """La confusion la plus facile, et la plus coûteuse."""
    assert Q65_V1.get("quoting_hours").klass is ConstraintClass.HARD_CONSTRAINT
    assert Q65_V1.get("selected_sessions").klass is ConstraintClass.POLICY_CONSTRAINT


def test_les_seuils_du_mandat_sont_de_la_politique():
    for name in ("planned_risk_per_trade", "max_open_risk", "max_validation_drawdown"):
        assert Q65_V1.get(name).klass is ConstraintClass.POLICY_CONSTRAINT


def test_l_empreinte_change_si_une_classification_change():
    autre = ConstraintRegistry(
        [ConstraintDeclaration("cooldown", "c", ConstraintOrigin.BROKER_OR_MARKET, "r")],
        "TEST",
    )
    assert autre.fingerprint != Q65_V1.fingerprint


def test_une_contrainte_declaree_deux_fois_est_refusee():
    d = ConstraintDeclaration("x", "x", ConstraintOrigin.OUR_ARCHITECTURE, "r")
    with pytest.raises(CampaignError, match="deux fois"):
        ConstraintRegistry([d, d], "TEST")


# ------------------------------------------------------------- la règle normative


def test_l_oracle_physique_ne_recoit_que_le_dur():
    applied = ("quoting_hours", "cooldown", "tick_size", "macro_filters")
    physique = Q65_V1.admissible_for(OracleKind.PHYSICAL_ORACLE, applied)
    assert set(physique) == {"quoting_hours", "tick_size"}


def test_l_oracle_de_politique_recoit_tout():
    applied = ("quoting_hours", "cooldown", "tick_size", "macro_filters")
    politique = Q65_V1.admissible_for(OracleKind.POLICY_ORACLE, applied)
    assert set(politique) == set(applied)


def test_une_contrainte_de_politique_interdit_l_enonce_universel():
    """Le verrou de Q65 : un cooldown ne peut pas éliminer « tout moteur possible »."""
    verdict = Q65_V1.universal_claim(("quoting_hours", "cooldown"))
    assert verdict.verdict is UniversalClaimVerdict.BLOCKED_BY_POLICY
    assert "cooldown" in verdict.offending
    assert not verdict.admissible


def test_l_enonce_universel_passe_sous_contraintes_dures_seules():
    verdict = Q65_V1.universal_claim(("quoting_hours", "tick_size", "minimum_lot"))
    assert verdict.admissible
    assert "courtier" in verdict.scope


def test_une_contrainte_hors_registre_bloque_au_lieu_d_etre_devinee():
    """Le registre est fermé.

    Deviner serait tentant : la classer `POLICY` écarterait la contrainte de la borne
    physique, ce qui va dans le sens sûr. Mais rien ne dit que la prochaine contrainte
    inconnue tombera du même côté, et une valeur par défaut sûre finit toujours par être
    prise pour une classification.
    """
    verdict = Q65_V1.universal_claim(("quoting_hours", "filtre_maison_v3"))
    assert verdict.verdict is UniversalClaimVerdict.BLOCKED_BY_UNCLASSIFIED
    assert verdict.offending == ("filtre_maison_v3",)


def test_une_contrainte_inconnue_leve_a_la_lecture():
    with pytest.raises(CampaignError, match="registre est fermé"):
        Q65_V1.get("inventee")


# ------------------------------------------------------------------- le capital


def test_le_capital_sans_preuve_n_entre_pas_dans_la_borne_physique():
    """Sans preuve, il est écarté — ce qui rend la borne physique plus favorable.

    L'écarter ne peut donc fabriquer aucune exclusion. C'est le sens sûr, et il est
    obtenu sans jamais prétendre que la contrainte n'existe pas.
    """
    physique = Q65_V1.admissible_for(
        OracleKind.PHYSICAL_ORACLE, ("available_capital", "tick_size")
    )
    assert set(physique) == {"tick_size"}


def test_le_capital_sans_preuve_bloque_l_enonce_universel():
    verdict = Q65_V1.universal_claim(("available_capital", "tick_size"))
    assert verdict.verdict is UniversalClaimVerdict.BLOCKED_BY_UNPROVEN_CONDITIONAL


def test_le_capital_prouve_entre_mais_limite_la_portee_au_compte():
    """« Impossible avec ce compte » n'est jamais « impossible sur XAUUSD »."""
    preuve = Q65_V1.capital_constraint(
        smallest_lot_risk_r=1.8, planned_risk_r=1.0, source="MT5 volume_min + stop",
    )
    assert preuve.holds
    physique = Q65_V1.admissible_for(
        OracleKind.PHYSICAL_ORACLE, ("available_capital", "tick_size"), [preuve]
    )
    assert set(physique) == {"available_capital", "tick_size"}

    verdict = Q65_V1.universal_claim(("available_capital", "tick_size"), [preuve])
    assert verdict.admissible
    assert "ce compte" in verdict.scope
    assert "jamais au marché" in verdict.scope


def test_un_capital_suffisant_n_est_pas_une_contrainte():
    preuve = Q65_V1.capital_constraint(0.4, 1.0, source="MT5 volume_min + stop")
    assert not preuve.holds
    assert preuve.execution_status is SignalExecutionStatus.EXECUTABLE
    physique = Q65_V1.admissible_for(
        OracleKind.PHYSICAL_ORACLE, ("available_capital",), [preuve]
    )
    assert physique == ()


def test_le_capital_bloquant_produit_le_statut_d_execution_du_mandat():
    preuve = Q65_V1.capital_constraint(1.8, 1.0, source="MT5 volume_min + stop")
    assert (
        preuve.execution_status
        is SignalExecutionStatus.EXECUTION_NOT_COMPATIBLE_WITH_CAPITAL
    )


def test_une_preuve_sans_source_est_refusee():
    with pytest.raises(CampaignError, match="source"):
        ConditionalHardProof("available_capital", 1.8, 1.0, source="  ")


# ---------------------------------------------------------------- types d'ordre


def test_l_oracle_physique_recoit_tous_les_modes_du_courtier():
    """Notre restriction volontaire ne le concerne pas."""
    modes = Q65_V1.physical_order_types(
        broker_offered=("MARKET", "LIMIT", "STOP"), self_allowed=("MARKET",)
    )
    assert modes == ("MARKET", "LIMIT", "STOP")


def test_un_mode_autorise_par_nous_mais_absent_du_courtier_est_refuse():
    with pytest.raises(CampaignError, match="non proposés"):
        Q65_V1.physical_order_types(("MARKET",), ("MARKET", "ICEBERG"))


def test_les_deux_faces_du_type_d_ordre_sont_declarees_separement():
    assert Q65_V1.get("broker_offered_order_types").klass is (
        ConstraintClass.HARD_CONSTRAINT
    )
    assert Q65_V1.get("self_restricted_order_types").klass is (
        ConstraintClass.POLICY_CONSTRAINT
    )
