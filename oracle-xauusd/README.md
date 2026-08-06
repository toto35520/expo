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
