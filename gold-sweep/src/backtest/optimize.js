/**
 * Recherche de parametres : balayage de sensibilite, grille, walk-forward.
 *
 * Principes appliques pour NE PAS sur-ajuster :
 *  - la grille tourne sur l'IN-SAMPLE uniquement, la validation se fait sur un
 *    OUT-OF-SAMPLE jamais vu pendant la recherche ;
 *  - le score penalise le faible nombre de trades (erreur-type de l'esperance)
 *    et le drawdown, au lieu de maximiser le rendement brut ;
 *  - le walk-forward ancre verifie que les parametres retenus tiennent sur des
 *    fenetres successives, pas seulement sur la moyenne.
 */

import { Worker } from 'node:worker_threads';
import { cpus } from 'node:os';
import { fileURLToPath } from 'node:url';
import { clone, deepMerge, setPath } from '../core/config.js';

const WORKER = fileURLToPath(new URL('./worker.js', import.meta.url));

/** Pool de workers evaluant des configurations en parallele. */
export class EvalPool {
  /** @param {string} csvPath @param {number} [size] */
  constructor(csvPath, size = Math.max(1, Math.min(cpus().length, 8))) {
    this.csvPath = csvPath;
    this.size = size;
    this.workers = [];
    this.ready = null;
  }

  async start() {
    this.workers = [];
    const readies = [];
    for (let i = 0; i < this.size; i++) {
      const w = new Worker(WORKER, { workerData: { csvPath: this.csvPath } });
      this.workers.push(w);
      readies.push(
        new Promise((resolve, reject) => {
          w.once('message', resolve);
          w.once('error', reject);
        })
      );
    }
    await Promise.all(readies);

    // UN SEUL ecouteur permanent par worker, qui delegue au lot en cours.
    // Attacher un ecouteur par appel a evaluate() les ferait s'accumuler :
    // les ecouteurs perimes des lots precedents recevraient aussi les
    // resultats suivants et ecraseraient leurs tableaux (les identifiants de
    // job repartent de 0 a chaque lot). C'est une source silencieuse de
    // resultats faux — d'ou cet ecouteur unique.
    for (const w of this.workers) {
      w.__sink = null;
      w.__fail = null;
      w.on('message', (msg) => {
        if (msg && msg.results && w.__sink) w.__sink(msg);
      });
      w.on('error', (e) => {
        if (w.__fail) w.__fail(e);
      });
    }
    return this;
  }

  /**
   * Evalue une liste d'overrides de config.
   * @param {Array<object>} overrides
   * @param {{minTrades?: number, onProgress?: (done:number,total:number)=>void}} [opts]
   * @returns {Promise<Array<object>>} resultats dans l'ordre des overrides
   */
  async evaluate(overrides, opts = {}) {
    const minTrades = opts.minTrades ?? 30;
    const jobs = overrides.map((override, id) => ({ id, override }));
    const out = new Array(jobs.length);
    let next = 0;
    let done = 0;
    const chunkSize = Math.max(1, Math.ceil(jobs.length / (this.workers.length * 8)));

    try {
      await Promise.all(
        this.workers.map(
          (w) =>
            new Promise((resolve, reject) => {
              const feed = () => {
                if (next >= jobs.length) return resolve();
                const chunk = jobs.slice(next, next + chunkSize);
                next += chunk.length;
                w.postMessage({ jobs: chunk, minTrades });
              };
              w.__sink = (msg) => {
                for (const r of msg.results) out[r.id] = r;
                done += msg.results.length;
                if (opts.onProgress) opts.onProgress(done, jobs.length);
                feed();
              };
              w.__fail = reject;
              feed();
            })
        )
      );
    } finally {
      // Detacher le lot courant : plus aucun message ne peut ecrire ici.
      for (const w of this.workers) {
        w.__sink = null;
        w.__fail = null;
      }
    }

    const missing = out.findIndex((r) => r === undefined);
    if (missing >= 0) {
      throw new Error(`Resultat manquant pour le job ${missing}/${jobs.length} : lot incomplet`);
    }
    return out;
  }

  async stop() {
    await Promise.all(this.workers.map((w) => w.terminate()));
    this.workers = [];
  }
}

/**
 * Produit le produit cartesien d'une specification de grille.
 * @param {object} base override de base
 * @param {Array<{path: string, values: Array<any>}>} dims
 * @returns {Array<object>} overrides
 */
export function expandGrid(base, dims) {
  let out = [clone(base)];
  for (const dim of dims) {
    const next = [];
    for (const cfg of out) {
      for (const v of dim.values) {
        const c = clone(cfg);
        setPath(c, dim.path, v);
        next.push(c);
      }
    }
    out = next;
  }
  return out;
}

/** Echantillonne aleatoirement une grille trop grande (recherche aleatoire). */
export function sampleGrid(base, dims, n, rngSeed = 1) {
  let seed = rngSeed;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  const seen = new Set();
  const out = [];
  let guard = 0;
  while (out.length < n && guard++ < n * 50) {
    const c = clone(base);
    const key = [];
    for (const dim of dims) {
      const v = dim.values[Math.floor(rnd() * dim.values.length)];
      setPath(c, dim.path, v);
      key.push(String(v));
    }
    const k = key.join('|');
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(c);
  }
  return out;
}

/**
 * Balayage de sensibilite : fait varier un parametre a la fois autour d'une
 * base. Sert a savoir QUELS parametres comptent avant de lancer une grille.
 *
 * @param {EvalPool} pool
 * @param {object} base
 * @param {Array<{path: string, values: Array<any>}>} dims
 * @param {object} [opts]
 */
export async function sensitivitySweep(pool, base, dims, opts = {}) {
  const overrides = [];
  const index = [];
  for (const dim of dims) {
    for (const v of dim.values) {
      const c = clone(base);
      setPath(c, dim.path, v);
      overrides.push(c);
      index.push({ path: dim.path, value: v });
    }
  }
  const res = await pool.evaluate(overrides, opts);
  const byParam = new Map();
  res.forEach((r, i) => {
    const { path, value } = index[i];
    if (!byParam.has(path)) byParam.set(path, []);
    byParam.get(path).push({ value, ...r });
  });
  return byParam;
}

/**
 * Walk-forward ancre : optimise sur [debut, splitN], valide sur la fenetre
 * suivante, puis avance. Renvoie la performance OOS concatenee.
 *
 * @param {EvalPool} pool
 * @param {object} base
 * @param {Array<{path:string, values:Array<any>}>} dims
 * @param {Array<{isFrom:string, isTo:string, oosFrom:string, oosTo:string}>} folds
 * @param {object} [opts]
 */
export async function walkForward(pool, base, dims, folds, opts = {}) {
  const out = [];
  for (const fold of folds) {
    // 1. Optimisation sur l'in-sample du fold.
    const isBase = deepMerge(clone(base), {
      sessions: { dateFrom: fold.isFrom, dateTo: fold.isTo },
    });
    const grid = opts.sampleSize
      ? sampleGrid(isBase, dims, opts.sampleSize, opts.rngSeed ?? 1)
      : expandGrid(isBase, dims);
    const isRes = await pool.evaluate(grid, { minTrades: opts.minTradesIs ?? 20 });

    let best = null;
    let bestIdx = -1;
    isRes.forEach((r, i) => {
      if (r && r.ok && Number.isFinite(r.score) && (!best || r.score > best.score)) {
        best = r;
        bestIdx = i;
      }
    });
    if (!best) {
      out.push({ fold, error: 'aucune config valide en in-sample' });
      continue;
    }

    // 2. Evaluation de la config gagnante sur l'out-of-sample.
    const winner = clone(grid[bestIdx]);
    const oosOverride = deepMerge(winner, {
      sessions: { dateFrom: fold.oosFrom, dateTo: fold.oosTo },
    });
    const [oos] = await pool.evaluate([oosOverride], { minTrades: 1 });

    out.push({
      fold,
      params: dims.reduce((acc, d) => {
        acc[d.path] = d.path.split('.').reduce((o, k) => o?.[k], winner);
        return acc;
      }, {}),
      is: best.metrics,
      isScore: best.score,
      oos: oos && oos.ok ? oos.metrics : null,
      oosError: oos && !oos.ok ? oos.error : null,
    });
  }
  return out;
}
