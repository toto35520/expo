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
- **Institutionnel** — suite ICT complète et score de confluence pondéré.
- **Actus** — calendrier économique USD et fil géopolitique lié à l'or.
- **Réglages** — capital, risque, score/ratio minimum, sessions, mode d'entrée.
- **Aide** — fonctionnement et limites.

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

## Sources de données

| Donnée | Source | Repli |
| --- | --- | --- |
| Bougies M5 | Binance PAXGUSDT | Binance data-api, Bybit, OKX, 2 relais CORS |
| Cours spot | gold-api.com | relais CORS |
| Calendrier USD | ForexFactory (`ff_calendar_thisweek.json`) | 2 relais CORS |
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

## Vérification

Testé en navigateur headless : syntaxe, absence d'erreur JS/NaN, rendu de chaque
type de signal, pagination de l'historique, calcul de taille de position, parsing
du calendrier, précision du filtre de chocs (10/10), et blocage effectif d'une
entrée tombant dans une fenêtre d'annonce.

Suite institutionnelle : les six fenêtres horaires renvoient des bougies, le
passage heure d'été/hiver de New York est correct (16 h en juillet, 15 h en
janvier pour 20:00 UTC), l'OTE tombe exactement sur 62 / 70,5 / 79 %, le RSI de
Wilder vaut 100 sur une série strictement croissante et 0 sur une série
décroissante, et le POC affiché est identique dans les deux panneaux.
