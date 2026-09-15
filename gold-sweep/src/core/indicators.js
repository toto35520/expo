/**
 * Indicateurs et primitives de structure de marche.
 * Toutes les fonctions sont causales : la valeur a l'index i n'utilise
 * jamais d'information posterieure a i (sauf `findSwings`, dont le decalage
 * de confirmation est explicite et respecte par le moteur).
 */

/**
 * ATR de Wilder. atr[i] est disponible a la cloture de la barre i.
 * Les `period` premieres valeurs sont NaN.
 * @param {import('./csv.js').Series} s
 * @param {number} period
 * @returns {Float64Array}
 */
export function atr(s, period) {
  const n = s.length;
  const out = new Float64Array(n).fill(NaN);
  if (n === 0) return out;

  let sum = 0;
  for (let i = 1; i < n; i++) {
    const prevClose = s.close[i - 1];
    const tr = Math.max(
      s.high[i] - s.low[i],
      Math.abs(s.high[i] - prevClose),
      Math.abs(s.low[i] - prevClose)
    );
    if (i <= period) {
      sum += tr;
      if (i === period) out[i] = sum / period;
    } else {
      out[i] = (out[i - 1] * (period - 1) + tr) / period;
    }
  }
  return out;
}

/**
 * Detection de swings fractals sur une plage de barres.
 *
 * Un swing bas a l'index j exige `lookback` barres de chaque cote dont le low
 * est STRICTEMENT superieur a low[j]. Il n'est donc confirme qu'a la barre
 * j + lookback : c'est cette latence que le moteur doit respecter pour ne pas
 * regarder dans le futur.
 *
 * @param {import('./csv.js').Series} s
 * @param {number} from index de debut (inclus)
 * @param {number} to index de fin (inclus)
 * @param {number} lookback
 * @returns {{lows: Array<{i:number, price:number, confirmedAt:number}>, highs: Array<{i:number, price:number, confirmedAt:number}>}}
 */
export function findSwings(s, from, to, lookback) {
  const lows = [];
  const highs = [];
  const lo = Math.max(from, lookback);
  const hi = Math.min(to, s.length - 1 - lookback);
  for (let j = lo; j <= hi; j++) {
    let isLow = true;
    let isHigh = true;
    for (let k = 1; k <= lookback; k++) {
      if (s.low[j - k] <= s.low[j] || s.low[j + k] <= s.low[j]) isLow = false;
      if (s.high[j - k] >= s.high[j] || s.high[j + k] >= s.high[j]) isHigh = false;
      if (!isLow && !isHigh) break;
    }
    if (isLow) lows.push({ i: j, price: s.low[j], confirmedAt: j + lookback });
    if (isHigh) highs.push({ i: j, price: s.high[j], confirmedAt: j + lookback });
  }
  return { lows, highs };
}

/**
 * Fair Value Gaps sur une plage de barres.
 *
 * Bearish FVG (trou laisse par une chute) : low[i-2] > high[i]
 *   -> zone [high[i], low[i-2]]. Le prix est SOUS la zone et doit remonter.
 *      bord proximal (touche en premier en remontant) = high[i] = bas de zone
 *      bord distal                                    = low[i-2] = haut de zone
 *
 * Bullish FVG (trou laisse par une hausse) : high[i-2] < low[i]
 *   -> zone [high[i-2], low[i]]. Le prix est AU-DESSUS et doit redescendre.
 *      bord proximal = low[i]      = haut de zone
 *      bord distal   = high[i-2]   = bas de zone
 *
 * @param {import('./csv.js').Series} s
 * @param {number} from index de la 3e barre du motif (inclus)
 * @param {number} to   index de la 3e barre du motif (inclus)
 * @param {'bearish'|'bullish'} kind
 * @returns {Array<{i:number, lower:number, upper:number, size:number, proximal:number, distal:number, kind:string}>}
 */
export function findFvgs(s, from, to, kind) {
  const out = [];
  const lo = Math.max(from, 2);
  const hi = Math.min(to, s.length - 1);
  for (let i = lo; i <= hi; i++) {
    if (kind === 'bearish') {
      const upper = s.low[i - 2];
      const lower = s.high[i];
      if (upper > lower) {
        out.push({ i, lower, upper, size: upper - lower, proximal: lower, distal: upper, kind });
      }
    } else {
      const lower = s.high[i - 2];
      const upper = s.low[i];
      if (upper > lower) {
        out.push({ i, lower, upper, size: upper - lower, proximal: upper, distal: lower, kind });
      }
    }
  }
  return out;
}

/**
 * Order Block : derniere bougie de sens oppose avant la jambe de deplacement.
 * Pour un setup vendeur, c'est la derniere bougie HAUSSIERE avant la chute.
 *
 * @param {import('./csv.js').Series} s
 * @param {number} legStart index de debut de la jambe (inclus)
 * @param {number} maxLookback nombre max de barres a remonter
 * @param {'sell'|'buy'} dir
 * @returns {{i:number, high:number, low:number, open:number, close:number}|null}
 */
export function findOrderBlock(s, legStart, maxLookback, dir) {
  const stop = Math.max(0, legStart - maxLookback);
  for (let i = legStart - 1; i >= stop; i--) {
    const bullish = s.close[i] > s.open[i];
    const bearish = s.close[i] < s.open[i];
    if ((dir === 'sell' && bullish) || (dir === 'buy' && bearish)) {
      return { i, high: s.high[i], low: s.low[i], open: s.open[i], close: s.close[i] };
    }
  }
  return null;
}

/**
 * Zone d'un Order Block selon le mode choisi.
 * @returns {{lower:number, upper:number, proximal:number, distal:number}}
 */
export function orderBlockZone(ob, zone, dir) {
  let lower;
  let upper;
  if (zone === 'body') {
    lower = Math.min(ob.open, ob.close);
    upper = Math.max(ob.open, ob.close);
  } else if (zone === 'upperHalf') {
    const mid = (ob.high + ob.low) / 2;
    lower = dir === 'sell' ? mid : ob.low;
    upper = dir === 'sell' ? ob.high : mid;
  } else {
    lower = ob.low;
    upper = ob.high;
  }
  // Pour une vente le prix remonte vers la zone : il touche d'abord le bas.
  const proximal = dir === 'sell' ? lower : upper;
  const distal = dir === 'sell' ? upper : lower;
  return { lower, upper, proximal, distal };
}

/**
 * Interpole un niveau dans une zone selon la convention du projet :
 * level=0 -> bord proximal (rempli le plus tot), level=1 -> bord distal.
 */
export function zoneLevel(z, level) {
  return z.proximal + (z.distal - z.proximal) * level;
}
