"""Calendrier économique : l'ennemi numéro un du scalpeur d'or.

Un NFP ou un CPI deplace XAUUSD de 20 a 40 $ en quelques secondes, avec un
spread qui passe de 0.20 $ a 5 $ et des stops sautés au marché. Aucune
configuration technique ne survit a ca : la seule réponse correcte est de ne
pas etre en position.

Source : le flux JSON public de ForexFactory (aucune cle). S'il est
inaccessible, on retombe sur un calendrier recurrent embarque, construit sur
les regles de publication connues (NFP le 1er vendredi, etc.). Ce repli est
approximatif et l'outil le signale explicitement.
"""

from __future__ import annotations

import calendar as calmod
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from goldscalp.util import LOG, Http, HttpConfig, cache_read, cache_write, now_ms

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Evenements à fort impact sur l'or, avec leur heure UTC habituelle.
# Utilise UNIQUEMENT en repli quand le flux en ligne est inaccessible.
BUILTIN_RULES = [
    ("NFP / Emploi US", "USD", "first_friday", 12, 30, 4),
    ("CPI US", "USD", "monthly_day", 12, 30, 13),
    ("PPI US", "USD", "monthly_day", 12, 30, 15),
    ("Ventes au détail US", "USD", "monthly_day", 12, 30, 16),
    ("FOMC (décision)", "USD", "fomc", 18, 0, 0),
    ("Inscriptions chomage US", "USD", "weekly", 12, 30, 3),   # jeudi
    ("PMI ISM manufacturier", "USD", "monthly_day", 14, 0, 1),
    ("PMI ISM services", "USD", "monthly_day", 14, 0, 3),
]

# Semaines de reunion FOMC 2026 (mercredi de décision).
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"]


@dataclass
class Event:
    ts: int              # ms UTC
    title: str
    currency: str
    impact: str          # "high" | "medium" | "low"
    forecast: str = ""
    previous: str = ""
    estimated: bool = False   # vrai si issu du calendrier de repli

    @property
    def minutes_until(self) -> float:
        return (self.ts - now_ms()) / 60000.0

    @property
    def is_gold_relevant(self) -> bool:
        return self.currency.upper() in ("USD", "ALL", "EUR", "CNY")


@dataclass
class NewsRisk:
    """Verdict du filtre actualites."""

    level: str                       # "libre" | "prudence" | "blocage"
    reason: str = ""
    next_event: Optional[Event] = None
    minutes_until: Optional[float] = None
    size_multiplier: float = 1.0     # facteur a appliquer à la taille de position
    estimated: bool = False

    @property
    def blocks_trading(self) -> bool:
        return self.level == "blocage"


def _first_friday(year: int, month: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    offset = (4 - first.weekday()) % 7      # 4 = vendredi
    return first + timedelta(days=offset)


def _nth_weekday_or_day(year: int, month: int, day: int) -> Optional[datetime]:
    last_day = calmod.monthrange(year, month)[1]
    if day > last_day:
        return None
    return datetime(year, month, day, tzinfo=timezone.utc)


def builtin_events(days_ahead: int = 7) -> list[Event]:
    """Calendrier de repli : approximatif, marque `estimated=True`."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    out: list[Event] = []

    for title, currency, rule, hour, minute, param in BUILTIN_RULES:
        cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Les regles hebdomadaires et FOMC balaient déjà tout l'horizon :
        # les faire passer dans la boucle mensuelle les dupliquerait.
        months = 1 if rule in ("weekly", "fomc") else 3
        for month_offset in range(0, months):
            month = (cursor.month - 1 + month_offset) % 12 + 1
            year = cursor.year + (cursor.month - 1 + month_offset) // 12
            when: Optional[datetime] = None

            if rule == "first_friday":
                when = _first_friday(year, month).replace(hour=hour, minute=minute)
            elif rule == "monthly_day":
                base = _nth_weekday_or_day(year, month, param)
                if base is not None:
                    # décalé au jour ouvre suivant si week-end
                    while base.weekday() >= 5:
                        base += timedelta(days=1)
                    when = base.replace(hour=hour, minute=minute)
            elif rule == "fomc":
                for iso in FOMC_2026:
                    day = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=hour, minute=minute)
                    if now <= day <= horizon:
                        out.append(Event(int(day.timestamp() * 1000), title, currency, "high", estimated=True))
                continue
            elif rule == "weekly":
                day = now
                for _ in range(days_ahead + 1):
                    if day.weekday() == param:
                        moment = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if now <= moment <= horizon:
                            out.append(Event(int(moment.timestamp() * 1000), title, currency, "high", estimated=True))
                    day += timedelta(days=1)
                continue

            if when is not None and now <= when <= horizon:
                out.append(Event(int(when.timestamp() * 1000), title, currency, "high", estimated=True))

    # Deduplication : une même regle peut retomber sur le même créneau.
    seen: set[tuple[int, str]] = set()
    unique: list[Event] = []
    for event in sorted(out, key=lambda e: e.ts):
        key = (event.ts, event.title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


class EconomicCalendar:
    def __init__(self, http: Optional[Http] = None, cache_seconds: float = 1800.0) -> None:
        # Comme la macro : si le flux traine, on bascule sur le calendrier
        # embarque plutot que de faire attendre le trader.
        self.http = http or Http(HttpConfig(timeout=6.0, retries=2, backoff=0.4))
        self.cache_seconds = cache_seconds
        self.is_estimated = False

    def fetch(self) -> list[Event]:
        cached = cache_read("ff_calendar.json", self.cache_seconds)
        payload = cached
        if payload is None:
            try:
                payload = self.http.get_json(FF_URL)
                cache_write("ff_calendar.json", payload)
            except Exception as exc:
                LOG.info("calendrier en ligne inaccessible (%s) - repli sur le calendrier embarque", exc)
                self.is_estimated = True
                return builtin_events()

        events: list[Event] = []
        for row in payload or []:
            try:
                raw_date = row.get("date")
                if not raw_date:
                    continue
                stamp = _parse_ff_date(raw_date)
                if stamp is None:
                    continue
                events.append(
                    Event(
                        ts=stamp,
                        title=str(row.get("title", "?")),
                        currency=str(row.get("country", "")).upper(),
                        impact=str(row.get("impact", "")).lower(),
                        forecast=str(row.get("forecast", "") or ""),
                        previous=str(row.get("previous", "") or ""),
                    )
                )
            except Exception:
                continue

        if not events:
            self.is_estimated = True
            return builtin_events()
        events.sort(key=lambda e: e.ts)
        return events

    def assess(self, events: list[Event], before_minutes: int = 20,
               after_minutes: int = 15, caution_minutes: int = 60) -> NewsRisk:
        """Verdict : peut-on scalper maintenant ?

        - blocage  : événement fort impact dans la fenêtre chaude
        - prudence : événement fort impact approchant -> taille réduite
        - libre    : rien en vue
        """
        relevant = [e for e in events if e.impact == "high" and e.is_gold_relevant]
        if not relevant:
            return NewsRisk("libre", "aucun événement majeur sur l'or", estimated=self.is_estimated)

        future = [e for e in relevant if e.minutes_until >= -after_minutes]
        if not future:
            return NewsRisk("libre", "aucun événement majeur a venir", estimated=self.is_estimated)

        nearest = min(future, key=lambda e: abs(e.minutes_until))
        delta = nearest.minutes_until

        if -after_minutes <= delta <= before_minutes:
            when = f"dans {delta:.0f} min" if delta >= 0 else f"il y a {-delta:.0f} min"
            return NewsRisk(
                "blocage",
                f"{nearest.title} ({nearest.currency}) {when} - spread et slippage incontrôlables",
                nearest, delta, 0.0, self.is_estimated,
            )

        if 0 <= delta <= caution_minutes:
            return NewsRisk(
                "prudence",
                f"{nearest.title} ({nearest.currency}) dans {delta:.0f} min - taille réduite de moitié",
                nearest, delta, 0.5, self.is_estimated,
            )

        return NewsRisk(
            "libre",
            f"prochain événement majeur : {nearest.title} dans {delta / 60:.1f} h",
            nearest, delta, 1.0, self.is_estimated,
        )


def _parse_ff_date(raw: str) -> Optional[int]:
    """ForexFactory renvoie par ex. `2026-08-30T08:30:00-04:00`."""
    text = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except ValueError:
            continue
    try:
        cleaned = text.replace("Z", "+00:00")
        return int(datetime.fromisoformat(cleaned).timestamp() * 1000)
    except ValueError:
        return None
