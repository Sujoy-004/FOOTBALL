"""Tests for the Elo sync module (elo_sync.py).

Covers TSV parsing, team name mapping, graduated correction,
validation, staleness levels, caching, and the full sync pipeline.
All tests use fixture data — no network access required.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.elo_sync import (
    apply_graduated_correction,
    get_staleness_level,
    parse_eloratings_tsv,
    resolve_team_names,
    sync_elo_from_eloratings,
    validate_eloratings_data,
)
from src.constants import ELORATINGS_TEAM_CODES


# ─── Fixture helpers ─────────────────────────────────────────────────────


def _make_tsv_row(code: str, rating: float, cols: int = 33) -> str:
    """Create a single TSV row matching eloratings.net World.tsv format.

    Column 2 (index 2) = team code, Column 3 (index 3) = Elo rating.
    Extra columns are filled with placeholder values.
    """
    parts = [f"VAL{i}" if i not in (2, 3) else (code if i == 2 else str(rating))
             for i in range(cols)]
    return "\t".join(parts)


def _make_tsv(rows: list[tuple[str, float]]) -> str:
    """Create a TSV string from a list of (code, rating) pairs."""
    return "\n".join(_make_tsv_row(code, rating) for code, rating in rows)


# ─── TestParse ───────────────────────────────────────────────────────────


class TestParse:
    """Tests for parse_eloratings_tsv."""

    def test_basic_tsv_parsing(self):
        """Parse 3-row TSV with valid data returns 3 tuples with correct types."""
        tsv = _make_tsv([("US", 2100.0), ("ES", 2157.0), ("FR", 2063.0)])
        parsed = parse_eloratings_tsv(tsv)
        assert len(parsed) == 3
        assert parsed[0] == ("US", 2100.0)
        assert parsed[1] == ("ES", 2157.0)
        assert parsed[2] == ("FR", 2063.0)

    def test_empty_input(self):
        """Empty string returns empty list."""
        assert parse_eloratings_tsv("") == []

    def test_skips_empty_rows(self):
        """TSV with blank lines skips them and returns only valid rows."""
        tsv = _make_tsv([("US", 2100.0)]) + "\n\n\n" + _make_tsv([("ES", 2157.0)])
        parsed = parse_eloratings_tsv(tsv)
        assert len(parsed) == 2

    def test_valid_rating_types(self):
        """Rating column is parsed as float."""
        tsv = _make_tsv([("US", 2100)])
        parsed = parse_eloratings_tsv(tsv)
        assert isinstance(parsed[0][1], float)
        assert parsed[0][1] == 2100.0

    def test_real_fixture(self):
        """Parses tests/fixtures/eloratings_world.tsv and returns 48+ tuples."""
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "eloratings_world.tsv"
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        content = fixture_path.read_text(encoding="utf-8")
        parsed = parse_eloratings_tsv(content)
        assert len(parsed) >= 48, f"Expected >= 48, got {len(parsed)}"
        # Check first row has valid code and rating
        code, rating = parsed[0]
        assert isinstance(code, str) and len(code) >= 2
        assert 1000 <= rating <= 2500

    def test_skips_row_with_non_numeric_rating(self):
        """Row where rating column is not a valid float should be skipped.

        Uses a non-numeric string (not NaN, which is technically a valid float)
        since that triggers the ValueError/TypeError catch in the parser.
        """
        # Row with non-numeric rating in col 3
        bad_row = "\t".join([f"VAL{i}" if i not in (2, 3) else ("XX" if i == 2 else "not_a_number") for i in range(33)])
        tsv = _make_tsv_row("US", 2100.0) + "\n" + bad_row
        parsed = parse_eloratings_tsv(tsv)
        assert len(parsed) == 1, f"Expected 1 valid row, got {len(parsed)}"
        assert parsed[0] == ("US", 2100.0)

    def test_skips_short_rows(self):
        """Row with fewer than 4 columns should be skipped."""
        tsv = "US\tUSA\tUS\n" + _make_tsv([("ES", 2157.0)])
        parsed = parse_eloratings_tsv(tsv)
        assert len(parsed) == 1


# ─── TestMapping ─────────────────────────────────────────────────────────


class TestMapping:
    """Tests for resolve_team_names."""

    def test_all_48_codes_resolve(self):
        """Every code in ELORATINGS_TEAM_CODES produces a canonical name."""
        # Build synthetic parsed list from all 48 codes
        parsed = [(code, 1500.0) for code in ELORATINGS_TEAM_CODES]
        # Create teams dict with all canonical names
        teams = {name: {"elo": 1500} for name in ELORATINGS_TEAM_CODES.values()}
        resolved = resolve_team_names(parsed, teams)
        # Every canonical name should be present
        for canonical in ELORATINGS_TEAM_CODES.values():
            assert canonical in resolved, f"Missing: {canonical}"
        assert len(resolved) == 48, f"Expected 48, got {len(resolved)}"

    def test_unmapped_code_warning(self):
        """A code not in ELORATINGS_TEAM_CODES should be absent from resolved dict."""
        parsed = [("US", 2100.0), ("XX", 1500.0)]
        teams = {"United States": {"elo": 2100}}
        resolved = resolve_team_names(parsed, teams)
        assert "United States" in resolved
        # "XX" should not resolve (no entry in code map)
        # We can't easily assert on logger.warning, but the key should be absent
        assert len(resolved) == 1

    def test_team_not_in_teams_dict(self):
        """Code mapping to a team name that's missing from teams dict should not appear."""
        parsed = [("US", 2100.0), ("ES", 2157.0)]
        teams = {"United States": {"elo": 2100}}  # Spain missing
        resolved = resolve_team_names(parsed, teams)
        assert "United States" in resolved
        assert "Spain" not in resolved
        assert len(resolved) == 1

    def test_turkiye_mapping(self):
        """TR code maps to Türkiye (our canonical name, not 'Turkey')."""
        parsed = [("TR", 1849.0)]
        teams = {"Türkiye": {"elo": 1540}}
        resolved = resolve_team_names(parsed, teams)
        assert "Türkiye" in resolved
        assert resolved["Türkiye"] == 1849.0

    def test_czech_republic_mapping(self):
        """CZ code maps to Czech Republic."""
        parsed = [("CZ", 1468.0)]
        teams = {"Czech Republic": {"elo": 1468}}
        resolved = resolve_team_names(parsed, teams)
        assert "Czech Republic" in resolved


# ─── TestCorrection ──────────────────────────────────────────────────────


class TestCorrection:
    """Tests for apply_graduated_correction.

    Thresholds per D-11:
    - |drift| < 10: ignore
    - 10 <= |drift| <= 30: blend 50%
    - |drift| > 30: overwrite + flag
    """

    def test_ignore_small_drift(self):
        """Drift < 10 → no correction entry, team unchanged."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1805.0})
        assert len(corrections) == 0
        assert teams["TestTeam"]["elo"] == 1800.0

    def test_blend_medium_drift(self):
        """Drift 20 (between 10 and 30) → new_elo = old + 20*0.5 = 1810, reason=blended_50pct."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1820.0})
        assert len(corrections) == 1
        assert teams["TestTeam"]["elo"] == 1810.0
        assert corrections[0]["reason"] == "blended_50pct"
        assert corrections[0]["drift_magnitude"] == 20.0

    def test_overwrite_large_drift(self):
        """Drift 50 (> 30) → new_elo = eloratings_value exactly, reason=overwrite_drift_gt_30."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1850.0})
        assert len(corrections) == 1
        assert teams["TestTeam"]["elo"] == 1850.0
        assert corrections[0]["reason"] == "overwrite_drift_gt_30"
        assert corrections[0]["drift_magnitude"] == 50.0

    def test_negative_drift_ignore(self):
        """Negative drift -8 (abs < 10) → ignored."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1792.0})
        assert len(corrections) == 0
        assert teams["TestTeam"]["elo"] == 1800.0

    def test_negative_drift_blend(self):
        """Negative drift -25 (abs 25, between 10 and 30) → blended."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1775.0})
        assert len(corrections) == 1
        # drift = 1775 - 1800 = -25. new_elo = 1800 + (-25)*0.5 = 1800 - 12.5 = 1787.5
        assert teams["TestTeam"]["elo"] == 1787.5
        assert corrections[0]["reason"] == "blended_50pct"
        assert corrections[0]["drift_magnitude"] == -25.0

    def test_negative_drift_overwrite(self):
        """Negative drift -100 (abs 100 > 30) → overwrite."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1700.0})
        assert len(corrections) == 1
        assert teams["TestTeam"]["elo"] == 1700.0
        assert corrections[0]["reason"] == "overwrite_drift_gt_30"
        assert corrections[0]["drift_magnitude"] == -100.0

    def test_edge_tolerance_boundary(self):
        """Drift exactly 10 → NOT ignored (tolerance is <10, so ==10 triggers blend)."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1810.0})
        assert len(corrections) == 1, f"Expected 1 correction, got {len(corrections)}"
        assert corrections[0]["reason"] == "blended_50pct"

    def test_edge_blend_boundary_low(self):
        """Drift exactly 10.1 → blended (just above tolerance)."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1810.1})
        assert len(corrections) == 1
        assert corrections[0]["reason"] == "blended_50pct"

    def test_edge_blend_boundary_high(self):
        """Drift exactly 30 → blended (implementation uses <= 30 for blend)."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1830.0})
        assert len(corrections) == 1
        assert corrections[0]["reason"] == "blended_50pct"
        # 30 * 0.5 = 15 → 1800 + 15 = 1815
        assert teams["TestTeam"]["elo"] == 1815.0

    def test_mutates_teams_dict(self):
        """Correction mutates the teams dict in-place."""
        teams = {"TeamA": {"elo": 2000.0}, "TeamB": {"elo": 2000.0}}
        corrections = apply_graduated_correction(teams, {"TeamA": 2050.0})
        assert teams["TeamA"]["elo"] == 2050.0  # mutated
        assert teams["TeamB"]["elo"] == 2000.0  # unchanged
        assert len(corrections) == 1

    def test_log_entry_structure(self):
        """Correction log entries have all required keys."""
        teams = {"TestTeam": {"elo": 1800.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 1900.0})
        entry = corrections[0]
        assert "timestamp" in entry
        assert entry["team"] == "TestTeam"
        assert entry["old_value"] == 1800.0
        assert entry["new_value"] == 1900.0
        assert entry["source"] == "eloratings.net"
        assert "drift_magnitude" in entry

    def test_very_large_drift(self):
        """Very large drift (>500) handled without overflow."""
        teams = {"TestTeam": {"elo": 1500.0}}
        corrections = apply_graduated_correction(teams, {"TestTeam": 2100.0})
        assert len(corrections) == 1
        assert teams["TestTeam"]["elo"] == 2100.0
        assert corrections[0]["reason"] == "overwrite_drift_gt_30"
        assert corrections[0]["drift_magnitude"] == 600.0


# ─── TestValidation ──────────────────────────────────────────────────────


class TestValidation:
    """Tests for validate_eloratings_data."""

    def test_valid_data(self):
        """48+ entries all in [1000, 2500] → (True, [])."""
        parsed = [(f"T{i:02d}", 1500.0) for i in range(48)]
        valid, messages = validate_eloratings_data(parsed)
        assert valid is True
        assert messages == []

    def test_too_few_teams(self):
        """< 48 entries → (False, [...])."""
        parsed = [(f"T{i:02d}", 1500.0) for i in range(47)]
        valid, messages = validate_eloratings_data(parsed)
        assert valid is False
        assert any("Expected >= 48 teams" in msg for msg in messages)

    def test_rating_out_of_range_low(self):
        """Rating 900 → (False, [...])."""
        parsed = [(f"T{i:02d}", 1500.0) for i in range(48)]
        parsed[0] = ("XX", 900.0)
        valid, messages = validate_eloratings_data(parsed)
        assert valid is False
        assert any("900" in msg for msg in messages)

    def test_rating_out_of_range_high(self):
        """Rating 3000 → (False, [...])."""
        parsed = [(f"T{i:02d}", 1500.0) for i in range(48)]
        parsed[0] = ("XX", 3000.0)
        valid, messages = validate_eloratings_data(parsed)
        assert valid is False
        assert any("3000" in msg for msg in messages)

    def test_multiple_validation_errors(self):
        """Both too few teams AND out-of-range → multiple messages.

        46 entries (below 48 threshold) with the last being out-of-range
        should produce at least 2 messages.
        """
        parsed = [(f"T{i:02d}", 1500.0) for i in range(46)]
        parsed.append(("XX", 3000.0))
        valid, messages = validate_eloratings_data(parsed)
        assert valid is False
        assert len(messages) >= 2, f"Expected >= 2 messages, got {len(messages)}: {messages}"

    def test_nan_rating_detected(self):
        """NaN rating → (False, [...])."""
        parsed = [(f"T{i:02d}", 1500.0) for i in range(48)]
        parsed[0] = ("XX", float("nan"))
        valid, messages = validate_eloratings_data(parsed)
        assert valid is False
        assert any("Invalid rating" in msg for msg in messages)


# ─── TestStaleness ───────────────────────────────────────────────────────


class TestStaleness:
    """Tests for get_staleness_level."""

    def test_green_below_24h(self):
        """10 hours → (0, 'green')."""
        assert get_staleness_level(10) == (0, "green")

    def test_info_24_to_48h(self):
        """30 hours → (1, 'info')."""
        assert get_staleness_level(30) == (1, "info")

    def test_yellow_48_to_72h(self):
        """72 hours → (2, 'yellow')."""
        assert get_staleness_level(72) == (2, "yellow")

    def test_red_72_to_168h(self):
        """100 hours → (3, 'red')."""
        assert get_staleness_level(100) == (3, "red")

    def test_critical_above_168h(self):
        """200 hours → (4, 'critical')."""
        assert get_staleness_level(200) == (4, "critical")

    def test_exact_boundaries(self):
        """Exactly at threshold values — <= comparison keeps 24h at level 0.

        With thresholds = (24, 48, 72, 168) and <= comparison:
        - 24.0  <= 24   → level 0 (green)
        - 48.0  <= 48   → level 1 (info)
        - 72.0  <= 72   → level 2 (yellow)
        - 168.0 <= 168  → level 3 (red)
        """
        assert get_staleness_level(24.0) == (0, "green"), f"24h should be level 0, got {get_staleness_level(24.0)}"
        assert get_staleness_level(48.0) == (1, "info"), f"48h should be level 1, got {get_staleness_level(48.0)}"
        assert get_staleness_level(72.0) == (2, "yellow"), f"72h should be level 2, got {get_staleness_level(72.0)}"
        assert get_staleness_level(168.0) == (3, "red"), f"168h should be level 3, got {get_staleness_level(168.0)}"

    def test_zero_hours(self):
        """0 hours → (0, 'green')."""
        assert get_staleness_level(0) == (0, "green")


# ─── TestCache ───────────────────────────────────────────────────────────


class TestCache:
    """Tests for state.py persistence of eloratings_cache and elo_update_log."""

    def test_cache_roundtrip(self, tmp_path):
        """save_eloratings_cache → load_eloratings_cache returns same data."""
        from src.state import load_eloratings_cache, save_eloratings_cache

        test_cache = {
            "fetched_at": "2026-06-15T12:00:00",
            "values": {"Argentina": 2115.0, "France": 2063.0},
        }
        save_eloratings_cache(test_cache, tmp_path)
        loaded = load_eloratings_cache(tmp_path)
        assert loaded == test_cache

    def test_cache_nonexistent_returns_empty(self, tmp_path):
        """load_eloratings_cache on empty path returns empty dict."""
        from src.state import load_eloratings_cache

        assert load_eloratings_cache(tmp_path) == {}

    def test_log_roundtrip(self, tmp_path):
        """save_elo_update_log → load_elo_update_log returns same data."""
        from src.state import load_elo_update_log, save_elo_update_log

        test_log = [
            {
                "timestamp": "2026-06-15T12:00:00",
                "team": "Norway",
                "old_value": 1504.0,
                "new_value": 1914.0,
                "source": "eloratings.net",
                "reason": "overwrite_drift_gt_30",
                "drift_magnitude": 410.0,
            }
        ]
        save_elo_update_log(test_log, tmp_path)
        loaded = load_elo_update_log(tmp_path)
        assert loaded == test_log

    def test_log_nonexistent_returns_empty(self, tmp_path):
        """load_elo_update_log on empty path returns empty list."""
        from src.state import load_elo_update_log

        assert load_elo_update_log(tmp_path) == []


# ─── TestSyncPipeline ────────────────────────────────────────────────────


class TestSyncPipeline:
    """Tests for sync_elo_from_eloratings (requires mocking fetch).

    State persistence functions are also mocked to prevent writing to real data
    files (teams.json, eloratings_cache.json, elo_update_log.json).
    """

    @patch("src.elo_sync.state.save_teams")
    @patch("src.elo_sync.state.save_eloratings_cache")
    @patch("src.elo_sync.state.save_elo_update_log")
    @patch("src.elo_sync.state.load_elo_update_log")
    @patch("src.elo_sync.fetch_eloratings_tsv")
    def test_sync_with_mocked_fetch(
        self, mock_fetch, mock_load_log, mock_save_log,
        mock_save_cache, mock_save_teams,
    ):
        """Mocked fetch returns TSV with 3 teams having known drift."""
        mock_load_log.return_value = []
        tsv_data = _make_tsv([
            ("US", 2100.0),   # drift 600 (>30) → overwrite
            ("ES", 2157.0),   # drift 0 (<10) → skip
            ("NO", 1914.0),   # drift 410 (>30) → overwrite
        ])
        mock_fetch.return_value = tsv_data
        teams = {
            "United States": {"elo": 1500.0},
            "Spain": {"elo": 2157.0},
            "Norway": {"elo": 1504.0},
        }
        corrections = sync_elo_from_eloratings(teams)
        # US drift=600 (overwrite), Norway drift=410 (overwrite), Spain drift=0 (skip)
        assert len(corrections) == 2, f"Expected 2 corrections, got {len(corrections)}"
        # Verify teams dict was mutated
        assert teams["United States"]["elo"] == 2100.0
        assert teams["Norway"]["elo"] == 1914.0
        # Spain unchanged
        assert teams["Spain"]["elo"] == 2157.0
        # State was persisted
        mock_save_cache.assert_called_once()
        mock_save_teams.assert_called_once()

    @patch("src.elo_sync.state.save_teams")
    @patch("src.elo_sync.state.save_eloratings_cache")
    @patch("src.elo_sync.state.save_elo_update_log")
    @patch("src.elo_sync.state.load_elo_update_log")
    @patch("src.elo_sync.fetch_eloratings_tsv")
    def test_sync_fetch_failure(
        self, mock_fetch, mock_load_log, mock_save_log,
        mock_save_cache, mock_save_teams,
    ):
        """When fetch returns None, sync returns None and no state is saved."""
        mock_fetch.return_value = None
        teams = {"United States": {"elo": 1500.0}}
        result = sync_elo_from_eloratings(teams)
        assert result is None
        mock_save_cache.assert_not_called()
        mock_save_teams.assert_not_called()

    @patch("src.elo_sync.state.save_teams")
    @patch("src.elo_sync.state.save_eloratings_cache")
    @patch("src.elo_sync.state.save_elo_update_log")
    @patch("src.elo_sync.state.load_elo_update_log")
    @patch("src.elo_sync.fetch_eloratings_tsv")
    def test_sync_blend_detected(
        self, mock_fetch, mock_load_log, mock_save_log,
        mock_save_cache, mock_save_teams,
    ):
        """Drift of 20 → blend correction applied and persisted."""
        mock_load_log.return_value = []
        tsv_data = _make_tsv([("US", 1820.0)])  # drift 20 → blend
        mock_fetch.return_value = tsv_data
        teams = {"United States": {"elo": 1800.0}}
        corrections = sync_elo_from_eloratings(teams)
        assert len(corrections) == 1
        assert corrections[0]["reason"] == "blended_50pct"
        assert teams["United States"]["elo"] == 1810.0
        mock_save_cache.assert_called_once()

    @patch("src.elo_sync.state.save_teams")
    @patch("src.elo_sync.state.save_eloratings_cache")
    @patch("src.elo_sync.state.save_elo_update_log")
    @patch("src.elo_sync.state.load_elo_update_log")
    @patch("src.elo_sync.fetch_eloratings_tsv")
    def test_sync_no_drift(
        self, mock_fetch, mock_load_log, mock_save_log,
        mock_save_cache, mock_save_teams,
    ):
        """No drift → empty list returned, teams not saved (no corrections)."""
        mock_load_log.return_value = []
        tsv_data = _make_tsv([("US", 1500.0)])
        mock_fetch.return_value = tsv_data
        teams = {"United States": {"elo": 1500.0}}
        corrections = sync_elo_from_eloratings(teams)
        assert corrections == []
        mock_save_cache.assert_called_once()
        mock_save_teams.assert_not_called()  # No corrections → no teams save
