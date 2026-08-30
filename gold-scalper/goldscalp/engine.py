"""Pipeline d'analyse : de la donnee brute au plan de trade.

Enchainement :
    donnees (Bybit / MT5 / simulation)
      -> recalibrage vers le referentiel MT5
      -> indicateurs + structure + regime, par timeframe
      -> macro + calendrier + microstructure
      -> fusion multi-timeframe
      -> plan de trade (entree, SL, TP1, TP2, taille)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from goldscalp.config import Config
from goldscalp.core.calibration import Calibration, health as calibration_health
from goldscalp.core.fundamental import FundamentalView, analyse_fundamentals
from goldscalp.core.indicators import compute_indicators
from goldscalp.core.microstructure import MicroView, analyse_derivatives, build_micro
from goldscalp.core.plan import TradePlan, build_plan, rejected_plan
from goldscalp.core.regime import SessionInfo, current_session, detect_regime
from goldscalp.core.scoring import Confluence, TimeframeView, build_timeframe_view, fuse
from goldscalp.core.series import Series, resample
from goldscalp.core.structure import build_structure
from goldscalp.data.bybit import BybitClient, BybitError, Instrument
from goldscalp.data.calendar import EconomicCalendar, NewsRisk
from goldscalp.data.macro import MacroFeed, MacroSeries
from goldscalp.data.mt5 import Mt5Bridge
from goldscalp.util import LOG, now_ms

TF_ROLES = {
    "M15": "contexte - definit le biais",
    "M5": "configuration - qualite du repli et structure",
    "M1": "declencheur - decide l'instant d'entree",
}


@dataclass
class DataBundle:
    """Tout ce qui a ete recupere, avec la tracabilite de chaque source."""

    series: dict[str, Series] = field(default_factory=dict)
    daily: Optional[Series] = None
    micro: MicroView = field(default_factory=MicroView)
    macro: dict[str, MacroSeries] = field(default_factory=dict)
    news: Optional[NewsRisk] = None
    instrument: Optional[Instrument] = None
    price_source: str = "?"
    simulated: bool = False
    fetch_seconds: float = 0.0
    sources: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def bars_total(self) -> int:
        return sum(len(s) for s in self.series.values())


@dataclass
class Analysis:
    ts: int
    price: float
    price_bybit: Optional[float]
    calibration: Calibration
    calibration_level: str
    calibration_problems: list[str]
    session: SessionInfo
    fundamental: FundamentalView
    confluence: Confluence
    plan: TradePlan
    data: DataBundle
    config: Config

    @property
    def has_trade(self) -> bool:
        return self.confluence.direction != 0 and self.plan.valid


# --------------------------------------------------------------------------- #
# Collecte
# --------------------------------------------------------------------------- #

def collect(config: Config, *, demo: bool = False, seed: Optional[int] = None,
            prefer_mt5: bool = True, use_micro: bool = True,
            demo_end_ms: Optional[int] = None) -> DataBundle:
    started = time.time()
    bundle = DataBundle()
    timeframes = list(config.engine.timeframes)

    if demo:
        from goldscalp.data import synthetic

        base_seed = seed if seed is not None else int(time.time()) // 900
        # Les timeframes superieurs sont reechantillonnes depuis le M1 : il en
        # faut assez pour que le M15 dispose de plus de 200 bougies, sinon
        # l'EMA200 du contexte reste indefinie et le biais est ampute.
        needed = max(config.engine.bars.get("M1", 2000), 6000)
        m1 = synthetic.generate_series("M1", needed, 2400.0, seed=base_seed,
                                       end_ms=demo_end_ms)
        bundle.series["M1"] = m1
        for timeframe in timeframes:
            if timeframe != "M1":
                bundle.series[timeframe] = resample(m1, timeframe)
        bundle.daily = resample(m1, "D1")
        price = m1.last.close
        # Le flux doit suivre le prix : dans un vrai marche, un mouvement
        # haussier s'accompagne d'un carnet et d'agressions acheteuses. Un
        # biais fixe, decorrele de l'action des prix, rend la simulation
        # inutilisable pour tester les regles qui croisent prix et flux.
        reference = m1[-20].close if len(m1) > 20 else price
        atr_guess = max(abs(price - reference) / 20.0, price * 0.0002)
        drift = (price - reference) / (atr_guess * 20.0)
        bias = max(-0.8, min(0.8, drift * 0.8))
        bundle.micro = build_micro(
            synthetic.generate_orderbook(price, seed=base_seed, bias=bias * 0.5),
            synthetic.generate_trades(price, 600, seed=base_seed,
                                      buy_ratio=0.5 + bias * 0.22),
            synthetic.generate_derivatives(seed=base_seed, bias=bias),
            price, m1[-30].close if len(m1) > 30 else price,
        )
        bundle.macro = synthetic.generate_macro(seed=base_seed, gold_bias=bias)
        bundle.price_source = "SIMULATION"
        bundle.simulated = True
        bundle.sources = {"prix": "simulateur interne", "macro": "simule", "calendrier": "non consulte"}
        bundle.fetch_seconds = round(time.time() - started, 3)
        return bundle

    # -- MT5 en priorite : c'est le prix ou tu vas reellement executer ------ #
    mt5_series: dict[str, Series] = {}
    if prefer_mt5:
        bridge = Mt5Bridge(config.market.mt5_symbol)
        if bridge.connect():
            try:
                for timeframe in timeframes + ["D1"]:
                    fetched = bridge.candles(timeframe, config.engine.bars.get(timeframe, 1000))
                    if fetched is not None and len(fetched) > 60:
                        mt5_series[timeframe] = fetched
            finally:
                bridge.close()
            if mt5_series:
                LOG.info("bougies MT5 recuperees pour %s", ", ".join(sorted(mt5_series)))

    # -- Bybit : indispensable pour la microstructure et le 24/7 ----------- #
    client = BybitClient()
    instrument: Optional[Instrument] = None
    try:
        instrument = client.resolve_instrument(config.market.bybit_symbol, config.market.bybit_category)
        bundle.instrument = instrument
        LOG.info("marche Bybit retenu : %s (%s)", instrument.symbol, instrument.category)
    except BybitError as exc:
        bundle.problems.append(f"Bybit inaccessible : {exc}")
        LOG.warning("Bybit inaccessible : %s", exc)

    bybit_series: dict[str, Series] = {}
    if instrument is not None and not client.offline:
        for timeframe in timeframes + ["D1"]:
            if client.offline:
                break
            try:
                fetched = client.klines(instrument, timeframe, config.engine.bars.get(timeframe, 1000))
                if len(fetched) > 60:
                    bybit_series[timeframe] = fetched
                else:
                    bundle.problems.append(f"Bybit {timeframe} : seulement {len(fetched)} bougies")
            except BybitError as exc:
                bundle.problems.append(f"Bybit {timeframe} : {exc}")

    # Choix de la source de prix : MT5 s'il couvre tous les timeframes.
    if all(tf in mt5_series for tf in timeframes):
        for timeframe in timeframes:
            bundle.series[timeframe] = mt5_series[timeframe]
        bundle.daily = mt5_series.get("D1") or bybit_series.get("D1")
        bundle.price_source = "MT5"
        bundle.sources["prix"] = f"MT5 {config.market.mt5_symbol} (broker)"
    elif bybit_series:
        for timeframe in timeframes:
            if timeframe in bybit_series:
                bundle.series[timeframe] = bybit_series[timeframe]
        bundle.daily = bybit_series.get("D1")
        bundle.price_source = "BYBIT"
        symbol = instrument.symbol if instrument else "?"
        bundle.sources["prix"] = f"Bybit {symbol} recalibre vers MT5"
    else:
        bundle.problems.append("aucune source de prix disponible")
        bundle.fetch_seconds = round(time.time() - started, 3)
        return bundle

    # Complete les timeframes manquants par reechantillonnage du plus fin.
    if "M1" in bundle.series:
        for timeframe in timeframes:
            if timeframe not in bundle.series:
                bundle.series[timeframe] = resample(bundle.series["M1"], timeframe)
                bundle.sources[timeframe] = "reechantillonne depuis M1"

    # -- microstructure ---------------------------------------------------- #
    if use_micro and instrument is not None and config.engine.use_microstructure:
        book = client.orderbook(instrument)
        trades = client.recent_trades(instrument)
        funding = client.funding_history(instrument)
        open_interest = client.open_interest(instrument)
        reference = bybit_series.get("M1") or bundle.series.get("M1")
        prices = [c.close for c in reference[-30:]] if reference else []
        derivatives = analyse_derivatives(funding, open_interest, prices)
        bundle.micro = build_micro(
            book, trades, derivatives,
            prices[-1] if prices else None,
            prices[0] if prices else None,
        )
        bundle.sources["microstructure"] = (
            f"Bybit carnet({len(book.bids) if book else 0} niveaux) "
            f"+ {len(trades)} trades + funding/OI"
        )
    elif not config.engine.use_microstructure:
        bundle.sources["microstructure"] = "desactivee"

    # -- macro ------------------------------------------------------------- #
    if config.engine.use_macro:
        try:
            bundle.macro = MacroFeed().fetch()
            if bundle.macro:
                first = next(iter(bundle.macro.values()))
                bundle.sources["macro"] = f"{len(bundle.macro)} series ({first.source})"
            else:
                bundle.problems.append("aucune serie macro disponible")
        except Exception as exc:
            bundle.problems.append(f"macro indisponible : {exc}")
    else:
        bundle.sources["macro"] = "desactivee"

    # -- calendrier -------------------------------------------------------- #
    if config.engine.use_calendar:
        calendar = EconomicCalendar()
        try:
            events = calendar.fetch()
            bundle.news = calendar.assess(
                events,
                config.engine.news_block_before_min,
                config.engine.news_block_after_min,
                config.engine.news_caution_min,
            )
            bundle.sources["calendrier"] = (
                f"{len(events)} evenements ({'repli embarque' if calendar.is_estimated else 'ForexFactory'})"
            )
        except Exception as exc:
            bundle.problems.append(f"calendrier indisponible : {exc}")
    else:
        bundle.sources["calendrier"] = "desactive"

    bundle.fetch_seconds = round(time.time() - started, 3)
    return bundle


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #

def analyse(bundle: DataBundle, config: Config, calibration: Calibration,
            spread_override: Optional[float] = None) -> Analysis:
    if not bundle.series:
        raise RuntimeError(
            "Aucune serie de prix : "
            + ("; ".join(bundle.problems) if bundle.problems else "sources injoignables")
        )

    # Recalibrage : uniquement si le prix vient de Bybit. Une serie MT5 est
    # deja dans le bon referentiel, la recaler serait une double correction.
    needs_shift = bundle.price_source == "BYBIT"
    price_bybit: Optional[float] = None

    views: dict[str, TimeframeView] = {}
    daily = bundle.daily
    if needs_shift and daily is not None:
        daily = calibration.apply(daily)

    for timeframe in config.engine.timeframes:
        series = bundle.series.get(timeframe)
        if series is None or len(series) < 60:
            LOG.warning("timeframe %s ignore (%d bougies)", timeframe, len(series) if series else 0)
            continue
        if timeframe == "M1" and series:
            price_bybit = series.last.close
        working = calibration.apply(series) if needs_shift else series
        closed = working.closed_only
        if len(closed) < 60:
            continue

        indicators = compute_indicators(closed)
        regime = detect_regime(indicators)
        structure = build_structure(
            closed, daily, indicators.atr_value,
            config.engine.swing_span.get(timeframe, 3),
        )
        views[timeframe] = build_timeframe_view(
            timeframe, indicators, structure, regime, TF_ROLES.get(timeframe, timeframe)
        )

    if not views:
        raise RuntimeError("aucun timeframe ne dispose d'assez de bougies pour etre analyse")

    reference = views.get("M1") or next(iter(views.values()))
    price = reference.indicators.price
    # En simulation, la session doit suivre l'horodatage des bougies, sinon on
    # analyse un marche de 14h avec les regles de la session de 22h.
    session = current_session(reference.indicators.series.last.ts if bundle.simulated else now_ms())

    fundamental = analyse_fundamentals(bundle.macro, bundle.news)
    level, problems = calibration_health(calibration)

    confluence = fuse(
        views, fundamental, bundle.micro, session,
        calibration.quality(),
        config.engine.min_confidence,
        config.engine.allow_counter_trend,
    )

    news_multiplier = bundle.news.size_multiplier if bundle.news else 1.0
    if confluence.direction != 0:
        plan = build_plan(
            confluence, calibration, config.risk, config.market, session,
            news_multiplier, spread_override,
        )
    else:
        reason = (
            "; ".join(confluence.vetoes)
            if confluence.vetoes
            else f"confiance {confluence.confidence:.0f}/100 sous le seuil de {config.engine.min_confidence:.0f}"
        )
        plan = rejected_plan(reason)

    return Analysis(
        ts=now_ms(),
        price=price,
        price_bybit=price_bybit,
        calibration=calibration,
        calibration_level=level,
        calibration_problems=problems,
        session=session,
        fundamental=fundamental,
        confluence=confluence,
        plan=plan,
        data=bundle,
        config=config,
    )


def run(config: Config, calibration: Calibration, *, demo: bool = False,
        seed: Optional[int] = None, prefer_mt5: bool = True,
        spread_override: Optional[float] = None,
        demo_end_ms: Optional[int] = None) -> Analysis:
    bundle = collect(config, demo=demo, seed=seed, prefer_mt5=prefer_mt5,
                     demo_end_ms=demo_end_ms)
    return analyse(bundle, config, calibration, spread_override)
