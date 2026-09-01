"""Calibrage à partir du SEUL prix MT5.

Le réseau n'est pas sollicité : les deux sources de référence sont simulées,
ce qui permet de vérifier le calcul du markup contre une vérité terrain.
"""

from __future__ import annotations

import unittest

from goldscalp import engine
from goldscalp.config import Config
from goldscalp.core.basis import Basis, estimate_basis
from goldscalp.core.calibration import Calibration
from tests.test_basis import market


class FakeBybit:
    """Client Bybit simulé SANS index or disponible.

    Ce fichier couvre les chemins de REPLI : le mode nominal (index du
    perpétuel or) est testé dans test_index_anchor.py. On force donc
    `index_price` à None pour exercer la bascule vers l'or spot.
    """

    price = 2407.35
    index = None
    reachable = True

    def __init__(self, *args, **kwargs):
        self.offline = not self.reachable

    def resolve_instrument(self, *args, **kwargs):
        from goldscalp.data.bybit import BybitError, Instrument

        if not self.reachable:
            raise BybitError("403 CloudFront : pays bloqué")
        return Instrument(symbol="XAUTUSDT", category="linear")

    def index_price(self, instrument=None):
        from goldscalp.data.bybit import BybitError

        if not self.reachable:
            raise BybitError("403 CloudFront : pays bloqué")
        return self.index

    def ticker(self, instrument):
        return {"lastPrice": str(self.price)}


class FakeYahoo:
    spot = 2400.00
    reachable = True

    def __init__(self, *args, **kwargs):
        self.offline = not self.reachable

    def resolve_instrument(self, symbol=None):
        from goldscalp.data.yahoo import YahooError, YahooInstrument

        if not self.reachable:
            raise YahooError("hôte injoignable")
        return YahooInstrument(symbol or "XAUUSD=X", "or spot", False)

    def last_price(self, instrument):
        return self.spot


class CalibrateBase(unittest.TestCase):
    def setUp(self):
        self._bybit, self._yahoo = engine.BybitClient, engine.YahooGoldClient
        self._measure = engine.measure_basis
        # Attributs de CLASSE : sans remise à zéro explicite, une valeur posée
        # par un test contamine les suivants.
        FakeBybit.reachable = True
        FakeBybit.index = None
        FakeBybit.price = 2407.35
        FakeYahoo.reachable = True
        FakeYahoo.spot = 2400.00
        engine.BybitClient = FakeBybit
        engine.YahooGoldClient = FakeYahoo
        # Base connue : spot = bybit - 7.35
        bybit, spot, _ = market(200, xaut_premium=-7.35)
        engine.measure_basis = lambda config: estimate_basis(bybit, spot)

    def tearDown(self):
        engine.BybitClient = self._bybit
        engine.YahooGoldClient = self._yahoo
        engine.measure_basis = self._measure


class TestProbe(CalibrateBase):
    def test_index_wins_when_available(self):
        """Le mode nominal : l'index du perpétuel or prime sur tout le reste."""
        FakeBybit.index = 2399.90
        probe = engine.probe_reference_price(Config())
        self.assertTrue(probe.ok)
        self.assertEqual(probe.reference, "index")
        self.assertAlmostEqual(probe.bybit, 2399.90, places=2)

    def test_falls_back_to_spot_without_index(self):
        probe = engine.probe_reference_price(Config())
        self.assertTrue(probe.ok)
        self.assertEqual(probe.symbol, "XAUUSD=X")
        self.assertAlmostEqual(probe.spot, 2400.00, places=2)
        self.assertEqual(probe.reference, "spot")
        self.assertIn("index", probe.problem)

    def test_falls_back_to_spot_when_bybit_is_blocked(self):
        """Le cas réel : fonction déployée dans une région filtrée par Bybit.
        L'or spot suffit, c'est déjà le référentiel visé."""
        FakeBybit.reachable = False
        probe = engine.probe_reference_price(Config())
        self.assertTrue(probe.ok)
        self.assertEqual(probe.symbol, "XAUUSD=X")
        self.assertAlmostEqual(probe.spot, 2400.00, places=2)
        self.assertEqual(probe.reference, "spot")
        self.assertIn("CloudFront", probe.problem)

    def test_reports_failure_when_no_source_answers(self):
        FakeBybit.reachable = False
        FakeYahoo.reachable = False
        probe = engine.probe_reference_price(Config())
        self.assertFalse(probe.ok)
        self.assertIn("Bybit", probe.problem)
        self.assertIn("Yahoo", probe.problem)


class TestCalibrateFromMt5(CalibrateBase):
    def test_single_price_measures_the_broker_markup(self):
        """Vérité terrain : spot 2400.00, MT5 2400.30 -> markup 0.30 $."""
        calibration, probe = engine.calibrate_from_mt5(Config(), Calibration(), 2400.30)
        self.assertTrue(probe.ok, probe.problem)
        self.assertEqual(calibration.reference, "spot")
        self.assertAlmostEqual(calibration.alpha, 0.30, places=1)

    def test_bid_and_ask_measure_the_spread(self):
        calibration, _ = engine.calibrate_from_mt5(Config(), Calibration(), 2400.15, 2400.45)
        self.assertAlmostEqual(calibration.spread, 0.30, places=2)
        self.assertAlmostEqual(calibration.alpha, 0.30, places=1)

    def test_reversed_bid_ask_is_corrected(self):
        calibration, probe = engine.calibrate_from_mt5(Config(), Calibration(), 2400.45, 2400.15)
        self.assertTrue(probe.ok, probe.problem)
        self.assertAlmostEqual(calibration.spread, 0.30, places=2)

    def test_single_price_reuses_the_known_spread(self):
        """Inventer un spread serait pire que réutiliser celui déjà mesuré."""
        first, _ = engine.calibrate_from_mt5(Config(), Calibration(), 2400.10, 2400.90)
        self.assertAlmostEqual(first.spread, 0.80, places=2)
        second, _ = engine.calibrate_from_mt5(Config(), first, 2400.50)
        self.assertAlmostEqual(second.spread, 0.80, places=2)

    def test_calibration_is_durable_when_basis_is_available(self):
        calibration, _ = engine.calibrate_from_mt5(Config(), Calibration(), 2400.30)
        self.assertFalse(calibration.is_stale)
        self.assertGreater(calibration.stale_after_ms, 24 * 3_600_000)

    def test_spot_reference_is_used_even_without_basis(self):
        """La base ne sert plus au calage : le spot EST déjà le référentiel."""
        engine.measure_basis = lambda config: Basis(note="pas de bougie commune")
        calibration, probe = engine.calibrate_from_mt5(Config(), Calibration(), 2400.30)
        self.assertTrue(probe.ok, probe.problem)
        self.assertEqual(calibration.reference, "spot")
        self.assertAlmostEqual(calibration.alpha, 0.30, places=1)

    def test_untouched_when_no_source_answers(self):
        FakeBybit.reachable = False
        FakeYahoo.reachable = False
        original = Calibration()
        calibration, probe = engine.calibrate_from_mt5(Config(), original, 2400.30)
        self.assertFalse(probe.ok)
        self.assertIs(calibration, original)

    def test_produced_prices_match_the_broker(self):
        """Le test qui compte : après calibrage au seul prix MT5, un prix Bybit
        converti doit retomber sur le prix broker."""
        calibration, probe = engine.calibrate_from_mt5(Config(), Calibration(), 2400.30)
        self.assertTrue(probe.ok, probe.problem)
        bybit, spot, broker = market(200, xaut_premium=-7.35, broker_markup=0.30)
        bundle = engine.DataBundle()
        bundle.series = {"M1": bybit}
        bundle.price_source = "BYBIT"
        bundle.basis = estimate_basis(bybit, spot)
        convert, chain, residual = engine._conversion(bundle, calibration)
        produced = convert(bybit).closed_only.last.close
        self.assertLess(abs(produced - broker[-2]), 0.25, chain)
        self.assertLess(residual, 0.5)


class TestWebEndpoint(CalibrateBase):
    def _api(self):
        import importlib.util
        import os

        os.environ.setdefault("GOLDSCALP_HOME", "/tmp/goldscalp-test")
        spec = importlib.util.spec_from_file_location("vapi", "api/index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.engine = engine
        return module

    def test_endpoint_returns_a_reusable_alpha(self):
        api = self._api()
        payload = api.run_calibration({"mt5": ["2400.30"]})
        self.assertTrue(payload["ok"])
        self.assertIn(payload["reference"], ("index", "spot"))
        self.assertTrue(payload["durable"])
        self.assertAlmostEqual(payload["alpha"], 0.30, places=1)
        self.assertIn("markup", payload["message"].lower())

    def test_endpoint_requires_the_price(self):
        api = self._api()
        with self.assertRaises(ValueError):
            api.run_calibration({})
        with self.assertRaises(ValueError):
            api.run_calibration({"mt5": ["0"]})

    def test_endpoint_accepts_bid_and_ask(self):
        api = self._api()
        payload = api.run_calibration({"bid": ["2400.15"], "ask": ["2400.45"]})
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["spread"], 0.30, places=2)
        self.assertAlmostEqual(payload["alpha"], 0.30, places=1)

    def test_reference_travels_with_alpha(self):
        """Un alpha de +0.15 en spot et +0.15 en brut ne décrivent pas le même
        écart : le référentiel doit accompagner la valeur."""
        api = self._api()
        as_spot, _ = api.build_calibration({"alpha": ["0.15"], "ref": ["spot"]})
        as_raw, _ = api.build_calibration({"alpha": ["0.15"]})
        self.assertEqual(as_spot.reference, "spot")
        self.assertEqual(as_raw.reference, "bybit")
        self.assertTrue(as_spot.anchors[0].is_spot_based)
        self.assertFalse(as_raw.anchors[0].is_spot_based)


if __name__ == "__main__":
    unittest.main()
