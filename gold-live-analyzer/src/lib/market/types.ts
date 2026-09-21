/** Types partages par tout le moteur d'analyse. */

export interface Candle {
  /** Debut de la bougie, epoch ms UTC. */
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export const TIMEFRAMES = ['M1', 'M5', 'M15', 'H1', 'H4'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const TF_MINUTES: Record<Timeframe, number> = {
  M1: 1,
  M5: 5,
  M15: 15,
  H1: 60,
  H4: 240,
};

export const TF_MS: Record<Timeframe, number> = {
  M1: 60_000,
  M5: 300_000,
  M15: 900_000,
  H1: 3_600_000,
  H4: 14_400_000,
};

export type Direction = 'BUY' | 'SELL';
export type Bias = 'HAUSSIER' | 'BAISSIER' | 'NEUTRE';

export interface Quote {
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  ts: number;
}

export function biasToDirection(bias: Bias): Direction | null {
  if (bias === 'HAUSSIER') return 'BUY';
  if (bias === 'BAISSIER') return 'SELL';
  return null;
}

/** Corps, meche haute, meche basse en valeur absolue de prix. */
export function anatomy(candle: Candle) {
  const range = Math.max(candle.h - candle.l, 1e-9);
  const body = Math.abs(candle.c - candle.o);
  const upper = candle.h - Math.max(candle.c, candle.o);
  const lower = Math.min(candle.c, candle.o) - candle.l;
  return {
    range,
    body,
    upper,
    lower,
    bodyRatio: body / range,
    upperRatio: upper / range,
    lowerRatio: lower / range,
    bullish: candle.c >= candle.o,
    /** Position de la cloture dans le range : 0 = sur le bas, 1 = sur le haut. */
    closePosition: (candle.c - candle.l) / range,
  };
}
