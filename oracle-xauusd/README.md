# oracle-xauusd — analyse.html

Copie de la page servie sur https://oracle-xauusd.vercel.app/analyse.html
(le projet Vercel n'est relié à aucun dépôt Git : les mises en ligne se font
par upload / CLI, ce fichier sert donc de référence versionnée).

## Correctif — incohérence sens du badge / sens du plan

Version `2026.08.06-h` (base : `2026.07.19-g`).

Symptôme : la carte « Décision » pouvait afficher un badge
`🟠 PRÉPARE-TOI — SELL EN APPROCHE` au-dessus d'un plan entièrement BUY
(vision « HAUSSE », `Sens BUY`, stop *sous* le plus bas). Le bouton
« J'ai pris ce trade au déclencheur » enregistrait alors le SELL, avec les
SL/TP du setup — donc un trade différent de celui affiché juste au-dessus.

Cause, dans `renderDecision()` : le setup « armé » était choisi sans vérifier
qu'il allait dans le sens de la décision.

```js
// avant — aucune contrainte de sens vis-à-vis de d.side
setups.find(s => s.ready >= 70 && (!sigLock || ...))
```

Le badge, la ligne « Déclencheur » et `window._plan` venaient du setup armé,
tandis que la vision, le tableau et la ligne de lot venaient de la décision `d`.
Deux trades opposés cohabitaient donc dans la même carte.

Corrections :

1. Un setup n'est armé que si `s.side === d.side` (l'intention d'origine, notée
   « jamais à contresens », n'était appliquée qu'au verrou anti-girouette).
2. Un seul objet `P` alimente badge, vision, tableau, lot et `window._plan` :
   l'écran et le bouton décrivent forcément le même trade.
3. Si une position est déjà ouverte, la carte affiche un rappel du trade en
   cours et le bouton « J'ai pris ce trade » est désactivé — plus de doublon
   ni de prise à contresens de sa propre position.

## Correctif — les garde-fous étaient contournables

Version `2026.08.06-i`.

Deux failles indépendantes de la précédente, qui laissaient passer des trades
que le moteur avait explicitement refusés :

### 1. Les blocages de sécurité n'engageaient que la carte, pas le bouton

`decideTrade()` refuse d'entrer pour dix raisons distinctes, mais toutes
renvoyaient le même `action: "WAIT"`. `renderDecision()` armait un setup dès
que `ready >= 70` sans regarder *pourquoi* le moteur avait dit non — un plan
prêt à cliquer s'affichait donc juste sous « journée TERMINÉE après 2 stops »,
« NFP dans 20 min » ou « H1/H4 ne confirme pas » (le filtre que le commentaire
du code chiffre à 51 % → 56 % de réussite).

`wait()` prend désormais un drapeau `hard`. Neuf refus sont marqués bloquants —
marché fermé, 2 stops sur la journée, news éco à moins de 45 min, RSI extrême
ou prix étiré, absence de confirmation H1/H4, vent de face du DXY (deux sens),
score sous le seuil d'edge. Tant qu'un blocage dur tient, aucun setup n'est
armé et aucun bouton d'entrée ne s'affiche ; la carte l'annonce explicitement.

Les quatre attentes souples (prix collé à un niveau, R:R insuffisant, bougie de
confirmation à venir, timing M5) continuent d'armer normalement : ce sont
précisément les cas où « prépare-toi » a un sens.

### 2. Les trades pris n'entraient pas dans le journal

`journalAdd()` n'était appelé que sur les signaux stricts émis par l'app.
Les trades pris au déclencheur via le bouton n'allaient que dans `myTrade`.
Conséquences : la carte « je vérifie mes propres trades » n'apprenait jamais
des trades réellement pris, et `slToday()` — qui déclenche la règle « 2 stops
= journée terminée » — ne comptait jamais les vraies pertes.

`journalTake()` inscrit maintenant tout trade pris ou déclaré, en marquant le
signal existant plutôt qu'en le doublonnant s'il vient d'être journalisé.
Ces lignes portent la mention `📥 pris` dans l'historique.

## Ajout — chat « Parle-moi »

Version `2026.08.06-j`.

Une carte de discussion sous le suivi de trade : question en français libre,
réponse immédiate. Le moteur lit l'instantané `AI` de la dernière analyse
(décision, snapshots M15/H1/H4, ATR, S/R, contexte, événement éco) plus
`myTrade`, `journalStats()`, `lessons()` et `slMultLearned()` — donc les
chiffres annoncés sont exactement ceux des cartes, jamais une approximation.

Aucun appel réseau : la réponse est instantanée et fonctionne hors connexion.

Intentions reconnues : avis sur le trade en cours, entrer ou non maintenant,
pourquoi cette décision, placement du stop, risque et lot, niveaux
(S/R, POC, VWAP, objectifs), tendance multi-timeframes, statistiques du
journal, actualité et événements, prix. Toute autre formulation renvoie le
menu des questions possibles.

L'avis sur le trade en cours applique la même hiérarchie que la carte de
suivi — marché fermé, stop touché, TP1 pris, signal inversé — et ajoute un
avertissement quand le biais passe contre la position sans qu'un signal
inverse soit encore donné.

`AI` est renseigné dans `analyze()` juste avant `renderDecision()`.

## Correctif — le flux temps réel pouvait se figer sans que rien ne le signale

Version `2026.08.06-k`.

`connectWS()` ne se reconnectait que sur `onclose`. Or un WebSocket peut cesser
d'émettre **sans se fermer** : bascule wifi/4G, mise en veille de l'écran,
coupure côté serveur. Dans ce cas :

- aucune reconnexion n'était déclenchée ;
- le prix restait figé sur la dernière valeur reçue ;
- le voyant `● temps réel` continuait de clignoter, puisqu'il n'était écrit
  que dans `onmessage` — il indiquait donc « direct » sur un prix mort ;
- surtout, `journalTick()` et `trackTrade()` ne tournent que sur les ticks :
  **la surveillance du stop et de l'objectif s'arrêtait complètement**, sans
  aucune alerte.

Ajouts :

- chien de garde toutes les 3 s ; le voyant dit la vérité (`temps réel` ≤ 15 s,
  `dernier prix il y a N s` ≤ 60 s, `⚠️ flux figé` au-delà) ;
- reconnexion forcée au-delà de 60 s sans tick, throttlée à 20 s ;
- bannière rouge à la coupure, bannière verte au rétablissement ;
- `catchUpTrade()` rejoue les bougies 1 min depuis l'ouverture du trade pour
  détecter un SL ou un TP1 touché pendant le trou, et prévient explicitement ;
- reprise sur `visibilitychange` (retour au premier plan, cas le plus fréquent
  sur téléphone) et sur `online` ;
- le chat expose l'âge du dernier tick et l'âge du recalage PAXG → spot XAU,
  avec le rappel que le prix affiché est un proxy, pas le flux du broker.

## Ajout — analyse des mouvements brutaux

`explainSpike()` se déclenche sur tout mouvement dépassant 0,7 × ATR en une
minute et croise six familles de causes : statistique économique programmée,
ouverture de session, volume de la bougie contre la moyenne des 20 précédentes,
niveau traversé (S/R, POC, pivots, VWAP), balayage de liquidité récent, niveau
de tension du radar risk-off. Chaque cause est assortie de ce qu'elle implique
pour le trade en cours.

Les mouvements sont horodatés, conservés (20 derniers, `localStorage`) et
affichés dans la carte « ⚡ Mouvements brutaux ». Le chat répond à
« pourquoi ça a bougé ? » et « tu es bien en direct ? ».

## Ajout — contrôle avant entrée et verdict explicite

Version `2026.08.06-l`.

`decideTrade()` construit désormais, avant tout retour, un tableau `checks` de
13 conditions vérifiées une par une : marché ouvert, moins de 2 stops sur la
journée, aucune statistique majeure à moins de 45 min, prix sans excès
(RSI et écart au VWAP), confirmation H1/H4, dollar pas à contre-courant,
avantage statistique, prix pas collé à un niveau contraire, R:R suffisant,
force du signal contre le seuil appris, figure ou alignement des horizons,
timing M5, trade jouable avec le capital.

La liste est jointe à **toutes** les réponses — feu vert comme attente — et
affichée sous le plan, avec pour chaque échec la raison exacte. Au-dessus,
une phrase sans ambiguïté : `✅ VAS-Y — ACHÈTE MAINTENANT · les 13 contrôles
sont au vert` ou `⛔ N'ENTRE PAS ENCORE — N contrôle(s) au rouge`.

Les libellés passent en français explicite : `VAS-Y — ACHÈTE MAINTENANT (BUY)`,
`PRÉPARE-TOI À VENDRE (SELL)`, et la ligne du plan indique `ACHAT (BUY)` /
`VENTE (SELL)` — le mot anglais ne peut plus être lu à l'envers.

### Bug corrigé au passage : verbe figé sur un signal persistant

Un signal actif est reconduit via `dec = { ...dec, action, side, dirUp, sticky }`,
qui réécrit le sens sans réécrire les champs dérivés. Un verbe stocké sur
l'objet serait donc resté sur l'ancien sens : la bannière pouvait annoncer
`ACHÈTE` au-dessus d'un signal `SELL` reconduit — exactement la famille de bug
du premier correctif. Le verbe est maintenant dérivé du plan affiché (`P`) au
moment du rendu, jamais stocké. Couvert par un test de régression.

## Ajout — marchés liés, confluence technique, order blocks

Version `2026.08.06-n`.

### Marchés liés à l'or

`/api/radar` renvoyait déjà cinq marchés (VIX, taux US 10 ans, pétrole WTI,
dollar, Bitcoin) mais un seul — le dollar — entrait dans la décision ; les
quatre autres étaient affichés puis ignorés.

`crossMarket()` les lit tous avec leur relation réelle à l'or et un seuil de
bruit par actif : sous le seuil, l'actif ne pèse rien (sinon cinq micro-
variations s'additionnaient en un biais inexistant). Score borné à ±10,
affiché en tête de la carte radar avec le détail marché par marché, et ajouté
comme 14ᵉ contrôle avant entrée.

### Confluence technique

Les contrôles disent si le trade est *autorisé* ; `confluence()` dit s'il est
*bon*. Treize figures vérifiées une par une dans le sens du trade : order
block, FVG non comblé, balayage de liquidité, trendline, Fibonacci 61,8 %,
structure de marché, empilement des EMA, position vs VWAP, profil de volume,
figure de bougie, divergence RSI, support/résistance d'appui, figure double.

Ces points ne bloquent pas — ils notent la qualité (HAUT VOL ≥ 9, CORRECTE ≥ 6,
FAIBLE en dessous). Un feu vert sous 6/13 affiche un avertissement explicite.

### Order blocks

`orderBlocks()` n'existait pas : la dernière bougie opposée avant une impulsion
qui casse la structure, filtrée des blocs déjà entièrement traversés.

### Bruit géopolitique écarté

Le flux donnait le poids maximal (3) au nucléaire **civil** — réacteurs,
déchets, radio-isotopes médicaux — et comptait des faits divers sportifs comme
tensions géopolitiques. Ces titres saturaient à eux seuls le score de
« géopolitique chaude ». `geoW()` écarte désormais le nucléaire civil, le sport
et les faits divers, et exige qu'un titre nomme une menace réelle (missile,
frappe, guerre, sanctions, blocus, escalade…) pour compter comme chaud.

Mesuré sur le flux réel : **11 titres « chauds » avant, 4 après** — les quatre
restants portant tous sur l'Iran, l'Ukraine ou une offensive russe.
