"""Generic multi-season store for round-robin league competitions.

A season-scoped flat-file catalog shared by league-format competition
brains (La Liga today; a future brain reuses it as-is). The UCL brain
retains its own private ``seasons.py`` for historical stability; the
fixture-id derivation below mirrors that module's proven contract while
parameterizing the namespace so each competition owns distinct ids.

Contract
--------
- ``derive_fixture_id(namespace, home, away)`` is deterministic and
  date-independent: a fixture's id never changes as kick-off time shifts.
- Every store write is atomic (fsync + ``os.replace``) with UTF-8 JSON.
- ``data/current.json`` is the runtime season pointer; absence means the
  brain's shipped season is active (the caller provides the default).
- Corrupt or missing reads degrade to empty payloads, never raise.

Layout
------
``<data_dir>/seasons/<dir_token>/{fixtures,results}.json``
``<data_dir>/current.json``
``<dir_token>`` is the season token with ``/`` replaced by ``_``
(``"2026/27"`` -> ``"2026_27"``).

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _atomic_write_json(data: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp"
    )
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


def normalize_season_dir(season_token: str) -> str:
    """Directory token for a season id (``"2026/27"`` -> ``"2026_27"``)."""
    return str(season_token).replace("/", "_")


def derive_fixture_id(namespace: str, home: str, away: str) -> str:
    """Deterministic, date-independent fixture id for one (home, away) pair.

    Date is deliberately excluded so a postponed fixture keeps its id; a
    competition passes its own ``namespace`` (e.g. ``"laliga-season-fixture"``).
    """
    material = f"{namespace}\n{home}\n{away}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _resolve_data_dir(data_dir: Path | str) -> Path:
    return Path(data_dir)


def seasons_root(data_dir: Path | str) -> Path:
    return _resolve_data_dir(data_dir) / "seasons"


def season_dir(data_dir: Path | str, season_token: str) -> Path:
    return seasons_root(data_dir) / normalize_season_dir(season_token)


def list_seasons(data_dir: Path | str) -> list[str]:
    """Directory tokens present under ``<data_dir>/seasons``."""
    root = seasons_root(data_dir)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and p.name.count("_") == 1
    )


def read_season_fixtures(data_dir: Path | str, season_token: str) -> dict:
    path = season_dir(data_dir, season_token) / "fixtures.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def read_season_results(data_dir: Path | str, season_token: str) -> dict:
    path = season_dir(data_dir, season_token) / "results.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_season_fixtures(
    data_dir: Path | str, season_token: str, payload: dict
) -> Path:
    payload = dict(payload)
    payload.setdefault("schema", 1)
    payload["season"] = season_token
    path = season_dir(data_dir, season_token) / "fixtures.json"
    _atomic_write_json(payload, path)
    return path


def write_season_results(
    data_dir: Path | str, season_token: str, payload: dict
) -> Path:
    payload = dict(payload)
    payload.setdefault("schema", 1)
    payload["season"] = season_token
    path = season_dir(data_dir, season_token) / "results.json"
    _atomic_write_json(payload, path)
    return path


def current_season_path(data_dir: Path | str) -> Path:
    return _resolve_data_dir(data_dir) / "current.json"


def get_current_season(data_dir: Path | str) -> dict:
    path = current_season_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def set_current_season(
    data_dir: Path | str,
    season_token: str,
    basis: str,
    provider: str | None = None,
) -> dict:
    pointer = {
        "season": season_token,
        "basis": basis,
        "provider": provider,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(pointer, current_season_path(data_dir))
    return dict(pointer)


def active_season(
    data_dir: Path | str, shipped_season: str
) -> tuple[str, dict]:
    """Resolve the active season: current.json pointer or shipped default."""
    current = get_current_season(data_dir)
    season = current.get("season")
    if season:
        return str(season), current
    return shipped_season, {}


def cleared_payload(data_dir: Path | str, season_token: str) -> dict:
    """Empty-but-marked store payload (schema + season identity)."""
    return {"schema": 1, "season": season_token, "provider": None}