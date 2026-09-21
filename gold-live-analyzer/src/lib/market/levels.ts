import { startOfUtcDay } from './sessions';
import type { Candle } from './types';

/**
 * Niveaux de reference. Ce sont les prix ou la liquidite se concentre : c'est
 * la que l'or vient chercher les stops et que les pullbacks se retournent.
 */

export type LevelKind =
  | 'PLUS_HAUT_JOUR'
  | 'PLUS_BAS_JOUR'
  | 'PLUS_HAUT_VEILLE'
  | 'PLUS_BAS_VEILLE'
  | 'CLOTURE_VEILLE'
  | 'PLUS_HAUT_ASIE'
  | 'PLUS_BAS_ASIE'
  | 'PIVOT'
  | 'RESISTANCE'
  | 'SUPPORT'
  | 'ROND';

export interface Level {
  kind: LevelKind;
  label: string;
  price: number;
  /** 0 a 1 : importance relative pour la confluence. */
  weight: number;
}

export interface LevelMap {
  all: Level[];
  above: Level[];
  below: Level[];
  nearest: Level | null;
  dayHigh: number | null;
  dayLow: number | null;
  prevDayHigh: number | null;
  prevDayLow: number | null;
  prevDayClose: number | null;
  asiaHigh: number | null;
  asiaLow: number | null;
}

function dayBuckets(candles: Candle[]): Map<number, Candle[]> {
  const map = new Map<number, Candle[]>();
  for (const c of candles) {
    const day = startOfUtcDay(c.t);
    const list = map.get(day);
    if (list) list.push(c);
    else map.set(day, [c]);
  }
  return map;
}

function extremes(candles: Candle[]) {
  let high = -Infinity;
  let low = Infinity;
  for (const c of candles) {
    if (c.h > high) high = c.h;
    if (c.l < low) low = c.l;
  }
  return {
    high: Number.isFinite(high) ? high : null,
    low: Number.isFinite(low) ? low : null,
  };
}

/**
 * @param intraday bougies fines (M5/M15) pour les extremes de seance
 * @param htf bougies H1/H4 pour les swings majeurs
 */
export function buildLevels(intraday: Candle[], htf: Candle[], price: number): LevelMap {
  const levels: Level[] = [];
  const buckets = dayBuckets(intraday);
  const days = [...buckets.keys()].sort((a, b) => a - b);

  const todayKey = days[days.length - 1];
  const prevKey = days[days.length - 2];

  const today = todayKey !== undefined ? extremes(buckets.get(todayKey)!) : { high: null, low: null };
  const prev = prevKey !== undefined ? extremes(buckets.get(prevKey)!) : { high: null, low: null };
  const prevBars = prevKey !== undefined ? buckets.get(prevKey)! : [];
  const prevClose = prevBars.length > 0 ? prevBars[prevBars.length - 1].c : null;

  // Range asiatique du jour : 00:00 -> 07:00 UTC.
  const asiaBars =
    todayKey !== undefined
      ? buckets.get(todayKey)!.filter((c) => c.t - todayKey < 7 * 3_600_000)
      : [];
  const asia = extremes(asiaBars);

  const push = (kind: LevelKind, label: string, value: number | null, weight: number) => {
    if (value === null || !Number.isFinite(value)) return;
    levels.push({ kind, label, price: value, weight });
  };

  push('PLUS_HAUT_JOUR', 'Plus haut du jour', today.high, 0.9);
  push('PLUS_BAS_JOUR', 'Plus bas du jour', today.low, 0.9);
  push('PLUS_HAUT_VEILLE', 'Plus haut de la veille', prev.high, 0.8);
  push('PLUS_BAS_VEILLE', 'Plus bas de la veille', prev.low, 0.8);
  push('CLOTURE_VEILLE', 'Cloture de la veille', prevClose, 0.6);
  push('PLUS_HAUT_ASIE', 'Plus haut de la seance asiatique', asia.high, 0.75);
  push('PLUS_BAS_ASIE', 'Plus bas de la seance asiatique', asia.low, 0.75);

  // Pivots classiques sur la veille.
  if (prev.high !== null && prev.low !== null && prevClose !== null) {
    const pivot = (prev.high + prev.low + prevClose) / 3;
    push('PIVOT', 'Pivot journalier', pivot, 0.7);
    push('RESISTANCE', 'R1', 2 * pivot - prev.low, 0.55);
    push('SUPPORT', 'S1', 2 * pivot - prev.high, 0.55);
    push('RESISTANCE', 'R2', pivot + (prev.high - prev.low), 0.45);
    push('SUPPORT', 'S2', pivot - (prev.high - prev.low), 0.45);
  }

  // Swings H1/H4 marquants a proximite.
  for (const level of swingLevels(htf, price)) levels.push(level);

  // Chiffres ronds : sur l'or les paliers de 10 $ et 50 $ sont des aimants.
  for (const step of [50, 10]) {
    const base = Math.round(price / step) * step;
    for (const offset of [-step, 0, step]) {
      const value = base + offset;
      if (Math.abs(value - price) > 60) continue;
      push('ROND', `Palier ${value.toFixed(0)} $`, value, step === 50 ? 0.5 : 0.35);
    }
  }

  const deduped = dedupe(levels);
  const above = deduped.filter((l) => l.price > price).sort((a, b) => a.price - b.price);
  const below = deduped.filter((l) => l.price <= price).sort((a, b) => b.price - a.price);

  const nearest = [...deduped].sort(
    (a, b) => Math.abs(a.price - price) - Math.abs(b.price - price)
  )[0] ?? null;

  return {
    all: deduped,
    above,
    below,
    nearest,
    dayHigh: today.high,
    dayLow: today.low,
    prevDayHigh: prev.high,
    prevDayLow: prev.low,
    prevDayClose: prevClose,
    asiaHigh: asia.high,
    asiaLow: asia.low,
  };
}

function swingLevels(htf: Candle[], price: number): Level[] {
  if (htf.length < 12) return [];
  const out: Level[] = [];
  const strength = 2;

  for (let i = strength; i < htf.length - strength; i++) {
    let isHigh = true;
    let isLow = true;
    for (let j = i - strength; j <= i + strength; j++) {
      if (j === i) continue;
      if (htf[j].h >= htf[i].h) isHigh = false;
      if (htf[j].l <= htf[i].l) isLow = false;
    }
    if (isHigh && Math.abs(htf[i].h - price) < 80) {
      out.push({ kind: 'RESISTANCE', label: 'Sommet H1', price: htf[i].h, weight: 0.65 });
    }
    if (isLow && Math.abs(htf[i].l - price) < 80) {
      out.push({ kind: 'SUPPORT', label: 'Creux H1', price: htf[i].l, weight: 0.65 });
    }
  }
  return out.slice(-12);
}

/** Fusionne les niveaux distants de moins de 0,8 $ en gardant le plus fort. */
function dedupe(levels: Level[], tolerance = 0.8): Level[] {
  const sorted = [...levels].sort((a, b) => a.price - b.price);
  const out: Level[] = [];
  for (const level of sorted) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.price - level.price) <= tolerance) {
      if (level.weight > prev.weight) out[out.length - 1] = level;
      continue;
    }
    out.push(level);
  }
  return out;
}

/** Niveau le plus proche dans une direction donnee, au-dela d'une marge. */
export function nextLevel(map: LevelMap, price: number, direction: 'UP' | 'DOWN', minDistance = 0.5): Level | null {
  const pool = direction === 'UP' ? map.above : map.below;
  return pool.find((l) => Math.abs(l.price - price) >= minDistance) ?? null;
}

/** Confluence : un niveau fort colle au prix renforce un setup. */
export function levelConfluence(map: LevelMap, price: number, tolerance: number): Level | null {
  let best: Level | null = null;
  for (const level of map.all) {
    if (Math.abs(level.price - price) > tolerance) continue;
    if (!best || level.weight > best.weight) best = level;
  }
  return best;
}
