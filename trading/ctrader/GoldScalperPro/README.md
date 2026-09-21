# Gold Scalper Pro v2 — cBot cTrader (XAUUSD)

Moteur de scalping intraday pour **cTrader Automate** (C#, cAlgo API), pensé pour l'or.
Il n'entre jamais sur un seul indicateur : chaque barre passe dans un pipeline de filtres,
et la taille de position est dérivée du risque, pas d'un lot fixe.

> ⚠️ **À lire avant de lancer ça en réel.** Aucun algo ne « fait que gagner ». Le scalping XAUUSD
> se joue surtout contre le spread, le slippage et le sur-trading. Ce code te donne une structure
> sérieuse et des coupe-circuits ; il ne te donne pas un edge garanti. **Backtest en tick data,
> puis démo plusieurs semaines** avant de risquer un euro.

---

## 1. Installation

**Option A — la plus rapide**
1. cTrader → onglet **Automate** → **New cBot**.
2. Colle tout le contenu de `GoldScalperPro.cs`.
3. **Build** (F6).
4. Ajoute une instance sur un graphique **XAUUSD M1** (ou M5), règle les paramètres, **Start**.

**Option B — projet .NET**
Copie le dossier dans `Documents/cAlgo/Sources/Robots/GoldScalperPro/` (le `.csproj` est fourni),
puis ouvre-le depuis cTrader.

### Calibrage obligatoire au premier lancement
Au démarrage le bot logge :

```
PipSize 0.01 | Digits 2 | live spread 18.0 pips
```

Les courtiers ne définissent pas le pip de l'or pareil (0,01 ou 0,1). **Regarde cette ligne**, puis
règle `Max spread (pips)` un peu au-dessus de ton spread normal (ex. spread habituel 18 → mets 25).
Tous les autres réglages en pips (stop plancher, trailing) suivent automatiquement la même échelle.

---

## 2. Comment il décide

```
 1. GATES       session / rollover / news / spread / volatilité / plafonds journaliers
 2. RÉGIME      ADX + ATR(rapide)/ATR(lent)  ->  Trend | Range | Chaos
 3. SETUP       Trend : rejet de pullback sur EMA, ou cassure de range
                Range : fade de bande de Bollinger (retour à l'intérieur)
 4. SCORE       force de tendance + écartement UT sup + momentum + bougie + coût  -> 0..100
 5. SIZING      % du capital / stop ATR, ajusté par la série, la courbe d'équité et le score
 6. EXÉCUTION   ordre market range avec plafond de slippage
 7. GESTION     échelle de TP (2 partiels + runner), break-even, trailing ATR,
                stop temporel, sortie panique sur explosion de spread, flat en fin de session
 8. PYRAMIDAGE  optionnel : renforts sur position gagnante, à risque réduit
```

### Les 3 régimes
| Régime | Condition | Ce qu'il fait |
|---|---|---|
| **Trend** | ADX ≥ `Trend ADX threshold` | Pullback EMA ou cassure, dans le sens du biais M15 |
| **Range** | ADX ≤ `Range ADX ceiling` | Fade des extrêmes de Bollinger, cible la bande médiane |
| **Chaos** | ATR rapide / ATR lent > `Chaos ratio` | **Ne trade pas** (news, spike) |

### Le score de confluence (0–100)
| Bloc | Points | Mesure |
|---|---|---|
| Force de tendance | 25 | ADX au-dessus du seuil de range |
| Écartement UT sup | 20 | \|EMA rapide − EMA lente\| du M15, normalisé par l'ATR |
| Momentum | 20 | Distance du RSI par rapport à 50 |
| Qualité de bougie | 15 | Corps / ATR |
| Coût d'exécution | 20 | Spread vs budget spread autorisé |

Un trade n'est pris que si `score ≥ Min quality score` (45 par défaut). Si
`Scale risk with quality` est actif, la taille est modulée entre ×0,6 et ×1,4 selon le score.

> Note : en régime Range, le bloc « force de tendance » vaut ~0 par construction — un fade
> plafonne donc autour de 75. C'est voulu : le fade doit être excellent sur les 4 autres axes.

---

## 3. Protections du capital

| Garde-fou | Paramètre | Défaut |
|---|---|---|
| Risque par trade | `Base risk per trade` | 0,5 % |
| Plafond dur de risque | `Risk ceiling` | 1,0 % |
| Perte max journalière | `Daily loss cap` | 3 % → flat + repos jusqu'au lendemain |
| Verrouillage du gain | `Daily profit lock` | 4 % → flat + repos |
| Trades max / jour | `Max trades per day` | 15 |
| Série de pertes | `Max consecutive losses` + `Cooldown` | 3 → pause 45 min |
| Risque après perte / gain | `Risk factor after a loss / win` | ×0,7 / ×1,15 |
| Filtre courbe d'équité | `Equity curve filter` | Réduit le risque (×0,5) quand les résultats du bot passent sous leur moyenne mobile |
| Spread anormal | `Spread spike vs average` | ×2 de la moyenne → pas d'entrée, et sortie si position à peine positive |

---

## 4. Sorties

- **Stop** : `ATR × 1,2`, avec plancher `spread × 2` (jamais de stop noyé dans le spread).
- **TP1** : 40 % de la position à 1,0 R.
- **TP2** : 50 % du reste à 1,8 R.
- **Runner** : break-even à 0,8 R, puis trailing `ATR × 1,0`, TP dur de sécurité à 3 R.
- **Stop temporel** : sortie après 60 barres (1 h en M1) si ça ne va nulle part.
- **Give-back** (off par défaut) : sortie si la position rend X % de son meilleur R.
- **Fin de session** : tout est fermé, pas de position qui traîne pendant le rollover.

---

## 5. Presets de départ

| Paramètre | Prudent | Équilibré (défaut) | Agressif |
|---|---|---|---|
| Base risk per trade | 0,25 % | 0,5 % | 0,8 % |
| Min quality score | 60 | 45 | 35 |
| Session | NewYorkOnly | LondonAndNewYork | LondonAndNewYork |
| Enable range mode | non | oui | oui |
| Max trades per day | 6 | 15 | 25 |
| Daily loss cap | 2 % | 3 % | 4 % |
| Enable pyramiding | non | non | oui (1 renfort) |
| Time stop (barres) | 40 | 60 | 90 |

Le pyramidage suppose `Max open positions` ≥ 1 : les entrées supplémentaires sont traitées comme
des **renforts** (même sens obligatoire, position existante ≥ `Add-on at R`, risque ×0,5).

---

## 6. Méthode de test (ne saute pas ces étapes)

1. **Backtest tick data** — cTrader → Backtesting → *Tick data (accurate)*. En M1 sur l'or, le
   mode « bar data » ment : il ne voit ni le spread variable ni l'ordre high/low intrabar.
2. **Commissions réelles** — renseigne la commission de ton compte dans les paramètres de backtest.
   Un scalpeur rentable brut est souvent mort net.
3. **Période longue** — minimum 12 mois, en incluant des phases de tendance ET de range.
4. **Walk-forward** — optimise sur 6 mois, valide sur les 3 mois suivants *sans retoucher*.
   Si ça ne tient pas hors échantillon, c'est du surapprentissage : les 94 paramètres de ce bot
   permettent d'overfitter n'importe quoi. Optimise 3–5 paramètres à la fois, pas 20.
5. **Démo forward ≥ 4 semaines** sur le serveur live de ton courtier, avec la VPS si tu comptes
   l'utiliser. C'est le seul test qui mesure le slippage réel.
6. **Puis** réel, avec la plus petite taille possible.

Paramètres à optimiser en priorité (les plus sensibles) :
`Stop loss = ATR x`, `Min quality score`, `Trend ADX threshold`, `Max spread`, `TP1/TP2 at R`.

---

## 7. Limites connues

- Pas de calendrier économique : cTrader n'y donne pas accès avec `AccessRights.None`. Le filtre
  news est **manuel** (`News blackout times`, en UTC — pense à mettre 12:30/14:00 pour NFP & CPI,
  et 18:00 les jours de FOMC).
- Le P&L journalier est mesuré en equity depuis le début de journée : un redémarrage du bot en
  cours de journée remet cette référence à zéro.
- Les stats de session (`win rate`, `profit factor`) comptent les fermetures partielles comme
  des trades distincts — c'est la mécanique de cTrader, pas un bug.
- Toutes les heures sont en **UTC** (le robot force `TimeZones.UTC`), pas en heure du courtier.
