/**
 * Chargement de barres OHLCV depuis un CSV.
 * Format attendu : time,open,high,low,close,volume
 * avec time en ISO8601 UTC ("2021-05-19T20:25:00.000Z").
 *
 * Les barres sont stockees en "struct of arrays" (Float64Array) : c'est ce qui
 * permet de rejouer 376k barres des milliers de fois pendant l'optimisation
 * sans pression sur le GC.
 */

import { readFileSync } from 'node:fs';
import { MS_MIN } from './time.js';

/**
 * @typedef {object} Series
 * @property {Float64Array} time   epoch ms (ouverture de la barre)
 * @property {Float64Array} open
 * @property {Float64Array} high
 * @property {Float64Array} low
 * @property {Float64Array} close
 * @property {Float64Array} volume
 * @property {number} length
 * @property {number} timeframeMs
 */

/**
 * @param {string} path
 * @param {{from?: string, to?: string}} [opts] bornes ISO inclusives/exclusives
 * @returns {Series}
 */
export function loadCsv(path, opts = {}) {
  const raw = readFileSync(path, 'utf8');
  const lines = raw.split('\n');

  // En-tete -> index de colonnes (tolerant a l'ordre et a la casse).
  const header = lines[0].replace(/^﻿/, '').trim().toLowerCase().split(',');
  const idx = {};
  for (const name of ['time', 'open', 'high', 'low', 'close', 'volume']) {
    idx[name] = header.indexOf(name);
  }
  for (const name of ['time', 'open', 'high', 'low', 'close']) {
    if (idx[name] < 0) {
      throw new Error(`Colonne "${name}" absente du CSV. En-tete lu : ${header.join(',')}`);
    }
  }

  const fromTs = opts.from ? Date.parse(opts.from) : -Infinity;
  const toTs = opts.to ? Date.parse(opts.to) : Infinity;

  const n = lines.length - 1;
  const time = new Float64Array(n);
  const open = new Float64Array(n);
  const high = new Float64Array(n);
  const low = new Float64Array(n);
  const close = new Float64Array(n);
  const volume = new Float64Array(n);

  let k = 0;
  let skippedBadRows = 0;
  let skippedOutOfRange = 0;

  for (let i = 1; i <= n; i++) {
    const line = lines[i];
    if (!line || line.length < 10) continue;
    const f = line.split(',');
    const ts = Date.parse(f[idx.time]);
    if (!Number.isFinite(ts)) {
      skippedBadRows++;
      continue;
    }
    if (ts < fromTs || ts >= toTs) {
      skippedOutOfRange++;
      continue;
    }
    const o = +f[idx.open];
    const h = +f[idx.high];
    const l = +f[idx.low];
    const c = +f[idx.close];
    // Rejet des barres corrompues : NaN, prix <= 0, ou OHLC incoherent.
    if (!(o > 0 && h > 0 && l > 0 && c > 0) || h < l || h < o || h < c || l > o || l > c) {
      skippedBadRows++;
      continue;
    }
    time[k] = ts;
    open[k] = o;
    high[k] = h;
    low[k] = l;
    close[k] = c;
    volume[k] = idx.volume >= 0 ? +f[idx.volume] || 0 : 0;
    k++;
  }

  // Les barres doivent etre strictement croissantes en temps.
  for (let i = 1; i < k; i++) {
    if (time[i] <= time[i - 1]) {
      throw new Error(
        `CSV non trie ou doublon a la ligne ~${i + 1} : ` +
          `${new Date(time[i - 1]).toISOString()} puis ${new Date(time[i]).toISOString()}`
      );
    }
  }

  const series = {
    time: time.subarray(0, k),
    open: open.subarray(0, k),
    high: high.subarray(0, k),
    low: low.subarray(0, k),
    close: close.subarray(0, k),
    volume: volume.subarray(0, k),
    length: k,
    timeframeMs: inferTimeframe(time, k),
    stats: { skippedBadRows, skippedOutOfRange },
  };
  return series;
}

/** Deduit le timeframe comme l'ecart le plus frequent entre barres. */
function inferTimeframe(time, k) {
  const counts = new Map();
  const sample = Math.min(k - 1, 5000);
  for (let i = 1; i <= sample; i++) {
    const d = time[i] - time[i - 1];
    counts.set(d, (counts.get(d) || 0) + 1);
  }
  let best = 5 * MS_MIN;
  let bestC = -1;
  for (const [d, c] of counts) {
    if (c > bestC) {
      bestC = c;
      best = d;
    }
  }
  return best;
}

/** Resume lisible d'une serie. @param {Series} s */
export function describeSeries(s) {
  return {
    bars: s.length,
    from: new Date(s.time[0]).toISOString(),
    to: new Date(s.time[s.length - 1]).toISOString(),
    timeframeMin: s.timeframeMs / MS_MIN,
    priceMin: Math.min(...sample(s.low, 1000)),
    priceMax: Math.max(...sample(s.high, 1000)),
    skipped: s.stats,
  };
}

function sample(arr, n) {
  const step = Math.max(1, Math.floor(arr.length / n));
  const out = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[i]);
  return out;
}
