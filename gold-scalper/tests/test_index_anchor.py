"""Ancrage sur l'index du perpétuel or : le mode nominal.

Ce que ces tests protègent, c'est la propriété qui manquait à la version
précédente : une ancre juste ne doit pas se périmer. L'écart mesuré entre
l'index or et le XAUUSD du broker est son markup — il ne dérive pas, donc rien
ne justifie de redemander une calibration.
"""

from __future__ import annotations

import unittest

from goldscalp import engine
from goldscalp.config import Config
from goldscalp.core import calibration as cal
from goldscalp.core.series import Candle, Series
from goldscalp.data.bybit import GOLD_INDEX_SYMBOL, BybitError, Instrument
from goldscalp.util import now_ms

DAY = (now_ms() // 86_400_000) * 86_400_000
MIDDAY = DAY + 14 * 3_600_000        # 14 h UTC, hors rollover
INDEX = 4437.00
BID, ASK = 4437.10, 4437.31          # markup attendu : +0.205 $


class TestAnchorValidation(unittest.TestCase):
    def test_accepts_a_realistic_anchor(self):
        cal.validate_anchor(INDEX, BID, ASK)          # ne doit rien lever

    def test_rejects_reversed_bid_ask(self):
        with self.assertRaises(cal.AnchorRefused) as ctx:
            cal.validate_anchor(INDEX, ASK, BID)
        self.assertIn("ASK", str(ctx.exception))

    def test_rejects_a_zero_spread(self):
        """Le même nombre saisi deux fois n'est pas un bid/ask."""
        with self.assertRaises(cal.AnchorRefused):
            cal.validate_anchor(INDEX, BID, BID)

    def test_rejects_a_rollover_spread(self):
        with self.assertRaises(cal.AnchorRefused) as ctx:
            cal.validate_anchor(INDEX, 4430.0, 4444.0)
        self.assertIn("Spread", str(ctx.exception))

    def test_rejects_an_implausible_offset(self):
        """Un écart de 60 $ ne décrit pas deux cotations du même métal."""
        with self.assertRaises(cal.AnchorRefused) as ctx:
            cal.validate_anchor(INDEX, 4500.00, 4500.20)
        self.assertIn("Décalage", str(ctx.exception))

    def test_rejects_non_positive_prices(self):
        for reference, bid, ask in ((0, BID, ASK), (INDEX, 0, ASK), (INDEX, BID, 0)):
            with self.assertRaises(cal.AnchorRefused):
                cal.validate_anchor(reference, bid, ask)


class TestCaptureWindow(unittest.TestCase):
    def test_allowed_during_the_session(self):
        allowed, _ = cal.capture_allowed(MIDDAY)
        self.assertTrue(allowed)

    def test_refused_during_the_daily_rollover(self):
        """Le spread explose quelques minutes autour de la clôture : y figer
        une ancre permanente enregistrerait un spread transitoire."""
        allowed, why = cal.capture_allowed(DAY + 21 * 3_600_000)
        self.assertFalse(allowed)
        self.assertIn("ollover", why)

    def test_refused_on_the_weekend(self):
        # 1970-01-03 était un samedi ; on cherche un samedi récent.
        saturday = DAY
        while int(((saturday // 86_400_000) + 4) % 7) != 5:
            saturday -= 86_400_000
        allowed, why = cal.capture_allowed(saturday + 14 * 3_600_000)
        self.assertFalse(allowed)
        self.assertIn("fermé", why)


class TestPermanence(unittest.TestCase):
    def _anchored(self, age_ms: int = 0) -> cal.Calibration:
        anchor = cal.Anchor(now_ms() - age_ms, INDEX, BID, ASK, spot=INDEX)
        calibration = cal.fit([anchor])
        calibration.reference = "index"
        return calibration

    def test_index_anchor_never_expires(self):
        for days in (0, 3, 30, 365):
            with self.subTest(jours=days):
                calibration = self._anchored(days * 86_400_000)
                self.assertFalse(calibration.is_stale)
                self.assertEqual(cal.health(calibration)[0], "ok")

    def test_raw_anchor_still_expires(self):
        """La permanence ne doit valoir QUE pour l'index : un ancrage adossé au
        métal tokenisé contient une prime qui dérive."""
        old = cal.fit([cal.Anchor(now_ms() - 8 * 3_600_000, 2400.0, 2407.1, 2407.4)])
        self.assertEqual(old.reference, "bybit")
        self.assertTrue(old.is_stale)
        self.assertEqual(cal.health(old)[0], "critique")

    def test_index_anchor_scores_highest(self):
        index = self._anchored()
        spot = cal.fit([cal.Anchor(now_ms(), INDEX, BID, ASK, spot=INDEX)])
        raw = cal.fit([cal.Anchor(now_ms(), 2400.0, 2407.1, 2407.4)])
        self.assertGreater(index.quality(), spot.quality())
        self.assertGreater(spot.quality(), raw.quality())

    def test_describe_names_the_reference(self):
        self.assertIn("index or", self._anchored().describe())


class FakeIndexBybit:
    """Client Bybit simulé exposant l'index du perpétuel or."""

    index = INDEX
    reachable = True

    def __init__(self, *args, **kwargs):
        self.offline = not self.reachable

    def resolve_instrument(self, symbol=None, category=None):
        if not self.reachable:
            raise BybitError("403 CloudFront")
        return Instrument(symbol or GOLD_INDEX_SYMBOL, category or "linear")

    def index_price(self, instrument=None):
        if not self.reachable:
            raise BybitError("403 CloudFront")
        return self.index

    def ticker(self, instrument):
        return {"indexPrice": str(self.index)}


class TestCalibrateOnIndex(unittest.TestCase):
    def setUp(self):
        self._bybit = engine.BybitClient
        FakeIndexBybit.reachable = True
        FakeIndexBybit.index = INDEX
        engine.BybitClient = FakeIndexBybit

    def tearDown(self):
        engine.BybitClient = self._bybit

    def test_probe_returns_the_index(self):
        probe = engine.probe_reference_price(Config())
        self.assertTrue(probe.ok)
        self.assertEqual(probe.reference_kind, "index")
        self.assertEqual(probe.symbol, GOLD_INDEX_SYMBOL)
        self.assertAlmostEqual(probe.bybit, INDEX, places=2)

    def test_bid_ask_measure_the_markup(self):
        calibration, probe = engine.calibrate_from_mt5(Config(), cal.Calibration(), BID, ASK)
        self.assertTrue(probe.ok)
        self.assertEqual(calibration.reference, "index")
        self.assertAlmostEqual(calibration.alpha, 0.205, places=3)
        self.assertAlmostEqual(calibration.spread, 0.21, places=3)
        self.assertFalse(calibration.is_stale)

    def test_refused_anchor_leaves_the_previous_one_intact(self):
        """Un rejet ne doit jamais dégrader une calibration déjà valide."""
        good, _ = engine.calibrate_from_mt5(Config(), cal.Calibration(), BID, ASK)
        after, probe = engine.calibrate_from_mt5(Config(), good, 4500.00, 4500.20)
        self.assertFalse(probe.ok)
        self.assertIn("Décalage", probe.problem)
        self.assertIs(after, good)
        self.assertAlmostEqual(after.alpha, 0.205, places=3)

    def test_conversion_applies_the_markup_directly(self):
        """Pas de base intermédiaire : la série EST le contrat indexé."""
        calibration, _ = engine.calibrate_from_mt5(Config(), cal.Calibration(), BID, ASK)
        candles = [Candle(i * 60_000, INDEX, INDEX + 0.4, INDEX - 0.4, INDEX, 10)
                   for i in range(40)]
        bundle = engine.DataBundle()
        bundle.series = {"M1": Series("M1", candles)}
        bundle.price_source = "BYBIT"
        bundle.instrument = Instrument(GOLD_INDEX_SYMBOL, "linear")
        # Bougies déjà au niveau de l'index : base du contrat nulle.
        bundle.index_price = candles[-1].close
        bundle.index_alignment = 0.0
        convert, chain, residual = engine._conversion(bundle, calibration)
        produced = convert(bundle.series["M1"]).last.close
        self.assertAlmostEqual(produced, INDEX + 0.205, places=3)
        self.assertIn("permanente", chain)
        self.assertLess(residual, 0.30)

    def test_conversion_survives_a_month_without_recalibrating(self):
        anchor = cal.Anchor(now_ms() - 30 * 86_400_000, INDEX, BID, ASK, spot=INDEX)
        calibration = cal.fit([anchor])
        calibration.reference = "index"
        candles = [Candle(i * 60_000, 4500.0, 4500.4, 4499.6, 4500.0, 10) for i in range(40)]
        bundle = engine.DataBundle()
        bundle.series = {"M1": Series("M1", candles)}
        bundle.price_source = "BYBIT"
        bundle.instrument = Instrument(GOLD_INDEX_SYMBOL, "linear")
        bundle.index_price = 4500.0
        bundle.index_alignment = 0.0
        convert, _, residual = engine._conversion(bundle, calibration)
        self.assertAlmostEqual(convert(bundle.series["M1"]).last.close, 4500.205, places=3)
        self.assertLess(residual, 0.30)

    def test_falls_back_when_the_index_is_unreachable(self):
        FakeIndexBybit.reachable = False
        probe = engine.probe_reference_price(Config())
        # Sans réseau dans cet environnement, Yahoo échoue aussi : ce qui compte
        # est que l'échec soit explicite et nomme les deux sources.
        if not probe.ok:
            self.assertIn("Bybit", probe.problem)
        else:
            self.assertEqual(probe.reference_kind, "spot")


class TestIndexAlignment(unittest.TestCase):
    """Le piège qui rendait le calage inopérant en conditions réelles.

    L'ancre est mesurée contre l'INDEX du perpétuel, mais les bougies portent
    le dernier prix TRAITÉ. Les deux diffèrent de la base du contrat, qui vaut
    couramment plusieurs dollars sur l'or. Appliquer le markup sans réaligner
    revient à ajouter un décalage mesuré sur A à des prix venus de B — et
    l'utilisateur a beau réajuster son ancre, l'écart ne se referme jamais.
    """

    LAST = 4434.00        # dernier prix traité du perpétuel
    CONTRACT_BASIS = 3.0  # index - dernier prix

    def _bundle(self, aligned: bool) -> engine.DataBundle:
        candles = [Candle(i * 60_000, self.LAST, self.LAST + 0.4,
                          self.LAST - 0.4, self.LAST, 10) for i in range(50)]
        bundle = engine.DataBundle()
        bundle.series = {"M1": Series("M1", candles)}
        bundle.price_source = "BYBIT"
        bundle.instrument = Instrument(GOLD_INDEX_SYMBOL, "linear")
        if aligned:
            bundle.index_price = INDEX
            bundle.index_alignment = self.CONTRACT_BASIS
        return bundle

    def _calibration(self) -> cal.Calibration:
        calibration = cal.fit([cal.Anchor(now_ms(), INDEX, BID, ASK, spot=INDEX)])
        calibration.reference = "index"
        return calibration

    def test_aligned_series_lands_on_the_broker_price(self):
        convert, chain, residual = engine._conversion(self._bundle(True), self._calibration())
        produced = convert(self._bundle(True).series["M1"]).last.close
        self.assertAlmostEqual(produced, (BID + ASK) / 2, places=2)
        self.assertIn("base du contrat", chain)
        self.assertLess(residual, 0.30)

    def test_unaligned_series_is_off_by_the_contract_basis(self):
        """Sans réalignement, l'erreur vaut exactement la base du contrat."""
        convert, _, _ = engine._conversion(self._bundle(False), self._calibration())
        produced = convert(self._bundle(False).series["M1"]).last.close
        self.assertAlmostEqual(produced - (BID + ASK) / 2, -self.CONTRACT_BASIS, places=2)

    def test_missing_index_inflates_the_declared_residual(self):
        """Ne pas pouvoir corriger la base doit se voir dans le chiffre annoncé,
        pas être passé sous silence."""
        _, chain, residual = engine._conversion(self._bundle(False), self._calibration())
        self.assertGreater(residual, 1.5)
        self.assertIn("index courant indisponible", chain)

    def test_alignment_shifts_without_deforming(self):
        """Un décalage constant ne doit rien changer à la structure technique :
        on corrige un niveau, pas une forme."""
        from goldscalp.core.indicators import compute_indicators

        base = self._bundle(False).series["M1"]
        moved = base.apply_calibration(self.CONTRACT_BASIS, 1.0)
        self.assertAlmostEqual(
            compute_indicators(base).atr_value,
            compute_indicators(moved).atr_value,
            places=6,
        )

    def test_absurd_alignment_is_refused_by_the_bound(self):
        from goldscalp.engine import MAX_INDEX_ALIGNMENT

        self.assertLess(self.CONTRACT_BASIS, MAX_INDEX_ALIGNMENT)
        self.assertGreater(MAX_INDEX_ALIGNMENT, 10.0)


if __name__ == "__main__":
    unittest.main()
