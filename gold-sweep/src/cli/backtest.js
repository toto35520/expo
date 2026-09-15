#!/usr/bin/env node
/**
 * gs-backtest — rejoue la strategie sur un CSV de barres M5.
 *
 * Exemples
 *   node src/cli/backtest.js --csv data/xauusd-m5.csv
 *   node src/cli/backtest.js --csv d.csv --preset frequent --html out/r.html
 *   node src/cli/backtest.js --csv d.csv --set stop.buffer=0.4 --set target.minRR=3
 *   node src/cli/backtest.js --csv d.csv --from 2025-01-01 --trades 20
 */

import { buildConfig } from '../core/config.js';
import { describeSeries, loadCsv } from '../core/csv.js';
import { atr } from '../core/indicators.js';
import { EconomicCalendar } from '../core/calendar.js';
import { RefBundle, RefSeries } from '../core/refdata.js';
import { runBacktest } from '../backtest/engine.js';
import { computeMetrics } from '../backtest/metrics.js';
import { printReport, printTrades, writeHtml, writeJson } from '../backtest/report.js';
import { PRESETS } from '../core/presets.js';
import { buildOverride, parseArgs } from './args.js';

const USAGE = `
gs-backtest — backtest de la strategie NY Open Liquidity Sweep (XAUUSD)

  --csv <chemin>          CSV de barres M5 : time,open,high,low,close,volume  (obligatoire)
  --preset <nom>          ${Object.keys(PRESETS).join(' | ')}
  --config <chemin.json>  surcharge de config complete
  --set <cle=valeur>      surcharge ponctuelle, repetable (ex: --set stop.buffer=0.4)
  --from / --to <date>    borne la periode evaluee (YYYY-MM-DD)
  --equity <n>            capital initial          --risk <pct>   risque par trade en %
  --spread <usd>          spread moyen modelise
  --dxy <chemin.csv>      serie DXY pour le filtre de correlation
  --us10y <chemin.csv>    serie US10Y pour le filtre macro
  --calendar <chemin.csv> calendrier economique : date,impact,event
  --trades [n]            liste les trades (n derniers, 0 = tous)
  --html <chemin>         ecrit un rapport HTML autonome
  --json <chemin>         ecrit le resultat complet en JSON
  --quiet                 n'affiche que les metriques essentielles
  --help
`;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.flags.help || args.flags.h) {
    console.log(USAGE);
    return;
  }
  const csvPath = args.flags.csv || process.env.GS_CSV;
  if (!csvPath) {
    console.error(USAGE);
    console.error('Erreur : --csv est obligatoire (ou definissez GS_CSV).');
    process.exitCode = 2;
    return;
  }

  const cfg = buildConfig(buildOverride(args));

  const series = loadCsv(String(csvPath));
  if (!series.length) throw new Error('CSV vide apres filtrage');
  if (!args.flags.quiet) {
    const d = describeSeries(series);
    console.log(
      `\n  DONNEES  ${d.bars} barres M${d.timeframeMin}  ${d.from.slice(0, 10)} -> ${d.to.slice(0, 10)}  ` +
        `prix ${d.priceMin.toFixed(0)}-${d.priceMax.toFixed(0)}` +
        (d.skipped.skippedBadRows ? `  (${d.skipped.skippedBadRows} lignes rejetees)` : '')
    );
  }

  const cache = new Map();
  const atrProvider = (p) => {
    if (!cache.has(p)) cache.set(p, atr(series, p));
    return cache.get(p);
  };

  // Series correlees et calendrier, si fournis.
  let refs = null;
  if (args.flags.dxy || args.flags.us10y) {
    refs = new RefBundle({
      dxy: args.flags.dxy ? RefSeries.fromCsv('DXY', String(args.flags.dxy)) : null,
      us10y: args.flags.us10y ? RefSeries.fromCsv('US10Y', String(args.flags.us10y)) : null,
    });
    if (!args.flags.quiet) console.log('  REFERENCES ' + JSON.stringify(refs.describe()));
  }
  let calendar = null;
  if (args.flags.calendar) {
    calendar = EconomicCalendar.fromCsv(String(args.flags.calendar));
    if (!args.flags.quiet) console.log(`  CALENDRIER ${calendar.byDate.size} dates chargees`);
  }

  const t0 = Date.now();
  const res = runBacktest(series, cfg, atrProvider, { collectTrades: true, collectEquity: true }, refs, calendar);
  const m = computeMetrics(res, cfg);
  const elapsed = Date.now() - t0;

  if (args.flags.quiet) {
    console.log(
      JSON.stringify({
        trades: m.trades,
        winRate: +m.winRate?.toFixed(2),
        totalR: +m.totalR?.toFixed(2),
        expectancyR: +m.expectancyR?.toFixed(4),
        profitFactor: +m.profitFactor?.toFixed(3),
        maxDdR: +m.maxDdR?.toFixed(2),
        netPnl: +m.netPnl?.toFixed(2),
        fillRate: +m.fillRate?.toFixed(1),
      })
    );
  } else {
    printReport(res, m, cfg, { title: 'BACKTEST — NY Open Liquidity Sweep' });
    console.log(`  (calcule en ${elapsed} ms sur ${series.length} barres)\n`);
  }

  if (args.flags.trades !== undefined) {
    const lim = args.flags.trades === true ? 0 : Number(args.flags.trades);
    printTrades(res.trades, lim);
  }
  if (args.flags.html) {
    const p = writeHtml(String(args.flags.html), { res, m, cfg });
    console.log(`  rapport HTML ecrit : ${p}`);
  }
  if (args.flags.json) {
    writeJson(String(args.flags.json), {
      generatedAt: new Date().toISOString(),
      csv: String(csvPath),
      config: cfg,
      metrics: m,
      funnel: res.funnel,
      orderStats: res.orderStats,
      trades: res.trades,
      equityCurve: res.equityCurve,
    });
    console.log(`  JSON ecrit : ${args.flags.json}`);
  }
}

main().catch((e) => {
  console.error(`\nErreur : ${e.message}\n`);
  if (process.env.GS_DEBUG) console.error(e.stack);
  process.exitCode = 1;
});
