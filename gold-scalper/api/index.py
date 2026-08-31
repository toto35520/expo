"""Fonction serverless Vercel exposant le moteur goldscalp en JSON.

Contraintes du serverless, et comment elles sont traitees :

  - Systeme de fichiers en LECTURE SEULE hors /tmp.
    -> GOLDSCALP_HOME est force sur /tmp AVANT tout import du paquet.

  - Aucune persistance entre invocations.
    -> La calibration ne peut pas etre lue sur disque. Elle arrive par
       paramètres d'URL ou par variables d'environnement du projet.

  - Pas de terminal MetaTrader 5.
    -> Le pont MT5 est désactivé ; on travaille sur les prix Bybit recales.

  - Budget de temps limite.
    -> Volumes de bougies reduits par rapport au mode ligne de commande, et
       caché disque dans /tmp reutilise entre deux invocations à chaud.

  - Bybit filtre les adresses IP americaines.
    -> vercel.json épingle la region sur fra1 (Francfort). Voir le README.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# --- doit preceder tout import de goldscalp -------------------------------- #
os.environ.setdefault("GOLDSCALP_HOME", "/tmp/goldscalp")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from goldscalp import __version__, engine                       # noqa: E402
from goldscalp.cli import to_payload                            # noqa: E402
from goldscalp.config import Config                             # noqa: E402
from goldscalp.core.calibration import Anchor, Calibration, add_anchor  # noqa: E402
from goldscalp.core.plan import build_plan                        # noqa: E402
from goldscalp.util import setup_logging                        # noqa: E402

setup_logging(os.environ.get("GOLDSCALP_LOG", "warn"))

# Volumes reduits : en serverless, chaque bougie supplementaire est du temps
# d'exécution facture et un risque de depassement.
WEB_BARS = {"M1": 500, "M5": 400, "M15": 300, "D1": 60}


def _first(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = params.get(key)
    return values[0] if values else default


def _as_float(params: dict[str, list[str]], key: str, default: float | None = None) -> float | None:
    raw = _first(params, key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"paramètre '{key}' invalidé : {raw!r} n'est pas un nombre")


def _as_bool(params: dict[str, list[str]], key: str, default: bool) -> bool:
    raw = _first(params, key)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "oui", "yes", "on")


def build_calibration(params: dict[str, list[str]]) -> tuple[Calibration, list[str]]:
    """Reconstruit la calibration sans disque.

    Trois voies, par ordre de priorité :
      1. un ancrage complet (bybit + bid + ask) passe dans l'URL ;
      2. alpha / beta / spread passés dans l'URL ;
      3. les variables d'environnement du projet Vercel.
    """
    notes: list[str] = []

    bybit = _as_float(params, "bybit")
    bid = _as_float(params, "bid")
    ask = _as_float(params, "ask")
    if bybit and bid and ask:
        return add_anchor(Calibration(), bybit, bid, ask, source="web"), notes

    alpha = _as_float(params, "alpha")
    beta = _as_float(params, "beta")
    spread = _as_float(params, "spread")

    if alpha is None and os.environ.get("GOLDSCALP_ALPHA"):
        try:
            alpha = float(os.environ["GOLDSCALP_ALPHA"])
        except ValueError:
            notes.append("Variable GOLDSCALP_ALPHA illisible, ignoree.")
    if beta is None and os.environ.get("GOLDSCALP_BETA"):
        try:
            beta = float(os.environ["GOLDSCALP_BETA"])
        except ValueError:
            notes.append("Variable GOLDSCALP_BETA illisible, ignoree.")
    if spread is None and os.environ.get("GOLDSCALP_SPREAD"):
        try:
            spread = float(os.environ["GOLDSCALP_SPREAD"])
        except ValueError:
            notes.append("Variable GOLDSCALP_SPREAD illisible, ignoree.")

    if alpha is None:
        notes.append(
            "AUCUNE CALIBRATION : les prix renvoyes sont des prix Bybit bruts, "
            "décalés de plusieurs dollars par rapport à ton broker. Renseigne "
            "alpha (et spread) avant d'exploiter ces niveaux."
        )
        return Calibration(), notes

    # Le référentiel change tout : un alpha de +0.15 est un markup broker
    # (durable), un alpha de +7.35 est un écart brut à Bybit (périssable).
    # Les confondre décalerait tous les prix de la prime XAUT entière.
    reference = (_first(params, "ref") or os.environ.get("GOLDSCALP_REF") or "bybit").lower()
    if reference not in ("index", "spot", "bybit"):
        reference = "bybit"

    calibration = Calibration(
        alpha=alpha,
        beta=beta if beta else 1.0,
        spread=spread if spread else 0.30,
        reference=reference,
        note=f"calibration fournie par l'appelant (web, référentiel {reference})",
    )
    # Sans ancrage horodaté, quality() vaudrait 0 et le moteur degraderait la
    # confiance. On pose un ancrage synthetique cohérent avec alpha/beta pour
    # que la calibration soit consideree comme fournie, tout en gardant la
    # trace de son origine déclarative.
    from goldscalp.util import now_ms

    pivot = 2400.0
    mid = calibration.to_mt5(pivot)
    calibration.anchors = [
        Anchor(now_ms(), pivot, mid - calibration.spread / 2,
               mid + calibration.spread / 2, source="declare",
               spot=pivot if reference in ("index", "spot") else None)
    ]
    notes.append(
        "Calibration déclarative (alpha/beta fournis) : elle n'a pas été "
        "vérifiée contre un tick MT5 réel. Recalibre depuis MT5 régulièrement."
    )
    return calibration, notes


def build_config(params: dict[str, list[str]]) -> Config:
    config = Config()
    config.engine.bars = dict(WEB_BARS)

    balance = _as_float(params, "balance")
    if balance is not None:
        config.risk.account_balance = balance
    risk_pct = _as_float(params, "risk")
    if risk_pct is not None:
        config.risk.risk_pct = risk_pct
    min_confidence = _as_float(params, "min_confidence")
    if min_confidence is not None:
        config.engine.min_confidence = min_confidence

    symbol = _first(params, "symbol")
    if symbol:
        config.market.mt5_symbol = symbol
    bybit_symbol = _first(params, "bybit_symbol")
    if bybit_symbol:
        config.market.bybit_symbol = bybit_symbol
    yahoo_symbol = _first(params, "yahoo_symbol")
    if yahoo_symbol:
        config.market.yahoo_symbol = yahoo_symbol
    config.engine.use_yahoo_fallback = _as_bool(params, "yahoo", True)
    # Mesure automatique de la base Bybit→spot : c'est elle qui ramène l'écart
    # au prix broker de plusieurs dollars à quelques dizaines de centimes.
    config.engine.use_spot_reference = _as_bool(params, "basis", True)
    turbo_confidence = _as_float(params, "turbo_confidence")
    if turbo_confidence is not None:
        config.engine.turbo_confidence = turbo_confidence

    config.engine.use_macro = _as_bool(params, "macro", True)
    config.engine.use_calendar = _as_bool(params, "calendar", True)
    config.engine.use_microstructure = _as_bool(params, "micro", True)
    config.engine.allow_counter_trend = _as_bool(params, "counter_trend", False)
    return config


def add_preview(payload: dict, analysis, calibration, config) -> dict:
    """Plan de PRÉPARATION quand aucun signal ne franchit le seuil.

    Ouvrir l'outil pour lire « aucun plan » n'apprend rien. On construit donc
    le plan que le moteur poserait SI la confiance montait, avec les niveaux
    déjà calculés. Il est marqué comme non exécutable et n'est jamais fourni
    quand un veto est actif : un veto n'est pas une question de confiance,
    c'est un refus.
    """
    if payload["plan"]["valid"] or analysis.confluence.vetoes:
        return payload

    score = analysis.confluence.final_score
    direction = 1 if score > 0 else -1 if score < 0 else 0
    if direction == 0:
        return payload

    probe = dataclasses.replace(analysis.confluence, direction=direction)
    news_multiplier = analysis.data.news.size_multiplier if analysis.data.news else 1.0
    plan = build_plan(probe, calibration, config.risk, config.market,
                      analysis.session, news_multiplier)
    if not plan.valid:
        return payload

    payload["preview"] = {
        "side": plan.side,
        "entry": plan.entry,
        "entry_type": plan.entry_type,
        "stop_loss": plan.stop,
        "stop_distance": plan.stop_distance,
        "take_profits": [
            {"label": t.label, "price": t.price, "r_multiple": t.r_multiple,
             "share": t.share, "rationale": t.rationale}
            for t in plan.targets
        ],
        "lots": plan.lots,
        "rr1": plan.rr1,
        "rr2": plan.rr2,
        "blocked_by": payload["plan"].get("rejection", ""),
        "missing_confidence": round(
            max(0.0, config.engine.min_confidence - analysis.confluence.confidence), 1
        ),
    }
    return payload


def run_analysis(params: dict[str, list[str]]) -> dict:
    config = build_config(params)
    problems = config.risk.validate()
    if problems:
        raise ValueError("; ".join(problems))

    calibration, notes = build_calibration(params)
    demo = _as_bool(params, "demo", False)
    seed_raw = _first(params, "seed")
    seed = int(seed_raw) if seed_raw and seed_raw.isdigit() else None

    analysis = engine.run(
        config, calibration,
        demo=demo,
        seed=seed,
        prefer_mt5=False,            # aucun terminal MT5 en serverless
        spread_override=_as_float(params, "spread"),
    )
    payload = to_payload(analysis)
    if _as_bool(params, "preview", True):
        payload = add_preview(payload, analysis, calibration, config)
    payload["notes"] = notes
    payload["version"] = __version__
    payload["region"] = os.environ.get("VERCEL_REGION", "inconnue")
    return payload


def run_calibration(params: dict[str, list[str]]) -> dict:
    """Cale la calibration à partir du SEUL prix affiché par MetaTrader 5.

    Le serveur relève lui-même le prix de référence et mesure la base : la
    seule chose qu'il ne peut pas deviner est ce qu'affiche le terminal de
    l'utilisateur. La réponse contient l'alpha à conserver côté navigateur,
    puisqu'une fonction serverless ne garde rien entre deux appels.
    """
    # BID et ASK, comme les affiche le terminal. Un seul prix reste accepté et
    # sera traité comme le milieu du marché.
    bid = _as_float(params, "bid")
    ask = _as_float(params, "ask")
    mt5_price = _as_float(params, "mt5")
    if bid is not None and ask is not None:
        mt5_price = bid
    elif mt5_price is None:
        raise ValueError(
            "Renseigne le BID et l'ASK affichés par ton MT5 (ou au minimum un prix)."
        )
    if mt5_price is None or mt5_price <= 0:
        raise ValueError("Prix MT5 invalide.")

    config = build_config(params)
    calibration, probe = engine.calibrate_from_mt5(config, Calibration(), mt5_price, ask)
    if not probe.ok:
        raise RuntimeError(
            "Impossible de relever un prix de référence pour te comparer. "
            + (probe.problem or "sources injoignables")
        )

    return {
        "ok": True,
        "alpha": round(calibration.alpha, 4),
        "permanent": calibration.reference == "index",
        "reference": calibration.reference,
        "spread": round(calibration.spread, 4),
        "quality": calibration.quality(),
        "mt5": mt5_price,
        "reference_symbol": probe.symbol,
        "reference_price": probe.bybit,
        "spot": probe.spot,
        "basis": {
            "ok": probe.basis.ok,
            "value": probe.basis.value,
            "dispersion": probe.basis.dispersion,
            "samples": probe.basis.samples,
        },
        "durable": calibration.reference in ("index", "spot"),
        "message": (
            f"Aligné sur ton broker : {calibration.alpha:+.2f} $. "
            "L'ancre reste active jusqu'à ce que tu la remplaces."
            if calibration.reference == "index"
            else f"Markup de ton broker : {calibration.alpha:+.2f} $. Valable plusieurs jours."
            if calibration.reference == "spot"
            else f"Écart au prix Bybit brut : {calibration.alpha:+.2f} $. "
                 "À refaire dans 2 à 4 heures (référence index indisponible)."
        ),
        "note": probe.problem or "",
    }


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Une analyse de scalp périmée est pire qu'aucune analyse.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        route = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "analyse"

        if route in ("calibrate", "calibrage"):
            try:
                self._send(200, run_calibration(params))
            except ValueError as exc:
                self._send(400, {"error": str(exc), "kind": "parametre_invalide"})
            except RuntimeError as exc:
                self._send(502, {"error": str(exc), "kind": "source_indisponible",
                                 "region": os.environ.get("VERCEL_REGION", "inconnue")})
            except Exception as exc:  # pragma: no cover
                self._send(500, {"error": f"{type(exc).__name__}: {exc}",
                                 "kind": "erreur_interne"})
            return

        if route in ("health", "sante"):
            self._send(200, {
                "ok": True,
                "version": __version__,
                "region": os.environ.get("VERCEL_REGION", "inconnue"),
                "python": sys.version.split()[0],
            })
            return

        try:
            self._send(200, run_analysis(params))
        except ValueError as exc:
            self._send(400, {"error": str(exc), "kind": "parametre_invalide"})
        except RuntimeError as exc:
            # Typiquement : Bybit injoignable depuis la region de la fonction.
            self._send(
                502,
                {
                    "error": str(exc),
                    "kind": "source_indisponible",
                    "region": os.environ.get("VERCEL_REGION", "inconnue"),
                    "conseil": (
                        "Bybit filtre certaines regions (notamment les Etats-Unis). "
                        "Verifie que vercel.json épingle une region autorisée "
                        "(fra1, sin1, hnd1), ou ajoute ?demo=1 pour valider le "
                        "déploiement sans réseau externe."
                    ),
                },
            )
        except Exception as exc:  # pragma: no cover
            self._send(500, {
                "error": f"{type(exc).__name__}: {exc}",
                "kind": "erreur_interne",
                "trace": traceback.format_exc()[-1500:],
            })
