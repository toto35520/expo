"""La source XAUUSD et le collecteur — ce qui est mesuré, et ce qui ne l'est pas."""

import json
import os

import pytest

from feasibility.collect_xauusd import Collector, CollectorConfig, preflight
from feasibility.cost_floor_xauusd import AccountType, BaseCurrency, Q63Status
from feasibility.mt5_source import (
    AcquisitionContract,
    AcquisitionMode,
    B1Anchor,
    MarketStateEstimator,
    MT5Source,
    ReplaySource,
    Tick,
    acquisition_report,
    spec_from_mapping,
    synthetic_ticks,
    write_ticks,
)
from feasibility.observability import MeasurementGrade
from feasibility.passive_campaign import (
    NS_PER_MS,
    NS_PER_SECOND,
    CampaignError,
    DataStatus,
    summarise_by_cell,
)

POLLED = AcquisitionContract(
    mode=AcquisitionMode.POLLED, poll_interval_ns=NS_PER_MS, description="test",
)


# --------------------------------------------------- horloge contre ancrage de B1


def test_une_source_sondee_garde_une_horloge_exacte():
    """La régression qui comptait le plus.

    Classer le sondage en `LOWER_BOUND` écartait chaque observation de la distribution
    locale : une collecte réelle d'une journée entière n'aurait produit aucun résumé, et
    elle l'aurait fait sans rien signaler.
    """
    assert POLLED.clock_grade is MeasurementGrade.EXACT_LOCAL
    assert POLLED.b1_anchor is B1Anchor.POLL_OBSERVATION


def test_le_biais_de_sondage_est_declare_plutot_que_dilue():
    assert POLLED.b1_quantisation_bias_ns == NS_PER_MS
    assert "1 ms" in acquisition_report(POLLED)


def test_une_source_poussee_n_a_aucun_temps_non_observe_avant_b1():
    pousse = AcquisitionContract(mode=AcquisitionMode.PUSHED)
    assert pousse.b1_anchor is B1Anchor.ARRIVAL
    assert pousse.b1_quantisation_bias_ns == 0


def test_un_mode_sonde_sans_intervalle_est_refuse():
    with pytest.raises(CampaignError, match="quantification"):
        AcquisitionContract(mode=AcquisitionMode.POLLED, poll_interval_ns=0)


def test_le_rejeu_ne_pretend_pas_mesurer_le_marche():
    rejeu = ReplaySource(path="/dev/null")
    assert not rejeu.contract.measures_market_latency
    assert rejeu.contract.b1_anchor is B1Anchor.REPLAY_NO_TRANSPORT
    assert "cette machine" in acquisition_report(rejeu.contract)


def test_l_horloge_du_courtier_reste_non_qualifiee():
    """B0 est enregistré, mais l'écart avec notre horloge contient un décalage inconnu."""
    assert not POLLED.provider_clock_qualified
    assert "NON qualifiée" in acquisition_report(POLLED)


# ----------------------------------------------------------------- état de marché


def test_les_centiles_partent_de_zero_plutot_que_d_inventer_une_rafale():
    est = MarketStateEstimator()
    ctx = est.update(Tick(bid=2_400.0, ask=2_400.1, provider_ns=None), 0)
    assert ctx.burst_percentile == 0.0
    assert ctx.spread_percentile == 0.0
    assert not est.warm


def test_le_rang_de_rafale_monte_avec_l_intensite():
    est = MarketStateEstimator()
    t = 0
    for _ in range(200):                      # régime calme : un tick toutes les 100 ms
        t += 100 * NS_PER_MS
        est.update(Tick(2_400.0, 2_400.1, None), t)
    for _ in range(50):                       # rafale : un tick toutes les 100 µs
        t += 100_000
        ctx = est.update(Tick(2_400.0, 2_400.1, None), t)
    assert ctx.burst_percentile > 0.9
    assert est.warm


def test_la_vitesse_est_nulle_au_premier_tick():
    est = MarketStateEstimator()
    ctx = est.update(Tick(2_400.0, 2_400.1, None), 1_000)
    assert ctx.price_velocity == 0.0


def test_la_fenetre_de_centiles_refuse_d_etre_degeneree():
    with pytest.raises(CampaignError, match="au moins 2"):
        MarketStateEstimator(history=1)


def test_le_taux_de_ticks_se_calcule_sur_la_fenetre_glissante():
    est = MarketStateEstimator()
    for i in range(10):
        ctx = est.update(Tick(2_400.0, 2_400.1, None), i * 100 * NS_PER_MS)
    assert ctx.tick_rate_1s == pytest.approx(10.0)


# ------------------------------------------------------------------------ MT5


class _FakeTick:
    def __init__(self, bid, ask, time_msc):
        self.bid, self.ask, self.time_msc, self.volume_real = bid, ask, time_msc, 0.0


class _FakeInfo:
    trade_contract_size = 100.0
    trade_tick_size = 0.01
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    volume_max = 50.0
    currency_profit = "USD"
    currency_margin = "USD"
    digits = 2
    swap_long = -3.0
    swap_short = -5.0
    swap_mode = 1
    swap_rollover3days = 3


class _FakeAccount:
    currency = "USD"
    server = "ICMarketsEU-Live12"
    name = "Raw Spread"


class _FakeMT5:
    def __init__(self, ticks):
        self._ticks, self._i = ticks, 0

    def initialize(self):
        return True

    def shutdown(self):
        return None

    def symbol_select(self, *_):
        return True

    def account_info(self):
        return _FakeAccount()

    def symbol_info(self, _):
        return _FakeInfo()

    def symbol_info_tick(self, _):
        if self._i >= len(self._ticks):
            return self._ticks[-1] if self._ticks else None
        t = self._ticks[self._i]
        self._i += 1
        return t


def test_mt5_lit_le_type_de_compte_et_la_devise():
    src = MT5Source(mt5_module=_FakeMT5([]))
    identite = src.account_identity()
    assert identite.account_type is AccountType.RAW_SPREAD
    assert identite.base_currency is BaseCurrency.USD


def test_un_compte_non_reconnu_reste_unknown_plutot_que_devine():
    """Une déduction incertaine ne doit pas devenir une commission contractuelle."""
    faux = _FakeMT5([])
    faux.account_info = lambda: type(
        "A", (), {"currency": "USD", "server": "X-Live", "name": "Compte principal"}
    )()
    assert MT5Source(mt5_module=faux).account_identity().account_type is (
        AccountType.UNKNOWN
    )


def test_mt5_releve_la_specification_du_symbole():
    spec = MT5Source(mt5_module=_FakeMT5([])).symbol_specification()
    assert spec is not None
    assert spec.contract_size == 100.0
    assert spec.swaps_known
    assert "symbol_info" in spec.read_from


def test_le_preflight_mt5_resout_les_trois_elements_de_q63():
    src = MT5Source(mt5_module=_FakeMT5([]))
    pre = preflight(src)
    assert pre.q63.status is Q63Status.VERIFIED
    assert pre.floor_before_rollover.resolved


def test_un_tick_identique_n_est_pas_un_nouvel_evenement():
    """Sinon la fréquence de sondage se ferait passer pour de l'activité de marché."""
    ticks = [_FakeTick(2_400.0, 2_400.1, 1_000)] * 5 + [_FakeTick(2_401.0, 2_401.1, 1_001)]
    src = MT5Source(mt5_module=_FakeMT5(ticks), poll_interval_ns=1)
    flux = src.ticks()
    vus = [next(flux) for _ in range(2)]
    assert [t.bid for t in vus] == [2_400.0, 2_401.0]


def test_le_paquet_mt5_absent_donne_une_erreur_utilisable():
    src = MT5Source()
    src._mt5 = None
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        with pytest.raises(CampaignError, match="replay"):
            src.open()


# ---------------------------------------------------------------------- rejeu


def test_le_rejeu_relit_ce_qui_a_ete_ecrit(tmp_path):
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(20))
    relus = list(ReplaySource(path=chemin).ticks())
    assert len(relus) == 20
    assert all(t.ask > t.bid for t in relus)


def test_un_releve_manuel_incomplet_est_refuse():
    with pytest.raises(CampaignError, match="champs manquants"):
        spec_from_mapping({"symbol": "XAUUSD"}, read_from="relevé manuel")


def test_un_releve_manuel_complet_porte_sa_provenance():
    spec = spec_from_mapping({
        "symbol": "XAUUSD", "contract_size": 100, "tick_size": 0.01, "point": 0.01,
        "volume_min": 0.01, "volume_step": 0.01, "volume_max": 50,
        "currency_profit": "USD", "currency_margin": "USD", "digits": 2,
    }, read_from="relevé manuel du terminal")
    assert "relevé manuel" in spec.read_from


# ------------------------------------------------------------------ collecteur


def test_le_collecteur_produit_observations_journal_et_manifeste(tmp_path):
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(400))
    source = ReplaySource(path=chemin)
    collector = Collector(source, CollectorConfig(out_dir=str(tmp_path / "out")))
    pre = preflight(source)
    collector.manifest(pre).write(collector.manifest_path)

    assert collector.run() == 400
    observations = collector.recorder.drain()
    assert len(observations) == 400
    assert os.path.exists(collector.journal_path)

    lignes = open(collector.journal_path, encoding="utf-8").read().strip().split("\n")
    assert len(lignes) == 400
    assert json.loads(lignes[0])["cell"].startswith("XAUUSD@MT5/")


def test_les_observations_collectees_alimentent_bien_une_distribution(tmp_path):
    """Le test qui aurait attrapé la confusion horloge / ancrage."""
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(300))
    collector = Collector(
        ReplaySource(path=chemin), CollectorConfig(out_dir=str(tmp_path / "out"))
    )
    collector.run()
    resumes = summarise_by_cell(collector.recorder.drain())
    assert resumes
    assert sum(s.observations for s in resumes.values()) == 300


def test_le_manifeste_classe_la_collecte_en_exploratoire(tmp_path):
    """Aucun gel de protocole n'est posé : rien de normatif ne peut en sortir."""
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(5))
    source = ReplaySource(path=chemin)
    collector = Collector(source, CollectorConfig(out_dir=str(tmp_path / "out")))
    collector.manifest(preflight(source)).write(collector.manifest_path)

    manifeste = json.load(open(collector.manifest_path, encoding="utf-8"))
    assert manifeste["data_status"] == DataStatus.EXPLORATORY.value
    assert manifeste["evaluation_is_final_engine"] is False
    assert manifeste["q1_fingerprint"]
    assert manifeste["q63_status"] == Q63Status.PROVISIONAL.value
    assert manifeste["q65_fingerprint"]


def test_le_collecteur_s_arrete_sur_demande(tmp_path):
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(500))
    collector = Collector(
        ReplaySource(path=chemin), CollectorConfig(out_dir=str(tmp_path / "out"))
    )
    collector.request_stop()
    assert collector.run() == 0


def test_le_collecteur_respecte_la_limite_d_evenements(tmp_path):
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(500))
    collector = Collector(
        ReplaySource(path=chemin),
        CollectorConfig(out_dir=str(tmp_path / "out"), max_events=42),
    )
    assert collector.run() == 42


def test_le_rapport_declare_les_trois_limites_de_la_collecte(tmp_path):
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(200))
    collector = Collector(
        ReplaySource(path=chemin), CollectorConfig(out_dir=str(tmp_path / "out"))
    )
    collector.run()
    rapport = collector.report()
    assert "REJEU" in rapport                       # durées non représentatives
    assert "évaluation était vide" in rapport       # borne inférieure du système final
    assert DataStatus.EXPLORATORY.value in rapport  # aucun verdict normatif possible


def test_un_intervalle_de_confiance_incalculable_le_dit(tmp_path):
    """Afficher un intervalle nul ferait passer une absence d'information pour de la précision."""
    chemin = str(tmp_path / "ticks.jsonl")
    write_ticks(chemin, synthetic_ticks(30))
    collector = Collector(
        ReplaySource(path=chemin),
        CollectorConfig(out_dir=str(tmp_path / "out"), quiet_block_ms=10_000),
    )
    collector.run()
    assert "IC non calculable" in collector.report()
