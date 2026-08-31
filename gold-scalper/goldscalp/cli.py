"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

from goldscalp import __version__, engine
from goldscalp.config import Config
from goldscalp.core.backtest import BacktestResult, run_backtest
from goldscalp.core.calibration import (
    Calibration,
    add_anchor,
    auto_anchor_from_mt5,
    calibration_path,
    health,
    load_calibration,
    save_calibration,
)
from goldscalp.core.series import resample
from goldscalp.ui.console import Palette, make_palette, render, render_compact
from goldscalp.util import ms_to_iso, setup_logging

BANNER = "goldscalp {version} - scalping XAU/USD, prix Bybit recale sur MT5"


# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    # Options globales dupliquees sur chaque sous-commande : exiger
    # `goldscalp --no-color selftest` et refuser `goldscalp selftest --no-color`
    # est une friction gratuite.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", default="warn", choices=["debug", "info", "warn", "error"],
                        help="verbosite des journaux (défaut: warn)")
    common.add_argument("--no-color", action="store_true", help="désactive les couleurs")
    common.add_argument("--config", help="chemin d'un fichier de configuration JSON")

    parser = argparse.ArgumentParser(
        parents=[common],
        prog="goldscalp",
        description=BANNER.format(version=__version__),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exemples :\n"
            "  goldscalp calibrate --mt5 4437.10 4437.31   (le BID et l'ASK de ton MT5)\n"
            "  goldscalp analyse --balance 5000 --risk 0.5\n"
            "  goldscalp watch --interval 30\n"
            "  goldscalp backtest --bars 6000\n"
            "  goldscalp analyse --demo --seed 11      (données simulées, sans réseau)\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"goldscalp {__version__}")

    sub = parser.add_subparsers(dest="command")

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--symbol", help="symbole MT5 (défaut: XAUUSD)")
        sp.add_argument("--bybit-symbol", help="symbole Bybit (défaut: détection auto XAUTUSDT/PAXGUSDT)")
        sp.add_argument("--bybit-category", choices=["spot", "linear"], help="catégorie du marché Bybit")
        sp.add_argument("--yahoo-symbol",
                        help="symbole Yahoo du repli (défaut : XAUUSD=X puis GC=F)")
        sp.add_argument("--no-yahoo", action="store_true",
                        help="désactive le repli Yahoo quand Bybit est injoignable")
        sp.add_argument("--balance", type=float, help="capital du compte")
        sp.add_argument("--risk", type=float, help="pourcentage du capital risque par trade")
        sp.add_argument("--min-confidence", type=float, help="seuil de confiance pour émettre un signal")
        sp.add_argument("--spread", type=float, help="force le spread MT5 en dollars")
        sp.add_argument("--timeframes", help="liste séparée par des virgules (défaut: M1,M5,M15)")
        sp.add_argument("--allow-counter-trend", action="store_true",
                        help="autorisé les signaux contre une tendance M15 forte")
        sp.add_argument("--no-macro", action="store_true", help="ignore l'analyse fondamentale")
        sp.add_argument("--no-calendar", action="store_true", help="ignore le calendrier économique")
        sp.add_argument("--no-micro", action="store_true", help="ignore carnet et flux")
        sp.add_argument("--no-mt5", action="store_true", help="n'interroge pas le terminal MT5")
        sp.add_argument("--demo", action="store_true",
                        help="données simulées, sans réseau (pour essayer l'outil)")
        sp.add_argument("--seed", type=int, help="graine du simulateur (avec --demo)")

    p_analyse = sub.add_parser("analyse", help="analyse complète et plan de trade", parents=[common])
    add_common(p_analyse)
    p_analyse.add_argument("--json", action="store_true", help="sortie JSON exploitable par un script")
    p_analyse.add_argument("-v", "--verbose", action="store_true", help="détaillé chaque composante")
    p_analyse.add_argument("--with-backtest", action="store_true",
                           help="mesuré les taux de reussite avant d'estimer l'espérance")

    p_watch = sub.add_parser("watch", help="surveillance continue, une ligne par évaluation", parents=[common])
    add_common(p_watch)
    p_watch.add_argument("--interval", type=float, default=30.0, help="secondes entre deux analyses")
    p_watch.add_argument("--only-signals", action="store_true", help="n'affiché que les signaux")
    p_watch.add_argument("--full-on-signal", action="store_true",
                         help="affiché le rapport complet quand un signal apparait")
    p_watch.add_argument("--max-iterations", type=int, help="s'arrêté après N tours")

    p_cal = sub.add_parser("calibrate", help="géré le calage Bybit -> MT5", parents=[common])
    p_cal.add_argument("--mt5", type=float, nargs="+", metavar="PRIX",
                       help="BID et ASK affichés par ton terminal MT5. "
                            "Un seul nombre est accepté et traité comme le milieu du marché")
    p_cal.add_argument("--bybit", type=float, help="prix Bybit relevé (calage manuel avancé)")
    p_cal.add_argument("--bid", type=float, help="bid MT5 au même instant")
    p_cal.add_argument("--ask", type=float, help="ask MT5 au même instant")
    p_cal.add_argument("--auto", action="store_true", help="relevé le tick MT5 automatiquement")
    p_cal.add_argument("--symbol", help="symbole MT5 pour l'ancrage automatique")
    p_cal.add_argument("--show", action="store_true", help="affiché la calibration courante")
    p_cal.add_argument("--reset", action="store_true", help="efface tous les ancrages")
    p_cal.add_argument("--no-basis", action="store_true",
                       help="n'essaie pas de mesurer la base Bybit→spot (ancrage brut)")
    p_cal.add_argument("--bybit-symbol", help="symbole Bybit")
    p_cal.add_argument("--bybit-category", choices=["spot", "linear"])
    p_cal.add_argument("--yahoo-symbol", help="symbole Yahoo pour l'or spot")
    p_cal.add_argument("--json", action="store_true")

    p_bt = sub.add_parser("backtest", help="backtest walk-forward du coeur technique", parents=[common])
    add_common(p_bt)
    p_bt.add_argument("--bars", type=int, default=6000, help="bougies M1 a charger")
    p_bt.add_argument("--threshold", type=float, default=0.35, help="score minimal pour entrer")
    p_bt.add_argument("--json", action="store_true")

    p_levels = sub.add_parser("levels", help="niveaux clés en prix MT5", parents=[common])
    add_common(p_levels)

    sub.add_parser("selftest", help="vérifie l'intégrité du moteur", parents=[common])

    p_config = sub.add_parser("config", help="affiché ou enregistre la configuration", parents=[common])
    p_config.add_argument("--save", action="store_true", help="ecrit la configuration sur disque")
    p_config.add_argument("--path", action="store_true", help="affiché les chemins utilises")

    return parser


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    market, risk, eng = config.market, config.risk, config.engine
    if getattr(args, "symbol", None):
        market.mt5_symbol = args.symbol
    if getattr(args, "bybit_symbol", None):
        market.bybit_symbol = args.bybit_symbol
    if getattr(args, "bybit_category", None):
        market.bybit_category = args.bybit_category
    if getattr(args, "yahoo_symbol", None):
        market.yahoo_symbol = args.yahoo_symbol
    if getattr(args, "no_yahoo", False):
        eng.use_yahoo_fallback = False
    if getattr(args, "balance", None) is not None:
        risk.account_balance = args.balance
    if getattr(args, "risk", None) is not None:
        risk.risk_pct = args.risk
    if getattr(args, "min_confidence", None) is not None:
        eng.min_confidence = args.min_confidence
    if getattr(args, "timeframes", None):
        eng.timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    if getattr(args, "allow_counter_trend", False):
        eng.allow_counter_trend = True
    if getattr(args, "no_macro", False):
        eng.use_macro = False
    if getattr(args, "no_calendar", False):
        eng.use_calendar = False
    if getattr(args, "no_micro", False):
        eng.use_microstructure = False
    return config


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #

def cmd_analyse(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    calibration = load_calibration()
    problems = config.risk.validate()
    if problems:
        for problem in problems:
            print(palette.red(f"configuration invalidé : {problem}"), file=sys.stderr)
        return 2

    try:
        bundle = engine.collect(
            config, demo=args.demo, seed=args.seed,
            prefer_mt5=not args.no_mt5,
        )
        analysis = engine.analyse(bundle, config, calibration, args.spread)
    except Exception as exc:
        print(palette.red(f"analyse impossible : {exc}"), file=sys.stderr)
        if args.log == "debug":
            raise
        return 1

    backtest: Optional[BacktestResult] = None
    if args.with_backtest:
        backtest = _backtest_from_bundle(bundle, config)
        rates = backtest.win_rates()
        if rates[0] > 0 and analysis.plan.valid:
            from goldscalp.core.plan import build_plan

            analysis.plan = build_plan(
                analysis.confluence, calibration, config.risk, config.market,
                analysis.session,
                bundle.news.size_multiplier if bundle.news else 1.0,
                args.spread, rates,
            )

    if args.json:
        print(json.dumps(to_payload(analysis, backtest), indent=2, ensure_ascii=False))
    else:
        print(render(analysis, palette, backtest, args.verbose))
    return 0


def cmd_watch(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    print(palette.bold(BANNER.format(version=__version__)))
    print(palette.grey(
        f"surveillance toutes les {args.interval:.0f}s - Ctrl+C pour arrêter\n"
    ))
    iterations = 0
    last_signal: Optional[tuple[int, bool]] = None
    while True:
        iterations += 1
        calibration = load_calibration()
        try:
            analysis = engine.run(
                config, calibration, demo=args.demo, seed=args.seed,
                prefer_mt5=not args.no_mt5, spread_override=args.spread,
            )
        except Exception as exc:
            print(palette.red(f"{time.strftime('%H:%M:%S')}  erreur : {exc}"))
            time.sleep(args.interval)
            continue

        signal = (analysis.confluence.direction, analysis.confluence.turbo)
        is_new = signal != last_signal and signal[0] != 0

        if analysis.confluence.direction != 0 or not args.only_signals:
            print(render_compact(analysis, palette))
        if is_new and args.full_on_signal:
            print()
            print(render(analysis, palette))
            print()
        last_signal = signal

        if args.max_iterations and iterations >= args.max_iterations:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\narret.")
            return 0


def cmd_calibrate(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    calibration = load_calibration()

    if args.reset:
        calibration = Calibration()
        path = save_calibration(calibration)
        print(palette.yellow(f"calibration effacee ({path})"))
        return 0

    if args.auto:
        try:
            from goldscalp.data.bybit import BybitClient

            client = BybitClient()
            instrument = client.resolve_instrument(config.market.bybit_symbol, config.market.bybit_category)
            ticker = client.ticker(instrument)
            bybit_price = float(ticker.get("lastPrice") or ticker.get("markPrice") or 0.0)
            if not bybit_price:
                raise RuntimeError("prix Bybit indisponible")
        except Exception as exc:
            print(palette.red(f"prix Bybit inaccessible : {exc}"), file=sys.stderr)
            return 1
        print(palette.grey(f"prix Bybit {instrument.symbol} : {bybit_price:.2f}"))
        spot = None
        if not args.no_basis:
            basis = engine.measure_basis(config)
            if basis.ok:
                spot = round(basis.to_spot(bybit_price), 4)
                print(palette.grey(f"  base mesurée : {basis.value:+.2f} $ -> or spot {spot:.2f}"))
        updated = auto_anchor_from_mt5(calibration, bybit_price,
                                       args.symbol or config.market.mt5_symbol, spot=spot)
        if updated is calibration:
            print(palette.red(
                "ancrage automatique impossible. Releve bid/ask dans MT5 et utilise :\n"
                f"  goldscalp calibrate --bybit {bybit_price:.2f} --bid <bid> --ask <ask>"
            ), file=sys.stderr)
            return 1
        calibration = updated
        save_calibration(calibration)

    elif args.mt5:
        # Le cas normal : l'utilisateur lit un prix dans MT5 et le recopie.
        # L'outil relève lui-même le prix Bybit et mesure la base.
        if len(args.mt5) > 2:
            print(palette.red("--mt5 accepte un prix (milieu) ou deux (bid et ask)"),
                  file=sys.stderr)
            return 2
        bid = args.mt5[0]
        ask = args.mt5[1] if len(args.mt5) > 1 else None
        updated, probe = engine.calibrate_from_mt5(config, calibration, bid, ask)
        if not probe.ok:
            print(palette.red(
                f"Impossible de relever un prix de référence.\n  {probe.problem}\n"
                "Sans lui, l'outil ne peut pas savoir de combien ton broker s'écarte.\n"
                "Vérifie ta connexion, ou fournis le calage complet :\n"
                "  goldscalp calibrate --bybit <prix> --bid <bid> --ask <ask>"
            ), file=sys.stderr)
            return 1

        calibration = updated
        save_calibration(calibration)
        print(palette.grey(f"  {probe.symbol} relevé : {probe.bybit:.2f}"))
        if probe.reference_kind == "index":
            print(palette.grey("  référence : index du perpétuel or Bybit (suit l'or réel)"))
        elif probe.spot is not None and probe.basis.ok:
            print(palette.grey(
                f"  base Bybit->spot : {probe.basis.value:+.2f} $ "
                f"(± {probe.basis.dispersion:.2f} sur {probe.basis.samples} bougies) "
                f"-> or spot {probe.spot:.2f}"
            ))
        elif probe.spot is not None:
            print(palette.grey("  référence : or spot direct (Bybit indisponible)"))
            print(palette.green(
                f"Calibré. Markup de ton broker : {calibration.alpha:+.2f} $. "
                "Valable plusieurs jours."
            ))
        else:
            print(palette.yellow(f"  base non mesurée ({probe.problem})"))
            print(palette.green(
                f"Calibré sur le prix Bybit brut : écart {calibration.alpha:+.2f} $. "
                "À refaire dans 2 à 4 heures."
            ))
        if ask is None:
            print(palette.grey(
                f"  spread suppose a {calibration.spread:.2f} $ (prix unique fourni). "
                "Donne bid et ask pour le mesurer : --mt5 <bid> <ask>"
            ))

    elif args.bybit is not None:
        if args.bid is None or args.ask is None:
            print(palette.red("--bid et --ask sont requis avec --bybit"), file=sys.stderr)
            return 2
        spot = None
        if not args.no_basis:
            basis = engine.measure_basis(config)
            if basis.ok:
                spot = round(basis.to_spot(args.bybit), 4)
                print(palette.grey(
                    f"  base Bybit->spot mesurée : {basis.value:+.2f} $ "
                    f"(± {basis.dispersion:.2f} sur {basis.samples} bougies)"
                ))
                print(palette.grey(f"  prix Bybit {args.bybit:.2f} -> or spot {spot:.2f}"))
            else:
                print(palette.yellow(
                    f"  base non mesurée ({basis.note}) : l'ancrage restera adossé au "
                    "prix Bybit brut et se périmera en quelques heures."
                ))
        calibration = add_anchor(calibration, args.bybit, args.bid, args.ask,
                                 source="manuel", spot=spot)
        save_calibration(calibration)
        if calibration.reference == "spot":
            print(palette.green(
                f"Ancrage enregistré — markup broker mesuré : {calibration.alpha:+.2f} $. "
                "Il reste valable plusieurs jours."
            ))
        else:
            print(palette.green("Ancrage enregistré (adossé au prix Bybit brut)."))

    elif not args.show:
        print(palette.yellow(
            "Rien à faire. Le plus simple : "
            "`goldscalp calibrate --mt5 <bid> <ask>`.\n"
            "Autres options : --show, --auto, --reset."
        ))

    if args.json:
        payload = calibration.to_dict()
        payload["quality"] = calibration.quality()
        payload["health"] = health(calibration)[0]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print()
    print(palette.bold("CALIBRATION"))
    print(f"  {calibration.describe()}")
    print(f"  fichier : {calibration_path()}")
    level, problems = health(calibration)
    color = {"ok": palette.green, "attention": palette.yellow, "critique": palette.red}[level]
    print(f"  état : {color(level.upper())}")
    for problem in problems:
        print(palette.yellow(f"    ! {problem}"))
    if calibration.anchors:
        print(f"\n  {len(calibration.anchors)} ancrage(s) :")
        for anchor in calibration.anchors[-8:]:
            print(
                f"    {ms_to_iso(anchor.ts)}  bybit {anchor.bybit:9.2f}  "
                f"mt5 {anchor.mt5_bid:9.2f}/{anchor.mt5_ask:<9.2f}  "
                f"écart {anchor.offset:+8.2f}  spread {anchor.spread:.2f}  [{anchor.source}]"
            )
        print(palette.grey(
            "\n  Pour identifier la PENTE (et pas seulement le décalage), il faut "
            "au moins 3 ancrages\n  espaces de plus de 8 $ de prix. Sinon l'outil "
            "applique un décalage constant."
        ))
    else:
        print(palette.yellow(
            "\n  Aucun ancrage. Ouvre MT5 sur XAUUSD, recopie le BID et l'ASK :\n"
            "    goldscalp calibrate --mt5 4437.10 4437.31\n"
            "  L'outil relève l'index or de Bybit et mémorise l'écart, sans expiration."
        ))
    return 0


def cmd_backtest(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    config.engine.bars["M1"] = max(args.bars, 1500)
    try:
        bundle = engine.collect(config, demo=args.demo, seed=args.seed,
                                prefer_mt5=not args.no_mt5, use_micro=False)
    except Exception as exc:
        print(palette.red(f"données indisponibles : {exc}"), file=sys.stderr)
        return 1

    result = _backtest_from_bundle(bundle, config, args.threshold)
    if args.json:
        print(json.dumps({
            "trades": result.count,
            "bars_tested": result.bars_tested,
            "tp1_rate": round(result.tp1_rate, 4),
            "tp2_rate": round(result.tp2_rate, 4),
            "stop_rate": round(result.stop_rate, 4),
            "expectancy_r": result.expectancy_r,
            "total_r": result.total_r,
            "profit_factor": result.profit_factor,
            "max_drawdown_r": result.max_drawdown_r,
            "avg_bars": result.avg_bars,
            "warnings": result.warnings,
        }, indent=2, ensure_ascii=False))
        return 0

    print(palette.bold("\nBACKTEST WALK-FORWARD"))
    print("-" * 60)
    for line in result.summary():
        print(f"  {line}")
    print()
    for warning in result.warnings:
        print(palette.grey(f"  {warning}"))
    print(palette.grey(
        "  Convention defavorable : si stop et cible tombent dans la même bougie,\n"
        "  le stop est compte. L'entrée se fait à l'ouverture de la bougie suivante."
    ))
    return 0


def cmd_levels(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    calibration = load_calibration()
    try:
        analysis = engine.run(config, calibration, demo=args.demo, seed=args.seed,
                              prefer_mt5=not args.no_mt5, spread_override=args.spread)
    except Exception as exc:
        print(palette.red(f"analyse impossible : {exc}"), file=sys.stderr)
        return 1

    price = analysis.price
    print(palette.bold(f"\nNIVEAUX CLÉS - {config.market.mt5_symbol} @ {price:.2f} $ "
                       f"(référentiel MT5)"))
    for timeframe in ("M15", "M5", "M1"):
        view = analysis.confluence.views.get(timeframe)
        if view is None:
            continue
        structure = view.structure
        from goldscalp.core.scoring import TREND_FR

        print(palette.blue(f"\n  {timeframe} - structure {TREND_FR.get(structure.trend, structure.trend)}, "
                           f"dernier événement {structure.last_event}"))

        def line(level, above: bool) -> str:
            distance = level.price - price
            # Le role d'un niveau dépend de sa position ACTUELLE : un ancien
            # support passe sous le prix redevient une résistance. Afficher sa
            # nature d'origine au-dessus du prix induit en erreur.
            role = "résistance" if above else "support"
            origin = level.label or level.kind
            colorize = palette.red if above else palette.green
            return (f"    {colorize(f'{level.price:10.2f}')}  {distance:+8.2f} $  "
                    f"force {level.strength:.2f}  {role:<10} (issu de {origin})")

        for level in reversed(structure.levels_above(price, 5)):
            print(line(level, True))
        print(f"    {palette.bold(f'{price:10.2f}')}  {'  <-- prix':>12}")
        for level in structure.levels_below(price, 5):
            print(line(level, False))

        # Les poches sont calculees sur la dernière clôture du timeframe, qui
        # peut differer du prix M1 courant : on les reclasse à l'affichage.
        pools = list(structure.liquidity_above) + list(structure.liquidity_below)
        above_pools = sorted(x for x in pools if x > price)
        below_pools = sorted((x for x in pools if x < price), reverse=True)
        if above_pools or below_pools:
            print(palette.grey(
                f"    liquidité au-dessus {[round(x, 2) for x in above_pools] or '-'} | "
                f"en dessous {[round(x, 2) for x in below_pools] or '-'}"
            ))
    return 0


def cmd_config(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    if args.path:
        from goldscalp.util import state_dir

        print(f"repertoire d'état : {state_dir()}")
        print(f"configuration     : {Config.default_path()}")
        print(f"calibration       : {calibration_path()}")
        return 0
    if args.save:
        path = config.save()
        print(palette.green(f"configuration enregistree dans {path}"))
        return 0
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_selftest(args: argparse.Namespace, config: Config, palette: Palette) -> int:
    from goldscalp.selftest import run_selftest

    return run_selftest(palette)


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #

def _backtest_from_bundle(bundle: engine.DataBundle, config: Config,
                          threshold: float = 0.35) -> BacktestResult:
    calibration = load_calibration()
    m5 = bundle.series.get("M5")
    if m5 is None and "M1" in bundle.series:
        m5 = resample(bundle.series["M1"], "M5")
    if m5 is None:
        result = BacktestResult()
        result.warnings.append("aucune série M5 disponible")
        return result
    m15 = bundle.series.get("M15")
    if bundle.price_source == "BYBIT":
        m5 = calibration.apply(m5)
        m15 = calibration.apply(m15) if m15 is not None else None
    return run_backtest(m5, m15, config.risk, calibration.spread, threshold)


def to_payload(analysis: engine.Analysis, backtest: Optional[BacktestResult] = None) -> dict:
    """Representation JSON complète, pour scripter par-dessus l'outil."""
    c = analysis.confluence
    plan = analysis.plan
    payload = {
        "timestamp": analysis.ts,
        "timestamp_iso": ms_to_iso(analysis.ts),
        "symbol": analysis.config.market.mt5_symbol,
        "price_mt5": round(analysis.price, 2),
        "price_bybit": round(analysis.price_bybit, 2) if analysis.price_bybit else None,
        "price_source": analysis.data.price_source,
        "simulated": analysis.data.simulated,
        "session": {
            "name": analysis.session.name,
            "volatility_factor": analysis.session.volatility_factor,
            "minutes_to_next": analysis.session.minutes_to_next,
        },
        "calibration": {
            "alpha": round(analysis.calibration.alpha, 4),
            "beta": round(analysis.calibration.beta, 8),
            "spread": analysis.calibration.spread,
            "quality": analysis.calibration.quality(),
            "health": analysis.calibration_level,
            "anchors": len(analysis.calibration.anchors),
            "reference": analysis.calibration.reference,
        },
        "signal": {
            "direction": c.direction,
            "side": c.side,
            "confidence": c.confidence,
            "raw_score": c.raw_score,
            "final_score": c.final_score,
            "alignment": c.alignment,
            "turbo": c.turbo,
            "turbo_reasons": c.turbo_reasons,
            "turbo_blockers": c.turbo_blockers,
            "style": c.style,
            "vetoes": c.vetoes,
            "warnings": c.warnings,
            "reasons": c.reasons,
        },
        "timeframes": {
            tf: {
                "score": view.score,
                "label": view.label,
                "regime": view.regime.label,
                "volatility": view.regime.volatility_state,
                "trend": view.structure.trend,
                "last_event": view.structure.last_event,
                "atr": round(view.indicators.atr_value, 3),
                "components": {
                    name: {"value": comp.value, "weight": comp.weight}
                    for name, comp in view.components.items()
                },
            }
            for tf, view in c.views.items()
        },
        "fundamental": {
            "score": analysis.fundamental.score,
            "confidence": analysis.fundamental.confidence,
            "bias": analysis.fundamental.bias,
            "label": analysis.fundamental.regime_label,
            "drivers": [
                {"key": d.key, "change_pct": d.change_pct, "contribution": d.contribution}
                for d in analysis.fundamental.drivers if d.change_pct is not None
            ],
            "news": (
                {
                    "level": analysis.fundamental.news.level,
                    "reason": analysis.fundamental.news.reason,
                    "minutes_until": analysis.fundamental.news.minutes_until,
                    "size_multiplier": analysis.fundamental.news.size_multiplier,
                    "estimated": analysis.fundamental.news.estimated,
                }
                if analysis.fundamental.news else None
            ),
        },
        "scalp": {
            "score": analysis.scalp.score,
            "verdict": analysis.scalp.verdict,
            "turbo_ready": analysis.scalp.turbo_ready,
            "burst": analysis.scalp.burst,
            "chase_bars": analysis.scalp.chase_bars,
            "spread_share": analysis.scalp.spread_share,
            "room": analysis.scalp.room,
            "velocity": analysis.scalp.velocity,
            "window": analysis.scalp.window,
            "estimated_target": analysis.scalp.estimated_target,
            "checks": [
                {"name": ck.name, "passed": ck.passed, "blocking": ck.blocking,
                 "value": ck.value, "detail": ck.detail}
                for ck in analysis.scalp.checks
            ],
        },
        "conversion": {
            "chain": analysis.conversion_chain,
            "residual_error": analysis.residual_error,
            "basis": {
                "ok": analysis.data.basis.ok,
                "value": analysis.data.basis.value,
                "dispersion": analysis.data.basis.dispersion,
                "drift_per_hour": analysis.data.basis.drift_per_hour,
                "samples": analysis.data.basis.samples,
                "quality": analysis.data.basis.quality(),
            },
        },
        "microstructure": {
            "score": analysis.data.micro.score,
            "imbalance": analysis.data.micro.imbalance,
            "flow_score": analysis.data.micro.flow.score,
            "buy_ratio": analysis.data.micro.flow.buy_ratio,
            "positioning": analysis.data.micro.derivatives.positioning,
            "funding_zscore": analysis.data.micro.derivatives.funding_zscore,
        },
        "plan": (
            {
                "valid": True,
                "side": plan.side,
                "entry": plan.entry,
                "entry_type": plan.entry_type,
                "entry_zone": list(plan.entry_zone),
                "stop_loss": plan.stop,
                "stop_distance": plan.stop_distance,
                "take_profits": [
                    {
                        "label": t.label, "price": t.price, "distance": round(t.distance, 2),
                        "r_multiple": t.r_multiple, "share": t.share, "rationale": t.rationale,
                    }
                    for t in plan.targets
                ],
                "lots": plan.lots,
                "risk_amount": plan.risk_amount,
                "reward_tp1": plan.reward_tp1,
                "reward_tp2": plan.reward_tp2,
                "rr1": plan.rr1,
                "rr2": plan.rr2,
                "expectancy_r": plan.expectancy_r,
                "spread": plan.spread,
                "management": plan.management,
                "invalidation": plan.invalidation,
                "notes": plan.notes,
            }
            if plan.valid else {"valid": False, "rejection": plan.rejection}
        ),
        "data": {
            "bars": {tf: len(s) for tf, s in analysis.data.series.items()},
            "sources": analysis.data.sources,
            "problems": analysis.data.problems,
            "fetch_seconds": analysis.data.fetch_seconds,
        },
    }
    if backtest is not None:
        payload["backtest"] = {
            "trades": backtest.count,
            "tp1_rate": round(backtest.tp1_rate, 4),
            "tp2_rate": round(backtest.tp2_rate, 4),
            "expectancy_r": backtest.expectancy_r,
            "profit_factor": backtest.profit_factor,
            "max_drawdown_r": backtest.max_drawdown_r,
        }
    return payload


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #

def _force_utf8_output() -> None:
    """Evite un UnicodeEncodeError sur les consoles Windows historiques.

    Le rapport contient des accents ; une console en cp1252 leve une exception
    a la premiere ligne affichée. On bascule les flux en UTF-8, avec
    remplacement des caracteres impossibles plutot qu'un plantage.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # flux redirige ou Python ancien
            pass


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log)
    palette = make_palette(False if args.no_color else None)

    if not args.command:
        parser.print_help()
        return 0

    config = Config.load(args.config)
    config = apply_overrides(config, args)

    handlers = {
        "analyse": cmd_analyse,
        "watch": cmd_watch,
        "calibrate": cmd_calibrate,
        "backtest": cmd_backtest,
        "levels": cmd_levels,
        "config": cmd_config,
        "selftest": cmd_selftest,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args, config, palette)
    except KeyboardInterrupt:
        print("\ninterrompu.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
