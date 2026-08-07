"""Q63 — ce que le plancher accepte de valoir, et ce qu'il refuse de valoir."""

import pytest

from feasibility.cost_floor_xauusd import (
    UNRESOLVED,
    AccountIdentity,
    AccountType,
    BaseCurrency,
    CommissionBasis,
    FloorUse,
    MT5SymbolSpecification,
    Q63_PROVISIONAL,
    Q63Specification,
    Q63Status,
    RolloverExposure,
    SwapConversion,
    Unresolved,
)
from feasibility.passive_campaign import CampaignError, OrderType

SPEC = MT5SymbolSpecification(
    symbol="XAUUSD", contract_size=100.0, tick_size=0.01, point=0.01,
    volume_min=0.01, volume_step=0.01, volume_max=50.0,
    currency_profit="USD", currency_margin="USD", digits=2,
    read_from="MT5 symbol_info(XAUUSD)",
)
RAW_USD = AccountIdentity(AccountType.RAW_SPREAD, BaseCurrency.USD, read_from="MT5")


def verifiee(**kw) -> Q63Specification:
    return Q63Specification(account=RAW_USD, symbol_spec=SPEC, **kw)


# ------------------------------------------------------------------- le statut


def test_le_plancher_fige_aujourd_hui_est_provisional():
    assert Q63_PROVISIONAL.status is Q63Status.PROVISIONAL
    manquants = {m.name for m in Q63_PROVISIONAL.missing_elements}
    assert manquants == {
        "ACCOUNT_TYPE", "ACCOUNT_BASE_CURRENCY", "MT5_SYMBOL_SPECIFICATION",
    }


def test_les_trois_elements_suffisent_a_passer_verified():
    assert verifiee().status is Q63Status.VERIFIED


def test_provisional_n_empeche_pas_d_enregistrer_mais_empeche_de_conclure():
    """La collecte n'attend rien ; seul le verdict attend.

    C'est la raison pour laquelle Q63 ne bloque pas le démarrage : un plancher non résolu
    interdit une exclusion, il n'interdit pas d'observer.
    """
    res = Q63_PROVISIONAL.resolve(
        OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER
    )
    assert not res.resolved
    with pytest.raises(CampaignError, match="non résolu"):
        res.value_for(FloorUse.ORACLE_EXCLUSION)


# --------------------------------------------------------------- la commission


def test_raw_usd_convertit_la_commission_par_le_contract_size():
    """7,00 USD aller-retour par lot de 100 oz, un seul côté certain → 0,035 USD/oz."""
    res = verifiee().resolve(
        OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER,
        CommissionBasis.ENTRY_ONLY,
    )
    assert res.resolved
    assert res.value_for(FloorUse.ORACLE_EXCLUSION) == pytest.approx(0.035)


def test_l_aller_retour_double_le_plancher():
    res = verifiee().resolve(
        OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER,
        CommissionBasis.ROUND_TURN,
    )
    assert res.value_for(FloorUse.ORACLE_EXCLUSION) == pytest.approx(0.07)


def test_un_compte_hors_usd_ne_convertit_pas_sans_taux_declare():
    """Un taux de change n'est pas contractuel — il ne rentre pas dans un plancher."""
    spec = Q63Specification(
        account=AccountIdentity(AccountType.RAW_SPREAD, BaseCurrency.EUR, read_from="MT5"),
        symbol_spec=SPEC,
    )
    assert spec.status is Q63Status.VERIFIED
    assert isinstance(spec.certain_commission_per_oz(CommissionBasis.ENTRY_ONLY),
                      Unresolved)


def test_le_compte_standard_n_a_pas_de_commission_separee():
    spec = Q63Specification(
        account=AccountIdentity(AccountType.STANDARD, BaseCurrency.USD, read_from="MT5"),
        symbol_spec=SPEC,
    )
    res = spec.resolve(OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER)
    # Zéro veut dire « pas de commission séparée », jamais « trader ne coûte rien » : le
    # mark-up existe, il n'est simplement pas un plancher.
    assert res.value_for(FloorUse.ORACLE_EXCLUSION) == 0.0


def test_sans_contract_size_aucune_conversion_n_est_legitime():
    spec = Q63Specification(account=RAW_USD, symbol_spec=None)
    assert isinstance(spec.certain_commission_per_oz(CommissionBasis.ENTRY_ONLY),
                      Unresolved)


# -------------------------------------------------------------- le financement


def test_cloturee_avant_le_rollover_le_financement_est_nul_par_preuve():
    assert verifiee().unavoidable_financing(
        RolloverExposure.CLOSES_BEFORE_ROLLOVER
    ) == 0.0


def test_traversant_le_rollover_sans_swap_le_plancher_est_bloque():
    res = verifiee().resolve(OrderType.AGGRESSIVE, RolloverExposure.MAY_CROSS_ROLLOVER)
    assert not res.resolved
    assert "SWAP_SPECIFICATION" in {m.name for m in res.missing}


def test_zero_serait_faux_et_non_prudent_pour_une_cellule_traversant_le_rollover():
    """La démonstration arithmétique, pas l'argument de prudence.

    Avec un swap créditeur, le coût réel passe **sous** la commission. Poser
    `financement = 0` produirait un plancher supérieur au coût réel : `C_réel ≥ C_floor`
    tombe, et l'exclusion qui s'appuierait dessus serait fabriquée.
    """
    credit = MT5SymbolSpecification(
        **{**{k: v for k, v in SPEC.__dict__.items()},
           "swap_long": -3.0, "swap_short": -5.0, "swap_mode": "POINTS"},
    )
    conv = SwapConversion("POINTS", usd_per_oz_per_swap_unit=0.001, source="MT5")
    spec = Q63Specification(account=RAW_USD, symbol_spec=credit, swap_conversion=conv)

    reel = spec.resolve(
        OrderType.AGGRESSIVE, RolloverExposure.MAY_CROSS_ROLLOVER,
        CommissionBasis.ENTRY_ONLY,
    ).value_for(FloorUse.ORACLE_EXCLUSION)
    naif = spec.certain_commission_per_oz(CommissionBasis.ENTRY_ONLY)

    assert reel < naif           # le crédit abaisse réellement le coût inévitable
    assert reel == pytest.approx(0.035 - 0.005)


def test_les_swaps_connus_ne_suffisent_pas_sans_conversion_declaree():
    """MT5 exprime les swaps selon `swap_mode` — points, devise, pourcentage.

    Les additionner à une commission en USD/oz sans conversion produirait un plancher
    dont l'unité n'existe pas.
    """
    avec_swaps = MT5SymbolSpecification(
        **{**SPEC.__dict__, "swap_long": -3.0, "swap_short": -5.0, "swap_mode": "POINTS"},
    )
    spec = Q63Specification(account=RAW_USD, symbol_spec=avec_swaps)
    assert isinstance(
        spec.unavoidable_financing(RolloverExposure.MAY_CROSS_ROLLOVER), Unresolved
    )


def test_une_conversion_etablie_pour_un_autre_mode_ne_s_applique_pas():
    avec_swaps = MT5SymbolSpecification(
        **{**SPEC.__dict__, "swap_long": -3.0, "swap_short": -5.0, "swap_mode": "POINTS"},
    )
    conv = SwapConversion("INTEREST", usd_per_oz_per_swap_unit=0.001, source="MT5")
    spec = Q63Specification(account=RAW_USD, symbol_spec=avec_swaps, swap_conversion=conv)
    assert isinstance(
        spec.unavoidable_financing(RolloverExposure.MAY_CROSS_ROLLOVER), Unresolved
    )


def test_une_conversion_sans_source_est_refusee():
    with pytest.raises(CampaignError, match="source"):
        SwapConversion("POINTS", 0.001, source="")


# --------------------------------------------------- ce que le plancher refuse


def test_le_plancher_refuse_de_servir_de_cout_attendu():
    """Il sous-estime délibérément : l'employer comme coût attendu inventerait un avantage."""
    res = verifiee().resolve(
        OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER
    )
    with pytest.raises(CampaignError, match="Q40"):
        res.value_for(FloorUse.EXPECTED_COST_MODEL)


def test_unresolved_n_a_pas_de_valeur_de_verite():
    """Le tester comme un booléen le ferait passer pour zéro sans un mot."""
    with pytest.raises(CampaignError, match="valeur de vérité"):
        bool(UNRESOLVED)


def test_unresolved_est_un_singleton():
    assert Unresolved() is UNRESOLVED


def test_le_franchissement_n_entre_jamais_dans_le_plancher_d_un_ordre_passif():
    res = verifiee().resolve(
        OrderType.PASSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER
    )
    assert res.floor is not None
    assert res.floor.observed_crossing == 0.0


def test_le_spread_moyen_publie_n_entre_pas_dans_le_plancher():
    res = verifiee().resolve(
        OrderType.AGGRESSIVE, RolloverExposure.CLOSES_BEFORE_ROLLOVER
    )
    assert res.components["observed_crossing"] == 0.0
    assert res.components["slippage_floor"] == 0.0
    assert res.components["adverse_selection_floor"] == 0.0


def test_une_specification_sans_provenance_est_refusee():
    with pytest.raises(CampaignError, match="provenance"):
        MT5SymbolSpecification(
            symbol="XAUUSD", contract_size=100.0, tick_size=0.01, point=0.01,
            volume_min=0.01, volume_step=0.01, volume_max=50.0,
            currency_profit="USD", currency_margin="USD", digits=2, read_from="",
        )


def test_l_empreinte_distingue_deux_comptes_differents():
    autre = Q63Specification(
        account=AccountIdentity(AccountType.STANDARD, BaseCurrency.USD, read_from="MT5"),
        symbol_spec=SPEC,
    )
    assert autre.fingerprint != verifiee().fingerprint
