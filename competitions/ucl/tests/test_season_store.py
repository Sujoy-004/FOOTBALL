"""Tests for competitions.ucl.src.seasons — season store abstraction."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    derive_fixture_id,
    empty_fixtures_document,
    empty_results_document,
    get_current_season,
    list_seasons,
    normalize_season_token,
    read_season_fixtures,
    read_season_results,
    resolve_active_view,
    season_dir,
    season_dir_id,
    season_display_id,
    set_current_season,
    write_season_fixtures,
    write_season_results,
)


class TestNormalizeSeasonToken:
    def test_none_returns_none(self):
        assert normalize_season_token(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_season_token("") is None

    def test_int_start_year(self):
        assert normalize_season_token(2026) == "2026/27"
        assert normalize_season_token(2025) == "2025/26"

    def test_full_strings(self):
        assert normalize_season_token("2025/26") == "2025/26"
        assert normalize_season_token("2026-27") == "2026/27"
        assert normalize_season_token("2025_26") == "2025/26"
        assert normalize_season_token("2025 26") == "2025/26"
        assert normalize_season_token("2026-2027") == "2026/27"

    def test_short_strings(self):
        assert normalize_season_token("25/26") == "2025/26"
        assert normalize_season_token("26-27") == "2026/27"

    def test_unparseable_returns_trimmed(self):
        assert normalize_season_token("  weird-season  ") == "weird-season"
        assert normalize_season_token("2025/27") == "2025/27"  # invalid end year


class TestSeasonDirId:
    def test_slash_to_underscore(self):
        assert season_dir_id("2026/27") == "2026_27"
        assert season_dir_id("2025/26") == "2025_26"

    def test_special_chars_sanitized(self):
        assert season_dir_id("2026-27") == "2026_27"
        assert season_dir_id("weird/season") == "weird_season"


class TestSeasonDir:
    def test_path_construction(self, tmp_path):
        dp = tmp_path
        p = season_dir(dp, "2026/27")
        assert p == dp / "seasons" / "2026_27"


class TestCurrentSeasonPointer:
    def test_set_and_get_roundtrip(self, tmp_path):
        payload = set_current_season(tmp_path, "2026/27", basis="provider", provider="FDO")
        assert payload["season"] == "2026/27"
        assert payload["basis"] == "provider"
        assert payload["provider"] == "FDO"

        got = get_current_season(tmp_path)
        assert got is not None
        assert got["season"] == "2026/27"
        assert got["basis"] == "provider"
        assert got["provider"] == "FDO"

    def test_atomic_write_no_partial_file(self, tmp_path):
        # Write and verify no temp files left
        set_current_season(tmp_path, "2026/27")
        temp_files = [p for p in tmp_path.iterdir() if ".tmp" in p.name]
        assert temp_files == []

    def test_corrupt_current_json_returns_none(self, tmp_path):
        (tmp_path / "current.json").write_text("{broken", encoding="utf-8")
        assert get_current_season(tmp_path) is None

    def test_malformed_current_json_returns_none(self, tmp_path):
        (tmp_path / "current.json").write_text('{"season": ""}', encoding="utf-8")
        assert get_current_season(tmp_path) is None

    def test_missing_current_json_returns_none(self, tmp_path):
        assert get_current_season(tmp_path) is None


class TestPerSeasonStores:
    def test_write_read_fixtures_roundtrip(self, tmp_path):
        doc = empty_fixtures_document("2026/27")
        doc["fixtures"].append({
            "match_id": "gen-abc123",
            "team_a": "Team A",
            "team_b": "Team B",
            "event_date": "2026-09-15T19:00:00+00:00",
            "stage": "LEAGUE_STAGE",
            "status": "scheduled",
        })
        doc["availability"]["fixtures_count"] = 1
        write_season_fixtures(tmp_path, "2026/27", doc)

        read_back = read_season_fixtures(tmp_path, "2026/27")
        assert read_back is not None
        assert read_back["season"] == "2026/27"
        assert len(read_back["fixtures"]) == 1
        assert read_back["fixtures"][0]["match_id"] == "gen-abc123"

    def test_write_read_results_roundtrip(self, tmp_path):
        doc = empty_results_document("2026/27")
        doc["matches"].append({
            "match_id": "gen-abc123",
            "team_a": "Team A",
            "team_b": "Team B",
            "home_score": 2,
            "away_score": 1,
        })
        write_season_results(tmp_path, "2026/27", doc)

        read_back = read_season_results(tmp_path, "2026/27")
        assert read_back is not None
        assert read_back["season"] == "2026/27"
        assert len(read_back["matches"]) == 1
        assert read_back["matches"][0]["home_score"] == 2

    def test_missing_returns_none(self, tmp_path):
        assert read_season_fixtures(tmp_path, "2026/27") is None
        assert read_season_results(tmp_path, "2026/27") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        sd = season_dir(tmp_path, "2026/27")
        sd.mkdir(parents=True)
        (sd / "fixtures.json").write_text("{broken", encoding="utf-8")
        assert read_season_fixtures(tmp_path, "2026/27") is None


class TestListSeasons:
    def test_lists_only_dirs_with_store_files(self, tmp_path):
        (tmp_path / "seasons" / "2026_27").mkdir(parents=True)
        (tmp_path / "seasons" / "2026_27" / "fixtures.json").write_text('{"fixtures": []}')
        (tmp_path / "seasons" / "2027_28").mkdir(parents=True)
        # empty dir - should not be listed
        (tmp_path / "seasons" / "empty_dir").mkdir(parents=True)

        assert list_seasons(tmp_path) == ["2026_27"]


class TestDeriveFixtureId:
    def test_deterministic(self):
        fid1 = derive_fixture_id("Team A", "Team B", "2026-09-15")
        fid2 = derive_fixture_id("Team A", "Team B", "2026-09-15")
        assert fid1 == fid2
        assert fid1.startswith("gen-")
        assert len(fid1) == 20  # "gen-" + 16 hex chars

    def test_order_independent(self):
        fid1 = derive_fixture_id("Team A", "Team B", "2026-09-15")
        fid2 = derive_fixture_id("Team B", "Team A", "2026-09-15")
        # Should be different because order matters for home/away
        assert fid1 != fid2


class TestResolveActiveView:
    def test_default_local_no_pointer(self, tmp_path):
        view = resolve_active_view(tmp_path)
        assert view["current"] is None
        assert view["current_season"] is None
        assert view["local_season"] == LOCAL_HISTORICAL_SEASON
        assert view["local_historical_is_active"] is True
        assert view["basis"] == "default_local"

    def test_pointer_local(self, tmp_path):
        set_current_season(tmp_path, LOCAL_HISTORICAL_SEASON)
        view = resolve_active_view(tmp_path)
        assert view["current_season"] == LOCAL_HISTORICAL_SEASON
        assert view["local_historical_is_active"] is True
        assert view["basis"] == "pointer_local"

    def test_pointer_other(self, tmp_path):
        set_current_season(tmp_path, "2026/27")
        # Create season store so it's listed
        sd = season_dir(tmp_path, "2026/27")
        sd.mkdir(parents=True)
        write_season_fixtures(tmp_path, "2026/27", empty_fixtures_document("2026/27"))

        view = resolve_active_view(tmp_path)
        assert view["current_season"] == "2026/27"
        assert view["local_historical_is_active"] is False
        assert view["basis"] == "pointer_other"
        assert "2026_27" in view["seasons"]

    def test_seasons_availability_counts(self, tmp_path):
        set_current_season(tmp_path, "2026/27")
        sd = season_dir(tmp_path, "2026/27")
        sd.mkdir(parents=True)
        fx_doc = empty_fixtures_document("2026/27")
        fx_doc["fixtures"] = [{"match_id": "1"}, {"match_id": "2"}]
        fx_doc["availability"]["fixtures_count"] = 2
        write_season_fixtures(tmp_path, "2026/27", fx_doc)

        res_doc = empty_results_document("2026/27")
        res_doc["matches"] = [{"match_id": "1"}]
        write_season_results(tmp_path, "2026/27", res_doc)

        view = resolve_active_view(tmp_path)
        assert view["seasons"]["2026_27"]["fixtures_count"] == 2
        assert view["seasons"]["2026_27"]["results_count"] == 1


class TestSeasonDisplayId:
    def test_directory_id_to_display(self):
        assert season_display_id("2026_27") == "2026/27"
        assert season_display_id("2025_26") == "2025/26"

    def test_other_ids_pass_through(self):
        assert season_display_id("weird-id") == "weird-id"
        assert season_display_id("2026/27") == "2026/27"