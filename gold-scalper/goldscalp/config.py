"""Configuration de l'outil : parametres de marche, de risque et de moteur."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from goldscalp.util import LOG, state_dir


@dataclass
class RiskConfig:
    account_balance: float = 10_000.0
    risk_pct: float = 0.5            # % du capital risque par trade
    max_risk_pct: float = 2.0        # plafond dur
    min_rr_tp1: float = 1.0          # R:R minimal exige sur TP1
    target_rr_tp1: float = 1.4
    target_rr_tp2: float = 2.6
    tp1_share: float = 0.6           # part de la position sortie a TP1
    max_stop_atr: float = 2.0        # stop plafonne a N x ATR(M5)
    min_stop_atr: float = 0.55
    max_spread: float = 0.60         # $ - au-dela, le scalp M1 n'est plus rentable
    stop_buffer_atr: float = 0.25    # marge sous/sur le niveau structurel
    max_lots: float = 10.0
    max_daily_trades: int = 12

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.account_balance <= 0:
            problems.append("le capital doit etre positif")
        if not 0 < self.risk_pct <= self.max_risk_pct:
            problems.append(f"risk_pct doit etre dans ]0, {self.max_risk_pct}]")
        if self.min_rr_tp1 < 0.5:
            problems.append("un R:R inferieur a 0.5 sur TP1 ne survit pas aux frais")
        if not 0 < self.tp1_share <= 1.0:
            problems.append("tp1_share doit etre dans ]0, 1]")
        return problems


@dataclass
class EngineConfig:
    timeframes: list[str] = field(default_factory=lambda: ["M1", "M5", "M15"])
    bars: dict[str, int] = field(default_factory=lambda: {"M1": 2000, "M5": 1500, "M15": 1000, "D1": 90})
    min_confidence: float = 55.0
    turbo_confidence: float = 78.0
    allow_counter_trend: bool = False
    news_block_before_min: int = 20
    news_block_after_min: int = 15
    news_caution_min: int = 60
    swing_span: dict[str, int] = field(default_factory=lambda: {"M1": 3, "M5": 3, "M15": 4})
    use_macro: bool = True
    use_calendar: bool = True
    use_microstructure: bool = True


@dataclass
class MarketConfig:
    mt5_symbol: str = "XAUUSD"
    bybit_symbol: Optional[str] = None      # None = detection auto
    bybit_category: Optional[str] = None    # None = linear puis spot
    contract_size: float = 100.0            # 1 lot XAUUSD = 100 onces
    digits: int = 2
    default_spread: float = 0.30


@dataclass
class Config:
    market: MarketConfig = field(default_factory=MarketConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)

    @classmethod
    def default_path(cls) -> str:
        return os.environ.get("GOLDSCALP_CONFIG") or os.path.join(state_dir(), "config.json")

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        target = path or cls.default_path()
        config = cls()
        if not os.path.exists(target):
            return config
        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            LOG.warning("config illisible (%s) - valeurs par defaut", exc)
            return config
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        config = cls()
        for section, klass in (("market", MarketConfig), ("risk", RiskConfig), ("engine", EngineConfig)):
            values = data.get(section) or {}
            current = getattr(config, section)
            for key, value in values.items():
                if hasattr(current, key):
                    setattr(current, key, value)
        return config

    def to_dict(self) -> dict[str, Any]:
        return {"market": asdict(self.market), "risk": asdict(self.risk), "engine": asdict(self.engine)}

    def save(self, path: Optional[str] = None) -> str:
        from goldscalp.util import json_dump_atomic

        target = path or self.default_path()
        json_dump_atomic(target, self.to_dict())
        return target
