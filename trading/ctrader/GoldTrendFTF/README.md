# Gold Trend — Forecast-to-Fill (cBot cTrader)

Implémentation cTrader d'une stratégie **or, en données journalières**, documentée et
validée en walk-forward dans un papier public. Ce n'est **pas** un scalpeur — et c'est
exactement le sujet.

---

## 1. Pourquoi ce bot existe

En cherchant « un bot qui gagne », deux papiers ressortent. Ils disent des choses opposées,
et les deux comptent.

### 1.1 La mauvaise nouvelle — le scalping OHLCV intraday ne passe pas les coûts

> Mesfin (2026), *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures:
> A Systematic Falsification Study*, arXiv:2605.04004

14 familles de signaux intraday testées sur 947 jours de barres 5 minutes, en walk-forward
strict, avec 5 critères fixés à l'avance (T ≥ 2,0 hors échantillon, ≥ 30 trades, rendement
net positif après friction, stabilité pluriannuelle, test de permutation).

**Aucun signal ne passe.** Le plafond d'edge brut mesuré est de 0,07 à 1,50 point — en
dessous du coût de friction de 2 points.

Résultats qui touchent directement un bot de type « Gold Scalper » :

| Signal testé | Résultat |
|---|---|
| Entrée sur pullback après cassure | **80,7 % de stop-out**, net −4,44 pts. « Une grande partie des cassures apparentes échouent et se retournent, ce qui rend les entrées sur pullback systématiquement fausses. » |
| Continuation après bougie d'expansion | **T = −10,96** — la direction de continuation est *activement fausse*. « Le mouvement est entièrement contenu dans la bougie d'expansion. Au moment où le signal de clôture se déclenche, le move est épuisé. » |
| Momentum sur pic de volume | Nul précis (T = +0,07 sur 2 119 trades) |
| Liquidity grab / retournement | Négatif **dans les deux sens** (T = −14,12 et −13,24) |
| Gap fill fade | Échec à toutes les heures d'entrée |
| **Or (MGC), toutes configs intraday** | `D105 — MGC intraday research closed, all approaches exhausted` |

Ce qui **a** marché dans la même étude (contrôles positifs, T = 5,83 et 5,15) partage un
seul trait : **une détention de 12 à 15 barres (60-75 min)** au lieu de 1 à 6, et une
classification de régime par GMM plutôt qu'un motif de prix à une barre.

> Interprétation des auteurs : sur un instrument très liquide, tout motif OHLCV public qui
> prédit la barre suivante est arbitré jusqu'à ce que son edge brut égale le coût du
> participant marginal. Pour du retail, cet équilibre est à 1-2 points sur des barres 5 min.

### 1.2 La bonne nouvelle — un edge documenté sur l'or, en journalier

> Singha, Aguilera-Toste & Lahiri (2025), *Forecast-to-Fill: Benchmark-Neutral Alpha and
> Billion-Dollar Capacity in Gold Futures (2015-2025)*, arXiv:2511.08571

Futures or CME, barres journalières, walk-forward glissant 10 ans d'entraînement → 6 mois
de test, 2 793 jours. Hors échantillon, net de 0,7 bps de coût linéaire et d'un terme
d'impact en racine carrée :

| Mesure | Valeur publiée |
|---|---|
| Sharpe | 2,88 (IC bootstrap [2,49 ; 3,27]) |
| Drawdown max | 0,52 % |
| Rendement annuel réalisé | **2,62 %** à une volatilité réalisée de 0,91 % |
| β vs or spot | 0,03 (neutre au marché) |
| Jours à plat | ~58 % |
| Test SPA | p < 0,001 |

**Lis bien la ligne « rendement réalisé ».** Le « 43 % de CAGR » du résumé est ce 2,62 %
remis à l'échelle du budget de volatilité de 15 % — c'est une affirmation de levier
(×16), pas un résultat mesuré. À prendre comme tel.

**Réserves honnêtes** : preprint arXiv, pas de peer review. Un seul actif. Un Sharpe de
2,88 est très au-dessus de ce que produit le trend following classique (0,5 à 1,0). Le
coût de 0,7 bps est institutionnel. La méthodologie décrite (gel des paramètres avant
chaque tranche, bootstrap par blocs, test SPA, tests de robustesse au retard et à
l'inversion du signal) est en revanche rigoureuse.

---

## 2. La stratégie

Tout est en **journalier**, sur le prix de clôture.

```
1. y = log(close),  lissé par une EMA        -> y~
2. slope = y~(t) - y~(t-1)                   -> intensité de tendance
3. z = (slope - moyenne) / écart-type         (fenêtre glissante)
4. p_trend = (clip(z, -3, 3) + 3) / 6        -> [0, 1]
5. m = 1 si close(t) > close(t-50), sinon 0  -> confirmation directionnelle
6. p_bull = 0.6 * p_trend + 0.4 * m

ENTRÉE   long si p_bull >= 0.52  ET  slope > 0
SORTIE   stop dur    : entrée - 2.0 x ATR(14)
         trailing    : plus haut atteint - 1.5 x ATR(14)
         timeout     : 30 jours
         dé-risquage : p_bear > 0.50 -> on ferme
TAILLE   ciblage de volatilité 15 % annualisée, levier plafonné à 2.0,
         pondéré par la confiance, puis Kelly fractionnaire 0.40
```

### Ce qui vient du papier, et ce qui n'en vient pas

| Paramètre | Source |
|---|---|
| K = 50, ω = 0,6, seuil 0,52, stop 2×ATR, trail 1,5×ATR, timeout 30 j, dé-risquage 0,5, vol cible 15 %, levier 2,0, Kelly 0,40 | **Verbatim du papier** |
| **Constante de lissage de l'EMA** | **Pas dans le papier** — cherchée sur une grille de 64 configs, valeur retenue non publiée. Défaut ici : 20 jours. **C'est le paramètre à walk-forwarder en premier.** |

### Adaptations retail assumées

- Le papier **gèle** les statistiques d'entraînement avant chaque tranche hors échantillon.
  Un bot live ne peut pas : la moyenne et l'écart-type de la pente sont calculés sur une
  **fenêtre glissante**.
- Le papier trade des futures continus avec P&L de roulement. Un CFD n'a pas de roulement
  mais paie du financement overnight, **non modélisé ici** — sur des positions tenues
  jusqu'à 30 jours, ce coût n'est pas négligeable, vérifie le swap de ton courtier.
- Le papier est **long seulement**. Le côté short existe ici en option, non validé.

---

## 3. ⚠️ Taille de compte minimum

Un stop de 2 × ATR(14) **journalier** sur l'or est très large. Sur XAUUSD chez un courtier
dont le lot minimum est 0,01 (= 1 once) :

| ATR journalier | Stop | Risque du plus petit lot possible | Compte nécessaire pour risquer 1 % |
|---|---|---|---|
| 40 $ | 800 pips | 68 € | **6 800 €** |
| 50 $ | 1 000 pips | 85 € | **8 500 €** |
| 60 $ | 1 200 pips | 102 € | **10 200 €** |

Sur un compte de **910 €**, la plus petite position possible risque déjà **7 à 11 %** de
l'equity. Aucun réglage ne corrige ça — c'est le lot minimum du courtier qui contraint.

En mode `VolatilityTarget`, c'est encore plus net : au levier maximum de 2,0 le papier
demanderait **0,49 once**, sous le minimum de 1 once. La stratégie est littéralement
intradable sous ~1 850 € même en forçant le levier.

**Le bot vérifie ça au démarrage et te l'écrit dans le journal.** Il refuse les trades dont
la taille calculée tombe sous le minimum plutôt que de prendre une position surdimensionnée.

---

## 4. Installation

1. cTrader → Automate → New cBot → nommer `GoldTrendFTF`.
2. Coller `GoldTrendFTF.cs`, Build (F6).
3. Instance sur **XAUUSD, timeframe D1** (le bot prévient si ce n'est pas le cas).
4. Lire le bloc de démarrage dans le journal — en particulier la ligne de taille de compte.

## 5. Avant de l'utiliser

1. Backteste sur **au moins 10 ans** de données journalières. C'est peu de trades par an :
   il faut de l'historique pour que ça veuille dire quelque chose.
2. Walk-forward sur la **constante d'EMA** uniquement, en laissant tout le reste figé aux
   valeurs du papier. Si tu optimises les 12 paramètres, tu refais de l'overfitting.
3. Vérifie le **coût de financement overnight** de ton courtier sur l'or — sur des positions
   de 30 jours, c'est un poste réel que le papier (qui trade des futures) n'a pas.
4. Compare à un simple *buy and hold* de l'or sur la même période. Le papier revendique
   β = 0,03 ; si ta version se contente de suivre l'or, l'edge revendiqué n'est pas répliqué.
