"""Provider configuration audit — Phase C (health) + Phase D (observability).

Pins:
1. ``web.common.get_data_provider`` selects the right provider for the
   configured ``DATA_PROVIDER`` / credentials, and returns ``None`` when
   nothing usable is configured (placeholder/empty keys never select).
2. Credentials are read at CALL time by every app (``_bsd_key()`` /
   ``_football_data_org_key()``): an ``os.environ`` value exported AFTER
   import is honoured, and no frozen module constant can shadow it.
3. The boot/refresh classification diagnostics (``NOT_CONFIGURED`` /
   ``CONNECTED`` / ``CONFIGURED_BUT_UNAVAILABLE``) exist in both refresh paths.

All tests are offline: providers are only instantiated, never called over
the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.data_providers.football_data_org_provider import (
    FootballDataOrgProvider,
)
from web.common import get_data_provider

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    """Isolate provider selection from any env leaked by earlier imports."""
    for key in ("DATA_PROVIDER", "BSD_API_KEY", "FOOTBALL_DATA_ORG_KEY"):
        monkeypatch.delenv(key, raising=False)


# ── Phase C: get_data_provider selection matrix ────────────────────────────


def test_football_data_mode_selects_fdo(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "football-data")
    provider = get_data_provider("bsd-key", "fdo-key", 3)
    assert isinstance(provider, FootballDataOrgProvider)


def test_bsd_mode_selects_bsd_with_league_id(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "bsd")
    provider = get_data_provider("bsd-key", "fdo-key", 3)
    assert isinstance(provider, BSDDataProvider)
    assert provider.league_id == 3


def test_auto_prefers_bsd(monkeypatch):
    provider = get_data_provider("bsd-key", "fdo-key", 3)
    assert isinstance(provider, BSDDataProvider)


def test_auto_falls_back_to_fdo(monkeypatch):
    provider = get_data_provider("", "fdo-key", 3)
    assert isinstance(provider, FootballDataOrgProvider)


def test_no_keys_returns_none(monkeypatch):
    assert get_data_provider("", "", 3) is None


def test_placeholder_keys_return_none(monkeypatch):
    assert get_data_provider(
        "your_bsd_api_key_here", "your_football_data_org_key_here", 3
    ) is None


def test_football_data_mode_without_fdo_key_falls_back_to_bsd(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "football-data")
    provider = get_data_provider("bsd-key", "", 3)
    assert isinstance(provider, BSDDataProvider)


# ── Call-time credential reads (no import-time freeze) ─────────────────────


@pytest.mark.parametrize(
    "module_name", ["web.laliga_app", "web.ucl_app", "web.wc_app"])
def test_accessors_read_env_at_call_time(monkeypatch, module_name):
    """Keys are resolved when they are USED, not when the module is
    imported. Setting os.environ after import must be visible."""
    import importlib

    mod = importlib.import_module(module_name)
    monkeypatch.delenv("BSD_API_KEY", raising=False)
    monkeypatch.delenv("FOOTBALL_DATA_ORG_KEY", raising=False)
    assert mod._bsd_key() == ""
    assert mod._football_data_org_key() == ""

    monkeypatch.setenv("BSD_API_KEY", "late-bsd")
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "late-fdo")
    assert mod._bsd_key() == "late-bsd"
    assert mod._football_data_org_key() == "late-fdo"


@pytest.mark.parametrize(
    "module_name", ["web.laliga_app", "web.ucl_app", "web.wc_app"])
def test_apps_hold_no_frozen_credential_constants(module_name):
    """The import-time constants are gone — nothing can read a stale value."""
    import importlib

    mod = importlib.import_module(module_name)
    assert not hasattr(mod, "BSD_API_KEY"), module_name
    assert not hasattr(mod, "FOOTBALL_DATA_ORG_KEY"), module_name


def test_late_env_resolves_a_provider(monkeypatch):
    """The refresh path passes the call-time accessor values straight into
    the provider factory, so a key exported after import selects a provider
    (instantiation only — no network)."""
    from web import laliga_app, ucl_app

    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "late-fdo-key")

    assert get_data_provider(
        laliga_app._bsd_key(), laliga_app._football_data_org_key(),
        laliga_app.LALIGA_BSD_LEAGUE_ID,
    ) is not None
    assert get_data_provider(
        ucl_app._bsd_key(), ucl_app._football_data_org_key(),
        ucl_app.UCL_LEAGUE_ID,
    ) is not None


def test_real_env_resolves_a_provider(monkeypatch):
    """With the repo .env loaded (even after import), the accessors return
    a credential and the refresh path resolves a real provider."""
    import importlib

    from dotenv import load_dotenv

    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    load_dotenv(str(REPO_ROOT / ".env"), override=True)

    import web.laliga_app as la
    import web.ucl_app as ua
    la = importlib.reload(la)
    ua = importlib.reload(ua)

    keys = [la._football_data_org_key(), ua._football_data_org_key()]
    if not any(keys):
        pytest.skip("no FOOTBALL_DATA_ORG_KEY configured in the environment")

    assert get_data_provider(
        la._bsd_key(), la._football_data_org_key(), la.LALIGA_BSD_LEAGUE_ID
    ) is not None
    assert get_data_provider(
        ua._bsd_key(), ua._football_data_org_key(), ua.UCL_LEAGUE_ID
    ) is not None


# ── Phase D: classification diagnostics present in the refresh paths ───────


def test_refresh_paths_carry_classification_diagnostics():
    ucl_src = (REPO_ROOT / "web" / "ucl_app.py").read_text(encoding="utf-8")
    laliga_src = (REPO_ROOT / "web" / "laliga_app.py").read_text(encoding="utf-8")
    for tag, src in (("ucl_app.py", ucl_src), ("laliga_app.py", laliga_src)):
        for token in ("NOT_CONFIGURED", "CONNECTED", "CONFIGURED_BUT_UNAVAILABLE"):
            assert token in src, f"{token} missing from web/{tag}"