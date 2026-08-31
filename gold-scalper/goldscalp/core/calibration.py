"""Recalibrage Bybit -> MetaTrader 5.

Le prix Bybit (XAUT/USDT, or tokenise) et le prix MT5 XAUUSD de ton broker
ne sont PAS le même nombre. Trois écarts se superposent :

  1. la prime/decote du XAUT sur l'or spot (quelques dollars, lente derive) ;
  2. le taux USDT/USD (peg imparfait, +/- 0.1 %) ;
  3. le markup et le swap propres au broker.

Modele retenu : affine, `mt5 = alpha + beta * bybit`.

  - alpha absorbe la prime XAUT et le markup broker,
  - beta absorbe la derive proportionnelle (peg USDT, markup en %).

Sans plusieurs ancrages à des prix ECARTES, beta n'est pas identifiable : on
le contraint alors à 1.0 (décalage pur). C'est la différence entre une
calibration honnête et une regression qui hallucine une pente.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from goldscalp.core.series import Series
from goldscalp.util import (
    LOG,
    clamp,
    json_dump_atomic,
    median,
    ms_to_iso,
    now_ms,
    state_dir,
    stdev,
    theil_sen,
)

# Au-dela, on considere que l'ancrage ne décrit plus le marché courant.
ANCHOR_MAX_AGE_MS = 6 * 3600 * 1000       # 6 h
ANCHOR_WARN_AGE_MS = 45 * 60 * 1000       # 45 min
MIN_RANGE_FOR_SLOPE = 8.0                 # $ d'amplitude minimale entre ancrages


@dataclass
class Anchor:
    """Un point de calage : prix source et prix MT5 observés SIMULTANÉMENT.

    `spot` est le prix de l'or spot au même instant, quand il est connu (prix
    Bybit corrigé de la base mesurée, ou cotation spot directe). Un ancrage qui
    le renseigne mesure le seul MARKUP DU BROKER, quantité petite et stable.
    Sans lui, l'ancrage mesure l'écart brut à Bybit, qui inclut la prime XAUT
    et se périme en quelques heures.
    """

    ts: int
    bybit: float
    mt5_bid: float
    mt5_ask: float
    source: str = "manuel"
    spot: Optional[float] = None

    @property
    def mt5_mid(self) -> float:
        return (self.mt5_bid + self.mt5_ask) / 2.0

    @property
    def spread(self) -> float:
        # Arrondi : 2412.60 - 2412.30 donne 0.29999999999972715 en binaire, et
        # ce bruit se propage jusque dans les prix affichés et le JSON.
        return round(max(self.mt5_ask - self.mt5_bid, 0.0), 5)

    @property
    def offset(self) -> float:
        """Écart au prix de référence de cet ancrage."""
        return round(self.mt5_mid - self.reference_price, 5)

    @property
    def reference_price(self) -> float:
        return self.spot if self.spot is not None else self.bybit

    @property
    def is_spot_based(self) -> bool:
        return self.spot is not None


@dataclass
class Calibration:
    alpha: float = 0.0
    beta: float = 1.0
    spread: float = 0.30            # spread MT5 typique en $ (XAUUSD)
    anchors: list[Anchor] = field(default_factory=list)
    fitted_at: int = 0
    residual_std: float = 0.0
    slope_fitted: bool = False
    note: str = "non calibré"
    reference: str = "bybit"     # "spot" quand alpha mesure le markup broker

    # -- conversions ------------------------------------------------------- #
    def to_mt5(self, bybit_price: float) -> float:
        return self.alpha + self.beta * bybit_price

    def to_bybit(self, mt5_price: float) -> float:
        return (mt5_price - self.alpha) / self.beta if self.beta else mt5_price

    def apply(self, series: Series) -> Series:
        return series.apply_calibration(self.alpha, self.beta)

    @property
    def half_spread(self) -> float:
        return self.spread / 2.0

    def ask(self, mid: float) -> float:
        return mid + self.half_spread

    def bid(self, mid: float) -> float:
        return mid - self.half_spread

    # -- qualité ----------------------------------------------------------- #
    @property
    def age_ms(self) -> int:
        if not self.anchors:
            return 10 ** 12
        return max(0, now_ms() - max(a.ts for a in self.anchors))

    @property
    def stale_after_ms(self) -> int:
        """Durée de vie utile de la calibration selon son référentiel.

        Un ancrage adossé au spot mesure le markup du broker : il tient des
        jours. Un ancrage adossé au prix Bybit brut inclut la prime XAUT, qui
        dérive en quelques heures.
        """
        return ANCHOR_MAX_AGE_MS * (28 if self.reference == "spot" else 1)

    @property
    def is_stale(self) -> bool:
        return self.age_ms > self.stale_after_ms

    def quality(self) -> float:
        """Score 0-100 : peut-on faire confiance aux prix MT5 produits ?"""
        if not self.anchors:
            return 0.0
        score = 30.0
        score += min(len(self.anchors), 6) * 5.0          # jusqu'à +30
        age = self.age_ms
        warn_at = ANCHOR_WARN_AGE_MS * (28 if self.reference == "spot" else 1)
        stale_at = self.stale_after_ms
        if age <= warn_at:
            score += 25.0
        elif age <= stale_at:
            score += 25.0 * (1 - (age - warn_at) / max(stale_at - warn_at, 1))
        if self.slope_fitted:
            score += 8.0
        if self.residual_std > 0:
            score -= clamp(self.residual_std * 8.0, 0.0, 25.0)
        if any(a.source.startswith("mt5") for a in self.anchors):
            score += 7.0
        if self.reference == "spot":
            # Un markup broker vieillit infiniment mieux qu'une prime XAUT.
            score += 12.0
        return round(clamp(score, 0.0, 100.0), 1)

    def describe(self) -> str:
        if not self.anchors:
            return "AUCUNE calibration - les prix affichés sont des prix bruts, non recalés"
        sign = "+" if self.alpha >= 0 else "-"
        beta_txt = f" x{self.beta:.6f}" if self.slope_fitted else ""
        left = "spot" if self.reference == "spot" else "Bybit"
        return (
            f"MT5 = {left} {sign} {abs(self.alpha):.2f}{beta_txt} | "
            f"spread {self.spread:.2f}$ | {len(self.anchors)} ancrage(s) | "
            f"qualité {self.quality():.0f}/100 | dernier {ms_to_iso(max(a.ts for a in self.anchors))}"
        )

    # -- persistance ------------------------------------------------------- #
    def to_dict(self) -> dict:
        data = asdict(self)
        data["anchors"] = [asdict(a) for a in self.anchors]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        known = {"ts", "bybit", "mt5_bid", "mt5_ask", "source", "spot"}
        anchors = [
            Anchor(**{k: v for k, v in a.items() if k in known})
            for a in data.get("anchors", [])
        ]
        return cls(
            alpha=float(data.get("alpha", 0.0)),
            beta=float(data.get("beta", 1.0)),
            spread=float(data.get("spread", 0.30)),
            anchors=anchors,
            fitted_at=int(data.get("fitted_at", 0)),
            residual_std=float(data.get("residual_std", 0.0)),
            slope_fitted=bool(data.get("slope_fitted", False)),
            note=str(data.get("note", "")),
            reference=str(data.get("reference", "bybit")),
        )


def calibration_path() -> str:
    return os.environ.get("GOLDSCALP_CALIBRATION") or os.path.join(state_dir(), "calibration.json")


def load_calibration(path: Optional[str] = None) -> Calibration:
    target = path or calibration_path()
    if not os.path.exists(target):
        return Calibration()
    try:
        import json

        with open(target, "r", encoding="utf-8") as fh:
            return Calibration.from_dict(json.load(fh))
    except Exception as exc:  # pragma: no cover - fichier corrompu
        LOG.warning("calibration illisible (%s), on repart de zero", exc)
        return Calibration()


def save_calibration(calib: Calibration, path: Optional[str] = None) -> str:
    target = path or calibration_path()
    json_dump_atomic(target, calib.to_dict())
    return target


def fit(anchors: list[Anchor], max_anchors: int = 24) -> Calibration:
    """Ajuste alpha/beta sur les ancrages, du plus robuste au plus prudent.

    Un ancrage adossé au spot ne se périme quasiment pas : il mesure le markup
    du broker, pas la prime du métal tokenisé. On garde donc les ancrages spot
    beaucoup plus longtemps que les ancrages bruts.
    """
    spot_anchors = [a for a in anchors if a.is_spot_based]
    # Les ancrages spot survivent 5 fois plus longtemps que les ancrages bruts.
    horizon = ANCHOR_MAX_AGE_MS * (20 if spot_anchors else 4)
    fresh = [a for a in anchors if now_ms() - a.ts <= horizon]
    fresh.sort(key=lambda a: a.ts)
    fresh = fresh[-max_anchors:]

    if not fresh:
        return Calibration(note="aucun ancrage exploitable")

    # Référentiel homogène : si l'on dispose d'ancrages spot, on ignore les
    # ancrages bruts. Mélanger les deux reviendrait à additionner un markup
    # broker et une prime XAUT dans le même alpha.
    usable = [a for a in fresh if a.is_spot_based] or fresh
    reference = "spot" if usable[0].is_spot_based else "bybit"

    spread = round(median([a.spread for a in usable if a.spread > 0]) or 0.30, 5)

    if len(usable) == 1:
        anchor = usable[0]
        return Calibration(
            alpha=round(anchor.offset, 6),
            beta=1.0,
            spread=spread,
            anchors=fresh,
            fitted_at=now_ms(),
            residual_std=0.0,
            slope_fitted=False,
            note=(
                "markup broker mesuré sur 1 ancrage spot" if reference == "spot"
                else "décalage simple (1 ancrage)"
            ),
            reference=reference,
        )

    fresh = usable
    xs = [a.reference_price for a in fresh]
    ys = [a.mt5_mid for a in fresh]
    coverage = max(xs) - min(xs)

    if len(fresh) >= 3 and coverage >= MIN_RANGE_FOR_SLOPE:
        alpha, beta = theil_sen(xs, ys)
        # Garde-fou : une pente hors [0.97, 1.03] est economiquement absurde
        # pour deux cotations du même metal. On retombe sur le décalage pur.
        if not 0.97 <= beta <= 1.03:
            LOG.warning("pente calibrée aberrante (%.5f), retour au décalage pur", beta)
            beta = 1.0
            alpha = median([a.offset for a in fresh])
            slope_fitted = False
        else:
            slope_fitted = True
    else:
        beta = 1.0
        # Mediane pondérée vers les ancrages recents : la prime XAUT derive.
        recent = fresh[-5:]
        alpha = median([a.offset for a in recent])
        slope_fitted = False

    residuals = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    note = (
        f"regression robuste sur {len(fresh)} ancrages (amplitude {coverage:.1f}$)"
        if slope_fitted
        else f"décalage median sur {len(fresh)} ancrages"
    )
    return Calibration(
        alpha=round(alpha, 6),
        beta=round(beta, 9),
        spread=spread,
        anchors=fresh,
        fitted_at=now_ms(),
        residual_std=round(stdev(residuals), 4),
        slope_fitted=slope_fitted,
        note=note,
        reference=reference,
    )


def add_anchor(calib: Calibration, bybit: float, mt5_bid: float, mt5_ask: float,
               source: str = "manuel", ts: Optional[int] = None,
               spot: Optional[float] = None) -> Calibration:
    """Ajoute un ancrage et refit. Renvoie une NOUVELLE calibration.

    Fournir `spot` (prix de l'or spot au même instant) transforme l'ancrage :
    il mesure alors le markup du broker au lieu de l'écart brut à Bybit, et
    reste valable des jours au lieu de quelques heures.
    """
    if mt5_ask < mt5_bid:
        mt5_bid, mt5_ask = mt5_ask, mt5_bid
    anchor = Anchor(ts=ts or now_ms(), bybit=bybit, mt5_bid=mt5_bid, mt5_ask=mt5_ask,
                    source=source, spot=spot)
    # Contrôle de dérive : seulement entre ancrages du MÊME référentiel.
    # Comparer un prix Bybit à une calibration adossée au spot produirait un
    # écart égal à la prime XAUT entière, et donc une fausse alerte.
    same_reference = calib.reference == ("spot" if anchor.is_spot_based else "bybit")
    if calib.anchors and same_reference:
        drift = anchor.mt5_mid - calib.to_mt5(anchor.reference_price)
        if abs(drift) > 3.0:
            LOG.warning(
                "derive de %.2f$ vs la calibration précédente - "
                "vérifie que les deux prix ont bien été relevés au même instant",
                drift,
            )
    return fit(calib.anchors + [anchor])


def auto_anchor_from_mt5(calib: Calibration, bybit_price: float, symbol: str = "XAUUSD",
                         spot: Optional[float] = None) -> Calibration:
    """Ancrage automatique en lisant le tick live du terminal MT5.

    Necessite le paquet `MetaTrader5` (Windows) et un terminal ouvert.
    Sans lui, la calibration reste inchangee.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        LOG.info("paquet MetaTrader5 absent - ancrage automatique indisponible")
        return calib

    if not mt5.initialize():
        LOG.warning("MT5 non joignable (%s) - lance le terminal et reessaie", mt5.last_error())
        return calib
    try:
        if not mt5.symbol_select(symbol, True):
            LOG.warning("symbole %s introuvable chez ce broker", symbol)
            return calib
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or not tick.bid or not tick.ask:
            LOG.warning("aucun tick %s disponible", symbol)
            return calib
        LOG.info("ancrage MT5 auto : bid %.2f / ask %.2f", tick.bid, tick.ask)
        return add_anchor(calib, bybit_price, float(tick.bid), float(tick.ask),
                          source="mt5_auto", spot=spot)
    finally:
        mt5.shutdown()


def health(calib: Calibration) -> tuple[str, list[str]]:
    """(niveau, messages) -> `ok` | `attention` | `critique`."""
    problems: list[str] = []
    level = "ok"

    if not calib.anchors:
        return "critique", [
            "Aucun ancrage MT5 : les niveaux ne sont pas en prix broker.",
            "Lance `goldscalp calibrate --bybit <prix> --bid <bid> --ask <ask>` avant de trader.",
        ]

    age = calib.age_ms
    if calib.reference == "spot":
        # L'ancrage mesure le markup du broker, pas la prime du métal tokenisé :
        # il reste valable des jours. Le seul risque est un changement de
        # conditions chez le courtier.
        if age > calib.stale_after_ms:
            level = "critique"
            problems.append(
                f"Ancrage spot vieux de {age / 86400000:.1f} jours - reprends un relevé."
            )
        elif age > calib.stale_after_ms / 2:
            level = "attention"
            problems.append(
                f"Ancrage spot vieux de {age / 86400000:.1f} jours - vérifie que ton "
                "broker n'a pas modifié son markup."
            )
    elif age > ANCHOR_MAX_AGE_MS:
        level = "critique"
        problems.append(f"Ancrage vieux de {age / 3600000:.1f} h - recalibre avant d'entrer.")
    elif age > ANCHOR_WARN_AGE_MS:
        level = "attention"
        problems.append(
            f"Ancrage vieux de {age / 60000:.0f} min et adossé au prix Bybit brut - "
            "la prime XAUT a pu dériver. Mesurer la base spot supprimerait ce problème."
        )

    if calib.residual_std > 1.0:
        level = "critique" if calib.residual_std > 2.5 else "attention"
        problems.append(
            f"Dispersion des ancrages élevée (sigma {calib.residual_std:.2f}$) - "
            "certains relevés n'etaient pas simultanes."
        )

    if calib.spread > 0.60:
        level = "attention" if level == "ok" else level
        problems.append(f"Spread broker large ({calib.spread:.2f}$) - le scalp M1 devient très cher.")

    if calib.quality() < 45:
        level = "critique" if level != "critique" else level
        problems.append(f"Qualité de calibration faible ({calib.quality():.0f}/100).")

    return level, problems
