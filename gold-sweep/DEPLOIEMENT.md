# Déploiement sur Vercel

Le tableau de bord est un **site statique** : aucune fonction serverless, aucune
base de données, aucune clé d'API. Le backtest tourne **dans le navigateur du
visiteur**, dans un Web Worker. Votre CSV ne quitte jamais votre machine.

## Ce qui est déployable, et ce qui ne l'est pas

| Fonction | Sur Vercel | Pourquoi |
|---|---|---|
| Backtest complet (376 k barres) | ✅ | moteur JS pur, exécuté côté client |
| Réglage des 132 paramètres | ✅ | |
| Graphiques, entonnoir, export | ✅ | |
| Confluences DXY / US10Y | ✅ | vous déposez les CSV localement |
| **Suivi cTrader temps réel** | ❌ | exige une **socket TLS persistante** ; le serverless coupe la connexion à chaque requête |
| **Placement d'ordres** | ❌ | même raison, et aucun secret ne doit vivre dans un navigateur |

Le live reste en CLI local :

```bash
node src/cli/live.js watch --symbol XAUUSD
```

Le moteur exécuté est **exactement le même** dans les deux cas — les modules sous
`web/dist/engine/` sont copiés depuis `src/` à la construction, `src/` reste la
source unique de vérité.

---

## Option 1 — Import Git (recommandé)

1. Poussez ce dossier sur un dépôt GitHub / GitLab / Bitbucket.
2. Sur <https://vercel.com/new>, importez le dépôt.
3. **Si `gold-sweep` est un sous-dossier du dépôt**, renseignez
   *Root Directory* = `gold-sweep`. Sinon, laissez vide.
4. Vercel lit `vercel.json` et applique automatiquement :
   - Build Command : `node web/build.mjs`
   - Output Directory : `web/dist`
   - Install Command : aucune (le projet n'a **aucune dépendance**)
   - Framework Preset : *Other*
5. Déployez. Chaque push redéploie.

## Option 2 — CLI Vercel

```bash
npm i -g vercel
cd gold-sweep
vercel            # préversion, URL partageable
vercel --prod     # production
```

## Option 3 — Glisser-déposer, sans build

Le dossier `web/dist/` est déjà construit et autonome :

```bash
node web/build.mjs          # (re)génère web/dist
```

Déposez ensuite `web/dist` sur <https://vercel.com/new> (onglet de dépôt direct),
ou servez-le par n'importe quel hébergeur statique (Netlify, Cloudflare Pages,
GitHub Pages, `nginx`…).

## Vérifier en local avant de déployer

Un serveur HTTP est nécessaire : les modules ES et les Web Workers ne
fonctionnent pas depuis `file://`.

```bash
node web/build.mjs
npx serve web/dist          # ou : python3 -m http.server -d web/dist 8000
```

Ouvrez l'URL, déposez `data/echantillon-xauusd-m5.csv` (fourni, ~6 semaines de
barres M5) pour un essai immédiat, puis votre historique complet.

---

## Notes techniques

**Aucune dépendance.** `installCommand` est neutralisé dans `vercel.json`.
Si Vercel signale une absence de `package-lock.json`, c'est normal.

**La construction échoue volontairement** si un module du moteur importe
`node:*` : le navigateur ne sait pas les résoudre, et un échec de build est
préférable à une page blanche en production. Les accès disque vivent
exclusivement dans `src/core/load.js`, qui n'est jamais copié côté web.

**Compatibilité navigateur.** Modules ES, Web Workers de type module,
`structuredClone`, `File.text()`. Chrome/Edge 89+, Firefox 114+, Safari 15.4+.

**Taille.** `web/dist` pèse environ 250 Ko, dont ~200 Ko de moteur et les
preuves de validation. Aucune police ni bibliothèque externe n'est chargée.

**En-têtes.** `vercel.json` pose `X-Content-Type-Options: nosniff` et
`Referrer-Policy: no-referrer`. Le moteur est mis en cache une heure ; la page
ne l'est pas, pour que vos mises à jour de configuration soient visibles
immédiatement.

**Confidentialité.** Aucune requête sortante, aucune télémétrie, aucun cookie.
La seule écriture locale est la préférence de thème (`localStorage`), et son
échec est rattrapé.
