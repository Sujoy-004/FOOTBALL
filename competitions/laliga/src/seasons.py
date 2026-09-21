"""LaLiga season store — thin binding of the shared generic store.

All storage logic lives in ``football_core.seasons`` (atomic writes,
season pointers, fixture-id derivation). This module only binds the
competition's namespace and shipped default so brains and the web layer
share one vocabulary.
"""

from __future__ import annotations

from football_core import seasons as _store

from competitions.laliga.src.constants import (
    DATA_DIR,
    SEASON_NAMESPACE,
    SHIPPED_SEASON,
)

SEASON_NAMESPACE_KEY = SEASON_NAMESPACE


def derive_fixture_id(home: str, away: str) -> str:
    """Deterministic date-independent fixture id for one home/away slot."""
    return _store.derive_fixture_id(SEASON_NAMESPACE, home, away)


def active_season(data_dir=DATA_DIR) -> str:
    """Resolve the active season token (current.json or shipped default)."""
    token, _ = _store.active_season(data_dir, SHIPPED_SEASON)
    return str(token)


def resolve_active_data_dir(data_dir=DATA_DIR):
    """Path to the active season's season-dir (mirrors UCL seams)."""
    return _store.season_dir(data_dir, active_season(data_dir))


def season_dir(data_dir=DATA_DIR, season_token=None):
    return _store.season_dir(data_dir, season_token or active_season(data_dir))


def read_fixtures(data_dir=DATA_DIR, season_token=None) -> dict:
    season_token = season_token or active_season(data_dir)
    return _store.read_season_fixtures(data_dir, season_token)


def read_results(data_dir=DATA_DIR, season_token=None) -> dict:
    season_token = season_token or active_season(data_dir)
    return _store.read_season_results(data_dir, season_token)


def write_fixtures(payload: dict, data_dir=DATA_DIR, season_token=None):
    season_token = season_token or active_season(data_dir)
    return _store.write_season_fixtures(data_dir, season_token, payload)


def write_results(payload: dict, data_dir=DATA_DIR, season_token=None):
    season_token = season_token or active_season(data_dir)
    return _store.write_season_results(data_dir, season_token, payload)


def list_seasons(data_dir=DATA_DIR) -> list[str]:
    return _store.list_seasons(data_dir)


def get_current_season(data_dir=DATA_DIR) -> dict:
    return _store.get_current_season(data_dir)


def set_current_season(data_dir=DATA_DIR, **pointer_kwargs) -> dict:
    return _store.set_current_season(data_dir, **pointer_kwargs)