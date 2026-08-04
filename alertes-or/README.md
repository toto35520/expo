# Alertes OR

Page HTML autonome (aucune dépendance, aucun build) qui surveille l'or (XAU/USD, via
les bougies 5 minutes du jeton PAXG) et détecte des setups
trend → sweep → reclaim → BOS → retest.

## Utiliser la page

Ouvre `index.html` directement dans un navigateur, ou héberge-le sur n'importe quel
serveur statique. Elle a besoin d'un accès Internet classique ; aucun serveur ni
compte n'est nécessaire.

Sur mobile, ajoute-la à l'écran d'accueil (Safari : Partager → « Sur l'écran
d'accueil » ; Chrome : menu ⋮ → « Ajouter à l'écran d'accueil »). Active les
notifications dans l'onglet Réglages.

## Onglets

- **Temps réel** — progression du setup, marché, confluence, dernier signal.
- **Signaux** — backtest de tes réglages sur l'historique chargé + signaux de la session.
- **Zones ICT** — Order Blocks, Breakers, FVG, IFVG, BPR, dealing range, liquidité, gaps.
- **Captures** — dépôt des graphiques H4/H1/M30/M5 et analyse visuelle locale.
- **Mes trades** — suivi live des trades saisis à la main ou adoptés depuis un signal.
- **Institutionnel** — suite ICT complète et score de confluence pondéré.
- **Actus** — calendrier économique USD et fil géopolitique lié à l'or.
- **Réglages** — capital, risque, score/ratio minimum, sessions, mode d'entrée.
- **Aide** — fonctionnement et limites.

## Philosophie : qualifier, pas bloquer

Les analyses ICT et institutionnelles **ne bloquent aucun signal**. Elles lui
donnent une note. Seuls deux garde-fous refusent réellement un trade : le
**ratio** (il faut un objectif à `minRiskReward`) et le **filtre actualités**.

Chaque entrée reçoit une note A/B/C/D issue des zones ICT touchées, de la
position dans le dealing range, de la confluence institutionnelle, du score de
séquence et du ratio disponible. Un setup moyen sort quand même — annoté comme
tel — plutôt que d'être supprimé en silence.

### Comment le blocage a été levé

Le sweep n'était armé que si toute la confluence était réunie **sur la bougie
même du sweep**. Sur 17 jours réels : 29 zones approchées, 2 sweeps, 0 entrée.
Le sweep s'arme désormais sur la prise de liquidité seule, et la confluence est
passée dans la note.

Les objectifs suivaient la même erreur : TP1 était le niveau le plus proche et
on exigeait qu'il fasse déjà 2R, ce qui refusait 197 candidates sur 223. TP1
vise maintenant ≈ 1R et c'est **TP2** qui doit atteindre le ratio, conformément
à la règle V8. Les cibles au-delà de 25 ATR sont ignorées : elles gonflaient le
ratio sans être atteignables.

Mesuré sur 60 jeux de données de 17 jours : entrées **1 → 20**, achats et
ventes équilibrés, ratio TP2 médian **5,3R**, dix setups à 5R ou plus. Le taux
de réussite affiché sur ces jeux n'a aucune valeur prédictive : ce sont des
marches aléatoires, sans avantage statistique par construction.

## Taille de position et plan de trade

L'analyseur dimensionne chaque trade sur ton capital réel :

- lot **arrondi au pas du broker** vers le bas (jamais au-dessus du risque autorisé) et plafonné par `maxLot` ;
- `riskPercent` borné par `maxRiskPercent` ;
- **conversion de devise** : l'or cote en USD, ton compte peut être en EUR. Le champ « 1 unité de ta devise = ? USD » sert à convertir le risque et les gains ;
- **marge** calculée depuis le levier, avec alerte au-delà de `maxMarginPercent` ;
- **gain projeté** à TP1, TP2 et TP3, dans la devise du compte ;
- si le lot minimum du broker dépasse déjà le risque autorisé, le trade est marqué **capital insuffisant** avec le chiffre exact, au lieu d'un lot fantaisiste.

## Familles de setups

Au-delà de la séquence sweep → réintégration → BOS → retest, l'analyseur
exploite les zones qu'il calcule déjà :

| Famille | Déclencheur |
| --- | --- |
| `SEQUENCE` | sweep, réintégration, BOS puis retest |
| `ZONE_HTF` | retour sur un OB, FVG, IFVG, BPR ou Breaker H4/H1/M30 avec bougie de rejet |
| `OTE` | retracement dans la zone 62–79 % d'une impulsion, avec rejet |
| `SILVER_BULLET` | sweep + MSS + FVG dans la fenêtre horaire stricte |

Chaque famille passe par les **mêmes garde-fous** : ratio minimum, veto
actualités, filtre de session, stop ni trop serré ni trop large, notation et
journal. La famille est enregistrée avec le trade, donc le journal dira
laquelle fonctionne réellement chez toi.

## Journal auto-apprenant

Chaque trade proposé par l'analyseur est **enregistré définitivement**, que tu
l'aies pris ou non, puis rejoué contre les bougies réelles jusqu'à son issue :
jamais déclenché, stop, TP1, TP2 ou TP3, avec le résultat en R.

Les statistiques sont regroupées par **note** (A/B/C/D) et par **sens**, et la
page en tire des conseils du type « les setups note D t'ont coûté 6R sur 24
trades : relève le score minimum ».

C'est de la **mesure, pas de l'apprentissage automatique**. Un conseil ne
s'affiche qu'à partir de 20 trades clôturés dans le groupe concerné ; en
dessous, l'interface le dit explicitement plutôt que de tirer des conclusions
sur trois trades. Le journal survit au rechargement (`localStorage`) et
n'influence jamais la détection : un test vérifie qu'il n'est pas référencé
dans `detect()`.

## Zones ICT / SMC

Détection sur bougies clôturées, de D1 à M5 :

| Élément | Détail |
| --- | --- |
| Timeframes | D1, H4, H1, M30, M15, M5 |
| Order Blocks | dernière bougie opposée avant un déplacement ≥ 1,1 ATR, validée par une cassure de structure, avec test d'invalidation |
| Breaker Blocks | Order Block cassé, rejoué en sens inverse |
| FVG | trois bougies, filtre ATR (8 %), suivi d'activité |
| IFVG | FVG traversée en clôture, rôle inversé |
| BPR | chevauchement de deux FVG opposées |
| Dealing range | swings H4, equilibrium 50 %, quartiles premium / discount |
| ERL | PDH, PDL, PWH, PWL |
| IRL | swings internes, equal highs/lows, midpoints de FVG |
| NDOG / NWOG | écarts 17:00 → 18:00 New York |
| Échelle d'objectifs | chaque cible de liquidité au-delà de l'entrée, avec son ratio R |

**Le ratio n'est pas plafonné** : `minRiskReward` est un plancher. Une cible à
5 R ou 10 R apparaît dans l'échelle dès qu'un niveau de liquidité la porte.

**SMT Gold/Silver n'est pas implémenté** : il faudrait des bougies M5 d'argent,
qu'aucune source branchée ici ne fournit. Le signaler vaut mieux que le simuler.

## Suite institutionnelle

Portée de `advanced.py` (GoldGuard V8.1) vers le navigateur :

| Module | Détail |
| --- | --- |
| Kill Zones | Asie, Londres, New York, clôture de Londres (heure NY) |
| Silver Bullet | fenêtres strictes 03–04, 10–11, 14–15 NY + détection sweep/MSS/FVG |
| Asian Range | 20:00–00:00 NY |
| CBDR | 14:00–20:00 NY + projections ×1/×2/×3 |
| OTE | 62–79 %, optimum 70,5 % |
| Power of Three | accumulation → manipulation → distribution |
| Judas Swing | sweep du range asiatique pendant Londres |
| VWAP session | ancré 18:00 NY, bandes ±1σ/±2σ |
| Volume Profile | POC, VAH, VAL, HVN, LVN |
| RSI / MACD | Wilder 14 · 12/26/9, sur M5, M15 et H1 |
| Delta / CVD | volume taker **réel** (Binance), proxy signé sinon |
| Open Interest | affiché indisponible tant qu'aucun flux futures n'est branché |

Le score de confluence pondère ces 12 filtres (poids 5 à 12) et renvoie
`ALIGNED` / `MIXED` / `OPPOSED` par côté, avec détection de conflit fort.
Il est **informatif** : il ne bloque pas les entrées, contrairement au filtre
actualités.

### Correctif apporté au portage

Dans `advanced.py`, `_rows_for_window` normalisait la borne de fin sur les
heures brutes (`end_hour if end_hour > start_hour else end_hour + 24`). Toute
fenêtre commençant avant 18:00 NY donnait une condition impossible
(`26 <= h < 5`) et retournait une liste vide : **Judas Swing, Power of Three et
Silver Bullet ne pouvaient jamais se déclencher**. Les 39 tests du moteur ne
couvraient que `silver_bullet_window` (l'horloge), pas `silver_bullet_setup`
(la détection). Ici les deux bornes sont normalisées sur l'échelle de session,
et un test vérifie que les six fenêtres renvoient des bougies.

## Analyse de captures

Glisser-déposer, clic ou Ctrl+V dans les emplacements H4, H1, M30 et M5. Les
images sont analysées **dans le navigateur** et ne sont jamais envoyées.

Mesuré au pixel, sans OCR :

| Mesure | Méthode |
| --- | --- |
| Graphique ou non | part de colonnes contenant des bougies |
| Tendance visuelle | régression du centre du tracé, exprimée en % de la hauteur |
| Premium / discount | position de la dernière bougie dans le range visible |
| Équilibre haussier / baissier | proportion de pixels verts et rouges |
| Lignes horizontales | rangées dont un segment continu couvre > 55 % de la largeur |
| Zones dessinées | blocs de teinte uniforme distincts du fond et des bougies |

La page **compare** ensuite la tendance lue sur l'image à celle que le moteur
calcule sur les bougies réelles, et signale tout désaccord.

Ce qui n'est **pas** extrait : les prix. Lire des chiffres au pixel produirait
des niveaux faux, et un stop faux coûte de l'argent. Les niveaux chiffrés
viennent toujours des bougies réelles. C'est aussi le choix de GoldGuard, dont
`vision.py` ne lit pas les images non plus : il consomme des métadonnées OCR
et ne sert que de garde-fou.

### Calendrier local

Les sources publiques de calendrier refusent les navigateurs (pas d'en-tête
CORS) et renvoient une page HTML aux relais. Plutôt que d'empiler des proxies
fragiles, la page recalcule **hors ligne** les annonces USD à horaire
déterministe, en heure de New York et avec l'heure d'été :

- inscriptions hebdomadaires au chômage — chaque jeudi 08:30 NY ;
- emploi non agricole (NFP) — premier vendredi du mois, 08:30 NY ;
- décisions FOMC — dates programmées, 14:00 NY.

Le filtre actualités reste donc **actif même sans réseau**. Ces dates sont
marquées « estimé » dans l'onglet Actus : le CPI, dont la date varie, n'est
volontairement pas deviné.

Les fenêtres de blocage sont des plages **absolues** (et non des heures de la
journée), pour qu'une annonce d'un jour ne bloque pas le même horaire les
autres jours.

## Suivi de trades

La page **suit** un trade dont tu fournis les niveaux, d'où qu'ils viennent.

- Saisie manuelle : sens, entrée, stop, TP1, TP2, note.
- Adoption en un clic du dernier signal de l'analyseur.
- Suivi live : attente d'entrée → déclenchement → stop/TP, résultat en R,
  excursion maximale favorable et défavorable, taille de lot, notifications.
- L'évaluation rejoue l'historique depuis la création : un trade posé la
  veille est correctement résolu même si la page est restée fermée.
- Les trades sont conservés dans le navigateur (`localStorage`) et survivent
  au rechargement.

Les niveaux se saisissent dans l'échelle affichée à l'écran (spot XAU/USD si
l'alignement est actif) et sont convertis vers l'échelle brute des bougies au
moment de l'évaluation. Un TP situé du mauvais côté de l'entrée est ignoré, et
une bougie touchant stop et TP est comptée comme perdante, comme dans le
backtest.

## Sources de données

| Donnée | Source | Repli |
| --- | --- | --- |
| Bougies M5 | Binance PAXGUSDT | Binance data-api, Bybit, OKX, 2 relais CORS |
| Cours spot | gold-api.com | relais CORS |
| Calendrier USD | ForexFactory (`ff_calendar_thisweek.json`) | 5 relais CORS, puis **calendrier local hors ligne** |
| Actualités | GDELT | relais CORS |

## Profondeur d'historique

La page charge **~5 000 bougies M5 (~17 jours)** en paginant l'API, puis met à jour
en incrémental. C'est nécessaire : l'analyse H4 utilise une EMA 50, donc il faut au
moins 50 bougies H4 (= 2 400 bougies M5). En dessous, la tendance H4 reste
bloquée sur « neutre » et **aucun setup ne peut s'armer**.

## Filtre actualités

Repris de la logique du moteur GoldGuard :

- **Calendrier** : une annonce USD à fort impact (ou dont le titre correspond à
  CPI/NFP/FOMC/Powell/Trump/tarifs/sanctions…) bloque les entrées de 30 min avant
  à 15 min après.
- **Choc macro** : un titre d'actualité contenant à la fois un nom politique
  (Trump, Fed, Powell, White House…) **et** un terme de marché (tarifs, sanctions,
  guerre, taux, inflation…) bloque les entrées pendant 45 min.

Les deux conditions doivent être réunies pour un choc, ce qui évite les faux
positifs (une actualité « guerre » sans acteur politique ne bloque pas).

## Setups de référence

Deux séquences « manuel de cours » sont construites à la main, une à l'achat et
une à la vente : rallye, pivot bas propre, pivot haut, sweep de liquidité,
réintégration en clôture, cassure de structure avec déplacement, puis retest.
Le test exige que le moteur sorte une entrée du bon sens, avec trois objectifs
ordonnés et un ratio d'au moins 2R.

Ces tests ont révélé un faux négatif réel : quand une bougie invalidait un
setup encore en attente, le moteur traitait l'invalidation **après** avoir déjà
sauté le bloc d'armement, si bien que cette bougie ne pouvait pas armer un
nouveau sweep. Or c'est précisément le cas fréquent en marché rapide, la bougie
qui invalide étant souvent la nouvelle prise de liquidité. Le setup de
référence était donc perdu. L'armement est désormais retenté sur la même
bougie après chaque invalidation.

## Vérification

Testé en navigateur headless : syntaxe, absence d'erreur JS/NaN, rendu de chaque
type de signal, pagination de l'historique, calcul de taille de position, parsing
du calendrier, précision du filtre de chocs (10/10), et blocage effectif d'une
entrée tombant dans une fenêtre d'annonce.

Analyse de captures : sur des graphiques générés à trajectoire imposée, la
tendance haussière, baissière et neutre est correctement identifiée, le
premium et le discount aussi, les lignes tracées sont comptées, une image qui
n'est pas un graphique est rejetée, un fichier non-image est refusé, et un
désaccord capture/moteur est signalé sans faux positif quand les deux
concordent.

Suite institutionnelle : les six fenêtres horaires renvoient des bougies, le
passage heure d'été/hiver de New York est correct (16 h en juillet, 15 h en
janvier pour 20:00 UTC), l'OTE tombe exactement sur 62 / 70,5 / 79 %, le RSI de
Wilder vaut 100 sur une série strictement croissante et 0 sur une série
décroissante, et le POC affiché est identique dans les deux panneaux.
