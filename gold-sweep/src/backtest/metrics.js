/**
 * Statistiques de performance a partir de la liste des trades.
 * Tout est exprime en R (multiples de risque) ET en USD : le R est
 * comparable entre configurations, l'USD parle au compte reel.
 */

/** Quantile d'un tableau de nombres. */
function quantile(arr, p) {
  if (!arr.length) return NaN;
  const b = arr.slice().sort((a, c) => a - c);
  return b[Math.min(b.length - 1, Math.max(0, Math.floor(p * b.length)))];
}

function mean(a) {
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
}

function stdev(a) {
  if (a.length < 2) return NaN;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1));
}

/**
 * @param {object} res resultat de runBacktest
 * @param {object} cfg
 */
export function computeMetrics(res, cfg) {
  const t = res.trades;
  const n = t.length;
  const rs = t.map((x) => x.r);
  const pnls = t.map((x) => x.pnl);

  const wins = t.filter((x) => x.pnl > 0);
  const losses = t.filter((x) => x.pnl < 0);
  const scratches = t.filter((x) => x.pnl === 0);

  const grossWin = wins.reduce((s, x) => s + x.pnl, 0);
  const grossLoss = -losses.reduce((s, x) => s + x.pnl, 0);

  // Drawdown recalcule sur la courbe des R cumules (independant du sizing).
  let cum = 0;
  let peak = 0;
  let maxDdR = 0;
  const cumR = [];
  for (const r of rs) {
    cum += r;
    cumR.push(cum);
    if (cum > peak) peak = cum;
    if (peak - cum > maxDdR) maxDdR = peak - cum;
  }

  // Sequences
  let curW = 0;
  let curL = 0;
  let maxW = 0;
  let maxL = 0;
  for (const x of t) {
    if (x.pnl > 0) {
      curW++;
      curL = 0;
      if (curW > maxW) maxW = curW;
    } else if (x.pnl < 0) {
      curL++;
      curW = 0;
      if (curL > maxL) maxL = curL;
    }
  }

  // Sharpe / Sortino sur les R par trade, annualises par le nombre de trades/an.
  const spanMs = n ? t[n - 1].exitTs - t[0].entryTs : 0;
  const years = spanMs / (365.25 * 86_400_000);
  const tradesPerYear = years > 0 ? n / years : NaN;
  const rMean = mean(rs);
  const rSd = stdev(rs);
  const downside = rs.filter((r) => r < 0);
  const dSd = downside.length > 1 ? Math.sqrt(downside.reduce((s, v) => s + v * v, 0) / downside.length) : NaN;

  const sharpe = Number.isFinite(rSd) && rSd > 0 ? (rMean / rSd) * Math.sqrt(tradesPerYear) : NaN;
  const sortino = Number.isFinite(dSd) && dSd > 0 ? (rMean / dSd) * Math.sqrt(tradesPerYear) : NaN;

  const totalR = cum;
  const netPnl = res.finalEquity - cfg.risk.initialEquity;
  const retPct = (netPnl / cfg.risk.initialEquity) * 100;
  const cagr =
    years > 0 && res.finalEquity > 0
      ? ((res.finalEquity / cfg.risk.initialEquity) ** (1 / years) - 1) * 100
      : NaN;

  // Ventilation par raison de sortie
  const byExit = {};
  for (const x of t) {
    byExit[x.exitReason] = byExit[x.exitReason] || { n: 0, r: 0 };
    byExit[x.exitReason].n++;
    byExit[x.exitReason].r += x.r;
  }

  // Ventilation par annee et par sens
  const byYear = {};
  for (const x of t) {
    const y = x.date.slice(0, 4);
    byYear[y] = byYear[y] || { n: 0, r: 0, wins: 0 };
    byYear[y].n++;
    byYear[y].r += x.r;
    if (x.pnl > 0) byYear[y].wins++;
  }
  const byDir = {};
  for (const x of t) {
    byDir[x.dir] = byDir[x.dir] || { n: 0, r: 0, wins: 0 };
    byDir[x.dir].n++;
    byDir[x.dir].r += x.r;
    if (x.pnl > 0) byDir[x.dir].wins++;
  }
  const byDow = {};
  for (const x of t) {
    const d = new Date(x.entryTs).getUTCDay();
    byDow[d] = byDow[d] || { n: 0, r: 0, wins: 0 };
    byDow[d].n++;
    byDow[d].r += x.r;
    if (x.pnl > 0) byDow[d].wins++;
  }

  const fillRate = res.orderStats.placed ? res.orderStats.filled / res.orderStats.placed : 0;

  return {
    trades: n,
    wins: wins.length,
    losses: losses.length,
    scratches: scratches.length,
    winRate: n ? (wins.length / n) * 100 : NaN,

    totalR,
    expectancyR: rMean,
    rStdev: rSd,
    medianR: quantile(rs, 0.5),
    bestR: n ? Math.max(...rs) : NaN,
    worstR: n ? Math.min(...rs) : NaN,

    avgWinR: wins.length ? mean(wins.map((x) => x.r)) : NaN,
    avgLossR: losses.length ? mean(losses.map((x) => x.r)) : NaN,
    payoffRatio: losses.length && wins.length ? mean(wins.map((x) => x.r)) / -mean(losses.map((x) => x.r)) : NaN,

    profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : NaN,
    netPnl,
    finalEquity: res.finalEquity,
    returnPct: retPct,
    cagrPct: cagr,
    maxDdUsd: res.maxDd,
    maxDdPct: res.maxDdPct,
    maxDdR,
    recoveryFactor: maxDdR > 0 ? totalR / maxDdR : NaN,
    sharpe,
    sortino,

    maxWinStreak: maxW,
    maxLossStreak: maxL,

    years,
    tradesPerYear,
    fillRate: fillRate * 100,
    avgRrPlanned: mean(t.map((x) => x.rrPlanned)),
    avgHoldBars: mean(t.map((x) => x.holdBars)),
    avgMfeR: mean(t.map((x) => x.mfeR)),
    avgMaeR: mean(t.map((x) => x.maeR)),

    byExit,
    byYear,
    byDir,
    byDow,
    cumR,
  };
}

/**
 * Score composite utilise par l'optimiseur.
 * Penalise le faible nombre de trades (sur-ajustement) et le drawdown.
 * @param {object} m metriques
 * @param {{minTrades?: number}} [opts]
 */
export function score(m, opts = {}) {
  const minTrades = opts.minTrades ?? 30;
  if (!m.trades || !Number.isFinite(m.expectancyR)) return -Infinity;
  if (m.trades < minTrades) return -Infinity;

  // Esperance ajustee de son erreur-type : recompense la robustesse
  // statistique, pas le coup de chance sur 12 trades.
  const se = m.rStdev / Math.sqrt(m.trades);
  const tStat = Number.isFinite(se) && se > 0 ? m.expectancyR / se : 0;

  const ddPenalty = m.maxDdR > 0 ? Math.min(1, 8 / m.maxDdR) : 1;
  return tStat * ddPenalty;
}
