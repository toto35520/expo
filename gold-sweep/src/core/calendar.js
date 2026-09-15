/**
 * Calendrier economique.
 *
 * Deux mecanismes complementaires, parce qu'aucun des deux n'est suffisant
 * seul :
 *
 *  1. CALENDRIER DETERMINISTE / FOURNI
 *     - le NFP tombe le 1er vendredi du mois : c'est calculable sans donnee
 *       externe (quelques exceptions historiques, cf. `nfpExceptions`) ;
 *     - le CPI et les decisions du FOMC ne suivent pas de regle simple : ils
 *       doivent etre fournis via un CSV, sinon ils ne sont pas filtres.
 *
 *  2. DETECTEUR DE CHOC PAR LA VOLATILITE (sans aucune donnee externe)
 *     Une publication "destructrice" se reconnait a son empreinte : la barre
 *     M5 de 13h30 fait plusieurs ATR d'amplitude. On la mesure APRES sa
 *     cloture (13h35), donc le filtre reste causal — aucun regard vers le
 *     futur. C'est le filet de securite qui attrape les CPI/NFP/FOMC meme
 *     sans calendrier a jour.
 */

import { readFileSync } from 'node:fs';
import { isoDate } from './time.js';

/**
 * Le NFP tombe le 1er vendredi du mois.
 * @param {number} ts epoch ms
 */
export function isNfpDay(ts) {
  const d = new Date(ts);
  if (d.getUTCDay() !== 5) return false;
  return d.getUTCDate() <= 7;
}

/**
 * Calendrier charge depuis un CSV : date,impact[,event]
 *   2026-01-13,high,CPI
 *   2026-01-28,high,FOMC
 * Les lignes d'impact 'high' constituent le blackout.
 */
export class EconomicCalendar {
  constructor() {
    /** @type {Map<string, Array<{impact:string, event:string}>>} */
    this.byDate = new Map();
    this.loaded = false;
  }

  /** @param {string} path */
  static fromCsv(path) {
    const cal = new EconomicCalendar();
    const raw = readFileSync(path, 'utf8');
    const lines = raw.split('\n');
    const header = lines[0].replace(/^﻿/, '').trim().toLowerCase().split(',');
    const iDate = header.indexOf('date');
    const iImpact = header.indexOf('impact');
    const iEvent = header.indexOf('event');
    if (iDate < 0) throw new Error('Calendrier : colonne "date" absente');
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) continue;
      const f = line.split(',');
      const date = f[iDate].trim().slice(0, 10);
      const impact = (iImpact >= 0 ? f[iImpact] || '' : 'high').trim().toLowerCase();
      const event = (iEvent >= 0 ? f[iEvent] || '' : '').trim();
      if (!cal.byDate.has(date)) cal.byDate.set(date, []);
      cal.byDate.get(date).push({ impact, event });
    }
    cal.loaded = true;
    return cal;
  }

  /** Le jour comporte-t-il une annonce de l'impact demande ? */
  has(date, impacts = ['high']) {
    const list = this.byDate.get(date);
    if (!list) return false;
    return list.some((e) => impacts.includes(e.impact));
  }

  /** Libelles des evenements du jour. */
  events(date) {
    return (this.byDate.get(date) || []).map((e) => e.event || e.impact);
  }
}

/**
 * Detecteur de choc : la barre couvrant `newsMinute` fait-elle plus de
 * `atrMult` x ATR d'amplitude ?
 *
 * Causal : appele seulement apres la cloture de cette barre.
 *
 * @param {import('./csv.js').Series} s
 * @param {number} dayStartIdx premiere barre du jour
 * @param {number} nowIdx barre courante (borne superieure de la recherche)
 * @param {number} newsMinute minute GMT de l'annonce
 * @param {Float64Array} atrArr
 * @param {number} atrMult
 * @returns {{spike:boolean, range:number, atr:number, ratio:number, idx:number}}
 */
export function newsSpike(s, dayStartIdx, nowIdx, newsMinute, atrArr, atrMult) {
  const MS_DAY = 86_400_000;
  let found = -1;
  for (let i = dayStartIdx; i <= nowIdx; i++) {
    const mod = Math.floor(((s.time[i] % MS_DAY) + MS_DAY) % MS_DAY / 60_000);
    if (mod === newsMinute) {
      found = i;
      break;
    }
    if (mod > newsMinute) break;
  }
  if (found < 0) return { spike: false, range: NaN, atr: NaN, ratio: NaN, idx: -1 };
  // ATR mesure AVANT la barre de news, sinon la barre se normalise elle-meme.
  const a = atrArr[found - 1];
  const range = s.high[found] - s.low[found];
  if (!Number.isFinite(a) || a <= 0) return { spike: false, range, atr: a, ratio: NaN, idx: found };
  const ratio = range / a;
  return { spike: ratio >= atrMult, range, atr: a, ratio, idx: found };
}

/** Dates "YYYY-MM-DD" des NFP sur une plage, utile pour inspection. */
export function listNfpDays(fromTs, toTs) {
  const out = [];
  for (let ts = fromTs; ts <= toTs; ts += 86_400_000) {
    if (isNfpDay(ts)) out.push(isoDate(ts));
  }
  return out;
}
