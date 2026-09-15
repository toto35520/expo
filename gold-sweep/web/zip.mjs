#!/usr/bin/env node
/**
 * Produit `out/gold-sweep.zip` : l'archive distribuable du projet.
 *
 * L'archive est ecrite dans `out/`, qui est ignore par git : un artefact de
 * build regenerable n'a pas sa place dans l'historique du depot (il le gonfle
 * definitivement et devient perime au commit suivant).
 *
 * Contenu : les sources, les tests, les preuves de validation, le tableau de
 * bord construit (`web/dist`, pour un deploiement sans build) et l'echantillon
 * CSV. Exclus : `out/` lui-meme, `node_modules`, `.git`, et tout `.env`.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PARENT = join(ROOT, '..');
const NAME = 'gold-sweep';
const OUT = join(ROOT, 'out', 'gold-sweep.zip');

mkdirSync(dirname(OUT), { recursive: true });

/**
 * Les identifiants ne doivent jamais partir dans une archive distribuee.
 *
 * Exclusions NOMMEES une par une, volontairement : `-x .env.*` aurait aussi
 * emporte `.env.exemple`, qui doit rester dans l'archive. Et `-i` n'est pas la
 * negation de `-x` — il restreint l'archive aux seuls motifs donnes, ce qui
 * produit une archive vide s'il est combine a `-x`.
 */
const EXCLUDE = [
  `${NAME}/out/*`,
  `${NAME}/node_modules/*`,
  `${NAME}/.git/*`,
  `${NAME}/.env`,
  `${NAME}/.env.local`,
  `${NAME}/.env.production`,
  `${NAME}/.vercel/*`,
  `${NAME}/*.token`,
  `${NAME}/secrets.json`,
  '*/.DS_Store',
];

try {
  execFileSync('zip', ['-rq', OUT, NAME, ...EXCLUDE.flatMap((e) => ['-x', e])], {
    cwd: PARENT,
    stdio: ['ignore', 'inherit', 'inherit'],
  });
} catch (e) {
  console.error(
    `\nEchec de la creation de l'archive : ${e.message}\n` +
      `La commande "zip" est-elle installee ? (apt install zip / brew install zip)\n`
  );
  process.exit(1);
}

const kb = Math.round(statSync(OUT).size / 1024);
const list = execFileSync('unzip', ['-l', OUT], { encoding: 'utf8' });
const files = (list.match(/^\s+\d+\s+\d{4}-\d{2}-\d{2}/gm) || []).length;
console.log(`out/gold-sweep.zip — ${kb} Ko, ${files} fichiers`);

/**
 * Garde-fou en profondeur : il doit etre PLUS LARGE que `EXCLUDE`, sinon il ne
 * peut jamais se declencher et ne sert a rien. Il attrape les noms de fichiers
 * sensibles qu'on n'a pas pense a exclure — une cle privee, un fichier
 * d'identifiants, un `.npmrc` avec un jeton.
 */
const SECRET_NAME =
  /\/(\.env(\.[\w-]+)?|\.npmrc|\.netrc|id_[rd]sa|[\w.-]*(secret|credential|password|token|apikey|api-key)[\w.-]*|[\w.-]+\.(pem|key|p12|pfx|keystore|jks))\s*$/i;
const leaked = list
  .split('\n')
  .map((l) => l.trimEnd())
  .filter((l) => SECRET_NAME.test(l) && !/\.env\.exemple$/.test(l));
if (leaked.length) {
  console.error('\nARCHIVE REFUSEE — fichiers sensibles inclus :');
  for (const l of leaked) console.error('  ' + l.trim());
  process.exit(1);
}
console.log('aucun fichier sensible dans l archive');
