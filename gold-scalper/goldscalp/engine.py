"""Pipeline d'analyse : de la donnee brute au plan de trade.

Enchainement :
    données (Bybit / MT5 / simulation)
      -> recalibrage vers le référentiel MT5
      -> indicateurs + structure + régime, par timeframe
      -> macro + calendrier + microstructure
      -> fusion multi-timeframe
      -> plan de trade (entrée, SL, TP1, TP2, taille)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from goldscalp.config import Config
from goldscalp.core.basis import Basis, best_common_timeframe, estimate_basis
from goldscalp.core.calibration import Calibration, add_anchor, health as calibration_health
from goldscalp.core.fundamental import FundamentalView, analyse_fundamentals
from goldscalp.core.indicators import compute_indicators
from goldscalp.core.microstructure import MicroView, analyse_derivatives, build_micro
from goldscalp.core.plan import TradePlan, build_plan, rejected_plan
from goldscalp.core.regime import SessionInfo, current_session, detect_regime
from goldscalp.core.scalp import ScalpView, analyse_scalp
from goldscalp.core.scoring import Confluence, TimeframeView, build_timeframe_view, fuse
from goldscalp.core.series import Series, resample
from goldscalp.core.structure import build_structure
from goldscalp.data.bybit import BybitClient, BybitError, Instrument
from goldscalp.data.calendar import EconomicCalendar, NewsRisk
from goldscalp.data.macro import MacroFeed, MacroSeries
from goldscalp.data.mt5 import Mt5Bridge
from goldscalp.data.yahoo import YahooError, YahooGoldClient, has_usable_volume
from goldscalp.util import LOG, now_ms

TF_ROLES = {
    "M15": "contexte - définit le biais",
    "M5": "configuration - qualité du repli et structure",
    "M1": "déclencheur - décide l'instant d'entrée",
}


@dataclass
class DataBundle:
    """Tout ce qui a été recupere, avec la tracabilite de chaque source."""

    series: dict[str, Series] = field(default_factory=dict)
    daily: Optional[Series] = None
    micro: MicroView = field(default_factory=MicroView)
    macro: dict[str, MacroSeries] = field(default_factory=dict)
    news: Optional[NewsRisk] = None
    instrument: Optional[Instrument] = None
    basis: Basis = field(default_factory=Basis)
    price_source: str = "?"
    simulated: bool = False
    fetch_seconds: float = 0.0
    sources: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def bars_total(self) -> int:
        return sum(len(s) for s in self.series.values())


def _conversion(bundle: "DataBundle", calibration: Calibration):
    """Construit la fonction série -> référentiel broker, et la décrit.

    Renvoie (convertisseur, description de la chaîne, écart résiduel estimé).
    Le résiduel est l'incertitude qui subsiste APRÈS conversion : c'est le
    chiffre qui répond honnêtement à « de combien mes niveaux peuvent-ils être
    faux ? ».
    """
    source = bundle.price_source
    basis = bundle.basis

    if source == "MT5":
        return (lambda series: series), "aucune (série broker directe)", 0.0

    if not calibration.anchors:
        return (
            lambda series: series,
            f"AUCUNE — prix {source} bruts, non recalés",
            999.0,
        )

    calibration_error = calibration.residual_std + calibration.half_spread

    # Étape 1 : ramener la source à l'or spot.
    if source == "YAHOO":
        to_spot = lambda series: series                      # noqa: E731 — déjà du spot
        step1 = "Yahoo = or spot"
        basis_error = 0.0
    elif basis.ok:
        to_spot = basis.apply
        step1 = f"Bybit {basis.value:+.2f} $ (base mesurée sur {basis.samples} bougies)"
        basis_error = basis.dispersion
    else:
        # Sans base, on ne peut convertir que si l'ancrage vise déjà Bybit.
        if calibration.reference == "bybit":
            return (
                calibration.apply,
                f"Bybit {calibration.alpha:+.2f} $ (ancrage manuel direct, base non mesurée)",
                round(calibration_error + 2.0, 2),
            )
        return (
            lambda series: series,
            "IMPOSSIBLE — ancrage adossé au spot mais base Bybit→spot non mesurée",
            999.0,
        )

    # Étape 2 : de l'or spot au prix du broker.
    if calibration.reference == "spot":
        spot_to_broker = calibration
    else:
        # L'ancrage a été pris contre Bybit : on le retranscrit en référentiel
        # spot grâce à la base, plutôt que de refuser de l'exploiter.
        if not basis.ok:
            return (calibration.apply, "ancrage direct Bybit", round(calibration_error + 2.0, 2))
        spot_to_broker = Calibration(
            alpha=round(calibration.alpha - basis.value, 6),
            beta=calibration.beta,
            spread=calibration.spread,
            anchors=calibration.anchors,
            residual_std=calibration.residual_std,
            slope_fitted=calibration.slope_fitted,
            reference="spot",
            note="ancrage Bybit retranscrit en référentiel spot",
        )

    step2 = f"spot {spot_to_broker.alpha:+.2f} $ (markup broker)"
    residual = round(basis_error + calibration_error, 2)

    def convert(series):
        return spot_to_broker.apply(to_spot(series))

    return convert, f"{step1} -> {step2}", residual


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
    scalp: ScalpView = field(default_factory=ScalpView)
    # Chaîne de conversion vers le référentiel broker, et incertitude qui
    # subsiste une fois cette conversion faite.
    conversion_chain: str = ""
    residual_error: float = 0.0

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
        # Les timeframes supérieurs sont reechantillonnes depuis le M1 : il en
        # faut assez pour que le M15 dispose de plus de 200 bougies, sinon
        # l'EMA200 du contexte reste indéfinie et le biais est ampute.
        needed = max(config.engine.bars.get("M1", 2000), 6000)
        m1 = synthetic.generate_series("M1", needed, 2400.0, seed=base_seed,
                                       end_ms=demo_end_ms)
        bundle.series["M1"] = m1
        for timeframe in timeframes:
            if timeframe != "M1":
                bundle.series[timeframe] = resample(m1, timeframe)
        bundle.daily = resample(m1, "D1")
        price = m1.last.close
        # Le flux doit suivre le prix : dans un vrai marché, un mouvement
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

        # Base simulée : le mode démo doit exercer la chaîne de conversion
        # complète, sinon la fonctionnalité qui ramène l'écart broker à
        # quelques centimes reste invisible hors ligne.
        premium = 7.25 + (base_seed % 7) * 0.15
        spot_reference = m1.apply_calibration(-premium, 1.0)
        bundle.basis = estimate_basis(m1, spot_reference)
        bundle.sources["base spot"] = f"simulée — {bundle.basis.describe()}"
        bundle.price_source = "SIMULATION"
        bundle.simulated = True
        bundle.sources = {"prix": "simulateur interne", "macro": "simule", "calendrier": "non consulte"}
        bundle.fetch_seconds = round(time.time() - started, 3)
        return bundle

    # -- MT5 en priorité : c'est le prix ou tu vas reellement exécuter ------ #
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
        LOG.info("marché Bybit retenu : %s (%s)", instrument.symbol, instrument.category)
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

    # -- repli Yahoo -------------------------------------------------------- #
    # Bybit filtre par pays au niveau de son CDN : une fonction hébergée aux
    # États-Unis reçoit un 403. Sans seconde source, l'outil serait inutilisable
    # là où il est déployé plutôt que là où l'utilisateur se trouve.
    yahoo_series: dict[str, Series] = {}
    yahoo_instrument = None

    # Référence spot : même quand Bybit répond, on récupère une série d'or spot
    # pour MESURER la base Bybit→spot. C'est ce qui permet de ramener l'écart
    # au prix broker de plusieurs dollars à quelques dizaines de centimes, sans
    # ancrage manuel à répéter toutes les deux heures.
    if bybit_series and config.engine.use_spot_reference:
        reference_client = YahooGoldClient()
        try:
            reference_instrument = reference_client.resolve_instrument(config.market.yahoo_symbol)
            for timeframe in ("M1", "M5"):
                if timeframe not in bybit_series or reference_client.offline:
                    continue
                fetched = reference_client.klines(reference_instrument, timeframe, 400)
                if len(fetched) > 30:
                    yahoo_series[timeframe] = fetched
            timeframe = best_common_timeframe(bybit_series, yahoo_series)
            if timeframe:
                bundle.basis = estimate_basis(bybit_series[timeframe], yahoo_series[timeframe])
                bundle.sources["base spot"] = (
                    f"{reference_instrument.symbol} sur {timeframe} — {bundle.basis.describe()}"
                )
            else:
                bundle.problems.append(
                    "Aucune bougie commune entre Bybit et l'or spot : la base ne peut "
                    "pas être mesurée, le recalage retombe sur l'ancrage manuel."
                )
        except YahooError as exc:
            bundle.problems.append(f"Référence spot indisponible : {exc}")
        yahoo_series = {}      # série de référence, pas série de prix

    if not bybit_series and not mt5_series and config.engine.use_yahoo_fallback:
        yahoo = YahooGoldClient()
        try:
            yahoo_instrument = yahoo.resolve_instrument(config.market.yahoo_symbol)
            LOG.info("repli Yahoo : %s (%s)", yahoo_instrument.symbol, yahoo_instrument.description)
        except YahooError as exc:
            bundle.problems.append(f"Yahoo inaccessible : {exc}")
        if yahoo_instrument is not None:
            for timeframe in timeframes + ["D1"]:
                if yahoo.offline:
                    break
                try:
                    fetched = yahoo.klines(yahoo_instrument, timeframe,
                                           config.engine.bars.get(timeframe, 1000))
                    if len(fetched) > 60:
                        yahoo_series[timeframe] = fetched
                    else:
                        bundle.problems.append(
                            f"Yahoo {timeframe} : seulement {len(fetched)} bougies"
                        )
                except YahooError as exc:
                    bundle.problems.append(f"Yahoo {timeframe} : {exc}")

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
        bundle.sources["prix"] = f"Bybit {symbol} recalibré vers MT5"
    elif yahoo_series:
        for timeframe in timeframes:
            if timeframe in yahoo_series:
                bundle.series[timeframe] = yahoo_series[timeframe]
        bundle.daily = yahoo_series.get("D1")
        bundle.price_source = "YAHOO"
        symbol = yahoo_instrument.symbol if yahoo_instrument else "?"
        bundle.sources["prix"] = f"Yahoo {symbol} recalibré vers MT5"
        reference = bundle.series.get("M5") or next(iter(bundle.series.values()))
        if not has_usable_volume(reference):
            bundle.problems.append(
                "Yahoo ne publie pas de volume sur ce symbole : VWAP, OBV et profil "
                "se rabattent sur une pondération temporelle, et la composante "
                "participation perd de sa valeur."
            )
        if reference and not reference.is_fresh(now_ms(), tolerance_bars=6):
            age_h = (now_ms() - reference.last.ts) / 3_600_000
            bundle.problems.append(
                f"Dernière bougie vieille de {age_h:.1f} h : l'or spot suit les "
                "horaires du forex, fermé du vendredi 22 h au dimanche 22 h UTC."
            )
    else:
        bundle.problems.append(
            "aucune source de prix disponible (MT5, Bybit et Yahoo ont tous échoué)"
        )
        bundle.fetch_seconds = round(time.time() - started, 3)
        return bundle

    # Complete les timeframes manquants par rééchantillonnage du plus fin.
    if "M1" in bundle.series:
        for timeframe in timeframes:
            if timeframe not in bundle.series:
                bundle.series[timeframe] = resample(bundle.series["M1"], timeframe)
                bundle.sources[timeframe] = "rééchantillonné depuis M1"

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
                bundle.sources["macro"] = f"{len(bundle.macro)} séries ({first.source})"
            else:
                bundle.problems.append("aucune série macro disponible")
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
                f"{len(events)} événements ({'repli embarqué' if calendar.is_estimated else 'ForexFactory'})"
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
            "Aucune série de prix : "
            + ("; ".join(bundle.problems) if bundle.problems else "sources injoignables")
        )

    # Conversion vers le référentiel broker, en deux temps explicites :
    #   1. source -> or spot   (base mesurée, automatique)
    #   2. or spot -> broker   (markup, ancrage manuel)
    # Une série MT5 est déjà au bon référentiel : la convertir serait une
    # double correction de plusieurs dollars.
    convert, chain, residual = _conversion(bundle, calibration)
    price_bybit: Optional[float] = None

    views: dict[str, TimeframeView] = {}
    daily = bundle.daily
    if daily is not None:
        daily = convert(daily)

    for timeframe in config.engine.timeframes:
        series = bundle.series.get(timeframe)
        if series is None or len(series) < 60:
            LOG.warning("timeframe %s ignore (%d bougies)", timeframe, len(series) if series else 0)
            continue
        if timeframe == "M1" and series:
            price_bybit = series.last.close
        working = convert(series)
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
    # analyse un marché de 14h avec les regles de la session de 22h.
    session = current_session(reference.indicators.series.last.ts if bundle.simulated else now_ms())

    fundamental = analyse_fundamentals(bundle.macro, bundle.news)
    level, problems = calibration_health(calibration)

    confluence = fuse(
        views, fundamental, bundle.micro, session,
        calibration.quality(),
        config.engine.min_confidence,
        config.engine.allow_counter_trend,
        config.engine.turbo_confidence,
    )

    # -- qualité d'exécution ------------------------------------------------ #
    # La confluence dit OÙ va le marché ; ceci dit si le trade est exécutable
    # MAINTENANT, au prix du scalp. Le turbo exige les deux.
    view_m1 = views.get("M1")
    view_m5 = views.get("M5") or view_m1
    hint = confluence.direction or (
        1 if confluence.final_score > 0 else -1 if confluence.final_score < 0 else 0
    )
    scalp = ScalpView()
    if view_m1 is not None and view_m5 is not None:
        scalp = analyse_scalp(
            hint, view_m1.indicators, view_m5.indicators, view_m5.structure,
            session, calibration.spread, view_m5.regime.target_multiplier,
        )
        if confluence.turbo and not scalp.turbo_ready:
            confluence.turbo = False
            confluence.warnings.append(
                f"Turbo refusé par l'analyse d'exécution ({scalp.score:.0%}) : {scalp.turbo_refusal}"
            )
            confluence.turbo_blockers.append(f"exécution : {scalp.turbo_refusal}")
        for blocker in scalp.blockers:
            if confluence.direction != 0:
                confluence.warnings.append(f"Exécution : {blocker.detail}")

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
        conversion_chain=chain,
        residual_error=residual,
        session=session,
        fundamental=fundamental,
        confluence=confluence,
        plan=plan,
        data=bundle,
        config=config,
        scalp=scalp,
    )


def measure_basis(config: Config) -> Basis:
    """Mesure la base Bybit → or spot, sans lancer d'analyse complète.

    Sert au moment de la calibration : convertir le prix Bybit relevé en son
    équivalent SPOT permet à l'ancrage de mesurer le seul markup du broker,
    donc de rester valable des jours au lieu de quelques heures.
    """
    client = BybitClient()
    try:
        instrument = client.resolve_instrument(config.market.bybit_symbol,
                                               config.market.bybit_category)
    except BybitError as exc:
        LOG.info("base non mesurable, Bybit indisponible : %s", exc)
        return Basis(note=f"Bybit indisponible ({exc})")

    yahoo = YahooGoldClient()
    try:
        reference = yahoo.resolve_instrument(config.market.yahoo_symbol)
    except YahooError as exc:
        LOG.info("base non mesurable, or spot indisponible : %s", exc)
        return Basis(note=f"or spot indisponible ({exc})")

    for timeframe in ("M1", "M5"):
        try:
            left = client.klines(instrument, timeframe, 300)
            right = yahoo.klines(reference, timeframe, 300)
        except (BybitError, YahooError) as exc:
            LOG.debug("base %s : %s", timeframe, exc)
            continue
        basis = estimate_basis(left, right)
        if basis.ok:
            return basis
    return Basis(note="aucune bougie commune entre les deux sources")


@dataclass
class CalibrationProbe:
    """Tout ce qu'il faut pour caler une calibration à partir du SEUL prix MT5.

    L'outil sait déjà lire le prix Bybit et mesurer la base Bybit→spot. La
    seule chose qu'il ne peut pas deviner, c'est ce qu'affiche le terminal de
    l'utilisateur : c'est donc la seule chose à lui demander.
    """

    bybit: Optional[float] = None
    spot: Optional[float] = None
    basis: Basis = field(default_factory=Basis)
    symbol: str = ""
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.bybit is not None

    @property
    def reference(self) -> str:
        return "spot" if self.spot is not None else "bybit"


def probe_reference_price(config: Config) -> CalibrationProbe:
    """Relève le prix de référence courant, par ordre de préférence.

    1. Bybit + base mesurée : on obtient le prix temps réel ET son équivalent
       spot, donc un ancrage qui mesure le seul markup du broker.
    2. Or spot Yahoo seul : suffisant, puisque c'est déjà le bon référentiel.
       Indispensable là où Bybit est filtré par pays.
    """
    problems: list[str] = []

    client = BybitClient()
    try:
        instrument = client.resolve_instrument(config.market.bybit_symbol,
                                               config.market.bybit_category)
        ticker = client.ticker(instrument)
        price = float(ticker.get("lastPrice") or ticker.get("markPrice") or 0.0)
        if price:
            probe = CalibrationProbe(bybit=price, symbol=instrument.symbol)
            probe.basis = measure_basis(config)
            if probe.basis.ok:
                probe.spot = round(probe.basis.to_spot(price), 4)
            else:
                probe.problem = probe.basis.note
            return probe
        problems.append("Bybit n'a renvoyé aucun prix")
    except BybitError as exc:
        problems.append(f"Bybit : {exc}")

    # Repli : l'or spot suffit, c'est déjà le référentiel visé.
    yahoo = YahooGoldClient()
    try:
        reference = yahoo.resolve_instrument(config.market.yahoo_symbol)
        spot = yahoo.last_price(reference)
        if spot:
            return CalibrationProbe(
                bybit=spot, spot=round(spot, 4), symbol=reference.symbol,
                problem="; ".join(problems),
            )
        problems.append("Yahoo n'a renvoyé aucun prix")
    except YahooError as exc:
        problems.append(f"Yahoo : {exc}")

    return CalibrationProbe(problem=" | ".join(problems))


def calibrate_from_mt5(config: Config, calibration: Calibration, mt5_bid: float,
                       mt5_ask: Optional[float] = None) -> tuple[Calibration, CalibrationProbe]:
    """Cale la calibration à partir du seul prix affiché par MetaTrader 5.

    Si un seul prix est fourni, il est traité comme le MILIEU du marché et le
    spread connu est conservé : mieux vaut réutiliser un spread déjà mesuré
    que d'en inventer un.
    """
    probe = probe_reference_price(config)
    if not probe.ok:
        return calibration, probe

    if mt5_ask is None:
        half = calibration.half_spread if calibration.anchors else 0.15
        bid, ask = mt5_bid - half, mt5_bid + half
    else:
        bid, ask = min(mt5_bid, mt5_ask), max(mt5_bid, mt5_ask)

    updated = add_anchor(calibration, probe.bybit, bid, ask,
                         source="prix_mt5", spot=probe.spot)
    return updated, probe


def run(config: Config, calibration: Calibration, *, demo: bool = False,
        seed: Optional[int] = None, prefer_mt5: bool = True,
        spread_override: Optional[float] = None,
        demo_end_ms: Optional[int] = None) -> Analysis:
    bundle = collect(config, demo=demo, seed=seed, prefer_mt5=prefer_mt5,
                     demo_end_ms=demo_end_ms)
    return analyse(bundle, config, calibration, spread_override)
