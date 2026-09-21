# Gold Regime Shift — cBot cTrader

Le seul mécanisme intraday qui a **survécu** à l'étude de falsification de Mesfin (2026),
transposé sur l'or en M15.

---

## 1. D'où ça vient

> Mesfin (2026), *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures:
> A Systematic Falsification Study*, arXiv:2605.04004

L'étude rejette **14 familles** de signaux intraday sur barres 5 minutes (cassures d'opening
range, fades de gap, pics de volume, liquidity grabs, continuation d'expansion…). Aucune ne
passe une friction de 2 points aller-retour.

Ses **deux contrôles positifs**, eux, passent largement :

| Signal | Trades | Net moyen | T-stat | Win rate | Profit factor |
|---|---|---|---|---|---|
| RTH Confluence (ATR-adaptive) | 538 (196 OOS) | +15,77 pts | **5,83** | 61,0 % | — |
| London Session Signal B | 289 | +5,77 pts | **5,15** | 64,7 % | 2,42 |

Les deux partagent **exactement deux propriétés** que tous les signaux rejetés n'avaient pas :

1. **La condition d'entrée est un état de régime et une probabilité de transition**, pas un
   motif de prix sur une bougie.
2. **La position est tenue 12 à 15 barres** (60-75 minutes), pas 1 à 6.

> Interprétation des auteurs : tout motif OHLCV public qui prédit la barre suivante est
> arbitré jusqu'à ce que son edge brut égale le coût du participant marginal. Ce qui échappe
> à ce plafond, ce sont les **transitions d'état structurelles**, pas les formes de bougies.

Ce bot implémente ce mécanisme.

---

## 2. Comment il marche

```
CHAQUE BARRE
  1. 3 features, toutes sans dimension :
       body   = (close - open) / range moyen
       range  = (high - low)   / range moyen
       volume = z-score du volume sur 50 barres

  2. Mélange gaussien (K=3) ajusté par EM sur une fenêtre glissante de 600 barres,
     ré-ajusté toutes les 50 barres. Covariance diagonale, calculs en log.

  3. Les composantes sont triées par moyenne de "body" :
       rang 0  -> BEAR      rang K-1 -> BULL
       celle dont le "range" moyen est le plus grand -> ACTIVE

  4. Matrice de transition de Markov estimée sur les 200 dernières étiquettes.

ENTRÉES
  TRANSITION  : bascule propre BEAR -> BULL (ou l'inverse), sans contamination
                sur les 2 barres précédentes
  CONFLUENCE  : régime ACTIVE + P(ACTIVE -> BULL) >= 0,15 + z-volume >= 0,5
  Exécution   : on arme, puis on attend un repli de 0,5 x ATR depuis la clôture
                du signal (patience : 2 barres). Suivi en interne, aucun ordre
                en attente laissé sur le serveur.

SORTIES
  hold        : 4 barres (= 60 min en M15) — c'est LA sortie, pas un filet
  stop        : 1,5 x ATR
  TP          : 2,0 R
  flip        : régime passé contre la position
  break-even  : à 1,0 R
```

L'initialisation de l'EM est **déterministe** (fenêtre triée, découpée en quantiles) : même
données, même modèle. Une graine aléatoire rendrait les backtests irreproductibles.

---

## 3. ⚠️ Ce que ce bot n'est pas

Lis ça avant de lui faire confiance.

- **Les contrôles positifs ont été mesurés sur MNQ (futures Nasdaq), pas sur l'or.** La même
  étude a clos la recherche intraday sur l'or par `D105 — MGC intraday research closed, all
  approaches exhausted`. Appliquer ce mécanisme à l'or est un **transfert d'hypothèse vers un
  instrument où les auteurs n'ont rien trouvé**. Ce n'est pas une réplication.
- **Le jeu de features du GMM n'est pas publié.** Les auteurs présentent ces deux signaux
  comme des contrôles issus d'un autre programme de recherche, sans détailler leurs entrées.
  Les 3 features ci-dessus sont **mon choix**, pas le leur.
- Les étiquettes d'un EM sont arbitraires : la numérotation « Regime 0/1/2 » du papier ne se
  transfère pas et n'est pas supposée ici. L'identité vient des paramètres ajustés.

**Le mécanisme a des preuves. Cette instanciation du mécanisme n'en a aucune.**

---

## 4. Installation et réglages

1. cTrader → Automate → New cBot → `GoldRegimeShift`, coller, Build.
2. Instance sur **XAUUSD M15** (le bot prévient si tu es ailleurs).
3. Régler `Max spread (pips)` d'après le spread affiché au démarrage.

| Timeframe | `Hold (bars)` | Détention réelle |
|---|---|---|
| **M15** (recommandé) | 4 | 60 min — structure du London Signal B |
| M5 | 13 | 65 min — structure du RTH Confluence |
| M1 | — | hors de la zone validée, ne le fais pas |

---

## 5. Ordre de test

1. **Backtest tick data, 12 mois, commissions réelles**, M15, réglages par défaut.
2. Lire le bloc `expectancy` : `Win rate X% | break-even win rate needed Y%`.
   Si X < Y, c'est perdant, peu importe le reste.
3. Comparer les deux modes séparément (`Signal mode` = `RegimeTransition`, puis
   `Confluence`). Le papier valide deux signaux distincts ; rien ne dit que les deux
   transfèrent sur l'or.
4. Ne walk-forwarder que **3 paramètres** : `Fit window`, `Hold (bars)`, `Stop = ATR x`.
   Le reste vient du papier ou de la structure du modèle.
5. Si l'expectancy est négative sur les deux modes après 200+ trades : le transfert vers
   l'or a échoué, et c'est le résultat le plus probable d'après l'étude elle-même.
   C'est une information, pas un échec — elle t'évite de perdre de l'argent en réel.
