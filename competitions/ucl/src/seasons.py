"""Season store abstraction for UCL — multi-season persistence layer.

Layout under the UCL data dir::

    data/seasons/<2025_26|2026_27>/fixtures.json   # normalized fixtures
    data/seasons/<id>/results.json                 # results attached to them
    data/current.json                              # active-season pointer

Directory ids are the display season id with ``/`` replaced by ``_``
(``"2026/27"`` -> ``"2026_27"``).

Historical 2025/26 intentionally does NOT live under ``data/seasons/``: it
is the shipped historical dataset whose canonical stores remain
``data/fixtures.json`` / ``data/results.json`` /
``data/knockout_results.json``. ``data/seasons/`` exists exclusively for
seasons DISCOVERED from provider feeds (a new current season), so a fresh
checkout never fabricates schedules for seasons nobody has observed yet.

All writes are atomic (temp file + ``os.replace``, utf-8, indent=2,
``ensure_ascii=False``). Every reader tolerates missing/corrupt files and
returns ``None`` instead of raising.

Stable fixture ids (documented contract used by the ingest router):

- ``<source id>`` verbatim when the provider supplies a match id;
- otherwise ``gen-`` + first 16 hex chars of
  ``sha256("ucl-season-fixture\\n{home}\\n{away}\\n{date}")`` — a
  deterministic hash of teams + date, stable across ingestion runs.

:func:`resolve_active_view` is a PURE summarizer (no writes, no network):
Agent B's lifecycle transitions consume it to decide whether the app still
shows the local historical season or a discovered one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The shipped historical dataset's season (canonical stores at data/ root).
LOCAL_HISTORICAL_SEASON = "2025/26"

SEASONS_DIRNAME = "seasons"
CURRENT_FILENAME = "current.json"
FIXTURES_FILENAME = "fixtures.json"
RESULTS_FILENAME = "results.json"
SEASON_STORE_SCHEMA = 1

__all__ = [
    "LOCAL_HISTORICAL_SEASON",
    "derive_fixture_id",
    "get_current_season",
    "list_seasons",
    "normalize_season_token",
    "read_season_fixtures",
    "read_season_results",
    "resolve_active_view",
    "season_dir",
    "season_dir_id",
    "season_display_id",
    "set_current_season",
    "write_season_fixtures",
    "write_season_results",
]

# "2026-27" / "2026_27" / "2026/27" / "2026 27" / "2026-2027"
_FULL_PATTERN = re.compile(r"^(\d{4})[-_/ ](\d{2,4})$")
# Explicit underscore pattern (regex char class with - at start can be tricky)
_UNDERSCORE_PATTERN = re.compile(r"^(\d{4})_(\d{2,4})$")
# "26-27" / "25/26" — two-digit start year
_SHORT_PATTERN = re.compile(r"^(\d{2})[-_/ ](\d{2})$")


# ── season id vocabulary ─────────────────────────────────────────────────────


def normalize_season_token(value: Any) -> str | None:
    """Normalize any common provider season spelling to ``"YYYY/YY"``.

    Accepted inputs: ``None`` (-> ``None``), an int starting year
    (``2026`` -> ``"2026/27"``), or strings like ``"2025/26"``,
    ``"2026-27"``, ``"2025_26"``, ``"25/26"``. Unparseable non-empty
    strings are returned trimmed as-is (they still identify SOME season —
    they must never collapse into the local historical one). Empty/blank
    input maps to ``None``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if 1900 <= value <= 2199:
            return f"{value}/{(value + 1) % 100:02d}"
        return None
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    if token.isdigit():
        try:
            return normalize_season_token(int(token))
        except ValueError:
            pass
    m = _FULL_PATTERN.match(token)
    if m:
        start = int(m.group(1))
        end_raw = m.group(2)
        end = int(end_raw)
        end_expected = (start + 1) % 100
        if len(end_raw) == 4:
            end %= 100
        if end == end_expected:
            return f"{start}/{end:02d}"
    m = _UNDERSCORE_PATTERN.match(token)
    if m:
        start = int(m.group(1))
        end_raw = m.group(2)
        end = int(end_raw)
        end_expected = (start + 1) % 100
        if len(end_raw) == 4:
            end %= 100
        if end == end_expected:
            return f"{start}/{end:02d}"
    m = _SHORT_PATTERN.match(token)
    if m:
        start = 2000 + int(m.group(1))
        end = int(m.group(2))
        if end == (start + 1) % 100:
            return f"{start}/{end % 100:02d}"
    return token


def season_display_id(dir_id_or_token: str) -> str:
    """Best-effort display id for a directory id (``"2026_27"`` ->
    ``"2026/27"``); other ids pass through unchanged."""
    token = str(dir_id_or_token).strip()
    m = re.match(r"^(\d{4})_(\d{2})$", token)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return token


def season_dir_id(season: Any) -> str:
    """Filesystem-safe directory id for a season token (``"2026/27"`` ->
    ``"2026_27"``)."""
    display = normalize_season_token(season) or str(season).strip()
    return re.sub(r"[^A-Za-z0-9.-]+", "_", display)


def season_dir(data_dir: str | Path, season: Any) -> Path:
    """Path of the season store directory for *season* under *data_dir*."""
    return Path(data_dir) / SEASONS_DIRNAME / season_dir_id(season)


# ── atomic JSON persistence ──────────────────────────────────────────────────


def _atomic_write_json(data: Any, path: Path) -> None:
    """Write *data* to *path* atomically (utf-8, indent=2, ensure_ascii=False)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── current-season pointer ───────────────────────────────────────────────────


def _current_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / CURRENT_FILENAME


def set_current_season(
    data_dir: str | Path,
    season: Any,
    *,
    basis: str = "provider",
    provider: str | None = None,
    activated_at: str | None = None,
) -> dict:
    """Atomically point ``current.json`` at *season*; returns the payload.

    Shape: ``{"season": <display id>, "activated_at": <iso8601>,
    "basis": <str>, "provider": <str|None>}``.
    """
    payload = {
        "season": normalize_season_token(season),
        "activated_at": activated_at
        or datetime.now(timezone.utc).isoformat(),
        "basis": basis,
        "provider": provider,
    }
    _atomic_write_json(payload, _current_path(data_dir))
    return payload


def get_current_season(data_dir: str | Path) -> dict | None:
    """Read the current-season pointer; ``None`` when absent or corrupt.

    Corrupt payloads (unparseable JSON, wrong shape, blank season) are
    logged and reported as ``None`` — never raised, never repaired silently.
    """
    path = _current_path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("[UCL] current.json unreadable (%s) — treating as unset", exc)
        return None
    if not isinstance(payload, dict) or not payload.get("season"):
        logger.warning("[UCL] current.json malformed — treating as unset")
        return None
    return payload


# ── per-season stores ────────────────────────────────────────────────────────


def list_seasons(data_dir: str | Path) -> list[str]:
    """Sorted directory ids of seasons holding at least one store file."""
    root = Path(data_dir) / SEASONS_DIRNAME
    if not root.is_dir():
        return []
    out: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if (child / FIXTURES_FILENAME).exists() or (child / RESULTS_FILENAME).exists():
            out.append(child.name)
    return sorted(out)


def read_season_fixtures(data_dir: str | Path, season: Any) -> dict | None:
    """Load a season's fixtures.json; ``None`` when absent/corrupt."""
    path = season_dir(data_dir, season) / FIXTURES_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("[UCL] %s unreadable (%s)", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def read_season_results(data_dir: str | Path, season: Any) -> dict | None:
    """Load a season's results.json; ``None`` when absent/corrupt."""
    path = season_dir(data_dir, season) / RESULTS_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("[UCL] %s unreadable (%s)", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def write_season_fixtures(data_dir: str | Path, season: Any, document: dict) -> str:
    """Persist a season fixtures document atomically; returns the path."""
    path = season_dir(data_dir, season) / FIXTURES_FILENAME
    _atomic_write_json(document, path)
    return str(path)


def write_season_results(data_dir: str | Path, season: Any, document: dict) -> str:
    """Persist a season results document atomically; returns the path."""
    path = season_dir(data_dir, season) / RESULTS_FILENAME
    _atomic_write_json(document, path)
    return str(path)


def derive_fixture_id(home_team: str, away_team: str, event_date: str | None) -> str:
    """Deterministic fallback fixture id (teams + date hash), see module doc."""
    basis = f"ucl-season-fixture\n{home_team}\n{away_team}\n{event_date or ''}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return f"gen-{digest[:16]}"


def _empty_availability() -> dict:
    # ``partial`` stays true until an explicit completion signal exists —
    # providers never declare a catalog complete, so claiming full coverage
    # would be fabrication.
    return {"fixtures_count": 0, "results_count": 0, "partial": True}


def empty_fixtures_document(season_display: str) -> dict:
    return {
        "schema": SEASON_STORE_SCHEMA,
        "season": season_display,
        "fixtures": [],
        "availability": _empty_availability(),
    }


def empty_results_document(season_display: str) -> dict:
    return {
        "schema": SEASON_STORE_SCHEMA,
        "season": season_display,
        "matches": [],
        "meta": {"provider": None},
    }


# ── active-view summary (pure; consumed by lifecycle transitions) ───────────


def resolve_active_view(data_dir: str | Path) -> dict:
    """Summarize which season view is active — pure, no writes, no network.

    Returns::

        {
          "current": <current.json payload> | None,
          "current_season": "2026/27" | None,
          "local_season": "2025/26",
          "seasons": {"2026_27": {"fixtures_count": n, "results_count": m}},
          "local_historical_is_active": bool,
          "basis": "default_local" | "pointer_local" | "pointer_other",
        }

    ``local_historical_is_active`` is True when no pointer exists or the
    pointer still names the local historical season. ``basis`` records WHY:
    ``default_local`` (no pointer — shipped dataset remains the view),
    ``pointer_local`` (pointer confirms the local season), or
    ``pointer_other`` (a discovered season took over).
    """
    dp = Path(data_dir)
    current = get_current_season(dp)
    current_season = (
        normalize_season_token(current.get("season")) if current else None
    )

    seasons: dict[str, dict] = {}
    for dir_id in list_seasons(dp):
        fx = read_season_fixtures(dp, dir_id)
        res = read_season_results(dp, dir_id)
        fx_rows = fx.get("fixtures") if isinstance(fx, dict) else None
        res_rows = res.get("matches") if isinstance(res, dict) else None
        seasons[dir_id] = {
            "fixtures_count": len(fx_rows) if isinstance(fx_rows, list) else 0,
            "results_count": len(res_rows) if isinstance(res_rows, list) else 0,
        }

    if current is None:
        is_local_active, basis = True, "default_local"
    elif current_season == LOCAL_HISTORICAL_SEASON:
        is_local_active, basis = True, "pointer_local"
    else:
        is_local_active, basis = False, "pointer_other"

    return {
        "current": current,
        "current_season": current_season,
        "local_season": LOCAL_HISTORICAL_SEASON,
        "seasons": seasons,
        "local_historical_is_active": is_local_active,
        "basis": basis,
    }
