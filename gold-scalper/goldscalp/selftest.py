"""Auto-verification du moteur.

Chaque contrôle porte sur une propriété qui, si elle casse, produit un
mauvais trade sans jamais lever d'exception. C'est exactement ce type de bug
qu'un outil de trading doit détecter tout seul.
"""

from __future__ import annotations

import random
from typing import Callable, Optional

from goldscalp.config import Config, RiskConfig
from goldscalp.core import indicators as ind
from goldscalp.core.backtest import run_backtest
from goldscalp.core.calibration import Calibration, add_anchor
from goldscalp.core.series import Candle, Series, resample
from goldscalp.data.synthetic import generate_series
from goldscalp.util import now_ms


class CheckFailure(AssertionError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


# --------------------------------------------------------------------------- #
# Controles
# --------------------------------------------------------------------------- #

def check_indicator_bounds() -> str:
    rising = [float(i) for i in range(1, 60)]
    falling = list(reversed(rising))
    _require(ind.last_valid(ind.rsi(rising, 14)) == 100.0, "RSI d'une série croissante doit valoir 100")
    _require(ind.last_valid(ind.rsi(falling, 14)) == 0.0, "RSI d'une série decroissante doit valoir 0")

    flat = [7.5] * 80
    _require(abs(ind.last_valid(ind.ema(flat, 21)) - 7.5) < 1e-9, "EMA d'une constante doit rendre la constante")
    _require(abs(ind.last_valid(ind.sma(flat, 21)) - 7.5) < 1e-9, "SMA d'une constante doit rendre la constante")

    series = generate_series("M1", 600, 2400.0, seed=1)
    iset = ind.compute_indicators(series.closed_only)
    rsi_value = ind.last_valid(iset.rsi14)
    _require(rsi_value is not None and 0 <= rsi_value <= 100, "RSI hors de [0, 100]")
    for name in ("stoch_k", "srsi_k"):
        value = ind.last_valid(getattr(iset, name))
        _require(value is None or -0.001 <= value <= 100.001, f"{name} hors de [0, 100]")
    pct = ind.last_valid(iset.pct_b)
    _require(pct is None or -3 <= pct <= 4, "%B aberrant")
    _require(iset.atr_value > 0, "ATR doit etre strictement positif")
    profile = iset.profile
    _require(profile is not None and profile.val <= profile.poc <= profile.vah,
             "profil de volume incohérent : VAL <= POC <= VAH attendu")
    return "indicateurs dans leurs bornés"


def check_causality() -> str:
    """Un indicateur ne doit jamais dépendre du futur.

    On calcule sur la série complète, puis sur la série tronquee, et on
    vérifie que les valeurs communes sont identiques. Une divergence signale
    une fuite temporelle - le bug le plus toxique d'un backtest.
    """
    series = generate_series("M5", 500, 2400.0, seed=9).closed_only
    full = ind.compute_indicators(series)
    cut = 400
    truncated = ind.compute_indicators(Series(series.timeframe, series.candles[:cut], series.symbol))

    for name in ("ema21", "rsi14", "atr14", "adx14", "macd_hist", "bb_upper", "vwap", "obv", "er"):
        line_full = getattr(full, name)
        line_cut = getattr(truncated, name)
        a, b = line_full[cut - 1], line_cut[-1]
        if a is None and b is None:
            continue
        _require(a is not None and b is not None, f"{name} : définition incohérente après troncature")
        _require(abs(a - b) < max(abs(a) * 1e-6, 1e-6),
                 f"{name} dépend du futur : {a} sur série complète contre {b} sur série tronquee")
    return "indicateurs causals (aucune fuite du futur)"


def check_resample() -> str:
    m1 = generate_series("M1", 1200, 2400.0, seed=3)
    m5 = resample(m1, "M5")
    _require(len(m5) >= 200, "rééchantillonnage M1 -> M5 trop court")
    bucket = [c for c in m1 if m5[10].ts <= c.ts < m5[10].ts + 5 * 60000]
    _require(abs(m5[10].high - max(c.high for c in bucket)) < 1e-9, "le haut agrégé ne correspond pas")
    _require(abs(m5[10].low - min(c.low for c in bucket)) < 1e-9, "le bas agrégé ne correspond pas")
    _require(abs(m5[10].open - bucket[0].open) < 1e-9, "l'ouverture agrégée ne correspond pas")
    _require(abs(m5[10].close - bucket[-1].close) < 1e-9, "la clôture agrégée ne correspond pas")
    return "rééchantillonnage exact (OHLC préservé)"


def check_calibration() -> str:
    calibration = add_anchor(Calibration(), 2400.0, 2407.00, 2407.30)
    _require(abs(calibration.to_mt5(2400.0) - 2407.15) < 0.01, "le décalage simple est mal applique")
    _require(abs(calibration.to_bybit(calibration.to_mt5(2412.34)) - 2412.34) < 1e-6,
             "aller-retour de conversion non reversible")
    _require(calibration.ask(2400.0) > calibration.bid(2400.0), "ask doit etre au-dessus du bid")

    # Ancrages colles : la pente n'est pas identifiable, beta doit rester à 1.
    clustered = Calibration()
    for price in (2400.0, 2400.3, 2400.1, 2399.9):
        clustered = add_anchor(clustered, price, price + 7.0, price + 7.3)
    _require(not clustered.slope_fitted and clustered.beta == 1.0,
             "une pente a été ajustée sur des ancrages trop proches : résultat non identifiable")

    # Ancrages écartés : la pente doit etre retrouvee.
    spread_out = Calibration()
    for price in (2350.0, 2400.0, 2450.0, 2500.0):
        target = 5.0 + 1.002 * price
        spread_out = add_anchor(spread_out, price, target - 0.15, target + 0.15)
    _require(spread_out.slope_fitted, "la pente aurait du etre identifiée sur des ancrages écartés")
    _require(abs(spread_out.beta - 1.002) < 1e-4, f"pente mal estimée : {spread_out.beta}")
    return "calibration : conversions, identifiabilité de la pente et garde-fous"


def check_no_signal_flip() -> str:
    """Une pénalité ne doit jamais inverser le sens du signal."""
    from goldscalp import engine

    config = Config()
    calibration = add_anchor(Calibration(), 2400.0, 2407.0, 2407.3)
    day = (now_ms() // 86400000) * 86400000
    checked = 0
    for seed in range(12):
        for hour in (3, 14, 22):
            analysis = engine.run(config, calibration, demo=True, seed=seed,
                                  demo_end_ms=day + hour * 3600000)
            confluence = analysis.confluence
            if abs(confluence.raw_score) < 0.02:
                continue
            checked += 1
            flipped = (confluence.raw_score > 0) != (confluence.final_score > 0)
            if flipped:
                additive = sum(m.value for m in confluence.modifiers if m.kind == "additif")
                _require(
                    abs(additive) > abs(confluence.raw_score),
                    "le signal a change de sens sans qu'un modificateur additif "
                    "le justifie : une atténuation a inverse le verdict",
                )
    _require(checked > 10, "echantillon de contrôle trop faible")
    return f"aucune inversion de signal illegitime ({checked} cas vérifiés)"


def check_plan_invariants() -> str:
    """Le plan doit etre cohérent : stop du bon cote, cibles ordonnées, R:R tenu."""
    from goldscalp import engine

    config = Config()
    calibration = add_anchor(Calibration(), 2400.0, 2407.0, 2407.3)
    day = (now_ms() // 86400000) * 86400000
    plans = 0
    for seed in range(40):
        analysis = engine.run(config, calibration, demo=True, seed=seed,
                              demo_end_ms=day + 14 * 3600000)
        plan = analysis.plan
        if not plan.valid:
            continue
        plans += 1
        direction = 1 if plan.side == "ACHAT" else -1
        _require((plan.stop - plan.entry) * direction < 0,
                 f"stop du mauvais cote (seed {seed}) : {plan.side} entrée {plan.entry} stop {plan.stop}")
        for target in plan.targets:
            _require((target.price - plan.entry) * direction > 0,
                     f"cible {target.label} du mauvais cote (seed {seed})")
        tp1, tp2 = plan.targets[0], plan.targets[1]
        _require((tp2.price - tp1.price) * direction > 0,
                 f"TP2 doit etre au-dela de TP1 (seed {seed})")
        _require(plan.rr1 >= config.risk.min_rr_tp1 - 1e-6,
                 f"R:R de TP1 sous le minimum (seed {seed}) : {plan.rr1}")
        _require(plan.rr2 > plan.rr1, f"TP2 doit offrir plus que TP1 (seed {seed})")
        _require(plan.lots >= 0.01, f"taille invalidé (seed {seed}) : {plan.lots}")
        _require(abs(plan.stop_distance - abs(plan.entry - plan.stop)) < 0.02,
                 f"distance de stop incohérente (seed {seed})")
        expected = plan.lots * plan.stop_distance * config.market.contract_size
        _require(abs(plan.risk_amount - expected) < max(expected * 0.02, 0.5),
                 f"le risque annoncé ne correspond pas à la taille (seed {seed})")
    _require(plans >= 3, f"trop peu de plans générés pour valider ({plans})")
    return f"invariants du plan respectes ({plans} plans vérifiés)"


def check_backtest_has_no_edge_on_noise() -> str:
    """Sur une marché aléatoire, l'espérance doit tourner autour de zero.

    Une espérance nettement positive sur du bruit pur ne signifie pas que le
    moteur est bon : elle signifie qu'il triche (fuite du futur ou comptage
    favorable des sorties).
    """
    rng = random.Random(4242)
    price = 2400.0
    step = 60000
    start = now_ms() - 14000 * step
    candles = []
    for i in range(14000):
        move = rng.gauss(0, 0.28)
        open_price = price
        close = open_price + move
        high = max(open_price, close) + abs(rng.gauss(0, 0.10))
        low = min(open_price, close) - abs(rng.gauss(0, 0.10))
        candles.append(Candle(start + i * step, open_price, high, low, close,
                              abs(rng.gauss(500, 120))))
        price = close
    m1 = Series("M1", candles)
    result = run_backtest(resample(m1, "M5"), resample(m1, "M15"), RiskConfig(), spread=0.30)
    _require(result.count >= 20, f"echantillon trop faible ({result.count} trades)")
    _require(
        result.expectancy_r < 0.12,
        f"espérance de {result.expectancy_r:+.3f} R sur du bruit pur : "
        "le backtest surestimé les résultats (fuite du futur ou comptage favorable)",
    )
    return f"backtest sans edge artificiel sur du bruit ({result.count} trades, {result.expectancy_r:+.3f} R)"


def check_micro_bounds() -> str:
    from goldscalp.data.synthetic import generate_derivatives, generate_orderbook, generate_trades
    from goldscalp.core.microstructure import build_micro

    for bias in (-0.8, 0.0, 0.8):
        book = generate_orderbook(2400.0, seed=1, bias=bias)
        trades = generate_trades(2400.0, 400, seed=2, buy_ratio=0.5 + bias * 0.3)
        micro = build_micro(book, trades, generate_derivatives(seed=3, bias=bias), 2401.0, 2400.0)
        _require(-1.0 <= micro.score <= 1.0, f"score microstructure hors bornés : {micro.score}")
        _require(-1.0 <= micro.imbalance <= 1.0, f"déséquilibre hors bornés : {micro.imbalance}")
    # Un carnet fortement acheteur doit produire un déséquilibre positif.
    strong = build_micro(generate_orderbook(2400.0, seed=5, bias=0.6),
                         generate_trades(2400.0, 400, seed=6, buy_ratio=0.85),
                         generate_derivatives(seed=7, bias=0.5), 2402.0, 2400.0)
    _require(strong.score > 0.2, f"flux nettement acheteur mal interprété : {strong.score}")
    return "microstructure : bornés et sens respectes"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("bornés des indicateurs", check_indicator_bounds),
    ("causalite (pas de fuite du futur)", check_causality),
    ("reechantillonnage", check_resample),
    ("calibration Bybit -> MT5", check_calibration),
    ("microstructure", check_micro_bounds),
    ("non-inversion du signal", check_no_signal_flip),
    ("invariants du plan de trade", check_plan_invariants),
    ("honnêteté du backtest", check_backtest_has_no_edge_on_noise),
]


def run_selftest(palette: Optional[object] = None) -> int:
    from goldscalp.ui.console import make_palette

    p = palette or make_palette()
    print(p.bold("\nAUTO-VÉRIFICATION DU MOTEUR"))  # type: ignore[attr-defined]
    print("-" * 70)
    failures = 0
    for label, check in CHECKS:
        try:
            detail = check()
        except CheckFailure as exc:
            failures += 1
            print(f"  {p.red('ECHEC')}  {label}")          # type: ignore[attr-defined]
            print(f"         {exc}")
        except Exception as exc:                            # pragma: no cover
            failures += 1
            print(f"  {p.red('ERREUR')} {label} : {type(exc).__name__}: {exc}")  # type: ignore[attr-defined]
        else:
            print(f"  {p.green('OK')}     {label}")         # type: ignore[attr-defined]
            print(f"         {p.grey(detail)}")             # type: ignore[attr-defined]
    print("-" * 70)
    if failures:
        print(p.red(f"  {failures} contrôle(s) en échec sur {len(CHECKS)}"))  # type: ignore[attr-defined]
        return 1
    print(p.green(f"  {len(CHECKS)} contrôles passés"))     # type: ignore[attr-defined]
    return 0
