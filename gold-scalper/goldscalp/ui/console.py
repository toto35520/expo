"""Rapport terminal.

Objectif de lisibilite : un scalpeur doit pouvoir lire le verdict, le plan et
la raison du refus en trois secondes, sans faire defiler.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from goldscalp.core.backtest import BacktestResult
from goldscalp.engine import Analysis
from goldscalp.util import ms_to_iso

# --------------------------------------------------------------------------- #
# Couleurs
# --------------------------------------------------------------------------- #

class Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def blue(self, t: str) -> str:
        return self._wrap("36", t)

    def magenta(self, t: str) -> str:
        return self._wrap("35", t)

    def grey(self, t: str) -> str:
        return self._wrap("90", t)

    def invert(self, t: str) -> str:
        return self._wrap("7", t)


def make_palette(force: Optional[bool] = None) -> Palette:
    if force is not None:
        return Palette(force)
    if os.environ.get("NO_COLOR"):
        return Palette(False)
    return Palette(sys.stdout.isatty())


WIDTH = 78

# Les libelles internes (regime, structure, volatilite) servent aussi de cles
# de comparaison dans le moteur : ils restent sans accent dans le code et sont
# accentues au moment de l'affichage seulement.
_LIBELLES = {
    "tendance_forte": "tendance forte", "compression": "compression",
    "expansion": "expansion", "range": "range", "chaos": "chaos",
    "tendance": "tendance", "basse": "basse", "normale": "normale",
    "haute": "haute", "extreme": "extr\u00eame", "haussier": "haussier",
    "baissier": "baissier", "neutre": "neutre", "indetermine": "ind\u00e9termin\u00e9",
}


def _fr(label: str) -> str:
    return _LIBELLES.get(label, label)


def _rule(char: str = "-") -> str:
    return char * WIDTH


def _title(text: str, palette: Palette) -> str:
    return palette.bold(f"{text}\n{_rule('=')}")


def _section(text: str, palette: Palette) -> str:
    return palette.blue(f"\n{text}\n{_rule()}")


def _bar(value: float, width: int = 22) -> str:
    """Jauge -1..+1 centree."""
    half = width // 2
    filled = int(abs(value) * half)
    if value >= 0:
        return " " * half + "|" + "#" * filled + " " * (half - filled)
    return " " * (half - filled) + "#" * filled + "|" + " " * half


# --------------------------------------------------------------------------- #
# Rapport
# --------------------------------------------------------------------------- #

def render(analysis: Analysis, palette: Optional[Palette] = None,
           backtest: Optional[BacktestResult] = None, verbose: bool = False) -> str:
    p = palette or make_palette()
    out: list[str] = []
    c = analysis.confluence
    plan = analysis.plan
    data = analysis.data

    # -- en-tête ----------------------------------------------------------- #
    out.append(_title(f"GOLDSCALP  -  {analysis.config.market.mt5_symbol}  scalp M1/M5/M15", p))
    if data.simulated:
        out.append(p.invert(p.yellow(
            " DONNÉES SIMULÉES - aucun prix réel, ne jamais trader ce signal ".center(WIDTH)
        )))

    source_note = {
        "MT5": "prix broker direct",
        "BYBIT": "prix Bybit recalibre vers MT5",
        "SIMULATION": "générateur interne",
    }.get(data.price_source, "")
    out.append(
        f"{p.bold(f'{analysis.price:.2f} $')}   "
        f"{p.grey(f'source {data.price_source} ({source_note})')}   "
        f"{p.grey(ms_to_iso(analysis.ts))}"
    )
    if analysis.price_bybit is not None and data.price_source == "BYBIT":
        delta = analysis.price - analysis.price_bybit
        out.append(p.grey(
            f"  Bybit brut {analysis.price_bybit:.2f} $  ->  MT5 {analysis.price:.2f} $  "
            f"(écart {delta:+.2f} $)"
        ))
    session = analysis.session
    session_color = p.green if session.is_prime else (p.red if session.is_poor else p.yellow)
    out.append(
        f"  Session {session_color(session.name)} "
        f"(x{session.volatility_factor:.2f} volatilité, change dans {session.minutes_to_next} min) "
        f"- {session.advice}"
    )

    # -- calibration ------------------------------------------------------- #
    level_color = {"ok": p.green, "attention": p.yellow, "critique": p.red}[analysis.calibration_level]
    out.append(_section("CALIBRAGE BYBIT -> MT5", p))
    out.append(f"  {level_color(analysis.calibration_level.upper())}  {analysis.calibration.describe()}")
    for problem in analysis.calibration_problems:
        out.append(p.yellow(f"  ! {problem}"))

    # -- verdict ----------------------------------------------------------- #
    out.append(_section("VERDICT", p))
    if c.direction > 0:
        badge = p.green(p.bold(f" ACHAT  {c.confidence:.0f}/100 "))
    elif c.direction < 0:
        badge = p.red(p.bold(f" VENTE  {c.confidence:.0f}/100 "))
    else:
        badge = p.grey(p.bold(" PAS DE TRADE "))
    turbo = p.magenta(p.bold("  [TURBO]")) if c.turbo else ""
    out.append(f"  {badge}{turbo}")
    out.append(
        f"  score technique {c.raw_score:+.3f} -> final {c.final_score:+.3f}  "
        f"| accord des timeframes {c.alignment:.0%}  | style {c.style}"
    )
    if c.turbo:
        out.append(p.magenta(
            "  TURBO : 3 timeframes alignes, session optimale, volatilité haute "
            "et flux confirmant. Entrée au marché."
        ))

    for veto in c.vetoes:
        out.append(p.red(f"  VETO : {veto}"))

    # -- plan -------------------------------------------------------------- #
    out.append(_section("PLAN DE TRADE", p))
    if not plan.valid:
        out.append(p.yellow(f"  Aucun plan : {plan.rejection}"))
    else:
        side_color = p.green if plan.side == "ACHAT" else p.red
        out.append(
            f"  {side_color(p.bold(plan.side))}  ordre {p.bold(plan.entry_type)} "
            f"a {p.bold(f'{plan.entry:.2f}')}"
            + (f"  (zone {plan.entry_zone[0]:.2f} - {plan.entry_zone[1]:.2f})"
               if plan.entry_type == "limite" else "")
        )
        out.append(f"  {'Stop loss':<12} {p.red(f'{plan.stop:>10.2f}')}   "
                   f"{plan.stop_distance:>6.2f} $   {p.grey('risque ' + f'{plan.risk_amount:.2f} $')}")
        for target in plan.targets:
            out.append(
                f"  {target.label:<12} {p.green(f'{target.price:>10.2f}')}   "
                f"{target.distance:>6.2f} $   "
                f"{p.bold(f'{target.r_multiple:.2f}R')}  {target.share:.0%} de la position"
            )
            out.append(p.grey(f"               -> {target.rationale}"))
        out.append(
            f"  {'Taille':<12} {p.bold(f'{plan.lots:>10.2f}')} lots   "
            f"spread {plan.spread:.2f} $   "
            f"gain TP1 {plan.reward_tp1:.2f} $ / TP2 {plan.reward_tp2:.2f} $"
        )
        expectancy_color = p.green if plan.expectancy_r > 0 else p.red
        out.append(
            f"  {'Esperance':<12} {expectancy_color(f'{plan.expectancy_r:>+10.3f} R')} par trade"
            + (p.grey("   (taux mesurés par le backtest)") if backtest and backtest.count >= 12
               else p.grey("   (estimation prudente, lance `backtest` pour des taux mesurés)"))
        )
        out.append("")
        for line in plan.management:
            out.append(f"  - {line}")
        out.append(p.grey(f"  {plan.invalidation}"))
        for note in plan.notes:
            out.append(p.yellow(f"  ! {note}"))

    # -- timeframes -------------------------------------------------------- #
    out.append(_section("LECTURE PAR TIMEFRAME", p))
    out.append(p.grey(f"  {'TF':<5}{'score':>7}  {'jauge':<24}{'régime':<17}{'volatilité':<12}rôle"))
    for timeframe in ("M15", "M5", "M1"):
        view = c.views.get(timeframe)
        if view is None:
            continue
        color = p.green if view.score > 0.15 else (p.red if view.score < -0.15 else p.grey)
        # On met en forme le texte BRUT puis on colore : appliquer une largeur
        # de champ à une chaine déjà pourvue de codes ANSI décalé tout.
        out.append(
            f"  {p.bold(f'{timeframe:<5}')}{color(f'{view.score:+.3f}'.rjust(7))}  "
            f"{p.grey(_bar(view.score))}  "
            f"{_fr(view.regime.label):<17}{_fr(view.regime.volatility_state):<12}{view.role}"
        )
        if verbose:
            for name, component in view.components.items():
                out.append(p.grey(
                    f"        {name:<15}{component.value:+.3f} x{component.weight:.2f} "
                    f"= {component.contribution:+.3f}"
                ))

    # -- fondamental ------------------------------------------------------- #
    fundamental = analysis.fundamental
    out.append(_section("ANALYSE FONDAMENTALE", p))
    bias_color = {"haussier": p.green, "baissier": p.red}.get(fundamental.bias, p.grey)
    out.append(
        f"  Biais macro {bias_color(p.bold(fundamental.bias))} "
        f"(score {fundamental.score:+.2f}, confiance {fundamental.confidence:.0%}, "
        f"effectif {fundamental.effective_score:+.2f})"
    )
    if fundamental.regime_label != "neutre":
        out.append(f"  {fundamental.regime_label}")
    for driver in fundamental.top_drivers(4):
        out.append(p.grey(f"    {driver.explain()}"))
    news = fundamental.news
    if news is not None:
        news_color = {"blocage": p.red, "prudence": p.yellow, "libre": p.green}[news.level]
        out.append(f"  Calendrier : {news_color(news.level.upper())} - {news.reason}")
    for note in fundamental.notes:
        out.append(p.yellow(f"  ! {note}"))

    # -- microstructure ---------------------------------------------------- #
    micro = data.micro
    lines = micro.summary()
    if lines:
        out.append(_section("MICROSTRUCTURE (carnet, flux, dérivés)", p))
        out.append(f"  Score de flux {micro.score:+.2f}")
        for line in lines:
            out.append(p.grey(f"    {line}"))

    # -- justification ----------------------------------------------------- #
    if c.reasons:
        out.append(_section("POURQUOI CE SIGNAL", p))
        seen: set[str] = set()
        for reason in c.reasons:
            if reason in seen:
                continue
            seen.add(reason)
            out.append(f"  - {reason}")

    if c.modifiers:
        out.append(_section("AJUSTEMENTS APPLIQUÉS", p))
        out.append(p.grey(
            "  Un ajustement additif déplace le score ; une atténuation ne fait "
            "que réduire la conviction."
        ))
        for modifier in c.modifiers:
            if modifier.kind == "attenuation":
                effect = p.yellow("atténue ")
            elif (modifier.value > 0) == (c.final_score >= 0):
                effect = p.green("renforce")
            else:
                effect = p.red("contrarie")
            out.append(
                f"  {modifier.name:<18}{modifier.display:>8}  {effect}  {modifier.detail}"
            )

    if c.warnings:
        out.append(_section("AVERTISSEMENTS", p))
        for warning in c.warnings:
            out.append(p.yellow(f"  ! {warning}"))

    # -- backtest ---------------------------------------------------------- #
    if backtest is not None:
        out.append(_section("BACKTEST DU COEUR TECHNIQUE", p))
        for line in backtest.summary():
            out.append(f"  {line}")
        for warning in backtest.warnings:
            out.append(p.grey(f"  {warning}"))

    # -- provenance -------------------------------------------------------- #
    out.append(_section("DONNÉES UTILISÉES", p))
    for timeframe in analysis.config.engine.timeframes:
        series = data.series.get(timeframe)
        if series:
            gaps = len(series.gaps())
            out.append(
                f"  {timeframe:<5}{len(series):>6} bougies  "
                f"{ms_to_iso(series[0].ts)} -> {ms_to_iso(series[-1].ts)}"
                + (p.yellow(f"  ({gaps} trous)") if gaps else "")
            )
    for key, value in data.sources.items():
        out.append(p.grey(f"  {key:<16}{value}"))
    out.append(p.grey(f"  collecte en {data.fetch_seconds:.2f} s, {data.bars_total} bougies au total"))
    for problem in data.problems:
        out.append(p.yellow(f"  ! {problem}"))

    out.append("")
    out.append(p.grey(
        "  Cet outil produit une analyse, pas un ordre. Le marché peut invalider "
        "n'importe quelle configuration."
    ))
    return "\n".join(out)


def render_compact(analysis: Analysis, palette: Optional[Palette] = None) -> str:
    """Une ligne : pour le mode surveillance."""
    p = palette or make_palette()
    c = analysis.confluence
    plan = analysis.plan
    stamp = ms_to_iso(analysis.ts)[11:19]

    if c.direction == 0:
        reason = c.vetoes[0][:40] if c.vetoes else f"conf {c.confidence:.0f}"
        return p.grey(f"{stamp}  {analysis.price:9.2f}  attente        ({reason})")

    side = p.green("ACHAT") if c.direction > 0 else p.red("VENTE")
    turbo = p.magenta("*") if c.turbo else " "
    if not plan.valid:
        return f"{stamp}  {analysis.price:9.2f}  {side}{turbo} conf {c.confidence:3.0f}  "\
               f"{p.yellow('plan refuse: ' + plan.rejection[:34])}"
    return (
        f"{stamp}  {analysis.price:9.2f}  {side}{turbo} conf {c.confidence:3.0f}  "
        f"E {plan.entry:.2f}  SL {plan.stop:.2f}  "
        f"TP1 {plan.targets[0].price:.2f} ({plan.rr1:.1f}R)  "
        f"TP2 {plan.targets[1].price:.2f} ({plan.rr2:.1f}R)  {plan.lots:.2f}lot"
    )
