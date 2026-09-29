# Bot de trading cTrader (or / forex / indices)

Bot Python branché sur l'**API officielle cTrader Open API**. Par défaut il trade l'or (XAUUSD) en H1.

> ⚠️ Aucune stratégie ne garantit un gain. Ce bot peut perdre de l'argent.
> Suis les étapes **dans l'ordre** : backtest → compte démo → réel avec un petit montant.

## Stratégie : suivi de tendance

| Élément | Règle |
|---|---|
| Tendance | Prix au-dessus de l'EMA 200 : uniquement des achats. En dessous : uniquement des ventes |
| Entrée | Croisement de l'EMA 20 et de l'EMA 50 dans le sens de la tendance, sur bougie clôturée |
| Stop loss | 2 × ATR(14), posé chez le courtier dès l'ouverture |
| Take profit | 3 × ATR(14), soit un ratio de 1:1,5 |
| Sortie anticipée | Croisement inverse des EMA |
| Taille | Calculée pour perdre **0,5 % du solde** au maximum si le stop est touché |
| Coupe-circuit | Plus aucune nouvelle position si la perte du jour atteint 2 % |
| Positions | Une seule à la fois. Le bot ne touche **que** ses propres positions (label `claude-bot`), jamais tes trades manuels |

Tous les paramètres se règlent dans `.env`.

## Installation (sur ton PC ou un VPS, Python 3.10 ou plus)

```bash
cd trading-bot
python -m venv .venv
source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # Windows : copy .env.example .env
```

## 1. Connecter ton compte cTrader

1. Va sur https://openapi.ctrader.com/apps, connecte-toi avec ton cTrader ID et crée une application.
   Mets `https://spotware.com` comme *Redirect URI*. L'activation par Spotware peut prendre un peu de temps.
2. Copie le *Client ID* et le *Secret* dans `.env`.
3. Lance :
   ```bash
   python get_token.py
   ```
   Ouvre le lien affiché et autorise l'application. Tu es alors redirigé vers une URL qui contient `code=XXXX` : colle cette valeur dans le terminal.
4. Le script affiche ton `CTRADER_ACCESS_TOKEN`, ton `CTRADER_REFRESH_TOKEN` et la liste de tes comptes. Recopie-les dans `.env`.
   Choisis d'abord un compte **DEMO** et mets `CTRADER_ENV=demo`.

Le token expire au bout d'environ 30 jours. Pour le renouveler : `python get_token.py --refresh`.

🔒 Ne partage jamais ton `.env`, ni avec moi dans le chat, ni sur GitHub. Il est déjà exclu par `.gitignore`.

## 2. Backtester sur l'historique de ton courtier

```bash
python bot.py --download 730                        # 2 ans de bougies H1 -> data/XAUUSD_H1.csv
python backtest.py data/XAUUSD_H1.csv --spread 0.30
```

Le backtest affiche le nombre de trades, le taux de réussite, le profit factor, le rendement et le drawdown maximal.
**Si le profit factor est inférieur à 1,2 ou si le drawdown est trop fort pour toi, ne passe pas en réel.**
Tu peux alors tester d'autres réglages dans `.env` (TIMEFRAME, SL_ATR, TP_ATR…).
Attention : à force de retoucher les réglages, on finit par coller au passé (sur-optimisation), et les résultats ne se reproduisent pas ensuite.

## 3. Lancer le bot

```bash
python bot.py
```

| Étape | Réglages `.env` | Ce qui se passe |
|---|---|---|
| a. Simulation | `CTRADER_ENV=demo`, `DRY_RUN=true` | Le bot affiche ses signaux sans envoyer d'ordre |
| b. Démo (2 à 4 semaines minimum) | `DRY_RUN=false` | Vrais ordres, argent fictif |
| c. Réel | `CTRADER_ENV=live`, `CTRADER_ACCOUNT_ID` = compte live, `RISK_PER_TRADE_PCT=0.25` pour commencer | Vrais ordres, argent réel |

Les journaux sont écrits à l'écran et dans `bot.log`.

Pour tourner 24h/24, il faut que la machine reste allumée. Un petit VPS Linux à quelques euros par mois suffit, avec `screen`, `tmux` ou un service systemd.

## Tests

```bash
pytest -q
```

## À propos de Trade Republic

Trade Republic ne propose **pas d'API publique**. Les outils non officiels (reverse engineering) enfreignent leurs conditions d'utilisation et risquent de faire bloquer ton compte. Ce bot fonctionne donc uniquement avec cTrader.
