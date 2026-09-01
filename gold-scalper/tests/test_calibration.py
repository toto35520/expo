"""Tests du recalibrage Bybit -> MT5.

C'est le maillon le plus dangereux de l'outil : une calibration fausse
deplace SILENCIEUSEMENT tous les niveaux de plusieurs dollars.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from goldscalp.core import calibration as cal
from goldscalp.core.series import Candle, Series
from goldscalp.util import now_ms


class TestConversions(unittest.TestCase):
    def test_offset_from_single_anchor(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.00, 2407.30)
        self.assertAlmostEqual(c.to_mt5(2400.0), 2407.15, places=2)
        self.assertAlmostEqual(c.to_mt5(2410.0), 2417.15, places=2)

    def test_round_trip_is_reversible(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.00, 2407.30)
        for price in (2350.0, 2400.0, 2478.9):
            self.assertAlmostEqual(c.to_bybit(c.to_mt5(price)), price, places=6)

    def test_bid_ask_straddle_mid(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.00, 2407.40)
        self.assertGreater(c.ask(2400.0), 2400.0)
        self.assertLess(c.bid(2400.0), 2400.0)
        self.assertAlmostEqual(c.ask(2400.0) - c.bid(2400.0), c.spread, places=6)

    def test_identity_without_anchors(self):
        c = cal.Calibration()
        self.assertEqual(c.to_mt5(2400.0), 2400.0)
        self.assertEqual(c.quality(), 0.0)

    def test_series_shift(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.00, 2407.30)
        series = Series("M1", [Candle(0, 2400, 2402, 2398, 2401, 10)])
        shifted = c.apply(series)
        self.assertAlmostEqual(shifted[0].high - series[0].high, 7.15, places=2)
        self.assertAlmostEqual(shifted[0].low - series[0].low, 7.15, places=2)
        # Le volume ne doit pas etre transforme par un decalage de prix.
        self.assertEqual(shifted[0].volume, series[0].volume)


class TestSlopeIdentifiability(unittest.TestCase):
    """Sans ancrages ecartes, la pente n'est pas mesurable : elle doit rester
    a 1.0 plutot que d'etre inventee a partir du bruit."""

    def test_clustered_anchors_keep_slope_one(self):
        c = cal.Calibration()
        for price in (2400.0, 2400.4, 2400.2, 2399.8, 2400.1):
            c = cal.add_anchor(c, price, price + 7.0, price + 7.3)
        self.assertFalse(c.slope_fitted)
        self.assertEqual(c.beta, 1.0)

    def test_spread_out_anchors_recover_slope(self):
        c = cal.Calibration()
        for price in (2300.0, 2380.0, 2450.0, 2520.0):
            target = 5.0 + 1.002 * price
            c = cal.add_anchor(c, price, target - 0.15, target + 0.15)
        self.assertTrue(c.slope_fitted)
        self.assertAlmostEqual(c.beta, 1.002, places=4)
        self.assertAlmostEqual(c.alpha, 5.0, places=1)

    def test_absurd_slope_is_rejected(self):
        # Ancrages incoherents qui impliqueraient une pente de ~2.
        c = cal.Calibration()
        for price, mt5 in ((2300.0, 2307.0), (2400.0, 2507.0), (2500.0, 2707.0)):
            c = cal.add_anchor(c, price, mt5 - 0.15, mt5 + 0.15)
        self.assertFalse(c.slope_fitted)
        self.assertEqual(c.beta, 1.0)

    def test_two_anchors_use_median_offset(self):
        c = cal.Calibration()
        c = cal.add_anchor(c, 2400.0, 2406.9, 2407.1)
        c = cal.add_anchor(c, 2500.0, 2506.9, 2507.1)
        self.assertFalse(c.slope_fitted)
        self.assertAlmostEqual(c.alpha, 7.0, places=2)


class TestHealth(unittest.TestCase):
    def test_no_anchor_is_critical(self):
        level, problems = cal.health(cal.Calibration())
        self.assertEqual(level, "critique")
        self.assertTrue(problems)

    def test_fresh_anchor_is_ok(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.0, 2407.3)
        self.assertEqual(cal.health(c)[0], "ok")

    def test_old_anchor_is_critical(self):
        old = now_ms() - 12 * 3600 * 1000
        c = cal.fit([cal.Anchor(old, 2400.0, 2407.0, 2407.3)])
        self.assertTrue(c.is_stale)
        self.assertEqual(cal.health(c)[0], "critique")

    def test_wide_spread_is_flagged(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2406.5, 2408.0)  # spread 1.5 $
        level, problems = cal.health(c)
        self.assertNotEqual(level, "ok")
        self.assertTrue(any("Spread" in p or "spread" in p for p in problems))

    def test_quality_increases_with_anchors(self):
        one = cal.add_anchor(cal.Calibration(), 2400.0, 2407.0, 2407.3)
        many = one
        for price in (2380.0, 2420.0, 2440.0):
            many = cal.add_anchor(many, price, price + 7.0, price + 7.3)
        self.assertGreater(many.quality(), one.quality())


class TestPersistence(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.0, 2407.3)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "calibration.json")
            cal.save_calibration(c, path)
            loaded = cal.load_calibration(path)
        self.assertAlmostEqual(loaded.alpha, c.alpha, places=6)
        self.assertEqual(loaded.beta, c.beta)
        self.assertEqual(len(loaded.anchors), 1)
        self.assertEqual(loaded.anchors[0].source, "manuel")

    def test_missing_file_gives_empty_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = cal.load_calibration(os.path.join(directory, "absent.json"))
        self.assertEqual(loaded.anchors, [])

    def test_corrupt_file_does_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "broken.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ pas du json")
            loaded = cal.load_calibration(path)
        self.assertEqual(loaded.anchors, [])


class TestAnchorNormalisation(unittest.TestCase):
    def test_bid_ask_swapped_is_corrected(self):
        c = cal.add_anchor(cal.Calibration(), 2400.0, 2407.30, 2407.00)  # inverses
        self.assertGreater(c.anchors[0].mt5_ask, c.anchors[0].mt5_bid)
        self.assertAlmostEqual(c.spread, 0.30, places=2)


if __name__ == "__main__":
    unittest.main()
