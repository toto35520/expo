import type { AnalysisContext, Sizing, TradePlan } from './types';

/**
 * Dimensionnement XAUUSD.
 *
 * 1 lot standard = 100 onces → 1 $ de mouvement = 100 $ par lot.
 *   lots = risque($) / (distance de stop en $ × taille du contrat)
 *
 * Arrondi vers le bas au pas du broker : on ne dépasse jamais le risque demandé.
 */
export function computeSizing(plan: TradePlan, ctx: AnalysisContext): Sizing | null {
  if (!plan.hasTrade || !plan.entry || !plan.stop) return null;

  const stopDistance = Math.abs(plan.entry - plan.stop);
  if (stopDistance <= 0) return null;

  const contractSize = ctx.contractSize > 0 ? ctx.contractSize : 100;
  const minLot = ctx.minLot > 0 ? ctx.minLot : 0.01;

  const riskRequested = (ctx.accountSize * ctx.riskPercent) / 100;
  const valuePerDollarPerLot = contractSize; // $ de P&L par 1 $ de mouvement, par lot
  const rawLots = riskRequested / (stopDistance * valuePerDollarPerLot);

  // Arrondi vers le bas au pas minimum du broker.
  const steps = Math.floor(rawLots / minLot);
  const lots = round(steps * minLot, 4);
  const riskActual = round(lots * stopDistance * valuePerDollarPerLot, 2);

  const reward1 = Math.abs(plan.tp1 - plan.entry);
  const reward2 = Math.abs(plan.tp2 - plan.entry);

  return {
    lots,
    stopDistance: round(stopDistance, 2),
    riskRequested: round(riskRequested, 2),
    riskActual,
    valuePerDollarPerLot,
    rr1: plan.tp1 ? round(reward1 / stopDistance, 2) : 0,
    rr2: plan.tp2 ? round(reward2 / stopDistance, 2) : 0,
    belowMinLot: lots < minLot,
  };
}

function round(n: number, d: number): number {
  const f = Math.pow(10, d);
  return Math.round(n * f) / f;
}

/** R réalisé sur un trade clôturé. */
export function realizedR(
  entry: number,
  stop: number,
  exit: number,
  direction: 'LONG' | 'SHORT' | 'NONE',
): number {
  const risk = Math.abs(entry - stop);
  if (risk <= 0 || direction === 'NONE') return 0;
  const move = direction === 'LONG' ? exit - entry : entry - exit;
  return round(move / risk, 2);
}
