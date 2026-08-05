# Gold Desk — analyse XAU/USD en 14 couches

Application web (PWA installable sur téléphone) qui analyse l'or couche par couche, puis **refuse ou valide** un trade selon des conditions éliminatoires calculées, pas selon une impression.

**Entièrement gratuit.** Hébergement sur l'offre gratuite Vercel, modèles à palier gratuit, et un mode manuel qui ne consomme aucune API du tout.

> **Ce que cet outil n'est pas.** Il ne prédit pas le marché et ne garantit aucun trade gagnant. Sa valeur vient de sa capacité à dire non : la plupart des configurations reçoivent la note **NO TRADE**. Un outil qui valide tout ne sert à rien. Cadre pédagogique — pas un conseil en investissement.

---

## Choisir son moteur

L'app est indépendante de tout fournisseur. Tu choisis dans l'interface, et tu peux changer à tout moment.

| Moteur | Coût | Ce qu'il vaut |
|---|---|---|
| **Google Gemini** | palier gratuit, sans carte bancaire | Le meilleur des options gratuites pour lire des graphiques. Schéma JSON natif. **Conseillé.** |
| **Groq** | palier gratuit | Très rapide. Lecture des chandeliers plus grossière — attends-toi à plus de couches UNKNOWN. |
| **OpenRouter** | modèles suffixés `:free` | Roue de secours quand un autre quota est épuisé. Disponibilité instable. |
| **Manuel** | 0 €, sans compte, sans quota | Tu notes toi-même les 14 couches, l'app fait le reste. Fonctionne hors ligne, pour toujours. |

**Ta clé reste dans ton navigateur.** Elle est stockée en local, transite par le serveur le temps d'un appel, et n'y est jamais enregistrée. Elle n'apparaît pas non plus dans l'export du journal.

### La partie qui ne dépend d'aucun modèle

Le modèle **juge** les 14 couches. L'application **décide** : le score, la confiance, les 11 conditions éliminatoires et le dimensionnement sont du code déterministe.

Conséquence pratique : passer d'un modèle haut de gamme à un modèle gratuit dégrade la lecture des graphiques, **pas la rigueur du verdict**. Un modèle qui renvoie « tout va bien, 100/100 » sur un trade au R:R de 1 obtient quand même NO TRADE — c'est couvert par les tests.

### Le mode manuel

C'est le seul mode réellement gratuit pour toujours, et probablement le plus formateur : il force à passer chaque couche au lieu de la survoler. Tu notes chaque couche *Soutient / Réserve / Contredit / Inconnu*, tu saisis ton trade, et l'app applique exactement les mêmes conditions éliminatoires, le même score et le même dimensionnement.

Laisse « Inconnu » ce que tu n'as pas vérifié. Cocher au hasard fait monter le score sans rien apporter — c'est le seul moyen de tromper cet outil, et ce serait te tromper toi.

---

## Ce qu'il fait

1. Tu déposes tes graphiques (W1, D1, H4, H1, M30, M5 — autant que tu veux).
2. Tu renseignes ce qu'un graphique ne peut pas montrer : DXY, taux réels, COT, GEX, prime de Shanghai, calendrier…
3. Le modèle analyse **les 14 couches, une par une, sans exception**.
4. L'application calcule le score, applique **11 conditions éliminatoires** et rend un verdict.
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
- Un setup existe réellement, avec des niveaux exploitables
- Entrée / stop / objectif cohérents avec la direction
- R:R au TP1 ≥ 1,5
- Stop compris entre 0,35 × et 3 × l'ATR journalier (**ATR obligatoire**)
- Position dimensionnable au risque demandé sans descendre sous le lot minimum
- Confiance globale ≥ 40 / 100
- Complétude des données ≥ 35 / 100

### Pourquoi deux chiffres et pas un seul

- **Score** : la qualité du setup.
- **Confiance** : ce qu'on en sait réellement.

Les confondre est malhonnête. Un score de 90 sur une confiance de 20 est refusé. Une couche `UNKNOWN` est ramenée à 50 quel que soit le score renvoyé : **une donnée absente n'est jamais un argument favorable**.

---

## Déploiement sur Vercel — gratuit

### 1. Importer le projet

Sur [vercel.com/new](https://vercel.com/new), importe ce dépôt.

**Réglage indispensable** — ce dossier vit dans le monorepo Expo, il faut donc pointer Vercel dessus :

| Champ | Valeur |
|---|---|
| **Root Directory** | `gold-analyzer` |
| Framework Preset | Next.js (détecté automatiquement) |
| Build Command | par défaut |

### 2. Aucune variable d'environnement n'est requise

Tu saisis ta clé directement dans l'app, à la première utilisation. C'est ce qui permet de rester sur l'offre gratuite Vercel : rien à configurer, rien à payer.

*Optionnel* — si tu préfères poser la clé une bonne fois côté serveur (usage strictement personnel : toute personne ayant l'URL consommerait ton quota), tu peux définir `GEMINI_API_KEY`, `GROQ_API_KEY` ou `OPENROUTER_API_KEY`.

### 3. Récupérer une clé gratuite

- **Gemini** → [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (sans carte bancaire)
- **Groq** → [console.groq.com/keys](https://console.groq.com/keys)
- **OpenRouter** → [openrouter.ai/keys](https://openrouter.ai/keys)

Ou n'en prends aucune et reste en mode manuel.

### 4. Installer sur le téléphone

- **iPhone** : ouvrir l'URL dans Safari → Partager → « Sur l'écran d'accueil »
- **Android** : Chrome → menu → « Installer l'application »

---

## Limites des paliers gratuits

Les quotas sont limités **par minute et par jour**, et les fournisseurs les modifient sans préavis. En cas de dépassement, l'app affiche l'erreur en clair et propose de changer de fournisseur ou de basculer en manuel. Rien n'est perdu.

**Point de confidentialité** : Google indique pouvoir utiliser les contenus envoyés via le palier gratuit pour améliorer ses produits. Ce sont des captures de graphiques, mais sache-le. Le mode manuel n'envoie rien nulle part.

Une analyse prend 20 s à 2 min selon le modèle. La route déclare `maxDuration = 300` et diffuse la réponse en flux continu (NDJSON) pour maintenir la connexion et afficher la progression.

---

## Développement local

```bash
cd gold-analyzer
npm install
npm run dev
```

Sur http://localhost:3000. Aucune clé nécessaire pour démarrer — le mode manuel fonctionne immédiatement.

```bash
npm run build       # build de production
npm run typecheck   # vérification TypeScript
node scripts/make-icons.mjs   # régénère les icônes PWA
```

Aucune dépendance à un SDK propriétaire : les appels partent en `fetch` brut vers l'API HTTP du fournisseur choisi. Ajouter un fournisseur revient à ajouter une entrée dans `lib/providers.ts`.

---

## Données et vie privée

Trades, analyses, contexte et clé API sont stockés dans le **localStorage du navigateur**. Le serveur ne conserve rien.

Conséquence : vider le cache du navigateur efface tout. Le journal a un bouton **Exporter** / **Importer** — sers-t'en. La clé API est volontairement exclue de l'export.

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
│   ├── page.tsx                  écran d'analyse (modes API et manuel)
│   ├── journal/page.tsx          journal + statistiques
│   └── api/analyze/route.ts      relais vers le fournisseur choisi, flux NDJSON
├── lib/
│   ├── providers.ts              Gemini / Groq / OpenRouter, erreurs, extraction JSON
│   ├── assemble.ts               normalisation défensive + verdict
│   ├── modules.ts                les 14 couches, poids, couches éliminatoires
│   ├── prompt.ts                 prompt système et contexte
│   ├── schema.ts                 schéma JSON de la sortie structurée
│   ├── scoring.ts                score, confiance, conditions éliminatoires, note
│   ├── sizing.ts                 dimensionnement XAUUSD
│   ├── stats.ts                  espérance, MAE/MFE, attribution, Monte-Carlo, Kelly
│   ├── image.ts                  redimensionnement navigateur
│   └── storage.ts                persistance localStorage
└── components/                   ProviderSetup, Dropzone, ContextForm, ManualForm, Report, Nav
```

**Séparation volontaire** : le modèle juge chaque couche ; l'application calcule le score, applique les conditions éliminatoires et rend le verdict.

### Robustesse face aux modèles gratuits

Les petits modèles omettent des champs, renvoient des nombres en chaînes (`"3 345,20"`, `"$3,325.00"`), inventent des identifiants de couche ou encadrent le JSON de Markdown. `lib/assemble.ts` répare ce qui est réparable et marque `UNKNOWN` le reste. Un plan de trade sans niveaux exploitables est neutralisé, quoi qu'annonce le modèle.

### Garde-fous dans le prompt

- Interdiction d'inventer un prix, un ATR ou un volume non lisible sur les graphiques fournis
- Le volume d'un graphique CFD est du **tick volume** — la couche order flow est plafonnée à une confiance faible sur cette seule base
- Le vocabulaire SMC est traduit en mécanique : FVG → zone de faible volume, order block → point d'initiation, sweep → cascade de stops. Ce sont des outils de **timing d'entrée**, jamais une thèse directionnelle
- Mode d'entrée par défaut sur l'or : **confirmation** (balayage → changement de caractère), jamais un ordre limite nu
- Aucune probabilité de réussite chiffrée, aucun langage de certitude
- `hasTrade: false` est la réponse attendue par défaut

---

## Limites connues

- **Un modèle gratuit lit les graphiques moins bien qu'un modèle haut de gamme.** C'est le compromis assumé. Le moteur de décision, lui, est identique.
- **Aucune donnée de marché n'est récupérée automatiquement.** DXY, COT, GEX, prime de Shanghai : tu les saisis à la main. C'est délibéré — inventer ces valeurs serait pire que de les laisser vides, et chaque source demande un abonnement ou un scraping fragile.
- **Le volume réel du COMEX n'est pas accessible** depuis une capture de broker CFD. L'app le signale plutôt que de faire semblant.
- **Aucun backtest intégré.** Le journal mesure ton edge en avant, pas en arrière.
- **Pas de synchronisation multi-appareils** — le stockage est local au navigateur.
