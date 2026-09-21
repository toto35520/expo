import { levelConfluence } from '../market/levels';
import type { Direction } from '../market/types';
import { buildTradeLevels, confirmationCandle, extremeOf, fmt, rsiDivergence } from './helpers';
import { Checklist, emptyResult, type Strategy, type StrategyResult } from './types';

/**
 * Retour a la moyenne en range.
 *
 * Strategie explicitement contre-tendance, donc bridee : elle ne se declenche
 * que si le contexte superieur est plat (pas de tendance a contrarier), que le
 * prix touche une extremite de Bollinger sur un niveau de reference, et que le
 * RSI est en exces avec divergence.
 */
export const meanReversionStrategy: Strategy = (ctx): StrategyResult => {
  const entry = ctx.tf[ctx.entryTf];
  const context = ctx.tf[ctx.contextTf];
  const base = emptyResult(
    'retour-moyenne',
    'Retour a la moyenne en range',
    'RETOURNEMENT',
    "Je surveille les exces sur les bords de range quand la tendance est plate."
  );

  if (!entry.ready || entry.atr === null || entry.bollinger === null || entry.rsi === null) {
    return base;
  }

  const atr = entry.atr;
  const bb = entry.bollinger;
  const rsi = entry.rsi;
  const price = ctx.price;

  const rangeContext = Math.abs(context.score) < 25;
  const weakTrend = entry.adx === null || entry.adx < 22;

  let direction: Direction | null = null;
  if (bb.percentB >= 0.95 && rsi >= 68) direction = 'SELL';
  else if (bb.percentB <= 0.05 && rsi <= 32) direction = 'BUY';

  if (!direction) {
    return {
      ...base,
      readiness: rangeContext ? 0.2 : 0.05,
      watching: rangeContext
        ? `Marche en range — j'attends un exces (RSI ${rsi.toFixed(0)}, position dans les bandes ${Math.round(bb.percentB * 100)} %).`
        : 'Tendance marquee : je desactive le retour a la moyenne.',
    };
  }

  const bull = direction === 'BUY';
  const level = levelConfluence(ctx.levels, price, 0.8 * atr);
  const divergence = rsiDivergence(entry.candles.slice(0, -1), entry.rsiSeries.slice(0, -1), direction, 24);
  const confirmation = confirmationCandle(entry.candles.slice(0, -1), direction, atr);

  const list = new Checklist()
    .add(rangeContext, 2.5, `Contexte ${ctx.contextTf} sans tendance nette`,
      `Tendance ${ctx.contextTf} marquee : trade a contre-courant deconseille`)
    .add(weakTrend, 1.5, `ADX faible (${entry.adx?.toFixed(0) ?? '-'}) : marche en range`,
      `ADX a ${entry.adx?.toFixed(0)} : la tendance peut prolonger l exces`)
    .add(true, 1.5, `Exces sur bande ${bull ? 'basse' : 'haute'} de Bollinger (RSI ${rsi.toFixed(0)})`)
    .add(level !== null, 1.5, level ? `Exces au contact de ${level.label} (${fmt(level.price)})` : '',
      'Exces sans niveau de reference pour le soutenir')
    .add(divergence, 1.5, 'Divergence RSI confirmee',
      'Pas de divergence RSI : l exces peut se prolonger')
    .add(confirmation.ok, 2, `Declencheur : ${confirmation.label}`,
      'Pas encore de bougie de retournement');

  const triggered = rangeContext && confirmation.ok && (divergence || level !== null);

  const structuralStop = bull
    ? extremeOf(entry.candles, 6, 'LOW') ?? price - atr
    : extremeOf(entry.candles, 6, 'HIGH') ?? price + atr;

  const levels = buildTradeLevels({
    direction,
    entry: bull ? ctx.quote.ask : ctx.quote.bid,
    structuralStop,
    atr,
    // En range, l'objectif naturel est le milieu de bande.
    structuralTarget: bb.middle,
    cushion: 0.25,
  });

  return {
    ...base,
    direction,
    readiness: list.readiness,
    triggered,
    score: Math.round(list.readiness * 100 * 0.9), // decote : contre-tendance
    reasons: list.reasons.filter(Boolean),
    missing: list.missing.filter(Boolean),
    levels,
    watching: triggered
      ? `Retour a la moyenne ${direction} arme (objectif ${fmt(bb.middle)}).`
      : `Exces detecte — ${list.missing.filter(Boolean)[0] ?? 'attente de confirmation'}.`,
  };
};
