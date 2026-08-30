"""Tests for competitions.ucl.src.lifecycle.discover (Exchange 3 → 4).

Builds temporary data dirs from the REAL repo stores (fixtures.json,
results.json, knockout_results.json) and mutates copies to cover each
lifecycle stage. Evidence-based expectations only — no fabrication.

Exchange 4 adds season-transition logic tests.
"""

import json
from pathlib import Path

import pytest

from competitions.ucl.src.lifecycle import LIFECYCLE_CONTRACT, discover, SUFFICIENT_FIXTURES_THRESHOLD, SUFFICIENT_RESULTS_THRESHOLD
from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    empty_fixtures_document,
    empty_results_document,
    season_dir,
    set_current_season,
    write_season_fixtures,
    write_season_results,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DATA_DIR = REPO_ROOT / "competitions" / "ucl" / "data"

SEASON = "2025/26"
TOTAL_LEAGUE = 144

CONTRACT_KEYS = {
    "season", "stage", "progress", "historical", "basis",
    "provider_current_season", "season_mismatch", "label", "diagnostics",
}

EXPECTED_COMPLETED = {
    "season": SEASON,
    "stage": "completed",
    "progress": {"played": TOTAL_LEAGUE, "total": TOTAL_LEAGUE},
    "historical": [SEASON],
    "basis": "derived",
    "provider_current_season": None,
    "season_mismatch": False,
    "label": f"{SEASON} - completed",
    "diagnostics": [],
}


def _real_rows() -> list:
    payload = json.loads((REAL_DATA_DIR / "results.json").read_text(encoding="utf-8"))
    rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
    assert isinstance(rows, list) and len(rows) == TOTAL_LEAGUE
    return rows


def _real_knockout() -> dict:
    return json.loads(
        (REAL_DATA_DIR / "knockout_results.json").read_text(encoding="utf-8"))


def _make_data_dir(
    tmp_path: Path,
    *,
    fixtures: bool = True,
    results_rows: list | None = None,
    knockout: dict | None = None,
    seasons: dict | None = None,
) -> Path:
    dst = tmp_path / "data"
    dst.mkdir()
    if fixtures:
        (dst / "fixtures.json").write_text(
            (REAL_DATA_DIR / "fixtures.json").read_text(encoding="utf-8"),
            encoding="utf-8")
    if results_rows is not None:
        (dst / "results.json").write_text(
            json.dumps({"matches": results_rows}), encoding="utf-8")
    if knockout is not None:
        (dst / "knockout_results.json").write_text(
            json.dumps(knockout), encoding="utf-8")
    if seasons is not None:
        (dst / "seasons.json").write_text(json.dumps(seasons), encoding="utf-8")
    return dst


def _completed_dir(tmp_path: Path) -> Path:
    return _make_data_dir(
        tmp_path, results_rows=_real_rows(), knockout=_real_knockout())


def _add_provider_season_store(
    data_dir: Path,
    provider_season: str,
    fixtures_count: int = 0,
    results_count: int = 0,
) -> None:
    """Add a provider season store under data/seasons/<season_id>/ with given counts."""
    sd = season_dir(data_dir, provider_season)
    sd.mkdir(parents=True, exist_ok=True)

    fx_doc = empty_fixtures_document(provider_season)
    fx_doc["fixtures"] = [{"match_id": f"gen-{i:04d}"} for i in range(fixtures_count)]
    fx_doc["availability"]["fixtures_count"] = fixtures_count
    fx_doc["availability"]["partial"] = fixtures_count < TOTAL_LEAGUE
    write_season_fixtures(data_dir, provider_season, fx_doc)

    res_doc = empty_results_document(provider_season)
    res_doc["matches"] = [
        {"match_id": f"gen-{i:04d}", "home_score": 1, "away_score": 0}
        for i in range(results_count)
    ]
    write_season_results(data_dir, provider_season, res_doc)


class TestSeasonTransition:
    """Exchange 4: Provider season transition logic tests."""

    def test_provider_season_newer_sufficient_fixtures_switches(self, tmp_path):
        """Provider season newer + fixtures >= 100 -> switch to provider, basis='provider'."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=100, results_count=0)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == provider_season
        assert result["basis"] == "provider"
        assert result["season_mismatch"] is True
        assert result["provider_current_season"] == provider_season
        assert "provider_season_insufficient_data" not in result["diagnostics"]
        assert "provider_season_not_in_store" not in result["diagnostics"]

    def test_provider_season_newer_sufficient_results_switches(self, tmp_path):
        """Provider season newer + results >= 50 -> switch to provider, basis='provider'."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=0, results_count=50)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == provider_season
        assert result["basis"] == "provider"
        assert result["season_mismatch"] is True

    def test_provider_season_insufficient_data_keeps_local(self, tmp_path):
        """Provider season newer but fixtures < 100 AND results < 50 -> keep local, diagnostic added."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=50, results_count=20)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == SEASON
        assert result["basis"] == "derived"
        assert result["season_mismatch"] is True
        assert result["provider_current_season"] == provider_season
        assert "provider_season_insufficient_data" in result["diagnostics"]

    def test_provider_season_not_in_store_keeps_local(self, tmp_path):
        """Provider season not in store at all -> keep local, diagnostic added."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == SEASON
        assert result["basis"] == "derived"
        assert result["season_mismatch"] is True
        assert "provider_season_not_in_store" in result["diagnostics"]

    def test_provider_season_older_no_mismatch(self, tmp_path):
        """Provider season same as local -> no mismatch, basis derived."""
        data_dir = _completed_dir(tmp_path)
        result = discover(data_dir, provider_season=SEASON)

        assert result["season"] == SEASON
        assert result["basis"] == "derived"
        assert result["season_mismatch"] is False
        assert result["provider_current_season"] is None

    def test_no_provider_hint_derived_behavior(self, tmp_path):
        """No provider_season arg -> derived behavior unchanged."""
        data_dir = _completed_dir(tmp_path)
        result = discover(data_dir)

        assert result["season"] == SEASON
        assert result["basis"] == "derived"
        assert result["season_mismatch"] is False
        assert result["provider_current_season"] is None
        assert result["stage"] == "completed"

    def test_threshold_constants_documented(self):
        """Threshold constants are defined and have expected values."""
        assert SUFFICIENT_FIXTURES_THRESHOLD == 100
        assert SUFFICIENT_RESULTS_THRESHOLD == 50

    def test_provider_season_fixtures_99_results_49_insufficient(self, tmp_path):
        """Fixtures=99 (<100) AND results=49 (<50) -> insufficient, keep local."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=99, results_count=49)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == SEASON
        assert result["basis"] == "derived"
        assert result["season_mismatch"] is True
        assert "provider_season_insufficient_data" in result["diagnostics"]

    def test_provider_season_fixtures_100_results_0_sufficient(self, tmp_path):
        """Fixtures=100 (>=100) AND results=0 -> sufficient, switch."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=100, results_count=0)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == provider_season
        assert result["basis"] == "provider"

    def test_provider_season_fixtures_0_results_50_sufficient(self, tmp_path):
        """Fixtures=0 AND results=50 (>=50) -> sufficient, switch."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=0, results_count=50)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == provider_season
        assert result["basis"] == "provider"


class TestProviderSeasonWithDifferentLocalStages:
    """Transition logic with various local season stages."""

    def test_local_active_provider_sufficient_switches(self, tmp_path):
        """Local season active, provider sufficient -> switch season label."""
        data_dir = _make_data_dir(tmp_path, results_rows=_real_rows()[:60])
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=100, results_count=0)
        result = discover(data_dir, provider_season=provider_season)

        # Once provider season is active, stage/progress are scoped to that season.
        assert result["season"] == provider_season
        assert result["basis"] == "provider"
        assert result["stage"] == "future"
        assert result["progress"]["played"] == 0

    def test_local_future_provider_sufficient_switches(self, tmp_path):
        """Local season future, provider sufficient -> switch season label."""
        data_dir = _make_data_dir(tmp_path)
        provider_season = "2026/27"
        _add_provider_season_store(data_dir, provider_season, fixtures_count=144, results_count=144)
        result = discover(data_dir, provider_season=provider_season)

        assert result["season"] == provider_season
        assert result["basis"] == "provider"
        assert result["stage"] == "active"


class TestStageClassification:
    def test_completed_full_results_and_v2_knockout_store(self, tmp_path):
        """Full league results + champion on file => completed."""
        result = discover(_completed_dir(tmp_path))
        assert result == EXPECTED_COMPLETED

    def test_active_partial_results(self, tmp_path):
        """60 of 144 league matches played => active with honest progress."""
        result = discover(_make_data_dir(tmp_path, results_rows=_real_rows()[:60]))
        assert result == {
            "season": SEASON,
            "stage": "active",
            "progress": {"played": 60, "total": TOTAL_LEAGUE},
            "historical": [],
            "basis": "derived",
            "provider_current_season": None,
            "season_mismatch": False,
            "label": f"{SEASON} - active",
            "diagnostics": ["ucl.league_incomplete", "ucl.knockout_store_unavailable", "ucl.champion_missing"],
        }

    def test_active_league_complete_but_knockout_empty(self, tmp_path):
        """144/144 league but knockout store empty => NOT completed."""
        result = discover(_make_data_dir(
            tmp_path, results_rows=_real_rows(), knockout={"matches": {}}))
        assert result["stage"] == "active"
        assert result["progress"] == {"played": TOTAL_LEAGUE, "total": TOTAL_LEAGUE}
        assert result["historical"] == []
        assert result["label"] == f"{SEASON} - active"

    def test_active_league_complete_but_knockout_missing(self, tmp_path):
        """Knockout file absent entirely stays distinguishable from completed."""
        result = discover(_make_data_dir(tmp_path, results_rows=_real_rows()))
        assert result["stage"] == "active"

    def test_future_fixtures_only(self, tmp_path):
        """Fixtures present, zero played results => future."""
        result = discover(_make_data_dir(tmp_path))
        assert result == {
            "season": SEASON,
            "stage": "future",
            "progress": {"played": 0, "total": TOTAL_LEAGUE},
            "historical": [],
            "basis": "derived",
            "provider_current_season": None,
            "season_mismatch": False,
            "label": f"{SEASON} - future",
            "diagnostics": [],
        }

    def test_future_via_config_declaration_without_fixtures(self, tmp_path):
        """No fixtures, but tracked config declares the season => future."""
        dst = _make_data_dir(
            tmp_path, fixtures=False,
            seasons={"seasons": [{"id": "2026/27", "status": "scheduled"}]})
        result = discover(dst)
        assert result["stage"] == "unknown"

    def test_unknown_empty_data_dir(self, tmp_path):
        """Zero evidence in every store => unknown, zeroed progress."""
        result = discover(_make_data_dir(tmp_path, fixtures=False))
        assert result["stage"] == "unknown"
        assert result["progress"] == {"played": 0, "total": 0}
        assert result["historical"] == []


class TestProviderSeason:
    def test_mismatch_reported_not_hidden(self, tmp_path):
        """Provider on a newer season WITH sufficient store data => switch, basis 'provider'."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        # Add provider season store with sufficient data
        _add_provider_season_store(data_dir, provider_season, fixtures_count=100, results_count=0)
        result = discover(data_dir, provider_season=provider_season)
        assert result["provider_current_season"] == provider_season
        assert result["season_mismatch"] is True
        assert result["basis"] == "provider"
        # Season switches to provider
        assert result["season"] == provider_season
        assert result["stage"] == "future"

    def test_mismatch_no_store_keeps_local(self, tmp_path):
        """Provider on a newer season WITHOUT store data => keep local, basis derived, diagnostic."""
        data_dir = _completed_dir(tmp_path)
        provider_season = "2026/27"
        # No provider season store added

        result = discover(data_dir, provider_season=provider_season)
        assert result["provider_current_season"] == provider_season
        assert result["season_mismatch"] is True
        assert result["basis"] == "derived"
        assert result["season"] == SEASON
        assert "provider_season_not_in_store" in result["diagnostics"]

    def test_matching_provider_season_is_no_mismatch(self, tmp_path):
        result = discover(_completed_dir(tmp_path), provider_season=SEASON)
        assert result["provider_current_season"] is None
        assert result["season_mismatch"] is False
        assert result["basis"] == "derived"


class TestTrackedConfig:
    def test_seasons_json_respected(self, tmp_path):
        """seasons.json feeds the historical list; basis becomes 'config'."""
        config = {"seasons": [
            {"id": "2026/27", "status": "upcoming"},
            {"id": "2024/25", "status": "completed"},
            {"id": SEASON, "status": "completed"},
        ]}
        result = discover(_make_data_dir(
            tmp_path,
            results_rows=_real_rows(),
            knockout=_real_knockout(),
            seasons=config))
        assert result["basis"] == "config"
        assert result["historical"] == ["2024/25", SEASON]
        assert result["stage"] == "completed"

    def test_malformed_seasons_json_falls_back_to_derived(self, tmp_path):
        dst = _make_data_dir(tmp_path, results_rows=_real_rows()[:10])
        (dst / "seasons.json").write_text("{not json", encoding="utf-8")
        result = discover(dst)
        assert result["basis"] == "derived"
        assert result["stage"] == "active"


class TestPhaseReuse:
    def test_precomputed_phase_is_reused_not_recomputed(self, tmp_path, monkeypatch):
        """When phase= is supplied the orchestrator must never run again."""
        import competitions.ucl.src.orchestrator as orch

        dst = _completed_dir(tmp_path)
        baseline = discover(dst)

        def _boom(_data_dir):
            raise AssertionError("phase was supplied; must not recompute")

        monkeypatch.setattr(orch, "compute_competition_phase", _boom)
        precomputed = json.loads(json.dumps({
            "phase": "completed", "label": "Completed", "champion": "PSG",
            "progress": {"played": 144, "total": 144},
            "stores": {"league_results": "available",
                       "knockout_results": "available"},
        }))
        result = discover(dst, phase=precomputed)
        assert result == baseline

    def test_lazy_phase_computation_matches_direct_call(self, tmp_path):
        """Without phase=, discover computes it lazily and agrees."""
        dst = _completed_dir(tmp_path)
        from competitions.ucl.src.orchestrator import compute_competition_phase
        assert discover(dst) == discover(dst, phase=compute_competition_phase(dst))


class TestContractAndDeterminism:
    def test_exact_key_contract(self, tmp_path):
        dst = _completed_dir(tmp_path)
        assert set(discover(dst).keys()) == CONTRACT_KEYS
        assert tuple(discover(dst).keys()) == LIFECYCLE_CONTRACT

    def test_deterministic_across_calls(self, tmp_path):
        dst = _completed_dir(tmp_path)
        first = discover(dst, provider_season="2026/27")
        second = discover(dst, provider_season="2026/27")
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
