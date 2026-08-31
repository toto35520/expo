"""Backtest walk-forward du coeur technique.

Ce que ce module mesuré, et ce qu'il NE mesuré PAS - la distinction est
essentielle pour ne pas se raconter d'histoires :

  MESURE     : la partie technique du moteur (tendance, momentum, structure,
               participation, retour à la moyenne) fusionnee M15 + M5, avec
               les mêmes regles de stop et de cibles que le mode live.
  NE MESURE PAS : la microstructure (carnet et flux ne sont pas historises
               par l'API publique), la macro intraday et le filtre news.

Les taux de reussite qui en sortent sont donc un PLANCHER prudent de ce que
fait le moteur complet, pas une promesse de performance.

Conventions honnêtes appliquees :
  - toute décision a la bougie i n'utilise que les données jusqu'à i ;
  - l'entrée se fait à l'ouverture de la bougie i+1, jamais au cours de
    clôture qui a servi a décider ;
  - si le stop et la cible sont tous deux dans la même bougie, on compte le
    STOP (hypothese defavorable) ;
  - le spread est prélevé a l'entrée et a la sortie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from goldscalp.config import RiskConfig
from goldscalp.core.indicators import IndicatorSet, compute_indicators
from goldscalp.core.regime import detect_regime
from goldscalp.core.scoring import build_timeframe_view
from goldscalp.core.series import Series, resample
from goldscalp.core.structure import build_structure
from goldscalp.util import LOG, clamp, mean, safe_div

TAIL = 260          # profondeur suffisante pour tous les lookbacks utilises
WARMUP = 320


@dataclass
class Trade:
    index: int
    ts: int
    side: int              # +1 / -1
    entry: float
    stop: float
    tp1: float
    tp2: float
    risk_unit: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0
    r_result: float = 0.0
    confidence: float = 0.0
    hit_tp1: bool = False
    hit_tp2: bool = False


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    bars_tested: int = 0
    timeframe: str = "M5"
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.trades)

    @property
    def tp1_rate(self) -> float:
        return safe_div(sum(1 for t in self.trades if t.hit_tp1), self.count, 0.0)

    @property
    def tp2_rate(self) -> float:
        return safe_div(sum(1 for t in self.trades if t.hit_tp2), self.count, 0.0)

    @property
    def stop_rate(self) -> float:
        return safe_div(sum(1 for t in self.trades if t.exit_reason == "stop"), self.count, 0.0)

    @property
    def expectancy_r(self) -> float:
        return round(mean([t.r_result for t in self.trades]), 3) if self.trades else 0.0

    @property
    def total_r(self) -> float:
        return round(sum(t.r_result for t in self.trades), 2)

    @property
    def profit_factor(self) -> float:
        gains = sum(t.r_result for t in self.trades if t.r_result > 0)
        losses = -sum(t.r_result for t in self.trades if t.r_result < 0)
        return round(safe_div(gains, losses, 0.0), 2)

    @property
    def max_drawdown_r(self) -> float:
        peak = 0.0
        equity = 0.0
        worst = 0.0
        for trade in self.trades:
            equity += trade.r_result
            peak = max(peak, equity)
            worst = min(worst, equity - peak)
        return round(worst, 2)

    @property
    def avg_bars(self) -> float:
        return round(mean([t.bars_held for t in self.trades]), 1) if self.trades else 0.0

    @property
    def longs(self) -> int:
        return sum(1 for t in self.trades if t.side > 0)

    def win_rates(self) -> tuple[float, float]:
        """(probabilité TP1, probabilité TP2) pour alimenter l'espérance live."""
        if self.count < 12:
            return (0.0, 0.0)
        return (round(self.tp1_rate, 3), round(self.tp2_rate, 3))

    def summary(self) -> list[str]:
        if not self.trades:
            return ["Aucun trade généré sur la période : le moteur est reste sélectif."]
        return [
            f"{self.count} trades sur {self.bars_tested} bougies {self.timeframe} "
            f"({self.longs} achats / {self.count - self.longs} ventes)",
            f"TP1 touche {self.tp1_rate:.1%} | TP2 touche {self.tp2_rate:.1%} | stop {self.stop_rate:.1%}",
            f"Espérance {self.expectancy_r:+.3f} R par trade | cumul {self.total_r:+.1f} R",
            f"Facteur de profit {self.profit_factor} | drawdown max {self.max_drawdown_r} R",
            f"Duree moyenne {self.avg_bars} bougies",
        ]


def _slice_indicators(full: IndicatorSet, series: Series, index: int) -> IndicatorSet:
    """Vue des indicateurs telle qu'elle existait a la bougie `index`.

    Tous les indicateurs sont causals (la valeur en i ne dépend que des
    bougies 0..i) : tronquer les lignes reproduit donc exactement ce que le
    moteur aurait vu en direct. On ne garde que la queue, seule consultee.
    """
    start = max(0, index - TAIL + 1)
    stop = index + 1

    def cut(line):  # type: ignore[no-untyped-def]
        return line[start:stop]

    window = Series(series.timeframe, series.candles[start:stop], series.symbol)
    return IndicatorSet(
        series=window,
        ema9=cut(full.ema9), ema21=cut(full.ema21), ema50=cut(full.ema50),
        ema200=cut(full.ema200), hma20=cut(full.hma20), rsi14=cut(full.rsi14),
        stoch_k=cut(full.stoch_k), stoch_d=cut(full.stoch_d),
        srsi_k=cut(full.srsi_k), srsi_d=cut(full.srsi_d),
        macd_line=cut(full.macd_line), macd_signal=cut(full.macd_signal),
        macd_hist=cut(full.macd_hist), atr14=cut(full.atr14), adx14=cut(full.adx14),
        plus_di=cut(full.plus_di), minus_di=cut(full.minus_di),
        bb_upper=cut(full.bb_upper), bb_basis=cut(full.bb_basis), bb_lower=cut(full.bb_lower),
        bb_width=cut(full.bb_width), pct_b=cut(full.pct_b),
        kc_upper=cut(full.kc_upper), kc_lower=cut(full.kc_lower),
        squeeze_on=cut(full.squeeze_on), st_line=cut(full.st_line), st_dir=cut(full.st_dir),
        vwap=cut(full.vwap), vwap_upper=cut(full.vwap_upper), vwap_lower=cut(full.vwap_lower),
        obv=cut(full.obv), vol_z=cut(full.vol_z), er=cut(full.er), cci=cut(full.cci),
        willr=cut(full.willr), roc5=cut(full.roc5),
        dc_upper=cut(full.dc_upper), dc_mid=cut(full.dc_mid), dc_lower=cut(full.dc_lower),
        profile=None,          # recalcule ponctuellement, trop couteux par barre
        divergence=None,
        patterns=[],
    )


def run_backtest(series_m5: Series, series_m15: Optional[Series], risk: RiskConfig,
                 spread: float = 0.30, threshold: float = 0.35,
                 max_bars_held: int = 24, structure_every: int = 5,
                 max_trades: int = 400) -> BacktestResult:
    """Walk-forward sur la série M5, contexte M15 aligne temporellement."""
    closed = series_m5.closed_only
    result = BacktestResult(timeframe=series_m5.timeframe)
    result.warnings.append(
        "Backtest du coeur technique uniquement : microstructure, macro et "
        "filtre news ne sont pas rejouables et sont exclus."
    )
    if len(closed) < WARMUP + 60:
        result.warnings.append(
            f"Historique insuffisant ({len(closed)} bougies, {WARMUP + 60} requises)."
        )
        return result

    full = compute_indicators(closed)
    context = series_m15.closed_only if series_m15 is not None else resample(closed, "M15")
    full_context = compute_indicators(context) if len(context) > WARMUP // 3 else None

    candles = closed.candles
    open_trade: Optional[Trade] = None
    structure_cache = None
    structure_cache_at = -10_000
    tested = 0

    for i in range(WARMUP, len(candles) - 1):
        # -- gestion d'un trade ouvert -------------------------------------- #
        if open_trade is not None:
            bar = candles[i]
            open_trade.bars_held += 1
            side = open_trade.side
            # Distance d'origine : le R de référence ne change pas quand le
            # stop remonte a l'équilibre.
            risk_unit = open_trade.risk_unit

            hit_stop = bar.low <= open_trade.stop if side > 0 else bar.high >= open_trade.stop
            hit_tp1 = bar.high >= open_trade.tp1 if side > 0 else bar.low <= open_trade.tp1
            hit_tp2 = bar.high >= open_trade.tp2 if side > 0 else bar.low <= open_trade.tp2

            if hit_tp1 and not open_trade.hit_tp1 and not hit_stop:
                open_trade.hit_tp1 = True
                # On applique la même regle qu'en live : des TP1 touche, le
                # stop remonte a l'entrée. Sans ce deplacement, créditer la
                # sortie partielle en ignorant la perte du reliquat gonflé
                # artificiellement les résultats.
                open_trade.stop = open_trade.entry
            if hit_stop:
                # Hypothese defavorable : le stop passe avant la cible dans la
                # même bougie. Toute autre convention flatte le résultat.
                if open_trade.hit_tp1:
                    # Partiel pris a TP1, reliquat sorti au stop remonte a
                    # l'entrée : sa contribution est donc nulle, pas negative.
                    open_trade.r_result = risk.tp1_share * abs(open_trade.tp1 - open_trade.entry) / risk_unit
                    open_trade.exit_reason = "stop_apres_tp1"
                else:
                    open_trade.r_result = -1.0
                    open_trade.exit_reason = "stop"
                open_trade.exit_price = open_trade.stop
                result.trades.append(open_trade)
                open_trade = None
            elif hit_tp2:
                open_trade.hit_tp1 = True
                open_trade.hit_tp2 = True
                r1 = abs(open_trade.tp1 - open_trade.entry) / risk_unit
                r2 = abs(open_trade.tp2 - open_trade.entry) / risk_unit
                open_trade.r_result = risk.tp1_share * r1 + (1 - risk.tp1_share) * r2
                open_trade.exit_reason = "tp2"
                open_trade.exit_price = open_trade.tp2
                result.trades.append(open_trade)
                open_trade = None
            elif open_trade.bars_held >= max_bars_held:
                exit_price = bar.close - spread / 2 if side > 0 else bar.close + spread / 2
                raw = (exit_price - open_trade.entry) * side / risk_unit
                if open_trade.hit_tp1:
                    r1 = abs(open_trade.tp1 - open_trade.entry) / risk_unit
                    open_trade.r_result = risk.tp1_share * r1 + (1 - risk.tp1_share) * raw
                else:
                    open_trade.r_result = raw
                open_trade.exit_reason = "temps"
                open_trade.exit_price = exit_price
                result.trades.append(open_trade)
                open_trade = None
            if open_trade is not None:
                continue

        if len(result.trades) >= max_trades:
            break

        # -- évaluation du signal ------------------------------------------- #
        tested += 1
        ind = _slice_indicators(full, closed, i)
        regime = detect_regime(ind)

        if i - structure_cache_at >= structure_every or structure_cache is None:
            structure_cache = build_structure(ind.series, None, ind.atr_value, 3)
            structure_cache_at = i
        view = build_timeframe_view("M5", ind, structure_cache, regime, "test")
        score = view.score

        # Contexte M15 : la bougie M15 close la plus recente à l'instant i.
        if full_context is not None:
            ts = candles[i].ts
            ctx_index = _last_index_before(context, ts)
            if ctx_index is not None and ctx_index > WARMUP // 3:
                ctx_ind = _slice_indicators(full_context, context, ctx_index)
                ctx_regime = detect_regime(ctx_ind)
                ctx_structure = build_structure(ctx_ind.series, None, ctx_ind.atr_value, 4)
                ctx_view = build_timeframe_view("M15", ctx_ind, ctx_structure, ctx_regime, "contexte")
                score = score * 0.6 + ctx_view.score * 0.4

        if abs(score) < threshold or not regime.is_tradable:
            continue

        side = 1 if score > 0 else -1
        entry_bar = candles[i + 1]
        entry = entry_bar.open + spread / 2 if side > 0 else entry_bar.open - spread / 2

        atr_value = ind.atr_value
        stop_distance = clamp(
            atr_value * regime.stop_multiplier,
            max(atr_value * risk.min_stop_atr, spread * 3),
            atr_value * risk.max_stop_atr,
        )
        stop = entry - stop_distance * side
        tp1 = entry + stop_distance * risk.target_rr_tp1 * regime.target_multiplier * side
        tp2 = entry + stop_distance * risk.target_rr_tp2 * regime.target_multiplier * side

        open_trade = Trade(
            index=i + 1, ts=entry_bar.ts, side=side, entry=entry, stop=stop,
            tp1=tp1, tp2=tp2, risk_unit=stop_distance,
            confidence=round(abs(score) * 100, 1),
        )

    result.bars_tested = tested
    LOG.debug("backtest: %d trades sur %d bougies évaluées", len(result.trades), tested)
    return result


def _last_index_before(series: Series, ts: int) -> Optional[int]:
    """Index de la dernière bougie de `séries` dont l'ouverture précède `ts`."""
    low, high = 0, len(series) - 1
    found: Optional[int] = None
    while low <= high:
        mid = (low + high) // 2
        if series[mid].ts <= ts:
            found = mid
            low = mid + 1
        else:
            high = mid - 1
    return found
