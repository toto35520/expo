"""Configuration chargée depuis le fichier .env (jamais de secrets dans le code)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "oui")


@dataclass(frozen=True)
class StrategyParams:
    ema_fast: int = int(os.getenv("EMA_FAST", 20))
    ema_slow: int = int(os.getenv("EMA_SLOW", 50))
    ema_trend: int = int(os.getenv("EMA_TREND", 200))
    atr_period: int = int(os.getenv("ATR_PERIOD", 14))
    sl_atr: float = float(os.getenv("SL_ATR", 2.0))   # stop loss = 2 x ATR
    tp_atr: float = float(os.getenv("TP_ATR", 3.0))   # take profit = 3 x ATR (ratio 1:1.5)


@dataclass(frozen=True)
class Settings:
    client_id: str = os.getenv("CTRADER_CLIENT_ID", "")
    client_secret: str = os.getenv("CTRADER_CLIENT_SECRET", "")
    access_token: str = os.getenv("CTRADER_ACCESS_TOKEN", "")
    account_id: int = int(os.getenv("CTRADER_ACCOUNT_ID", 0) or 0)
    env: str = os.getenv("CTRADER_ENV", "demo").lower()        # demo | live

    symbol: str = os.getenv("SYMBOL", "XAUUSD")
    timeframe: str = os.getenv("TIMEFRAME", "H1")

    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", 0.5))
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", 2.0))
    dry_run: bool = _bool("DRY_RUN", True)                      # True = aucun ordre envoyé
    label: str = os.getenv("BOT_LABEL", "claude-bot")

    strategy: StrategyParams = StrategyParams()


TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}
