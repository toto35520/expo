"""Analyse fondamentale de l'or, orientee scalp.

Sur un horizon de quelques minutes, le "fondamental" n'est pas le deficit
budgetaire americain : c'est ce que font MAINTENANT le dollar, les taux et
l'appetit pour le risque. On mesure donc l'impulsion intraday de chaque
moteur, on la signe par sa correlation connue avec l'or, et on agrege.

Regle de conception : une source absente est retiree du calcul et de sa
ponderation. Jamais de valeur par defaut inventee - une macro muette doit
produire un score de 0 avec une confiance basse, pas un faux signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from goldscalp.data.calendar import NewsRisk
from goldscalp.data.macro import MacroSeries
from goldscalp.util import clamp, safe_div

# Poids relatifs des moteurs macro de l'or.
DRIVER_WEIGHTS = {
    "dxy": 0.34,      # le dollar domine
    "us10y": 0.26,    # cout d'opportunite
    "us02y": 0.10,
    "vix": 0.14,      # refuge
    "spx": 0.06,
    "silver": 0.08,   # confirmation du complexe metaux precieux
    "oil": 0.02,      # canal inflation, marginal en intraday
}

LABELS = {
    "dxy": "Dollar (DXY)",
    "us10y": "Taux 10 ans US",
    "us02y": "Taux 2 ans US",
    "vix": "Volatilite (VIX)",
    "spx": "Actions (S&P 500)",
    "silver": "Argent",
    "oil": "Petrole",
}


@dataclass
class DriverReading:
    key: str
    label: str
    change_pct: Optional[float]
    momentum_z: Optional[float]
    correlation: float
    contribution: float        # score signe dans [-1, +1], deja oriente or
    weight: float
    source: str

    def explain(self) -> str:
        if self.change_pct is None:
            return f"{self.label} : indisponible"
        sens = "soutient l'or" if self.contribution > 0.05 else (
            "pese sur l'or" if self.contribution < -0.05 else "neutre"
        )
        return (
            f"{self.label} {self.change_pct:+.2f}% "
            f"(z {self.momentum_z:+.1f}) -> {sens} [{self.contribution:+.2f}]"
            if self.momentum_z is not None
            else f"{self.label} {self.change_pct:+.2f}% -> {sens} [{self.contribution:+.2f}]"
        )


@dataclass
class FundamentalView:
    score: float = 0.0             # [-1, +1], positif = haussier or
    confidence: float = 0.0        # [0, 1] : part des moteurs reellement lus
    drivers: list[DriverReading] = field(default_factory=list)
    news: Optional[NewsRisk] = None
    regime_label: str = "neutre"
    notes: list[str] = field(default_factory=list)

    @property
    def bias(self) -> str:
        if self.confidence < 0.25:
            return "indetermine"
        if self.score > 0.30:
            return "haussier"
        if self.score < -0.30:
            return "baissier"
        return "neutre"

    @property
    def effective_score(self) -> float:
        """Score pondere par la confiance : une macro muette ne pousse rien."""
        return round(self.score * self.confidence, 3)

    def top_drivers(self, n: int = 3) -> list[DriverReading]:
        readings = [d for d in self.drivers if d.change_pct is not None]
        return sorted(readings, key=lambda d: abs(d.contribution), reverse=True)[:n]


def analyse_fundamentals(macro: dict[str, MacroSeries], news: Optional[NewsRisk] = None,
                         lookback_bars: int = 12) -> FundamentalView:
    readings: list[DriverReading] = []
    weighted_sum = 0.0
    weight_used = 0.0
    weight_total = sum(DRIVER_WEIGHTS.values())

    for key, weight in DRIVER_WEIGHTS.items():
        series = macro.get(key)
        if series is None or len(series.closes) < 5:
            readings.append(
                DriverReading(key, LABELS.get(key, key), None, None, 0.0, 0.0, weight, "absent")
            )
            continue

        change = series.change_pct(min(lookback_bars, len(series.closes) - 1))
        momentum = series.momentum_z()
        if change is None:
            readings.append(
                DriverReading(key, LABELS.get(key, key), None, None, 0.0, 0.0, weight, series.source)
            )
            continue

        # Normalisation : 0.5 % de variation = mouvement macro significatif.
        # Le VIX bouge beaucoup plus, on lui donne une echelle propre.
        scale = 3.0 if key == "vix" else 0.5
        normalized = clamp(change / scale, -1.5, 1.5)
        if momentum is not None:
            normalized = normalized * 0.7 + clamp(momentum / 2.5, -1.0, 1.0) * 0.3

        contribution = clamp(normalized * series.correlation, -1.0, 1.0)
        weighted_sum += contribution * weight
        weight_used += weight
        readings.append(
            DriverReading(
                key=key,
                label=LABELS.get(key, key),
                change_pct=round(change, 4),
                momentum_z=round(momentum, 3) if momentum is not None else None,
                correlation=series.correlation,
                contribution=round(contribution, 3),
                weight=weight,
                source=series.source,
            )
        )

    score = clamp(safe_div(weighted_sum, weight_used, 0.0), -1.0, 1.0)
    confidence = clamp(safe_div(weight_used, weight_total, 0.0), 0.0, 1.0)

    notes: list[str] = []
    if confidence < 0.4:
        notes.append(
            "Moins de la moitie des moteurs macro sont lisibles : "
            "l'analyse fondamentale ne pese quasiment rien dans ce signal."
        )
    if news is not None:
        if news.blocks_trading:
            notes.append(f"FENETRE NEWS : {news.reason}")
        elif news.level == "prudence":
            notes.append(f"News proche : {news.reason}")
        if news.estimated:
            notes.append(
                "Calendrier issu du repli embarque (flux en ligne inaccessible) : "
                "horaires approximatifs, verifie sur ton calendrier habituel."
            )

    regime_label = "neutre"
    if confidence >= 0.25:
        if score > 0.45:
            regime_label = "macro nettement favorable a l'or"
        elif score > 0.15:
            regime_label = "macro legerement favorable a l'or"
        elif score < -0.45:
            regime_label = "macro nettement defavorable a l'or"
        elif score < -0.15:
            regime_label = "macro legerement defavorable a l'or"

    return FundamentalView(
        score=round(score, 3),
        confidence=round(confidence, 3),
        drivers=readings,
        news=news,
        regime_label=regime_label,
        notes=notes,
    )
