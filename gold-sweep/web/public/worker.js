/**
 * Worker de backtest.
 *
 * Le CSV est lu et analyse ICI, dans le worker : les 24 Mo ne traversent
 * jamais le fil principal et l'interface ne gele pas. La serie analysee et
 * les ATR sont mis en cache, si bien qu'un second backtest avec d'autres
 * parametres est instantane.
 *
 * Ce worker execute le MEME moteur que le CLI Node — les modules sous
 * `engine/` sont copies tels quels depuis `src/` par web/build.mjs.
 */

import { buildConfig, deepMerge } from './engine/core/config.js';
import { describeSeries, parseCsv } from './engine/core/csv.js';
import { atr } from './engine/core/indicators.js';
import { EconomicCalendar } from './engine/core/calendar.js';
import { RefBundle, RefSeries } from './engine/core/refdata.js';
import { runBacktest } from './engine/backtest/engine.js';
import { computeMetrics } from './engine/backtest/metrics.js';
import { renderHtml } from './engine/backtest/render.js';
import { PRESETS } from './engine/core/presets.js';

/**
 * Resout `__preset` : le prereglage sert de BASE, les champs de l'interface
 * la surchargent. Sans cette etape le prereglage choisi serait ignore.
 */
function resolveOverride(raw) {
  const { __preset, ...rest } = raw || {};
  if (!__preset) return rest;
  if (!(__preset in PRESETS)) {
    throw new Error(`Prereglage inconnu : ${__preset}. Disponibles : ${Object.keys(PRESETS).join(', ')}`);
  }
  return deepMerge(structuredClone(PRESETS[__preset]), rest);
}

/** @type {import('./engine/core/csv.js').Series|null} */
let series = null;
let atrCache = new Map();
let refs = null;
let calendar = null;
/** Dernier resultat, conserve pour l'export. */
let last = null;

const atrProvider = (p) => {
  if (!atrCache.has(p)) atrCache.set(p, atr(series, p));
  return atrCache.get(p);
};

const fail = (id, e) =>
  postMessage({ id, ok: false, error: String((e && e.message) || e), stack: e && e.stack });

onmessage = async (ev) => {
  const { id, type, payload } = ev.data;
  try {
    // ── Chargement de la serie principale ────────────────────────────
    if (type === 'load') {
      const t0 = performance.now();
      const text = await payload.file.text();
      series = parseCsv(text);
      atrCache = new Map();
      if (!series.length) throw new Error('Aucune barre exploitable dans ce CSV.');
      atrProvider(14);
      postMessage({
        id,
        ok: true,
        result: {
          describe: describeSeries(series),
          parseMs: Math.round(performance.now() - t0),
          bytes: payload.file.size,
          name: payload.file.name,
        },
      });
      return;
    }

    // ── Series correlees (DXY / US10Y) ───────────────────────────────
    if (type === 'loadRef') {
      const text = await payload.file.text();
      const ref = RefSeries.fromText(payload.name, text);
      refs = refs || new RefBundle({});
      refs[payload.name === 'DXY' ? 'dxy' : 'us10y'] = ref;
      postMessage({
        id,
        ok: true,
        result: {
          name: payload.name,
          bars: ref.s.length,
          from: new Date(ref.s.time[0]).toISOString().slice(0, 10),
          to: new Date(ref.s.time[ref.s.length - 1]).toISOString().slice(0, 10),
        },
      });
      return;
    }

    // ── Calendrier economique ────────────────────────────────────────
    if (type === 'loadCalendar') {
      const text = await payload.file.text();
      calendar = EconomicCalendar.fromText(text);
      postMessage({ id, ok: true, result: { dates: calendar.byDate.size } });
      return;
    }

    if (type === 'clearRefs') {
      refs = null;
      calendar = null;
      postMessage({ id, ok: true, result: {} });
      return;
    }

    // ── Backtest ─────────────────────────────────────────────────────
    if (type === 'run') {
      if (!series) throw new Error('Chargez d abord un CSV de barres M5.');
      const t0 = performance.now();
      // buildConfig valide la surcharge : une valeur hors bornes leve ici,
      // avec un message explicite, plutot que de degrader le resultat.
      const cfg = buildConfig(resolveOverride(payload.override));
      const res = runBacktest(series, cfg, atrProvider, { collectTrades: true, collectEquity: true }, refs, calendar);
      const m = computeMetrics(res, cfg);
      last = { res, m, cfg };
      postMessage({
        id,
        ok: true,
        result: {
          runMs: Math.round(performance.now() - t0),
          metrics: m,
          funnel: res.funnel,
          orderStats: res.orderStats,
          trades: res.trades,
          config: cfg,
        },
      });
      return;
    }

    // ── Export du rapport HTML (meme rendu que le CLI) ───────────────
    if (type === 'exportHtml') {
      if (!last) throw new Error('Lancez un backtest avant d exporter.');
      postMessage({ id, ok: true, result: { html: renderHtml(last) } });
      return;
    }

    throw new Error(`Message inconnu : ${type}`);
  } catch (e) {
    fail(id, e);
  }
};

postMessage({ ready: true });
