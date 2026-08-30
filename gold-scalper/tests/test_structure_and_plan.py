"""Tests de la structure de marche et du plan de trade."""

from __future__ import annotations

import unittest

from goldscalp.config import Config, MarketConfig, RiskConfig
from goldscalp.core.calibration import Calibration, add_anchor
from goldscalp.core.indicators import compute_indicators
from goldscalp.core.plan import build_plan
from goldscalp.core.regime import SessionInfo, current_session, detect_regime
from goldscalp.core.scoring import build_timeframe_view, fuse
from goldscalp.core.series import Candle, Series, resample
from goldscalp.core.structure import (
    build_structure,
    cluster_levels,
    fib_levels,
    find_swings,
    impulse_leg,
    round_numbers,
)
from goldscalp.data.synthetic import generate_series
from goldscalp.util import now_ms


def ramp(count: int, start: float, step: float, noise: float = 0.0) -> Series:
    candles = []
    price = start
    for i in range(count):
        open_price = price
        price += step
        high = max(open_price, price) + 0.4 + noise
        low = min(open_price, price) - 0.4 - noise
        candles.append(Candle(i * 300000, open_price, high, low, price, 500.0))
    return Series("M5", candles)


class TestSwings(unittest.TestCase):
    def test_finds_obvious_peak(self):
        closes = [2400, 2401, 2402, 2405, 2402, 2401, 2400]
        candles = [
            Candle(i * 60000, c, c + 0.1, c - 0.1, c, 10.0) for i, c in enumerate(closes)
        ]
        swings = find_swings(candles, span=2)
        highs = [s for s in swings if s.kind == "high"]
        self.assertTrue(any(abs(s.price - 2405.1) < 0.2 for s in highs))

    def test_ignores_edges(self):
        # Aucun pivot ne peut etre confirme dans les `span` premieres et
        # dernieres bougies : c'est ce qui rend la detection causale.
        series = generate_series("M5", 60, 2400.0, seed=3)
        swings = find_swings(series.candles, span=3)
        for swing in swings:
            self.assertGreaterEqual(swing.index, 3)
            self.assertLess(swing.index, len(series) - 3)


class TestLevels(unittest.TestCase):
    def test_cluster_merges_nearby_prices(self):
        points = [(2400.0, "support", 1.0), (2400.2, "support", 0.9), (2412.0, "resistance", 0.8)]
        levels = cluster_levels(points, tolerance=1.0)
        self.assertEqual(len(levels), 2)

    def test_more_touches_means_more_strength(self):
        one = cluster_levels([(2400.0, "support", 0.5)], tolerance=1.0)[0]
        many = cluster_levels(
            [(2400.0 + i * 0.1, "support", 0.5) for i in range(5)], tolerance=1.0
        )[0]
        self.assertGreater(many.strength, one.strength)

    def test_strength_is_absolute_not_relative(self):
        """Un niveau isole ne doit pas etre ecrase parce qu'un autre amas est
        gros : sinon les TP migrent vers des chiffres ronds sans substance."""
        points = [(2400.0, "support", 0.9)] + [(2450.0 + i * 0.05, "resistance", 0.5) for i in range(9)]
        levels = cluster_levels(points, tolerance=1.0)
        isolated = min(levels, key=lambda l: abs(l.price - 2400.0))
        self.assertGreater(isolated.strength, 0.35)

    def test_round_numbers_ranked_by_significance(self):
        levels = {round(l.price): l.strength for l in round_numbers(2400.0, step=5.0, count=4)}
        self.assertGreater(levels[2400], levels[2410])   # centaine > dizaine
        self.assertGreater(levels[2410], levels[2415])   # dizaine > multiple de 5


class TestImpulseAndFib(unittest.TestCase):
    def test_fib_levels_lie_between_extremes(self):
        levels = fib_levels(2450.0, 2400.0, uptrend=True)
        for name in ("0.382", "0.5", "0.618"):
            self.assertGreater(levels[name], 2400.0)
            self.assertLess(levels[name], 2450.0)
        # Les extensions doivent sortir de la jambe.
        self.assertGreater(levels["1.272"], 2450.0)

    def test_fib_empty_when_no_range(self):
        self.assertEqual(fib_levels(2400.0, 2400.0, True), {})

    def test_impulse_leg_uses_extremes(self):
        series = ramp(120, 2400.0, 0.35)
        swings = find_swings(series.candles, 3)
        high, low, up = impulse_leg(swings, series.candles)
        if high is not None:
            self.assertGreater(high, low)
            self.assertTrue(up)


class TestStructureView(unittest.TestCase):
    def test_uptrend_detected(self):
        series = ramp(200, 2400.0, 0.30)
        structure = build_structure(series, None, atr_value=1.0)
        self.assertEqual(structure.trend, "haussier")

    def test_downtrend_detected(self):
        series = ramp(200, 2500.0, -0.30)
        structure = build_structure(series, None, atr_value=1.0)
        self.assertEqual(structure.trend, "baissier")

    def test_levels_sorted_around_price(self):
        series = generate_series("M5", 300, 2400.0, seed=8).closed_only
        indicators = compute_indicators(series)
        structure = build_structure(series, None, indicators.atr_value)
        price = series.last.close
        above = structure.levels_above(price, 4)
        below = structure.levels_below(price, 4)
        self.assertTrue(all(l.price > price for l in above))
        self.assertTrue(all(l.price < price for l in below))
        self.assertEqual(above, sorted(above, key=lambda l: l.price))
        self.assertEqual(below, sorted(below, key=lambda l: l.price, reverse=True))

    def test_short_series_degrades_gracefully(self):
        structure = build_structure(Series("M5", []), None, 1.0)
        self.assertEqual(structure.trend, "range")
        self.assertEqual(structure.levels, [])


class TestTradePlan(unittest.TestCase):
    """Le plan doit etre geometriquement coherent, quoi qu'il arrive."""

    def _confluence(self, seed: int, hour: int = 14):
        day = (now_ms() // 86400000) * 86400000
        m1 = generate_series("M1", 2000, 2400.0, seed=seed, end_ms=day + hour * 3600000)
        views = {}
        for timeframe in ("M1", "M5", "M15"):
            series = (m1 if timeframe == "M1" else resample(m1, timeframe)).closed_only
            indicators = compute_indicators(series)
            regime = detect_regime(indicators)
            structure = build_structure(series, None, indicators.atr_value)
            views[timeframe] = build_timeframe_view(timeframe, indicators, structure, regime, "test")
        from goldscalp.core.fundamental import FundamentalView
        from goldscalp.core.microstructure import MicroView

        return fuse(views, FundamentalView(), MicroView(), current_session(day + hour * 3600000), 80.0, 0.0)

    def test_plan_geometry(self):
        calibration = add_anchor(Calibration(), 2400.0, 2407.0, 2407.3)
        risk, market = RiskConfig(), MarketConfig()
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        built = 0
        for seed in range(25):
            confluence = self._confluence(seed)
            if confluence.direction == 0:
                continue
            plan = build_plan(confluence, calibration, risk, market, session)
            if not plan.valid:
                continue
            built += 1
            direction = 1 if plan.side == "ACHAT" else -1
            with self.subTest(seed=seed):
                self.assertLess((plan.stop - plan.entry) * direction, 0, "stop du mauvais cote")
                for target in plan.targets:
                    self.assertGreater((target.price - plan.entry) * direction, 0,
                                       f"{target.label} du mauvais cote")
                self.assertGreater((plan.targets[1].price - plan.targets[0].price) * direction, 0,
                                   "TP2 doit depasser TP1")
                self.assertGreaterEqual(plan.rr1, risk.min_rr_tp1 - 1e-6)
                self.assertGreater(plan.rr2, plan.rr1)
                self.assertGreaterEqual(plan.lots, 0.01)
        self.assertGreater(built, 0, "aucun plan construit : le test ne verifie rien")

    def test_position_size_matches_declared_risk(self):
        calibration = add_anchor(Calibration(), 2400.0, 2407.0, 2407.3)
        market = MarketConfig()
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        for balance, risk_pct in ((10_000.0, 0.5), (50_000.0, 1.0)):
            risk = RiskConfig(account_balance=balance, risk_pct=risk_pct)
            for seed in range(25):
                confluence = self._confluence(seed)
                if confluence.direction == 0:
                    continue
                plan = build_plan(confluence, calibration, risk, market, session)
                if not plan.valid:
                    continue
                expected = plan.lots * plan.stop_distance * market.contract_size
                self.assertAlmostEqual(plan.risk_amount, expected, delta=max(expected * 0.02, 0.5))
                # Le risque ne doit jamais depasser le plafond declare.
                self.assertLessEqual(plan.risk_amount, balance * risk_pct / 100.0 * 1.30)
                break

    def test_excessive_spread_is_refused(self):
        calibration = add_anchor(Calibration(), 2400.0, 2405.0, 2410.0)   # spread 5 $
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        for seed in range(25):
            confluence = self._confluence(seed)
            if confluence.direction == 0:
                continue
            plan = build_plan(confluence, calibration, RiskConfig(), MarketConfig(), session)
            self.assertFalse(plan.valid)
            self.assertIn("spread", plan.rejection.lower())
            return
        self.skipTest("aucun signal genere pour ce controle")

    def test_news_multiplier_reduces_size(self):
        calibration = add_anchor(Calibration(), 2400.0, 2407.0, 2407.3)
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        for seed in range(25):
            confluence = self._confluence(seed)
            if confluence.direction == 0:
                continue
            full = build_plan(confluence, calibration, RiskConfig(), MarketConfig(), session, 1.0)
            half = build_plan(confluence, calibration, RiskConfig(), MarketConfig(), session, 0.5)
            if not (full.valid and half.valid):
                continue
            self.assertLess(half.lots, full.lots)
            return
        self.skipTest("aucun plan genere pour ce controle")


if __name__ == "__main__":
    unittest.main()
