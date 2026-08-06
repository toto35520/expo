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
