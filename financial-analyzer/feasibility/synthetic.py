"""Générateur de ticks synthétiques — pour les tests et la démonstration uniquement.

**Aucun chiffre produit ici n'est une donnée de marché.** Les paramètres sont arbitraires
et servent à exercer le code, pas à décrire l'or. Toute conclusion tirée d'une exécution
sur ces données serait une conclusion sur le générateur.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NS_PER_SECOND = 1_000_000_000
NS_PER_DAY = 86_400 * NS_PER_SECOND


@dataclass(frozen=True)
class SyntheticTicks:
    timestamps_ns: np.ndarray
    mid: np.ndarray
    spread: np.ndarray
    #: Identifiant de séance : c'est le bloc indépendant du rééchantillonnage.
    cluster_ids: np.ndarray
    session: np.ndarray


def generate(
    days: int = 25,
    ticks_per_session: int = 40_000,
    session_seconds: int = 4 * 3_600,
    session_start_hour: int = 9,
    start_price: float = 4_000.0,
    tick_size: float = 0.01,
    base_volatility: float = 0.012,
    seed: int = 7,
) -> SyntheticTicks:
    """Série de ticks avec saisonnalité intraday sur la volatilité et le spread.

    La densité de ticks est un paramètre de premier ordre et non un détail : à densité
    trop faible, un horizon d'une seconde ne contient aucun tick, l'amplitude sature sur
    le pas de cotation et la courbe kappa devient plate — un artefact du générateur qui
    se lirait comme un résultat de marché.

    La saisonnalité est délibérée : elle permet de vérifier que les calculs conditionnels
    par tranche de session font bien apparaître des cellules différentes, ce qu'une série
    homogène ne testerait pas.
    """
    rng = np.random.default_rng(seed)
    session_ns = session_seconds * NS_PER_SECOND

    ts, mids, spreads, clusters, sessions = [], [], [], [], []
    price = start_price

    for d in range(days):
        day_start = d * NS_PER_DAY + session_start_hour * 3_600 * NS_PER_SECOND
        # Progression irrégulière du temps : les ticks n'arrivent pas à cadence fixe.
        gaps = rng.exponential(session_ns / ticks_per_session, size=ticks_per_session)
        day_ts = day_start + np.cumsum(gaps).astype(np.int64)
        day_ts = day_ts[day_ts < day_start + session_ns]
        n = day_ts.size

        # Deux pics d'activité dans la séance, comme un recouvrement de places.
        frac = (day_ts - day_start) / session_ns
        intensity = 0.4 + 1.6 * (
            np.exp(-((frac - 0.35) ** 2) / 0.006) + np.exp(-((frac - 0.60) ** 2) / 0.010)
        )

        steps = rng.normal(0.0, base_volatility * np.sqrt(intensity), size=n)
        # Quelques sauts rares : sans eux, la queue de distribution serait irréaliste et
        # la détection d'événements du protocole Q19 n'aurait rien à trouver.
        jumps = rng.random(n) < 0.0004
        steps[jumps] += rng.normal(0.0, 1.2, size=int(jumps.sum())) * np.sign(
            rng.normal(size=int(jumps.sum()))
        )

        day_mid = price + np.cumsum(steps)
        day_mid = np.round(day_mid / tick_size) * tick_size
        price = float(day_mid[-1])

        day_spread = np.maximum(
            tick_size, rng.gamma(shape=3.0, scale=0.05, size=n) / np.sqrt(intensity)
        )

        ts.append(day_ts)
        mids.append(day_mid)
        spreads.append(day_spread)
        clusters.append(np.full(n, d, dtype=np.int64))
        sessions.append(np.where(frac < 0.45, "LONDON", "NEW_YORK"))

    return SyntheticTicks(
        timestamps_ns=np.concatenate(ts),
        mid=np.concatenate(mids),
        spread=np.concatenate(spreads),
        cluster_ids=np.concatenate(clusters),
        session=np.concatenate(sessions),
    )


def latency_samples(
    n: int = 5_000,
    median_ms: float = 90.0,
    tail_ms: float = 600.0,
    burst_inflation: float = 3.0,
    seed: int = 11,
) -> tuple[np.ndarray, np.ndarray]:
    """Deux distributions de latence : hors rafale et en rafale.

    La seconde est délibérément plus lourde. C'est le point de l'ADR-102 : la latence se
    dégrade précisément quand les signaux se déclenchent, de sorte qu'un centile calculé
    sur l'ensemble sous-estime celui qui compte.
    """
    rng = np.random.default_rng(seed)
    sigma = np.log(tail_ms / median_ms) / 2.0

    quiet = rng.lognormal(np.log(median_ms), sigma, size=n)
    burst = rng.lognormal(np.log(median_ms * burst_inflation), sigma * 1.3, size=n)
    return (
        (quiet * 1e6).astype(np.int64),
        (burst * 1e6).astype(np.int64),
    )
