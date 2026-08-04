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

- **Temps réel** — progression du setup, marché, dernier signal, bandeaux d'alerte.
- **Signaux** — backtest de tes réglages sur l'historique chargé + signaux de la session.
- **Actus** — calendrier économique USD et fil géopolitique lié à l'or.
- **Réglages** — capital, risque, score/ratio minimum, sessions, mode d'entrée.
- **Aide** — fonctionnement et limites.

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
du calendrier, précision du filtre de chocs, et blocage effectif d'une entrée
tombant dans une fenêtre d'annonce.
