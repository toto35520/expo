"""Construction du plan de trade : entrée, stop, TP1, TP2, taille, gestion.

Regles non negociables appliquees ici :

  1. Le stop est place ou la thèse est INVALIDEE (sous une structure), pas a
     une distance ronde arbitraire.
  2. Le spread est intégré partout : on achete a l'ask, on vend au bid, et
     un TP se juge sur le prix qui le declenche reellement.
  3. Un trade dont le TP1 n'atteint pas le R:R minimal est refuse. Un bon
     signal avec un mauvais R:R reste un mauvais trade.
  4. La taille découle du stop, jamais l'inverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from goldscalp.config import MarketConfig, RiskConfig
from goldscalp.core.calibration import Calibration
from goldscalp.core.indicators import IndicatorSet, last_valid
from goldscalp.core.regime import Regime, SessionInfo
from goldscalp.core.scoring import Confluence
from goldscalp.core.structure import Level, StructureView
from goldscalp.util import clamp, safe_div


@dataclass
class Target:
    label: str
    price: float
    distance: float
    r_multiple: float
    share: float
    rationale: str


@dataclass
class TradePlan:
    side: str                       # ACHAT | VENTE
    entry: float
    entry_type: str                 # marché | limite
    entry_zone: tuple[float, float]
    stop: float
    stop_distance: float
    targets: list[Target]
    lots: float
    risk_amount: float
    reward_tp1: float
    reward_tp2: float
    spread: float
    rr1: float
    rr2: float
    expectancy_r: float
    management: list[str] = field(default_factory=list)
    invalidation: str = ""
    notes: list[str] = field(default_factory=list)
    valid: bool = True
    rejection: str = ""
    grade: str = "-"                                # A, B ou C
    grade_reasons: list[str] = field(default_factory=list)

    @property
    def grade_label(self) -> str:
        return {
            "A": "configuration de premier choix",
            "B": "configuration correcte",
            "C": "configuration limite - taille réduite",
        }.get(self.grade, "non noté")

    @property
    def tp1(self) -> Optional[Target]:
        return self.targets[0] if self.targets else None

    @property
    def tp2(self) -> Optional[Target]:
        return self.targets[1] if len(self.targets) > 1 else None


def _candidate_levels(structure: StructureView, ind: IndicatorSet, price: float,
                      direction: int) -> list[tuple[float, str, float]]:
    """Tous les prix ou le marché à une raison de s'arrêter, dans le sens du trade.

    Renvoie (prix, justification, solidité). La solidité compte autant que la
    distance : viser le premier chiffre rond venu place les TP sur des niveaux
    que rien ne defend, et le prix les traverse sans ralentir.
    """
    out: list[tuple[float, str, float]] = []

    levels: list[Level] = structure.levels_above(price, 10) if direction > 0 else structure.levels_below(price, 10)
    for level in levels:
        out.append((level.price, f"niveau {level.label or level.kind} (force {level.strength:.2f})", level.strength))

    # Les poches de liquidité sont les meilleures cibles : c'est la que sont
    # les stops des autres, donc la que le prix est aspire.
    pools = structure.liquidity_above if direction > 0 else structure.liquidity_below
    for pool in pools:
        out.append((pool, "poche de liquidité (stops accumulés)", 0.88))

    if ind.profile is not None:
        for value, name, weight in ((ind.profile.poc, "POC", 0.80),
                                    (ind.profile.vah, "Value Area High", 0.72),
                                    (ind.profile.val, "Value Area Low", 0.72)):
            if (direction > 0 and value > price) or (direction < 0 and value < price):
                out.append((value, f"{name} du profil de volume", weight))

    for value, name, weight in ((last_valid(ind.vwap), "VWAP", 0.78),
                                (last_valid(ind.vwap_upper), "VWAP +1 sigma", 0.58),
                                (last_valid(ind.vwap_lower), "VWAP -1 sigma", 0.58)):
        if value is not None and ((direction > 0 and value > price) or (direction < 0 and value < price)):
            out.append((value, name, weight))

    fib_weights = {"0.618": 0.62, "0.5": 0.58, "0.382": 0.52, "1.272": 0.66, "1.618": 0.68}
    for name, value in structure.fib.items():
        if (direction > 0 and value > price) or (direction < 0 and value < price):
            out.append((value, f"Fibonacci {name}", fib_weights.get(name, 0.45)))

    bb = last_valid(ind.bb_upper) if direction > 0 else last_valid(ind.bb_lower)
    if bb is not None and ((direction > 0 and bb > price) or (direction < 0 and bb < price)):
        out.append((bb, "bande de Bollinger", 0.55))

    # Tri par proximité, deduplication en gardant le plus solide du groupe.
    out.sort(key=lambda item: abs(item[0] - price))
    unique: list[tuple[float, str, float]] = []
    tolerance = max(ind.atr_value * 0.18, price * 0.00012)
    for value, label, weight in out:
        for index, (kept, kept_label, kept_weight) in enumerate(unique):
            if abs(value - kept) <= tolerance:
                if weight > kept_weight:
                    # Confluence : deux raisons au même prix renforcent la cible.
                    unique[index] = (kept, f"{label} + {kept_label}"[:70], min(1.0, weight + 0.08))
                else:
                    unique[index] = (kept, kept_label, min(1.0, kept_weight + 0.08))
                break
        else:
            unique.append((value, label, weight))
    return unique


def _structural_stop(structure: StructureView, ind: IndicatorSet, entry: float,
                     direction: int, buffer_value: float) -> tuple[Optional[float], str]:
    """Stop sous la dernière structure qui porte la thèse."""
    if direction > 0:
        anchors = [p for p in (structure.swing_low, structure.range_low) if p is not None and p < entry]
        supports = [l.price for l in structure.levels_below(entry, 3)]
        anchors.extend(supports)
        if not anchors:
            return None, ""
        chosen = max(anchors)              # le plus proche sous le prix
        return chosen - buffer_value, f"sous le support structurel {chosen:.2f}"
    anchors = [p for p in (structure.swing_high, structure.range_high) if p is not None and p > entry]
    resistances = [l.price for l in structure.levels_above(entry, 3)]
    anchors.extend(resistances)
    if not anchors:
        return None, ""
    chosen = min(anchors)
    return chosen + buffer_value, f"au-dessus de la résistance structurelle {chosen:.2f}"


def _entry_zone(ind_m1: IndicatorSet, structure_m5: StructureView, price: float,
                direction: int, atr_m5: float, style: str, turbo: bool) -> tuple[float, str, tuple[float, float]]:
    """Determine le prix d'entrée et son type.

    En turbo on prend le marché : attendre un repli fait rater le mouvement.
    Sinon on vise un repli sur EMA21 M1 ou un retracement de Fibonacci,
    a condition qu'il reste à portée (moins de 0.8 ATR M5).
    """
    if turbo:
        return price, "marché", (price, price)

    candidates: list[float] = []
    ema21 = last_valid(ind_m1.ema21)
    if ema21 is not None:
        candidates.append(ema21)
    vwap_v = last_valid(ind_m1.vwap)
    if vwap_v is not None:
        candidates.append(vwap_v)
    for name in ("0.382", "0.5"):
        if name in structure_m5.fib:
            candidates.append(structure_m5.fib[name])

    if direction > 0:
        pullbacks = [c for c in candidates if c < price]
        best = max(pullbacks) if pullbacks else None
    else:
        pullbacks = [c for c in candidates if c > price]
        best = min(pullbacks) if pullbacks else None

    max_distance = atr_m5 * 0.8
    if best is None or abs(price - best) > max_distance or abs(price - best) < atr_m5 * 0.05:
        return price, "marché", (price, price)

    low, high = (best, price) if direction > 0 else (price, best)
    return best, "limite", (round(low, 2), round(high, 2))


def build_plan(confluence: Confluence, calibration: Calibration, risk: RiskConfig,
               market: MarketConfig, session: SessionInfo,
               news_multiplier: float = 1.0, spread_override: Optional[float] = None,
               win_rates: Optional[tuple[float, float]] = None) -> TradePlan:
    """Assemble le plan complet. Les prix sont déjà en référentiel MT5."""
    direction = confluence.direction
    side = "ACHAT" if direction > 0 else "VENTE"

    view_m5 = confluence.views.get("M5") or confluence.views.get("M1")
    view_m1 = confluence.views.get("M1") or view_m5
    if view_m5 is None or view_m1 is None:
        return rejected_plan("aucun timeframe exploitable pour construire le plan")

    ind_m5, ind_m1 = view_m5.indicators, view_m1.indicators
    structure_m5 = view_m5.structure
    regime: Regime = view_m5.regime
    atr_m5 = ind_m5.atr_value
    price = ind_m1.price
    spread = spread_override if spread_override is not None else calibration.spread

    if spread > risk.max_spread:
        return rejected_plan(
            f"spread de {spread:.2f}$ supérieur au plafond de {risk.max_spread:.2f}$ - "
            "le coût d'entrée mange la cible"
        )

    # -- entrée ------------------------------------------------------------- #
    mid_entry, entry_type, zone = _entry_zone(
        ind_m1, structure_m5, price, direction, atr_m5, confluence.style, confluence.turbo
    )
    # On achete a l'ask, on vend au bid.
    entry = calibration.ask(mid_entry) if direction > 0 else calibration.bid(mid_entry)

    # -- stop ---------------------------------------------------------------#
    buffer_value = max(atr_m5 * risk.stop_buffer_atr, spread * 1.5)
    structural, stop_reason = _structural_stop(structure_m5, ind_m5, mid_entry, direction, buffer_value)
    atr_stop_distance = atr_m5 * regime.stop_multiplier
    atr_stop = mid_entry - atr_stop_distance if direction > 0 else mid_entry + atr_stop_distance

    if structural is None:
        stop_mid = atr_stop
        stop_reason = f"{atr_stop_distance:.2f}$ ({regime.stop_multiplier:.2f} x ATR M5), aucune structure proche"
    elif direction > 0:
        stop_mid = min(structural, atr_stop)
        stop_reason = stop_reason if structural <= atr_stop else f"{atr_stop_distance:.2f}$ (ATR M5)"
    else:
        stop_mid = max(structural, atr_stop)
        stop_reason = stop_reason if structural >= atr_stop else f"{atr_stop_distance:.2f}$ (ATR M5)"

    # Bornes : ni un stop ridicule qui saute sur le bruit, ni un stop enorme.
    min_distance = max(atr_m5 * risk.min_stop_atr, spread * 3.0)
    max_distance = atr_m5 * risk.max_stop_atr
    if confluence.turbo:
        # Un scalp turbo dure quelques minutes. Lui accorder 2 ATR M5 de stop,
        # c'est risquer une heure de range sur un trade censé en durer dix : le
        # stop doit s'aligner sur l'horizon réel du trade, donc sur l'ATR M1.
        max_distance = min(max_distance, max(ind_m1.atr_value * 1.6, spread * 5.0))
        min_distance = min(min_distance, max_distance * 0.85)
    raw_distance = abs(mid_entry - stop_mid)
    distance = clamp(raw_distance, min_distance, max_distance)
    if abs(distance - raw_distance) > 1e-9:
        stop_reason += (
            f" (ajusté au plancher {min_distance:.2f}$)" if distance > raw_distance
            else f" (ajusté au plafond {max_distance:.2f}$)"
        )
    stop_mid = mid_entry - distance if direction > 0 else mid_entry + distance
    # Le stop se declenche au bid en achat, a l'ask en vente : on l'ecarte du spread.
    stop = calibration.bid(stop_mid) if direction > 0 else calibration.ask(stop_mid)
    stop_distance = abs(entry - stop)

    if stop_distance <= 0:
        return rejected_plan("distance de stop nulle - données incoherentes")

    # -- cibles -------------------------------------------------------------#
    candidates = _candidate_levels(structure_m5, ind_m5, mid_entry, direction)
    targets: list[Target] = []

    def r_of(target_price: float) -> float:
        return abs(target_price - entry) / stop_distance

    # TP1 : le premier obstacle serieux qui paie au moins le R:R minimal.
    tp1_price: Optional[float] = None
    tp1_reason = ""
    # Deux passés : on exigé d'abord un niveau solide, on assouplit ensuite.
    # Un TP pose sur un niveau que rien ne defend n'est pas un TP, c'est un
    # nombre.
    for min_strength in (0.50, 0.32):
        for value, label, strength in candidates:
            if strength < min_strength:
                continue
            # La sortie se fait au bid en achat : la cible doit etre atteinte
            # par le prix qui declenche reellement l'ordre.
            exit_price = calibration.bid(value) if direction > 0 else calibration.ask(value)
            ratio = r_of(exit_price)
            if risk.min_rr_tp1 <= ratio <= 3.0:
                tp1_price, tp1_reason = exit_price, label
                break
        if tp1_price is not None:
            break

    if tp1_price is None:
        distance_tp1 = stop_distance * risk.target_rr_tp1 * regime.target_multiplier
        tp1_price = entry + distance_tp1 if direction > 0 else entry - distance_tp1
        tp1_reason = f"projection {risk.target_rr_tp1:.1f}R ajustée au régime ({regime.label})"

    rr1 = r_of(tp1_price)
    if rr1 < risk.min_rr_tp1:
        return rejected_plan(
            f"aucune cible n'offre le R:R minimal de {risk.min_rr_tp1:.1f} "
            f"(meilleure trouvee : {rr1:.2f}R) - le prix est collé à un obstacle"
        )

    targets.append(
        Target("TP1", round(tp1_price, market.digits), abs(tp1_price - entry), round(rr1, 2),
               risk.tp1_share, tp1_reason)
    )

    # TP2 : l'obstacle suivant, au minimum a target_rr_tp2.
    tp2_price: Optional[float] = None
    tp2_reason = ""
    for value, label, strength in candidates:
        if strength < 0.50:
            continue
        exit_price = calibration.bid(value) if direction > 0 else calibration.ask(value)
        if direction > 0 and exit_price <= tp1_price * 1.0001:
            continue
        if direction < 0 and exit_price >= tp1_price * 0.9999:
            continue
        ratio = r_of(exit_price)
        if ratio >= max(risk.target_rr_tp2 * 0.7, rr1 + 0.5):
            tp2_price, tp2_reason = exit_price, label
            break

    if tp2_price is None:
        # Projection de la jambe d'impulsion (mouvement mesuré), sinon R:R cible.
        measured = None
        if structure_m5.leg_high is not None and structure_m5.leg_low is not None:
            leg = structure_m5.leg_high - structure_m5.leg_low
            measured = entry + leg * 0.8 if direction > 0 else entry - leg * 0.8
        fallback_distance = stop_distance * risk.target_rr_tp2 * regime.target_multiplier
        projected = entry + fallback_distance if direction > 0 else entry - fallback_distance
        if measured is not None and r_of(measured) >= rr1 + 0.5:
            tp2_price = measured
            tp2_reason = "mouvement mesuré (projection de la jambe d'impulsion)"
        else:
            tp2_price = projected
            tp2_reason = f"projection {risk.target_rr_tp2:.1f}R ajustée au régime"

    rr2 = r_of(tp2_price)
    targets.append(
        Target("TP2", round(tp2_price, market.digits), abs(tp2_price - entry), round(rr2, 2),
               round(1.0 - risk.tp1_share, 3), tp2_reason)
    )

    # -- taille -------------------------------------------------------------#
    risk_pct = min(risk.risk_pct, risk.max_risk_pct)
    risk_amount = risk.account_balance * risk_pct / 100.0
    risk_amount *= news_multiplier

    # Modulation par la confiance : un signal a 60 % ne merite pas la même
    # taille qu'un signal a 90 %.
    confidence_factor = clamp(0.55 + (confluence.confidence - 50.0) / 100.0, 0.55, 1.15)
    risk_amount *= confidence_factor

    value_per_unit = market.contract_size          # $ gagnes par lot et par $ de mouvement
    raw_lots = safe_div(risk_amount, stop_distance * value_per_unit, 0.0)
    lots = min(round(raw_lots, 2), risk.max_lots)
    if lots < 0.01:
        return rejected_plan(
            f"taille calculee inférieure au lot minimum (0.01) : avec {risk_amount:.2f}$ de risque "
            f"et un stop de {stop_distance:.2f}$, il faudrait {raw_lots:.4f} lot. "
            "Augmente le capital ou le pourcentage de risque."
        )

    effective_risk = lots * stop_distance * value_per_unit
    reward_tp1 = lots * risk.tp1_share * targets[0].distance * value_per_unit
    reward_tp2 = lots * (1 - risk.tp1_share) * targets[1].distance * value_per_unit

    # -- espérance ----------------------------------------------------------#
    if win_rates is not None and win_rates[0] > 0:
        p1, p2 = win_rates
    else:
        # Modele de référence : sur une marché aléatoire, la probabilité
        # d'atteindre +kR avant -1R vaut 1/(1+k). L'edge du moteur deplace
        # cette base, la confiance en fixe l'ampleur. Faire dépendre la
        # probabilité de la seule confiance produit des aberrations : un TP1
        # a 2.8R annoncé a 72 % de reussite est une promesse intenable.
        edge = clamp((confluence.confidence - 55.0) / 100.0 * 0.20, -0.10, 0.20)
        p1 = clamp(1.0 / (1.0 + rr1) + edge, 0.10, 0.80)
        p2 = clamp(1.0 / (1.0 + rr2) + edge * 0.7, 0.05, min(p1, 0.60))
    # Decomposition des issues :
    #   - TP2 atteint            -> part1 x rr1 + part2 x rr2
    #   - TP1 seul puis stop a BE -> part1 x rr1 (le reliquat sort à zéro)
    #   - stop direct            -> -1 R
    tp1_only = max(p1 - p2, 0.0)
    loss_probability = max(0.0, 1.0 - p1)
    expectancy = (
        p2 * (risk.tp1_share * rr1 + (1 - risk.tp1_share) * rr2)
        + tp1_only * risk.tp1_share * rr1
        - loss_probability * 1.0
    )

    # Un plan géométriquement valide mais d'espérance nulle n'est pas un
    # trade : c'est une occasion de payer le spread. On le refuse ici plutôt
    # que de le proposer et de laisser l'utilisateur faire le tri.
    if expectancy < risk.min_expectancy_r:
        return rejected_plan(
            f"espérance de {expectancy:+.2f} R sous le plancher de "
            f"{risk.min_expectancy_r:+.2f} R — le gain attendu ne paie pas le risque"
        )

    # -- note de qualité ------------------------------------------------------#
    # Quatre critères objectifs, pour que la différence entre une très bonne
    # configuration et une configuration limite se voie d'un coup d'œil.
    criteria = {
        "confiance directionnelle": confluence.confidence >= 70,
        "accord des timeframes": confluence.alignment >= 0.99,
        f"TP1 au-dessus de {risk.target_rr_tp1:.1f}R": rr1 >= risk.target_rr_tp1,
        "espérance supérieure à 0.35 R": expectancy >= 0.35,
    }
    met = [name for name, ok in criteria.items() if ok]
    missing = [name for name, ok in criteria.items() if not ok]
    grade = "A" if len(met) >= 4 else "B" if len(met) >= 2 else "C"

    # -- gestion ------------------------------------------------------------#
    management = [
        f"Sortir {risk.tp1_share:.0%} de la position à TP1 ({targets[0].price:.2f}).",
        f"Dès TP1 touché, remonter le stop à l'entrée + spread "
        f"({calibration.ask(entry) if direction > 0 else calibration.bid(entry):.2f}) : le trade devient gratuit.",
        f"Suivre le reste sous l'EMA9 M1 ou à {regime.stop_multiplier:.2f} x ATR, "
        f"en ne relâchant jamais le stop.",
        f"Stop temporel : si TP1 n'est pas touché en {_time_stop_bars(regime)} bougies M1, sortir au marché - "
        "la thèse avait une durée de vie, elle est expirée.",
    ]
    if session.minutes_to_next < 25:
        management.append(
            f"Changement de session dans {session.minutes_to_next} min "
            f"(vers {_next_session_name(session)}) : la volatilité va changer de régime."
        )
    if confluence.turbo:
        management.insert(0, "Mode TURBO : entrée au marché, ne pas attendre de repli.")

    invalidation = (
        f"Thèse invalidée si le prix clôture {'sous' if direction > 0 else 'au-dessus de'} "
        f"{stop_mid:.2f} en M5, ou si la structure M15 passe "
        f"{'baissière' if direction > 0 else 'haussière'}."
    )

    notes: list[str] = []
    if entry_type == "limite":
        notes.append(
            f"Ordre LIMITE à {entry:.2f} : si le prix part sans toi, laisse-le partir. "
            "Courir après un repli manque est la première source de pertes en scalp."
        )
    if news_multiplier < 1.0:
        notes.append(f"Taille réduite a {news_multiplier:.0%} en raison du calendrier économique.")
    if confidence_factor < 0.8:
        notes.append(f"Taille réduite a {confidence_factor:.0%} : confiance du signal moderee.")

    return TradePlan(
        side=side,
        entry=round(entry, market.digits),
        entry_type=entry_type,
        entry_zone=zone,
        stop=round(stop, market.digits),
        stop_distance=round(stop_distance, market.digits),
        targets=targets,
        lots=lots,
        risk_amount=round(effective_risk, 2),
        reward_tp1=round(reward_tp1, 2),
        reward_tp2=round(reward_tp2, 2),
        spread=round(spread, market.digits),
        rr1=round(rr1, 2),
        rr2=round(rr2, 2),
        expectancy_r=round(expectancy, 3),
        management=management,
        invalidation=invalidation,
        notes=notes,
        valid=True,
        grade=grade,
        grade_reasons=(
            [f"acquis : {', '.join(met)}"] if met else []
        ) + ([f"manque : {', '.join(missing)}"] if missing else []),
    )


def _time_stop_bars(regime: Regime) -> int:
    if regime.label == "tendance_forte":
        return 25
    if regime.favors_trend:
        return 20
    return 12


def _next_session_name(session: SessionInfo) -> str:
    from goldscalp.core.regime import SESSIONS

    names = [s[0] for s in SESSIONS]
    try:
        index = names.index(session.name)
    except ValueError:
        return "?"
    return names[(index + 1) % len(names)]


def rejected_plan(reason: str) -> TradePlan:
    """Plan refuse, avec la raison lisible du refus."""
    return TradePlan(
        side="AUCUN", entry=0.0, entry_type="-", entry_zone=(0.0, 0.0), stop=0.0,
        stop_distance=0.0, targets=[], lots=0.0, risk_amount=0.0, reward_tp1=0.0,
        reward_tp2=0.0, spread=0.0, rr1=0.0, rr2=0.0, expectancy_r=0.0,
        valid=False, rejection=reason,
    )
