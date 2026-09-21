import type { Bias, Candle } from './types';

/**
 * Lecture de structure de marche : swings, sequence HH/HL vs LH/LL,
 * cassure de structure (BOS) et changement de caractere (CHoCH).
 */

export interface Swing {
  index: number;
  t: number;
  price: number;
  kind: 'HIGH' | 'LOW';
}

export interface Leg {
  from: Swing;
  to: Swing;
  direction: 'UP' | 'DOWN';
  amplitude: number;
}

export interface StructureRead {
  swings: Swing[];
  highs: Swing[];
  lows: Swing[];
  bias: Bias;
  /** Libelle lisible : "creux et sommets ascendants", etc. */
  label: string;
  lastLeg: Leg | null;
  /** Dernier sommet / creux confirme — les niveaux que le marche vient chercher. */
  lastHigh: Swing | null;
  lastLow: Swing | null;
  /** Cassure de structure dans le sens de la tendance. */
  bos: { direction: 'UP' | 'DOWN'; level: number; at: number } | null;
  /** Cassure contre la tendance : premier signe de retournement. */
  choch: { direction: 'UP' | 'DOWN'; level: number; at: number } | null;
}

/**
 * Detection de swings par fractales : un sommet est un plus-haut entoure de
 * `strength` bougies de chaque cote. Les `strength` dernieres bougies ne
 * peuvent donc pas encore produire de swing confirme.
 *
 * La comparaison est stricte a gauche et large a droite. Ce detail compte :
 * sur l'or les sommets egaux (doubles sommets, plateaux de liquidite) sont
 * frequents, et une comparaison stricte des deux cotes ne detecterait aucun
 * swing sur ces zones — justement celles qui interessent le plus.
 */
export function findSwings(candles: Candle[], strength = 2): Swing[] {
  const swings: Swing[] = [];
  for (let i = strength; i < candles.length - strength; i++) {
    let isHigh = true;
    let isLow = true;

    for (let j = i - strength; j < i && (isHigh || isLow); j++) {
      if (candles[j].h >= candles[i].h) isHigh = false;
      if (candles[j].l <= candles[i].l) isLow = false;
    }
    for (let j = i + 1; j <= i + strength && (isHigh || isLow); j++) {
      if (candles[j].h > candles[i].h) isHigh = false;
      if (candles[j].l < candles[i].l) isLow = false;
    }

    if (isHigh) swings.push({ index: i, t: candles[i].t, price: candles[i].h, kind: 'HIGH' });
    if (isLow) swings.push({ index: i, t: candles[i].t, price: candles[i].l, kind: 'LOW' });
  }
  return swings.sort((a, b) => a.index - b.index);
}

export function analyzeStructure(candles: Candle[], strength = 2): StructureRead {
  const empty: StructureRead = {
    swings: [],
    highs: [],
    lows: [],
    bias: 'NEUTRE',
    label: 'pas assez de donnees',
    lastLeg: null,
    lastHigh: null,
    lastLow: null,
    bos: null,
    choch: null,
  };
  if (candles.length < strength * 2 + 6) return empty;

  const swings = findSwings(candles, strength);
  const highs = swings.filter((s) => s.kind === 'HIGH');
  const lows = swings.filter((s) => s.kind === 'LOW');
  if (highs.length < 2 || lows.length < 2) return { ...empty, swings, highs, lows };

  const h1 = highs[highs.length - 1];
  const h0 = highs[highs.length - 2];
  const l1 = lows[lows.length - 1];
  const l0 = lows[lows.length - 2];

  const higherHighs = h1.price > h0.price;
  const higherLows = l1.price > l0.price;

  let bias: Bias = 'NEUTRE';
  let label = 'structure en range, sommets et creux imbriques';
  if (higherHighs && higherLows) {
    bias = 'HAUSSIER';
    label = 'sommets et creux ascendants (HH / HL)';
  } else if (!higherHighs && !higherLows) {
    bias = 'BAISSIER';
    label = 'sommets et creux descendants (LH / LL)';
  } else if (higherHighs && !higherLows) {
    label = 'sommets ascendants mais creux qui glissent — expansion instable';
  } else {
    label = 'creux ascendants sous des sommets qui baissent — compression';
  }

  const ordered = [...swings].sort((a, b) => a.index - b.index);
  const lastTwo = ordered.slice(-2);
  const lastLeg: Leg | null =
    lastTwo.length === 2 && lastTwo[0].kind !== lastTwo[1].kind
      ? {
          from: lastTwo[0],
          to: lastTwo[1],
          direction: lastTwo[1].price > lastTwo[0].price ? 'UP' : 'DOWN',
          amplitude: Math.abs(lastTwo[1].price - lastTwo[0].price),
        }
      : null;

  // BOS / CHoCH : on regarde si une cloture recente a franchi le dernier swing.
  const recent = candles.slice(-Math.min(candles.length, strength + 4));
  let bos: StructureRead['bos'] = null;
  let choch: StructureRead['choch'] = null;

  for (const c of recent) {
    if (c.c > h1.price) {
      const event = { direction: 'UP' as const, level: h1.price, at: c.t };
      if (bias === 'BAISSIER') choch = event;
      else bos = event;
    }
    if (c.c < l1.price) {
      const event = { direction: 'DOWN' as const, level: l1.price, at: c.t };
      if (bias === 'HAUSSIER') choch = event;
      else bos = event;
    }
  }

  return { swings, highs, lows, bias, label, lastLeg, lastHigh: h1, lastLow: l1, bos, choch };
}

/** Retracement de Fibonacci sur la derniere jambe d'impulsion. */
export function fibZone(leg: Leg): {
  level382: number;
  level500: number;
  level618: number;
  level786: number;
  inZone: (price: number) => boolean;
} {
  const start = leg.from.price;
  const end = leg.to.price;
  const span = end - start;
  const at = (ratio: number) => end - span * ratio;

  const level382 = at(0.382);
  const level618 = at(0.618);
  const lo = Math.min(level382, level618);
  const hi = Math.max(level382, level618);

  return {
    level382,
    level500: at(0.5),
    level618,
    level786: at(0.786),
    inZone: (price: number) => price >= lo && price <= hi,
  };
}
