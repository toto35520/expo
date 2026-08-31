"""Utilitaires transverses : HTTP, caché disque, logs, maths de base.

Aucune dépendance externe : urllib + json + math suffisent.
"""

from __future__ import annotations

import json
import logging
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence

LOG = logging.getLogger("goldscalp")

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def setup_logging(level: str = "info") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%H:%M:%S"))
    LOG.handlers[:] = [handler]
    LOG.setLevel(_LEVELS.get(level.lower(), logging.INFO))
    LOG.propagate = False


# --------------------------------------------------------------------------- #
# Temps
# --------------------------------------------------------------------------- #

def now_ms() -> int:
    return int(time.time() * 1000)


def ms_to_iso(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ms / 1000)) + "Z"



# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = "") -> None:
        super().__init__(f"HTTP {status} sur {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body


@dataclass
class HttpConfig:
    timeout: float = 15.0
    retries: int = 4
    backoff: float = 0.8
    user_agent: str = "goldscalp/1.0 (+https://github.com/)"
    verify_tls: bool = True


class Http:
    """Client HTTP minimaliste avec retry exponentiel et caché mémoire court."""

    def __init__(self, config: HttpConfig | None = None) -> None:
        self.config = config or HttpConfig()
        self._ctx = ssl.create_default_context()
        if not self.config.verify_tls:  # jamais par défaut, uniquement debug explicite
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if ca_bundle and os.path.exists(ca_bundle) and self.config.verify_tls:
            try:
                self._ctx.load_verify_locations(ca_bundle)
            except OSError:  # pragma: no cover - dépend de l'environnement
                LOG.debug("CA bundle %s illisible, on garde le store système", ca_bundle)
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ctx),
            urllib.request.ProxyHandler(),  # respecte HTTP(S)_PROXY
        )

    def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> bytes:
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", self.config.user_agent)
        req.add_header("Accept", "application/json, text/csv, */*")
        for key, value in (headers or {}).items():
            req.add_header(key, value)

        last: Exception | None = None
        for attempt in range(self.config.retries):
            try:
                with self._opener.open(req, timeout=self.config.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # pragma: no cover
                    pass
                last = HttpError(exc.code, url, body)
                # 4xx (hors 429) : inutile de reessayer
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise last
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                last = exc
            sleep_for = self.config.backoff * (2 ** attempt)
            LOG.debug("GET %s échoué (%s), retry dans %.1fs", url, last, sleep_for)
            time.sleep(sleep_for)
        assert last is not None
        raise last

    def get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        raw = self.get(url, params, headers)
        return json.loads(raw.decode("utf-8", "replace"))

    def get_text(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
        return self.get(url, params, headers).decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Cache disque
# --------------------------------------------------------------------------- #

def state_dir() -> str:
    """Repertoire persistant (calibration, caché) surchargable par GOLDSCALP_HOME."""
    base = os.environ.get("GOLDSCALP_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".goldscalp")
    os.makedirs(base, exist_ok=True)
    return base


def cache_path(name: str) -> str:
    directory = os.path.join(state_dir(), "cache")
    os.makedirs(directory, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return os.path.join(directory, safe)


def cache_read(name: str, max_age_s: float) -> Any | None:
    path = cache_path(name)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    if time.time() - stat.st_mtime > max_age_s:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def cache_write(name: str, payload: Any) -> None:
    path = cache_path(name)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except OSError as exc:  # pragma: no cover - disque plein / readonly
        LOG.debug("caché non ecrit (%s): %s", name, exc)


def json_dump_atomic(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Maths
# --------------------------------------------------------------------------- #

def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den not in (0, 0.0) and math.isfinite(den) else default


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(var, 0.0))


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def percentile(values: Sequence[float], pct: float) -> float:
    """Percentile lineaire (pct dans [0, 100])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = clamp(pct, 0.0, 100.0) / 100.0 * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return ordered[low]
    frac = pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def rank_pct(values: Sequence[float], value: float) -> float:
    """Position de `value` dans `values`, en pourcentage (0-100)."""
    if not values:
        return 50.0
    below = sum(1 for v in values if v <= value)
    return 100.0 * below / len(values)



def linreg_slope(values: Sequence[float]) -> float:
    """Pente d'une regression lineaire simple sur l'index (0..n-1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = mean(values)
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return safe_div(num, den)


def theil_sen(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Regression robuste (pente mediane des paires) -> (intercept, pente).

    Insensible aux outliers, ideal pour caler Bybit sur MT5 a partir
    d'ancrages saisis a la main (donc potentiellement salis).
    """
    n = min(len(xs), len(ys))
    if n == 0:
        return 0.0, 1.0
    if n == 1:
        return ys[0] - xs[0], 1.0
    slopes: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if abs(dx) < 1e-9:
                continue
            slopes.append((ys[j] - ys[i]) / dx)
    slope = median(slopes) if slopes else 1.0
    intercept = median([ys[i] - slope * xs[i] for i in range(n)])
    return intercept, slope


