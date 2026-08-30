"""Exchange 8 — Transactional UCL season activation.

Regression tests for the guarantee that ``POST /api/season`` never persists
a flipped ``current.json`` when a downstream step (e.g. ``compute_all``)
fails after the pointer was switched: the pointer must be rolled back to
the previously-active season while the error still surfaces to the client.

These tests never mutate the repository's real data: they run against a
copied tmp data dir via monkeypatched ``web.ucl_app.DATA_DIR``.

Note on ``raise_server_exceptions=False``: unhandled 5xx failures are routed
by FastAPI to ServerErrorMiddleware's handler, which deliberately re-raises
after sending so servers can log the error. ``raise_server_exceptions=False``
is the TestClient switch that delivers that 500 response to the test.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def snapshot_mode(monkeypatch):
    """Pin every app boot here to snapshot (zero network)."""
    import web.startup as startup
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    startup._last_decision = startup.StartupDecision("snapshot", "")
    yield
    startup._last_decision = None


@pytest.fixture
def ucl_data_dir(tmp_path, monkeypatch):
    """Copy the real UCL data dir to a temp location and point web.ucl_app
    at it, so POST /api/season never mutates real data."""
    import web.ucl_app as ucl_app
    dst = tmp_path / "ucl_data"
    shutil.copytree(UCL_DATA, dst, dirs_exist_ok=True)
    monkeypatch.setattr(ucl_app, "DATA_DIR", dst)
    ucl_app.cache = {}
    ucl_app.sim_cache = {}
    return dst


@pytest.fixture
def client(ucl_data_dir):
    from web.server import app as server_app
    with TestClient(server_app, raise_server_exceptions=False) as c:
        yield c


def _read_pointer(data_dir):
    path = Path(data_dir) / "current.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _active_season(client):
    return client.get("/ucl/api/seasons").json().get("active_season")


# ── transactional activation ────────────────────────────────────────────

class TestSeasonActivationTransactional:
    def test_downstream_failure_rolls_back_pointer(self, client, ucl_data_dir, monkeypatch):
        """If compute_all raises after the flip, POST still returns 5xx and
        current.json is restored to the ORIGINAL season."""
        import web.ucl_app as ucl_app
        original = _active_season(client)
        target = "2025/26" if original == "2026/27" else "2026/27"
        original_pointer = _read_pointer(ucl_data_dir)

        def _boom():
            raise RuntimeError("downstream compute failure")

        monkeypatch.setattr(ucl_app, "compute_all", _boom)
        r = client.post("/ucl/api/season", json={"season": target})

        assert r.status_code == 500, r.text
        assert "internal error" in r.text
        restored = _read_pointer(ucl_data_dir)
        assert restored is not None
        assert restored["season"] == original
        assert restored["basis"] == original_pointer["basis"]
        assert restored["provider"] == original_pointer["provider"]
        assert _active_season(client) == original

    def test_downstream_failure_without_prior_pointer_deletes_file(
        self, client, ucl_data_dir, monkeypatch):
        """When no current.json existed before the flip, rollback removes it."""
        import web.ucl_app as ucl_app
        pointer_path = Path(ucl_data_dir) / "current.json"
        assert pointer_path.exists()
        pointer_path.unlink()

        def _boom():
            raise RuntimeError("downstream compute failure")

        monkeypatch.setattr(ucl_app, "compute_all", _boom)
        r = client.post("/ucl/api/season", json={"season": "2026/27"})

        assert r.status_code == 500, r.text
        assert not pointer_path.exists()
        assert _active_season(client) == "2025/26"

    def test_happy_path_switches_season_and_back(self, client, ucl_data_dir):
        """Normal flow still works: the pointer flips, and switching back to
        the original restores it."""
        original = _active_season(client)
        target = "2025/26" if original == "2026/27" else "2026/27"

        r = client.post("/ucl/api/season", json={"season": target})
        assert r.status_code == 200, r.text
        assert r.json().get("current", {}).get("season") == target
        assert _read_pointer(ucl_data_dir)["season"] == target
        assert _active_season(client) == target

        r = client.post("/ucl/api/season", json={"season": original})
        assert r.status_code == 200, r.text
        assert _read_pointer(ucl_data_dir)["season"] == original
        assert _active_season(client) == original