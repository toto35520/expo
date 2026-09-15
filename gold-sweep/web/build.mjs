#!/usr/bin/env node
/**
 * Construit `web/dist/` : le site statique deployable sur Vercel.
 *
 * Principe : le moteur N'EST PAS duplique. Ce script copie les modules
 * reellement utilises par le backtest depuis `src/`, en conservant
 * l'arborescence pour que les imports relatifs continuent de fonctionner.
 * `src/` reste la source unique de verite.
 *
 * Garde-fou : la construction ECHOUE si un module copie importe `node:*`.
 * Le navigateur ne peut pas les resoudre, et un echec de build est
 * preferable a une page blanche en production.
 */

import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const DIST = join(HERE, 'dist');

/** Modules du moteur necessaires cote navigateur. */
const ENGINE = [
  'src/core/config.js',
  'src/core/time.js',
  'src/core/csv.js',
  'src/core/indicators.js',
  'src/core/strategy.js',
  'src/core/calendar.js',
  'src/core/refdata.js',
  'src/core/presets.js',
  'src/backtest/engine.js',
  'src/backtest/metrics.js',
  'src/backtest/render.js',
];

rmSync(DIST, { recursive: true, force: true });
mkdirSync(DIST, { recursive: true });

// 1. Fichiers statiques du tableau de bord.
cpSync(join(HERE, 'public'), DIST, { recursive: true });

// 2. Moteur, avec verification de compatibilite navigateur.
const offenders = [];
for (const rel of ENGINE) {
  const src = join(ROOT, rel);
  const code = readFileSync(src, 'utf8');
  const bad = [...code.matchAll(/^\s*import[^;]*?['"](node:[^'"]+)['"]/gm)].map((m) => m[1]);
  if (bad.length) offenders.push(`${rel} importe ${[...new Set(bad)].join(', ')}`);
  const dest = join(DIST, 'engine', rel.replace(/^src\//, ''));
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, code);
}
if (offenders.length) {
  console.error('\nCONSTRUCTION INTERROMPUE — modules incompatibles navigateur :');
  for (const o of offenders) console.error('  - ' + o);
  console.error('\nDeplacez les acces disque dans src/core/load.js (seul module Node autorise).\n');
  process.exit(1);
}

// 3. Resultats de validation pre-calcules : la page est utile sans CSV.
const docs = {};
for (const f of ['01-sensibilite.txt', '02-robustesse.txt', '03-candidats.txt', '04-grille-surajustement.txt']) {
  try {
    docs[f] = readFileSync(join(ROOT, 'docs', f), 'utf8');
  } catch {
    /* preuve absente : la page l'indiquera */
  }
}
writeFileSync(join(DIST, 'validation.json'), JSON.stringify(docs));

// 4. Inventaire, pour verification.
const walk = (dir, acc = []) => {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) walk(p, acc);
    else acc.push(relative(DIST, p));
  }
  return acc;
};
const files = walk(DIST).sort();
console.log(`web/dist construit — ${files.length} fichiers`);
for (const f of files) console.log('  ' + f);
