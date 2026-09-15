/**
 * Machine a etats de la strategie "NY Open Liquidity Sweep" (XAUUSD).
 *
 * CE FICHIER EST LE CŒUR PARTAGE : le backtest et le moniteur live consomment
 * exactement le meme code. Ce qui est valide sur 5 ans d'historique est donc
 * litteralement ce qui tourne sur le compte reel.
 *
 * Contrat de causalite : `onBar(s, i)` ne lit JAMAIS un index > i.
 * Les swings fractals ne sont consideres qu'apres leur barre de confirmation
 * (j + swingLookback <= i), ce qui elimine le biais de look-ahead.
 *
 * Phases (conformes a la description de la strategie) :
 *   Phase 1  IDLE    -> ARMED     : range de Londres 07:00-12:00 GMT fige
 *   Phase 2  ARMED   -> SWEPT     : balayage du High/Low de Londres 13:00-14:30
 *   Phase 3  SWEPT   -> CONFIRMED : MSS + deplacement + Fair Value Gap
 *   Phase 4  CONFIRMED           : emission du setup (limite, SL, TP)
 */

import { isNfpDay, newsSpike } from './calendar.js';
import { resolveDistance, roundPrice, toPips } from './config.js';
import {
  findFvgs,
  findOrderBlock,
  orderBlockZone,
  zoneLevel,
} from './indicators.js';
import {
  MS_DAY,
  isoDate,
  londonShiftMinutes,
  nyShiftMinutes,
  utcDayIndex,
  utcDayOfWeek,
  utcMinuteOfDay,
} from './time.js';

/** Etats du plan journalier. */
export const Phase = {
  IDLE: 'IDLE',
  ARMED: 'ARMED',
  SWEPT: 'SWEPT',
  DONE: 'DONE',
  SKIPPED: 'SKIPPED',
};

/** Toutes les raisons de rejet tracees dans l'entonnoir de diagnostic. */
export const REJECTIONS = [
  'dayOutOfRange',
  'dayWeekday',
  'daySkipDate',
  'dayLondonIncomplete',
  'dayLondonRangeTooSmall',
  'dayLondonRangeTooLarge',
  'dayAtrRegime',
  'sweepNone',
  'sweepSideDisabled',
  'sweepTooFar',
  'sweepNoCloseBack',
  'sweepWindowExpired',
  'mssNoStructure',
  'mssNoBreak',
  'mssTimeout',
  'mssNoDisplacement',
  'fvgMissing',
  'fvgTooSmall',
  'entryNoZone',
  'entryBehindMarket',
  'slTooTight',
  'slTooWide',
  'rrTooLow',
  'rrTooHigh',
  'filterNews',
  'filterDailyBias',
  'filterPdhPdl',
  'filterSignalTooEarly',
  'filterSilverBullet',
  'filterPremium',
  'filterDxy',
  'filterUs10y',
  'filterRefMissing',
  'filterInducement',
  'dayNewsBlackout',
  'filterNewsSpike',
];

function emptyFunnel() {
  const f = {
    barsSeen: 0,
    daysSeen: 0,
    daysArmed: 0,
    daysSwept: 0,
    daysSweptHigh: 0,
    daysSweptLow: 0,
    daysMssBreak: 0,
    setupsEmitted: 0,
    setupsSell: 0,
    setupsBuy: 0,
    rejected: {},
  };
  for (const r of REJECTIONS) f.rejected[r] = 0;
  return f;
}

export class SweepStrategy {
  /**
   * @param {object} cfg config resolue via buildConfig()
   * @param {(atrPeriod:number)=>Float64Array} atrProvider renvoie l'ATR precalcule
   * @param {import('./refdata.js').RefBundle|null} [refs] series correlees (DXY, US10Y)
   * @param {import('./calendar.js').EconomicCalendar|null} [calendar]
   */
  constructor(cfg, atrProvider, refs = null, calendar = null) {
    this.cfg = cfg;
    this.atrProvider = atrProvider;
    this.refs = refs;
    this.calendar = calendar;
    if (refs) refs.prepare(cfg);
    this.funnel = emptyFunnel();

    /** Etat du jour courant. */
    this.day = null;
    /**
     * Journal compact des journees terminees (borne). C'est ce qui permet de
     * repondre a « pourquoi pas de trade aujourd'hui ? » : on garde l'etat
     * atteint et le motif de blocage, pas seulement les setups retenus.
     */
    this.dayLog = [];
    this.dayLogMax = 500;
    /** High/Low du jour precedent (pour le filtre de confluence PDH/PDL). */
    this.prevDay = null;
    /** High/Low accumules du jour courant. */
    this.curDayHL = null;
  }

  /** Incremente un compteur de rejet. */
  _reject(reason, meta) {
    this.funnel.rejected[reason]++;
    if (this.day) {
      this.day.rejections.push(reason);
      this.day.lastRejection = { reason, ...meta };
    }
    return null;
  }

  /**
   * Resume compact d'une journee, pour le journal et pour l'affichage
   * « plan du jour ».
   */
  summarizeDay(d = this.day) {
    if (!d) return null;
    return {
      date: d.date,
      dow: d.dow,
      phase: d.phase,
      londonHigh: Number.isFinite(d.londonHigh) ? d.londonHigh : null,
      londonLow: Number.isFinite(d.londonLow) ? d.londonLow : null,
      londonRange: d.londonRange ?? null,
      londonBars: d.londonBars,
      dayOpen: d.dayOpen,
      sweep: d.sweep
        ? {
            side: d.sweep.side,
            dir: d.sweep.dir,
            level: d.sweep.level,
            extreme: d.sweep.extremePrice,
            penetration: Math.abs(d.sweep.extremePrice - d.sweep.level),
            atrAtSweep: d.sweep.atrAtSweep,
            at: d.sweep.crossTs,
            ambiguous: d.sweep.ambiguous,
          }
        : null,
      setups: d.setups.length,
      /** Dernier motif de blocage rencontre — la reponse a « pourquoi rien ». */
      lastRejection: d.lastRejection ? { ...d.lastRejection } : null,
      rejections: d.rejections.slice(-6),
    };
  }

  /** Initialise l'etat pour un nouveau jour UTC. */
  _startDay(s, i) {
    const ts = s.time[i];
    const cfg = this.cfg;

    // Archiver la journee qui s'acheve avant de la remplacer.
    if (this.day) {
      this.dayLog.push(this.summarizeDay(this.day));
      if (this.dayLog.length > this.dayLogMax) this.dayLog.shift();
    }

    // Rotation du High/Low journalier (pour PDH/PDL du jour suivant).
    if (this.curDayHL) this.prevDay = this.curDayHL;
    this.curDayHL = { high: s.high[i], low: s.low[i] };

    const dow = utcDayOfWeek(ts);
    const date = isoDate(ts);

    this.day = {
      dayIndex: utcDayIndex(ts),
      date,
      dow,
      startIdx: i,
      dayOpen: s.open[i],
      phase: Phase.IDLE,

      // Decalages DST resolus une fois par jour.
      londonShift: londonShiftMinutes(ts, cfg.sessions.londonAnchor),
      nyShift: nyShiftMinutes(ts, cfg.sessions.nyAnchor),

      // Phase 1
      londonHigh: -Infinity,
      londonLow: Infinity,
      londonHighIdx: -1,
      londonLowIdx: -1,
      londonBars: 0,
      londonFinalized: false,

      // Phase 2
      sweepCount: 0,
      sweep: null,

      // Phase 3 : swings confirmes causalement, pour le MSS.
      swingLows: [],
      swingHighs: [],

      // Diagnostic
      rejections: [],
      lastRejection: null,
      setups: [],
    };

    this.funnel.daysSeen++;

    const { dateFrom, dateTo } = cfg.resolved;
    if ((dateFrom && date < dateFrom) || (dateTo && date > dateTo)) {
      this.day.phase = Phase.SKIPPED;
      this._reject('dayOutOfRange', { date });
    } else if (!cfg.resolved.weekdays.has(dow)) {
      this.day.phase = Phase.SKIPPED;
      this._reject('dayWeekday', { date });
    } else if (cfg.resolved.skipDates.has(date)) {
      this.day.phase = Phase.SKIPPED;
      this._reject('daySkipDate', { date });
    } else if (this._dayBlackout(ts, date)) {
      this.day.phase = Phase.SKIPPED;
      this._reject('dayNewsBlackout', { date });
    }
  }

  /**
   * Blackout connu a l'avance (calendrier / NFP). Le detecteur de choc par la
   * volatilite est evalue plus tard, quand la bougie de 13h30 a cloture.
   */
  _dayBlackout(ts, date) {
    const mode = this.cfg.filters.newsBlackout;
    if (mode === 'off' || mode === 'volatilitySpike') return false;
    if ((mode === 'nfp' || mode === 'all') && isNfpDay(ts)) return true;
    if ((mode === 'calendar' || mode === 'all') && this.calendar && this.calendar.has(date, ['high']))
      return true;
    return false;
  }

  /** Fenetres horaires du jour, decalage DST applique. */
  _windows() {
    const r = this.cfg.resolved;
    const ls = this.day.londonShift;
    const ns = this.day.nyShift;
    return {
      londonStart: r.londonStart + ls,
      londonEnd: r.londonEnd + ls,
      sweepStart: r.sweepStart + ns,
      sweepEnd: r.sweepEnd + ns,
      confirmEnd: r.confirmEnd + ns,
      entryExpiry: r.entryExpiry + ns,
      forceCloseAt: r.forceCloseAt + ns,
      newsTime: r.newsTime + ns,
    };
  }

  /**
   * Alimente la strategie avec la barre `i` de la serie `s`.
   * @param {import('./csv.js').Series} s
   * @param {number} i
   * @returns {Array<object>} setups emis sur cette barre (0 ou 1)
   */
  onBar(s, i) {
    const cfg = this.cfg;
    const ts = s.time[i];
    this.funnel.barsSeen++;

    // ── Rotation de journee ────────────────────────────────────────────
    if (!this.day || utcDayIndex(ts) !== this.day.dayIndex) {
      this._startDay(s, i);
    } else {
      if (s.high[i] > this.curDayHL.high) this.curDayHL.high = s.high[i];
      if (s.low[i] < this.curDayHL.low) this.curDayHL.low = s.low[i];
    }

    const d = this.day;
    if (d.phase === Phase.SKIPPED || d.phase === Phase.DONE) return [];

    const mod = utcMinuteOfDay(ts);
    const w = this._windows();
    const atrArr = this.atrProvider(cfg.filters.atrPeriod);
    const atrNow = atrArr[i];

    // ── Phase 1 : construction du range de Londres ────────────────────
    if (!d.londonFinalized) {
      const inLondon =
        mod >= w.londonStart &&
        (cfg.sessions.londonEndInclusive ? mod <= w.londonEnd : mod < w.londonEnd);

      if (inLondon) {
        if (s.high[i] > d.londonHigh) {
          d.londonHigh = s.high[i];
          d.londonHighIdx = i;
        }
        if (s.low[i] < d.londonLow) {
          d.londonLow = s.low[i];
          d.londonLowIdx = i;
        }
        d.londonBars++;
        return [];
      }

      if (mod < w.londonStart) return []; // Avant Londres : rien a faire.

      // Premiere barre apres la fin de Londres -> on fige le range.
      d.londonFinalized = true;
      d.londonRange = d.londonHigh - d.londonLow;

      if (d.londonBars < cfg.sessions.minLondonBars) {
        d.phase = Phase.SKIPPED;
        this._reject('dayLondonIncomplete', { bars: d.londonBars });
        return [];
      }

      const ctx = { atr: atrNow, price: s.close[i], range: d.londonRange };
      const rMin = resolveDistance(cfg, cfg.filters.londonRangeMode, cfg.filters.londonRangeMin, ctx);
      const rMax = resolveDistance(cfg, cfg.filters.londonRangeMode, cfg.filters.londonRangeMax, ctx);
      if (rMin !== null && Number.isFinite(rMin) && d.londonRange < rMin) {
        d.phase = Phase.SKIPPED;
        this._reject('dayLondonRangeTooSmall', { range: d.londonRange, min: rMin });
        return [];
      }
      if (rMax !== null && Number.isFinite(rMax) && d.londonRange > rMax) {
        d.phase = Phase.SKIPPED;
        this._reject('dayLondonRangeTooLarge', { range: d.londonRange, max: rMax });
        return [];
      }

      // Filtre de regime de volatilite (ATR en % du prix).
      const atrPct = (atrNow / s.close[i]) * 100;
      const { atrPctPriceMin: aMin, atrPctPriceMax: aMax } = cfg.filters;
      if ((aMin !== null && atrPct < aMin) || (aMax !== null && atrPct > aMax)) {
        d.phase = Phase.SKIPPED;
        this._reject('dayAtrRegime', { atrPct });
        return [];
      }

      d.phase = Phase.ARMED;
      this.funnel.daysArmed++;
      return [];
    }

    // ── Suivi causal des swings (necessaire au MSS) ────────────────────
    this._trackSwings(s, i);

    // ── Phase 2 : detection du balayage ───────────────────────────────
    if (d.phase === Phase.ARMED) {
      if (mod < w.sweepStart) return [];
      if (mod > w.sweepEnd) {
        d.phase = Phase.DONE;
        this._reject('sweepNone', {});
        return [];
      }
      this._detectSweep(s, i, atrNow);
      if (d.phase !== Phase.SWEPT) return [];
    }

    // ── Phase 3 + 4 : MSS puis emission du setup ──────────────────────
    if (d.phase === Phase.SWEPT) {
      return this._trackSweepAndMss(s, i, atrNow, w, mod);
    }
    return [];
  }

  /**
   * Confirme les swings fractals de facon causale : a la barre i, la barre
   * j = i - lookback peut enfin etre declaree swing (elle a lookback barres
   * de chaque cote).
   */
  _trackSwings(s, i) {
    const lb = this.cfg.mss.swingLookback;
    const j = i - lb;
    const d = this.day;
    if (j < d.startIdx + lb) return;

    let isLow = true;
    let isHigh = true;
    for (let k = 1; k <= lb; k++) {
      if (s.low[j - k] <= s.low[j] || s.low[j + k] <= s.low[j]) isLow = false;
      if (s.high[j - k] >= s.high[j] || s.high[j + k] >= s.high[j]) isHigh = false;
      if (!isLow && !isHigh) return;
    }
    if (isLow) d.swingLows.push({ i: j, price: s.low[j] });
    if (isHigh) d.swingHighs.push({ i: j, price: s.high[j] });
  }

  /** Phase 2 : le prix depasse-t-il le High ou le Low de Londres ? */
  _detectSweep(s, i, atrNow) {
    const cfg = this.cfg;
    const d = this.day;
    const ctx = { atr: atrNow, price: s.close[i], range: d.londonRange };
    const minPen = resolveDistance(cfg, cfg.sweep.penetrationMode, cfg.sweep.minPenetration, ctx);
    if (!Number.isFinite(minPen)) return;

    const penHigh = s.high[i] - d.londonHigh;
    const penLow = d.londonLow - s.low[i];
    const hitHigh = penHigh >= minPen;
    const hitLow = penLow >= minPen;
    if (!hitHigh && !hitLow) return;

    // Les deux cotes balayes dans la meme barre M5 : on ne peut pas trancher
    // l'ordre chronologique intra-barre, on retient la penetration dominante
    // et on marque le setup comme ambigu (tracable dans le rapport).
    let side;
    let ambiguous = false;
    if (hitHigh && hitLow) {
      ambiguous = true;
      side = penHigh >= penLow ? 'high' : 'low';
    } else {
      side = hitHigh ? 'high' : 'low';
    }

    if (
      (side === 'high' && cfg.sweep.side === 'lowOnly') ||
      (side === 'low' && cfg.sweep.side === 'highOnly')
    ) {
      this._reject('sweepSideDisabled', { side });
      d.phase = Phase.DONE;
      return;
    }

    d.sweep = {
      side,
      dir: side === 'high' ? 'sell' : 'buy',
      ambiguous,
      level: side === 'high' ? d.londonHigh : d.londonLow,
      crossIdx: i,
      crossTs: s.time[i],
      extremeIdx: i,
      extremePrice: side === 'high' ? s.high[i] : s.low[i],
      closedBack: false,
      atrAtSweep: atrNow,
    };
    d.sweepCount++;
    d.phase = Phase.SWEPT;
    this.funnel.daysSwept++;
    if (side === 'high') this.funnel.daysSweptHigh++;
    else this.funnel.daysSweptLow++;
  }

  /** Phases 3 & 4 : suivi de l'extreme du piege, MSS, puis setup. */
  _trackSweepAndMss(s, i, atrNow, w, mod) {
    const cfg = this.cfg;
    const d = this.day;
    const sw = d.sweep;
    const isSell = sw.dir === 'sell';
    const ctx = { atr: atrNow, price: s.close[i], range: d.londonRange };

    // Mise a jour de l'extreme du piege (le futur point d'ancrage du SL).
    if (isSell) {
      if (s.high[i] > sw.extremePrice) {
        sw.extremePrice = s.high[i];
        sw.extremeIdx = i;
      }
    } else if (s.low[i] < sw.extremePrice) {
      sw.extremePrice = s.low[i];
      sw.extremeIdx = i;
    }

    // Invalidation : penetration excessive = vraie cassure, pas un piege.
    const maxPen = resolveDistance(cfg, cfg.sweep.penetrationMode, cfg.sweep.maxPenetration, ctx);
    const pen = isSell ? sw.extremePrice - sw.level : sw.level - sw.extremePrice;
    if (Number.isFinite(maxPen) && pen > maxPen) {
      this._reject('sweepTooFar', { pen, maxPen });
      return this._afterSweepFail(s, i);
    }

    // Option : exiger une cloture de retour dans le range (rejet confirme).
    if (cfg.sweep.requireCloseBack && !sw.closedBack) {
      const back = isSell ? s.close[i] < sw.level : s.close[i] > sw.level;
      if (back) {
        sw.closedBack = true;
      } else if (i - sw.crossIdx >= cfg.sweep.closeBackMaxBars) {
        this._reject('sweepNoCloseBack', {});
        return this._afterSweepFail(s, i);
      } else {
        return [];
      }
    }

    // Expiration de la fenetre de confirmation.
    if (mod > w.confirmEnd) {
      this._reject('mssTimeout', {});
      d.phase = Phase.DONE;
      return [];
    }
    if (i - sw.crossIdx > cfg.mss.maxBarsAfterSweep) {
      this._reject('mssTimeout', { bars: i - sw.crossIdx });
      d.phase = Phase.DONE;
      return [];
    }

    // ── Structure protegee a casser ─────────────────────────────────
    const struct = this._protectedStructure(s, i);
    if (!struct) {
      this._reject('mssNoStructure', {});
      return [];
    }

    // ── Cassure de structure (MSS) ──────────────────────────────────
    const buf = resolveDistance(cfg, cfg.mss.breakBufferMode, cfg.mss.breakBuffer, ctx);
    const probe = cfg.mss.breakType === 'close' ? s.close[i] : isSell ? s.low[i] : s.high[i];
    const broke = isSell ? probe < struct.price - buf : probe > struct.price + buf;
    if (!broke) {
      this._reject('mssNoBreak', {});
      return [];
    }
    this.funnel.daysMssBreak++;

    // ── Deplacement ("bougie longue, pleine, violente") ─────────────
    const leg = this._findDisplacementLeg(s, i, atrNow, isSell);
    if (!leg) {
      this._reject('mssNoDisplacement', {});
      return [];
    }

    // ── Construction du setup ───────────────────────────────────────
    const setup = this._buildSetup(s, i, atrNow, w, struct, leg, ctx);

    // Fin de traitement de CE balayage. Si la config autorise plusieurs
    // opportunites par jour, on se re-arme pour guetter un nouveau balayage
    // (typiquement le cote oppose) au lieu de cloturer la journee.
    if (d.sweepCount < cfg.sweep.maxPerDay) {
      d.sweep = null;
      d.phase = Phase.ARMED;
    } else {
      d.phase = Phase.DONE;
    }
    if (!setup) return [];

    d.setups.push(setup);
    this.funnel.setupsEmitted++;
    if (setup.dir === 'sell') this.funnel.setupsSell++;
    else this.funnel.setupsBuy++;
    return [setup];
  }

  /** Reprise eventuelle apres echec d'un balayage. */
  _afterSweepFail(s, i) {
    const cfg = this.cfg;
    const d = this.day;
    if (cfg.sweep.allowOppositeAfterFail && d.sweepCount < cfg.sweep.maxPerDay) {
      d.sweep = null;
      d.phase = Phase.ARMED;
    } else {
      d.phase = Phase.DONE;
    }
    return [];
  }

  /**
   * Determine le niveau de structure que le MSS doit casser :
   * le dernier "plus bas" (pour une vente) qui a propulse le prix vers
   * l'extreme du piege.
   */
  _protectedStructure(s, i) {
    const cfg = this.cfg;
    const d = this.day;
    const sw = d.sweep;
    const isSell = sw.dir === 'sell';

    if (cfg.mss.ref === 'priorBar') {
      const j = Math.max(d.startIdx, sw.extremeIdx - 1);
      return { i: j, price: isSell ? s.low[j] : s.high[j], src: 'priorBar' };
    }

    if (cfg.mss.ref === 'fractal') {
      const list = isSell ? d.swingLows : d.swingHighs;
      // Dernier swing confirme STRICTEMENT avant la barre de l'extreme.
      for (let k = list.length - 1; k >= 0; k--) {
        if (list[k].i < sw.extremeIdx) return { ...list[k], src: 'fractal' };
      }
      if (cfg.mss.fallbackRef !== 'lowestSinceCross') return null;
    }

    // 'lowestSinceCross' (mode direct ou repli du mode fractal)
    let best = isSell ? Infinity : -Infinity;
    let bestIdx = -1;
    const from = Math.max(d.startIdx, sw.crossIdx);
    for (let j = from; j <= sw.extremeIdx; j++) {
      if (isSell ? s.low[j] < best : s.high[j] > best) {
        best = isSell ? s.low[j] : s.high[j];
        bestIdx = j;
      }
    }
    if (bestIdx < 0) return null;
    return { i: bestIdx, price: best, src: 'lowestSinceCross' };
  }

  /**
   * Cherche une jambe de deplacement se terminant a la barre i qui satisfait
   * les seuils de corps / amplitude / plenitude. Teste les longueurs 1..N et
   * retient celle dont le corps est le plus grand.
   */
  _findDisplacementLeg(s, i, atrNow, isSell) {
    const dsp = this.cfg.mss.displacement;
    const d = this.day;
    const maxLen = Math.max(1, dsp.lookbackBars);

    let best = null;
    for (let len = 1; len <= maxLen; len++) {
      const start = i - len + 1;
      if (start < d.startIdx) break;

      let hi = -Infinity;
      let lo = Infinity;
      for (let j = start; j <= i; j++) {
        if (s.high[j] > hi) hi = s.high[j];
        if (s.low[j] < lo) lo = s.low[j];
      }
      const range = hi - lo;
      const body = isSell ? s.open[start] - s.close[i] : s.close[i] - s.open[start];
      const candidate = { start, end: i, body, range, high: hi, low: lo, len };

      if (!dsp.enabled) return candidate;
      if (body <= 0 || range <= 0) continue;
      if (!Number.isFinite(atrNow)) continue;
      if (body < dsp.minBodyAtrMult * atrNow) continue;
      if (range < dsp.minRangeAtrMult * atrNow) continue;
      if (body / range < dsp.minBodyRatio) continue;

      if (!best || body > best.body) best = candidate;
    }
    return best;
  }

  /** Phase 4 : entree, SL, TP, R:R et filtres finaux. */
  _buildSetup(s, i, atrNow, w, struct, leg, ctx) {
    const cfg = this.cfg;
    const d = this.day;
    const sw = d.sweep;
    const isSell = sw.dir === 'sell';
    const close = s.close[i];

    // ── Zone d'entree ──────────────────────────────────────────────
    let entry = null;
    let zoneKind = null;
    let fvg = null;
    let ob = null;

    const wantFvg = cfg.entry.model === 'fvg' || cfg.entry.model === 'fvgOrOb';
    if (wantFvg) {
      fvg = this._selectFvg(s, i, leg, atrNow, ctx, isSell, close);
      if (fvg) {
        entry = fvg.proximal + (fvg.distal - fvg.proximal) * cfg.entry.fvgLevel;
        zoneKind = 'fvg';
      } else if (cfg.entry.model === 'fvg') {
        return this._reject(this._fvgRejectReason, {});
      }
    }

    if (!entry && (cfg.entry.model === 'orderBlock' || cfg.entry.model === 'fvgOrOb')) {
      ob = findOrderBlock(s, leg.start, cfg.entry.obLookbackBars, sw.dir);
      if (ob) {
        const z = orderBlockZone(ob, cfg.entry.obZone, sw.dir);
        entry = zoneLevel(z, cfg.entry.obLevel);
        zoneKind = 'orderBlock';
      }
    }

    if (!entry && cfg.entry.model === 'ote') {
      // Retracement de la jambe : 0 = fin de jambe, 1 = debut de jambe.
      const a = isSell ? leg.low : leg.high;
      const b = isSell ? leg.high : leg.low;
      entry = a + (b - a) * cfg.entry.oteLevel;
      zoneKind = 'ote';
    }

    if (!entry && cfg.entry.model === 'market') {
      entry = close;
      zoneKind = 'market';
    }

    if (!entry || !Number.isFinite(entry)) return this._reject('entryNoZone', {});

    // Une limite de vente doit etre AU-DESSUS du marche (et l'inverse pour un
    // achat) : sinon la zone est deja consommee et l'ordre s'executerait au
    // marche a un prix defavorable.
    if (zoneKind !== 'market') {
      if (isSell ? entry <= close : entry >= close) {
        return this._reject('entryBehindMarket', { entry, close });
      }
    }

    // ── Stop loss ──────────────────────────────────────────────────
    const slBuf = resolveDistance(cfg, cfg.stop.bufferMode, cfg.stop.buffer, ctx);
    if (!Number.isFinite(slBuf)) return this._reject('slTooTight', {});

    let slAnchor;
    if (cfg.stop.anchor === 'fvgDistal' && fvg) {
      slAnchor = fvg.distal;
    } else if (cfg.stop.anchor === 'structureExtreme') {
      let ext = isSell ? -Infinity : Infinity;
      for (let j = Math.min(struct.i, sw.crossIdx); j <= i; j++) {
        if (isSell ? s.high[j] > ext : s.low[j] < ext) ext = isSell ? s.high[j] : s.low[j];
      }
      slAnchor = ext;
    } else {
      slAnchor = sw.extremePrice;
    }
    // Le SL ne doit jamais etre a l'interieur de la zone d'entree.
    slAnchor = isSell ? Math.max(slAnchor, entry) : Math.min(slAnchor, entry);
    const sl = isSell ? slAnchor + slBuf : slAnchor - slBuf;

    const slDist = Math.abs(sl - entry);
    const dMin = resolveDistance(cfg, cfg.stop.distanceMode, cfg.stop.minDistance, ctx);
    const dMax = resolveDistance(cfg, cfg.stop.distanceMode, cfg.stop.maxDistance, ctx);
    if (Number.isFinite(dMin) && slDist < dMin) return this._reject('slTooTight', { slDist, dMin });
    if (Number.isFinite(dMax) && slDist > dMax) return this._reject('slTooWide', { slDist, dMax });

    // ── Take profit ────────────────────────────────────────────────
    // offset negatif = on devance le niveau (remplissage plus sur).
    const off = resolveDistance(cfg, cfg.target.offsetMode, cfg.target.offset, ctx);
    const frontRun = -(Number.isFinite(off) ? off : 0);
    const londonTarget = isSell ? d.londonLow + frontRun : d.londonHigh - frontRun;
    const rrTarget = isSell
      ? entry - cfg.target.rrMultiple * slDist
      : entry + cfg.target.rrMultiple * slDist;

    let tp;
    if (cfg.target.anchor === 'rrMultiple') tp = rrTarget;
    else if (cfg.target.anchor === 'nearestOf')
      tp = isSell ? Math.max(londonTarget, rrTarget) : Math.min(londonTarget, rrTarget);
    else tp = londonTarget;

    // Le TP doit etre du bon cote de l'entree.
    if (isSell ? tp >= entry : tp <= entry) return this._reject('rrTooLow', { tp, entry });

    const reward = Math.abs(tp - entry);
    const rr = reward / slDist;
    if (rr < cfg.target.minRR) return this._reject('rrTooLow', { rr });
    if (rr > cfg.target.maxRR) return this._reject('rrTooHigh', { rr });

    // ── Filtres contextuels ────────────────────────────────────────
    if (cfg.filters.news !== 'off') {
      const swMod = utcMinuteOfDay(sw.crossTs);
      const inNews = Math.abs(swMod - w.newsTime) <= cfg.sessions.newsWindowMinutes;
      if (cfg.filters.news === 'require' && !inNews) return this._reject('filterNews', {});
      if (cfg.filters.news === 'avoid' && inNews) return this._reject('filterNews', {});
    }

    if (cfg.filters.dailyBias === 'dailyOpen') {
      // Vendre uniquement en prime (au-dessus de l'open du jour), acheter en discount.
      const ok = isSell ? close > d.dayOpen : close < d.dayOpen;
      if (!ok) return this._reject('filterDailyBias', {});
    }

    if (cfg.filters.pdhPdlProximity !== null && this.prevDay) {
      const prox = resolveDistance(
        cfg,
        cfg.filters.pdhPdlProximityMode,
        cfg.filters.pdhPdlProximity,
        ctx
      );
      const ref = isSell ? this.prevDay.high : this.prevDay.low;
      if (!(Math.abs(sw.level - ref) <= prox)) return this._reject('filterPdhPdl', {});
    }

    // ── Inducement : le piege doit avoir eu son aimant a liquidite ──
    if (cfg.sweep.requireInducement) {
      const depth = resolveDistance(
        cfg,
        cfg.sweep.inducementDepthMode,
        cfg.sweep.inducementMinDepth,
        ctx
      );
      const list = isSell ? d.swingHighs : d.swingLows;
      const from = sw.crossIdx - cfg.sweep.inducementLookbackBars;
      const found = list.some(
        (p) =>
          p.i < sw.crossIdx &&
          p.i >= from &&
          (isSell ? p.price <= sw.level - depth : p.price >= sw.level + depth)
      );
      if (!found) return this._reject('filterInducement', { depth });
    }

    // ── Choc de volatilite : publication destructrice detectee ──────
    const nbMode = cfg.filters.newsBlackout;
    if (nbMode === 'volatilitySpike' || nbMode === 'all') {
      const spike = newsSpike(
        s,
        d.startIdx,
        i,
        cfg.resolved.newsTime + d.nyShift,
        this.atrProvider(cfg.filters.atrPeriod),
        cfg.filters.newsSpikeAtrMult
      );
      if (spike.spike) return this._reject('filterNewsSpike', { ratio: spike.ratio });
    }

    // ── Timing : ne rien accepter avant la reaction a l'annonce ────
    const signalMod = utcMinuteOfDay(s.time[i]);
    const notBefore = cfg.resolved.signalNotBefore + d.nyShift;
    if (signalMod < notBefore) {
      return this._reject('filterSignalTooEarly', { signalMod, notBefore });
    }

    // ── Fenetre Silver Bullet ──────────────────────────────────────
    const sbStart = cfg.resolved.silverBulletStart + d.nyShift;
    const sbEnd = cfg.resolved.silverBulletEnd + d.nyShift;
    const sbMode = cfg.filters.silverBullet;
    if (sbMode === 'signal' || sbMode === 'both') {
      if (signalMod < sbStart || signalMod > sbEnd) {
        return this._reject('filterSilverBullet', { signalMod, sbStart, sbEnd });
      }
    }

    // ── Premium / Discount (juste valeur) ──────────────────────────
    const pdMode = cfg.filters.premiumDiscount;
    const thr = cfg.filters.premiumThreshold;
    let fibLondon = NaN;
    let fibLeg = NaN;
    if (pdMode !== 'off') {
      // Position de l'entree dans la structure, 0 = bas, 1 = haut.
      const fibIn = (lowEnd, highEnd) =>
        highEnd > lowEnd ? (entry - lowEnd) / (highEnd - lowEnd) : NaN;

      fibLondon = fibIn(d.londonLow, d.londonHigh);
      fibLeg = isSell
        ? fibIn(leg.low, sw.extremePrice)
        : fibIn(sw.extremePrice, leg.high);

      const ok = (f) => {
        if (!Number.isFinite(f)) return false;
        return isSell ? f >= thr : f <= 1 - thr;
      };
      const needLondon = pdMode === 'londonRange' || pdMode === 'both';
      const needLeg = pdMode === 'mssLeg' || pdMode === 'both';
      if ((needLondon && !ok(fibLondon)) || (needLeg && !ok(fibLeg))) {
        return this._reject('filterPremium', { fibLondon, fibLeg, thr });
      }
    }

    // ── Confluence DXY (correlation inverse) ───────────────────────
    let dxyInfo = null;
    const dxyCfg = cfg.refs.dxy;
    if (dxyCfg.mode !== 'off') {
      const ref = this.refs && this.refs.dxy;
      if (!ref) {
        if (dxyCfg.onMissing === 'block') return this._reject('filterRefMissing', { ref: 'DXY' });
      } else {
        // Miroir : l'or balaye son HAUT -> le DXY doit balayer son BAS.
        const mirrorSide = sw.side === 'high' ? 'low' : 'high';
        const refPrice = ref.priceAt(sw.crossTs);
        const minPen = (dxyCfg.minPenetrationPct / 100) * refPrice;
        const swept = ref.sweptExtreme(
          sw.crossTs,
          mirrorSide,
          dxyCfg.lagMinutes * 60_000,
          minPen
        );
        let rejected = { available: swept.available, rejected: true, move: NaN };
        if (swept.available && dxyCfg.requireReversal) {
          rejected = ref.rejectedExtreme(
            swept.extremeTs ?? sw.crossTs,
            mirrorSide,
            dxyCfg.reversalWithinMinutes * 60_000,
            (dxyCfg.minReversalPct / 100) * refPrice
          );
        }
        dxyInfo = {
          mirrorSide,
          available: swept.available,
          swept: swept.swept,
          penetration: swept.penetration,
          reversal: rejected.rejected,
          reversalMove: rejected.move,
        };
        if (!swept.available) {
          if (dxyCfg.onMissing === 'block') return this._reject('filterRefMissing', { ref: 'DXY' });
        } else if (dxyCfg.mode === 'require') {
          if (!swept.swept) return this._reject('filterDxy', { penetration: swept.penetration });
          if (dxyCfg.requireReversal && !rejected.rejected) {
            return this._reject('filterDxy', { reason: 'pasDeRejet', move: rejected.move });
          }
        }
      }
    }

    // ── Filtre macro US10Y (concurrence de rendement) ──────────────
    let us10yInfo = null;
    const tyCfg = cfg.refs.us10y;
    if (tyCfg.mode === 'alignTrend') {
      const ref = this.refs && this.refs.us10y;
      if (!ref) {
        if (tyCfg.onMissing === 'block') return this._reject('filterRefMissing', { ref: 'US10Y' });
      } else {
        const sl = ref.slopePct(s.time[i], tyCfg.lookbackBars);
        us10yInfo = { available: sl.available, slopePct: sl.slopePct, last: sl.last };
        if (!sl.available) {
          if (tyCfg.onMissing === 'block') return this._reject('filterRefMissing', { ref: 'US10Y' });
        } else {
          // Rendements en hausse -> ventes seulement ; en baisse -> achats.
          const aligned = isSell
            ? sl.slopePct >= tyCfg.minSlopePct
            : sl.slopePct <= -tyCfg.minSlopePct;
          if (!aligned) return this._reject('filterUs10y', { slopePct: sl.slopePct });
        }
      }
    }

    // ── Echelle de cibles TP1 / TP2 / TP3 ──────────────────────────
    const internal = this._internalLiquidity(s, i, entry, tp, isSell, slDist);
    const targets = this._buildTargets({ entry, tp, slDist, isSell, internal, d });

    // ── Setup final ────────────────────────────────────────────────
    const expiryBars = cfg.entry.expiryBars;
    return {
      date: d.date,
      dir: sw.dir,
      side: sw.side,
      ambiguousSweep: sw.ambiguous,

      signalIdx: i,
      signalTs: s.time[i],
      signalClose: close,

      entry: roundPrice(cfg, entry),
      sl: roundPrice(cfg, sl),
      tp: roundPrice(cfg, tp),
      rr,
      slDistUsd: slDist,
      slDistPips: toPips(cfg, slDist),
      rewardUsd: reward,

      zoneKind,
      entryModel: cfg.entry.model,
      fvg: fvg ? { lower: fvg.lower, upper: fvg.upper, size: fvg.size, barIdx: fvg.i } : null,
      ob: ob ? { barIdx: ob.i, high: ob.high, low: ob.low } : null,

      londonHigh: d.londonHigh,
      londonLow: d.londonLow,
      londonRange: d.londonRange,
      sweepLevel: sw.level,
      sweepExtreme: sw.extremePrice,
      sweepPenetrationUsd: Math.abs(sw.extremePrice - sw.level),
      sweepTs: sw.crossTs,
      structureLevel: struct.price,
      structureSrc: struct.src,
      displacementBody: leg.body,
      displacementLen: leg.len,
      atrAtSignal: atrNow,
      atrPctPrice: (atrNow / close) * 100,
      dayOpen: d.dayOpen,

      // Liquidite interne : premier "plus bas" a court terme entre l'entree et
      // l'objectif final, cible naturelle du profit partiel.
      internalLiquidity: internal,
      /** Echelle de cibles consommee par le moteur (1 a 3 crans). */
      targets,

      // Confluences (annotees meme en mode 'soft', pour le rapport).
      fibLondon,
      fibLeg,
      dxy: dxyInfo,
      us10y: us10yInfo,

      // Contraintes de cycle de vie de l'ordre, en absolu pour le moteur.
      expiryIdx: expiryBars > 0 ? i + expiryBars : Infinity,
      expiryMinute: w.entryExpiry,
      forceCloseMinute: w.forceCloseAt,
      /** Fenetre de remplissage imposee si filters.silverBullet couvre 'fill'. */
      fillFromMinute: sbMode === 'fill' || sbMode === 'both' ? sbStart : -Infinity,
      fillUntilMinute: sbMode === 'fill' || sbMode === 'both' ? sbEnd : Infinity,
    };
  }

  /**
   * Construit l'echelle de cibles.
   *
   * Invariants garantis (le moteur peut s'y fier) :
   *  - au moins un cran, le dernier fermant TOUJOURS le reste de la position ;
   *  - prix strictement au-dela de l'entree dans le sens du trade ;
   *  - progression monotone vers la cible finale, jamais au-dela ;
   *  - espacement minimal entre crans, sinon le cran est ECARTE.
   *
   * @returns {Array<{name:string, price:number, closePct:number, rr:number, anchor:string}>}
   */
  _buildTargets({ entry, tp, slDist, isSell, internal, d }) {
    const cfg = this.cfg;
    const L = cfg.target.levels;

    // Echelle a un seul cran : comportement historique, bit-identique.
    if (!L.enabled) {
      if (cfg.manage.partial.enabled) {
        const pp = cfg.manage.partial;
        const raw =
          pp.anchor === 'internalLiquidity'
            ? internal
              ? internal.level
              : NaN
            : isSell
              ? entry - pp.atRR * slDist
              : entry + pp.atRR * slDist;
        if (Number.isFinite(raw)) {
          const beyond = isSell ? raw <= entry - pp.minRR * slDist : raw >= entry + pp.minRR * slDist;
          const before = isSell ? raw > tp : raw < tp;
          if (beyond && before) {
            return [
              { name: 'partial', price: roundPrice(cfg, raw), closePct: pp.closePct, rr: Math.abs(raw - entry) / slDist, anchor: pp.anchor },
              { name: 'tp', price: tp, closePct: 1, rr: Math.abs(tp - entry) / slDist, anchor: 'final' },
            ];
          }
        }
      }
      return [{ name: 'tp', price: tp, closePct: 1, rr: Math.abs(tp - entry) / slDist, anchor: 'final' }];
    }

    const equilibrium = d.londonLow + 0.5 * d.londonRange;
    const priceFor = (spec) => {
      switch (spec.anchor) {
        case 'internalLiquidity':
          return internal ? internal.level : NaN;
        case 'equilibrium':
          return equilibrium;
        case 'final':
          return tp;
        case 'rr':
          return isSell ? entry - spec.rr * slDist : entry + spec.rr * slDist;
        default:
          return NaN;
      }
    };

    const out = [];
    let prev = entry;
    for (const [name, spec] of [['TP1', L.tp1], ['TP2', L.tp2], ['TP3', L.tp3]]) {
      let price = priceFor(spec);
      // Ancre indisponible -> repli sur un multiple de R, si configure.
      if (!Number.isFinite(price) && spec.fallbackRR !== null) {
        price = isSell ? entry - spec.fallbackRR * slDist : entry + spec.fallbackRR * slDist;
      }
      if (!Number.isFinite(price)) continue;

      // Au-dela de l'entree, en deca de la cible finale, et suffisamment
      // espace du cran precedent.
      const gap = Math.abs(price - prev) / slDist;
      const forward = isSell ? price < prev : price > prev;
      const withinFinal = isSell ? price >= tp : price <= tp;
      if (!forward || !withinFinal || gap < L.minSpacingR) continue;

      out.push({
        name,
        price: roundPrice(cfg, price),
        closePct: spec.closePct,
        rr: Math.abs(price - entry) / slDist,
        anchor: spec.anchor,
      });
      prev = price;
    }

    // Aucun cran retenu : on retombe sur la cible finale seule.
    if (!out.length) {
      return [{ name: 'TP', price: tp, closePct: 1, rr: Math.abs(tp - entry) / slDist, anchor: 'final' }];
    }
    // Le dernier cran ferme toujours le reste.
    out[out.length - 1].closePct = 1;
    return out;
  }

  /**
   * Premier niveau de liquidite interne entre l'entree et l'objectif : le
   * swing bas (pour une vente) le plus proche de l'entree, situe au-dela du
   * seuil `partial.minRR` et en deca du take profit.
   *
   * Balaye toutes les barres du jour (Londres incluse) : les poches de
   * liquidite interieures au range sont justement celles de la session.
   */
  _internalLiquidity(s, i, entry, tp, isSell, slDist) {
    const cfg = this.cfg;
    const lb = cfg.mss.swingLookback;
    const d = this.day;
    const minDist = cfg.manage.partial.minRR * slDist;

    let best = null;
    for (let j = d.startIdx + lb; j <= i - lb; j++) {
      let ok = true;
      for (let k = 1; k <= lb; k++) {
        if (isSell) {
          if (s.low[j - k] <= s.low[j] || s.low[j + k] <= s.low[j]) {
            ok = false;
            break;
          }
        } else if (s.high[j - k] >= s.high[j] || s.high[j + k] >= s.high[j]) {
          ok = false;
          break;
        }
      }
      if (!ok) continue;
      const price = isSell ? s.low[j] : s.high[j];
      // Doit etre entre l'entree (+ marge) et le TP.
      const beyondEntry = isSell ? price <= entry - minDist : price >= entry + minDist;
      const beforeTp = isSell ? price > tp : price < tp;
      if (!beyondEntry || !beforeTp) continue;
      // Le plus proche de l'entree = la premiere poche rencontree.
      if (!best || (isSell ? price > best.price : price < best.price)) {
        best = { i: j, price };
      }
    }
    return best ? { level: best.price, barIdx: best.i, rr: Math.abs(best.price - entry) / slDist } : null;
  }

  /** Selectionne le FVG de la jambe de deplacement selon la config. */
  _selectFvg(s, i, leg, atrNow, ctx, isSell, close) {
    const cfg = this.cfg;
    this._fvgRejectReason = 'fvgMissing';

    const from = Math.max(2, leg.start - cfg.fvg.searchBars);
    const all = findFvgs(s, from, i, isSell ? 'bearish' : 'bullish');
    if (!all.length) return null;

    const minSize = resolveDistance(cfg, cfg.fvg.minSizeMode, cfg.fvg.minSize, ctx);
    const sized = all.filter((f) => !Number.isFinite(minSize) || f.size >= minSize);
    if (!sized.length) {
      this._fvgRejectReason = 'fvgTooSmall';
      return null;
    }

    // Le FVG doit rester devant le marche : pour une vente, entierement
    // au-dessus du prix actuel (sinon deja comble).
    const ahead = sized.filter((f) => (isSell ? f.proximal > close : f.proximal < close));
    const pool = ahead.length ? ahead : cfg.fvg.allowEncroached ? sized : [];
    if (!pool.length) {
      this._fvgRejectReason = 'entryBehindMarket';
      return null;
    }

    if (cfg.fvg.selection === 'largest') {
      return pool.reduce((a, b) => (b.size > a.size ? b : a));
    }
    if (cfg.fvg.selection === 'first') return pool[0];
    // 'nearest' : le plus proche du prix actuel.
    return pool.reduce((a, b) =>
      Math.abs(b.proximal - close) < Math.abs(a.proximal - close) ? b : a
    );
  }
}
