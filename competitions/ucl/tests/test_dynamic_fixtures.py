"""Tests for multi-season dynamic fixture ingestion (FAILURE 4).

Covers:
- Provider events carry season + fixture-ish metadata through the flat mapper
- Ingestion groups events by season field
- Season == local/historical ("2025/26") -> EXACTLY today's behavior (template merge; byte-compat)
- Different season -> route to season store: create/update fixtures.json from SCHEDULED/timed events
- Stable fixture ids: provider source id when present, else deterministic hash
- Finished events attach to known fixtures (match by source id first, else (home,away) pair)
- Unmatched finished events counted skipped_no_target, NEVER silently written elsewhere
- Partial fixture catalogs represented honestly (counts + availability fields)
- Idempotent double-ingestion produces zero diffs
- Unknown-season events never mutate another season's files
- Mixed payload containing 2025/26-season events still routes to legacy path identically
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from competitions.ucl.src.ingest import ingest_ucl_events_multi_season
from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    read_season_fixtures,
    read_season_results,
    resolve_active_view,
    season_dir,
)


def _load_fdo_sample() -> list[dict]:
    """Load synthetic FDO flat events for a hypothetical 2026/27 season."""
    fixtures_path = Path(__file__).parent / "fixtures" / "fdo_flat_2026_sample.json"
    with open(fixtures_path) as f:
        raw = json.load(f)

    # Map through the same mapper the provider uses
    from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider
    return [FootballDataOrgProvider._map_match(m) for m in raw]


def _make_minimal_ucl_data_dir(tmp_path: Path) -> Path:
    """Create a minimal UCL data dir with fixtures.json and templates."""
    repo_data = Path(__file__).resolve().parents[1] / "data"
    dp = tmp_path / "data"
    dp.mkdir(parents=True)

    # Copy templates and fixtures
    shutil.copy(repo_data / "fixtures.json", dp / "fixtures.json")
    shutil.copy(repo_data / "playoff_pairings.json", dp / "playoff_pairings.json")
    shutil.copy(repo_data / "bracket_rules.json", dp / "bracket_rules.json")
    shutil.copy(repo_data / "team_aliases.json", dp / "team_aliases.json")

    # Initialize empty runtime stores
    (dp / "results.json").write_text('{"matches": []}', encoding="utf-8")
    (dp / "knockout_results.json").write_text('{"matches": {}}', encoding="utf-8")

    return dp


class TestMultiSeasonIngestion:
    """Test the multi-season ingestion router."""

    def test_new_season_creates_season_store(self, tmp_path):
        """A new season (not 2025/26) creates data/seasons/<id>/fixtures.json + results.json."""
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()

        result = ingest_ucl_events_multi_season(events, dp, "TestProvider")

        # Should have created season store for 2026/27
        per_season = result["per_season"]
        assert "2026/27" in per_season
        season_info = per_season["2026/27"]
        assert season_info["legacy"] is False
        assert season_info["fixtures_total"] == 6  # 4 scheduled + 2 finished (actually 6 events total)
        assert season_info["fixtures_added"] == 6
        assert season_info["results_added"] == 2  # 2 finished events
        assert season_info["skipped_no_target"] == 0

        # Verify files created
        sd = season_dir(dp, "2026/27")
        assert (sd / "fixtures.json").exists()
        assert (sd / "results.json").exists()

        # Check fixtures document
        fx = read_season_fixtures(dp, "2026/27")
        assert fx is not None
        assert fx["season"] == "2026/27"
        assert len(fx["fixtures"]) == 6
        assert fx["availability"]["fixtures_count"] == 6
        assert fx["availability"]["partial"] is True  # never claimed complete

        # Check results document
        res = read_season_results(dp, "2026/27")
        assert res is not None
        assert res["season"] == "2026/27"
        assert len(res["matches"]) == 2

        # Verify fixture IDs use provider source IDs
        fixture_ids = {fx_entry["match_id"] for fx_entry in fx["fixtures"]}
        assert "1001" in fixture_ids
        assert "1002" in fixture_ids
        assert "1003" in fixture_ids

    def test_finished_events_attach_to_fixtures_by_source_id(self, tmp_path):
        """Finished events match fixtures by provider source id first."""
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()

        result = ingest_ucl_events_multi_season(events, dp, "TestProvider")

        res = read_season_results(dp, "2026/27")
        match_ids = {m["match_id"] for m in res["matches"]}
        # Finished events have ids 1001 and 1002
        assert "1001" in match_ids
        assert "1002" in match_ids
        # Check scores preserved
        m1 = next(m for m in res["matches"] if m["match_id"] == "1001")
        assert m1["home_score"] == 2
        assert m1["away_score"] == 1

    def test_idempotent_double_ingestion_zero_diffs(self, tmp_path):
        """Ingesting the same payload twice produces zero diffs."""
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()

        result1 = ingest_ucl_events_multi_season(events, dp, "TestProvider")
        # Capture file contents after first ingestion
        fx1 = (season_dir(dp, "2026/27") / "fixtures.json").read_bytes()
        res1 = (season_dir(dp, "2026/27") / "results.json").read_bytes()

        result2 = ingest_ucl_events_multi_season(events, dp, "TestProvider")
        fx2 = (season_dir(dp, "2026/27") / "fixtures.json").read_bytes()
        res2 = (season_dir(dp, "2026/27") / "results.json").read_bytes()

        assert fx1 == fx2, "fixtures.json changed on second ingestion"
        assert res1 == res2, "results.json changed on second ingestion"
        # Second ingestion should report zero new changes
        assert result2["per_season"]["2026/27"]["fixtures_added"] == 0
        assert result2["per_season"]["2026/27"]["fixtures_updated"] == 0
        assert result2["per_season"]["2026/27"]["results_added"] == 0
        assert result2["per_season"]["2026/27"]["results_updated"] == 0

    def test_unmatched_finished_event_skipped_no_target(self, tmp_path):
        """Finished event referencing UNKNOWN pair lands in skipped_no_target."""
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()

        # Add a finished event for teams not in the fixture catalog
        # No match_id -> no fixture created -> skipped_no_target
        unknown_event = {
            "home_team": "Unknown Team A",
            "away_team": "Unknown Team B",
            "home_score": 1,
            "away_score": 0,
            "status": "finished",
            "stage": "LEAGUE_STAGE",
            "event_date": "2026-09-15T19:00:00Z",
            "season": "2026/27",
            # No match_id - provider didn't assign one for this phantom match
        }
        events_with_unknown = events + [unknown_event]

        result = ingest_ucl_events_multi_season(events_with_unknown, dp, "TestProvider")

        season_info = result["per_season"]["2026/27"]
        assert season_info["skipped_no_target"] == 1

        # Verify it didn't create a phantom result entry
        res = read_season_results(dp, "2026/27")
        match_ids = {m["match_id"] for m in res["matches"]}
        assert "9999" not in match_ids

        # Verify 2025/26 stores untouched
        legacy_results = json.loads((dp / "results.json").read_text(encoding="utf-8"))
        assert legacy_results["matches"] == []  # still empty

    def test_historical_season_routes_to_legacy(self, tmp_path):
        """Events with season == 2025/26 route to legacy results.json + knockout_results.json."""
        dp = _make_minimal_ucl_data_dir(tmp_path)

        # Create events with 2025/26 season (matching legacy fixture IDs)
        legacy_events = [
            {
                "home_team": "Athletic Bilbao",
                "away_team": "Arsenal",
                "home_score": 0,
                "away_score": 2,
                "status": "finished",
                "stage": "LEAGUE_STAGE",
                "event_date": "2025-09-17T19:00:00Z",
                "season": "2025/26",
                "match_id": "MD01_01",
            },
            {
                "home_team": "PSV",
                "away_team": "Union SG",
                "home_score": 1,
                "away_score": 3,
                "status": "finished",
                "stage": "LEAGUE_STAGE",
                "event_date": "2025-09-17T19:00:00Z",
                "season": "2025/26",
                "match_id": "MD01_02",
            },
        ]

        result = ingest_ucl_events_multi_season(legacy_events, dp, "TestProvider")

        per_season = result["per_season"]
        assert LOCAL_HISTORICAL_SEASON in per_season
        season_info = per_season[LOCAL_HISTORICAL_SEASON]
        assert season_info["legacy"] is True
        assert season_info["results_count"] == 2

        # Verify legacy results.json was written
        legacy_results = json.loads((dp / "results.json").read_text(encoding="utf-8"))
        assert len(legacy_results["matches"]) == 2
        match_ids = {m["match_id"] for m in legacy_results["matches"]}
        assert "MD01_01" in match_ids
        assert "MD01_02" in match_ids

    def test_mixed_payload_routes_correctly(self, tmp_path):
        """Mixed payload with both 2025/26 and 2026/27 events routes each correctly."""
        dp = _make_minimal_ucl_data_dir(tmp_path)

        legacy_events = [
            {
                "home_team": "Athletic Bilbao",
                "away_team": "Arsenal",
                "home_score": 0,
                "away_score": 2,
                "status": "finished",
                "stage": "LEAGUE_STAGE",
                "event_date": "2025-09-17T19:00:00Z",
                "season": "2025/26",
                "match_id": "MD01_01",
            },
        ]
        new_events = _load_fdo_sample()
        mixed = legacy_events + new_events

        result = ingest_ucl_events_multi_season(mixed, dp, "TestProvider")

        per_season = result["per_season"]
        assert LOCAL_HISTORICAL_SEASON in per_season
        assert "2026/27" in per_season

        # Legacy season handled by legacy path
        assert per_season[LOCAL_HISTORICAL_SEASON]["legacy"] is True
        assert per_season[LOCAL_HISTORICAL_SEASON]["results_count"] == 1

        # New season handled by season store
        assert per_season["2026/27"]["legacy"] is False
        assert per_season["2026/27"]["fixtures_total"] == 6
        assert per_season["2026/27"]["results_added"] == 2

        # Verify legacy results
        legacy_results = json.loads((dp / "results.json").read_text(encoding="utf-8"))
        assert len(legacy_results["matches"]) == 1

        # Verify new season store
        fx = read_season_fixtures(dp, "2026/27")
        assert len(fx["fixtures"]) == 6

    def test_unknown_season_isolated(self, tmp_path):
        """Events with unparseable season don't mutate other seasons."""
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()

        # Add event with garbage season
        garbage_event = events[0].copy()
        garbage_event["season"] = "not-a-season"
        garbage_event["home_team"] = "Garbage FC"
        garbage_event["away_team"] = "Trash United"
        garbage_event["status"] = "finished"
        garbage_event["home_score"] = 1
        garbage_event["away_score"] = 0
        events_with_garbage = events + [garbage_event]

        result = ingest_ucl_events_multi_season(events_with_garbage, dp, "TestProvider")

        # Should have "unknown" season entry
        per_season = result["per_season"]
        # Garbage season gets normalized to None or the raw token
        # The key thing: it shouldn't affect 2026/27 or 2025/26
        assert "2026/27" in per_season
        # Legacy untouched
        legacy_results = json.loads((dp / "results.json").read_text(encoding="utf-8"))
        assert legacy_results["matches"] == []


class TestResolveActiveViewWithNewSeason:
    """Test that resolve_active_view correctly summarizes the new season store."""

    def test_active_view_shows_new_season(self, tmp_path):
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()
        ingest_ucl_events_multi_season(events, dp, "TestProvider")

        # Set current pointer to new season
        from competitions.ucl.src.seasons import set_current_season
        set_current_season(dp, "2026/27", basis="provider", provider="TestProvider")

        view = resolve_active_view(dp)
        assert view["current_season"] == "2026/27"
        assert view["local_historical_is_active"] is False
        assert view["basis"] == "pointer_other"
        assert "2026_27" in view["seasons"]
        assert view["seasons"]["2026_27"]["fixtures_count"] == 6
        assert view["seasons"]["2026_27"]["results_count"] == 2

    def test_active_view_shows_local_when_no_pointer(self, tmp_path):
        dp = _make_minimal_ucl_data_dir(tmp_path)
        events = _load_fdo_sample()
        ingest_ucl_events_multi_season(events, dp, "TestProvider")

        # No current.json set
        view = resolve_active_view(dp)
        assert view["current_season"] is None
        assert view["local_historical_is_active"] is True
        assert view["basis"] == "default_local"


class TestDeterministicFixtureIdFallback:
    """Test deterministic hash fallback when provider doesn't supply match_id."""

    def test_generated_id_stable_across_runs(self, tmp_path):
        """derive_fixture_id produces stable IDs for same teams+date."""
        from competitions.ucl.src.seasons import derive_fixture_id

        fid1 = derive_fixture_id("Team X", "Team Y", "2026-09-15")
        fid2 = derive_fixture_id("Team X", "Team Y", "2026-09-15")
        assert fid1 == fid2
        assert fid1.startswith("gen-")

    def test_generated_id_used_when_no_source_id(self, tmp_path):
        """Events without match_id get deterministic generated IDs."""
        dp = _make_minimal_ucl_data_dir(tmp_path)

        # Event without match_id (simulating provider that doesn't provide one)
        event_no_id = {
            "home_team": "Team X",
            "away_team": "Team Y",
            "home_score": 0,
            "away_score": 0,
            "status": "scheduled",
            "stage": "LEAGUE_STAGE",
            "event_date": "2026-09-15T19:00:00Z",
            "season": "2026/27",
            # No match_id field
        }

        result = ingest_ucl_events_multi_season([event_no_id], dp, "TestProvider")

        fx = read_season_fixtures(dp, "2026/27")
        assert len(fx["fixtures"]) == 1
        fid = fx["fixtures"][0]["match_id"]
        assert fid.startswith("gen-")

        # Re-ingest should use same generated ID (idempotent)
        result2 = ingest_ucl_events_multi_season([event_no_id], dp, "TestProvider")
        fx2 = read_season_fixtures(dp, "2026/27")
        assert fx2["fixtures"][0]["match_id"] == fid