#!/usr/bin/env node
/**
 * gs-optimize — recherche de parametres avec garde-fous anti-sur-ajustement.
 *
 * Trois modes :
 *   sensitivity  un parametre a la fois : quels reglages comptent ?
 *   grid         grille aleatoire sur l'IN-SAMPLE + validation OUT-OF-SAMPLE
 *                + groupe temoin + correlation de rang (le test qui compte)
 *   walkforward  reoptimisation glissante, resultat hors echantillon concatene
 *
 * Le score maximise n'est PAS le rendement : c'est l'esperance divisee par son
 * erreur-type, penalisee par le drawdown. Maximiser le rendement brut sur un
 * historique fini revient a choisir le bruit le plus flatteur.
 */

import { writeFileSync } from 'node:fs';
import { clone, deepMerge } from '../core/config.js';
import { EvalPool, expandGrid, sampleGrid, sensitivitySweep, walkForward } from '../backtest/optimize.js';
import { buildOverride, parseArgs } from './args.js';

const USAGE = `
gs-optimize — recherche de parametres (anti-sur-ajustement)

  gs-optimize sensitivity --csv <f> [--dims <f.json>]
  gs-optimize grid        --csv <f> [--n 5000] [--is-to 2024-12-31] [--top 60]
  gs-optimize walkforward --csv <f> [--n 1500]

  --csv <chemin>        CSV de barres M5  (obligatoire)
  --dims <chemin.json>  dimensions a explorer : [{"path":"stop.buffer","values":[...]}]
  --n <n>               taille de l'echantillon aleatoire (grid / walkforward)
  --is-from --is-to     bornes de l'in-sample (defaut : debut -> 2024-12-31)
  --oos-from --oos-to   bornes de l'out-of-sample (defaut : 2025-01-01 -> fin)
  --top <n>             nombre de configs validees en OOS (defaut 60)
  --min-trades <n>      nombre minimal de trades pour qu'une config soit notee
  --workers <n>         parallelisme (defaut : nombre de coeurs)
  --json <chemin>       ecrit le resultat complet
  --preset / --set      base de config commune a toutes les evaluations
  --help
`;

/** Dimensions par defaut : celles dont l'impact mesure est le plus fort. */
const DEFAULT_DIMS = [
  { path: 'entry.model', values: ['fvg', 'ote', 'orderBlock', 'fvgOrOb'] },
  { path: 'entry.fvgLevel', values: [0.25, 0.5, 0.75, 1.0] },
  { path: 'entry.expiryBars', values: [6, 9, 12, 18, 24] },
  { path: 'stop.anchor', values: ['sweepExtreme', 'structureExtreme'] },
  { path: 'stop.buffer', values: [0.15, 0.25, 0.4, 0.6] },
  { path: 'stop.maxDistance', values: [3, 4, 5, 6] },
  { path: 'target.anchor', values: ['oppositeLondon', 'rrMultiple', 'nearestOf'] },
  { path: 'target.minRR', values: [1.5, 2.0, 2.5, 3.0] },
  { path: 'target.rrMultiple', values: [3, 4, 5] },
  { path: 'sweep.maxPenetration', values: [1.5, 2.5, 3.5, 4.5] },
  { path: 'sweep.side', values: ['both', 'highOnly'] },
  { path: 'mss.ref', values: ['fractal', 'priorBar', 'lowestSinceCross'] },
  { path: 'mss.breakType', values: ['close', 'wick'] },
  { path: 'mss.maxBarsAfterSweep', values: [8, 12, 16] },
  { path: 'mss.displacement.minBodyAtrMult', values: [0.3, 0.6, 0.9] },
  { path: 'filters.premiumDiscount', values: ['off', 'mssLeg'] },
  { path: 'manage.maxHoldBars', values: [24, 48, 96] },
];

const f = (v, w, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '-').padStart(w);
const avg = (a, k) => (a.length ? a.reduce((s, x) => s + (Number.isFinite(x[k]) ? x[k] : 0), 0) / a.length : NaN);

/** Correlation de rang de Spearman. */
function spearman(pairs) {
  if (pairs.length < 6) return NaN;
  const rank = (v) => {
    const ix = v.map((a, i) => [a, i]).sort((a, b) => a[0] - b[0]);
    const r = new Array(v.length);
    ix.forEach(([, i], k) => (r[i] = k + 1));
    return r;
  };
  const rx = rank(pairs.map((p) => p[0]));
  const ry = rank(pairs.map((p) => p[1]));
  const n = pairs.length;
  const d2 = rx.reduce((s, v, i) => s + (v - ry[i]) ** 2, 0);
  return 1 - (6 * d2) / (n * (n * n - 1));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const mode = args._[0];
  if (args.flags.help || !mode) {
    console.log(USAGE);
    return;
  }
  const csvPath = args.flags.csv || process.env.GS_CSV;
  if (!csvPath) {
    console.error(USAGE);
    console.error('Erreur : --csv est obligatoire.');
    process.exitCode = 2;
    return;
  }

  const dims = args.flags.dims
    ? JSON.parse(await import('node:fs').then((fs) => fs.readFileSync(String(args.flags.dims), 'utf8')))
    : DEFAULT_DIMS;
  const base = buildOverride(args);
  const minTrades = args.flags['min-trades'] ? Number(args.flags['min-trades']) : 25;
  const workers = args.flags.workers ? Number(args.flags.workers) : undefined;

  // `null` ecrase desormais la valeur de base (cf. deepMerge) : une borne
  // absente doit donc etre transmise explicitement comme null pour effacer
  // celle de l'autre fenetre, jamais omise.
  const IS = {
    dateFrom: args.flags['is-from'] ? String(args.flags['is-from']) : null,
    dateTo: String(args.flags['is-to'] || '2024-12-31'),
  };
  const OOS = {
    dateFrom: String(args.flags['oos-from'] || '2025-01-01'),
    dateTo: args.flags['oos-to'] ? String(args.flags['oos-to']) : null,
  };

  const pool = await new EvalPool(String(csvPath), workers).start();
  const out = { mode, generatedAt: new Date().toISOString(), csv: String(csvPath), dims };

  try {
    if (mode === 'sensitivity') {
      const b = deepMerge(clone(base), { sessions: { ...IS } });
      console.log(`\n  SENSIBILITE — in-sample ${IS.dateFrom || 'debut'} -> ${IS.dateTo}\n`);
      const byParam = await sensitivitySweep(pool, b, dims, { minTrades });
      const rows = [];
      for (const [path, list] of byParam) {
        const valid = list.filter((r) => r.ok && r.metrics.trades >= 5);
        if (!valid.length) continue;
        const rs = valid.map((r) => r.metrics.totalR);
        rows.push({ path, spread: Math.max(...rs) - Math.min(...rs), list });
      }
      rows.sort((a, b2) => b2.spread - a.spread);
      for (const { path, spread, list } of rows) {
        console.log(`  ${path}   [amplitude ${spread.toFixed(1)} R]`);
        console.log('      valeur          trades  %reuss   totalR   esper.R     PF  maxDD_R  %rempl');
        for (const r of list) {
          if (!r.ok) {
            console.log(`      ${String(r.value).padEnd(15)} ERREUR ${r.error}`);
            continue;
          }
          const m = r.metrics;
          console.log(
            `      ${String(r.value).padEnd(15)}${f(m.trades, 6, 0)}${f(m.winRate, 8, 1)}${f(m.totalR, 9, 1)}` +
              `${f(m.expectancyR, 10, 3)}${f(m.profitFactor, 7, 2)}${f(m.maxDdR, 9, 1)}${f(m.fillRate, 8, 0)}`
          );
        }
        console.log('');
      }
      out.rows = rows.map((r) => ({ path: r.path, spread: r.spread, values: r.list.map((x) => ({ value: x.value, ok: x.ok, metrics: x.metrics, score: x.score })) }));
    } else if (mode === 'grid') {
      const N = args.flags.n ? Number(args.flags.n) : 5000;
      const TOP = args.flags.top ? Number(args.flags.top) : 60;
      const isBase = deepMerge(clone(base), { sessions: { ...IS } });
      const grid = N > 0 ? sampleGrid(isBase, dims, N, 20260915) : expandGrid(isBase, dims);
      console.log(`\n  GRILLE — ${grid.length} configs sur ${IS.dateFrom || 'debut'} -> ${IS.dateTo}`);
      const t0 = Date.now();
      const isRes = await pool.evaluate(grid, {
        minTrades,
        onProgress: (d, t) => { if (d % 1000 === 0) console.log(`    ${d}/${t}  (${((Date.now() - t0) / 1000).toFixed(0)}s)`); },
      });
      const ranked = isRes.map((r, i) => ({ i, r })).filter((x) => x.r?.ok && Number.isFinite(x.r.score)).sort((a, b) => b.r.score - a.r.score);
      console.log(`  configs valides (>=${minTrades} trades) : ${ranked.length}/${grid.length}`);

      const top = ranked.slice(0, TOP);
      const oosRes = await pool.evaluate(top.map((x) => deepMerge(clone(grid[x.i]), { sessions: { ...OOS } })), { minTrades: 1 });
      const rows = top.map((x, k) => ({
        params: dims.reduce((a, d) => { a[d.path] = d.path.split('.').reduce((o, kk) => o?.[kk], grid[x.i]); return a; }, {}),
        override: grid[x.i],
        isScore: x.r.score,
        is: x.r.metrics,
        oos: oosRes[k]?.ok ? oosRes[k].metrics : null,
      }));

      // Groupe temoin : configs valides tirees au hasard hors du top.
      let seed = 424242;
      const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
      const rest = ranked.slice(TOP);
      const picked = [];
      const used = new Set();
      while (picked.length < Math.min(TOP, rest.length)) {
        const k = Math.floor(rnd() * rest.length);
        if (used.has(k)) continue;
        used.add(k);
        picked.push(rest[k]);
      }
      const ctrlRes = picked.length
        ? await pool.evaluate(picked.map((x) => deepMerge(clone(grid[x.i]), { sessions: { ...OOS } })), { minTrades: 1 })
        : [];

      console.log(`\n  TOP ${Math.min(25, rows.length)} IN-SAMPLE -> resultat OUT-OF-SAMPLE (${OOS.dateFrom} -> ${OOS.dateTo || 'fin'})`);
      console.log('    #  IS:trad %reus  totR  espR   PF  ddR | OOS:trad %reus  totR  espR   PF  ddR');
      rows.slice(0, 25).forEach((r, k) => {
        const a = r.is;
        const b2 = r.oos;
        console.log(
          `  ${String(k + 1).padStart(3)}${f(a.trades, 7, 0)}${f(a.winRate, 6, 1)}${f(a.totalR, 6, 1)}${f(a.expectancyR, 6, 2)}${f(a.profitFactor, 5, 2)}${f(a.maxDdR, 5, 1)} |` +
            (b2 ? `${f(b2.trades, 8, 0)}${f(b2.winRate, 6, 1)}${f(b2.totalR, 6, 1)}${f(b2.expectancyR, 6, 2)}${f(b2.profitFactor, 5, 2)}${f(b2.maxDdR, 5, 1)}` : '   (aucun trade OOS)')
        );
      });

      const oosOk = rows.map((r) => r.oos).filter(Boolean);
      const ctrl = ctrlRes.filter((r) => r?.ok).map((r) => r.metrics);
      const posPct = (a) => (a.length ? (100 * a.filter((x) => x.totalR > 0).length) / a.length : NaN);
      const rho = spearman(rows.filter((r) => r.oos).map((r) => [r.isScore, r.oos.expectancyR]));
      console.log('\n  CONTROLE DE SUR-AJUSTEMENT');
      console.log('                        n    espR moy   totalR moy   % rentables OOS');
      console.log(`    top ${String(TOP).padEnd(15)}${String(oosOk.length).padStart(4)}${f(avg(oosOk, 'expectancyR'), 12, 3)}${f(avg(oosOk, 'totalR'), 13, 1)}${f(posPct(oosOk), 18, 0)} %`);
      console.log(`    temoin aleatoire  ${String(ctrl.length).padStart(4)}${f(avg(ctrl, 'expectancyR'), 12, 3)}${f(avg(ctrl, 'totalR'), 13, 1)}${f(posPct(ctrl), 18, 0)} %`);
      console.log(`\n    correlation de rang score IS <-> esperance OOS : ${f(rho, 6, 3)}`);
      console.log('    Lecture : proche de 0 => optimiser en in-sample n\'apporte rien en reel.');
      console.log('              Si le temoin fait aussi bien que le top, la grille n\'a trouve que du bruit.\n');
      out.is = IS; out.oos = OOS; out.validCount = ranked.length; out.rows = rows; out.control = ctrl; out.spearman = rho;
    } else if (mode === 'walkforward') {
      const N = args.flags.n ? Number(args.flags.n) : 1500;
      const folds = [
        { isFrom: '2021-05-19', isTo: '2023-06-30', oosFrom: '2023-07-01', oosTo: '2023-12-31' },
        { isFrom: '2021-05-19', isTo: '2023-12-31', oosFrom: '2024-01-01', oosTo: '2024-06-30' },
        { isFrom: '2021-05-19', isTo: '2024-06-30', oosFrom: '2024-07-01', oosTo: '2024-12-31' },
        { isFrom: '2021-05-19', isTo: '2024-12-31', oosFrom: '2025-01-01', oosTo: '2025-06-30' },
        { isFrom: '2021-05-19', isTo: '2025-06-30', oosFrom: '2025-07-01', oosTo: '2025-12-31' },
        { isFrom: '2021-05-19', isTo: '2025-12-31', oosFrom: '2026-01-01', oosTo: '2026-12-31' },
      ];
      console.log(`\n  WALK-FORWARD ANCRE — ${folds.length} fenetres, ${N} configs testees par fenetre\n`);
      const wf = await walkForward(pool, base, dims, folds, { sampleSize: N, minTradesIs: 20, rngSeed: 31337 });
      console.log('    fenetre hors echantillon   IS:trad espR  |  OOS:trad %reus  totalR  espR');
      let sumR = 0;
      let sumN = 0;
      for (const r of wf) {
        if (r.error) { console.log(`    ${r.fold.oosFrom} : ${r.error}`); continue; }
        const o = r.oos;
        sumR += o ? o.totalR : 0;
        sumN += o ? o.trades : 0;
        console.log(
          `    ${r.fold.oosFrom} -> ${r.fold.oosTo}${f(r.is.trades, 8, 0)}${f(r.is.expectancyR, 6, 2)}  |` +
            (o ? `${f(o.trades, 10, 0)}${f(o.winRate, 6, 1)}${f(o.totalR, 8, 1)}${f(o.expectancyR, 6, 2)}` : '   (aucun trade)')
        );
      }
      console.log('    ' + '-'.repeat(68));
      const espR = sumN ? sumR / sumN : NaN;
      console.log(`    CUMUL HORS ECHANTILLON : ${f(sumR, 6, 1)} R sur ${sumN} trades   (esperance ${f(espR, 6, 3)} R/trade)`);
      console.log('    C\'est le seul chiffre qui approche une performance realiste.\n');
      out.folds = wf; out.totalOosR = sumR; out.totalOosTrades = sumN;
    } else {
      console.error(USAGE);
      console.error(`Mode inconnu : ${mode}`);
      process.exitCode = 2;
      return;
    }
  } finally {
    await pool.stop();
  }

  if (args.flags.json) {
    writeFileSync(String(args.flags.json), JSON.stringify(out, null, 2));
    console.log(`  JSON ecrit : ${args.flags.json}`);
  }
}

main().catch((e) => {
  console.error(`\nErreur : ${e.message}\n`);
  if (process.env.GS_DEBUG) console.error(e.stack);
  process.exitCode = 1;
});
