/**
 * Series de reference correlees (DXY, US10Y, ...).
 *
 * L'or ne se lit pas en vase clos : le DXY est son miroir mathematique et
 * l'US10Y son concurrent de rendement. Ce module aligne une serie secondaire
 * sur l'horodatage de la serie principale et expose les primitives dont la
 * strategie a besoin (range de Londres du DXY, pente de l'US10Y).
 *
 * Une reference absente ne casse jamais le moteur : le filtre renvoie
 * `available:false` et la config decide (`onMissing: 'pass' | 'block'`).
 */

import { loadCsv } from './csv.js';
import { MS_DAY, londonShiftMinutes, utcDayIndex, utcMinuteOfDay } from './time.js';

export class RefSeries {
  /**
   * @param {string} name identifiant lisible ('DXY', 'US10Y')
   * @param {import('./csv.js').Series} series
   */
  constructor(name, series) {
    this.name = name;
    this.s = series;
    /** @type {Map<number, {high:number, low:number, bars:number}>} */
    this.londonByDay = new Map();
    this._builtFor = null;
  }

  /** Charge une reference depuis un CSV au meme format que la serie principale. */
  static fromCsv(name, path) {
    return new RefSeries(name, loadCsv(path));
  }

  /**
   * Index de la derniere barre dont l'ouverture est <= ts (recherche binaire).
   * @param {number} ts
   * @returns {number} -1 si ts precede toute la serie
   */
  idxAt(ts) {
    const t = this.s.time;
    let lo = 0;
    let hi = this.s.length - 1;
    if (hi < 0 || t[0] > ts) return -1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (t[mid] <= ts) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  /**
   * L'horodatage demande est-il couvert par la reference ?
   * On exige que la barre trouvee soit assez proche (pas de trou de donnees).
   * @param {number} ts @param {number} maxLagMs
   */
  covers(ts, maxLagMs = 15 * 60_000) {
    const i = this.idxAt(ts);
    return i >= 0 && ts - this.s.time[i] <= maxLagMs;
  }

  /** Dernier prix connu de la reference a l'horodatage ts (NaN si non couvert). */
  priceAt(ts) {
    const i = this.idxAt(ts);
    return i < 0 ? NaN : this.s.close[i];
  }

  /**
   * Precalcule le High/Low de la session de Londres de la reference, jour par
   * jour, avec les memes bornes horaires que la strategie principale.
   * @param {{londonStart:number, londonEnd:number, londonEndInclusive:boolean, anchor:'gmt'|'local'}} win
   */
  buildLondonRanges(win) {
    const key = JSON.stringify(win);
    if (this._builtFor === key) return this;
    this.londonByDay.clear();
    const s = this.s;
    for (let i = 0; i < s.length; i++) {
      const ts = s.time[i];
      const shift = londonShiftMinutes(ts, win.anchor);
      const mod = utcMinuteOfDay(ts);
      const start = win.londonStart + shift;
      const end = win.londonEnd + shift;
      const inside = mod >= start && (win.londonEndInclusive ? mod <= end : mod < end);
      if (!inside) continue;
      const d = utcDayIndex(ts);
      let r = this.londonByDay.get(d);
      if (!r) {
        r = { high: -Infinity, low: Infinity, bars: 0 };
        this.londonByDay.set(d, r);
      }
      if (s.high[i] > r.high) r.high = s.high[i];
      if (s.low[i] < r.low) r.low = s.low[i];
      r.bars++;
    }
    this._builtFor = key;
    return this;
  }

  /** Range de Londres de la reference pour le jour contenant ts. */
  londonAt(ts) {
    return this.londonByDay.get(utcDayIndex(ts)) || null;
  }

  /**
   * La reference a-t-elle balaye son propre extreme de Londres dans la fenetre
   * [ts - lagMs, ts + lagMs] ? C'est le test de confluence miroir du DXY.
   *
   * @param {number} ts horodatage du balayage de l'or
   * @param {'high'|'low'} side extreme de la reference a tester
   * @param {number} lagMs tolerance temporelle
   * @param {number} minPenetration penetration minimale (unites de la reference)
   * @returns {{available:boolean, swept:boolean, penetration:number, extremeTs:number|null}}
   */
  sweptExtreme(ts, side, lagMs, minPenetration) {
    const lon = this.londonAt(ts);
    if (!lon || !Number.isFinite(lon.high) || !this.covers(ts)) {
      return { available: false, swept: false, penetration: NaN, extremeTs: null };
    }
    const s = this.s;
    const from = this.idxAt(ts - lagMs);
    const to = this.idxAt(ts + lagMs);
    if (from < 0 || to < from) {
      return { available: true, swept: false, penetration: 0, extremeTs: null };
    }
    let best = 0;
    let bestTs = null;
    for (let i = from; i <= to; i++) {
      const pen = side === 'high' ? s.high[i] - lon.high : lon.low - s.low[i];
      if (pen > best) {
        best = pen;
        bestTs = s.time[i];
      }
    }
    return {
      available: true,
      swept: best >= minPenetration,
      penetration: best,
      extremeTs: bestTs,
    };
  }

  /**
   * Rejet violent : apres avoir balaye son extreme, la reference revient-elle
   * franchement de l'autre cote ? (le "DXY rebondit violemment sur son support")
   *
   * @param {number} ts @param {'high'|'low'} side extreme balaye
   * @param {number} withinMs fenetre d'observation apres ts
   * @param {number} minMove mouvement minimal de retour (unites de la reference)
   */
  rejectedExtreme(ts, side, withinMs, minMove) {
    const lon = this.londonAt(ts);
    if (!lon || !this.covers(ts)) return { available: false, rejected: false, move: NaN };
    const s = this.s;
    const from = this.idxAt(ts);
    const to = this.idxAt(ts + withinMs);
    if (from < 0 || to < from) return { available: true, rejected: false, move: 0 };
    // Balayage du bas -> on veut une remontee au-dessus du bas de Londres.
    let move = 0;
    for (let i = from; i <= to; i++) {
      const m = side === 'low' ? s.close[i] - lon.low : lon.high - s.close[i];
      if (m > move) move = m;
    }
    return { available: true, rejected: move >= minMove, move };
  }

  /**
   * Pente de la reference sur les N dernieres barres avant ts, en % de sa
   * propre valeur. Sert au filtre de tendance US10Y.
   *
   * @param {number} ts @param {number} lookbackBars
   * @returns {{available:boolean, slopePct:number, last:number}}
   */
  slopePct(ts, lookbackBars) {
    if (!this.covers(ts)) return { available: false, slopePct: NaN, last: NaN };
    const i = this.idxAt(ts);
    const j = i - lookbackBars;
    if (j < 0) return { available: false, slopePct: NaN, last: NaN };
    const a = this.s.close[j];
    const b = this.s.close[i];
    if (!(a > 0)) return { available: false, slopePct: NaN, last: b };
    return { available: true, slopePct: ((b - a) / a) * 100, last: b };
  }
}

/**
 * Conteneur des references disponibles. Absentes = filtres degrades proprement.
 */
export class RefBundle {
  constructor({ dxy = null, us10y = null } = {}) {
    this.dxy = dxy;
    this.us10y = us10y;
  }

  /** Prepare les ranges de Londres des references selon la config. */
  prepare(cfg) {
    const win = {
      londonStart: cfg.resolved.londonStart,
      londonEnd: cfg.resolved.londonEnd,
      londonEndInclusive: cfg.sessions.londonEndInclusive,
      anchor: cfg.sessions.londonAnchor,
    };
    if (this.dxy) this.dxy.buildLondonRanges(win);
    if (this.us10y) this.us10y.buildLondonRanges(win);
    return this;
  }

  describe() {
    const d = (r) =>
      r
        ? {
            bars: r.s.length,
            from: new Date(r.s.time[0]).toISOString().slice(0, 10),
            to: new Date(r.s.time[r.s.length - 1]).toISOString().slice(0, 10),
          }
        : null;
    return { dxy: d(this.dxy), us10y: d(this.us10y) };
  }
}
