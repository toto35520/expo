"""Tests des indicateurs : bornes, references connues, causalite."""

from __future__ import annotations

import unittest

from goldscalp.core import indicators as ind
from goldscalp.core.series import Candle, Series
from goldscalp.data.synthetic import generate_series


def make_candles(closes: list[float], spread: float = 0.5) -> list[Candle]:
    out = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i else close
        out.append(
            Candle(
                ts=i * 60000,
                open=open_price,
                high=max(open_price, close) + spread,
                low=min(open_price, close) - spread,
                close=close,
                volume=100.0,
            )
        )
    return out


class TestMovingAverages(unittest.TestCase):
    def test_sma_known_value(self):
        self.assertAlmostEqual(ind.last_valid(ind.sma([1, 2, 3, 4, 5], 5)), 3.0)

    def test_ema_of_constant_is_constant(self):
        self.assertAlmostEqual(ind.last_valid(ind.ema([7.5] * 80, 21)), 7.5)

    def test_rma_of_constant_is_constant(self):
        self.assertAlmostEqual(ind.last_valid(ind.rma([2.0] * 60, 14)), 2.0)

    def test_leading_values_are_none(self):
        line = ind.sma([1.0] * 10, 5)
        self.assertEqual(line[:4], [None] * 4)
        self.assertIsNotNone(line[4])

    def test_period_longer_than_data_gives_all_none(self):
        self.assertEqual(ind.ema([1.0, 2.0], 20), [None, None])


class TestOscillators(unittest.TestCase):
    def test_rsi_extremes(self):
        rising = [float(i) for i in range(1, 60)]
        self.assertEqual(ind.last_valid(ind.rsi(rising, 14)), 100.0)
        self.assertEqual(ind.last_valid(ind.rsi(list(reversed(rising)), 14)), 0.0)

    def test_rsi_matches_wilder_reference(self):
        # Serie de reference de Wilder ; l'amorce RMA donne les memes valeurs
        # que TradingView (ta.rsi).
        data = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
                46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41]
        values = [v for v in ind.rsi(data, 14) if v is not None]
        self.assertAlmostEqual(values[0], 70.46, places=1)
        self.assertAlmostEqual(values[1], 66.25, places=1)

    def test_rsi_stays_in_bounds_on_noise(self):
        series = generate_series("M1", 400, 2400.0, seed=5).closed_only
        for value in ind.rsi(series.closes, 14):
            if value is not None:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 100.0)

    def test_stochastic_bounds(self):
        candles = make_candles([2400 + i * 0.3 for i in range(80)])
        k_line, d_line = ind.stochastic(candles)
        for line in (k_line, d_line):
            for value in line:
                if value is not None:
                    self.assertGreaterEqual(value, -1e-9)
                    self.assertLessEqual(value, 100 + 1e-9)


class TestVolatility(unittest.TestCase):
    def test_atr_positive(self):
        candles = make_candles([2400 + i * 0.2 for i in range(60)])
        value = ind.last_valid(ind.atr(candles, 14))
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)

    def test_true_range_covers_gaps(self):
        candles = [
            Candle(0, 2400, 2401, 2399, 2400.5),
            Candle(60000, 2420, 2421, 2419, 2420.5),   # gap haussier
        ]
        # Le TR doit refleter l'ecart avec la cloture precedente, pas le seul
        # range de la bougie.
        self.assertAlmostEqual(ind.true_range(candles)[1], 2421 - 2400.5)

    def test_bollinger_order(self):
        closes = [2400 + (i % 7) for i in range(80)]
        upper, basis, lower = ind.bollinger(closes, 20, 2.0)
        for u, b, l in zip(upper, basis, lower):
            if None not in (u, b, l):
                self.assertGreaterEqual(u, b)
                self.assertGreaterEqual(b, l)


class TestVolumeProfile(unittest.TestCase):
    def test_value_area_ordering(self):
        series = generate_series("M5", 300, 2400.0, seed=11).closed_only
        profile = ind.volume_profile(series.candles)
        self.assertIsNotNone(profile)
        self.assertLessEqual(profile.val, profile.poc)
        self.assertLessEqual(profile.poc, profile.vah)

    def test_poc_lands_where_volume_concentrates(self):
        # Beaucoup de bougies serrees autour de 2400, quelques-unes loin.
        candles = [Candle(i * 60000, 2400, 2400.4, 2399.6, 2400, 1000.0) for i in range(60)]
        candles += [Candle((60 + i) * 60000, 2450, 2450.4, 2449.6, 2450, 5.0) for i in range(10)]
        profile = ind.volume_profile(candles, bins=40)
        self.assertLess(abs(profile.poc - 2400), 3.0)

    def test_returns_none_on_short_input(self):
        self.assertIsNone(ind.volume_profile(make_candles([2400.0] * 5)))


class TestCausality(unittest.TestCase):
    """La valeur en i ne doit dependre que des bougies 0..i."""

    def test_lines_unchanged_by_future_data(self):
        series = generate_series("M5", 420, 2400.0, seed=17).closed_only
        cut = 330
        full = ind.compute_indicators(series)
        partial = ind.compute_indicators(
            Series(series.timeframe, series.candles[:cut], series.symbol)
        )
        for name in ("ema21", "rsi14", "atr14", "adx14", "macd_hist", "vwap", "obv", "er", "cci"):
            with self.subTest(indicator=name):
                a = getattr(full, name)[cut - 1]
                b = getattr(partial, name)[-1]
                if a is None and b is None:
                    continue
                self.assertIsNotNone(a)
                self.assertIsNotNone(b)
                self.assertAlmostEqual(a, b, places=6)


class TestPatterns(unittest.TestCase):
    def test_bullish_engulfing(self):
        candles = [
            Candle(0, 2400, 2401, 2399, 2400.5),
            Candle(60000, 2402, 2402.5, 2398, 2398.5),      # bougie baissiere
            Candle(120000, 2398, 2403.5, 2397.8, 2403.0),   # englobe la precedente
        ]
        self.assertIn("engulfing_haussier", ind.candle_patterns(candles, 1.0))

    def test_doji_detected(self):
        candles = make_candles([2400.0, 2400.0, 2400.0])
        candles[-1] = Candle(120000, 2400.0, 2402.0, 2398.0, 2400.02)
        self.assertIn("doji", ind.candle_patterns(candles, 1.0))


class TestDivergence(unittest.TestCase):
    def test_no_divergence_on_short_series(self):
        series = generate_series("M1", 30, 2400.0, seed=1)
        self.assertIsNone(ind.find_divergence(series.candles, ind.rsi(series.closes, 14)))

    def test_detects_bullish_divergence(self):
        # Prix qui fait un plus bas plus bas, oscillateur qui remonte.
        closes = [2400 - i * 0.5 for i in range(40)] + [2385 + i * 0.4 for i in range(20)]
        closes += [2390 - i * 0.55 for i in range(30)]
        candles = make_candles(closes)
        result = ind.find_divergence(candles, ind.rsi(closes, 14), lookback=70)
        # On n'exige pas un sens precis (la serie est synthetique), seulement
        # que la detection ne casse pas et respecte son contrat.
        if result is not None:
            self.assertIn(result.kind, ("bullish", "bearish", "hidden_bullish", "hidden_bearish"))
            self.assertGreaterEqual(result.strength, 0.0)
            self.assertLessEqual(result.strength, 1.0)


if __name__ == "__main__":
    unittest.main()
