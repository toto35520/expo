/**
 * Worker d'evaluation de configurations.
 * Le CSV et les ATR sont charges UNE fois au demarrage du worker, puis
 * chaque message evalue un override de config. C'est ce qui rend la
 * recherche sur grille exploitable (des milliers de backtests).
 */
import { parentPort, workerData } from 'node:worker_threads';
import { buildConfig } from '../core/config.js';
import { loadCsv } from '../core/csv.js';
import { atr } from '../core/indicators.js';
import { runBacktest } from './engine.js';
import { computeMetrics, score } from './metrics.js';

const series = loadCsv(workerData.csvPath);
const atrCache = new Map();
const atrProvider = (p) => {
  if (!atrCache.has(p)) atrCache.set(p, atr(series, p));
  return atrCache.get(p);
};
// Prechauffage de l'ATR par defaut.
atrProvider(14);

parentPort.on('message', (msg) => {
  if (msg.type === 'stop') {
    parentPort.close();
    return;
  }
  const results = [];
  for (const job of msg.jobs) {
    try {
      const cfg = buildConfig(job.override);
      const res = runBacktest(series, cfg, atrProvider, {
        collectTrades: true,
        collectEquity: false,
      });
      const m = computeMetrics(res, cfg);
      results.push({
        id: job.id,
        ok: true,
        score: score(m, { minTrades: msg.minTrades }),
        metrics: {
          trades: m.trades,
          winRate: m.winRate,
          totalR: m.totalR,
          expectancyR: m.expectancyR,
          rStdev: m.rStdev,
          profitFactor: m.profitFactor,
          maxDdR: m.maxDdR,
          maxDdPct: m.maxDdPct,
          sharpe: m.sharpe,
          recoveryFactor: m.recoveryFactor,
          fillRate: m.fillRate,
          tradesPerYear: m.tradesPerYear,
          avgRrPlanned: m.avgRrPlanned,
          payoffRatio: m.payoffRatio,
          maxLossStreak: m.maxLossStreak,
          returnPct: m.returnPct,
          byExit: m.byExit,
          byYear: m.byYear,
          byDir: m.byDir,
        },
        orderStats: res.orderStats,
      });
    } catch (e) {
      results.push({ id: job.id, ok: false, error: String(e.message || e) });
    }
  }
  parentPort.postMessage({ results });
});

parentPort.postMessage({ ready: true });
