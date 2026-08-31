"""Moteur de confluence multi-timeframe.

Principe : chaque timeframe à un ROLE, pas un vote egal.

  M15 -> le contexte. Definit le biais. On ne scalpe pas contre lui sans
         raison structurelle explicite.
  M5  -> la configuration. C'est la que se lit la qualité du repli, la
         structure et la zone d'entrée.
  M1  -> le déclencheur. Il ne créé pas un trade, il en décide l'instant.

Chaque timeframe produit cinq composantes notees dans [-1, +1], agregees
avec des poids qui dépendent du REGIME (en tendance on suit, en range on
fade). Puis viennent les modificateurs transverses : fondamental,
microstructure, session, news, qualité de calibration.

Toute la chaine est tracable : chaque point de score est justifie par une
ligne lisible dans le rapport. Une boite noire qui dit "achete" ne vaut rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from goldscalp.core.fundamental import FundamentalView
from goldscalp.core.indicators import IndicatorSet, last, last_valid, slope_of, valid_tail
from goldscalp.core.microstructure import MicroView
from goldscalp.core.regime import Regime, SessionInfo
from goldscalp.core.structure import StructureView
from goldscalp.util import clamp, safe_div

# Poids des composantes selon le régime dominant.
COMPONENT_WEIGHTS = {
    "tendance": {"trend": 0.38, "momentum": 0.24, "structure": 0.24, "participation": 0.10, "meanrev": 0.04},
    "range": {"trend": 0.14, "momentum": 0.20, "structure": 0.28, "participation": 0.08, "meanrev": 0.30},
    "neutre": {"trend": 0.28, "momentum": 0.24, "structure": 0.26, "participation": 0.10, "meanrev": 0.12},
}

# Poids de base par timeframe, ajustés ensuite selon le régime M15.
TF_BASE_WEIGHTS = {"M15": 0.42, "M5": 0.36, "M1": 0.22}

# Les valeurs internes servent de clés de comparaison dans tout le moteur :
# elles restent en ASCII et ne sont traduites qu'au moment de l'affichage.
TREND_FR = {"haussier": "haussière", "baissier": "baissière", "range": "en range"}
DIVERGENCE_FR = {
    "bullish": "haussière classique",
    "bearish": "baissière classique",
    "hidden_bullish": "haussière cachée",
    "hidden_bearish": "baissière cachée",
}


@dataclass
class Component:
    name: str
    value: float          # [-1, +1]
    weight: float
    details: list[str] = field(default_factory=list)

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class TimeframeView:
    timeframe: str
    indicators: IndicatorSet
    structure: StructureView
    regime: Regime
    components: dict[str, Component]
    score: float          # [-1, +1]
    role: str

    @property
    def direction(self) -> int:
        if self.score > 0.15:
            return 1
        if self.score < -0.15:
            return -1
        return 0

    @property
    def label(self) -> str:
        if self.score > 0.45:
            return "haussier fort"
        if self.score > 0.15:
            return "haussier"
        if self.score < -0.45:
            return "baissier fort"
        if self.score < -0.15:
            return "baissier"
        return "neutre"

    def top_reasons(self, n: int = 3) -> list[str]:
        ordered = sorted(self.components.values(), key=lambda c: abs(c.contribution), reverse=True)
        out: list[str] = []
        for component in ordered[:n]:
            for detail in component.details[:2]:
                out.append(f"[{self.timeframe}] {detail}")
        return out


# --------------------------------------------------------------------------- #
# Composantes
# --------------------------------------------------------------------------- #

def _score_trend(ind: IndicatorSet) -> Component:
    details: list[str] = []
    parts: list[tuple[float, float]] = []   # (valeur, poids)
    price = ind.price

    e9, e21, e50, e200 = (last_valid(x) for x in (ind.ema9, ind.ema21, ind.ema50, ind.ema200))

    # Empilement des moyennes : la lecture de tendance la plus directe.
    if None not in (e9, e21, e50):
        if e9 > e21 > e50:
            parts.append((1.0, 0.30))
            details.append("EMA 9>21>50 empilées à la hausse")
        elif e9 < e21 < e50:
            parts.append((-1.0, 0.30))
            details.append("EMA 9<21<50 empilées à la baisse")
        else:
            partial = 0.5 if e9 > e21 else -0.5
            parts.append((partial, 0.15))
            details.append("EMA entremêlées - tendance courte non établie")

    if e200 is not None:
        above = price > e200
        parts.append((0.8 if above else -0.8, 0.18))
        details.append(f"prix {'au-dessus de' if above else 'sous'} l'EMA200 ({e200:.2f})")

    # Pente de l'EMA21, normalisée par l'ATR : comparable entre timeframes.
    slope21 = slope_of(ind.ema21, 6)
    if slope21 is not None and ind.atr_value > 0:
        norm = clamp(slope21 / (ind.atr_value * 0.30), -1.0, 1.0)
        parts.append((norm, 0.20))
        if abs(norm) > 0.35:
            details.append(f"EMA21 en pente {'haussière' if norm > 0 else 'baissière'} ({norm:+.2f} ATR/barre)")

    if ind.st_dir:
        direction = ind.st_dir[-1]
        parts.append((float(direction), 0.16))
        details.append(f"Supertrend {'haussier' if direction > 0 else 'baissier'}")

    adx_v = last_valid(ind.adx14)
    pdi, mdi = last_valid(ind.plus_di), last_valid(ind.minus_di)
    if None not in (adx_v, pdi, mdi):
        strength = clamp((adx_v - 18) / 22.0, 0.0, 1.0)
        direction = 1.0 if pdi > mdi else -1.0
        parts.append((direction * strength, 0.16))
        if strength > 0.3:
            details.append(f"ADX {adx_v:.0f} avec {'+DI' if direction > 0 else '-DI'} devant")

    total_weight = sum(w for _, w in parts) or 1.0
    value = clamp(sum(v * w for v, w in parts) / total_weight, -1.0, 1.0)
    return Component("trend", round(value, 3), 0.0, details)


def _score_momentum(ind: IndicatorSet) -> Component:
    details: list[str] = []
    parts: list[tuple[float, float]] = []

    rsi_v = last_valid(ind.rsi14)
    if rsi_v is not None:
        centered = clamp((rsi_v - 50) / 25.0, -1.0, 1.0)
        parts.append((centered, 0.26))
        rsi_slope = slope_of(ind.rsi14, 4)
        if rsi_slope is not None:
            parts.append((clamp(rsi_slope / 4.0, -1.0, 1.0), 0.12))
        if rsi_v > 68 or rsi_v < 32:
            details.append(f"RSI {rsi_v:.0f} ({'surachat' if rsi_v > 68 else 'survente'})")
        else:
            details.append(f"RSI {rsi_v:.0f}")

    hist = last_valid(ind.macd_hist)
    if hist is not None and ind.atr_value > 0:
        norm = clamp(hist / (ind.atr_value * 0.5), -1.0, 1.0)
        parts.append((norm, 0.22))
        prev = last(ind.macd_hist, 1)
        if prev is not None:
            growing = abs(hist) > abs(prev)
            details.append(
                f"MACD histogramme {hist:+.3f} "
                f"({'accélère' if growing else 'ralentit'})"
            )

    srsi = last_valid(ind.srsi_k)
    srsi_d = last_valid(ind.srsi_d)
    if srsi is not None:
        centered = clamp((srsi - 50) / 40.0, -1.0, 1.0)
        parts.append((centered, 0.16))
        if srsi_d is not None and abs(srsi - srsi_d) > 4:
            cross = "haussier" if srsi > srsi_d else "baissier"
            details.append(f"StochRSI {srsi:.0f} croisement {cross}")

    roc_v = last_valid(ind.roc5)
    if roc_v is not None:
        parts.append((clamp(roc_v / 0.25, -1.0, 1.0), 0.14))

    cci_v = last_valid(ind.cci)
    if cci_v is not None:
        parts.append((clamp(cci_v / 150.0, -1.0, 1.0), 0.10))

    willr = last_valid(ind.willr)
    if willr is not None:
        parts.append((clamp((willr + 50) / 35.0, -1.0, 1.0), 0.10))

    total_weight = sum(w for _, w in parts) or 1.0
    value = clamp(sum(v * w for v, w in parts) / total_weight, -1.0, 1.0)
    return Component("momentum", round(value, 3), 0.0, details)


def _score_structure(ind: IndicatorSet, structure: StructureView) -> Component:
    details: list[str] = []
    parts: list[tuple[float, float]] = []
    price = ind.price
    atr = ind.atr_value

    mapping = {"haussier": 1.0, "baissier": -1.0, "range": 0.0}
    parts.append((mapping.get(structure.trend, 0.0), 0.26))
    details.append(f"structure {TREND_FR.get(structure.trend, structure.trend)}")

    if structure.last_event != "aucun":
        recency = clamp(1.0 - structure.event_bars_ago / 25.0, 0.0, 1.0)
        sign = 1.0 if structure.last_event.endswith("haussier") else -1.0
        # Un CHoCH est un signal de retournement : plus fort mais plus risque.
        magnitude = 0.9 if structure.last_event.startswith("CHoCH") else 0.7
        parts.append((sign * magnitude * recency, 0.22))
        if recency > 0.2:
            details.append(f"{structure.last_event} il y a {structure.event_bars_ago} barres")

    vwap_v = last_valid(ind.vwap)
    if vwap_v is not None and atr > 0:
        distance = clamp((price - vwap_v) / (atr * 2.0), -1.0, 1.0)
        parts.append((distance, 0.18))
        details.append(f"prix à {(price - vwap_v):+.2f}$ du VWAP")

    if ind.profile is not None:
        profile = ind.profile
        if price > profile.vah:
            parts.append((0.7, 0.14))
            details.append(f"au-dessus de la Value Area ({profile.vah:.2f}) - acceptation haussière")
        elif price < profile.val:
            parts.append((-0.7, 0.14))
            details.append(f"sous la Value Area ({profile.val:.2f}) - acceptation baissière")
        else:
            pos = safe_div(price - profile.val, profile.vah - profile.val, 0.5)
            parts.append((clamp((pos - 0.5) * 1.2, -1.0, 1.0), 0.10))
            details.append(f"dans la Value Area (POC {profile.poc:.2f}) - équilibre")

    # Marge de manoeuvre : un prix colle sous une résistance a peu de place.
    above = structure.nearest_above(price)
    below = structure.nearest_below(price)
    if above is not None and below is not None:
        room_up = above.price - price
        room_down = price - below.price
        balance = clamp(safe_div(room_up - room_down, room_up + room_down, 0.0), -1.0, 1.0)
        parts.append((balance, 0.12))
        if room_up < atr * 0.6:
            details.append(f"résistance immédiate a {above.price:.2f} ({above.label})")
        if room_down < atr * 0.6:
            details.append(f"support immédiat a {below.price:.2f} ({below.label})")

    patterns = ind.patterns
    bullish_patterns = {"engulfing_haussier", "marteau", "marubozu_haussier", "trois_soldats_blancs"}
    bearish_patterns = {"engulfing_baissier", "etoile_filante", "marubozu_baissier", "trois_corbeaux_noirs"}
    hits = sum(1 for p in patterns if p in bullish_patterns) - sum(1 for p in patterns if p in bearish_patterns)
    if hits:
        parts.append((clamp(hits / 2.0, -1.0, 1.0), 0.08))
        details.append("bougies : " + ", ".join(patterns[:3]))

    total_weight = sum(w for _, w in parts) or 1.0
    value = clamp(sum(v * w for v, w in parts) / total_weight, -1.0, 1.0)
    return Component("structure", round(value, 3), 0.0, details)


def _score_participation(ind: IndicatorSet, regime: Regime) -> Component:
    """Le volume et la volatilité ne donnent pas de direction : ils disent si
    le mouvement en cours merite qu'on le suive."""
    details: list[str] = []
    parts: list[tuple[float, float]] = []

    vol_z = last_valid(ind.vol_z)
    last_candle = ind.series.last
    if vol_z is not None:
        direction = 1.0 if last_candle.bullish else -1.0
        conviction = clamp(vol_z / 2.0, -0.5, 1.0)
        parts.append((direction * max(conviction, 0.0), 0.40))
        if vol_z > 1.2:
            details.append(f"volume {vol_z:+.1f} écart-types - participation réelle")
        elif vol_z < -0.8:
            details.append(f"volume faible ({vol_z:+.1f} sigma) - mouvement peu crédible")

    obv_slope = slope_of(ind.obv, 10)
    if obv_slope is not None:
        volumes = valid_tail(ind.obv, 30)
        span = (max(volumes) - min(volumes)) if len(volumes) > 2 else 0.0
        if span > 0:
            parts.append((clamp(obv_slope / (span / 10.0), -1.0, 1.0), 0.30))

    # Sortie de compression : le carburant du scalp.
    if len(ind.squeeze_on) > 3:
        just_released = (not ind.squeeze_on[-1]) and any(ind.squeeze_on[-4:-1])
        if just_released:
            direction = 1.0 if last_candle.bullish else -1.0
            parts.append((direction, 0.30))
            details.append("sortie de compression (squeeze relâché) - expansion en cours")

    if regime.volatility_state == "basse":
        details.append("volatilité au plancher - les cibles de scalp sont hors de portee")

    total_weight = sum(w for _, w in parts) or 1.0
    value = clamp(sum(v * w for v, w in parts) / total_weight, -1.0, 1.0)
    return Component("participation", round(value, 3), 0.0, details)


def _score_meanrev(ind: IndicatorSet) -> Component:
    """Composante contrarienne : elle ne compte vraiment qu'en range."""
    details: list[str] = []
    parts: list[tuple[float, float]] = []

    pct_b = last_valid(ind.pct_b)
    if pct_b is not None:
        if pct_b > 1.0:
            parts.append((-clamp((pct_b - 1.0) * 3, 0.3, 1.0), 0.34))
            details.append(f"prix hors bande supérieure (%B {pct_b:.2f}) - extension a corriger")
        elif pct_b < 0.0:
            parts.append((clamp(-pct_b * 3, 0.3, 1.0), 0.34))
            details.append(f"prix hors bande inférieure (%B {pct_b:.2f}) - extension a corriger")
        else:
            parts.append((clamp((0.5 - pct_b) * 1.2, -1.0, 1.0), 0.18))

    rsi_v = last_valid(ind.rsi14)
    if rsi_v is not None:
        if rsi_v > 72:
            parts.append((-clamp((rsi_v - 72) / 15.0, 0.2, 1.0), 0.26))
        elif rsi_v < 28:
            parts.append((clamp((28 - rsi_v) / 15.0, 0.2, 1.0), 0.26))

    if ind.divergence is not None:
        div = ind.divergence
        sign = 1.0 if "bullish" in div.kind else -1.0
        parts.append((sign * div.strength, 0.30))
        details.append(
            f"divergence {DIVERGENCE_FR.get(div.kind, div.kind)} "
            f"(force {div.strength:.2f}, il y a {div.bars_ago} barres)"
        )

    willr = last_valid(ind.willr)
    if willr is not None:
        if willr > -12:
            parts.append((-0.6, 0.10))
        elif willr < -88:
            parts.append((0.6, 0.10))

    total_weight = sum(w for _, w in parts) or 1.0
    value = clamp(sum(v * w for v, w in parts) / total_weight, -1.0, 1.0)
    return Component("meanrev", round(value, 3), 0.0, details)


def build_timeframe_view(timeframe: str, ind: IndicatorSet, structure: StructureView,
                         regime: Regime, role: str) -> TimeframeView:
    if regime.favors_trend:
        weights = COMPONENT_WEIGHTS["tendance"]
    elif regime.favors_fade:
        weights = COMPONENT_WEIGHTS["range"]
    else:
        weights = COMPONENT_WEIGHTS["neutre"]

    components = {
        "trend": _score_trend(ind),
        "momentum": _score_momentum(ind),
        "structure": _score_structure(ind, structure),
        "participation": _score_participation(ind, regime),
        "meanrev": _score_meanrev(ind),
    }
    for name, component in components.items():
        component.weight = weights[name]

    score = clamp(sum(c.contribution for c in components.values()), -1.0, 1.0)
    return TimeframeView(timeframe, ind, structure, regime, components, round(score, 3), role)


# --------------------------------------------------------------------------- #
# Fusion multi-timeframe
# --------------------------------------------------------------------------- #

@dataclass
class Modifier:
    """Ajustement du score fusionne.

    Deux natures, et la distinction est critique :

      "additif"     : deplace le score (fondamental, flux). Peut legitimement
                      changer le sens si la contradiction est forte.
      "atténuation" : facteur multiplicatif dans ]0, 1]. Reduit la CONVICTION
                      sans jamais pouvoir inverser le sens.

    Melanger les deux est un bug classique : une pénalité additive signee
    appliquee à un score faible le fait basculer de l'autre cote, et l'outil
    recommandé alors exactement l'inverse de ce qu'il a mesuré.
    """

    name: str
    kind: str             # "additif" | "atténuation"
    value: float          # delta signe, ou facteur multiplicatif
    detail: str

    @property
    def display(self) -> str:
        return f"{self.value:+.3f}" if self.kind == "additif" else f"x{self.value:.2f}"


@dataclass
class Confluence:
    direction: int                 # +1 long, -1 short, 0 pas de trade
    raw_score: float               # fusion des timeframes, [-1, +1]
    final_score: float             # après modificateurs, [-1, +1]
    confidence: float              # 0..100
    views: dict[str, TimeframeView]
    modifiers: list[Modifier] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    alignment: float = 0.0         # 0..1, accord entre timeframes
    turbo: bool = False
    style: str = "suivi"           # suivi | fade

    @property
    def side(self) -> str:
        return "ACHAT" if self.direction > 0 else "VENTE" if self.direction < 0 else "AUCUN"

    @property
    def blocked(self) -> bool:
        return bool(self.vetoes)


def fuse(views: dict[str, TimeframeView], fundamental: FundamentalView, micro: MicroView,
         session: SessionInfo, calibration_quality: float,
         min_confidence: float = 55.0, allow_counter_trend: bool = False) -> Confluence:
    """Fusionne tout en un signal unique, tracable et defendable."""
    present = {tf: v for tf, v in views.items() if tf in TF_BASE_WEIGHTS}
    if not present:
        return Confluence(0, 0.0, 0.0, 0.0, views, vetoes=["aucun timeframe exploitable"])

    context = present.get("M15")
    weights = dict(TF_BASE_WEIGHTS)

    # En tendance nette sur M15, le contexte prend le pas ; en range, le
    # timing M1 devient l'élément décisif.
    if context is not None:
        if context.regime.favors_trend:
            weights = {"M15": 0.48, "M5": 0.34, "M1": 0.18}
        elif context.regime.favors_fade:
            weights = {"M15": 0.30, "M5": 0.32, "M1": 0.38}

    usable = {tf: w for tf, w in weights.items() if tf in present}
    total_weight = sum(usable.values()) or 1.0
    raw = sum(present[tf].score * w for tf, w in usable.items()) / total_weight

    # Alignement : les timeframes racontent-ils la même histoire ?
    signs = [present[tf].direction for tf in usable if present[tf].direction != 0]
    if signs:
        dominant = 1 if sum(signs) > 0 else -1
        alignment = sum(1 for s in signs if s == dominant) / len(usable)
    else:
        alignment = 0.0

    modifiers: list[Modifier] = []
    reasons: list[str] = []
    warnings: list[str] = []
    vetoes: list[str] = []

    direction_hint = 1 if raw > 0 else -1

    # -- alignement -------------------------------------------------------- #
    if alignment >= 0.99 and len(usable) >= 3:
        modifiers.append(Modifier("alignement", "additif", 0.12 * direction_hint,
                                  "les 3 timeframes pointent dans le même sens"))
    elif context is not None and "M1" in present:
        if context.direction != 0 and present["M1"].direction != 0 and context.direction != present["M1"].direction:
            modifiers.append(Modifier("conflit M15/M1", "attenuation", 0.80,
                                      "le déclencheur M1 contredit le contexte M15"))
            warnings.append("M1 et M15 divergent : signal de contre-tendance, taille réduite conseillée")

    # -- contre-tendance --------------------------------------------------- #
    if context is not None and context.regime.label == "tendance_forte":
        if direction_hint != 0 and context.regime.direction != 0 and direction_hint != context.regime.direction:
            if allow_counter_trend:
                modifiers.append(Modifier("contre-tendance", "attenuation", 0.60,
                                          "position contre une tendance M15 forte"))
                warnings.append("Contre une tendance M15 forte : historiquement le plus mauvais pari du scalpeur")
            else:
                vetoes.append(
                    "Signal contre une tendance M15 forte "
                    f"({'haussière' if context.regime.direction > 0 else 'baissière'}). "
                    "Utilise --allow-counter-trend pour l'autoriser."
                )

    # -- fondamental ------------------------------------------------------- #
    if fundamental.confidence >= 0.25:
        delta = fundamental.effective_score * 0.18
        modifiers.append(Modifier("fondamental", "additif", delta,
                                  f"{fundamental.regime_label} (score {fundamental.score:+.2f}, "
                                  f"confiance {fundamental.confidence:.0%})"))
        if abs(fundamental.effective_score) > 0.3:
            reasons.append(f"Macro : {fundamental.regime_label}")
        top = fundamental.top_drivers(2)
        for driver in top:
            reasons.append(f"Macro : {driver.explain()}")
    else:
        warnings.append("Données macro insuffisantes : le signal est purement technique")

    # -- microstructure ---------------------------------------------------- #
    micro_score = micro.score
    if abs(micro_score) > 0.05:
        modifiers.append(Modifier("microstructure", "additif", micro_score * 0.14,
                                  "; ".join(micro.summary()) or f"flux {micro_score:+.2f}"))
        for line in micro.summary()[:2]:
            reasons.append(f"Flux : {line}")
    if micro.flow.absorption > 0.5:
        warnings.append("Absorption détectée : gros volumes sans progression du prix, cassure suspecte")

    # -- session ----------------------------------------------------------- #
    if session.is_prime:
        modifiers.append(Modifier("session", "additif", 0.06 * direction_hint,
                                  f"session {session.name} - liquidité optimale"))
    elif session.is_poor:
        modifiers.append(Modifier("session", "attenuation", 0.78,
                                  f"session {session.name} - {session.advice}"))
        warnings.append(f"Session {session.name} : {session.advice}")

    # -- volatilité exploitable -------------------------------------------- #
    driver_tf = present.get("M5") or present.get("M1")
    if driver_tf is not None and driver_tf.regime.volatility_state == "basse":
        modifiers.append(Modifier("volatilité", "attenuation", 0.70,
                                  "volatilité au plancher, le mouvement ne paiera pas le spread"))
        warnings.append("Volatilité basse : le ratio gain/spread se dégrade fortement")
    if driver_tf is not None and driver_tf.regime.label == "chaos":
        vetoes.append("Régime chaotique : beaucoup de mouvement, aucune direction exploitable")

    # -- news -------------------------------------------------------------- #
    if fundamental.news is not None and fundamental.news.blocks_trading:
        vetoes.append(f"Fenetre news : {fundamental.news.reason}")
    elif fundamental.news is not None and fundamental.news.level == "prudence":
        warnings.append(fundamental.news.reason)

    # -- calibration ------------------------------------------------------- #
    if calibration_quality < 40:
        warnings.append(
            f"Calibration MT5 faible ({calibration_quality:.0f}/100) : "
            "les niveaux peuvent etre décalés de plusieurs dollars"
        )

    # Les deltas additifs deplacent le score ; les atténuations n'en reduisent
    # que l'amplitude. Une pénalité ne peut donc jamais retourner le signal.
    additive = sum(m.value for m in modifiers if m.kind == "additif")
    attenuation = 1.0
    for modifier in modifiers:
        if modifier.kind == "attenuation":
            attenuation *= modifier.value
    final = clamp((raw + additive) * attenuation, -1.0, 1.0)

    # -- confiance --------------------------------------------------------- #
    # Échelle : un score fusionne de 0.50 correspond à une configuration
    # serieuse et doit sortir autour de 60/100 une fois alignee. Un facteur
    # 100 laissait tous les vrais signaux sous le seuil.
    confidence = clamp(abs(final) * 125.0, 0.0, 100.0)
    confidence *= 0.55 + 0.45 * alignment                 # l'accord MTF compte double
    if context is not None and context.regime.favors_trend and context.direction == (1 if final > 0 else -1):
        confidence *= 1.10
    confidence *= clamp(0.75 + calibration_quality / 400.0, 0.75, 1.0)
    confidence *= clamp(0.80 + session.volatility_factor * 0.16, 0.80, 1.06)
    confidence = round(clamp(confidence, 0.0, 100.0), 1)

    direction = 0
    if not vetoes and confidence >= min_confidence:
        direction = 1 if final > 0 else -1 if final < 0 else 0

    style = "fade"
    if context is not None and context.regime.favors_trend:
        style = "suivi"
    elif driver_tf is not None and driver_tf.regime.favors_trend:
        style = "suivi"

    turbo = bool(
        direction != 0
        and alignment >= 0.99
        and confidence >= 78
        and session.is_prime
        and driver_tf is not None
        and driver_tf.regime.volatility_state in ("haute", "extreme")
        and abs(micro_score) > 0.15
        and (micro_score > 0) == (direction > 0)
    )

    # Insertion en tête dans l'ordre inverse : le lecteur voit d'abord le
    # contexte M15, puis la configuration M5, puis le déclencheur M1.
    for tf in ("M1", "M5", "M15"):
        if tf in present:
            reasons = present[tf].top_reasons(2) + reasons

    return Confluence(
        direction=direction,
        raw_score=round(raw, 3),
        final_score=round(final, 3),
        confidence=confidence,
        views=views,
        modifiers=modifiers,
        reasons=reasons,
        warnings=warnings,
        vetoes=vetoes,
        alignment=round(alignment, 3),
        turbo=turbo,
        style=style,
    )
