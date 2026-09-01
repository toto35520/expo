"""goldscalp - moteur de scalping XAU/USD (or) multi-timeframe.

Prix source : Bybit (XAUT/USDT, dispo 24/7 y compris week-end)
Prix d'exécution : MetaTrader 5 (XAUUSD broker), via recalibrage affine.

Le coeur du package n'a AUCUNE dépendance externe obligatoire : tout tourne
avec la lib standard Python 3.9+. Les extras (MetaTrader5, rich) sont
détectés a l'exécution et dégradent proprement s'ils sont absents.
"""

__version__ = "1.0.0"

APP_NAME = "goldscalp"

