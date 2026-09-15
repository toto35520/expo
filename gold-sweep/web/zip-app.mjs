#!/usr/bin/env node
/**
 * Produit `out/gold-sweep-vercel.zip` : l'APPLICATION SEULE, prete a deposer
 * sur Vercel.
 *
 * Difference avec `zip.mjs` : ici les fichiers sont a la RACINE de l'archive
 * (pas dans un sous-dossier), il n'y a aucun build a lancer, aucun CLI, aucune
 * dependance. On dezippe, on depose, c'est en ligne.
 */

import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const DIST = join(HERE, 'dist');
const STAGE = join(ROOT, 'out', '_app');
const OUT = join(ROOT, 'out', 'gold-sweep-vercel.zip');

rmSync(STAGE, { recursive: true, force: true });
mkdirSync(STAGE, { recursive: true });

// 1. Le site construit, a la racine.
cpSync(DIST, STAGE, { recursive: true });

// 2. Un echantillon pour essayer tout de suite.
cpSync(join(ROOT, 'data', 'echantillon-xauusd-m5.csv'), join(STAGE, 'exemple-xauusd-m5.csv'));

// 3. Config Vercel minimale : PAS de buildCommand — le site est deja construit.
writeFileSync(
  join(STAGE, 'vercel.json'),
  JSON.stringify(
    {
      $schema: 'https://openapi.vercel.sh/vercel.json',
      headers: [
        {
          source: '/(.*)',
          headers: [
            { key: 'X-Content-Type-Options', value: 'nosniff' },
            { key: 'Referrer-Policy', value: 'no-referrer' },
          ],
        },
      ],
    },
    null,
    2
  ) + '\n'
);

// 4. Mode d'emploi court.
writeFileSync(
  join(STAGE, 'README.md'),
  `# Gold Sweep — application web

Site **statique**. Rien a installer, rien a construire.

## Deployer sur Vercel

1. <https://vercel.com/new>
2. Glissez ce dossier (ou son contenu) dans la zone de depot
3. Framework Preset : **Other** — laissez Build Command et Output Directory VIDES
4. Deploy

En ligne de commande :

\`\`\`bash
npx vercel --prod
\`\`\`

## Essayer en local

Un serveur HTTP est necessaire (les Web Workers ne fonctionnent pas en \`file://\`) :

\`\`\`bash
npx serve .
# ou
python3 -m http.server 8000
\`\`\`

## Utilisation

Deposez un CSV de barres M5 au format \`time,open,high,low,close,volume\`
(time en ISO 8601 UTC). \`exemple-xauusd-m5.csv\` est fourni pour un essai
immediat.

Le backtest tourne **dans votre navigateur**. Votre fichier ne part nulle part :
aucun televersement, aucune requete sortante, aucune telemetrie.

## Ce que cette page ne fait pas

Le suivi cTrader **temps reel** n'est pas ici : il exige une socket TLS
persistante qu'un hebergement serverless ne peut pas tenir, et aucune cle d'API
ne doit vivre dans un navigateur. Cette page est la surface d'analyse et de
backtest.

## Avertissement

Le backtest de cette strategie **ne demontre pas d'avantage statistique**
(t de Student 0,94 sur 22 trades, la ou il faut |t| > 2). Le detail est affiche
en haut de la page. Outil de recherche — le trading de l'or avec effet de levier
peut faire perdre la totalite du capital.
`
);

// 5. Archive avec les fichiers a la racine.
rmSync(OUT, { force: true });
execFileSync('zip', ['-rq', OUT, '.', '-x', '*/.DS_Store'], {
  cwd: STAGE,
  stdio: ['ignore', 'inherit', 'inherit'],
});

const list = execFileSync('unzip', ['-l', OUT], { encoding: 'utf8' });
const files = (list.match(/^\s+\d+\s+\d{4}-\d{2}-\d{2}/gm) || []).length;
console.log(`out/gold-sweep-vercel.zip — ${Math.round(statSync(OUT).size / 1024)} Ko, ${files} fichiers`);
console.log('');
console.log(list.split('\n').filter((l) => /\d{2}:\d{2}\s{3}/.test(l)).map((l) => '  ' + l.trim().split(/\s{3}/).pop()).join('\n'));

rmSync(STAGE, { recursive: true, force: true });
