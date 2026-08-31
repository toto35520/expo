"""Tests de l'analyse d'exécution scalp et du portillon turbo."""

from __future__ import annotations

import unittest

from goldscalp import engine
from goldscalp.config import Config
from goldscalp.core.calibration import Calibration, add_anchor
from goldscalp.core.indicators import compute_indicators
from goldscalp.core.fundamental import FundamentalView
from goldscalp.core.microstructure import FlowStats, MicroView
from goldscalp.core.regime import SessionInfo, detect_regime
from goldscalp.core.scoring import build_timeframe_view, fuse
from goldscalp.core.scalp import MAX_SPREAD_SHARE, ScalpView, analyse_scalp, _opening_window
from goldscalp.core.series import Candle, Series, resample
from goldscalp.core.structure import Level, StructureView, build_structure
from goldscalp.data.synthetic import generate_series
from goldscalp.util import now_ms

DAY = (now_ms() // 86_400_000) * 86_400_000
PRIME = SessionInfo("Londres+NY", 1.55, "", 14, 90)
DEAD = SessionInfo("Cloture", 0.60, "éviter", 22, 90)


def context(seed: int = 3, bars: int = 2000, hour: int = 14):
    m1 = generate_series("M1", bars, 2400.0, seed=seed, end_ms=DAY + hour * 3_600_000).closed_only
    m5 = resample(m1, "M5").closed_only
    ind1, ind5 = compute_indicators(m1), compute_indicators(m5)
    structure = build_structure(m5, None, ind5.atr_value)
    return ind1, ind5, structure


class TestScalpChecks(unittest.TestCase):
    def test_no_direction_yields_empty_view(self):
        ind1, ind5, structure = context()
        view = analyse_scalp(0, ind1, ind5, structure, PRIME, 0.30)
        self.assertEqual(view.checks, [])
        self.assertFalse(view.turbo_ready)
        self.assertIn("aucune direction", view.verdict)

    def test_every_check_is_produced(self):
        ind1, ind5, structure = context()
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        self.assertEqual(len(view.checks), 11)
        self.assertTrue(all(check.detail for check in view.checks))
        self.assertGreaterEqual(view.score, 0.0)
        self.assertLessEqual(view.score, 1.0)

    def test_wide_spread_blocks_execution(self):
        """Le contrôle économique du scalp : un spread qui mange la cible rend
        le trade perdant par construction, quelle que soit la direction."""
        ind1, ind5, structure = context()
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, spread=3.0)
        blocker_names = [c.name for c in view.blockers]
        self.assertIn("coût du spread", blocker_names)
        self.assertFalse(view.turbo_ready)
        self.assertGreater(view.spread_share, MAX_SPREAD_SHARE)

    def test_tight_spread_passes(self):
        ind1, ind5, structure = context()
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, spread=0.20)
        spread_check = next(c for c in view.checks if c.name == "coût du spread")
        self.assertTrue(spread_check.passed)

    def test_wall_in_front_blocks_execution(self):
        """Entrer collé sous une résistance solide n'est pas un scalp."""
        ind1, ind5, structure = context()
        price = ind1.series.last.close
        structure.levels = [Level(price=price + 0.05, kind="resistance", strength=0.95,
                                  touches=6, label="mur")]
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        self.assertIn("espace disponible", [c.name for c in view.blockers])

    def test_weak_level_is_not_treated_as_an_obstacle(self):
        """Un chiffre rond touché une fois ne défend rien : le compter comme
        obstacle rendrait tout scalp impossible."""
        ind1, ind5, structure = context()
        price = ind1.series.last.close
        structure.levels = [Level(price=price + 0.05, kind="round", strength=0.25,
                                  touches=1, label="rond")]
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        self.assertNotIn("espace disponible", [c.name for c in view.blockers])

    def test_dead_session_fails_the_window_check(self):
        ind1, ind5, structure = context()
        good = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        poor = analyse_scalp(1, ind1, ind5, structure, DEAD, 0.30)
        self.assertLess(poor.score, good.score)

    def test_imminent_session_change_is_flagged(self):
        ind1, ind5, structure = context()
        soon = SessionInfo("Londres+NY", 1.55, "", 14, 3)
        view = analyse_scalp(1, ind1, ind5, structure, soon, 0.30)
        check = next(c for c in view.checks if c.name == "stabilité de session")
        self.assertFalse(check.passed)

    def test_chasing_is_detected(self):
        """Cinq bougies d'impulsion déjà parcourues : entrer maintenant, c'est
        courir après le mouvement."""
        ind1, ind5, structure = context()
        candles = list(ind1.series.candles)
        price = candles[-6].close
        for offset in range(5):
            price += 2.0
            candles[-5 + offset] = Candle(candles[-5 + offset].ts, price - 2.0,
                                          price + 0.1, price - 2.1, price, 500)
        ind1.series.candles = candles
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        self.assertGreaterEqual(view.chase_bars, 4)
        self.assertFalse(next(c for c in view.checks if c.name == "entrée non tardive").passed)

    def test_rejection_wick_is_detected(self):
        ind1, ind5, structure = context()
        last = ind1.series.candles[-1]
        # Bougie à longue mèche haute : le marché a repoussé les acheteurs.
        ind1.series.candles[-1] = Candle(last.ts, last.close, last.close + 6.0,
                                         last.close - 0.2, last.close + 0.1, 500)
        view = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.30)
        self.assertFalse(next(c for c in view.checks if c.name == "absence de rejet").passed)

    def test_opening_windows(self):
        self.assertIn("Londres", _opening_window(DAY + 7 * 3_600_000 + 10 * 60_000))
        self.assertIn("New York", _opening_window(DAY + 12 * 3_600_000 + 40 * 60_000))
        self.assertEqual(_opening_window(DAY + 3 * 3_600_000), "")

    def test_score_reflects_failures(self):
        ind1, ind5, structure = context()
        clean = analyse_scalp(1, ind1, ind5, structure, PRIME, 0.20)
        crippled = analyse_scalp(1, ind1, ind5, structure, DEAD, 2.5)
        self.assertLess(crippled.score, clean.score)
        self.assertIn("refusée", crippled.verdict)


class TestTurboGate(unittest.TestCase):
    """La porte turbo est testée par CONSTRUCTION, pas par échantillonnage.

    Chercher un turbo dans des données aléatoires ne prouve rien quand il
    n'apparaît pas : on ne sait pas distinguer « la règle est trop stricte »
    de « l'échantillon ne contenait pas le cas ». On fabrique donc la
    situation, puis on retire une condition à la fois.
    """

    _views: dict = {}

    @classmethod
    def setUpClass(cls):
        for bias in (4.0, -4.0):
            m1 = generate_series("M1", 6000, 2400.0, seed=1,
                                 end_ms=DAY + 14 * 3_600_000, trend_bias=bias)
            views = {}
            for timeframe in ("M1", "M5", "M15"):
                series = (m1 if timeframe == "M1" else resample(m1, timeframe)).closed_only
                indicators = compute_indicators(series)
                regime = detect_regime(indicators)
                views[timeframe] = build_timeframe_view(
                    timeframe, indicators, build_structure(series, None, indicators.atr_value),
                    regime, "test",
                )
            cls._views[bias] = views

    @staticmethod
    def _micro(direction: int) -> MicroView:
        ratio = 0.78 if direction > 0 else 0.22
        sign = 1.0 if direction > 0 else -1.0
        return MicroView(
            flow=FlowStats(buy_ratio=ratio, cvd_slope=0.6 * sign, large_trade_bias=0.5 * sign),
            imbalance=0.55 * sign,
        )

    def _fuse(self, bias: float = 4.0, session: SessionInfo = PRIME,
              micro: MicroView | None = None, turbo_confidence: float = 78.0):
        direction = 1 if bias > 0 else -1
        return fuse(self._views[bias], FundamentalView(),
                    micro if micro is not None else self._micro(direction),
                    session, 90.0, 55.0, False, turbo_confidence)

    # -- la porte s'ouvre quand tout est réuni ------------------------------ #
    def test_turbo_fires_when_every_condition_holds(self):
        for bias in (4.0, -4.0):
            with self.subTest(sens="achat" if bias > 0 else "vente"):
                confluence = self._fuse(bias)
                self.assertTrue(confluence.turbo, confluence.turbo_blockers)
                self.assertGreaterEqual(len(confluence.turbo_reasons), 3)
                self.assertEqual(confluence.turbo_blockers, [])

    # -- et se referme dès qu'une condition tombe --------------------------- #
    def test_poor_session_refuses_turbo(self):
        confluence = self._fuse(session=DEAD)
        self.assertFalse(confluence.turbo)
        self.assertTrue(any("liquide" in b for b in confluence.turbo_blockers))

    def test_confidence_below_threshold_refuses_turbo(self):
        confluence = self._fuse(turbo_confidence=99.9)
        self.assertFalse(confluence.turbo)
        self.assertTrue(any("seuil turbo" in b for b in confluence.turbo_blockers))

    def test_contradicting_flow_costs_a_corroborator(self):
        """Un flux qui va contre le signal ne bloque pas seul, mais retire un
        facteur corroborant : c'est exactement la nuance recherchée."""
        with_flow = self._fuse()
        against = self._fuse(micro=self._micro(-1))
        self.assertIn("flux confirmant le sens", with_flow.turbo_reasons)
        self.assertIn("flux confirmant le sens", against.turbo_blockers)

    def test_neutral_flow_alone_does_not_kill_turbo(self):
        """Trois corroborants sur quatre suffisent : un flux muet ne doit pas
        annuler une configuration par ailleurs parfaite."""
        confluence = self._fuse(micro=MicroView())
        self.assertNotIn("flux confirmant le sens", confluence.turbo_reasons)
        self.assertTrue(confluence.turbo)

    def test_refusal_is_always_explained(self):
        confluence = self._fuse(session=DEAD)
        self.assertTrue(confluence.turbo_blockers)
        self.assertTrue(all(isinstance(b, str) and b for b in confluence.turbo_blockers))

    # -- intégration : le turbo reste rare et toujours exécutable ------------ #
    def test_turbo_never_fires_without_an_executable_setup(self):
        config = Config()
        calibration = add_anchor(Calibration(), 2400.0, 2407.10, 2407.40)
        signals = turbo = 0
        for seed in range(25):
            analysis = engine.run(config, calibration, demo=True, seed=seed,
                                  demo_end_ms=DAY + 14 * 3_600_000)
            if not analysis.confluence.direction:
                continue
            signals += 1
            if analysis.confluence.turbo:
                turbo += 1
                self.assertTrue(analysis.scalp.turbo_ready)
                self.assertEqual(analysis.scalp.blockers, [])
                if analysis.plan.valid:
                    atr1 = analysis.confluence.views["M1"].indicators.atr_value
                    self.assertLessEqual(analysis.plan.stop_distance, atr1 * 1.7 + 0.05)
                    self.assertEqual(analysis.plan.entry_type, "marché")
        self.assertGreater(signals, 5)
        self.assertLess(turbo / signals, 0.5, "le mode turbo se déclenche trop souvent")

    def test_scalp_view_attached_to_every_signal(self):
        config = Config()
        calibration = add_anchor(Calibration(), 2400.0, 2407.10, 2407.40)
        for seed in range(12):
            analysis = engine.run(config, calibration, demo=True, seed=seed,
                                  demo_end_ms=DAY + 14 * 3_600_000)
            if analysis.confluence.direction:
                self.assertIsInstance(analysis.scalp, ScalpView)
                self.assertEqual(len(analysis.scalp.checks), 11)
                return


if __name__ == "__main__":
    unittest.main()
