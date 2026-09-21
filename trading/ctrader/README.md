# cBots cTrader — index

Cinq robots, construits dans cet ordre. **Aucun n'a été validé sur des données historiques.**
Ce tableau dit ce que chacun fait **à la seconde où tu appuies sur Start**.

| Bot | Timeframe | Trade en démarrant ? | Risque par défaut | Coupe-circuit |
|---|---|---|---|---|
| **GoldOrderFlow** v0.5 | M1 | 🔵 **NON** — `Measure only = Oui` | 0,5 % | perte jour 3 % |
| GoldScalperPro | M1 | 🔴 **OUI, immédiatement** | 0,5 % | perte jour 3 %, 15 trades/j |
| GoldRegimeShift | M15 | 🔴 **OUI, immédiatement** | 0,5 % | perte jour 3 %, 6 trades/j |
| GoldBlueClose | M1 | 🔴 **OUI, immédiatement** | 0,01 lot × 3 | **stop panier 2 %**, perte jour 4 % |
| GoldTrendFTF | D1 | 🟡 oui, mais refusera de dimensionner | 1 % | compte trop petit (~7 000 € requis) |

**Rien ne trade tant que tu n'as pas ajouté une instance ET appuyé sur Start.** Compiler ne
trade pas. Ajouter une instance ne trade pas.

---

## Ordre d'utilisation recommandé

### 1. GoldOrderFlow — à lancer maintenant, en mesure

C'est le seul qui ne risque rien par construction. Lance-le sur XAUUSD M1, laisse-le tourner
quelques sessions, et lis le bloc `order flow regression` dans le journal à l'arrêt.

Il te donnera trois chiffres qui décident de la suite : `beta`, `t`, et le niveau d'OFI
nécessaire pour couvrir ton spread. **Ne passe pas `Measure only` à Non avant d'avoir lu ça.**

### 2. Les backtests — la seule étape qui manque

Quatre bots, zéro backtest. Le backtester est dans cTrader, onglet à côté de l'éditeur.

| Bot | Réglages du test |
|---|---|
| GoldRegimeShift | M15, tick data, 12 mois, commissions réelles. Calibrer d'abord la **fréquence** (0,31-0,72 trade/jour) avant de regarder le P&L |
| GoldScalperPro | M1, tick data, 12 mois. Lire `by setup` — `TREND-BREAKOUT` est le suspect principal |
| GoldBlueClose | M1, tick data, 12 mois. Regarder **une seule ligne** : `ONE loss erases N wins` |

Chacun écrit son bloc `expectancy` à la fin avec `Win rate X% | break-even win rate needed Y%`.
Si X < Y, c'est perdant, peu importe l'allure de la courbe.

### 3. Avant de passer un seul bot en réel

- [ ] Backtest tick data 12 mois avec tes commissions
- [ ] Expectancy positive sur 200+ trades
- [ ] Validation hors échantillon sans retoucher les réglages
- [ ] Démo forward ≥ 4 semaines sur le serveur live
- [ ] `Max spread (pips)` calibré sur le spread réel affiché au démarrage
- [ ] Vérifier que le compte est bien celui que tu crois

---

## Ce que la recherche dit de tout ça

Deux études de falsification trouvées en cherchant, et elles cadrent le projet :

**Mesfin (2026), arXiv:2605.04004** — 14 familles de signaux intraday OHLCV sur barres 5 min,
walk-forward strict. **Aucune ne franchit une friction de 2 points.** Les entrées sur pullback
après cassure stoppent 80,7 % du temps ; la continuation d'expansion va significativement dans
le mauvais sens (T = −10,96). La recherche intraday sur l'or y est close :
`D105 — MGC intraday research closed, all approaches exhausted`.

**Darmanin (2026), arXiv:2607.20093** — 5 familles retail contre 3 barrières (edge statistique,
viabilité économique, survie du capital). **4 réfutées** (oscillateurs, volume, calendrier,
chandeliers), 2 indéterminées (tendance, momentum), **0 supportée**.

Ça ne dit pas qu'aucun edge n'existe. Ça dit que les chemins évidents ont été testés et
ne passent pas — et que la barrière n'est ni le levier ni la ruine, mais la conjonction
*edge statistique* + *implémentabilité économique après coûts*.

C'est pourquoi le bot le plus récent commence en mode mesure.
