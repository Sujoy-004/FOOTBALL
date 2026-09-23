"""Provider configuration audit — Phase C (health) + Phase D (observability).

Pins:
1. ``web.common.get_data_provider`` selects the right provider for the
   configured ``DATA_PROVIDER`` / credentials, and returns ``None`` when
   nothing usable is configured (placeholder/empty keys never select).
2. The load-order fix in ``web/__init__.py``: laliga_app / ucl_app no longer
   capture empty key constants at import time under the repo ``.env``.
3. The boot/refresh classification diagnostics (``NOT_CONFIGURED`` /
   ``CONNECTED`` / ``CONFIGURED_BUT_UNAVAILABLE``) exist in both refresh paths.

All tests are offline: providers are only instantiated, never called over
the network.
"""

from __future__ import annotations

import subprocess
import sys
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


# ── Phase C: import-time capture fix (web/__init__ runs load_dotenv) ───────


def _import_probe_lines() -> list[str]:
    probe = (
        "import os, sys\n"
        "sys.path.insert(0, {root!r})\n"
        "for k in ('BSD_API_KEY', 'FOOTBALL_DATA_ORG_KEY', 'DATA_PROVIDER'):\n"
        "    os.environ.pop(k, None)\n"
        "import web.laliga_app as l\n"
        "import web.ucl_app as u\n"
        "print('L', bool(l.BSD_API_KEY), bool(l.FOOTBALL_DATA_ORG_KEY))\n"
        "print('U', bool(u.BSD_API_KEY), bool(u.FOOTBALL_DATA_ORG_KEY))\n"
    ).format(root=str(REPO_ROOT))
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


@pytest.mark.skipif(
    not (REPO_ROOT / ".env").exists(), reason="no .env in the repo to load"
)
def test_laliga_and_ucl_capture_keys_at_import_after_fix():
    """web/__init__ runs load_dotenv() so laliga_app/ucl_app import with
    populated (non-empty) credential constants instead of pre-captured empty
    strings. Regresses the 'No data provider' boot symptom."""
    lines = _import_probe_lines()
    assert "L True True" in lines
    assert "U True True" in lines


@pytest.mark.skipif(
    not (REPO_ROOT / ".env").exists(), reason="no .env in the repo to load"
)
def test_live_env_constants_resolve_a_provider():
    """Under the real .env, the module constants the refresh paths pass to
    get_data_provider resolve to a non-None provider (instantiation only —
    no network)."""
    import importlib

    import web.laliga_app as la
    import web.ucl_app as ua

    # The autouse fixture wiped the env; reload the real .env and the modules
    # so the import-time capture replays with the credentials present.
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    la = importlib.reload(la)
    ua = importlib.reload(ua)

    laliga_provider = get_data_provider(
        la.BSD_API_KEY, la.FOOTBALL_DATA_ORG_KEY, la.LALIGA_BSD_LEAGUE_ID
    )
    ucl_provider = get_data_provider(
        ua.BSD_API_KEY, ua.FOOTBALL_DATA_ORG_KEY, ua.UCL_LEAGUE_ID
    )
    assert laliga_provider is not None
    assert ucl_provider is not None
    assert la.FOOTBALL_DATA_ORG_KEY and ua.FOOTBALL_DATA_ORG_KEY


# ── Phase D: classification diagnostics present in the refresh paths ───────


def test_refresh_paths_carry_classification_diagnostics():
    ucl_src = (REPO_ROOT / "web" / "ucl_app.py").read_text(encoding="utf-8")
    laliga_src = (REPO_ROOT / "web" / "laliga_app.py").read_text(encoding="utf-8")
    for tag, src in (("ucl_app.py", ucl_src), ("laliga_app.py", laliga_src)):
        for token in ("NOT_CONFIGURED", "CONNECTED", "CONFIGURED_BUT_UNAVAILABLE"):
            assert token in src, f"{token} missing from web/{tag}"