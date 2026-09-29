# GoldLiveEngine — cBot cTrader pour XAUUSD

> **Statut : NON TESTÉ sur données XAUUSD réelles.**
> Le code compile contre l'API officielle `cTrader.Automate` et passe 30 auto-tests mécaniques (look-ahead, sizing, partiels, fuseaux, sécurité).
> Aucun win rate, profit factor ou drawdown sur l'or n'a été mesuré. Les données historiques étaient inaccessibles depuis l'environnement de développement.
> **Suis la procédure de validation ci-dessous avant d'engager de l'argent réel.**

## Contenu

| Fichier | Rôle |
|---|---|
| `GoldLiveEngine.cs` | Le cBot complet. Un seul fichier : moteur + adaptateur cTrader |
| `GoldLiveEngine.csproj` | Projet .NET 6 identique à celui de cTrader (`dotnet build` pour compiler hors cTrader) |
| `research/` | Outil de recherche : rejoue **le même moteur** sur ton historique (backtest année par année, TRAIN / VALIDATION / OOS, walk-forward, plateaux de paramètres, ablation, stress des coûts, Monte Carlo, Holm-Bonferroni, auto-tests) |

## 1. Installer dans cTrader

1. Dans cTrader, va dans **Algo**, puis **cBots**, clique sur **New** et nomme le cBot `GoldLiveEngine`.
2. Remplace tout le code par le contenu de `GoldLiveEngine.cs`, puis clique sur **Build**.
3. Attache le cBot à un graphique **XAUUSD en M5**. M1 est possible, mais le coût du spread y est à peu près deux fois plus lourd par rapport à la volatilité.
4. Le cBot force le fuseau **UTC** (`TimeZone = TimeZones.UTC`). Les sessions sont converties en heure de Londres et de New York, avec l'heure d'été.
5. Pour faire tourner plusieurs instances sur le même compte, donne à chacune un **Instance tag** différent.

## 2. Protocole de validation (dans cet ordre)

### Étape A — Backtest cTrader (données du broker, spread réel)
- Choisis le mode **« Tick data from server »** : c'est le seul mode qui reproduit le spread variable.
- Lance un backtest par année : 2020, 2021, 2022, 2023, 2024, 2025, 2026. À la fin de chaque run, le journal affiche un résumé (`RÉSUMÉ GoldLiveEngine`).
- Réglages par défaut uniquement. **Ne rien optimiser à cette étape.**

### Étape B — Recherche hors cTrader (même moteur, analyses statistiques)
```bash
# 1. Télécharger l'historique M5 depuis ton compte (bot Python du dossier parent, .env configuré)
cd ..
TIMEFRAME=M5 python bot.py --download 2500      # -> data/XAUUSD_M5.csv (environ 7 ans)

# 2. Lancer l'analyse (.NET 8 requis)
cd ctrader-cbot/research
dotnet run -c Release -- --selftest
dotnet run -c Release -- --csv ../../data/XAUUSD_M5.csv --spread 0.30 --slippage 0.05 --commission 0.07 --out report.md
```
Mets **le spread moyen réel de ton broker** (`--spread`) et **sa commission** par once aller-retour (`--commission`). Par exemple, 7 $ par lot de 100 onces donnent 0,07.

### Critères GO / NO-GO (fixés AVANT d'avoir vu les résultats)

Passage en démo seulement si **tous** ces critères sont remplis avec les paramètres par défaut :

| Critère | Seuil |
|---|---|
| Espérance OOS (en R) | > 0 |
| Espérance VALIDATION (en R) | > 0 |
| Walk-forward OOS concaténé | espérance > 0 et PF ≥ 1,10 |
| Années positives | au moins 5 sur 7 (aucune année < −8 %) |
| Coûts ×1,5 + slippage 0,10 | espérance ≥ 0 |
| Monte Carlo, coût +0,05 R | P(DD ≥ 20 %) < 10 % |
| Nombre de trades | ≥ 150 par an |
| Holm-Bonferroni | au moins un setup avec une edge significative. Les setups non significatifs **et** d'espérance négative en VALIDATION doivent être désactivés |

Si un critère échoue, **ne compense pas en optimisant sur toute la période**. Retire ce qui ne marche pas (setup, filtre), puis vérifie sur VALIDATION et OOS.

### Étape C — Démo (minimum 2 à 3 mois, au moins 100 trades)
Compare la démo au backtest sur la même période : écart de spread, slippage, nombre de trades, R moyen. Un écart d'espérance supérieur à 0,05 R par trade doit être expliqué avant d'aller plus loin.

### Étape D — Réel
Commence avec `Risk per trade = 0.10 à 0.25 %`, puis augmente seulement après 3 mois conformes à la démo.

## 3. Ce qu'il est raisonnable d'optimiser (avec parcimonie)
- `Min confluence score`, dans un plateau, jamais une valeur isolée.
- `TP1 (R)` et la répartition des clôtures partielles. L'ablation « sans TP partiels » montre si les partiels servent l'espérance ou seulement le win rate.
- L'activation ou non de chaque setup (A/B/C/D) et des sessions.
- `Max spread (x ATR)` selon ton broker.

## 4. Ce qu'il ne faut PAS optimiser
- Les périodes d'EMA (20/50/200), d'ATR (14/200) et d'ADX (14) : ce sont des constantes.
- Les poids du score de confluence : des constantes dans le code.
- Les seuils internes des setups : profondeur du sweep, taille de la box, ratio de mèche.
- Le couple TP2/TP3 ou le trailing « à la décimale » près.

Plus il y a de degrés de liberté, plus le backtest ment.
