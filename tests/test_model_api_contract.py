"""Contract tests for the read-only model views: GET /api/elo and /api/blend.

The Elo and Blending views are best-effort on the frontend: a 404 or a crash
renders an explicit empty state. These tests pin that contract for all three
competitions — the documented key set, the source enum, numeric ratings, and
the hard rule that a cold (unbooted) cache degrades to an empty payload
instead of a 500 or invented data.

Offline by construction: the endpoints read in-memory caches and shipped seed
files only, and the one network-capable helper (ClubElo fetch) is poisoned in
``test_elo_never_fetches``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ELO_KEYS = {"ratings", "source", "as_of"}
ELO_SOURCES = {"seed", "live", "clubelo", "coefficient", "teams", "empty"}
BLEND_KEYS = {
    "n_signals_available",
    "available_signals",
    "blend_weights",
    "backtest_briers",
    "calibration_status",
    "n_matches_for_calibration",
    "threshold",
}

COMPETITIONS = ["worldcup", "ucl", "laliga"]
MODULES = {"worldcup": "wc_app", "ucl": "ucl_app", "laliga": "laliga_app"}
#: Holder competition id per competition (the migrated apps' derived cache
#: lives in the holder slot, not in a module global).
COMP_IDS = {"worldcup": "worldcup", "ucl": "ucl", "laliga": "laliga"}


def _module(competition: str):
    import importlib

    return importlib.import_module(f"web.{MODULES[competition]}")


def _app(competition: str):
    return getattr(_module(competition), MODULES[competition])


def _client(competition: str) -> TestClient:
    """Client WITHOUT the lifespan: the cold state the views must survive."""
    return TestClient(_app(competition))


@pytest.fixture
def fake_cache():
    """Install a fake derived cache for one competition; restore it after.

    Post-migration (plans 04-02/04-03) the migrated apps' derived cache
    lives in the holder's frozen slot, so a fake cache is PUBLISHED with
    the app's own observed stamp — that is what makes ``_snap()`` serve it —
    instead of being assigned to a module global. World Cup still exposes
    its pre-migration ``cache`` global (it migrates in 04-04) and keeps the
    monkeypatch path.

    The previous generation (data, mode, stamp) is restored verbatim, so a
    fake never leaks into the next test and a restored state never pairs
    one generation's data with another generation's stamp.
    """
    from web.derived import holder

    installed: list[tuple[str, dict, str | None, object]] = []

    def _install(competition: str, data: dict) -> None:
        comp = COMP_IDS[competition]
        module = _module(competition)
        installed.append((
            comp,
            dict(holder.read_data(comp)),
            holder.read_mode(comp),
            holder.read_stamp(comp),
        ))
        holder.publish_data(comp, data, mode=data.get("mode", "results"),
                            stamp=module._observed_stamp())

    yield _install

    for comp, data, mode, stamp in installed:
        if stamp is None:
            holder.reset(comp)      # nothing was published before: drop the fake
        else:
            holder.publish_data(comp, data, mode=mode, stamp=stamp)


@pytest.mark.parametrize("competition", COMPETITIONS)
def test_elo_contract_on_cold_cache(competition: str):
    """Unbooted cache: 200, documented keys, numeric-or-absent ratings."""
    response = _client(competition).get("/api/elo")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == ELO_KEYS
    assert payload["source"] in ELO_SOURCES
    assert isinstance(payload["ratings"], dict)
    assert all(isinstance(v, (int, float)) for v in payload["ratings"].values())
    assert isinstance(payload["as_of"], str)


@pytest.mark.parametrize("competition", COMPETITIONS)
def test_elo_empty_state_never_raises(competition: str, monkeypatch, fake_cache):
    """No cache and no shipped seed: the explicit empty payload, not a 500."""
    module = _module(competition)
    if competition == "worldcup":
        monkeypatch.setattr(module, "cache", {})   # pre-migration global (04-04)
    else:
        fake_cache(competition, {})
    if hasattr(module, "load_elo_ratings"):
        monkeypatch.setattr(module, "load_elo_ratings", lambda *_a, **_k: {})
    assert _client(competition).get("/api/elo").json() == {
        "ratings": {}, "source": "empty", "as_of": ""}


@pytest.mark.parametrize(
    "competition, expected", [("ucl", "clubelo"), ("laliga", "seed")]
)
def test_elo_prefers_cache_ratings_over_seed(
    competition: str, expected: str, monkeypatch, fake_cache
):
    """Boot-time ratings win and are labelled with the source they came from."""
    fake_cache(competition, {
        "elo_ratings": {"Real Madrid": 1832.5, "Bayern": 1801.0},
    })
    payload = _client(competition).get("/api/elo").json()
    assert payload["ratings"] == {"Real Madrid": 1832.5, "Bayern": 1801.0}
    assert payload["source"] == expected


def test_elo_reports_when_clubelo_ratings_were_read(monkeypatch, fake_cache):
    """Real ClubElo values carry the store's fetch stamp, not a blank."""
    import web.ucl_app as ucl

    fake_cache("ucl", {
        "elo_ratings": {"Real Madrid": 1832.5},
        "signals": {"refined_elo": {
            "provenance": "clubelo",
            "as_of": "2026-09-30T04:15:00+00:00",
        }},
    })
    payload = TestClient(ucl.ucl_app).get("/api/elo").json()
    assert payload["source"] == "clubelo"
    assert payload["as_of"] == "2026-09-30T04:15:00+00:00"


def test_elo_coefficient_fallback_has_no_as_of(monkeypatch, fake_cache):
    """A coefficient estimate has no date, so it must not be given one."""
    import web.ucl_app as ucl

    fake_cache("ucl", {
        "elo_ratings": {"Real Madrid": 1832.5},
        "signals": {"refined_elo": {
            "provenance": "coefficient_derived",
            "as_of": "2026-09-30T04:15:00+00:00",
        }},
    })
    payload = TestClient(ucl.ucl_app).get("/api/elo").json()
    assert payload["source"] == "coefficient"
    assert payload["as_of"] == ""


def test_elo_worldcup_reads_teams_cache(monkeypatch):
    import web.wc_app as wc

    monkeypatch.setattr(wc, "cache", {
        "teams": [{"name": "Brazil", "elo": 1712.0}, {"name": "Japan", "elo": 1543.25}],
    })
    payload = TestClient(wc.wc_app).get("/api/elo").json()
    assert payload == {
        "ratings": {"Brazil": 1712.0, "Japan": 1543.25},
        "source": "teams",
        "as_of": "",
    }


def test_elo_never_fetches(monkeypatch):
    """A GET must never reach ClubElo (monkeypatched to explode)."""
    import web.ucl_app as ucl

    def _boom(*_args, **_kwargs):
        raise AssertionError("/api/elo must not fetch Elo ratings")

    monkeypatch.setattr(ucl, "fetch_team_elos", _boom)
    assert TestClient(ucl.ucl_app).get("/api/elo").status_code == 200


@pytest.mark.parametrize("competition", ["ucl", "laliga"])
def test_blend_contract(competition: str):
    payload = _client(competition).get("/api/blend").json()
    assert set(payload) == BLEND_KEYS
    assert payload["threshold"] == 30
    assert isinstance(payload["n_matches_for_calibration"], int)
    assert payload["n_matches_for_calibration"] >= 0
    # A cold start reports no weights and no signals — never fabricated ones.
    if payload["calibration_status"] == "cold_start":
        assert payload["blend_weights"] == {}
        assert payload["n_signals_available"] == 0


def test_blend_laliga_reports_real_weights_never_fabricated():
    """LaLiga is calibrated once run_calibration_task() has run; either way
    the payload is honest — real fitted weights, or an empty cold start."""
    payload = _client("laliga").get("/api/blend").json()
    if payload["calibration_status"] == "cold_start":
        assert payload["blend_weights"] == {}
        assert payload["available_signals"] == []
        return
    weights = payload["blend_weights"]
    assert set(weights) == set(payload["available_signals"])
    assert payload["n_signals_available"] == len(weights)
    assert all(isinstance(w, (int, float)) and w >= 0 for w in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert payload["n_matches_for_calibration"] >= payload["threshold"]


def test_blend_ucl_weights_are_real_artifact_numbers():
    payload = _client("ucl").get("/api/blend").json()
    weights = payload["blend_weights"]
    assert set(weights) == set(payload["available_signals"])
    assert payload["n_signals_available"] == len(weights)
    assert all(isinstance(w, (int, float)) and w > 0 for w in weights.values())
    if weights:
        # Weights are only reported as calibrated on a real match count.
        assert payload["n_matches_for_calibration"] >= payload["threshold"]


def test_blend_worldcup_route_unchanged():
    """WC keeps its own compute_blend_info-backed route."""
    assert set(_client("worldcup").get("/api/blend").json()) == BLEND_KEYS
