/**
 * Rapports de backtest : console lisible, JSON, et page HTML autonome.
 */

import { writeFileSync } from 'node:fs';
import { renderHtml } from './render.js';

const DOW = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];

const n = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '-');
const pad = (v, w, d = 2) => n(v, d).padStart(w);

/** Rapport console complet. */
export function printReport(res, m, cfg, { title = 'BACKTEST' } = {}) {
  const line = (c = '─') => console.log(c.repeat(78));

  line('═');
  console.log(`  ${title} — ${cfg.instrument.symbol}`);
  line('═');

  console.log('\n  PARAMETRAGE ACTIF');
  console.log(`    periode            ${cfg.sessions.dateFrom || 'debut'} -> ${cfg.sessions.dateTo || 'fin'}`);
  console.log(`    Londres            ${cfg.sessions.londonStart}-${cfg.sessions.londonEnd} GMT (ancre ${cfg.sessions.londonAnchor})`);
  console.log(`    balayage           ${cfg.sessions.sweepStart}-${cfg.sessions.sweepEnd} GMT (ancre ${cfg.sessions.nyAnchor})`);
  console.log(`    signal pas avant   ${cfg.sessions.signalNotBefore} GMT`);
  console.log(`    confirmation max   ${cfg.sessions.confirmEnd} GMT | cloture forcee ${cfg.sessions.forceCloseAt} GMT`);
  console.log(`    entree             ${cfg.entry.model} niveau ${cfg.entry.model === 'fvg' ? cfg.entry.fvgLevel : cfg.entry.model === 'ote' ? cfg.entry.oteLevel : cfg.entry.obLevel}, expire ${cfg.entry.expiryBars} barres`);
  console.log(`    stop               ancre ${cfg.stop.anchor} + ${cfg.stop.buffer} ${cfg.stop.bufferMode}, borne ${cfg.stop.minDistance}-${cfg.stop.maxDistance} ${cfg.stop.distanceMode}`);
  console.log(`    objectif           ${cfg.target.anchor}, R:R min ${cfg.target.minRR}, decalage ${cfg.target.offset} ${cfg.target.offsetMode}`);
  console.log(`    balayage           penetration ${cfg.sweep.minPenetration}-${cfg.sweep.maxPenetration} ${cfg.sweep.penetrationMode}, cote ${cfg.sweep.side}`);
  console.log(`    filtres            premium=${cfg.filters.premiumDiscount} silverBullet=${cfg.filters.silverBullet} news=${cfg.filters.newsBlackout}`);
  console.log(`    gestion            BE=${cfg.manage.breakEvenAtRR ?? 'off'} partiel=${cfg.manage.partial.enabled ? cfg.manage.partial.anchor : 'off'} trail=${cfg.manage.trail} duree max=${cfg.manage.maxHoldBars} barres`);
  console.log(`    couts              spread ${cfg.costs.spreadUsd} $ (news ${cfg.costs.spreadUsdNews} $), slippage stop ${cfg.costs.slippageUsdOnStop} $, commission ${cfg.costs.commissionPerLotPerSide} $/lot/cote`);
  console.log(`    execution          intra-barre ${cfg.execution.intrabar}`);
  console.log(`    risque             ${cfg.risk.model} ${cfg.risk.pctPerTrade}% sur ${cfg.risk.initialEquity} $ (capitalisation ${cfg.risk.compounding})`);

  console.log('\n  ENTONNOIR DE SELECTION');
  const f = res.funnel;
  const pct = (a, b) => (b ? ` (${((a / b) * 100).toFixed(0)}%)` : '');
  console.log(`    jours observes           ${String(f.daysSeen).padStart(6)}`);
  console.log(`    jours armes (range OK)   ${String(f.daysArmed).padStart(6)}${pct(f.daysArmed, f.daysSeen)}`);
  console.log(`    jours avec balayage      ${String(f.daysSwept).padStart(6)}${pct(f.daysSwept, f.daysArmed)}   haut=${f.daysSweptHigh} bas=${f.daysSweptLow}`);
  console.log(`    jours avec cassure MSS   ${String(f.daysMssBreak).padStart(6)}${pct(f.daysMssBreak, f.daysSwept)}`);
  console.log(`    setups emis              ${String(f.setupsEmitted).padStart(6)}${pct(f.setupsEmitted, f.daysMssBreak)}   vente=${f.setupsSell} achat=${f.setupsBuy}`);
  console.log(`    ordres remplis           ${String(res.orderStats.filled).padStart(6)}${pct(res.orderStats.filled, res.orderStats.placed)}`);

  const rej = Object.entries(f.rejected).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (rej.length) {
    console.log('\n    principaux motifs de rejet');
    for (const [k, v] of rej.slice(0, 12)) console.log(`      ${k.padEnd(26)} ${String(v).padStart(6)}`);
  }

  console.log('\n    devenir des ordres places');
  for (const [k, v] of Object.entries(res.orderStats)) {
    if (v > 0) console.log(`      ${k.padEnd(26)} ${String(v).padStart(6)}`);
  }

  if (!m.trades) {
    console.log('\n  AUCUN TRADE — desserrez les filtres ou elargissez la periode.\n');
    return;
  }

  console.log('\n  RESULTATS');
  console.log(`    trades                   ${String(m.trades).padStart(8)}   soit ${n(m.tradesPerYear, 1)} / an sur ${n(m.years, 2)} ans`);
  console.log(`    taux de reussite         ${pad(m.winRate, 8, 1)} %   ${m.wins} gains / ${m.losses} pertes / ${m.scratches} nuls`);
  console.log(`    total                    ${pad(m.totalR, 8, 1)} R`);
  console.log(`    esperance                ${pad(m.expectancyR, 8, 3)} R / trade   (ecart-type ${n(m.rStdev, 2)})`);
  const se = m.rStdev / Math.sqrt(m.trades);
  const t = se > 0 ? m.expectancyR / se : NaN;
  console.log(`    t de Student             ${pad(t, 8, 2)}       ${Math.abs(t) > 2 ? '<-- significatif a 5%' : '<-- NON significatif (|t| < 2)'}`);
  console.log(`    profit factor            ${pad(m.profitFactor, 8, 2)}`);
  console.log(`    gain moyen / perte moy.  ${pad(m.avgWinR, 8, 2)} R / ${n(m.avgLossR, 2)} R   (payoff ${n(m.payoffRatio, 2)})`);
  console.log(`    R median / meilleur / pire ${pad(m.medianR, 6, 2)} / ${n(m.bestR, 2)} / ${n(m.worstR, 2)}`);
  console.log(`    drawdown max             ${pad(m.maxDdR, 8, 1)} R   = ${n(m.maxDdPct, 1)} % du capital`);
  console.log(`    facteur de recuperation  ${pad(m.recoveryFactor, 8, 2)}`);
  console.log(`    Sharpe / Sortino         ${pad(m.sharpe, 8, 2)} / ${n(m.sortino, 2)}`);
  console.log(`    plus longue serie        ${m.maxWinStreak} gains / ${m.maxLossStreak} pertes`);
  console.log(`    taux de remplissage      ${pad(m.fillRate, 8, 1)} %`);
  console.log(`    R:R planifie moyen       ${pad(m.avgRrPlanned, 8, 2)}`);
  console.log(`    MFE / MAE moyens         ${pad(m.avgMfeR, 8, 2)} R / ${n(m.avgMaeR, 2)} R`);
  console.log(`    duree moyenne            ${pad(m.avgHoldBars, 8, 1)} barres M5 (${n(m.avgHoldBars * 5 / 60, 1)} h)`);

  console.log('\n  CAPITAL');
  console.log(`    initial                  ${pad(cfg.risk.initialEquity, 10)} $`);
  console.log(`    final                    ${pad(m.finalEquity, 10)} $`);
  console.log(`    resultat net             ${pad(m.netPnl, 10)} $   = ${n(m.returnPct, 1)} %   (TCAM ${n(m.cagrPct, 1)} %)`);
  console.log(`    drawdown max             ${pad(m.maxDdUsd, 10)} $   = ${n(m.maxDdPct, 1)} %`);

  console.log('\n  PAR ANNEE');
  console.log('    annee  trades  reussite    total R   esperance');
  for (const y of Object.keys(m.byYear).sort()) {
    const v = m.byYear[y];
    console.log(`    ${y}   ${String(v.n).padStart(5)}   ${pad((v.wins / v.n) * 100, 7, 1)} %  ${pad(v.r, 9, 1)}   ${pad(v.r / v.n, 9, 3)}`);
  }

  console.log('\n  PAR SENS');
  console.log('    sens    trades  reussite    total R');
  for (const [k, v] of Object.entries(m.byDir)) {
    console.log(`    ${(k === 'sell' ? 'vente' : 'achat').padEnd(7)} ${String(v.n).padStart(5)}   ${pad((v.wins / v.n) * 100, 7, 1)} %  ${pad(v.r, 9, 1)}`);
  }

  console.log('\n  PAR JOUR DE LA SEMAINE');
  console.log('    jour        trades  reussite    total R');
  for (const k of Object.keys(m.byDow).sort()) {
    const v = m.byDow[k];
    console.log(`    ${DOW[k].padEnd(11)} ${String(v.n).padStart(5)}   ${pad((v.wins / v.n) * 100, 7, 1)} %  ${pad(v.r, 9, 1)}`);
  }

  console.log('\n  PAR MOTIF DE SORTIE');
  console.log('    motif          trades    total R    R moyen');
  for (const [k, v] of Object.entries(m.byExit).sort((a, b) => b[1].n - a[1].n)) {
    console.log(`    ${k.padEnd(14)} ${String(v.n).padStart(5)}  ${pad(v.r, 9, 1)}  ${pad(v.r / v.n, 9, 3)}`);
  }
  console.log('');
  line('═');
}

/** Liste des trades en console. */
export function printTrades(trades, limit = 0) {
  const list = limit > 0 ? trades.slice(-limit) : trades;
  console.log(`\n  TRADES (${list.length}${limit && trades.length > limit ? ` derniers sur ${trades.length}` : ''})`);
  console.log('    date        h.entree  sens   entree      SL       TP     sortie  motif        lots      R      $');
  for (const t of list) {
    console.log(
      `    ${t.date}  ${t.entryTime.slice(11, 16)}    ${(t.dir === 'sell' ? 'V' : 'A')}  ` +
        `${pad(t.entry, 9)} ${pad(t.sl, 8)} ${pad(t.tp, 8)} ${pad(t.exit, 9)}  ${t.exitReason.padEnd(11)} ` +
        `${pad(t.lots, 6)} ${pad(t.r, 6)} ${pad(t.pnl, 8)}`
    );
  }
  console.log('');
}

/** Ecrit un JSON complet. */
export function writeJson(path, payload) {
  writeFileSync(path, JSON.stringify(payload, null, 2));
}

/** Ecrit la page HTML autonome sur disque. */
export function writeHtml(path, opts) {
  writeFileSync(path, renderHtml(opts));
  return path;
}

export { renderHtml };
