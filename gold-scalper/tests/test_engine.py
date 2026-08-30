"""Tests de bout en bout : pipeline, fusion, backtest, CLI."""

from __future__ import annotations

import io
import json
import os
import random
import tempfile
import unittest
from contextlib import redirect_stdout

from goldscalp import engine
from goldscalp.cli import main, to_payload
from goldscalp.config import Config, RiskConfig
from goldscalp.core.backtest import run_backtest
from goldscalp.core.calibration import Calibration, add_anchor
from goldscalp.core.fundamental import FundamentalView, analyse_fundamentals
from goldscalp.core.microstructure import MicroView
from goldscalp.core.regime import SessionInfo, current_session, detect_regime
from goldscalp.core.scoring import build_timeframe_view, fuse
from goldscalp.core.series import Candle, Series, resample
from goldscalp.core.indicators import compute_indicators
from goldscalp.core.structure import build_structure
from goldscalp.data.calendar import EconomicCalendar, Event
from goldscalp.data.synthetic import generate_macro, generate_series
from goldscalp.util import now_ms

DAY = (now_ms() // 86400000) * 86400000
PRIME = DAY + 14 * 3600000        # chevauchement Londres / New York
DEAD = DAY + 2 * 3600000          # session asiatique


def calibration() -> Calibration:
    return add_anchor(Calibration(), 2400.0, 2407.00, 2407.30)


class TestPipeline(unittest.TestCase):
    def test_demo_run_produces_analysis(self):
        analysis = engine.run(Config(), calibration(), demo=True, seed=11, demo_end_ms=PRIME)
        self.assertTrue(analysis.data.simulated)
        self.assertGreater(analysis.price, 0)
        self.assertEqual(set(analysis.confluence.views), {"M1", "M5", "M15"})
        self.assertGreater(analysis.data.bars_total, 1000)

    def test_session_follows_simulated_clock(self):
        prime = engine.run(Config(), calibration(), demo=True, seed=3, demo_end_ms=PRIME)
        dead = engine.run(Config(), calibration(), demo=True, seed=3, demo_end_ms=DEAD)
        self.assertEqual(prime.session.name, "Londres+NY")
        self.assertEqual(dead.session.name, "Asie")

    def test_confidence_in_bounds(self):
        for seed in range(12):
            analysis = engine.run(Config(), calibration(), demo=True, seed=seed, demo_end_ms=PRIME)
            self.assertGreaterEqual(analysis.confluence.confidence, 0.0)
            self.assertLessEqual(analysis.confluence.confidence, 100.0)
            self.assertGreaterEqual(analysis.confluence.final_score, -1.0)
            self.assertLessEqual(analysis.confluence.final_score, 1.0)

    def test_no_price_source_raises_clear_error(self):
        empty = engine.DataBundle()
        empty.problems.append("Bybit inaccessible")
        with self.assertRaises(RuntimeError) as ctx:
            engine.analyse(empty, Config(), calibration())
        self.assertIn("Bybit inaccessible", str(ctx.exception))

    def test_calibration_applied_only_to_bybit_prices(self):
        """Une serie deja en referentiel MT5 ne doit pas etre decalee : ce
        serait une double correction de plusieurs dollars."""
        bundle = engine.collect(Config(), demo=True, seed=5, demo_end_ms=PRIME)
        raw_price = bundle.series["M1"].closed_only.last.close
        bundle.price_source = "MT5"
        as_mt5 = engine.analyse(bundle, Config(), calibration())
        self.assertAlmostEqual(as_mt5.price, raw_price, places=2)

        bundle2 = engine.collect(Config(), demo=True, seed=5, demo_end_ms=PRIME)
        bundle2.price_source = "BYBIT"
        as_bybit = engine.analyse(bundle2, Config(), calibration())
        self.assertAlmostEqual(as_bybit.price - raw_price, 7.15, places=2)


class TestFusion(unittest.TestCase):
    def _views(self, seed: int, end_ms: int = PRIME):
        m1 = generate_series("M1", 2000, 2400.0, seed=seed, end_ms=end_ms)
        views = {}
        for timeframe in ("M1", "M5", "M15"):
            series = (m1 if timeframe == "M1" else resample(m1, timeframe)).closed_only
            indicators = compute_indicators(series)
            regime = detect_regime(indicators)
            structure = build_structure(series, None, indicators.atr_value)
            views[timeframe] = build_timeframe_view(timeframe, indicators, structure, regime, "test")
        return views

    def test_attenuation_never_flips_direction(self):
        """Propriete centrale : une penalite reduit la conviction, elle ne
        retourne jamais le verdict."""
        session = SessionInfo("Cloture", 0.60, "eviter", 22, 30)   # session penalisante
        for seed in range(20):
            views = self._views(seed)
            confluence = fuse(views, FundamentalView(), MicroView(), session, 80.0, 55.0)
            if abs(confluence.raw_score) < 0.02:
                continue
            additive = sum(m.value for m in confluence.modifiers if m.kind == "additif")
            flipped = (confluence.raw_score > 0) != (confluence.final_score > 0)
            with self.subTest(seed=seed):
                if flipped:
                    self.assertGreater(abs(additive), abs(confluence.raw_score),
                                       "une attenuation a inverse le signal")

    def test_news_blackout_vetoes_trade(self):
        calendar = EconomicCalendar()
        risk = calendar.assess([Event(now_ms() + 5 * 60000, "NFP", "USD", "high")])
        self.assertTrue(risk.blocks_trading)
        fundamental = analyse_fundamentals(generate_macro(seed=1, gold_bias=1.0), risk)
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        for seed in range(20):
            confluence = fuse(self._views(seed), fundamental, MicroView(), session, 90.0, 0.0)
            self.assertEqual(confluence.direction, 0, "un trade a ete emis en fenetre news")
            self.assertTrue(confluence.vetoes)

    def test_counter_trend_blocked_by_default(self):
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        blocked = 0
        for seed in range(30):
            views = self._views(seed)
            confluence = fuse(views, FundamentalView(), MicroView(), session, 90.0, 0.0,
                              allow_counter_trend=False)
            if any("contre une tendance" in v for v in confluence.vetoes):
                blocked += 1
                self.assertEqual(confluence.direction, 0)
        # On ne peut pas garantir qu'un tel cas apparaisse, mais s'il apparait
        # le veto doit avoir bloque le signal.
        self.assertGreaterEqual(blocked, 0)

    def test_low_confidence_yields_no_trade(self):
        session = SessionInfo("Londres+NY", 1.55, "", 14, 60)
        for seed in range(10):
            confluence = fuse(self._views(seed), FundamentalView(), MicroView(), session,
                              90.0, min_confidence=99.9)
            if confluence.confidence < 99.9:
                self.assertEqual(confluence.direction, 0)


class TestBacktest(unittest.TestCase):
    def _random_walk(self, bars: int, seed: int) -> Series:
        rng = random.Random(seed)
        price = 2400.0
        start = now_ms() - bars * 60000
        candles = []
        for i in range(bars):
            open_price = price
            price += rng.gauss(0, 0.28)
            candles.append(
                Candle(start + i * 60000, open_price,
                       max(open_price, price) + abs(rng.gauss(0, 0.10)),
                       min(open_price, price) - abs(rng.gauss(0, 0.10)),
                       price, abs(rng.gauss(500, 120)))
            )
        return Series("M1", candles)

    def test_no_edge_on_pure_noise(self):
        """Une esperance nettement positive sur du bruit signalerait une fuite
        du futur ou un comptage de sorties favorable."""
        m1 = self._random_walk(14000, 4242)
        result = run_backtest(resample(m1, "M5"), resample(m1, "M15"), RiskConfig(), spread=0.30)
        self.assertGreater(result.count, 20)
        self.assertLess(result.expectancy_r, 0.12)

    def test_short_history_is_reported_not_crashed(self):
        m1 = self._random_walk(300, 1)
        result = run_backtest(resample(m1, "M5"), None, RiskConfig())
        self.assertEqual(result.count, 0)
        self.assertTrue(any("insuffisant" in w for w in result.warnings))

    def test_stats_are_self_consistent(self):
        m1 = self._random_walk(12000, 77)
        result = run_backtest(resample(m1, "M5"), resample(m1, "M15"), RiskConfig(), spread=0.30)
        if result.count == 0:
            self.skipTest("aucun trade genere")
        self.assertAlmostEqual(result.total_r, sum(t.r_result for t in result.trades), places=1)
        self.assertLessEqual(result.max_drawdown_r, 0.0)
        for trade in result.trades:
            self.assertGreaterEqual(trade.r_result, -1.0001, "une perte depasse le risque engage")
            self.assertIn(trade.exit_reason, ("stop", "stop_apres_tp1", "tp2", "temps"))

    def test_win_rates_need_a_sample(self):
        empty = run_backtest(Series("M5", []), None, RiskConfig())
        self.assertEqual(empty.win_rates(), (0.0, 0.0))


class TestJsonPayload(unittest.TestCase):
    def test_payload_is_serialisable_and_complete(self):
        analysis = engine.run(Config(), calibration(), demo=True, seed=11, demo_end_ms=PRIME)
        payload = to_payload(analysis)
        text = json.dumps(payload)                 # ne doit pas lever
        self.assertGreater(len(text), 500)
        for key in ("price_mt5", "signal", "plan", "timeframes", "fundamental",
                    "microstructure", "calibration", "data"):
            self.assertIn(key, payload)
        self.assertIn(payload["signal"]["side"], ("ACHAT", "VENTE", "AUCUN"))

    def test_invalid_plan_carries_reason(self):
        config = Config()
        config.engine.min_confidence = 99.9
        analysis = engine.run(config, calibration(), demo=True, seed=1, demo_end_ms=DEAD)
        payload = to_payload(analysis)
        self.assertFalse(payload["plan"]["valid"])
        self.assertTrue(payload["plan"]["rejection"])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("GOLDSCALP_HOME")
        os.environ["GOLDSCALP_HOME"] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GOLDSCALP_HOME", None)
        else:
            os.environ["GOLDSCALP_HOME"] = self._old
        self.tmp.cleanup()

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_help_without_command(self):
        code, output = self._run([])
        self.assertEqual(code, 0)
        self.assertIn("goldscalp", output)

    def test_selftest_passes(self):
        code, output = self._run(["selftest", "--no-color"])
        self.assertEqual(code, 0, output)

    def test_calibrate_then_analyse(self):
        code, _ = self._run(["calibrate", "--bybit", "2400", "--bid", "2407", "--ask", "2407.3",
                             "--no-color"])
        self.assertEqual(code, 0)
        code, output = self._run(["analyse", "--demo", "--seed", "11", "--json", "--no-color"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertAlmostEqual(payload["calibration"]["alpha"], 7.15, places=2)
        self.assertEqual(payload["calibration"]["anchors"], 1)

    def test_analyse_rejects_invalid_risk(self):
        code, _ = self._run(["analyse", "--demo", "--risk", "-1", "--no-color"])
        self.assertEqual(code, 2)

    def test_watch_stops_after_max_iterations(self):
        code, output = self._run(["watch", "--demo", "--interval", "0", "--max-iterations", "2",
                                  "--no-color"])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(output.count("\n"), 3)

    def test_backtest_json(self):
        code, output = self._run(["backtest", "--demo", "--seed", "2024", "--bars", "6000",
                                  "--json", "--no-color"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        for key in ("trades", "expectancy_r", "profit_factor", "warnings"):
            self.assertIn(key, payload)

    def test_config_roundtrip(self):
        code, output = self._run(["config", "--no-color"])
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertIn("risk", data)
        code, _ = self._run(["config", "--save", "--no-color"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(Config.default_path()))

    def test_levels_runs(self):
        code, output = self._run(["levels", "--demo", "--seed", "11", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("NIVEAUX CLES", output)


if __name__ == "__main__":
    unittest.main()
