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

À la première barre exploitable, le bot écrit un bloc **CALIBRATION** dans le journal :

```
--- CALIBRATION (XAUUSD) ---
1 pip = 0.1 in price | digits 2 | spread now 0.9 pips (avg 0.9)
ATR(14) = 14.2 pips -> stop 17.0 pips | TP1 17.0 | TP2 30.7
'Max spread (pips)' is set to 5.0. Suggested for this broker: 3
Risk 0.50% of 910.16 EUR = 4.55 -> 3 units (0.03 lots), broker minimum 1 units
Session window is UTC. Server time now: 17:20 UTC, in session: False
----------------------------
```

Les courtiers ne définissent pas le pip de l'or pareil (0,01 ou 0,1) : sur un broker à
`1 pip = 0.1`, un spread de 0,9 pip vaut 0,09 $ ; sur un broker à `1 pip = 0.01`, le même
spread s'affiche 9 pips. **Règle `Max spread (pips)` sur la valeur suggérée**, tout le reste
(stop plancher, trailing, TP) suit automatiquement la même échelle.

Le défaut est volontairement bas (5) : en cas de mauvaise échelle, le bot refuse de trader
plutôt que d'entrer dans un spread qui mange le R. Si le dashboard affiche
`spread 18.0p > 5.0p`, ce n'est pas un bug — c'est ce filtre, et le bloc CALIBRATION te
donne la valeur à mettre.

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

## 7. Compatibilité cTrader

Le code cible cTrader **4.x / 5.x** et compile sans warning sur ces versions.
Sur un cTrader plus ancien, deux retours en arrière possibles :

| Erreur de build | Correctif |
|---|---|
| `'RobotAttribute' does not contain a definition for 'AddIndicators'` | Dans `[Robot(...)]`, supprimer `, AddIndicators = true` |
| `No overload for 'ModifyPosition' takes 4 arguments` | Ligne ~1089, supprimer `, ProtectionType.Absolute` |

## 8. Le dashboard

Le panneau en haut à **droite** du graphique donne l'état en direct :

| Ligne | Ce que ça veut dire |
|---|---|
| `regime` | Trend / Range / Chaos / Unknown — le régime détecté à la dernière barre |
| `status` | **la raison exacte pour laquelle il ne trade pas** (`outside session`, `spread ... > ...`, `quality 38 < 45`, `cooldown active`...) ou `ready` |
| `score` | dernier score de confluence calculé, face au minimum requis |
| `spread` | spread instantané et sa moyenne glissante |
| `open` / `today` | positions ouvertes, et compteur de trades du jour |
| `day P/L` | variation de l'equity depuis le début de journée (sert aux coupe-circuits) |

Si rien ne se passe, la ligne `status` répond à la question. `outside session` = normal hors
07:00–17:00 UTC par défaut : le bot reprend tout seul à l'ouverture de la fenêtre.

## 9. La boucle d'amélioration

C'est ici que les performances se gagnent — pas en ajoutant des indicateurs, mais en mesurant
puis en coupant.

### Le rapport de fin de session

Quand tu arrêtes le bot (ou à la fin d'un backtest), il écrit ceci dans le journal :

```
=== session summary ===
Trades 214 | wins 118 (55.1%)
Profit factor 1.34 | average 0.11R | max drawdown 63.20 EUR
Entry slippage 0.38 pips on average over 214 market fills
--- by setup ---
TREND-PULLBACK    118 trades | win  59% | net    184.50 | PF 1.62
TREND-BREAKOUT     61 trades | win  48% | net    -22.10 | PF 0.92
RANGE-FADE         35 trades | win  57% | net     41.30 | PF 1.28
--- by hour (UTC) ---
07h                42 trades | win  62% | net     96.40 | PF 1.88
08h                39 trades | win  51% | net      8.20 | PF 1.06
13h                48 trades | win  58% | net     71.10 | PF 1.51
16h                31 trades | win  39% | net    -48.90 | PF 0.71
```

### Ce que tu en fais

1. **Un setup sous PF 1,0 sur ≥ 40 trades** → coupe-le : `Enable trend mode`,
   `Enable range mode`, `Breakout entries`, `Pullback entries` sont là pour ça.
   Dans l'exemple ci-dessus, désactiver `Breakout entries` remonte le PF global.
2. **Une heure sous PF 1,0 sur ≥ 30 trades** → sors-la avec `Trading hours UTC`.
   Ici : `7-15` au lieu de tout, et l'heure 16 disparaît.
3. **Slippage moyen > 1 pip** → passe `Entry execution` en `LimitRetrace`.
4. Re-backteste. Si le PF monte **et** que ça tient hors échantillon, tu gardes.
   S'il monte seulement en échantillon, tu viens d'overfitter : reviens en arrière.

Ne coupe jamais sur moins de 30 trades dans un bucket — c'est du bruit, pas un signal.

### Entrée à la limite (`Entry execution = LimitRetrace`)

Au lieu de payer le spread pour chasser la clôture de la bougie de signal, le bot pose un
**ordre limite au niveau sur lequel le setup a été construit** (l'EMA de pullback, le niveau
cassé, la bande de Bollinger) et attend que le prix revienne :

| | Market | LimitRetrace |
|---|---|---|
| Taux de remplissage | 100 % | ~40-60 % |
| Prix d'entrée | clôture + spread | le niveau, souvent 2-5 pips mieux |
| Effet sur un stop de 17 pips | — | **10 à 30 % de R gagné par trade rempli** |

C'est le plus gros levier d'exécution du bot, mais il change la nature de la stratégie
(moins de trades, meilleurs prix) : **backteste les deux modes séparément**, ne suppose pas.
`Limit offset` décale l'ordre vers le prix actuel (remplit plus souvent, un peu moins bien),
`Limit expiry` annule l'ordre après N barres — un niveau vieux de 5 barres n'est plus le setup.

### Sortie sur cassure de tendance (`Exit trend trades on EMA flip`)

Ferme un trade de tendance quand l'EMA rapide repasse de l'autre côté de l'EMA de pullback,
**uniquement si le trade n'est pas en perte**. Capture le retournement plus tôt que le trailing
ATR. À tester : ça améliore le PF sur des marchés qui tournent vite, ça le dégrade sur des
tendances qui respirent.

## 10. Critères d'acceptation du backtest

Le code est fini. La **stratégie**, elle, n'est validée par aucun trade historique : les valeurs
par défaut sont des choix raisonnés, pas des chiffres optimisés. Voilà comment trancher.

### Le coût par trade (à calculer sur TON compte)

```
coût en R  =  (spread + commission en pips) / stop en pips
```

Exemple réel (Fusion Markets, XAUUSD, 1 pip = 0,10 $) : spread 0,9 pip + commission ~0,45 pip
sur un stop de 17 pips → **~8 % du R perdu à chaque aller-retour**. C'est un bon terrain :
au-dessus de 20 %, le scalping de l'or est mathématiquement condamné quelle que soit la logique.

### Le verdict

| Mesure | Garder | Jeter |
|---|---|---|
| Nombre de trades | ≥ 200 sur ≥ 12 mois | < 100 (statistiquement vide) |
| Profit factor (net de commissions) | ≥ 1,25 | < 1,10 |
| Drawdown max | < 15 % | > 25 % |
| Écart in-sample / out-of-sample | PF hors échantillon ≥ 80 % du PF optimisé | effondrement hors échantillon |
| Profit factor > 2,5 | **suspect** — vérifier les données et les commissions | |

Un PF spectaculaire sur 40 trades ne veut rien dire. Un PF de 1,3 sur 400 trades, stable
hors échantillon, vaut infiniment plus.

### Protocole

1. Backtest **tick data** + commissions réelles, 12 mois minimum.
2. Optimise **3 à 5 paramètres maximum** sur les 6 premiers mois
   (`Stop loss = ATR x`, `Min quality score`, `Trend ADX threshold`, `TP1/TP2 at R`).
3. Valide sur les 3 mois suivants **sans retoucher un seul réglage**.
4. Si ça tient : démo ≥ 4 semaines sur le serveur live.
5. Si ça ne tient pas : ce n'est pas un réglage à ajuster, c'est la stratégie qui n'a pas d'edge
   sur cette période. Change de logique plutôt que de re-optimiser.

## 11. Limites connues

- Pas de calendrier économique : cTrader n'y donne pas accès avec `AccessRights.None`. Le filtre
  news est **manuel** (`News blackout times`, en UTC — pense à mettre 12:30/14:00 pour NFP & CPI,
  et 18:00 les jours de FOMC).
- Le P&L journalier est mesuré en equity depuis le début de journée : un redémarrage du bot en
  cours de journée remet cette référence à zéro.
- Les stats du bot regroupent les fermetures partielles par position : un trade sorti en
  3 morceaux compte pour **un** trade, avec son P&L total. Le rapport de cTrader, lui, les
  compte séparément — les deux chiffres ne coïncideront pas, et c'est normal.
- Toutes les heures sont en **UTC** (le robot force `TimeZones.UTC`), pas en heure du courtier.
