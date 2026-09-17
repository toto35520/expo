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

## Limites — à lire avant de risquer un euro

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
