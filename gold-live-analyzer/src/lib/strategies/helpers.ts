import { anatomy, type Candle, type Direction } from '../market/types';
import type { StrategyLevels, TimeframeAnalysis } from './types';

/** Bougie de rejet : longue meche du bon cote et cloture qui repart. */
export function isRejection(candle: Candle, direction: Direction, minWick = 0.33): boolean {
  const a = anatomy(candle);
  if (direction === 'BUY') {
    return a.lowerRatio >= minWick && a.closePosition >= 0.55;
  }
  return a.upperRatio >= minWick && a.closePosition <= 0.45;
}

/** Avalement : le corps englobe celui de la bougie precedente. */
export function isEngulfing(prev: Candle, current: Candle, direction: Direction): boolean {
  const body = Math.abs(current.c - current.o);
  const prevBody = Math.abs(prev.c - prev.o);
  if (body <= prevBody) return false;
  if (direction === 'BUY') {
    return current.c > current.o && current.c > prev.o && current.o <= prev.c;
  }
  return current.c < current.o && current.c < prev.o && current.o >= prev.c;
}

/** Momentum : cloture franche dans le sens, corps dominant. */
export function isMomentum(candle: Candle, direction: Direction, atr: number): boolean {
  const a = anatomy(candle);
  if (a.bodyRatio < 0.55) return false;
  if (a.range < atr * 0.7) return false;
  return direction === 'BUY' ? a.bullish : !a.bullish;
}

export function confirmationCandle(
  candles: Candle[],
  direction: Direction,
  atr: number
): { ok: boolean; label: string } {
  if (candles.length < 2) return { ok: false, label: '' };
  const current = candles[candles.length - 1];
  const prev = candles[candles.length - 2];

  if (isEngulfing(prev, current, direction)) {
    return { ok: true, label: direction === 'BUY' ? 'avalement haussier' : 'avalement baissier' };
  }
  if (isRejection(current, direction)) {
    return {
      ok: true,
      label: direction === 'BUY' ? 'meche de rejet sous le support' : 'meche de rejet sur la resistance',
    };
  }
  if (isMomentum(current, direction, atr)) {
    return { ok: true, label: direction === 'BUY' ? 'bougie de momentum haussier' : 'bougie de momentum baissier' };
  }
  return { ok: false, label: '' };
}

/** Plus bas / plus haut des N dernieres bougies. */
export function extremeOf(candles: Candle[], lookback: number, kind: 'LOW' | 'HIGH'): number | null {
  const slice = candles.slice(-lookback);
  if (slice.length === 0) return null;
  return kind === 'LOW'
    ? Math.min(...slice.map((c) => c.l))
    : Math.max(...slice.map((c) => c.h));
}

/**
 * Construit entree / stop / objectifs.
 *
 * Le stop est place au-dela de la structure, avec un coussin ATR pour ne pas
 * se faire sortir par le bruit ; les objectifs sont exprimes en multiples du
 * risque, avec un objectif intermediaire pose sur la structure opposee.
 */
export function buildTradeLevels(params: {
  direction: Direction;
  entry: number;
  structuralStop: number;
  atr: number;
  /** Cible structurelle optionnelle (dernier sommet / creux). */
  structuralTarget?: number | null;
  cushion?: number;
  minStopAtr?: number;
}): StrategyLevels | null {
  const { direction, entry, structuralStop, atr } = params;
  const cushion = (params.cushion ?? 0.35) * atr;
  const minStop = (params.minStopAtr ?? 0.8) * atr;

  let stopLoss =
    direction === 'BUY' ? structuralStop - cushion : structuralStop + cushion;

  const rawRisk = Math.abs(entry - stopLoss);
  if (!Number.isFinite(rawRisk) || rawRisk <= 0) return null;

  // Stop trop serre = sortie sur le bruit : on impose un plancher en ATR.
  if (rawRisk < minStop) {
    stopLoss = direction === 'BUY' ? entry - minStop : entry + minStop;
  }

  const risk = Math.abs(entry - stopLoss);
  if (risk <= 0) return null;

  const sign = direction === 'BUY' ? 1 : -1;
  const tp1 = entry + sign * risk;
  const tp3 = entry + sign * risk * 3;

  let tp2 = entry + sign * risk * 2;
  const target = params.structuralTarget;
  if (target != null && Number.isFinite(target)) {
    const beyondTp1 = direction === 'BUY' ? target > tp1 : target < tp1;
    const beforeTp3 = direction === 'BUY' ? target < tp3 : target > tp3;
    if (beyondTp1 && beforeTp3) tp2 = target;
  }

  return { entry, stopLoss, takeProfits: [tp1, tp2, tp3] };
}

/** Rang percentile d'une valeur dans une serie (0 = plus bas historique). */
export function percentileRank(series: (number | null)[], value: number, lookback = 100): number | null {
  const pool = series.slice(-lookback).filter((v): v is number => v !== null);
  if (pool.length < 10) return null;
  const below = pool.filter((v) => v < value).length;
  return below / pool.length;
}

/**
 * Divergence RSI sur les N dernieres bougies : le prix fait un nouvel extreme
 * que le RSI ne confirme pas.
 */
export function rsiDivergence(
  candles: Candle[],
  rsiSeries: (number | null)[],
  direction: Direction,
  lookback = 20
): boolean {
  const n = candles.length;
  if (n < lookback + 2 || rsiSeries.length !== n) return false;

  const start = n - lookback;
  const recent = candles.slice(start);
  const recentRsi = rsiSeries.slice(start);

  if (direction === 'SELL') {
    let iMax = 0;
    for (let i = 1; i < recent.length; i++) if (recent[i].h > recent[iMax].h) iMax = i;
    if (iMax < recent.length - 3) return false;
    let jMax = 0;
    for (let j = 1; j < iMax - 2; j++) if (recent[j].h > recent[jMax].h) jMax = j;
    const rNow = recentRsi[iMax];
    const rPrev = recentRsi[jMax];
    if (rNow == null || rPrev == null) return false;
    return recent[iMax].h > recent[jMax].h && rNow < rPrev - 1.5;
  }

  let iMin = 0;
  for (let i = 1; i < recent.length; i++) if (recent[i].l < recent[iMin].l) iMin = i;
  if (iMin < recent.length - 3) return false;
  let jMin = 0;
  for (let j = 1; j < iMin - 2; j++) if (recent[j].l < recent[jMin].l) jMin = j;
  const rNow = recentRsi[iMin];
  const rPrev = recentRsi[jMin];
  if (rNow == null || rPrev == null) return false;
  return recent[iMin].l < recent[jMin].l && rNow > rPrev + 1.5;
}

/** Le contexte superieur valide-t-il cette direction ? */
export function contextAgrees(context: TimeframeAnalysis, direction: Direction): boolean {
  if (direction === 'BUY') return context.score >= 15;
  return context.score <= -15;
}

export function fmt(price: number): string {
  return price.toFixed(2);
}
