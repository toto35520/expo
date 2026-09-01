"""Tests de la source de repli Yahoo et de la chaîne de sélection des sources.

Le réseau n'est pas sollicité : on injecte des réponses conformes au format
réel de l'API chart v8, y compris ses pièges (valeurs nulles, volumes absents,
tableaux de longueurs inégales).
"""

from __future__ import annotations

import unittest
from typing import Any

from goldscalp import engine
from goldscalp.config import Config
from goldscalp.core.calibration import Calibration, add_anchor
from goldscalp.data import yahoo as yh
from goldscalp.util import now_ms


def chart_payload(bars: int = 400, step_s: int = 900, start: float = 2400.0,
                  with_volume: bool = True, holes: bool = False) -> dict[str, Any]:
    """Réponse Yahoo synthétique au format exact de l'API chart v8."""
    now = now_ms() // 1000
    first = now - bars * step_s
    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    price = start
    for i in range(bars):
        price += (i % 7 - 3) * 0.25
        timestamps.append(first + i * step_s)
        if holes and i % 37 == 0:
            # Yahoo laisse des créneaux nuls quand rien ne s'est traité.
            opens.append(None); highs.append(None); lows.append(None); closes.append(None)
            volumes.append(None)
            continue
        opens.append(price)
        highs.append(price + 0.6)
        lows.append(price - 0.6)
        closes.append(price + 0.1)
        volumes.append(1500.0 + i if with_volume else None)
    return {
        "meta": {"symbol": "XAUUSD=X", "regularMarketPrice": closes[-1] or start},
        "timestamp": timestamps,
        "indicators": {"quote": [{"open": opens, "high": highs, "low": lows,
                                  "close": closes, "volume": volumes}]},
    }


class FakeHttp:
    """Substitut d'Http qui rejoue des réponses préparées."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url: str, params=None, headers=None):  # type: ignore[no-untyped-def]
        self.calls.append((url, params or {}))
        if self.error:
            raise self.error
        return {"chart": {"result": [self.payload], "error": None}}


class TestYahooParsing(unittest.TestCase):
    def test_parses_candles(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(300)))
        instrument = yh.YahooInstrument("XAUUSD=X", "test", True)
        series = client.klines(instrument, "M15", 1000)
        self.assertGreater(len(series), 250)
        self.assertEqual(series.timeframe, "M15")
        for candle in series:
            self.assertGreaterEqual(candle.high, candle.low)
            self.assertGreaterEqual(candle.high, candle.open)
            self.assertLessEqual(candle.low, candle.open)

    def test_timestamps_converted_to_milliseconds(self):
        payload = chart_payload(120)
        client = yh.YahooGoldClient(http=FakeHttp(payload))
        series = client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M15", 500)
        self.assertEqual(series[0].ts, payload["timestamp"][0] * 1000)

    def test_null_slots_are_dropped_not_zeroed(self):
        """Un créneau nul doit disparaître, jamais devenir un prix à zéro :
        une bougie à 0 $ détruirait tous les indicateurs en aval."""
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(300, holes=True)))
        series = client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M15", 1000)
        self.assertTrue(all(candle.close > 100 for candle in series))
        self.assertLess(len(series), 300)

    def test_last_candle_marked_open(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(200)))
        series = client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M15", 500)
        self.assertFalse(series[-1].closed)
        self.assertTrue(series[-2].closed)

    def test_missing_volume_becomes_zero(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(200, with_volume=False)))
        series = client.klines(yh.YahooInstrument("XAUUSD=X", "", False), "M15", 500)
        self.assertTrue(all(candle.volume == 0.0 for candle in series))
        self.assertFalse(yh.has_usable_volume(series))

    def test_volume_detected_when_present(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(200, with_volume=True)))
        series = client.klines(yh.YahooInstrument("GC=F", "", True), "M15", 500)
        self.assertTrue(yh.has_usable_volume(series))

    def test_unknown_timeframe_rejected(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(50)))
        with self.assertRaises(yh.YahooError):
            client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M2", 100)

    def test_interval_and_range_match_timeframe(self):
        http = FakeHttp(chart_payload(50))
        client = yh.YahooGoldClient(http=http)
        client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M1", 100)
        _, params = http.calls[-1]
        # Yahoo plafonne la granularité 1 minute à 7 jours d'historique.
        self.assertEqual(params["interval"], "1m")
        self.assertIn(params["range"], ("5d", "7d"))


class TestYahooResilience(unittest.TestCase):
    def test_circuit_breaker_opens_on_transport_failure(self):
        client = yh.YahooGoldClient(http=FakeHttp(error=OSError("réseau coupé")))
        with self.assertRaises(yh.YahooError):
            client.resolve_instrument()
        self.assertTrue(client.offline)
        # Le deuxième appel doit échouer immédiatement, sans retenter le réseau.
        before = len(client.http.calls)  # type: ignore[attr-defined]
        with self.assertRaises(yh.YahooError):
            client.klines(yh.YahooInstrument("XAUUSD=X", "", True), "M5", 100)
        self.assertEqual(len(client.http.calls), before)  # type: ignore[attr-defined]

    def test_short_series_is_rejected_during_resolution(self):
        client = yh.YahooGoldClient(http=FakeHttp(chart_payload(5)))
        with self.assertRaises(yh.YahooError):
            client.resolve_instrument()

    def test_explicit_symbol_is_honoured(self):
        http = FakeHttp(chart_payload(200))
        client = yh.YahooGoldClient(http=http)
        instrument = client.resolve_instrument("GC=F")
        self.assertEqual(instrument.symbol, "GC=F")
        self.assertIn("GC=F", http.calls[0][0])


class TestSourceChain(unittest.TestCase):
    """Bybit géo-bloqué doit basculer sur Yahoo, pas faire échouer l'analyse."""

    def setUp(self):
        self.original_bybit = engine.BybitClient
        self.original_yahoo = engine.YahooGoldClient

    def tearDown(self):
        engine.BybitClient = self.original_bybit
        engine.YahooGoldClient = self.original_yahoo

    def _break_bybit(self):
        from goldscalp.data.bybit import BybitError

        class DeadBybit:
            def __init__(self, *a, **k):
                self.offline = True

            def resolve_instrument(self, *a, **k):
                raise BybitError(
                    "HTTP 403 : The Amazon CloudFront distribution is configured "
                    "to block access from your country"
                )

        engine.BybitClient = DeadBybit

    def _serve_yahoo(self):
        class LiveYahoo:
            def __init__(self, *a, **k):
                self.offline = False

            def resolve_instrument(self, symbol=None):
                return yh.YahooInstrument(symbol or "XAUUSD=X", "or spot", False)

            def klines(self, instrument, timeframe, bars=1000):
                step = {"M1": 60, "M5": 300, "M15": 900, "D1": 86400}[timeframe]
                count = {"M1": 900, "M5": 700, "M15": 500, "D1": 120}[timeframe]
                client = yh.YahooGoldClient(
                    http=FakeHttp(chart_payload(count, step_s=step, with_volume=False))
                )
                return client.klines(instrument, timeframe, bars)

        engine.YahooGoldClient = LiveYahoo

    def test_falls_back_to_yahoo_when_bybit_blocked(self):
        self._break_bybit()
        self._serve_yahoo()
        bundle = engine.collect(Config(), prefer_mt5=False)
        self.assertEqual(bundle.price_source, "YAHOO")
        self.assertTrue(bundle.series)
        self.assertTrue(any("CloudFront" in p for p in bundle.problems))
        self.assertTrue(any("volume" in p for p in bundle.problems))

    def test_analysis_completes_on_yahoo_data(self):
        self._break_bybit()
        self._serve_yahoo()
        config = Config()
        calibration = add_anchor(Calibration(), 2400.0, 2400.35, 2400.65)
        analysis = engine.analyse(
            engine.collect(config, prefer_mt5=False), config, calibration
        )
        self.assertEqual(analysis.data.price_source, "YAHOO")
        self.assertGreater(analysis.price, 100)
        self.assertEqual(set(analysis.confluence.views), {"M1", "M5", "M15"})

    def test_yahoo_prices_are_recalibrated(self):
        """Une série Yahoo doit subir le recalage broker, comme une série Bybit."""
        self._break_bybit()
        self._serve_yahoo()
        config = Config()
        bundle = engine.collect(config, prefer_mt5=False)
        raw = bundle.series["M1"].closed_only.last.close
        calibration = add_anchor(Calibration(), 2400.0, 2404.85, 2405.15)
        analysis = engine.analyse(bundle, config, calibration)
        self.assertAlmostEqual(analysis.price - raw, 5.0, places=2)

    def test_fallback_can_be_disabled(self):
        self._break_bybit()
        self._serve_yahoo()
        config = Config()
        config.engine.use_yahoo_fallback = False
        bundle = engine.collect(config, prefer_mt5=False)
        self.assertEqual(bundle.price_source, "?")
        self.assertFalse(bundle.series)

    def test_clear_error_when_every_source_fails(self):
        self._break_bybit()

        class DeadYahoo:
            def __init__(self, *a, **k):
                self.offline = True

            def resolve_instrument(self, *a, **k):
                raise yh.YahooError("aucun hôte joignable")

        engine.YahooGoldClient = DeadYahoo
        config = Config()
        bundle = engine.collect(config, prefer_mt5=False)
        with self.assertRaises(RuntimeError) as ctx:
            engine.analyse(bundle, config, Calibration())
        message = str(ctx.exception)
        self.assertIn("Bybit", message)
        self.assertIn("Yahoo", message)


if __name__ == "__main__":
    unittest.main()
