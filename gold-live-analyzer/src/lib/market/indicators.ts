import type { Candle } from './types';

/**
 * Indicateurs techniques — implementations pures, sans dependance.
 * Chaque fonction renvoie un tableau aligne sur `values` : `null` tant que la
 * periode de chauffe n'est pas atteinte.
 */

export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;

  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;

  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** RSI de Wilder. */
export function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= period) return out;

  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = values[i] - values[i - 1];
    if (delta >= 0) gain += delta;
    else loss -= delta;
  }
  gain /= period;
  loss /= period;
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);

  for (let i = period + 1; i < values.length; i++) {
    const delta = values[i] - values[i - 1];
    const up = delta > 0 ? delta : 0;
    const down = delta < 0 ? -delta : 0;
    gain = (gain * (period - 1) + up) / period;
    loss = (loss * (period - 1) + down) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export function trueRange(candles: Candle[]): number[] {
  return candles.map((c, i) => {
    if (i === 0) return c.h - c.l;
    const prevClose = candles[i - 1].c;
    return Math.max(c.h - c.l, Math.abs(c.h - prevClose), Math.abs(c.l - prevClose));
  });
}

/** ATR de Wilder — la mesure de volatilite utilisee pour les stops. */
export function atr(candles: Candle[], period = 14): (number | null)[] {
  const tr = trueRange(candles);
  const out: (number | null)[] = new Array(candles.length).fill(null);
  if (candles.length < period) return out;

  let sum = 0;
  for (let i = 0; i < period; i++) sum += tr[i];
  let prev = sum / period;
  out[period - 1] = prev;

  for (let i = period; i < candles.length; i++) {
    prev = (prev * (period - 1) + tr[i]) / period;
    out[i] = prev;
  }
  return out;
}

export interface MacdPoint {
  macd: number;
  signal: number;
  histogram: number;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9
): (MacdPoint | null)[] {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const line: number[] = [];
  const lineIndex: number[] = [];

  for (let i = 0; i < values.length; i++) {
    const f = emaFast[i];
    const s = emaSlow[i];
    if (f !== null && s !== null) {
      line.push(f - s);
      lineIndex.push(i);
    }
  }

  const signal = ema(line, signalPeriod);
  const out: (MacdPoint | null)[] = new Array(values.length).fill(null);
  for (let j = 0; j < line.length; j++) {
    const sig = signal[j];
    if (sig === null) continue;
    out[lineIndex[j]] = { macd: line[j], signal: sig, histogram: line[j] - sig };
  }
  return out;
}

export interface BollingerPoint {
  upper: number;
  middle: number;
  lower: number;
  /** Largeur normalisee : (upper - lower) / middle. */
  bandwidth: number;
  /** Position du prix dans les bandes : 0 = bande basse, 1 = bande haute. */
  percentB: number;
}

export function bollinger(
  values: number[],
  period = 20,
  multiplier = 2
): (BollingerPoint | null)[] {
  const basis = sma(values, period);
  const out: (BollingerPoint | null)[] = new Array(values.length).fill(null);

  for (let i = period - 1; i < values.length; i++) {
    const mean = basis[i];
    if (mean === null) continue;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      variance += (values[j] - mean) ** 2;
    }
    const sd = Math.sqrt(variance / period);
    const upper = mean + multiplier * sd;
    const lower = mean - multiplier * sd;
    const width = Math.max(upper - lower, 1e-9);
    out[i] = {
      upper,
      middle: mean,
      lower,
      bandwidth: (upper - lower) / Math.max(mean, 1e-9),
      percentB: (values[i] - lower) / width,
    };
  }
  return out;
}

/** ADX de Wilder — mesure la force de tendance (pas sa direction). */
export function adx(candles: Candle[], period = 14): (number | null)[] {
  const len = candles.length;
  const out: (number | null)[] = new Array(len).fill(null);
  if (len < period * 2) return out;

  const plusDM: number[] = new Array(len).fill(0);
  const minusDM: number[] = new Array(len).fill(0);
  const tr = trueRange(candles);

  for (let i = 1; i < len; i++) {
    const upMove = candles[i].h - candles[i - 1].h;
    const downMove = candles[i - 1].l - candles[i].l;
    plusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0;
    minusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0;
  }

  let smoothTR = 0;
  let smoothPlus = 0;
  let smoothMinus = 0;
  for (let i = 1; i <= period; i++) {
    smoothTR += tr[i];
    smoothPlus += plusDM[i];
    smoothMinus += minusDM[i];
  }

  const dxSeries: { index: number; dx: number }[] = [];
  for (let i = period + 1; i < len; i++) {
    smoothTR = smoothTR - smoothTR / period + tr[i];
    smoothPlus = smoothPlus - smoothPlus / period + plusDM[i];
    smoothMinus = smoothMinus - smoothMinus / period + minusDM[i];

    const diPlus = smoothTR === 0 ? 0 : (100 * smoothPlus) / smoothTR;
    const diMinus = smoothTR === 0 ? 0 : (100 * smoothMinus) / smoothTR;
    const sum = diPlus + diMinus;
    dxSeries.push({ index: i, dx: sum === 0 ? 0 : (100 * Math.abs(diPlus - diMinus)) / sum });
  }

  if (dxSeries.length < period) return out;

  let adxValue = 0;
  for (let i = 0; i < period; i++) adxValue += dxSeries[i].dx;
  adxValue /= period;
  out[dxSeries[period - 1].index] = adxValue;

  for (let i = period; i < dxSeries.length; i++) {
    adxValue = (adxValue * (period - 1) + dxSeries[i].dx) / period;
    out[dxSeries[i].index] = adxValue;
  }
  return out;
}

/**
 * VWAP ancre sur la journee UTC. Les bougies de l'API ne portent qu'un volume
 * en ticks : c'est une approximation de l'activite, suffisante pour situer le
 * prix moyen pondere de la seance.
 */
export function sessionVwap(candles: Candle[]): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null);
  let day = -1;
  let cumPV = 0;
  let cumV = 0;

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const currentDay = Math.floor(c.t / 86_400_000);
    if (currentDay !== day) {
      day = currentDay;
      cumPV = 0;
      cumV = 0;
    }
    const typical = (c.h + c.l + c.c) / 3;
    const weight = c.v > 0 ? c.v : 1;
    cumPV += typical * weight;
    cumV += weight;
    out[i] = cumV > 0 ? cumPV / cumV : null;
  }
  return out;
}

export function last<T>(series: (T | null)[], offset = 0): T | null {
  const index = series.length - 1 - offset;
  return index >= 0 ? series[index] : null;
}

/** Pente normalisee d'une serie, exprimee en % de la valeur courante. */
export function slopePct(series: (number | null)[], lookback = 5): number | null {
  const current = last(series);
  const past = last(series, lookback);
  if (current === null || past === null || past === 0) return null;
  return ((current - past) / Math.abs(past)) * 100;
}
