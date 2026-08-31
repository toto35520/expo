# goldscalp

Outil de scalping **XAU/USD (or)** en ligne de commande.

Il lit le prix de l'or sur **Bybit**, le **recalibre vers le référentiel MT5 de
ton broker**, croise une analyse **technique multi-timeframe (M1 / M5 / M15)**
avec une analyse **fondamentale intraday** et la **microstructure du carnet**,
puis produit un plan de trade complet : entrée, **stop loss**, **TP1**, **TP2**,
taille de position et règles de gestion.

**Aucune dépendance obligatoire.** Le cœur tourne avec Python 3.9+ nu :
ni numpy, ni pandas, ni requests. Le paquet `MetaTrader5` est un extra
facultatif (Windows) qui améliore la précision quand il est présent.

---

## Sommaire

1. [Pourquoi recalibrer Bybit sur MT5](#1-pourquoi-recalibrer-bybit-sur-mt5)
2. [Installation](#2-installation)
3. [Première étape obligatoire : la calibration](#3-première-étape-obligatoire--la-calibration)
4. [Commandes](#4-commandes)
5. [Lire le rapport](#5-lire-le-rapport)
6. [Comment le moteur décide](#6-comment-le-moteur-décide)
7. [Stop loss, TP1, TP2 et taille de position](#7-stop-loss-tp1-tp2-et-taille-de-position)
8. [Le mode TURBO](#8-le-mode-turbo)
9. [Backtest : ce qu'il mesure vraiment](#9-backtest--ce-quil-mesure-vraiment)
10. [Configuration](#10-configuration)
11. [Tableau de bord web et déploiement Vercel](#11-tableau-de-bord-web-et-déploiement-vercel)
12. [Limites connues](#12-limites-connues)

---

## 1. Pourquoi recalibrer Bybit sur MT5

Bybit cote l'or **tokenisé** (XAUT, Tether Gold). Ton broker MT5 cote XAUUSD.
Ce ne sont pas les mêmes nombres. Trois écarts se superposent :

| Écart | Origine | Ordre de grandeur |
|---|---|---|
| Prime XAUT | l'or tokenisé se négocie avec une prime ou une décote sur le spot | quelques dollars, dérive lente |
| Peg USDT/USD | l'USDT ne vaut pas exactement 1,00 $ | ± 0,1 % |
| Markup broker | marge et spread propres à ton courtier | 0,10 à 0,60 $ |

Poser un TP à 2 412,50 lu sur Bybit alors que ton broker cote 2 419,85 revient à
**placer un ordre 7 dollars à côté**. C'est la première cause d'échec de ce type
de montage.

**Intérêt de Bybit malgré cet écart :** ce marché cote **24 h / 24, 7 j / 7**, y
compris le week-end quand le forex est fermé, et il expose un **carnet d'ordres,
un flux d'exécutions, le funding et l'open interest** — des données que MT5 ne
donne pas.

### Deux sources de prix, dans cet ordre

| Source | Quand | Ce qu'elle apporte | Ce qui manque |
|---|---|---|---|
| **MT5** | paquet `MetaTrader5` installé, terminal ouvert | le prix exact de ton broker, aucun recalage nécessaire | Windows uniquement |
| **Bybit** `XAUTUSDT` | par défaut | 24/7, carnet, flux, funding, open interest | prime XAUT à recalibrer ; **filtré par pays** |
| **Yahoo** `XAUUSD=X` | repli automatique | **or spot** — l'écart au broker se réduit à son markup | pas de volume, pas de microstructure, fermé le week-end |

Le repli Yahoo n'est pas cosmétique : Bybit filtre par pays **au niveau de son
CDN**. Depuis un serveur américain, l'API renvoie
`403 — The Amazon CloudFront distribution is configured to block access from
your country`. Sans seconde source, l'outil serait inutilisable là où il est
déployé plutôt que là où tu te trouves.

Quand le repli s'active, l'outil le dit : la source affichée passe à `YAHOO`, et
l'absence de volume est signalée explicitement — les indicateurs de participation
se rabattent alors sur une pondération temporelle.

### Le modèle appliqué

```
prix_MT5 = alpha + beta × prix_Bybit
```

- **alpha** absorbe la prime XAUT et le markup broker ;
- **beta** absorbe la dérive proportionnelle (peg USDT, markup en pourcentage).

**Garde-fou important :** sans plusieurs ancrages pris à des **prix écartés**
(au moins 3, séparés de plus de 8 $), la pente `beta` n'est **pas
identifiable** — la régression n'ajusterait que du bruit. L'outil la force
alors à 1,0 et applique un décalage constant. Il te le dit explicitement plutôt
que d'inventer une pente.

Une pente hors de l'intervalle [0,97 ; 1,03] est rejetée d'office : deux
cotations du même métal ne peuvent pas diverger à ce point.

---

## 2. Installation

```bash
git clone <ce-dépôt>
cd gold-scalper

# Utilisation directe, sans installer quoi que ce soit
python3 -m goldscalp --help

# Ou installation en tant que commande
pip install -e .
goldscalp --help
```

**Extra facultatif (Windows uniquement)** — active la lecture directe des
bougies du broker, l'ancrage automatique et la taille de contrat réelle :

```bash
pip install MetaTrader5
```

Sans lui, tout fonctionne : l'outil travaille sur les prix Bybit recalibrés.

### Vérifier que le moteur est sain

```bash
python3 -m goldscalp selftest
```

Huit contrôles, dont deux essentiels : **causalité** (aucun indicateur ne lit le
futur) et **honnêteté du backtest** (aucun edge artificiel sur du bruit pur).

### Essayer sans réseau ni broker

```bash
python3 -m goldscalp analyse --demo --seed 11
```

Le mode `--demo` utilise un simulateur de marché interne. Toute sortie produite
dans ce mode est marquée en évidence : **elle ne doit jamais être tradée.**

---

## 3. Première étape obligatoire : la calibration

Sans calibration, les niveaux affichés sont des **prix Bybit bruts**, décalés de
plusieurs dollars par rapport à ton broker. L'outil refuse de le passer sous
silence : il affiche `CRITIQUE` tant que rien n'est calé.

### Méthode manuelle (fonctionne partout)

1. Ouvre MT5 sur XAUUSD, note le **bid** et l'**ask**.
2. Note le prix Bybit **au même instant** (c'est le point critique : quelques
   secondes d'écart en session active suffisent à fausser l'ancrage).
3. Enregistre :

```bash
python3 -m goldscalp calibrate --bybit 2405.10 --bid 2412.30 --ask 2412.60
```

### Méthode automatique (Windows, terminal MT5 ouvert)

```bash
python3 -m goldscalp calibrate --auto
```

L'outil lit le prix Bybit et le tick MT5 lui-même, ce qui garantit la
simultanéité.

### Consulter l'état

```bash
python3 -m goldscalp calibrate --show
```

```
CALIBRATION
  MT5 = Bybit + 7.35 | spread 0.30$ | 1 ancrage(s) | qualite 60/100
  etat : OK
```

**Recalibre toutes les 2 à 4 heures.** La prime XAUT dérive. Au-delà de 45 min
l'outil passe en `attention`, au-delà de 6 h en `critique`.

Pour identifier la pente en plus du décalage, ajoute des ancrages à des moments
où le prix a bougé de plus de 8 $ : l'outil bascule automatiquement sur une
**régression robuste (Theil–Sen)**, insensible à un relevé bâclé.

---

## 4. Commandes

| Commande | Rôle |
|---|---|
| `analyse` | analyse complète et plan de trade |
| `watch` | surveillance continue, une ligne par évaluation |
| `calibrate` | gère le calage Bybit → MT5 |
| `backtest` | backtest walk-forward du cœur technique |
| `levels` | niveaux clés en prix MT5 |
| `selftest` | vérifie l'intégrité du moteur |
| `config` | affiche ou enregistre la configuration |

### Exemples

```bash
# Analyse avec ton capital et ton risque
python3 -m goldscalp analyse --balance 5000 --risk 0.5

# Détail de chaque composante du score
python3 -m goldscalp analyse -v

# Espérance calculée sur des taux MESURÉS plutôt qu'estimés
python3 -m goldscalp analyse --with-backtest

# Sortie JSON, pour scripter par-dessus
python3 -m goldscalp analyse --json

# Surveillance : une ligne toutes les 30 s, rapport complet à chaque signal
python3 -m goldscalp watch --interval 30 --full-on-signal

# Seulement quand il y a quelque chose à faire
python3 -m goldscalp watch --only-signals

# Niveaux clés en prix broker
python3 -m goldscalp levels

# Backtest sur 6 000 bougies M1
python3 -m goldscalp backtest --bars 6000
```

### Options utiles

| Option | Effet |
|---|---|
| `--balance` / `--risk` | capital et pourcentage risqué par trade |
| `--min-confidence` | seuil d'émission du signal (défaut 55) |
| `--spread` | force le spread MT5 en dollars |
| `--timeframes M1,M5,M15` | change les unités de temps analysées |
| `--allow-counter-trend` | autorise les signaux contre une tendance M15 forte |
| `--no-macro` / `--no-calendar` / `--no-micro` | désactive un bloc d'analyse |
| `--no-mt5` | n'interroge pas le terminal MT5 |
| `--demo --seed N` | données simulées, sans réseau |

---

## 5. Lire le rapport

```
VERDICT
------------------------------------------------------------------------
   VENTE  94/100   [TURBO]
  score technique -0.782 -> final -0.909  | accord des timeframes 100%

PLAN DE TRADE
------------------------------------------------------------------------
  VENTE  ordre marche a 2374.23
  Stop loss       2379.24     5.01 $   risque 50.10 $
  TP1             2360.15    14.08 $   2.81R  60% de la position
               -> poche de liquidite (stops accumules)
  TP2             2350.15    24.08 $   4.81R  40% de la position
               -> niveau 2350 (force 0.65)
  Taille             0.10 lots   spread 0.30 $
  Esperance        +0.399 R par trade
```

Chaque cible indique **pourquoi elle est là**. Un TP sans justification
structurelle est un nombre, pas un objectif.

Le rapport contient ensuite :

- **LECTURE PAR TIMEFRAME** — score, régime et volatilité de chaque unité ;
- **ANALYSE FONDAMENTALE** — dollar, taux, risque, calendrier ;
- **MICROSTRUCTURE** — carnet, flux agressif, funding, open interest ;
- **POURQUOI CE SIGNAL** — la liste des faits qui ont pesé ;
- **AJUSTEMENTS APPLIQUÉS** — chaque correction, avec son effet ;
- **AVERTISSEMENTS** — ce qui devrait te faire hésiter ;
- **DONNÉES UTILISÉES** — provenance et fraîcheur de chaque source.

Rien n'est masqué. Une boîte noire qui dit « achète » ne vaut rien.

---

## 6. Comment le moteur décide

### Les timeframes ont des rôles, pas des votes égaux

| Unité | Rôle | Poids |
|---|---|---|
| **M15** | le **contexte** — définit le biais | 42 % (48 % en tendance) |
| **M5** | la **configuration** — qualité du repli, structure | 36 % |
| **M1** | le **déclencheur** — décide l'instant d'entrée | 22 % (38 % en range) |

Les poids s'adaptent au régime : en tendance nette le contexte domine, en range
c'est le timing M1 qui devient décisif.

### Cinq composantes par timeframe

| Composante | Ce qu'elle mesure | Indicateurs |
|---|---|---|
| **trend** | direction établie | empilement EMA 9/21/50/200, pente EMA21 normalisée par l'ATR, Supertrend, ADX/DMI |
| **momentum** | accélération | RSI, StochRSI, MACD, ROC, CCI, Williams %R |
| **structure** | où est le prix | swings, BOS/CHoCH, VWAP, profil de volume (POC/VAH/VAL), pivots, patterns de bougies |
| **participation** | le mouvement est-il réel | z-score de volume, OBV, sortie de compression |
| **meanrev** | extension à corriger | %B des Bollinger, RSI extrême, divergences |

### Régimes détectés

`tendance_forte`, `tendance`, `range`, `compression`, `expansion`, `chaos`.

Le régime pilote la pondération des composantes, la largeur du stop et
l'ambition des cibles. Le régime `chaos` (beaucoup de mouvement, aucune
direction) **bloque le trade** : c'est le pire contexte pour scalper.

### Sessions

| Session (UTC) | Facteur | Caractère |
|---|---|---|
| Asie 00–07 | ×0,55 | range, faible amplitude |
| Londres 07–12 | ×1,15 | premières vraies impulsions |
| **Londres+NY 12–16** | **×1,55** | **meilleure fenêtre de scalp** |
| New York 16–20 | ×1,00 | tendances qui s'essoufflent |
| Clôture 20–24 | ×0,60 | liquidité faible, spreads larges |

### Analyse fondamentale intraday

Sur un horizon de quelques minutes, le fondamental n'est pas le déficit
américain : c'est ce que font **maintenant** le dollar, les taux et l'appétit
pour le risque.

| Moteur | Corrélation avec l'or | Poids |
|---|---|---|
| Dollar (DXY) | **négative** forte | 34 % |
| Taux 10 ans US | **négative** (coût d'opportunité) | 26 % |
| Volatilité (VIX) | **positive** (valeur refuge) | 14 % |
| Taux 2 ans US | négative | 10 % |
| Argent | positive (confirmation du complexe métaux) | 8 % |
| S&P 500 | légèrement négative | 6 % |
| Pétrole | légèrement positive (canal inflation) | 2 % |

Sources gratuites sans clé : Yahoo Finance (intraday 15 min), repli sur Stooq
(journalier). **Une source absente est retirée du calcul et de sa pondération**,
jamais remplacée par une valeur inventée. La confiance affichée reflète la part
des moteurs réellement lus.

### Calendrier économique

Un NFP ou un CPI déplace XAUUSD de 20 à 40 $ en quelques secondes, avec un
spread qui passe de 0,20 $ à 5 $ et des stops sautés au marché. Aucune
configuration technique ne survit à ça.

- **20 min avant / 15 min après** un événement à fort impact → **blocage**
- **60 min avant** → **taille divisée par deux**

Source : flux JSON public de ForexFactory. S'il est inaccessible, l'outil
retombe sur un calendrier récurrent embarqué (NFP le premier vendredi, dates
FOMC, etc.) et **signale que les horaires sont approximatifs**.

### Microstructure

Ces signaux ne viennent pas des bougies. En M1, ils font la différence entre une
cassure qui tient et une mèche qui piège les retardataires.

- **déséquilibre du carnet** dans une bande de 0,05 % autour du mid ;
- **CVD** (delta cumulé) et biais des gros ordres ;
- **absorption** : gros volumes sans progression du prix → cassure suspecte ;
- **funding extrême** → lecture contrarienne ;
- **open interest croisé au prix** → `nouveaux_longs`, `short_squeeze`,
  `long_liquidation`…

### Additif ou atténuation : une distinction critique

Le score fusionné reçoit deux natures d'ajustements :

- **additif** (fondamental, flux) — déplace le score, peut légitimement changer
  le sens si la contradiction est forte ;
- **atténuation** (session pauvre, volatilité basse, conflit M15/M1,
  contre-tendance) — facteur multiplicatif dans ]0 ; 1]. Réduit la conviction,
  **ne peut jamais inverser le verdict**.

Mélanger les deux est un bug classique : une pénalité additive signée appliquée
à un score faible le fait basculer de l'autre côté, et l'outil recommande alors
exactement l'inverse de ce qu'il a mesuré. Le `selftest` vérifie cette propriété
sur des dizaines de cas.

---

## 7. Stop loss, TP1, TP2 et taille de position

### Quatre règles non négociables

1. **Le stop est placé où la thèse est invalidée** — sous une structure — pas à
   une distance ronde arbitraire.
2. **Le spread est intégré partout** : on achète à l'ask, on vend au bid, et un
   TP se juge sur le prix qui le déclenche réellement.
3. **Un trade dont le TP1 n'atteint pas le R:R minimal est refusé.** Un bon
   signal avec un mauvais R:R reste un mauvais trade.
4. **La taille découle du stop**, jamais l'inverse.

### Entrée

- **Mode normal** : ordre **limite** sur un repli (EMA21 M1, VWAP, ou
  retracement Fibonacci 0,382–0,5), à condition qu'il reste à portée
  (moins de 0,8 × ATR M5).
- **Mode turbo** : ordre **au marché** — attendre un repli ferait rater le
  mouvement.

### Stop loss

```
stop = le plus proche entre :
   - structure (dernier swing) ± marge (0,25 × ATR M5, minimum 1,5 × spread)
   - ATR M5 × multiplicateur de régime (0,85 à 1,55 selon la volatilité)
puis borné entre 0,55 × ATR et 2,0 × ATR
```

Le bornage évite les deux échecs symétriques : un stop si serré qu'il saute sur
le bruit, ou si large que le R:R s'effondre.

### TP1 et TP2

Les cibles sont cherchées parmi les prix où le marché a une **raison** de
s'arrêter, chacun pondéré par sa **solidité** :

| Type de cible | Solidité |
|---|---|
| poche de liquidité (stops accumulés) | 0,88 |
| POC du profil de volume | 0,80 |
| VWAP | 0,78 |
| niveau S/R multi-touches | 0,25 à 1,00 selon touches et récence |
| extension Fibonacci 1,272 / 1,618 | 0,66 / 0,68 |
| Value Area High / Low | 0,72 |
| chiffre rond | 0,25 (×5) à 0,85 (×100) |

**TP1** : premier niveau **solide** (≥ 0,50) offrant au moins le R:R minimal.
**TP2** : niveau suivant de solidité ≥ 0,50, ou projection du mouvement mesuré.
À défaut, projection en R ajustée au régime.

Sortie par défaut : **60 % à TP1, 40 % à TP2**.

### Taille de position

```
risque_$ = capital × risque_%  ×  multiplicateur_news  ×  facteur_confiance
lots     = risque_$ / (distance_stop × 100)        (1 lot XAUUSD = 100 onces)
```

Le **facteur de confiance** module entre 0,55 et 1,15 : un signal à 60/100 ne
mérite pas la même taille qu'un signal à 95/100.

### Gestion après l'entrée

- sortir 60 % à TP1 ;
- **remonter le stop à l'entrée + spread** dès TP1 touché — le trade devient
  gratuit ;
- suivre le reste sous l'EMA9 M1 ou à N × ATR, **sans jamais relâcher le stop** ;
- **stop temporel** : si TP1 n'est pas touché en 12 à 25 bougies selon le
  régime, sortir au marché. La thèse avait une durée de vie, elle est expirée.

### L'espérance affichée

Elle repose sur un modèle de référence honnête : sur une marche aléatoire, la
probabilité d'atteindre **+kR avant −1R** vaut `1/(1+k)`. La confiance du signal
déplace cette base d'au plus 20 points.

C'est volontairement conservateur. Faire dépendre la probabilité de la seule
confiance produit des aberrations — annoncer 72 % de réussite sur un TP à 2,8R
est une promesse intenable. Avec `--with-backtest`, ces probabilités sont
remplacées par des **taux mesurés** sur ton historique réel.

---

## 8. Le mode TURBO

Le drapeau `[TURBO]` n'apparaît que si **six conditions** sont réunies
simultanément :

1. les 3 timeframes sont alignés (accord 100 %) ;
2. confiance ≥ 78/100 ;
3. session à forte liquidité (Londres, Londres+NY) ;
4. volatilité haute ou extrême ;
5. score de microstructure supérieur à 0,15 en valeur absolue ;
6. ce flux va **dans le sens** du signal.

En turbo, l'entrée passe **au marché** au lieu d'attendre un repli. C'est rare,
et c'est fait exprès : un mode turbo qui se déclenche tout le temps n'est pas un
mode turbo.

---

## 9. Backtest : ce qu'il mesure vraiment

```bash
python3 -m goldscalp backtest --bars 6000
```

### Ce qu'il mesure

Le **cœur technique** : tendance, momentum, structure, participation, retour à
la moyenne, fusionnés M15 + M5, avec les mêmes règles de stop et de cibles que
le mode live.

### Ce qu'il ne mesure pas

La **microstructure** (carnet et flux ne sont pas historisés par l'API
publique), la **macro intraday** et le **filtre news**. Les taux obtenus sont
donc un **plancher prudent**, pas une promesse de performance.

### Conventions appliquées

- toute décision à la bougie *i* n'utilise que les données jusqu'à *i* ;
- l'entrée se fait à l'**ouverture de la bougie suivante**, jamais au cours de
  clôture qui a servi à décider ;
- si le stop **et** la cible tombent dans la même bougie, le **stop** est
  compté ;
- le spread est prélevé à l'entrée et à la sortie ;
- après TP1, le stop remonte à l'entrée — comme la règle de gestion live.

### Le contrôle qui compte

`selftest` vérifie que sur une **marche aléatoire pure**, l'espérance reste
proche de zéro. Une espérance nettement positive sur du bruit ne signifierait
pas que le moteur est bon : elle signifierait qu'il **triche** (fuite du futur
ou comptage favorable des sorties).

Résultats de validation sur données synthétiques :

| Données | Espérance | Facteur de profit |
|---|---|---|
| bruit pur (aucun edge) | −0,03 R | 0,98 |
| momentum faible | +0,07 R | 1,12 |
| momentum fort | +0,25 R | 1,46 |

Le moteur ne détecte un edge que lorsqu'il en existe un.

---

## 10. Configuration

```bash
python3 -m goldscalp config           # affiche
python3 -m goldscalp config --save    # écrit sur disque
python3 -m goldscalp config --path    # emplacements des fichiers
```

Fichiers dans `~/.goldscalp/` (surchargeable par `GOLDSCALP_HOME`) :

- `config.json` — paramètres
- `calibration.json` — ancrages Bybit ↔ MT5
- `cache/` — cache court des données macro et du calendrier

### Paramètres de risque principaux

| Clé | Défaut | Rôle |
|---|---|---|
| `account_balance` | 10 000 | capital du compte |
| `risk_pct` | 0,5 | % risqué par trade |
| `min_rr_tp1` | 1,0 | R:R minimal exigé sur TP1 |
| `tp1_share` | 0,6 | part sortie à TP1 |
| `max_stop_atr` | 2,0 | stop plafonné à N × ATR M5 |
| `max_spread` | 0,60 | au-delà, le scalp M1 n'est plus rentable |

---

## 11. Tableau de bord web et déploiement Vercel

En plus de la ligne de commande, le dépôt contient une **interface web**
déployable sur Vercel : une fonction Python serverless qui expose le moteur en
JSON, et un tableau de bord statique qui l'interroge.

```
api/index.py       fonction serverless (/api/analyse, /api/health)
public/index.html  tableau de bord (aucune dépendance, aucun CDN)
vercel.json        région, durée maximale, réécritures
dev_server.py      serveur local reproduisant le routage Vercel
```

### Essayer en local d'abord

```bash
python3 dev_server.py      # puis http://127.0.0.1:8000
```

### Déployer

1. Pousse ce dossier sur GitHub, puis **Add New Project** sur Vercel.
2. **Root Directory : `gold-scalper`** — c'est le réglage le plus important.
   Sans lui, Vercel tente de construire la racine du dépôt.
3. **Framework Preset : Other.** Pas de commande de build, pas d'installation.
4. Déploie, puis **vérifie d'abord en mode démo** :
   `https://<ton-projet>.vercel.app/?` puis active *Démo* dans les réglages,
   ou appelle directement `https://<ton-projet>.vercel.app/api/analyse?demo=1`.

Ou en une commande, depuis ce dossier :

```bash
npx vercel --prod
```

### Le point qui casse tout : la région

**Bybit filtre les adresses IP américaines**, au niveau de son CDN. Une fonction
déployée à Washington (`iad1`, la région par défaut de beaucoup de comptes)
reçoit ceci :

```
403 — The Amazon CloudFront distribution is configured to block access
      from your country
```

`vercel.json` demande `fra1` (Francfort), mais **ce champ n'est pas toujours
honoré** : selon le plan, la région des fonctions est imposée par le projet. Le
réglage fiable est dans l'interface :

> **Project Settings → Functions → Function Region → Frankfurt, Germany (fra1)**
>
> puis **redéploie** — le changement ne s'applique pas au déploiement existant.

Autres régions convenables : `dub1` (Dublin), `cdg1` (Paris), `sin1`
(Singapour), `hnd1` (Tokyo). À éviter : `iad1`, `sfo1`, `cle1`, `pdx1`.

**Depuis l'ajout du repli Yahoo, ce n'est plus bloquant** : si Bybit refuse,
l'outil bascule seul sur l'or spot Yahoo et continue de produire des signaux.
Corriger la région reste préférable — tu récupères le 24/7, le volume et la
microstructure.

Pour vérifier la région servie : `https://<ton-projet>.vercel.app/api/health`
renvoie le champ `region`.

### La calibration en serverless

Une fonction serverless **ne garde rien entre deux appels** : le fichier
`~/.goldscalp/calibration.json` de la ligne de commande n'existe pas. La
calibration doit donc être fournie à chaque requête, par ordre de priorité :

1. **un ancrage complet** dans l'URL : `?bybit=2405.10&bid=2412.30&ask=2412.60` ;
2. **alpha / beta / spread** dans l'URL : `?alpha=7.35&spread=0.30` ;
3. **les variables d'environnement du projet Vercel** :
   `GOLDSCALP_ALPHA`, `GOLDSCALP_BETA`, `GOLDSCALP_SPREAD`.

Le tableau de bord retient tes réglages dans le stockage local du navigateur et
les renvoie à chaque appel — ils ne quittent jamais ton poste autrement que dans
l'URL de ta propre requête. **Sans alpha, la page affiche des prix Bybit bruts**
et le signale en rouge.

### Paramètres de l'API

`GET /api/analyse` accepte : `alpha`, `beta`, `spread`, `bybit`, `bid`, `ask`,
`balance`, `risk`, `min_confidence`, `symbol`, `bybit_symbol`, `macro`,
`calendar`, `micro`, `counter_trend`, `demo`, `seed`.
`GET /api/health` renvoie la version, la région et la version de Python.

### Ce que la version web ne fait pas

- **Pas de pont MT5.** Aucun terminal MetaTrader ne tourne sur un serveur
  Vercel : les prix viennent forcément de Bybit, recalibrés.
- **Pas de mode `watch`.** Le serverless ne maintient pas de boucle. Le tableau
  de bord fait du rafraîchissement côté navigateur, avec un bouton *Auto* qui se
  suspend quand l'onglet passe en arrière-plan pour ne pas consommer
  d'invocations inutilement.
- **Volumes réduits.** 500 bougies M1, 400 M5, 300 M15 au lieu des volumes de la
  ligne de commande, pour tenir dans le budget de temps d'exécution.
- **Pas de backtest.** Trop long pour une invocation ; reste en ligne de commande.

### Coût et exposition

Chaque chargement déclenche une invocation. En rafraîchissement automatique
toutes les 60 s, cela fait environ 1 440 invocations par jour et par onglet
ouvert — largement dans les limites du plan Hobby, mais à surveiller si tu
laisses la page ouverte en permanence sur plusieurs appareils.

**L'URL est publique par défaut.** N'importe qui la connaissant peut appeler
l'API et consommer tes invocations. Si tu veux la garder privée, active
*Deployment Protection* (Vercel Password Protection) dans les réglages du
projet.

---

## 12. Limites connues

À lire avant de mettre le moindre euro en jeu.

- **XAUT n'est pas XAUUSD.** Le recalibrage corrige le niveau, pas les
  divergences ponctuelles de liquidité. En cas de stress sur les stablecoins,
  l'écart peut s'ouvrir brutalement et la calibration devient fausse en
  quelques minutes.
- **La calibration vieillit.** Recalibre toutes les 2 à 4 heures. L'outil
  t'avertit, mais il ne peut pas le deviner à ta place.
- **Le repli Yahoo n'est pas l'égal de Bybit.** Pas de volume sur `XAUUSD=X`,
  donc pas de vraie lecture de participation ; pas de carnet ni de flux, donc
  pas de microstructure ; et l'or spot ferme du vendredi 22 h au dimanche 22 h
  UTC. L'outil signale chacun de ces manques plutôt que de les combler par des
  valeurs inventées.
- **La microstructure vient de Bybit, pas de ton broker.** Le carnet XAUT n'est
  pas le carnet de ton courtier. Le signal de flux reste informatif sur la
  direction du métal, pas sur l'exécution que tu obtiendras.
- **Le calendrier de repli est approximatif.** Quand le flux ForexFactory est
  inaccessible, les horaires embarqués sont des règles générales. Vérifie sur
  ton calendrier habituel.
- **Le backtest n'inclut ni slippage variable, ni élargissement du spread en
  news, ni rejets d'ordre.** En conditions réelles, compte moins que les
  chiffres affichés.
- **Aucune exécution automatique.** L'outil ne passe pas d'ordre et n'accède
  jamais à ton compte. Il produit une analyse ; la décision et l'exécution
  restent les tiennes.
- **Le mode `--demo` ne vaut rien pour trader.** C'est un simulateur destiné à
  essayer l'interface et à tester le moteur.

---

## Architecture

```
goldscalp/
├── cli.py              interface en ligne de commande
├── config.py           paramètres marché / risque / moteur
├── engine.py           pipeline : données -> analyse -> plan
├── selftest.py         contrôles d'intégrité du moteur
├── util.py             HTTP, cache, maths (Theil-Sen, percentiles…)
├── core/
│   ├── series.py           bougies OHLCV, rééchantillonnage
│   ├── indicators.py       ~30 indicateurs en Python pur
│   ├── structure.py        swings, BOS/CHoCH, S/R, pivots, fibs, liquidité
│   ├── microstructure.py   carnet, CVD, funding, open interest
│   ├── calibration.py      recalibrage affine Bybit -> MT5
│   ├── regime.py           régimes de marché et sessions
│   ├── fundamental.py      dollar, taux, risque
│   ├── scoring.py          fusion multi-timeframe
│   ├── plan.py             entrée, SL, TP1, TP2, taille
│   └── backtest.py         walk-forward sans fuite du futur
├── data/
│   ├── bybit.py            client API v5 (public, sans clé)
│   ├── yahoo.py            source de repli (or spot, non géo-bloquée)
│   ├── mt5.py              pont MetaTrader 5 (facultatif)
│   ├── macro.py            Yahoo Finance / Stooq
│   ├── calendar.py         ForexFactory + calendrier de repli
│   └── synthetic.py        simulateur de marché
└── ui/console.py       rapport terminal

api/index.py            fonction serverless Vercel
public/index.html       tableau de bord web
dev_server.py           serveur local (routage identique a Vercel)
vercel.json             region, duree maximale, reecritures
```

### Tests

```bash
python3 -m unittest discover -s tests
```

94 tests couvrant les bornes des indicateurs, la causalité, l'identifiabilité de
la pente de calibration, la géométrie des plans, la non-inversion des signaux,
l'honnêteté du backtest, la bascule de source quand Bybit est géo-bloqué, et le
CLI.

---

## Avertissement

Cet outil produit une **analyse**, pas un ordre. Le trading de l'or avec effet
de levier peut entraîner des pertes supérieures au dépôt initial. Le marché peut
invalider n'importe quelle configuration, quelle qu'en soit la confiance
affichée.
