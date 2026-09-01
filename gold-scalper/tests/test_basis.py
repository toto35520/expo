"""Tests de la base Bybit↔spot et de la chaîne de conversion vers le broker.

Le critère qui compte n'est pas « le code tourne » mais « de combien de dollars
le prix affiché s'écarte-t-il du vrai prix du broker ». C'est ce que ces tests
mesurent, sur un marché simulé dont on connaît la vérité terrain.
"""

from __future__ import annotations

import random
import unittest

from goldscalp import engine
from goldscalp.config import Config
from goldscalp.core.basis import MIN_SAMPLES, Basis, best_common_timeframe, estimate_basis
from goldscalp.core.calibration import Anchor, Calibration, add_anchor, fit
from goldscalp.core.series import Candle, Series
from goldscalp.util import now_ms


def market(bars: int = 200, step_ms: int = 60_000, spot_start: float = 2400.0,
           xaut_premium: float = -7.35, premium_drift: float = 0.0,
           noise: float = 0.0, broker_markup: float = 0.30,
           seed: int = 1) -> tuple[Series, Series, list[float]]:
    """Marché synthétique dont on connaît la vérité terrain.

    Renvoie (série Bybit, série spot, prix broker réels bougie par bougie).
    """
    rng = random.Random(seed)
    base = (now_ms() // step_ms) * step_ms - bars * step_ms
    bybit, spot, broker = [], [], []
    price = spot_start
    for i in range(bars):
        price += rng.gauss(0, 0.7)
        premium = xaut_premium + premium_drift * i
        bybit_price = price - premium + rng.gauss(0, noise)
        spot.append(Candle(base + i * step_ms, price, price + 0.4, price - 0.4, price, 100))
        bybit.append(Candle(base + i * step_ms, bybit_price, bybit_price + 0.4,
                            bybit_price - 0.4, bybit_price, 100))
        broker.append(price + broker_markup)
    # Comme dans la réalité, la dernière bougie est encore en formation : les
    # deux séries et la vérité terrain restent alors alignées sur l'indice -2.
    for group in (bybit, spot):
        live = group[-1]
        group[-1] = Candle(live.ts, live.open, live.high, live.low, live.close,
                           live.volume, live.turnover, closed=False)
    return Series("M1", bybit), Series("M1", spot), broker


class TestBasisEstimation(unittest.TestCase):
    def test_recovers_a_constant_premium(self):
        bybit, spot, _ = market(200, xaut_premium=-7.35)
        basis = estimate_basis(bybit, spot)
        self.assertTrue(basis.ok)
        self.assertAlmostEqual(basis.value, -7.35, places=2)
        self.assertLess(basis.dispersion, 0.01)

    def test_survives_noise(self):
        bybit, spot, _ = market(200, xaut_premium=-7.35, noise=0.30, seed=5)
        basis = estimate_basis(bybit, spot)
        self.assertAlmostEqual(basis.value, -7.35, delta=0.15)

    def test_ignores_a_single_absurd_candle(self):
        """Une mèche de liquidation ne doit pas déplacer la base : la médiane
        est choisie précisément pour ça."""
        bybit, spot, _ = market(200, xaut_premium=-7.35)
        spot.candles[100] = Candle(spot[100].ts, 9000, 9000, 9000, 9000, 1)
        basis = estimate_basis(bybit, spot)
        self.assertAlmostEqual(basis.value, -7.35, delta=0.05)

    def test_follows_a_drifting_premium(self):
        """Quand la prime dérive, la base doit suivre la valeur RÉCENTE, pas
        la moyenne de la fenêtre."""
        bybit, spot, _ = market(200, xaut_premium=-8.0, premium_drift=0.02)
        basis = estimate_basis(bybit, spot)
        final_premium = -8.0 + 0.02 * 199
        average_premium = -8.0 + 0.02 * 100
        self.assertLess(abs(basis.value - final_premium), abs(basis.value - average_premium))
        self.assertGreater(basis.drift_per_hour, 0.5)

    def test_refuses_when_too_few_common_bars(self):
        bybit, spot, _ = market(200)
        short = Series("M1", spot.candles[:MIN_SAMPLES - 2])
        basis = estimate_basis(bybit, short)
        self.assertFalse(basis.ok)
        self.assertEqual(basis.quality(), 0.0)

    def test_refuses_an_implausible_gap(self):
        """Deux cotations de l'or ne peuvent pas différer de 500 $ : mieux vaut
        refuser que corriger avec une valeur absurde."""
        bybit, spot, _ = market(200, xaut_premium=-500.0)
        basis = estimate_basis(bybit, spot)
        self.assertFalse(basis.ok)
        self.assertEqual(basis.value, 0.0)

    def test_only_closed_candles_are_compared(self):
        bybit, spot, _ = market(60)
        basis = estimate_basis(bybit, spot)
        self.assertLess(basis.last_ts, bybit.last.ts)

    def test_best_common_timeframe_prefers_finest(self):
        bybit, spot, _ = market(200)
        chosen = best_common_timeframe({"M1": bybit, "M5": bybit}, {"M1": spot, "M5": spot})
        self.assertEqual(chosen, "M1")

    def test_no_common_timeframe_returns_none(self):
        bybit, spot, _ = market(200)
        shifted = Series("M1", [Candle(c.ts + 7, c.open, c.high, c.low, c.close) for c in spot])
        self.assertIsNone(best_common_timeframe({"M1": bybit}, {"M1": shifted}))


class TestSpotAnchoring(unittest.TestCase):
    def test_spot_anchor_measures_broker_markup_only(self):
        calibration = add_anchor(Calibration(), 2407.35, 2400.15, 2400.45, spot=2400.0)
        self.assertEqual(calibration.reference, "spot")
        self.assertAlmostEqual(calibration.alpha, 0.30, places=2)

    def test_raw_anchor_keeps_legacy_behaviour(self):
        calibration = add_anchor(Calibration(), 2400.0, 2407.10, 2407.40)
        self.assertEqual(calibration.reference, "bybit")
        self.assertAlmostEqual(calibration.alpha, 7.25, places=2)

    def test_spot_anchors_win_over_raw_ones(self):
        """Mélanger les deux référentiels additionnerait un markup broker et une
        prime XAUT dans le même alpha."""
        calibration = add_anchor(Calibration(), 2400.0, 2407.10, 2407.40)
        calibration = add_anchor(calibration, 2407.35, 2400.15, 2400.45, spot=2400.0)
        self.assertEqual(calibration.reference, "spot")
        self.assertAlmostEqual(calibration.alpha, 0.30, places=2)

    def test_spot_anchor_survives_days(self):
        recent = fit([Anchor(now_ms(), 2407.35, 2400.15, 2400.45, spot=2400.0)])
        old = fit([Anchor(now_ms() - 3 * 86_400_000, 2407.35, 2400.15, 2400.45, spot=2400.0)])
        self.assertFalse(old.is_stale)
        self.assertGreater(old.quality(), 55.0)
        self.assertAlmostEqual(old.alpha, recent.alpha, places=4)

    def test_raw_anchor_expires_in_hours(self):
        old = fit([Anchor(now_ms() - 8 * 3_600_000, 2400.0, 2407.1, 2407.4)])
        self.assertTrue(old.is_stale)

    def test_persistence_keeps_the_spot_field(self):
        import os
        import tempfile

        from goldscalp.core.calibration import load_calibration, save_calibration

        calibration = add_anchor(Calibration(), 2407.35, 2400.15, 2400.45, spot=2400.0)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "c.json")
            save_calibration(calibration, path)
            loaded = load_calibration(path)
        self.assertEqual(loaded.reference, "spot")
        self.assertEqual(loaded.anchors[0].spot, 2400.0)


class TestConversionAccuracy(unittest.TestCase):
    """LE test qui compte : quel écart reste-t-il au prix réel du broker ?"""

    def _bundle(self, bybit: Series, spot: Series, source: str = "BYBIT") -> engine.DataBundle:
        bundle = engine.DataBundle()
        bundle.series = {"M1": bybit if source == "BYBIT" else spot}
        bundle.price_source = source
        if source == "BYBIT":
            bundle.basis = estimate_basis(bybit, spot)
        return bundle

    def test_error_collapses_to_cents_with_basis_and_spot_anchor(self):
        bybit, spot, broker = market(200, xaut_premium=-7.35, noise=0.05, broker_markup=0.30)
        bundle = self._bundle(bybit, spot)
        anchor_spot = spot.closed_only.last.close
        calibration = add_anchor(
            Calibration(), bybit.closed_only.last.close,
            anchor_spot + 0.15, anchor_spot + 0.45, spot=anchor_spot,
        )
        convert, chain, residual = engine._conversion(bundle, calibration)
        produced = convert(bybit).closed_only.last.close
        truth = broker[-2]
        self.assertLess(abs(produced - truth), 0.25,
                        f"écart de {abs(produced - truth):.3f} $ — chaîne : {chain}")
        self.assertLess(residual, 0.6)
        self.assertIn("base mesurée", chain)

    def test_drifting_premium_stays_accurate_without_recalibrating(self):
        """Le cas qui tuait l'ancrage manuel : la prime XAUT dérive de 4 $ et
        l'ancrage date d'il y a longtemps. La base mesurée absorbe la dérive."""
        bybit, spot, broker = market(300, xaut_premium=-6.0, premium_drift=0.015,
                                     broker_markup=0.30)
        bundle = self._bundle(bybit, spot)
        # Ancrage pris au tout début de la fenêtre, jamais renouvelé.
        old_spot = spot[10].close
        calibration = fit([
            Anchor(spot[10].ts, bybit[10].close, old_spot + 0.15, old_spot + 0.45,
                   spot=old_spot)
        ])
        convert, chain, _ = engine._conversion(bundle, calibration)
        produced = convert(bybit).closed_only.last.close
        self.assertLess(abs(produced - broker[-2]), 0.35)

        # Sans base, le même ancrage ancien serait faux de plusieurs dollars.
        naive = engine.DataBundle()
        naive.series = {"M1": bybit}
        naive.price_source = "BYBIT"
        legacy = fit([Anchor(spot[10].ts, bybit[10].close,
                             broker[10] - 0.15, broker[10] + 0.15)])
        convert_naive, _, _ = engine._conversion(naive, legacy)
        self.assertGreater(abs(convert_naive(bybit).closed_only.last.close - broker[-2]), 2.0)

    def test_yahoo_source_needs_no_basis(self):
        bybit, spot, broker = market(200, broker_markup=0.30)
        bundle = self._bundle(bybit, spot, source="YAHOO")
        anchor_spot = spot.closed_only.last.close
        calibration = add_anchor(Calibration(), anchor_spot, anchor_spot + 0.15,
                                 anchor_spot + 0.45, spot=anchor_spot)
        convert, chain, residual = engine._conversion(bundle, calibration)
        self.assertLess(abs(convert(spot).closed_only.last.close - broker[-2]), 0.2)
        self.assertIn("or spot", chain)

    def test_legacy_anchor_is_retranscribed_not_discarded(self):
        bybit, spot, broker = market(200, xaut_premium=-7.35, broker_markup=0.30)
        bundle = self._bundle(bybit, spot)
        legacy = fit([Anchor(now_ms(), bybit[-5].close,
                             broker[-5] - 0.15, broker[-5] + 0.15)])
        self.assertEqual(legacy.reference, "bybit")
        convert, chain, _ = engine._conversion(bundle, legacy)
        self.assertLess(abs(convert(bybit).closed_only.last.close - broker[-2]), 0.6)

    def test_mt5_series_is_never_converted(self):
        bybit, spot, _ = market(120)
        bundle = engine.DataBundle()
        bundle.series = {"M1": spot}
        bundle.price_source = "MT5"
        convert, chain, residual = engine._conversion(bundle, Calibration())
        self.assertEqual(convert(spot).last.close, spot.last.close)
        self.assertEqual(residual, 0.0)

    def test_uncalibrated_is_flagged_loudly(self):
        bybit, spot, _ = market(120)
        bundle = self._bundle(bybit, spot)
        convert, chain, residual = engine._conversion(bundle, Calibration())
        self.assertIn("AUCUNE", chain)
        self.assertGreater(residual, 100)

    def test_spot_anchor_without_basis_refuses_rather_than_guesses(self):
        """Un ancrage spot sans base mesurée ne peut pas convertir une série
        Bybit. Produire un prix quand même serait faux de plusieurs dollars."""
        bybit, spot, _ = market(120)
        bundle = engine.DataBundle()
        bundle.series = {"M1": bybit}
        bundle.price_source = "BYBIT"
        bundle.basis = Basis()
        calibration = add_anchor(Calibration(), 2407.35, 2400.15, 2400.45, spot=2400.0)
        convert, chain, residual = engine._conversion(bundle, calibration)
        self.assertIn("IMPOSSIBLE", chain)
        self.assertGreater(residual, 100)


if __name__ == "__main__":
    unittest.main()
