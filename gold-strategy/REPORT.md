# XAUUSD — recherche systématique de stratégies

Données : 357 968 bougies M5, 25/08/2021 → 11/09/2026 (1 303 séances).
Or : 1 790 $ → 4 348 $ (**+143 %**), plus haut à 5 588 $.

Tout est mesuré **en unités d'ATR**, pas en dollars. C'est indispensable ici : l'ATR M5
est passé de 1,08 $ (2021) à 6,49 $ (2026), l'ATR journalier de ~24 $ à ~105 $. Un
backtest en dollars bruts attribuerait tout le P&L à 2025-2026 et ne mesurerait que
la volatilité, pas une compétence.

**Coûts** : 0,30 $/oz aller-retour (spread + slippage) appliqués à chaque trade, avec
test de sensibilité jusqu'à 1,00 $.

## Le benchmark à battre

| | CAGR | Vol | Sharpe | DD max |
|---|---|---|---|---|
| Buy & hold or | +19,2 % | 18,2 % | **1,03** | −26,6 % |

La barre est haute : la période couvre un marché haussier historique. Toute stratégie
long-only va paraître brillante pour de mauvaises raisons.

---

## Ce qui NE marche pas (testé, rejeté)

### Breakouts — 27 configurations, aucune ne passe

| Stratégie | n | Espérance | Sharpe |
|---|---|---|---|
| ORB Londres 02-03 → 11:00 | 1 298 | **−0,101 R** | −1,27 |
| ORB Londres 03-04 → 11:00 | 1 296 | −0,039 R | −0,49 |
| ORB New York 09:30-10:30 | 1 131 | +0,022 R | +0,48 |
| Asian range 19:00-00:00 | 1 183 | −0,010 R | −0,19 |
| Asian range 19:00-02:00 | 1 229 | +0,011 R | +0,17 |
| Silver Bullet ICT 10-11 NY | 1 132 | +0,001 R | +0,02 |

Le *Asian range breakout* et le *London ORB*, omniprésents sur les forums et YouTube,
n'ont **aucun edge** sur cet échantillon.

**Et le fade ne marche pas non plus.** L'ORB Londres étant nettement négatif, la
tentation est de l'inverser. Testé : espérance **−0,137 R**, t = −3,56. Les deux sens
perdent. Ce n'était donc pas un edge inversable, seulement du coût et du bruit dans une
géométrie stop/target défavorable. C'est exactement le piège que le résultat négatif
initial tendait.

### Indicateurs — le fade perd systématiquement

| Famille | Meilleur Sharpe | Pire Sharpe |
|---|---|---|
| Bollinger FADE | −0,24 (H4) | −1,61 (M15) |
| RSI(2) 5/95 fade | −0,47 (D1) | −2,56 (M15) |
| MACD | +0,58 (D1) | −1,94 (M15) |
| RSI(2) Connors long-only | +0,59 (D1) | −0,66 (M15) |

**L'or tend, il ne revient pas.** Toutes les stratégies de retour à la moyenne perdent,
et d'autant plus vite que l'unité de temps est basse (les frais dominent en M15).

Les croisements d'EMA *long-only* affichent des Sharpe de 1,25 à 1,65 — mais leurs
versions *long + short* tombent à 0,27-1,08. Quand retirer le côté short détruit la
performance, l'edge n'est pas dans le timing : c'est du beta long déguisé.

### Anomalies de calendrier et de microstructure — toutes nulles

| Hypothèse testée | Résultat |
|---|---|
| Momentum intraday (Gao-Han-Li-Zhou) | corr ≈ 0,00 — ne fonctionne pas sur l'or |
| Fix PM de Londres (10:00 NY) | t = +0,39 à +1,51 |
| Gap du week-end (continuation ou fade) | t = ±1,23 (n = 223) |
| Turn-of-month | t = +1,74 — *moins* que le reste du mois (+2,36) |
| Jour NFP (1er vendredi) | t = +1,30 (n = 59) |
| Autocorrélation quotidienne (lags 1→20) | tous |t| < 1,5 |

Aucune mémoire exploitable à l'échelle quotidienne : le trend-following pur n'a pas
de fondement statistique sur l'or, il ne fait que suivre la hausse.

---

## Stratégie A — dérive de réouverture asiatique

### Découverte

Balayage heure par heure du P&L intra-journalier (open→close, sans gap) :

| Heure NY | Moyenne (ATR) | t | Part de la dérive du jour |
|---|---|---|---|
| **18:00** | **+0,0251** | **+7,42** | **42 % en 1 heure sur 23** |
| 19:00 | +0,0044 | +1,74 | |
| toutes les autres | < 0,005 | |t| < 1,5 | |

**Validation contre le data-mining** : sur 44 fenêtres de 2 h balayées sur les 24 heures,
les **6 meilleures sont toutes situées entre 18:00 et 22:30 NY**. Aucune autre plage
horaire n'approche. Ce n'est pas un pic tiré d'une grille, c'est la seule anomalie
horaire de ce jeu de données.

18:00 NY = la réouverture après la coupure quotidienne de 17:00-18:00, donc le début de
la session asiatique.

### Le test qui compte : est-ce un artefact ?

La littérature ([QuantPedia sur GDX](https://quantpedia.com/dangers-of-relying-on-ohlc-prices-the-case-of-overnight-drift-in-gdx-etf/))
avertit que ce type de dérive vit souvent dans le **premier print de réouverture**, là
où le spread est le plus large et où aucun ordre ne peut être servi au prix affiché.

Décalage de l'entrée, minute par minute :

| Entrée | t |
|---|---|
| open 18:00 (prix affiché) | **+7,45** |
| close 18:00 = ordre marché à 18:05 | **+3,32** |
| open 18:15 | +2,12 |

**63 % de l'edge brut disparaît en 5 minutes.** Tout ce qui suit utilise donc l'entrée
à 18:05 (clôture de la bougie 18:00), exécutable.

### Règles

```
Entrée  : achat au marché à 18:05 NY (clôture de la bougie M5 de 18:00)
Sortie  : clôture de la position à 20:55 NY
Filtre 1: ne pas trader la réouverture du dimanche soir
Filtre 2: clôture quotidienne précédente > SMA(200) quotidienne
```

Le filtre 1 n'est pas de l'optimisation : la séance étiquetée « lundi » ouvre le
**dimanche** à 18:00 NY, après 48 h de fermeture. Microstructure différente, dérive
absente (t = −0,13 contre +2,49 à +5,47 pour les autres jours).

Le filtre 2 est robuste à sa période — ce n'est pas 200 qui est magique :

| Filtre | SMA50 | SMA100 | SMA150 | SMA200 | SMA250 | SMA300 | aucun |
|---|---|---|---|---|---|---|---|
| Sharpe net | 1,80 | 2,04 | 2,62 | 2,36 | 2,52 | 2,53 | 1,64 |

### Résultats (frais 0,30 $ inclus)

| | |
|---|---|
| Trades | 694 (~165/an) |
| Net $/trade | **+1,755** |
| Moyenne R (net) | +0,0239 ATR, **t = +3,92** |
| Taux de réussite | 53,6 % |
| Profit factor | 1,672 |
| Sharpe | **2,36** |
| Exposition | 5,7 % du temps |

**Walk-forward** — sortie choisie uniquement sur 2021-2024, appliquée en aveugle ensuite :

| Sortie | t in-sample | t out-of-sample | Net $/trade OOS |
|---|---|---|---|
| 19:55 | +1,74 | +2,89 | +1,94 |
| **20:55** (retenue) | **+1,85** | **+3,46** | **+3,06** |
| 21:55 | +0,44 | +2,85 | +2,65 |

**Bootstrap** (20 000 rééchantillonnages) : IC 95 % = [+0,0120 ; +0,0358], P(moyenne ≤ 0) = **0,00 %**.
Bootstrap par blocs de 20 (respecte l'autocorrélation) : P = **0,02 %**.

**Stress sur le spread** : rentable jusqu'à ~1,00 $ de coût aller-retour.

| Coût | 0,20 $ | 0,30 $ | 0,50 $ | 0,80 $ | 1,00 $ |
|---|---|---|---|---|---|
| Sharpe | 2,63 | 2,36 | 1,81 | 0,99 | 0,45 |

### La limite à comprendre absolument

L'edge est **stable en unités d'ATR** (~0,024 ATR toutes les années) mais le coût est
**fixe en dollars**. La rentabilité dépend donc du niveau de volatilité :

| Année | ATR journalier | Net $/trade |
|---|---|---|
| 2022 | 25 $ | −0,93 |
| 2023 | 24 $ | +0,48 |
| 2024 | 33 $ | +0,45 |
| 2025 | 58 $ | +1,84 |
| 2026 | 127 $ | +7,23 |

Seuil de rentabilité : **ATR > ~15-20 $**. Aujourd'hui l'ATR est à ~105 $, très
confortable. En 2022 la stratégie ne gagnait rien net de frais.

C'est aussi ce que dit le walk-forward : in-sample (2021-2024) net de frais ≈ **0 $**,
out-of-sample (2024-2026) fortement positif. C'est l'inverse du profil d'un
sur-apprentissage — mais cela signifie que la performance suit le régime de volatilité.

---

## Stratégie B — tendance vol-ciblée (et ce qu'elle n'est pas)

Aucune seconde anomalie indépendante n'existe dans ces données. La meilleure
« stratégie 2 » disponible est un filtre de tendance à volatilité ciblée — utile, mais
**ce n'est pas de l'alpha** :

```
Position: long si EMA(21) > EMA(55) en quotidien, sinon flat
Taille  : ajustée pour viser 10 % de volatilité annualisée (levier plafonné à 3)
```

| | CAGR | Vol | Sharpe | DD max |
|---|---|---|---|---|
| EMA 21/55 vol-ciblée | +14,3 % | 9,4 % | 1,43 | −8,7 % |
| Buy & hold vol-ciblé | +14,7 % | 11,1 % | 1,26 | −16,4 % |

Le filtre **divise le drawdown par deux**. L'écart de Sharpe (1,43 vs 1,26) repose sur
17 trades en 5 ans — statistiquement, c'est du bruit. À présenter comme un contrôle du
risque, pas comme un générateur de rendement.

---

## Portefeuille combiné

Corrélation A ↔ B : **+0,17**. Corrélation A ↔ or : **+0,23**. A n'est exposée que
5,7 % du temps, B sert de socle.

| | CAGR | Vol | Sharpe | DD max |
|---|---|---|---|---|
| A seule | +13,4 % | 7,3 % | 1,71 | −6,2 % |
| B seule | +14,3 % | 9,4 % | 1,43 | −8,7 % |
| **Portefeuille 50/50** | **+14,1 %** | **6,4 %** | **2,03** | **−5,1 %** |
| Buy & hold | +19,2 % | 18,2 % | 1,03 | −26,6 % |

Le buy & hold finit plus haut en absolu — l'or a fait +143 %. Il y arrive avec trois
fois la volatilité et cinq fois le drawdown. À risque égal, le portefeuille domine.

---

## Seconde passe — 10 hypothèses de plus, et le test de data-snooping

### Correction d'un défaut de la première passe

Le balayage initial de 44 fenêtres contenait une erreur d'indexation : les fenêtres
traversant la frontière de séance (ex. « 16:00→18:00, t = −1,91 ») étaient lues à
l'envers, 18:00 étant le *début* de la séance et 16:00 la *fin*. Cette ligne mesurait
l'inverse du rendement du jour. Strategy A n'était pas touchée (18:00→20:55 est
correctement ordonné), mais le balayage a été refait.

**Balayage exhaustif corrigé** : 555 fenêtres (grille 30 min, durées 1 h à 8 h),
contrôle de Benjamini-Hochberg à 5 %. **7 survivent — toutes commencent à 18:00.**
Aucune fenêtre négative au-delà de t = −2,5 : il n'existe pas d'edge short horaire.

### Ce qui a encore été testé et rejeté

| Hypothèse | Résultat |
|---|---|
| 15 features quotidiennes (momentum, volume, NR7, inside day, largeur BB, position de clôture, streaks, jour du mois) | **aucune ne survit au FDR** |
| Pivots floor-trader (P, R1/R2, S1/S2 — fade et breakout) | 10 variantes, toutes \|t\| < 2,1 |
| Chandeliers (engulfing, marteau, doji, 3 soldats) | rien (D1 doji t = 2,45, ne survit pas au FDR) |
| Ichimoku, Parabolic SAR, Heikin-Ashi, ADX+EMA | long-only : Sharpe 0,24-1,09, sous le buy & hold |
| Filtre volume sur Strategy A | **rejeté** — non monotone, et le signe s'inverse en walk-forward |
| Rebond post-session US sur Strategy A | **rejeté** — écart nul in-sample, n'apparaît qu'en OOS |
| 10 variantes de sortie (stops, targets, trailing, durées) | **toutes dégradent** la version simple |

### Deux résultats négatifs qui valent d'être connus

**Le « squeeze » de volatilité ne prédit pas d'expansion.** C'est l'inverse :

| État | Amplitude du mouvement le lendemain |
|---|---|
| ATR5/ATR20 < 0,8 (comprimé) | **−12,2 %** vs la base |
| ATR5/ATR20 > 1,2 (dilaté) | **+25,8 %** vs la base |
| Largeur BB dans les 20 % bas | −1,0 % |
| Jour NR7 | +0,3 % |

La volatilité s'auto-entretient, elle n'alterne pas. Le setup « compression → explosion »
(NR7, Bollinger squeeze), omniprésent en formation, n'a aucun fondement ici.

**Le fade du VWAP perd de façon fiable.** Sur 37 systèmes testés dans cette passe,
3 survivent au FDR — et **deux sont des perdants** :

| Système | t | Sharpe |
|---|---|---|
| Fade du VWAP à 2σ | **−4,49** | −2,00 |
| Retour au VWAP (>1,5σ) | **−3,52** | −1,55 |
| Ichimoku H4 long-only | +3,40 | +0,60 |

Le résultat le plus significatif de tout le lot est une stratégie qui perd de l'argent.

### Le test qui compte : White's Reality Check

Après ~730 hypothèses testées dans cette étude, à \|t\| > 2 on attend **~33 faux positifs
par pur hasard**. Le bootstrap de la première passe (P(moyenne ≤ 0) = 0,00 %) testait une
hypothèse *unique* — il ignorait la recherche. Il fallait corriger.

Méthode : imposer l'hypothèse nulle (centrage), rééchantillonner les jours par blocs de 10
(ce qui préserve la corrélation entre fenêtres qui se chevauchent), et comparer le
\|t\| observé à la distribution du **maximum** sous la nulle.

| Périmètre de recherche | \|t\| observé | p ajusté | Verdict |
|---|---|---|---|
| 555 fenêtres, brut de frais | 3,52 | **0,064** | **ne passe pas** |
| 1 665 hypothèses (fenêtres × filtres), net de frais | 3,95 | **0,036** | passe, de justesse |

Le signal horaire **brut** ne survit donc pas seul. C'est la règle filtrée et nette de
frais qui passe, à p = 0,036 — significatif, mais loin d'être écrasant.

### Ce qui soutient quand même l'edge

**La largeur.** Un pic de bruit serait isolé ; ici l'effet est un bloc contigu :

| Heure de départ NY | Fenêtres | % avec t > 0 | t moyen |
|---|---|---|---|
| **18:00** | 30 | **100 %** | **+2,56** |
| **19:00** | 30 | **100 %** | **+1,32** |
| 20:00 | 30 | 80 % | +0,41 |
| *toutes les autres* | 27 à 30 | 0 à 73 % | **négatif** |

Toutes les sorties possibles fonctionnent entre 18:00 et 19:00, entourées d'un désert.

**La littérature.** L'anomalie overnight est documentée indépendamment de ce jeu de
données, sur d'autres classes d'actifs (Haghani, Ragulin & Dewey). Si on la traite comme
une hypothèse *a priori* issue de la littérature plutôt que comme une découverte issue du
balayage, la correction de data-snooping ne s'applique pas et le p-value pertinent est
celui de l'hypothèse unique (< 0,001). Les deux lectures sont défendables ; la vérité est
entre les deux.

### Piège de méthode à connaître

Soustraire un coût **fixe** à toutes les fenêtres crée de faux signaux négatifs. La
fenêtre la plus « significative » du balayage net (23:30→00:30, t = −4,54) a un t **brut
de −0,24** : zéro. Son écart-type intraday est simplement le plus petit de la journée
(0,078 contre 0,18-0,22 à 18:00), donc les frais y pèsent le plus lourd en t. La shorter
perdrait aussi. Ne jamais lire un t net sans regarder le t brut.

---

## Limites — à lire avant de risquer un euro

0. **Le p-value ajusté du data-snooping est 0,036**, pas 0,000. Après ~730 hypothèses
   testées, l'edge passe le test de White de justesse. Ce n'est pas un résultat écrasant.
1. **Un seul régime.** 5 ans, tous dans un marché haussier historique. Aucun test en
   marché baissier durable. Le filtre SMA200 et le biais long ne sont pas validés à la
   baisse.
2. **A est long-only.** Sa justification économique (prime de risque overnight, demande
   physique asiatique) prédit un affaiblissement, voire une inversion, en marché baissier.
3. **L'anomalie se dégrade peut-être.** La Fed de New York a publié en juillet 2026
   [*The Disappearing Overnight Drift*](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/).
   2026 est effectivement l'année la plus faible de l'échantillon pour le signal brut
   (t = 1,95 contre 4,44 en 2023).
4. **Les frais sont supposés, pas mesurés.** Le flux ne contient pas de spread. À 18:05 NY
   la liquidité est mince : vérifier le spread réel de votre broker à cette heure précise
   avant toute chose. C'est le paramètre n°1.
5. **Un seul flux, un seul broker.** L'heure exacte de la coupure quotidienne varie selon
   les brokers — la règle « 18:00 NY » doit être recalée sur votre flux.
6. **Pas de filtre événementiel** (FOMC, CPI, NFP).

## Reproduire

```bash
python3 strategy.py chemin/vers/xauusd_m5.csv
```

Le fichier `equity_curves.html` contient les courbes d'équité comparées.

## Sources consultées

- [Night Moves: Is the Overnight Drift the Grandmother of All Market Anomalies?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4139328) — Haghani, Ragulin, Dewey
- [The Disappearing Overnight Drift](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/) — Liberty Street Economics, Fed de New York
- [Dangers of Relying on OHLC Prices — Overnight Drift in GDX](https://quantpedia.com/dangers-of-relying-on-ohlc-prices-the-case-of-overnight-drift-in-gdx-etf/) — QuantPedia
- [The "night effect" of intraday trading: Chinese gold and silver futures](https://www.sciencedirect.com/science/article/abs/pii/S1044028325000110) — ScienceDirect
- [Asian Range Breakout Strategy: Rules, Timing & Tracked Results](https://www.breakoutalerts.io/blog/asian-range-breakout-strategy) — Breakout Alerts
- [XAUUSD Trading Strategies: 3 Backtested Approaches](https://quant-signals.com/xauusd-trading-strategies/) — Quant Signals
- [Gold Trading Strategies 2026: Best XAU/USD Strategies](https://www.litefinance.org/blog/for-investors/gold-trading/gold-trading-strategies/) — LiteFinance
- [Best Time to Trade Gold: XAU/USD Volatility by Session](https://acy.com/en/market-news/education/best-time-trade-gold-xauusd-sessions-news-091755/) — ACY
