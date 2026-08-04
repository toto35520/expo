# Alertes OR

Page HTML autonome (aucune dépendance, aucun build) qui surveille l'or (XAU/USD, via
les bougies 5 minutes du jeton PAXG) et détecte des setups trend → sweep → reclaim → BOS → retest.

## Utiliser la page

Ouvre `index.html` directement dans un navigateur (double-clic, ou héberge-le sur
n'importe quel serveur statique). Elle a besoin d'un accès Internet classique pour
interroger Binance / Bybit / OKX (bougies) et gold-api.com (cours spot) — aucun
serveur ni compte n'est nécessaire.

Sur mobile, ajoute-la à l'écran d'accueil (Safari : Partager → « Sur l'écran
d'accueil » ; Chrome : menu ⋮ → « Ajouter à l'écran d'accueil ») pour la retrouver
comme une app. Active les notifications dans l'onglet Réglages pour être alerté
même si l'écran est éteint (tant que la page reste ouverte).

Testé (moteur de détection, rendu de chaque type de signal, gestion des erreurs
réseau, calcul de taille de position) sans erreur JS ni valeur NaN/undefined.
