# gold-sweep — XAUUSD « NY Open Liquidity Sweep »

Outil d'analyse de l'or : **moteur de stratégie unique** partagé entre le
backtest historique et l'exécution temps réel sur **cTrader Open API**.

Zéro dépendance npm. Node ≥ 18. Le codec protobuf, le client TLS et le moteur
de backtest sont écrits à la main : rien à installer, rien à mettre à jour.

```bash
node src/cli/backtest.js --csv data/xauusd-m5.csv --html out/rapport.html
node src/cli/optimize.js walkforward --csv data/xauusd-m5.csv
node src/cli/live.js watch --symbol XAUUSD          # mode alerte
node --test test/*.test.js                          # 38 tests

node web/build.mjs && npx serve web/dist            # tableau de bord web
```

Un **tableau de bord web** déployable sur Vercel accompagne le CLI : il exécute
le même moteur *dans le navigateur*, sans téléverser votre CSV.
Voir [DEPLOIEMENT.md](DEPLOIEMENT.md). Le suivi cTrader temps réel reste en CLI
local — il exige une socket TLS persistante, qu'un hébergement serverless ne
peut pas tenir.

---

## ⚠️ Verdict de validation — à lire avant toute utilisation

Backtest sur **375 985 barres M5, 2021-05-19 → 2026-09-07**, coûts inclus
(spread 0,22 $ / 0,45 $ en fenêtre news, slippage 0,06 $ sur stop) et
hypothèse intra-barre **pessimiste systématique**.

### La stratégie est légèrement positive mais **statistiquement non prouvée**

| Préréglage | Trades | /an | Réussite | Total R | PF | maxDD | **t de Student** |
|---|---|---|---|---|---|---|---|
| `stable` (défaut) | 22 | 4,7 | 45,5 % | +6,9 R | 1,57 | 4,1 R | 0,94 |
| `literal` | 19 | 4,3 | 47,4 % | +4,3 R | 1,42 | 3,4 R | 0,71 |
| `frequent` | 50 | 10,1 | 38,0 % | +16,6 R | 1,53 | 8,1 R | **1,19** |
| `ote` | 40 | 8,8 | 40,0 % | +11,2 R | 1,43 | 6,1 R | 0,93 |
| `selective` | 15 | 3,2 | 53,3 % | +7,4 R | 2,02 | 3,0 R | **1,17** |

**Aucun préréglage n'atteint |t| > 2**, le seuil usuel de significativité à
5 % ; le meilleur (`frequent`) plafonne à 1,19. Sur le préréglage par défaut :
22 trades, écart-type 1,56 R, donc une erreur-type de l'espérance de 0,33 R —
un résultat de +0,31 R/trade est indiscernable du hasard.

Le problème n'est pas le signe, c'est la **fréquence** : 3 à 10 trades par an
ne permettent pas de conclure, même sur 5 ans d'historique. Il faudrait environ
**100 trades** au même taux pour que |t| dépasse 2, soit une dizaine d'années
au rythme du préréglage par défaut.

### L'optimisation en in-sample ne transfère pas

Grille de 5 000 configurations tirées sur 2021-05 → 2024-12 (2 427 retenues
avec au moins 25 trades), validées sur 2025-01 → 2026-09 — période jamais vue
pendant la recherche :

| | n | Espérance OOS | Total R OOS | % rentables OOS |
|---|---|---|---|---|
| Top 60 in-sample | 60 | −0,245 R | −7,1 R | 27 % |
| **Témoin aléatoire** | 60 | **−0,195 R** | **−7,0 R** | **32 %** |

**Le témoin aléatoire fait marginalement mieux que le top 60.** Corrélation de
rang (Spearman) entre score in-sample et espérance out-of-sample : **0,126**.
La meilleure configuration in-sample (26 trades, +26,5 R, PF 3,40) rend +2,0 R
et PF 1,16 hors échantillon. Seules 10 des 25 meilleures sont rentables OOS —
soit un tirage à pile ou face.

Reproductible :
`node src/cli/optimize.js grid --csv data/xauusd-m5.csv --n 5000`
(sortie complète dans `docs/04-grille-surajustement.txt`)

C'est pourquoi les valeurs par défaut **ne sont pas** la configuration
gagnante de la grille : elles viennent des constats structurels reproduits sur
toutes les coupes, et du candidat le plus stable d'année en année.

Détail annuel du préréglage par défaut — et sa limite :

| Année | Trades | Total R |
|---|---|---|
| 2021 (à partir de mai) | 1 | +2,2 |
| 2022 | 5 | −2,4 |
| 2023 | 2 | +3,7 |
| 2024 | 1 | +1,6 |
| 2025 | 9 | +1,0 |
| 2026 (jusqu'en sept.) | 4 | +0,7 |

Cinq années sur six sont positives, mais avec **1 à 2 trades** en 2021, 2023 et
2024 : « année positive » ne signifie rien à ce volume. C'est un critère de
sélection moins mauvais que le rendement brut, pas une preuve.

### Le split inverse ne sauve pas la stratégie

Optimiser sur 2025-2026 puis tester sur 2021-2024 donne une espérance moyenne
de **+0,115 R** (28 configurations rentables sur 40) — mais une corrélation de
rang de **−0,507** : les meilleures configurations récentes sont les *moins*
bonnes sur l'historique ancien. Aucun transfert dans un sens comme dans
l'autre.

### Walk-forward ancré — le seul chiffre réaliste

Réoptimisation glissante sur 6 fenêtres, résultats hors échantillon concaténés :
**+3,8 R sur 29 trades**, espérance **+0,132 R/trade**, positif sur 4 fenêtres
sur 6. Une variante de l'échantillonnage donne +4,3 R sur 30 trades
(`docs/02-robustesse.txt`) : l'ordre de grandeur est stable, mais avec un
écart-type de ~1,6 R l'erreur-type vaut 0,30 R — le résultat reste dans le
bruit.

Reproductible :
`node src/cli/optimize.js walkforward --csv data/xauusd-m5.csv --n 1500`

### Conclusion honnête

Ce modèle n'est **ni démontré ni réfuté**. La lecture des flux de liquidité est
cohérente et le détail des mesures ci-dessous la corrobore ponctuellement, mais
l'historique disponible ne suffit pas à établir un avantage. **À utiliser en
mode alerte ou sur compte démo** jusqu'à ce que vous ayez accumulé assez de
trades réels pour trancher vous-même.

---

### Preuves brutes

Les sorties non retouchées des mesures citées ici sont dans `docs/` :

| Fichier | Contenu |
|---|---|
| `01-sensibilite.txt` | 149 évaluations, un paramètre à la fois, classées par impact |
| `02-robustesse.txt` | split inverse, stabilité annuelle, walk-forward |
| `03-candidats.txt` | 12 configurations candidates avec t de Student |
| `04-grille-surajustement.txt` | grille de 5 000 configs + témoin + Spearman |

---

## Ce que les données ont réellement montré

### 1. L'or a changé de régime : tout paramètre en USD absolu dérive

| Année | Prix médian | ATR(14) M5 | Range de Londres | ATR en % du prix |
|---|---|---|---|---|
| 2021 | 1 801 | 0,96 $ | 8,25 $ | 0,053 % |
| 2023 | 1 947 | 1,02 $ | 8,22 $ | 0,052 % |
| 2025 | 3 353 | 2,71 $ | 19,15 $ | 0,081 % |
| 2026 | 4 589 | **5,29 $** | **35,67 $** | 0,115 % |

L'ATR M5 a été **multiplié par 5,5**. Le « SL de 15 à 30 pips » de la
description valait 1,5 à 3 ATR en 2021 mais seulement **0,3 à 0,6 ATR en
2026** : il serait systématiquement balayé.

→ **Toutes les distances sont donc exprimées en multiples d'ATR** (`atr`),
pas en pips. Le même réglage vaut 2,9 pips en 2021 et 16 pips en 2026.
Les modes `pips`, `usd`, `pctPrice` et `rangePct` restent disponibles.

### 2. Les stops serrés sont la première cause de perte

| `stop.buffer` | Total R |
|---|---|
| 0,15 ATR | **−9,4 R** |
| 0,25 ATR | −4,5 R |
| 0,40 ATR | **+10,5 R** |

Écart de 20 R sur un seul paramètre. Défaut retenu : **0,30 ATR** (milieu de
la zone stable, pas le maximum mesuré — qui serait du sur-ajustement).

### 3. Un balayage trop profond n'est pas un piège

| `sweep.maxPenetration` | Total R |
|---|---|
| 1,5 ATR | +3,6 R |
| 3,0 ATR | ~0 R |
| illimité | **−12,0 R** |

Distribution mesurée de la pénétration au moment du MSS : médiane 1,67 ATR,
p75 2,85 ATR, p90 4,09 ATR. Défaut : **3,0 ATR**.

### 4. Le R:R annoncé n'est pas atteignable

La stratégie promet « 1:3 à 1:5 minimum ». Mesuré avec TP au niveau opposé de
Londres et SL au-dessus du piège :

| `entry.fvgLevel` | R:R médian | % R:R ≥ 3 | Remplissage |
|---|---|---|---|
| 0,00 (bord proche) | 1,74 | 18 % | 67 % |
| 0,50 (milieu) | 2,04 | 25 % | 52 % |
| 0,75 | 2,26 | 31 % | 46 % |
| 1,00 (bord lointain) | 2,52 | 38 % | 42 % |

**R:R médian réel : ~2,0.** Exiger 3 supprime 75 % des setups. Défaut :
`minRR = 2.0`, `fvgLevel = 0.75` (meilleur compromis mesuré entre prix et
probabilité de remplissage).

### 5. Toute gestion « protectrice » détruit l'avantage

| Gestion | Réussite | Total R |
|---|---|---|
| Aucune (TP ou SL) | 31,0 % | **+9,4 R** |
| Partiel 50 % @ 2R | 34,5 % | +4,5 R |
| Partiel sur liquidité interne | 36,2 % | +2,4 R |
| **Breakeven @ 1R** | **48,3 %** | **−8,7 R** |
| BE @ 1R + partiel | 48,3 % | −10,7 R |
| Trailing ATR | 17,6 % | −15,4 R |

Le breakeven fait grimper le taux de réussite de 31 à 48 % et **détruit
quand même 18 R**. Raison : l'avantage vit entièrement dans les rares runs
complets jusqu'au bas de Londres (gagnant moyen 1,84 R, meilleur 3,71 R).
L'or retrace profondément avant de partir — le BE transforme les futurs
gagnants en nuls. Défauts : **aucune gestion dynamique**.

### 6. Le côté vente domine

| Sens | Trades | Réussite | Total R |
|---|---|---|---|
| Vente (balayage du haut) | 16 | 50,0 % | **+8,4 R** |
| Achat (balayage du bas) | 6 | 33,3 % | −1,5 R |

Cohérent avec la logique décrite. Le côté achat reste actif par défaut
(`sweep.side: both`) parce que le désactiver ne laisse que 16 trades — encore
moins concluant. `highOnly` est disponible.

### 7. Vos horaires GMT fixes sont les bons

`sessions.nyAnchor: 'gmt'` (heures figées) bat `'local'` (recalage sur l'heure
de New York) : +9,4 R contre −13,5 R. Les deux référentiels sont implémentés
avec les règles DST US et UK codées en dur, mais le GMT fixe gagne.

### 8. Les jours NFP ne sont pas tous explosifs

Amplitude de la bougie de 13:30 GMT rapportée à l'ATR :

| | Médiane | p90 |
|---|---|---|
| Tous les jours | 1,52 | 2,88 |
| Jours NFP | 1,49 | **6,38** |

Même médiane, queue bien plus épaisse. Bloquer tous les NFP écarte beaucoup de
jours inoffensifs. Le détecteur `volatilitySpike` attrape la publication
réellement destructrice quel que soit son nom, **sans aucun calendrier** —
en mesurant la bougie de 13:30 après sa clôture (donc sans regard vers le
futur, puisque `signalNotBefore` est à 13:35). Seuil 3 ATR → 8,9 % des jours
écartés.

### 9. Empiler toutes les confluences vide le filtre

Le préréglage `checklist` (premium/discount + Silver Bullet + blackout +
inducement) ne laisse que **5 trades en 5 ans et 4 mois** (−0,4 R). Chaque
condition retire des setups valides et leur intersection est quasiment vide.
À garder comme grille de lecture, pas comme réglage de production.

---

## Ce qui est implémenté

Les quatre phases décrites, plus toutes vos additions :

| Concept | Paramètre | Backtesté |
|---|---|---|
| Range de Londres 07:00–12:00 GMT | `sessions.london*` | ✅ |
| Balayage 13:00–14:30 GMT | `sessions.sweep*`, `sweep.*` | ✅ |
| MSS + déplacement | `mss.*`, `mss.displacement.*` | ✅ |
| Fair Value Gap | `fvg.*`, `entry.fvgLevel` | ✅ |
| Order Block | `entry.model: orderBlock`, `entry.obZone` | ✅ |
| OTE (Fibonacci) | `entry.model: ote`, `entry.oteLevel` | ✅ |
| SL au sommet du piège | `stop.anchor`, `stop.buffer` | ✅ |
| TP au niveau opposé de Londres | `target.anchor` | ✅ |
| **Premium / Discount** | `filters.premiumDiscount` | ✅ |
| **Silver Bullet 14:00–15:00** | `filters.silverBullet` | ✅ |
| **Pas de signal avant 13:35** | `sessions.signalNotBefore` | ✅ (dans les défauts) |
| **Inducement (faux balayage)** | `sweep.requireInducement` | ✅ |
| **Blackout news destructrices** | `filters.newsBlackout` | ✅ |
| **Breakeven / partiels** | `manage.breakEvenAtRR`, `manage.partial` | ✅ |
| **Partiel sur liquidité interne** | `manage.partial.anchor` | ✅ |
| **Corrélation inverse DXY** | `refs.dxy.*` | ❌ **données manquantes** |
| **Filtre macro US10Y** | `refs.us10y.*` | ❌ **données manquantes** |

**132 paramètres**, tous documentés dans `src/core/config.js`, tous validés au
démarrage (une valeur hors bornes lève une erreur explicite, elle ne dégrade
pas silencieusement le résultat).

### Les deux filtres que je n'ai pas pu valider

Le code du DXY et de l'US10Y est **écrit, testé et branché en live** — mais je
n'avais que le CSV XAUUSD. Pour les backtester, exportez les séries depuis
votre propre compte cTrader :

```bash
node src/cli/live.js history --symbol USDX  --days 1900 --out data/dxy-m5.csv
node src/cli/live.js history --symbol US10Y --days 1900 --out data/us10y-m5.csv

node src/cli/backtest.js --csv data/xauusd-m5.csv \
  --dxy data/dxy-m5.csv --us10y data/us10y-m5.csv \
  --set refs.dxy.mode=require --set refs.us10y.mode=alignTrend
```

Le nom exact du symbole dépend de votre broker — `gs-live symbols --filter USD`
vous le donnera. Si l'une des séries manque, le filtre se signale
`available: false` et `refs.<nom>.onMissing` décide (`pass` par défaut : il ne
bloque rien plutôt que de bloquer sur une donnée absente).

---

## Connexion cTrader

1. Créez une application sur <https://openapi.ctrader.com/> → `clientId` + `clientSecret`
2. Obtenez un `accessToken` OAuth2 pour votre compte
3. `cp .env.exemple .env`, remplissez, puis `set -a && . ./.env && set +a`

```bash
node src/cli/live.js accounts                      # comptes accessibles
node src/cli/live.js symbols --filter XAU           # nom exact du symbole
node src/cli/live.js discover --symbol XAUUSD       # ⚠️ à faire avant d'exécuter
node src/cli/live.js plan --symbol XAUUSD           # plan du jour, puis quitte
node src/cli/live.js watch --symbol XAUUSD          # surveillance (alerte)
node src/cli/live.js watch --symbol XAUUSD --execute --env demo
```

### ⚠️ `discover` avant toute exécution réelle

`instrument.apiVolumePerLot` (défaut **10 000**) détermine la taille de vos
positions. Les numéros de champ de `ProtoOASymbol` ne sont pas garantis
identiques d'un broker à l'autre, et je refuse de deviner une disposition
binaire dans du code qui déplace de l'argent. `discover` affiche les champs
**réellement envoyés** par votre broker avec leur numéro et leur type —
vérifiez `lotSize`, `minVolume` et `stepVolume` puis ajustez.

Le décodeur protobuf refuse de lire un champ dont le type de fil ne correspond
pas au schéma : un numéro erroné donne une valeur absente signalée dans
`__wireMismatch`, jamais une valeur fausse.

### Mode alerte vs exécution

Sans `--execute`, rien n'est envoyé au broker : le setup est affiché avec la
checklist en 5 points, le dimensionnement et le R:R. Avec `--execute`, l'ordre
limite est transmis **avec son SL, son TP et son expiration attachés côté
cTrader** : même si ce processus s'arrête, la protection reste en place.

---

## Backtest

```bash
node src/cli/backtest.js --csv data/xauusd-m5.csv                  # défaut
node src/cli/backtest.js --csv d.csv --preset frequent --trades 0  # + trades
node src/cli/backtest.js --csv d.csv --set stop.buffer=0.4 --set target.minRR=3
node src/cli/backtest.js --csv d.csv --from 2025-01-01 --html out/r.html
node src/cli/backtest.js --csv d.csv --calendar data/calendrier-exemple.csv \
  --set filters.newsBlackout=all
```

Format CSV attendu : `time,open,high,low,close,volume` avec `time` en ISO 8601
UTC. Les lignes incohérentes (OHLC impossible, prix ≤ 0) sont rejetées et
comptées ; un CSV non trié lève une erreur plutôt que de produire un résultat
faux.

Le rapport affiche l'**entonnoir de sélection** complet : combien de jours sont
armés, combien sont balayés, combien produisent un MSS, combien de setups
survivent à chaque filtre, et **pourquoi les autres ont été rejetés** (36 motifs
distincts). C'est l'outil de réglage : si `fvgMissing` domine, desserrez
`fvg.minSize` ; si `rrTooLow` domine, votre `minRR` est trop ambitieux.

## Optimisation

```bash
node src/cli/optimize.js sensitivity --csv d.csv    # quels réglages comptent
node src/cli/optimize.js grid        --csv d.csv --n 5000
node src/cli/optimize.js walkforward --csv d.csv --n 1500
```

Le mode `grid` fournit systématiquement le **groupe témoin** et la
**corrélation de rang** : si les meilleures configurations in-sample ne battent
pas un tirage au hasard hors échantillon, l'optimisation n'a trouvé que du
bruit — et le rapport vous le dit.

Le score maximisé n'est pas le rendement mais l'espérance divisée par son
erreur-type, pénalisée par le drawdown.

---

## Hypothèses d'exécution

**Modèle de prix.** Le CSV est traité comme la série **mid**, d'où
`ask = mid + spread/2` et `bid = mid − spread/2`. Cela pénalise correctement
les trois événements : remplissage de la limite plus difficile, déclenchement
du stop plus facile, take profit plus difficile. Ne jamais évaluer les niveaux
sur le mid brut.

**Ordre intra-barre.** Une barre M5 ne dit pas si le haut ou le bas a été
touché en premier. `execution.intrabar` :

- `conservative` (**défaut**) — toujours le pire cas. Le seul honnête.
- `ohlcPath` — chemin reconstruit O→H→L→C / O→L→H→C.
- `optimistic` — meilleur cas. Sert uniquement à borner l'incertitude
  (préréglage `auditOptimistic`), jamais à décider.

**Causalité.** Le moteur ne lit jamais une barre postérieure à l'instant
courant. Les swings fractals ne sont utilisés qu'après leur barre de
confirmation (`j + lookback ≤ i`). Le test `pas de regard vers le futur`
vérifie qu'un backtest sur historique tronqué produit **exactement** les mêmes
trades que le préfixe du backtest complet — la seule preuve qui compte.

---

## Tableau de bord web

`web/` contient une page statique qui rejoue le backtest **côté navigateur**,
dans un Web Worker :

- le CSV est lu localement — **aucun téléversement**, aucune limite de taille
  (376 k barres analysées en ~400 ms, backtest en ~100 ms) ;
- les 132 paramètres sont réglables : champs guidés pour les plus influents,
  surcharge JSON libre pour le reste ;
- courbe des R cumulés, résultat par année, entonnoir de sélection, motifs de
  rejet, liste des trades — tous survolables, tous doublés d'une vue tableau ;
- export du rapport HTML (même module que le CLI), du résultat JSON et de la
  configuration JSON rechargeable avec `--config` ;
- les preuves de validation sont embarquées : la page est utile sans CSV.

Le moteur n'est **pas dupliqué** : `web/build.mjs` copie les modules depuis
`src/` et **échoue si l'un d'eux importe `node:*`**. Les accès disque sont
isolés dans `src/core/load.js`, jamais copié côté web.

Vérifié par un test de bout en bout sous Chromium (mode clair et sombre) : le
navigateur produit **exactement les mêmes chiffres que le CLI** (22 trades,
+6,9 R, PF 1,57, t = 0,94), aucune erreur console, aucun débordement horizontal
en 1200 px comme en 390 px.

## Architecture

```
src/core/
  config.js      132 paramètres documentés + validation + distances ATR
  presets.js     6 préréglages, chiffres vérifiés par les tests
  time.js        sessions GMT, règles DST US et UK codées en dur
  csv.js         chargement rapide (376k barres en 0,5 s)
  indicators.js  ATR Wilder, swings fractals, FVG, Order Block
  strategy.js    ⭐ machine à états — PARTAGÉE backtest ↔ live
  calendar.js    NFP déterministe + détecteur de choc + calendrier CSV
  refdata.js     séries corrélées (DXY, US10Y) alignées par horodatage
src/backtest/
  engine.js      simulation barre par barre, modèle bid/ask, intra-barre
  metrics.js     PF, espérance, t de Student, MAE/MFE, ventilations
  optimize.js    pool de workers, grille, sensibilité, walk-forward
  report.js      console, JSON, HTML autonome
src/live/
  protobuf.js    codec wire format écrit à la main (+ decodeUnknown)
  ctrader/       schémas de messages + client TLS (trames, heartbeat,
                 reconnexion à backoff, rafraîchissement de jeton)
  feed.js        agrégation M5, ATR incrémental (identique au batch)
  monitor.js     exécution live, dimensionnement, checklist 5 points
src/cli/         backtest.js, optimize.js, live.js
src/backtest/render.js   rendu HTML pur, partagé CLI <-> web
src/core/load.js         SEUL module du moteur à dépendre de Node
web/
  build.mjs      construit web/dist (copie du moteur + garde-fou node:*)
  public/        index.html, app.js, charts.js, worker.js
test/unit.test.js  38 tests
```

Le même `SweepStrategy` tourne au backtest et en live. L'ATR incrémental du
flux live est **bit-identique** à l'ATR batch (vérifié sur 20 000 barres,
écart max 0,00e+00). Ce qui est validé sur l'historique est littéralement ce
qui tourne sur le compte.

---

## Exemple de dimensionnement

Compte **10 000 $**, risque **1 %**, or à 4 405 $, SL à 6,80 $ (68 pips) :

```
lots     = 100 $ / (6,80 $ × 100 oz)  = 0,147  →  0,14 (pas de 0,01)
risque   = 6,80 × 0,14 × 100          = 95,20 $   (0,95 % du capital)
si TP    = 25,50 × 0,14 × 100         = 357,00 $
```

Sur un compte de **1 000 $**, le même setup donne 0,01 lot (le minimum), soit
6,80 $ de risque — 0,68 %. En dessous, `sizeFor` renvoie un volume nul avec un
motif explicite et **aucun ordre n'est placé** plutôt qu'un ordre mal calibré.

---

## Limites connues

- **Échantillon insuffisant.** 4 à 9 trades par an. Aucun résultat n'est
  statistiquement significatif sur 5 ans.
- **DXY et US10Y non validés** faute de données (code prêt, voir plus haut).
- **Calendrier économique incomplet.** Le NFP est déterministe, le CPI et le
  FOMC doivent être fournis en CSV. Le détecteur de choc par la volatilité
  compense sans donnée externe.
- **Pas de reprise d'état.** Un redémarrage rejoue l'historique du jour pour
  reconstituer le plan, mais les setups passés ne sont pas ré-exécutés. Les
  ordres déjà transmis vivent côté cTrader avec leur SL/TP.
- **Un seul symbole, une seule position à la fois.**
- **`apiVolumePerLot` à vérifier** avec `discover` avant toute exécution réelle.

## Licence et avertissement

Outil d'analyse et de recherche. Le trading de l'or avec effet de levier peut
faire perdre la totalité du capital. Les résultats de backtest ne préjugent pas
des résultats futurs — et ce backtest en particulier **ne démontre pas**
d'avantage statistique. Commencez en mode alerte, puis sur compte démo.
