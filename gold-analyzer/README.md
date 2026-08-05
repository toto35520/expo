# Gold Desk — analyse XAU/USD en 14 couches

Application web (PWA installable sur téléphone) qui analyse l'or couche par couche à partir de tes graphiques, puis **refuse ou valide** un trade selon des conditions éliminatoires calculées, pas selon une impression.

> **Ce que cet outil n'est pas.** Il ne prédit pas le marché et ne garantit aucun trade gagnant. Sa valeur vient de sa capacité à dire non : la plupart des configurations reçoivent la note **NO TRADE**. Un outil qui valide tout ne sert à rien. Cadre pédagogique — pas un conseil en investissement.

---

## Ce qu'il fait

1. Tu déposes tes graphiques (W1, D1, H4, H1, M30, M5 — autant que tu veux).
2. Tu renseignes ce qu'un graphique ne peut pas montrer : DXY, taux réels, COT, GEX, prime de Shanghai, calendrier…
3. Claude analyse **les 14 couches, une par une, sans exception**.
4. L'application — pas le modèle — calcule le score, applique **11 conditions éliminatoires** et rend un verdict.
5. Si le trade passe, tu l'envoies au journal, qui le suit jusqu'à la clôture et calcule ton espérance réelle.

### Les 14 couches

| # | Couche | Poids | Éliminatoire |
|---|---|---:|:---:|
| 1 | Macro & taux réels | 12 | |
| 2 | Calendrier économique & risque événementiel | 6 | ● |
| 3 | Structure de marché multi-timeframe | 14 | ● |
| 4 | Niveaux clés & pools de liquidité | 10 | |
| 5 | Order flow & volume réel | 8 | |
| 6 | Price action & mécanique (FVG, OB, sweeps) | 8 | |
| 7 | Options & positionnement dealer | 5 | |
| 8 | Marché physique & courbe des futures | 4 | |
| 9 | Flux & positionnement | 5 | |
| 10 | Corrélations intermarchés | 6 | |
| 11 | Détection de régime | 8 | ● |
| 12 | Saisonnalité & timing de session | 3 | |
| 13 | Réaction au news | 4 | |
| 14 | Exécution, dimensionnement & risque | 7 | ● |

### Les conditions éliminatoires

Une seule qui échoue annule le trade, **quel que soit le score**.

- Les 4 couches éliminatoires ne sont pas en FAIL
- Un setup existe réellement
- Entrée / stop / objectif cohérents avec la direction
- R:R au TP1 ≥ 1,5
- Stop compris entre 0,35 × et 3 × l'ATR journalier (**ATR obligatoire**)
- Position dimensionnable au risque demandé sans descendre sous le lot minimum
- Confiance globale ≥ 40 / 100
- Complétude des données ≥ 35 / 100

### Pourquoi deux chiffres et pas un seul

- **Score** : la qualité du setup.
- **Confiance** : ce qu'on en sait réellement.

Les confondre est malhonnête. Un score de 90 sur une confiance de 20 ne vaut rien, et l'outil le refuse. Une couche `UNKNOWN` est ramenée à 50 quel que soit le score renvoyé : **une donnée absente n'est jamais un argument favorable**.

---

## Déploiement sur Vercel

### 1. Récupérer une clé API

Sur [console.anthropic.com](https://console.anthropic.com/settings/keys). L'app tourne sur `claude-opus-5`.

### 2. Importer le projet

Sur [vercel.com/new](https://vercel.com/new), importe ce dépôt.

**Réglage indispensable** — ce dossier vit dans le monorepo Expo, il faut donc pointer Vercel dessus :

| Champ | Valeur |
|---|---|
| **Root Directory** | `gold-analyzer` |
| Framework Preset | Next.js (détecté automatiquement) |
| Build Command | par défaut |

### 3. Variable d'environnement

Project Settings → Environment Variables :

```
ANTHROPIC_API_KEY = sk-ant-...
```

Optionnel : `ANTHROPIC_MODEL` pour changer de modèle.

La clé reste **côté serveur** — elle n'est jamais exposée au navigateur.

### 4. Installer sur le téléphone

- **iPhone** : ouvrir l'URL dans Safari → Partager → « Sur l'écran d'accueil »
- **Android** : Chrome → menu → « Installer l'application »

---

## Durée d'exécution et plans Vercel

Une analyse vision sur 4-6 graphiques à effort élevé prend **60 à 180 secondes**. La route déclare `maxDuration = 300`.

| Plan | Durée max | Résultat |
|---|---|---|
| Hobby | 300 s (Fluid Compute, activé par défaut) | fonctionne |
| Pro | 300 s+ | fonctionne |

Si tu obtiens un timeout : réduis le nombre de graphiques, ou vérifie que Fluid Compute est actif (Project Settings → Functions).

La réponse est diffusée en flux continu (NDJSON), ce qui maintient la connexion ouverte et affiche la progression pendant l'analyse.

---

## Développement local

```bash
cd gold-analyzer
npm install
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env.local
npm run dev
```

Sur http://localhost:3000.

```bash
npm run build       # build de production
npm run typecheck   # vérification TypeScript
node scripts/make-icons.mjs   # régénère les icônes PWA
```

---

## Coût par analyse

`claude-opus-5` : 5 $ / M tokens en entrée, 25 $ / M en sortie.

Une analyse typique — 5 graphiques + contexte + raisonnement + rapport complet :

| Poste | Ordre de grandeur |
|---|---|
| Images (5 × ~4 800 tokens) | ~24 000 |
| Prompt système + contexte | ~4 000 |
| Raisonnement + rapport | ~8 000 |
| **Coût** | **~0,35 $** |

Les captures sont redimensionnées à 2 576 px sur le grand côté côté navigateur — au-delà, l'API redimensionne de toute façon, donc les pixels en plus ne sont que du coût.

---

## Données et vie privée

Trades, analyses et contexte sont stockés dans le **localStorage du navigateur**. Rien n'est envoyé à un serveur en dehors de l'appel à l'API Anthropic pendant l'analyse.

Conséquence : vider le cache du navigateur efface tout. Le journal a un bouton **Exporter** / **Importer** — sers-t'en.

---

## Le journal

C'est la partie qui fait progresser, et celle que presque personne ne remplit.

- **Espérance** = (taux de réussite × gain moyen) − (taux de perte × perte moyenne), en R. Un avertissement s'affiche sous 100 trades : en dessous, le taux de réussite est du bruit.
- **MAE / MFE** : jusqu'où le prix est allé contre toi avant de repartir, et jusqu'où il est allé en ta faveur avant ta sortie. L'app en tire des verdicts directs — stop trop large, sortie trop tôt, perdants qui passent en positif avant de tourner.
- **Attribution** par setup, session, direction et note. Le résultat typique : un seul setup génère tout le profit.
- **Monte-Carlo** : tes propres trades remélangés 2 000 fois, pour connaître ton drawdown réaliste au 95e centile — celui pour lequel il faut dimensionner.
- **Kelly fractionnaire** à partir de 30 trades.
- **Note d'exécution** séparée du P&L : un trade gagnant mal exécuté reste un mauvais trade.

---

## Suivi d'un trade ouvert

Depuis le journal, bouton **Réévaluer la thèse** sur un trade en attente ou ouvert. Recharge les graphiques actuels : l'analyse porte alors sur la validité de la thèse (invalidation touchée ? structure retournée ? ajustement justifié ?), pas sur un nouveau setup. L'immobilité est traitée comme une réponse valide.

---

## Architecture

```
gold-analyzer/
├── app/
│   ├── page.tsx                  écran d'analyse
│   ├── journal/page.tsx          journal + statistiques
│   └── api/analyze/route.ts      appel Claude (vision + sortie structurée), flux NDJSON
├── lib/
│   ├── modules.ts                les 14 couches, poids, couches éliminatoires
│   ├── prompt.ts                 prompt système et contexte
│   ├── schema.ts                 schéma JSON de la sortie structurée
│   ├── scoring.ts                score, confiance, conditions éliminatoires, note
│   ├── sizing.ts                 dimensionnement XAUUSD
│   ├── stats.ts                  espérance, MAE/MFE, attribution, Monte-Carlo, Kelly
│   ├── image.ts                  redimensionnement navigateur
│   └── storage.ts                persistance localStorage
└── components/                   Dropzone, ContextForm, Report, Nav
```

**Séparation volontaire** : le modèle juge chaque couche indépendamment ; l'application calcule le score, applique les conditions éliminatoires et rend le verdict. Le modèle ne peut pas s'auto-attribuer une bonne note.

### Garde-fous dans le prompt

- Interdiction d'inventer un prix, un ATR ou un volume non lisible sur les graphiques fournis
- Le volume d'un graphique CFD est du **tick volume** — la couche order flow est plafonnée à une confiance faible sur cette seule base
- Le vocabulaire SMC est traduit en mécanique : FVG → zone de faible volume, order block → point d'initiation, sweep → cascade de stops. Ce sont des outils de **timing d'entrée**, jamais une thèse directionnelle
- Mode d'entrée par défaut sur l'or : **confirmation** (balayage → changement de caractère), jamais un ordre limite nu
- Aucune probabilité de réussite chiffrée, aucun langage de certitude
- `hasTrade: false` est la réponse attendue par défaut

---

## Limites connues

- **Une clé API est nécessaire** — l'app n'a pas de mode démo.
- **Aucune donnée de marché n'est récupérée automatiquement.** DXY, COT, GEX, prime de Shanghai : tu les saisis à la main. C'est délibéré — inventer ces valeurs serait pire que de les laisser vides, et chaque source demande un abonnement ou un scraping fragile.
- **Le volume réel du COMEX n'est pas accessible** depuis une capture de broker CFD. L'app le signale plutôt que de faire semblant.
- **Aucun backtest intégré.** Le journal mesure ton edge en avant, pas en arrière.
- **Pas de synchronisation multi-appareils** — le stockage est local au navigateur.
